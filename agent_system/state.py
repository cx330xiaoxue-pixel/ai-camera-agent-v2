"""Explicit, immutable shot lifecycle; observations never change this state."""

from typing import Literal

from pydantic import Field

from .errors import AgentError
from .models import AgentDecision, ContractModel, ExecutionEvent, Identifier, ShotExecutionPlan
from .validation import validate_plan


class AgentState(ContractModel):
    plan_id: Identifier
    shot_id: Identifier
    registry_revision: Identifier
    status: Literal["PLANNED", "READY", "EXECUTING", "PAUSED", "COMPLETED", "FAILED"] = "PLANNED"
    reason: str | None = None
    correction_count: int = Field(default=0, ge=0)

    @classmethod
    def from_plan(cls, plan: ShotExecutionPlan):
        return cls(plan_id=plan.plan_id, shot_id=plan.shot_id, registry_revision=plan.registry_revision)

    def _transition(self, target, reason=None):
        allowed = {
            "PLANNED": {"READY", "FAILED"},
            "READY": {"EXECUTING", "FAILED"},
            "EXECUTING": {"PAUSED", "COMPLETED", "FAILED"},
            "PAUSED": {"EXECUTING"},
        }
        if target not in allowed.get(self.status, set()):
            raise AgentError("INVALID_STATE_TRANSITION", f"Cannot move from {self.status} to {target}")
        return self.model_copy(update={"status": target, "reason": reason})

    def mark_ready(self, plan, registry):
        validated = validate_plan(plan, registry)
        if (validated.plan_id, validated.shot_id, validated.registry_revision) != (self.plan_id, self.shot_id, self.registry_revision):
            raise AgentError("INVALID_PLAN", "Validated plan does not match current state")
        return self._transition("READY")

    def on_executor_event(self, event: ExecutionEvent):
        event = ExecutionEvent.model_validate(event.model_dump())
        if event.plan_id != self.plan_id or event.action_id is not None:
            raise AgentError("INVALID_STATE_TRANSITION", "Only matching plan-level events change shot state")
        if event.status == "accepted":
            if self.status != "READY":
                raise AgentError("INVALID_STATE_TRANSITION", "Acceptance requires READY")
            return self
        # A repeated running report is informational, never permission to resume a pause.
        if event.status == "running" and self.status == "EXECUTING":
            return self
        target = {"running": "EXECUTING", "completed": "COMPLETED", "failed": "FAILED"}[event.status]
        if self.status == "PAUSED":
            raise AgentError("INVALID_STATE_TRANSITION", "Paused state requires explicit resume confirmation")
        return self._transition(target, event.reason)

    def confirm_pause(self):
        return self._transition("PAUSED", "Pause explicitly confirmed")

    def confirm_resume(self):
        if self.status != "PAUSED":
            raise AgentError("INVALID_STATE_TRANSITION", "Resume confirmation requires PAUSED")
        return self._transition("EXECUTING", "Resume explicitly confirmed")

    def fail(self, reason):
        return self._transition("FAILED", reason)

    def record_correction(self, decision: AgentDecision):
        """Count an issued semantic ADJUST, not a confirmed hardware execution."""
        if self.status != "EXECUTING":
            raise AgentError("INVALID_STATE_TRANSITION", "Correction recording requires EXECUTING")
        decision = AgentDecision.model_validate(decision.model_dump())
        if decision.decision != "ADJUST":
            raise AgentError("UNSUPPORTED_CORRECTION", "Only ADJUST consumes correction budget")
        intent = decision.correction_intent
        if intent.shot_id != self.shot_id or intent.plan_id != self.plan_id:
            raise AgentError("INVALID_PLAN", "Correction must match the current shot and plan")
        return self.model_copy(update={"correction_count": self.correction_count + 1})
