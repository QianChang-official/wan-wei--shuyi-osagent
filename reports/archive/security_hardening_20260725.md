# Security hardening 2026-07-25

## 修复内容

- SSRF DNS 重绑定 TOCTOU：新增 `resolve_external_url()`，校验后返回 pinned IP；OpenAI-compatible smoke 使用 pinned IP 直连，并保留原 Host/SNI，避免请求阶段再次 DNS 解析。
- SSRF 纵深防御：默认阻断列表增加 `198.18.0.0/15`。
- 沙盒信息泄露：从沙盒白名单移除 `which` 与 `df`，避免回显工具链路径和挂载布局。
- 同步线程池 DoS 面：真实 smoke 超时从 90s 收紧到 20s，并增加 4 并发的小型信号量；队列满时返回 `busy`。

## 验证

```bash
python -m compileall -q backend/app
PYTHONPATH=. python scripts/run_pytest.py -q backend/app/model_gateway/test_ssrf.py backend/app/tests/test_platform_api_smoke.py
PYTHONPATH=. python scripts/run_pytest.py -q
```
