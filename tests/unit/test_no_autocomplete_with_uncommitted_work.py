"""An agent that wrote its deliverable and never committed is not "no changes".

Finding K (2026-09-03): `orphan_auto_complete ... empty diff (exit code 0)`
fired on a worktree whose `git add -A` salvage then produced a 2-file patch.
Both the "empty diff" and "no commits" reads come from committed state only.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from bernstein.core.agents.agent_lifecycle import _uncommitted_work_paths


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "wt"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@e.com"], repo)
    _run(["git", "config", "user.name", "T"], repo)
    _run(["git", "config", "commit.gpgsign", "false"], repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "seed"], repo)
    return repo


def test_a_clean_worktree_reports_nothing(tmp_path: Path) -> None:
    assert _uncommitted_work_paths(_repo(tmp_path)) == []


def test_untracked_deliverable_is_reported(tmp_path: Path) -> None:
    """The measured shape: files written, never added, never committed."""
    repo = _repo(tmp_path)
    (repo / "adapter.go").write_text("package p\n", encoding="utf-8")
    (repo / "registry.go").write_text("package p\n", encoding="utf-8")
    assert len(_uncommitted_work_paths(repo)) == 2


def test_tracked_edits_are_reported(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("edited\n", encoding="utf-8")
    assert _uncommitted_work_paths(repo) != []


def test_gitignored_files_are_not_work(tmp_path: Path) -> None:
    """git status --porcelain already honours .gitignore; build junk is not a deliverable."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("junk/\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "ignore"], repo)
    (repo / "junk").mkdir()
    (repo / "junk" / "out.o").write_text("x", encoding="utf-8")
    assert _uncommitted_work_paths(repo) == []


def test_a_missing_or_broken_path_never_claims_dirty(tmp_path: Path) -> None:
    """The guard only suppresses auto-completion; a broken git call must not fail a task."""
    assert _uncommitted_work_paths(None) == []
    assert _uncommitted_work_paths(tmp_path / "does-not-exist") == []
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert _uncommitted_work_paths(plain) == []
