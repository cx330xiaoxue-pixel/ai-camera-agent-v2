"""Contract compilation only: no visual-to-mechanical mapping."""

import pytest

from agent_system.errors import AgentError
from agent_system.models import TargetTrajectory
from agent_system.mocks import MockExecutor, MockReachabilityValidator
from agent_system.reachability import ReachabilityResult
from agent_system.state import AgentState
from agent_system.validation import validate_plan
from test_visual_contract import captain_trajectory_data


def setup_compiler(load_module, status="REACHABLE"):
    module = load_module("motion_compiler")
    trajectory = TargetTrajectory.model_validate(captain_trajectory_data())
    registry = module.demo_registry()
    compiler = module.MockMotionCompiler(trajectory, fixture_id="captain-fixed-object")
    context = AgentState(plan_id="demo-plan", shot_id="object-shot", registry_revision=registry.revision, status="PLANNED")
    reachability = MockReachabilityValidator(ReachabilityResult(status=status, reason="MOCK ONLY fixture verdict"))
    return compiler, trajectory, registry, context, reachability


def test_reachable_compiles_valid_plan_without_executing(load_module):
    compiler, trajectory, registry, context, reachability = setup_compiler(load_module)
    plan = compiler.compile(trajectory, context, registry, reachability)
    assert validate_plan(plan, registry) == plan
    assert plan.shot_id == context.shot_id and plan.plan_id == context.plan_id
    assert plan.actions[0].source == "INITIAL"
    assert plan.actions[0].action_name == "mock_record_fixture"
    assert plan.actions[0].parameters == {"fixture_id": "captain-fixed-object", "duration": 5.0}
    assert context.status == "PLANNED"


@pytest.mark.parametrize("status", ["UNREACHABLE", "UNKNOWN"])
def test_refuses_before_execution(load_module, status):
    compiler, trajectory, registry, context, reachability = setup_compiler(load_module, status)
    executor = MockExecutor(registry)
    with pytest.raises(AgentError) as error:
        compiler.compile(trajectory, context, registry, reachability)
    assert error.value.code == "REACHABILITY_REFUSED"
    assert error.value.context["status"] == status
    assert executor.records == ()


def test_mock_compiler_only_accepts_registered_fixture(load_module):
    compiler, trajectory, registry, context, reachability = setup_compiler(load_module)
    data = trajectory.model_dump()
    data["keyframes"][0]["frame_state"]["center_x"] = 0.4
    with pytest.raises(AgentError, match="UNSUPPORTED_TRAJECTORY"):
        compiler.compile(TargetTrajectory.model_validate(data), context, registry, reachability)


def test_revision_mismatch_and_invalid_recipe_are_rejected(load_module):
    compiler, trajectory, registry, context, reachability = setup_compiler(load_module)
    with pytest.raises(AgentError, match="REGISTRY_MISMATCH"):
        compiler.compile(trajectory, context.model_copy(update={"registry_revision": "old"}), registry, reachability)
    data = registry.model_dump()
    data["actions"].pop("mock_record_fixture")
    with pytest.raises(AgentError, match="UNKNOWN_ACTION"):
        compiler.compile(trajectory, context, type(registry).model_validate(data), reachability)


def test_context_must_be_preexecution_and_ids_are_unique(load_module):
    compiler, trajectory, registry, context, reachability = setup_compiler(load_module)
    with pytest.raises(AgentError, match="INVALID_STATE_TRANSITION"):
        compiler.compile(trajectory, context.model_copy(update={"status": "EXECUTING"}), registry, reachability)
    first = compiler.compile(trajectory, context, registry, reachability)
    second = compiler.compile(trajectory, context, registry, reachability)
    assert first.actions[0].action_id != second.actions[0].action_id
