"""Explicit opt-in Real Planner V2 smoke, never a robot/Compiler validation."""

import json

import pytest

from agent_system.demo_v2 import DEMO_REQUEST
from agent_system.llm import OpenAIDirectorLLM
from agent_system.models import UserRequest
from agent_system.mocks import MockReachabilityValidator
from agent_system.motion_compiler import demo_registry
from agent_system.planner_v2 import VISUAL_DIRECTOR_INSTRUCTIONS, VisualPlanner
from agent_system.reachability import ReachabilityResult
from real_llm_support import real_client


@pytest.mark.integration
def test_real_fixed_object_visual_trajectory():
    with real_client("RUN_AGENT_PLANNER_V2_SMOKE") as (client, model):
        planner = VisualPlanner(OpenAIDirectorLLM(client, model=model, instructions=VISUAL_DIRECTOR_INSTRUCTIONS))
        script = planner.plan(UserRequest(text=DEMO_REQUEST), demo_registry(), MockReachabilityValidator(
            ReachabilityResult(status="REACHABLE", reason="MOCK ONLY; not real physical feasibility"),
        ))
        assert script.schema_version == "0.2"
        assert len(script.shots) == 1, "One continuous change should not be overplanned"
        shot = script.shots[0]
        assert shot.subject_action is None and shot.camera_motions == []
        assert shot.composition_target is None
        trajectory = shot.target_trajectory
        assert trajectory.duration == 5.0
        assert trajectory.keyframes[0].frame_state.subject_height_ratio == 0.4
        assert trajectory.keyframes[-1].frame_state.subject_height_ratio == 0.7
        assert trajectory.keyframes[0].frame_state.center_y > trajectory.keyframes[-1].frame_state.center_y
        assert all(frame.frame_state.distance is None for frame in trajectory.keyframes)
        assert trajectory.tolerance.distance_tolerance is None
        assert 1 <= len(client.requests) <= 2
        assert all(request["text"]["format"]["strict"] for request in client.requests)
        print("REAL_PLANNER_V2_RESULT=" + json.dumps({
            "model": model, "requests": len(client.requests), "schema": "PASS", "business": "PASS",
            "shot_script": script.model_dump(), "reachability": "MOCK ONLY",
            "robot_motion_validated": False,
        }, ensure_ascii=False, allow_nan=False))
