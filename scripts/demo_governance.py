"""宛委·枢忆 三分钟治理证据链演示脚本。

自动完成「写入 → 检索 → 删除 → 验证 → 导出证明」全流程，
每步打印关键信息，供录屏或现场演示使用。

用法：
    python scripts/demo_governance.py --api-key <key> [--base-url http://127.0.0.1:8010]

前置条件：服务已启动（scripts/run_dev.sh）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def _request(
    base_url: str,
    path: str,
    *,
    api_key: str,
    method: str = "GET",
    body: dict | None = None,
) -> tuple[int, dict | str]:
    """发 HTTP 请求，返回 (status_code, parsed_body)。"""
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _print_step(step: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  步骤 {step}：{title}")
    print(f"{'='*60}")


def _print_kv(key: str, value: str) -> None:
    print(f"  {key:<20} {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="宛委·枢忆 治理证据链演示")
    parser.add_argument("--api-key", required=True, help="API key")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010", help="后端地址")
    args = parser.parse_args()

    base = args.base_url
    key = args.api_key

    print("宛委·枢忆 可审计 Agent 记忆治理平台")
    print("三分钟证据链：写入 → 检索 → 删除 → 验证 → 导出证明")
    print(f"目标服务：{base}")

    # ── 步骤 0：健康检查 ──────────────────────────────────────────────
    _print_step(0, "健康检查")
    status, body = _request(base, "/health/ready", api_key=key)
    if status != 200:
        print(f"  ❌ 服务未就绪（{status}），请先启动服务")
        return 1
    _print_kv("状态", "就绪")

    # ── 步骤 1：写入记忆 ──────────────────────────────────────────────
    _print_step(1, "写入记忆")
    statement = "项目Alpha的数据库密码是 db@Alpha2026!，仅限内网使用"
    status, body = _request(
        base,
        "/memory/v2/capsules",
        api_key=key,
        method="POST",
        body={
            "memory_class": "knowledge",
            "content": {"knowledge_type": "credential", "statement": statement},
            "source_type": "manual_config",
        },
    )
    if status != 200:
        print(f"  ❌ 写入失败（{status}）：{body}")
        return 1
    capsule_id = body["capsule_id"]
    _print_kv("capsule_id", capsule_id)
    _print_kv("内容", statement)
    _print_kv("policy_gate", body.get("governance", {}).get("policy_result", "—"))
    _print_kv("生命周期", body.get("state", {}).get("lifecycle", "—"))

    # ── 步骤 2：检索召回 ──────────────────────────────────────────────
    _print_step(2, "检索召回（跨会话记忆）")
    status, body = _request(
        base,
        "/memory/v2/search",
        api_key=key,
        method="POST",
        body={"query": "项目Alpha 数据库密码", "top_k": 5},
    )
    if status != 200:
        print(f"  ❌ 检索失败（{status}）：{body}")
        return 1
    hits = body.get("items", [])
    _print_kv("命中数", str(len(hits)))
    if hits:
        _print_kv("首条内容", hits[0].get("content", {}).get("statement", "—")[:60])
        _print_kv("provenance", json.dumps(hits[0].get("provenance", {}), ensure_ascii=False)[:80])

    # ── 步骤 3：删除记忆 ──────────────────────────────────────────────
    _print_step(3, "删除记忆")
    status, body = _request(
        base,
        "/memory/forget/preview",
        api_key=key,
        method="POST",
        body={"instruction": "项目Alpha"},
    )
    if status != 200:
        print(f"  ❌ 删除预览失败（{status}）：{body}")
        return 1
    request_id = body["forget_request_id"]
    _print_kv("forget_request_id", request_id)
    _print_kv("匹配数", str(body.get("matched_count", "—")))

    status, body = _request(
        base,
        "/memory/forget/confirm",
        api_key=key,
        method="POST",
        body={
            "forget_request_id": request_id,
            "confirm": True,
            "mode": "hard_delete",
            "capsule_ids": [capsule_id],
        },
    )
    if status != 200:
        print(f"  ❌ 删除确认失败（{status}）：{body}")
        return 1
    _print_kv("删除结果", "已执行（hard_delete）")

    # ── 步骤 4：验证删除 ──────────────────────────────────────────────
    _print_step(4, "验证删除完整性")
    status, body = _request(
        base,
        f"/memory/governance/verify-deletion/{capsule_id}",
        api_key=key,
    )
    if status != 200:
        print(f"  ❌ 验证失败（{status}）：{body}")
        return 1
    residue = body.get("residue", {})
    _print_kv("验证结论", "✅ 通过" if body.get("complete") else "❌ 未通过")
    _print_kv("主表残留", str(residue.get("capsules", 0)))
    _print_kv("FTS 残留", str(residue.get("fts", 0)))
    _print_kv("图边残留", str(residue.get("relation_edges", 0)))
    _print_kv("向量引用残留", str(residue.get("vector_refs", 0)))
    _print_kv("遗留表残留", str(residue.get("legacy_capsules", 0) + residue.get("legacy_event_links", 0)))

    # ── 步骤 5：导出删除证明 ──────────────────────────────────────────
    _print_step(5, "导出删除证明（PDF 证书）")
    cert_url = f"{base}/memory/governance/verify-deletion/{capsule_id}/certificate"
    req = urllib.request.Request(cert_url, headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            pdf_bytes = resp.read()
            cert_path = f"deletion-certificate-{capsule_id}.pdf"
            with open(cert_path, "wb") as f:
                f.write(pdf_bytes)
            _print_kv("证书文件", cert_path)
            _print_kv("文件大小", f"{len(pdf_bytes):,} bytes")
            _print_kv("PDF 头", pdf_bytes[:5].decode("latin-1"))
    except urllib.error.HTTPError as e:
        print(f"  ❌ 证书生成失败（{e.code}）：{e.read().decode('utf-8', errors='replace')[:200]}")
        return 1

    # ── 完成 ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  证据链演示完成")
    print(f"{'='*60}")
    print(f"  删除证明证书已生成：{cert_path}")
    print("  该证书包含审计编号、五处取证结果与证据链说明，")
    print("  可归档、可出示、可验证。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
