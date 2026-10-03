# Agent Core / Agent V2 Demo

## Agent V2 Demo

Python 3.11+; use this project's existing `.venv` (Pydantic, jsonschema and pytest).
From `D:\黑客松` in PowerShell, no API key or network is needed for the default demo:

```powershell
.venv/Scripts/python.exe -m agent_system.demo_v2
.venv/Scripts/python.exe -m pytest -q -W error
```

The default fixed-object scenario shows: low position / 40% image height at 0 s,
60% center_y / 55% height at 2.5 s, centered / 70% height at 5 s. It prints
CONTINUE, ADJUST (visual correction components), PAUSE (target lost), then
pre-execution unreachable refusal and a separate missing-distance fixture.
`low=0.70` is a **MOCK / DEMO TARGET VALUE**, not a calibrated team standard.
The main trajectory does not invent a distance. Explicit times are observation-relative
fixtures, not a decision about the future pause/resume timeline policy.

For individual demonstrations:

```powershell
.venv/Scripts/python.exe -m agent_system.demo_v2 --scenario normal
.venv/Scripts/python.exe -m agent_system.demo_v2 --scenario offset
.venv/Scripts/python.exe -m agent_system.demo_v2 --scenario lost
.venv/Scripts/python.exe -m agent_system.demo_v2 --scenario unreachable
.venv/Scripts/python.exe -m agent_system.demo_v2 --scenario distance-missing
```

**Real software:** ShotScript 0.2, normalized FrameState/TargetTrajectory, linear
sampling, visual business validation, Registry/atomic Plan validation, state
machine and deterministic Feedback V2. Planner V2 reuses the Director adapter,
generates visual targets only, and permits at most one business repair.

**MOCK ONLY:** default FakeDirectorLLM output, reachability verdict, Compiler,
Executor, observations and correction permissions. FakeDirectorLLM is a scripted
fixture, not natural-language intelligence. The compiler registers one exact
demo fixture and produces `mock_record_fixture`, a recording-only operation in
an independent `mock-v2-demo` Registry snapshot. It does not derive any mechanical
movement. V0 Registry, Tool Mapper, Director and feedback remain compatible.
UNKNOWN and UNREACHABLE refuse before execution. ADJUST ends at visual intent;
no mechanical correction is performed. PAUSE is a proposal, not a confirmed device pause.

Optional **real DeepSeek Planner V2 smoke** (separate from offline tests):
configure the existing local `.env` or process environment with `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `AGENT_OPENAI_MODEL`, without putting credentials in code or logs.
The already installed official SDK is used; no provider rewrite is required.

```powershell
$env:RUN_AGENT_PLANNER_V2_SMOKE='1'
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m pytest tests/test_planner_v2_smoke.py -m integration -q -W error -s
```

Current single-case real result: PASS (DeepSeek / deepseek-flash, one request).
See [real_planner_v2_validation.md](real_planner_v2_validation.md). This validates
real visual planning, **not robot movement or real reachability**. Default regression:
507 passed / 10 integration deselected. The previous 9 real V0 passes are historical.

External teams still need to supply a real Reachability adapter and visual-to-motion
Compiler mapping with Registry parameters/constraints; App/Vision observation format,
coordinate/orientation conventions, canonical distance unit and execution timing
association. Current mapping is **PENDING HARDWARE / PLANNING CONTRACT**. Agent naming,
Compiler ownership, distance planning, pause/resume policy and final demo Shot mode
remain pending team decisions, not blockers for this offline delivery.

Existing files modified for this delivery were backed up under
`backup/20261003-104331/`, preserving relative paths. No core files were deleted.

## V0 historical core

Agent-only deterministic foundation, Agent 3 V0 composition feedback and Agent 2 V0
tool-call planning and Agent 1 constrained ShotScript planning. Default tests are offline;
Phase 4B real LLM verification passes with DeepSeek / deepseek-flash; see the validation report below.
No App, Vision detection, device communication or hardware control is implemented.

## Setup and tests

Python 3.11+. From this directory in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[test]"
.venv/Scripts/python.exe -m pytest -q -W error
```

The current workspace uses an isolated `.venv`; global Python dependencies were not changed.
Verified versions: Python 3.11.5, Pydantic 2.13.5, pytest 8.4.2, jsonschema 4.26.0.
The additional whole-environment `pip check` is not clean: an unrelated `ultralytics`
distribution in `.venv` has missing Vision dependencies. Phase 1 never imports it.
Those packages were not installed, removed or repaired by this Agent implementation.
The strict Agent test suite passes independently of that environment issue.

## Contracts and boundaries

- `models.py`: fixed Pydantic envelopes, strict input types, forbidden extra fields,
  finite normalized coordinates and ordered bbox corners. `transition`, `tempo`,
  `timing_requirement`, and `target_action_id` are optional.
- `Observation.bbox` is required: explicit `null` means no target. Missing bbox and
  malformed coordinates are invalid. `no_target` is a derived property, not a second
  serialized field. Coordinates are never repaired.
- `registry.py`: configuration loading and self-contained JSON Schema validation.
  Remote schema references are rejected; loading a registry never fetches network data.
- `validation.py`: revalidates envelopes and dynamic parameters at boundaries.
  Initial plans require matching shot/plan/revision, unique action IDs, INITIAL sources,
  and complete validation before execution. V0 does not declare parallel capability;
  PARALLEL is rejected. Correction envelopes are validated separately.
- `state.py`: immutable state snapshots. Callers retain returned state objects.
  `from_plan` creates PLANNED; `mark_ready` performs full validation. A matching
  plan-level executor running event enters EXECUTING. Acceptance alone stays READY.
  Only explicit `confirm_pause` / `confirm_resume` changes pause state. Correction
  action-level events cannot complete the enclosing shot.
- If validation raises `AgentError`, the caller may record the failure with
  `state.fail(error.reason)`. A failed validation never returns READY.
- `observations.py`: admission only, without decisions, corrections, or state mutation.
  `timestamp` and explicit `now` are seconds in the same clock domain. Freshness is an
  explicit configuration argument; future timestamps are invalid. An observation exactly
  at the age limit is accepted. Wrong shot, stale and inactive state are rejected.

Allowed lifecycle:

```text
PLANNED -> READY -> EXECUTING -> COMPLETED
    |        |          |
    v        v          v
  FAILED   FAILED     FAILED
                        
EXECUTING -> PAUSED -> EXECUTING (explicit confirmed resume only)
```

COMPLETED and FAILED are terminal. PAUSED cannot become COMPLETED.

## MOCK ONLY

`mock_registry.json` is test configuration, not a real team/hardware contract:

| Action | Mock parameters | Usage |
| --- | --- | --- |
| move_forward | speed_level enum + duration (0, 10] | INITIAL |
| move_backward | speed_level enum + duration (0, 10] | INITIAL |
| rotate | direction left/right + duration (0, 2] | INITIAL / CORRECTION |
| hold | duration (0, 10] | INITIAL |

All durations and ranges are MOCK ONLY. No physical velocity, distance, angle,
motor mapping, or real calibration is implied. Each entry owns its JSON Schema.

`MockExecutor` revalidates each submission before recording acceptance. A plan is
an atomic job; a standalone action is a job keyed by plan_id/action_id. Execution
is explicitly advanced through accepted -> running -> completed, or failed.
It records plan_id, optional action_id, status, and reason. It does not simulate
individual movements, elapsed motion time, feedback, or physics. Submission snapshots
are copied; invalid plans create no execution records.

`mock_observations` supplies NORMAL, LEFT_OFFSET, RIGHT_OFFSET, NEAR_EDGE, LOST,
STALE and WRONG_SHOT. `MOCK_FRESHNESS_SECONDS = 1.0` is MOCK TEST CONFIG only.
Tests construct plans and explicit lifecycle confirmations; they do not run an Agent.

## TDD gate record

Every implementation group started with failing tests, followed by targeted and full
suite runs. Failures were missing implementation, not deliberately removed assertions.

| Group | Red | Targeted green | Full-suite green |
| --- | ---: | ---: | ---: |
| Models | 35 failed | 35 passed | 35 passed |
| Registry / dynamic parameters | 21 failed | 21 passed | 56 passed |
| Atomic plans | 11 failed | 11 passed | 67 passed |
| Mock executor | 9 failed | 9 passed | 76 passed |
| State | 15 failed | 15 passed | 91 passed |
| Observation gate / fixtures | 18 failed | 18 passed | 109 passed |
| Existing-component assembly verification | no new implementation | 3 passed | 112 passed |

Assembly checks cover explicit lifecycle, paused observation rejection, mutated nested
parameter rejection and recording validation failure. They passed immediately because
they compose already-tested components; they are not claimed as another red/green cycle.

## Phase boundary

Phase 1 implements Contract, Registry, Validator, Mock, State and Observation Gate.
Agent 1 planning is documented in Phase 4A below; real external execution adapters remain unimplemented. Real LLM
smoke verification is pending. Team-provided interfaces must replace MOCK ONLY
configuration through later Registry/schema/adapter integration.

## Phase 2: deterministic Agent 3

`feedback.evaluate_feedback(observation, target, state, config, now=...)` returns:

```text
(ObservationGateResult, AgentDecision | None, AgentState)
```

The function calls the unchanged Phase 1 Observation Gate first. Rejected observations
produce no AgentDecision, do not enter the private feedback logic, and return the original
state. Gate result codes remain unchanged. Timestamps must use the Gate's clock domain.

`FeedbackConfig` requires `max_corrections` (nonnegative integer) and `max_age_seconds`
(finite nonnegative number). It has no implicit production defaults. Tests use
`max_corrections=3` and the existing `MOCK_FRESHNESS_SECONDS=1.0`, explicitly MOCK TEST
CONFIG. Composition tolerances remain exclusively in `CompositionTarget`.

Decision order after Gate acceptance:

1. Explicit no target: PAUSE / `target_lost`.
2. Invalid composition target: PAUSE / `invalid_composition_target`.
3. Both center errors within inclusive tolerances: CONTINUE / `within_tolerance`,
   regardless of the correction count.
4. An offset still requires correction but the count is at or above the maximum:
   PAUSE / `correction_budget_exhausted`. Budget limits new ADJUST requests only.
5. Otherwise ADJUST / `horizontal_offset` or `vertical_offset`.

Center, width and height are calculated from normalized bbox. Width/height do not affect
decisions because V0 has no size target. Decimal representations avoid binary floating
point rounding producing a false offset at an exact decimal boundary; no tolerance epsilon
or extra visual policy is introduced. NEAR_EDGE follows the same numeric rules as any bbox.

An ADJUST reuses the existing `CorrectionIntent`: shot_id, plan_id, correction_dimension,
target, reason and optional target_action_id (unset in V0). Its target is the desired center
coordinate; reasons are `subject_x_should_increase/decrease` or
`subject_y_should_increase/decrease`. They describe image composition, not device motion.
For two-axis offsets, the axis with the greatest excess beyond its tolerance is selected;
ties select horizontal. Vertical decisions do not assert that the executor can correct them.

The only Phase 1 Contract extension is `AgentState.correction_count`, default 0, a strict
nonnegative integer. The previous state had no place to persist the required correction
budget. `AgentState.record_correction` increments an immutable state snapshot only for
a matching ADJUST during EXECUTING. `evaluate_feedback` delegates to it once per issued
ADJUST. This counts semantic decisions issued, not actions executed or corrections proven
successful. The caller must retain the returned state. Pause/resume preserves the count;
creating a new state from a new plan starts a new budget.

PAUSE is a decision requesting a pause, not proof that execution has stopped. It never
automatically changes the lifecycle to PAUSED. Existing explicit pause confirmation remains
required. Observations cannot resume PAUSED. No ActionRegistry mapping or executor call is
performed by feedback logic.

Phase 2 TDD record:

| Group | Red | Targeted green | Full-suite green |
| --- | --- | --- | --- |
| Correction budget state | 11 failed, 3 pre-existing validation cases passed | 14 passed | 126 passed |
| Feedback / Gate / offline integration | 42 newly added cases failed (feedback module absent) | 56 passed | 168 passed |

Final command: `.venv/Scripts/python.exe -m pytest -q -W error`.
Phase 1's 112 cases remain unchanged; Phase 2 adds 56 cases in `tests/test_feedback.py`.
Network calls are blocked in the NORMAL/ADJUST/LOST tests and API keys are absent.
The known unrelated ultralytics environment issue is left untouched.

V0 limitations: single observation, static center target, one correction dimension per
decision, no pose/action recognition, no edge-risk policy, no LLM interpretation, no
in-flight correction synchronization or temporal filtering. These are future enhancements,
not current decision rules. Phase 2 stops at semantic CorrectionIntent.

## Phase 2.1: budget patch

The previous budget check preceded the in-tolerance check. Two new regression cases
(count equal to and above maximum, with recovered NORMAL frame) failed before the patch.
The budget check now follows the CONTINUE check. Existing exhausted/zero-budget tests
use offset observations, preserving their rejection assertions under the corrected policy.
Targeted feedback tests: 58 passed. Complete regression after this patch: 170 passed.

## Phase 3: Agent 2 V0

```text
CameraMotionIntent / CorrectionIntent
    -> registry snapshot -> filtered dynamic function tools
    -> LLM ToolCallCandidate(tool_name, arguments)
    -> local envelope injection -> existing Action Validator
    -> validated StructuredAction (no execution)
```

`ActionPlanner` has three entry points:

- `plan_motion(intent, context, registry)` produces one INITIAL action.
- `plan_correction(intent, context, registry)` produces one CORRECTION action.
- `plan_shot(shot, context, registry)` maps motions in order, then validates a complete
  SEQUENTIAL ShotExecutionPlan. Any failed motion rejects the whole result. No prefix
  is returned or executed. The existing relation check is shared from Validator so
  PARALLEL fails before model calls.

Context reuses AgentState's shot_id, plan_id and registry_revision. A registry snapshot
keeps an individual planning request or shot consistent. action_id is a local UUID;
the model cannot provide or override any envelope field. The candidate model accepts
only tool_name and arguments, with extra fields forbidden.

The Registry remains the only tool source. INITIAL requires INITIAL in allowed_usage.
CORRECTION requires both correction_allowed and CORRECTION in allowed_usage.
Tool descriptions and parameter schemas are copied from Registry, not embedded in
the prompt. Structurally strict-compatible object schemas use strict=true; optional
fields or other non-strict-compatible structures use strict=false without changing
the local schema. The provider's full JSON Schema support still needs real smoke testing.
Local validation is mandatory in both cases.

One minimum capability field was necessary: RegistryEntry.correction_dimensions.
Usage permission alone could not distinguish horizontal from vertical correction.
It defaults to an empty list (no declared dimension). Mock rotate declares horizontal
only. This is MOCK ONLY metadata, not a physical direction/calibration mapping. All
four action names, the mock-v0 revision and all parameter schemas remain unchanged.
Vertical correction with this Registry fails before calling the model. Later capability
updates are configuration changes, not action-name checks in Agent 2.

Unsupported selection (adapter returns None) becomes CAPABILITY_VIOLATION for motion,
or UNSUPPORTED_CORRECTION for correction. Unknown actions fail immediately. No fallback
motion, new action or modified director intent is synthesized. A known exposed action
with invalid parameters can receive one repair request containing the Validator error
and its original schema. Repair exposes only that action; switching action is rejected.
A second invalid result fails. Envelopes and permission failures are not repaired.

## LLM adapter boundary

`llm.py` defines ToolCallingLLM, ToolCallCandidate and two adapters:

- FakeToolCallingLLM returns scripted fixture responses. It does not simulate intelligence.
- OpenAIToolCallingLLM accepts an injected official SDK client and explicit model. It uses
  Responses function tools with tool_choice=auto, parallel_tool_calls=false and store=false.
  It parses zero or one function call, never invokes a tool, and rejects malformed JSON,
  multiple calls and incomplete responses. Provider errors are normalized without including
  exception messages that may contain credentials.

The adapter has no SDK import, credential discovery or model default in offline core.
Tests use SDK-shaped local stubs; they do not prove real SDK/model compatibility.

Official references inspected:

- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [SDK structured-output tools example](https://github.com/openai/openai-python/blob/main/examples/responses/structured_outputs_tools.py)
- [SDK Responses parsing](https://github.com/openai/openai-python/blob/main/src/openai/lib/_parsing/_responses.py)

## Phase 3 historical Real LLM status: PENDING INTEGRATION

The following records the Phase 3 gate. Phase 4B now validates both Agent 1 and Agent 2;
see [real_llm_validation.md](real_llm_validation.md) for current evidence.

Two integration-marked tests are excluded by default. No real provider call was made.
The OpenAI SDK was not installed by this phase. When the provider/model/key are explicitly
confirmed, optional installation is `pip install -e ".[openai]"`. To opt into smoke tests,
set RUN_AGENT_OPENAI_SMOKE=1, AGENT_OPENAI_MODEL and OPENAI_API_KEY, then run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_openai_smoke.py -q -W error -m integration
```

Without explicit opt-in this command reports two PENDING INTEGRATION skips. The smoke
client disables SDK retries and uses a bounded timeout; application parameter repair
still remains at most one retry. Smoke tests do not execute selected actions.

## Phase 3 verification

| Group | Red | Green |
| --- | --- | --- |
| Phase 2.1 recovered-frame regression | 2 failed | 170 full-suite passed |
| Dynamic tool exposure / mapping / plans | 25 failed | 195 full-suite passed |
| Repair pinning / shared relation validation | 3 failed, 29 passed | 202 full-suite passed |
| OpenAI adapter boundary | 12 failed | 214 full-suite passed |

Default final gate: 214 passed, 2 integration tests deselected; exit code 0.
Baseline was 168 passed. Added offline cases: 2 budget + 32 planner + 12 adapter = 46.
Real smoke check without opt-in: 2 skipped, not claimed as real-model verification.
The known unrelated ultralytics dependency issue remains untouched.

Phase 3 limitations: one Intent -> one Action, SEQUENTIAL only, declared correction
dimensions only, no real calibration or feedback execution synchronization. A model can
still misunderstand semantic intent while returning a schema-valid permitted tool;
offline fixture tests do not establish language understanding or semantic equivalence.
Real-provider semantic evaluation and schema compatibility remain integration work.
Phase 3 stops at validated actions/plans; Agent 1 is implemented in Phase 4A below.

## Phase 4A: Agent 1 AI Director

```text
UserRequest + ActionRegistry snapshot
    -> project_capability -> Director LLM candidate
    -> existing ShotScript schema -> business validation
    -> ordered Shots with CameraMotionIntent and measurable CompositionTarget
```

`director.Director(llm, config=...).plan(request, registry)` reuses the existing contracts.
No DirectorShot/Storyboard model, framework, executor dispatch or hardware integration
was added. `DirectorConfig` defaults are **MVP PLANNING CONFIG**: 1–4 shots, each with
positive expected_duration at most 10 illustrative seconds. Director duration is distinct
from an Action's execution parameter. These bounds can change without modifying prompts.

The minimum Registry extension is `motion_semantics`, default empty (fail closed).
Usage permissions and parameter schemas alone could not describe director-level movement.
Only INITIAL-allowed entries with explicitly declared semantics appear in `ActionCapability`:
revision, motion semantics/descriptions and execution relations. Agent 1 never receives
function names as a separate action list or parameter schemas. The V0 relation policy is
shared with the existing Validator. Mock semantics are forward-like, backward-like,
rotation and hold; all are **MOCK ONLY**. The four action names, parameter schemas, ranges,
correction permissions and mock-v0 revision are unchanged.

The stable `llm.DIRECTOR_INSTRUCTIONS` contains no static capability table or fixed filming
template. User request, capability, planning bounds and constrained ShotScript JSON Schema
are runtime inputs. A registry update changes the next planning request automatically.
Composition need not be centered: all four center/tolerance values are finite normalized
numbers and remain directly consumable by Agent 3. Transitions are director descriptions,
not automatic editing instructions.

`validation.validate_shot_script` performs schema revalidation, schema/revision checks,
unique nonblank shot IDs, stable list order, nonblank goals/subject actions, shot-count and
duration bounds, declared motion semantics and supported relationships. Extra hardware
fields are forbidden by existing contracts. Explicit parameter assignments such as PWM=,
GPIO= or speed= inside motion prose are rejected; this limited check is not a general
semantic guarantee. Schema correctness alone does not prove creative intent alignment.

`FakeDirectorLLM` returns scripted fixtures, not creative intelligence. A schema-valid
business-invalid candidate may be regenerated once with its validation error, original
request and current capability. A second invalid candidate fails. Malformed schema,
forged version/revision, provider failure and explicit unsupported result fail immediately.
V0 uses CAPABILITY_VIOLATION rather than silently substituting a different creative plan.

`OpenAIDirectorLLM` extends the existing injected-client boundary. It uses Responses
`text.format` json_schema with strict=true and store=false. An API-only required nullable
`shot_script` wrapper permits an explicit unsupported result. Optional local fields become
required nullable fields only in the copied wire schema; the local ShotScript contract
is unchanged. Completed responses, strict JSON and provider-schema validation are required
before business validation. Refusal, truncation, duplicate JSON keys and provider failures
are explicit errors. No SDK import, API-key lookup or model default occurs in offline core.

Official interface checked: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
SDK-shaped stub tests verify our request/parser boundary, not a real provider/model.

### Phase 4A verification

| Group | RED / evidence | GREEN |
| --- | --- | --- |
| Projection / Director / business validation | 28 failed before implementation | 28 targeted; 242 full-suite passed |
| Existing-component bounds / cross-agent assembly | 11 passed using implemented components | 39 Director cases passed |
| Structured-output adapter | 16 failed before implementation | 55 Phase 4 cases; 269 full-suite passed |
| Parameter-assignment boundary | 4 failed before patch | 59 Phase 4 cases; 273 full-suite passed |

Full offline E2E starts with a UserRequest and scripted Director, maps its first Shot using
Phase 3 FakeToolCallingLLM, validates/submits a complete plan, confirms EXECUTING and feeds
Mock observations into Agent 3. NORMAL -> CONTINUE; LEFT_OFFSET -> ADJUST -> validated
CORRECTION action; LOST -> PAUSE. Networking is blocked and no API key is needed. Plans
remain READY until the Mock Executor explicitly reports running. No real device is used.

Final Phase 4A gate: **273 passed, 6 integration deselected, exit code 0**.
Baseline: 214 offline cases. Added: 43 Director/assembly cases + 16 adapter cases = 59.
Four Director integration cases were added alongside the two existing Agent 2 smoke cases.
The Phase 1–3 tests remain passing. The unrelated ultralytics environment issue is untouched.

### Phase 4B: PASS — DeepSeek / deepseek-flash

At the Phase 4A gate, there was no installed OpenAI SDK or configured model/API key.
No real model calls were made during Phase 4A; four Director smoke cases skipped without opt-in.
Phase 4B subsequently installed the existing optional OpenAI SDK in `.venv` and verified
DeepSeek / deepseek-flash through the same Responses adapters. Its final isolated run was
9 passed, exit 0; default offline regression is now 281 passed, 9 integration deselected.
The eight new offline cases verify integration isolation, configuration/error handling and
the one controlled Prompt adjustment. No Agent Contract or Mock parameters changed.
Full case results, initial failures and provider compatibility are recorded in
[real_llm_validation.md](real_llm_validation.md).
After provider/model/key are confirmed and the optional SDK is available, opt-in uses
RUN_AGENT_DIRECTOR_SMOKE=1, AGENT_OPENAI_MODEL and OPENAI_API_KEY:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_director_smoke.py -q -W error -m integration -s
```

Q1 outfit change, Q2 character entrance, Q3 mandatory unsupported movement and Q4 a single
short entrance shot check structural constraints, capabilities and overplanning. Printed
Q1/Q2 scripts still require human review for intent alignment and distinct structure.
Phase 4B includes real Agent 1 -> real Agent 2 consumption of D1's first motion; full
real mapping of every generated shot is not claimed. No LLM-as-a-Judge or aesthetic
benchmark is implemented. The expanded D1-D4/T1-T5 suite uses RUN_AGENT_REAL_LLM_VALIDATION=1
as a common explicit opt-in, reads three local `.env` settings only within that integration
boundary, and never records credentials. Process environment takes precedence.

V0 historical limitations: single-person static center targets, one motion -> one action,
SEQUENTIAL only, no broad creative-quality or physical-calibration guarantee, no automatic adaptation,
editing, action recognition or team integration. The three Agent core contracts now close
offline. The Phase 4B smoke gate now passes. Next is incremental real team Contract/Adapter
review; no App/hardware integration starts automatically.

## Development progress

`agent_progress.json` is the single machine-readable development status source.
`AGENT_PROGRESS.md` is its generated readable view. Update both after each formal Gate
using real test evidence; Phase 1–4 percentages describe Agent Core only. These files are
supervision artifacts and are never imported by the Agent runtime. Removing them does
not change Agent behavior. Formal stage reports end with a concise Agent Progress block.

## Phase 5B: trajectory feedback (deterministic, offline)

The V0 `evaluate_feedback` path remains available. New `evaluate_feedback_v2`
consumes an existing `TargetTrajectory`, an explicit `trajectory_time`, a plan-bound
`Observation`, `AgentState`, `FeedbackConfig` and `CorrectionCapability`.
`trajectory_time` is the relative execution time corresponding to that observation;
an eventual Execution Timing Adapter supplies it. Feedback never reads a wall clock
to locate the trajectory. Pause/resume and post-trajectory timing policy are pending.

The caller must provide `trajectory_plan_id` from the plan associated with the
trajectory, and `Observation.plan_id` must match the active state. Do not fabricate
these associations by assigning an old observation the current plan ID. The shared
Observation Gate rejects absent V2 IDs, wrong plans/shots, stale or malformed
observations and inactive states before decision logic. V0 may still omit plan ID.
The explicit `now` argument is used only for Gate freshness, not trajectory sampling.

Expected state is sampled with `trajectory.evaluate(trajectory_time)`; measured
state comes only from `Observation.to_frame_state()`. Center x/y and subject height
use their independent normalized tolerances. Distance comparison requires same
canonical internal unit for target, measurement and tolerance. The team has not
chosen that unit; this module performs no conversion. When no distance target exists,
measured distance is ignored. A distance target requires a distance tolerance at the
feedback business boundary; a missing required measurement produces PAUSE.
The Phase 5A structural trajectory contract remains unchanged.

ADJUST carries a `TrajectoryCorrectionIntent` with shot/plan IDs, relative time,
reason and one or more `CorrectionComponent`s. Each component holds dimension,
target value, observed value and signed error (observed minus target). Dimensions
are CENTER_X, CENTER_Y, SUBJECT_HEIGHT_RATIO and DISTANCE. Component order is stable,
not a severity ranking or execution order. No cross-unit max comparison is made.
All out-of-tolerance dimensions must be permitted by `CorrectionCapability`, or the
decision is PAUSE (`unsupported_correction`), without a partial correction.

One ADJUST consumes one correction request, even for multiple components. Within
tolerance always permits CONTINUE, including exhausted budgets. LOST -> target_lost;
required distance absent -> required_measurement_missing; remaining deviation with
exhausted budget -> correction_budget_exhausted. Invalid trajectory times retain
INVALID_TRAJECTORY_TIME errors without clamping, extrapolation or hold-last-frame.
PAUSE is a proposal; an external confirmation still controls lifecycle state.

`mock_correction_capabilities()` supplies ALL, VISUAL_ONLY, HORIZONTAL_ONLY and NONE
fixtures. These permissions are MOCK ONLY and declare no real hardware ability.
No Compiler, Reachability call, Director V2, LLM or device execution occurs here.
The new components are not accepted as legacy Agent 2 motor actions.

The captain example uses MOCK TARGET VALUES: y=0.70/height=0.40 at 0 s and
y=0.50/height=0.70 at 5 s. At 2.5 s the target is y=0.60/height=0.55. An observation
y=0.66/height=0.47 yields a single request restoring CENTER_Y and SUBJECT_HEIGHT_RATIO.
Example distance remains null. Agent naming, Compiler ownership, distance planning,
canonical units, pause/resume and single/multiple-Shot demo mode remain pending.
