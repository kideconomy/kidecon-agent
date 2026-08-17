"""Tests for wrappers/docs_mirror.py — the read-only legal docs mirror.

Covers: the staff-only tier gate, keyring provisioning blocks, clone/pull
behavior via an injected runner, staleness degradation with disclosure,
credential hygiene (PAT never logged), path traversal rejection, config
validation, and build_docs_mirror enablement rules.
"""

import logging
from types import SimpleNamespace

import keyring
import pytest

from wrappers.docs_mirror import DEFAULT_REPO_URL
from wrappers.docs_mirror import KEYRING_KEY
from wrappers.docs_mirror import DocsMirror
from wrappers.docs_mirror import build_docs_mirror
from wrappers.hub_client import KEYRING_SERVICE

logger = logging.getLogger(__name__)


class FakeRunner:
    """Records argv lists and returns canned CompletedProcess-like results."""

    def __init__(self, results=None, raise_exc=None):
        self.calls: list[list[str]] = []
        self.results = results or {}
        self.raise_exc = raise_exc

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if self.raise_exc is not None:
            raise self.raise_exc
        op = "clone" if "clone" in argv else ("fetch" if "fetch" in argv else ("merge" if "merge" in argv else "rev-parse"))
        default = SimpleNamespace(returncode=0, stdout="abc1234def5678\n", stderr="")
        return self.results.get(op, default)


@pytest.fixture
def docs_token(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda service, key: "ghp_testtoken")


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda service, key: None)


def _mirror(tmp_path, runner=None, **kwargs):
    return DocsMirror(
        mirror_dir=tmp_path / "workspace" / "legal-docs",
        runner=runner or FakeRunner(),
        **kwargs,
    )


# ------------------------------------------------------------------
# staff-only tier gate
# ------------------------------------------------------------------
def test_sync_blocked_below_min_tier_without_any_subprocess(tmp_path, docs_token):
    runner = FakeRunner()
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=2)
    assert result["ok"] is False
    assert "staff-only" in result["error"]
    assert "your tier: 2" in result["error"]
    assert "To proceed:" in result["error"]
    assert runner.calls == []


def test_sync_allowed_at_tier_3(tmp_path, docs_token):
    mirror = _mirror(tmp_path, runner=FakeRunner())
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True


# ------------------------------------------------------------------
# provisioning block
# ------------------------------------------------------------------
def test_sync_blocked_without_keyring_credential(tmp_path, no_token):
    runner = FakeRunner()
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is False
    assert "kidecon key add --name github-docs" in result["error"]
    assert runner.calls == []


# ------------------------------------------------------------------
# clone path
# ------------------------------------------------------------------
def test_first_sync_clones_shallow_with_auth_header_and_clean_url(tmp_path, docs_token):
    runner = FakeRunner()
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True
    assert result["cloned"] is True
    assert result["fresh"] is True
    assert result["commit"] == "abc1234def5678"
    assert result["error"] is None
    assert result["warning"] is None

    clone_argv = runner.calls[0]
    assert clone_argv[0] == "git"
    assert "clone" in clone_argv
    assert "--depth" in clone_argv
    assert "1" in clone_argv
    assert "--branch" in clone_argv
    assert "main" in clone_argv
    assert DEFAULT_REPO_URL in clone_argv
    # Auth travels as a per-invocation -c http.extraheader, never in the URL.
    auth_args = [a for a in clone_argv if a.startswith("http.extraheader=")]
    assert len(auth_args) == 1
    assert "Authorization: Basic" in auth_args[0]
    assert "ghp_testtoken" not in DEFAULT_REPO_URL


def test_clone_failure_returns_three_part_block(tmp_path, docs_token, caplog):
    runner = FakeRunner(results={"clone": SimpleNamespace(returncode=128, stdout="", stderr="fatal: secret-url-echo")})
    mirror = _mirror(tmp_path, runner=runner)
    with caplog.at_level(logging.DEBUG, logger="wrappers.docs_mirror"):
        result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is False
    assert "could not be cloned" in result["error"]
    assert "Reason:" in result["error"]
    assert "To proceed:" in result["error"]
    # git stderr can echo URLs/config — it must never reach the logs.
    assert "secret-url-echo" not in caplog.text


def test_unexpected_runner_exception_never_raises_out_of_sync(tmp_path, docs_token):
    _existing_clone(tmp_path)

    class ExplodingRunner(FakeRunner):
        def __call__(self, argv, timeout):
            if "fetch" in argv:
                raise RuntimeError("runner exploded")
            return super().__call__(argv, timeout)

    mirror = _mirror(tmp_path, runner=ExplodingRunner())
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True
    assert result["fresh"] is False
    assert result["warning"] is not None


def test_clone_timeout_returns_block(tmp_path, docs_token):
    import subprocess

    runner = FakeRunner(raise_exc=subprocess.TimeoutExpired(cmd="git", timeout=1))
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is False
    assert "did not complete" in result["error"]


def test_pat_never_appears_in_logs(tmp_path, docs_token, caplog):
    mirror = _mirror(tmp_path, runner=FakeRunner())
    with caplog.at_level(logging.DEBUG, logger="wrappers.docs_mirror"):
        mirror.sync(agent_hub_tier=3)
    assert "ghp_testtoken" not in caplog.text


# ------------------------------------------------------------------
# pull path (existing clone)
# ------------------------------------------------------------------
def _existing_clone(tmp_path):
    mirror_dir = tmp_path / "workspace" / "legal-docs"
    (mirror_dir / ".git").mkdir(parents=True)
    return mirror_dir


def test_sync_existing_clone_fetches_and_fast_forwards(tmp_path, docs_token):
    _existing_clone(tmp_path)
    runner = FakeRunner()
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True
    assert result["cloned"] is False
    assert result["fresh"] is True
    ops = ["clone" if "clone" in c else "fetch" if "fetch" in c else "merge" if "merge" in c else "rev-parse" for c in runner.calls]
    assert "clone" not in ops
    assert "fetch" in ops
    assert "merge" in ops
    merge_argv = next(c for c in runner.calls if "merge" in c)
    assert "--ff-only" in merge_argv


def test_fetch_failure_degrades_to_stale_copy_with_disclosure(tmp_path, docs_token):
    _existing_clone(tmp_path)
    runner = FakeRunner(results={"fetch": SimpleNamespace(returncode=128, stdout="", stderr="net down")})
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True
    assert result["fresh"] is False
    assert result["error"] is None
    assert result["warning"] is not None
    assert "last local copy" in result["warning"]
    assert "Reason:" in result["warning"]


def test_merge_failure_degrades_to_stale_copy(tmp_path, docs_token):
    _existing_clone(tmp_path)
    runner = FakeRunner(results={"merge": SimpleNamespace(returncode=1, stdout="", stderr="diverged")})
    mirror = _mirror(tmp_path, runner=runner)
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True
    assert result["fresh"] is False
    assert "diverged" in result["warning"]


def test_fetch_timeout_degrades_to_stale_copy(tmp_path, docs_token):
    import subprocess

    _existing_clone(tmp_path)

    class TimeoutOnFetch(FakeRunner):
        def __call__(self, argv, timeout):
            if "fetch" in argv:
                raise subprocess.TimeoutExpired(cmd="git", timeout=1)
            return super().__call__(argv, timeout)

    mirror = _mirror(tmp_path, runner=TimeoutOnFetch())
    result = mirror.sync(agent_hub_tier=3)
    assert result["ok"] is True
    assert result["fresh"] is False
    assert "could not be reached" in result["warning"]


# ------------------------------------------------------------------
# path containment
# ------------------------------------------------------------------
def test_path_resolves_inside_mirror(tmp_path, docs_token):
    mirror = _mirror(tmp_path)
    target = mirror.path("01_corpus", "protocol", "lexicon.md")
    assert target == (mirror.dir / "01_corpus" / "protocol" / "lexicon.md").resolve()


def test_path_rejects_traversal(tmp_path, docs_token):
    mirror = _mirror(tmp_path)
    with pytest.raises(PermissionError):
        mirror.path("..", "..", "etc", "passwd")


# ------------------------------------------------------------------
# config validation
# ------------------------------------------------------------------
def test_repo_url_with_embedded_credentials_rejected(tmp_path):
    with pytest.raises(ValueError, match="no embedded credentials"):
        DocsMirror(repo_url="https://user:tok@github.com/x/y.git", mirror_dir=tmp_path)


def test_non_https_repo_url_rejected(tmp_path):
    with pytest.raises(ValueError, match="plain https"):
        DocsMirror(repo_url="http://github.com/x/y.git", mirror_dir=tmp_path)


def test_unsafe_branch_rejected(tmp_path):
    with pytest.raises(ValueError, match="safe branch name"):
        DocsMirror(branch="main; rm -rf /", mirror_dir=tmp_path)


# ------------------------------------------------------------------
# build_docs_mirror
# ------------------------------------------------------------------
def test_build_returns_none_when_disabled(no_token):
    assert build_docs_mirror({}) is None
    assert build_docs_mirror({"docs": {"enabled": False}}) is None


def test_build_returns_none_when_enabled_but_no_credential(no_token):
    assert build_docs_mirror({"docs": {"enabled": True}}) is None


def test_build_returns_mirror_when_enabled_and_provisioned(docs_token):
    mirror = build_docs_mirror({"docs": {"enabled": True}})
    assert mirror is not None
    assert mirror.branch == "main"
    assert mirror.repo_url == DEFAULT_REPO_URL


def test_build_clamps_min_hub_tier_to_staff_floor(docs_token):
    mirror = build_docs_mirror({"docs": {"enabled": True, "min_hub_tier": 1}})
    assert mirror is not None
    assert mirror.min_hub_tier == 3


def test_build_returns_none_on_invalid_repo_url(docs_token):
    assert build_docs_mirror({"docs": {"enabled": True, "repo_url": "http://nope"}}) is None


def test_build_respects_subfolder_config(docs_token):
    mirror = build_docs_mirror({"docs": {"enabled": True, "subfolder": "my-corpus"}})
    assert mirror is not None
    assert mirror.dir.name == "my-corpus"


def test_build_rejects_unsafe_subfolder(docs_token):
    assert build_docs_mirror({"docs": {"enabled": True, "subfolder": "../etc"}}) is None


def test_build_defaults_subfolder_to_legal_docs(docs_token):
    mirror = build_docs_mirror({"docs": {"enabled": True}})
    assert mirror is not None
    assert mirror.dir.name == "legal-docs"


def test_keyring_key_matches_cli_convention():
    # `kidecon key add --name github-docs` stores api_key_github-docs.
    assert KEYRING_KEY == "api_key_github-docs"
    assert KEYRING_SERVICE == "kidecon-agent"
