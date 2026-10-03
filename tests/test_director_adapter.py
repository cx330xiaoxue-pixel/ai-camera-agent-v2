"""Provider wire tests use SDK-shaped local stubs, not a real LLM."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from agent_system.errors import AgentError
from agent_system.models import ShotScript
from agent_system.registry import load_mock_registry, project_capability
from test_director import script_data
from test_llm_adapter import ResponsesStub


def adapter(load_module, text, *, status="completed", error=None):
    stub = ResponsesStub(SimpleNamespace(status=status, output_text=text), error)
    real = load_module("llm").OpenAIDirectorLLM(SimpleNamespace(responses=stub), model="explicit-test-model")
    return real, stub


def generate(load_module, real, *, repair_error=None):
    module = load_module("director")
    capability = project_capability(load_mock_registry())
    schema = module.director_schema(capability, module.DirectorConfig())
    return real.generate_script({"text": "我想拍个换装视频"}, capability.model_dump(), schema,
                                planning_config=module.DirectorConfig().model_dump(), repair_error=repair_error)


def strict_script():
    output = script_data()
    for shot in output["shots"]:
        for motion in shot["camera_motions"]:
            motion["timing_requirement"] = None
    return output


def test_director_uses_structured_output_and_runtime_input(load_module):
    output = strict_script()
    real, stub = adapter(load_module, json.dumps({"shot_script": output}))
    assert generate(load_module, real) == output
    request = stub.calls[0]
    assert request["store"] is False and request["model"] == "explicit-test-model"
    assert "tools" not in request
    fmt = request["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    Draft202012Validator.check_schema(fmt["schema"])
    Draft202012Validator(fmt["schema"]).validate({"shot_script": output})
    payload = json.loads(request["input"][0]["content"])
    assert payload["user_request"]["text"] == "我想拍个换装视频"
    assert payload["capability"]["registry_revision"] == "mock-v0"


def test_provider_schema_is_strict_without_modifying_contract(load_module):
    original = deepcopy(ShotScript.model_json_schema())
    real, stub = adapter(load_module, '{"shot_script": null}')
    assert generate(load_module, real) is None
    schema = stub.calls[0]["text"]["format"]["schema"]
    assert schema["type"] == "object" and "anyOf" not in schema
    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            assert "default" not in node
            for child in node.values(): inspect(child)
        elif isinstance(node, list):
            for child in node: inspect(child)
    inspect(schema)
    assert ShotScript.model_json_schema() == original


def test_director_prompt_has_no_static_mock_action_or_motion_table(load_module):
    real, stub = adapter(load_module, '{"shot_script": null}')
    generate(load_module, real)
    prompt = stub.calls[0]["instructions"]
    for value in list(load_mock_registry().actions) + list(project_capability(load_mock_registry()).motions):
        assert value not in prompt


@pytest.mark.parametrize("text", ["not-json", "[]", "{}", '{"shot_script": null, "parameters": {}}',
                                   '{"shot_script": null, "shot_script": null}', '{"shot_script": NaN}',
                                   '{"shot_script": {"shots": []}}'])
def test_malformed_provider_script_rejected(load_module, text):
    real, _ = adapter(load_module, text)
    with pytest.raises(AgentError) as caught:
        generate(load_module, real)
    assert caught.value.code == "SCHEMA_ERROR"


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_incomplete_response_is_not_a_plan(load_module, status):
    real, _ = adapter(load_module, '{"shot_script": null}', status=status)
    with pytest.raises(AgentError) as caught:
        generate(load_module, real)
    assert caught.value.code == "LLM_ERROR"


def test_director_provider_error_has_no_secrets_or_unbounded_retry(load_module):
    real, stub = adapter(load_module, "", error=RuntimeError("secret credential"))
    with pytest.raises(AgentError) as caught:
        generate(load_module, real)
    assert caught.value.code == "LLM_ERROR" and "secret credential" not in str(caught.value)
    assert len(stub.calls) == 1


def test_repair_context_and_original_request_are_sent(load_module):
    real, stub = adapter(load_module, '{"shot_script": null}')
    error = {"code": "INVALID_PLAN", "reason": "duplicate shot_id"}
    generate(load_module, real, repair_error=error)
    payload = json.loads(stub.calls[0]["input"][0]["content"])
    assert payload["repair_error"] == error and payload["user_request"]["text"] == "我想拍个换装视频"


def test_director_requires_explicit_model(load_module):
    with pytest.raises(AgentError) as caught:
        load_module("llm").OpenAIDirectorLLM(None, model=" ")
    assert caught.value.code == "SCHEMA_ERROR"


def test_provider_refusal_is_explicit_not_unsupported_capability(load_module):
    real, stub = adapter(load_module, "")
    stub.response.output = [SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="refused")])]
    with pytest.raises(AgentError) as caught:
        generate(load_module, real)
    assert caught.value.code == "LLM_ERROR"


def test_director_prompt_prevents_feedback_incompatible_or_disguised_motions(load_module):
    real, stub = adapter(load_module, '{"shot_script": null}')
    generate(load_module, real)
    prompt = stub.calls[0]["instructions"]
    assert "one visible subject throughout every shot" in prompt
    assert "Never disguise unsupported movement" in prompt
    assert "A required unsupported operation means shot_script=null" in prompt
