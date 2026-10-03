"""Phase 5B TDD: MOCK TARGET VALUES, capabilities and canonical-unit fixtures."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_system.errors import AgentError
from agent_system.models import AgentDecision, Observation, TargetTrajectory
from agent_system.state import AgentState
from test_visual_contract import captain_trajectory_data


def new_model(load_module, name):
    module = load_module("models")
    assert hasattr(module, name), f"V2 feedback contract not implemented: {name}"
    return getattr(module, name)


def component_data(dimension="CENTER_Y", target=0.6, observed=0.66):
    return {"dimension": dimension, "target_value": target, "observed_value": observed,
            "error": float(Decimal(str(observed)) - Decimal(str(target)))}


def correction_data():
    return {"shot_id": "object-shot", "plan_id": "object-plan", "trajectory_time": 2.5,
            "reason": "trajectory_offset", "components": [component_data(), component_data("SUBJECT_HEIGHT_RATIO", 0.55, 0.47)]}


def current_state(**changes):
    values = {"shot_id": "object-shot", "plan_id": "object-plan", "registry_revision": "mock-v0", "status": "EXECUTING"}
    values.update(changes)
    return AgentState(**values)


def test_v2_decision_carries_multiple_components_and_round_trips(load_module):
    cls = new_model(load_module, "TrajectoryCorrectionIntent")
    intent = cls(**correction_data())
    decision = AgentDecision(decision="ADJUST", reason="trajectory_offset", correction_intent=intent)
    restored = AgentDecision.model_validate_json(decision.model_dump_json())
    assert isinstance(restored.correction_intent, cls)
    assert len(restored.correction_intent.components) == 2


def test_state_counts_multi_dimension_request_once(load_module):
    intent = new_model(load_module, "TrajectoryCorrectionIntent")(**correction_data())
    state = current_state()
    updated = state.record_correction(AgentDecision(decision="ADJUST", reason="trajectory_offset", correction_intent=intent))
    assert updated.correction_count == 1 and state.correction_count == 0
    assert updated.status == "EXECUTING"


@pytest.mark.parametrize("dimension,target,observed", [
    ("CENTER_X", 0.5, 0.3), ("CENTER_Y", 0.6, 0.66),
    ("SUBJECT_HEIGHT_RATIO", 0.55, 0.47), ("DISTANCE", 2.0, 2.5),
])
def test_component_uses_dimension_correct_values_and_signed_error(load_module, dimension, target, observed):
    component = new_model(load_module, "CorrectionComponent")(**component_data(dimension, target, observed))
    assert component.error == float(Decimal(str(observed)) - Decimal(str(target)))


@pytest.mark.parametrize("dimension,target,observed", [
    ("CENTER_X", -0.1, 0.5), ("CENTER_Y", 0.5, 1.1),
    ("SUBJECT_HEIGHT_RATIO", 0.0, 0.4), ("SUBJECT_HEIGHT_RATIO", 0.4, 1.1),
    ("DISTANCE", 0.0, 1.0), ("DISTANCE", 1.0, -1.0),
])
def test_component_rejects_invalid_dimension_values(load_module, dimension, target, observed):
    cls = new_model(load_module, "CorrectionComponent")
    with pytest.raises(ValidationError):
        cls(**component_data(dimension, target, observed))


@pytest.mark.parametrize("change", [{"dimension": "ROTATE"}, {"error": float("nan")}, {"error": 0.9}, {"pwm": 200}])
def test_component_rejects_hardware_or_inconsistent_error(load_module, change):
    cls = new_model(load_module, "CorrectionComponent")
    values = component_data()
    values.update(change)
    with pytest.raises(ValidationError):
        cls(**values)


@pytest.mark.parametrize("components", [[], [component_data(), component_data()]])
def test_intent_requires_nonempty_unique_dimensions(load_module, components):
    cls = new_model(load_module, "TrajectoryCorrectionIntent")
    values = correction_data()
    values["components"] = components
    with pytest.raises(ValidationError):
        cls(**values)


@pytest.mark.parametrize("time", [-0.1, float("nan"), float("inf")])
def test_intent_rejects_invalid_relative_time(load_module, time):
    cls = new_model(load_module, "TrajectoryCorrectionIntent")
    values = correction_data()
    values["trajectory_time"] = time
    with pytest.raises(ValidationError):
        cls(**values)


def test_correction_capability_is_explicit_finite_dimension_set(load_module):
    cls = new_model(load_module, "CorrectionCapability")
    assert cls(allowed_dimensions=[]).allowed_dimensions == []
    assert cls(allowed_dimensions=["CENTER_X"]).allowed_dimensions == ["CENTER_X"]
    with pytest.raises(ValidationError):
        cls(allowed_dimensions=["ROTATE"])
    with pytest.raises(ValidationError):
        cls(allowed_dimensions=["CENTER_X", "CENTER_X"])


@pytest.mark.parametrize("decision", ["CONTINUE", "PAUSE"])
def test_non_adjust_cannot_carry_v2_intent(load_module, decision):
    intent = new_model(load_module, "TrajectoryCorrectionIntent")(**correction_data())
    with pytest.raises(ValidationError):
        AgentDecision(decision=decision, reason="not_adjusting", correction_intent=intent)


def observation_data(**changes):
    values = {"shot_id": "object-shot", "plan_id": "object-plan", "timestamp": 100.0,
              "bbox": {"x1": 0.4, "y1": 0.325, "x2": 0.6, "y2": 0.875}}
    values.update(changes)
    return values


def test_gate_accepts_matching_plan_in_required_mode(load_module):
    assert "plan_id" in Observation.model_fields, "Observation plan association not implemented"
    gate = load_module("observations").gate_observation(observation_data(), current_state(), now=100.0, max_age_seconds=1.0, require_plan_id=True)
    assert gate.accepted and gate.observation.plan_id == "object-plan"


@pytest.mark.parametrize("required", [False, True])
def test_gate_rejects_old_plan_even_for_same_shot(load_module, required):
    assert "plan_id" in Observation.model_fields, "Observation plan association not implemented"
    gate = load_module("observations").gate_observation(observation_data(plan_id="old-plan"), current_state(), now=100.0, max_age_seconds=1.0, require_plan_id=required)
    assert not gate.accepted and gate.code == "WRONG_PLAN"


def test_required_plan_association_cannot_be_missing(load_module):
    assert "plan_id" in Observation.model_fields, "Observation plan association not implemented"
    payload = observation_data()
    del payload["plan_id"]
    gate = load_module("observations").gate_observation(payload, current_state(), now=100.0, max_age_seconds=1.0, require_plan_id=True)
    assert not gate.accepted and gate.code == "MISSING_PLAN"


def test_v0_gate_still_accepts_observation_without_plan_id(load_module):
    assert "plan_id" in Observation.model_fields, "Observation plan association not implemented"
    payload = observation_data()
    del payload["plan_id"]
    gate = load_module("observations").gate_observation(payload, current_state(), now=100.0, max_age_seconds=1.0)
    assert gate.accepted


def test_gate_rejects_invalid_plan_identifier(load_module):
    assert "plan_id" in Observation.model_fields, "Observation plan association not implemented"
    gate = load_module("observations").gate_observation(observation_data(plan_id=""), current_state(), now=100.0, max_age_seconds=1.0, require_plan_id=True)
    assert not gate.accepted and gate.code == "INVALID_OBSERVATION"


ALL_DIMENSIONS = ["CENTER_X", "CENTER_Y", "SUBJECT_HEIGHT_RATIO", "DISTANCE"]  # MOCK ONLY


def measured_observation(*, center_x=0.5, center_y=0.6, height=0.55, distance=None, **changes):
    x, y, half_height = Decimal(str(center_x)), Decimal(str(center_y)), Decimal(str(height)) / 2
    box = {"x1": float(x - Decimal("0.1")), "x2": float(x + Decimal("0.1")),
           "y1": float(y - half_height), "y2": float(y + half_height)}
    return Observation(**observation_data(bbox=box, distance=distance, **changes))


def trajectory_with_distance(distance=None, tolerance=None):
    payload = captain_trajectory_data()
    for keyframe in payload["keyframes"]:
        keyframe["frame_state"]["distance"] = distance
    if tolerance is not None:
        payload["tolerance"]["distance_tolerance"] = tolerance
    return TargetTrajectory(**payload)


def run_feedback(load_module, *, observation=None, trajectory=None, trajectory_time=2.5,
                 state=None, dimensions=None, max_corrections=3, now=100.0, trajectory_plan_id="object-plan"):
    feedback = load_module("feedback")
    assert hasattr(feedback, "evaluate_feedback_v2"), "Trajectory Feedback V2 not implemented"
    capability = new_model(load_module, "CorrectionCapability")(allowed_dimensions=ALL_DIMENSIONS if dimensions is None else dimensions)
    return feedback.evaluate_feedback_v2(
        trajectory=trajectory_with_distance() if trajectory is None else trajectory,
        trajectory_time=trajectory_time,
        observation=measured_observation() if observation is None else observation,
        state=current_state() if state is None else state,
        config=feedback.FeedbackConfig(max_corrections=max_corrections, max_age_seconds=1.0),  # MOCK TEST CONFIG
        correction_capability=capability, trajectory_plan_id=trajectory_plan_id, now=now,
    )


@pytest.mark.parametrize("t,y,height", [(0.0, 0.7, 0.4), (2.5, 0.6, 0.55), (5.0, 0.5, 0.7)])
def test_feedback_samples_explicit_captain_keyframe_time(load_module, t, y, height):
    state = current_state()
    gate, decision, updated = run_feedback(load_module, trajectory_time=t, observation=measured_observation(center_y=y, height=height), state=state)
    assert gate.accepted and decision.decision == "CONTINUE"
    assert decision.reason == "within_trajectory_tolerance"
    assert decision.correction_intent is None and updated == state


@pytest.mark.parametrize("t", [-0.1, 5.01, float("nan"), float("inf"), True])
def test_feedback_rejects_invalid_time_without_hold_or_extrapolation(load_module, t):
    with pytest.raises(AgentError) as error:
        run_feedback(load_module, trajectory_time=t)
    assert error.value.code == "INVALID_TRAJECTORY_TIME"


@pytest.mark.parametrize("changes,dimension,target", [
    ({"center_x": 0.6}, "CENTER_X", 0.5), ({"center_y": 0.66}, "CENTER_Y", 0.6),
    ({"height": 0.3}, "SUBJECT_HEIGHT_RATIO", 0.55), ({"height": 0.75}, "SUBJECT_HEIGHT_RATIO", 0.55),
])
def test_individual_position_and_size_errors_produce_domain_correction(load_module, changes, dimension, target):
    gate, decision, updated = run_feedback(load_module, observation=measured_observation(**changes))
    assert gate.accepted and decision.decision == "ADJUST"
    assert updated.correction_count == 1
    component, = decision.correction_intent.components
    assert component.dimension == dimension and component.target_value == target


@pytest.mark.parametrize("changes", [{"center_x": 0.55}, {"center_y": 0.65}, {"height": 0.6}])
def test_visual_tolerance_boundaries_are_inclusive(load_module, changes):
    _, decision, _ = run_feedback(load_module, observation=measured_observation(**changes))
    assert decision.decision == "CONTINUE"


def test_slightly_over_tolerance_has_no_hidden_epsilon(load_module):
    _, decision, _ = run_feedback(load_module, observation=measured_observation(center_x=0.550000001))
    assert decision.decision == "ADJUST"


def test_xy_errors_share_one_request_and_one_budget_unit(load_module):
    _, decision, state = run_feedback(load_module, observation=measured_observation(center_x=0.6, center_y=0.66))
    assert decision.decision == "ADJUST"
    assert [component.dimension for component in decision.correction_intent.components] == ["CENTER_X", "CENTER_Y"]
    assert state.correction_count == 1


def test_captain_offset_restores_y_and_height_at_current_time(load_module):
    _, decision, state = run_feedback(load_module, observation=measured_observation(center_y=0.66, height=0.47))
    assert decision.decision == "ADJUST"
    intent = decision.correction_intent
    assert intent.shot_id == "object-shot" and intent.plan_id == "object-plan" and intent.trajectory_time == 2.5
    assert [(c.dimension, c.target_value, c.observed_value, c.error) for c in intent.components] == [
        ("CENTER_Y", 0.6, 0.66, 0.06), ("SUBJECT_HEIGHT_RATIO", 0.55, 0.47, -0.08)]
    assert state.correction_count == 1
    for forbidden in ("rotate", "move_forward", "speed", "duration", "angle", "PWM", "GPIO", "motor"):
        assert forbidden not in intent.model_dump_json()


def test_unconstrained_distance_is_ignored_even_when_measured(load_module):
    _, decision, _ = run_feedback(load_module, observation=measured_observation(distance=100.0))
    assert decision.decision == "CONTINUE"


@pytest.mark.parametrize("distance", [2.0, 2.1])
def test_distance_target_accepts_value_and_inclusive_tolerance(load_module, distance):
    _, decision, _ = run_feedback(load_module, trajectory=trajectory_with_distance(2.0, 0.1), observation=measured_observation(distance=distance))
    assert decision.decision == "CONTINUE"


def test_distance_error_can_be_corrected_only_as_physical_domain_value(load_module):
    _, decision, _ = run_feedback(load_module, trajectory=trajectory_with_distance(2.0, 0.1), observation=measured_observation(distance=2.5))
    assert decision.decision == "ADJUST"
    component, = decision.correction_intent.components
    assert component.dimension == "DISTANCE" and component.target_value == 2.0 and component.error == 0.5


def test_required_distance_measurement_missing_pauses(load_module):
    _, decision, updated = run_feedback(load_module, trajectory=trajectory_with_distance(2.0, 0.1))
    assert decision.decision == "PAUSE" and decision.reason == "required_measurement_missing"
    assert decision.correction_intent is None and updated.correction_count == 0


def test_distance_target_without_tolerance_rejected_at_feedback_business_boundary(load_module):
    trajectory = trajectory_with_distance(2.0)  # Phase 5A structural contract remains valid.
    with pytest.raises(AgentError) as error:
        run_feedback(load_module, trajectory=trajectory, observation=measured_observation(distance=2.0))
    assert error.value.code == "INVALID_PLAN"


def test_height_and_distance_errors_are_both_reported_not_ranked(load_module):
    _, decision, state = run_feedback(load_module, trajectory=trajectory_with_distance(2.0, 0.1), observation=measured_observation(height=0.47, distance=8.0))
    assert decision.decision == "ADJUST"
    assert [c.dimension for c in decision.correction_intent.components] == ["SUBJECT_HEIGHT_RATIO", "DISTANCE"]
    assert state.correction_count == 1


@pytest.mark.parametrize("observation,dimensions", [
    ({"center_y": 0.66}, ["CENTER_X"]), ({"height": 0.47}, ["CENTER_X", "CENTER_Y"]),
    ({"center_x": 0.6, "center_y": 0.66}, ["CENTER_X"]),
])
def test_any_unsupported_required_dimension_pauses_without_partial_correction(load_module, observation, dimensions):
    _, decision, state = run_feedback(load_module, observation=measured_observation(**observation), dimensions=dimensions)
    assert decision.decision == "PAUSE" and decision.reason == "unsupported_correction"
    assert decision.correction_intent is None and state.correction_count == 0


def test_distance_error_without_distance_capability_pauses(load_module):
    _, decision, _ = run_feedback(load_module, trajectory=trajectory_with_distance(2.0, 0.1), observation=measured_observation(height=0.47, distance=8.0), dimensions=ALL_DIMENSIONS[:-1])
    assert decision.decision == "PAUSE" and decision.reason == "unsupported_correction"


@pytest.mark.parametrize("count", [3, 4])
def test_offset_at_exhausted_budget_pauses(load_module, count):
    state = current_state(correction_count=count)
    _, decision, updated = run_feedback(load_module, observation=measured_observation(height=0.47), state=state)
    assert decision.decision == "PAUSE" and decision.reason == "correction_budget_exhausted"
    assert decision.correction_intent is None and updated == state


@pytest.mark.parametrize("count", [3, 4])
def test_restored_frame_continues_despite_exhausted_budget(load_module, count):
    state = current_state(correction_count=count)
    _, decision, updated = run_feedback(load_module, state=state, dimensions=[])
    assert decision.decision == "CONTINUE" and updated == state


@pytest.mark.parametrize("scenario,status,code", [
    ("wrong_shot", "EXECUTING", "WRONG_SHOT"), ("stale", "EXECUTING", "STALE"),
    ("normal", "PAUSED", "INACTIVE_STATE"), ("normal", "READY", "INACTIVE_STATE"),
    ("normal", "PLANNED", "INACTIVE_STATE"), ("normal", "COMPLETED", "INACTIVE_STATE"),
    ("normal", "FAILED", "INACTIVE_STATE"), ("old_plan", "EXECUTING", "WRONG_PLAN"),
    ("missing_plan", "EXECUTING", "MISSING_PLAN"), ("invalid_bbox", "EXECUTING", "INVALID_OBSERVATION"),
])
def test_rejected_observation_never_runs_v2_logic(load_module, monkeypatch, scenario, status, code):
    feedback = load_module("feedback")
    assert hasattr(feedback, "evaluate_feedback_v2"), "Trajectory Feedback V2 not implemented"
    def must_not_run(*args, **kwargs):
        pytest.fail("Gate-rejected observation reached Feedback V2")
    monkeypatch.setattr(feedback, "_decide_trajectory_feedback", must_not_run)
    payload = observation_data()
    if scenario == "wrong_shot": payload["shot_id"] = "other-shot"
    elif scenario == "stale": payload["timestamp"] = 98.0
    elif scenario == "old_plan": payload["plan_id"] = "old-plan"
    elif scenario == "missing_plan": del payload["plan_id"]
    elif scenario == "invalid_bbox": payload["bbox"]["y2"] = -0.1
    state = current_state(status=status)
    gate, decision, updated = run_feedback(load_module, observation=payload, state=state)
    assert not gate.accepted and gate.code == code and decision is None and updated == state


def test_wrong_trajectory_plan_binding_never_runs_feedback(load_module, monkeypatch):
    feedback = load_module("feedback")
    assert hasattr(feedback, "evaluate_feedback_v2"), "Trajectory Feedback V2 not implemented"
    def must_not_run(*args, **kwargs):
        pytest.fail("Wrong trajectory plan reached feedback")
    monkeypatch.setattr(feedback, "_decide_trajectory_feedback", must_not_run)
    gate, decision, state = run_feedback(load_module, trajectory_plan_id="old-plan")
    assert not gate.accepted and gate.code == "WRONG_PLAN" and decision is None and state.correction_count == 0


def test_lost_target_pauses_without_fabricated_correction(load_module):
    gate, decision, state = run_feedback(load_module, observation=Observation(**observation_data(bbox=None)))
    assert gate.accepted and decision.decision == "PAUSE" and decision.reason == "target_lost"
    assert decision.correction_intent is None and state.correction_count == 0


def test_feedback_never_derives_trajectory_time_from_wall_clock(load_module, monkeypatch):
    import time
    monkeypatch.setattr(time, "time", lambda: pytest.fail("Feedback must not read wall clock"))
    observation = measured_observation()
    _, at_middle, _ = run_feedback(load_module, observation=observation, trajectory_time=2.5)
    _, at_start, _ = run_feedback(load_module, observation=observation, trajectory_time=0.0)
    assert at_middle.decision == "CONTINUE" and at_start.decision == "ADJUST"


@pytest.mark.parametrize("scenario,result", [("exact", "CONTINUE"), ("offset", "ADJUST"), ("lost", "PAUSE")])
def test_offline_trajectory_feedback_contract_e2e(load_module, monkeypatch, scenario, result):
    import socket
    def no_network(*args, **kwargs):
        pytest.fail("Feedback E2E must remain offline")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    trajectory = trajectory_with_distance()
    observation = measured_observation(center_y=0.66, height=0.47) if scenario == "offset" else measured_observation()
    if scenario == "lost": observation = Observation(**observation_data(bbox=None))
    gate, decision, _ = run_feedback(load_module, observation=observation, trajectory=trajectory)
    assert gate.accepted and decision.decision == result


@pytest.mark.parametrize("fixture,result", [("ALL", "ADJUST"), ("VISUAL_ONLY", "ADJUST"), ("HORIZONTAL_ONLY", "PAUSE"), ("NONE", "PAUSE")])
def test_mock_capability_fixture_controls_feedback_without_hardware(load_module, fixture, result):
    mocks = load_module("mocks")
    assert hasattr(mocks, "mock_correction_capabilities"), "MOCK correction capability fixtures not implemented"
    capability = mocks.mock_correction_capabilities()[fixture]
    feedback = load_module("feedback")
    gate, decision, state = feedback.evaluate_feedback_v2(
        trajectory=trajectory_with_distance(), trajectory_time=2.5,
        observation=measured_observation(center_y=0.66, height=0.47), state=current_state(),
        config=feedback.FeedbackConfig(max_corrections=3, max_age_seconds=1.0),
        correction_capability=capability, trajectory_plan_id="object-plan", now=100.0)
    assert gate.accepted and decision.decision == result
    assert state.correction_count == (1 if result == "ADJUST" else 0)


@pytest.mark.parametrize("t,y,height,distance", [(0.0, 0.7, 0.4, 2.0), (2.5, 0.6, 0.55, 1.5), (5.0, 0.5, 0.7, 1.0)])
def test_feedback_compares_interpolated_distance_at_observation_time(load_module, t, y, height, distance):
    payload = captain_trajectory_data()
    payload["keyframes"][0]["frame_state"]["distance"] = 2.0
    payload["keyframes"][1]["frame_state"]["distance"] = 1.0
    payload["tolerance"]["distance_tolerance"] = 0.1
    _, decision, _ = run_feedback(load_module, trajectory=TargetTrajectory(**payload), trajectory_time=t,
                                 observation=measured_observation(center_y=y, height=height, distance=distance))
    assert decision.decision == "CONTINUE"


def test_zero_budget_blocks_new_request_but_not_matching_frame(load_module):
    _, matching, _ = run_feedback(load_module, max_corrections=0)
    _, offset, state = run_feedback(load_module, max_corrections=0, observation=measured_observation(height=0.47))
    assert matching.decision == "CONTINUE"
    assert offset.decision == "PAUSE" and offset.reason == "correction_budget_exhausted"
    assert state.correction_count == 0


def test_pause_decision_is_proposal_not_lifecycle_confirmation(load_module):
    original = current_state()
    _, decision, state = run_feedback(load_module, observation=Observation(**observation_data(bbox=None)), state=original)
    assert decision.decision == "PAUSE"
    assert state == original and state.status == "EXECUTING"
