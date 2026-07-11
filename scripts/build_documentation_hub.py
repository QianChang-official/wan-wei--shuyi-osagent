from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Category:
    name: str
    anchor: str
    files: tuple[str, ...]


CATEGORY_SOURCES: tuple[Category, ...] = (
    Category(
        name="项目与版本",
        anchor="category-project-version",
        files=(
            "CHANGELOG.md",
            "INSPIRATION_POOL.md",
            "PLAN.md",
            "PROJECT_EXPLORATION_20260710.md",
            "ROADMAP.md",
            "VERSION_LINEAGE.md",
        ),
    ),
    Category(
        name="架构与运行时",
        anchor="category-architecture-runtime",
        files=(
            "ARCHITECTURE.md",
            "ASI_ORIENTED_MEMORY_ENVIRONMENT.md",
            "V06_MEMORYOPS_RUNTIME.md",
            "V07_MEMORYOPS_AUTOPILOT_PLATFORM.md",
            "V08_AUTHORITATIVE_TECH_ADOPTION_MATRIX.md",
            "V09_RESEARCH_SYSTEM_REPRODUCTION.md",
            "V091_DEEP_EXPANSION_VISUAL_VERIFICATION.md",
        ),
    ),
    Category(
        name="记忆与 Schema",
        anchor="category-memory-schema",
        files=(
            "ADVANCED_MEMORY_TECH.md",
            "AFFECTIVE_MEMORY_BRANCH.md",
            "MEMORY_CAPSULE_V2_SCHEMA.md",
            "PREFERENCE_KNOWLEDGE_EVOLUTION_POLICY.md",
            "PREFERENCE_KNOWLEDGE_MEMORY_ARCHITECTURE.md",
        ),
    ),
    Category(
        name="治理与安全",
        anchor="category-governance-security",
        files=(
            "ASI_RISK_MAPPING.md",
            "MEMORY_GOVERNANCE_POLICY.md",
            "MEMORY_SECURITY_EVAL.md",
            "OVERSIGHT_COMMAND_LOOP.md",
            "SECURITY_MEMORY.md",
        ),
    ),
    Category(
        name="API 与工作流",
        anchor="category-api-workflow",
        files=(
            "API.md",
            "OSAGENT_COMPETITION_WORKFLOW.md",
            "OSAGENT_MODEL_GATEWAY_FLOW.md",
        ),
    ),
    Category(
        name="评测与合规",
        anchor="category-evaluation-compliance",
        files=(
            "AcceptanceTestSpecification.md",
            "COMPETITION_REQUIREMENT_COVERAGE.md",
            "EVALUATION.md",
            "PRODUCTION_MEMORY_EVAL.md",
        ),
    ),
    Category(
        name="麒麟适配",
        anchor="category-kylin",
        files=(
            "COMPATIBILITY_TEST_REPORT.md",
            "KYLIN_DOCS_MAPPING.md",
            "KYLIN_NATIVE_SDK_INTEGRATION.md",
            "KYLIN_VM_TEST_PLAN.md",
        ),
    ),
    Category(
        name="部署与运维",
        anchor="category-deployment-operations",
        files=(
            "DEPENDENCY_GOVERNANCE.md",
            "DEPLOYMENT.md",
            "OPERATIONS.md",
            "RELEASE_CHECKLIST.md",
            "USER_MANUAL.md",
        ),
    ),
    Category(
        name="研究资料",
        anchor="category-research",
        files=(
            "BACKGROUND_READING.md",
            "SOTA_ALIGNMENT.md",
            "V04_V05_AUTHORITATIVE_REFERENCES.md",
        ),
    ),
    Category(
        name="历史备份",
        anchor="category-backups",
        files=(
            "AcceptanceTestSpecification.backup_20260701_091345.md",
            "AFFECTIVE_MEMORY_BRANCH.backup_20260701_091345.md",
            "ARCHITECTURE.backup_20260701_091345.md",
            "ARCHITECTURE.v0_2.backup_20260701_030504.md",
            "EVALUATION.backup_20260701_091345.md",
            "SOTA_ALIGNMENT.backup_20260701_091345.md",
        ),
    ),
)


_FENCE_OPENING = re.compile(r"^(?: {0,3})(?P<marker>`{3,}|~{3,}).*$")
_ATX_HEADING = re.compile(
    r"^(?P<indent> {0,3})(?P<hashes>#{1,6})(?=[ \t]|$)(?P<content>.*)$"
)


def validate_source_manifest(docs_dir: Path) -> tuple[Path, ...]:
    declared_names = tuple(
        filename for category in CATEGORY_SOURCES for filename in category.files
    )
    duplicate_names = sorted(
        filename
        for filename, count in Counter(declared_names).items()
        if count > 1
    )
    if duplicate_names:
        raise ValueError(f"duplicate declared source filenames: {duplicate_names}")

    actual_paths = tuple(sorted(docs_dir.glob("*.md"), key=lambda path: path.name))
    actual_names = {path.name for path in actual_paths}
    declared_name_set = set(declared_names)
    missing = sorted(declared_name_set - actual_names)
    unexpected = sorted(actual_names - declared_name_set)
    if missing or unexpected:
        raise ValueError(
            f"source manifest drift: missing={missing}; unexpected={unexpected}"
        )

    return actual_paths


def transform_source_headings(source: str) -> str:
    normalized_source = source.replace("\r\n", "\n").replace("\r", "\n")
    has_terminal_newline = normalized_source.endswith("\n")
    lines = normalized_source.split("\n")
    if has_terminal_newline:
        lines.pop()

    transformed_lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0

    for line in lines:
        if fence_character is not None:
            transformed_lines.append(line)
            closing_fence = re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*",
                line,
            )
            if closing_fence:
                fence_character = None
                fence_length = 0
            continue

        opening_fence = _FENCE_OPENING.fullmatch(line)
        if opening_fence:
            marker = opening_fence.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            transformed_lines.append(line)
            continue

        heading = _ATX_HEADING.fullmatch(line)
        if not heading:
            transformed_lines.append(line)
            continue

        source_level = len(heading.group("hashes"))
        target_level = min(6, source_level + 3)
        if source_level >= 4:
            transformed_lines.append(
                f"{heading.group('indent')}<!-- source-heading-level: {source_level} -->"
            )
        transformed_lines.append(
            f"{heading.group('indent')}{'#' * target_level}{heading.group('content')}"
        )

    return "\n".join(transformed_lines) + ("\n" if has_terminal_newline else "")
