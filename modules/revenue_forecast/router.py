from __future__ import annotations

from datetime import datetime, timedelta, date
from io import BytesIO, StringIO
from math import ceil
import re
import csv
import zipfile

import pytz
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_ID
from hooks.hooks import register_hook
from logger import logger

from . import db, settings, texts
from database.models import Admin


router = Router()

if isinstance(ADMIN_ID, (list, tuple, set)):
    ADMIN_IDS = {int(x) for x in ADMIN_ID if x is not None}
else:
    ADMIN_IDS = {int(ADMIN_ID)} if ADMIN_ID else set()


class AdSpendForm(StatesGroup):
    amount = State()


class UTMAdSpendForm(StatesGroup):
    source_code = State()
    amount = State()


async def _build_main_keyboard(can_edit_ads: bool) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_REFRESH, callback_data="rf|refresh")
    builder.button(text=texts.BTN_DAILY_FORECAST, callback_data="rf|daily|open")
    if settings.ENABLE_ADS_BLOCK and can_edit_ads:
        builder.button(text=texts.BTN_EDIT_AD_SPEND, callback_data="rf|ads|edit")
    builder.button(text=texts.BTN_UTM_STATS, callback_data="rf|utm")
    builder.button(text=texts.BTN_BACK, callback_data=settings.STATS_ANCHOR_CALLBACK)
    builder.adjust(1)
    return builder


def _build_daily_keyboard(target_date: date) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    builder.row(
        InlineKeyboardButton(text="⬅️", callback_data=f"rf|date|{prev_date.isoformat()}"),
        InlineKeyboardButton(text="🗓️ Сегодня", callback_data="rf|date|today"),
        InlineKeyboardButton(text="➡️", callback_data=f"rf|date|{next_date.isoformat()}"),
    )
    builder.row(InlineKeyboardButton(text=texts.BTN_BACK, callback_data="rf|open"))
    return builder


def _ads_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.ADS_BTN_CANCEL, callback_data="rf|ads|cancel")
    builder.adjust(1)
    return builder.as_markup()


def _ads_saved_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BTN_TO_STATS, callback_data="rf|admin")
    builder.adjust(1)
    return builder.as_markup()


def _utm_keyboard(page: int, total_pages: int, entries: list[dict[str, Any]]):
    def _short_title(title: str, max_len: int = 18) -> str:
        clean = title.strip()
        if len(clean) <= max_len:
            return clean
        return clean[: max_len - 1] + "…"

    builder = InlineKeyboardBuilder()
    for entry in entries:
        code = str(entry.get("code") or "")
        if not code:
            continue
        title = str(entry.get("title") or code)
        label = _short_title(title) or code
        builder.row(
            InlineKeyboardButton(
                text=f"{texts.BTN_UTM_EDIT_AD_SPEND} {label}",
                callback_data=f"rf|utm|ads|edit|{code}",
            )
        )
    builder.row(InlineKeyboardButton(text=texts.BTN_REFRESH, callback_data=f"rf|utm|refresh|{page}"))
    # builder.row(InlineKeyboardButton(text=texts.BTN_UTM_EXPORT, callback_data="rf|utm|export"))
    if total_pages > 1:
        prev_page = max(1, page - 1)
        next_page = min(total_pages, page + 1)
        builder.row(
            InlineKeyboardButton(text="⬅️", callback_data=f"rf|utm|page|{prev_page}"),
            InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="rf|noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"rf|utm|page|{next_page}"),
        )
    builder.row(InlineKeyboardButton(text=texts.BTN_BACK, callback_data="rf|utm|back"))
    return builder.as_markup()


def _get_utm_page_from_markup(message: Message | None) -> int:
    if not message or not message.reply_markup:
        return 1
    try:
        for row in message.reply_markup.inline_keyboard:
            for btn in row:
                data = getattr(btn, "callback_data", "") or ""
                if data.startswith("rf|utm|refresh|"):
                    page_raw = data.split("|")[-1]
                    return int(page_raw)
    except Exception:
        return 1
    return 1


async def _resolve_can_edit_ads(session: AsyncSession, tg_id: int | None) -> bool:
    if not settings.ENABLE_ADS_BLOCK or not tg_id:
        return False
    if tg_id in ADMIN_IDS:
        return True
    result = await session.execute(select(Admin.role).where(Admin.tg_id == tg_id))
    role = result.scalar_one_or_none()
    return role is not None and str(role).lower() != "moderator"


async def _prepare_summary(session: AsyncSession, can_edit_ads: bool) -> tuple[str, Any]:
    moscow_tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.now(moscow_tz)
    now = now_msk.astimezone(pytz.UTC).replace(tzinfo=None)
    dt_start, dt_end = await db.get_month_bounds(now)
    expiring = await db.get_expiring_by_plan(session, dt_start, dt_end, settings)
    baseline_expiring = await db.get_baseline_expiring_by_plan(session, dt_start, dt_end, settings)
    received = await db.get_received(session, dt_start, dt_end, settings)
    probs_to_use = settings.PLAN_PROB_OVERRIDES or {}
    global_p = settings.RENEWAL_PROBABILITY
    if (not probs_to_use) and (global_p is None):
        probs_to_use = await db.estimate_auto_renewal_probs(session, months_back=3, grace_days=0, flags=settings)
        global_p = None
    
    data = db.compute_forecast(
        expiring,
        received,
        probs=probs_to_use,
        global_prob=global_p,
    )
    baseline = db.compute_forecast(
        baseline_expiring,
        {"net": 0.0, "paid": 0.0, "refunds": 0.0},
        probs=probs_to_use,
        global_prob=global_p,
    )
    data["plan_baseline"] = baseline.get("forecast", 0.0)
    data["by_plans_baseline"] = baseline_expiring
    data["by_plans_current"]  = expiring
    mode = getattr(settings, "COMPLETION_MODE", "cash")
    plan_sum = float(data["plan_baseline"])
    recognized_total = None
    if plan_sum > 0:
        if mode == "plan_vs_forecast":
            forecast_sum = float(data.get("forecast", 0.0))
            data["plan_completion_pct"] = max(0.0, min(100.0, (plan_sum - forecast_sum) / plan_sum * 100.0))
        elif mode == "accrual":
            recognized = await db.get_recognized_revenue_accrual(session, dt_start, now, settings)
            recognized_total = float(recognized.get("total", 0.0))
            data["plan_completion_pct"] = (recognized_total / plan_sum) * 100.0
        else:  
            fact_sum = float(data.get("received", 0.0))
            data["plan_completion_pct"] = (fact_sum / plan_sum) * 100.0
    else:
        data["plan_completion_pct"] = None

    if plan_sum > 0:
        if mode == "plan_vs_forecast":
            data["plan_gap"] = float(data.get("forecast", 0.0))
        elif mode == "accrual":
            if recognized_total is None:
                rec = await db.get_recognized_revenue_accrual(session, dt_start, now, settings)
                recognized_total = float(rec.get("total", 0.0))
            data["plan_gap"] = max(0.0, plan_sum - recognized_total)
        else:  
            fact = float(data.get("received", 0.0))
            data["plan_gap"] = max(0.0, plan_sum - fact)
    else:
        data["plan_gap"] = 0.0
    kpis = await db.calc_kpis(
        session, dt_start, dt_end, settings,
        data.get("by_plans", {}),
        probs=probs_to_use,
        global_prob=global_p,
    )
    data["metrics"] = kpis
    data["updated_human_msk"] = now_msk.strftime("%d.%m.%y %H:%M:%S")
    if settings.ENABLE_ADS_BLOCK:
        spend_amount = await db.get_ad_spend(session, dt_start.date())
        new_clients, new_revenue = await db.get_new_clients_and_revenue(session, dt_start, dt_end)
        spend_amount = float(spend_amount)
        cac_value = None
        if spend_amount > 0 and new_clients > 0:
            cac_value = spend_amount / new_clients
        roi_value = None
        if spend_amount > 0:
            roi_value = ((new_revenue - spend_amount) / spend_amount) * 100.0
        data["ads"] = {
            "spend": spend_amount,
            "new_clients": new_clients,
            "new_revenue": new_revenue,
            "cac": cac_value,
            "roi": roi_value,
        }
    text = texts.render_summary(data)
    kb = await _build_main_keyboard(can_edit_ads)
    return text, kb.as_markup()


async def _prepare_utm_stats(session: AsyncSession, page: int) -> tuple[str, Any]:
    moscow_tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.now(moscow_tz)
    now_utc = now_msk.astimezone(pytz.UTC).replace(tzinfo=None)
    current_start, current_end = await db.get_month_bounds(now_utc)
    previous_ref = current_start - timedelta(days=1)
    previous_start, previous_end = await db.get_month_bounds(previous_ref)

    raw_stats = await db.get_utm_stats(
        session,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    items: list[dict[str, Any]] = []
    for entry in raw_stats:
        previous_val = float(entry.get("previous", 0.0))
        current_val = float(entry.get("current", 0.0))
        renewals_val = float(entry.get("renewals", 0.0))
        payments_val = int(entry.get("payments", 0))
        total_amount_val = float(entry.get("total_amount", 0.0))
        new_clients_val = int(entry.get("new_clients", 0))
        new_revenue_val = float(entry.get("new_revenue", 0.0))
        ad_spend_val = float(entry.get("ad_spend", 0.0))
        cac_val = entry.get("cac")
        roi_val = entry.get("roi")
        growth_pct: float | None
        growth_infinite = False
        if abs(previous_val) < 1e-9:
            if abs(current_val) < 1e-9:
                growth_pct = 0.0
            else:
                growth_pct = None
                growth_infinite = True
        else:
            growth_pct = ((current_val - previous_val) / previous_val) * 100.0

        items.append(
            {
                "code": entry.get("code"),
                "title": entry.get("title"),
                "previous": previous_val,
                "current": current_val,
                "renewals": renewals_val,
                "payments": payments_val,
                "total_amount": total_amount_val,
                "new_clients": new_clients_val,
                "new_revenue": new_revenue_val,
                "ad_spend": ad_spend_val,
                "cac": cac_val,
                "roi": roi_val,
                "growth_pct": growth_pct,
                "growth_infinite": growth_infinite,
            }
        )

    page_size = max(1, int(getattr(settings, "UTM_PAGE_SIZE", 3)))
    total_pages = max(1, ceil(len(items) / page_size))
    safe_page = max(1, min(page, total_pages))
    start = (safe_page - 1) * page_size
    stop = start + page_size
    page_items = items[start:stop]

    data = {
        "items": page_items,
        "updated_human_msk": now_msk.strftime("%d.%m.%y %H:%M:%S"),
        "page": safe_page,
        "total_pages": total_pages,
    }
    text = texts.render_utm_stats(data)
    return text, _utm_keyboard(safe_page, total_pages, page_items)


def _safe_sheet_title(title: str, fallback: str, used: set[str]) -> str:
    raw = title or fallback or "UTM"
    clean = re.sub(r"[\\/*?:\[\]]", " ", raw).strip() or "UTM"
    base = clean[:31]
    candidate = base
    counter = 1
    while candidate in used or not candidate:
        suffix = f"_{counter}"
        candidate = (base[: 31 - len(suffix)] + suffix) if len(base) + len(suffix) > 31 else base + suffix
        counter += 1
    used.add(candidate)
    return candidate


async def _build_utm_export(session: AsyncSession) -> BytesIO:
    sources = await db.get_utm_sources(session)
    if not sources:
        raise ValueError("no_sources")

    now_utc = datetime.utcnow()
    timeseries = await db.get_utm_daily_stats(session, until_utc=now_utc)
    spend_map = await db.get_ad_spend_by_source_all(session)

    moscow_tz = pytz.timezone("Europe/Moscow")
    end_date = now_utc.astimezone(moscow_tz).date()

    used_titles: set[str] = set()
    headers = [
        "Дата",
        "Новые клиенты",
        "Сумма первых платежей",
        "Сумма продлений",
        "Сумма всех платежей",
        "Уникальные клиенты",
        "Регистрации",
        "Триалы",
        "Количество платежей",
        "Расход на рекламу (месяц)",
        "CAC",
        "ROI",
    ]

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for src in sources:
            code = src.get("code") or ""
            title = src.get("title") or code
            if not code:
                continue

            created_at = src.get("created_at")
            if isinstance(created_at, datetime):
                start_date = created_at.date()
            elif isinstance(created_at, date):
                start_date = created_at
            else:
                start_date = end_date

            start_date = min(start_date, end_date)
            by_day = timeseries.get(code, {})
            current = start_date

            safe_title = _safe_sheet_title(str(title), code, used_titles)
            csv_buffer = StringIO()
            csv_buffer.write("\ufeff")
            writer = csv.writer(csv_buffer)
            writer.writerow(headers)

            while current <= end_date:
                stats = by_day.get(current) or {}
                month_start = current.replace(day=1)
                ad_spend = float(spend_map.get(code, {}).get(month_start, 0.0))

                new_clients = int(stats.get("new_clients", 0))
                new_revenue = float(stats.get("first_amount", 0.0))
                renewals = float(stats.get("renewals", 0.0))
                total_amount = float(stats.get("total_amount", 0.0))
                unique_clients = int(stats.get("unique_clients", 0))
                registrations = int(stats.get("registrations", 0))
                trials = int(stats.get("trials", 0))
                payments_count = int(stats.get("payments_count", 0))

                cac = (ad_spend / new_clients) if (ad_spend > 0 and new_clients > 0) else None
                roi = ((new_revenue - ad_spend) / ad_spend * 100.0) if ad_spend > 0 else None

                writer.writerow(
                    [
                        current.strftime("%d.%m.%Y"),
                        new_clients,
                        round(new_revenue, 2),
                        round(renewals, 2),
                        round(total_amount, 2),
                        unique_clients,
                        registrations,
                        trials,
                        payments_count,
                        round(ad_spend, 2),
                        round(cac, 2) if cac is not None else "—",
                        round(roi, 2) if roi is not None else "—",
                    ]
                )

                current += timedelta(days=1)

            archive.writestr(f"{safe_title}.csv", csv_buffer.getvalue())

    buffer.seek(0)
    return buffer


async def _render_summary(message: Message, session: AsyncSession, can_edit_ads: bool):
    text, markup = await _prepare_summary(session, can_edit_ads)
    await message.edit_text(text=text, reply_markup=markup)


async def _render_daily_view(message: Message, session: AsyncSession, target_date: date):
    moscow_tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.now(moscow_tz)

    dt_start_msk = moscow_tz.localize(datetime.combine(target_date, datetime.min.time()))
    dt_end_msk = dt_start_msk + timedelta(days=1)
    dt_start_utc = dt_start_msk.astimezone(pytz.UTC).replace(tzinfo=None)
    dt_end_utc = dt_end_msk.astimezone(pytz.UTC).replace(tzinfo=None)

    expiring_details = await db.get_expiring_by_plan(session, dt_start_utc, dt_end_utc, settings)

    data = {
        "date_str": target_date.strftime("%d.%m.%Y"),
        "details": expiring_details,
        "updated_human_msk": now_msk.strftime("%d.%m.%y %H:%M:%S"),
    }

    text = texts.render_daily_summary(data)
    markup = _build_daily_keyboard(target_date).as_markup()
    await message.edit_text(text=text, reply_markup=markup)


async def _render_utm(message: Message, session: AsyncSession, page: int):
    text, markup = await _prepare_utm_stats(session, page)
    await message.edit_text(text=text, reply_markup=markup)


@router.callback_query(F.data == "rf|open")
async def open_forecast(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        can_edit = await _resolve_can_edit_ads(session, callback.from_user.id if callback.from_user else None)
        await _render_summary(callback.message, session, can_edit)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] open_forecast error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data == "rf|daily|open")
async def open_daily_forecast(callback: CallbackQuery, session: AsyncSession):
    try:
        today = datetime.now(pytz.timezone("Europe/Moscow")).date()
        await _render_daily_view(callback.message, session, today)
        await callback.answer()
    except Exception as exc:
        logger.error(f"[RF] open_daily_forecast error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data.startswith("rf|date|"))
async def change_daily_forecast_date(callback: CallbackQuery, session: AsyncSession):
    try:
        date_str = callback.data.split("|", 2)[2]
        target_date = (
            datetime.now(pytz.timezone("Europe/Moscow")).date()
            if date_str == "today"
            else date.fromisoformat(date_str)
        )
        await _render_daily_view(callback.message, session, target_date)
        await callback.answer()
    except Exception as exc:
        logger.error(f"[RF] change_daily_forecast_date error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data == "rf|refresh")
async def refresh_forecast(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        can_edit = await _resolve_can_edit_ads(session, callback.from_user.id if callback.from_user else None)
        await _render_summary(callback.message, session, can_edit)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] refresh_forecast error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data == "rf|utm")
async def open_utm(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        await _render_utm(callback.message, session, page=1)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] open_utm error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data.startswith("rf|utm|refresh"))
async def refresh_utm(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        parts = callback.data.split("|")
        page = int(parts[-1]) if len(parts) > 3 else 1
        await _render_utm(callback.message, session, page=page)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] refresh_utm error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data.startswith("rf|utm|page|"))
async def utm_change_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        page_raw = callback.data.split("|", 3)[3]
        page = int(page_raw)
        await _render_utm(callback.message, session, page=page)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] utm_change_page error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data == "rf|utm|export")
async def export_utm_csv(callback: CallbackQuery, session: AsyncSession):
    try:
        buffer = await _build_utm_export(session)
    except ValueError:
        await callback.answer(texts.UTM_EXPORT_NO_DATA, show_alert=True)
        return
    except Exception as exc:
        logger.error(f"[RF] utm_export error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)
        return

    filename = f"utm_stats_{datetime.now(pytz.timezone('Europe/Moscow')).strftime('%Y%m%d')}.zip"
    await callback.answer()
    await callback.message.answer_document(
        BufferedInputFile(buffer.getvalue(), filename=filename),
        caption=texts.UTM_EXPORT_READY,
    )


@router.callback_query(F.data == "rf|noop")
async def utm_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "rf|utm|back")
async def back_from_utm(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        can_edit = await _resolve_can_edit_ads(session, callback.from_user.id if callback.from_user else None)
        await _render_summary(callback.message, session, can_edit)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] back_from_utm error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


async def statistics_menu_hook(**kwargs: Any):
    return {
        "after": settings.STATS_ANCHOR_CALLBACK,
        "button": InlineKeyboardButton(text=texts.BTN_ADMIN_FORECAST, callback_data="rf|admin"),
    }


register_hook("statistics_menu", statistics_menu_hook)

if settings.SHOW_IN_ADMIN_PANEL:
    async def admin_panel_hook(**kwargs: Any):
        admin_role = kwargs.get("admin_role")
        if admin_role and str(admin_role).lower() == "moderator":
            return None
        return {
            "button": InlineKeyboardButton(
                text=texts.BTN_ADMIN_FORECAST,
                callback_data="rf|admin",
            ),
        }

    register_hook("admin_panel", admin_panel_hook)


@router.callback_query(F.data == "rf|admin")
async def admin_open(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        can_edit = await _resolve_can_edit_ads(session, callback.from_user.id if callback.from_user else None)
        await _render_summary(callback.message, session, can_edit)
        await callback.answer()
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF] admin_open error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data == "rf|ads|edit")
async def start_ad_spend_input(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        can_edit = await _resolve_can_edit_ads(session, callback.from_user.id if callback.from_user else None)
        if not can_edit:
            await callback.answer(texts.ADS_FORBIDDEN, show_alert=True)
            return
        await state.set_state(AdSpendForm.amount)
        msg = callback.message
        await state.update_data(
            summary_chat_id=msg.chat.id if msg else None,
            summary_message_id=msg.message_id if msg else None,
            summary_thread_id=getattr(msg, "message_thread_id", None) if msg else None,
        )
        await callback.answer()
        await callback.message.answer(texts.ADS_ENTER_AMOUNT, reply_markup=_ads_cancel_keyboard())
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF][ADS] start error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.callback_query(F.data == "rf|ads|cancel")
async def cancel_ad_spend(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(texts.ADS_CANCELLED, reply_markup=_ads_saved_keyboard())


@router.message(AdSpendForm.amount)
async def process_ad_spend_amount(message: Message, session: AsyncSession, state: FSMContext):
    original = message.text or ""
    raw = original.strip()
    normalized = raw.replace(" ", "").replace(",", ".")
    try:
        amount = float(normalized)
        if amount < 0:
            raise ValueError("negative")
    except Exception:
        logger.warning(f"[RF][ADS] parse error raw={original}")
        await message.answer(texts.ADS_PARSE_ERROR)
        return
    moscow_tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.now(moscow_tz)
    now_utc = now_msk.astimezone(pytz.UTC).replace(tzinfo=None)
    dt_start, _ = await db.get_month_bounds(now_utc)
    try:
        await db.upsert_ad_spend(
            session,
            dt_start.date(),
            amount,
            None,
            message.from_user.id if message.from_user else 0,
        )
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF][ADS] save error: {exc}")
        await message.answer(texts.ERROR)
        return
    await state.clear()
    await message.answer(texts.ADS_SAVED, reply_markup=_ads_saved_keyboard())


@router.callback_query(F.data.startswith("rf|utm|ads|edit|"))
async def start_utm_ad_spend_input(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    try:
        can_edit = await _resolve_can_edit_ads(session, callback.from_user.id if callback.from_user else None)
        if not can_edit:
            await callback.answer(texts.ADS_FORBIDDEN, show_alert=True)
            return
        parts = callback.data.split("|", 4)
        source_code = parts[4] if len(parts) > 4 else ""
        await state.set_state(UTMAdSpendForm.amount)
        msg = callback.message
        await state.update_data(
            utm_source_code=source_code,
            utm_page=_get_utm_page_from_markup(msg),
            utm_chat_id=msg.chat.id if msg else None,
            utm_message_id=msg.message_id if msg else None,
            utm_thread_id=getattr(msg, "message_thread_id", None) if msg else None,
        )
        await callback.answer()
        await callback.message.answer(
            texts.UTM_ADS_ENTER_AMOUNT.format(source_code=source_code),
            reply_markup=_ads_cancel_keyboard(),
        )
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF][UTM][ADS] start error: {exc}")
        await callback.answer(texts.ERROR, show_alert=True)


@router.message(UTMAdSpendForm.amount)
async def process_utm_ad_spend_amount(message: Message, session: AsyncSession, state: FSMContext):
    original = message.text or ""
    raw = original.strip()
    normalized = raw.replace(" ", "").replace(",", ".")
    try:
        amount = float(normalized)
        if amount < 0:
            raise ValueError("negative")
    except Exception:
        logger.warning(f"[RF][UTM][ADS] parse error raw={original}")
        await message.answer(texts.ADS_PARSE_ERROR)
        return

    data = await state.get_data()
    source_code = data.get("utm_source_code") or ""
    page = int(data.get("utm_page") or 1)
    chat_id = data.get("utm_chat_id")
    message_id = data.get("utm_message_id")
    thread_id = data.get("utm_thread_id")

    moscow_tz = pytz.timezone("Europe/Moscow")
    now_msk = datetime.now(moscow_tz)
    now_utc = now_msk.astimezone(pytz.UTC).replace(tzinfo=None)
    dt_start, _ = await db.get_month_bounds(now_utc)

    try:
        await db.upsert_ad_spend_by_source(
            session,
            month_start=dt_start,
            source_code=source_code,
            amount=amount,
            comment=None,
            tg_id=message.from_user.id if message.from_user else 0,
        )
    except Exception as exc:
        await state.clear()
        logger.error(f"[RF][UTM][ADS] save error: {exc}")
        await message.answer(texts.ERROR)
        return

    await state.clear()
    await message.answer(texts.UTM_ADS_SAVED, reply_markup=_ads_saved_keyboard())

    if chat_id and message_id:
        try:
            text, markup = await _prepare_utm_stats(session, page)
            await message.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
        except Exception as exc:
            logger.error(f"[RF][UTM][ADS] refresh error: {exc}")

