"""Offline delivery tests: all execution and observations are MOCK ONLY."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("scenario,decision", [
    ("normal", "CONTINUE"), ("offset", "ADJUST"),
    ("lost", "PAUSE"), ("distance-missing", "PAUSE"),
])
def test_offline_pipeline_decisions(load_module, scenario, decision):
    result = load_module("demo_v2").run_scenario(scenario)
    assert result["status"] == "PASS"
    assert all(row["decision"].decision == decision for row in result["timeline"])
    assert result["state"].status == "EXECUTING"
    assert [event.status for event in result["execution_events"]] == ["accepted", "running"]
    if scenario == "offset":
        correction = result["timeline"][1]["decision"].correction_intent
        assert {item.dimension for item in correction.components} == {"CENTER_Y", "SUBJECT_HEIGHT_RATIO"}
        assert {item.dimension: item.target_value for item in correction.components} == {"CENTER_Y": 0.6, "SUBJECT_HEIGHT_RATIO": 0.55}
        assert not any(word in correction.model_dump_json() for word in ["motor", "rotate", "pwm", "gimbal"])
    if scenario == "distance-missing":
        assert result["timeline"][0]["decision"].reason == "required_measurement_missing"


@pytest.mark.parametrize("scenario", ["unreachable", "unknown"])
def test_unapproved_trajectory_never_reaches_executor(load_module, scenario):
    result = load_module("demo_v2").run_scenario(scenario)
    assert result["status"] == "REFUSED"
    assert result["reason"] == "REACHABILITY_REFUSED"
    assert result["execution_events"] == [] and "plan" not in result


def test_default_timeline_exhibits_three_decisions_and_no_distance_invention(load_module):
    result = load_module("demo_v2").run_scenario("timeline")
    assert [row["time"] for row in result["timeline"]] == [0.0, 2.5, 5.0]
    assert [row["decision"].decision for row in result["timeline"]] == ["CONTINUE", "ADJUST", "PAUSE"]
    assert [row["expected"].subject_height_ratio for row in result["timeline"]] == [0.4, 0.55, 0.7]
    assert all(row["expected"].distance is None for row in result["timeline"])
    assert result["script"].shots[0].subject_action is None
    assert result["state"].correction_count == 1


def test_cli_is_offline_and_labels_mock_components(load_module):
    module = load_module("demo_v2")
    env = dict(os.environ, PYTHONUTF8="0")
    env.pop("OPENAI_API_KEY", None)
    completed = subprocess.run([sys.executable, "-m", "agent_system.demo_v2"],
                               cwd=Path(__file__).resolve().parents[1], env=env,
                               capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.decode("utf-8", errors="replace")
    assert module.DEMO_REQUEST in output, "Windows CLI output must preserve Chinese in UTF-8"
    for text in ("MOCK REACHABILITY", "MOCK MOTION COMPILER", "FakeDirectorLLM",
                 "CONTINUE", "ADJUST", "PAUSE", "TrajectoryCorrectionIntent", "REFUSED"):
        assert text in output
    assert "PENDING HARDWARE / PLANNING CONTRACT" in output
