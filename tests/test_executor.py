from copy import deepcopy

import pytest


def executor(load_module):
    return load_module("mocks").MockExecutor(load_module("registry").load_mock_registry())


def test_plan_lifecycle_is_explicit(load_module, plan_data):
    mock = executor(load_module)
    event = mock.submit_plan(plan_data)
    assert event.status == "accepted"
    assert event.plan_id == "p1" and event.action_id is None
    assert [record.status for record in mock.records] == ["accepted"]
    assert mock.start("p1").status == "running"
    assert mock.complete("p1").status == "completed"
    assert [record.status for record in mock.records] == ["accepted", "running", "completed"]
    assert all(record.reason for record in mock.records)


def test_explicit_failure(load_module, plan_data):
    mock = executor(load_module)
    mock.submit_plan(plan_data)
    event = mock.fail("p1", reason="MOCK ONLY injected failure")
    assert event.status == "failed" and "injected" in event.reason


def test_invalid_plan_has_zero_side_effects(load_module, plan_data):
    mock = executor(load_module)
    bad = deepcopy(plan_data["actions"][0])
    bad.update(action_id="a2", action_name="nonexistent")
    plan_data["actions"].append(bad)
    with pytest.raises(load_module("errors").AgentError):
        mock.submit_plan(plan_data)
    assert mock.records == ()


def test_correction_envelope_lifecycle(load_module, action_data):
    mock = executor(load_module)
    action_data.update(source="CORRECTION", action_name="rotate", parameters={"direction": "left", "duration": 0.5})
    accepted = mock.submit_action(action_data)
    assert accepted.action_id == "a1"
    assert mock.start("p1", action_id="a1").status == "running"
    assert mock.complete("p1", action_id="a1").status == "completed"


@pytest.mark.parametrize("case", ["complete_before_start", "restart_terminal", "duplicate", "unknown"])
def test_illegal_executor_lifecycle(load_module, plan_data, case):
    mock = executor(load_module)
    mock.submit_plan(plan_data)
    error = load_module("errors").AgentError
    with pytest.raises(error) as caught:
        if case == "complete_before_start":
            mock.complete("p1")
        elif case == "restart_terminal":
            mock.start("p1")
            mock.complete("p1")
            mock.start("p1")
        elif case == "duplicate":
            mock.submit_plan(plan_data)
        else:
            mock.start("unknown")
    assert caught.value.code == "INVALID_STATE_TRANSITION"


def test_submission_owns_snapshot(load_module, plan_data):
    mock = executor(load_module)
    mock.submit_plan(plan_data)
    plan_data["actions"][0]["parameters"]["duration"] = -1
    assert mock.submitted[("p1", None)].actions[0].parameters["duration"] == 2.0
