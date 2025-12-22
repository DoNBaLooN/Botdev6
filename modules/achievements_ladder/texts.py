from typing import Any, Iterable


TITLE = "🎯 Лестница достижений"
PROGRESS = "Ступени: {steps}, до награды {remain}"
REWARD_CLAIMED = "Награда за {steps} ступеней выдана!"
NOTHING_TO_CLAIM = "Пока нечего забирать"
CAP_BLOCKED = "Превышен лимит наград на этот месяц"
CHANNEL_PROMPT = "Подпишитесь на канал и нажмите 'Проверить канал'"
CHANNEL_BONUS_OK = "Бонус за канал начислен!"
CHANNEL_NOT_JOINED = "Вы не подписаны на канал"
CHANNEL_ALREADY = "Бонус за канал уже был получен"
ANNOUNCE_USER = "🏆 Вы достигли {steps} ступеней!"
WEEKLY_SUMMARY = "За неделю вы набрали {delta} ступеней, всего {steps}"
TOP_TITLE = "🏆 ТОП-{limit}"
REWARDS_TITLE = "🎁 Награды"
BREAKDOWN_TITLE = "📊 Откуда ступени"
BREAKDOWN_TOTAL = "Всего: {steps} {word}"
BREAKDOWN_RAW = "Начислено: {raw} ступеней, коррекция: −{offset}"
BREAKDOWN_NONE = "Данные пока не набраны"

HOWTO_SHORT = (
    "📈 <b>Как набрать шаги:</b>\n"
    "<blockquote>"
    "1️⃣ Подпишитесь на канал и нажмите <b>«Проверить канал»</b> — получите шаги.\n"
    "2️⃣ Заходите в бота каждый день — <b>ежедневные шаги</b> накапливаются.\n"
    "3️⃣ Приглашайте друзей — за каждого <b>+шаги</b>.\n"
    "4️⃣ Оплачивайте подписку или продление — это тоже <b>+шаги</b>.\n"
    "5️⃣ Когда достигнете порога — нажмите <b>«Получить награду»</b> 🎁."
    "</blockquote>"
)

HOWTO_FULL = (
    "🧗 <b>Лестница достижений — ваш путь к наградам!</b>\n\n"
    "<blockquote>"
    "💬 <b>Канал:</b> подпишитесь на наш канал — получите мгновенные шаги, затем нажмите <b>«Проверить канал»</b>.\n\n"
    "📅 <b>Ежедневно:</b> открывайте бота раз в день — копите ежедневные шаги (есть месячный лимит).\n\n"
    "👥 <b>Друзья:</b> делитесь ботом — за приглашённых и их оплаты начисляются шаги.\n\n"
    "💳 <b>Платежи:</b> чем длиннее план (1/3/6/12 мес.), тем больше шагов вы получаете.\n\n"
    "🎁 <b>Награды:</b> достигли порога — жмите <b>«Получить награду»</b> и получите дополнительные дни подписки.\n"
    "</blockquote>\n"
    "💡 <i>Совет:</i> следите за прогрессом — бот напомнит, когда вы будете близко к новой награде! 🚀"
)

def format_top(entries: list[dict[str, int]], limit: int) -> str:
    lines = [TOP_TITLE.format(limit=limit)]
    for idx, item in enumerate(entries, 1):
        mention = f"@{item['username']}" if item.get("username") else str(item["tg_id"])
        steps: int = int(item["steps"])
        lines.append(f"{idx}. {mention} — {steps} {_steps_word(steps)}")
    return "\n".join(lines)


def _steps_word(n: int) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return "ступеней"
    n %= 10
    if n == 1:
        return "ступень"
    if 1 < n < 5:
        return "ступени"
    return "ступеней"


def announce_remain(remain: int) -> str:
    return f"До следующей награды осталось {remain} {_steps_word(remain)}"


def format_rewards(thresholds: Iterable[dict[str, Any]], steps: int, claimed: set[int]) -> str:
    lines = [REWARDS_TITLE]
    thresholds_list = list(thresholds)
    last_index = len(thresholds_list) - 1
    for idx, threshold in enumerate(thresholds_list):
        reward_text = _format_reward(threshold.get("reward", {}))
        step_value = threshold.get("steps", 0)
        if step_value in claimed:
            line = f"🟩 {step_value} — {reward_text}  (получена)"
        elif steps >= step_value:
            line = f"🟨 {step_value} — {reward_text}  (доступно)"
        else:
            remain = step_value - steps
            line = f"◻️ {step_value} — {reward_text} (осталось {remain})"
        if idx == last_index:
            line += "  🏁"
        lines.append(line)
    return "\n".join(lines)


def format_breakdown(data: dict[str, Any]) -> str:
    total_steps = int(data.get("total", 0))
    lines = [BREAKDOWN_TITLE, BREAKDOWN_TOTAL.format(steps=total_steps, word=_steps_word(total_steps))]

    raw_total = data.get("raw_total")
    offset = data.get("offset", {}).get("value", 0)
    if raw_total is None:
        raw_total = total_steps
    if offset:
        lines.append(
            BREAKDOWN_RAW.format(
                raw=_format_steps_value(raw_total),
                offset=_format_steps_value(offset),
            )
        )

    invites = data.get("invites", {})
    lines.append(
        "• Приглашения: +{steps} ({count} чел.)".format(
            steps=_format_steps_value(invites.get("steps", 0)),
            count=invites.get("count", 0),
        )
    )

    self_pay = data.get("self_pay", {})
    lines.append(
        "• Свои оплаты: +{steps}{details}".format(
            steps=_format_steps_value(self_pay.get("steps", 0)),
            details=_format_payment_details(self_pay.get("counts", {})),
        )
    )

    ref_pay = data.get("ref_pay", {})
    lines.append(
        "• Оплаты друзей: +{steps}{details}".format(
            steps=_format_steps_value(ref_pay.get("steps", 0)),
            details=_format_payment_details(ref_pay.get("counts", {})),
        )
    )

    channel = data.get("channel", {})
    channel_suffix = " (получен)" if channel.get("received") else " (не получен)"
    lines.append(
        "• Канал: +{steps}{suffix}".format(
            steps=_format_steps_value(channel.get("steps", 0)),
            suffix=channel_suffix,
        )
    )

    daily = data.get("daily", {})
    lines.append(
        "• Ежедневные визиты: +{steps} ({applied}/{cap} учт., всего {recorded})".format(
            steps=_format_steps_value(daily.get("steps", 0)),
            applied=daily.get("applied_days", 0),
            cap=daily.get("cap", 0),
            recorded=daily.get("recorded_days", 0),
        )
    )

    streak = data.get("streak", {})
    lines.append(
        "• Серии по 7 дней: +{steps} ({bonuses} бонусов)".format(
            steps=_format_steps_value(streak.get("steps", 0)),
            bonuses=streak.get("bonuses", 0),
        )
    )

    if offset:
        lines.append(f"• Коррекция: −{_format_steps_value(offset)}")

    if len(lines) == 2:
        lines.append(BREAKDOWN_NONE)

    return "\n".join(lines)


def _format_reward(reward: dict[str, Any]) -> str:
    value = reward.get("value")
    reward_type = reward.get("type")
    if reward_type == "days" and isinstance(value, int):
        return f"+{value} {_days_word(value)}"
    if value is not None and reward_type:
        return f"+{value} {reward_type}"
    if value is not None:
        return f"+{value}"
    return "+?"


def _days_word(n: int) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return "дней"
    n %= 10
    if n == 1:
        return "день"
    if 1 < n < 5:
        return "дня"
    return "дней"


def _format_steps_value(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num - int(num)) < 1e-9:
        return str(int(num))
    return f"{num:.2f}".rstrip("0").rstrip(".")


def _format_payment_details(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    if "any" in counts:
        return f" ({counts['any']} оплат)"
    parts: list[str] = []
    for key, value in sorted(counts.items(), key=lambda item: int(item[0])):
        parts.append(f"{value}×{key} мес.")
    return f" ({', '.join(parts)})"
