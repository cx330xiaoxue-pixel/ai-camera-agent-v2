"""MOCK ONLY: explicit lifecycle simulation, no devices, networking or sleeps."""

from .errors import AgentError
from .models import CorrectionCapability, ExecutionEvent, Observation, TargetTrajectory
from .reachability import ReachabilityResult
from .validation import validate_action, validate_plan


class MockReachabilityValidator:
    """MOCK ONLY: return a fixture outcome, never infer physical reachability."""

    def __init__(self, result: ReachabilityResult):
        self.result = ReachabilityResult.model_validate(result.model_dump())

    def validate(self, trajectory: TargetTrajectory) -> ReachabilityResult:
        payload = trajectory.model_dump() if isinstance(trajectory, TargetTrajectory) else trajectory
        TargetTrajectory.model_validate(payload)
        return self.result


class MockExecutor:
    def __init__(self, registry):
        self.registry = registry.model_copy(deep=True)
        self._submitted = {}
        self._events = []
        self._statuses = {}

    @property
    def records(self):
        return tuple(self._events)

    @property
    def submitted(self):
        return {key: value.model_copy(deep=True) for key, value in self._submitted.items()}

    def submit_plan(self, plan):
        validated = validate_plan(plan, self.registry)
        return self._accept(validated, None)

    def submit_action(self, action):
        validated = validate_action(action, self.registry)
        return self._accept(validated, validated.action_id)

    def _accept(self, validated, action_id):
        key = (validated.plan_id, action_id)
        if key in self._statuses:
            raise AgentError("INVALID_STATE_TRANSITION", "Submission ID already exists")
        self._submitted[key] = validated.model_copy(deep=True)
        return self._record(key, "accepted", "MOCK ONLY: validated submission accepted")

    def _record(self, key, status, reason):
        event = ExecutionEvent(plan_id=key[0], action_id=key[1], status=status, reason=reason)
        self._statuses[key] = status
        self._events.append(event)
        return event

    def _advance(self, key, target, reason):
        allowed = {"accepted": {"running", "failed"}, "running": {"completed", "failed"}}
        current = self._statuses.get(key)
        if target not in allowed.get(current, set()):
            raise AgentError("INVALID_STATE_TRANSITION", f"Mock execution cannot move from {current} to {target}")
        return self._record(key, target, reason)

    def start(self, plan_id, *, action_id=None):
        return self._advance((plan_id, action_id), "running", "MOCK ONLY: execution explicitly started")

    def complete(self, plan_id, *, action_id=None):
        return self._advance((plan_id, action_id), "completed", "MOCK ONLY: execution explicitly completed")

    def fail(self, plan_id, *, reason, action_id=None):
        return self._advance((plan_id, action_id), "failed", reason)


# MOCK TEST CONFIG, not a real App/Vision freshness requirement.
MOCK_FRESHNESS_SECONDS = 1.0


def mock_correction_capabilities():
    """MOCK ONLY frame permissions, not declarations of real hardware ability."""
    visual = ["CENTER_X", "CENTER_Y", "SUBJECT_HEIGHT_RATIO"]
    return {
        "VISUAL_ONLY": CorrectionCapability(allowed_dimensions=visual),
        "ALL": CorrectionCapability(allowed_dimensions=visual + ["DISTANCE"]),
        "HORIZONTAL_ONLY": CorrectionCapability(allowed_dimensions=["CENTER_X"]),
        "NONE": CorrectionCapability(allowed_dimensions=[]),
    }


def mock_observations(*, shot_id="s1", now=100.0):
    """MOCK ONLY normalized single-person fixtures; no detection implementation."""
    boxes = {
        "NORMAL": {"x1": 0.35, "y1": 0.2, "x2": 0.65, "y2": 0.8},
        "LEFT_OFFSET": {"x1": 0.05, "y1": 0.2, "x2": 0.35, "y2": 0.8},
        "RIGHT_OFFSET": {"x1": 0.65, "y1": 0.2, "x2": 0.95, "y2": 0.8},
        "NEAR_EDGE": {"x1": 0.01, "y1": 0.2, "x2": 0.21, "y2": 0.8},
        "LOST": None,
        "STALE": {"x1": 0.35, "y1": 0.2, "x2": 0.65, "y2": 0.8},
        "WRONG_SHOT": {"x1": 0.35, "y1": 0.2, "x2": 0.65, "y2": 0.8},
    }
    return {
        name: Observation(
            shot_id=f"{shot_id}-other" if name == "WRONG_SHOT" else shot_id,
            timestamp=now - MOCK_FRESHNESS_SECONDS - 1.0 if name == "STALE" else now,
            bbox=box,
        )
        for name, box in boxes.items()
    }
