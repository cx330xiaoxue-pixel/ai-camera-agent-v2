import pytest
from pydantic import ValidationError


def test_valid_script_round_trip(load_module, shot_data):
    m = load_module("models")
    script = m.ShotScript(
        schema_version="0.1", registry_revision="mock-v0",
        overall_goal="An outfit video", shots=[shot_data],
    )
    assert m.ShotScript.model_validate_json(script.model_dump_json()) == script
    assert script.shots[0].transition is None
    assert script.shots[0].camera_motions[0].motion == "push toward subject"
    assert m.UserRequest(text="Make an outfit video").text == "Make an outfit video"


@pytest.mark.parametrize("field", ["target_center_x", "target_center_y", "tolerance_x", "tolerance_y"])
@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_normalized_target(load_module, shot_data, field, value):
    m = load_module("models")
    shot_data["composition_target"][field] = value
    with pytest.raises(ValidationError):
        m.Shot.model_validate(shot_data)


def test_empty_actions_rejected(load_module, plan_data):
    m = load_module("models")
    plan_data["actions"] = []
    with pytest.raises(ValidationError):
        m.ShotExecutionPlan.model_validate(plan_data)


def test_empty_motions_rejected(load_module, shot_data):
    m = load_module("models")
    shot_data["camera_motions"] = []
    with pytest.raises(ValidationError):
        m.Shot.model_validate(shot_data)


def test_empty_script_rejected(load_module):
    m = load_module("models")
    with pytest.raises(ValidationError):
        m.ShotScript(schema_version="0.1", registry_revision="mock-v0", overall_goal="Video", shots=[])


@pytest.mark.parametrize("bbox", [
    {"x1": 0.7, "y1": 0.2, "x2": 0.3, "y2": 0.8},
    {"x1": 0.2, "y1": 0.8, "x2": 0.7, "y2": 0.2},
    {"x1": 0.2, "y1": 0.2, "x2": 0.2, "y2": 0.8},
    {"x1": -0.1, "y1": 0.2, "x2": 0.7, "y2": 0.8},
    {"x1": 0.2, "y1": 0.2, "x2": 1.1, "y2": 0.8},
])
def test_invalid_bbox_rejected_without_repair(load_module, bbox):
    m = load_module("models")
    with pytest.raises(ValidationError):
        m.Observation(shot_id="s1", timestamp=100.0, bbox=bbox)


def test_lost_target_is_explicit_null_bbox(load_module):
    m = load_module("models")
    lost = m.Observation(shot_id="s1", timestamp=100.0, bbox=None)
    assert lost.no_target is True
    with pytest.raises(ValidationError):
        m.Observation(shot_id="s1", timestamp=100.0)


@pytest.mark.parametrize("decision", ["UNKNOWN", "ADJUST"])
def test_invalid_decision_rejected(load_module, decision):
    m = load_module("models")
    with pytest.raises(ValidationError):
        m.AgentDecision(decision=decision, reason="Test")


def test_adjust_contains_semantic_correction(load_module):
    m = load_module("models")
    correction = m.CorrectionIntent(
        shot_id="s1", plan_id="p1", correction_dimension="horizontal",
        target=0.5, reason="Restore horizontal framing",
    )
    decision = m.AgentDecision(decision="ADJUST", reason="Off target", correction_intent=correction)
    assert decision.correction_intent.target_action_id is None
    assert decision.correction_intent.target == 0.5


def test_continue_cannot_hide_correction(load_module):
    m = load_module("models")
    with pytest.raises(ValidationError):
        m.AgentDecision(decision="CONTINUE", reason="Fine", correction_intent={
            "shot_id": "s1", "plan_id": "p1", "correction_dimension": "horizontal",
            "target": 0.5, "reason": "Restore framing",
        })


def test_initial_and_correction_share_envelope(load_module, action_data):
    m = load_module("models")
    initial = m.StructuredAction.model_validate(action_data)
    action_data["source"] = "CORRECTION"
    correction = m.StructuredAction.model_validate(action_data)
    assert initial.source == "INITIAL"
    assert correction.source == "CORRECTION"
    assert initial.plan_id == correction.plan_id


@pytest.mark.parametrize("field,value", [("expected_duration", -1.0), ("expected_duration", "2")])
def test_duration_invalid_or_coerced_rejected(load_module, shot_data, field, value):
    m = load_module("models")
    shot_data[field] = value
    with pytest.raises(ValidationError):
        m.Shot.model_validate(shot_data)


def test_unknown_fields_and_hardware_fields_rejected(load_module):
    m = load_module("models")
    with pytest.raises(ValidationError):
        m.CameraMotionIntent(motion="push", pwm=100)


def test_two_semantic_motions_preserve_order(load_module, shot_data):
    m = load_module("models")
    shot_data["camera_motions"].append({"motion": "stay still", "timing_requirement": "after push"})
    shot = m.Shot.model_validate(shot_data)
    assert [motion.motion for motion in shot.camera_motions] == ["push toward subject", "stay still"]
