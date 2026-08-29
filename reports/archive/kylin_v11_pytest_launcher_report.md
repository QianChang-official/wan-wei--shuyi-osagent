# Kylin V11 pytest 启动器与审计 ID 修复报告

## 背景

在 Kylin V11 x86_64 VM 上，仓库依赖安装完成后，直接执行 `python -m pytest` 可能在测试收集阶段触发 Pydantic v2 二进制扩展加载错误：

```text
pydantic_core/_pydantic_core.cpython-312-x86_64-linux-gnu.so: failed to map segment from shared object
```

同一环境中，普通 Python 解释器直接 `import pydantic_core`、`import pydantic`、`import fastapi`、`import fastapi.testclient` 均可成功。因此该问题表现为 pytest CLI 启动/收集阶段的动态库加载兼容性问题，不是项目业务代码或依赖 wheel 缺失。

## 修复 1：Kylin pytest 启动器

新增 `scripts/run_pytest.py`：

- 先以 `python -c` 方式重新进入解释器；
- 预加载 `pydantic_core`、`pydantic`、`fastapi`；
- 再调用 `pytest.main(...)`；
- 不跳过测试、不修改断言、不降低验收强度；
- `scripts/verify.sh` 已改为通过该启动器运行 pytest。

## 修复 2：审计 ID 与业务 uuid 解耦

全量测试暴露出一个目标机真实问题：`test_write_capsule_rollback_does_not_leak` 会 monkeypatch capsule 写入路径的 `uuid.uuid4`，在 Kylin 原生向量索引路径启用时，该 monkeypatch 会连带影响 `audit.service.record_in_transaction()`，导致审计日志主键重复。

修复方式：

- `backend/app/audit/service.py` 的审计 ID 从 `uuid.uuid4().hex[:12]` 改为 `secrets.token_hex(6)`；
- 新增回归测试 `test_audit_ids_do_not_follow_capsule_uuid_monkeypatch`，确保业务 uuid monkeypatch 不会固定审计 ID。

## 已验证环境

```text
OS: Kylin V11 / 银河麒麟桌面操作系统V11
Kernel: 6.6.0-63-generic
Architecture: x86_64
Python: 3.12.3
SQLite: 3.42.0
pytest: 9.1.1
fastapi: 0.139.0
pydantic: 2.13.4
```

## 已验证命令

```bash
python -m compileall -q backend/app
PYTHONPATH=. python scripts/run_pytest.py -q
```

结果：

```text
522 passed, 3 skipped, 1 warning in 111.43s
```

特别确认：SQLite backup / restore 相关用例在 Kylin V11 x86_64 目标环境中通过。
