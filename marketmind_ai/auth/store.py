"""Atomic owner-only local credentials with process-wide rotating-token locks."""
from __future__ import annotations

from contextlib import contextmanager
try:
    import fcntl
except ImportError:  # The CLI remains importable on platforms without secure POSIX storage.
    fcntl = None
import json
import os
from pathlib import Path
import secrets
import stat
import uuid

from .errors import PlanError


class CredentialStore:
    def __init__(self, root: Path):
        self.directory = Path(root) / "chatgpt-plan"

    def __repr__(self):
        return "<CredentialStore>"

    @contextmanager
    def locked(self):
        """Lock across reading, remote refresh/revocation, and atomic replacement."""
        if fcntl is None or not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "getuid", "fchmod")):
            raise PlanError("unsupported_storage_platform")
        dfd = lfd = None
        try:
            root = self.directory.parent
            if root.is_symlink():
                raise PlanError("unsafe_storage")
            root.mkdir(parents=True, exist_ok=True)
            self.directory.mkdir(mode=0o700, exist_ok=True)
            dfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._check_owned(dfd, directory=True)
            os.fchmod(dfd, 0o700)
            lfd = os.open("credentials.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
            self._check_owned(lfd)
            os.fchmod(lfd, 0o600)
            fcntl.flock(lfd, fcntl.LOCK_EX)
            data = self._read(dfd)
            yield StoreTransaction(dfd, data)
        except PlanError:
            raise
        except (OSError, ValueError, TypeError, KeyError):
            raise PlanError("unsafe_storage" if self.directory.is_symlink() or (self.directory / "credentials.json").is_symlink() else "storage_error") from None
        finally:
            if lfd is not None:
                os.close(lfd)
            if dfd is not None:
                os.close(dfd)

    @staticmethod
    def _check_owned(fd, directory=False):
        info = os.fstat(fd)
        if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                or info.st_uid != os.getuid() or (not directory and info.st_nlink != 1)):
            raise PlanError("unsafe_storage")

    def _read(self, dfd):
        try:
            fd = os.open("credentials.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        except FileNotFoundError:
            return {"version": 1, "accounts": {}}
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            self._check_owned(stream.fileno())
            os.fchmod(stream.fileno(), 0o600)
            data = json.load(stream)
        if (not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("accounts"), dict)):
            raise PlanError("storage_error")
        return data


class StoreTransaction:
    def __init__(self, dfd, data):
        self._dfd = dfd
        self.data = data

    def __repr__(self):
        return "<StoreTransaction>"

    def host_id(self):
        if not self.data.get("ext_agent_host_id"):
            self.data["ext_agent_host_id"] = "urn:uuid:" + str(uuid.uuid4())
            self.save()
        return self.data["ext_agent_host_id"]

    def save(self):
        name = ".credentials-" + secrets.token_hex(16)
        fd = None
        try:
            try:
                info = os.stat("credentials.json", dir_fd=self._dfd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                    raise PlanError("unsafe_storage")
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self._dfd)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                fd = None
                os.fchmod(stream.fileno(), 0o600)
                json.dump(self.data, stream, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, "credentials.json", src_dir_fd=self._dfd, dst_dir_fd=self._dfd)
            os.fsync(self._dfd)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(name, dir_fd=self._dfd)
            except FileNotFoundError:
                pass
