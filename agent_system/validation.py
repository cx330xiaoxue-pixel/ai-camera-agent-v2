"""Independent envelope, Registry and dynamic JSON Schema validation."""

import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .errors import AgentError
from .models import ShotExecutionPlan, ShotScript, StructuredAction
from .registry import ActionCapability, ActionRegistry


def validate_visual_shot_script(script, capability, config) -> ShotScript:
    """V2 visual business boundary; geometry is not physical reachability."""
    try:
        payload = script.model_dump() if isinstance(script, ShotScript) else script
        candidate = ShotScript.model_validate(payload)
    except ValidationError as exc:
        raise AgentError("SCHEMA_ERROR", "Invalid visual ShotScript contract") from exc
    if candidate.schema_version != "0.2":
        raise AgentError("SCHEMA_ERROR", "Visual planning requires schema 0.2")
    if candidate.registry_revision != capability["registry_revision"]:
        raise AgentError("REGISTRY_MISMATCH", "Visual plan revision differs from current context")
    if not config.min_shots <= len(candidate.shots) <= config.max_shots:
        raise AgentError("INVALID_PLAN", "Shot count exceeds MVP planning bounds")
    identifiers = [shot.shot_id for shot in candidate.shots]
    if len(set(identifiers)) != len(identifiers):
        raise AgentError("INVALID_PLAN", "Shot IDs must be unique")
    if not candidate.overall_goal.strip():
        raise AgentError("INVALID_PLAN", "Overall goal must be meaningful")
    for shot in candidate.shots:
        if not shot.shot_id.strip() or not shot.shot_goal.strip():
            raise AgentError("INVALID_PLAN", "Every Shot needs an ID and visual purpose")
        if shot.camera_motions or shot.composition_target is not None:
            raise AgentError("CAPABILITY_VIOLATION", "V2 planner must use authoritative visual trajectory only")
        if shot.execution_relation not in capability["execution_relations"]:
            raise AgentError("CAPABILITY_VIOLATION", "Requested Shot relationship is unsupported")
        trajectory = shot.target_trajectory
        if shot.expected_duration > config.max_shot_duration or len(trajectory.keyframes) > config.max_keyframes:
            raise AgentError("INVALID_PLAN", "Visual trajectory exceeds MVP duration/keyframe bounds")
        if trajectory.keyframes[0].frame_state.distance is not None:
            if not config.allow_distance_targets:
                raise AgentError("CAPABILITY_VIOLATION", "Distance planning is not enabled by this contract")
            if trajectory.tolerance.distance_tolerance is None:
                raise AgentError("INVALID_PLAN", "Distance target requires distance tolerance in canonical internal unit")
    return candidate


def validate_action(action: StructuredAction | dict[str, Any], registry: ActionRegistry) -> StructuredAction:
    try:
        payload = action.model_dump() if isinstance(action, StructuredAction) else action
        candidate = StructuredAction.model_validate(payload)
    except ValidationError as exc:
        raise AgentError("SCHEMA_ERROR", f"Invalid action envelope: {exc}") from exc
    if candidate.registry_revision != registry.revision:
        raise AgentError("REGISTRY_MISMATCH", "Action revision differs from the current registry", {
            "expected": registry.revision, "actual": candidate.registry_revision,
        })
    entry = registry.actions.get(candidate.action_name)
    if entry is None:
        raise AgentError("UNKNOWN_ACTION", f"Action {candidate.action_name!r} is not registered")
    if candidate.source == "CORRECTION" and not entry.correction_allowed:
        raise AgentError("UNSUPPORTED_CORRECTION", f"{candidate.action_name!r} is not permitted for correction")
    if candidate.source not in entry.allowed_usage:
        raise AgentError("CAPABILITY_VIOLATION", f"{candidate.action_name!r} does not allow {candidate.source}")
    try:
        # JSON Schema expects JSON data, not NaN, infinity or arbitrary Python objects.
        json.dumps(candidate.parameters, allow_nan=False)
        errors = list(Draft202012Validator(entry.parameter_schema).iter_errors(candidate.parameters))
    except (TypeError, ValueError) as exc:
        raise AgentError("INVALID_PARAMETERS", f"Parameters must be finite JSON data: {exc}") from exc
    if errors:
        error = errors[0]
        raise AgentError("INVALID_PARAMETERS", error.message, {
            "action_id": candidate.action_id, "path": list(error.absolute_path),
        })
    return candidate


def validate_execution_relation(relation: str) -> None:
    if relation != "SEQUENTIAL":
        raise AgentError("CAPABILITY_VIOLATION", "V0 registry declares no parallel execution capability")


def validate_shot_script(script, capability: ActionCapability, config) -> ShotScript:
    """Director schema and business boundary; never produces hardware actions."""
    try:
        payload = script.model_dump() if isinstance(script, ShotScript) else script
        candidate = ShotScript.model_validate(payload)
    except ValidationError as exc:
        raise AgentError("SCHEMA_ERROR", f"Invalid ShotScript: {exc}") from exc
    if candidate.schema_version != config.schema_version:
        raise AgentError("SCHEMA_ERROR", "Unsupported ShotScript schema_version")
    if candidate.registry_revision != capability.registry_revision:
        raise AgentError("REGISTRY_MISMATCH", "ShotScript revision differs from planning capability")
    if not config.min_shots <= len(candidate.shots) <= config.max_shots:
        raise AgentError("INVALID_PLAN", "Shot count exceeds MVP planning bounds")
    if not candidate.overall_goal.strip():
        raise AgentError("INVALID_PLAN", "overall_goal must describe the filming goal")
    seen = set()
    for shot in candidate.shots:
        if shot.shot_id in seen or not shot.shot_id.strip():
            raise AgentError("INVALID_PLAN", "shot_id must be nonblank and unique")
        seen.add(shot.shot_id)
        if not shot.shot_goal.strip() or not shot.subject_action.strip():
            raise AgentError("INVALID_PLAN", "Each Shot needs a filming goal and subject action")
        if shot.expected_duration > config.max_shot_duration:
            raise AgentError("INVALID_PLAN", "Shot duration exceeds MVP planning bound")
        validate_execution_relation(shot.execution_relation)
        if shot.execution_relation not in capability.execution_relations:
            raise AgentError("CAPABILITY_VIOLATION", "Shot motion relationship is not supported")
        for motion in shot.camera_motions:
            if motion.motion not in capability.motions:
                raise AgentError("CAPABILITY_VIOLATION", "Director motion is not in the current capability", {
                    "shot_id": shot.shot_id, "motion": motion.motion,
                })
            # Reject explicit command assignments in otherwise free-text intent fields.
            # Natural director timing prose remains legal; this is not semantic NLP.
            for text in (motion.tempo, motion.timing_requirement):
                if text and re.search(r"\b(?:PWM|GPIO|speed(?:_level)?|distance|duration|angle)\s*[:=]", text, re.IGNORECASE):
                    raise AgentError("INVALID_PLAN", "Director intent cannot contain hardware parameter assignments")
    return candidate


def validate_plan(plan: ShotExecutionPlan | dict[str, Any], registry: ActionRegistry) -> ShotExecutionPlan:
    """Validate an INITIAL plan completely before returning any executable result."""
    try:
        payload = plan.model_dump() if isinstance(plan, ShotExecutionPlan) else plan
        candidate = ShotExecutionPlan.model_validate(payload)
    except ValidationError as exc:
        raise AgentError("SCHEMA_ERROR", f"Invalid plan envelope: {exc}") from exc
    if candidate.registry_revision != registry.revision:
        raise AgentError("REGISTRY_MISMATCH", "Plan revision differs from current registry")
    validate_execution_relation(candidate.execution_relation)
    seen = set()
    for action in candidate.actions:
        if action.shot_id != candidate.shot_id or action.plan_id != candidate.plan_id:
            raise AgentError("INVALID_PLAN", "Action shot_id and plan_id must match the plan")
        if action.registry_revision != candidate.registry_revision:
            raise AgentError("REGISTRY_MISMATCH", "Action revision must match the plan")
        if action.source != "INITIAL":
            raise AgentError("INVALID_PLAN", "Initial plans can only contain INITIAL actions")
        if action.action_id in seen:
            raise AgentError("INVALID_PLAN", "Action IDs must be unique within a plan")
        seen.add(action.action_id)
        validate_action(action, registry)
    return candidate
