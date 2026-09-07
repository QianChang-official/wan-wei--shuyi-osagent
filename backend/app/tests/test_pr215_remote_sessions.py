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

"""Regression coverage for interrupted mobile uploads using temporary storage."""

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest


@pytest.fixture
def mobile_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv('WANWEI_MEMORY_DB', str(tmp_path / 'memory.db'))
    monkeypatch.setenv('WANWEI_PLATFORM_DIR', str(tmp_path / 'platform'))
    from backend.app.platform_api import mobile_remote

    monkeypatch.setattr(mobile_remote, '_UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(mobile_remote, 'actor_id_for_request', lambda request: 'upload-test-owner')
    return mobile_remote


@pytest.mark.parametrize('failure_type', [OSError, asyncio.CancelledError])
def test_interrupted_upload_removes_unregistered_bytes(mobile_uploads, failure_type):
    module = mobile_uploads
    chunks = iter([b'partial upload'])

    async def read(_size):
        try:
            return next(chunks)
        except StopIteration:
            raise failure_type('interrupted') from None

    upload = SimpleNamespace(size=0, headers={}, read=read)
    with pytest.raises(failure_type):
        asyncio.run(module.upload_file(request=SimpleNamespace(), file=upload, note=''))
    assert list(module._UPLOAD_DIR.iterdir()) == []


def test_failed_metadata_registration_removes_uploaded_bytes(mobile_uploads, monkeypatch):
    module = mobile_uploads
    chunks = iter([b'complete upload', b''])

    async def read(_size):
        return next(chunks)

    def unavailable():
        raise sqlite3.OperationalError('metadata database unavailable')

    monkeypatch.setattr(module, 'get_conn', unavailable)
    upload = SimpleNamespace(size=0, headers={}, read=read)
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(module.upload_file(request=SimpleNamespace(), file=upload, note=''))
    assert list(module._UPLOAD_DIR.iterdir()) == []


def test_upload_rejects_changed_database_identity(mobile_uploads, tmp_path, monkeypatch):
    from backend.app import db

    module = mobile_uploads
    monkeypatch.setattr(module, 'configured_actor_id', lambda: 'configured-owner')
    connection = module.get_conn()
    module._file_meta_table(connection)
    database = tmp_path / 'memory.db'
    actual = database.stat()
    # Windows holds open SQLite files, so simulate the recorded identity of a
    # replaced database without moving an open file out of the test directory.
    monkeypatch.setitem(db._db_fingerprints, str(database), (actual.st_dev, actual.st_ino + 1))
    chunks = iter([b'complete upload', b''])

    async def read(_size):
        return next(chunks)

    upload = SimpleNamespace(
        size=0, headers={}, read=read, filename='upload.txt', content_type='text/plain',
    )
    with pytest.raises(db.DatabaseIdentityError):
        asyncio.run(module.upload_file(request=SimpleNamespace(), file=upload, note=''))
    assert connection.execute('SELECT COUNT(*) FROM mobile_files').fetchone()[0] == 0
    assert list(module._UPLOAD_DIR.iterdir()) == []


def test_streamed_size_limit_removes_file_after_closing_handle(mobile_uploads, monkeypatch):
    module = mobile_uploads
    monkeypatch.setattr(module, 'MOBILE_UPLOAD_MAX_FILE_BYTES', 4)
    chunks = iter([b'abc', b'def'])

    async def read(_size):
        return next(chunks)

    upload = SimpleNamespace(size=0, headers={}, read=read)
    with pytest.raises(module.HTTPException) as error:
        asyncio.run(module.upload_file(request=SimpleNamespace(), file=upload, note=''))
    assert error.value.status_code == 413
    assert list(module._UPLOAD_DIR.iterdir()) == []


def test_file_id_collision_preserves_preexisting_upload(mobile_uploads, monkeypatch):
    module = mobile_uploads
    module._UPLOAD_DIR.mkdir()
    existing = module._UPLOAD_DIR / 'file_111111111111'
    existing.write_bytes(b'existing upload')
    monkeypatch.setattr(module.uuid, 'uuid4', lambda: SimpleNamespace(hex='1' * 32))
    upload = SimpleNamespace(size=0, headers={})

    with pytest.raises(FileExistsError):
        asyncio.run(module.upload_file(request=SimpleNamespace(), file=upload, note=''))
    assert existing.read_bytes() == b'existing upload'


def test_simultaneous_upload_registration_respects_owner_quota(mobile_uploads, tmp_path, monkeypatch):
    from backend.app import db

    module = mobile_uploads
    database = tmp_path / 'quota.db'
    monkeypatch.setenv('WANWEI_MEMORY_DB', str(database))
    with sqlite3.connect(database) as connection:
        module._file_meta_table(connection)
    monkeypatch.setattr(module, 'MAX_FILES', 1)
    monkeypatch.setattr(module, 'configured_actor_id', lambda: 'configured-owner')
    local = threading.local()
    monkeypatch.setattr(module, 'get_conn', lambda: local.connection)
    monkeypatch.setattr(db, 'get_conn', lambda: local.connection)
    barrier = threading.Barrier(4)
    upload = SimpleNamespace(filename='file.txt', content_type='text/plain')

    def register(index):
        connection = sqlite3.connect(database, timeout=5)
        local.connection = connection
        try:
            barrier.wait(timeout=5)
            module._register_uploaded_file(f'file_{index:012x}', upload, 1, 'upload-test-owner')
            return 'registered'
        except module.HTTPException as error:
            assert error.status_code == 413
            return 'quota-exceeded'
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(register, range(4)))
    assert outcomes.count('registered') == 1
    assert outcomes.count('quota-exceeded') == 3
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM mobile_files').fetchone()[0] == 1
