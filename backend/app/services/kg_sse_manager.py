"""SSE manager for Knowledge Graph extraction jobs.

Mirrors the structure of SSEManager in audit_service but scoped to KG jobs.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.schemas.kg import KGEvent, KGSnapshot


@dataclass
class KGJobState:
    stage: str = "queued"
    status: str = "queued"
    seq: int = 0
    events: List[KGEvent] = field(default_factory=list)


class KGSSEManager:
    def __init__(self) -> None:
        self._queues: Dict[str, List[asyncio.Queue[KGEvent]]] = defaultdict(list)
        self._state: Dict[str, KGJobState] = defaultdict(KGJobState)
        self._known_ids: set[str] = set()

    def create_job(self, graph_id: str) -> None:
        _ = self._state[graph_id]
        self._known_ids.add(graph_id)

    def exists(self, graph_id: str) -> bool:
        return graph_id in self._known_ids

    async def subscribe(self, graph_id: str) -> asyncio.Queue[KGEvent]:
        queue: asyncio.Queue[KGEvent] = asyncio.Queue()
        self._queues[graph_id].append(queue)
        return queue

    async def unsubscribe(self, graph_id: str, queue: asyncio.Queue[KGEvent]) -> None:
        if graph_id in self._queues and queue in self._queues[graph_id]:
            self._queues[graph_id].remove(queue)

    async def publish(
        self,
        graph_id: str,
        event: str,
        stage: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> KGEvent:
        state = self._state[graph_id]
        state.seq += 1
        entry = KGEvent(
            graph_id=graph_id,
            event=event,  # type: ignore[arg-type]
            stage=stage,  # type: ignore[arg-type]
            seq=state.seq,
            ts=datetime.now(timezone.utc),
            payload=payload or {},
        )

        state.stage = stage
        if event == "kg_completed":
            state.status = "completed"
        elif event == "kg_failed":
            state.status = "failed"
        elif state.status not in {"completed", "failed"}:
            state.status = "running"

        state.events.append(entry)

        for queue in self._queues.get(graph_id, []):
            await queue.put(entry)

        return entry

    def snapshot(self, graph_id: str) -> KGSnapshot:
        state = self._state[graph_id]
        return KGSnapshot(
            graph_id=graph_id,
            stage=state.stage,  # type: ignore[arg-type]
            status=state.status,
            events=list(state.events),
        )


kg_sse_manager = KGSSEManager()
