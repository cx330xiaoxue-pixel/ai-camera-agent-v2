"""Visual planner only: screen-space targets, never physical movement parameters."""

from pydantic import Field, model_validator

from .errors import AgentError
from .llm import DirectorLLMAdapter
from .models import ContractModel, PositiveTime, ShotScript, UserRequest, VISUAL_SHOT_SCRIPT_VERSION
from .motion_compiler import require_reachable
from .registry import ActionRegistry, project_capability
from .validation import validate_visual_shot_script


VISUAL_DIRECTOR_INSTRUCTIONS = (
    "Plan a short visual ShotScript from the supplied filming request using the supplied schema. "
    "Only output shot goals, optional subject action, and time-varying screen-space target keyframes. "
    "For a fixed object subject_action is null: the phone moves, not the object. "
    "Image coordinates are normalized [0,1], x rightward and y downward; height ratio is subject image height. "
    "Every frame must fit: center_y-height/2 >= 0 and center_y+height/2 <= 1. "
    "Keyframes start at time zero and increase strictly, with linear interpolation. "
    "Preserve explicitly requested start/end height ratios and total duration; expected_duration equals final time. "
    "Use few shots and keyframes. For a single continuous visual change, prefer one Shot and two keyframes. "
    "Generate measurable targets and tolerances; do not invent physical distance when not requested. "
    "If distance targets are not enabled, every distance and distance_tolerance is null. "
    "Do not output hardware functions, motor commands, rail displacement, wheel speed, beam/gimbal angles or PWM. "
    "Visual schema validity does not guarantee reachability; that is checked by a separate external gate. "
    "Never claim physical feasibility from the illustrative capability. "
    "If the request cannot be represented within supplied constraints return shot_script=null. "
    "For repair_error regenerate the whole script once, preserving the user's goal. "
    "Return only the final structured result, never internal reasoning."
)


class VisualPlannerConfig(ContractModel):
    """MVP PLANNING CONFIG, not hardware limits or final product policy."""

    min_shots: int = Field(default=1, ge=1)
    max_shots: int = Field(default=4, ge=1)
    max_keyframes: int = Field(default=4, ge=2)
    max_shot_duration: PositiveTime = 10.0
    allow_distance_targets: bool = False  # PENDING TEAM CONTRACT; opt-in fixture only.

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.min_shots > self.max_shots:
            raise ValueError("min_shots must not exceed max_shots")
        return self


def visual_capability(registry, config):
    projection = project_capability(registry)
    return {
        "registry_revision": projection.registry_revision,
        "declared_motion_semantics": projection.motions,
        "execution_relations": projection.execution_relations,
        "expressible_visual_dimensions": ["CENTER_X", "CENTER_Y", "SUBJECT_HEIGHT_RATIO"],
        "distance_targets_enabled": config.allow_distance_targets,
        "reachability": "Separate external verdict required; visual expressibility is not physical capability",
    }


def visual_director_schema(capability, config):
    schema = ShotScript.model_json_schema()
    schema["properties"]["schema_version"]["enum"] = [VISUAL_SHOT_SCRIPT_VERSION]
    schema["properties"]["registry_revision"]["enum"] = [capability["registry_revision"]]
    schema["properties"]["shots"].update(minItems=config.min_shots, maxItems=config.max_shots)
    shot = schema["$defs"]["Shot"]
    for name in ("composition_target", "camera_motions"):
        shot["properties"].pop(name)
    shot["properties"]["target_trajectory"] = {"$ref": "#/$defs/TargetTrajectory"}
    shot["required"].append("target_trajectory")
    shot["properties"]["expected_duration"]["maximum"] = config.max_shot_duration
    shot["properties"]["execution_relation"]["enum"] = capability["execution_relations"]
    schema["$defs"]["TargetTrajectory"]["properties"]["keyframes"]["maxItems"] = config.max_keyframes
    schema["$defs"]["TargetTrajectoryKeyframe"]["properties"]["time_offset"]["maximum"] = config.max_shot_duration
    if not config.allow_distance_targets:
        schema["$defs"]["FrameState"]["properties"]["distance"] = {"type": "null"}
        schema["$defs"]["TrajectoryTolerance"]["properties"]["distance_tolerance"] = {"type": "null"}
    for name in ("CompositionTarget", "CameraMotionIntent"):
        schema["$defs"].pop(name)
    return schema


class VisualPlanner:
    def __init__(self, llm: DirectorLLMAdapter, *, config: VisualPlannerConfig | None = None):
        self.llm = llm
        self.config = config or VisualPlannerConfig()

    def plan(self, request: UserRequest, registry: ActionRegistry, reachability) -> ShotScript:
        request = UserRequest.model_validate(request.model_dump())
        snapshot = ActionRegistry.model_validate(registry.model_dump())
        capability = visual_capability(snapshot, self.config)
        schema = visual_director_schema(capability, self.config)
        repair_error = None
        for attempt in range(2):
            candidate = self.llm.generate_script(
                request.model_dump(), capability, schema,
                planning_config=self.config.model_dump(), repair_error=repair_error,
            )
            if candidate is None:
                raise AgentError("CAPABILITY_VIOLATION", "Visual request is not supported; no substitution accepted")
            try:
                result = validate_visual_shot_script(candidate, capability, self.config)
            except AgentError as error:
                if attempt or error.code not in {"INVALID_PLAN", "CAPABILITY_VIOLATION"}:
                    raise
                repair_error = {"code": error.code, "reason": error.reason, "context": error.context}
                continue
            # An explicit refusal is not repaired by guessing a different mechanical route.
            for shot in result.shots:
                require_reachable(shot.target_trajectory, reachability)
            return result
        raise AssertionError("Unreachable visual repair state")
