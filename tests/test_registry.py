import json

import pytest


@pytest.fixture
def registry_api(load_module):
    return lambda: (load_module("registry"), load_module("validation"), load_module("errors"))


def test_mock_registry_load_and_single_action(registry_api, action_data):
    r, v, _ = registry_api()
    registry = r.load_mock_registry()
    assert registry.revision == "mock-v0"
    assert set(registry.actions) == {"move_forward", "move_backward", "rotate", "hold"}
    assert all("MOCK ONLY" in entry.description for entry in registry.actions.values())
    assert v.validate_action(action_data, registry).parameters["duration"] == 2.0


@pytest.mark.parametrize("change,code", [
    ({"action_name": "cinematic_orbit"}, "UNKNOWN_ACTION"),
    ({"registry_revision": "real-v1"}, "REGISTRY_MISMATCH"),
    ({"parameters": {"speed_level": "slow"}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": "2"}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": True}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": 0}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": 11}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "superfast", "duration": 2}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": 2, "pwm": 100}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": float("nan")}}, "INVALID_PARAMETERS"),
    ({"parameters": {"speed_level": "slow", "duration": float("inf")}}, "INVALID_PARAMETERS"),
    ({"source": "CORRECTION"}, "UNSUPPORTED_CORRECTION"),
])
def test_invalid_actions_rejected(registry_api, action_data, change, code):
    r, v, e = registry_api()
    action_data.update(change)
    with pytest.raises(e.AgentError) as caught:
        v.validate_action(action_data, r.load_mock_registry())
    assert caught.value.code == code
    assert caught.value.reason
    assert str(caught.value).startswith(code)


def test_allowed_correction_uses_same_envelope(registry_api, action_data):
    r, v, _ = registry_api()
    action_data.update(source="CORRECTION", action_name="rotate", parameters={"direction": "left", "duration": 0.5})
    result = v.validate_action(action_data, r.load_mock_registry())
    assert result.source == "CORRECTION"


def test_allowed_usage_independent_of_correction_permission(registry_api, action_data):
    r, v, e = registry_api()
    config = r.load_mock_registry().model_dump()
    config["actions"]["rotate"]["allowed_usage"] = ["CORRECTION"]
    registry = r.ActionRegistry.model_validate(config)
    action_data.update(action_name="rotate", parameters={"direction": "left", "duration": 0.5})
    with pytest.raises(e.AgentError) as caught:
        v.validate_action(action_data, registry)
    assert caught.value.code == "CAPABILITY_VIOLATION"


def test_schema_errors_wrapped_for_action_envelope(registry_api, action_data):
    r, v, e = registry_api()
    action_data["source"] = "EXECUTE_WHATEVER"
    with pytest.raises(e.AgentError) as caught:
        v.validate_action(action_data, r.load_mock_registry())
    assert caught.value.code == "SCHEMA_ERROR"


def test_registry_loaded_from_external_json_path(registry_api, tmp_path):
    r, v, _ = registry_api()
    config = r.load_mock_registry().model_dump()
    config["revision"] = "mock-v1"
    entry = config["actions"].pop("hold")
    entry["action_name"] = "wait_here"
    entry["parameter_schema"] = {
        "type": "object", "properties": {"ticks": {"type": "integer", "minimum": 1}},
        "required": ["ticks"], "additionalProperties": False,
    }
    config["actions"] = {"wait_here": entry}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    registry = r.load_registry(path)
    result = v.validate_action({
        "action_id": "a2", "shot_id": "s1", "plan_id": "p1", "source": "INITIAL",
        "action_name": "wait_here", "parameters": {"ticks": 2}, "registry_revision": "mock-v1",
    }, registry)
    assert result.action_name == "wait_here"


@pytest.mark.parametrize("invalid", ["bad_schema", "name_mismatch", "remote_reference"])
def test_malformed_registry_rejected_before_use(registry_api, tmp_path, invalid):
    r, _, e = registry_api()
    config = r.load_mock_registry().model_dump()
    if invalid == "bad_schema":
        config["actions"]["hold"]["parameter_schema"]["type"] = "not-a-json-type"
    elif invalid == "name_mismatch":
        config["actions"]["hold"]["action_name"] = "different_name"
    else:
        config["actions"]["hold"]["parameter_schema"] = {"$ref": "https://example.invalid/schema.json"}
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(e.AgentError) as caught:
        r.load_registry(path)
    assert caught.value.code == "SCHEMA_ERROR"


def test_invalid_config_json_reports_reason(registry_api, tmp_path):
    r, _, e = registry_api()
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(e.AgentError) as caught:
        r.load_registry(path)
    assert caught.value.code == "SCHEMA_ERROR"
