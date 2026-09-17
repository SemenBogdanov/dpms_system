"""Non-secret crash marker: never store prompts, identifiers, or credentials."""

import os
from pathlib import Path
import stat
from datetime import datetime, timezone
from uuid import uuid4


class RecoveryState:
    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Recovery directory must be private and owned by this user")
        self.marker = self.directory / "inference-pending"
        self.owned = False

    @property
    def pending(self) -> bool:
        return self.marker.exists() or self.marker.is_symlink()

    def begin(self):
        fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.owned = True
        try:
            os.write(fd, b"pending\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        self._sync_directory()

    def finish(self):
        if not self.owned:
            raise RuntimeError("Cannot clear a marker from another process")
        self.marker.unlink()
        self._sync_directory()
        self.owned = False

    def archive_pending(self) -> Path:
        """Archive an operator-confirmed stale marker without reading its contents."""
        if self.owned:
            raise RuntimeError("Cannot archive a marker owned by the active process")
        info = self.marker.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size != len(b"pending\n")
            or info.st_nlink != 1
        ):
            raise ValueError("Recovery marker is not a private regular file")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archived = self.directory / f"recovered-{stamp}-{uuid4().hex[:8]}.marker"
        os.link(self.marker, archived, follow_symlinks=False)
        current_info = self.marker.lstat()
        archived_info = archived.lstat()
        expected_identity = (info.st_dev, info.st_ino)
        if (
            not stat.S_ISREG(archived_info.st_mode)
            or (current_info.st_dev, current_info.st_ino) != expected_identity
            or (archived_info.st_dev, archived_info.st_ino) != expected_identity
        ):
            archived.unlink()
            self._sync_directory()
            raise ValueError("Recovery marker changed during archival")
        self._sync_directory()
        self.marker.unlink()
        self._sync_directory()
        return archived

    def _sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
