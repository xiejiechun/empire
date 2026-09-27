import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from empire.contracts.download import FilePolicy
from empire.plugins.infra import download_storage
from empire.plugins.infra.download_storage import DownloadStorage


def policy(filename="report.pdf", size=32, **kwargs):
    return FilePolicy(filename=filename, max_body_bytes=size, max_wire_bytes=size, **kwargs)


@pytest.fixture
def storage(tmp_path):
    return DownloadStorage(tmp_path / "downloads", quota_bytes=100, min_free_bytes=0)


def test_commit_checks_split_signature_digest_and_keeps_published_file(storage):
    body = b"%PDF-report"
    digest = hashlib.sha256(body).hexdigest()
    sink = storage.begin(policy(signature=b"%PDF-", expected_sha256=digest))
    sink.write(body[:2])
    sink.write(body[2:])
    result = sink.commit()
    assert result == {"path": str(storage.root / "report.pdf"), "bytes": len(body), "sha256": digest}
    assert storage.active[sink] == 0
    assert storage._occupied() == len(body)
    storage.end(sink)
    storage.end(sink)
    assert (storage.root / "report.pdf").read_bytes() == body
    assert not storage.active and not list(storage.root.glob(".part-*"))


@pytest.mark.parametrize("filename", [
    "../outside.pdf", "a/b.pdf", r"a\b.pdf", "C:report.pdf", "/report.pdf",
    "report.", "CON", "con.pdf", "PRN.txt", "NUL.pdf", "aux", "COM1.pdf",
    "lpt9.bin", "report:stream", "report ", "", None, 2,
])
def test_invalid_and_windows_reserved_names_are_rejected_without_creation(storage, filename):
    with pytest.raises(ValueError, match="文件名"):
        storage.begin(policy(filename=filename))
    assert not storage.root.exists() and not storage.active


@pytest.mark.parametrize("kwargs", [
    {"expected_sha256": "bad"}, {"expected_sha256": 12},
    {"signature": "not-bytes"}, {"signature": None}, {"signature": b"x" * 4097},
])
def test_invalid_integrity_fields_are_rejected_before_creation(storage, kwargs):
    with pytest.raises(ValueError):
        storage.begin(policy(**kwargs))
    assert not storage.root.exists()


@pytest.mark.parametrize("kwargs", [{"signature": b"%PDF-"}, {"expected_sha256": "0" * 64}])
def test_failed_integrity_only_removes_owned_partial(storage, kwargs):
    sink = storage.begin(policy(**kwargs))
    unrelated = storage.root / ".part-user-original"
    unrelated.write_bytes(b"keep")
    sink.write(b"wrong")
    with pytest.raises(ValueError):
        sink.commit()
    storage.end(sink)
    assert not sink.target.exists() and not sink.path.exists()
    assert unrelated.read_bytes() == b"keep"


def test_existing_or_concurrent_target_is_never_overwritten(storage):
    sink = storage.begin(policy())
    with pytest.raises(ValueError, match="正在下载"):
        storage.begin(policy())
    sink.write(b"new")
    sink.target.write_bytes(b"original")  # Another owner publishes after begin.
    with pytest.raises(FileExistsError):
        sink.commit()
    storage.end(sink)
    assert sink.target.read_bytes() == b"original"
    with pytest.raises(ValueError, match="已存在"):
        storage.begin(policy())


def test_quota_counts_nested_existing_files_and_reserves_inflight_size(tmp_path):
    store = DownloadStorage(tmp_path, quota_bytes=20, min_free_bytes=0)
    folder = tmp_path / "originals"
    folder.mkdir()
    (folder / "keep.pdf").write_bytes(b"12345")
    (tmp_path / ".part-old").write_bytes(b"12345")
    sink = store.begin(policy(size=10))
    sink.write(b"12345")
    assert store._occupied() + sum(store.active.values()) == 20
    with pytest.raises(ValueError, match="配额"):
        store.begin(policy("second.pdf", size=1))
    sink.commit()
    assert store._occupied() + sum(store.active.values()) == 15
    second = store.begin(policy("second.pdf", size=5))
    assert store._occupied() + sum(store.active.values()) == 20
    store.end(second)
    store.end(sink)
    assert (folder / "keep.pdf").read_bytes() == (tmp_path / ".part-old").read_bytes() == b"12345"


def test_write_cannot_exceed_reserved_size(storage):
    sink = storage.begin(policy(size=3))
    sink.write(b"12")
    with pytest.raises(ValueError, match="正文上限"):
        sink.write(b"34")
    assert sink.size == 2
    storage.end(sink)
    assert not sink.path.exists() and not storage.active
    with pytest.raises(ValueError, match="已关闭"):
        sink.write(b"x")


def test_low_disk_rejects_begin_and_midstream_write(storage, monkeypatch):
    monkeypatch.setattr(download_storage.shutil, "disk_usage", lambda _: SimpleNamespace(free=8))
    with pytest.raises(ValueError, match="磁盘空间"):
        storage.begin(policy(size=9))
    assert not storage.active and not list(storage.root.iterdir())
    sink = storage.begin(policy(size=8))
    sink.write(b"1234")
    monkeypatch.setattr(download_storage.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="安全余量"):
        sink.write(b"5")
    storage.end(sink)
    assert not sink.path.exists()


def test_concurrent_begin_never_overreserves(tmp_path):
    store = DownloadStorage(tmp_path, quota_bytes=10, min_free_bytes=0)
    barrier = Barrier(2)

    def begin(filename):
        barrier.wait()
        try:
            return store.begin(policy(filename, size=10))
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        sinks = list(executor.map(begin, ["first.pdf", "second.pdf"]))
    assert sum(sink is not None for sink in sinks) == 1
    assert sum(store.active.values()) == 10
    store.end(next(sink for sink in sinks if sink))


def test_concurrency_guard_applies_to_direct_begin_callers(tmp_path):
    store = DownloadStorage(tmp_path, quota_bytes=100, min_free_bytes=0, concurrency=1)
    sink = store.begin(policy("one.pdf"))
    with pytest.raises(ValueError, match="并发"):
        store.begin(policy("two.pdf"))
    store.end(sink)


def test_failed_cleanup_retains_owned_file_and_reservation_for_retry(storage, monkeypatch):
    sink = storage.begin(policy())
    original = Path.unlink

    def fail(path, *args, **kwargs):
        if path == sink.path:
            raise PermissionError("temporary sharing violation")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(PermissionError):
        storage.end(sink)
    assert sink in storage.active and sink.path.exists()
    monkeypatch.setattr(Path, "unlink", original)
    storage.end(sink)
    assert not storage.active and not sink.path.exists()


def test_replaced_partial_is_not_deleted_or_published(storage):
    sink = storage.begin(policy())
    sink.write(b"download")
    sink.file.close()
    moved = storage.root / "moved-owned-part"
    sink.path.rename(moved)
    sink.path.write_bytes(b"user replacement")
    with pytest.raises(ValueError, match="身份"):
        storage.end(sink)
    assert sink.path.read_bytes() == b"user replacement"
    assert moved.read_bytes() == b"download" and sink in storage.active
    with pytest.raises(ValueError, match="身份"):
        storage.begin(policy("another.pdf"))


def test_replaced_root_is_not_cleaned(storage):
    sink = storage.begin(policy())
    sink.write(b"owned")
    sink.file.close()
    previous = storage.root.with_name("moved-original-directory")
    storage.root.rename(previous)
    storage.root.mkdir()
    sink.path.write_bytes(b"user original")
    with pytest.raises(ValueError, match="目录身份"):
        storage.end(sink)
    assert sink.path.read_bytes() == b"user original"
    assert (previous / sink.path.name).read_bytes() == b"owned"
    assert sink in storage.active


def test_disk_failure_before_publication_only_removes_owned_part(storage, monkeypatch):
    sink = storage.begin(policy())
    sink.write(b"download")
    original = storage.root / "original.pdf"
    original.write_bytes(b"keep")

    def fail(_):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(download_storage.os, "fsync", fail)
    with pytest.raises(OSError):
        sink.commit()
    storage.end(sink)
    assert not sink.target.exists() and not sink.path.exists()
    assert original.read_bytes() == b"keep"


def test_end_rejects_sink_from_other_storage(storage, tmp_path):
    sink = storage.begin(policy())
    other = DownloadStorage(tmp_path / "other", quota_bytes=100, min_free_bytes=0)
    with pytest.raises(ValueError, match="其他"):
        other.end(sink)
    assert sink.path.exists()
    storage.end(sink)


def symlink_or_skip(target, link, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symbolic link privilege is unavailable")
        raise


def test_symlink_root_or_ancestor_is_not_followed(tmp_path):
    target = tmp_path / "user-originals"
    target.mkdir()
    link = tmp_path / "linked"
    symlink_or_skip(target, link, directory=True)
    store = DownloadStorage(link / "child", quota_bytes=100, min_free_bytes=0)
    with pytest.raises(ValueError, match="链接"):
        store.begin(policy())
    assert not (target / "child").exists()


def test_symlink_inside_root_is_not_followed(storage, tmp_path):
    storage.root.mkdir()
    original = tmp_path / "user-original.pdf"
    original.write_bytes(b"keep")
    symlink_or_skip(original, storage.root / "linked.pdf")
    with pytest.raises(ValueError, match="链接"):
        storage.begin(policy())
    assert original.read_bytes() == b"keep" and not storage.active


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction boundary")
@pytest.mark.parametrize("inside", [False, True])
def test_windows_junction_is_not_followed(tmp_path, inside):
    import _winapi

    target = tmp_path / "user-originals"
    target.mkdir()
    original = target / "original.pdf"
    original.write_bytes(b"keep")
    root = tmp_path / "downloads"
    root.mkdir()
    link = root / "linked" if inside else tmp_path / "linked"
    _winapi.CreateJunction(str(target), str(link))
    store = DownloadStorage(root if inside else link, quota_bytes=100, min_free_bytes=0)
    with pytest.raises(ValueError, match="联接"):
        store.begin(policy())
    assert original.read_bytes() == b"keep" and not store.active


def test_policy_validation_does_not_require_modifying_contract(storage):
    # Even a malformed caller cannot turn a negative reservation into free quota.
    malformed = SimpleNamespace(**vars(replace(policy(), filename="valid.pdf")))
    malformed.max_body_bytes = -1
    with pytest.raises(ValueError, match="正整数"):
        storage.begin(malformed)
