# Planner V2 Real LLM Validation

- Date: 2026-10-03 (Asia/Shanghai)
- Provider: DeepSeek, OpenAI-compatible Responses API
- Model: deepseek-flash
- Scope: real natural-language request -> ShotScript 0.2 / visual TargetTrajectory.
- Result: **PASS**; 1 real integration test; 1 provider request; exit code 0.
- Command: `RUN_AGENT_PLANNER_V2_SMOKE=1` with
  `.venv/Scripts/python.exe -m pytest tests/test_planner_v2_smoke.py -m integration -q -W error -s`.

Input: 拍摄固定桌面青铜器：从偏低、占画面高度40%，用5秒升到中部并放大到70%。

| Time | center_x | center_y | subject_height_ratio | distance |
| --- | --- | --- | --- | --- |
| 0 s | 0.50 | 0.75 | 0.40 | null |
| 5 s | 0.50 | 0.50 | 0.70 | null |

One Shot, unique ID `shot_1`, expected_duration=5.0, subject_action=null,
composition_target=null, camera_motions=[], SEQUENTIAL. All normalized tolerance
values were 0.05; distance_tolerance=null. The model chose 0.75 for "low";
this is one generated target, not a team standard or calibrated physical pose.

Checks: strict JSON Schema response format requested and locally checked;
Pydantic geometry/time validation PASS; visual business validation PASS;
requested duration/start/end height preserved; no invented distance; no mechanical
parameter fields; no V0 motion intent required. No repair or prompt iteration used.

The separate Reachability verdict in this test was **MOCK ONLY**. The Compiler,
Executor and phone observations were not real. This test did not submit a motion
plan, execute a robot, demonstrate physical reachability, or close a real control loop.
The current mock compiler accepts only its explicitly registered demonstration
fixture; it does not claim to compile this different real-generated trajectory.

Default offline regression after adding this smoke: 507 passed / 10 integration
deselected, exit 0. Prior 9 V0 real integration passes remain historical evidence;
they were not rerun in this delivery. Real validation is a single-case smoke,
not a broad quality/reliability benchmark. No credentials are stored in this report.
