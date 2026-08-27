# MemoryOS 记忆治理层

> 实现状态：已落地并有测试覆盖（199 个测试函数，参数化展开后 246 项）。
> 规范来源：仓库 `AI优化/` 下的五份草案 + `MemoryOS-core参考实现.md`。
> 本文档记录**实际实现**与规范的差异，以及每处偏差的理由——不是规范的复述。

## 为什么要这一层

记忆底座（`backend/app/memory_runtime/`）解决的是「存得下、搜得到」。治理层解决的是
另外三个问题：

- **它凭什么在这里**：来源、写入意图、置信度、版本链 → Provenance Card + 账本
- **什么时候该走**：过期、冲突、被推翻、被遗忘 → 生命周期状态机
- **值不值得留**：成本 vs 收益 → 经济账本 + 健康度

上线前，`state.lifecycle` 是一个各处直接赋值的自由字符串（`evolution.reinforce` /
`deprecate` / `conflict_mark` 直接写，`capsule_store.forget_capsules_in_transaction`
也直接写），没有任何一处校验转移是否合法。`deleted → active`、
`forgotten → reinforced` 这类「已删除记忆被复活」的写入无人拦截。对一个以记忆治理
为卖点的系统，这是数据完整性缺口。

## 模块结构

```
backend/app/memoryos/
├── lifecycle.py        926 行  状态机（转移裁决 + FTS 同步 + 账本副作用）
├── health.py           629 行  MHS 健康度 + 三面板 + 趋势快照
├── harness.py          611 行  MEB/MHEB 评测 runner
├── governance.py       500 行  账本 / Provenance / 删除验证 / MHG 分级
├── export.py            owner-scoped 脱敏 Markdown/JSON 证据导出与 SHA-256 完整性摘要
├── accounting.py       460 行  成本-收益-ROI 经济账本
├── report_contract.py  139 行  score_report.json 校验契约
└── cases/public/*.json          5 类公开用例集
```

**依赖方向（防循环导入）**：`memoryos.*` 可在模块级 import 基础设施
（`..db` / `..utils` / `..audit`）；对 `memory_runtime.*` 的依赖一律**函数内局部
import**。反向地，`memory_runtime.*` 只从 `lifecycle` 的**纯词表段**（枚举、转移表、
常量，无 DB 访问）做模块级 import。这沿用仓库既有做法（`capsule_store` 局部 import
`vector_index`、`evolution` 局部 import `tier_manager`），不引入新范式。

## 生命周期状态机

状态词表沿用项目既有的 9 个词 + 新增 `stale`，**不照搬规范改名**：规范的 `archived`
在本项目一直叫 `deprecated`，改名会波及 60+ 测试文件且零收益。

| 规范状态 | 本项目状态 | 说明 |
| --- | --- | --- |
| archived | `deprecated` | 同义：主动归档 / 自动降权 |
| （无对应） | `rejected` | 策略闸门拒绝，内容从未落 FTS |
| deleted 细分 | `forgotten` | 软删（保留行，可升级为硬删） |
| deleted 细分 | `deleted` | 硬删（行已消失） |
| stale | `stale` | 本次新增，此前完全不存在 |

合法转移表（`lifecycle.TRANSITIONS`，与代码一致）：

```
candidate    -> active, rejected, quarantined, forgotten, deleted
active       -> reinforced, stale, conflicted, deprecated, quarantined, forgotten, deleted
reinforced   -> active, stale, conflicted, deprecated, quarantined, forgotten, deleted
stale        -> active, reinforced, deprecated, forgotten, deleted
conflicted   -> active, reinforced, deprecated, quarantined, forgotten, deleted
deprecated   -> active, forgotten, deleted            # restore
quarantined  -> active, rejected, forgotten, deleted  # release 须显式确认
rejected     -> deleted
forgotten    -> deleted                               # 软删升级为硬删
deleted      -> ∅                                     # 终态
```

最关键的一条约束：**`forgotten` 与 `deleted` 都到不了任何可检索状态**——已遗忘的
记忆不可复活。

可检索状态集是唯一真相源（`RETRIEVABLE_STATES = {active, reinforced, conflicted,
stale}`），`capsule_store` 与 `retrieval` 都从这里取，避免各写一份 `IN` 列表而漂移。

### 顺手修掉的功能断链

`capsule_store` 原先只在 `lifecycle == 'active'` 时写 FTS，而**没有任何代码把
candidate/quarantined 转成 active 并补写索引**——也就是说被人工确认过的记忆永远搜不到。
`apply_transition` 现在承担 FTS 同步：转入 `{active, reinforced, conflicted, stale}`
且 policy ∈ `{allow, redact}` → 先 DELETE 再 INSERT（FTS5 无唯一约束，必须先删防重）；
转出 → DELETE。「确认后的 candidate 可检索」和「quarantined 不可检索」两条验收标准
至此才第一次真正成立。

### 与规范的有意偏差

1. **`resolve_conflict` 的败方默认转 `deprecated` 而非规范的 `deleted`。**
   规范 §2 写「loser 进 deleted（账本保留）」。但本项目 `deleted` 是硬删（行消失），
   裁决失败的一方直接物理删除会让「当初为什么这么裁决」失去现场证据。默认改为可审计的
   `deprecated`，需要物理删除的调用方显式传 `loser_state`。
2. **`stale` 是「可检索但降权」而非「不可检索」。** 规范原表把 stale 标为
   「⚠️（低权重或弃权）」，因此纳入 `RETRIEVABLE_STATES`，在 `retrieval` 侧按
   `RETRIEVAL_SCORE_PENALTY` 扣固定分数（排在同等条件的新鲜记忆之后），而不是从
   候选集剔除。「弃权」那一半语义落在高风险查询上：`HIGH_RISK_EXCLUDED_STATES`
   把 `conflicted` 与 `stale` 一并排除，此时 trace 里会记
   `high_risk: exclude conflicted/stale`。上线前库中不存在任何 stale 行，此改动对
   既有数据的检索行为影响为零。
3. **批量遗忘对非法转移是跳过并上报，不是抛异常。**
   `forget_capsules_in_transaction` 的既有契约是「跳过查不到的 id」而非整批失败，
   因此非法转移同样按跳过处理并列进返回值的 `rejected_transitions`。单条操作
   （`POST /memory/lifecycle/transition`）才硬抛 `IllegalTransitionError` → 422。

`IllegalTransitionError` 继承 `ValueError`，因为 `app_runtime` 的 tier 端点已有
`except ValueError` 处理链，继承可保证既有错误路径不变。

## 账本与治理

`memory_ledger` 与既有 `audit_logs` **并存而非取代**。审计表记全应用范围的操作留痕；
账本是记忆域的专用账目，多出四样正是规范要回答的问题：

- `actor` —— 谁做的（human / agent / system / 插件名）
- `before_hash` / `after_hash` —— 内容级 SHA-256，可证明「改了什么」
- `risk_class` —— 独立列而非埋在 payload JSON 里，可直接聚合
- **append-only 由 SQLite 触发器强制**，不是文档声明：任何 UPDATE/DELETE 都
  `RAISE(ABORT)`，篡改账本必须先改 schema，而 schema 改动会留在版本历史里

账本写入与业务写入**同事务**（复用 `audit.service.record_in_transaction` 的契约），
保证「记忆存在 ⇔ 有账目 ⇔ 有账户」三者不脱节。被策略闸门拒绝的写入也留账
（`op_type='write_rejected'`）——被拒记忆没有主表行，账本是唯一留痕处。

**删除完整性验证**（`verify_deletion`）逐项检查主表 / FTS / 图边 / 向量引用 / legacy
五处，规范里这是 MHG-5 一票否决项。该端点的授权来源是**账本而不是主表**：硬删后主表
已无行，用 `get_capsule` 鉴权会让「验证一条已被彻底删除的记忆」永远 404——而那恰恰是
最需要验证的情形。

**MHG 事故分级**：未解决的 MHG≥3 置起发布冻结（`/memory/governance/release-gate`）。
刻意**不并入 `/health/ready`**：治理冻结发布不等于应用不可用，混进就绪探针会让编排
系统误杀一个健康实例。端点只登记应做的响应动作，不代替人执行回滚与红队复盘。

## 经济账本

收益信号不是新造的：`evolution.reflect_task` 的入参里本来就有 `helpful_memories` 与
`misleading_memories`，接到 `settle_recall_outcome` 即可，不需要任何新的用户输入。

收益取值 `useful=1.0 / neutral=0.1 / harmful=-2.0`。harmful 记 -2.0 而非 -1.0：一条
误导性记忆造成的损害大于一条有用记忆的收益，这样 ROI 会明确转负，而不是被几次
neutral 召回稀释掉。

**热路径开销为零新增写往返**：检索侧记账挂在 `capsule_store.bump_usage_batch` 已有的
那个事务里，并复用 `retrieval._usage_bump_due` 的 60 秒时间窗门控。改动这里时请保持
该性质——不要在 `search` 里单独开事务记账，那会把只读搜索变成每次都写库。

衰减候选有 7 天宽限期（`WANWEI_MEMORY_DECAY_MIN_AGE_DAYS`）：刚写入还没来得及被召回的
记忆 ROI 天然是负的，不设宽限期，Decay Panel 会被当天新写的记忆淹没而失去可操作性。

## 健康度

MHS 把过期率、冲突率、噪声率、删除残留、敏感覆盖、闲置率、投毒事故聚合成单一分数
（0–100，≥80 healthy / ≥60 warning / 其余 critical）。

**诚实边界**：参考实现的 `health_report()` 把 `precision_at_5` 硬编码成 `0.9`。
本仓 `REVIEW.md` 把「把模拟/未实现说成实测」列为阻断级问题，因此不照抄——没有实跑
评测报告时 `precision@5` 如实输出 `null`，MHS 跳过该维度并在 `unmeasured` 里注明。
宁可分数少一个维度，也不用编造值把仪表盘填满。

同理，`poisoning_incidents` 只统计**真实事故**（未解决的 MHG 事故）；被隔离闸门成功
拦下的投毒尝试单列为 `poisoning_blocked` 且**不扣分**——拦截成功是系统在正常工作，
为此扣健康分是反向激励。

**趋势曲线**需先采样：`POST /memory/health/snapshot`，或每日 MEB 评测收尾自动采一条
（`source='meb:<suite>'`）。刻意做成显式动作而不是在 `GET /memory/health` 里顺手写库
——读端点写库会让前端轮询把快照表撑爆，曲线也会退化成「谁看得勤谁点多」而不是时间
序列。没采过样时如实返回空序列 + 提示，不用当前即时值伪造历史。

趋势点只带 `mhs`、`level`、`precision_at_5` 等标量，不背完整 `metrics` 对象——一条
200 点的曲线背 200 份完整指标快照，响应体会膨胀到没法轮询。

## MEB / MHEB 评测

5 类用例 × 4 维加权：

| 维度 | 权重 |
| --- | --- |
| ux | 0.40 |
| safety | 0.25 |
| product | 0.25 |
| academic | 0.10 |

用例类别：`preference_extraction` / `knowledge_recall` / `conflict_update` /
`forgetting` / `poisoning`。套件规模：mini 14 例（每 PR 门禁）、full 20 例（每日）、
redteam 8 例（每周）。

```bash
python scripts/run_meb.py --suite mini --fail-under 1.0
python scripts/run_meb.py --suite full --save-traces
python scripts/run_meb.py --check-only          # 只校验既有报告的契约
python scripts/run_meb.py --suite mini --write-baseline    # 刷新回归基线
```

产出 `reports/meb_score_report.json`，先过 `report_contract` 校验再落盘——宁可在产出时
失败，也不要把一份字段缺失的报告喂给 CI 门禁和控制台。

报告同时包含 `competition_metrics`：偏好提取准确率按偏好用例通过率计算，
`knowledge_recall` 按知识用例中声明 `relevant_refs` 的 Recall@5 计算，冲突正确率按
冲突用例通过率计算，检索延迟取 trace 的 p95。指标携带样本数、来源和局限，
`official=false`；自建公开用例结果不能替代官方公开/隐藏集成绩。

**评测库隔离**：默认在临时目录建一次性库并在结束后清理，绝不继承 shell 里的
`WANWEI_MEMORY_DB`。评测会写入、遗忘、硬删记忆，误指向真实库就是数据事故。

### 回归基线

基线**按套件分文件**：`reports/meb_baseline_{mini,full,redteam}.json`，各存该套件的
`pass_rate` / `mheb_overall` / `run_id` / 用例数，不存整份报告（基线要能一眼 diff 出
改了什么）。判定逻辑在 `harness.compare_to_baseline`，不在 workflow 的内联脚本里，
因此本地可复现、能被 pytest 覆盖。

这里修过一个假门禁：最初的实现拿单槽的 `meb_score_report.json` 当基线，套件不同就
跳过对比。而 per-PR 写 mini、每日写 full、每周写 redteam，无论提交哪一份都至多匹配
一种流程，其余永远打印「套件不同，跳过对比」——门禁看着在跑，实际从不触发。
按套件分文件后，套件不匹配在结构上不可能发生。

四种判定结果：

| status | 是否失败 | 场景 |
| --- | --- | --- |
| `ok` | 否 | 没有退步（含跌幅在阈值内、以及有提升） |
| `regressed` | **是** | 跌幅超阈值（默认 5 个百分点） |
| `no_baseline` | 否 | 该套件还没有基线（首次运行正常），但会打印创建命令，不静默放过 |
| `malformed` | **是** | 基线存在但 `pass_rate` 不是数值——坏基线会让门禁永久失效，必须让人看见 |

跌幅判定用**已舍入到 6 位的差值**，与日志里打印的百分比同源：直接比
`before - current` 会踩浮点表示（`1.0 - 0.95 = 0.050000000000000044 > 0.05`），
结果是日志显示「下降 5.00%（阈值 5%）」却判失败，看起来像误报。恰好等于阈值不算退步。

CI 分工：`ci.yml` 每 PR 跑 Mini-MEB + 基线比较（只在 ubuntu + py3.12 一个组合上——
评测测的是记忆层逻辑，与 OS/Python 版本无关）；`memory-bench.yml` 跑每日 full 与
每周 redteam，同样带基线比较。

**未实现**：规范里的「每月 Benchmark Sync（同步 hidden set + 更新基线）」没有做。
隐藏集需要一个仓库外的用例源，本仓库只提供 `WANWEI_MEB_HIDDEN_DIR` 加载机制，没有
可同步的对象。不放一个空跑的 job 假装覆盖了它。

## 数据表

| 表 | 用途 | 特殊约束 |
| --- | --- | --- |
| `memory_ledger` | 不可变账本 | 两个触发器强制 append-only |
| `memory_accounts` | 逐条成本/收益/ROI | `roi` 为派生列，计费后同事务重算，便于建索引查负 ROI |
| `memory_incidents` | MHG 事故 | 未解决的 MHG≥3 置起发布冻结 |
| `memory_health_snapshots` | MHS 历史快照 | 只由显式采样动作写入 |

四张表都建在主库（与 `memory_capsules_v2` 同库同事务），因此账本可与业务写入原子落库。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WANWEI_LIFECYCLE_STALE_IDLE_DAYS` | `0` | 闲置降权阈值；0 = 只按 `valid_until` 判过期 |
| `WANWEI_MEMORY_TOKEN_COST` | `0.000002` | 单 token 成本 |
| `WANWEI_MEMORY_STORAGE_PER_KB` | `0.00001` | 每 KB 存储成本 |
| `WANWEI_MEMORY_MAINTENANCE_COST` | `0.001` | 单次维护固定成本 |
| `WANWEI_MEMORY_DECAY_MIN_AGE_DAYS` | `7` | 衰减候选宽限期 |
| `WANWEI_HEALTH_DELETION_SAMPLE` | `50` | 删除残留抽样条数 |
| `WANWEI_HEALTH_UNUSED_DAYS` | `30` | 「长期未用」天数阈值 |
| `WANWEI_MEB_HIDDEN_DIR` | 未设 | 隐藏用例集目录（仓库内无隐藏集） |

## 端点清单

全部端点默认受 `APIKeyMiddleware` 保护（`security/auth.py` 的公开路径是显式白名单），
并按 owner/soul 作用域隔离，跨属主请求按「不存在」处理返回 404 而不泄漏存在性。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/memory/lifecycle/transition` | 受裁决的转移，非法转移 422 |
| POST | `/memory/lifecycle/confirm` | 确认 candidate 或放行 quarantined，结清策略闸门并补写 FTS |
| POST | `/memory/lifecycle/resolve-conflict` | 裁决冲突，维护 supersedes 版本链 |
| POST | `/memory/lifecycle/scan-stale` | 扫描并标记过期记忆 |
| GET | `/memory/lifecycle/{id}` | 当前态 + 全部合法后继 + 转移历史 |
| GET | `/memory/ledger/{id}` | 单条记忆的不可变账目 |
| GET | `/memory/governance/release-gate` | 发布闸门状态 |
| GET/POST | `/memory/governance/incidents` | MHG 事故查询 / 登记 |
| GET | `/memory/governance/provenance/{id}` | Provenance Card |
| GET | `/memory/governance/export` | owner/soul 作用域的脱敏 Markdown/JSON 证据包 |
| GET | `/memory/governance/verify-deletion/{id}` | 五处删除完整性取证 |
| GET | `/memory/accounting/summary` | 经济汇总（带估算免责说明） |
| GET | `/memory/accounting/{id}` | 单条记忆账户 |
| GET | `/memory/health` | MHS + 子指标 + 问题清单 + 未测量项 |
| GET | `/memory/health/decay` | Decay Panel 三分类 |
| GET | `/memory/health/self-knowledge` | Self-Knowledge Panel |
| POST | `/memory/health/snapshot` | 采一次健康度快照 |
| GET | `/memory/health/trend` | MHS 近 N 天曲线 |
| GET | `/memoryos/bench/report` | 上次 MEB 实跑报告（没跑过 404，不返回样例） |

路由顺序注意：固定路径必须先于同前缀的参数路径注册，否则会被路径参数吞掉
（`/memory/accounting/summary` 先于 `/memory/accounting/{capsule_id}`，
`/memory/lifecycle/*` 的动作路径先于 `/memory/lifecycle/{capsule_id}`）。
