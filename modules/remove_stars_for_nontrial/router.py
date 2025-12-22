from __future__ import annotations

from typing import Any

from aiogram import Router

from hooks.hooks import register_hook
from logger import logger

from . import settings
from .db import user_is_trial, key_is_trial, client_is_trial


router = Router(name="remove_stars_for_nontrial")


async def pay_menu_buttons_hook(**kwargs: Any):
    session = kwargs.get("session")
    tg_id = kwargs.get("tg_id") or kwargs.get("chat_id")
    # контекст выбора при формировании платёжного меню
    key_name = kwargs.get("key_name") or kwargs.get("key")   # текстовое имя ключа (колонка keys.key)
    client_id = kwargs.get("client_id")                      # колонка keys.client_id

    if session is None or tg_id is None:
        if settings.DEBUG_LOG:
            logger.warning("[remove_stars_for_nontrial] session/tg_id not provided in hook kwargs")
        return None

    try:
        # Приоритетная проверка:
        # 1) по конкретному ключу (key) — самый точный сценарий
        if key_name:
            is_trial = await key_is_trial(session, key_name, settings.TRIAL_TARIFF_ID)
            if settings.DEBUG_LOG:
                logger.info(f"[remove_stars_for_nontrial] key={key_name!r} (tariff_id={settings.TRIAL_TARIFF_ID}) -> is_trial={is_trial}")
        # 2) по конкретному client_id (в связке с tg_id)
        elif client_id:
            is_trial = await client_is_trial(session, tg_id, str(client_id), settings.TRIAL_TARIFF_ID)
            if settings.DEBUG_LOG:
                logger.info(f"[remove_stars_for_nontrial] client_id={client_id} tg_id={tg_id} (tariff_id={settings.TRIAL_TARIFF_ID}) -> is_trial={is_trial}")
        # 3) иначе — любой активный trial у пользователя
        else:
            is_trial = await user_is_trial(session, tg_id, settings.TRIAL_TARIFF_ID)
            if settings.DEBUG_LOG:
                logger.info(f"[remove_stars_for_nontrial] tg_id={tg_id} (tariff_id={settings.TRIAL_TARIFF_ID}) -> is_trial={is_trial}")

        if is_trial:
            return None
        if settings.REMOVE_BY_PREFIX:
            return {"remove_prefix": settings.STARS_CALLBACK_PREFIX}
        return {"remove": settings.STARS_CALLBACK_DATA}
        # Всегда скрываем кнопку "Ввести свою сумму"
        actions: list[dict[str, str]] = [{"remove": settings.CUSTOM_AMOUNT_CALLBACK_DATA}]

        # Если у пользователя нет активного триала — дополнительно убираем оплату звёздами
        if not is_trial:
            if settings.REMOVE_BY_PREFIX:
                actions.append({"remove_prefix": settings.STARS_CALLBACK_PREFIX})
            else:
                actions.append({"remove": settings.STARS_CALLBACK_DATA})

        # Возвращаем один или несколько "действий" для хука формирования клавиатуры
        if settings.DEBUG_LOG:
            logger.info(f"[remove_stars_for_nontrial] actions={actions}")
        # Если интеграция хука ожидает один объект — при одном действии вернём dict, иначе список
        if len(actions) == 1:
            return actions[0]
        return actions
    except Exception as e:
        logger.exception(f"[remove_stars_for_nontrial] error: {e}")
        return None


register_hook("pay_menu_buttons", pay_menu_buttons_hook)
