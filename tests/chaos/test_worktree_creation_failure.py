"""Chaos test: git worktree creation failure."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import respx
from bernstein.core.worktree import WorktreeError
from httpx import Response

if TYPE_CHECKING:
    from bernstein.core.orchestrator import Orchestrator
    from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_worktree_creation_failure(
    test_client: TestClient, orchestrator_factory, integration_sdd: Path, monkeypatch
):
    # 1. Create a task
    test_client.post("/tasks", json={"title": "Worktree Task", "description": "I need a worktree", "role": "backend"})

    # 2. Run orchestrator
    orch: Orchestrator = orchestrator_factory(max_agents=1, use_worktrees=True)
    orch._approval_gate = None
    orch._incident_manager.auto_pause = False

    # CHAOS: Mock worktree creation failure
    def failing_create(*args, **kwargs):
        raise WorktreeError("Mock worktree creation failed")

    monkeypatch.setattr(orch._spawner._worktree_mgr, "create", failing_create)

    # Track where the adapter was spawned
    spawned_workdirs = []
    from bernstein.adapters.registry import get_adapter

    adapter = get_adapter("integration-mock")
    original_spawn = adapter.spawn

    def tracked_spawn(**kwargs):
        spawned_workdirs.append(kwargs.get("workdir"))
        return original_spawn(**kwargs)

    monkeypatch.setattr(adapter, "spawn", tracked_spawn)

    with respx.mock(base_url="http://127.0.0.1:8052") as respx_mock:

        def handler(request):
            method = request.method
            path = request.url.path
            api_path = path if path.startswith("/") else "/" + path

            content = request.read()
            headers = dict(request.headers)
            resp = test_client.request(method, api_path, content=content, headers=headers)
            return Response(resp.status_code, content=resp.content, headers=dict(resp.headers))

        respx_mock.route().mock(side_effect=handler)

        # Run tick
        orch.tick()

        # 3. Verify
        # No fallback to the operator checkout: the spawn is refused outright.
        # Running at the root lets the agent commit over the checked-out branch
        # and lets reap-time salvage rename that branch to salvage/<session>.
        assert spawned_workdirs == []
        assert integration_sdd.parent not in spawned_workdirs
