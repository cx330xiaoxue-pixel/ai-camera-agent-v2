"""Agent 2 V0: registry-constrained candidates, local validation, no execution."""

from copy import deepcopy
from uuid import uuid4

from pydantic import ValidationError

from .errors import AgentError
from .llm import ToolCallCandidate, ToolCallingLLM
from .models import CameraMotionIntent, CorrectionIntent, Shot, ShotExecutionPlan, StructuredAction
from .registry import ActionRegistry
from .state import AgentState
from .validation import validate_action, validate_execution_relation, validate_plan


def _strict_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            if schema.get("additionalProperties") is not False or set(schema.get("required", [])) != set(schema.get("properties", {})):
                return False
        return all(_strict_objects(value) for value in schema.values())
    if isinstance(schema, list):
        return all(_strict_objects(value) for value in schema)
    return True


def build_tool_definitions(registry: ActionRegistry, source: str, *, correction_dimension: str | None = None) -> list[dict]:
    if source not in ("INITIAL", "CORRECTION"):
        raise AgentError("SCHEMA_ERROR", "Unknown action usage")
    tools = []
    for entry in registry.actions.values():
        if source not in entry.allowed_usage:
            continue
        if source == "CORRECTION":
            if not entry.correction_allowed:
                continue
            if correction_dimension is not None and correction_dimension not in entry.correction_dimensions:
                continue
        schema = deepcopy(entry.parameter_schema)
        tools.append({"type": "function", "name": entry.action_name, "description": entry.description,
                      "parameters": schema, "strict": schema.get("type") == "object" and _strict_objects(schema)})
    return tools


class ActionPlanner:
    def __init__(self, llm: ToolCallingLLM):
        self.llm = llm

    def plan_motion(self, intent: CameraMotionIntent, context: AgentState, registry: ActionRegistry) -> StructuredAction:
        intent = CameraMotionIntent.model_validate(intent.model_dump())
        return self._plan(intent.model_dump(), context, registry, "INITIAL")

    def plan_correction(self, intent: CorrectionIntent, context: AgentState, registry: ActionRegistry) -> StructuredAction:
        intent = CorrectionIntent.model_validate(intent.model_dump())
        if intent.shot_id != context.shot_id or intent.plan_id != context.plan_id:
            raise AgentError("INVALID_PLAN", "Correction context differs from current shot/plan")
        semantic = intent.model_dump(exclude={"shot_id", "plan_id", "target_action_id"})
        return self._plan(semantic, context, registry, "CORRECTION", dimension=intent.correction_dimension)

    def _plan(self, semantic, context, registry, source, dimension=None):
        snapshot = registry.model_copy(deep=True)
        if context.registry_revision != snapshot.revision:
            raise AgentError("REGISTRY_MISMATCH", "Execution context differs from registry revision")
        tools = build_tool_definitions(snapshot, source, correction_dimension=dimension)
        unsupported = "UNSUPPORTED_CORRECTION" if source == "CORRECTION" else "CAPABILITY_VIOLATION"
        if not tools:
            raise AgentError(unsupported, "No permitted tool declares the requested capability")
        exposed = {tool["name"] for tool in tools}
        intent_context = {"source": source, "intent": semantic}
        repair_error = None
        action_id = str(uuid4())
        for attempt in range(2):
            raw = self.llm.select_tool(deepcopy(intent_context), deepcopy(tools), repair_error=deepcopy(repair_error))
            if raw is None:
                raise AgentError(unsupported, "No exact tool can satisfy the requested intent")
            try:
                payload = raw.model_dump() if isinstance(raw, ToolCallCandidate) else raw
                candidate = ToolCallCandidate.model_validate(payload)
            except ValidationError as exc:
                raise AgentError("SCHEMA_ERROR", f"Invalid tool-call candidate: {exc}") from exc
            if candidate.tool_name not in snapshot.actions:
                raise AgentError("UNKNOWN_ACTION", f"Tool {candidate.tool_name!r} is not registered")
            if candidate.tool_name not in exposed:
                raise AgentError(unsupported, "Selected tool was not exposed for this intent")
            if repair_error is not None and candidate.tool_name != repair_error["candidate"]["tool_name"]:
                raise AgentError("CAPABILITY_VIOLATION", "Parameter repair cannot change the selected action")
            action = StructuredAction(action_id=action_id, shot_id=context.shot_id, plan_id=context.plan_id,
                                      source=source, action_name=candidate.tool_name, parameters=candidate.arguments,
                                      registry_revision=snapshot.revision)
            try:
                return validate_action(action, snapshot)
            except AgentError as exc:
                if exc.code != "INVALID_PARAMETERS" or attempt == 1:
                    raise
                repair_error = {"code": exc.code, "reason": exc.reason, "context": exc.context,
                                "candidate": candidate.model_dump()}
                tools = [tool for tool in tools if tool["name"] == candidate.tool_name]

    def plan_shot(self, shot: Shot, context: AgentState, registry: ActionRegistry) -> ShotExecutionPlan:
        shot = Shot.model_validate(shot.model_dump())
        if shot.shot_id != context.shot_id:
            raise AgentError("INVALID_PLAN", "Shot does not match the execution context")
        snapshot = registry.model_copy(deep=True)
        # Validate relation/context before spending any model calls; no plan is executed.
        validate_execution_relation(shot.execution_relation)
        actions = [self.plan_motion(intent, context, snapshot) for intent in shot.camera_motions]
        plan = ShotExecutionPlan(plan_id=context.plan_id, shot_id=shot.shot_id, registry_revision=snapshot.revision,
                                 actions=actions, execution_relation=shot.execution_relation)
        return validate_plan(plan, snapshot)
