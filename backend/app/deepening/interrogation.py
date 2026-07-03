from __future__ import annotations

from .schemas import InterrogationAnswerIn

_QUESTIONS = [
    {"id": "chain_design", "title": "OSAgent 全链路怎么设计？", "focus": "input -> policy -> memory -> tools -> evidence -> export"},
    {"id": "intent_split", "title": "用户意图怎么拆？", "focus": "goal, risk, source layer, tool plan, evidence requirement"},
    {"id": "memory_optimization", "title": "记忆怎么优化？", "focus": "capsule lifecycle, retention, retrieval top-k, conflict edges"},
    {"id": "token_saving", "title": "Token 怎么省？", "focus": "compression, source handles, mode routing, visual fallback"},
    {"id": "design_reason", "title": "为什么这么设计？", "focus": "competition coverage, safety boundary, runnable prototype"},
    {"id": "online_failure", "title": "线上挂了怎么办？", "focus": "health, logs, fallback console, dry-run recovery"},
    {"id": "cost_model", "title": "成本降了多少？", "focus": "relative model only, no fabricated number"},
    {"id": "data_and_fallback", "title": "数据在哪里，兜底是什么？", "focus": "SQLite, reports, docs, dist, audit log"},
]

_ANSWERS = {
    "chain_design": "链路以 source_layer 为入口校验，把用户意图拆成任务目标、风险等级、证据需求和工具计划；MemoryCapsule 保存可审计状态，Policy Gate 控制敏感操作，Evidence Cards 绑定检索来源，最后由 console/docs/reports 导出验收材料。",
    "intent_split": "意图拆解先判定目标类型和风险，再选择 shallow/normal/deep/audit 深度；高风险任务要求更多 evidence cards、reflection loops 和 visual checks，低风险任务只做局部读取与 smoke。",
    "memory_optimization": "记忆优化不是无限塞上下文，而是通过 lifecycle、trust_score、retention_score、relation_edges 和 top-k 限制，把可复用证据和当前任务相关片段绑定。",
    "token_saving": "Token 节省来自 source handles、摘要化 session core、按风险分档 top-k、复用版本谱系文档、浏览器失败时走 dist token + API smoke fallback；这里只给相对模型，不伪造具体节省金额。",
    "design_reason": "设计目标是比赛可交付的 runnable prototype：有后端 API、前端可视化、真实评测报告、诚实边界和文档矩阵，而不是只写概念稿。",
    "online_failure": "线上故障先看 /health、API smoke、前端 dist 是否挂载、Arena 是否退化；可降级到 legacy console、只读 dry-run、报告导出和人工确认。",
    "cost_model": "成本模型目前只表达相对倍率：deep/audit 会增加检索和验证成本，但通过 top-k、压缩摘要、fallback 验证和 dry-run 限制避免无限扩张；真实金额需要接入调用日志后再填。",
    "data_and_fallback": "数据证据在 SQLite、reports、docs、前端 dist 和 git diff 中；兜底是只读 API smoke、compile/build、Arena 报告、source_layer 过滤和 partial/planned/pending 诚实标注。",
}


def questions() -> dict:
    return {"version": "v0.9.1", "items": _QUESTIONS}


def answer_dry_run(req: InterrogationAnswerIn) -> dict:
    selected = req.question_id if req.question_id in _ANSWERS else "chain_design"
    return {
        "dry_run": True,
        "question_id": selected,
        "detail_level": req.detail_level,
        "deep_answer": _ANSWERS[selected],
        "follow_up_questions": [
            "这个回答对应的 runtime evidence 是哪一个？",
            "哪些部分只是 planned，不能写成 done？",
            "如果 API 或前端验证失败，fallback 证据是什么？",
        ],
        "context_used": req.context[:240],
    }
