# Phase 4B — Real LLM Validation

Date: 2026-10-02 (Asia/Shanghai). Provider: **DeepSeek**. Model: **deepseek-flash**.
Endpoint: https://api.deepseek.com. SDK: OpenAI Python **3.23.0**, installed only in `.venv`.
No Anthropic client or endpoint was used. Credentials are read locally, never recorded here.

## Gate result

**PASS — Agent 1 AND Agent 2 real validation.** Agent 3 remains deterministic.

- Final isolated integration run: **9 passed, 0 failed, 0 skipped; exit code 0**.
- Eight cases invoke the real provider. T4 is an intentionally local pre-call rejection.
- D1 includes a real Agent 1 -> real Agent 2 first-motion mapping, not a Fake adapter.
- Final offline regression: **281 passed, 9 integration deselected; exit code 0**.
- Offline baseline was 273; eight added offline tests cover validation-test isolation,
  local configuration handling, credential-safe error rendering and delivered Prompt rules.
- No App, Vision, Executor/device communication or physical calibration was added.

## Agent 1 cases

| Case | Exact input | Shots | Schema / Business | Capability | Composition | Downstream | Result |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| D1 | 我想拍个换装视频 | 3 | PASS | PASS | Existing Agent 3 reads every target | Real Agent 2 maps first motion to validated hold | PASS |
| D2 | 帮我拍一个有电影感的人物出场视频 | 3 | PASS | PASS | Existing Agent 3 reads every target | Every motion revalidates as existing CameraMotionIntent | PASS |
| D3 | 帮我拍一个人物缓慢出场的短镜头 | 1 | PASS | PASS | Existing Agent 3 reads the target | Existing CameraMotionIntent contract PASS | PASS |
| D4 | 必须用无人机从头顶俯冲后完整环绕我，不接受替代方案 | 0 | Explicit unsupported result parsed | CAPABILITY_VIOLATION as expected | N/A | No execution action generated | PASS |

Quick human review of the final run:

- D1 has before/change/after structure; all three shots use hold in this run. It aligns
  with outfit-change intent but clothing-change choreography/duration is still a human
  feasibility concern. No automatic editing or change-completion recognition is claimed.
- D2 differs from D1: visible subject in offset composition, a forward entrance beat,
  then a held final pose; motions are rotation -> forward-like -> hold. The revised
  wording describes a viewing-direction change rather than claiming a camera orbit.
- D3 uses a single held shot with a subject already partially visible near the frame edge;
  it does not create unnecessary shots. One-frame feedback may still react during movement.
- Mandatory unsupported drone movement is rejected rather than silently replaced.
- Only D1's first motion was mapped by real Agent 2 in this small smoke suite. D2/D3
  downstream checks establish contract consumability, not full real execution-plan quality.

## Agent 2 cases

| Case | Intent | Available tools | Selected tool | Local Validator | Result |
| --- | --- | --- | --- | --- | --- |
| T1 | forward-like initial motion | move_forward, move_backward, rotate, hold | move_forward | PASS | PASS |
| T2 | hold initial motion | move_forward, move_backward, rotate, hold | hold | PASS | PASS |
| T3 | horizontal CorrectionIntent | rotate only | rotate | PASS; CORRECTION source | PASS |
| T4 | vertical CorrectionIntent | none for this dimension | none; no provider call | UNSUPPORTED_CORRECTION | PASS |
| T5 | hold with temporary registry revision/name | mock_dynamic_hold only | mock_dynamic_hold | PASS; new revision retained | PASS |

T5 changes only an in-memory test snapshot. The project Mock Registry was not modified.
Every returned action is assembled locally and passes the original Registry Validator.
Tool calls are never executed by the LLM adapters or planners.

## Provider compatibility

- Agent 1 uses actual Responses `text.format` JSON Schema with strict=true, not JSON mode.
  The nested Shot/CompositionTarget/CameraMotionIntent output is parsed and locally
  revalidated; forbidden fields, motion enums and all required data remain constrained.
- A separate negative service probe supplied a deliberately invalid schema type. The
  server rejected it with **HTTP 400 / Invalid json schema**. The endpoint processes
  the schema instead of merely accepting a request for generic JSON.
- Agent 2 receives actual Responses function_call items with JSON arguments. No textual
  recommendation is treated as a tool call.
- DeepSeek documents that parallel_tool_calls is ignored and parallel calling is enabled.
  The existing adapter still rejects multiple candidates locally. This limit is not
  guaranteed by the remote flag, and is not relaxed for this provider.
- Existing OpenAI-format Responses adapters worked unchanged against this endpoint.
  Provider differences did not alter ShotScript, Registry, StructuredAction, State or Agent 3.
- Sources: [DeepSeek Responses API](https://api-docs.deepseek.com/guides/responses_api/),
  [Response reference](https://api-docs.deepseek.com/api/create-response/),
  [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/).

## Failures and one controlled Prompt adjustment

1. An early isolated D1 attempt returned LLM_ERROR. The issue did not reproduce in later
   same-pipeline diagnostic/final runs; its exact cause is unresolved. It is not recorded
   as a proven Core bug or a proven network fault.
2. The first complete run was **7 passed, 2 failed**: D4 returned a supported-looking
   replacement script instead of rejecting the mandatory request; T3 returned no tool.
3. Manual review also found an off-frame subject in D2 and camera-orbit wording hidden
   behind the supported rotation label. These were model/prompt-quality issues despite
   structural validation passing.
4. One Prompt adjustment batch clarified: visible subject throughout V0 shots; no hidden
   unsupported movement; mandatory unsupported operations return null; filtered MOCK
   correction tools use illustrative arguments without claiming physical calibration.
5. New local tests failed before the change, then passed. The final nine-case real run
   passed after this one adjustment. No repeated Prompt tuning was performed.

## Re-run

Fill local `.env` using `.env.example`; do not put credentials in this report or chat.
Process environment takes precedence over the three local settings. Offline Core does not
read `.env`. To opt into the separate integration suite in PowerShell:

```powershell
$env:RUN_AGENT_REAL_LLM_VALIDATION = '1'
.venv/Scripts/python.exe -m pytest tests/test_director_smoke.py tests/test_openai_smoke.py -q -W error -m integration --tb=short -s
```

The SDK has retries disabled and a 30-second request timeout. Existing application repair
remains at most once. Request recording excludes credentials/headers/input text, and
provider exception chains are suppressed in pytest failure output.

## Known limitations / next boundary

Small smoke evidence is not statistical reliability, aesthetic quality or real calibration.
Subject actions and qualitative timing still need human review. All hardware parameters
are MOCK ONLY, and no full physical shot or team interface has been verified. Output
language is not currently fixed. The unrelated ultralytics dependency issue is untouched.

Next: **Phase 5 — Team Contract / Integration Readiness**, after user review. No hardware
or App implementation begins automatically.
