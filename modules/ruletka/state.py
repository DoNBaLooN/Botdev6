"""State management for roulette runtime configuration."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from logger import logger

from . import settings


@dataclass(slots=True)
class _StateData:
    enabled: bool = field(default=settings.ENABLED)
    base_jackpot: Decimal = field(default=settings.BASE_JACKPOT)


class RouletteStateManager:
    """Persisted mutable state for the roulette module."""

    def __init__(self) -> None:
        self._path = Path(settings.STATE_FILE)
        self._lock = asyncio.Lock()
        self._data = _StateData()
        self._loaded = False
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            else:
                raw = {}
            enabled = raw.get("enabled")
            if isinstance(enabled, bool):
                self._data.enabled = enabled
            base_jackpot = raw.get("base_jackpot")
            if base_jackpot is not None:
                self._data.base_jackpot = Decimal(str(base_jackpot))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Ruletka] Не удалось загрузить состояние: %s", exc)
        finally:
            self._loaded = True

    async def _save(self) -> None:
        payload: dict[str, Any] = {
            "enabled": self._data.enabled,
            "base_jackpot": str(self._data.base_jackpot),
        }
        try:
            await asyncio.to_thread(self._write_file, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Ruletka] Не удалось сохранить состояние: %s", exc)

    def _write_file(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def enabled(self) -> bool:
        self._ensure_loaded()
        return self._data.enabled

    @property
    def base_jackpot(self) -> Decimal:
        self._ensure_loaded()
        return self._data.base_jackpot

    async def set_enabled(self, value: bool) -> None:
        async with self._lock:
            self._data.enabled = value
            await self._save()

    async def set_base_jackpot(self, value: Decimal) -> None:
        async with self._lock:
            self._data.base_jackpot = value
            await self._save()


state = RouletteStateManager()

