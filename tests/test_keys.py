import json
import logging

from wrappers.keys import enumerate_keys
from wrappers.keys import well_known_provider_specs

logger = logging.getLogger(__name__)


def _point_index_at(tmp_path, monkeypatch, providers):
    import wrappers.keys as keys_mod

    index = tmp_path / "keys.json"
    index.write_text(json.dumps(providers))
    monkeypatch.setattr(keys_mod, "INDEX_PATH", index)


class TestEnumerateKeys:
    def test_includes_legacy_and_account_slots(self, monkeypatch):
        def fake_get(svc, key):
            if key == "kideconomy_username":
                return "kid-user"
            return None

        monkeypatch.setattr("keyring.get_password", fake_get)
        entries = enumerate_keys(profile=None)

        labels = [e.label for e in entries]
        assert "hub_jwt" in labels
        assert "agent_id" in labels
        assert "kideconomy_username" in labels
        assert "kideconomy_token" in labels

        ke = next(e for e in entries if e.label == "kideconomy_username")
        assert ke.value == "kid-user"
        assert ke.secret is False
        assert ke.description

    def test_secret_flag_masks_tokens(self, monkeypatch):
        def fake_get(svc, key):
            return "super-secret-value" if key == "kideconomy_token" else None

        monkeypatch.setattr("keyring.get_password", fake_get)
        entries = enumerate_keys(profile=None)

        token = next(e for e in entries if e.label == "kideconomy_token")
        assert token.secret is True
        assert token.value == "super-secret-value"

    def test_provider_keys_enumerated_from_manifest(self, tmp_path, monkeypatch):
        _point_index_at(tmp_path, monkeypatch, ["openrouter", "github-docs"])
        monkeypatch.setattr("keyring.get_password", lambda svc, key: "ab12..." if "api_key_" in key or key == "api_key_github-docs" else None)

        entries = enumerate_keys(profile=None)
        provider_labels = [e.label for e in entries if e.category == "provider"]

        assert "openrouter" in provider_labels
        assert "github-docs" in provider_labels

    def test_well_known_provider_specs_merges_manifest(self, tmp_path, monkeypatch):
        _point_index_at(tmp_path, monkeypatch, ["my-custom-provider"])
        specs = well_known_provider_specs()
        keys = {s.key for s in specs}
        assert "openrouter" in keys
        assert "my-custom-provider" in keys

    def test_provider_keyring_key_uses_api_key_prefix(self, monkeypatch, tmp_path):
        _point_index_at(tmp_path, monkeypatch, [])
        monkeypatch.setattr("keyring.get_password", lambda svc, key: None)
        entries = enumerate_keys(profile=None)
        openrouter = next(e for e in entries if e.label == "openrouter")
        assert openrouter.key == "api_key_openrouter"

    def test_masked_property_obscures_secrets(self, monkeypatch, tmp_path):
        _point_index_at(tmp_path, monkeypatch, [])
        monkeypatch.setattr(
            "keyring.get_password",
            lambda svc, key: "sk-super-long-secret-abc123" if key == "api_key_openrouter" else None,
        )
        entries = enumerate_keys(profile=None)
        openrouter = next(e for e in entries if e.label == "openrouter")
        assert openrouter.secret is True
        assert "super-long-secret" not in openrouter.masked
        assert openrouter.masked == "sk-s...c123"

    def test_masked_property_shows_full_non_secret(self, monkeypatch, tmp_path):
        _point_index_at(tmp_path, monkeypatch, [])
        monkeypatch.setattr(
            "keyring.get_password",
            lambda svc, key: "ke-username" if key == "kideconomy_username" else None,
        )
        entries = enumerate_keys(profile=None)
        username = next(e for e in entries if e.label == "kideconomy_username")
        assert username.secret is False
        assert username.masked == "ke-username"

    def test_no_profile_does_not_include_agent_keys(self, monkeypatch, tmp_path):
        _point_index_at(tmp_path, monkeypatch, [])
        import wrappers.profile_store as ps

        monkeypatch.setattr(ps, "PROFILES_DIR", tmp_path / "agents")
        monkeypatch.setattr("keyring.get_password", lambda svc, key: None)
        entries = enumerate_keys(profile=None)
        assert not any(e.category == "agent" for e in entries)

    def test_profile_includes_per_agent_jwt_slot(self, tmp_path, monkeypatch):
        from wrappers.profile_store import Profile

        monkeypatch.setattr("keyring.get_password", lambda svc, key: None)
        prof = Profile(agent_id="ag-123", name="hermes", jwt="jwt-456", ke_username="ke-user")

        entries = enumerate_keys(profile=prof)
        agent_entries = [e for e in entries if e.category == "agent"]

        jwt = next(e for e in agent_entries if e.key == "jwt_hermes")
        assert jwt.value == "jwt-456"
        assert jwt.secret is True

        agent_id = next(e for e in agent_entries if "agent_id" in e.key)
        assert agent_id.value == "ag-123"
        assert agent_id.secret is False
