"""Non-secret crash marker: never store prompts, identifiers, or credentials."""

import os
from pathlib import Path
import stat


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

    def _sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
