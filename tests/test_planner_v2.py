"""Planner V2: visual contracts, finite repair and explicit reachability gate."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agent_system.errors import AgentError
from agent_system.llm import FakeDirectorLLM, OpenAIDirectorLLM
from agent_system.mocks import MockReachabilityValidator
from agent_system.reachability import ReachabilityResult
from agent_system.models import UserRequest
from agent_system.motion_compiler import demo_registry
from test_visual_contract import captain_trajectory_data


REQUEST = "固定桌面青铜器：从偏低、占画面高度40%，用5秒升到中部并放大到70%"


def script_data():
    return {"schema_version": "0.2", "registry_revision": demo_registry().revision,
            "overall_goal": "展示固定桌面物体的画面位置与比例变化",
            "shots": [{"shot_id": "object-shot", "shot_goal": "主体由偏低升到中部并放大",
                       "subject_action": None, "target_trajectory": captain_trajectory_data(),
                       "expected_duration": 5.0, "transition": None, "execution_relation": "SEQUENTIAL"}]}


def reachable(status="REACHABLE"):
    return MockReachabilityValidator(ReachabilityResult(status=status, reason="MOCK ONLY"))


def test_fixed_object_plans_visual_script_and_exposes_dynamic_context(load_module):
    module = load_module("planner_v2")
    llm = FakeDirectorLLM([script_data()])
    result = module.VisualPlanner(llm).plan(UserRequest(text=REQUEST), demo_registry(), reachable())
    assert result.schema_version == "0.2" and result.shots[0].subject_action is None
    assert result.shots[0].camera_motions == []
    assert result.shots[0].target_trajectory.evaluate(2.5).subject_height_ratio == 0.55
    assert llm.calls[0]["capability"]["registry_revision"] == result.registry_revision
    assert "parameter_schema" not in json.dumps(llm.calls[0]["capability"])


@pytest.mark.parametrize("change,code", [
    ("duplicate", "INVALID_PLAN"), ("parallel", "CAPABILITY_VIOLATION"),
    ("hardware", "SCHEMA_ERROR"), ("no_trajectory", "SCHEMA_ERROR"),
    ("distance", "CAPABILITY_VIOLATION"), ("revision", "REGISTRY_MISMATCH"),
    ("too_many", "INVALID_PLAN"), ("long_duration", "INVALID_PLAN"),
])
def test_invalid_candidates_refused(load_module, change, code):
    module = load_module("planner_v2")
    data = script_data()
    shot = data["shots"][0]
    if change == "duplicate":
        data["shots"].append(deepcopy(shot))
    elif change == "parallel":
        shot["execution_relation"] = "PARALLEL"
    elif change == "hardware":
        shot["target_trajectory"]["keyframes"][0]["frame_state"]["pwm"] = 20
    elif change == "no_trajectory":
        shot.pop("target_trajectory")
    elif change == "distance":
        for frame in shot["target_trajectory"]["keyframes"]:
            frame["frame_state"]["distance"] = 1.0
    elif change == "revision":
        data["registry_revision"] = "invented"
    elif change == "too_many":
        data["shots"] = [dict(deepcopy(shot), shot_id=f"s-{i}") for i in range(5)]
    elif change == "long_duration":
        shot["expected_duration"] = 20.0
        shot["target_trajectory"]["keyframes"][-1]["time_offset"] = 20.0
    llm = FakeDirectorLLM([data, data])
    with pytest.raises(AgentError) as error:
        module.VisualPlanner(llm).plan(UserRequest(text=REQUEST), demo_registry(), reachable())
    assert error.value.code == code
    assert len(llm.calls) <= 2


def test_repair_once_then_validate_whole_script(load_module):
    module = load_module("planner_v2")
    bad = script_data()
    bad["shots"].append(deepcopy(bad["shots"][0]))
    llm = FakeDirectorLLM([bad, script_data()])
    result = module.VisualPlanner(llm).plan(UserRequest(text=REQUEST), demo_registry(), reachable())
    assert len(result.shots) == 1 and len(llm.calls) == 2
    assert llm.calls[1]["repair_error"]["code"] == "INVALID_PLAN"


@pytest.mark.parametrize("status", ["UNREACHABLE", "UNKNOWN"])
def test_reachability_refusal_is_not_a_creative_repair(load_module, status):
    llm = FakeDirectorLLM([script_data()])
    with pytest.raises(AgentError, match="REACHABILITY_REFUSED"):
        load_module("planner_v2").VisualPlanner(llm).plan(UserRequest(text=REQUEST), demo_registry(), reachable(status))
    assert len(llm.calls) == 1


def test_registry_revision_updates_schema_without_prompt_changes(load_module):
    module = load_module("planner_v2")
    registry = demo_registry().model_copy(update={"revision": "mock-demo-new"})
    data = script_data()
    data["registry_revision"] = registry.revision
    llm = FakeDirectorLLM([data])
    result = module.VisualPlanner(llm).plan(UserRequest(text=REQUEST), registry, reachable())
    assert result.registry_revision == "mock-demo-new"
    assert llm.calls[0]["schema"]["properties"]["registry_revision"]["enum"] == [registry.revision]


def test_existing_provider_adapter_accepts_visual_prompt_and_strict_schema(load_module):
    module = load_module("planner_v2")
    requests = []
    data = script_data()
    # Strict nullable fields are explicit on the provider wire, not guessed JSON.
    data["shots"][0]["target_trajectory"]["tolerance"]["distance_tolerance"] = None
    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(status="completed", output=[], output_text=json.dumps({"shot_script": data}))
    llm = OpenAIDirectorLLM(SimpleNamespace(responses=SimpleNamespace(create=create)),
                            model="test-only", instructions=module.VISUAL_DIRECTOR_INSTRUCTIONS)
    result = module.VisualPlanner(llm).plan(UserRequest(text=REQUEST), demo_registry(), reachable())
    assert result.shots[0].target_trajectory.duration == 5.0
    assert requests[0]["text"]["format"]["strict"] is True
    assert requests[0]["instructions"] == module.VISUAL_DIRECTOR_INSTRUCTIONS
    assert "mock_record_fixture" not in requests[0]["instructions"]
