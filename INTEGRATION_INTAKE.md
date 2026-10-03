# Integration Intake

当前模式：**INTEGRATION**。Agent V2 **DEMO READY**；**尚未 REAL ROBOT VALIDATED**。
停止主动扩展 Agent 架构。只有真实联调证明必要时，才进行带失败测试的最小核心修改。
V0、Mock、507-test 基线和已有备份均保留。

## Frozen baseline

- Git：`D:\黑客松` 当前不是 Git 仓库；未初始化 Git、未创建 commit。
- 本轮离线回归：`507 passed / 10 integration deselected`，exit code 0。
- Demo：`.venv/Scripts/python.exe -m agent_system.demo_v2`；本轮 timeline smoke exit 0。
- Real LLM：DeepSeek / deepseek-flash，Planner V2 已有单次真实 smoke PASS；本轮未调用模型。
- V0 Real LLM：9 项历史 PASS；不声称本轮重新运行。
- 基线文件清单与 SHA-256：[integration_baseline.json](integration_baseline.json)。
- 真实模型证据：[real_planner_v2_validation.md](real_planner_v2_validation.md)。

内部真实软件：Planner V2、Feedback V2、Visual Contract、Registry/Validator、状态机和 Adapter 边界。
当前外部模拟：默认 FakeDirector、Reachability、Compiler、Executor、Observation 和修正权限。
Mock Compiler 不产生真实机构运动；Real Planner PASS 不代表机器人运动 PASS。

## Intake records

[integration_intake.json](integration_intake.json) 是团队信息记录源，包含每条记录的
source_team、confirmed_value、missing_information、affected_contract、integration_status。
此文件与进度文件均不是 Agent 运行时依赖。

| Category | Record | Status | Current evidence |
| --- | --- | --- | --- |
| APP_VISION | APP_VISION-001 | WAITING | 已有 bbox/测距背景说明，尚无真实 payload Contract |
| REACHABILITY | REACHABILITY-001 | WAITING | 内部 Protocol 已存在，尚无真实校验接口 |
| MOTION_COMPILER | MOTION_COMPILER-001 | WAITING | 内部边界 + Mock 已存在，真实映射未交付 |
| EXECUTOR | EXECUTOR-001 | WAITING | 内部事件/状态机已存在，真实执行接口未交付 |

WAITING 表示尚未收到可实施 Adapter 的正式接口；概念性背景不是已集成证据。
每批新信息新增可追溯记录，记录来源与确认值，不覆盖未确认事项为事实。

只使用以下五种状态：

- WAITING：等待正式信息。
- PARTIAL：收到部分信息，但具体字段/行为仍缺失。
- READY_FOR_ADAPTER：当前批次的样例与约定足以编写对应 Adapter。
- INTEGRATED：Adapter Contract Test 和全量离线回归通过，尚未取得真机证据。
- VALIDATED：该层真实系统验证通过并记录证据；不自动代表整个机器人 E2E 通过。

## Fixed boundaries

App/Vision：External Payload → Observation Adapter → Internal Observation V1 → Gate → Feedback V2。
保留内部 normalized bbox + optional distance，不把外部 JSON 解析放进 Feedback。
坐标、单位、目标丢失和时钟差异只在 Adapter 中转换；不虚构 plan_id 或轨迹时间。

执行：TargetTrajectory → Reachability Adapter → Motion Compiler Adapter → ShotExecutionPlan
→ 现有原子 Validator → Executor Adapter。
仅 REACHABLE 可执行；UNREACHABLE/UNKNOWN 都拒绝。Planner 不输出机械参数。
真实硬件参数和物理映射留在外部 Contract / Compiler Adapter，不由 Agent 猜测。

## Incremental workflow

1. 更新该批团队信息及 Contract Status，明确缺失项。
2. 增加或修改对应 Adapter fixture；确认现有同职责文件，避免重复。
3. 先写失败 Contract Test 并确认失败。
4. 修改前备份已有文件，然后进行最小 Adapter 实现。
5. 运行相关测试。
6. 运行 `.venv/Scripts/python.exe -m pytest -q -W error`，保持原 507 项通过。
7. 全部通过后标记 INTEGRATED；同步 `agent_progress.json` / `AGENT_PROGRESS.md`。
8. 真机或该层真实外部系统验证通过后，才标记 VALIDATED 并记录证据。

收到信息后的简短回复只包含：New Information、Contract Impact、Files Changed、Tests、
Integration Status、Missing。不得因单个字段变化重写 Agent Core。

## Layered real validation

A. Real Observation + Mock Compiler。
B. Real Compiler + Mock Observation。
C. Real Observation + Real Compiler。
D. 完整真实系统，包括真实 Reachability、Executor 和执行时间关联。

所有层保留白名单、参数和计划原子校验。失败保持该层准确状态，不把 Core 历史 PASS 改为 FAIL。
Real Robot E2E 当前 WAITING，不自动启动联调或调用真实设备。

## Current status

Planner V2 / Feedback V2 / Visual Contract / Real Planner LLM / Mock Compiler / Offline E2E：PASS。
Real Observation / Reachability / Compiler / Executor / Robot E2E：WAITING。
Agent 命名、Compiler 归属、距离单位与用户规划权限、pause/resume 时间策略及最终 Shot 演示模式
仍待团队确认；本轮不替队长冻结答案。
