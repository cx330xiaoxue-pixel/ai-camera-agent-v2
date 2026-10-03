"""Fixed Agent contracts. Dynamic action parameters belong to the Registry."""

from decimal import Decimal
from math import isfinite
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import AgentError

Normalized = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositiveTime = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1)]
ActionSource = Literal["INITIAL", "CORRECTION"]
ExecutionRelation = Literal["SEQUENTIAL", "PARALLEL"]
LEGACY_SHOT_SCRIPT_VERSION = "0.1"
VISUAL_SHOT_SCRIPT_VERSION = "0.2"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class UserRequest(ContractModel):
    text: Identifier


class CompositionTarget(ContractModel):
    """Legacy V0 center-only target; no implicit size or trajectory conversion."""

    target_center_x: Normalized
    target_center_y: Normalized
    tolerance_x: Normalized
    tolerance_y: Normalized


class FrameState(ContractModel):
    """Shared visual state, not a hardware pose. Distance unit is external."""

    center_x: Normalized
    center_y: Normalized
    subject_height_ratio: Annotated[float, Field(gt=0.0, le=1.0, allow_inf_nan=False)]
    distance: Annotated[float, Field(gt=0.0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def valid_vertical_extent(self):
        # Use the stored float domain: re-encoding independently rounded center
        # and height as exact decimals can falsely reject a legal edge bbox.
        half_height = self.subject_height_ratio / 2
        if self.center_y - half_height < 0 or self.center_y + half_height > 1:
            raise ValueError("Subject height must fit the normalized frame; coordinates are not clamped")
        return self


class TrajectoryTolerance(ContractModel):
    center_x_tolerance: Normalized
    center_y_tolerance: Normalized
    height_ratio_tolerance: Normalized
    # Physical unit follows distance; meaningful only for a distance target.
    distance_tolerance: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None = None


class TargetTrajectoryKeyframe(ContractModel):
    # Shot-relative seconds. Execution clock alignment is a later migration.
    time_offset: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    frame_state: FrameState


class TargetTrajectory(ContractModel):
    """V1 image-space contract. Interpolation is always piecewise LINEAR.

    Schema validity makes no statement about physical reachability.
    """

    keyframes: list[TargetTrajectoryKeyframe] = Field(min_length=2)
    tolerance: TrajectoryTolerance

    @model_validator(mode="after")
    def ordered_times_and_consistent_distance(self):
        if self.keyframes[0].time_offset != 0.0:
            raise ValueError("First keyframe time_offset must be zero")
        if any(right.time_offset <= left.time_offset for left, right in zip(self.keyframes, self.keyframes[1:])):
            raise ValueError("Keyframe times must be strictly increasing")
        has_distance = [keyframe.frame_state.distance is not None for keyframe in self.keyframes]
        if any(has_distance) and not all(has_distance):
            raise ValueError("Keyframe distance targets must be all null or all present")
        return self

    @property
    def duration(self) -> float:
        return self.keyframes[-1].time_offset

    def evaluate(self, t: float) -> FrameState:
        """Sample only within [0, duration]; never clamp or extrapolate."""
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not isfinite(t) or not 0 <= t <= self.duration:
            raise AgentError("INVALID_TRAJECTORY_TIME", "Sampling time must be finite and within the trajectory duration")
        for keyframe in self.keyframes:
            if t == keyframe.time_offset:
                return keyframe.frame_state
        for left, right in zip(self.keyframes, self.keyframes[1:]):
            if left.time_offset < t < right.time_offset:
                weight = (Decimal(str(t)) - Decimal(str(left.time_offset))) / (Decimal(str(right.time_offset)) - Decimal(str(left.time_offset)))
                values = {}
                for name in FrameState.model_fields:
                    start, end = getattr(left.frame_state, name), getattr(right.frame_state, name)
                    values[name] = None if start is None else float(Decimal(str(start)) * (1 - weight) + Decimal(str(end)) * weight)
                return FrameState(**values)
        raise AgentError("INVALID_TRAJECTORY_TIME", "No trajectory segment contains the sampling time")


class CameraMotionIntent(ContractModel):
    motion: Identifier
    tempo: str | None = None
    timing_requirement: str | None = None


class Shot(ContractModel):
    shot_id: Identifier
    shot_goal: Identifier
    subject_action: Identifier | None = None
    composition_target: CompositionTarget | None = None
    camera_motions: list[CameraMotionIntent] = Field(default_factory=list)
    # Authoritative for the visual path; legacy fields are retained for compatibility.
    target_trajectory: TargetTrajectory | None = None
    execution_relation: ExecutionRelation = "SEQUENTIAL"
    expected_duration: PositiveTime
    transition: str | None = None

    @model_validator(mode="after")
    def valid_target_path(self):
        if self.target_trajectory is None:
            if self.composition_target is None or not self.camera_motions or self.subject_action is None:
                raise ValueError("V0 Shot requires composition_target, camera_motions and subject_action")
        elif self.expected_duration != self.target_trajectory.duration:
            raise ValueError("Shot expected_duration must equal target trajectory duration")
        return self


class ShotScript(ContractModel):
    schema_version: Identifier
    registry_revision: Identifier
    overall_goal: Identifier
    shots: list[Shot] = Field(min_length=1)

    @model_validator(mode="after")
    def version_matches_target_path(self):
        if self.schema_version == LEGACY_SHOT_SCRIPT_VERSION:
            if any(shot.target_trajectory is not None for shot in self.shots):
                raise ValueError("ShotScript 0.1 is the legacy static path, not a trajectory script")
        elif self.schema_version == VISUAL_SHOT_SCRIPT_VERSION:
            if any(shot.target_trajectory is None for shot in self.shots):
                raise ValueError("ShotScript 0.2 requires a target_trajectory for every Shot")
        else:
            raise ValueError("Unsupported ShotScript schema_version")
        return self


class StructuredAction(ContractModel):
    action_id: Identifier
    shot_id: Identifier
    plan_id: Identifier
    source: ActionSource
    action_name: Identifier
    parameters: dict[str, Any]
    registry_revision: Identifier


class ShotExecutionPlan(ContractModel):
    plan_id: Identifier
    shot_id: Identifier
    registry_revision: Identifier
    actions: list[StructuredAction] = Field(min_length=1)
    execution_relation: ExecutionRelation


class BoundingBox(ContractModel):
    x1: Normalized
    y1: Normalized
    x2: Normalized
    y2: Normalized

    @model_validator(mode="after")
    def ordered_corners(self):
        if self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError("bbox must satisfy x1 < x2 and y1 < y2; coordinates are not repaired")
        return self


class Observation(ContractModel):
    shot_id: Identifier
    # Optional for V0 compatibility; V2 Gate requires a plan-bound observation.
    plan_id: Identifier | None = None
    # Seconds on the same clock as the Gate's explicit `now`; not hardware time.
    timestamp: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    # Required null means NO_TARGET; a missing field or malformed box is invalid.
    bbox: BoundingBox | None
    # Optional physical measurement; no unit conversion or distance target policy.
    distance: Annotated[float, Field(gt=0.0, allow_inf_nan=False)] | None = None

    @property
    def no_target(self) -> bool:
        return self.bbox is None

    def to_frame_state(self) -> FrameState | None:
        """Derive visual values from the sole bbox source; lost means no state."""
        if self.no_target:
            return None
        x1, y1, x2, y2 = (Decimal(str(value)) for value in (self.bbox.x1, self.bbox.y1, self.bbox.x2, self.bbox.y2))
        return FrameState(center_x=float((x1 + x2) / 2), center_y=float((y1 + y2) / 2),
                          subject_height_ratio=float(y2 - y1), distance=self.distance)


class CorrectionIntent(ContractModel):
    shot_id: Identifier
    plan_id: Identifier
    correction_dimension: Literal["horizontal", "vertical", "height_ratio"]
    target: Normalized
    reason: Identifier
    target_action_id: Identifier | None = None


FrameDimension = Literal["CENTER_X", "CENTER_Y", "SUBJECT_HEIGHT_RATIO", "DISTANCE"]


class CorrectionCapability(ContractModel):
    """Explicit permitted frame dimensions, not hardware actions or reachability."""

    allowed_dimensions: list[FrameDimension]

    @model_validator(mode="after")
    def unique_dimensions(self):
        if len(set(self.allowed_dimensions)) != len(self.allowed_dimensions):
            raise ValueError("Correction capability dimensions must be unique")
        return self


class CorrectionComponent(ContractModel):
    dimension: FrameDimension
    target_value: Annotated[float, Field(allow_inf_nan=False)]
    observed_value: Annotated[float, Field(allow_inf_nan=False)]
    error: Annotated[float, Field(allow_inf_nan=False)]

    @model_validator(mode="after")
    def valid_values_and_signed_error(self):
        for value in (self.target_value, self.observed_value):
            if self.dimension == "DISTANCE":
                valid = value > 0
            elif self.dimension == "SUBJECT_HEIGHT_RATIO":
                valid = 0 < value <= 1
            else:
                valid = 0 <= value <= 1
            if not valid:
                raise ValueError("Correction value is outside the dimension's domain")
        expected_error = float(Decimal(str(self.observed_value)) - Decimal(str(self.target_value)))
        if self.error != expected_error:
            raise ValueError("Correction error must equal observed_value minus target_value")
        return self


class TrajectoryCorrectionIntent(ContractModel):
    """Restore frame targets at explicit trajectory time; no motion commands."""

    shot_id: Identifier
    plan_id: Identifier
    trajectory_time: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    reason: Identifier
    components: list[CorrectionComponent] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_component_dimensions(self):
        dimensions = [component.dimension for component in self.components]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("Correction components must use unique dimensions")
        return self


class AgentDecision(ContractModel):
    decision: Literal["CONTINUE", "ADJUST", "PAUSE"]
    reason: Identifier
    correction_intent: CorrectionIntent | TrajectoryCorrectionIntent | None = None

    @model_validator(mode="after")
    def correction_matches_decision(self):
        if self.decision == "ADJUST" and self.correction_intent is None:
            raise ValueError("ADJUST requires CorrectionIntent")
        if self.decision != "ADJUST" and self.correction_intent is not None:
            raise ValueError("Only ADJUST may carry CorrectionIntent")
        return self


class ExecutionEvent(ContractModel):
    """Mock/adapter lifecycle report, not a physical device protocol."""

    plan_id: Identifier
    action_id: Identifier | None = None
    status: Literal["accepted", "running", "completed", "failed"]
    reason: Identifier
