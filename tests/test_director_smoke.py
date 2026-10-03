"""Real Director validation. Opt-in only; never runs with default pytest."""

import pytest

from agent_system.action_planner import ActionPlanner
from agent_system.director import Director
from agent_system.errors import AgentError
from agent_system.feedback import FeedbackConfig, evaluate_feedback
from agent_system.llm import OpenAIDirectorLLM, OpenAIToolCallingLLM
from agent_system.models import CameraMotionIntent, Observation, UserRequest
from agent_system.registry import load_mock_registry, project_capability
from agent_system.state import AgentState
from agent_system.validation import validate_action, validate_shot_script
from real_llm_support import real_client


@pytest.mark.integration
@pytest.mark.parametrize("case,request_text,unsupported,short", [
    ("D1", "我想拍个换装视频", False, False),
    ("D2", "帮我拍一个有电影感的人物出场视频", False, False),
    ("D3", "帮我拍一个人物缓慢出场的短镜头", False, True),
    ("D4", "必须用无人机从头顶俯冲后完整环绕我，不接受替代方案", True, False),
])
def test_real_director_quality_smoke(case, request_text, unsupported, short, record_property):
    registry = load_mock_registry()
    with real_client("RUN_AGENT_DIRECTOR_SMOKE") as (client, model):
        director = Director(OpenAIDirectorLLM(client, model=model))
        if unsupported:
            with pytest.raises(AgentError) as caught:
                director.plan(UserRequest(text=request_text), registry)
            assert caught.value.code == "CAPABILITY_VIOLATION"
            record_property("capability", "unsupported request explicitly rejected")
            return
        script = director.plan(UserRequest(text=request_text), registry)
        assert validate_shot_script(script, project_capability(registry), director.config) == script
        assert 1 <= len(script.shots) <= 4
        if short:
            assert len(script.shots) <= 2, "Short-shot request is overplanned; review model quality"
        for shot in script.shots:
            for motion in shot.camera_motions:
                assert CameraMotionIntent.model_validate(motion.model_dump()) == motion
            target = shot.composition_target
            state = AgentState(shot_id=shot.shot_id, plan_id=f"{case}-{shot.shot_id}",
                               registry_revision=registry.revision, status="EXECUTING")
            # MOCK TEST CONFIG. Legal bbox close to this particular generated target.
            observation = Observation(shot_id=shot.shot_id, timestamp=100.0, bbox={
                "x1": max(0.0, target.target_center_x - 0.05),
                "x2": min(1.0, target.target_center_x + 0.05),
                "y1": max(0.0, target.target_center_y - 0.05),
                "y2": min(1.0, target.target_center_y + 0.05),
            })
            gate, decision, _ = evaluate_feedback(observation, target, state,
                                                  FeedbackConfig(max_corrections=3, max_age_seconds=1.0), now=100.0)
            assert gate.accepted and decision.reason != "invalid_composition_target"
        if case == "D1":
            # One real downstream mapping keeps this smoke gate small and inexpensive.
            shot = script.shots[0]
            context = AgentState(shot_id=shot.shot_id, plan_id="real-e2e-p1", registry_revision=registry.revision)
            action = ActionPlanner(OpenAIToolCallingLLM(client, model=model)).plan_motion(
                shot.camera_motions[0], context, registry)
            assert validate_action(action, registry) == action and action.source == "INITIAL"
            record_property("real_downstream_tool", action.action_name)
        assert any("text" in request and request["text"]["format"]["strict"] is True for request in client.requests)
        for field in ("schema", "business", "capability", "composition"):
            record_property(field, "PASS")
        record_property("shot_count", len(script.shots))
        print(f"{case}: {script.model_dump_json(indent=2)}")
        # D1/D2 intent alignment and distinct structure require human review of
        # these actual outputs. A programmatic PASS is not a creative-quality verdict.
