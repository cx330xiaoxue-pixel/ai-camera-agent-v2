import pytest


def planned(load_module, plan_data):
    return load_module("state").AgentState.from_plan(load_module("models").ShotExecutionPlan.model_validate(plan_data))


def ready(load_module, plan_data):
    return planned(load_module, plan_data).mark_ready(plan_data, load_module("registry").load_mock_registry())


def event(load_module, status, plan_id="p1", action_id=None):
    return load_module("models").ExecutionEvent(plan_id=plan_id, action_id=action_id, status=status, reason="MOCK TEST CONFIG")


def test_validation_does_not_start_execution(load_module, plan_data):
    state = planned(load_module, plan_data)
    assert state.status == "PLANNED"
    state = state.mark_ready(plan_data, load_module("registry").load_mock_registry())
    assert state.status == "READY"
    assert state.on_executor_event(event(load_module, "accepted")).status == "READY"
    assert state.on_executor_event(event(load_module, "running")).status == "EXECUTING"


@pytest.mark.parametrize("path", ["completed", "failed", "pause_resume", "planned_failure", "ready_failure"])
def test_legal_state_paths(load_module, plan_data, path):
    state = planned(load_module, plan_data)
    if path == "planned_failure":
        assert state.fail("validation rejected").status == "FAILED"
        return
    state = state.mark_ready(plan_data, load_module("registry").load_mock_registry())
    if path == "ready_failure":
        assert state.fail("submission failed").status == "FAILED"
        return
    state = state.on_executor_event(event(load_module, "running"))
    if path == "pause_resume":
        state = state.confirm_pause()
        assert state.status == "PAUSED"
        assert state.confirm_resume().status == "EXECUTING"
    else:
        assert state.on_executor_event(event(load_module, path)).status == path.upper()


@pytest.mark.parametrize("case", ["planned_start", "completed_start", "failed_start", "paused_complete", "paused_running", "wrong_plan", "correction_event", "invalid_ready"])
def test_illegal_state_changes(load_module, plan_data, case):
    state = planned(load_module, plan_data)
    error = load_module("errors").AgentError
    with pytest.raises(error):
        if case == "planned_start":
            state.on_executor_event(event(load_module, "running"))
        elif case == "invalid_ready":
            plan_data["actions"][0]["action_name"] = "unknown"
            state.mark_ready(plan_data, load_module("registry").load_mock_registry())
        else:
            state = ready(load_module, plan_data)
            if case == "wrong_plan":
                state.on_executor_event(event(load_module, "running", plan_id="other"))
            elif case == "correction_event":
                state.on_executor_event(event(load_module, "completed", action_id="correction"))
            else:
                state = state.on_executor_event(event(load_module, "running"))
                if case == "failed_start":
                    state = state.fail("mock failure")
                elif case == "completed_start":
                    state = state.on_executor_event(event(load_module, "completed"))
                else:
                    state = state.confirm_pause()
                state.on_executor_event(event(load_module, "completed" if case == "paused_complete" else "running"))


def test_ready_plan_must_match_state(load_module, plan_data):
    state = planned(load_module, plan_data)
    plan_data["shot_id"] = "other"
    plan_data["actions"][0]["shot_id"] = "other"
    with pytest.raises(load_module("errors").AgentError) as caught:
        state.mark_ready(plan_data, load_module("registry").load_mock_registry())
    assert caught.value.code == "INVALID_PLAN"
