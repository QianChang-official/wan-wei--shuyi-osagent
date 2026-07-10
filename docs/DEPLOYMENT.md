# 部署指南

本文档对应当前 `main` 分支的 FastAPI + SQLite + Vue 3 单机部署。默认端口统一为 `8010`，生产构建由 FastAPI 挂载在 `/console/`。

## 1. 环境要求

- Python 3.10 或更高版本
- Node.js 20 或更高版本
- npm 10 或更高版本
- Windows 10/11、Linux 或麒麟 OS

项目无需外部数据库。默认开发数据库位于 `data/runtime/memory.db`；也可通过 `WANWEI_MEMORY_DB` 指定其他路径。

## 2. Windows 一键搭建

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1
```

打开：

- 控制台：`http://127.0.0.1:8010/console/`
- 健康检查：`http://127.0.0.1:8010/health`
- 开发 API 文档：`http://127.0.0.1:8010/docs`

开发模式默认 API Key 为 `wanwei-dev-key`，控制台已经预填。生产模式必须显式设置强密钥：

```powershell
$env:WANWEI_API_KEY='replace-with-a-strong-random-key'
powershell -ExecutionPolicy Bypass -File .\scripts\run_dev.ps1 -Production
```

服务密钥通过环境变量传入，避免进入命令行参数；同一密钥在控制台侧栏输入后仅保存在当前页面内存，不写入 `localStorage`、配置文件或构建产物。

## 3. Linux / 麒麟 OS

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend/console-vue && npm ci && npm run build && cd ../..
./scripts/run_dev.sh
```

如脚本不可执行，先运行 `chmod +x scripts/*.sh`。

## 4. 开发模式

后端：

```powershell
.\scripts\run_dev.ps1
```

需要前端热更新时，在另一个终端运行：

```powershell
cd frontend\console-vue
npm run dev
```

Vite 地址为 `http://127.0.0.1:5173/console/`，所有当前 API 前缀都会代理到 `http://127.0.0.1:8010`。

## 5. 验证

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1
$env:PYTHONPATH='backend'
.\backend\.venv\Scripts\python.exe -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\run_eval.ps1
```

HTTP smoke 会验证健康检查、控制台静态文件、未授权拒绝、鉴权后的记忆写入/检索和 workflow dry-run。

## 6. 可选本地模型

完整离线搭建不要求真实模型服务，`local_mock` 可用于 dry-run。要启用 OpenAI-compatible/llama.cpp 真实 smoke，启动前设置：

```powershell
$env:WANWEI_OPENAI_COMPATIBLE_BASE='http://127.0.0.1:8084/v1'
$env:WANWEI_OPENAI_COMPATIBLE_MODEL='your-model-id'
$env:WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST='127.0.0.1'
.\scripts\run_dev.ps1
```

私网或本机地址默认会被 SSRF 防护拒绝，必须把精确主机加入 `WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST`。不要把通配网段加入白名单。

## 7. 配置项

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `WANWEI_MEMORY_DB` | SQLite 文件路径 | 平台数据目录；项目脚本使用 `data/runtime/memory.db` |
| `WANWEI_DATA_DIR` | 未指定数据库时的数据目录 | Windows `%LOCALAPPDATA%/wanwei-shuyi`；Linux `$XDG_DATA_HOME/wanwei-shuyi` |
| `WANWEI_API_KEY` | API 鉴权密钥 | 开发模式 `wanwei-dev-key` |
| `WANWEI_PRODUCTION` | 禁用 OpenAPI 文档并强制密钥 | 未设置 |
| `WANWEI_OPENAI_COMPATIBLE_BASE` | 本地模型 API 根地址 | 未配置 |
| `WANWEI_OPENAI_COMPATIBLE_MODEL` | 本地模型 ID | 未配置 |
| `WANWEI_OPENAI_COMPATIBLE_HOST_ALLOWLIST` | SSRF 精确主机白名单 | 未配置 |

## 8. 当前部署边界

- 限流器是单进程内存实现；不要用多 worker 冒充共享限流。
- SQLite 适合本机演示和单节点原型，不等同于高可用生产数据库。
- Anthropic/Gemini 目前是 catalog/stub，不执行真实调用。
- MCP/Skills、多设备同步、图召回和部分观测模块仍为 partial/planned。
- 仓库当前没有正式 Release、版本 tag 或许可证文件；对外分发前需由项目所有者补齐许可证和发布流程。
