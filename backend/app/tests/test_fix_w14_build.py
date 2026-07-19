"""W14 构建部署与脚本修复的针对性回归测试。

覆盖条目：
- 11-#4  scripts/vm_*.py 不再硬编码 VM 密码，改读 WANWEI_VM_PASSWORD，未设置时报错退出
- 02-#8/11-#7  .gitignore 增补 data/platform/
- 02-#15  .env.example 的 WANWEI_API_KEY_SOURCE 标注 compose-only
- 11-#6/11-#11  ci.yml dist 门禁改真实校验、接入 npm run test:security
- 11-#8   cryptography 钉版
- 11-#12  .dockerignore 排除 reports/ 但保留运行时所需的两个 Arena 产物
- 12-#9 残留  scripts/smoke.py 头部诚实标注覆盖范围（不含 /platform/*）
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"

PASSWORD_ENV_SCRIPTS = ["vm_restart_ssh.py", "vm_run_setup.py", "vm_start_ssh.py", "vm_unlock.py"]
HARD_CODED_PASSWORD = re.compile(
    r'''(?m)^\s*(?:PASSWORD|PW)\s*=\s*(["'])(?!\$\{)[^"'\r\n]+\1\s*$'''
)


def test_vm_scripts_no_hardcoded_password():
    offenders = []
    for path in sorted(SCRIPTS.glob("vm_*.py")) + sorted(SCRIPTS.glob("guest_*.sh")):
        text = path.read_text(encoding="utf-8")
        if HARD_CODED_PASSWORD.search(text):
            offenders.append(path.name)
    assert not offenders, f"仍存在硬编码 VM 密码: {offenders}"


def test_guest_setup_sh_reads_password_from_env():
    text = (SCRIPTS / "guest_setup.sh").read_text(encoding="utf-8")
    assert "WANWEI_VM_PASSWORD:?" in text
    assert not HARD_CODED_PASSWORD.search(text)


def test_vm_password_scripts_read_env_and_guard():
    for name in PASSWORD_ENV_SCRIPTS:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert 'os.environ.get("WANWEI_VM_PASSWORD")' in text, name
        assert "sys.exit(" in text and "WANWEI_VM_PASSWORD" in text, name


def test_vm_password_scripts_exit_without_env():
    for name in PASSWORD_ENV_SCRIPTS:
        env = {key: value for key, value in os.environ.items() if key != "WANWEI_VM_PASSWORD"}
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / name)],
            capture_output=True,
            env=env,
            timeout=30,
        )
        assert proc.returncode != 0, f"{name} 未设置 WANWEI_VM_PASSWORD 时应当拒绝运行"
        output = proc.stderr + proc.stdout
        assert b"WANWEI_VM_PASSWORD" in output, name


def test_gitignore_covers_data_platform():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/runtime/" in text
    assert "data/platform/" in text


def test_env_example_marks_api_key_source_compose_only():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    idx = next(i for i, line in enumerate(lines) if line.startswith("WANWEI_API_KEY_SOURCE="))
    comment_block = "\n".join(lines[max(0, idx - 3):idx])
    assert "compose-only" in comment_block


def test_ci_has_real_dist_gate_and_security_test():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "git diff --exit-code -- frontend/console-vue/dist" not in text
    assert "npm run test:security" in text
    assert "npm run test:contracts" in text
    assert "working-directory: desktop" in text and "npm test" in text
    assert 'grep -q \'id="app"\' dist/index.html' in text
    assert "dist/index.html missing" in text

    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "git diff --exit-code -- frontend/console-vue/dist" not in release
    assert "npm run test:security" in release
    assert "npm run test:contracts" in release
    assert "working-directory: desktop" in release and "npm test" in release
    assert "dist/index.html missing" in release


def test_cryptography_pinned():
    text = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("cryptography"))
    assert line.startswith("cryptography=="), f"cryptography 未钉版: {line}"


def test_dockerignore_excludes_reports_but_keeps_runtime_artifacts():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "reports/*" in text
    assert "!reports/production_memory_eval_metrics.json" in text
    assert "!reports/production_memory_eval_report.md" in text


def test_smoke_py_header_states_coverage_honestly():
    text = (SCRIPTS / "smoke.py").read_text(encoding="utf-8")
    assert "不覆盖 /platform/*" in text
    assert "test_platform_api_smoke.py" in text


def test_one_off_scripts_have_purpose_header():
    missing = []
    for path in sorted(SCRIPTS.glob("vm_*.py")):
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        if not first_line.startswith("#"):
            missing.append(path.name)
    assert not missing, f"一次性脚本缺少头部用途注释: {missing}"
