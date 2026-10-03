"""Runnable offline fixed-object demonstration. All execution is MOCK ONLY.

The FakeDirectorLLM response is scripted, not proof of natural-language intelligence.
Real planning is independently verified by the opt-in integration smoke test.
"""

import argparse
from decimal import Decimal
import sys

from .errors import AgentError
from .feedback import FeedbackConfig, evaluate_feedback_v2
from .llm import FakeDirectorLLM
from .models import FrameState, Observation, ShotScript, UserRequest
from .mocks import MockExecutor, MockReachabilityValidator, mock_correction_capabilities
from .motion_compiler import MockMotionCompiler, demo_registry
from .planner_v2 import VisualPlanner, VisualPlannerConfig
from .reachability import ReachabilityResult
from .state import AgentState


DEMO_REQUEST = "拍摄固定桌面青铜器：从偏低、占画面高度40%，用5秒升到中部并放大到70%"
SCENARIOS = ("timeline", "normal", "offset", "lost", "unreachable", "unknown", "distance-missing")


def captain_script(registry_revision, *, distance_fixture=False) -> ShotScript:
    """MOCK / DEMO TARGET VALUES: 'low' y=.70, 'middle' y=.50, not team standards."""
    distance = 2.0 if distance_fixture else None  # MOCK canonical-unit fixture only.
    return ShotScript.model_validate({
        "schema_version": "0.2", "registry_revision": registry_revision,
        "overall_goal": "展示固定桌面物体在画面内的位置和大小变化",
        "shots": [{
            "shot_id": "object-shot", "shot_goal": "主体由偏低升到中部，画面高度占比由40%增加至70%",
            "subject_action": None, "expected_duration": 5.0, "transition": None,
            "target_trajectory": {
                "keyframes": [
                    {"time_offset": 0.0, "frame_state": {"center_x": 0.5, "center_y": 0.7,
                     "subject_height_ratio": 0.4, "distance": distance}},
                    {"time_offset": 5.0, "frame_state": {"center_x": 0.5, "center_y": 0.5,
                     "subject_height_ratio": 0.7, "distance": distance}},
                ], "tolerance": {"center_x_tolerance": 0.05, "center_y_tolerance": 0.05,
                                  "height_ratio_tolerance": 0.05,
                                  "distance_tolerance": 0.1 if distance_fixture else None},
            },
        }],
    })


def _observation(frame, *, shot_id, plan_id, timestamp, lost=False, missing_distance=False):
    """MOCK ONLY bbox synthesis, not detection or camera/sensor integration."""
    bbox = None
    if not lost:
        x = Decimal(str(frame.center_x))
        y = Decimal(str(frame.center_y))
        half_height = Decimal(str(frame.subject_height_ratio)) / 2
        bbox = {"x1": float(x - Decimal("0.1")), "x2": float(x + Decimal("0.1")),
                "y1": float(y - half_height), "y2": float(y + half_height)}
    return Observation(shot_id=shot_id, plan_id=plan_id, timestamp=timestamp,
                       bbox=bbox, distance=None if missing_distance else frame.distance)


def run_scenario(scenario="timeline"):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown demo scenario")
    registry = demo_registry()
    distance_fixture = scenario == "distance-missing"
    fixture = captain_script(registry.revision, distance_fixture=distance_fixture)
    request = DEMO_REQUEST if not distance_fixture else DEMO_REQUEST + "；附带显式 MOCK 距离目标 fixture"
    verdict = {"unreachable": "UNREACHABLE", "unknown": "UNKNOWN"}.get(scenario, "REACHABLE")
    reachability = MockReachabilityValidator(ReachabilityResult(status=verdict, reason="MOCK ONLY fixture verdict"))
    executor = MockExecutor(registry)
    try:
        script = VisualPlanner(FakeDirectorLLM([fixture.model_dump()]), config=VisualPlannerConfig(
            allow_distance_targets=distance_fixture,
        )).plan(UserRequest(text=request), registry, reachability)
    except AgentError as error:
        if error.code != "REACHABILITY_REFUSED":
            raise
        return {"scenario": scenario, "status": "REFUSED", "user_request": request,
                "reason": error.code, "reachability": verdict, "execution_events": list(executor.records)}
    shot = script.shots[0]
    context = AgentState(plan_id="demo-" + scenario, shot_id=shot.shot_id, registry_revision=registry.revision)
    compiler = MockMotionCompiler(fixture.shots[0].target_trajectory, fixture_id="captain-fixed-object" + ("-distance" if distance_fixture else ""))
    plan = compiler.compile(shot.target_trajectory, context, registry, reachability)
    state = context.mark_ready(plan, registry)
    state = state.on_executor_event(executor.submit_plan(plan))
    state = state.on_executor_event(executor.start(plan.plan_id))
    timeline = []
    # Explicit MOCK TEST CONFIG and observation-relative times; no clock inference.
    config = FeedbackConfig(max_corrections=3, max_age_seconds=1.0)
    for index, sample_time in enumerate((0.0, 2.5, 5.0)):
        expected = shot.target_trajectory.evaluate(sample_time)
        mode = ("normal", "offset", "lost")[index] if scenario == "timeline" else scenario
        measured = expected
        if mode == "offset":
            values = expected.model_dump()
            values["center_y"] = float(Decimal(str(expected.center_y)) + Decimal("0.06"))
            values["subject_height_ratio"] = float(Decimal(str(expected.subject_height_ratio)) - Decimal("0.08"))
            measured = FrameState.model_validate(values)
        observation = _observation(measured, shot_id=shot.shot_id, plan_id=plan.plan_id,
                                   timestamp=100.0 + sample_time, lost=mode == "lost",
                                   missing_distance=distance_fixture)
        gate, decision, state = evaluate_feedback_v2(
            shot.target_trajectory, sample_time, observation, state, config,
            mock_correction_capabilities()["ALL"], trajectory_plan_id=plan.plan_id, now=observation.timestamp,
        )
        if not gate.accepted or decision is None:
            raise AgentError("INVALID_OBSERVATION", "Demo observation was not admitted", {"reason": gate.code})
        timeline.append({"time": sample_time, "expected": expected,
                         "measured": observation.to_frame_state(), "decision": decision})
    return {"scenario": scenario, "status": "PASS", "user_request": request, "script": script,
            "reachability": verdict, "plan": plan, "timeline": timeline, "state": state,
            "execution_events": list(executor.records)}


def print_scenario(result):
    print("\n=== " + result["scenario"] + " ===")
    print("1. User Request: " + result["user_request"])
    print("Planner: FakeDirectorLLM / scripted offline fixture / 0 API calls")
    print("MOCK / DEMO TARGET VALUE: low center_y=0.70; middle=0.50; not a team standard")
    if result["status"] == "REFUSED":
        print("3. Reachability: MOCK REACHABILITY -> " + result["reachability"])
        print("REFUSED before execution: " + result["reason"])
        print("Executor submissions: 0")
        return
    shot = result["script"].shots[0]
    print("2. Planner V2 Output: ShotScript 0.2 / fixed object / subject_action=null")
    print(shot.target_trajectory.model_dump_json(indent=2))
    print("3. Reachability: MOCK REACHABILITY -> " + result["reachability"])
    print("4. Execution Plan: MOCK MOTION COMPILER (recording-only recipe; no movement mapping)")
    print(result["plan"].model_dump_json(indent=2))
    print("5. Feedback Timeline (explicit observation-relative fixture time)")
    for row in result["timeline"]:
        print("t=" + str(row["time"]))
        print("Expected: " + row["expected"].model_dump_json())
        print("Measured: " + (row["measured"].model_dump_json() if row["measured"] else "null / target lost"))
        print("Decision: " + row["decision"].decision + " / " + row["decision"].reason)
        if row["decision"].correction_intent:
            print("TrajectoryCorrectionIntent (visual dimensions only):")
            print(row["decision"].correction_intent.model_dump_json(indent=2))
    print("PAUSE is a decision proposal; no device pause/resume is claimed.")


def main():
    # Explicit UTF-8 for Chinese requests in Windows terminals and captured output.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Offline fixed-object Agent V2 demo; MOCK ONLY execution")
    parser.add_argument("--scenario", choices=("all",) + SCENARIOS, default="all")
    args = parser.parse_args()
    print("Agent V2 Demo: PENDING HARDWARE / PLANNING CONTRACT")
    print("Reachability, Compiler, Executor, Observation and correction permissions are MOCK ONLY.")
    scenarios = ("timeline", "unreachable", "distance-missing") if args.scenario == "all" else (args.scenario,)
    for scenario in scenarios:
        print_scenario(run_scenario(scenario))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
