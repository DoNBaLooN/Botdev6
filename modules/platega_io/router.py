import uuid
from typing import Any

import aiohttp
from aiohttp.web import Response
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from hooks.hooks import register_hook

from .settings import ENABLE, MERCHANT_ID, API_KEY, CALLBACK_PATH, PAYMENT_METHODS, SUCCESS_URL, FAILED_URL

router = Router(name="platega_module")


class ReplenishBalancePlategaState(StatesGroup):
    entering_custom_amount = State()


async def _pg_headers() -> dict[str, str]:
    return {"X-MerchantId": MERCHANT_ID, "X-Secret": API_KEY, "Content-Type": "application/json"}


async def _suggest_amounts(session: AsyncSession) -> list[int]:
    from database.tariffs import get_tariffs
    from config import RENEWAL_PRICES

    tariffs = await get_tariffs(session)
    tariff_prices: list[int] = []
    for t in tariffs:
        try:
            p = t.get("price")
            if p is None:
                continue
            p_int = int(float(p))
            if p_int > 0:
                tariff_prices.append(p_int)
        except Exception:
            continue

    renewal_prices: list[int] = []
    try:
        renewal_prices = [int(v) for v in (RENEWAL_PRICES or {}).values() if int(v) > 0]
    except Exception:
        pass

    amounts = sorted(set(tariff_prices + renewal_prices))[:6]
    return amounts or [300, 500, 1000]


def _amounts_keyboard(method_code: int, amounts: list[int], back_cb: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for a in amounts:
        kb.row(InlineKeyboardButton(text=f"+{a}₽", callback_data=f"platega_amount|{method_code}|{a}"))
    kb.row(InlineKeyboardButton(text="Ввести сумму", callback_data=f"plg_custom_amount|{method_code}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb))
    return kb


async def _show_amounts(target_message, session: AsyncSession, method_code: int, back_cb: str, title: str):
    from handlers.utils import edit_or_send_message

    amounts = await _suggest_amounts(session)
    kb = _amounts_keyboard(method_code, amounts, back_cb)
    await edit_or_send_message(target_message=target_message, text=title, reply_markup=kb.as_markup(), force_text=True)


async def _pg_create_link(amount_rub: int, method: int | None = None, payload: str | None = None) -> str | None:
    url = "https://app.platega.io/transaction/process"
    success_url = SUCCESS_URL
    failed_url = FAILED_URL
    body = {
        "paymentMethod": int(method or 2),
        "id": str(uuid.uuid4()),
        "paymentDetails": {"amount": int(amount_rub), "currency": "RUB"},
        "description": "Topup",
        "return": success_url,
        "failedUrl": failed_url,
    }
    if payload:
        body["payload"] = payload
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=await _pg_headers(), json=body, timeout=30) as r:
                data = await r.json(content_type=None)
                try:
                    external_id = str(data.get("id") or body.get("id"))
                    if external_id and payload:
                        from sqlalchemy import insert
                        from database import async_session_maker
                        from .models import PendingPayment, ModuleBase
                        try:
                            async with async_session_maker() as sess:
                                await sess.run_sync(ModuleBase.metadata.create_all, bind=sess.bind)
                        except Exception:
                            pass
                        async with async_session_maker() as sess:
                            stmt = insert(PendingPayment).values(
                                external_id=external_id,
                                tg_id=int(payload),
                                amount=float(amount_rub),
                                payment_system="platega",
                                method_code=int(method or 0),
                            )
                            try:
                                await sess.execute(stmt)
                                await sess.commit()
                            except Exception:
                                await sess.rollback()
                except Exception:
                    pass
                return data.get("redirect") or data.get("return")
    except Exception:
        return None


def _providers_patch() -> dict[str, dict[str, Any]]:
    if not ENABLE:
        return {}
    # Экспортируем один провайдер PLATEGA (RUB). fast не используется (core вызывает только функции из core).
    return {"PLATEGA": {"currency": "RUB", "value": "pay_platega", "fast": None, "module": "platega_io", "enabled": True}}


@router.callback_query(F.data == "pay_platega")
async def pay_platega_start(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    from .texts import PLATEGA_SELECT_METHOD, PLATEGA_SELECT_SUM, PLATEGA_UNAVAILABLE
    if not ENABLE:
        await cb.answer(PLATEGA_UNAVAILABLE, show_alert=True)
        return
    enabled_methods = [m for m in PAYMENT_METHODS if m.get("enable")]
    if len(enabled_methods) <= 1:
        method_code = (enabled_methods[0]["code"] if enabled_methods else 2)
        await _show_amounts(cb.message, session, method_code, back_cb="pay", title=PLATEGA_SELECT_SUM)
        return
    kb = InlineKeyboardBuilder()
    for m in enabled_methods:
        kb.row(InlineKeyboardButton(text=m["label"], callback_data=f"platega_method|{m['code']}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="pay"))
    from handlers.utils import edit_or_send_message
    await edit_or_send_message(target_message=cb.message, text=PLATEGA_SELECT_METHOD, reply_markup=kb.as_markup(), force_text=True)


@router.callback_query(F.data.startswith("pay_plg|"))
async def pay_platega_from_main(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    method_code = int(cb.data.split("|")[-1])
    from .texts import PLATEGA_SELECT_SUM
    await _show_amounts(cb.message, session, method_code, back_cb="pay", title=PLATEGA_SELECT_SUM)


@router.callback_query(F.data.startswith("platega_method|"))
async def pay_platega_method(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    method_code = int(cb.data.split("|")[-1])
    from .texts import PLATEGA_SELECT_SUM
    await _show_amounts(cb.message, session, method_code, back_cb="pay_platega", title=PLATEGA_SELECT_SUM)


@router.callback_query(F.data.startswith("platega_amount|"))
async def pay_platega_amount(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    parts = cb.data.split("|")
    if len(parts) == 3:
        method_code = int(parts[1])
        amount = int(parts[2])
    else:
        method_code = 2
        amount = int(parts[-1])
    link = await _pg_create_link(amount, method_code, payload=str(cb.from_user.id))
    if not link:
        from .texts import PLATEGA_CREATE_LINK_ERROR
        from handlers.utils import edit_or_send_message
        kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад", callback_data="pay"))
        await edit_or_send_message(target_message=cb.message, text=PLATEGA_CREATE_LINK_ERROR, reply_markup=kb.as_markup(), force_text=True)
        return
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Оплатить", url=link))
    kb.row(InlineKeyboardButton(text="Готово", callback_data="balance"))
    from handlers.utils import edit_or_send_message
    await edit_or_send_message(target_message=cb.message, text=f"Оплатите и вернитесь в бот. Сумма: {amount}₽", reply_markup=kb.as_markup(), force_text=True)


@router.callback_query(F.data.startswith("plg_custom_amount|"))
async def platega_custom_amount(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("|")
    method_code = int(parts[1]) if len(parts) > 1 else 2
    await state.update_data(platega_method=method_code)
    from .texts import PLATEGA_ENTER_SUM
    from handlers.utils import edit_or_send_message
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="⬅️ Назад", callback_data="pay_platega"))
    await edit_or_send_message(target_message=cb.message, text=PLATEGA_ENTER_SUM, reply_markup=kb.as_markup(), force_text=True)
    await state.set_state(ReplenishBalancePlategaState.entering_custom_amount)


@router.message(ReplenishBalancePlategaState.entering_custom_amount)
async def handle_platega_custom_amount_input(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    try:
        amount = int(text)
        if amount <= 0:
            raise ValueError
    except Exception:
        from handlers.utils import edit_or_send_message
        await edit_or_send_message(target_message=message, text="Некорректная сумма. Введите целое число больше 0.", reply_markup=None, force_text=True)
        return

    data = await state.get_data()
    method_code = int(data.get("platega_method", 2))

    link = await _pg_create_link(amount, method_code, payload=str(message.from_user.id))
    if not link:
        from .texts import PLATEGA_CREATE_LINK_ERROR_SIMPLE
        from handlers.utils import edit_or_send_message
        await edit_or_send_message(target_message=message, text=PLATEGA_CREATE_LINK_ERROR_SIMPLE, reply_markup=None, force_text=True)
        return

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Оплатить", url=link))
    kb.row(InlineKeyboardButton(text="Готово", callback_data="balance"))
    from handlers.utils import edit_or_send_message
    await edit_or_send_message(target_message=message, text=f"Оплатите и вернитесь в бот. Сумма: {amount}₽", reply_markup=kb.as_markup(), force_text=True)
    await state.clear()


def get_webhook_data():
    async def handler(request):
        try:
            data = await request.json()
        except Exception:
            return Response(status=400, text="bad json")
        auth_header = request.headers.get("Authorization") or ""
        mid = (
            request.headers.get("X-MerchantId")
            or request.headers.get("X-MerchantID")
            or request.headers.get("X-Merchant-Id")
            or request.headers.get("MerchantId")
            or request.headers.get("Merchant-Id")
            or data.get("merchantId")
            or data.get("merchant_id")
            or ""
        )
        sec = (
            request.headers.get("X-Secret")
            or request.headers.get("X-Secret-Key")
            or request.headers.get("X-Api-Key")
            or request.headers.get("X-API-Key")
            or request.headers.get("X-Token")
            or (auth_header.split(" ", 1)[1] if auth_header.lower().startswith("bearer ") else "")
            or data.get("secret")
            or data.get("apiKey")
            or ""
        )

        mid = str(mid).strip()
        sec = str(sec).strip()

        if mid != MERCHANT_ID or sec != API_KEY:
            try:
                from logger import logger
                def _mask(v: str) -> str:
                    if not v:
                        return ""
                    if len(v) <= 8:
                        return v[0:2] + "***" + v[-2:]
                    return v[0:4] + "***" + v[-4:]
                logger.warning(
                    f"[PlategaWebhook] 403 auth failed: mid_match={mid == MERCHANT_ID}, sec_match={sec == API_KEY}, "
                    f"mid={_mask(mid)}, cfg_mid={_mask(MERCHANT_ID)}, sec={_mask(sec)}, cfg_sec={_mask(API_KEY)}"
                )
            except Exception:
                pass
            return Response(status=403, text="forbidden")

        status_raw = data.get("status")
        status = str(status_raw or "").strip().upper()
        # В разных интеграциях поле суммы может быть строкой
        try:
            amount = float(data.get("amount") or 0)
        except Exception:
            try:
                amount = float(str(data.get("amount") or "0").replace(",", "."))
            except Exception:
                amount = 0.0

        # Получим идентификатор пользователя: payload/id/orderId
        payload_raw = (
            data.get("payload")
            or data.get("id")
            or data.get("orderId")
            or data.get("order_id")
            or ""
        )
        payload = str(payload_raw)
        try:
            from database import async_session_maker, update_balance, add_payment
            from sqlalchemy import delete, select
            from .models import PendingPayment, ModuleBase
            try:
                tg_id = int(str(payload).strip() or 0)
            except Exception:
                tg_id = 0

            # Статусы успешной оплаты: поддерживаем строки и числовой код 7
            is_success = False
            try:
                if isinstance(status_raw, (int, float)):
                    is_success = int(status_raw) == 7
                else:
                    is_success = status in {"CONFIRMED", "PAID", "SUCCESS", "COMPLETED", "7"}
            except Exception:
                is_success = status in {"CONFIRMED", "PAID", "SUCCESS", "COMPLETED", "7"}

            async with async_session_maker() as sess:
                try:
                    await sess.run_sync(ModuleBase.metadata.create_all, bind=sess.bind)
                except Exception:
                    pass
                if tg_id <= 0:
                    try:
                        result = await sess.execute(select(PendingPayment).where(PendingPayment.external_id == str(data.get("id") or "")))
                        row = result.scalar_one_or_none()
                        if row:
                            tg_id = int(row.tg_id or 0)
                            if amount <= 0 and row.amount:
                                amount = float(row.amount)
                            await sess.execute(delete(PendingPayment).where(PendingPayment.external_id == row.external_id))
                            await sess.commit()
                    except Exception:
                        await sess.rollback()

                if is_success and tg_id:
                    await update_balance(sess, tg_id, amount)
                    await add_payment(sess, tg_id, amount, "platega")
                    try:
                        from handlers.payments.utils import send_payment_success_notification
                        await send_payment_success_notification(tg_id, float(amount), sess)
                    except Exception:
                        pass
            return Response(status=200, text="ok")
        except Exception:
            return Response(status=200, text="ok")
    return {"path": CALLBACK_PATH, "handler": handler}


from hooks.hooks import register_hook as _register_hook
@_register_hook("providers_config")
def providers_hook(providers: dict[str, dict], flags: dict[str, bool] | None = None) -> dict:
    return _providers_patch()

register_hook("web_app", get_webhook_data)


@register_hook("pay_menu_buttons")
async def pay_menu_buttons_hook(**kwargs):
    if not ENABLE:
        return None
    # Заменим дефолтную кнопку провайдера на красивую подпись
    return [
        {"remove": "pay_platega"},
        {"button": InlineKeyboardButton(text="СБП", callback_data="pay_platega")},
    ]



def get_fast_flow_handler():
    try:
        from .settings import ENABLE as MOD_ENABLE
        from .settings import FAST_FLOW_ENABLE, PAYMENT_KEY, PAYMENT_METHODS as METHODS
    except Exception:
        MOD_ENABLE = ENABLE
        FAST_FLOW_ENABLE = False
        METHODS = PAYMENT_METHODS
        PAYMENT_KEY = "PLATEGA_FAST"

    if not MOD_ENABLE or not FAST_FLOW_ENABLE:
        return None

    async def handler(callback_query: CallbackQuery, session: AsyncSession, state: FSMContext):
        try:
            from handlers.utils import edit_or_send_message
            from logger import logger
            required_amount = 0
            try:
                data = await state.get_data()
                required_amount = int(data.get("required_amount", 0) or 0)
            except Exception:
                required_amount = 0

            if required_amount <= 0:
                try:
                    from database.temporary_data import get_temporary_data
                    from database import get_tariff_by_id
                    tmp = await get_temporary_data(session, callback_query.from_user.id)
                    if tmp and isinstance(tmp.get("data"), dict):
                        tmp_data = tmp["data"]
                        if tmp_data.get("required_amount"):
                            required_amount = int(tmp_data.get("required_amount") or 0)
                        elif tmp_data.get("cost"):
                            required_amount = int(float(tmp_data.get("cost") or 0))
                        elif tmp_data.get("tariff_id"):
                            try:
                                tariff = await get_tariff_by_id(session, int(tmp_data.get("tariff_id")))
                                if tariff and tariff.get("price_rub"):
                                    required_amount = int(tariff["price_rub"])
                            except Exception:
                                pass
                except Exception as e:
                    logger.error(f"[PlategaFast] Не удалось получить required_amount: {e}")

            if required_amount <= 0:
                required_amount = 1

            kb = InlineKeyboardBuilder()
            enabled_methods = [m for m in METHODS if m.get("enable")]
            if not enabled_methods:
                enabled_methods = [{"code": 2, "label": "СБП / QR"}]
            for m in enabled_methods:
                label = str(m.get("label") or f"Метод {m['code']}")
                kb.row(InlineKeyboardButton(text=label, callback_data=f"platega_amount|{m['code']}|{required_amount}"))
            kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="balance"))

            await edit_or_send_message(
                target_message=callback_query.message,
                text=f"Недостаточно средств. Пополните на <b>{required_amount}₽</b> выбрав способ оплаты ниже:",
                reply_markup=kb.as_markup(),
                force_text=True,
            )
        except Exception as e:
            try:
                from logger import logger
                logger.error(f"[PlategaFast] Ошибка показа сумм: {e}")
            except Exception:
                pass
            return

    return {"payment_key": PAYMENT_KEY, "handler": handler}

