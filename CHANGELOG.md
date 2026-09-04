# 更新日志

本日志按时间倒序记录可追溯的项目变更。Unreleased 条目尚未形成发布版本或 Git tag，不代表已对外发布。

## Unreleased

### 2026-09-04 - TKE Temporal Knowledge Evolution 知识双时态与演化时间轴（#204）
- 新增 `backend/app/memory_runtime/temporal_knowledge.py`：TKE 时序核心，扩展 #202 的 knowledge_evolution（不新建平行体系，边词表对齐既有四类）。命名定档 TKE（Temporal Knowledge Evolution），与 EGPM 构成双体系叙事（偏好：情感→偏好→演化 ｜ 知识：时间→真值→演化）。
- 双时态：`state.valid_from` 补全 valid_time 区间（`valid_until` 已有，scan_stale 消费）；`set_valid_time` 经 update_capsule 写入（账本留痕、区间自洽校验、显式清空语义）。
- as-of 历史回放（两种模式诚实区分）：`truth`（世界真值，valid_time 判定——延迟导入场景「今天录入 2025 年历史知识仍可回答过去时刻」，命中者 recorded_at 暴露事后导入）；`belief`（系统当时认知，valid_time+transaction_time 双过滤——严格双时态口径）。全不命中如实返回 None + 各阶段淘汰名单。
- 时效冲突升级为区间判定：`classify_temporal_relation` 在双方都有显式 valid_time 时——区间不重叠 → 演化（不再误报冲突，detector 标注 knowledge_tke_v1）；区间重叠 → 真 temporal 冲突（证据更硬，覆盖标记词判定）；无显式区间行为与 #202 完全一致。
- Knowledge Timeline：`knowledge_timeline` 聚合演化链 + 账本事件（ledger_history 数据已在，缺的就是聚合层）+ 双时态区间为升序事件流；未知 op_type 原样透传；附 as-of 回放演示点。
- freshness（knowledge_confidence.recency 的 TKE 升级口径）：时间衰减 + `verified_at`（mark_verified 写 state，provenance 布尔位不覆盖）+ 引用稳定度（evidence_for/derived_from 入边实时计数不落库）；引用稳定度是 **max 兜底不是掺水**——时间信号新鲜时不拉低分数，衰减后托起（被反复引用的知识未必陈旧）。批量调用方预加载边表共享一次全表读。
- TKE Benchmark（`scripts/bench_tke.py` + `reports/tke_benchmark.json/report.md`）：四场景（软件演化/流程演化/规范替换/延迟导入）真实写路径，**Active Knowledge Accuracy 100%、Evolution Chain Accuracy 100%**，原始逐采样判定留 JSON 可复现。
- 新增 API：POST `/memory/knowledge-evolution/valid-time`、`/as-of`、`/verify`、GET `/timeline/{capsule_id}`（Literal 受控 mode，非法值 422）。
- 新增测试 40 条：test_temporal_knowledge / test_knowledge_timeline / test_freshness_scoring，覆盖双时态读写、as-of 双模式、半开区间边界、区间判定集成、时间轴聚合与回放、freshness 因果方向（含引用不惩罚回归）。全量 1719 passed / 6 skipped / 0 failed。

### 2026-09-04 - Knowledge Evolution 评审修复（PR #203 review）
- 事务顺序改为「先建后拆」：新胶囊的边/版本先落库、旧胶囊的生命周期转移在后——转移失败留下的是可重试中间态（重调幂等收敛），不再出现「旧知识已归档、演化证据丢失」的破坏态；版本链判定改用转移前的新鲜读收窄 TOCTOU 窗口，残余竞态最坏后果（幂等 update 账目一条）在 docstring 诚实标注。
- 自指演化边（new==old）显式拒绝：会形成单节点环并把自己转 deprecated。
- 英文状态词改词边界匹配：phone/condition/offer 不再误命中 on/off 组（CJK 保持子串——中文无词边界）。
- rerank 不可见状态显式归零：forgotten/deleted/quarantined/rejected/candidate 乘子 0.0，不按 active 缺省 1.0 对待。
- rerank 混合类缺省基础分统一 0.5（知识与非知识一致）：此前知识 0.5、非知识 0.0，active 知识会无条件碾压非知识候选，跨类比较失去意义。
- explain 不再外发 provenance.writer_identity（作者身份最小披露，读端点只留 source_type 与 verified）。
- tuning 权重读取的兜底 except 从裸 Exception 收窄为 (ImportError, AttributeError)——knowledge_evolution 与 preference_graph 两处同口径修复（宽 except 吞代码 bug 的教训见 PR #200）。
- explain 一次加载原始边表、演化链回溯与冲突扫描复用（原先一次请求 3 次无索引全表读）。
- 新增回归测试 7 条：自指拒绝、先建后拆、英文词边界（正反例）、不可见状态归零、混合类公平基础分、writer_identity 不外发。

### 2026-09-04 - Knowledge Conflict Resolution & Evolution（#202）
- 新增 `backend/app/memory_runtime/knowledge_evolution.py`：知识冲突消解与演化机制，与偏好演化（#198）形成双演化体系。零新表：节点即 knowledge capsule、边即 relation_edges（与 preference_graph 同一存储口径），知识状态机不发明新状态（active/superseded/deprecated/conflicted/forgotten 映射到既有 lifecycle）。
- 冲突检测四分类（规则式、每类带触发证据）：fact（同 key 异 value，K=V 抽取兼容中英文等号/冒号/is/为/是）、status（互斥状态词组 + 共享主语，CJK bigram 分词）、config（同参数不同数值）、temporal（覆盖标记词）。值恰为互斥状态对时 fact 升级为 status（redis is online/offline）。
- Knowledge Version：`state.knowledge_version` 随 supersedes 演化递增（Firefox→Chrome→Edge = 1→2→3）；invalidates 证伪失效不递增版本（无继任）；derived_from 只写边不动版本。
- 版本演化：`evolve_knowledge` 落 supersedes/invalidates/conflicts_with/derived_from 边；旧知识经状态机转 deprecated + 版本链字段（幂等——版本链已就位则跳过转移，零 transition 账本噪音，与 #200 评审修复后的同一口径）；演化链回溯限深防退化 DAG（MAX_EVOLUTION_DEPTH=100）+ 环防护。
- Active Knowledge Selection：`knowledge_confidence = 0.30×recency + 0.30×trust + 0.25×source_authority + 0.15×usage`（trust 复用 policy_gate 的 trust_score、source 复用 conflict_resolution 分级表）；`suggest_active_knowledge` 只建议不执行（auto_execute 恒 False），同分决胜按 created_at 新者在前。
- Knowledge Explain：`explain_knowledge` 一次返回当前版本/状态/四因子置信度/演化链/双向冲突记录/裁决建议/来源证据。
- 检索增强：`knowledge_rerank` 只读重排，active→1.0、stale→0.85、conflicted→0.60、deprecated→0.5^代数（传递深度计算）封底 0.1；基础分缺省中性 0.5（真实胶囊无 retrieval_score 字段，按 0 处理会退化为 id 字典序）；非知识候选恒等通过；不 bump usage_count。
- 新增 API：POST `/memory/knowledge-evolution/detect-conflicts`、`/evolve`、`/active-suggest`、`/rerank`、GET `/explain/{capsule_id}`（Literal 受控边名，非法值 422）。
- 新增测试 49 条（验收要求的四件套）：test_knowledge_conflict / test_knowledge_evolution / test_active_knowledge / test_conflict_retrieval，覆盖四类冲突检测、版本链、幂等、限深/环防护、四因子因果方向、建议式裁决边界、检索降权、explain 全景与端到端闭环。

### 2026-09-04 - Preference Graph 评审修复（PR #200 review）
- 幂等修复：`record_preference_evolution(replaces)` 重复调用不再无条件重跑 `apply_transition`（旧版本会重复生命周期 UPDATE + FTS 同步 + 追加 transition 账目，正是 apply_transition 文档警告的账本噪音）；版本链是否需要追加以事务内读到的 state 为准，本地死代码快照突变已移除。
- 级联限深：replaces 链回溯新增 `MAX_CHAIN_DEPTH=100` 上限——`seen` 集合只防环不防退化 DAG，被污染数据串起的超长链会拖成全表遍历并锁死请求路径；截断时记 warning 并在结果里如实上报 `cascade.depth_truncated`。
- `_load_raw_out_edges` 截断可观测：多取一行探测 LIMIT 命中，命中即记 warning（链可能不完整，宁可漏不可挂死口径），不再静默丢弃。
- 重排无信号可区分：偏好候选不在图视图时 `preference_score=None`（「没测到」）而非 0.5（「实测中性」），乘子仍按中性 0.5——telemetry/门控消费方不再拿到安静的假信号。
- 异常口径收窄：级联删除重验的兜底 except 从裸 `Exception` 收窄为 `(sqlite3.Error, RuntimeError, OSError)` 并加 `exc_info=True`——宽 except 会吞 NameError/TypeError/AttributeError（本仓真实事故：静默失效的采样器让 benchmark 假绿）。
- 新增回归测试 3 条：幂等重调零 transition 账目、深度截断如实上报（含正常短链不误报）、无信号 None 分数。

### 2026-09-04 - Preference Graph 偏好记忆图与偏好演化机制（#198）
- 新增 `backend/app/memory_runtime/preference_graph.py`：在既有 capsule 之上建偏好图视图——节点（preference/evidence/constraint，由 memory_class 推断、`content.preference_graph_node_type` 显式覆盖）与受控词表边（evidence_for / emotion_for / constraint_of / replaces / conflicts_with / derived_from），边写入既有 relation_edges JSON 列（零新表、与 RRF 图通道键名兼容）。
- preference_score 四因子评分模型：emotion(0.35) + recency(0.25) + frequency(0.20) + evidence(0.20)，权重进 tuning `preference_graph` 段可调；四因子分解随分数返回（可解释）。
- 偏好演化：`record_preference_evolution` 落 replaces 边并把旧偏好经状态机转 deprecated（版本链 superseded_by 维护、幂等）；conflicts_with 只标记冲突不动生命周期（治理底线：冲突必须显式裁决）。
- 建议式冲突裁决：`suggest_active_preference` 按多因子权重给出 active_preference 建议，auto_execute 恒 False，生效路径仍是 `lifecycle.resolve_conflict(actor='human')`。
- 级联遗忘：`cascade_forget_preference` 沿 replaces 链回溯遗忘旧版本（限深防环）、摘除指向目标的 evidence_for/emotion_for 边（证据胶囊保留）、strip 已忘胶囊间的死边后重验删除完整性（all_complete 以 strip 后为准）。
- preference-aware retrieval：`preference_rerank` 只读重排，`final = retrieval_score × (1−w + w×preference_score)`，只影响 preference 类候选；w=0 严格恒等（消融基线）；不 bump usage_count。生产检索路径未接线（纯增量口径，与 RRF 融合入口同策略）。
- 新增 API：GET `/memory/preference-graph`、POST `/memory/preference-graph/evolution`、`/active-suggest`、`/cascade-forget`、`/rerank`（schemas 用 Literal 受控边名，非法值 422）。
- 新增测试 42 条：test_preference_graph / test_preference_evolution / test_preference_conflict / test_preference_retrieval，覆盖节点推断、边词表、评分因子因果、演化幂等、冲突治理边界、级联遗忘（含环防护与删除完整性）、重排恒等基线。

### 2026-09-03 - 工具调用序列偏好挖掘（#164 B2）
- 新增序列模式挖掘独立模块与建议式偏好闸门函数（evaluate_preference_candidate，强制 requires_confirmation）；尚未接入主链路（无生产调用方），接线与调用时机另行评审。

## 2026-07-18 - v0.11.0「万枢」桌面协作平台

- 新增 `backend/app/platform_api/` 万枢平台 API 聚合包，由 `app.main` 统一以 `/platform` 前缀挂载，子模块自动发现、单模块导入失败仅告警跳过，共八个后端模块：
  - `providers`：31 家模型厂商接入目录（catalog）与用户配置管理，密钥 Fernet 加密落盘、接口只写不读；配置就绪才真实调用，否则返回明确 stub 标识。
  - `agents`：多智能体编排运行（run），全平台共享思考深度六档（low/medium/high/xhigh/max/ultracode）与工作档位三档 gear 门禁（human_review/sandbox/device；device 与 sandbox 同为可执行档位，整机级危险操作由具体模块显式校验）。
  - `spaces`：项目任务空间 tree / main / perch 三态状态机；alpha 期为目录级物理隔离 + 状态机建模，真实 `git worktree` 绑定列入 M2。
  - `automation`：AI 可编辑工作流，规则式中文解析器把自然语言指令转为流程定义 diff（engine='mock'，诚实标注为模拟引擎）；运行模拟不真实执行 shell/http/agent/memory 步骤，仅返回 would_run 说明。
  - `knowledge`：知识库收录、分块与检索；基于 SQLite FTS5（CJK 逐字插空格分词，支持中文子串检索），0 命中时 LIKE 兜底；**无外部向量检索后端**，麒麟原生向量 SDK 的接入列入 M2。
  - `memory_center`：记忆指令（「记住……」快捷写入，单条不超过 200 行，remember / instructions / phrases 写入前统一过 Policy Gate 拦截密码/密钥/投毒）与手动触发的会话摘要归档（`/dreams/archive-now`）；无每夜自动调度（`/dreams/schedule` 如实返回 `enabled:false, mode:'manual'`），压缩冗余/合并近义/标记冲突/全程审计留痕列入 M2。
  - `system_svc`：系统服务出口（健康检查、防睡眠状态镜像、通用设置、语音输入存档、防追踪浏览器规则与启动计划、模拟器镜像下载、LAN 模式与手机配对 token 签发、沙盒命令执行、wanwei CLI 使用指南）；版本/模块清单/自启动状态查询当前未实现，列入 M2。
  - `mcp_hub`：MCP 服务器注册表与工具调用代理；stdio 传输仅在服务端显式开启 device 档且 command 命中 `WANWEI_MCP_STDIO_COMMANDS` 白名单时真实连接，子进程使用最小环境且不继承 `WANWEI_*` 服务秘密；sse/streamable_http 真实连接为 M2，调用结果以 stub/live/error 诚实标注。
- 新增 `frontend/console-vue/src/views/platform/` 十一个中文视图：万枢工作台（WorkbenchView）、模型接入（ProvidersView）、智能体（AgentsView）、空间（SpacesView）、自动化（AutomationView）、知识库（KnowledgeView）、记忆中枢（MemoryCenterView）、会话（SessionsView）、设置（SettingsView）、帮助（HelpView）、手机伴侣（MobileView）。
- 桌面端 `desktop/src` 新增防睡眠（`powerSaveBlocker` app/display 双模式）、局域网手机控制（后端 `127.0.0.1 ↔ 0.0.0.0` 热重启切换、私有网段 IPv4 优选、LAN token 配对）与浮动工作区小窗（420×640 无边框置顶，加载移动视图）。
- 修复自动化模块路由：统一收敛到 `/platform/automation` 前缀，固定路径（/flows/ai-edit、/flows/schedule/overview）先于参数路径（/flows/{fid}）注册，避免被参数路径吞掉。
- 新增 `docs/万枢平台-架构设计.md`：愿景定位、Orca 理念映射、麒麟标准符合性清单、系统架构、八模块 M1 契约、安全边界与 M1–M3 路线图。
- 许可证改用国产木兰宽松许可证第 2 版（Mulan PSL v2）。
- 事实边界保持诚实：本平台仍为可运行单节点 alpha；真实模型 API 调用（未配置时 stub）、git worktree 真实绑定等未接通能力一律以 stub / simulated 明确标注，不宣称已可用；device 档与 sandbox 同为可执行档位，整机级危险操作由具体模块显式校验。


### 2026-09-03 - RRF 三路融合排序（#164）

- 落地 FTS / vector / graph 三路 RRF 融合与两跳图扩散，保持纯增量口径。
- 新增融合入口与消融验证；当前尚未接入主检索路径，后续接线另行评审。

### 2026-09-03 - Outcome Validation（#180）
- 新增偏好执行结果反馈闭环：支持 accept/reject/undo/retry/unknown、Beta 后验修正、可追溯有界审计日志与环境变量 feature flag。
- 修复 #180：feature flag 关闭时结果反馈严格 no-op，并补齐偏好胶囊级 `record_outcome` 持久化接线。
- Outcome Validation 的对照实验未在本分支运行，待并入 EGPM 评测基准（#181）后统一验证。

### 2026-09-03 - ReDoS 修复：脱敏正则加界 + 16KB 长度闸 + workflow 输入限长（#172）
- 交叉审查补强：大文本分段脱敏改为「分段保守处理 + 拼接后全规则兜底补跑」，URL 凭据规则按 ：// 锚点窗口执行（str.find 线性定位，窗口 300 字符），修复跨段切点腰斩 token 的漏脱敏回归，同时保证补跑阶段无 O(n·256) 起点试探（168KB 最坏输入实测 0.41s）。

- `security/redaction.py` URL 凭据正则（`user:password@host`）加界改造：用户段排除 `@`、user/password 各限 256 字符并保留终止 `@` 断言，消除「`://` 后超长文本每起点回溯到串尾」的二次方回溯；正常 URL（http/https/ftp、多段、无凭据 URL、中文语境）脱敏结果与旧正则逐字符一致，新增回归测试锁定。
- `redact_sensitive_text` / `redact_audit_payload` 入口加 16KB 长度闸：超过阈值的文本按 ≤1KB 段切分、逐段脱敏再拼接，私钥块多行规则在拼接完整串上兜底，单次调用耗时由 O(n²) 降为线性（168KB 最坏输入实测 <1s，修复前同规模约 40s）。
- `WorkflowRunIn.scenario` / `user_goal` 补 `max_length`，与 `security/input_limits.MAX_GOAL_LENGTH` 对齐；超长输入由 FastAPI 返回 422。
- 新增 `tests/test_redaction_dos.py` 回归：168KB 性能门禁、URL 正则行为等价、422 校验、16KB 闸分段与整串处理一致性。

### 2026-09-03 - 安全评分账本校验修复（#173）

- 修复安全评分对 `memory_ledger` TEXT 主键执行递归整数 CTE 导致的无限递归；改为一次性读取并在 Python 校验 ledger ID 完整性。

### 2026-09-03 - MCP stdio 环境键名过滤

- MCP stdio 用户环境变量写入和启动前统一过滤危险键（含大小写不敏感的 `PATH`、`LD_PRELOAD`、`LD_LIBRARY_PATH`、`DYLD_*`、`NODE_OPTIONS`、`PYTHONPATH`、`PYTHONSTARTUP`、`BASH_ENV`、`ENV`、`SHELL`），合法键继续透传。

### 2026-09-03 - governance incidents 作用域口径定档（#175）

- GET /memory/governance/incidents 明确定位为平台级全局治理事件流（无 owner 维度，任意持有效 key 者可见），口径写入 docstring 与 OpenAPI description；POST description 限长对齐 input_limits 口径、detected_by 收紧为 Literal 四值（非法 422）；capsule_id 可见性校验保留不变。

### 2026-09-03 - rotate_api_key 可逆回滚修复（#176）

- 修复 API key A→B→A 回滚因历史 inactive 行联合主键冲突而返回 500；轮换事务失败时显式回滚，确保旧 key 失效与新 key 落库保持原子性。

### 2026-09-03 - EGPM Phase-3 Benchmark（#181）

- 修复六类场景的 topic 隔离并收口评测运行器常量与说明；+Drift 为滑窗众数变化代理检测器，真实漂移（#168）与 Outcome Validation（#180）未接线，相应列标注为未验证。

### 2026-09-03 - 情感证据权重：preference Beta 更新的情感调制（issue #179）

preference 记忆的 Beta 置信度更新接入**情感证据权重**（加权更新 α += w / β += w，
默认 w = 1.0 严格保持既有等权语义，feature flag 关闭时与旧行为逐位一致）：
- **Emotion ≠ Preference**：情感信号绝不直接产生偏好，只作单次证据的强弱调制信号
  参与 Beta 更新——偏好方向仍完全由 reinforce / deprecate 证据决定，杜绝
  「高情感 == 高偏好置信度」的直接映射。
- **Feature flag**：新增 `WANWEI_AFFECTIVE_EVIDENCE`（默认关闭，真值取
  1/true/yes/on）；关闭时无论传入什么权重一律等权 1.0，同一套代码/数据流可直接跑
  「Beta」与「Beta + Affect」两组消融，而非比较两套同时变化的系统。
- **权重规则**：合法权重为有限正实数并裁剪到 `[w_min, w_max]`（默认
  `[0.5, 3.0]`，`WANWEI_AFFECTIVE_W_MIN/MAX` 可配）；NaN / inf / 非正数 / 非数值
  （含 bool）等非法输入一律**精确回落 1.0、不参与区间裁剪**——非法 = 无有效情感
  信号 = 中性基线，区间裁剪只作用于合法的情感权重。
- **审计可追溯**：每次证据参数追加到 `state[preference_evidence_log]`（有界保留
  最近 `WANWEI_EVIDENCE_LOG_LIMIT` 条，默认 20），可追溯方向 / 原始情感信号 /
  权重 / α/β 增量 / 时间；旧数据无该键时自动从空表开始，不覆盖原始证据。
- **消融如实记录**：`scripts/ablation_affective_weight.py` 合成证据流三臂消融
  （A.Unit / B.Random / C.Affect，seed=179）实测情感加权**暂未带来 Brier 提升**
  （A 0.1482 / B 0.1562 / C 0.1524）；属合成机制自检而非真实评测——feature flag
  默认关闭即该结论的生产护栏，真实收益需真实反馈另行验证。

### 2026-09-03 - 低危加固批量 L1-L8 + 工程项（#177）

- L1-L8 低危加固：身份 key 脱敏与强度校验、模型端点写入前 SSRF 校验、工作流字段长度限制、移动上传配额与 SSE 上限、下载错误脱敏、JsonStore 原子 mutate、提交路径 TOCTOU 复核。
- 备忘：全局同类 schema 无界字段已盘点，本批仅收紧 `WorkflowRunIn`，其余保持兼容待后续专项处理。

### 2026-08-26 - CI 质量门禁与事务恢复修复

- 修复 SQLite 线程本地连接的关闭竞态：测试清理或应用关闭不再从其他线程强制关闭正在执行查询的连接，避免 Linux 下原生段错误；连接代际失效后由所属线程自行回收，并新增并发回归测试。
- 统一应用包内部相对导入，防止生产 `app.*` 入口同时加载第二套 `backend.app.*` 数据库与服务单例；新增静态导入门禁和 ASGI 启动模块身份回归测试。
- 修复后端 Ruff 门禁中的未定义名称与错误合并残留，恢复 Python 3.10/3.12 测试矩阵的可执行性，并让结构化上下文测试显式设置模型网关前置条件，不再依赖开发机配置或模块加载顺序。
- 修复模型网关测试的进程级 smoke executor 泄漏：共享夹具会清理所有模块导入别名，reload 前也会先关闭旧 runtime，避免全量测试中的线程残留与顺序污染。
- 修复遗忘结果持久化在意外异常后未回滚 `BEGIN IMMEDIATE` 的问题；失败仍原样抛出，但重放请求不再继承陈旧写事务或数据库锁。
- 前端会话架构契约测试改用 Vite SSR 模块加载器，保留 `/console/*` 别名解析；生产构建、安全测试、契约测试与桌面打包契约恢复通过。
- README 补充前端契约测试与桌面测试的本地自验命令。

### 2026-08-25 - 情感检测器否定/程度规则与排序门禁（#121）

修复 `affect/emotion_detector` 纯子串词表的方向性误判（issue 实测 4/4 反义句被判 positive，且以 0.15 权重进入检索排序、被永久写进记忆标签）：
- **否定翻转**：情感词紧邻否定前缀（不太/没/别/not…）时有效极性取反，标签跟随有效极性；被否定的焦虑/兴奋命中整条丢弃。
- **程度放大**：程度副词（非常/太/「好+情绪词」/very…）作 ×1.5 幅度乘子，不再当独立正向信号——旧版裸「好」在「好像/好多」里子串误命中是主要误判源，已从词表移除。
- **惯用语豁免**：「不错/不赖/没问题」先于否定规则参与，不被「不」误翻转；正负并存且 |Δp|≤0.15 时如实判 `mixed`，不再默认 positive。
- **排序门禁**：内置 20 条最小标注集自检（含反讽样例并如实计入错误），准确率 <0.7 时 `ranking_factor()`=0，检索侧停用 affective 权重；当前实测 0.95。新增回归测试 17 例钉住 issue 的全部反例。
- 同族收窄：`classify_intent` 裸「差」改「差劲/差评/太差」，「差不多就行」不再误报 complaint。已知边界：不分词、不识别反讽；`perception/intake.py` 另有一份独立词表未动（不同标签体系、挂主链路，后续单独评估）。

### 2026-08-25 - CI 矩阵修复（Python 3.10 兼容 + 环境无关化测试）

修复 #66 合并后四个 Backend CI job 的 3 个失败（本地未在 Python 3.10 预检、且 CI 环境 DNS 与本地不同——已在流程中补齐跨版本预检与环境无关化测试）：
- MCP 超时分类的 Python 3.10 兼容：`mcp_hub.py` 新增 `_TIMEOUT_ERRORS` 别名元组并替换全部 7 处超时捕获。根因是 `asyncio.wait_for` 超时抛的 `asyncio.TimeoutError` 与内建 `TimeoutError` 在 ≤3.10 是两个类，3.11 才合并——旧代码只捕内建类，3.10 上超时落进通用 Exception 分支被误分类为 error（仅 3.10 job 可见，3.12/3.14 无法复现）。
- 白名单测试环境无关化：`test_put_config_accepts/rejects_*` 改用回环字面量地址验证「同一主机，白名单开→收、关→拒」——不再依赖真实域名解析，fake-ip 代理机与 CI 公网 DNS 行为一致。
- 本地新增 `.venv-ci310` / `.venv-ci312` 预检环境（`.gitignore` 已加 `.venv-*/`）；修复后三版本全量对齐：**py310 = py312 = py314 = 1159 passed / 3 skipped**。

### 2026-08-24 - SenseNova 接入验证与 SSRF 白名单/推理模型修复

接入实测（商汤日日新免费测试 key，OpenAI 兼容端点 `token.sensenova.cn/v1`）暴露并修复两个真实可用性问题，端到端已验证：探测 1.4s、`/soul/chat` 对话 1.8s 真实回包。
- SSRF 主机白名单单源化扩展：解析入口下沉到 `security.ssrf.extra_allowed_hosts()`（推荐名 `WANWEI_SSRF_EXTRA_ALLOWED_HOSTS`，与历史名合并去重），并全仓统一消费——模型网关三原生通路、providers 写入/本地探测/OAuth 设备流、automation http 步骤、MCP 远程传输、系统服务镜像下载与语音转写共 9 类外呼路径同口径；消除「能连的主机存不进去/跑不动」的分裂。白名单外的主机维持拦截。
- 推理模型空回复修复：三家协议统一处理「输出全在推理字段」的情形——openai 兼容通路回退 `reasoning_content`；anthropic 原生回退 thinking 块；gemini 原生优先取非 thought 部件、为空时回退思考文本。此前 deepseek-r*/v*、Claude 扩展思考、Gemini 2.5 思考型均可能得到「成功但空回复」（gemini 还会把思考片段混入正式输出）。
- 镜像下载残留竞态加固：失败路径在写终态前先清理 `.part`，保证「error 状态对外可见时必无残留文件」。
- 新增回归测试 `test_ssrf_extra_hosts_unification.py`（9 例：单源解析 / 各路径 allowlist 实参捕获 / 三协议空输出回退）及其它配套用例；README「真实边界」补充代理共存说明。

### 2026-08-24 - MCP sse / streamable_http 真实传输

- MCP hub 三种传输全部真实化：sse（GET 事件流拿 endpoint 事件 + POST JSON-RPC 在流上等配对响应）与 streamable_http（POST `Accept: application/json, text/event-stream`，兼容纯 JSON 与 SSE data 帧响应、遵循 Mcp-Session-Id）按 JSON-RPC 2024-11-05 实现 initialize → tools/list → tools/call 完整握手；超时沿用服务器配置的单次请求预算。
- 每次真实连接前重跑 resolve_external_url pinned-IP 解析（IP 钉住 + 原始 Host/SNI + trust_env=False + 不跟随重定向）；新增显式精确主机白名单 env `WANWEI_MCP_HTTP_HOST_ALLOWLIST`（默认空 = 全拒），写入校验与连接前双重检查。
- stub 语义诚实迁移：三种已实现传输的 stub 分支删除——缺配置/连接失败/协议错误一律如实返回 error（调用侧保留 503 server_not_connected 契约但记录 mode:'error'），stub 仅保留给未来新增传输类型的兜底。相关既有断言同步更新。
- 新增回归测试 backend/app/tests/test_mcp_sse_http_transports.py（13 例：双传输往返 / SSE 帧解析 / 500·脏数据·断连·超时降级 / 写入期与连接期 SSRF 拦截）。

### 2026-08-24 - Bedrock SigV4 与 OAuth 设备授权真实通路

- AWS Bedrock InvokeModel 真实调用接通：model_gateway 手工实现 SigV4 签名（无需 boto3），签名离线对齐 AWS 官方测试向量（get-vanilla / post-vanilla）；请求走既有 pinned-IP SSRF 防护通道，SECRET 只参与签名派生，绝不出现在 URL、payload 或任何响应中。凭据格式固定为 `ACCESS_KEY_ID|SECRET_ACCESS_KEY`（Fernet 加密落盘，绝不回显；格式错误在发出任何网络请求前即拦截并映射 not_configured 语义），region 从 api_base 主机名自动提取。当前适配 meta.llama*（prompt 体）与 amazon.nova*（messages-v1 体）两类模型体，其余家族如实拒绝 unsupported_model_format，绝不猜测协议。
- 对话选择链同步放开：`aws_bedrock` 移出 `get_active_provider()` 的协议未实现集合，接入舱启用后 `/soul/chat` 即经统一分发器 `_provider_dispatch` 路由到 Bedrock 原生通路；OAuth-only 三家仍不参与对话自动选择。
- RFC 8628 OAuth 设备授权状态机落地：`/platform/providers/auth/{pid}/begin|poll` 真实对接 GitHub Copilot 与 Google Vertex AI 官方设备码端点（pinned-IP + SSRF 校验）。client_id 取自 provider 配置的 extra.client_id 或环境变量 `WANWEI_OAUTH_CLIENT_ID_{PID}`，缺失时如实 501 并说明配置方式，绝不伪造 verification_uri/user_code；pending 态（device_code/user_code/interval/expires_at）存 JsonStore 带 TTL 过期清理；poll 按 authorization_pending / slow_down（后续间隔 +5s）/ expired_token / access_denied 四态处理，成功后令牌 Fernet 加密入库且任何路径不回显明文；无 begin 先例时 poll 如实 409，绝不虚构 authorized。
- 诚实边界：DashScope（通义千问 OAuth）官方设备授权端点尚未公布，qwen_oauth 的 begin/poll 保持如实 501「待核实」，即使配置了 client_id 也不发起任何设备码流程。
- 新增回归测试 `backend/app/tests/test_bedrock_sigv4_and_oauth_device.py`（26 例）：SigV4 官方向量离线校验 / invoke 请求构造与凭据不回显 / 目录条目与 not_configured 语义 / 设备授权全状态机与诚实红线 / 对话路由。

### 2026-08-24 - 梦境调度与下载/转写真实化

- 记忆中枢梦境归档支持每日定时自动触发：新增 `GET/PUT /platform/memory/dreams/schedule`（持久化于 `JsonStore('memory_center')` 键 `dream_schedule`；HH:MM（UTC）校验、默认 03:00），GET 返回的 enabled/time/last_run/next_run 全部实时计算；router lifespan 内挂 asyncio 调度协程，到点复用 `/dreams/archive-now` 函数本体触发一次整理，last_run 同日幂等防重复。宕机跨过当日时刻当天内补跑一次，跨天不补；默认仍关闭（enabled=false 协程空转、零副作用）。
- 模拟器镜像下载真实化：配置 `WANWEI_EMULATOR_IMAGE_URL`（可选 `WANWEI_EMULATOR_IMAGE_SHA256`）后，镜像下载改为 httpx 流式真实拉取——pinned-IP 连接、`.part` 临时文件原子改名落盘 `data/platform/downloads/`、进度按真实字节/Content-Length 推进、SHA256 不匹配报错并丢弃内容、cancel 真正中断并清理残留。
- 语音转写真实化：配置 `WANWEI_ASR_BASE_URL` 与 `WANWEI_ASR_API_KEY`（可选 `WANWEI_ASR_MODEL`，默认 whisper-1）后，对已存档音频以 OpenAI 兼容 multipart 调用 `/audio/transcriptions` 真实转写并回填文本；调用失败如实降级为仅存档，API key 绝不落盘。
- 诚实边界：上述任一 env 未配置时保持既有行为与文案逐字不变——镜像下载维持模拟推进（每 0.5s 推进 2%，标注 simulated:true），语音转写维持「仅存档」stub 标注；不为配置缺失虚构成功结果。
- 新增回归测试 `backend/app/tests/test_dreams_schedule_and_downloads.py`。

### 2026-08-24 - 自动化工作流真实执行（gear 门禁）

- 自动化工作流（`platform_api.automation`）按执行档位 gear 三档启用真实执行：`human_review`（默认档）仅表示等待人工审查，运行一律 dry-run 模拟；`sandbox`/`device` 为显式选择的可执行档，`/flows/{fid}/run` 与定时触发进入真实执行。旧流程与旧 run 记录无 gear/mode 字段时读取视图自动回填（gear→human_review、mode→dry_run），行为不变。
- 五类步骤的真实执行方式与安全约束：
  - shell：复用 `_system_svc_runtime` 沙盒白名单校验（命令名与逐个参数均在白名单内、拒绝元字符），cwd 监禁 `data/platform/sandbox/`、最小环境变量、5s 超时、stdout/stderr 各截断 4KB；白名单外命令一律 failed 并在 detail 写明原因，绝不静默放行。
  - http：仅 GET/POST，URL 先过 `resolve_external_url` SSRF 校验再以 pinned-IP 直连（httpx `trust_env=False`、不跟随重定向、10s 超时、响应体截断 4KB）；非 2xx 如实 failed 带状态码。
  - memory：写入前过 Policy Gate 预检，拦截即 failed 且内容不落库并落 `policy_blocked` 审计；正常内容经 capsule_store 真实写入后可按胶囊 id 读回。
  - condition：仅 ast 字面比较的安全求值，函数调用/动态导入/未知名称/语法错误如实 failed。
  - agent：复用 agents 模块 `_try_gateway` 网关回退链，网关不可用时如实 failed，不回退模拟文本。
- 新增显式模拟入口 `POST /flows/{fid}/simulate`：对任意档位（含 sandbox/device）强制 dry-run 预演，真实执行入口仍是 `/run`；device 档未显式授权（环境变量门禁）时 fail-closed，步骤 failed 且运行不留 running 假死。
- run 记录新增 `mode` 字段（`'real'|'dry_run'`）；真实执行起止各落一条审计事件 `flow_run_started` / `flow_run_finished`（payload 带 mode 与终态 status）。
- 诚实边界：human_review 默认档绝不变成可执行授权——默认流程的行为与修复前完全一致（模拟执行、仅返回 would_run 说明）；ai-edit 规则解析不擅自改动 gear，编辑现有流程保留原档位、新建提案归一为 human_review。
- 新增回归测试 `backend/app/tests/test_automation_real_exec.py`（17 例）：dry-run 保持 / shell 白名单命中与拒绝（含路径越界与元字符）/ http 往返与 404 与 SSRF 拦截 / memory 写入拦截与读写往返 / condition 合法与非法求值 / agent 网关可用与不可用 / device fail-closed / gear 默认值与旧记录兼容 / simulate 强制模拟 / on_error=stop 跳过语义 / 起止审计事件。

### 2026-08-24 - DeepSeek 等云端模型真实调用通路

- 打通「模型接入舱 → 对话引擎」链路：`/soul/chat` 现优先消费模型接入舱中用户显式启用的云端 provider（新增 `platform_api.providers.get_active_provider()`：按目录顺序取第一个 enabled 且密钥可解密、base_url/model 齐备的配置；OAuth-only 与 SigV4 协议不参与选择，azure_foundry 占位端点在改写 base_url 前视为不可用），无启用配置时回退既有 `WANWEI_OPENAI_COMPATIBLE_*` 本地端点。DeepSeek 官方接口（OpenAI 兼容）自此端到端真实可用：连通性测试与对话共用 model_gateway 的 hardened smoke path（pinned-IP SSRF 防护 + 有界专用线程池；Fernet 解密后的密钥仅进调用头，绝不回显）。
- `/soul/chat` 响应的 `provider` 字段如实回实际来源（如 `deepseek`），不再笼统标 `openai_compatible`；失败仍如实 `provider_error`，不回退 mock。
- 智能体运行（`platform_api.agents`）网关回退链接入同一事实源：agent 未绑定 provider 时自动使用接入舱中已启用的云端 provider；调用统一经 `_provider_dispatch` 分发，anthropic/gemini 绑定走原生协议。
- `google_ai_studio` 作为 Gemini 原生协议别名分发到 `_gemini_smoke`，并剥掉目录默认端点尾部 `/v1beta` 避免双重前缀。
- model_gateway provider 目录新增 `deepseek` 条目；`/model-gateway/test` 对其不再返回 not_implemented。
- 新增回归测试 `backend/app/tests/test_deepseek_real_chat_path.py`（13 例）、`test_agents_gateway_chain.py`（4 例）：选择语义 / 对话路由 / 失败诚实 / 回退契约 / 目录与别名。
- README「真实边界」同步更新：31 家接入中 OpenAI 兼容云端供应商（含 DeepSeek）已接通真实调用；AWS Bedrock（SigV4）与 OAuth-only（通义千问 OAuth / GitHub Copilot / Google Vertex AI）尚未接通，如实保留未实现状态。

### 2026-08-24 - MemoryOS 记忆治理层

设计规范见 `AI优化/MemoryOS-*.md`（Lifecycle 状态机 / Governance 账本 / Accounting
经济账本 / Health 健康度 / Benchmark Harness 五份草案；该目录为本地设计材料，未纳入
版本库，代码注释里的路径是出处标注而非仓库内路径）。实现见
[docs/MemoryOS-记忆治理层.md](docs/MemoryOS-记忆治理层.md)。

- 新增 `backend/app/memoryos/` 记忆治理包（约 3.6k 行，223 个测试函数、参数化展开后 277 项），与 `memory_runtime/` 平级协作而非取代：
  - `lifecycle`：10 态生命周期状态机。此前 `state.lifecycle` 是各处直接赋值的自由字符串，`deleted → active`、`forgotten → reinforced` 这类「已删除记忆被复活」的写入无人拦截；现由转移表裁决，非法转移经 `POST /memory/lifecycle/transition` 返回 422 而非静默放行。`forgotten`/`deleted` 不可回到任何可检索状态。
  - `governance`：`memory_ledger` 不可变账本（actor、内容 SHA-256 前后哈希、独立 `risk_class` 列，**append-only 由 SQLite 触发器强制**，UPDATE/DELETE 直接 ABORT）、Provenance Card、五处删除完整性验证（主表 / FTS / 图边 / 向量引用 / legacy）、MHG 1–5 级事故分级与发布冻结。
  - `accounting`：逐条记忆的成本-收益-ROI 账本。收益信号取自既有 `evolution.reflect_task` 的 `helpful_memories` / `misleading_memories`，不需要新的用户输入；检索侧记账挂在 `bump_usage_batch` 已有事务内并复用 60 秒时间窗门控，搜索路径**不新增写往返**。
  - `health`：MHS 综合分 + Health / Decay / Self-Knowledge 三面板 + 7 天趋势曲线。
  - `harness`：MEB/MHEB 评测 runner，5 类用例 × 4 维加权（ux .4 / safety .25 / product .25 / academic .1），产出前先过 `report_contract` 校验。
- 修复功能断链：`capsule_store` 原先只在 `lifecycle == 'active'` 时写 FTS，而没有任何代码把 candidate/quarantined 转成 active 并补写索引——被人工确认过的记忆永远搜不到。`apply_transition` 现承担 FTS 同步（转入可检索态先 DELETE 再 INSERT 防重，转出 DELETE），「确认后的 candidate 可检索」与「quarantined 不可检索」两条验收标准至此才真正成立。
- 修复 `run_suite` 中健康度快照采样引用未定义变量导致的静默失效：宽 `except` 曾把该 `NameError` 咽成一行 warning，评测照报「通过」而趋势曲线整轮无数据。现编码错误（NameError/TypeError/AttributeError）直接抛出，只有环境性故障降级为 warning，并补回归测试断言快照条数。
- 新增四张表（均在主库，账本可与业务写入原子落库）：`memory_ledger`、`memory_accounts`、`memory_incidents`、`memory_health_snapshots`。
- 新增 20 个 `/memory/*` 与 `/memoryos/*` 端点，默认受 `APIKeyMiddleware` 保护并按 owner/soul 作用域隔离，跨属主请求返回 404 不泄漏存在性。删除验证端点的授权来源是**账本而非主表**——硬删后主表已无行，用主表鉴权会让「验证一条已被彻底删除的记忆」永远 404，而那恰是最需要验证的情形。
- 新增 `scripts/run_meb.py` 与 `.github/workflows/memory-bench.yml`：每 PR 跑 Mini-MEB 门禁，每日 full / 每周 redteam。评测默认在临时库中运行，不继承 `WANWEI_MEMORY_DB`。
- 修复回归门禁空转：基线原先取单槽的 `reports/meb_score_report.json` 并在 `suite` 不同时跳过对比，而 per-PR 写 mini、每日写 full、每周写 redteam，无论提交哪一份都至多匹配一种流程，其余永远打印「套件不同，跳过对比」——门禁看着在跑却从不触发。改为按套件分文件（`reports/meb_baseline_{mini,full,redteam}.json`），判定逻辑移入 `harness.compare_to_baseline` 以便本地复现与 pytest 覆盖，并区分 `ok` / `regressed` / `no_baseline`（不失败但打印创建命令）/ `malformed`（坏基线会让门禁永久失效，判失败）。跌幅比较使用已舍入的差值，避免 `1.0 - 0.95 = 0.050000000000000044` 这类浮点噪声让日志显示「下降 5.00%（阈值 5%）」却判失败。
- 新增 MQ（Memory Quotient）能力画像与 `GET /memoryos/mq`（规范 `AI优化/MemoryOS-IQMQ双轴框架.md` §10.3）：把已有 5 类 MEB 用例换成能力视角读法——安全治理 .30 / 检索效率 .20 / 更新正确性 .20 / 写入精度 .15 / 遗忘可控性 .15（权重为本项目选择，规范只列子能力未给权重；安全最高是因为被投毒的记忆会让 Agent 主动做错事，与"少记一条偏好"不对称）。与 `category_breakdown` 同源，不会给出互相矛盾的两个分数。三条诚实约束由 `report_contract` **强制**而非文档声明：未覆盖子能力为 `null` 而非 0（总分只按已覆盖项归一，否则 redteam 套件的 MQ 会被压到 0.30 读起来像"能力极差"）；`iq` 非 null 即报 `iq_must_be_null_this_system_does_not_measure_it`（留一个能填数字的 IQ 字段早晚会有人塞估算值）；不输出 IQ×MQ 象限定位（象限需要两个坐标，只有 MQ 时宣称象限就是编造）。旧格式报告返回 409 并给重跑命令，不在读路径上临时算分数——否则分数会失去出处。
- 与规范的有意偏差（理由见实现文档）：冲突裁决败方默认转 `deprecated` 而非规范的 `deleted`（保留裁决现场证据）；`stale` 为「可检索但降权」，仅在高风险查询下排除；批量遗忘对非法转移跳过并列入 `rejected_transitions` 而非整批失败。
- 未实现项如实记录：`AI优化/MemoryOS-白皮书结构.md` 的 8 章白皮书为写作交付物，本轮未撰写；`AI优化/1.txt` 的 L0–L4 分层与 LoRA 慢速固化属研究方向，需本地模型训练能力，超出本仓范围；规范的「每月 Benchmark Sync」无仓库外用例源可同步。
- 诚实边界：成本金额基于「字符数 × 0.3」token 估算而非实测用量，响应带 `honesty_note` 明示；无实跑评测报告时 `precision@5` 输出 `null` 且 MHS 跳过该维度（未采纳参考实现硬编码 `0.9` 的做法）；被闸门拦下的投毒尝试记为 `poisoning_blocked` 且不扣健康分；MEB 当前仅有公开集（`hidden_cases=0`），规范的「每月 Benchmark Sync」未实现；pass_rate 1.0 是本仓自建用例集上的结果，与 LongMemEval / BEAM 等公开赛题不可比。发布冻结刻意不并入 `/health/ready`——治理冻结发布不等于实例不可用。

### 2026-08-04 - Issue #38 安全与韧性收尾

- 修复自动化流程部分更新的并发丢字段问题，创建/更新/运行记录继续在持久化锁内完成，并补充确定性并发回归测试。
- 将 `/soul/chat` 的真实 OpenAI-compatible 调用接入有界专用线程池，并改为异步路由等待；模型网络阻塞或队列满时不会占满 Starlette/AnyIO 默认工作线程，失败仍明确返回 `provider_error`。
- 收紧 owner/Soul 作用域、平台服务 gear 门禁、MCP stdio 命令与参数校验、密钥/环境隔离和边界容错；MCP 解释器或包启动器白名单继续按高信任任意代码执行边界管理。
- 将后端 `cryptography` 锁定版本升级至 `50.0.0`，消除 CI 供应链审计报告的已知漏洞版本。
- 兼容 Python 3.10 的 `asyncio.TimeoutError` 超时语义，避免跨平台模型池截止时间被误升级为未处理异常。
- 补充 owner 与 Soul 隔离、自动化 dry-run、device gear 和 MCP 高信任边界文档；本条目不代表已发布版本或正式签名产物。

### 2026-08-03 - 平台输出与会话容错加固

- 知识检索在最新、FTS 与 LIKE 三条返回路径统一返回规范化的原始文档标题，保持 API 与 CRUD 契约一致；FTS 正文仅保留系统生成的高亮标记并继续转义不受信内容，前端使用 Vue 文本插值完成渲染编码。
- 会话列表会将无法转换为有限整数的脏数据安全归零，不再因单条异常记录中断整体响应。
- 容器集成测试改为运行时生成临时加密密钥，不再保留固定测试密钥。

### 2026-08-03 - PR #37：情感衰减并发与空间提交路径安全

- 情感衰减写回改用包含完整状态快照的乐观锁；检测到并发状态更新时跳过本轮衰减，避免覆盖新提交的情感变化。
- 空间提交的文件列表在组装 `git add` 前统一规范化并校验仓库根边界，拒绝绝对路径、越界路径、空路径、NUL 字节及指向仓库外的符号链接。
- 路径边界改用 `realpath`、`commonpath` 与仓库相对路径转换，消除未校验用户路径进入文件系统表达式的静态污点链。

### 2026-08-03 - Persona 与系统提示注入治理

- persona 的名称、特质、表达风格、价值观和自我叙述在写入前统一经过策略检查，并对跨字段拆分载荷进行组合判定；拒绝结果由 API 明确返回 422 且不落库。
- 系统提示在完整组装后再次执行策略检查，安全降级文本不再引用可能由旧版本写入的不可信 persona 内容。
- `redact` 记忆在列表、单条查询、搜索、命令召回、遗忘预览、Soul 状态、系统提示和研究复现图等外发路径递归脱敏；存储原文保持不变。
- 情感状态转换仅接受有限的 `0..10` 强度和受支持的 trigger；针对幽灵 Soul 的转换请求明确返回 404，零强度不再意外切换 mood。
- 知识文档创建、更新和批量导入统一限制单篇正文不超过 100,000 字符；批量导入会跳过单条超限正文并继续处理有效条目。
- 保留模型网关 `PROVIDERS` 导入兼容快照至 v0.12，并将 MCP stdio 缺失 stdin 的断言改为生产环境仍生效的明确错误。

### 2026-08-03 - Electron 43 桌面安全升级

- Electron 升级至 43.2.0、electron-builder 升级至 26.15.3，清理旧桌面构建依赖中的高危与严重漏洞，并同步迁移 Linux desktop 配置。
- 新增 deb/rpm 实际打包门禁，校验桌面入口元数据、运行时依赖、desktop 依赖审计与产物哈希；麒麟桌面的安装、渲染、托盘和窗口关联仍以目标机验收结果为准。
- deb/rpm 安装会强制校验 Electron 沙箱权限，最终卸载会清理复制的 systemd 用户服务；CI 增加 deb 实装、沙箱权限与无残留卸载门禁。
- deb/rpm 安装会安全创建 `wanwei-shuyi-desktop` 命令行入口，拒绝覆盖管理员已有文件或外部链接；最终卸载仅清理仍指向本应用的入口与空安装目录，deb/rpm 的重装升级流程均纳入实装门禁。
- 桌面端启动前会验证缓存 Python 环境的关键原生扩展；依赖哈希失效或导入失败时完整重建 venv，修复麒麟系统安全元数据变化后后端无法启动的问题。
- 桌面包会携带总览页所需的 Arena 指标报告；后端与 deb/rpm 打包共用同一校验契约，报告缺失、格式无效或计数与比率矛盾时拒绝成功响应/产物，不再把缺失字段渲染为 `undefined`。
- 托盘新增浮动工作区显示开关并跟随窗口的真实可见/最小化状态；无边框小窗增加始终可用的拖动标题区，并将按钮、输入框与链接排除出拖动捕获，恢复显示、拖动和隐藏。首次使用仍需完成手机伴侣配对，已配对桌面会话可直接交互。

### 2026-08-03 - Node 22 构建工具链

- 源码构建、CI 与容器前端构建基线升级为 Node.js 22；setup 脚本会拒绝不满足要求的旧版本。终端用户安装已打包的 deb/rpm 不受此构建侧要求影响。

### 2026-07-12 - 文档中心整合

- 根目录文档中心收录原 docs/*.md 的全文内容、稳定锚点、来源元数据和 SHA-256。
- README、交付导出、研究吸收、工具注册、工作流和深做契约的文档引用统一指向文档中心锚点。
- 文档中心保留为根目录唯一入口；已收录的源文档与一次性生成脚本不再单独保留。
- 发布预检改为验证文档中心及部署、运维、发布清单锚点，不再依赖已收录的 docs/*.md 源文件。
- README 重构为当前可运行能力、验证证据、启动/验证入口和真实边界，避免把 partial/planned 或环境特定结论写成通用生产能力。

### 2026-07-12 - PR #21：麒麟 VM 证据与向量删除硬化

- 合并提交：3e38918。
- 在 Kylin V11 2603 x86_64 QEMU/WHPX VM 的捕获源码快照中，记录官方 embedding/vector Bridge 的构建、状态探测、写入、语义检索、遗忘删除、历史重建和延迟原始证据。
- 将 Capsule 本地遗忘、delete_pending、审计和遗忘票据纳入事务状态机，并加入 generation fencing、删除 claim、tombstone 和有界 sweeper，防止晚到 upsert 或陈旧回放复活向量。
- SDK 不可用或原生操作失败时保持 SQLite FTS5 显式后备；失败 Capsule 的后备检索与统计保持有界和可审计。
- PR 远端检查全部成功。VM 结论仅适用于捕获源码快照和该 VM，不覆盖最终合并 SHA、物理硬件、LoongArch/ARM、OCR、大规模数据、长期稳定性或 SLA。

### 2026-07-11 - PR #20：原生 SDK 优先检索

- 合并提交：9f5c9e4。
- 新增官方 Kylin text-embedding/vector-engine SDK 的 C++17 stdin/stdout JSON Bridge，配置显式 bridge 路径并约束输入输出协议。
- 原生 SDK 可用时优先向量检索；不可用或失败时显式回退 FTS5；补充索引映射、治理写入/删除和有界历史 reindex。
- 当时主机不具备厂商 ABI/工具链，目标 VM 的真实 SDK 行为与性能证据在后续 PR #21 单独记录。

### 2026-07-11 - PR #19：Kylin VM 兼容性工具

- 合并提交：98c694f。
- 新增 QEMU/WHPX Kylin V11 启动脚本、仅监听 127.0.0.1:5959 的 QMP 键盘辅助脚本和 VM 测试计划。
- 此项提供安装、磁盘启动和图形登录的复现工具，不等同于 SDK 或目标硬件认证。

### 2026-07-11 - PR #18：人工依赖治理

- 合并提交：5513355。
- 移除自动版本升级和自动安全修复 PR，改为人工按生态、兼容边界和验证结果审阅依赖变更。
- 保留漏洞告警、Dependency Audit/Review、CodeQL、Trivy、Secret Scanning 和 Push Protection。

### 2026-07-10 - v0.10.0 交付硬化、赛题校准与审阅门槛

- 合并提交：2b38255；相关提交：0e0dc65、9a8a6b0。
- 增加非 root 多阶段 Docker 镜像、安全默认 Compose、Windows/Linux setup、smoke、verify、backup 和 secret 初始化脚本。
- 增加 health/readiness、受保护 metrics、请求 ID、SQLite 在线备份、完整性校验、停机恢复、生产密钥强度和可信代理限流边界。
- 增加跨平台 CI、HTTP/容器 smoke、CodeQL、依赖审查、Trivy、SBOM 和发布前检查；README 明确 alpha、赛题就绪度和未验收边界。
- v0.10.0-delivery-hardening 仍为 in_progress；公开 Release 的许可证前置条件已满足——项目所有者已选定国产开源许可证木兰宽松许可证第2版（Mulan PSL v2），全文见根目录 LICENSE。

## 2026-07-09 - v0.9.6.2 CI/CD 清理

- 相关提交：753057b、01a9d41、19e7cea、2e34327、69e63c4。
- 修复主分支与 PR pipeline 依赖路径和入口，统一 PR 目标为 main，移除失效的 master pipeline。
- 删除未使用的 guardrail 死代码和历史认证辅助函数，保留 APIKeyMiddleware 作为认证主路径。
- 新增中文更新日志。

## 2026-07-08 - v0.9.6.1 静态扫描修复

- 相关提交：7d0cb7e、4b4d890。
- 修复静态扫描发现的问题并完成合并。

## 2026-07-06 - v0.9.6 限流与测试硬化

- 相关提交：4555bfa、1a12160。
- 增加限流、核心路径测试、性能基线工具、批量查询优化、线程本地连接复用和 WAL。
- 移除 workflow 内存 fallback，运行记录统一经 SQLite 持久化。

## 2026-07-05 - v0.9.5 持久化与 v0.9.4 安全基线

- v0.9.5 相关提交：da7f741、3d191f9。新增 workflow run SQLite 持久化、TTL 清理、时区感知 UTC 和 FastAPI lifespan 迁移。
- v0.9.4 相关提交：b05663e、7b4c3c2、870b967。修复 SSRF、认证、敏感 GET、审计和 Policy Gate 安全边界。
- v0.9.3 相关提交：fbcd665。完成 workflow run dry-run、阶段编排、trace 和 artifacts API。

## 2026-07-04 - v0.9.1 深做层与 GitHub 迁移

- 相关提交：026e9e8、24862c6、c282d75、d59ea81、b3cf2ce。
- 新增深做追问、视觉验证、契约检查和安全 dry-run 接口。
- 初始化 GitHub 仓库和默认 pipeline 模板，完成 Gitee 到 GitHub 的迁移。

## 2026-07-03 - v0.9 至 v0.4 平台、运行时和治理基础

- v0.9：3618454，新增轻量研究系统复现层。
- v0.8：e18e271，新增权威技术吸收矩阵和研究吸收控制台。
- v0.7：d5dfc2c，扩展 MemoryOps Autopilot 平台和 20 舱 Studio。
- v0.6：13ea153、a9e5d8a、bf42238、a156094、744ac61，新增运行时、MemoryArena-Lite、复盘 case、误召回风险 case 和 source-layer 原则。
- 前端与工程：44e8fd7、502ecac、cc4c017，新增 Vue 控制台并移除受跟踪的 node_modules。
- v0.5：a4bf334、5dfbd58、fd0e187、fbe1ff8、4b4fae7，建立偏好/知识记忆架构、MemoryCapsule v2、监督闭环和生产评测规范。
- v0.4：63e2a55、264ddc1、685191e、31dc027、a2fd551，建立记忆治理、安全评测、ASI 风险映射和权威参考基础。

## 2026-07-01 - v0.3.1 初始项目

- 相关提交：f65214f。
- 初始化宛委·枢忆 OSAgent 项目，建立早期 Memory OS、情感感知记忆和安全边界文档基础。
