import pytest


def state(load_module, status="EXECUTING"):
    return load_module("state").AgentState(plan_id="p1", shot_id="s1", registry_revision="mock-v0", status=status)


def test_fresh_observation_accepted(load_module):
    fixtures = load_module("mocks").mock_observations(shot_id="s1", now=100.0)
    result = load_module("observations").gate_observation(fixtures["NORMAL"], state(load_module), now=100.0, max_age_seconds=1.0)
    assert result.accepted and result.code == "ACCEPTED"
    assert result.observation == fixtures["NORMAL"]


@pytest.mark.parametrize("status", ["PLANNED", "READY", "PAUSED", "COMPLETED", "FAILED"])
def test_inactive_state_cannot_process_or_resume(load_module, status):
    current = state(load_module, status)
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["NORMAL"]
    result = load_module("observations").gate_observation(observation, current, now=100.0, max_age_seconds=1.0)
    assert not result.accepted and result.code == "INACTIVE_STATE"
    assert result.observation is None and current.status == status
    assert not hasattr(result, "correction_intent")


@pytest.mark.parametrize("scenario,code", [("STALE", "STALE"), ("WRONG_SHOT", "WRONG_SHOT")])
def test_bad_context_rejected(load_module, scenario, code):
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)[scenario]
    result = load_module("observations").gate_observation(observation, state(load_module), now=100.0, max_age_seconds=1.0)
    assert not result.accepted and result.code == code and result.reason


def test_lost_target_is_valid_observation(load_module):
    observation = load_module("mocks").mock_observations(shot_id="s1", now=100.0)["LOST"]
    result = load_module("observations").gate_observation(observation, state(load_module), now=100.0, max_age_seconds=1.0)
    assert result.accepted and result.observation.no_target


@pytest.mark.parametrize("change", ["ordering", "missing", "both_representations", "future"])
def test_invalid_observation_not_repaired(load_module, change):
    raw = {"shot_id": "s1", "timestamp": 100.0, "bbox": {"x1": 0.3, "y1": 0.2, "x2": 0.7, "y2": 0.8}}
    if change == "ordering":
        raw["bbox"]["x1"] = 0.9
    elif change == "missing":
        del raw["bbox"]
    elif change == "both_representations":
        raw["no_target"] = True
    else:
        raw["timestamp"] = 101.0
    result = load_module("observations").gate_observation(raw, state(load_module), now=100.0, max_age_seconds=1.0)
    assert not result.accepted and result.code == "INVALID_OBSERVATION"


def test_freshness_boundary(load_module):
    raw = {"shot_id": "s1", "timestamp": 99.0, "bbox": None}
    gate = load_module("observations").gate_observation
    assert gate(raw, state(load_module), now=100.0, max_age_seconds=1.0).accepted
    assert gate(raw, state(load_module), now=100.001, max_age_seconds=1.0).code == "STALE"


@pytest.mark.parametrize("now,age", [(float("nan"), 1.0), (100.0, -1.0), (100.0, float("inf"))])
def test_invalid_gate_configuration(load_module, now, age):
    with pytest.raises(ValueError):
        load_module("observations").gate_observation({"shot_id": "s1", "timestamp": 100.0, "bbox": None}, state(load_module), now=now, max_age_seconds=age)


def test_mock_scenarios_have_expected_geometry(load_module):
    fixtures = load_module("mocks").mock_observations(shot_id="s1", now=100.0)
    assert set(fixtures) == {"NORMAL", "LEFT_OFFSET", "RIGHT_OFFSET", "NEAR_EDGE", "LOST", "STALE", "WRONG_SHOT"}
    center = lambda observation: (observation.bbox.x1 + observation.bbox.x2) / 2
    assert abs(center(fixtures["NORMAL"]) - 0.5) <= 0.1
    assert center(fixtures["LEFT_OFFSET"]) < 0.4
    assert center(fixtures["RIGHT_OFFSET"]) > 0.6
    assert fixtures["NEAR_EDGE"].bbox.x1 < 0.05
    assert fixtures["LOST"].bbox is None
