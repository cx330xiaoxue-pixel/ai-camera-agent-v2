"""Real tool validation; no implicit provider/model/credential selection."""

import pytest

from agent_system.action_planner import ActionPlanner, build_tool_definitions
from agent_system.errors import AgentError
from agent_system.llm import OpenAIToolCallingLLM
from agent_system.models import CameraMotionIntent, CorrectionIntent
from agent_system.registry import ActionRegistry, load_mock_registry
from agent_system.state import AgentState
from agent_system.validation import validate_action
from real_llm_support import real_client


@pytest.mark.integration
@pytest.mark.parametrize("case", ["T1", "T2", "T3", "T4", "T5"])
def test_real_openai_registry_smoke(case, record_property):
    registry = load_mock_registry()
    context = AgentState(plan_id="smoke-p1", shot_id="smoke-s1", registry_revision=registry.revision)

    if case == "T4":
        # Pure capability guard: explicitly fail if any provider call is attempted.
        class MustNotCallModel:
            def select_tool(self, *args, **kwargs):
                pytest.fail("Unsupported vertical correction must fail before calling a provider")
        intent = CorrectionIntent(shot_id=context.shot_id, plan_id=context.plan_id,
                                  correction_dimension="vertical", target=0.5, reason="subject_y_should_increase")
        with pytest.raises(AgentError) as caught:
            ActionPlanner(MustNotCallModel()).plan_correction(intent, context, registry)
        assert caught.value.code == "UNSUPPORTED_CORRECTION"
        record_property("provider_calls", 0)
        return

    if case == "T5":
        # Temporary test snapshot only: no production/mock config is modified.
        data = registry.model_dump()
        data["revision"] = "smoke-dynamic-v1"
        original = data["actions"].pop("hold")
        original["action_name"] = "mock_dynamic_hold"
        data["actions"] = {"mock_dynamic_hold": original}
        registry = ActionRegistry.model_validate(data)
        context = AgentState(plan_id=context.plan_id, shot_id=context.shot_id, registry_revision=registry.revision)
    with real_client("RUN_AGENT_OPENAI_SMOKE") as (client, model):
        planner = ActionPlanner(OpenAIToolCallingLLM(client, model=model))
        if case == "T3":
            intent = CorrectionIntent(shot_id=context.shot_id, plan_id=context.plan_id, correction_dimension="horizontal", target=0.5, reason="subject_x_should_increase")
            action = planner.plan_correction(intent, context, registry)
            assert action.source == "CORRECTION" and action.action_name == "rotate"
            assert all({tool["name"] for tool in request["tools"]} == {"rotate"} for request in client.requests)
        else:
            intent = CameraMotionIntent(motion="forward-like" if case == "T1" else "hold",
                                        tempo="slow", timing_requirement="one illustrative second")
            action = planner.plan_motion(intent, context, registry)
            expected_tool = "move_forward" if case == "T1" else "mock_dynamic_hold" if case == "T5" else "hold"
            assert action.action_name == expected_tool, "Legal but wrong tool is a model-quality failure"
            assert action.source == "INITIAL"
            assert client.requests[0]["tools"] == build_tool_definitions(registry, "INITIAL")
        assert validate_action(action, registry) == action
        assert action.registry_revision == registry.revision
        record_property("selected_tool", action.action_name)
        record_property("parameters_validator", "PASS")
        print(f"{case}: available={[tool['name'] for tool in client.requests[0]['tools']]}; selected={action.action_name}; validator=PASS")

