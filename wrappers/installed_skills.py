"""Local skill opt-in set — the user's explicitly installed skills.

A user must explicitly opt in to a skill before their agent can use it. The
installed set lives in ``kidecon.yaml`` under the top-level ``installed_skills``
key (a list of skill names). It is **per-user**: one install set is shared by
all of that user's agents, because the config file is shared.

This module is the single read/write accessor for that key — the CLI
``kidecon skills install/uninstall`` commands and the runtime both go through
it so the on-disk format never drifts between writers.

The install set is **not** a security control. The hub remains the authority
for tier/block gating on ``discover``/``get_skill``; this is a UX opt-in that
decides which in-tier skills are *active* for cognition. The active index is
``installed ∩ tier-accessible catalog`` (see ``wrappers/skill_loader.py``).

Config path resolution mirrors ``cli.kidecon.load_config`` so this module reads
and writes the same file the rest of the CLI uses.
"""

import logging
import pathlib

import yaml
from yaml import YAMLError

logger = logging.getLogger(__name__)

CONFIG_PATH = "kidecon.yaml"
INSTALLED_KEY = "installed_skills"


def resolve_config_path() -> pathlib.Path:
    """Return the config path that ``load_config`` would read, or the home default.

    Matches the candidate order in ``cli.kidecon.load_config``: cwd first, then
    ``~/.config/kidecon/kidecon.yaml``. When no candidate exists, returns the
    home default so a fresh ``set_installed`` creates it in the canonical place.
    """
    candidates = [
        pathlib.Path(CONFIG_PATH),
        pathlib.Path.home() / ".config" / "kidecon" / "kidecon.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return pathlib.Path.home() / ".config" / "kidecon" / "kidecon.yaml"


def _read_config() -> dict:
    path = resolve_config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_bytes())
    except OSError as exc:
        logger.warning("Could not read %s — treating as empty config: %s", path, exc)
        return {}
    except YAMLError as exc:
        logger.warning("Could not parse %s — treating as empty config: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_config(data: dict) -> pathlib.Path:
    path = resolve_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys=False preserves the user's existing key ordering in kidecon.yaml.
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return path


def get_installed_skills() -> list[str]:
    """Return the installed skill-name list (stripped, non-empty, order-preserving)."""
    data = _read_config()
    raw = data.get(INSTALLED_KEY) or []
    if not isinstance(raw, list):
        logger.warning("%s is not a list in %s — treating as empty", INSTALLED_KEY, resolve_config_path())
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def set_installed(name: str, *, add: bool) -> list[str]:
    """Add (add=True) or remove (add=False) a skill name from the install set.

    Names are stored verbatim and matched case-insensitively so a re-install
    with different casing is idempotent. Returns the resulting list (read back
    from disk) so callers can display the new state immediately.
    """
    target = (name or "").strip()
    data = _read_config()
    current = data.get(INSTALLED_KEY) or []
    if not isinstance(current, list):
        current = []
    current = [str(x).strip() for x in current if str(x).strip()]
    lower = {x.lower() for x in current}
    if add:
        if target and target.lower() not in lower:
            current.append(target)
    else:
        current = [x for x in current if x.lower() != target.lower()]
    data[INSTALLED_KEY] = current
    _write_config(data)
    return get_installed_skills()


def installed_lower_set(names: list[str] | None) -> set[str]:
    """Helper for callers that just need a lowercase lookup set."""
    return {(x or "").lower() for x in (names or []) if x}
