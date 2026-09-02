"""A session that exited 0 must never be failed by a log-pattern match.

Regression for 2026-09-02: the scanner greps the agent transcript for risky
substrings, matched "401" in a message the agent had merely printed, and failed
a task whose work had already merged - then retried it twice and DLQ'd it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bernstein.core.agents.agent_lifecycle import _handle_failure_detection


class _Tracker:
    """Stands in for the rate-limit tracker; records whether it was consulted."""

    def __init__(self) -> None:
        self.scanned = False

    def detect_failure_type(self, _log_path: Path) -> str:
        self.scanned = True
        return "auth_error"

    def throttle_provider(self, *_a: Any, **_k: Any) -> None:
        raise AssertionError("a clean exit must not throttle the provider")


def _orch(tmp_path: Path, tracker: _Tracker) -> SimpleNamespace:
    return SimpleNamespace(_rate_limit_tracker=tracker, _workdir=tmp_path, _router=None)


def _session(exit_code: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="resolver-709a30dd",
        provider="codex",
        exit_code=exit_code,
        model_config=None,
    )


def test_clean_exit_is_not_failed_and_the_log_is_not_scanned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tracker = _Tracker()
    with caplog.at_level("INFO"):
        handled = _handle_failure_detection(
            _orch(tmp_path, tracker),
            SimpleNamespace(id="t1"),
            "t1",
            _session(0),
            "main",
            0.0,
            {},
        )
    assert handled is False, "a clean exit must fall through to the orphan path"
    assert tracker.scanned is False, "a clean exit must not even scan the log"
    assert any("exited 0" in r.message for r in caplog.records)


@pytest.mark.parametrize("exit_code", [1, 137, None])
def test_a_real_death_still_reaches_the_scanner(tmp_path: Path, exit_code: int | None) -> None:
    """The guard is scoped to exit_code == 0; every other death still scans."""
    tracker = _Tracker()
    with pytest.raises(AssertionError, match="must not throttle"):
        _handle_failure_detection(
            _orch(tmp_path, tracker),
            SimpleNamespace(id="t1"),
            "t1",
            _session(exit_code),
            "main",
            0.0,
            {},
        )
    assert tracker.scanned is True
