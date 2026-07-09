import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Isolate all file I/O under a per-test HOME.

    MemoryStore/SessionStore/tools.py resolve ``~/kidecon`` via ``Path.home()``,
    which reads $HOME. Pointing HOME at a tmp dir keeps tests from polluting the
    real user's ``~/kidecon`` directory and gives every test a clean slate.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
