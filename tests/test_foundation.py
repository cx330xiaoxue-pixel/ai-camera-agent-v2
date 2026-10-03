"""Agent-only assembly checks; all plans/decisions are supplied fixtures, not agents."""

import pytest


def test_deterministic_foundation_end_to_end(load_module, plan_data):
    registry = load_module("registry").load_mock_registry()
    plan = load_module("models").ShotExecutionPlan.model_validate(plan_data)
    current = load_module("state").AgentState.from_plan(plan)
    executor = load_module("mocks").MockExecutor(registry)
    current = current.mark_ready(plan, registry)
    accepted = executor.submit_plan(plan)
    current = current.on_executor_event(accepted)
    assert current.status == "READY"
    current = current.on_executor_event(executor.start(plan.plan_id))
    observations = load_module("mocks").mock_observations(shot_id=plan.shot_id, now=100.0)
    gate = load_module("observations").gate_observation
    assert gate(observations["NORMAL"], current, now=100.0, max_age_seconds=1.0).accepted
    assert gate(observations["LOST"], current, now=100.0, max_age_seconds=1.0).accepted
    paused = current.confirm_pause()
    assert gate(observations["NORMAL"], paused, now=100.0, max_age_seconds=1.0).code == "INACTIVE_STATE"
    assert paused.status == "PAUSED"
    current = paused.confirm_resume()
    current = current.on_executor_event(executor.complete(plan.plan_id))
    assert current.status == "COMPLETED"
    assert gate(observations["NORMAL"], current, now=100.0, max_age_seconds=1.0).code == "INACTIVE_STATE"


def test_invalid_parameters_cannot_be_smuggled_after_model_creation(load_module, plan_data):
    registry = load_module("registry").load_mock_registry()
    plan = load_module("models").ShotExecutionPlan.model_validate(plan_data)
    # Pydantic frozen objects still contain mutable lists/dicts; boundaries must revalidate.
    plan.actions[0].parameters["duration"] = -1.0
    executor = load_module("mocks").MockExecutor(registry)
    with pytest.raises(load_module("errors").AgentError) as caught:
        executor.submit_plan(plan)
    assert caught.value.code == "INVALID_PARAMETERS"
    assert executor.records == ()


def test_failed_validation_can_be_recorded_without_starting_execution(load_module, plan_data):
    current = load_module("state").AgentState.from_plan(load_module("models").ShotExecutionPlan.model_validate(plan_data))
    plan_data["actions"][0]["action_name"] = "invented"
    with pytest.raises(load_module("errors").AgentError) as caught:
        current.mark_ready(plan_data, load_module("registry").load_mock_registry())
    current = current.fail(caught.value.reason)
    assert current.status == "FAILED" and current.reason
