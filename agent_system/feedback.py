"""Agent 3: gated deterministic V0 composition and V2 trajectory feedback."""

from decimal import Decimal

from pydantic import Field, ValidationError

from .errors import AgentError
from .models import (AgentDecision, CompositionTarget, ContractModel, CorrectionCapability,
                     CorrectionComponent, CorrectionIntent, Observation, TargetTrajectory,
                     TrajectoryCorrectionIntent)
from .observations import ObservationGateResult, gate_observation
from .state import AgentState


class FeedbackConfig(ContractModel):
    # Explicit caller configuration. No real hardware policy or implicit defaults.
    max_corrections: int = Field(ge=0)
    max_age_seconds: float = Field(ge=0.0, allow_inf_nan=False)


def _decide_feedback(
    observation: Observation,
    target: CompositionTarget | dict,
    state: AgentState,
    config: FeedbackConfig,
) -> AgentDecision:
    """Private pure decision path; called only after the existing Gate accepts."""
    if observation.no_target:
        return AgentDecision(decision="PAUSE", reason="target_lost")
    try:
        payload = target.model_dump() if isinstance(target, CompositionTarget) else target
        target = CompositionTarget.model_validate(payload)
    except ValidationError:
        return AgentDecision(decision="PAUSE", reason="invalid_composition_target")

    # Decimal representations preserve inclusive decimal tolerance boundaries,
    # without adding a hidden epsilon or widening the composition tolerance.
    box = observation.bbox
    x1, y1, x2, y2 = (Decimal(str(value)) for value in (box.x1, box.y1, box.x2, box.y2))
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    _bbox_width, _bbox_height = x2 - x1, y2 - y1
    # Width and height have no decision role in the center-only V0 Contract.
    desired_x, desired_y = Decimal(str(target.target_center_x)), Decimal(str(target.target_center_y))
    excess_x = abs(center_x - desired_x) - Decimal(str(target.tolerance_x))
    excess_y = abs(center_y - desired_y) - Decimal(str(target.tolerance_y))
    if excess_x <= 0 and excess_y <= 0:
        return AgentDecision(decision="CONTINUE", reason="within_tolerance")
    if state.correction_count >= config.max_corrections:
        return AgentDecision(decision="PAUSE", reason="correction_budget_exhausted")

    # One CorrectionIntent expresses one dimension. Fix greatest excess first;
    # equal excesses choose horizontal. No full-plan regeneration or hardware mapping.
    horizontal = excess_x >= excess_y
    dimension = "horizontal" if horizontal else "vertical"
    desired = target.target_center_x if horizontal else target.target_center_y
    current, target_value = (center_x, desired_x) if horizontal else (center_y, desired_y)
    axis = "x" if horizontal else "y"
    direction = "increase" if current < target_value else "decrease"
    intent = CorrectionIntent(
        shot_id=state.shot_id,
        plan_id=state.plan_id,
        correction_dimension=dimension,
        target=desired,
        reason=f"subject_{axis}_should_{direction}",
    )
    return AgentDecision(decision="ADJUST", reason=f"{dimension}_offset", correction_intent=intent)


def evaluate_feedback(
    observation: Observation | dict,
    target: CompositionTarget | dict,
    state: AgentState,
    config: FeedbackConfig,
    *,
    now: float,
) -> tuple[ObservationGateResult, AgentDecision | None, AgentState]:
    """Return (gate, optional decision, new state). Caller retains the returned state.

    Gate rejection returns no AgentDecision. Issued ADJUST consumes one budget unit
    through AgentState; PAUSE proposes a pause and does not confirm device lifecycle.
    """
    gate = gate_observation(observation, state, now=now, max_age_seconds=config.max_age_seconds)
    if not gate.accepted:
        return gate, None, state
    decision = _decide_feedback(gate.observation, target, state, config)
    updated = state.record_correction(decision) if decision.decision == "ADJUST" else state
    return gate, decision, updated


def _decide_trajectory_feedback(
    trajectory: TargetTrajectory,
    trajectory_time: float,
    observation: Observation,
    state: AgentState,
    config: FeedbackConfig,
    correction_capability: CorrectionCapability,
) -> AgentDecision:
    """Pure V2 decision path after admission. No clocks, motion or reachability."""
    trajectory = TargetTrajectory.model_validate(trajectory.model_dump())
    correction_capability = CorrectionCapability.model_validate(correction_capability.model_dump())
    tolerance = trajectory.tolerance
    if trajectory.keyframes[0].frame_state.distance is not None and tolerance.distance_tolerance is None:
        raise AgentError("INVALID_PLAN", "Distance target requires distance_tolerance for feedback")
    expected = trajectory.evaluate(trajectory_time)
    measured = observation.to_frame_state()
    if measured is None:
        return AgentDecision(decision="PAUSE", reason="target_lost")
    if expected.distance is not None and measured.distance is None:
        return AgentDecision(decision="PAUSE", reason="required_measurement_missing")

    # Stable contract order only, never priority or cross-unit severity ranking.
    dimensions = [
        ("CENTER_X", "center_x", tolerance.center_x_tolerance),
        ("CENTER_Y", "center_y", tolerance.center_y_tolerance),
        ("SUBJECT_HEIGHT_RATIO", "subject_height_ratio", tolerance.height_ratio_tolerance),
    ]
    if expected.distance is not None:
        # Comparison requires the same canonical internal unit from both adapters.
        dimensions.append(("DISTANCE", "distance", tolerance.distance_tolerance))
    components = []
    for dimension, field, allowed_error in dimensions:
        target_value, observed_value = getattr(expected, field), getattr(measured, field)
        error = Decimal(str(observed_value)) - Decimal(str(target_value))
        if abs(error) > Decimal(str(allowed_error)):
            components.append(CorrectionComponent(dimension=dimension, target_value=target_value,
                                                  observed_value=observed_value, error=float(error)))
    if not components:
        return AgentDecision(decision="CONTINUE", reason="within_trajectory_tolerance")
    if any(component.dimension not in correction_capability.allowed_dimensions for component in components):
        return AgentDecision(decision="PAUSE", reason="unsupported_correction")
    if state.correction_count >= config.max_corrections:
        return AgentDecision(decision="PAUSE", reason="correction_budget_exhausted")
    intent = TrajectoryCorrectionIntent(shot_id=state.shot_id, plan_id=state.plan_id,
                                       trajectory_time=trajectory_time, reason="trajectory_offset", components=components)
    return AgentDecision(decision="ADJUST", reason="trajectory_offset", correction_intent=intent)


def evaluate_feedback_v2(
    trajectory: TargetTrajectory,
    trajectory_time: float,
    observation: Observation | dict,
    state: AgentState,
    config: FeedbackConfig,
    correction_capability: CorrectionCapability,
    *,
    trajectory_plan_id: str,
    now: float,
) -> tuple[ObservationGateResult, AgentDecision | None, AgentState]:
    """Consume resolved observation-relative trajectory_time, never derive it.

    trajectory_plan_id must come from the plan associated with this trajectory.
    V2 requires Observation.plan_id; legacy missing IDs remain valid only in V0.
    Explicit now is used solely for Gate freshness, not trajectory sampling.
    Distance comparison requires the same canonical internal unit. Pause/resume
    policy remains external. PAUSE proposes a pause without changing lifecycle.
    """
    gate = gate_observation(observation, state, now=now, max_age_seconds=config.max_age_seconds,
                            require_plan_id=True)
    if not gate.accepted:
        return gate, None, state
    if trajectory_plan_id != state.plan_id:
        return ObservationGateResult(False, "WRONG_PLAN", "Trajectory belongs to a different execution plan"), None, state
    decision = _decide_trajectory_feedback(trajectory, trajectory_time, gate.observation, state, config, correction_capability)
    updated = state.record_correction(decision) if decision.decision == "ADJUST" else state
    return gate, decision, updated
