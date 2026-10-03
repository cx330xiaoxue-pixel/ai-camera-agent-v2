from copy import deepcopy

import pytest


def test_one_action_plan(load_module, plan_data):
    registry = load_module("registry").load_mock_registry()
    plan = load_module("validation").validate_plan(plan_data, registry)
    assert len(plan.actions) == 1


def test_two_sequential_actions(load_module, plan_data):
    second = deepcopy(plan_data["actions"][0])
    second["action_id"] = "a2"
    second["action_name"] = "move_backward"
    plan_data["actions"].append(second)
    plan = load_module("validation").validate_plan(plan_data, load_module("registry").load_mock_registry())
    assert [action.action_id for action in plan.actions] == ["a1", "a2"]


@pytest.mark.parametrize("case,code", [
    ("parallel", "CAPABILITY_VIOLATION"),
    ("unknown", "UNKNOWN_ACTION"),
    ("shot", "INVALID_PLAN"),
    ("plan", "INVALID_PLAN"),
    ("revision", "REGISTRY_MISMATCH"),
    ("source", "INVALID_PLAN"),
    ("duplicate", "INVALID_PLAN"),
    ("outer_revision", "REGISTRY_MISMATCH"),
    ("empty", "SCHEMA_ERROR"),
])
def test_reject_entire_plan(load_module, plan_data, case, code):
    registry = load_module("registry").load_mock_registry()
    error = load_module("errors").AgentError
    validation = load_module("validation")
    if case == "parallel":
        plan_data["execution_relation"] = "PARALLEL"
    elif case == "unknown":
        bad = deepcopy(plan_data["actions"][0])
        bad.update(action_id="bad", action_name="invented_action")
        plan_data["actions"].append(bad)
    elif case == "shot":
        plan_data["actions"][0]["shot_id"] = "other"
    elif case == "plan":
        plan_data["actions"][0]["plan_id"] = "other"
    elif case == "revision":
        plan_data["actions"][0]["registry_revision"] = "old"
    elif case == "source":
        plan_data["actions"][0]["source"] = "CORRECTION"
    elif case == "duplicate":
        plan_data["actions"].append(deepcopy(plan_data["actions"][0]))
    elif case == "outer_revision":
        plan_data["registry_revision"] = "old"
    elif case == "empty":
        plan_data["actions"] = []
    with pytest.raises(error) as caught:
        validation.validate_plan(plan_data, registry)
    assert caught.value.code == code
    assert caught.value.reason
