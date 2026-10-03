"""Offline Agent 2 tests; every parameter is MOCK ONLY."""

from copy import deepcopy

import pytest

from agent_system.errors import AgentError
from agent_system.models import CameraMotionIntent, CorrectionIntent, Shot
from agent_system.registry import ActionRegistry, load_mock_registry
from agent_system.state import AgentState


def context():
    return AgentState(plan_id="p1", shot_id="s1", registry_revision="mock-v0")


def correction(dimension="horizontal"):
    return CorrectionIntent(shot_id="s1", plan_id="p1", correction_dimension=dimension, target=0.5, reason="subject_x_should_increase" if dimension == "horizontal" else "subject_y_should_increase")


def candidate(name="move_forward", **arguments):
    return {"tool_name": name, "arguments": arguments or {"speed_level": "slow", "duration": 1.0}}


def planner(load_module, responses):
    fake = load_module("llm").FakeToolCallingLLM(responses)
    return load_module("action_planner").ActionPlanner(fake), fake


def test_initial_tool_exposure_follows_allowed_usage(load_module):
    registry_data = load_mock_registry().model_dump()
    registry_data["actions"]["rotate"]["allowed_usage"] = ["CORRECTION"]
    tools = load_module("action_planner").build_tool_definitions(ActionRegistry.model_validate(registry_data), "INITIAL")
    assert {tool["name"] for tool in tools} == {"move_forward", "move_backward", "hold"}
    assert all(tool["type"] == "function" for tool in tools)


def test_correction_tools_require_both_permissions(load_module):
    data = load_mock_registry().model_dump()
    data["actions"]["move_forward"]["correction_allowed"] = True
    tools = load_module("action_planner").build_tool_definitions(ActionRegistry.model_validate(data), "CORRECTION")
    assert [tool["name"] for tool in tools] == ["rotate"]


def test_tool_definitions_change_with_registry_not_prompt(load_module):
    data = load_mock_registry().model_dump()
    entry = data["actions"].pop("hold")
    entry.update(action_name="wait_here", description="MOCK ONLY dynamically renamed tool")
    data["actions"]["wait_here"] = entry
    registry = ActionRegistry.model_validate(data)
    tools = load_module("action_planner").build_tool_definitions(registry, "INITIAL")
    tool = next(tool for tool in tools if tool["name"] == "wait_here")
    assert tool["parameters"] == registry.actions["wait_here"].parameter_schema
    assert tool["description"] == entry["description"]
    tool["parameters"]["properties"]["duration"]["maximum"] = 999
    assert registry.actions["wait_here"].parameter_schema["properties"]["duration"]["maximum"] == 10
    agent, fake = planner(load_module, [candidate("wait_here", duration=1.0)])
    action = agent.plan_motion(CameraMotionIntent(motion="remain still"), context(), registry)
    assert action.action_name == "wait_here"


def test_registry_can_explicitly_declare_correction_dimension():
    assert load_mock_registry().actions["rotate"].correction_dimensions == ["horizontal"]


@pytest.mark.parametrize("name,motion,args", [("move_forward", "slowly push toward subject", {"speed_level": "slow", "duration": 1.0}), ("hold", "remain still", {"duration": 1.0})])
def test_initial_motion_maps_to_validated_action(load_module, name, motion, args):
    agent, fake = planner(load_module, [candidate(name, **args)])
    action = agent.plan_motion(CameraMotionIntent(motion=motion), context(), load_mock_registry())
    assert action.source == "INITIAL" and action.action_name == name
    assert (action.shot_id, action.plan_id, action.registry_revision) == ("s1", "p1", "mock-v0")
    assert len(fake.calls) == 1


def test_unsupported_motion_returns_capability_error(load_module):
    agent, fake = planner(load_module, [None])
    with pytest.raises(AgentError) as caught:
        agent.plan_motion(CameraMotionIntent(motion="orbit around subject"), context(), load_mock_registry())
    assert caught.value.code == "CAPABILITY_VIOLATION" and len(fake.calls) == 1


@pytest.mark.parametrize("arguments", [{"speed_level": "slow", "duration": "1"}, {"speed_level": "slow", "duration": 11.0}, {"speed_level": "slow", "duration": 1.0, "PWM": 100}])
def test_illegal_parameters_fail_after_one_repair(load_module, arguments):
    bad = candidate(**arguments)
    agent, fake = planner(load_module, [bad, bad])
    with pytest.raises(AgentError) as caught:
        agent.plan_motion(CameraMotionIntent(motion="push forward"), context(), load_mock_registry())
    assert caught.value.code == "INVALID_PARAMETERS" and len(fake.calls) == 2


def test_horizontal_correction_only_sees_capable_correction_tools(load_module):
    agent, fake = planner(load_module, [candidate("rotate", direction="left", duration=0.5)])
    action = agent.plan_correction(correction(), context(), load_mock_registry())
    assert action.source == "CORRECTION" and action.action_name == "rotate"
    assert (action.shot_id, action.plan_id) == ("s1", "p1")
    assert [tool["name"] for tool in fake.calls[0]["tools"]] == ["rotate"]


def test_vertical_correction_cannot_guess_rotate(load_module):
    agent, fake = planner(load_module, [candidate("rotate", direction="left", duration=0.5)])
    with pytest.raises(AgentError) as caught:
        agent.plan_correction(correction("vertical"), context(), load_mock_registry())
    assert caught.value.code == "UNSUPPORTED_CORRECTION" and fake.calls == []


def test_initial_only_action_cannot_escape_correction_exposure(load_module):
    agent, fake = planner(load_module, [candidate()])
    with pytest.raises(AgentError) as caught:
        agent.plan_correction(correction(), context(), load_mock_registry())
    assert caught.value.code == "UNSUPPORTED_CORRECTION" and len(fake.calls) == 1


@pytest.mark.parametrize("field", ["shot_id", "plan_id", "registry_revision", "source", "action_id"])
def test_llm_cannot_override_envelope(load_module, field):
    malicious = candidate()
    malicious[field] = "forged"
    agent, fake = planner(load_module, [malicious])
    with pytest.raises(AgentError) as caught:
        agent.plan_motion(CameraMotionIntent(motion="push"), context(), load_mock_registry())
    assert caught.value.code == "SCHEMA_ERROR" and len(fake.calls) == 1


def test_action_ids_are_local_and_unique(load_module):
    agent, _ = planner(load_module, [candidate(), candidate()])
    first = agent.plan_motion(CameraMotionIntent(motion="push"), context(), load_mock_registry())
    second = agent.plan_motion(CameraMotionIntent(motion="push"), context(), load_mock_registry())
    assert first.action_id and second.action_id and first.action_id != second.action_id


def test_one_repair_gets_validator_error_and_same_schema(load_module):
    agent, fake = planner(load_module, [candidate(duration="bad", speed_level="slow"), candidate()])
    action = agent.plan_motion(CameraMotionIntent(motion="push"), context(), load_mock_registry())
    assert action.parameters["duration"] == 1.0 and len(fake.calls) == 2
    repair = fake.calls[1]["repair_error"]
    assert repair["code"] == "INVALID_PARAMETERS" and repair["reason"]
    original = next(tool for tool in fake.calls[0]["tools"] if tool["name"] == "move_forward")
    assert fake.calls[1]["tools"] == [original]


def test_unknown_action_never_retries(load_module):
    agent, fake = planner(load_module, [candidate("invented_action"), candidate()])
    with pytest.raises(AgentError) as caught:
        agent.plan_motion(CameraMotionIntent(motion="push"), context(), load_mock_registry())
    assert caught.value.code == "UNKNOWN_ACTION" and len(fake.calls) == 1


@pytest.mark.parametrize("motion_count", [1, 2])
def test_ordered_motions_assemble_atomic_plan(load_module, shot_data, motion_count):
    shot_data["camera_motions"] = [{"motion": "push"}] + ([{"motion": "remain still"}] if motion_count == 2 else [])
    agent, fake = planner(load_module, [candidate(), candidate("hold", duration=1.0)])
    plan = agent.plan_shot(Shot.model_validate(shot_data), context(), load_mock_registry())
    assert [action.action_name for action in plan.actions] == ["move_forward", "hold"][:motion_count]
    assert plan.execution_relation == "SEQUENTIAL" and len(fake.calls) == motion_count


def test_second_motion_failure_does_not_return_or_execute_prefix(load_module, shot_data, monkeypatch):
    from agent_system.mocks import MockExecutor
    def forbidden(*args, **kwargs):
        pytest.fail("Agent 2 attempted execution")
    monkeypatch.setattr(MockExecutor, "submit_plan", forbidden)
    monkeypatch.setattr(MockExecutor, "submit_action", forbidden)
    shot_data["camera_motions"] = [{"motion": "push"}, {"motion": "orbit"}]
    agent, fake = planner(load_module, [candidate(), None])
    with pytest.raises(AgentError) as caught:
        agent.plan_shot(Shot.model_validate(shot_data), context(), load_mock_registry())
    assert caught.value.code == "CAPABILITY_VIOLATION" and len(fake.calls) == 2


def test_parallel_plan_rejected_without_llm_calls(load_module, shot_data):
    shot_data["execution_relation"] = "PARALLEL"
    agent, fake = planner(load_module, [candidate()])
    with pytest.raises(AgentError) as caught:
        agent.plan_shot(Shot.model_validate(shot_data), context(), load_mock_registry())
    assert caught.value.code == "CAPABILITY_VIOLATION" and fake.calls == []


def test_parameter_repair_cannot_switch_to_another_action(load_module):
    agent, fake = planner(load_module, [candidate(speed_level="slow", duration="bad"), candidate("hold", duration=1.0)])
    with pytest.raises(AgentError) as caught:
        agent.plan_motion(CameraMotionIntent(motion="push"), context(), load_mock_registry())
    assert caught.value.code == "CAPABILITY_VIOLATION" and len(fake.calls) == 2


def test_shared_relation_validator_rejects_parallel(load_module):
    validation = load_module("validation")
    validation.validate_execution_relation("SEQUENTIAL")
    with pytest.raises(AgentError) as caught:
        validation.validate_execution_relation("PARALLEL")
    assert caught.value.code == "CAPABILITY_VIOLATION"


def test_optional_registry_parameter_is_not_made_required_for_provider(load_module):
    data = load_mock_registry().model_dump()
    data["actions"]["hold"]["parameter_schema"]["required"] = []
    tools = load_module("action_planner").build_tool_definitions(ActionRegistry.model_validate(data), "INITIAL")
    hold = next(tool for tool in tools if tool["name"] == "hold")
    assert hold["parameters"]["required"] == [] and hold["strict"] is False


def test_correction_capability_can_change_by_registry_config(load_module):
    data = load_mock_registry().model_dump()
    data["actions"]["rotate"]["correction_dimensions"] = ["vertical"]
    # MOCK ONLY capability update; does not imply real rotate can correct vertical.
    agent, fake = planner(load_module, [candidate("rotate", direction="left", duration=0.5)])
    action = agent.plan_correction(correction("vertical"), context(), ActionRegistry.model_validate(data))
    assert action.source == "CORRECTION" and len(fake.calls) == 1


@pytest.mark.parametrize("field,expected", [("registry_revision", "REGISTRY_MISMATCH"), ("shot_id", "INVALID_PLAN"), ("plan_id", "INVALID_PLAN")])
def test_wrong_correction_context_rejected_before_model(load_module, field, expected):
    wrong = context().model_copy(update={field: "other"})
    agent, fake = planner(load_module, [candidate("rotate", direction="left", duration=0.5)])
    with pytest.raises(AgentError) as caught:
        agent.plan_correction(correction(), wrong, load_mock_registry())
    assert caught.value.code == expected and fake.calls == []
