from __future__ import annotations

import asyncio
import functools
import inspect
import re
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Iterable, Tuple

import requests
from requests import Response
from requests.exceptions import RequestException

from logger import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import db, settings, texts


@dataclass(slots=True)
class SendResult:
    success: bool
    status_code: int | None
    message: str

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.success


_CID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{6,64}$")
_PREFIX_STRIP_CHARS = "_=:-"


def _normalize_cid(cid: str | None) -> str | None:
    if not isinstance(cid, str):
        return None
    trimmed = cid.strip()
    return trimmed or None


def _mask_cid(cid: str | None) -> str:
    if not cid:
        return "<empty>"
    visible = cid[-4:]
    masked_prefix = "*" * max(0, len(cid) - len(visible))
    return f"{masked_prefix}{visible}" if masked_prefix else visible


def mask_cid(cid: str | None) -> str:
    return _mask_cid(cid)


_PATCH_FLAG_ATTR = "__yandex_offline_conv_patched__"
_INSTRUMENTATION_INSTALLED = False


def _replace_function_references(original: Callable[..., Any], replacement: Callable[..., Any]) -> int:
    replaced = 0
    for module in list(sys.modules.values()):
        module_dict = getattr(module, "__dict__", None)
        if not module_dict:
            continue
        for attr, value in list(module_dict.items()):
            if value is original:
                try:
                    setattr(module, attr, replacement)
                    replaced += 1
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception(
                        "%s Failed to replace reference %s.%s during instrumentation",
                        texts.LOG_PREFIX,
                        getattr(module, "__name__", module),
                        attr,
                    )
    return replaced


def _summarize_argument(name: str, value: Any) -> Any:
    if name == "session" and value is not None:
        return f"<{type(value).__name__}>"
    if name in {"message", "callback", "callback_query", "state"} and value is not None:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        preview = {k: value[k] for k in list(value.keys())[:5]}
        if len(value) > len(preview):
            preview["..."] = f"+{len(value) - len(preview)} keys"
        return preview
    return value


def _sanitize_arguments(arguments: inspect.BoundArguments) -> dict[str, Any]:
    return {name: _summarize_argument(name, value) for name, value in arguments.arguments.items()}


def _extract_plan_id(plan: Any) -> int | None:
    candidate = None
    if isinstance(plan, (int, str)):
        candidate = plan
    elif isinstance(plan, dict):
        candidate = plan.get("id") or plan.get("tariff_id")
    else:
        for attr in ("id", "tariff_id", "plan_id"):
            if hasattr(plan, attr):
                candidate = getattr(plan, attr)
                if candidate is not None:
                    break
    if candidate is None:
        return None
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _collect_plan_flags(plan: Any) -> dict[str, Any]:
    if plan is None:
        return {}

    getter = None
    if isinstance(plan, dict):
        getter = plan.get
    else:
        getter = lambda key: getattr(plan, key, None)

    flags: dict[str, Any] = {}

    is_trial_value = getter("is_trial")
    if is_trial_value is None:
        is_trial_value = getter("trial")
    if is_trial_value is not None:
        flags["is_trial"] = bool(is_trial_value)

    trial_days = getter("trial_days")
    if trial_days:
        flags["trial_days"] = trial_days

    duration_days = getter("duration_days")
    if duration_days:
        flags["duration_days"] = duration_days

    price = getter("price_rub")
    if price is not None:
        try:
            price_decimal = Decimal(str(price))
        except Exception:  # pragma: no cover - diagnostic only
            flags["price_rub"] = price
        else:
            flags["price_rub"] = str(price_decimal)
            if price_decimal == 0:
                flags["zero_price"] = True

    name = getter("name")
    if isinstance(name, str) and name:
        flags["name_contains_trial"] = "trial" in name.lower() or "триал" in name.lower()

    return flags


def _coerce_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", 0):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_event_value(amount: Any) -> str | None:
    if amount is None or isinstance(amount, bool):
        return None

    if isinstance(amount, str):
        trimmed = amount.strip()
        if not trimmed:
            return None
        trimmed = trimmed.replace(" ", "").replace(",", ".")
        if trimmed.isdigit():
            if int(trimmed) <= 0:
                return None
            return trimmed
        try:
            decimal_amount = Decimal(trimmed)
        except (InvalidOperation, ValueError):
            logger.debug(
                "%s Unable to parse purchase amount for ev: %r",
                texts.LOG_PREFIX,
                amount,
            )
            return None
    else:
        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            logger.debug(
                "%s Unable to parse purchase amount for ev: %r",
                texts.LOG_PREFIX,
                amount,
            )
            return None

    decimal_amount = decimal_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if decimal_amount <= 0:
        return None
    return str(int(decimal_amount))


async def _evaluate_trial_condition(bound: inspect.BoundArguments) -> tuple[bool, dict[str, Any]]:
    plan_argument = bound.arguments.get("plan")
    plan_flags = _collect_plan_flags(plan_argument)
    plan_id = _extract_plan_id(plan_argument)

    hints: list[str] = []
    raw_is_trial = bound.arguments.get("is_trial")
    if _coerce_truthy(raw_is_trial):
        hints.append("arg:is_trial")
    if plan_flags.get("is_trial"):
        hints.append("plan:is_trial")
    trial_days = plan_flags.get("trial_days")
    if trial_days:
        hints.append(f"plan:trial_days={trial_days}")
    if plan_flags.get("zero_price"):
        hints.append("plan:zero_price")
    if plan_flags.get("name_contains_trial"):
        hints.append("plan:name_contains_trial")

    debug_payload = {
        "hints": hints,
        "plan_id": plan_id,
        "plan_flags": plan_flags,
        "raw_is_trial": raw_is_trial,
    }
    return bool(hints), debug_payload


async def _dispatch_send(func: Callable[..., SendResult], *args, **kwargs) -> SendResult:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return func(*args, **kwargs)

    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


async def _has_existing_trial(session: AsyncSession | None, tg_id: Any) -> bool:
    if session is None or not isinstance(session, AsyncSession):
        return False

    try:
        numeric_tg_id = int(tg_id)
    except (TypeError, ValueError):
        logger.warning("%s Unable to parse tg_id for trial check: %r", texts.LOG_PREFIX, tg_id)
        return True

    try:
        from database.models import User

        result = await session.execute(
            select(User.trial).where(User.tg_id == numeric_tg_id).limit(1)
        )
        trial_value = result.scalar_one_or_none()
    except Exception:
        logger.exception(
            "%s Failed to check existing trial for tg_id=%s", texts.LOG_PREFIX, numeric_tg_id
        )
        return True

    if trial_value is None:
        return False

    try:
        numeric_trial = int(trial_value)
    except (TypeError, ValueError):
        return True

    return numeric_trial != 0


async def _has_successful_purchase(session: AsyncSession | None, tg_id: Any) -> bool:
    if session is None or not isinstance(session, AsyncSession):
        return False

    try:
        numeric_tg_id = int(tg_id)
    except (TypeError, ValueError):
        logger.warning(
            "%s Unable to parse tg_id for purchase check: %r", texts.LOG_PREFIX, tg_id
        )
        return True

    try:
        from database.models import Payment

        result = await session.execute(
            select(Payment.id)
            .where(Payment.tg_id == numeric_tg_id, Payment.status == "success")
            .limit(1)
        )
    except Exception:
        logger.exception(
            "%s Failed to check existing purchase for tg_id=%s", texts.LOG_PREFIX, numeric_tg_id
        )
        return True

    return result.first() is not None


async def _handle_trial_event(
    session: AsyncSession | None,
    tg_id: Any,
    *,
    plan: Any = None,
    context: str = "",
) -> None:
    if session is None or not isinstance(session, AsyncSession):
        logger.debug(
            "%s Skipping trial tracking (no session) for tg_id=%s context=%s",
            texts.LOG_PREFIX,
            tg_id,
            context,
        )
        return

    try:
        numeric_tg_id = int(tg_id)
    except (TypeError, ValueError):
        logger.warning(
            "%s Skipping trial tracking due to invalid tg_id=%r context=%s",
            texts.LOG_PREFIX,
            tg_id,
            context,
        )
        return

    try:
        cid, counter_tid = await db.get_cid(session, numeric_tg_id)
    except Exception:
        logger.exception(
            "%s Failed to look up cid for trial event (tg_id=%s context=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            context,
        )
        return

    if not cid:
        logger.debug(
            "%s No cid stored for trial event (tg_id=%s context=%s plan=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            context,
            plan,
        )
        return

    try:
        result = await _dispatch_send(send_trial_add, cid, counter_tid=counter_tid)
    except Exception:
        logger.exception(
            "%s Unexpected error while sending trial event (tg_id=%s context=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            context,
        )
        return

    masked_cid = mask_cid(cid)
    if result.success:
        logger.info(
            "%s Trial event sent (tg_id=%s cid=%s context=%s plan=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            masked_cid,
            context or "unknown",
            plan,
        )
    else:
        logger.warning(
            "%s Trial event failed (tg_id=%s cid=%s context=%s plan=%s status=%s message=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            masked_cid,
            context or "unknown",
            plan,
            result.status_code,
            result.message,
        )


async def _handle_purchase_event(
    session: AsyncSession | None,
    tg_id: Any,
    *,
    amount: Any = None,
    payment_system: Any = None,
    context: str = "",
) -> None:
    if session is None or not isinstance(session, AsyncSession):
        logger.debug(
            "%s Skipping purchase tracking (no session) for tg_id=%s context=%s",
            texts.LOG_PREFIX,
            tg_id,
            context,
        )
        return

    try:
        numeric_tg_id = int(tg_id)
    except (TypeError, ValueError):
        logger.warning(
            "%s Skipping purchase tracking due to invalid tg_id=%r context=%s",
            texts.LOG_PREFIX,
            tg_id,
            context,
        )
        return

    try:
        cid, counter_tid = await db.get_cid(session, numeric_tg_id)
    except Exception:
        logger.exception(
            "%s Failed to look up cid for purchase event (tg_id=%s context=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            context,
        )
        return

    if not cid:
        logger.debug(
            "%s No cid stored for purchase event (tg_id=%s context=%s amount=%s system=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            context,
            amount,
            payment_system,
        )
        return

    try:
        result = await _dispatch_send(
            send_purchase,
            cid,
            counter_tid=counter_tid,
            amount=amount,
        )
    except Exception:
        logger.exception(
            "%s Unexpected error while sending purchase event (tg_id=%s context=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            context,
        )
        return

    masked_cid = mask_cid(cid)
    if result.success:
        logger.info(
            "%s Purchase event sent (tg_id=%s cid=%s context=%s amount=%s system=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            masked_cid,
            context or "unknown",
            amount,
            payment_system,
        )
    else:
        logger.warning(
            "%s Purchase event failed (tg_id=%s cid=%s context=%s amount=%s system=%s status=%s message=%s)",
            texts.LOG_PREFIX,
            numeric_tg_id,
            masked_cid,
            context or "unknown",
            amount,
            payment_system,
            result.status_code,
            result.message,
        )


def _instrument_create_key_on_cluster() -> None:
    try:
        from handlers.keys.operations import creation as key_creation
    except Exception as exc:
        logger.warning(
            "%s Unable to import key creation module for instrumentation: %s",
            texts.LOG_PREFIX,
            exc,
        )
        return

    original = getattr(key_creation, "create_key_on_cluster", None)
    if original is None or getattr(original, _PATCH_FLAG_ATTR, False):
        return

    signature = inspect.signature(original)

    @functools.wraps(original)
    async def wrapped(*args, **kwargs):
        try:
            bound = signature.bind_partial(*args, **kwargs)
        except TypeError:
            logger.exception(
                "%s Failed to bind arguments for create_key_on_cluster instrumentation",
                texts.LOG_PREFIX,
            )
            return await original(*args, **kwargs)

        logger.debug(
            "%s create_key_on_cluster instrumentation entry tg_id=%s named=%s",
            texts.LOG_PREFIX,
            bound.arguments.get("tg_id"),
            _sanitize_arguments(bound),
        )

        session = bound.arguments.get("session")
        tg_id = bound.arguments.get("tg_id")
        had_trial_before = False
        try:
            had_trial_before = await _has_existing_trial(session, tg_id)
        except Exception:
            logger.exception(
                "%s Failed to check prior trial status (tg_id=%s)",
                texts.LOG_PREFIX,
                tg_id,
            )

        result = await original(*args, **kwargs)

        try:
            should_track, debug_payload = await _evaluate_trial_condition(bound)
        except Exception:
            logger.exception(
                "%s Failed to evaluate trial condition (tg_id=%s)",
                texts.LOG_PREFIX,
                bound.arguments.get("tg_id"),
            )
            return result

        debug_context = dict(debug_payload)
        if "plan_snapshot" in debug_context and debug_context["plan_snapshot"] is not None:
            debug_context["plan_snapshot"] = _summarize_argument("plan", debug_context["plan_snapshot"])

        logger.debug(
            "%s create_key_on_cluster instrumentation decision tg_id=%s track=%s details=%s",
            texts.LOG_PREFIX,
            bound.arguments.get("tg_id"),
            should_track,
            debug_context,
        )

        if should_track:
            plan = debug_payload.get("plan_snapshot") or bound.arguments.get("plan")
            if had_trial_before:
                logger.debug(
                    "%s Skipping trial event for tg_id=%s (existing trial detected)",
                    texts.LOG_PREFIX,
                    tg_id,
                )
            else:
                try:
                    await _handle_trial_event(
                        session,
                        tg_id,
                        plan=plan,
                        context="create_key_on_cluster",
                    )
                except Exception:
                    logger.exception(
                        "%s Trial tracking handler raised (tg_id=%s context=create_key_on_cluster)",
                        texts.LOG_PREFIX,
                        bound.arguments.get("tg_id"),
                    )

        return result

    setattr(original, _PATCH_FLAG_ATTR, True)
    setattr(wrapped, _PATCH_FLAG_ATTR, True)
    key_creation.create_key_on_cluster = wrapped
    replaced = _replace_function_references(original, wrapped)
    if replaced:
        logger.debug(
            "%s create_key_on_cluster references updated in %s locations",
            texts.LOG_PREFIX,
            replaced,
        )
    logger.info("%s Instrumented create_key_on_cluster for trial tracking", texts.LOG_PREFIX)


def _instrument_add_payment() -> None:
    try:
        from database import payments as payments_module
        import database as database_pkg
    except Exception as exc:
        logger.warning(
            "%s Unable to import payments module for instrumentation: %s",
            texts.LOG_PREFIX,
            exc,
        )
        return

    original = getattr(payments_module, "add_payment", None)
    if original is None or getattr(original, _PATCH_FLAG_ATTR, False):
        return

    signature = inspect.signature(original)

    @functools.wraps(original)
    async def wrapped(*args, **kwargs):
        try:
            bound = signature.bind_partial(*args, **kwargs)
        except TypeError:
            logger.exception(
                "%s Failed to bind arguments for add_payment instrumentation",
                texts.LOG_PREFIX,
            )
            return await original(*args, **kwargs)

        logger.debug(
            "%s add_payment instrumentation entry tg_id=%s named=%s",
            texts.LOG_PREFIX,
            bound.arguments.get("tg_id"),
            _sanitize_arguments(bound),
        )

        session = bound.arguments.get("session")
        tg_id = bound.arguments.get("tg_id")
        had_purchase_before = False
        try:
            had_purchase_before = await _has_successful_purchase(session, tg_id)
        except Exception:
            logger.exception(
                "%s Failed to check prior purchase status (tg_id=%s)",
                texts.LOG_PREFIX,
                tg_id,
            )

        result = await original(*args, **kwargs)

        amount = bound.arguments.get("amount")
        payment_system = bound.arguments.get("payment_system")

        if had_purchase_before:
            logger.debug(
                "%s Skipping purchase event for tg_id=%s (existing purchase detected)",
                texts.LOG_PREFIX,
                tg_id,
            )
        else:
            try:
                await _handle_purchase_event(
                    session,
                    tg_id,
                    amount=amount,
                    payment_system=payment_system,
                    context="add_payment",
                )
            except Exception:
                logger.exception(
                    "%s Purchase tracking handler raised (tg_id=%s context=add_payment)",
                    texts.LOG_PREFIX,
                    tg_id,
                )

        return result

    setattr(original, _PATCH_FLAG_ATTR, True)
    setattr(wrapped, _PATCH_FLAG_ATTR, True)
    payments_module.add_payment = wrapped
    if getattr(database_pkg, "add_payment", None) is original:
        database_pkg.add_payment = wrapped
    replaced = _replace_function_references(original, wrapped)
    if replaced:
        logger.debug(
            "%s add_payment references updated in %s locations",
            texts.LOG_PREFIX,
            replaced,
        )
    logger.info("%s Instrumented add_payment for purchase tracking", texts.LOG_PREFIX)


def _instrument_update_trial() -> None:
    try:
        from database import users as users_module
        import database as database_pkg
    except Exception as exc:
        logger.warning(
            "%s Unable to import users module for instrumentation: %s",
            texts.LOG_PREFIX,
            exc,
        )
        return

    original = getattr(users_module, "update_trial", None)
    if original is None or getattr(original, _PATCH_FLAG_ATTR, False):
        return

    signature = inspect.signature(original)

    @functools.wraps(original)
    async def wrapped(*args, **kwargs):
        try:
            bound = signature.bind_partial(*args, **kwargs)
        except TypeError:
            logger.exception(
                "%s Failed to bind arguments for update_trial instrumentation",
                texts.LOG_PREFIX,
            )
            return await original(*args, **kwargs)

        logger.debug(
            "%s update_trial instrumentation entry tg_id=%s named=%s",
            texts.LOG_PREFIX,
            bound.arguments.get("tg_id"),
            _sanitize_arguments(bound),
        )

        session = bound.arguments.get("session")
        tg_id = bound.arguments.get("tg_id")
        had_trial_before = False
        try:
            had_trial_before = await _has_existing_trial(session, tg_id)
        except Exception:
            logger.exception(
                "%s Failed to check prior trial status (tg_id=%s)",
                texts.LOG_PREFIX,
                tg_id,
            )

        result = await original(*args, **kwargs)

        status = bound.arguments.get("status")

        if status == 1 and had_trial_before:
            logger.debug(
                "%s Skipping trial event for tg_id=%s (existing trial detected)",
                texts.LOG_PREFIX,
                tg_id,
            )
        elif status == 1:
            try:
                await _handle_trial_event(
                    session,
                    tg_id,
                    context="update_trial",
                )
            except Exception:
                logger.exception(
                    "%s Trial tracking handler raised (tg_id=%s context=update_trial)",
                    texts.LOG_PREFIX,
                    tg_id,
                )

        return result

    setattr(original, _PATCH_FLAG_ATTR, True)
    setattr(wrapped, _PATCH_FLAG_ATTR, True)
    users_module.update_trial = wrapped
    if getattr(database_pkg, "update_trial", None) is original:
        database_pkg.update_trial = wrapped
    replaced = _replace_function_references(original, wrapped)
    if replaced:
        logger.debug(
            "%s update_trial references updated in %s locations",
            texts.LOG_PREFIX,
            replaced,
        )
    logger.info("%s Instrumented update_trial for trial tracking", texts.LOG_PREFIX)


def _instrument_handle_utm_link() -> None:
    from handlers import start as start_handlers

    original = getattr(start_handlers, "handle_utm_link", None)
    if original is None or getattr(original, _PATCH_FLAG_ATTR, False):
        return

    signature = inspect.signature(original)

    @functools.wraps(original)
    async def wrapped(*args, **kwargs):
        try:
            bound = signature.bind_partial(*args, **kwargs)
        except TypeError:
            logger.exception(
                "%s Failed to bind arguments for handle_utm_link instrumentation",
                texts.LOG_PREFIX,
            )
            return await original(*args, **kwargs)

        utm_code = bound.arguments.get("utm_code")
        cleaned_utm, cid = _trim_utm_code(utm_code)

        if cleaned_utm and cleaned_utm != utm_code:
            logger.debug(
                "%s Trimmed cid from utm_code=%r -> %r (cid=%s)",
                texts.LOG_PREFIX,
                utm_code,
                cleaned_utm,
                _mask_cid(cid),
            )
            bound.arguments["utm_code"] = cleaned_utm
            return await original(**bound.arguments)

        return await original(*args, **kwargs)

    setattr(original, _PATCH_FLAG_ATTR, True)
    setattr(wrapped, _PATCH_FLAG_ATTR, True)
    start_handlers.handle_utm_link = wrapped
    replaced = _replace_function_references(original, wrapped)
    if replaced:
        logger.debug(
            "%s handle_utm_link references updated in %s locations",
            texts.LOG_PREFIX,
            replaced,
        )
    logger.info("%s Instrumented handle_utm_link for UTM trimming", texts.LOG_PREFIX)


def install_instrumentation() -> None:
    global _INSTRUMENTATION_INSTALLED
    if _INSTRUMENTATION_INSTALLED:
        return

    _instrument_create_key_on_cluster()
    _instrument_add_payment()
    _instrument_update_trial()
    _instrument_handle_utm_link()
    _INSTRUMENTATION_INSTALLED = True

def _iter_counter_configs() -> list[dict[str, str]]:
    counters = getattr(settings, "YA_COUNTERS", None) or []
    configs: list[dict[str, str]] = []
    for counter in counters:
        if not isinstance(counter, dict):
            continue
        tid = counter.get("tid")
        ms = counter.get("ms")
        prefix = counter.get("start_prefix") or ""
        if not tid or not ms:
            continue
        configs.append({"tid": str(tid), "ms": str(ms), "start_prefix": str(prefix)})
    return configs


def _iter_prefix_candidates() -> Iterable[tuple[str, dict[str, str] | None]]:
    seen: set[str] = set()

    for counter in _iter_counter_configs():
        prefix = counter.get("start_prefix", "") or ""
        if prefix in seen:
            continue
        seen.add(prefix)
        yield prefix, counter

    fallback_prefix = getattr(settings, "START_PREFIX", "") or ""
    if fallback_prefix not in seen:
        seen.add(fallback_prefix)
        yield fallback_prefix, None

    if "" not in seen:
        yield "", None


def extract_cid(part: str) -> Tuple[str | None, str | None, str | None]:
    if not part or not isinstance(part, str):
        return None, None, None

    trimmed_part = part.strip()
    if not trimmed_part:
        return None, None, None

    trimmed_lower = trimmed_part.lower()

    for prefix, counter in _iter_prefix_candidates():
        prefix_lower = prefix.lower()
        base_prefix = prefix_lower.rstrip(_PREFIX_STRIP_CHARS) if prefix_lower else ""

        remainder: str | None = None
        remainder_start = 0
        if prefix and trimmed_lower.startswith(prefix_lower):
            suffix = trimmed_part[len(prefix) :]
            stripped_suffix = suffix.lstrip(_PREFIX_STRIP_CHARS)
            remainder_start = len(trimmed_part) - len(stripped_suffix)
            remainder = stripped_suffix
        elif base_prefix and trimmed_lower == base_prefix:
            cleaned_part = trimmed_part.rstrip(_PREFIX_STRIP_CHARS) or trimmed_part
            logger.debug(
                "%s Prefix trim match (base): part=%r prefix=%r base_prefix=%r cleaned_part=%r",
                texts.LOG_PREFIX,
                trimmed_part,
                prefix,
                base_prefix,
                cleaned_part,
            )
            return None, cleaned_part, counter.get("tid") if counter else None
        elif not prefix:
            remainder = trimmed_part
        else:
            continue

        if remainder is None:
            continue

        for separator in ("?", "&", "#"):
            if separator in remainder:
                remainder = remainder.split(separator, 1)[0]
                break

        candidate = remainder.strip(_PREFIX_STRIP_CHARS)
        cleaned_part = trimmed_part
        if candidate:
            idx = trimmed_part.find(candidate, remainder_start)
            if idx != -1:
                cleaned_part = trimmed_part[:idx]
        cleaned_part = cleaned_part.rstrip(_PREFIX_STRIP_CHARS) or None
        masked_candidate = mask_cid(candidate) if candidate else None
        logger.debug(
            "%s Prefix trim: part=%r prefix=%r base_prefix=%r remainder=%r candidate=%r cleaned_part=%r",
            texts.LOG_PREFIX,
            trimmed_part,
            prefix,
            base_prefix,
            remainder,
            masked_candidate,
            cleaned_part,
        )

        if candidate and _CID_PATTERN.fullmatch(candidate):
            return candidate, cleaned_part, counter.get("tid") if counter else None

        if cleaned_part:
            return None, cleaned_part, counter.get("tid") if counter else None

    return None, None, None


def _trim_utm_code(utm_code: str | None) -> tuple[str | None, str | None]:
    if not utm_code or not isinstance(utm_code, str):
        return utm_code, None

    cid, cleaned_part, _ = extract_cid(utm_code)
    if cleaned_part:
        return cleaned_part, cid
    return utm_code, cid


def is_valid_cid(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    return bool(_CID_PATTERN.fullmatch(value.strip()))


async def store_cid(
    session,
    tg_id: int,
    cid: str,
    *,
    start_part: str | None = None,
    cleaned_part: str | None = None,
    counter_tid: str | None = None,
) -> None:

    logger.debug(
        "%s Storing cid=%s for tg_id=%s (start_part=%r, cleaned_part=%r)",
        texts.LOG_PREFIX,
        _mask_cid(cid),
        tg_id,
        start_part,
        cleaned_part,
    )
    await db.upsert_cid(session, tg_id, cid, counter_tid=counter_tid)


def _iter_counter_payloads(
    normalized_cid: str, *, counter_tid: str | None = None
) -> Iterable[dict[str, str]]:
    yielded = False
    matching_tid = str(counter_tid) if counter_tid else None

    configs = _iter_counter_configs()
    if matching_tid:
        for counter in configs:
            tid = counter.get("tid")
            if tid and str(tid) == matching_tid:
                ms = counter.get("ms")
                if not ms:
                    break
                yielded = True
                yield {"tid": str(tid), "cid": normalized_cid, "ms": str(ms)}
                break
        else:
            logger.warning(
                "%s Counter tid=%s not configured; falling back to all counters",
                texts.LOG_PREFIX,
                matching_tid,
            )

    if not yielded:
        for counter in configs:
            tid = counter.get("tid")
            ms = counter.get("ms")
            if not tid or not ms:
                continue
            yielded = True
            yield {"tid": str(tid), "cid": normalized_cid, "ms": str(ms)}

    if not yielded:
        logger.error(
            "%s Measurement Protocol credentials are not configured for any counter (cid=%s)",
            texts.LOG_PREFIX,
            _mask_cid(normalized_cid),
        )


def _prepare_common_payload(
    cid: str, *, counter_tid: str | None = None
) -> tuple[str, list[dict[str, str]]] | SendResult:
    normalized = _normalize_cid(cid)
    if not normalized:
        message = "ClientID (cid) must be a non-empty string"
        logger.warning("%s %s", texts.LOG_PREFIX, message)
        return SendResult(False, None, message)

    payloads = list(_iter_counter_payloads(normalized, counter_tid=counter_tid))
    if not payloads:
        message = "Measurement Protocol credentials are not configured"
        return SendResult(False, None, message)

    return normalized, payloads


def _collect_url() -> str:
    return settings.YA_COLLECT_URL or "https://mc.yandex.ru/collect"


def _send_with_retry(kind: str, payload: dict[str, str], cid: str, *, counter_id: str | None = None) -> SendResult:
    url = _collect_url()
    masked_cid = _mask_cid(cid)
    timeout = settings.YA_TIMEOUT_SECONDS
    max_attempts = max(1, settings.YA_MAX_ATTEMPTS)
    delay = max(0.0, settings.YA_RETRY_DELAY_SECONDS)
    counter_label = counter_id or "<unknown>"

    last_message = ""
    for attempt in range(1, max_attempts + 1):
        try:
            response: Response = requests.post(url, data=payload, timeout=timeout)
        except RequestException as exc:  # network error
            last_message = str(exc)
            logger.warning(
                "%s MP %s request error (attempt %s/%s, cid=%s, counter=%s): %s",
                texts.LOG_PREFIX,
                kind,
                attempt,
                max_attempts,
                masked_cid,
                counter_label,
                last_message,
            )
            if attempt == max_attempts:
                return SendResult(False, None, last_message)
            if delay:
                time.sleep(delay)
            continue

        status = response.status_code
        body = response.text
        if 200 <= status < 300:
            logger.info(
                "%s MP %s delivered (cid=%s, counter=%s, status=%s)",
                texts.LOG_PREFIX,
                kind,
                masked_cid,
                counter_label,
                status,
            )
            return SendResult(True, status, "ok")

        last_message = f"status={status} body={body}"
        if 500 <= status < 600:
            logger.warning(
                "%s MP %s server error (attempt %s/%s, cid=%s, counter=%s, status=%s)",
                texts.LOG_PREFIX,
                kind,
                attempt,
                max_attempts,
                masked_cid,
                counter_label,
                status,
            )
            if attempt == max_attempts:
                return SendResult(False, status, last_message)
            if delay:
                time.sleep(delay)
            continue

        logger.error(
            "%s MP %s rejected (cid=%s, counter=%s, status=%s)",
            texts.LOG_PREFIX,
            kind,
            masked_cid,
            counter_label,
            status,
        )
        return SendResult(False, status, last_message)

    return SendResult(False, None, last_message or "unknown error")


def _pageview_payload(base_payload: dict[str, str]) -> dict[str, str]:
    payload = dict(base_payload)
    payload.update(
        {
            "t": "pageview",
            "dl": settings.YA_DL,
            "dr": settings.YA_DR,
            "dt": settings.YA_DT,
        }
    )
    return payload


def _event_payload(
    base_payload: dict[str, str], *, ea: str, extra: dict[str, str] | None = None
) -> dict[str, str]:
    payload = dict(base_payload)
    payload.update({"t": "event", "ea": ea})
    if settings.YA_EVENT_INCLUDE_DL and settings.YA_DL:
        payload.setdefault("dl", settings.YA_DL)
    if extra:
        payload.update(extra)
    return payload


def send_pageview(cid: str, *, counter_tid: str | None = None) -> SendResult:
    prepared = _prepare_common_payload(cid, counter_tid=counter_tid)
    if isinstance(prepared, SendResult):
        return prepared
    normalized_cid, base_payloads = prepared

    last_result: SendResult | None = None
    for base_payload in base_payloads:
        payload = _pageview_payload(base_payload)
        last_result = _send_with_retry(
            "pageview",
            payload,
            normalized_cid,
            counter_id=base_payload.get("tid"),
        )
        if not last_result.success:
            return last_result

    return last_result or SendResult(True, 200, "ok")


def send_trial_add(cid: str, *, counter_tid: str | None = None) -> SendResult:
    pageview_result = send_pageview(cid, counter_tid=counter_tid)
    if not pageview_result.success:
        return pageview_result

    prepared = _prepare_common_payload(cid, counter_tid=counter_tid)
    if isinstance(prepared, SendResult):
        return prepared
    normalized_cid, base_payloads = prepared

    last_result: SendResult | None = None
    for base_payload in base_payloads:
        payload = _event_payload(base_payload, ea="trial-add")
        last_result = _send_with_retry(
            "trial-add",
            payload,
            normalized_cid,
            counter_id=base_payload.get("tid"),
        )
        if not last_result.success:
            return last_result

    return last_result or SendResult(True, 200, "ok")


def send_purchase(
    cid: str,
    order_id: str | None = None,
    *,
    counter_tid: str | None = None,
    amount: Any = None,
) -> SendResult:
    pageview_result = send_pageview(cid, counter_tid=counter_tid)
    if not pageview_result.success:
        return pageview_result

    prepared = _prepare_common_payload(cid, counter_tid=counter_tid)
    if isinstance(prepared, SendResult):
        return prepared
    normalized_cid, base_payloads = prepared

    last_result: SendResult | None = None
    event_value = _normalize_event_value(amount)
    extra_payload = {"ev": event_value} if event_value is not None else None
    for base_payload in base_payloads:
        payload = _event_payload(base_payload, ea="purchase", extra=extra_payload)
        last_result = _send_with_retry(
            "purchase",
            payload,
            normalized_cid,
            counter_id=base_payload.get("tid"),
        )
        if not last_result.success:
            return last_result

    return last_result or SendResult(True, 200, "ok")
