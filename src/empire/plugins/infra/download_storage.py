"""Quota-controlled file sink. Only owned temporary files are ever removed."""
import asyncio
import hashlib
import os
import re
import shutil
import stat
import threading
from pathlib import Path
from uuid import uuid4


def _identity(value):
    return value.st_dev, value.st_ino


def _is_link(path):
    return path.is_symlink() or path.is_junction()


class FileSink:
    def __init__(self, store, policy):
        self.store, self.policy = store, policy
        self.target = store.root / policy.filename
        self.path = store.root / (".part-" + uuid4().hex)
        self.file = self.path.open("xb")
        self.identity = _identity(os.fstat(self.file.fileno()))
        self.size = 0
        self.digest = hashlib.sha256()
        self.prefix = bytearray()
        self.committed = False

    def _owned_part(self):
        self.store._check_root()
        if not self.path.exists() and not self.path.is_symlink():
            return False
        value = self.path.lstat()
        if not stat.S_ISREG(value.st_mode) or _identity(value) != self.identity:
            raise ValueError("下载临时文件身份已变化，不修改该路径")
        return True

    def write(self, chunk):
        with self.store.lock:
            self.store._check_root()
            if self.file.closed or self.committed or self not in self.store.active:
                raise ValueError("下载写入器已关闭")
            if self.size + len(chunk) > self.policy.max_body_bytes:
                raise ValueError("下载文件超过声明的正文上限")
            if shutil.disk_usage(self.store.root).free < self.store.min_free + len(chunk):
                raise ValueError("磁盘剩余空间低于下载安全余量")
            written = self.file.write(chunk)
            if written != len(chunk):
                raise OSError("下载文件未完整写入")
            self.size += written
            self.digest.update(chunk)
            if len(self.prefix) < len(self.policy.signature):
                self.prefix.extend(chunk[:len(self.policy.signature) - len(self.prefix)])

    def commit(self):
        with self.store.lock:
            if self.file.closed or self.committed or self not in self.store.active:
                raise ValueError("下载写入器已关闭")
            if not self._owned_part():
                raise ValueError("下载临时文件已丢失")
            digest = self.digest.hexdigest()
            if self.policy.signature and bytes(self.prefix) != self.policy.signature:
                raise ValueError("下载文件的格式签名不符合插件声明")
            if self.policy.expected_sha256 and digest != self.policy.expected_sha256:
                raise ValueError("下载文件 SHA-256 不符合预期")
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()
            # An exclusive hard link publishes atomically without replacing user files.
            os.link(self.path, self.target, follow_symlinks=False)
            self.committed = True
            self.store.active[self] = 0  # The published file now counts as occupied space.
            if self._owned_part():
                self.path.unlink()
            return {"path": str(self.target), "bytes": self.size, "sha256": digest}

    def close(self):
        with self.store.lock:
            self.file.close()
            if self._owned_part():
                self.path.unlink()


class DownloadStorage:
    def __init__(self, root, *, quota_bytes, min_free_bytes, concurrency=4):
        self.root = Path(os.path.abspath(root))
        if (type(quota_bytes) is not int or quota_bytes <= 0 or
                type(min_free_bytes) is not int or min_free_bytes < 0 or
                type(concurrency) is not int or not 1 <= concurrency <= 64):
            raise ValueError("文件下载磁盘配额/余量/并发无效")
        self.quota, self.min_free = quota_bytes, min_free_bytes
        self.concurrency = concurrency
        self.active = {}
        self.lock = threading.RLock()
        self.root_identity = None
        self.slots = asyncio.Semaphore(concurrency)

    def _check_root(self, *, create=False):
        for path in (*reversed(self.root.parents), self.root):
            if _is_link(path):
                raise ValueError("下载目录不能经过符号链接或目录联接")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        value = self.root.stat()
        if not stat.S_ISDIR(value.st_mode):
            raise ValueError("下载目录不是普通目录")
        identity = _identity(value)
        if self.root_identity is not None and identity != self.root_identity:
            raise ValueError("下载目录身份已变化，不修改其中的文件")
        self.root_identity = identity

    def _occupied(self):
        owned = {sink.path: sink for sink in self.active}
        total, pending = 0, [self.root]
        while pending:
            for path in pending.pop().iterdir():
                if _is_link(path):
                    raise ValueError("下载目录含符号链接或目录联接，不跟随外部路径")
                value = path.stat()
                if stat.S_ISDIR(value.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(value.st_mode):
                    if path in owned:
                        if _identity(value) != owned[path].identity:
                            raise ValueError("下载临时文件身份已变化，不忽略替换文件的占用")
                    else:
                        total += value.st_size
                else:
                    raise ValueError("下载目录包含非普通文件")
        return total

    @staticmethod
    def _validate_policy(policy):
        if (not isinstance(policy.filename, str) or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", policy.filename)
                or policy.filename.endswith(".")
                or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]",
                                policy.filename.split(".", 1)[0], re.I)):
            raise ValueError("下载文件名须为不含路径的稳定业务标识")
        if policy.expected_sha256 is not None and (
                not isinstance(policy.expected_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", policy.expected_sha256)):
            raise ValueError("文件预期摘要格式无效")
        if not isinstance(policy.signature, bytes) or len(policy.signature) > 4096:
            raise ValueError("文件签名须为不超过 4096 字节的 bytes")
        if type(policy.max_body_bytes) is not int or policy.max_body_bytes < 1:
            raise ValueError("文件正文上限须为正整数")

    def begin(self, policy):
        self._validate_policy(policy)
        with self.lock:
            self._check_root(create=True)
            target = self.root / policy.filename
            if target.exists() or target.is_symlink() or any(s.target == target for s in self.active):
                raise ValueError("下载目标已存在或正在下载，不覆盖已有文件")
            if len(self.active) >= self.concurrency:
                raise ValueError("文件下载并发已达到上限")
            occupied, reserved = self._occupied(), sum(self.active.values())
            if occupied + reserved + policy.max_body_bytes > self.quota:
                raise ValueError("文件下载目录配额不足；保留已有文件")
            if shutil.disk_usage(self.root).free < self.min_free + reserved + policy.max_body_bytes:
                raise ValueError("磁盘空间不足以安全完成本次下载")
            sink = FileSink(self, policy)
            self.active[sink] = policy.max_body_bytes
            return sink

    def end(self, sink):
        with self.lock:
            if sink.store is not self:
                raise ValueError("不能清理其他下载存储拥有的文件")
            sink.close()
            self.active.pop(sink, None)
