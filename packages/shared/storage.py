import shutil
from pathlib import Path
from typing import Protocol

from packages.shared.config import settings


class Storage(Protocol):
    def resolve(self, key: str) -> Path: ...
    def remove_tree(self, key: str) -> None: ...


class LocalStorage:
    """Replace this boundary with encrypted object storage for a hosted deployment."""

    def resolve(self, key: str) -> Path:
        root = settings().storage_root.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Invalid storage key")
        return path

    def remove_tree(self, key: str) -> None:
        path = self.resolve(key)
        if path == settings().storage_root.resolve():
            raise ValueError("Cannot remove storage root")
        shutil.rmtree(path, ignore_errors=True)


storage = LocalStorage()
