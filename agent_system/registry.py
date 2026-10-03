"""Config-driven action definitions. The supplied V0 config is MOCK ONLY."""

import json
from pathlib import Path
from typing import Any, Literal, get_args

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, model_validator

from .errors import AgentError
from .models import ActionSource, ContractModel, ExecutionRelation, Identifier


def _check_local_schema(value: Any) -> None:
    if isinstance(value, dict):
        for keyword in ("$ref", "$dynamicRef"):
            reference = value.get(keyword)
            if reference is not None and (not isinstance(reference, str) or not reference.startswith("#")):
                raise ValueError("Parameter schemas must be self-contained; remote references are not loaded")
        for child in value.values():
            _check_local_schema(child)
    elif isinstance(value, list):
        for child in value:
            _check_local_schema(child)


class RegistryEntry(ContractModel):
    action_name: Identifier
    description: Identifier
    parameter_schema: dict[str, Any]
    allowed_usage: list[ActionSource] = Field(min_length=1)
    correction_allowed: bool
    # Empty means no declared composition capability; never infer it from a name.
    correction_dimensions: list[Literal["horizontal", "vertical", "height_ratio"]] = Field(default_factory=list)
    # Explicit director semantics, not inferred from function names or parameters.
    motion_semantics: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_parameter_schema(self):
        Draft202012Validator.check_schema(self.parameter_schema)
        _check_local_schema(self.parameter_schema)
        return self


class ActionRegistry(ContractModel):
    revision: Identifier
    actions: dict[str, RegistryEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def matching_names(self):
        for name, entry in self.actions.items():
            if name != entry.action_name:
                raise ValueError(f"Registry key {name!r} must match action_name {entry.action_name!r}")
        return self


class ActionCapability(ContractModel):
    registry_revision: Identifier
    motions: dict[str, str]
    execution_relations: list[ExecutionRelation]


def project_capability(registry: ActionRegistry) -> ActionCapability:
    # Share the existing V0 execution policy instead of a second relation table.
    from .validation import validate_execution_relation

    motions = {}
    for entry in registry.actions.values():
        if "INITIAL" in entry.allowed_usage:
            for semantic in entry.motion_semantics:
                motions[semantic] = entry.description
    relations = []
    for relation in get_args(ExecutionRelation):
        try:
            validate_execution_relation(relation)
        except AgentError:
            continue
        relations.append(relation)
    return ActionCapability(registry_revision=registry.revision, motions=motions, execution_relations=relations)


def load_registry(path: str | Path) -> ActionRegistry:
    try:
        return ActionRegistry.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, SchemaError) as exc:
        # Registry schema errors are boundary errors, never an executable partial registry.
        raise AgentError("SCHEMA_ERROR", f"Cannot load registry: {exc}", {"path": str(path)}) from exc


def load_mock_registry() -> ActionRegistry:
    return load_registry(Path(__file__).with_name("mock_registry.json"))
