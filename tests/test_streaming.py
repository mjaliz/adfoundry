"""Correctness tests for _ChatMessageDeltaExtractor.

The extractor must produce a stream of decoded characters whose concatenation
equals json.loads(...)["chat_message"], regardless of how the input is chunked.
"""
from __future__ import annotations

import json
import random

import pytest

from adfoundry.llm import _ChatMessageDeltaExtractor


def _extract_via_extractor(payloads: list[str]) -> str:
    """Feed a sequence of arbitrary deltas; return the concatenated chat_message text."""
    out: list[str] = []
    extractor = _ChatMessageDeltaExtractor(out.append)
    for chunk in payloads:
        extractor.feed(chunk)
    return "".join(out)


def _split_random(text: str, seed: int) -> list[str]:
    rng = random.Random(seed)
    chunks: list[str] = []
    i = 0
    while i < len(text):
        n = rng.randint(1, max(1, min(5, len(text) - i)))
        chunks.append(text[i : i + n])
        i += n
    return chunks


@pytest.mark.parametrize(
    "obj",
    [
        {"chat_message": "Hello world"},
        {"chat_message": "First", "html": "<p>x</p>"},
        {"html": "<p>x</p>", "chat_message": "Last"},
        {"a": 1, "chat_message": "between", "b": [1, 2, 3]},
        {"chat_message": "with \"quotes\" inside"},
        {"chat_message": "newlines\nand\ttabs"},
        {"chat_message": "back\\slash"},
        {"chat_message": "unicode emoji 🚀 and persian چرم"},
        {"chat_message": "control  and forward/slash"},
        {
            "chat_message": "Generator response",
            "report": {"chat_message": "should be ignored", "score": 80},
        },
        # chat_message inside another field's value should not leak through.
        {
            "html": "<p>\"chat_message\": stay out</p>",
            "chat_message": "the real one",
        },
    ],
)
def test_extractor_matches_json_loads_under_random_chunking(obj: dict) -> None:
    raw = json.dumps(obj, ensure_ascii=False)
    expected = obj["chat_message"]
    # Try several chunkings; each must produce the same extracted text.
    for seed in range(5):
        chunks = _split_random(raw, seed)
        assert _extract_via_extractor(chunks) == expected, (
            f"Failed for seed={seed} chunks={chunks!r}"
        )


def test_extractor_handles_unicode_escape_split_across_deltas() -> None:
    raw = json.dumps({"chat_message": "snowman ☃ ok"}, ensure_ascii=True)
    # raw will contain the ASCII-escape sequence; split it across many boundaries
    out: list[str] = []
    extractor = _ChatMessageDeltaExtractor(out.append)
    for ch in raw:  # one character at a time — worst case
        extractor.feed(ch)
    assert "".join(out) == "snowman ☃ ok"


def test_extractor_emits_nothing_when_chat_message_absent() -> None:
    assert _extract_via_extractor(['{"html": "<p>x</p>"}']) == ""


def test_extractor_ignores_chat_message_at_nested_depth() -> None:
    payload = '{"report": {"chat_message": "hidden"}, "html": "x"}'
    assert _extract_via_extractor([payload]) == ""


def test_extractor_returns_partial_text_when_stream_incomplete() -> None:
    # Truncated mid-value
    out: list[str] = []
    extractor = _ChatMessageDeltaExtractor(out.append)
    extractor.feed('{"chat_message": "Hello, wor')
    assert "".join(out) == "Hello, wor"


def test_extractor_does_not_emit_inside_other_string_with_chat_message_substring() -> None:
    payload = '{"html": "<a class=\\"chat_message\\">x</a>", "chat_message": "real"}'
    assert _extract_via_extractor([payload]) == "real"
