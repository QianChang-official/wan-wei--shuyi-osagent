from __future__ import annotations

from .schemas import AdoptionRoute, ResearchTechnology, VersionMapping


TECHNOLOGIES: list[ResearchTechnology] = [
    ResearchTechnology(
        id="memoryarena",
        name="MemoryArena",
        source_level="B",
        publication_status="arxiv_preprint",
        core_idea="Multi-session Memory-Agent-Environment loops with write/read/action traces and assertion-oriented evaluation.",
        target_modules=["归藏评测舱", "兰台鉴证", "MemoryArena Workbench"],
        adoption_ratio=0.90,
        current_status="partial",
        v08_actions=[
            "Add research adoption catalog and Workbench route design.",
            "Model case editor, session timeline, action trace, failure diagnosis, and historical report trend fields.",
            "Keep existing 5-case MemoryArena-Lite as the verified baseline.",
        ],
        v09_risk_controls=[
            "Separate synthetic benchmark assertions from production success claims.",
            "Add misleading-memory and production-task metrics only after real instrumentation.",
        ],
        evidence_files=["backend/app/memory_arena/runner.py", "backend/app/memory_arena/cases", "reports/production_memory_eval_report.md"],
        source_urls=["https://arxiv.org/abs/2602.16313", "https://github.com/ZexueHe/MemoryArena"],
    ),
    ResearchTechnology(
        id="memos",
        name="MemOS / MemCube-like memory resource governance",
        source_level="B",
        publication_status="arxiv_preprint",
        core_idea="Treat memory as a manageable system resource with lifecycle, scope, tier, scheduling, migration, sync, and access policy.",
        target_modules=["枢忆核", "MemoryCapsule 2.1", "建木同步", "玉衡权限舱"],
        adoption_ratio=0.85,
        current_status="partial",
        v08_actions=[
            "Define MemoryCapsule 2.1 extension fields: memory_scope, memory_tier, scheduler_policy, access_policy, migration_state, sync_state, version_vector.",
            "Map MemCube-like resource governance into platform module and frontend research cockpit.",
        ],
        v09_risk_controls=[
            "Verify migration and sync semantics before claiming multi-device production readiness.",
            "Add access-policy tests for high-risk memory reuse.",
        ],
        evidence_files=["docs/MEMORY_CAPSULE_V2_SCHEMA.md", "backend/app/platform/service.py"],
        source_urls=["https://arxiv.org/abs/2507.03724"],
    ),
    ResearchTechnology(
        id="reflexion",
        name="Reflexion",
        source_level="A",
        publication_status="confirmed_published",
        core_idea="Actor / Evaluator / Self-Reflection loop that turns language feedback into improved future behavior.",
        target_modules=["兰台复盘", "Reflection Engine", "自进化闭环"],
        adoption_ratio=0.85,
        current_status="partial",
        v08_actions=[
            "Specify reflection evaluator stub, failure taxonomy, reflection_quality_score, and before/after comparison fields.",
            "Connect self_evolution_loop enhancement route to current Reflection/Evolution runtime.",
        ],
        v09_risk_controls=[
            "Detect self-reinforcing false reflections and require evidence cards for high-impact updates.",
            "Benchmark reflection quality separately from task success.",
        ],
        evidence_files=["backend/app/memory_runtime/evolution.py", "backend/app/memory_arena/cases/self_evolution_loop.json"],
        source_urls=["https://arxiv.org/abs/2303.11366", "https://github.com/noahshinn/reflexion"],
    ),
    ResearchTechnology(
        id="memorybank",
        name="MemoryBank",
        source_level="A",
        publication_status="aaai_2024",
        core_idea="Long-term user memory with reinforcement, forgetting, and personality/preference adaptation.",
        target_modules=["玄珠偏好", "忘机机制", "司南调参舱"],
        adoption_ratio=0.85,
        current_status="partial",
        v08_actions=[
            "Define memory_strength, recall_count, last_recalled_at, forgetting_decay, and retention_score visualization route.",
            "Map forgetting mechanism 2.0 from current preview/confirm to retention decay and purge verification.",
        ],
        v09_risk_controls=[
            "Prevent emotional salience from overriding governance decisions.",
            "Add deletion verification and retention-decay tests before claiming precise forgetting completion.",
        ],
        evidence_files=["docs/PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md", "backend/app/tuning/service.py"],
        source_urls=["https://arxiv.org/abs/2305.10250"],
    ),
    ResearchTechnology(
        id="hipporag",
        name="HippoRAG",
        source_level="A",
        publication_status="neurips_2024",
        core_idea="Knowledge graph plus Personalized PageRank-style spreading recall inspired by hippocampal indexing.",
        target_modules=["建木网络", "Hippo-Lite Graph Recall", "琅嬛知识"],
        adoption_ratio=0.80,
        current_status="planned",
        v08_actions=[
            "Define MemoryCapsule nodes, relation_edges, query seed nodes, PageRank-like spreading recall stub, and evidence path display.",
            "Expose Hippo-Lite route in research adoption cockpit without claiming full graph retrieval implementation.",
        ],
        v09_risk_controls=[
            "Measure graph recall against FTS baseline before claiming accuracy gains.",
            "Control hallucinated evidence paths with provenance checks.",
        ],
        evidence_files=["docs/MEMORY_CAPSULE_V2_SCHEMA.md", "backend/app/platform/service.py"],
        source_urls=["https://arxiv.org/abs/2405.14831", "https://github.com/OSU-NLP-Group/HippoRAG"],
    ),
    ResearchTechnology(
        id="locomo",
        name="LoCoMo",
        source_level="A",
        publication_status="acl_2024",
        core_idea="Long conversation memory evaluation with event graphs, timeline QA, and long-range consistency checks.",
        target_modules=["归藏评测舱", "Long-Session Mode", "玄衡评分舱"],
        adoption_ratio=0.78,
        current_status="planned",
        v08_actions=[
            "Define mini-LoCoMo case template, event graph, timeline QA, and long-session scenario catalog.",
        ],
        v09_risk_controls=[
            "Separate long-session consistency from short case pass rate.",
            "Add adversarial timeline contradiction checks.",
        ],
        evidence_files=["backend/app/memory_arena/cases", "docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md"],
        source_urls=["https://github.com/snap-research/locomo"],
    ),
    ResearchTechnology(
        id="memgpt",
        name="MemGPT",
        source_level="B",
        publication_status="arxiv_preprint",
        core_idea="Virtual context management and OS-like memory tiers that page between working and archival memory.",
        target_modules=["枢忆核", "Memory Tier Manager", "通玄模型舱"],
        adoption_ratio=0.80,
        current_status="partial",
        v08_actions=[
            "Map working_context, active_capsules, archival_capsules, paging_policy, and context budget panel into MemoryCapsule 2.1 route.",
        ],
        v09_risk_controls=[
            "Benchmark context budget behavior before claiming latency or quality improvement.",
            "Guard paging decisions with trust and source-layer constraints.",
        ],
        evidence_files=["docs/ADVANCED_MEMORY_TECH.md", "backend/app/research_adoption/service.py"],
        source_urls=["https://arxiv.org/abs/2310.08560", "https://github.com/letta-ai/letta"],
    ),
    ResearchTechnology(
        id="generative_agents",
        name="Generative Agents",
        source_level="A",
        publication_status="confirmed_published",
        core_idea="Memory stream, reflection, and planning loop for believable agent behavior over time.",
        target_modules=["太微观测舱", "天工编排舱", "兰台复盘"],
        adoption_ratio=0.75,
        current_status="planned",
        v08_actions=[
            "Define observation stream, importance score, reflection trigger, and plan timeline as platform route concepts.",
        ],
        v09_risk_controls=[
            "Avoid over-humanized claims; keep planning traces auditable and bounded.",
            "Add provenance and confirmation gates to reflection-triggered memory writes.",
        ],
        evidence_files=["docs/AFFECTIVE_MEMORY_BRANCH.md", "docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md"],
        source_urls=["https://arxiv.org/abs/2304.03442", "https://github.com/joonspk-research/generative_agents"],
    ),
    ResearchTechnology(
        id="agemem",
        name="AgeMem / Agentic Memory tools",
        source_level="B",
        publication_status="arxiv_preprint",
        core_idea="Expose memory operations as agent tool actions: add, update, delete, retrieve, summarize, filter, discard.",
        target_modules=["百工技能舱", "Memory Tools API", "玉衡权限舱"],
        adoption_ratio=0.80,
        current_status="planned",
        v08_actions=[
            "Pre-register memory.add, memory.update, memory.delete, memory.retrieve, memory.summarize, memory.filter interfaces in the adoption route.",
            "Keep training/RL layer explicitly planned, not implemented.",
        ],
        v09_risk_controls=[
            "Add tool permission checks and write-confirmation tests before enabling mutating memory tools.",
            "Log tool calls into evidence cards and audit flow.",
        ],
        evidence_files=["backend/app/tool_registry/service.py", "docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md"],
        source_urls=["https://github.com/y1y5/AgeMem"],
    ),
]

ROUTES: list[AdoptionRoute] = [
    AdoptionRoute(
        route_id="memoryarena_workbench",
        name_cn="MemoryArena Workbench",
        target_pillar="归藏评测舱 / 兰台鉴证",
        backend_plan=["case editor schema", "session timeline", "write/read/action trace", "assertion failure diagnosis", "historical report index"],
        frontend_plan=["Workbench entry", "case cards", "timeline panel", "failure diagnosis drawer", "trend summary"],
        arena_plan=["Keep 5-case baseline", "Add interdependent subtasks", "Add long-session templates"],
        status="partial",
        expected_impact="Make evaluation a platform workbench instead of a single script output.",
    ),
    AdoptionRoute(
        route_id="hippo_lite_graph_recall",
        name_cn="Hippo-Lite 建木网络",
        target_pillar="建木网络 / 琅嬛知识",
        backend_plan=["capsule node adapter", "relation edge loader", "query seed selector", "PageRank-like spreading recall stub", "evidence path object"],
        frontend_plan=["graph recall route card", "seed nodes", "evidence path display"],
        arena_plan=["Compare graph recall with FTS baseline after v0.8 catalog lands"],
        status="planned",
        expected_impact="Prepare structured relation recall without pretending full HippoRAG reproduction.",
    ),
    AdoptionRoute(
        route_id="memorybank_retention",
        name_cn="MemoryBank Retention",
        target_pillar="玄珠偏好 / 忘机机制",
        backend_plan=["memory_strength", "recall_count", "last_recalled_at", "forgetting_decay", "retention_score"],
        frontend_plan=["retention meter", "decay preview", "forgetting 2.0 route notes"],
        arena_plan=["Add retention-decay case after schema migration"],
        status="partial",
        expected_impact="Turn preference adaptation and forgetting into measurable lifecycle fields.",
    ),
    AdoptionRoute(
        route_id="reflexion_evaluator",
        name_cn="Reflexion Evaluator",
        target_pillar="兰台复盘 / Reflection Engine",
        backend_plan=["evaluator stub", "failure taxonomy", "reflection_quality_score", "before/after comparison"],
        frontend_plan=["quality score panel", "failure taxonomy chips", "before/after trace"],
        arena_plan=["Enhance self_evolution_loop with evaluator assertions"],
        status="partial",
        expected_impact="Move reflection from post-hoc notes toward diagnosable improvement loops.",
    ),
    AdoptionRoute(
        route_id="memory_tools_api",
        name_cn="Memory Tools API",
        target_pillar="百工技能舱 / 玉衡权限舱",
        backend_plan=["memory.add", "memory.update", "memory.delete", "memory.retrieve", "memory.summarize", "memory.filter"],
        frontend_plan=["tool registry memory operation group", "permission labels", "audit storage hints"],
        arena_plan=["Add mutating tool confirmation tests before activation"],
        status="planned",
        expected_impact="Prepares agentic memory operations while keeping mutating tools supervised.",
    ),
]

VERSION_MAP: list[VersionMapping] = [
    VersionMapping(
        version="v0.1",
        positioning="Basic memory write/retrieve prototype.",
        authoritative_support=["Agent memory write/retrieve foundations"],
        completed=["Basic event memory", "Initial retrieval concept"],
        unfinished=["Governance", "Evidence", "Evaluation"],
        inherited_by=["v0.2 MemoryCapsule", "v0.6 Runtime"],
        evidence_files=["docs/PLAN.md", "docs/ARCHITECTURE.md"],
    ),
    VersionMapping(
        version="v0.2",
        positioning="MemoryCapsule and preference/knowledge dual-track structure.",
        authoritative_support=["MemoryBank", "MemGPT"],
        completed=["Capsule abstraction", "Preference/knowledge split"],
        unfinished=["Lifecycle governance", "Arena metrics"],
        inherited_by=["v0.5 preference-knowledge layer", "v0.8 MemOS mapping"],
        evidence_files=["docs/MEMORY_CAPSULE_V2_SCHEMA.md"],
    ),
    VersionMapping(
        version="v0.3",
        positioning="Memory OS and affective memory branch.",
        authoritative_support=["Generative Agents", "Reflexion", "affective memory references"],
        completed=["Emotional salience concept", "Reflection route idea"],
        unfinished=["Affective boundary enforcement"],
        inherited_by=["v0.3.1 boundary correction", "v0.7 platform cockpit"],
        evidence_files=["docs/AFFECTIVE_MEMORY_BRANCH.md"],
    ),
    VersionMapping(
        version="v0.4",
        positioning="Safety memory governance foundation.",
        authoritative_support=["MemOS governance framing", "privacy/lifecycle governance references"],
        completed=["ASI risk mapping", "Memory governance policy", "Security eval docs"],
        unfinished=["Executable gate integration"],
        inherited_by=["v0.6 Policy Gate", "v0.8 risk-control mapping"],
        evidence_files=["docs/MEMORY_GOVERNANCE_POLICY.md", "docs/ASI_RISK_MAPPING.md"],
    ),
    VersionMapping(
        version="v0.5",
        positioning="Preference-knowledge memory optimization layer.",
        authoritative_support=["MemoryBank", "Reflexion", "MemOS"],
        completed=["Preference/knowledge evolution policy", "Oversight loop", "Production eval plan"],
        unfinished=["Runtime metrics"],
        inherited_by=["v0.6 MemoryArena-Lite", "v0.8 retention route"],
        evidence_files=["docs/PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md", "docs/PRODUCTION_MEMORY_EVAL.md"],
    ),
    VersionMapping(
        version="v0.6",
        positioning="MemoryOps Runtime + Production MemoryArena-Lite.",
        authoritative_support=["MemoryArena", "LoCoMo", "Reflexion"],
        completed=["FastAPI runtime", "SQLite + FTS5", "5 cases / 16 assertions", "Reflection/Evolution"],
        unfinished=["Long-session evaluation", "Production-task success metric"],
        inherited_by=["v0.7 platform", "v0.8 MemoryArena Workbench"],
        evidence_files=["docs/V06_MEMORYOPS_RUNTIME.md", "reports/production_memory_eval_report.md"],
    ),
    VersionMapping(
        version="v0.7",
        positioning="MemoryOps Autopilot Platform and 20-cabin Studio.",
        authoritative_support=["MemoryOps platform synthesis", "MCP/Skills orchestration framing"],
        completed=["20 platform modules", "Model Gateway stub", "Tool Registry stub", "Tuning and Export stubs", "Vue Studio expansion"],
        unfinished=["Deep implementation for sync, observability, scoring, orchestration"],
        inherited_by=["v0.8 technology adoption cockpit"],
        evidence_files=["docs/V07_MEMORYOPS_AUTOPILOT_PLATFORM.md", "docs/COMPETITION_REQUIREMENT_COVERAGE.md"],
    ),
    VersionMapping(
        version="v0.8",
        positioning="Authoritative Technology Adoption Edition.",
        authoritative_support=["MemoryArena", "MemOS", "Reflexion", "MemoryBank", "HippoRAG", "LoCoMo", "MemGPT", "Generative Agents", "AgeMem"],
        completed=["Research adoption catalog/API", "Five engineering routes", "Research cockpit", "Adoption matrix docs"],
        unfinished=["Full reproduction of external systems", "Real new metrics beyond existing Arena baseline"],
        inherited_by=["v0.9 risk convergence and engineering hardening"],
        evidence_files=["docs/V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md", "backend/app/research_adoption/service.py"],
    ),
]


def list_technologies() -> dict:
    return {"items": [item.model_dump() for item in TECHNOLOGIES]}


def list_routes() -> dict:
    return {"items": [item.model_dump() for item in ROUTES]}


def version_map() -> dict:
    return {"items": [item.model_dump() for item in VERSION_MAP]}
