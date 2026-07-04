# 宛委枢忆 OSAgent v0.9.3 工作流闭环验收报告

验收时间：2026-07-04
项目路径：`/home/administrator/wanwei_osagent_work`
控制台地址：`http://127.0.0.1:8011/console/`

## 结论

已将控制台从 v0.9.1 的研究/复现扩展阶段，推进到 **v0.9.3 Workflow Run 主线**：

- 新增可执行但安全的 workflow dry-run 编排器。
- 将 Workflow Run、Audit、Model Gateway、Tuning、Overview 串成可见闭环。
- 修正前端重复 `/workflow` 路由残留。
- 将后端 health、frontend dist、README、VERSION_LINEAGE 同步到 v0.9.3 叙事。
- 经 Python 编译、前端构建、API smoke、浏览器视觉验证通过。

## 本轮重点改造

1. **Workflow Run 页面**
   - 从静态“深做追问/规划页”改为真实 Workflow Run 控制面。
   - 支持选择预置 case，并调用后端 dry-run API。
   - 展示 stage timeline、证据卡、policy verdict、arena deltas、trace_id。

2. **后端 Workflow API**
   - 新增 `/workflow/run-dry-run`。
   - 新增 `/workflow/design`、`/workflow/competition-mapping`、`/workflow/runs` 系列端点。
   - dry-run 只做安全模拟，不执行危险真实动作。
   - 输出 stage latency、policy gate、evidence card、arena measurement、audit trace。

3. **Audit Trace**
   - 审计页支持 trace_id 过滤。
   - workflow dry-run 产生的 trace 能在审计流水里闭环追踪。

4. **Model Gateway**
   - 增加模型路由与 workflow stages 的关系说明。
   - 明确 memory retrieval / policy review / command planning 等用途。

5. **Tuning**
   - 新增控制链路测量口径。
   - 明确 `workflow_dry_run_latency_ms` 是 stage budget 合计。
   - 明确模型生成延迟独立展示，不混入 OSAgent 控制链路延迟。

## 真实 API 端点清单

本报告只记录当前 8011 服务真实可用端点，均无 `/api` 前缀：

- `GET /health`
- `GET /workflow/design`
- `GET /workflow/competition-mapping`
- `POST /workflow/run-dry-run`
- `POST /workflow/runs`
- `GET /workflow/runs/{run_id}`
- `GET /workflow/runs/{run_id}/trace`
- `GET /workflow/runs/{run_id}/artifacts`
- `GET /audit/logs?limit=50&trace_id=...`

## 验证记录

### 命令行验证

- Python 编译：`python3 -m compileall backend/app`
- 前端构建：`npm run build`
- Workflow API smoke：`POST /workflow/run-dry-run`
- Health smoke：`GET /health`

关键结果：

- `workflow_run` health 版本为 `v0.9.3-workflow-run`
- workflow dry-run 返回 `run_id`、`trace_id`、`stage_outputs`、`evidence_cards`、`policy_verdict`、`arena_measurements`
- frontend build 成功生成 dist assets

### 浏览器视觉验证截图

截图已保存到桌面：

- `wanwei_v093_workflow_run.png`
- `wanwei_v093_audit_trace_filter.png`
- `wanwei_v093_model_gateway.png`
- `wanwei_v093_tuning_latency.png`
- `wanwei_v093_overview.png`

视觉确认内容：

- Workflow Run 页面显示 v0.9.3 主线、dry-run、stage timeline、证据卡、policy verdict。
- Audit 页面显示 trace_id 过滤与 workflow run 事件。
- Model Gateway 页面显示 workflow stage routing。
- Tuning 页面显示 `workflow_dry_run_latency_ms` 与模型生成延迟分离口径。
- Overview 页面显示 `v0.9.3 Workflow Run 主线`，不再显示旧的 v0.7/v0.9 research health 叙事。

## 安全边界

v0.9.3 的 Workflow Run 是生产控制面的“安全 dry-run”版本：

- 不执行真实外部写操作。
- 高风险动作只进入 policy review / needs confirmation。
- evidence card 和 audit trace 必须存在。
- autopilot 仍标记为 planned，不开放真实危险自动化。

## 后续建议

下一阶段可进入 v0.9.4：

1. 将 workflow template 扩展为可配置 DAG。
2. 为真实 MCP/command execution 增加权限沙箱与确认队列。
3. 将 Arena cases 扩展到更多 failure modes。
4. 增加 trace replay 与审计回放页面。
5. 增加端到端自动化 UI 测试。

## 最终轻量复验（8011 常驻服务）

复验时间：2026-07-04 18:06 UTC / 本机桌面时间 2026-07-05 02:06

本次只验证真实端点，均无 `/api` 前缀：

- `GET /health`：HTTP 200，`status=ok`，`version=v0.9.3-workflow-run`
- `POST /workflow/run-dry-run`：HTTP 200，返回 `status=completed`、`run_id=wfr_9c50dcdfe4e7`、`trace_id=trace_9f115eb2409e`、`trace_len=10`
- `POST /workflow/runs`：HTTP 200，返回 `status=completed`、`run_id=wfr_1e7dd6caadca`、`trace_id=trace_aca9efb0652e`
- `GET /workflow/runs/{run_id}/trace`：HTTP 200，返回 `run_id`、`trace_id`、`items`，`trace_len=10`
- `GET /audit/logs?limit=50&trace_id={trace_id}`：HTTP 200，返回 `items`，命中 1 条审计记录
- `GET /console/?v=final093#/workflow`：HTTP 200，浏览器打开成功并完成截图

新增最终截图：

- `wanwei_v093_final_workflow.png`

最终结论：v0.9.3 Workflow Run 主线在 8011 常驻服务上完成轻量复验；报告中的 API 记录已统一为真实无 `/api` 前缀端点。
