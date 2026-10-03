"""OpenAI adapter contract tests use a local SDK-shaped stub, never a real model."""

from types import SimpleNamespace
import json

import pytest

from agent_system.errors import AgentError
from agent_system.registry import load_mock_registry


class ResponsesStub:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def call(name="hold", arguments='{"duration": 1.0}'):
    return SimpleNamespace(type="function_call", name=name, arguments=arguments)


def adapter(load_module, *, output=None, status="completed", error=None):
    stub = ResponsesStub(SimpleNamespace(status=status, output=output or []), error)
    client = SimpleNamespace(responses=stub)
    real = load_module("llm").OpenAIToolCallingLLM(client, model="explicit-test-model")
    return real, stub


def test_responses_adapter_uses_exact_dynamic_tools_and_no_dispatch(load_module):
    real, stub = adapter(load_module, output=[SimpleNamespace(type="reasoning"), call()])
    tools = load_module("action_planner").build_tool_definitions(load_mock_registry(), "INITIAL")
    selected = real.select_tool({"source": "INITIAL", "intent": {"motion": "remain still"}}, tools)
    assert selected.tool_name == "hold" and selected.arguments == {"duration": 1.0}
    request = stub.calls[0]
    assert request["tools"] == tools and request["tool_choice"] == "auto"
    assert request["parallel_tool_calls"] is False and request["store"] is False
    assert request["model"] == "explicit-test-model" and len(stub.calls) == 1
    assert json.loads(request["input"][0]["content"])["intent"]["motion"] == "remain still"


def test_prompt_has_no_hardcoded_mock_action_names(load_module):
    real, stub = adapter(load_module)
    real.select_tool({"intent": {"motion": "orbit"}}, [])
    prompt = stub.calls[0]["instructions"]
    for name in load_mock_registry().actions:
        assert name not in prompt


def test_no_tool_call_represents_unsupported_intent(load_module):
    real, _ = adapter(load_module, output=[SimpleNamespace(type="message")])
    assert real.select_tool({"intent": {"motion": "orbit"}}, []) is None


@pytest.mark.parametrize("output", [[call(), call()], [call(arguments="not-json")], [call(arguments="[]")], [call(arguments='{"duration": NaN}')], [call(arguments='{"duration": 1, "duration": 2}')]])
def test_invalid_provider_call_shape_rejected(load_module, output):
    real, _ = adapter(load_module, output=output)
    with pytest.raises(AgentError) as caught:
        real.select_tool({}, [])
    assert caught.value.code == "SCHEMA_ERROR"


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_incomplete_provider_response_is_not_a_candidate(load_module, status):
    real, _ = adapter(load_module, output=[call()], status=status)
    with pytest.raises(AgentError) as caught:
        real.select_tool({}, [])
    assert caught.value.code == "LLM_ERROR"


def test_provider_error_does_not_expose_exception_secrets_or_retry(load_module):
    real, stub = adapter(load_module, error=RuntimeError("secret credential value"))
    with pytest.raises(AgentError) as caught:
        real.select_tool({}, [])
    assert caught.value.code == "LLM_ERROR" and "secret credential value" not in caught.value.reason
    assert len(stub.calls) == 1


def test_repair_context_is_sent_without_rewriting_tools(load_module):
    real, stub = adapter(load_module, output=[call()])
    tools = load_module("action_planner").build_tool_definitions(load_mock_registry(), "INITIAL")[-1:]
    repair = {"code": "INVALID_PARAMETERS", "reason": "duration must be number"}
    real.select_tool({"intent": {"motion": "remain still"}}, tools, repair_error=repair)
    payload = json.loads(stub.calls[0]["input"][0]["content"])
    assert payload["repair_error"] == repair and stub.calls[0]["tools"] == tools


def test_tool_prompt_distinguishes_declared_mock_correction_from_calibration(load_module):
    real, stub = adapter(load_module)
    real.select_tool({"source": "CORRECTION", "intent": {"correction_dimension": "horizontal"}}, [])
    prompt = stub.calls[0]["instructions"]
    assert "permission- and dimension-filtered" in prompt
    assert "illustrative parameters" in prompt
    assert "not physical calibration" in prompt
