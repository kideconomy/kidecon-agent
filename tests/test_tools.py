"""Tests for the workspace local tools — focused on the new text_diff tool."""

import pytest

from wrappers import tools


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    base = tmp_path / "workspace"
    base.mkdir()
    tools.set_workspace_dir(base)
    return base


def test_set_workspace_dir_changes_resolution(tmp_path):
    custom = tmp_path / "custom"
    custom.mkdir()
    tools.set_workspace_dir(custom)
    assert tools.workspace_dir() == custom.resolve()


def test_workspace_dir_defaults_to_home(tmp_path):
    # conftest patches Path.home() to tmp_path; default is tmp_path/kidecon/workspace
    assert tools.workspace_dir() == tmp_path / "kidecon" / "workspace"


def test_text_diff_identical_files(workspace):
    (workspace / "a.md").write_text("same content\n")
    (workspace / "b.md").write_text("same content\n")
    result = tools.text_diff("a.md", "b.md")
    assert result.startswith("No differences.")


def test_text_diff_produces_unified_diff(workspace):
    (workspace / "a.md").write_text("line one\nline two\n")
    (workspace / "b.md").write_text("line one\nline TWO\n")
    result = tools.text_diff("a.md", "b.md")
    assert "--- a.md" in result
    assert "+++ b.md" in result
    assert "-line two" in result
    assert "+line TWO" in result


def test_text_diff_missing_file_returns_friendly_message(workspace):
    (workspace / "a.md").write_text("x\n")
    result = tools.text_diff("a.md", "missing.md")
    assert result.startswith("Diff unavailable:")
    assert "missing.md" in result


def test_text_diff_rejects_escape_from_workspace(workspace):
    (workspace / "a.md").write_text("x\n")
    result = tools.text_diff("a.md", "../../etc/passwd")
    assert result.startswith("Diff unavailable:")
    assert "outside workspace" in result


def test_text_diff_truncates_huge_output(workspace, monkeypatch):
    monkeypatch.setattr(tools, "MAX_DIFF_CHARS", 500)
    (workspace / "a.md").write_text("\n".join(f"line {i}" for i in range(1000)))
    (workspace / "b.md").write_text("\n".join(f"LINE {i}" for i in range(1000)))
    result = tools.text_diff("a.md", "b.md")
    assert "truncated" in result
    assert len(result) < 700
