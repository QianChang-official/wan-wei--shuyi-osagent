import hashlib
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_documentation_hub import (  # noqa: E402
    CATEGORY_SOURCES,
    build_hub,
    transform_source_headings,
    validate_source_manifest,
)


class BuildDocumentationHubTests(unittest.TestCase):
    def test_transform_source_headings_preserves_fenced_code(self):
        source = """# H1
### H3
#### H4
```bash
# shell comment
```
~~~text
## literal
~~~
"""

        transformed = transform_source_headings(source)

        self.assertEqual(
            transformed,
            """#### H1
###### H3
<!-- source-heading-level: 4 -->
###### H4
```bash
# shell comment
```
~~~text
## literal
~~~
""",
        )

    def test_transform_source_headings_preserves_trailing_lines_in_unclosed_fence(self):
        source = "# Outside\r\n```bash\r\n# literal\r\n\r\n\r\n"

        transformed = transform_source_headings(source)

        self.assertEqual(
            transformed,
            "#### Outside\n```bash\n# literal\n\n\n",
        )

    def test_transform_source_headings_preserves_eof_in_unclosed_backtick_fence(self):
        source = "# Outside\r\n```bash\r\n# literal"

        transformed = transform_source_headings(source)

        self.assertEqual(transformed, "#### Outside\n```bash\n# literal")

    def test_transform_source_headings_preserves_eof_in_unclosed_tilde_fence(self):
        source = "# Outside\n~~~text\n## literal"

        transformed = transform_source_headings(source)

        self.assertEqual(transformed, "#### Outside\n~~~text\n## literal")

    def test_source_manifest_matches_docs_directory(self):
        actual = validate_source_manifest(ROOT / "docs")
        declared = tuple(
            filename
            for category in CATEGORY_SOURCES
            for filename in category.files
        )

        self.assertEqual(len(CATEGORY_SOURCES), 10)
        self.assertEqual(len(actual), 48)
        self.assertEqual(len(declared), 48)
        self.assertEqual(
            sum(".backup_" in filename for filename in declared),
            6,
        )
        self.assertEqual({path.name for path in actual}, set(declared))

    def test_build_hub_renders_every_declared_source_with_stable_metadata(self):
        rendered = build_hub(
            ROOT,
            generated_on="2026-07-12",
            source_commit="e0d18b4",
        )
        declared = tuple(
            filename
            for category in CATEGORY_SOURCES
            for filename in category.files
        )

        self.assertEqual(rendered.count("<!-- source-start: docs/"), 48)
        self.assertEqual(rendered.count("<!-- source-end: docs/"), 48)
        self.assertEqual(rendered.count("<details>"), 48)
        self.assertEqual(rendered.count('<a id="category-'), 10)
        self.assertEqual(
            sum(
                rendered.count(f"## {category.name}")
                for category in CATEGORY_SOURCES
            ),
            10,
        )
        self.assertIn("## 快速跳转目录", rendered)
        self.assertIn("## 历史备份", rendered)

        for filename in declared:
            self.assertEqual(
                rendered.count(f"<!-- source-start: docs/{filename} -->"),
                1,
            )

        anchors = re.findall(r'<a id="([^"]+)"></a>', rendered)
        self.assertEqual(len(anchors), len(set(anchors)))

        for source_path in validate_source_manifest(ROOT / "docs"):
            self.assertIn(
                hashlib.sha256(source_path.read_bytes()).hexdigest(),
                rendered,
            )

    def test_project_documentation_hub_references_target_existing_anchors(self):
        rendered = (ROOT / "文档中心_DOCUMENTATION_HUB.md").read_text(encoding="utf-8")
        anchors = set(re.findall(r'<a id="([^"]+)"></a>', rendered))
        reference_files = (
            ROOT / "README.md",
            ROOT / "backend/app/deepening/contract_truth.py",
            ROOT / "backend/app/export_center/service.py",
            ROOT / "backend/app/research_adoption/service.py",
            ROOT / "backend/app/tool_registry/service.py",
            ROOT / "backend/app/workflow/service.py",
        )
        references: list[tuple[Path, str]] = []
        for reference_file in reference_files:
            content = reference_file.read_text(encoding="utf-8")
            references.extend(
                (reference_file, anchor)
                for anchor in re.findall(
                    r"文档中心_DOCUMENTATION_HUB\.md#([a-z0-9_-]+)",
                    content,
                )
            )

        self.assertGreater(len(references), 0)
        self.assertEqual(
            [],
            [
                f"{reference_file.relative_to(ROOT)}#{anchor}"
                for reference_file, anchor in references
                if anchor not in anchors
            ],
        )


if __name__ == "__main__":
    unittest.main()
