"""Short, explicitly owned temporary directories for filesystem operations."""

from contextlib import contextmanager
from pathlib import Path
import shutil
from tempfile import gettempdir
from uuid import uuid4


@contextmanager
def isolated_directory(parent=None, prefix="gk_"):
    base = Path(parent if parent is not None else gettempdir()).resolve()
    work = base / (prefix + uuid4().hex[:10])
    # Windows tempfile can retry an unmapped permission failure many times.
    work.mkdir()
    try:
        yield work
    finally:
        if work.exists():
            resolved = work.resolve()
            if resolved != work or not resolved.is_relative_to(base) or resolved == base:
                raise OSError("Temporary directory moved outside its owned parent")
            shutil.rmtree(resolved)
