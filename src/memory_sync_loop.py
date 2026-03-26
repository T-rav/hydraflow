"""Background worker loop — memory sync."""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from memory import MemorySyncWorker

logger = logging.getLogger("hydraflow.memory_sync_loop")


class MemorySyncLoop(BaseBackgroundLoop):
    """Reads local JSONL memory items and rebuilds the digest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        memory_sync: MemorySyncWorker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="memory_sync", config=config, deps=deps)
        self._memory_sync = memory_sync

    def _get_default_interval(self) -> int:
        return self._config.memory_sync_interval

    async def _do_work(self) -> dict[str, Any] | None:
        result = await self._memory_sync.sync()
        await self._memory_sync.publish_sync_event(result)
        return dict(result)
