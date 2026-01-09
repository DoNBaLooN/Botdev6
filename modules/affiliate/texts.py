"""Тексты и шаблоны сообщений модуля партнёрской программы."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, Mapping

from . import settings


TITLE = "👥 <b>Партнёрская программа</b>"
INSTRUCTION = (
    "💼 <b>Зарабатывайте вместе с нами!</b>\n"
    "<blockquote>"
    "1️⃣ Приглашайте друзей по своей <b>уникальной ссылке</b> и получайте <b>процент с их покупок</b>.\n"
    "2️⃣ Выводите заработанные средства удобным способом."
    "</blockquote>"
)

# Показываем ссылку в виде кода, чтобы по нажатию она не открывалась,
# а удобно копировалась (долгое нажатие → копировать).
LINK_TITLE = "🔗 <b>Ваша ссылка:</b>\n<code>{link}</code>"

STATS_TITLE = "📊 <b>Ваша статистика</b>"
STATS_LINE = "👥 Приглашено: <b>{invited}</b>"
STATS_BALANCE = "💰 Баланс: <b>{available:.2f} {currency}</b>"
STATS_ON_HOLD = "⏳ В ожидании: <b>{hold:.2f} {currency}</b>"
STATS_METHOD = "🏦 Способ вывода: <b>{method}</b>"
STATS_REQUISITES = "💳 Реквизиты: <b>{masked}</b>"

LEVELS_TITLE = "💎 <b>Ставки по уровням</b>"
LEVEL_LINE = "Уровень {level} — <b>{percent}%</b>"

BTN_WITHDRAW = "💸 Вывести средства"
BTN_INVITE = "📨 Пригласить друзей"
BTN_REQUISITES = "⚙️ Реквизиты"
BTN_BACK = "⬅️ Назад"
BTN_ATTACH_CARD = "➕ Привязать карту (RU)"
BTN_EDIT_CARD = "✏️ Изменить карту"
BTN_DELETE_CARD = "🗑 Удалить карту"
BTN_SAVE_CARD = "💾 Сохранить"
BTN_CANCEL = "⬅️ Назад"
BTN_CARD_BACK = "⬅️ В партнёрку"
BTN_WITHDRAW_SEND = "📤 Отправить заявку"
BTN_WITHDRAW_ALL = "💰 Вывести всё"
BTN_SUPPORT = "📩 Поддержка"
BTN_ADMIN_BACK = "⬅️ В админку"
BTN_ADMIN_FILTER_STATUS = "Статус"
BTN_ADMIN_FILTER_PERIOD = "Период"
BTN_ADMIN_FILTER_TG = "🔍 По tg_id"
BTN_ADMIN_CLEAR_FILTERS = "♻️ Сбросить фильтры"

CARD_HEADER_EMPTY = "⚙️ <b>Реквизиты вывода</b>"
CARD_METHOD_NOT_SET = "Способ вывода: <b>не задан</b>"
CARD_PROMPT_SET = "Вы можете привязать карту для мгновенных выплат."
CARD_METHOD_SET = "Способ: <b>Карта (RU)</b>"
CARD_CURRENT = "Текущая карта: <b>{masked}</b>"
CARD_PROMPT_EDIT = "Вы можете изменить или удалить реквизиты в любой момент."
CARD_PROMPT_ENTER = (
    "Введите номер карты (16–19 цифр).\n"
    "Допустимы только российские карты. Без пробелов и спецсимволов."
)
CARD_INVALID = "❌ Неверный номер карты. Проверьте ввод."
CARD_INVALID_BIN = "❌ Карта должна быть выпущена в РФ."
CARD_SAME_AS_CURRENT = "ℹ️ Эта карта уже сохранена."
CARD_SAVED = "✅ Реквизиты сохранены."
CARD_DELETED = "✅ Реквизиты удалены."
CARD_DELETE_CONFIRM = "Вы уверены, что хотите удалить привязанную карту?"
CARD_DELETE_CANCELLED = "Удаление отменено."
CARD_SAVE_PROMPT = "Сохранить карту <b>{masked}</b>?"
CARD_SAVE_CANCELLED = "Сохранение отменено."


from . import settings

# --- Блок вывода с учётом времени холда ---
if settings.HOLD_DAYS > 0:
    HOLD_NOTE = f" (задержка {settings.HOLD_DAYS} дн. перед выплатой)"
    HOLD_EXPLAIN = f"<i>⏳ Начисленные бонусы становятся доступными через {settings.HOLD_DAYS} день после оплаты.</i>"
else:
    HOLD_NOTE = ""
    HOLD_EXPLAIN = ""

WITHDRAW_HEADER = f"💸 <b>Вывод средств</b>{HOLD_NOTE}"
WITHDRAW_BALANCE = "На вашем партнёрском балансе <b>{available:.2f} {currency}</b>."
WITHDRAW_THRESHOLD = "Вывод доступен от {threshold:.0f}{currency}."
WITHDRAW_PROMPT_AMOUNT = "Укажите сумму для вывода (в {currency})."

# Внизу блока добавляем пояснение о холде, если он включён
def format_withdraw_info(available: Decimal, currency: str) -> str:
    parts = [
        WITHDRAW_HEADER,
        WITHDRAW_BALANCE.format(available=available, currency=currency),
        WITHDRAW_THRESHOLD.format(threshold=settings.MIN_PAYOUT_RUB, currency=currency),
    ]
    if settings.HOLD_DAYS > 0:
        parts.append(HOLD_EXPLAIN)
    return "\n".join(parts)
WITHDRAW_NO_CARD = "❌ Укажите реквизиты перед выводом."
WITHDRAW_INSUFFICIENT = "❌ Недостаточно средств для вывода."\
    " Доступно: {available:.2f}{currency}."
WITHDRAW_PENDING_EXISTS = "❌ У вас уже есть заявка в обработке. Дождитесь решения."
WITHDRAW_CONFIRM = "Отправить заявку на <b>{amount:.2f} {currency}</b>?"
WITHDRAW_CREATED = "🧾 Заявка №<code>{withdraw_id}</code> на <b>{amount:.2f} {currency}</b> создана. Ожидайте подтверждения."
WITHDRAW_RATE_LIMIT = "❌ Слишком часто. Попробуйте позже."

WITHDRAW_USER_SUCCESS = (
    "✅ Выплата по заявке №<code>{withdraw_id}</code> на <b>{amount:.2f} {currency}</b> проведена. "
    "Средства поступят в течение нескольких минут."
)
WITHDRAW_USER_REJECT = (
    "❌ Выплата по заявке №<code>{withdraw_id}</code> не проведена. "
    "Свяжитесь с поддержкой для уточнения деталей."
)

ADMIN_WITHDRAW_TITLE = "🧾 <b>Заявки на вывод партнёрам</b>"
ADMIN_WITHDRAW_DETAIL_TITLE = "🧾 <b>Заявка на вывод</b>"
ADMIN_WITHDRAW_EMPTY = "Заявок не найдено."
ADMIN_WITHDRAW_NOT_FOUND = "Заявка не найдена."
ADMIN_WITHDRAW_CARD = "Карта: {number}"
ADMIN_WITHDRAW_LIST_LINE = "№{id} • {status} • {amount:.2f} {currency} • <code>{tg_id}</code> • {created}"
ADMIN_WITHDRAW_BUTTON = "№{id} • {amount:.2f} {currency} • {status}"
ADMIN_WITHDRAW_LINE = (
    "№{id} • {status}\n"
    "Пользователь: <code>{tg_id}</code>\n"
    "Сумма: {amount:.2f} {currency}\n"
    "Создана: {created}\n"
    "Метод: {method}\n"
    "{card_line}\n"
    "Баланс: доступно {available:.2f} {currency}, в холде {hold:.2f} {currency}\n"
    "Обработал: {admin}\n"
)

ADMIN_PARTNER_STATS_TITLE = "📈 <b>Статистика по партнёрам</b>"
ADMIN_PARTNER_STATS_EMPTY = "Партнёры с активностью пока не найдены."
ADMIN_PARTNER_STATS_LINE = (
    "<code>{tg_id}</code> — 👥 {referrals} • 💰 {total:.2f} {currency}"
    " (доступно {available:.2f} {currency}, холд {hold:.2f} {currency})"
)

ADMIN_STATUS_PENDING = "⏳ В ожидании"
ADMIN_STATUS_PAID = "✅ Выплачено"
ADMIN_STATUS_REJECTED = "❌ Отклонено"
ADMIN_REMINDER = (
    "⏳ Заявка №{id} от <code>{tg_id}</code> на {amount:.2f} {currency} ожидает обработки более {hours} ч."
)

INVITE_MESSAGE = (
    "👥 Делитесь ссылкой и зарабатывайте!\n\n"
    "<code>{link}</code>"
)
INVITE_QR_HINT = "📸 Отсканируйте QR-код ниже, чтобы открыть ссылку."
INVITE_QR_CAPTION = "👥 Ваша пригласительная ссылка:\n<code>{link}</code>"
INVITE_SENT = "Ссылка скопирована. Отправьте друзьям!"

ADMIN_WITHDRAW_NOTIFICATION = (
    "🧾 Новая заявка на вывод №{id}\n"
    "Пользователь: <code>{tg_id}</code> ({username})\n"
    "Сумма: {amount:.2f} {currency}\n"
    "Баланс: доступно {available:.2f} {currency}, в холде {hold:.2f} {currency}\n"
    "Карта: {card_number} ({card_mask})\n"
    "Создана: {created}"
)

ADMIN_WITHDRAW_ALREADY_PROCESSED = "Эта заявка уже обработана."
ADMIN_WITHDRAW_APPROVED = "Заявка #{id} отмечена как выплаченная."
ADMIN_WITHDRAW_REJECTED = "Заявка #{id} отклонена."

USER_THRESHOLD_REMINDER = (
    "💰 На вашем партнёрском балансе достаточно средств ({amount:.2f} {currency}) для вывода. "
    "Оформите заявку в разделе партнёрки."
)
ADMIN_PENDING_REMINDER = (
    "⏳ Есть {count} заявок на вывод, ожидающих решения. Самая старая — №{id} (tg_id {tg_id})."
)

CARD_DELETE_CONFIRMATION = "Подтвердите удаление карты?"


STATUS_TITLES: Mapping[str, str] = {
    "pending": ADMIN_STATUS_PENDING,
    "paid": ADMIN_STATUS_PAID,
    "rejected": ADMIN_STATUS_REJECTED,
}


def format_levels(levels: Iterable[tuple[int, Decimal]]) -> str:
    # Красивые «медали» для первых трёх уровней, дальше — маркеры.
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines: list[str] = []
    for level, pct in levels:
        icon = medal.get(level, "🔹")
        lines.append(f"{icon} " + LEVEL_LINE.format(level=level, percent=int(pct * 100)))
    # основной блок ставок + пример под ним в цитате
    levels_block = "\n".join([LEVELS_TITLE, f"<blockquote>{chr(10).join(lines)}</blockquote>"])
    example_block = '<blockquote><b>Пример:</b> платёж 420₽ → бонус <b>147.0₽</b>.</blockquote>'
    return f"{levels_block}\n{example_block}"


def format_stats(invited: int, available: Decimal, hold: Decimal, method: str, masked: str) -> str:
    lines = [
        STATS_LINE.format(invited=invited),
        STATS_BALANCE.format(available=available, currency=settings.CURRENCY),
        STATS_ON_HOLD.format(hold=hold, currency=settings.CURRENCY),
        STATS_METHOD.format(method=method),
        STATS_REQUISITES.format(masked=masked),
    ]
    stats_block = "\n".join([STATS_TITLE, f"<blockquote>{chr(10).join(lines)}</blockquote>"])
    # дополнительная строка под блоком статистики
    threshold_line = "<i>💸 Вывод доступен от 100₽.</i>"
    return f"{stats_block}\n{threshold_line}"


def format_datetime(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M")


def mask_card_number(number: str) -> str:
    number = number[-4:]
    return f"{settings.CARD_MASK_SYMBOL * 4} {number}" if number else "—"
