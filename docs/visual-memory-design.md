# 视觉记忆子系统设计（VISTA 启发）

> v0.14 · 实现位置 `backend/app/memory_visual/` · 测试 `backend/app/tests/test_memory_visual.py`

## 动机

枢忆的记忆底座此前只收文本。图片要么被 OCR 成一段描述后丢弃原图（有损、不可复核），
要么根本进不了记忆系统。VISTA（[joshhhhhan/VISTA](https://github.com/joshhhhhan/VISTA)，
arXiv:2610.02200）在 ARC-AGI-3 上验证了另一条路：**无损视觉记忆**——观察以原始字节
归档，模型推理时按需回看（inspect 区域裁剪 / read_pixels 像素采样），而不是入库时
一次性压成文字。

本子系统把这条思路移植进枢忆，并与项目立身之本（治理闭环）对齐：
**图片既然能记住，就必须能证明删干净。**

## 借鉴 VISTA 的三件事

| VISTA 概念 | 本项目落地 |
|---|---|
| `Visual` 不可变契约（sha256 + 尺寸 + mime 声明须与字节一致，拒绝动图） | `store._validate_visual_bytes()` 入库校验 |
| `inspect` 区域裁剪 + 最近邻放大回看归档帧 | `inspect.inspect_views()`，坐标改为源图像素坐标（归档图尺寸任意，非 VISTA 的固定 1024²） |
| `read_pixels` 等分网格中心采样 + RGB 符号调色板 | `inspect.read_pixels()`，调色板改为单次调用内构建（API 无会话态） |
| `derived_from` 派生证据必须署名来源 | `kind=derived` 强制 `derived_from` 非空且指向已存在资产 |

## 存储模型

```
memory_capsules_v2          memory_visual_assets（删除取证第六处）
├─ capsule_id (PK)     1──n ├─ asset_id (PK, vas_xxx)
├─ content.modality         ├─ sha256          ← 删除后账本里唯一的内容锚点
│   = 'visual'              ├─ width / height / mime_type
├─ content.asset_sha256     ├─ kind (current/historical/derived)
├─ content.text (caption)   ├─ derived_from (JSON)
└─ ...                      └─ data (BLOB，原始字节，无损)

memory_visual_vectors（删除取证第七处）
├─ asset_id (PK) ─ capsule_id
├─ embedding (BLOB, 167 维 float32, L2 归一化)
└─ owner_id / soul_id      ← 作用域隔离与文本向量同口径
```

- caption 进既有 FTS 通道，文本检索不变；图片字节走视觉语义索引（下节）。
- 上限：单图 8 MiB、单边 4096px、单帧。超出即 `VisualValidationError` → HTTP 422。

## 视觉语义检索（以图搜图）

嵌入方案（`memory_visual/embedding.py`，167 维，PIL + numpy，无外部模型依赖）：
64×64 归一化 → 空间金字塔（全局 + 2×2 网格）→ 每区域 HSV 联合直方图 32 维
（8×2×2，捕捉暗红≠亮红的通道交互）+ 边缘密度 1 维，再拼宽高比 2 维，L2 归一化。

- **低延迟**：numpy 矩阵乘暴力余弦，167 维 × 1 万条 < 5ms 量级；响应自带
  `latency_ms` / `scanned` / `index` 口径，测试里有 300 条 < 100ms 的回归基准。
  量级到百万再换 HNSW（与文本 local_embedding 同一口径）。
- **索引生命周期与 FTS 同口径**：仅 active + 闸门放行入索引；candidate/
  quarantined 确认放行时在 `lifecycle._sync_fts` 里补写；遗忘/删除同事务清除。
- **作用域隔离**：owner/soul 严格匹配，与 local_embedding #153 口径一致。

## API

| 端点 | 说明 |
|---|---|
| `POST /memory/visual/write` | base64 图片 + caption 写入；过策略闸门，reject 不落资产 |
| `GET /memory/visual/{capsule_id}/assets` | 资产清单（不含字节） |
| `POST /memory/visual/inspect` | 多视图区域回看，裁剪 + 最近邻放大，返回 base64 PNG |
| `POST /memory/visual/read-pixels` | 网格像素采样，返回符号调色板 + 行字符串（≤64 视图 / ≤4096 采样点） |
| `POST /memory/visual/search` | 以图搜图（查询图或库内资产），暴力余弦，返回 score/latency_ms |

回看是只读操作：不计 usage、不触发召回记账、不改生命周期。

## 治理闭环

1. **写入闸门**：caption 过 `evaluate_policy`（文本口径不变）；图片二进制的
   格式/体积/帧数校验在 store 层，失败即拒绝，不进 quarantine（ malformed
   输入是调用方错误，不是可疑内容）。
2. **账本**：`write` + `visual_attach` 两笔账目，`visual_attach` 的
   after_content 锚定图片 sha256。
3. **遗忘/删除**：`forget_capsules_in_transaction` 同事务清除资产行，
   软删硬删都清（字节是敏感内容本体，不留软删副本）。
4. **删除取证扩展为七处**：主表 / FTS / 图边反向引用 / 向量引用 / legacy /
   **视觉资产** / **视觉向量**。PDF 证书同步新增两栏。
   老库无 visual 表按 0 处理（防御口径与 purge 一致）。

## 边界声明（诚实清单）

- 视觉嵌入是**感知相似**（颜色/布局/结构），不是 CLIP 级语义
  （"猫"≈"猫"可以，"猫"≈"宠物"不行）。信创离线环境无 GPU / 无 CLIP 模型
  分发；CLIP 接入是既定后续方向，向量表带 dim 列已预留兼容。
- 回看不做内容理解：inspect/read_pixels 只搬像素，解释由调用方模型完成。
- 单节点形态不变；资产 BLOB 在主 SQLite 库内，无独立对象存储。
