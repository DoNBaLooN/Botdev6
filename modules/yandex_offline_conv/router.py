from __future__ import annotations

from typing import Any

from aiogram import Router
from sqlalchemy.ext.asyncio import AsyncSession

from hooks.hooks import register_hook
from logger import logger

from . import services, settings, texts


router = Router(name="yandex_offline_conv")


def _truncate(value: str | None, limit: int = 200) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


async def start_link_hook(
    message=None,
    session: AsyncSession | None = None,
    user_data: dict | None = None,
    part: str = "",
    **_: Any,
):
    if session is None:
        logger.warning(f"{texts.LOG_PREFIX} start_link hook invoked without session")
        return None

    module_enabled = settings.ENABLED
    logger.debug(
        "%s start_link hook received part=%r (enabled=%s)",
        texts.LOG_PREFIX,
        part,
        module_enabled,
    )

    tg_id = None
    if user_data and isinstance(user_data, dict):
        tg_id = user_data.get("tg_id")
    if tg_id is None and message is not None:
        from_user = getattr(message, "from_user", None)
        if from_user is not None:
            tg_id = getattr(from_user, "id", None)
        if tg_id is None:
            chat = getattr(message, "chat", None)
            tg_id = getattr(chat, "id", None)

    if tg_id is None:
        logger.debug(f"{texts.LOG_PREFIX} Unable to determine tg_id for start parameter: %s", part)
        return None

    cid, cleaned_part, counter_tid = services.extract_cid(part)
    logger.debug(
        "%s Extracted data for tg_id=%s: part=%r, cid=%r, cleaned_part=%r",
        texts.LOG_PREFIX,
        tg_id,
        part,
        services.mask_cid(cid),
        cleaned_part,
    )

    if not cid:
        if cleaned_part:
            logger.debug(
                "%s start parameter matched prefix but no cid found for tg_id=%s",
                texts.LOG_PREFIX,
                tg_id,
            )
            return cleaned_part
        logger.debug(
            "%s Skipping part=%r for tg_id=%s — does not match configured prefix",
            texts.LOG_PREFIX,
            part,
            tg_id,
        )
        return None

    try:
        if not services.is_valid_cid(cid):
            logger.warning(
                "%s Received malformed cid for tg_id=%s: %s",
                texts.LOG_PREFIX,
                tg_id,
                services.mask_cid(cid),
            )
            return cleaned_part or part or None

        await services.store_cid(
            session,
            tg_id,
            cid,
            start_part=part,
            cleaned_part=cleaned_part,
            counter_tid=counter_tid,
        )
        await session.commit()
        logger.info(
            "%s Captured cid=%s for tg_id=%s",
            texts.LOG_PREFIX,
            services.mask_cid(cid),
            tg_id,
        )
        if not module_enabled:
            logger.info(
                "%s Module disabled, but start link metadata persisted for tg_id=%s",
                texts.LOG_PREFIX,
                tg_id,
            )
    except Exception:
        await session.rollback()
        logger.exception(
            "%s Failed to process start code for tg_id=%s (cid=%s, part=%s)",
            texts.LOG_PREFIX,
            tg_id,
            services.mask_cid(cid),
            _truncate(part),
        )

    return cleaned_part or part or None


register_hook("start_link", start_link_hook)


logger.info("%s Module yandex_offline_conv initialized", texts.LOG_PREFIX)
