from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
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
_ANCHOR = re.compile(r'<a id="(?P<anchor>[^"]+)"></a>')
_SOURCE_BOUNDARY = re.compile(
    r"<!-- source-(?P<kind>start|end): (?P<path>docs/[^\r\n]+\.md) -->"
)
_DETAILS_TAG = re.compile(r"<details(?:\s[^>]*)?>|</details>", re.IGNORECASE)
_GENERATED_ON_METADATA = re.compile(
    r"^- \*\*生成日期\*\*：`(?P<value>\d{4}-\d{2}-\d{2})`$",
    re.MULTILINE,
)
_SOURCE_COMMIT_METADATA = re.compile(
    r"^- \*\*源提交\*\*：`(?P<value>[0-9a-fA-F]{7,64})`$",
    re.MULTILINE,
)
_HUB_FILENAME = "文档中心_DOCUMENTATION_HUB.md"


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_anchor(filename: str) -> str:
    slug_source = Path(filename).stem.casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source).strip("-") or "document"
    filename_digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8]
    return f"doc-{slug}-{filename_digest}"


def extract_title(source: str, fallback: str) -> str:
    fence_character: str | None = None
    fence_length = 0

    for line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if fence_character is not None:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*",
                line,
            ):
                fence_character = None
                fence_length = 0
            continue

        opening_fence = _FENCE_OPENING.fullmatch(line)
        if opening_fence:
            marker = opening_fence.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            continue

        heading = _ATX_HEADING.fullmatch(line)
        if heading:
            title = heading.group("content").strip()
            title = re.sub(r"[ \t]+#+[ \t]*$", "", title).strip()
            if title:
                return title

    return fallback


def extract_summary(source: str) -> str:
    paragraph: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    in_html_comment = False

    for line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if fence_character is not None:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*",
                line,
            ):
                fence_character = None
                fence_length = 0
            continue

        opening_fence = _FENCE_OPENING.fullmatch(line)
        if opening_fence:
            marker = opening_fence.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            continue

        stripped = line.strip()
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_html_comment = True
            continue

        if not stripped:
            if paragraph:
                break
            continue
        if _ATX_HEADING.fullmatch(line) or re.fullmatch(r" {0,3}(?:-{3,}|\*{3,}|_{3,})", line):
            if paragraph:
                break
            continue

        summary_line = re.sub(r"^>\s?", "", stripped)
        if summary_line:
            paragraph.append(summary_line)

    summary = " ".join(paragraph).strip()
    if not summary:
        return "未提供独立摘要；请展开查看完整正文。"
    if len(summary) > 240:
        return summary[:239].rstrip() + "…"
    return summary


def latest_docs_commit(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "docs"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"cannot determine latest docs commit: {error}") from error

    commit = completed.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        raise ValueError("cannot determine latest docs commit: git returned no commit")
    return commit


def _validated_generation_date(generated_on: str) -> str:
    try:
        parsed = date.fromisoformat(generated_on)
    except ValueError as error:
        raise ValueError(
            f"invalid generation date {generated_on!r}; expected YYYY-MM-DD"
        ) from error
    if parsed.isoformat() != generated_on:
        raise ValueError(f"invalid generation date {generated_on!r}; expected YYYY-MM-DD")
    return generated_on


def _source_status(filename: str) -> str:
    return "historical backup" if ".backup_" in filename else "current"


def _directory_label(title: str) -> str:
    return title.replace("[", "\\[").replace("]", "\\]")


def build_hub(root: Path, *, generated_on: str, source_commit: str) -> str:
    generated_on = _validated_generation_date(generated_on)
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", source_commit):
        raise ValueError("source commit must be a 7-64 character hexadecimal Git commit")

    docs_dir = root / "docs"
    validate_source_manifest(docs_dir)
    source_records: dict[str, tuple[str, str, str, str]] = {}
    for category in CATEGORY_SOURCES:
        for filename in category.files:
            source_path = docs_dir / filename
            source = source_path.read_text(encoding="utf-8")
            source_records[filename] = (
                source,
                extract_title(source, Path(filename).stem),
                extract_summary(source),
                sha256_file(source_path),
            )

    declared_count = sum(len(category.files) for category in CATEGORY_SOURCES)
    backup_count = sum(
        ".backup_" in filename
        for category in CATEGORY_SOURCES
        for filename in category.files
    )
    current_count = declared_count - backup_count

    output: list[str] = [
        "# 宛委·枢忆 OSAgent 文档中心",
        "",
        "> 本文件是面向审阅阶段生成的保真文档合集。每份来源文档均以独立、可追溯的全文块收录。",
        "",
        f"- **生成日期**：`{generated_on}`",
        f"- **源提交**：`{source_commit}`",
        f"- **收录总数**：{declared_count} docs",
        f"- **分类总数**：{len(CATEGORY_SOURCES)} categories",
        f"- **现行文档**：{current_count} current documents",
        f"- **历史备份**：{backup_count} backups",
        "",
        "> **保留保证**：本阶段保留 `docs/` 下全部 48 份源文件（42 份现行文档、6 份历史备份）；合集不删除、移动、覆盖或静默改写任何源文档。",
        "",
        '<a id="documentation-index"></a>',
        "",
        "## 快速跳转目录",
        "",
    ]

    for category in CATEGORY_SOURCES:
        output.append(f"- [{category.name}](#{category.anchor})（{len(category.files)}）")
    output.append("")

    for category in CATEGORY_SOURCES:
        output.extend(
            [
                f'<a id="{category.anchor}"></a>',
                "",
                f"## {category.name}",
                "",
            ]
        )
        for filename in category.files:
            _, title, summary, _ = source_records[filename]
            status = _source_status(filename)
            output.append(
                f"- [{_directory_label(title)}](#{document_anchor(filename)}) — "
                f"`{status}` · `docs/{filename}` — {summary}"
            )
        output.append("")

        for filename in category.files:
            source, title, summary, source_hash = source_records[filename]
            status = _source_status(filename)
            transformed_source = transform_source_headings(source)
            output.extend(
                [
                    f"<!-- source-start: docs/{filename} -->",
                    f'<a id="{document_anchor(filename)}"></a>',
                    "",
                    f"### {title}",
                    "",
                    f"- **源路径**：`docs/{filename}`",
                    f"- **状态**：`{status}`",
                    f"- **SHA-256**：`{source_hash}`",
                    f"- **源提交**：`{source_commit}`",
                    f"- **标题**：{title}",
                    f"- **摘要**：{summary}",
                    "",
                    "<details><summary>展开完整正文</summary>",
                    "",
                    transformed_source,
                    "</details>",
                    "",
                    "↩ [返回快速跳转目录](#documentation-index)",
                    "",
                    f"<!-- source-end: docs/{filename} -->",
                    "",
                ]
            )

    rendered = "\n".join(output).rstrip() + "\n"
    validate_rendered_hub(rendered, root)
    return rendered


def _validate_fences(rendered: str) -> None:
    fence_character: str | None = None
    fence_length = 0
    opening_line = 0

    for line_number, line in enumerate(rendered.splitlines(), start=1):
        if fence_character is not None:
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*",
                line,
            ):
                fence_character = None
                fence_length = 0
                opening_line = 0
            continue

        opening_fence = _FENCE_OPENING.fullmatch(line)
        if opening_fence:
            marker = opening_fence.group("marker")
            fence_character = marker[0]
            fence_length = len(marker)
            opening_line = line_number

    if fence_character is not None:
        raise ValueError(f"unclosed fence opened at rendered line {opening_line}")


def validate_rendered_hub(rendered: str, root: Path) -> None:
    docs_dir = root / "docs"
    validate_source_manifest(docs_dir)

    anchors = [match.group("anchor") for match in _ANCHOR.finditer(rendered)]
    duplicate_anchors = sorted(
        anchor for anchor, count in Counter(anchors).items() if count > 1
    )
    if duplicate_anchors:
        raise ValueError(f"duplicate anchors: {duplicate_anchors}")
    if "documentation-index" not in anchors:
        raise ValueError("missing documentation-index anchor")

    expected_anchors = {
        "documentation-index",
        *(category.anchor for category in CATEGORY_SOURCES),
        *(
            document_anchor(filename)
            for category in CATEGORY_SOURCES
            for filename in category.files
        ),
    }
    missing_anchors = sorted(expected_anchors - set(anchors))
    unexpected_anchors = sorted(set(anchors) - expected_anchors)
    if missing_anchors or unexpected_anchors:
        raise ValueError(
            f"anchor manifest drift: missing={missing_anchors}; unexpected={unexpected_anchors}"
        )

    details_depth = 0
    details_count = 0
    for tag in _DETAILS_TAG.finditer(rendered):
        if tag.group(0).casefold().startswith("</"):
            details_depth -= 1
            if details_depth < 0:
                raise ValueError("unclosed details: closing tag has no opening tag")
        else:
            details_depth += 1
            details_count += 1
    if details_depth:
        raise ValueError(f"unclosed details: {details_depth} block(s) remain open")
    if details_count != 48:
        raise ValueError(f"details block count mismatch: expected 48, found {details_count}")

    boundary_stack: list[str] = []
    starts: list[str] = []
    ends: list[str] = []
    for boundary in _SOURCE_BOUNDARY.finditer(rendered):
        kind = boundary.group("kind")
        source_path = boundary.group("path")
        if kind == "start":
            if boundary_stack:
                raise ValueError(
                    f"nested source boundary: {source_path} starts inside {boundary_stack[-1]}"
                )
            boundary_stack.append(source_path)
            starts.append(source_path)
        else:
            if not boundary_stack:
                raise ValueError(f"unmatched source-end boundary: {source_path}")
            expected_path = boundary_stack.pop()
            if source_path != expected_path:
                raise ValueError(
                    f"mismatched source boundary: expected {expected_path}, found {source_path}"
                )
            ends.append(source_path)
    if boundary_stack:
        raise ValueError(f"unclosed source boundary: {boundary_stack[-1]}")

    declared_paths = [
        f"docs/{filename}"
        for category in CATEGORY_SOURCES
        for filename in category.files
    ]
    duplicate_starts = sorted(
        source_path
        for source_path, count in Counter(starts).items()
        if count > 1
    )
    duplicate_ends = sorted(
        source_path
        for source_path, count in Counter(ends).items()
        if count > 1
    )
    if duplicate_starts or duplicate_ends:
        raise ValueError(
            "duplicate source boundaries: "
            f"starts={duplicate_starts}; ends={duplicate_ends}"
        )
    if starts != declared_paths or ends != declared_paths:
        raise ValueError(
            "source boundary manifest drift: "
            f"expected={declared_paths}; starts={starts}; ends={ends}"
        )

    for category in CATEGORY_SOURCES:
        category_heading = f'<a id="{category.anchor}"></a>\n\n## {category.name}'
        if category_heading not in rendered:
            raise ValueError(f"missing category heading: {category.name}")
        for filename in category.files:
            relative_path = f"docs/{filename}"
            start_marker = f"<!-- source-start: {relative_path} -->"
            end_marker = f"<!-- source-end: {relative_path} -->"
            block = rendered.split(start_marker, 1)[1].split(end_marker, 1)[0]
            expected_hash = sha256_file(docs_dir / filename)
            if f"- **SHA-256**：`{expected_hash}`" not in block:
                raise ValueError(
                    f"stale generated output: SHA-256 metadata mismatch for {relative_path}"
                )
            if transform_source_headings(
                (docs_dir / filename).read_text(encoding="utf-8")
            ) not in block:
                raise ValueError(
                    f"stale generated output: transformed body mismatch for {relative_path}"
                )

    _validate_fences(rendered)


def _metadata_value(pattern: re.Pattern[str], rendered: str, label: str) -> str:
    match = pattern.search(rendered)
    if not match:
        raise ValueError(f"missing generated {label} metadata")
    return match.group("value")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or check the lossless documentation hub."
    )
    parser.add_argument(
        "--generated-on",
        metavar="YYYY-MM-DD",
        help="freeze the generation date (defaults to today when writing)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate that the checked-in documentation hub is current",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    hub_path = root / _HUB_FILENAME

    try:
        if args.check:
            if not hub_path.is_file():
                raise ValueError(f"missing generated output: {hub_path}")
            checked_in = hub_path.read_text(encoding="utf-8")
            generated_on = args.generated_on or _metadata_value(
                _GENERATED_ON_METADATA,
                checked_in,
                "date",
            )
            source_commit = _metadata_value(
                _SOURCE_COMMIT_METADATA,
                checked_in,
                "source commit",
            )
            validate_rendered_hub(checked_in, root)
            expected = build_hub(
                root,
                generated_on=generated_on,
                source_commit=source_commit,
            )
            if checked_in != expected:
                raise ValueError(
                    "stale generated output: run "
                    "`py -3.11 scripts/build_documentation_hub.py "
                    f"--generated-on {generated_on}`"
                )
            print(f"documentation hub is current: {hub_path}")
            return 0

        generated_on = args.generated_on or date.today().isoformat()
        source_commit = latest_docs_commit(root)
        rendered = build_hub(
            root,
            generated_on=generated_on,
            source_commit=source_commit,
        )
        with hub_path.open("w", encoding="utf-8", newline="\n") as hub_file:
            hub_file.write(rendered)
        print(
            f"wrote 48 documents in 10 categories to {hub_path} "
            f"(source commit {source_commit})"
        )
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"documentation hub error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
