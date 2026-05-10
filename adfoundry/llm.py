from __future__ import annotations
from typing import Any, TypeAlias, TypeVar

from pydantic import BaseModel

from adfoundry.models import RunMode
from adfoundry.settings import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
ResponsesContentPart: TypeAlias = dict[str, str]
ResponsesUserContent: TypeAlias = str | list[ResponsesContentPart]
ResponsesMessage: TypeAlias = dict[str, Any]


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
            from openai import OpenAI

            client_kwargs = {
                "api_key": self.settings.openai_api_key,
                "timeout": self.settings.openai_timeout_seconds,
            }
            if self.settings.openai_base_url:
                client_kwargs["base_url"] = self.settings.openai_base_url
            client = OpenAI(**client_kwargs)
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


def json_prompt(name: str, context: str) -> tuple[str, str]:
    system = (
        f"You are the {name} in AdFoundry, an agentic campaign builder. "
        "Return only structured output that matches the provided schema exactly. "
        "Use only the supplied context as evidence; do not invent offers, claims, logos, endorsements, prices, or unsupported brand facts. "
        "Make specific, concise decisions in polished executive-review language, favoring brand evidence and conversion value over generic marketing ideas."
    )
    return system, context
