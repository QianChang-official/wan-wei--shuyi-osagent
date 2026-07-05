# 宛委枢忆 OSAgent v0.9.4 Security Baseline 复验报告

分支：`v0.9.4-security-baseline`
基线：`fbcd665 feat: close v0.9.3 workflow run dry-run loop`
目标：不新增功能、不做 PPT/视频，只修 P0 安全红线。

## 已修复范围

### P0-1 SSRF

- `/model-gateway/test` 不再接受用户传入的 `api_base`。
- 后端只使用 provider catalog 中配置的 `api_base`。
- 新增 `backend/app/security/ssrf.py`。
- 拒绝 loopback、localhost、10/8、172.16/12、192.168/16、169.254/16、IPv6 loopback/link-local/private/multicast。
- 增加 SSRF 回归测试。

### P0-2 API 认证

- 新增 `backend/app/security/auth.py`。
- `WANWEI_API_KEY` 存在时，所有 `POST/PUT/PATCH/DELETE` 均要求 `X-API-Key`。
- `/health`、`/console` 静态入口保持公开。
- 无 key / 错 key 返回 401。

### P0-3 legacy policy gate

- `/memory/events` 改用统一 `evaluate_policy()`。
- 命中 password/token/secret/API key/OpenAI key/AWS key/手机号/身份证等 S3/PII 时拒绝写入。
- rejected 事件只写 audit，不进入 `memory_events` 或 FTS。

### P0-4 forget_confirm

- 新增 `forget_capsules()`。
- capsule 软删除为 `forgotten/deleted`，默认检索不可见。
- 同步删除 `memory_capsules_v2_fts` 条目。
- legacy `memory_events`/`memory_fts` 根据 preview candidate 清理。
- audit 记录 `deleted_capsule_ids` 和 `deleted_event_ids`。

### P0-5 中文检索

- 删除“未命中时 fallback 到 latest”的行为。
- 增加 CJK substring / bigram 辅助检索。
- 覆盖：`周报`、`正式语气`、`三段式结构`。
- 不存在关键词返回空，不再误召回最新 capsule。

## 同步工程红线

- DB 文件创建/访问时强制 `0600`。
- `WANWEI_PRODUCTION=1` 时禁用 `/docs`、`/redoc`、`/openapi.json`。
- `backend/requirements.txt` 增加 `pytest==8.4.2`，保持 `pydantic==1.10.26`。
- `.workflow/branch-pipeline.yml` 改为安装 `backend/requirements.txt`、compile backend、运行安全回归测试，不再执行不存在的 `main.py`。
- 新增安全测试：`backend/app/model_gateway/test_ssrf.py`、`backend/app/tests/test_security_baseline.py`。

## 真实验证结果

### Python compile + 安全回归

命令：

```bash
. .venv/bin/activate
python3 -m compileall -q backend/app
PYTHONPATH=. pytest -q backend/app/model_gateway/test_ssrf.py backend/app/tests/test_security_baseline.py
```

结果：

```text
14 passed
```

### 前端构建

命令：

```bash
cd frontend/console-vue
npm run build
```

结果：

```text
vite build success, 84 modules transformed
```

### MemoryArena

命令：

```bash
./scripts/run_eval.sh
```

结果：

```text
total_cases = 5
total_assertions = 16
assertions_passed = 16
unsafe_autonomy_rate = 0.0
```

### 生产模式 HTTP smoke

临时启动：

```bash
WANWEI_API_KEY=test-key-0934 WANWEI_PRODUCTION=1 PYTHONPATH=backend python -m uvicorn app.main:app --host 127.0.0.1 --port 8012
```

结果：

```text
GET  /health                       -> 200, version=v0.9.3-workflow-run
POST /memory/v2/capsules no key    -> 401
POST /memory/v2/capsules with key  -> 200
GET  /memory/v2/search?q=周报      -> 200, results=1
GET  /docs                         -> 404
GET  /openapi.json                 -> 404
POST /workflow/runs no key         -> 401
```

## 仍保留边界

- 当前认证是最小 API Key baseline，不是完整 RBAC/OAuth。
- 当前 SSRF 防护不允许用户任意 URL 输入；provider URL 仍建议通过部署配置审查。
- `forget_confirm` 对 legacy preview candidate 执行清理；复杂级联关系仍可在 v0.9.5 后扩展。
- 中文检索为最小稳定 CJK substring/bigram，不是完整分词/向量召回。

## 结论

v0.9.4-security-baseline 已压住复审报告中可被直接复测的 P0 红线：SSRF、无认证写接口、legacy secret 写入、forget_confirm 不删除、中文检索 fallback、DB 权限、生产 docs/openapi 暴露、CI 入口错误和测试文件缺失。
