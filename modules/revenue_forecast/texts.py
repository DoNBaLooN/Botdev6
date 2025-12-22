"""User-visible texts for revenue forecast module."""

BTN_FINANCE = "Финансы"
BTN_REFRESH = "🔄 Обновить"
BTN_BACK = "⬅️ Назад"
BTN_EDIT_AD_SPEND = "✏️ Ввести расходы на рекламу"
BTN_TO_STATS = "📈 К статистике"
BTN_UTM_STATS = "🏷️ Общая UTM-статистика"
BTN_DAILY_FORECAST = "📆 Прогноз по дням"
BTN_UTM_EDIT_AD_SPEND = "✏️ Расход"
BTN_UTM_EXPORT = "📥 Выгрузить CSV"

TITLE = "<b>📈 Финансовая статистика</b>"
CUR_MONTH = "📅 <b>Текущий месяц</b>"
DETAILS = "📊 <b>Детали</b>"
DETAILS_PLAN = "📊 <b>План на начало месяца — детализация</b>"
DETAILS_REMAIN = "📊 <b>Остаток на сегодня — детализация</b>"
RETENTION_TITLE = "🧲 <b>Удержание и отток</b>"

ADS_TITLE = "📢 <b>Реклама и эффективность</b>"
ADS_SPEND = "├ 📊 Расход за месяц: <b>{amount}</b>"
ADS_NEW_CLIENTS = "├ 👥 Новые клиенты: <b>{count}</b>"
ADS_NEW_REVENUE = "├ 💰 Выручка от новых клиентов: <b>{amount}</b>"
ADS_CAC = "├ CAC: <b>{value}</b>"
ADS_ROI = "└ ROI: <b>{value}</b>"

ADS_BTN_CANCEL = "↩️ Отмена"
ADS_ENTER_AMOUNT = "Введи сумму расходов на рекламу за месяц (в рублях). Можно использовать точку или запятую."
ADS_PARSE_ERROR = "Не удалось распознать сумму. Введи число, например 12345.67"
ADS_SAVED = "Расходы на рекламу сохранены."
ADS_FORBIDDEN = "Недостаточно прав для изменения расходов."
ADS_CANCELLED = "Ввод расходов отменён."
UTM_ADS_ENTER_AMOUNT = "Введите сумму расходов для метки {source_code}"
UTM_ADS_SAVED = "Расход сохранён"

ADMIN_TITLE = "<b>📈 Прогноз выручки</b>"
BTN_ADMIN_FORECAST = "💰 Прогноз выручки"
ADMIN_META = "Диагностика"
BTN_ADMIN_SETTINGS = "⚙️ Настройки"
BTN_EXPORT = "📤 Экспорт CSV"
BTN_RECALC = "🔄 Пересчитать"

ERROR = "Статистика временно недоступна"

UTM_TITLE = "<b>🏷️ Аналитика по UTM-меткам</b>"
UTM_PAGE = "📑 Страница {page}/{total}"
UTM_UPDATED = "⏱️ Обновлено: <b>{ts}</b>"
UTM_NO_DATA = "🚫 Активных UTM-меток не найдено."
UTM_ENTRY_HEADER = "📌 <b>Метка: {name}</b>"

UTM_REVENUE_TITLE   = "💰 Выручка"
UTM_PREVIOUS = "├ 📉 Прошлый месяц: <b>{amount}</b>"
UTM_CURRENT = "├ 📈 Текущий месяц: <b>{amount}</b>"
UTM_GROWTH = "└ 📊 Прирост: <b>{value}</b>"

UTM_RENEWALS_TITLE = "🔁 Продлений за весь период"
UTM_RENEWALS_VALUE = "└ 💵 Сумма: <b>{amount}</b>"

UTM_PURCHASES_TITLE = "💳 Всего за весь период"
UTM_PURCHASES_COUNT = "├ 🛒 Покупки: <b>{count}</b>"
UTM_PURCHASES_SUM = "└ 💸 Сумма: <b>{amount}</b>"

UTM_ADS_TITLE = "📢 Реклама и эффективность"
UTM_ADS_SPEND = "├ 📊 Расход за месяц: <b>{amount}</b>"
UTM_ADS_NEW_CLIENTS = "├ 👥 Новые клиенты: <b>{count}</b>"
UTM_ADS_NEW_REVENUE = "├ 💰 Выручка от новых клиентов: <b>{amount}</b>"
UTM_ADS_CAC = "├ CAC: <b>{value}</b>"
UTM_ADS_ROI = "└ ROI: <b>{value}</b>"
UTM_EXPORT_READY = "ZIP с CSV по UTM-меткам готов."
UTM_EXPORT_NO_DATA = "Нет UTM-меток для выгрузки."

DAILY_TITLE = "<b>📆 Прогноз на {date}</b>"
DAILY_DETAILS = "📊 <b>Истекает в выбранный день</b>"

def _render_details(by_plans: dict) -> list[str]:
    lines = [DETAILS]
    items = []
    for name, d in (by_plans or {}).items():
        items.append((
            int(d.get("period_months") or 999),
            str(name or "").lower(),
            str(name or ""),
            int(d.get("count", 0)),
            float(d.get("price", 0.0)),
        ))
    items.sort(key=lambda x: (x[0], x[1]))
    if not items:
        lines.append("└ —")
        return lines
    for i, (_m, _key, name, cnt, price) in enumerate(items):
        prefix = "└" if i == len(items) - 1 else "├"
        total = float(cnt) * float(price)
        lines.append(f"{prefix} {name}: <b>{cnt} × {price:.2f} ₽ = {total:.2f} ₽</b>")
    return lines


def _render_details_with_heading(by_plans: dict, heading: str) -> list[str]:
    lines: list[str] = []
    if heading:
        lines.append(heading)
    items = []
    for name, d in (by_plans or {}).items():
        items.append((
            int(d.get("period_months") or 999),
            str(name or "").lower(),
            str(name or ""),
            int(d.get("count", 0)),
            float(d.get("price", 0.0)),
        ))
    items.sort(key=lambda x: (x[0], x[1]))
    if not items:
        lines.append("└ —")
        return lines
    for i, (_m, _key, name, cnt, price) in enumerate(items):
        prefix = "└" if i == len(items) - 1 else "├"
        total = float(cnt) * float(price)
        lines.append(f"{prefix} {name}: <b>{cnt} × {price:.2f} ₽ = {total:.2f} ₽</b>")
    return lines


def render_summary(data: dict) -> str:
    bp_current  = data.get("by_plans_current", {})
    top_lines = [
        f"└ 🎯 План на начало месяца: <b>{data.get('plan_baseline', 0.0):.2f} ₽</b>",
        f"└ 💰 Ожидаемые продления: <b>{data.get('forecast', 0.0):.2f} ₽</b>",
        f"└ ✅ Факт: <b>{data.get('received', 0.0):.2f} ₽</b>",
        (
            f"└ 📏 Выполнено: <b>{data.get('plan_completion_pct'):.1f}%</b>"
            if data.get('plan_completion_pct') is not None
            else "└ 📏 Выполнено: <b>—</b>"
        ),
    ]
    remain_details_lines = _render_details_with_heading(bp_current, "")
    metrics = data.get("metrics") or {}
    metrics_lines = [
        f"├ 💳 Средний чек: <b>{metrics.get('avg_check', 0.0):.2f} ₽</b>",
        f"├ 📦 Оплат за месяц: <b>{metrics.get('paid_count', 0)}</b>",
        f"├ 👥 Активные пользователи: <b>{metrics.get('active_users', 0)}</b>",
        f"├ 🔑 Активных оплаченных ключей: <b>{metrics.get('active_paid_keys', 0)}</b>",
        f"├ 📊 ARPU: <b>{metrics.get('arpu', 0.0):.2f} ₽</b>",
        f"└ 🔁 MRR (активная база): <b>{metrics.get('mrr_active', 0.0):.2f} ₽/мес</b>",
    ]
    ads_data = data.get("ads")
    if ads_data is not None:
        def _fmt_money(val: float) -> str:
            return "0 ₽" if abs(val) < 0.005 else f"{val:.2f} ₽"

        spend = _fmt_money(float(ads_data.get("spend", 0.0)))
        new_clients = int(ads_data.get("new_clients", 0))
        new_revenue = _fmt_money(float(ads_data.get("new_revenue", 0.0)))
        cac_val = ads_data.get("cac")
        roi_val = ads_data.get("roi")
        cac = f"{cac_val:.2f} ₽" if cac_val is not None else "—"
        roi = f"{roi_val:.1f}%" if roi_val is not None else "—"
        ads_lines = [
            ADS_SPEND.format(amount=spend),
            ADS_NEW_CLIENTS.format(count=new_clients),
            ADS_NEW_REVENUE.format(amount=new_revenue),
            ADS_CAC.format(value=cac),
            ADS_ROI.format(value=roi),
        ]
    else:
        ads_lines = None
    ret_lines = [
        (f"├ 🧲 Retention: <b>{ (metrics.get('retention_rate')*100):.1f}%</b>"
         if metrics.get('retention_rate') is not None else "├ 🧲 Retention: <b>—</b>"),
        (f"├ 💔 Churn: <b>{ (metrics.get('churn_rate')*100):.1f}%</b>"
         if metrics.get('churn_rate') is not None else "├ 💔 Churn: <b>—</b>"),
        f"├ ✅ Продлили: <b>{metrics.get('renewed_count', 0)}</b>",
        f"├ ⏳ Ещё не продлили: <b>{metrics.get('not_renewed_yet', 0)}</b>",
    ]
    def _blockquote(lines: list[str]) -> str:
        compact = [ln for ln in lines if ln and ln.strip()]
        return "<blockquote>" + "\n".join(compact) + "</blockquote>"

    parts = []
    parts.append(TITLE)
    parts.append("")
    parts.append("📅 <b>Текущий месяц</b>")
    parts.append(_blockquote(top_lines))
    parts.append("")
    parts.append(DETAILS_REMAIN)
    parts.append(_blockquote(remain_details_lines))
    if ads_lines:
        parts.append("")
        parts.append(ADS_TITLE)
        parts.append(_blockquote(ads_lines))
        parts.append("")
    parts.append("📐 <b>Метрики</b>")
    parts.append(_blockquote(metrics_lines))
    parts.append("")
    parts.append(RETENTION_TITLE)
    parts.append(_blockquote(ret_lines))
    out: list[str] = []
    last_blank = False
    for p in parts:
        if p == "":
            if not last_blank:
                out.append(p)
            last_blank = True
        else:
            out.append(p)
            last_blank = False
    upd = data.get("updated_human_msk")
    if upd:
        out.append("")
        out.append(f"⏱️ <i>Последнее обновление:</i> <code>{upd}</code>")
    return "\n".join(out)



def render_utm_stats(data: dict) -> str:
    items = data.get("items", [])
    updated = data.get("updated_human_msk")
    page = data.get("page")
    total_pages = data.get("total_pages")

    def _fmt_money(value: float) -> str:
        return f"{value:,.2f} ₽".replace(",", " ")

    def _blockquote(lines: list[str]) -> str:
        compact = [ln for ln in lines if ln and ln.strip()]
        return "<blockquote>" + "\n".join(compact) + "</blockquote>"

    parts: list[str] = []
    parts.append(UTM_TITLE)
    if total_pages and total_pages > 1 and page:
        parts.append(UTM_PAGE.format(page=page, total=total_pages))
    parts.append("")

    if not items:
        parts.append(UTM_NO_DATA)
    else:
        for entry in items:
            parts.append(UTM_ENTRY_HEADER.format(name=entry.get("title") or entry.get("code")))

            growth_pct = entry.get("growth_pct")
            growth_inf = entry.get("growth_infinite")
            if growth_pct is None and growth_inf:
                growth_str = "∞"
            elif growth_pct is None:
                growth_str = "—"
            else:
                growth_str = f"{growth_pct:+.1f}%"

            lines_all: list[str] = []
            lines_all.append(UTM_REVENUE_TITLE)
            lines_all.extend([
                UTM_PREVIOUS.format(amount=_fmt_money(entry.get("previous", 0.0))),
                UTM_CURRENT.format(amount=_fmt_money(entry.get("current", 0.0))),
                UTM_GROWTH.format(value=growth_str),
                "",  
            ])

            lines_all.append(UTM_RENEWALS_TITLE)
            lines_all.append(
                UTM_RENEWALS_VALUE.format(amount=_fmt_money(entry.get("renewals", 0.0)))
            )
            lines_all.append("")
            lines_all.append(UTM_PURCHASES_TITLE)
            lines_all.extend([
                UTM_PURCHASES_COUNT.format(count=int(entry.get("payments", 0))),
                UTM_PURCHASES_SUM.format(amount=_fmt_money(entry.get("total_amount", 0.0))),
            ])

            ads_spend_val = float(entry.get("ad_spend", 0.0))
            if (
                ads_spend_val > 0
                or int(entry.get("new_clients", 0)) > 0
                or float(entry.get("new_revenue", 0.0)) > 0
            ):
                ads_cac = entry.get("cac")
                ads_roi = entry.get("roi")
                def _fmt_cac(value: float | None) -> str:
                    return "—" if value is None else _fmt_money(value)

                def _fmt_roi(value: float | None) -> str:
                    return "—" if value is None else f"{value:.1f}%"

                lines_all.append("")
                lines_all.append(UTM_ADS_TITLE)
                lines_all.extend([
                    UTM_ADS_SPEND.format(amount=_fmt_money(ads_spend_val)),
                    UTM_ADS_NEW_CLIENTS.format(count=int(entry.get("new_clients", 0))),
                    UTM_ADS_NEW_REVENUE.format(amount=_fmt_money(entry.get("new_revenue", 0.0))),
                    UTM_ADS_CAC.format(value=_fmt_cac(ads_cac)),
                    UTM_ADS_ROI.format(value=_fmt_roi(ads_roi)),
                ])

            parts.append(_blockquote(lines_all))
            parts.append("")

    if updated:
        parts.append(f"⏱️ <i>Последнее обновление:</i> <code>{updated}</code>")
    out: list[str] = []
    last_blank = False
    for p in parts:
        if p == "":
            if not last_blank:
                out.append(p)
            last_blank = True
        else:
            out.append(p)
            last_blank = False

    return "\n".join(out)


def render_daily_summary(data: dict) -> str:
    details = data.get("details", {})
    updated = data.get("updated_human_msk")

    def _blockquote(lines: list[str]) -> str:
        compact = [ln for ln in lines if ln and ln.strip()]
        return "<blockquote>" + "\n".join(compact) + "</blockquote>"

    parts: list[str] = []
    parts.append(DAILY_TITLE.format(date=data.get("date_str", "")))
    parts.append("")
    parts.append(DAILY_DETAILS)
    parts.append(_blockquote(_render_details(details)))

    if updated:
        parts.append("")
        parts.append(f"⏱️ <i>Последнее обновление:</i> <code>{updated}</code>")

    out: list[str] = []
    last_blank = False
    for p in parts:
        if p == "":
            if not last_blank:
                out.append(p)
            last_blank = True
        else:
            out.append(p)
            last_blank = False

    return "\n".join(out)
