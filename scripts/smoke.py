"""跨平台 HTTP 交付冒烟脚本。

覆盖范围（如实标注）：/health/live、/health/ready、/console/ 页面可达、
/audit/logs 与 /metrics 的 API Key 鉴权（缺失时 401）、/memory/v2 胶囊写入与检索、
/workflow/runs dry-run、/metrics 指标文本。
不覆盖 /platform/* 端点；platform 冒烟由后端 pytest（backend/app/tests/test_platform_api_smoke.py）承担。
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


def request(
    base_url: str,
    path: str,
    *,
    api_key: str | None = None,
    method: str = "GET",
    body: dict | None = None,
    request_id: str | None = None,
    timeout: float = 10,
) -> tuple[int, dict | str, dict[str, str]]:
    headers = {}
    payload = None
    if api_key:
        headers["X-API-Key"] = api_key
    if request_id:
        headers["X-Request-ID"] = request_id
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    target = base_url.rstrip("/") + path
    req = urllib.request.Request(target, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            parsed = json.loads(raw) if "json" in content_type else raw
            return response.status, parsed, {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed, {key.lower(): value for key, value in exc.headers.items()}


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(base_url: str, api_key: str, timeout: float) -> dict:
    status, health, headers = request(
        base_url,
        "/health/live",
        request_id="wanwei-smoke",
        timeout=timeout,
    )
    assert_true(status == 200 and isinstance(health, dict) and health.get("status") == "alive", "Liveness probe failed.")
    assert_true(headers.get("x-request-id") == "wanwei-smoke", "Request ID was not propagated.")

    status, readiness, _ = request(base_url, "/health/ready", timeout=timeout)
    assert_true(status == 200 and isinstance(readiness, dict) and readiness.get("status") == "ready", "Readiness probe failed.")

    status, console, _ = request(base_url, "/console/", timeout=timeout)
    assert_true(status == 200 and isinstance(console, str) and '<div id="app"></div>' in console, "Vue console is unavailable.")

    status, _, _ = request(base_url, "/audit/logs", timeout=timeout)
    assert_true(status == 401, "Protected endpoint accepted a missing API key.")

    marker = f"wanwei-smoke-{time.time_ns()}"
    status, capsule, _ = request(
        base_url,
        "/memory/v2/capsules",
        api_key=api_key,
        method="POST",
        body={
            "memory_class": "knowledge",
            "content": {"text": f"Delivery verification marker {marker}"},
            "scene": "delivery_smoke",
        },
        timeout=timeout,
    )
    assert_true(status == 200 and isinstance(capsule, dict) and str(capsule.get("capsule_id", "")).startswith("cap_"), "Capsule write failed.")

    query = urllib.parse.urlencode({"q": marker, "top_k": 5})
    status, search, _ = request(base_url, f"/memory/v2/search?{query}", api_key=api_key, timeout=timeout)
    results = search.get("results", []) if isinstance(search, dict) else []
    assert_true(status == 200 and results and results[0].get("capsule_id") == capsule["capsule_id"], "Capsule retrieval failed.")

    status, workflow, _ = request(
        base_url,
        "/workflow/runs",
        api_key=api_key,
        method="POST",
        body={
            "scenario": "weekly_report_preference_learning",
            "user_goal": "Verify the delivery baseline.",
            "include_model_gateway": False,
            "include_forgetting": False,
            "dry_run": True,
        },
        timeout=timeout,
    )
    assert_true(status == 200 and isinstance(workflow, dict) and str(workflow.get("run_id", "")).startswith("wfr_"), "Workflow run failed.")

    status, _, _ = request(base_url, "/metrics", timeout=timeout)
    assert_true(status == 401, "Metrics endpoint accepted a missing API key.")
    status, metrics, _ = request(base_url, "/metrics", api_key=api_key, timeout=timeout)
    assert_true(status == 200 and isinstance(metrics, str) and "wanwei_http_requests_total" in metrics, "Metrics endpoint failed.")

    return {
        "status": "passed",
        "version": health.get("version"),
        "capsule_id": capsule["capsule_id"],
        "workflow_run_id": workflow["run_id"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-platform HTTP delivery smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--api-key", default="wanwei-dev-key")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    print(json.dumps(run(args.base_url, args.api_key, args.timeout), ensure_ascii=False))


if __name__ == "__main__":
    main()
