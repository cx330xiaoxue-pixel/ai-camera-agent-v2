"""Admission gate only. No feedback decisions, corrections or state mutations."""

from dataclasses import dataclass
from math import isfinite

from pydantic import ValidationError

from .models import Observation
from .state import AgentState


@dataclass(frozen=True)
class ObservationGateResult:
    accepted: bool
    code: str
    reason: str
    observation: Observation | None = None


def gate_observation(observation, state: AgentState, *, now: float, max_age_seconds: float,
                     require_plan_id: bool = False) -> ObservationGateResult:
    """timestamp and now must use seconds from the same clock domain."""
    if not isfinite(now) or now < 0 or not isfinite(max_age_seconds) or max_age_seconds < 0:
        raise ValueError("Gate clock and freshness threshold must be finite nonnegative values")
    if state.status != "EXECUTING":
        return ObservationGateResult(False, "INACTIVE_STATE", "Feedback requires EXECUTING")
    try:
        payload = observation.model_dump() if isinstance(observation, Observation) else observation
        candidate = Observation.model_validate(payload)
    except ValidationError as exc:
        return ObservationGateResult(False, "INVALID_OBSERVATION", str(exc))
    if candidate.shot_id != state.shot_id:
        return ObservationGateResult(False, "WRONG_SHOT", "Observation belongs to a different shot")
    if require_plan_id and candidate.plan_id is None:
        return ObservationGateResult(False, "MISSING_PLAN", "Trajectory feedback requires an explicit observation plan_id")
    if candidate.plan_id is not None and candidate.plan_id != state.plan_id:
        return ObservationGateResult(False, "WRONG_PLAN", "Observation belongs to a different execution plan")
    age = now - candidate.timestamp
    if age < 0:
        return ObservationGateResult(False, "INVALID_OBSERVATION", "Observation timestamp is in the future")
    if age > max_age_seconds:
        return ObservationGateResult(False, "STALE", "Observation exceeds the configured freshness threshold")
    return ObservationGateResult(True, "ACCEPTED", "Fresh observation admitted", candidate)
