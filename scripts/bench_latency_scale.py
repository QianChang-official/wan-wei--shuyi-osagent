#!/usr/bin/env python3
"""延迟规模曲线基准:检索延迟 vs 记忆库规模(1k / 10k / 50k)。

赛题要求(4)的硬指标是「检索响应延迟 ≤ 500ms」。现有证据
(reports/kylin-native-sdk-evidence/latency.json)只有 30 样本 2 条 query,
评审会追问「10 万条记忆下还达标吗」。本脚本产出规模曲线回答这个问题。

设计(诚实口径):
- 三档规模: 1000 / 10000 / 50000 条记忆胶囊
- 50 条不同 query(中文,覆盖偏好/知识/任务主题)
- 冷态(首跑)与热态(重复)分开统计
- 原始数据(逐次延迟)留 JSON,可复现
- 每档独立 db 文件,避免相互污染

用法:
  python scripts/bench_latency_scale.py [--sizes 1000 10000 50000] [--queries 50]
  python scripts/bench_latency_scale.py --sizes 1000   # 快速冒烟
输出:
  reports/latency_scale.json  — 原始数据 + p50/p95/p99 汇总
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
# 仓库根与 backend 都需入 path(与 scripts/run_meb.py 同口径,仓内并存
# backend.app.* 与 app.* 两种导入风格)。放 sys.path 末尾,避免遮蔽同名包。
for _p in (str(_REPO), str(_REPO / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

# 50 条不同主题的中文 query(覆盖偏好/知识/任务/情感)
QUERIES = [
    "我喜欢喝什么咖啡", "项目用什么数据库", "下周有什么安排", "用户对什么过敏",
    "推荐一个提神的饮料", "后端技术栈是什么", "最近在忙的项目", "我的饮食禁忌",
    "团队例会时间", "代码审查的流程", "部署到生产环境的步骤", "如何备份数据",
    "性能优化的方向", "记忆系统怎么工作", "偏好的版本历史", "冲突怎么处理",
    "遗忘的证据", "安全策略有哪些", "端侧延迟要求", "麒麟系统适配",
    "向量检索的原理", "全文检索的优势", "情感如何影响记忆", "短期记忆流转",
    "长期记忆巩固", "审计日志的作用", "账本如何记录", "健康度指标", "评测的方法",
    "基线对比实验", "消融实验设计", "检索准确率", "召回率计算", "冲突消解机制",
    "偏好提取算法", "知识图谱构建", "实体关系抽取", "语义相似度", "重排序策略",
    "缓存策略", "索引结构", "倒排索引", "BM25 算法", "向量量化", "降维技术",
    "在线学习", "增量更新", "遗忘曲线", "记忆衰减", "置信度估计",
]

TOPICS = ["咖啡", "项目", "会议", "偏好", "安全", "检索", "记忆", "任务", "团队", "系统"]


def _gen_corpus(n: int, seed: int = 42) -> list[str]:
    """生成 n 条多样化记忆文本(确定性)。"""
    rng = random.Random(seed)
    corpus = []
    for i in range(n):
        topic = TOPICS[i % len(TOPICS)]
        corpus.append(
            f"记录{i}: 关于{topic}的事项,编号{rng.randint(1000,9999)},"
            f"内容涉及{rng.choice(TOPICS)}与{rng.choice(TOPICS)}的关联处理,"
            f"时间{2026}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"
        )
    return corpus


def _seed_db(db_path: str, corpus: list[str]) -> None:
    """向指定 db 写入语料。

    诚实口径: 用正常 write_capsule 路径写入(过 policy gate + 生命周期),
    不直写 SQL 伪造 lifecycle/governance — 语料必须与真实写入同构,
    否则 baseline 测的不是真实检索路径。语料构造是一次性成本,可接受慢。
    """
    os.environ["WANWEI_MEMORY_DB"] = db_path
    import backend.app.db as dbmod
    from backend.app import init_db

    dbmod.close_all()
    init_db.main()
    from backend.app.memory_runtime.capsule_store import write_capsule

    for text in corpus:
        write_capsule(memory_class="knowledge", content={"text": text})
    dbmod.close_all()


def _bench_one(db_path: str, queries: list[str], warm: bool) -> list[float]:
    """在指定 db 上跑一组 query,返回逐次延迟 ms。"""
    os.environ["WANWEI_MEMORY_DB"] = db_path
    import backend.app.db as dbmod

    dbmod.close_all()
    from backend.app.memory_runtime.retrieval import search_capsules

    # 热态:先跑完整一遍预热 OS page cache,再计时
    if warm:
        for q in queries:
            search_capsules(q, top_k=5)
    lat = []
    for q in queries:
        t0 = time.perf_counter()
        search_capsules(q, top_k=5)
        lat.append((time.perf_counter() - t0) * 1000)
    return lat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    ap.add_argument("--queries", type=int, default=50)
    ap.add_argument("--out", default="reports/latency_scale.json")
    args = ap.parse_args()

    queries = QUERIES[: args.queries]
    result = {
        "meta": {
            "date": time.strftime("%Y-%m-%d"),
            "backend": "fts5_sqlite",
            "sizes": args.sizes,
            "query_count": len(queries),
            "platform": __import__("platform").platform(),
            "python": __import__("platform").python_version(),
            "sqlite": __import__("sqlite3").sqlite_version,
            "cpu": __import__("platform").processor() or "unknown",
            "note": "端侧 SQLite FTS5 检索,冷/热两态,逐次原始延迟;p95/p99 用 inclusive 分位法(不超实测 max)",
        },
        "runs": [],
    }

    for size in args.sizes:
        corpus = _gen_corpus(size)
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, f"bench_{size}.db")
        try:
            t_seed = time.perf_counter()
            _seed_db(db_path, corpus)
            seed_s = time.perf_counter() - t_seed

            cold = _bench_one(db_path, queries, warm=False)
            hot = _bench_one(db_path, queries, warm=True)
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

        def stats(xs: list[float]) -> dict:
            # 小样本(50)用 inclusive 分位法:不会外推超出实测 max,数字自洽。
            # (此前误用默认 exclusive 法,p99 会插值超出 max,被 review 抓出)
            qs = statistics.quantiles(xs, n=100, method="inclusive")
            return {
                "p50": round(statistics.median(xs), 2),
                "p95": round(qs[94], 2),
                "p99": round(qs[98], 2),
                "max": round(max(xs), 2),
                "n": len(xs),
            }

        result["runs"].append({
            "size": size,
            "seed_seconds": round(seed_s, 1),
            "cold": {**stats(cold), "raw": cold},
            "hot": {**stats(hot), "raw": hot},
        })
        print(f"[{size:>6}] seed {seed_s:.0f}s | cold p95 {stats(cold)['p95']}ms | hot p95 {stats(hot)['p95']}ms")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
