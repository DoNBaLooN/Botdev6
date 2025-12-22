"""Text constants for the roulette module."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

from logger import logger

from . import settings
from .models import RouletteSpin


TITLE_MENU = "<b>🎰 Рулетка</b>"

BUTTON_SPIN = "🎰 Крутить ({amount} {currency})"
BUTTON_SPIN_FREE = "🎰 Крутить ({amount} {currency} | +{free_spins} 🎟️)"
BUTTON_SPIN_AGAIN = "🎰 Крутить ещё"
BUTTON_STATS = "📊 Статистика"
BUTTON_PRIZES = "🎁 Призы"
BUTTON_LEADERBOARD = "🏆 Рейтинг"
BUTTON_BONUS = "🎁 Ежедневный бонус"
BUTTON_BACK = "⬅️ Назад"
BUTTON_START = "🎰 Рулетка"
BUTTON_LEADERBOARD_REFRESH = "🔄 Обновить"
BUTTON_MAIN_MENU = "⬅️ В меню"
BUTTON_PROFILE_ENTRY = "🎰 Рулетка / Бонус"
BUTTON_LEADERBOARD_SHORT = "🏆 Топ побед"
BUTTON_PAY_PROMO = "+ Бонусные прокруты"
BUTTON_KEY_MENU = "🎰 Рулетка"
BUTTON_ADMIN_PANEL = "🎰 Рулетка"
BUTTON_NOTIFY_DISABLE = "🔕 Отключить уведомления"
BUTTON_NOTIFY_ENABLE = "🔔 Включить уведомления"

INSUFFICIENT_FUNDS = "Недостаточно средств для ставки."
INSUFFICIENT_FUNDS_PROMPT = "Для использования рулетки пополните баланс."
BUTTON_BALANCE = "💳 Баланс"
MODULE_DISABLED = "Рулетка временно недоступна."
ERROR_MESSAGE = "Произошла ошибка. Попробуйте ещё раз позже."
COOLDOWN_MESSAGE = "Подождите немного перед следующей попыткой."
CONCURRENT_SPIN = "У вас уже запущен спин. Подождите завершения."
DAILY_SPEND_LIMIT = "Дневной лимит ставок исчерпан."
DAILY_WIN_LIMIT = "Дневной лимит выигрышей исчерпан."
BONUS_NOT_AVAILABLE = "Бонус пока недоступен. Попробуйте позже."
BONUS_GRANTED_FREE_SPIN = "Получен бесплатный спин!"
BONUS_GRANTED_COINS = "Начислено {amount} {currency}!"
BONUS_DISABLED = "Ежедневный бонус отключён."

SPIN_PREPARING = "🎰 Подготовка к спину…"
RESULT_TITLE = "<b>🎰 РЕЗУЛЬТАТ</b>"
RESULT_COMMENT_EMPTY = "💔 Пусто… Не расстраивайтесь, удача скоро улыбнётся!"
RESULT_COMMENT_WIN = "✅ Вы выиграли: +{amount} {currency}"
RESULT_COMMENT_JACKPOT = "🏆 Джекпот! +{amount} {currency}"
SPIN_RESULT_TEMPLATE = (
    "Выигрыш: <b>{win}</b> {currency}\n"
    "Баланс: <b>{balance}</b> {currency}\n"
    "Джекпот: <b>{jackpot}</b> {currency}"
)

PRIZES_HEADER = "<b>🎁 Призы рулетки</b>\n"
PRIZES_GROUP_HEADER = "{emoji} <b>{rarity}</b> ({chance}%)"
PRIZE_ITEM = "• {icon} {title} — {amount} ({chance}%)"
PRIZE_ITEM_JACKPOT = "• {icon} {title} — Джекпот ({chance}%)"
PRIZES_GUARANTEE = "Гарантия каждые {base} / VIP каждые {vip} спинов."

STATS_HEADER = "<b>📊 Ваша статистика</b>\n"
STATS_TEMPLATE = (
    "Всего спинов: <b>{spins_total}</b>\n"
    "Выигрышей: <b>{wins_total}</b>\n"
    "Winrate: <b>{winrate}</b>%\n"
    "Сумма выигрышей: <b>{sum_win}</b> {currency}\n"
    "Средний выигрыш: <b>{avg_win}</b> {currency}\n"
    "Крупнейший выигрыш: <b>{best_win}</b> {currency}\n"
    "Последний джекпот: <b>{last_jackpot}</b> {currency}\n"
    "Текущая серия побед: <b>{streak_now}</b>\n"
    "Лучшая серия: <b>{streak_best}</b>\n"
    "Выигрышных дней: <b>{winning_days}</b>\n"
    "VIP: <b>{vip}</b>\n"
    "Гарантия через: <b>{guarantee_left}</b> (≥ {guarantee_min})"
)

LEADERBOARD_ROW = "{place}. <code>{mask}</code> — {amount} {currency}\n"
LEADERBOARD_YOUR_PLACE = "\nВаше место: <b>{place}</b> ({amount} {currency})"
LEADERBOARD_EMPTY = "Пока нет данных для рейтинга."

LEADERBOARD_SCOPE_BUTTON_LABELS = {
    "today": "Сегодня",
    "all_time": "За всё время",
}

LEADERBOARD_SCOPE_TITLE_LABELS = {
    "today": "сегодня",
    "all_time": "за всё время",
}


def leaderboard_title(scope: str, *, limit: int | None = None) -> str:
    descriptor = LEADERBOARD_SCOPE_TITLE_LABELS.get(scope, LEADERBOARD_SCOPE_TITLE_LABELS["all_time"])
    prefix = f"Топ {limit} игроков" if limit else "Топ игроков"
    return f"<b>🏆 {prefix} ({descriptor})</b>"


def leaderboard_scope_button(scope: str, *, active: bool) -> str:
    label = LEADERBOARD_SCOPE_BUTTON_LABELS.get(scope, LEADERBOARD_SCOPE_BUTTON_LABELS["all_time"])
    return f"✅ {label}" if active else label

ANIMATION_DELAY_HINT = "Замедляемся…"

PERIODIC_GUARANTEE = "Следующий спин гарантирует приз!"
PERIODIC_BIG_JACKPOT = "Джекпот уже {jackpot} {currency}!"
PERIODIC_RETURN = "Давно не заходили: приходите за удачей!"
PERIODIC_BONUS_READY = "Доступен ежедневный бонус! Заберите подарок 🎁"
NOTIFY_ENABLED = "✅ Уведомления включены"
NOTIFY_DISABLED = "✅ Уведомления отключены"

ADMIN_TOGGLE_MODULE = "⚙️ Вкл/Выкл модуль"
ADMIN_RESET_GUARANTEE = "♻️ Сброс гарантий"
ADMIN_SET_BASE_JACKPOT = "💰 Изменить BASE_JACKPOT"
ADMIN_FORCE_JACKPOT = "⚡️ Форс-джекпот (DEV)"
ADMIN_LAST_SPINS = "📝 Последние спины"
ADMIN_EXPORT_CSV = "📄 Экспорт CSV"
ADMIN_STATUS_ON = "Включен"
ADMIN_STATUS_OFF = "Отключен"
ADMIN_TOGGLE_RESULT = "Статус модуля: <b>{status}</b>"
ADMIN_PROMPT_BASE = "Введите новое значение BASE_JACKPOT (например, 750.00):"
ADMIN_PROMPT_TG_ID = "Введите TG ID пользователя для сброса гарантии:"
ADMIN_FORCE_DONE = "Джекпот принудительно установлен на базовое значение."
ADMIN_EXPORT_READY = "Готово"
ADMIN_EXPORT_CAPTION = "Экспорт последних спинов рулетки"
ADMIN_INVALID_INPUT = "Некорректный ввод. Попробуйте снова."
ADMIN_RESET_DONE = "Гарантия для пользователя <code>{tg_id}</code> сброшена."
ADMIN_BASE_UPDATED = "BASE_JACKPOT обновлён до {amount}."


def format_slot_box(icons: Iterable[str]) -> str:
    rendered = [str(icon) for icon in icons]
    if not rendered:
        rendered = [" "]
    row = " ".join(rendered).strip()
    if not row:
        row = " "
    width = max(len(row), 1)
    top = f"╔{'═' * width}╗"
    bottom = f"╚{'═' * width}╝"
    return "\n".join((top, row, bottom))


def format_result_box(icons: Sequence[str]) -> str:
    return format_slot_box(icons)


def render_menu_description(
    *,
    jackpot: str,
    bet: str,
    free_spins: int,
    vip_active: bool,
    guarantee_left: int,
    guarantee_threshold: int,
    guarantee_min: str,
    currency: str,
) -> str:
    vip_status = "Активен" if vip_active else "Нет"
    min_label = guarantee_min
    emoji = settings.RARITY_EMOJI.get(guarantee_min)
    if emoji:
        min_label = f"{emoji} {guarantee_min}"
    lines = [
        f"Джекпот: <b>{jackpot}</b> {currency}",
        f"Ставка: <b>{bet}</b> {currency}",
        f"VIP статус: <b>{vip_status}</b>",
        f"Гарантия: <b>{guarantee_left}</b> / {guarantee_threshold} (≥ {min_label})",
        f"Бесплатные спины: <b>{free_spins}</b>",
    ]
    return "\n".join(lines)


def format_rarity_prizes() -> str:
    rows: list[str] = []
    detailed_probability = Decimal("0")
    expected_probability = Decimal("0")
    for rarity in settings.RARITIES:
        name = str(rarity.get("name"))
        weight = Decimal(str(rarity.get("weight", 0)))
        prizes = list(rarity.get("prizes", []))
        if not prizes:
            continue

        is_miss_group = name.strip().lower() == "проигрыш"
        if is_miss_group and not settings.SHOW_MISS_IN_LIST:
            continue

        group_chance = _format_percent(weight)
        rarity_emoji = settings.RARITY_EMOJI.get(name, "⚪️")
        expected_probability += weight

        total_weight = sum(int(prize.get("weight", 1)) for prize in prizes) or 1
        entries: list[dict[str, str]] = []
        max_title = 0
        max_amount = 0
        for prize in prizes:
            prize_weight = Decimal(str(prize.get("weight", 1)))
            chance_value = (weight * prize_weight) / Decimal(total_weight)
            detailed_probability += chance_value
            chance_text = _format_percent(chance_value)
            title = str(prize.get("title"))
            code = str(prize.get("code", "")).upper()
            amount = prize.get("amount")
            if isinstance(amount, str) and amount.upper() == "JACKPOT":
                amount_text = "Джекпот"
                line_template = PRIZE_ITEM_JACKPOT
            else:
                amount_text = f"{_format_amount(amount)} {settings.CURRENCY_EMOJI}"
                line_template = PRIZE_ITEM
            icon = settings.PRIZE_ICONS.get(code, settings.PRIZE_ICONS.get("NONE", "🎁"))
            entries.append(
                {
                    "line_template": line_template,
                    "icon": icon,
                    "title": title,
                    "amount": amount_text,
                    "chance": chance_text,
                }
            )
            max_title = max(max_title, len(title))
            max_amount = max(max_amount, len(amount_text))

        # Заголовок редкости (жирным)
        group_header = f"{rarity_emoji} <b>{name}</b> ({group_chance}%)"

        # Призы в цитате
        prize_lines: list[str] = []
        for entry in entries:
            line = entry["line_template"].format(
                icon=entry["icon"],
                title=entry["title"],
                amount=entry["amount"],
                chance=entry["chance"],
            )
            prize_lines.append(f"> {line}")

        items_block = "\n".join(prize_lines)
        rows.append(f"{group_header}\n{items_block}")

    guarantee_line = PRIZES_GUARANTEE.format(
        base=settings.GUARANTEE_BASE,
        vip=settings.GUARANTEE_VIP,
    )

    summary = "\n\n".join(rows + [guarantee_line])

    if rows:
        header = PRIZES_HEADER.rstrip()
        body = f"{header}\n\n{summary}"
    else:
        body = PRIZES_HEADER + guarantee_line

    if (
        rows
        and detailed_probability
        and expected_probability
        and (detailed_probability - expected_probability).copy_abs() > Decimal("0.5")
    ):
        logger.warning(
            "[Ruletка] Сумма вероятностей призов = %s%% (ожидалось %s%%)",
            detailed_probability,
            expected_probability,
        )
    return body


def render_admin_overview(*, enabled: bool, base_jackpot: str, jackpot: str) -> str:
    status = ADMIN_STATUS_ON if enabled else ADMIN_STATUS_OFF
    return (
        "<b>🎰 Рулетка — админ</b>\n"
        f"Статус: <b>{status}</b>\n"
        f"BASE_JACKPOT: <b>{base_jackpot}</b> {settings.CURRENCY_EMOJI}\n"
        f"Текущий джекпот: <b>{jackpot}</b> {settings.CURRENCY_EMOJI}"
    )


def render_admin_last_spins(spins: Sequence[RouletteSpin], *, currency: str) -> str:
    if not spins:
        return "Пока нет спинов."
    lines = ["<b>📝 Последние спины</b>"]
    for spin in spins:
        lines.append(
            " • "
            + f"<code>{spin.tg_id}</code> — {spin.rarity} ({spin.prize_code or '—'})"
            + f" — {_format_amount(spin.win)} {currency}"
            + f" — {spin.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    return "\n".join(lines)


def _format_amount(value: object) -> str:
    dec = Decimal(str(value or 0))
    dec = dec.quantize(Decimal("0.01"))
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_percent(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
