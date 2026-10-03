"""Phase 2.1: budget limits new corrections, not continuation of recovered shots."""

import pytest

from agent_system.feedback import FeedbackConfig, evaluate_feedback
from agent_system.models import CompositionTarget
from agent_system.mocks import mock_observations
from agent_system.state import AgentState


@pytest.mark.parametrize("count", [3, 4])
def test_recovered_frame_continues_with_exhausted_budget(count):
    state = AgentState(plan_id="p1", shot_id="s1", registry_revision="mock-v0", status="EXECUTING", correction_count=count)
    target = CompositionTarget(target_center_x=0.5, target_center_y=0.5, tolerance_x=0.1, tolerance_y=0.1)
    gate, decision, updated = evaluate_feedback(mock_observations(now=100.0)["NORMAL"], target, state, FeedbackConfig(max_corrections=3, max_age_seconds=1.0), now=100.0)
    assert gate.accepted and decision.decision == "CONTINUE"
    assert decision.reason == "within_tolerance" and updated is state
