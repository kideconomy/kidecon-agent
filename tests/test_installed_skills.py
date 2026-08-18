import logging
from unittest.mock import MagicMock

import yaml
from typer.testing import CliRunner

from cli import kidecon as cli
from wrappers.installed_skills import INSTALLED_KEY
from wrappers.installed_skills import get_installed_skills
from wrappers.installed_skills import resolve_config_path
from wrappers.installed_skills import set_installed

logger = logging.getLogger(__name__)

runner = CliRunner()


# ------------------------------------------------------------------
# installed_skills persistence helpers
# ------------------------------------------------------------------
def test_get_installed_skills_defaults_empty():
    assert get_installed_skills() == []


def test_set_installed_add_round_trip():
    result = set_installed("docs-mirror", add=True)
    assert "docs-mirror" in result
    assert get_installed_skills() == ["docs-mirror"]
    data = yaml.safe_load(resolve_config_path().read_text())
    assert data[INSTALLED_KEY] == ["docs-mirror"]


def test_set_installed_remove():
    set_installed("docs-mirror", add=True)
    set_installed("clickup-ticket", add=True)
    result = set_installed("docs-mirror", add=False)
    assert result == ["clickup-ticket"]


def test_set_installed_case_insensitive_idempotent():
    set_installed("Docs-Mirror", add=True)
    result = set_installed("docs-mirror", add=True)
    # first casing is preserved; re-adding different casing is a no-op
    assert result == ["Docs-Mirror"]


def test_set_installed_creates_config_file():
    result = set_installed("alpha", add=True)
    assert result == ["alpha"]
    assert resolve_config_path().exists()


def test_set_installed_preserves_existing_config_keys():
    path = resolve_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"hub_url": "http://localhost:8000", "skills": {"x": {"config": 1}}}))
    set_installed("alpha", add=True)
    data = yaml.safe_load(path.read_text())
    assert data["hub_url"] == "http://localhost:8000"
    assert data[INSTALLED_KEY] == ["alpha"]


def test_set_installed_preserves_key_order():
    path = resolve_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    original = {"hub_url": "http://localhost:8000", "skills": {"x": {"config": 1}}}
    path.write_text(yaml.dump(original, sort_keys=False))
    set_installed("alpha", add=True)
    data = yaml.safe_load(path.read_text())
    # sort_keys=False keeps insertion order, not alphabetical
    # (alphabetical would put installed_skills before skills).
    assert list(data.keys()) == ["hub_url", "skills", INSTALLED_KEY]


# ------------------------------------------------------------------
# CLI install/uninstall/list
# ------------------------------------------------------------------
def _catalog_client():
    client = MagicMock()
    client.discover_skills.return_value = [
        {"id": "sk-docs", "name": "docs-mirror", "version": "1.0.0", "category": "documentation"},
        {"id": "sk-click", "name": "clickup-ticket", "version": "1.0.0", "category": "tool"},
    ]
    return client


def test_skills_install_ok(monkeypatch):
    client = _catalog_client()
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    result = runner.invoke(cli.app, ["skills", "install", "docs-mirror"])
    assert result.exit_code == 0
    assert "docs-mirror" in result.output
    assert get_installed_skills() == ["docs-mirror"]


def _client_with_install_message(install_message):
    client = MagicMock()
    client.discover_skills.return_value = [
        {
            "id": "sk-fun",
            "name": "fun-facts",
            "version": "1.0.0",
            "category": "knowledge",
            "description": "Provides fun facts on demand.",
            "config": {"install_message": install_message},
        },
    ]
    return client


def test_skills_install_prints_author_install_message(monkeypatch):
    msg = "You can now ask Hermes for a fun fact any time you like!"
    client = _client_with_install_message(msg)
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    result = runner.invoke(cli.app, ["skills", "install", "fun-facts"])
    assert result.exit_code == 0
    assert "Congratulations" in result.output
    assert msg in result.output
    assert get_installed_skills() == ["fun-facts"]


def test_skills_install_falls_back_to_description(monkeypatch):
    client = _client_with_install_message(None)
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    result = runner.invoke(cli.app, ["skills", "install", "fun-facts"])
    assert result.exit_code == 0
    # No author message → the one-line description is shown instead.
    assert "Provides fun facts on demand." in result.output
    assert get_installed_skills() == ["fun-facts"]


def test_skills_install_by_id_resolves_to_name(monkeypatch):
    client = _catalog_client()
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    result = runner.invoke(cli.app, ["skills", "install", "sk-docs"])
    assert result.exit_code == 0
    # stored under the canonical name, not the id
    assert get_installed_skills() == ["docs-mirror"]


def test_skills_install_rejects_unknown(monkeypatch):
    client = _catalog_client()
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    result = runner.invoke(cli.app, ["skills", "install", "does-not-exist"])
    assert result.exit_code == 1
    assert "not found" in result.output
    assert get_installed_skills() == []


def test_skills_install_rejects_not_tier_accessible(monkeypatch):
    # A tier-blocked / out-of-tier skill is absent from this agent's discover
    # catalog, so the install is rejected (no hub write, no local write).
    client = _catalog_client()
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    result = runner.invoke(cli.app, ["skills", "install", "staff-only-skill"])
    assert result.exit_code == 1
    assert get_installed_skills() == []


def test_skills_uninstall(monkeypatch):
    set_installed("docs-mirror", add=True)
    result = runner.invoke(cli.app, ["skills", "uninstall", "docs-mirror"])
    assert result.exit_code == 0
    assert get_installed_skills() == []


def test_skills_list_shows_installed_and_available(monkeypatch):
    client = _catalog_client()
    monkeypatch.setattr(cli, "require_auth", lambda: client)
    set_installed("docs-mirror", add=True)
    result = runner.invoke(cli.app, ["skills", "list"])
    assert result.exit_code == 0
    assert "Installed" in result.output
    assert "docs-mirror" in result.output
    assert "Available" in result.output
    assert "clickup-ticket" in result.output
