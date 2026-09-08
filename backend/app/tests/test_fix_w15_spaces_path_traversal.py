# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""
FIX-04（04-#06）：spaces commit 的 files 路径穿越防护回归测试。

背景
----
`POST /spaces/{pid}/commit` 原实现直接展开请求体：

    add_args = ['add', '--', *body.files]

`git add -- <paths>` **接受工作树外的路径**，git 会把仓库外文件纳入索引并
真实提交。因此传 `files: ["../../.env"]` 或 `["/etc/passwd"]` 可让敏感文件
进入提交，配合 push 即造成外泄。

修复：新增 `guards.validate_repo_files()`，对每一项做 realpath 规范化并断言
落在仓库根内，拒绝绝对路径、`..` 逃逸与指向外部的符号链接；校验放在命令
组装前，使 dry_run 回显与真实执行使用同一批安全路径。
"""

import os
from pathlib import Path

import pytest


def _validate(files, root):
    """延迟导入：guards 模块级依赖 `app.` 前缀路径，需在 conftest 配好后再导。"""
    from backend.app.platform_api.guards import validate_repo_files

    return validate_repo_files(files, root)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """构造一个仓库目录，内含正常文件与子目录，外部放一个敏感文件。"""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "README.md").write_text("ok", encoding="utf-8")
    (root / "src" / "main.py").write_text("print(1)", encoding="utf-8")
    # 仓库外的敏感文件（穿越攻击的目标）
    (tmp_path / ".env").write_text("SECRET=leaked", encoding="utf-8")
    return root


# --- 正常路径必须放行 ---------------------------------------------------


def test_plain_relative_paths_allowed(repo: Path):
    assert _validate(["README.md"], repo) == ["README.md"]


def test_subdirectory_paths_allowed(repo: Path):
    assert _validate(["src/main.py"], repo) == ["src/main.py"]


def test_paths_are_normalized_to_repo_relative(repo: Path):
    """`./src/../README.md` 这类合法但不规范的写法应被归一化，而非拒绝。"""
    assert _validate(["./src/../README.md"], repo) == ["README.md"]


def test_nonexistent_path_allowed(repo: Path):
    """不校验存在性：git add 支持暂存删除操作，路径不存在由 git 自身报错。"""
    assert _validate(["src/deleted.py"], repo) == ["src/deleted.py"]


def test_multiple_files_all_returned(repo: Path):
    result = _validate(["README.md", "src/main.py"], repo)
    assert result == ["README.md", "src/main.py"]


# --- 穿越形态必须拒绝 -------------------------------------------------


def test_parent_traversal_rejected(repo: Path):
    """泠泠报告中的原始 PoC：files:["../../.env"]。"""
    with pytest.raises(ValueError, match="逃出仓库根"):
        _validate(["../.env"], repo)


def test_deep_parent_traversal_rejected(repo: Path):
    with pytest.raises(ValueError, match="逃出仓库根"):
        _validate(["../../../../etc/passwd"], repo)


def test_traversal_hidden_mid_path_rejected(repo: Path):
    """`..` 出现在路径中段同样要拦（先拼接后 resolve，不靠字面匹配）。"""
    with pytest.raises(ValueError, match="逃出仓库根"):
        _validate(["src/../../.env"], repo)


def test_same_prefix_sibling_rejected(repo: Path):
    """相邻目录名即使以仓库名开头，也不能被误判为仓库子目录。"""
    sibling_name = f"{repo.name}-backup"
    with pytest.raises(ValueError, match="逃出仓库根"):
        _validate([f"../{sibling_name}/secret.txt"], repo)


def test_absolute_posix_path_rejected(repo: Path):
    """POSIX 绝对路径必须被拒。

    错误分支因平台而异：POSIX 上 `/etc/passwd` 是绝对路径，走"绝对路径"分支；
    Windows 上它缺盘符不算绝对路径，会走"逃出仓库根"分支。两者都是拒绝，
    故断言只校验"被拒绝"而不锁定具体文案。
    """
    with pytest.raises(ValueError, match="绝对路径|逃出仓库根"):
        _validate(["/etc/passwd"], repo)


@pytest.mark.skipif(os.name != "nt", reason="Windows 盘符路径形态")
def test_absolute_windows_path_rejected(repo: Path):
    with pytest.raises(ValueError, match="绝对路径"):
        _validate([r"C:\Windows\System32\drivers\etc\hosts"], repo)


def test_empty_and_blank_rejected(repo: Path):
    with pytest.raises(ValueError, match="空路径"):
        _validate([""], repo)
    with pytest.raises(ValueError, match="空路径"):
        _validate(["   "], repo)


def test_nul_byte_rejected(repo: Path):
    """NUL 可截断底层路径处理，须在进入文件系统调用前拦下。"""
    with pytest.raises(ValueError, match="NUL"):
        _validate(["README.md\x00../../.env"], repo)


def test_one_bad_path_rejects_whole_batch(repo: Path):
    """批量中任一项越界即整体拒绝，不允许"部分放行"。"""
    with pytest.raises(ValueError):
        _validate(["README.md", "../.env"], repo)


@pytest.mark.skipif(
    not hasattr(os, "symlink") or os.name == "nt",
    reason="Windows 创建符号链接通常需要管理员权限",
)
def test_symlink_escaping_repo_rejected(repo: Path, tmp_path: Path):
    """仓库内的软链指向仓库外文件时，按 realpath 判定应被拒绝。"""
    link = repo / "leak.env"
    link.symlink_to(tmp_path / ".env")
    with pytest.raises(ValueError, match="逃出仓库根"):
        _validate(["leak.env"], repo)
