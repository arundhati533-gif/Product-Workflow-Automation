import json

import anthropic
import httpx2 as httpx
import pytest

from core.llm import ClaudeLLM, LLMError, Usage, compute_cost, estimate_meeting_cost
from core.schemas import EpicsOutput

EPICS_JSON = {"epics": [{"id": None, "title": "Ingestion", "description": "d", "requirement_ids": ["REQ-1"]}]}


def make_client(captured: list, stop_reason="end_turn", status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if status != 200:
            return httpx.Response(status, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(EPICS_JSON)}],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 200,
                      "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 0},
        })
    return anthropic.Anthropic(api_key="test", max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_request_shape_and_parsed_result():
    captured = []
    llm = ClaudeLLM("claude-opus-5", client=make_client(captured))
    result = llm.generate("SYSTEM", "CONTEXT", "PROMPT", EpicsOutput)

    body = json.loads(captured[0].content)
    assert body["model"] == "claude-opus-5"
    assert body["system"][0] == {"type": "text", "text": "SYSTEM"}
    assert body["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in captured[0].headers["anthropic-beta"]

    assert isinstance(result.output, EpicsOutput)
    assert result.output.epics[0].title == "Ingestion"
    assert result.usage == Usage(100, 200, 3000, 0)
    assert result.cost_usd == compute_cost("claude-opus-5", result.usage)


def test_sonnet_does_not_send_fallbacks():
    captured = []
    ClaudeLLM("claude-sonnet-5", client=make_client(captured)).generate("S", "C", "P", EpicsOutput)
    assert "fallbacks" not in json.loads(captured[0].content)


@pytest.mark.parametrize("stop_reason, message", [("refusal", "declined"), ("max_tokens", "cut off")])
def test_bad_stop_reasons_raise(stop_reason, message):
    llm = ClaudeLLM("claude-sonnet-5", client=make_client([], stop_reason=stop_reason))
    with pytest.raises(LLMError, match=message):
        llm.generate("S", "C", "P", EpicsOutput)


@pytest.mark.parametrize("status, message", [(401, "API key"), (429, "Rate limited"), (500, "500")])
def test_api_errors_become_friendly_messages(status, message):
    llm = ClaudeLLM("claude-sonnet-5", client=make_client([], status=status))
    with pytest.raises(LLMError, match=message):
        llm.generate("S", "C", "P", EpicsOutput)


def test_unknown_model_rejected():
    with pytest.raises(ValueError):
        ClaudeLLM("gpt-4")


def test_cost_maths():
    # Opus 5: $5 in, $25 out per 1M; cache write 1.25x, read 0.1x
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000,
                  cache_write_tokens=1_000_000, cache_read_tokens=1_000_000)
    assert compute_cost("claude-opus-5", usage) == pytest.approx(5 + 25 + 6.25 + 0.5)


def test_estimate_is_cheaper_on_sonnet_and_scales_with_length():
    short, long = "word " * 1000, "word " * 10000
    assert estimate_meeting_cost("claude-sonnet-5", short) < estimate_meeting_cost("claude-opus-5", short)
    assert estimate_meeting_cost("claude-opus-5", short) < estimate_meeting_cost("claude-opus-5", long)
