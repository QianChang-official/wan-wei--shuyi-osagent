# 多模态感知层设计（AstrBot 启发）

> v0.15 · 实现位置 `backend/app/perception/`（events / session / pipeline / adapters/）
> · 测试 `backend/app/tests/test_perception_multimodal.py`（22 例）

## 动机与选型

感知层此前只有文本对话（`intake.py`）。本版把语音对话、图片、视频、传感器
连接四类输入统一进来，并与既有的记忆治理闭环、视觉记忆子系统打通。

**AstrBot 只借鉴、不引用**：核实其许可证为 **AGPL-3.0**（Soulter，
2022-2099），强 Copyleft + 网络服务条款，与本项目 Mulan PSL v2 不兼容——
一行代码都不能抄。借鉴的是架构分层：

| AstrBot 思想 | 本项目落地 |
|---|---|
| 平台适配器 → 归一化事件 → 流水线 | `adapters/ → PerceptionEvent → pipeline.py` |
| Provider 懒加载 + 可用性检查 | sherpa-onnx / OpenCV / pyserial 全部可选依赖，缺席即降级 |
| 消息生命周期可观测 | 感知会话状态机 + 反馈事件流 |

**直接用的库**（许可证已核实）：numpy（BSD-3，已是依赖）。
**可选增强**（缺席自动降级，不装不报错）：sherpa-onnx（Apache-2.0，
ASR）、OpenCV（Apache-2.0，视频解码）、silero-vad（MIT，VAD 增强）、
pyserial（BSD-3，串口传输层）。**状态机自研**（transitions 库是 MIT，
但需求只是一张 33 行的转移表，引库不如引表直白）。

## 架构

```
 audio.wav ─▶ AudioAdapter ─┐                    ┌─▶ 策略闸门 → 记忆胶囊
 frames/png ─▶ VideoAdapter ─┼─▶ PerceptionEvent ─┤
 serial流   ─▶ SensorAdapter ─┘   （归一化契约）    └─▶ 视觉记忆（图片/关键帧）
 image.png ─────────────────────────┘
                    │
                    ▼
        PerceptionSession 状态机（每步产出反馈事件）
```

## 会话状态机（`session.py`）

```
idle ──begin──▶ capturing ──capture_done──▶ understanding
  ▲                                            │ understood
  │                                            ▼
  └──── responded ◀──────────────────── responding
  （任意状态）──fault──▶ error ──recover──▶ idle
```

- 与 `memoryos.lifecycle` 同一 idiom：显式转移表裁决，非法转移抛
  `IllegalPerceptionTransition`（HTTP 422）
- `error` 不是终态：解码失败/断连走 `fault → error → recover → idle`
  自动恢复，感知会话不能死在一次故障里
- 每次转移产出反馈事件（`pfb_*`），随响应返回（`feedback` 字段）+
  `GET /memory/perception/session/{id}` 可查——「感知正在做什么」可见

## 三个适配器

**语音（`adapters/audio.py`）**：WAV → 16bit 单声道 PCM 归一化（numpy，
`audioop` 已在 py3.13 移除）→ 能量法 VAD 切段。VAD 用**双门限迟滞**
（onset -42dB / offset -50dB / 240ms hangover）——施密特触发器思路，
单门限会在一句话的气口处把句子切碎。可选 sherpa-onnx ASR
（`WANWEI_ASR_MODEL_DIR`），缺席时段落元数据（起止/能量）照常入库、
`transcript: null` 诚实降级。

**视频（`adapters/video.py`）**：关键帧检测复用**视觉记忆的 167 维嵌入**
（`memory_visual.embedding.embed_image`）算相邻关键帧余弦距离，超阈值
（0.18）判场景切换。感知层与记忆层共享同一套嵌入——视频关键帧天然进入
语义检索。与**上一关键帧**比而不是上一帧（渐变镜头不雪崩连爆）。
解码可插拔：上游直接给 PNG 帧序列，或 OpenCV 懒加载解码视频文件。

**传感器（`adapters/sensor.py`，电子电路侧）**：与下位机固件对齐的串口
帧协议 `AA 55 | len | type | channel | float32 LE | CRC-16/CCITT-FALSE`。
解析器是**字节流状态机**（粘包/半包/噪声自动滑窗重同步，不是理想化的
整帧读取）。检测层两件电路思路的软件对应物：
- **迟滞比较器**（施密特触发）：越限报警后要跌破 `high - hysteresis`
  才恢复，消除阈值附近抖动的报警振荡
- **突变检测**：读数对 EMA 的偏离 > 3σ（指数估计，内存口径恒定）
传输层 pyserial 可选，测试/回放用内存字节流。

## 治理口径（不变）

- 所有记忆写入过既有闸门：文本过 `evaluate_policy`，图片过 store 层校验
- **传感器读数本体不入库**——只有报警触发/恢复/突变事件级信号写记忆，
  高频遥测不该淹没记忆库
- 视频关键帧以 `derived_from` 串链（第 N 帧派生自第 N-1 帧），
  回看任一帧可顺链重建场景演变，且完整进入删除七处取证

## API

| 端点 | 说明 |
|---|---|
| `POST /memory/perception/image` | 图片感知 → 视觉记忆 |
| `POST /memory/perception/audio` | WAV → VAD 切段 →（可选 ASR）→ 语音记忆 |
| `POST /memory/perception/video` | 帧序列或视频字节 → 关键帧 → 视觉记忆链 |
| `POST /memory/perception/sensor` | 串口帧流 → 解析 → 报警/突变 → 事件记忆 |
| `GET /memory/perception/session/{id}` | 会话状态与反馈历史 |

## 边界声明（诚实清单）

- ASR / 视频解码 / 串口传输是**可选依赖**，缺席即降级（语音段元数据
  照常入库、视频需上游给帧序列、传感器走 HTTP 回放），不假装在工作
- 感知会话是运行时对象（进程内存），不进 SQLite——需要持久的是记忆，
  不是会话；重启后会话状态丢失是已知边界
- 本版不做实时流（WebSocket 推送、音频流式 VAD），批量上传-处理-反馈
  模型；实时流是既定后续方向
