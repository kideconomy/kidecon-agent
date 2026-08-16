"""Legal docs mirror — read-only git mirror of the protocol-docs corpus.

Maintains a shallow, read-only local copy of the legal protocol docs repo
(default ``kideconomy/kideconomy-protocol-docs``) inside the agent workspace
so the comparison skill can read full documents locally while Lexor remains
the source of guidance and ground truth.

Three-layer staff-only enforcement (mirrors ``wrappers/lexor_client.py``):
  1. Provisioning: only staff agents have ``api_key_github-docs`` in the
     keyring (a read-only fine-grained PAT scoped to the docs repo).
  2. Local tier gate: ``sync()`` refuses unless ``agent_hub_tier >= min_hub_tier``.
  3. Read-only by construction: only clone/fetch/merge --ff-only/rev-parse are
     ever run. The mirror never pushes, creates branches, or commits.

Credential hygiene: the PAT is injected per-invocation via
``git -c http.extraheader=...`` and is never stored on disk (the remote URL in
``.git/config`` stays credential-free), never logged, and never placed in a
trace. Residual exposure: for the duration of each clone/fetch the header is
visible in the git process argv (``/proc/<pid>/cmdline``) to the same user and
root — the same principal that can already read the keyring directly, so this
does not widen the trust boundary, but it is broader than the Lexor JWT path
(which travels as an HTTP header). All errors return transparent three-part
messages (what happened / why / what to do next) instead of raising, so a
mirror failure never breaks a turn — the agent degrades to the last local
copy and says so.
"""

import base64
import logging
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from wrappers.keys import KEYRING_SERVICE
from wrappers.keys import api_key
from wrappers.tools import workspace_dir

logger = logging.getLogger(__name__)

KEYRING_KEY = api_key("github-docs")

DOCS_MIRROR_DIRNAME = "legal-docs"

DEFAULT_REPO_URL = "https://github.com/kideconomy/kideconomy-protocol-docs.git"
DEFAULT_BRANCH = "main"
DEFAULT_MIN_HUB_TIER = 3
DEFAULT_CLONE_TIMEOUT = 120.0
DEFAULT_FETCH_TIMEOUT = 60.0

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")


def _validate_repo_url(repo_url: str) -> None:
    """Reject anything that is not a plain https URL without embedded credentials."""
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("docs.repo_url must be a plain https URL with no embedded credentials")


def _validate_branch(branch: str) -> None:
    if not _BRANCH_RE.match(branch):
        raise ValueError(f"docs.branch is not a safe branch name: {branch!r}")


def _default_runner(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    # Fixed argv, shell=False: argv is built only from validated config values.
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


class DocsMirror:
    """Read-only local mirror of the legal protocol docs repository.

    Constructed at boot only when ``docs.enabled`` is true and a keyring
    credential is present. When ``None`` is passed to ``CognitiveEngine``, the
    mirror is disabled and the agent behaves exactly as before.
    """

    def __init__(
        self,
        repo_url: str = DEFAULT_REPO_URL,
        branch: str = DEFAULT_BRANCH,
        mirror_dir: Path | None = None,
        min_hub_tier: int = DEFAULT_MIN_HUB_TIER,
        clone_timeout: float = DEFAULT_CLONE_TIMEOUT,
        fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
        runner=None,
    ) -> None:
        _validate_repo_url(repo_url)
        _validate_branch(branch)
        self.repo_url = repo_url
        self.branch = branch
        # Resolved lazily so tests that patch Path.home() per-test isolate cleanly.
        self.dir = Path(mirror_dir) if mirror_dir else workspace_dir() / DOCS_MIRROR_DIRNAME
        self.min_hub_tier = min_hub_tier
        self.clone_timeout = clone_timeout
        self.fetch_timeout = fetch_timeout
        # runner is injectable for tests: (argv, timeout) -> CompletedProcess.
        self._runner = runner or _default_runner

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def exists(self) -> bool:
        """True when a local clone is already present."""
        return (self.dir / ".git").is_dir()

    def sync(self, agent_hub_tier: int) -> dict:
        """Clone (first use) or fast-forward the mirror.

        Returns a dict with:
          ok: bool — the mirror is usable (possibly stale) after this call.
          cloned: bool — a fresh clone happened on this call.
          fresh: bool — the mirror matches the remote branch tip.
          commit: str | None — HEAD SHA after the call, when known.
          error: str | None — three-part message when the mirror is unusable.
          warning: str | None — three-part staleness disclosure when the remote
                  refresh failed but the existing copy is still usable.
        Never raises.
        """
        if agent_hub_tier < self.min_hub_tier:
            return self._blocked(
                "Docs mirror sync was blocked.",
                f"The legal docs mirror is staff-only (your tier: {agent_hub_tier}).",
                "Ask your administrator to request staff access.",
            )

        token = self._read_token()
        if token is None:
            return self._blocked(
                "Docs mirror sync was skipped.",
                "No docs credential is configured for this agent.",
                "Ask your administrator to provision a read-only token via "
                "`kidecon key add --name github-docs --value <pat>`.",
            )

        if not self.exists():
            return self._clone(token)
        return self._pull(token)

    def head_commit(self) -> str | None:
        """Current HEAD SHA of the mirror, or None when unavailable."""
        proc = self._run_git(["git", "-C", str(self.dir), "rev-parse", "HEAD"], self.fetch_timeout)
        if proc is None or proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    def path(self, *parts: str) -> Path:
        """Resolve a path inside the mirror, rejecting traversal outside it."""
        target = self.dir.joinpath(*parts).resolve()
        if not target.is_relative_to(self.dir.resolve()):
            raise PermissionError(f"Access denied: path outside the docs mirror: {parts!r}")
        return target

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _run_git(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess | None:
        """Run one git command. Returns None on any failure; never raises.

        Logs only the subcommand and outcome — never the argv, which carries
        the per-invocation auth header.
        """
        op = next((a for a in argv if a in ("clone", "fetch", "merge", "rev-parse")), "git")
        try:
            return self._runner(argv, timeout)
        except subprocess.TimeoutExpired:
            logger.warning("docs mirror op timed out (op=%s)", op)
            return None
        except Exception:
            logger.exception("docs mirror op failed to run (op=%s)", op)
            return None

    def _auth_args(self, token: str) -> list[str]:
        """Per-invocation auth so the PAT never lands in .git/config or on disk."""
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return ["-c", f"http.extraheader=Authorization: Basic {encoded}"]

    def _clone(self, token: str) -> dict:
        started = time.monotonic()
        argv = [
            "git",
            *self._auth_args(token),
            "clone",
            "--depth",
            "1",
            "--branch",
            self.branch,
            self.repo_url,
            str(self.dir),
        ]
        proc = self._run_git(argv, self.clone_timeout)
        if proc is None:
            return self._blocked(
                "Docs mirror setup failed.",
                "Cloning the docs repository did not complete.",
                "Retry later; if it persists, check network access to GitHub and that git is installed.",
            )
        if proc.returncode != 0:
            # Never log stderr: git errors can echo URLs/config values.
            logger.warning("docs mirror clone failed (rc=%d)", proc.returncode)
            return self._blocked(
                "Docs mirror setup failed.",
                "The docs repository could not be cloned.",
                "Check docs.repo_url and that the credential has read access, then retry.",
            )
        commit = self.head_commit()
        logger.info(
            "docs mirror cloned (branch=%s, commit=%s, %.1fs)",
            self.branch,
            commit,
            time.monotonic() - started,
        )
        return {"ok": True, "cloned": True, "fresh": True, "commit": commit, "error": None, "warning": None}

    def _pull(self, token: str) -> dict:
        started = time.monotonic()
        before = self.head_commit()
        fetch_argv = [
            "git",
            *self._auth_args(token),
            "-C",
            str(self.dir),
            "fetch",
            "--depth",
            "1",
            "origin",
            self.branch,
        ]
        proc = self._run_git(fetch_argv, self.fetch_timeout)
        if proc is None:
            return self._stale(before, "the docs repository could not be reached")
        if proc.returncode != 0:
            logger.warning("docs mirror fetch failed (rc=%d)", proc.returncode)
            return self._stale(before, "the docs repository could not be reached")

        merge_argv = ["git", "-C", str(self.dir), "merge", "--ff-only", "FETCH_HEAD"]
        proc = self._run_git(merge_argv, self.fetch_timeout)
        if proc is None or proc.returncode != 0:
            logger.warning("docs mirror merge failed")
            return self._stale(before, "the local copy has diverged and cannot fast-forward")

        commit = self.head_commit()
        logger.info(
            "docs mirror synced (branch=%s, commit=%s, %.1fs)",
            self.branch,
            commit,
            time.monotonic() - started,
        )
        return {"ok": True, "cloned": False, "fresh": True, "commit": commit, "error": None, "warning": None}

    def _stale(self, commit: str | None, why: str) -> dict:
        """Mirror stays usable at its last copy; the disclosure travels to the user."""
        return {
            "ok": True,
            "cloned": False,
            "fresh": False,
            "commit": commit,
            "error": None,
            "warning": (
                "Docs mirror refresh failed — continuing with the last local copy. "
                f"Reason: {why}. "
                "To proceed: comparisons may lag the latest corpus; retry the sync later."
            ),
        }

    def _blocked(self, what: str, why: str, next_step: str) -> dict:
        return {
            "ok": False,
            "cloned": False,
            "fresh": False,
            "commit": None,
            "error": self._block_msg(what, why, next_step),
            "warning": None,
        }

    def _read_token(self) -> str | None:
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
        except Exception:
            logger.exception("keyring lookup for docs credential failed")
            return None

    @staticmethod
    def _block_msg(what: str, why: str, next_step: str) -> str:
        return f"{what} Reason: {why} To proceed: {next_step}"


def build_docs_mirror(config: dict) -> DocsMirror | None:
    """Construct a DocsMirror from agent config, or None when disabled.

    Enabled only when ``config["docs"]["enabled"]`` is true AND a keyring
    credential is present. Returns None otherwise so the runtime can pass None
    to CognitiveEngine and disable the mirror with zero behavior change.

    ``min_hub_tier`` is clamped to >= 3 (staff-only) to prevent an operator
    from silently weakening the staff-only gate via local config.
    """
    docs_config = config.get("docs") or {}
    if not docs_config.get("enabled", False):
        return None

    repo_url = docs_config.get("repo_url", DEFAULT_REPO_URL)
    branch = docs_config.get("branch", DEFAULT_BRANCH)

    min_hub_tier = int(docs_config.get("min_hub_tier", DEFAULT_MIN_HUB_TIER))
    if min_hub_tier < DEFAULT_MIN_HUB_TIER:
        logger.warning(
            "Docs min_hub_tier=%d is below the staff-only floor (%d) — "
            "clamping to %d. The docs mirror is staff-only by design.",
            min_hub_tier,
            DEFAULT_MIN_HUB_TIER,
            DEFAULT_MIN_HUB_TIER,
        )
        min_hub_tier = DEFAULT_MIN_HUB_TIER

    try:
        mirror = DocsMirror(repo_url=repo_url, branch=branch, min_hub_tier=min_hub_tier)
    except ValueError:
        logger.exception("Docs config is invalid — disabling mirror")
        return None

    if mirror._read_token() is None:
        logger.warning(
            "Docs enabled but no %s in keyring — run "
            "`kidecon key add --name github-docs --value <pat>`. Disabling until provisioned.",
            KEYRING_KEY,
        )
        return None

    logger.info("Docs mirror ready (repo=%s, branch=%s)", repo_url, branch)
    return mirror
