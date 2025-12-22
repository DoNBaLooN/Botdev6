"""Wallet integration helpers for the roulette module."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import logger

from . import settings
from .db import change_user_balance, get_user_balance
from .models import RouletteSpin


class WalletError(RuntimeError):
    """Base class for wallet related errors."""


class InsufficientFunds(WalletError):
    """Raised when the user has not enough balance."""


class WalletCommunicationError(WalletError):
    """Raised when wallet HTTP requests fail."""


@dataclass(slots=True)
class WalletReservation:
    success: bool
    balance_after: Decimal | None
    already_processed: bool = False
    existing_spin: RouletteSpin | None = None


_PROCESSED_COMMITS: set[UUID] = set()
_PROCESSED_ROLLBACKS: set[UUID] = set()


def _format_amount(value: Decimal | float | int | str) -> str:
    dec = Decimal(str(value)).quantize(Decimal("0.01"))
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


class WalletService:
    """Facade for DB or HTTP based wallet operations."""

    def __init__(self, session: AsyncSession, *, timeout: float = 15.0) -> None:
        self._session = session
        self._timeout = timeout

    async def reserve(self, *, tg_id: int, amount: Decimal, spin_id: UUID) -> WalletReservation:
        logger.info(
            "[Ruletka][wallet] reserve spin_id=%s tg_id=%s amount=%s",
            spin_id,
            tg_id,
            _format_amount(amount),
        )
        existing = await self._session.execute(
            select(RouletteSpin).where(RouletteSpin.spin_id == spin_id)
        )
        existing_spin = existing.scalar_one_or_none()
        if existing_spin is not None:
            logger.info(
                "[Ruletka] Повторный запрос спина %s, используем существующую запись",
                spin_id,
            )
            return WalletReservation(True, None, already_processed=True, existing_spin=existing_spin)

        mode = settings.WALLET_MODE.lower()
        if mode == "db":
            reservation = await self._reserve_db(tg_id=tg_id, amount=amount)
            logger.info(
                "[Ruletka][wallet] reserve_ok spin_id=%s tg_id=%s balance_after=%s",
                spin_id,
                tg_id,
                "—" if reservation.balance_after is None else _format_amount(reservation.balance_after),
            )
            return reservation
        if mode == "http":
            reservation = await self._reserve_http(tg_id=tg_id, amount=amount, spin_id=spin_id)
            logger.info(
                "[Ruletka][wallet] reserve_ok spin_id=%s tg_id=%s via=http",
                spin_id,
                tg_id,
            )
            return reservation
        raise WalletError(f"Unknown wallet mode: {settings.WALLET_MODE}")

    async def commit(
        self,
        *,
        tg_id: int,
        amount: Decimal,
        spin_id: UUID,
        jackpot_win: bool,
        bet: Decimal | None = None,
    ) -> Decimal | None:
        if spin_id in _PROCESSED_COMMITS:
            logger.info("[Ruletka][wallet] commit_skip spin_id=%s reason=idempotent", spin_id)
            return None
        logger.info(
            "[Ruletka][wallet] commit spin_id=%s tg_id=%s bet=%s win=%s jackpot=%s",
            spin_id,
            tg_id,
            _format_amount(bet) if bet is not None else "—",
            _format_amount(amount),
            jackpot_win,
        )
        mode = settings.WALLET_MODE.lower()
        if mode == "db":
            if amount == 0:
                _PROCESSED_COMMITS.add(spin_id)
                logger.info("[Ruletka][wallet] commit_ok spin_id=%s amount=0", spin_id)
                return None
            new_balance = await change_user_balance(self._session, tg_id, amount)
            _PROCESSED_COMMITS.add(spin_id)
            logger.info(
                "[Ruletka][wallet] commit_ok spin_id=%s tg_id=%s balance_after=%s",
                spin_id,
                tg_id,
                _format_amount(new_balance),
            )
            return new_balance
        if mode == "http":
            await self._call_http(
                endpoint=settings.WALLET_ENDPOINTS.get("commit"),
                payload={
                    "tg_id": tg_id,
                    "amount": str(amount),
                    "spin_id": str(spin_id),
                    "jackpot_win": jackpot_win,
                },
            )
            _PROCESSED_COMMITS.add(spin_id)
            logger.info("[Ruletka][wallet] commit_ok spin_id=%s via=http", spin_id)
            return None
        raise WalletError(f"Unknown wallet mode: {settings.WALLET_MODE}")

    async def rollback(self, *, tg_id: int, amount: Decimal, spin_id: UUID) -> None:
        if spin_id in _PROCESSED_ROLLBACKS:
            logger.info("[Ruletka][wallet] rollback_skip spin_id=%s reason=idempotent", spin_id)
            return
        logger.info(
            "[Ruletka][wallet] rollback spin_id=%s tg_id=%s amount=%s",
            spin_id,
            tg_id,
            _format_amount(amount),
        )
        mode = settings.WALLET_MODE.lower()
        if mode == "db":
            await change_user_balance(self._session, tg_id, amount)
            _PROCESSED_ROLLBACKS.add(spin_id)
            logger.info("[Ruletka][wallet] rollback_ok spin_id=%s via=db", spin_id)
            return
        if mode == "http":
            await self._call_http(
                endpoint=settings.WALLET_ENDPOINTS.get("rollback"),
                payload={
                    "tg_id": tg_id,
                    "amount": str(amount),
                    "spin_id": str(spin_id),
                },
            )
            _PROCESSED_ROLLBACKS.add(spin_id)
            logger.info("[Ruletka][wallet] rollback_ok spin_id=%s via=http", spin_id)
            return
        raise WalletError(f"Unknown wallet mode: {settings.WALLET_MODE}")

    async def _reserve_db(self, *, tg_id: int, amount: Decimal) -> WalletReservation:
        balance = await get_user_balance(self._session, tg_id, for_update=True)
        if balance < amount:
            raise InsufficientFunds(f"Balance {balance} < {amount}")
        new_balance = await change_user_balance(self._session, tg_id, -amount)
        return WalletReservation(True, new_balance)

    async def _reserve_http(self, *, tg_id: int, amount: Decimal, spin_id: UUID) -> WalletReservation:
        await self._call_http(
            endpoint=settings.WALLET_ENDPOINTS.get("reserve"),
            payload={
                "tg_id": tg_id,
                "amount": str(amount),
                "spin_id": str(spin_id),
            },
        )
        return WalletReservation(True, None)

    async def _call_http(self, *, endpoint: str | None, payload: dict[str, Any]) -> Any:
        if not endpoint:
            raise WalletCommunicationError("Wallet endpoint is not configured")

        retries = 3
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                import aiohttp

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout)) as session:
                    async with session.post(
                        endpoint,
                        json=payload,
                        headers={"X-Request-Id": payload.get("spin_id", "")},
                    ) as response:
                        logger.info(
                            "[Ruletka][wallet] http_call endpoint=%s spin_id=%s status=%s attempt=%s",
                            endpoint,
                            payload.get("spin_id"),
                            response.status,
                            attempt,
                        )
                        if response.status >= 500:
                            raise WalletCommunicationError(
                                f"Wallet error {response.status}: {await response.text()}"
                            )
                        if response.status >= 400:
                            text = await response.text()
                            raise WalletError(f"Wallet rejected request: {text}")
                        text = await response.text()
                        if not text:
                            return None
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "[Ruletka] Ошибка запроса кошелька (%s/%s): %s",
                    attempt,
                    retries,
                    exc,
                )
                if attempt == retries:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise WalletCommunicationError(str(last_error))
