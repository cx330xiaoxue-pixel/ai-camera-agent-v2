"""Phase 5A contracts only. All fixture positions are MOCK TARGET VALUES."""

import pytest
from pydantic import ValidationError

from agent_system.errors import AgentError


def model(load_module, name):
    module = load_module("models")
    assert hasattr(module, name), f"Visual contract not implemented: {name}"
    return getattr(module, name)


def frame_data(**changes):
    values = {"center_x": 0.5, "center_y": 0.5, "subject_height_ratio": 0.4, "distance": None}
    values.update(changes)
    return values


def test_valid_frame_state_without_distance(load_module):
    frame = model(load_module, "FrameState")(**frame_data())
    assert frame.center_x == 0.5 and frame.subject_height_ratio == 0.4
    assert frame.distance is None


def test_frame_state_distance_is_optional_and_preserved(load_module):
    cls = model(load_module, "FrameState")
    assert cls(center_x=0.5, center_y=0.5, subject_height_ratio=0.4).distance is None
    assert cls(**frame_data(distance=2.0)).distance == 2.0  # MOCK physical value; unit not frozen.


@pytest.mark.parametrize("field", ["center_x", "center_y"])
@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), "0.5", True])
def test_invalid_frame_center_rejected(load_module, field, value):
    cls = model(load_module, "FrameState")
    with pytest.raises(ValidationError):
        cls(**frame_data(**{field: value}))


@pytest.mark.parametrize("value", [0.0, -0.1, 1.01, float("nan"), float("inf"), "0.4"])
def test_invalid_frame_height_rejected(load_module, value):
    cls = model(load_module, "FrameState")
    with pytest.raises(ValidationError):
        cls(**frame_data(subject_height_ratio=value))


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), "2.0", True])
def test_invalid_frame_distance_rejected(load_module, value):
    cls = model(load_module, "FrameState")
    with pytest.raises(ValidationError):
        cls(**frame_data(distance=value))


@pytest.mark.parametrize("center_y", [0.1, 0.9])
def test_frame_geometry_rejected_without_clamping(load_module, center_y):
    cls = model(load_module, "FrameState")
    with pytest.raises(ValidationError, match="height"):
        cls(**frame_data(center_y=center_y, subject_height_ratio=0.4))


@pytest.mark.parametrize("center_y,height", [(0.3, 0.6), (0.7, 0.6), (0.5, 1.0)])
def test_frame_geometry_accepts_exact_screen_edges(load_module, center_y, height):
    assert model(load_module, "FrameState")(**frame_data(center_y=center_y, subject_height_ratio=height)).center_y == center_y


def test_frame_state_forbids_hardware_and_duplicate_bbox_fields(load_module):
    cls = model(load_module, "FrameState")
    with pytest.raises(ValidationError):
        cls(**frame_data(), pwm=200)
    with pytest.raises(ValidationError):
        cls(**frame_data(), bbox={})


# MOCK TARGET VALUES, not team definitions of "low" or "middle".
LOW_TARGET_FIXTURE = 0.7
CENTER_TARGET_FIXTURE = 0.5


def captain_trajectory_data():
    return {
        "keyframes": [
            {"time_offset": 0.0, "frame_state": frame_data(center_y=LOW_TARGET_FIXTURE)},
            {"time_offset": 5.0, "frame_state": frame_data(center_y=CENTER_TARGET_FIXTURE, subject_height_ratio=0.7)},
        ],
        "tolerance": {"center_x_tolerance": 0.05, "center_y_tolerance": 0.05, "height_ratio_tolerance": 0.05},
    }


def test_valid_trajectory_has_relative_duration_and_no_distance_target(load_module):
    trajectory = model(load_module, "TargetTrajectory")(**captain_trajectory_data())
    assert trajectory.duration == 5.0
    assert all(k.frame_state.distance is None for k in trajectory.keyframes)
    assert trajectory.tolerance.distance_tolerance is None


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), "0", True])
def test_invalid_keyframe_time_rejected(load_module, value):
    cls = model(load_module, "TargetTrajectoryKeyframe")
    with pytest.raises(ValidationError):
        cls(time_offset=value, frame_state=frame_data())


@pytest.mark.parametrize("times", [[], [0.0], [1.0, 5.0], [0.0, 0.0], [0.0, 5.0, 4.0]])
def test_invalid_trajectory_time_sequence_rejected(load_module, times):
    cls = model(load_module, "TargetTrajectory")
    payload = captain_trajectory_data()
    payload["keyframes"] = [{"time_offset": t, "frame_state": frame_data()} for t in times]
    with pytest.raises(ValidationError):
        cls(**payload)


@pytest.mark.parametrize("field", ["center_x_tolerance", "center_y_tolerance", "height_ratio_tolerance"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_normalized_tolerance_rejected(load_module, field, value):
    cls = model(load_module, "TargetTrajectory")
    payload = captain_trajectory_data()
    payload["tolerance"][field] = value
    with pytest.raises(ValidationError):
        cls(**payload)


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_invalid_distance_tolerance_rejected(load_module, value):
    cls = model(load_module, "TargetTrajectory")
    payload = captain_trajectory_data()
    payload["tolerance"]["distance_tolerance"] = value
    with pytest.raises(ValidationError):
        cls(**payload)


def test_zero_tolerances_are_valid_exact_match_policy(load_module):
    cls = model(load_module, "TrajectoryTolerance")
    assert cls(center_x_tolerance=0.0, center_y_tolerance=0.0, height_ratio_tolerance=0.0, distance_tolerance=0.0).height_ratio_tolerance == 0.0


def test_invalid_nested_frame_rejected(load_module):
    cls = model(load_module, "TargetTrajectory")
    payload = captain_trajectory_data()
    payload["keyframes"][0]["frame_state"]["subject_height_ratio"] = 0.9
    with pytest.raises(ValidationError):
        cls(**payload)


@pytest.mark.parametrize("first,last", [(None, 1.0), (1.0, None)])
def test_mixed_distance_targets_rejected(load_module, first, last):
    cls = model(load_module, "TargetTrajectory")
    payload = captain_trajectory_data()
    payload["keyframes"][0]["frame_state"]["distance"] = first
    payload["keyframes"][1]["frame_state"]["distance"] = last
    with pytest.raises(ValidationError, match="distance"):
        cls(**payload)


@pytest.mark.parametrize("time,y,height", [(0.0, 0.7, 0.4), (2.5, 0.6, 0.55), (5.0, 0.5, 0.7)])
def test_captain_position_and_size_example(load_module, time, y, height):
    trajectory = model(load_module, "TargetTrajectory")(**captain_trajectory_data())
    expected = trajectory.evaluate(time)
    assert expected.center_y == y
    assert expected.subject_height_ratio == height
    assert expected.distance is None


def test_all_present_distance_targets_interpolate(load_module):
    cls = model(load_module, "TargetTrajectory")
    payload = captain_trajectory_data()
    payload["keyframes"][0]["frame_state"]["distance"] = 2.0  # MOCK value; external unit.
    payload["keyframes"][1]["frame_state"]["distance"] = 1.0
    trajectory = cls(**payload)
    assert trajectory.evaluate(0.0).distance == 2.0
    assert trajectory.evaluate(2.5).distance == 1.5
    assert trajectory.evaluate(5.0).distance == 1.0


def test_piecewise_interpolation_samples_correct_segment_and_exact_keyframe(load_module):
    payload = captain_trajectory_data()
    payload["keyframes"] = [
        {"time_offset": 0.0, "frame_state": frame_data(center_x=0.2)},
        {"time_offset": 2.0, "frame_state": frame_data(center_x=0.4, subject_height_ratio=0.5)},
        {"time_offset": 5.0, "frame_state": frame_data(center_x=0.8, subject_height_ratio=0.7)},
    ]
    trajectory = model(load_module, "TargetTrajectory")(**payload)
    assert trajectory.evaluate(2.0) == trajectory.keyframes[1].frame_state
    assert trajectory.evaluate(1.0).center_x == 0.3
    assert trajectory.evaluate(3.5).center_x == 0.6
    assert trajectory.evaluate(3.5).subject_height_ratio == 0.6


def test_constant_trajectory_preserves_known_state(load_module):
    payload = captain_trajectory_data()
    for keyframe in payload["keyframes"]:
        keyframe["frame_state"] = frame_data()
    trajectory = model(load_module, "TargetTrajectory")(**payload)
    assert trajectory.evaluate(0.0) == trajectory.evaluate(2.5) == trajectory.evaluate(5.0)


@pytest.mark.parametrize("time", [-0.01, 5.01, float("nan"), float("inf"), "2.5", True])
def test_invalid_sampling_time_rejected_without_extrapolation(load_module, time):
    trajectory = model(load_module, "TargetTrajectory")(**captain_trajectory_data())
    with pytest.raises(AgentError) as error:
        trajectory.evaluate(time)
    assert error.value.code == "INVALID_TRAJECTORY_TIME"


def test_trajectory_rejects_llm_chosen_curve_type(load_module):
    cls = model(load_module, "TargetTrajectory")
    with pytest.raises(ValidationError):
        cls(**captain_trajectory_data(), interpolation="CUBIC")


def test_trajectory_json_round_trip(load_module):
    cls = model(load_module, "TargetTrajectory")
    trajectory = cls(**captain_trajectory_data())
    assert cls.model_validate_json(trajectory.model_dump_json()) == trajectory


def observation_data(**changes):
    values = {"shot_id": "object-shot", "timestamp": 100.0, "bbox": {"x1": 0.4, "y1": 0.325, "x2": 0.6, "y2": 0.875}}
    values.update(changes)
    return values


def test_observation_converts_bbox_to_frame_state_without_stored_duplicates(load_module):
    observation = model(load_module, "Observation")(**observation_data())
    assert hasattr(observation, "to_frame_state"), "Observation conversion not implemented"
    measured = observation.to_frame_state()
    assert measured.center_x == 0.5
    assert measured.center_y == 0.6
    assert measured.subject_height_ratio == 0.55
    assert measured.distance is None
    assert not {"center_x", "center_y", "subject_height_ratio"}.intersection(observation.model_dump())


def test_observation_distance_preserved_without_conversion_or_invented_unit(load_module):
    observation = model(load_module, "Observation")(**observation_data(distance=2.0))
    assert observation.distance == observation.to_frame_state().distance == 2.0


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), "2.0", True])
def test_invalid_observation_distance_rejected(load_module, value):
    cls = model(load_module, "Observation")
    assert "distance" in cls.model_fields, "Observation distance field not implemented"
    with pytest.raises(ValidationError):
        cls(**observation_data(distance=value))


@pytest.mark.parametrize("distance", [None, 2.0])
def test_lost_observation_never_fabricates_frame_state(load_module, distance):
    observation = model(load_module, "Observation")(**observation_data(bbox=None, distance=distance))
    assert hasattr(observation, "to_frame_state"), "Observation conversion not implemented"
    assert observation.no_target and observation.to_frame_state() is None


@pytest.mark.parametrize("bbox", [
    {"x1": 0.1, "y1": 0.0, "x2": 0.9, "y2": 1.0},
    {"x1": 0.1, "y1": 0.0, "x2": 0.9, "y2": 0.6},
    {"x1": 0.1, "y1": 0.4, "x2": 0.9, "y2": 1.0},
    {"x1": 0.499, "y1": 0.499, "x2": 0.501, "y2": 0.501},
])
def test_legal_bbox_extents_remain_legal_frame_states(load_module, bbox):
    observation = model(load_module, "Observation")(**observation_data(bbox=bbox))
    assert hasattr(observation, "to_frame_state"), "Observation conversion not implemented"
    measured = observation.to_frame_state()
    assert measured is not None
    assert 0 < measured.subject_height_ratio <= 1


def test_contract_e2e_expected_and_measured_share_frame_state(load_module, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        pytest.fail("Visual Contract E2E must stay offline")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    expected = model(load_module, "TargetTrajectory")(**captain_trajectory_data()).evaluate(2.5)
    observation = model(load_module, "Observation")(**observation_data())
    assert hasattr(observation, "to_frame_state"), "Observation conversion not implemented"
    measured = observation.to_frame_state()
    assert isinstance(measured, type(expected))
    assert expected == measured


def visual_shot_data(**changes):
    values = {"shot_id": "object-shot", "shot_goal": "展示固定物体", "subject_action": None,
              "target_trajectory": captain_trajectory_data(), "expected_duration": 5.0}
    values.update(changes)
    return values


def visual_script_data(**changes):
    values = {"schema_version": "0.2", "registry_revision": "mock-v0", "overall_goal": "固定物体画面目标",
              "shots": [visual_shot_data()]}
    values.update(changes)
    return values


def test_fixed_object_shot_accepts_null_subject_action_and_no_legacy_targets(load_module):
    shot = model(load_module, "Shot")(**visual_shot_data())
    assert shot.subject_action is None
    assert shot.composition_target is None and shot.camera_motions == []
    assert shot.target_trajectory.duration == shot.expected_duration


def test_visual_shot_can_omit_subject_action(load_module):
    payload = visual_shot_data()
    del payload["subject_action"]
    assert model(load_module, "Shot")(**payload).subject_action is None


def test_visual_trajectory_is_authoritative_when_legacy_field_is_retained(load_module, shot_data):
    payload = visual_shot_data(composition_target=shot_data["composition_target"])
    payload["composition_target"]["target_center_y"] = 0.2
    shot = model(load_module, "Shot")(**payload)
    assert shot.target_trajectory.evaluate(0.0).center_y == LOW_TARGET_FIXTURE


def test_trajectory_duration_must_match_declared_shot_duration(load_module):
    cls = model(load_module, "Shot")
    assert cls(**visual_shot_data()).expected_duration == 5.0
    with pytest.raises(ValidationError, match="duration"):
        cls(**visual_shot_data(expected_duration=4.0))


def test_visual_script_version_and_json_round_trip(load_module):
    cls = model(load_module, "ShotScript")
    script = cls(**visual_script_data())
    assert script.schema_version == "0.2"
    assert cls.model_validate_json(script.model_dump_json()) == script


def test_visual_version_requires_trajectory_not_legacy_static_target(load_module, shot_data):
    cls = model(load_module, "ShotScript")
    # Check the new contract works before checking its rejection policy.
    assert cls(**visual_script_data()).shots[0].target_trajectory is not None
    with pytest.raises(ValidationError, match="trajectory"):
        cls(**visual_script_data(shots=[shot_data]))


def test_legacy_version_cannot_smuggle_visual_trajectory(load_module):
    cls = model(load_module, "ShotScript")
    assert cls(**visual_script_data()).schema_version == "0.2"
    with pytest.raises(ValidationError, match="0.1"):
        cls(**visual_script_data(schema_version="0.1"))


def test_unsupported_script_version_rejected(load_module, shot_data):
    cls = model(load_module, "ShotScript")
    assert cls(**visual_script_data()).schema_version == "0.2"
    with pytest.raises(ValidationError):
        cls(**visual_script_data(schema_version="9.9", shots=[shot_data]))


def test_v0_static_path_stays_explicit_without_fabricated_size(load_module, shot_data):
    shot = model(load_module, "Shot")(**shot_data)
    assert hasattr(shot, "target_trajectory"), "Visual Shot field not implemented"
    assert shot.target_trajectory is None
    assert not hasattr(shot.composition_target, "subject_height_ratio")


def test_legacy_director_schema_does_not_expose_visual_target_contract(load_module):
    director = load_module("director")
    registry = load_module("registry")
    schema = director.director_schema(registry.project_capability(registry.load_mock_registry()), director.DirectorConfig())
    fields = schema["$defs"]["Shot"]["properties"]
    assert "target_trajectory" not in fields
    assert "FrameState" not in schema["$defs"]
    assert fields["camera_motions"]["minItems"] == 1
    assert {"subject_action", "composition_target", "camera_motions"} <= set(schema["$defs"]["Shot"]["required"])


def test_v0_director_does_not_claim_to_plan_visual_schema(load_module):
    director = load_module("director")
    registry = load_module("registry")
    with pytest.raises(AgentError) as error:
        director.director_schema(registry.project_capability(registry.load_mock_registry()), director.DirectorConfig(schema_version="0.2"))
    assert error.value.code == "SCHEMA_ERROR"


@pytest.mark.parametrize("status", ["REACHABLE", "UNREACHABLE", "UNKNOWN"])
def test_mock_reachability_reports_only_explicit_fixture_outcome(load_module, status):
    boundary = load_module("reachability")
    trajectory = model(load_module, "TargetTrajectory")(**captain_trajectory_data())
    result = boundary.ReachabilityResult(status=status, reason=f"MOCK ONLY: {status} fixture, no physical model")
    validator = load_module("mocks").MockReachabilityValidator(result)
    assert validator.validate(trajectory) == result
    assert hasattr(boundary, "ReachabilityValidator")


def test_mock_reachability_does_not_accept_invalid_visual_contract(load_module):
    boundary = load_module("reachability")
    validator = load_module("mocks").MockReachabilityValidator(
        boundary.ReachabilityResult(status="REACHABLE", reason="MOCK ONLY fixture"))
    invalid = captain_trajectory_data()
    invalid["keyframes"][1]["time_offset"] = 0.0
    with pytest.raises(ValidationError):
        validator.validate(invalid)


@pytest.mark.parametrize("payload", [{"status": "PASS", "reason": "not a reachability outcome"}, {"status": "UNKNOWN", "reason": ""}])
def test_reachability_result_requires_finite_status_set_and_reason(load_module, payload):
    boundary = load_module("reachability")
    with pytest.raises(ValidationError):
        boundary.ReachabilityResult(**payload)


@pytest.mark.parametrize("top,bottom", [(0.0, 10 / 1080), (1 - 10 / 1080, 1.0)])
def test_pixel_normalized_edge_bbox_not_rejected_by_decimal_reencoding(load_module, top, bottom):
    bbox = {"x1": 0.2, "y1": top, "x2": 0.8, "y2": bottom}
    observation = model(load_module, "Observation")(**observation_data(bbox=bbox))
    assert observation.to_frame_state() is not None
