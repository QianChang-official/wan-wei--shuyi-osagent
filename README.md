# 宛委·枢忆 OSAgent

面向麒麟操作系统的多源融合偏好与知识记忆优化系统。

## 定位

构建可治理、可演化、可防投毒、可评测的端侧 OS Agent 记忆系统；引入 MemoryCapsule 统一记忆容器、TTME-style 推理期记忆扩展、SimpleMem-style 语义压缩、Trust-aware 记忆安全护栏和纵向记忆安全评测机制。

## 快速启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.init_db
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

```bash
curl http://127.0.0.1:8765/health
```

## 目录

- docs：完整项目文档
- backend：FastAPI + SQLite 原型
- data：样例与评测数据
- assets/mindmap：新版思维导图

## v0.6 MemoryOps Runtime 演示

v0.6 已新增最小可运行 MemoryOps Runtime 与 Production MemoryArena-Lite：

```bash
chmod +x scripts/run_eval.sh
./scripts/run_eval.sh
```

输出：

```text
reports/production_memory_eval_report.md
reports/production_memory_eval_metrics.json
```

当前 Lite 评测覆盖三条多会话生产场景：论文引用治理、Git 提交前审查、记忆投毒与偏好确认。详见 `docs/V06_MEMORYOPS_RUNTIME.md`。
