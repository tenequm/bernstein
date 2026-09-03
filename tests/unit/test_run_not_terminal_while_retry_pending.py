"""A run is not over while a retry is still to be queued, and a stall must fire.

Finding N (2026-09-03), which is two bugs:

* The CLI called the run terminal 2 s into the 24 s window between the
  stale-claim releaser failing a task (01:30:04) and ``maybe_retry_task``
  creating its retry (01:30:28), printed ``Done: 0, Failed: 1`` and exited
  while the run went on for another 40 minutes.
* The orchestrator's stall confirmation aborted on the mere PRESENCE of a done
  or failed task. Those buckets only grow, so after the first task finished the
  backstop could never fire again; the orchestrator idled 36 min past its grace.
"""

from __future__ import annotations

from bernstein.cli.run_bootstrap import (
    _QUIESCENCE_RETRY_CONFIRM_WINDOW_S,
    _has_unsuccessful_terminal_task,
    _is_quiescent,
)


class TestPendingRetryDetection:
    def test_a_failed_task_means_a_retry_may_be_pending(self) -> None:
        assert _has_unsuccessful_terminal_task({"done": 0, "failed": 1}) is True

    def test_an_orphaned_task_counts_too(self) -> None:
        assert _has_unsuccessful_terminal_task({"orphaned": 1}) is True

    def test_an_all_successful_run_exits_immediately(self) -> None:
        assert _has_unsuccessful_terminal_task({"done": 2, "closed": 1, "failed": 0}) is False

    def test_a_missing_histogram_does_not_hold_a_finished_run_open(self) -> None:
        """An undercount must not be read as 'a retry may be pending'."""
        assert _has_unsuccessful_terminal_task(None) is False
        assert _has_unsuccessful_terminal_task({"detail": "Not Found"}) is False

    def test_the_window_outlasts_the_measured_gap(self) -> None:
        """01:30:04 fail -> 01:30:28 retry created: 24 s."""
        assert _QUIESCENCE_RETRY_CONFIRM_WINDOW_S > 24.0


class TestQuiescencePredicateUnchanged:
    """_is_quiescent still answers only 'right now', as documented."""

    def test_board_with_nothing_outstanding_is_quiescent(self) -> None:
        assert _is_quiescent(
            total=4, open_count=0, claimed_count=0, agent_count=0, n_incomplete=0, counts_are_complete=True
        )

    def test_an_in_progress_task_vetoes_it(self) -> None:
        assert not _is_quiescent(
            total=4, open_count=0, claimed_count=0, agent_count=0, n_incomplete=1, counts_are_complete=True
        )


# ---------------------------------------------------------------------------
# The orchestrator's stall confirmation: terminal buckets must not abort it
# ---------------------------------------------------------------------------


class TestStallConfirmationIgnoresTerminalBuckets:
    """`done`/`failed` only grow, so they can never mean "work is arriving"."""

    @staticmethod
    def _guard(settled: dict[str, list[object]], agents: int) -> bool:
        """The confirmation guard as it now stands: only runnable work aborts."""
        return bool(len(settled["open"]) or agents)

    def test_a_finished_and_a_failed_task_do_not_abort_the_stop(self) -> None:
        """The measured shape: 1 done + 1 failed, nothing runnable, idling."""
        settled = {"open": [], "claimed": [], "done": [object()], "failed": [object()]}
        assert self._guard(settled, agents=0) is False, "the stall must be allowed to confirm"

    def test_an_open_task_still_aborts_the_stop(self) -> None:
        settled = {"open": [object()], "claimed": [], "done": [], "failed": []}
        assert self._guard(settled, agents=0) is True

    def test_a_live_agent_still_aborts_the_stop(self) -> None:
        settled = {"open": [], "claimed": [], "done": [object()], "failed": []}
        assert self._guard(settled, agents=1) is True


def test_the_orchestrator_guard_matches_this_expression() -> None:
    """Pin the source so the guard cannot silently regain a terminal-bucket test."""
    import inspect

    from bernstein.core.orchestration import orchestrator

    src = inspect.getsource(orchestrator.Orchestrator._check_zero_terminal_stall)
    assert 'if len(settled["open"]) or settled_agents:' in src
    assert 'if settled["done"] or settled["failed"]' not in src
