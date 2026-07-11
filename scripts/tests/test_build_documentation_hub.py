import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_documentation_hub import (  # noqa: E402
    CATEGORY_SOURCES,
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


if __name__ == "__main__":
    unittest.main()
