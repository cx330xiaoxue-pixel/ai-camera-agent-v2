"""Agent 1: constrained director planning, not action selection or execution."""

from pydantic import Field, model_validator

from .errors import AgentError
from .llm import DirectorLLMAdapter
from .models import ContractModel, Identifier, LEGACY_SHOT_SCRIPT_VERSION, PositiveTime, ShotScript, UserRequest
from .registry import ActionRegistry, project_capability
from .validation import validate_shot_script


class DirectorConfig(ContractModel):
    """MVP PLANNING CONFIG: adjustable demo bounds, not permanent product rules."""

    schema_version: Identifier = "0.1"
    min_shots: int = Field(default=1, ge=1)
    max_shots: int = Field(default=4, ge=1)
    max_shot_duration: PositiveTime = 10.0

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.min_shots > self.max_shots:
            raise ValueError("min_shots must not exceed max_shots")
        return self


def director_schema(capability, config) -> dict:
    if config.schema_version != LEGACY_SHOT_SCRIPT_VERSION:
        raise AgentError("SCHEMA_ERROR", "V0 Director does not plan visual trajectory scripts")
    schema = ShotScript.model_json_schema()
    schema["properties"]["schema_version"]["enum"] = [config.schema_version]
    schema["properties"]["registry_revision"]["enum"] = [capability.registry_revision]
    schema["properties"]["shots"].update(minItems=config.min_shots, maxItems=config.max_shots)
    schema["$defs"]["CameraMotionIntent"]["properties"]["motion"]["enum"] = list(capability.motions)
    shot_fields = schema["$defs"]["Shot"]["properties"]
    # Keep the historical provider wire schema while Shot supports both paths.
    shot_fields.pop("target_trajectory")
    for name in ("subject_action", "composition_target"):
        shot_fields[name] = next(part for part in shot_fields[name]["anyOf"] if part.get("type") != "null")
    shot_fields["camera_motions"]["minItems"] = 1
    schema["$defs"]["Shot"]["required"].extend(["subject_action", "composition_target", "camera_motions"])
    for name in ("FrameState", "TrajectoryTolerance", "TargetTrajectoryKeyframe", "TargetTrajectory"):
        schema["$defs"].pop(name)
    shot_fields["execution_relation"]["enum"] = capability.execution_relations
    shot_fields["expected_duration"]["maximum"] = config.max_shot_duration
    return schema


class Director:
    def __init__(self, llm: DirectorLLMAdapter, *, config: DirectorConfig | None = None):
        self.llm = llm
        self.config = config or DirectorConfig()

    def plan(self, request: UserRequest, registry: ActionRegistry) -> ShotScript:
        request = UserRequest.model_validate(request.model_dump())
        snapshot = ActionRegistry.model_validate(registry.model_dump())
        capability = project_capability(snapshot)
        if not capability.motions:
            raise AgentError("CAPABILITY_VIOLATION", "No director motion capability is declared")
        schema = director_schema(capability, self.config)
        repair_error = None
        for attempt in range(2):
            candidate = self.llm.generate_script(
                request.model_dump(), capability.model_dump(), schema,
                planning_config=self.config.model_dump(), repair_error=repair_error,
            )
            if candidate is None:
                raise AgentError("CAPABILITY_VIOLATION", "Requested filming intent is not supported; no alternative accepted")
            try:
                return validate_shot_script(candidate, capability, self.config)
            except AgentError as exc:
                if attempt or exc.code not in {"INVALID_PLAN", "CAPABILITY_VIOLATION"}:
                    raise
                repair_error = {"code": exc.code, "reason": exc.reason, "context": exc.context}
        raise AssertionError("Unreachable director repair state")
