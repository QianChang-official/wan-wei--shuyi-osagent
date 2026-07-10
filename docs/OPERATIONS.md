# 生产运维与灾备手册

本文档面向当前单节点 FastAPI + SQLite 部署。它提供可重复的部署、观测、备份恢复和事件响应流程，但不把单节点方案描述为高可用集群。

## 1. 运行边界

- 单应用进程、单 SQLite 数据库。
- 限流为单进程内存令牌桶；多 worker 会放大有效额度，当前不支持。
- 建议仅绑定回环地址，由受控反向代理负责 TLS 和外部访问。
- 目标 RPO 由备份频率决定；默认建议至少每日一次并保留异机副本。
- 恢复需要停机；RTO 取决于数据库大小、校验和重新 smoke 的耗时。

## 2. 容器部署

Windows：

```powershell
Copy-Item .env.example .env
.\scripts\init_secret.ps1
docker compose config
docker compose build
docker compose up -d
$key = (Get-Content .\secrets\wanwei_api_key.txt -Raw).Trim()
.\backend\.venv\Scripts\python.exe .\scripts\smoke.py --api-key $key
```

Linux/麒麟候选环境：

```bash
cp .env.example .env
bash scripts/init_secret.sh
docker compose config
docker compose build
docker compose up -d
bash scripts/smoke.sh --api-key "$(tr -d '\r\n' < secrets/wanwei_api_key.txt)"
```

镜像使用非 root UID/GID `10001:10001`，Compose 默认启用只读根文件系统、`no-new-privileges`、`cap_drop: ALL` 和持久化 `/data` 卷。

## 3. 健康与观测

| 信号 | 含义 | 处理 |
| --- | --- | --- |
| `/health/live` 非 200 | 进程不可用 | 重启并检查启动日志 |
| `/health/ready` 非 200 | SQLite 或静态控制台不可用 | 停止流量，检查数据卷/构建产物 |
| `/metrics` | 受 API Key 保护的 Prometheus 文本 | 由可信采集器拉取 |
| `X-Request-ID` | 请求关联标识 | 在客户端错误与服务日志间关联 |

当前指标包括 `wanwei_build_info`、`wanwei_uptime_seconds`、in-flight、请求计数和累计耗时。路由标签使用 FastAPI 路由模板，不记录查询词、Capsule ID 或 run ID，避免高基数和敏感信息进入指标。

## 4. 密钥管理与可信代理

- 生产 API Key 至少 32 字符。
- 优先使用 `WANWEI_API_KEY_FILE`，不要把密钥写进镜像、Git、Compose 文件或命令行历史。
- `scripts/init_secret.*` 只打印文件位置，不打印密钥值。
- 当前不支持双密钥重叠窗口；轮换需要短暂停止入口流量、替换 secret、重建容器并 smoke。

应用默认关闭 Uvicorn 对代理头的自动信任。只有直接对端是受控代理时，才设置 `WANWEI_TRUSTED_PROXY_IPS` 为明确 IP/CIDR；不要配置 `0.0.0.0/0`。应用从右向左剥离受信任代理，只使用第一个非受信任地址；无效链条或全受信任链条回退到直接对端。入口代理仍应清理或覆盖客户端传入的 `X-Forwarded-For`。该变量只影响限流分桶，不参与鉴权。

## 5. 在线备份

```powershell
.\scripts\backup.ps1 -Action create -Path .\data\backups
.\scripts\backup.ps1 -Action verify -Path .\data\backups\wanwei-<timestamp>.db
```

```bash
bash scripts/backup.sh create --output data/backups
bash scripts/backup.sh verify --input data/backups/wanwei-<timestamp>.db
```

容器运行中可执行：

```bash
docker compose exec app python -m app.operations.backup create --output /data/backups
docker compose exec app python -m app.operations.backup verify --input /data/backups/wanwei-<timestamp>.db
```

每个备份都包含相邻的 `.manifest.json`，记录格式版本、应用版本、大小、表数量与 SHA-256。恢复强制要求清单存在且匹配。

## 6. 停机恢复

恢复前必须停止服务，避免旧连接继续写入目标文件：

```bash
docker compose stop app
docker compose run --rm app python -m app.operations.backup restore --input /data/backups/wanwei-<timestamp>.db --force
docker compose up -d
```

原生 Windows：

```powershell
# 先停止 run_dev.ps1 对应进程
.\scripts\backup.ps1 -Action restore -Path .\data\backups\wanwei-<timestamp>.db -Force
.\scripts\run_dev.ps1
.\scripts\smoke.ps1 -ApiKey '<current-key>'
```

若目标数据库已存在，恢复工具会先在 `backups/pre-restore` 创建安全副本。恢复后必须通过 readiness、HTTP smoke 和关键业务数据抽查。

## 7. 灾备演练

至少每个发布周期执行一次：

1. 写入带唯一标识的测试 Capsule 与 workflow run。
2. 创建备份并验证清单。
3. 在隔离目录或隔离环境恢复该备份。
4. 验证 `PRAGMA quick_check`、关键表、测试 Capsule 与 workflow run。
5. 运行 `scripts/smoke.py`。
6. 记录备份大小、恢复耗时、RPO/RTO 和操作者。

不能只验证“备份命令成功”；没有恢复演练的备份不可视为已验证灾备。

## 8. 升级与回滚

升级前创建并异机保存已验证备份，在预发布环境运行 `scripts/verify.*` 和容器 smoke。项目尚未引入正式数据库迁移框架，因此跨 schema 回滚必须同时恢复升级前数据库备份，不能仅切换镜像。

## 9. 事件响应

- **密钥疑似泄露**：撤销入口流量、轮换 key、重建容器、检索审计日志并保全证据。
- **数据库损坏**：停止服务、保留原文件、验证最近备份、执行隔离恢复后再切换。
- **持续 429**：确认流量、代理信任和伪造转发头。
- **模型网关异常**：禁用真实 provider，保持 `local_mock` dry-run；不要放宽 SSRF 白名单。
- **依赖漏洞**：复现审计结果，升级并运行完整验收，不直接忽略高危结果。
