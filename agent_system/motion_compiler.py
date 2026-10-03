"""Execution contract only. Real image-to-mechanics mapping is WAITING_EXTERNAL."""

from typing import Protocol
from uuid import uuid4

from .errors import AgentError
from .models import ShotExecutionPlan, StructuredAction, TargetTrajectory
from .reachability import ReachabilityResult, ReachabilityValidator
from .registry import ActionRegistry, load_mock_registry
from .state import AgentState
from .validation import validate_plan


class MotionCompiler(Protocol):
    def compile(self, trajectory: TargetTrajectory, context: AgentState,
                registry: ActionRegistry, reachability: ReachabilityValidator) -> ShotExecutionPlan: ...


def require_reachable(trajectory, validator):
    result = ReachabilityResult.model_validate(validator.validate(trajectory).model_dump())
    if result.status != "REACHABLE":
        raise AgentError("REACHABILITY_REFUSED", "Trajectory is not approved for execution",
                         {"status": result.status, "reason": result.reason})
    return result


def demo_registry() -> ActionRegistry:
    """MOCK ONLY: add a recording operation, never a hardware movement function.

    The V0 registry file is untouched. This operation just names a fixture in a
    validated execution envelope; it cannot physically produce that trajectory.
    """
    data = load_mock_registry().model_dump()
    data["revision"] = "mock-v2-demo"
    data["actions"]["mock_record_fixture"] = {
        "action_name": "mock_record_fixture",
        "description": "MOCK ONLY: record a registered visual fixture; no mechanical execution or mapping.",
        "parameter_schema": {
            "type": "object", "properties": {
                "fixture_id": {"type": "string", "minLength": 1},
                "duration": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
            }, "required": ["fixture_id", "duration"], "additionalProperties": False,
        }, "allowed_usage": ["INITIAL"], "correction_allowed": False,
    }
    return ActionRegistry.model_validate(data)


class MockMotionCompiler:
    """MOCK ONLY: one explicitly registered fixture -> recording-only recipe.

    Registration is not a reachability guarantee. A reachability verdict is
    separately required on every compile, and the whole plan is locally validated.
    No Executor is called here, and no correction movements are generated.
    """

    def __init__(self, fixture: TargetTrajectory, *, fixture_id: str):
        self.fixture = TargetTrajectory.model_validate(fixture.model_dump())
        self.fixture_id = fixture_id

    def compile(self, trajectory, context, registry, reachability):
        trajectory = TargetTrajectory.model_validate(trajectory.model_dump())
        context = AgentState.model_validate(context.model_dump())
        registry = ActionRegistry.model_validate(registry.model_dump())
        if context.status != "PLANNED":
            raise AgentError("INVALID_STATE_TRANSITION", "Compilation requires a PLANNED context")
        if context.registry_revision != registry.revision:
            raise AgentError("REGISTRY_MISMATCH", "Compiler context does not match registry")
        require_reachable(trajectory, reachability)
        if trajectory != self.fixture:
            raise AgentError("UNSUPPORTED_TRAJECTORY", "MOCK ONLY compiler accepts only its registered fixture")
        action = StructuredAction(
            action_id=str(uuid4()), shot_id=context.shot_id, plan_id=context.plan_id,
            source="INITIAL", action_name="mock_record_fixture",
            parameters={"fixture_id": self.fixture_id, "duration": trajectory.duration},
            registry_revision=registry.revision,
        )
        return validate_plan(ShotExecutionPlan(
            plan_id=context.plan_id, shot_id=context.shot_id, registry_revision=registry.revision,
            actions=[action], execution_relation="SEQUENTIAL",
        ), registry)
