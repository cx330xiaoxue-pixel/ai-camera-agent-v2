"""Agent 1 offline fixtures. They test contracts, not creative model intelligence."""

from copy import deepcopy

import pytest

from agent_system.errors import AgentError
from agent_system.models import UserRequest
from agent_system.registry import ActionRegistry, load_mock_registry


def script_data(*, motion="forward-like", count=2, goal="换装视频", revision="mock-v0"):
    return {
        "schema_version": "0.1", "registry_revision": revision, "overall_goal": goal,
        "shots": [{
            "shot_id": f"s{index + 1}", "shot_goal": "展示换装前状态" if index == 0 else "展示换装后状态",
            "subject_action": "面向镜头摆姿势", "composition_target": {
                "target_center_x": 0.5, "target_center_y": 0.5, "tolerance_x": 0.1, "tolerance_y": 0.1},
            "camera_motions": [{"motion": motion, "tempo": "slow"}],
            "execution_relation": "SEQUENTIAL", "expected_duration": 3.0, "transition": "cut",
        } for index in range(count)],
    }


def director(load_module, outputs):
    fake = load_module("llm").FakeDirectorLLM(outputs)
    return load_module("director").Director(fake), fake


def test_capability_projection_exposes_semantics_not_parameters(load_module):
    capability = load_module("registry").project_capability(load_mock_registry())
    assert set(capability.motions) == {"forward-like", "backward-like", "rotation", "hold"}
    assert capability.registry_revision == "mock-v0" and capability.execution_relations == ["SEQUENTIAL"]
    serialized = capability.model_dump_json()
    assert "parameter_schema" not in serialized and "speed_level" not in serialized
    for action in ("move_forward", "move_backward", "rotate"):
        assert action not in capability.motions


def test_projection_excludes_correction_only_and_undeclared_motion(load_module):
    data = load_mock_registry().model_dump()
    data["actions"]["rotate"]["allowed_usage"] = ["CORRECTION"]
    data["actions"]["hold"]["motion_semantics"] = []
    capability = load_module("registry").project_capability(ActionRegistry.model_validate(data))
    assert set(capability.motions) == {"forward-like", "backward-like"}


def test_registry_change_updates_capability_and_director_input(load_module):
    data = load_mock_registry().model_dump()
    data["revision"] = "mock-v1"
    data["actions"]["move_forward"]["motion_semantics"] = ["gentle-push"]
    output = script_data(motion="gentle-push", revision="mock-v1")
    agent, fake = director(load_module, [output])
    script = agent.plan(UserRequest(text="换装视频"), ActionRegistry.model_validate(data))
    assert script.registry_revision == "mock-v1"
    assert "gentle-push" in fake.calls[0]["capability"]["motions"]
    assert "forward-like" not in fake.calls[0]["capability"]["motions"]


@pytest.mark.parametrize("count", [1, 2])
def test_valid_director_output_preserves_order(load_module, count):
    agent, fake = director(load_module, [script_data(count=count)])
    result = agent.plan(UserRequest(text="我想拍个换装视频"), load_mock_registry())
    assert len(result.shots) == count
    assert [shot.shot_id for shot in result.shots] == [f"s{i+1}" for i in range(count)]
    assert fake.calls[0]["user_request"] == {"text": "我想拍个换装视频"}
    assert len(fake.calls) == 1


@pytest.mark.parametrize("case,code", [
    ("empty", "SCHEMA_ERROR"), ("duplicate", "INVALID_PLAN"),
    ("missing_composition", "SCHEMA_ERROR"), ("text_composition", "SCHEMA_ERROR"),
    ("coordinate", "SCHEMA_ERROR"), ("missing_motion", "SCHEMA_ERROR"),
    ("empty_motion", "SCHEMA_ERROR"), ("unsupported", "CAPABILITY_VIOLATION"),
    ("parallel", "CAPABILITY_VIOLATION"), ("revision", "REGISTRY_MISMATCH"),
    ("schema_version", "SCHEMA_ERROR"), ("too_many", "INVALID_PLAN"),
    ("duration", "INVALID_PLAN"), ("negative_duration", "SCHEMA_ERROR"),
    ("hardware", "SCHEMA_ERROR"), ("blank_subject", "INVALID_PLAN"),
])
def test_invalid_script_rejected(load_module, case, code):
    bad = script_data()
    shot = bad["shots"][0]
    if case == "empty": bad["shots"] = []
    elif case == "duplicate": bad["shots"][1]["shot_id"] = shot["shot_id"]
    elif case == "missing_composition": del shot["composition_target"]
    elif case == "text_composition": shot["composition_target"] = "电影感"
    elif case == "coordinate": shot["composition_target"]["target_center_x"] = 1.2
    elif case == "missing_motion": del shot["camera_motions"]
    elif case == "empty_motion": shot["camera_motions"] = []
    elif case == "unsupported": shot["camera_motions"][0]["motion"] = "drone orbit"
    elif case == "parallel": shot["execution_relation"] = "PARALLEL"
    elif case == "revision": bad["registry_revision"] = "invented-revision"
    elif case == "schema_version": bad["schema_version"] = "unsupported-version"
    elif case == "too_many": bad = script_data(count=5)
    elif case == "duration": shot["expected_duration"] = 11.0
    elif case == "negative_duration": shot["expected_duration"] = -1.0
    elif case == "hardware": shot["camera_motions"][0]["parameters"] = {"PWM": 200}
    elif case == "blank_subject": shot["subject_action"] = " "
    validator = load_module("validation")
    capability = load_module("registry").project_capability(load_mock_registry())
    with pytest.raises(AgentError) as caught:
        validator.validate_shot_script(bad, capability, load_module("director").DirectorConfig())
    assert caught.value.code == code


def test_two_sequential_motions_are_supported(load_module):
    output = script_data(count=1)
    output["shots"][0]["camera_motions"].append({"motion": "hold"})
    agent, _ = director(load_module, [output])
    script = agent.plan(UserRequest(text="推进后停住"), load_mock_registry())
    assert [motion.motion for motion in script.shots[0].camera_motions] == ["forward-like", "hold"]


def test_business_error_repaired_once_with_original_request_and_capability(load_module):
    bad = script_data()
    bad["shots"][1]["shot_id"] = "s1"
    agent, fake = director(load_module, [bad, script_data()])
    output = agent.plan(UserRequest(text="我想拍个换装视频"), load_mock_registry())
    assert len(output.shots) == 2 and len(fake.calls) == 2
    assert fake.calls[1]["repair_error"]["code"] == "INVALID_PLAN"
    assert fake.calls[0]["user_request"] == fake.calls[1]["user_request"]
    assert fake.calls[0]["capability"] == fake.calls[1]["capability"]


def test_second_invalid_candidate_fails_without_third_attempt(load_module):
    bad = script_data()
    bad["shots"][1]["shot_id"] = "s1"
    agent, fake = director(load_module, [bad, bad, script_data()])
    with pytest.raises(AgentError) as caught:
        agent.plan(UserRequest(text="换装视频"), load_mock_registry())
    assert caught.value.code == "INVALID_PLAN" and len(fake.calls) == 2


def test_unsupported_request_fails_explicitly_without_alternative(load_module):
    agent, fake = director(load_module, [None])
    with pytest.raises(AgentError) as caught:
        agent.plan(UserRequest(text="无人机从头顶俯冲下来环绕我"), load_mock_registry())
    assert caught.value.code == "CAPABILITY_VIOLATION" and len(fake.calls) == 1


def test_empty_capability_does_not_call_director_model(load_module):
    data = load_mock_registry().model_dump()
    for entry in data["actions"].values(): entry["motion_semantics"] = []
    agent, fake = director(load_module, [script_data()])
    with pytest.raises(AgentError) as caught:
        agent.plan(UserRequest(text="拍个视频"), ActionRegistry.model_validate(data))
    assert caught.value.code == "CAPABILITY_VIOLATION" and fake.calls == []


def test_different_request_fixtures_flow_through_same_pipeline(load_module):
    outfit = script_data(goal="换装视频")
    entrance = script_data(count=1, motion="hold", goal="人物出场")
    entrance["shots"][0]["subject_action"] = "缓慢走入画面"
    agent, fake = director(load_module, [outfit, entrance])
    first = agent.plan(UserRequest(text="我想拍个换装视频"), load_mock_registry())
    second = agent.plan(UserRequest(text="人物缓慢出场的短镜头"), load_mock_registry())
    assert first != second and len(second.shots) == 1
    assert fake.calls[0]["user_request"] != fake.calls[1]["user_request"]


def test_noncenter_composition_is_preserved(load_module):
    output = script_data(count=1)
    output["shots"][0]["composition_target"]["target_center_x"] = 0.3
    agent, _ = director(load_module, [output])
    script = agent.plan(UserRequest(text="人物放在画面左侧"), load_mock_registry())
    assert script.shots[0].composition_target.target_center_x == 0.3


def test_runtime_schema_constrains_motion_revision_count_and_duration(load_module):
    agent, fake = director(load_module, [script_data()])
    agent.plan(UserRequest(text="换装"), load_mock_registry())
    schema = fake.calls[0]["schema"]
    assert schema["properties"]["registry_revision"]["enum"] == ["mock-v0"]
    assert schema["properties"]["shots"]["maxItems"] == 4
    assert schema["$defs"]["Shot"]["properties"]["expected_duration"]["maximum"] == 10.0
    assert set(schema["$defs"]["CameraMotionIntent"]["properties"]["motion"]["enum"]) == set(fake.calls[0]["capability"]["motions"])


@pytest.mark.parametrize("field,value", [("registry_revision", "forged"), ("schema_version", "forged")])
def test_forged_context_is_not_repaired(load_module, field, value):
    bad = script_data()
    bad[field] = value
    agent, fake = director(load_module, [bad, script_data()])
    with pytest.raises(AgentError):
        agent.plan(UserRequest(text="换装"), load_mock_registry())
    assert len(fake.calls) == 1


def test_motion_capability_violation_can_repair_once(load_module):
    agent, fake = director(load_module, [script_data(motion="crane"), script_data(motion="hold")])
    result = agent.plan(UserRequest(text="展示人物，可选择支持的运镜"), load_mock_registry())
    assert result.shots[0].camera_motions[0].motion == "hold"
    assert fake.calls[1]["repair_error"]["code"] == "CAPABILITY_VIOLATION"


def test_order_is_not_sorted_by_shot_id(load_module):
    output = script_data()
    output["shots"][0]["shot_id"] = "z"
    output["shots"][1]["shot_id"] = "a"
    agent, _ = director(load_module, [output])
    assert [shot.shot_id for shot in agent.plan(UserRequest(text="换装"), load_mock_registry()).shots] == ["z", "a"]


@pytest.mark.parametrize("config", [{"min_shots": 3, "max_shots": 2}, {"max_shots": 0}, {"max_shot_duration": 0.0}])
def test_invalid_mvp_config_rejected(load_module, config):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        load_module("director").DirectorConfig(**config)


@pytest.mark.parametrize("text", ["PWM=200", "speed = 3", "duration: 5", "GPIO = 4"])
def test_motion_text_cannot_smuggle_hardware_parameter_assignment(load_module, text):
    bad = script_data()
    bad["shots"][0]["camera_motions"][0]["timing_requirement"] = text
    with pytest.raises(AgentError) as caught:
        load_module("validation").validate_shot_script(
            bad, load_module("registry").project_capability(load_mock_registry()),
            load_module("director").DirectorConfig(),
        )
    assert caught.value.code == "INVALID_PLAN"


@pytest.mark.parametrize("scenario,expected", [("NORMAL", "CONTINUE"), ("LEFT_OFFSET", "ADJUST"), ("LOST", "PAUSE")])
def test_three_agent_offline_e2e(load_module, monkeypatch, scenario, expected):
    import socket
    from agent_system.state import AgentState

    def no_network(*args, **kwargs):
        pytest.fail("Agent-only E2E must never connect to a provider or device")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    registry = load_mock_registry()
    agent, _ = director(load_module, [script_data()])
    script = agent.plan(UserRequest(text="我想拍个换装视频"), registry)
    shot = script.shots[0]
    replies = [{"tool_name": "move_forward", "arguments": {"speed_level": "slow", "duration": 1.0}},
               {"tool_name": "rotate", "arguments": {"direction": "left", "duration": 0.5}}]
    fake_tool = load_module("llm").FakeToolCallingLLM(replies)
    planner = load_module("action_planner").ActionPlanner(fake_tool)
    context = AgentState(shot_id=shot.shot_id, plan_id="e2e-p1", registry_revision=registry.revision)
    plan = planner.plan_shot(shot, context, registry)
    assert plan.actions[0].source == "INITIAL"
    assert plan.actions[0].parameters["duration"] != shot.expected_duration
    mocks = load_module("mocks")
    executor = mocks.MockExecutor(registry)
    state = context.mark_ready(plan, registry)
    state = state.on_executor_event(executor.submit_plan(plan))
    assert state.status == "READY"
    state = state.on_executor_event(executor.start(plan.plan_id))
    observation = mocks.mock_observations(shot_id=shot.shot_id)[scenario]
    feedback = load_module("feedback")
    gate, decision, state = feedback.evaluate_feedback(
        observation, shot.composition_target, state,
        feedback.FeedbackConfig(max_corrections=3, max_age_seconds=mocks.MOCK_FRESHNESS_SECONDS), now=100.0,
    )
    assert gate.accepted and decision.decision == expected
    if expected == "ADJUST":
        correction = planner.plan_correction(decision.correction_intent, state, registry)
        assert correction.source == "CORRECTION" and correction.shot_id == shot.shot_id
        assert load_module("validation").validate_action(correction, registry) == correction
        executor.submit_action(correction)  # External orchestration, never Agent 1/2 dispatch.
        assert state.correction_count == 1
    else:
        assert decision.correction_intent is None and len(fake_tool.calls) == 1
