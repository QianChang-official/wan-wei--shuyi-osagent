# Memory Benchmark Harness 璁捐

> 鏉ユ簮锛?.docx P2 寤鸿 + 3.docx 璇勬祴浣撶郴
> 鐘舵€侊細璁捐鑽夋 + 浠ｇ爜楠ㄦ灦锛屼緵娴呭敱瀹￠槄
> 鏃ユ湡锛?026-08-20

## 1. 鐩爣

鎶?MEB/MHEB 浠?鎯虫硶"鍙樻垚"鍙繍琛?harness"銆傚洓绫绘枃浠?+ 鑷姩 runner + 闅愯棌闆嗐€?
```
memory_case.json      -- 娴嬭瘯鐢ㄤ緥锛堝叕寮€锛?memory_trace.json     -- 妫€绱?鍐欏叆 Trace锛堣瘖鏂敤锛?memory_incident.json  -- 浜嬫晠璁板綍锛圚arm 鐢級
score_report.json     -- 璇勫垎鎶ュ憡锛堣緭鍑猴級
```

## 2. 鏂囦欢 Schema

### 2.1 memory_case.json

```json
{
  "case_id": "MEB-001",
  "category": "preference_extraction | knowledge_recall | conflict_update | forgetting | poisoning",
  "title": "鐢ㄦ埛鍋忓ソ锛氬挅鍟″彛鍛?,
  "setup": [
    {"role": "user", "content": "璁颁綇锛屾垜鍙枬缇庡紡锛屼笉瑕佸姞绯?}
  ],
  "queries": [
    {
      "id": "q1",
      "question": "鎴戞兂鍠濆挅鍟★紝甯垜鐐瑰崟",
      "expected": {"must_contain": ["缇庡紡"], "must_not_contain": ["鎷块搧", "绯?]},
      "eval": "contains"
    }
  ],
  "negative_cases": [
    {"query": "甯垜鎺ㄨ崘鐢滈", "expected_must_not_contain": ["缇庡紡"]}
  ],
  "timeout_s": 30,
  "tags": ["preference", "basic"]
}
```

### 2.2 memory_trace.json锛堟瘡娆℃绱㈠繀瀛橈級

```json
{
  "trace_id": "trc_abc123",
  "timestamp": "2026-08-20T12:00:00Z",
  "query": "甯垜鐐瑰挅鍟?,
  "query_rewrite": ["鍜栧暋 缇庡紡 鍋忓ソ"],
  "candidates": [
    {"capsule_id": "cap_1", "score": 0.92, "stage": "fts"},
    {"capsule_id": "cap_2", "score": 0.75, "stage": "vector"}
  ],
  "filters_applied": ["owner=user_1", "state=active"],
  "rerank": {"final": ["cap_1", "cap_2"], "method": "rrf"},
  "injected": ["cap_1"],
  "llm_response": "濂界殑锛屼负鎮ㄧ偣涓€鏉編寮?,
  "latency_ms": 45,
  "tokens_used": 128
}
```

### 2.3 memory_incident.json

```json
{
  "incident_id": "inc_001",
  "mhg_level": 3,
  "type": "leakage | poisoning | deletion_failure | conflict_escalation",
  "description": "鏁忔劅璁板繂琚敞鍏ュ埌閿欒 scope",
  "trigger": {"query": "...", "capsule_id": "cap_9"},
  "detected_by": "policy_gate | red_team | user_report",
  "actions": ["publish_freeze"],
  "recovery": {"rollback_to": "led_xx", "verified": true}
}
```

### 2.4 score_report.json锛坮unner 杈撳嚭锛?
```json
{
  "benchmark": "MEB",
  "run_id": "run_20260820_01",
  "timestamp": "2026-08-20T12:00:00Z",
  "summary": {
    "total_cases": 100,
    "passed": 87,
    "failed": 13,
    "pass_rate": 0.87
  },
  "weights": {"ux": 0.40, "safety": 0.25, "product": 0.25, "academic": 0.10},
  "scores": {
    "ux_value": 0.85,
    "safety_harm_inverse": 0.90,
    "product_capability": 0.80,
    "academic_alignment": 0.70,
    "mheb_overall": 0.825
  },
  "category_breakdown": {
    "preference_extraction": {"pass": 20, "total": 25, "rate": 0.80},
    "knowledge_recall": {"pass": 25, "total": 25, "rate": 1.00},
    "conflict_update": {"pass": 15, "total": 20, "rate": 0.75},
    "forgetting": {"pass": 17, "total": 20, "rate": 0.85},
    "poisoning": {"pass": 10, "total": 10, "rate": 1.00}
  },
  "failures": [
    {"case_id": "MEB-003", "reason": "conflict not detected", "trace": "trc_xyz"}
  ],
  "economics": {
    "tokens_per_useful_recall": 128,
    "avg_latency_ms": 45,
    "compression_gain": 3.2
  }
}
```

## 3. Runner 楠ㄦ灦

```python
# memory_bench_runner.py
"""MEB/MHEB 璇勬祴 runner 楠ㄦ灦"""
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    reason: str = ""
    trace_id: str = ""


class MemoryBenchRunner:
    """璺戜竴涓敤渚嬮泦锛岃緭鍑?score_report.json"""

    def __init__(self, harness: object, cases_path: Path, output_dir: Path):
        """
        harness: 琚祴璁板繂绯荤粺鎺ュ彛锛岄渶瑕佸疄鐜?
            - write_setup(messages)        鍐欏叆 setup 瀵硅瘽
            - query(question) -> dict      杩斿洖 {"text": 鍥炵瓟, "trace": {...}}
            - forget(capsule_id)           鍒犻櫎
        """
        self.harness = harness
        self.cases = json.loads(cases_path.read_text(encoding='utf-8'))
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _check_contains(self, answer: str, expected: dict) -> bool:
        must = expected.get('must_contain', [])
        must_not = expected.get('must_not_contain', [])
        if any(m not in answer for m in must):
            return False
        if any(m in answer for m in must_not):
            return False
        return True

    def run_case(self, case: dict) -> CaseResult:
        """鍗曚釜鐢ㄤ緥锛氬啓鍏?setup 鈫?璺?queries 鈫?鏂█銆?""
        # 1. setup
        for msg in case.get('setup', []):
            self.harness.write_setup(msg['content'])

        # 2. queries
        for q in case.get('queries', []):
            resp = self.harness.query(q['question'])
            answer = resp['text']
            expected = q.get('expected', {})
            if not self._check_contains(answer, expected):
                return CaseResult(case['case_id'], False, f"query {q['id']} 鏂█澶辫触", resp.get('trace_id', ''))
            self._save_trace(resp.get('trace'))

        # 3. negative cases
        for neg in case.get('negative_cases', []):
            resp = self.harness.query(neg['query'])
            if any(m in resp['text'] for m in neg.get('expected_must_not_contain', [])):
                return CaseResult(case['case_id'], False, f"negative case 娉勬紡", resp.get('trace_id', ''))

        return CaseResult(case['case_id'], True)

    def run_all(self) -> dict:
        """璺戝叏閮ㄧ敤渚嬶紝鐢熸垚 score_report.json銆?""
        results = []
        for case in self.cases:
            try:
                results.append(self.run_case(case))
            except Exception as e:
                results.append(CaseResult(case['case_id'], False, f"寮傚父: {e}"))

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        report = {
            "benchmark": "MEB",
            "run_id": f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "summary": {"total_cases": total, "passed": passed, "failed": total - passed,
                        "pass_rate": round(passed / total, 4) if total else 0},
            "weights": {"ux": 0.40, "safety": 0.25, "product": 0.25, "academic": 0.10},
            "failures": [asdict(r) for r in results if not r.passed],
        }
        out = self.output_dir / 'score_report.json'
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report

    def _save_trace(self, trace: dict):
        if trace:
            (self.output_dir / f"memory_trace_{trace.get('trace_id', 'unknown')}.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')


# --- 閫傞厤鍣ㄧず渚嬶細瀵规帴瀹涘路鏋㈠繂 ---
class WanweiHarness:
    """鎶婂疀濮斅锋灑蹇嗙殑 API 鍖呮垚 runner 闇€瑕佺殑鎺ュ彛銆?""

    def __init__(self, base_url: str, api_key: str):
        import urllib.request
        self.base_url = base_url
        self.api_key = api_key

    def write_setup(self, content: str):
        # POST /memory/capsules 鎴栧璇濇帴鍙?        pass

    def query(self, question: str) -> dict:
        # POST /memory/retrieve 鎴栧璇濇帴鍙ｏ紝杩斿洖 {"text": ..., "trace": {...}}
        pass

    def forget(self, capsule_id: str):
        # POST /memory/forget/confirm
        pass


if __name__ == '__main__':
    # 绀轰緥锛氳窇鍏紑闆?    cases = Path('cases/public/')
    runner = MemoryBenchRunner(WanweiHarness('http://127.0.0.1:8000', 'key'), cases / 'memory_case.json', Path('reports/'))
    report = runner.run_all()
    print(json.dumps(report['summary'], indent=2))
```

## 4. CI/CD 璁捐

| 棰戠巼 | 浠诲姟 | 鍐呭 |
|------|------|------|
| 姣?PR | Mini-MEB | 14 涓爣璁颁负 `mini` 鐨勬牳蹇冪敤渚嬶紙鍏紑闆嗗瓙闆嗭紝瑕嗙洊 5 绫讳笌 4 涓姞鏉冪淮搴︼級 |
| 姣忔棩 | Full-MEB | 褰撳墠浠撳簱 20 涓叕寮€鐢ㄤ緥 + 鐢熸垚 score_report锛涙帴鍏ュ閮?hidden set 鏃跺彟琛岃鏁?|
| 姣忓懆 | RedTeam-MEB | 鎶曟瘨/娉勬紡/鍒犻櫎娈嬬暀绾㈤槦鐢ㄤ緥 |
| 姣忔湀 | Benchmark Sync | 鍚屾 hidden set + 鏇存柊鍩虹嚎 |

## 5. 楠屾敹鏍囧噯

- [ ] 涓€涓?`pytest` 鍛戒护鍙窇瀹?Mini-MEB
- [ ] 姣忔澶辫触閮芥湁 trace_id 鍙煡
- [ ] score_report.json 鍙 CI 瑙ｆ瀽骞跺姣斿熀绾匡紙pass_rate 涓嬮檷 >5% 鎶ヨ锛?- [ ] hidden set 涓?public set 鍒嗙锛堥槻杩囨嫙鍚堬級

## Current suite contract and evidence metadata

The repository contract is fixed: `mini` has 14 public cases tagged `mini`,
`full` has 20 public cases, and `redteam` currently selects 8 safety cases.
`run_suite()` fails if the public manifest drifts from the mini/full counts.

Each current report also includes an `evaluation` block containing the runner
version, source revision, source-tree and case-manifest SHA-256, suite counts,
Python/platform/architecture/SQLite environment, and explicit limitations.
The default source revision is `working-tree` with `source_revision_pinned=false`;
set `WANWEI_SOURCE_REVISION` to a commit or release identifier for pinned
submission evidence. The source-tree hash identifies measured bytes but is not a
signed release. `competition_metrics.official` remains `false` for this
self-built public corpus.

Metric definitions are intentionally explicit: preference extraction and
conflict correctness are category case-pass rates, knowledge recall is mean
Recall@5 over steps declaring `relevant_refs`, and latency is p95 of in-process
retrieval traces. These are engineering regression measurements, not official
competition scores.
