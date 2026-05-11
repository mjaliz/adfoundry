from __future__ import annotations
from typing import Any, Callable, TypeAlias, TypeVar

from pydantic import BaseModel

from adfoundry.models import RunMode
from adfoundry.settings import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
ResponsesContentPart: TypeAlias = dict[str, str]
ResponsesUserContent: TypeAlias = str | list[ResponsesContentPart]
ResponsesMessage: TypeAlias = dict[str, Any]


class _ChatMessageDeltaExtractor:
    """Streams the value of a top-level ``chat_message`` string field as it arrives.

    Maintains just enough JSON state to (1) track string vs structural mode,
    (2) track object depth so only top-level keys are considered, and
    (3) emit decoded characters of the chat_message value through ``on_delta``.
    Handles standard JSON escapes and ``\\uXXXX`` Unicode sequences split across
    arbitrary stream boundaries.
    """

    _ESCAPES = {
        "n": "\n", "t": "\t", "r": "\r", "b": "\b",
        "f": "\f", '"': '"', "\\": "\\", "/": "/",
    }

    def __init__(self, on_delta: Callable[[str], None]) -> None:
        self._on_delta = on_delta
        self._depth = 0
        self._in_string = False
        self._is_value_string = False
        self._is_chat_value = False
        self._current_key_chars: list[str] = []
        self._after_colon = False
        self._last_top_key: str | None = None
        self._escape = False
        self._unicode_remaining = 0
        self._unicode_buf: list[str] = []

    def feed(self, delta: str) -> None:
        for ch in delta:
            self._step(ch)

    def _emit(self, s: str) -> None:
        if self._is_chat_value and s:
            self._on_delta(s)

    def _record_key(self, s: str) -> None:
        if self._in_string and not self._is_value_string:
            self._current_key_chars.append(s)

    def _step(self, ch: str) -> None:
        if self._unicode_remaining > 0:
            self._unicode_buf.append(ch)
            self._unicode_remaining -= 1
            if self._unicode_remaining == 0:
                try:
                    actual = chr(int("".join(self._unicode_buf), 16))
                except ValueError:
                    actual = "?"
                self._unicode_buf = []
                self._emit(actual)
                self._record_key(actual)
            return

        if self._in_string:
            if self._escape:
                self._escape = False
                if ch == "u":
                    self._unicode_remaining = 4
                    self._unicode_buf = []
                    return
                actual = self._ESCAPES.get(ch, ch)
                self._emit(actual)
                self._record_key(actual)
                return
            if ch == "\\":
                self._escape = True
                return
            if ch == '"':
                # closing the current string
                if not self._is_value_string and self._depth == 1:
                    self._last_top_key = "".join(self._current_key_chars)
                self._current_key_chars = []
                self._in_string = False
                self._is_chat_value = False
                self._is_value_string = False
                return
            self._emit(ch)
            self._record_key(ch)
            return

        # Outside a string — structural / whitespace.
        if ch == '"':
            self._in_string = True
            if self._after_colon:
                self._is_value_string = True
                self._is_chat_value = (
                    self._depth == 1 and self._last_top_key == "chat_message"
                )
                self._after_colon = False
            else:
                self._is_value_string = False
                self._current_key_chars = []
            return
        if ch in "{[":
            self._depth += 1
            self._after_colon = False
            return
        if ch in "}]":
            self._depth -= 1
            self._after_colon = False
            return
        if ch == ":":
            self._after_colon = True
            return
        if ch == ",":
            self._after_colon = False
            return
        # whitespace, digits, true/false/null tokens — irrelevant for extraction.


class OpenAIModelGateway:
    """Thin OpenAI Responses API adapter with safe fixture fallback behavior."""

    def __init__(
        self,
        mode: RunMode = "hybrid",
        model: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.mode = mode
        self.settings = settings or get_settings()
        self.model = model or self.settings.openai_model
        self.last_error: str | None = None
        self.live_available = bool(self.settings.openai_api_key)

    @property
    def should_call_live(self) -> bool:
        return self.mode in {"hybrid", "live"} and self.live_available

    def parse(self, schema: type[T], system: str, user: ResponsesUserContent) -> T | None:
        return self.parse_messages(
            schema,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

    def parse_messages(
        self,
        schema: type[T],
        messages: list[ResponsesMessage],
    ) -> T | None:
        if not self.should_call_live:
            if self.mode == "live":
                self.last_error = "OPENAI_API_KEY is not set."
            return None

        try:
            client = self._client()
            response = client.responses.parse(
                model=self.model,
                input=messages,
                text_format=schema,
            )
            return response.output_parsed
        except Exception as exc:  # pragma: no cover - depends on external API state
            self.last_error = str(exc)
            if self.mode == "live":
                raise
            return None

    def stream_messages(
        self,
        schema: type[T],
        messages: list[ResponsesMessage],
        on_chat_delta: Callable[[str], None] | None = None,
    ) -> T | None:
        """Stream a structured-output response, surfacing chat_message tokens live.

        When the gateway is not live (fixture / no API key), returns None.
        Otherwise opens a streaming response and yields decoded chat_message
        characters through on_chat_delta as they arrive, then returns the final
        parsed Pydantic object. Falls through to parse_messages on any error
        when not in strict ``live`` mode.
        """
        if not self.should_call_live:
            if self.mode == "live":
                self.last_error = "OPENAI_API_KEY is not set."
            return None

        try:
            client = self._client()
            extractor = _ChatMessageDeltaExtractor(on_chat_delta) if on_chat_delta else None
            with client.responses.stream(
                model=self.model,
                input=messages,
                text_format=schema,
            ) as stream:
                for event in stream:
                    if extractor is None:
                        continue
                    delta = self._delta_from_event(event)
                    if delta:
                        extractor.feed(delta)
                final = stream.get_final_response()
            return getattr(final, "output_parsed", None)
        except Exception as exc:  # pragma: no cover - depends on external API state
            self.last_error = str(exc)
            if self.mode == "live":
                raise
            # Fall back to non-streaming attempt so the caller still gets a result.
            return self.parse_messages(schema, messages)

    @staticmethod
    def _delta_from_event(event: Any) -> str:
        """Extract a text delta from a Responses-API stream event, if present."""
        event_type = getattr(event, "type", "")
        if event_type != "response.output_text.delta":
            return ""
        delta = getattr(event, "delta", None)
        if isinstance(delta, str):
            return delta
        # Some SDK shapes nest the delta under .data.delta
        data = getattr(event, "data", None)
        if data is not None:
            nested = getattr(data, "delta", None)
            if isinstance(nested, str):
                return nested
        return ""

    def _client(self) -> Any:
        from openai import OpenAI

        client_kwargs: dict[str, Any] = {
            "api_key": self.settings.openai_api_key,
            "timeout": self.settings.openai_timeout_seconds,
        }
        if self.settings.openai_base_url:
            client_kwargs["base_url"] = self.settings.openai_base_url
        return OpenAI(**client_kwargs)


def json_prompt(name: str, context: str) -> tuple[str, str]:
    system = (
        f"You are the {name} in AdFoundry, an agentic campaign builder. "
        "Return only structured output that matches the provided schema exactly. "
        "Use only the supplied context as evidence; do not invent offers, claims, logos, endorsements, prices, or unsupported brand facts. "
        "Make specific, concise decisions in polished executive-review language, favoring brand evidence and conversion value over generic marketing ideas."
    )
    return system, context
