# SECURITY: This is a permission gate, not a sandbox. No seccomp/AppArmor
# isolation, no net-egress block. Upgrade path: see AGENT_NETWORK_REFERENCE.md
# §1.5 for real sandbox requirements (seccomp, AppArmor, network egress blocking).
import logging
import subprocess
from datetime import UTC
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path.home() / "kidecon" / "user_scripts"
TIMEOUT_SECONDS = 60
APPROVED_FILE = Path.home() / "kidecon" / ".approved_scripts"


class UserScriptSandbox:
    def __init__(self):
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        APPROVED_FILE.touch()

    def _is_approved(self, script_name: str) -> bool:
        approved_lines = APPROVED_FILE.read_text().splitlines()
        return any(line.startswith(f"{script_name}\t") for line in approved_lines)

    def _approve(self, script_name: str, reason: str = "user") -> None:
        approved_lines = APPROVED_FILE.read_text().splitlines()
        if not any(line.startswith(f"{script_name}\t") for line in approved_lines):
            timestamp = datetime.now(UTC).isoformat()
            with APPROVED_FILE.open("a") as f:
                f.write(f"{script_name}\t{timestamp}\tapproved\t{reason}\n")

    def execute(self, script_name: str, args: list[str] | None = None, auto_approve: bool = False) -> dict:
        script_path = SCRIPTS_DIR / f"{script_name}.py"
        if not script_path.exists():
            return {"error": f"Script not found: {script_name}"}

        if not self._is_approved(script_name):
            if not auto_approve:
                return {"error": "First run requires approval", "requires_approval": True}
            self._approve(script_name)

        cmd = ["python", str(script_path), *(args or [])]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=str(SCRIPTS_DIR),
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Script timed out after {TIMEOUT_SECONDS}s"}
