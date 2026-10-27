"""In-memory registry of live simulations (one SimulationService each)."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

from services.simulation_service import SimulationService

MAX_LIVE_SIMULATIONS = 50


@dataclass
class Entry:
    run_id: str
    service: SimulationService
    created_at: str
    lock: threading.Lock = field(default_factory=threading.Lock)


class SimulationStore:
    def __init__(self, max_live: int = MAX_LIVE_SIMULATIONS):
        self.max_live = max_live
        self._entries: Dict[str, Entry] = {}
        self._guard = threading.Lock()

    def add(self, service: SimulationService, run_id: str | None = None,
            created_at: str | None = None) -> Entry:
        """Register a live run. Pass run_id/created_at to bring a saved run back (resume)."""
        with self._guard:
            if run_id is not None:
                self._entries.pop(run_id, None)
            while len(self._entries) >= self.max_live:  # evict the oldest run
                self._entries.pop(next(iter(self._entries)))
            entry = Entry(
                run_id=run_id or uuid.uuid4().hex[:8],
                service=service,
                created_at=created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._entries[entry.run_id] = entry
            return entry

    def get(self, run_id: str) -> Entry | None:
        with self._guard:
            return self._entries.get(run_id)

    def delete(self, run_id: str) -> bool:
        with self._guard:
            return self._entries.pop(run_id, None) is not None

    def all(self) -> List[Entry]:
        with self._guard:
            return list(self._entries.values())
