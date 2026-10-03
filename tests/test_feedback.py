"""Phase 2 tests. All feedback thresholds below are MOCK TEST CONFIG."""

import pytest
from pydantic import ValidationError


def current_state(load_module, **changes):
    values = {"plan_id": "p1", "shot_id": "s1", "registry_revision": "mock-v0", "status": "EXECUTING"}
    values.update(changes)
    return load_module("state").AgentState(**values)


def adjustment(load_module, **changes):
    correction = {"shot_id": "s1", "plan_id": "p1", "correction_dimension": "horizontal", "target": 0.5, "reason": "subject_x_should_increase"}
    correction.update(changes)
    return load_module("models").AgentDecision(decision="ADJUST", reason="horizontal_offset", correction_intent=correction)


def test_correction_count_starts_at_zero(load_module):
    assert current_state(load_module).correction_count == 0


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_invalid_correction_count(load_module, count):
    with pytest.raises(ValidationError):
        current_state(load_module, correction_count=count)


def test_state_records_issued_adjustment_without_mutating_original(load_module):
    state = current_state(load_module)
    updated = state.record_correction(adjustment(load_module))
    assert updated.correction_count == 1 and state.correction_count == 0
    assert updated.status == "EXECUTING" and updated.plan_id == "p1"
    assert updated.confirm_pause().confirm_resume().correction_count == 1


@pytest.mark.parametrize("status", ["PLANNED", "READY", "PAUSED", "COMPLETED", "FAILED"])
def test_correction_recording_requires_execution(load_module, status):
    state = current_state(load_module, status=status)
    with pytest.raises(load_module("errors").AgentError) as caught:
        state.record_correction(adjustment(load_module))
    assert caught.value.code == "INVALID_STATE_TRANSITION"


@pytest.mark.parametrize("field", ["shot_id", "plan_id"])
def test_correction_recording_requires_matching_context(load_module, field):
    with pytest.raises(load_module("errors").AgentError) as caught:
        current_state(load_module).record_correction(adjustment(load_module, **{field: "other"}))
    assert caught.value.code == "INVALID_PLAN"


@pytest.mark.parametrize("decision", ["CONTINUE", "PAUSE"])
def test_only_adjustment_consumes_budget(load_module, decision):
    state = current_state(load_module)
    value = load_module("models").AgentDecision(decision=decision, reason="test")
    with pytest.raises(load_module("errors").AgentError) as caught:
        state.record_correction(value)
    assert caught.value.code == "UNSUPPORTED_CORRECTION"


def evaluate(load_module, *, observation=None, state=None, target=None, config=None, now=100.0):
    feedback = load_module("feedback")
    if observation is None:
        observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["NORMAL"]
    if state is None:
        state = current_state(load_module)
    if target is None:
        target = load_module("models").CompositionTarget(target_center_x=0.5, target_center_y=0.5, tolerance_x=0.1, tolerance_y=0.1)
    if config is None:
        # MOCK TEST CONFIG only. Tolerance remains solely in CompositionTarget.
        config = feedback.FeedbackConfig(max_corrections=3, max_age_seconds=load_module("mocks").MOCK_FRESHNESS_SECONDS)
    return feedback.evaluate_feedback(observation, target, state, config, now=now)


def observation_box(load_module, x1, y1, x2, y2):
    return load_module("models").Observation(shot_id="s1", timestamp=100.0, bbox={"x1": x1, "y1": y1, "x2": x2, "y2": y2})


@pytest.mark.parametrize("bbox", [
    (0.35, 0.2, 0.65, 0.8),  # NORMAL / exact target center
    (0.3, 0.2, 0.5, 0.8),   # left tolerance boundary
    (0.5, 0.2, 0.7, 0.8),   # right tolerance boundary
    (0.35, 0.3, 0.65, 0.5), # top tolerance boundary
    (0.35, 0.5, 0.65, 0.7), # bottom tolerance boundary
    (0.499999, 0.499999, 0.500001, 0.500001), # tiny but legal
    (0.001, 0.001, 0.999, 0.999),           # almost full frame
])
def test_continue_within_inclusive_tolerance(load_module, bbox):
    gate, decision, updated = evaluate(load_module, observation=observation_box(load_module, *bbox))
    assert gate.accepted
    assert decision.decision == "CONTINUE" and decision.reason == "within_tolerance"
    assert decision.correction_intent is None and updated.correction_count == 0


def test_decimal_tolerance_boundary_is_not_rounding_induced_offset(load_module):
    target = load_module("models").CompositionTarget(target_center_x=0.2, target_center_y=0.5, tolerance_x=0.1, tolerance_y=0.1)
    _, decision, _ = evaluate(load_module, observation=observation_box(load_module, 0.2, 0.2, 0.4, 0.8), target=target)
    assert decision.decision == "CONTINUE"


@pytest.mark.parametrize("scenario,direction", [("LEFT_OFFSET", "subject_x_should_increase"), ("RIGHT_OFFSET", "subject_x_should_decrease"), ("NEAR_EDGE", "subject_x_should_increase")])
def test_horizontal_offset_produces_semantic_correction(load_module, scenario, direction):
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)[scenario]
    original = current_state(load_module)
    gate, decision, updated = evaluate(load_module, observation=observation, state=original)
    assert gate.accepted and decision.decision == "ADJUST"
    assert decision.reason == "horizontal_offset"
    intent = decision.correction_intent
    assert (intent.shot_id, intent.plan_id) == ("s1", "p1")
    assert intent.correction_dimension == "horizontal" and intent.target == 0.5
    assert intent.reason == direction
    assert updated.correction_count == 1 and original.correction_count == 0
    assert updated.status == "EXECUTING"
    assert load_module("models").CorrectionIntent.model_validate_json(intent.model_dump_json()) == intent
    for forbidden in ("rotate", "move_forward", "move_backward", "speed", "duration", "angle", "PWM", "GPIO"):
        assert forbidden not in intent.model_dump_json()


@pytest.mark.parametrize("bbox,direction", [((0.35, 0.0, 0.65, 0.2), "subject_y_should_increase"), ((0.35, 0.8, 0.65, 1.0), "subject_y_should_decrease")])
def test_vertical_offset_is_composition_only(load_module, bbox, direction):
    _, decision, updated = evaluate(load_module, observation=observation_box(load_module, *bbox))
    assert decision.decision == "ADJUST" and decision.reason == "vertical_offset"
    assert decision.correction_intent.correction_dimension == "vertical"
    assert decision.correction_intent.target == 0.5 and decision.correction_intent.reason == direction
    assert updated.correction_count == 1


def test_slightly_outside_tolerance_adjusts(load_module):
    _, decision, _ = evaluate(load_module, observation=observation_box(load_module, 0.500000002, 0.2, 0.7, 0.8))
    assert decision.decision == "ADJUST"


@pytest.mark.parametrize("bbox,dimension", [((0.0, 0.1, 0.2, 0.3), "horizontal"), ((0.1, 0.0, 0.3, 0.2), "vertical"), ((0.0, 0.0, 0.2, 0.2), "horizontal")])
def test_dual_axis_chooses_larger_excess_with_horizontal_tie_break(load_module, bbox, dimension):
    _, decision, _ = evaluate(load_module, observation=observation_box(load_module, *bbox))
    assert decision.decision == "ADJUST"
    assert decision.correction_intent.correction_dimension == dimension


def test_lost_target_pauses_without_guessing(load_module):
    lost = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["LOST"]
    gate, decision, updated = evaluate(load_module, observation=lost)
    assert gate.accepted and decision.decision == "PAUSE" and decision.reason == "target_lost"
    assert decision.correction_intent is None
    assert updated.status == "EXECUTING" and updated.correction_count == 0


@pytest.mark.parametrize("count", [3, 4])
def test_exhausted_budget_pauses_when_new_correction_is_needed(load_module, count):
    offset = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["LEFT_OFFSET"]
    _, decision, updated = evaluate(load_module, observation=offset, state=current_state(load_module, correction_count=count))
    assert decision.decision == "PAUSE" and decision.reason == "correction_budget_exhausted"
    assert decision.correction_intent is None and updated.correction_count == count


def test_budget_limits_repeated_adjustments(load_module):
    feedback = load_module("feedback")
    config = feedback.FeedbackConfig(max_corrections=2, max_age_seconds=1.0)
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["LEFT_OFFSET"]
    state = current_state(load_module)
    for expected_count in (1, 2):
        _, decision, state = evaluate(load_module, observation=observation, state=state, config=config)
        assert decision.decision == "ADJUST" and state.correction_count == expected_count
    _, decision, state = evaluate(load_module, observation=observation, state=state, config=config)
    assert decision.decision == "PAUSE" and state.correction_count == 2


def test_zero_budget_disables_adjustments(load_module):
    config = load_module("feedback").FeedbackConfig(max_corrections=0, max_age_seconds=1.0)
    offset = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["LEFT_OFFSET"]
    _, decision, state = evaluate(load_module, observation=offset, config=config)
    assert decision.decision == "PAUSE" and state.correction_count == 0


@pytest.mark.parametrize("field,value", [("max_corrections", -1), ("max_corrections", True), ("max_corrections", 1.5), ("max_age_seconds", -0.1), ("max_age_seconds", float("nan")), ("max_age_seconds", float("inf"))])
def test_feedback_configuration_rejects_invalid_thresholds(load_module, field, value):
    values = {"max_corrections": 3, "max_age_seconds": 1.0}
    values[field] = value
    with pytest.raises(ValidationError):
        load_module("feedback").FeedbackConfig(**values)


@pytest.mark.parametrize("scenario,status,code", [
    ("STALE", "EXECUTING", "STALE"),
    ("WRONG_SHOT", "EXECUTING", "WRONG_SHOT"),
    ("NORMAL", "PAUSED", "INACTIVE_STATE"),
    ("NORMAL", "READY", "INACTIVE_STATE"),
    ("NORMAL", "PLANNED", "INACTIVE_STATE"),
    ("NORMAL", "COMPLETED", "INACTIVE_STATE"),
    ("NORMAL", "FAILED", "INACTIVE_STATE"),
])
def test_gate_rejection_never_runs_feedback(load_module, monkeypatch, scenario, status, code):
    feedback = load_module("feedback")
    def must_not_run(*args, **kwargs):
        pytest.fail("Rejected observation reached feedback logic")
    monkeypatch.setattr(feedback, "_decide_feedback", must_not_run)
    state = current_state(load_module, status=status)
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)[scenario]
    gate, decision, returned_state = evaluate(load_module, observation=observation, state=state)
    assert not gate.accepted and gate.code == code
    assert decision is None and returned_state is state


def test_invalid_bbox_rejected_before_feedback(load_module, monkeypatch):
    feedback = load_module("feedback")
    def must_not_run(*args, **kwargs):
        pytest.fail("Invalid bbox reached feedback logic")
    monkeypatch.setattr(feedback, "_decide_feedback", must_not_run)
    raw = {"shot_id": "s1", "timestamp": 100.0, "bbox": {"x1": 0.9, "y1": 0.2, "x2": 0.3, "y2": 0.8}}
    gate, decision, state = evaluate(load_module, observation=raw)
    assert gate.code == "INVALID_OBSERVATION" and decision is None and state.correction_count == 0


def test_freshness_configuration_is_passed_to_existing_gate(load_module):
    feedback = load_module("feedback")
    stale = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["STALE"]
    config = feedback.FeedbackConfig(max_corrections=3, max_age_seconds=3.0)
    gate, decision, _ = evaluate(load_module, observation=stale, config=config)
    assert gate.accepted and decision.decision == "CONTINUE"


@pytest.mark.parametrize("invalid_x", [1.2, float("nan")])
def test_invalid_target_cannot_produce_unsafe_correction(load_module, invalid_x):
    target = {"target_center_x": invalid_x, "target_center_y": 0.5, "tolerance_x": 0.1, "tolerance_y": 0.1}
    gate, decision, state = evaluate(load_module, target=target)
    assert gate.accepted and decision.decision == "PAUSE" and decision.reason == "invalid_composition_target"
    assert decision.correction_intent is None and state.correction_count == 0


@pytest.mark.parametrize("scenario,expected", [("NORMAL", "CONTINUE"), ("LEFT_OFFSET", "ADJUST"), ("LOST", "PAUSE")])
def test_feedback_runs_offline_without_api_keys(load_module, monkeypatch, scenario, expected):
    import socket
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    def no_network(*args, **kwargs):
        pytest.fail("Agent 3 attempted network access")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)[scenario]
    _, decision, _ = evaluate(load_module, observation=observation)
    assert decision.decision == expected
