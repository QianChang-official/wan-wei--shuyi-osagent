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

"""Regression tests for issue #92: assert and bare except Exception cleanup.

验证:
- app_runtime.py 中 soul_chat 不再使用 assert
- app_runtime.py 中 except Exception 已收窄为具体异常类型（事务回滚除外）
- 不再出现裸 except Exception（无具体类型），事务回滚场景允许保留
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

APP_RUNTIME = Path(__file__).resolve().parents[3] / "backend" / "app" / "app_runtime.py"


def _find_bare_except_exception(filepath: Path) -> list[tuple[int, str]]:
    """Find bare `except Exception:` or `except Exception as exc:` in file.

    排除事务回滚场景（紧邻 conn.rollback() 的 except Exception 是合理的）。
    """
    text = filepath.read_text(encoding="utf-8")
    tree = ast.parse(text)
    lines = text.splitlines()
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                continue  # bare except:
            is_bare_exception = False
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                is_bare_exception = True
            elif isinstance(node.type, ast.Tuple):
                for elt in node.type.elts:
                    if isinstance(elt, ast.Name) and elt.id == "Exception":
                        is_bare_exception = True
                        break
            if not is_bare_exception:
                continue
            # 检查是否是事务回滚场景（下一行包含 conn.rollback()）
            handler_lines = lines[node.lineno - 1 : node.end_lineno]
            if any("conn.rollback()" in ln for ln in handler_lines):
                continue
            results.append((node.lineno, ast.get_source_segment(text, node) or ""))
    return results


def _find_asserts(filepath: Path) -> list[tuple[int, str]]:
    """Find assert statements in file."""
    text = filepath.read_text(encoding="utf-8")
    tree = ast.parse(text)
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            results.append((node.lineno, ast.get_source_segment(text, node) or ""))
    return results


def test_no_bare_except_exception_in_app_runtime():
    """app_runtime.py 不应再出现裸 except Exception（事务回滚场景除外）。"""
    bare = _find_bare_except_exception(APP_RUNTIME)
    assert not bare, f"Found bare except Exception at lines: {[b[0] for b in bare]}"


def test_no_assert_in_app_runtime():
    """app_runtime.py 不应再出现 assert 语句。"""
    asserts = _find_asserts(APP_RUNTIME)
    assert not asserts, f"Found assert at lines: {[a[0] for a in asserts]}"


def test_soul_chat_raises_422_on_missing_soul():
    """soul_chat 在 soul_scope 为 None 时应抛出 HTTPException(422)。"""
    text = APP_RUNTIME.read_text(encoding="utf-8")
    assert 'if soul_scope is None:' in text
    assert 'status_code=422' in text
    assert 'soul_selection_required' in text
    # 确保旧的 assert 已不存在
    assert 'assert soul_scope is not None' not in text


def test_specific_exception_types_used():
    """验证关键位置的 except 已使用具体异常类型。"""
    text = APP_RUNTIME.read_text(encoding="utf-8")
    # forget_preview DB 回滚（非事务内部路径，保留收窄）
    assert 'except (sqlite3.Error, OSError):' in text
    # remove_vectors 回退应使用 RuntimeError / OSError / ConnectionError
    assert 'except (RuntimeError, OSError, ConnectionError):' in text
    # 网关调用应使用 RuntimeError / ConnectionError / TimeoutError / OSError
    # (+ SSRFError 拦截需要，见 issue #87/#88 修复)
    assert 'except (RuntimeError, ConnectionError, TimeoutError, OSError, SSRFError) as exc:' in text
    # 事务回滚场景允许 except Exception（确保回滚安全）
    assert 'except Exception:' in text
