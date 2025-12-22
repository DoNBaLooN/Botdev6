
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict

import sqlalchemy

from sqlalchemy import (
    Table,
    func,
    select,
    case,
    cast,
    BigInteger,
    DateTime,
    literal,
    text,
    and_,
    not_,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from logger import logger

from . import settings
from .models import AdSpend, AdSpendSource


try:  
    from database.models import (
        Key as KeyModel,
        Payment as PaymentModel,
        Tariff as PlanModel,
        TrackingSource as TrackingSourceModel,
        User as UserModel,
    )
except Exception:
    KeyModel = PlanModel = PaymentModel = None
    TrackingSourceModel = UserModel = None


async def get_ad_spend(session: AsyncSession, month_start: date | datetime) -> float:
    if isinstance(month_start, datetime):
        month_dt = month_start.date()
    else:
        month_dt = month_start
    stmt = select(func.coalesce(func.sum(AdSpend.amount_rub), 0.0)).where(AdSpend.month_start == month_dt)
    result = await session.execute(stmt)
    amount = result.scalar_one_or_none()
    return float(amount or 0.0)


async def upsert_ad_spend(
    session: AsyncSession,
    month_start: date | datetime,
    amount: float,
    comment: str | None,
    tg_id: int,
) -> None:
    if isinstance(month_start, datetime):
        month_dt = month_start.date()
    else:
        month_dt = month_start

    stmt = (
        insert(AdSpend)
        .values(
            month_start=month_dt,
            amount_rub=float(amount),
            comment=comment or None,
            created_by=int(tg_id),
            updated_at=datetime.utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[AdSpend.month_start],
            set_={
                "amount_rub": float(amount),
                "comment": comment or None,
                "created_by": int(tg_id),
                "updated_at": datetime.utcnow(),
            },
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info("[RF][ADS] upsert amount=%s month=%s by=%s", float(amount), month_dt, tg_id)


async def get_ad_spend_by_sources(session: AsyncSession, month_start: date | datetime) -> dict[str, float]:
    if isinstance(month_start, datetime):
        month_dt = month_start.date()
    else:
        month_dt = month_start
    stmt = (
        select(AdSpendSource.source_code, func.coalesce(func.sum(AdSpendSource.amount_rub), 0.0))
        .where(AdSpendSource.month_start == month_dt)
        .group_by(AdSpendSource.source_code)
    )
    rows = await session.execute(stmt)
    return {str(code or ""): float(amount or 0.0) for code, amount in rows.all()}


async def get_ad_spend_by_source_all(session: AsyncSession) -> dict[str, dict[date, float]]:
    stmt = (
        select(AdSpendSource.source_code, AdSpendSource.month_start, func.coalesce(func.sum(AdSpendSource.amount_rub), 0.0))
        .group_by(AdSpendSource.source_code, AdSpendSource.month_start)
    )
    rows = await session.execute(stmt)
    data: dict[str, dict[date, float]] = {}
    for source_code, month_start, amount in rows.all():
        code = str(source_code or "")
        month = month_start if isinstance(month_start, date) else None
        if not month:
            continue
        data.setdefault(code, {})[month] = float(amount or 0.0)
    return data


async def upsert_ad_spend_by_source(
    session: AsyncSession,
    month_start: date | datetime,
    source_code: str,
    amount: float,
    comment: str | None,
    tg_id: int,
) -> None:
    if isinstance(month_start, datetime):
        month_dt = month_start.date()
    else:
        month_dt = month_start

    stmt = (
        insert(AdSpendSource)
        .values(
            month_start=month_dt,
            source_code=str(source_code),
            amount_rub=float(amount),
            comment=comment or None,
            created_by=int(tg_id),
            updated_at=datetime.utcnow(),
        )
        .on_conflict_do_update(
            index_elements=[AdSpendSource.month_start, AdSpendSource.source_code],
            set_={
                "amount_rub": float(amount),
                "comment": comment or None,
                "created_by": int(tg_id),
                "updated_at": datetime.utcnow(),
            },
        )
    )
    await session.execute(stmt)
    await session.commit()
    logger.info(
        "[RF][ADS][UTM] upsert amount=%s month=%s source=%s by=%s",
        float(amount),
        month_dt,
        source_code,
        tg_id,
    )


async def get_new_clients_and_revenue(
    session: AsyncSession,
    dt_start: datetime,
    dt_end: datetime,
) -> tuple[int, float]:
    _, _, payment_model = await _get_models(session)
    tg_col = payment_model.c.tg_id if isinstance(payment_model, Table) else payment_model.tg_id
    status_col = payment_model.c.status if isinstance(payment_model, Table) else payment_model.status
    created_col = (
        payment_model.c.created_at if isinstance(payment_model, Table) else payment_model.created_at
    )
    amount_col = payment_model.c.amount if isinstance(payment_model, Table) else payment_model.amount

    first_payments = (
        select(
            tg_col.label("tg_id"),
            func.min(created_col).label("first_paid_at"),
        )
        .where(status_col == "success")
        .group_by(tg_col)
        .subquery("first_payments")
    )

    new_clients_subq = (
        select(first_payments.c.tg_id)
        .where(first_payments.c.first_paid_at >= dt_start, first_payments.c.first_paid_at < dt_end)
        .subquery("new_clients")
    )

    count_stmt = select(func.count()).select_from(new_clients_subq)
    new_clients = int((await session.execute(count_stmt)).scalar() or 0)
    if new_clients == 0:
        return 0, 0.0

    revenue_stmt = (
        select(func.coalesce(func.sum(amount_col), 0.0))
        .where(
            status_col == "success",
            created_col >= dt_start,
            created_col < dt_end,
            tg_col.in_(select(new_clients_subq.c.tg_id)),
        )
    )
    revenue = float((await session.execute(revenue_stmt)).scalar() or 0.0)
    return new_clients, revenue


async def estimate_auto_renewal_probs(
    session: AsyncSession,
    months_back: int = 3,
    grace_days: int = 0,
    flags: Any = settings,
) -> Dict[str, float]:
    sql = """
    WITH months AS (
      SELECT
        date_trunc('month', (now() AT TIME ZONE 'UTC')) - (s.i * INTERVAL '1 month') AS m_start_utc,
        date_trunc('month', (now() AT TIME ZONE 'UTC')) - ((s.i - 1) * INTERVAL '1 month') AS m_end_utc
      FROM generate_series(1, :months_back) AS s(i)
    ), months_ms AS (
      SELECT
        m_start_utc,
        m_end_utc,
        (EXTRACT(EPOCH FROM m_start_utc)*1000)::bigint AS start_ms,
        (EXTRACT(EPOCH FROM m_end_utc)*1000)::bigint   AS end_ms
      FROM months
    ), plans AS (
      SELECT
        t.id,
        t.group_code,
        COALESCE(t.duration_days, 30) AS duration_days,
        (COALESCE(t.duration_days,30)::bigint * 86400000::bigint) AS dur_ms
      FROM tariffs t
    ), base AS (
      SELECT
        k.client_id,
        k.expiry_time,
        COALESCE(k.is_frozen, false) AS is_frozen,
        p.group_code,
        p.duration_days,
        (k.expiry_time - p.dur_ms) AS prev_ms
      FROM keys k
      JOIN plans p ON p.id = k.tariff_id
    ), filtered AS (
      SELECT
        b.client_id, b.expiry_time, b.is_frozen, b.group_code, b.duration_days,
        b.prev_ms, mm.start_ms, mm.end_ms
      FROM base b
      JOIN months_ms mm
        ON b.prev_ms >= mm.start_ms AND b.prev_ms < mm.end_ms
    ), prepared AS (
      SELECT
        CASE
          WHEN duration_days BETWEEN 25 AND 40  THEN '1m'
          WHEN duration_days BETWEEN 80 AND 100 THEN '3m'
          WHEN duration_days BETWEEN 360 AND 390 THEN '12m'
          ELSE 'other'
        END AS bucket,
        expiry_time, is_frozen, group_code, start_ms, end_ms
      FROM filtered
    )
    SELECT
      bucket,
      COUNT(*)::bigint                                   AS cohort,
      COUNT(*) FILTER (WHERE expiry_time >= end_ms + (:grace_ms)::bigint)::bigint AS renewed
    FROM prepared
    WHERE (:skip_frozen)::boolean IS FALSE OR is_frozen IS FALSE
      AND (
           (:exclude_trials)::boolean IS FALSE
           OR (group_code IS DISTINCT FROM 'trial')
          )
    GROUP BY bucket;
    """
    params = {
        "months_back": int(months_back),
        "grace_ms": int(grace_days) * 86400000,
        "skip_frozen": bool(getattr(flags, "SKIP_FROZEN", False)),
        "exclude_trials": bool(getattr(flags, "EXCLUDE_TRIALS", False)),
    }
    rows = (await session.execute(text(sql), params)).all()

    result: Dict[str, float] = {}
    totals = {"1m": (0,0), "3m": (0,0), "12m": (0,0), "other": (0,0)}
    for bucket, cohort, renewed in rows:
        c = int(cohort or 0)
        r = int(renewed or 0)
        if bucket not in totals:
            totals[bucket] = (0,0)
        C,R = totals[bucket]
        totals[bucket] = (C + c, R + r)
    for b, (C, R) in totals.items():
        if C > 0:
            p = (R + 1) / (C + 2)
        else:
            p = 1.0 
        result[b] = max(0.0, min(1.0, float(p)))
    return result


async def get_recognized_revenue_accrual(
    session: AsyncSession,
    dt_start: datetime,
    dt_now: datetime,
    flags: Any,
) -> dict[str, Any]:
    key_model, plan_model, _ = await _get_models(session)

    start_ms = int(dt_start.timestamp() * 1000)
    now_ms   = int(dt_now.timestamp()   * 1000)

    dur_ms = (func.coalesce(
        (plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days),
        30
    ).cast(BigInteger) * literal(86400000, type_=BigInteger))

    prev_expiry_ms = (
        (key_model.c.expiry_time if isinstance(key_model, Table) else key_model.expiry_time)
        - dur_ms
    )

    cols = {
        "id": (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
        "name": (plan_model.c.name if isinstance(plan_model, Table) else plan_model.name),
        "group_code": (plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code),
        "price": (plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub),
        "dur": (plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days),
        "client": (key_model.c.client_id if isinstance(key_model, Table) else key_model.client_id),
        "frozen": (key_model.c.is_frozen if isinstance(key_model, Table) else key_model.is_frozen),
    }

    stmt = (
        select(
            cols["id"], cols["name"], cols["group_code"],
            func.count(cols["client"]),
            cols["price"], cols["dur"],
        )
        .join(plan_model, (key_model.c.tariff_id if isinstance(key_model, Table) else key_model.tariff_id) == cols["id"])
        .where(prev_expiry_ms >= start_ms, prev_expiry_ms < now_ms)
    )

    if getattr(flags, "SKIP_FROZEN", False):
        stmt = stmt.where(cols["frozen"].is_(False))

    if getattr(flags, "EXCLUDE_TRIALS", False):
        price_col = cols["price"]
        gc_col    = cols["group_code"]
        stmt = stmt.where(~((gc_col == "trial") | (func.coalesce(price_col, 0) == 0)))

    stmt = stmt.group_by(cols["id"], cols["name"], cols["group_code"], cols["price"], cols["dur"])
    res = await session.execute(stmt)

    total = 0.0
    by_plans: dict[str, dict[str, Any]] = {}
    for _id, name, gcode, cnt, price, dur in res:
        cnt = int(cnt or 0); price = float(price or 0.0)
        s = cnt * price
        total += s
        by_plans[str(name)] = {
            "count": cnt,
            "price": price,
            "sum": s,
            "period_months": round((dur or 0) / 30) if dur else None,
            "group_code": gcode,
        }
    return {"total": total, "by_plans": by_plans}

async def get_month_bounds(now_utc: datetime) -> tuple[datetime, datetime]:
    start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def get_utm_stats(
    session: AsyncSession,
    current_start: datetime,
    current_end: datetime,
    previous_start: datetime,
    previous_end: datetime,
) -> list[dict[str, Any]]:
    if TrackingSourceModel is None or UserModel is None:
        raise RuntimeError("TrackingSource or User model is unavailable")

    _, _, Payment = await _get_models(session)

    payment_table = Payment if isinstance(Payment, Table) else Payment.__table__
    user_table = (
        UserModel
        if isinstance(UserModel, Table)
        else getattr(UserModel, "__table__", None)
    )
    source_table = (
        TrackingSourceModel
        if isinstance(TrackingSourceModel, Table)
        else getattr(TrackingSourceModel, "__table__", None)
    )

    if user_table is None or source_table is None:
        raise RuntimeError("Failed to resolve tables for UTM analytics")

    pay_tg = payment_table.c.tg_id
    pay_amount = payment_table.c.amount
    pay_status = payment_table.c.status
    pay_created = payment_table.c.created_at
    pay_system = payment_table.c.payment_system

    users_tg = user_table.c.tg_id
    users_source = user_table.c.source_code

    excluded_systems = ("coupon", "referral", "cashback")

    source_alias = source_table.alias("utm_src")

    payments_with_source = (
        select(
            source_alias.c.code.label("source_code"),
            source_alias.c.name.label("source_name"),
            source_alias.c.created_at.label("source_created_at"),
            pay_tg.label("tg_id"),
            pay_amount.label("amount"),
            pay_created.label("payment_created_at"),
            func.row_number()
            .over(
                partition_by=(source_alias.c.code, pay_tg),
                order_by=pay_created,
            )
            .label("rn"),
        )
        .select_from(
            payment_table.join(user_table, pay_tg == users_tg).join(
                source_alias, users_source == source_alias.c.code
            )
        )
        .where(
            pay_status == "success",
            users_source.is_not(None),
            not_(pay_system.in_(excluded_systems)),
            pay_created >= source_alias.c.created_at,
            source_alias.c.type == "utm",
        )
    ).subquery("payments_with_source")

    prev_sum = func.coalesce(
        func.sum(
            case(
                (
                    and_(
                        payments_with_source.c.payment_created_at >= previous_start,
                        payments_with_source.c.payment_created_at < previous_end,
                        payments_with_source.c.rn == 1,
                    ),
                    payments_with_source.c.amount,
                ),
                else_=0.0,
            )
        ),
        0.0,
    )

    curr_sum = func.coalesce(
        func.sum(
            case(
                (
                    and_(
                        payments_with_source.c.payment_created_at >= current_start,
                        payments_with_source.c.payment_created_at < current_end,
                        payments_with_source.c.rn == 1,
                    ),
                    payments_with_source.c.amount,
                ),
                else_=0.0,
            )
        ),
        0.0,
    )

    renewals_sum = func.coalesce(
        func.sum(
            case(
                (payments_with_source.c.rn > 1, payments_with_source.c.amount),
                else_=0.0,
            )
        ),
        0.0,
    )

    total_unique_payers = func.coalesce(
        func.count(func.distinct(payments_with_source.c.tg_id)),
        0,
    )

    new_clients_count = func.count(
        func.distinct(
            case(
                (
                    and_(
                        payments_with_source.c.payment_created_at >= current_start,
                        payments_with_source.c.payment_created_at < current_end,
                        payments_with_source.c.rn == 1,
                    ),
                    payments_with_source.c.tg_id,
                ),
                else_=None,
            )
        )
    )

    new_revenue_sum = func.coalesce(
        func.sum(
            case(
                (
                    and_(
                        payments_with_source.c.payment_created_at >= current_start,
                        payments_with_source.c.payment_created_at < current_end,
                        payments_with_source.c.rn == 1,
                    ),
                    payments_with_source.c.amount,
                ),
                else_=0.0,
            )
        ),
        0.0,
    )

    lifetime_total_amount = func.coalesce(
        func.sum(payments_with_source.c.amount),
        0.0,
    )

    query = (
        select(
            source_table.c.code.label("code"),
            func.coalesce(source_table.c.name, source_table.c.code).label("title"),
            prev_sum.label("previous"),
            curr_sum.label("current"),
            renewals_sum.label("renewals"),
            total_unique_payers.label("payments"),
            lifetime_total_amount.label("total_amount"),
            new_clients_count.label("new_clients"),
            new_revenue_sum.label("new_revenue"),
        )
        .select_from(
            source_table.outerjoin(
                payments_with_source,
                payments_with_source.c.source_code == source_table.c.code,
            )
        )
        .where(source_table.c.type == "utm")
        .group_by(source_table.c.code, source_table.c.name)
        .order_by(source_table.c.code)
    )

    result = await session.execute(query)
    rows = result.all()

    spend_map = await get_ad_spend_by_sources(session, current_start.date())

    stats: list[dict[str, Any]] = []
    for (
        code,
        title,
        previous,
        current,
        renewals,
        payments,
        total_amount,
        new_clients,
        new_revenue,
    ) in rows:
        source_code = str(code or "")
        spend_amount = float(spend_map.get(source_code, 0.0))
        new_clients_val = int(new_clients or 0)
        new_revenue_val = float(new_revenue or 0.0)
        cac = (spend_amount / new_clients_val) if (spend_amount > 0 and new_clients_val > 0) else None
        roi = ((new_revenue_val - spend_amount) / spend_amount * 100.0) if spend_amount > 0 else None
        stats.append(
            {
                "code": source_code,
                "title": str(title or code or ""),
                "previous": float(previous or 0.0),
                "current": float(current or 0.0),
                "renewals": float(renewals or 0.0),
                "payments": int(payments or 0),
                "total_amount": float(total_amount or 0.0),
                "new_clients": new_clients_val,
                "new_revenue": new_revenue_val,
                "ad_spend": spend_amount,
                "cac": cac,
                "roi": roi,
            }
        )

    return stats


async def get_utm_sources(session: AsyncSession) -> list[dict[str, Any]]:
    if TrackingSourceModel is None:
        raise RuntimeError("TrackingSource model is unavailable")

    source_table = (
        TrackingSourceModel
        if isinstance(TrackingSourceModel, Table)
        else getattr(TrackingSourceModel, "__table__", None)
    )

    if source_table is None:
        raise RuntimeError("Failed to resolve table for UTM sources")

    stmt = (
        select(source_table.c.code, source_table.c.name, source_table.c.created_at)
        .where(source_table.c.type == "utm")
        .order_by(source_table.c.code)
    )
    rows = await session.execute(stmt)
    sources: list[dict[str, Any]] = []
    for code, name, created_at in rows.all():
        sources.append(
            {
                "code": str(code or ""),
                "title": str(name or code or ""),
                "created_at": created_at,
            }
        )
    return sources


async def get_utm_daily_stats(
    session: AsyncSession,
    until_utc: datetime,
) -> dict[str, dict[date, dict[str, Any]]]:
    if TrackingSourceModel is None or UserModel is None:
        raise RuntimeError("TrackingSource or User model is unavailable")

    _, _, Payment = await _get_models(session)

    payment_table = Payment if isinstance(Payment, Table) else Payment.__table__
    user_table = (
        UserModel
        if isinstance(UserModel, Table)
        else getattr(UserModel, "__table__", None)
    )
    source_table = (
        TrackingSourceModel
        if isinstance(TrackingSourceModel, Table)
        else getattr(TrackingSourceModel, "__table__", None)
    )

    if user_table is None or source_table is None:
        raise RuntimeError("Failed to resolve tables for UTM analytics")

    pay_tg = payment_table.c.tg_id
    pay_amount = payment_table.c.amount
    pay_status = payment_table.c.status
    pay_created = payment_table.c.created_at
    pay_system = payment_table.c.payment_system

    users_tg = user_table.c.tg_id
    users_source = user_table.c.source_code
    users_created = user_table.c.created_at

    excluded_systems = ("coupon", "referral", "cashback")

    source_alias = source_table.alias("utm_src")

    reg_created_dt = users_created
    try:
        if isinstance(reg_created_dt.type, DateTime):
            reg_created_ts = reg_created_dt
        else:
            reg_created_ts = func.to_timestamp(reg_created_dt / 1000.0)
    except Exception:
        reg_created_ts = func.to_timestamp(reg_created_dt / 1000.0)

    registrations_query = (
        select(
            source_alias.c.code.label("source_code"),
            func.date_trunc("day", reg_created_ts).label("reg_day"),
            func.count().label("registrations"),
        )
        .select_from(user_table.join(source_alias, users_source == source_alias.c.code))
        .where(
            users_source.is_not(None),
            source_alias.c.type == "utm",
            reg_created_ts < until_utc,
        )
        .group_by(source_alias.c.code, "reg_day")
    )

    payments_with_source = (
        select(
            source_alias.c.code.label("source_code"),
            source_alias.c.created_at.label("source_created_at"),
            pay_tg.label("tg_id"),
            pay_amount.label("amount"),
            pay_created.label("payment_created_at"),
            func.row_number()
            .over(partition_by=(source_alias.c.code, pay_tg), order_by=pay_created)
            .label("rn"),
        )
        .select_from(
            payment_table.join(user_table, pay_tg == users_tg).join(
                source_alias, users_source == source_alias.c.code
            )
        )
        .where(
            pay_status == "success",
            users_source.is_not(None),
            not_(pay_system.in_(excluded_systems)),
            pay_created >= source_alias.c.created_at,
            source_alias.c.type == "utm",
            pay_created < until_utc,
        )
    ).subquery("utm_payments_by_day")

    day_col = func.date_trunc("day", payments_with_source.c.payment_created_at).label("payment_day")

    query = (
        select(
            payments_with_source.c.source_code,
            day_col,
            func.coalesce(
                func.sum(
                    case((payments_with_source.c.rn == 1, payments_with_source.c.amount), else_=0.0)
                ),
                0.0,
            ).label("first_amount"),
            func.count(
                func.distinct(
                    case(
                        (
                            payments_with_source.c.rn == 1,
                            payments_with_source.c.tg_id,
                        ),
                        else_=None,
                    )
                )
            ).label("new_clients"),
            func.coalesce(
                func.sum(
                    case((payments_with_source.c.rn > 1, payments_with_source.c.amount), else_=0.0)
                ),
                0.0,
            ).label("renewals"),
            func.coalesce(func.sum(payments_with_source.c.amount), 0.0).label("total_amount"),
            func.count(func.distinct(payments_with_source.c.tg_id)).label("unique_clients"),
            func.count().label("payments_count"),
        )
        .group_by(payments_with_source.c.source_code, day_col)
        .order_by(payments_with_source.c.source_code, day_col)
    )

    registrations_rows = await session.execute(registrations_query)
    registrations: dict[str, dict[date, int]] = {}
    for source_code, reg_day, reg_count in registrations_rows.all():
        code = str(source_code or "")
        reg_dt = reg_day.date() if isinstance(reg_day, datetime) else None
        if not reg_dt:
            continue
        registrations.setdefault(code, {})[reg_dt] = int(reg_count or 0)

    key_model, plan_model, _ = await _get_models(session)
    key_table = key_model if isinstance(key_model, Table) else key_model.__table__
    plan_table = plan_model if isinstance(plan_model, Table) else plan_model.__table__

    key_created_col = key_table.c.created_at
    if isinstance(key_created_col.type, DateTime):
        trial_created_ts = key_created_col
    else:
        trial_created_ts = func.to_timestamp(key_created_col / 1000.0)

    plan_group_col = plan_table.c.group_code
    key_tg_col = key_table.c.tg_id
    key_tariff_col = key_table.c.tariff_id

    trials_query = (
        select(
            source_alias.c.code.label("source_code"),
            func.date_trunc("day", trial_created_ts).label("trial_day"),
            func.count().label("trials"),
        )
        .select_from(
            key_table
            .join(plan_table, key_tariff_col == plan_table.c.id)
            .join(user_table, key_tg_col == users_tg)
            .join(source_alias, users_source == source_alias.c.code)
        )
        .where(
            source_alias.c.type == "utm",
            users_source.is_not(None),
            plan_group_col == "trial",
            trial_created_ts < until_utc,
        )
        .group_by(source_alias.c.code, "trial_day")
    )

    trials_rows = await session.execute(trials_query)
    trials: dict[str, dict[date, int]] = {}
    for source_code, trial_day, trial_count in trials_rows.all():
        code = str(source_code or "")
        trial_dt = trial_day.date() if isinstance(trial_day, datetime) else None
        if not trial_dt:
            continue
        trials.setdefault(code, {})[trial_dt] = int(trial_count or 0)

    rows = await session.execute(query)
    data: dict[str, dict[date, dict[str, Any]]] = {}

    def _ensure_entry(code: str, day_dt: date) -> dict[str, Any]:
        by_code = data.setdefault(code, {})
        if day_dt not in by_code:
            by_code[day_dt] = {
                "first_amount": 0.0,
                "new_clients": 0,
                "renewals": 0.0,
                "total_amount": 0.0,
                "unique_clients": 0,
                "payments_count": 0,
                "registrations": 0,
                "trials": 0,
            }
        return by_code[day_dt]

    for source_code, day, first_amount, new_clients, renewals, total_amount, unique_clients, payments_count in rows.all():
        code = str(source_code or "")
        day_dt = day.date() if isinstance(day, datetime) else None
        if not day_dt:
            continue
        entry = _ensure_entry(code, day_dt)
        entry.update(
            {
                "first_amount": float(first_amount or 0.0),
                "new_clients": int(new_clients or 0),
                "renewals": float(renewals or 0.0),
                "total_amount": float(total_amount or 0.0),
                "unique_clients": int(unique_clients or 0),
                "payments_count": int(payments_count or 0),
            }
        )

    for code, reg_data in registrations.items():
        for reg_day, reg_count in reg_data.items():
            entry = _ensure_entry(code, reg_day)
            entry["registrations"] = reg_count

    for code, trial_data in trials.items():
        for trial_day, trial_count in trial_data.items():
            entry = _ensure_entry(code, trial_day)
            entry["trials"] = trial_count

    return data


async def _reflect_tables(session: AsyncSession) -> tuple[Table, Table, Table]: 
    engine = session.bind
    insp = sqlalchemy.inspect(engine)
    metadata = sqlalchemy.MetaData()

    tables_cfg = settings.DISCOVERY_FALLBACKS["tables"]
    names = {k: tables_cfg.get(k) for k in ("keys", "plans", "payments")}

    def resolve(name_hint: str | None, candidates: list[str]) -> str:
        if name_hint and name_hint in candidates:
            return name_hint
        for cand in candidates:
            if name_hint and cand.startswith(name_hint):
                return cand
        for cand in candidates:
            if name_hint is None and any(x in cand for x in ("key", "plan", "payment")):
                return cand
        raise LookupError(f"Table for {name_hint or 'unknown'} not found")

    table_names = insp.get_table_names()
    key_table = Table(resolve(names["keys"], table_names), metadata, autoload_with=engine)
    plan_table = Table(resolve(names["plans"], table_names), metadata, autoload_with=engine)
    payment_table = Table(resolve(names["payments"], table_names), metadata, autoload_with=engine)
    return key_table, plan_table, payment_table


async def _get_models(session: AsyncSession):
    global KeyModel, PlanModel, PaymentModel
    if KeyModel and PlanModel and PaymentModel:
        return KeyModel, PlanModel, PaymentModel
    try:
        KeyModel, PlanModel, PaymentModel = await _reflect_tables(session)
        logger.info("[RF] Using reflected tables for discovery")
        return KeyModel, PlanModel, PaymentModel
    except Exception as exc: 
        logger.error(f"[RF] Discovery failed: {exc}")
        raise

def _bucket_plan(group_code: str | None, duration_days: int | None) -> str:
    if group_code in ("1m", "3m", "12m"):
        return group_code
    months = round((duration_days or 0) / 30) if duration_days else 0
    if months == 1:
        return "1m"
    if months == 3:
        return "3m"
    if 10 <= months <= 13:
        return "12m"
    return "other"




async def get_expiring_by_plan(
    session: AsyncSession,
    dt_start: datetime,
    dt_end: datetime,
    flags: Any,
) -> dict[str, dict[str, Any]]:
    key_model, plan_model, _ = await _get_models(session)

    start_ms = int(dt_start.timestamp() * 1000)
    end_ms = int(dt_end.timestamp() * 1000)

    stmt = (
        select(
            (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
            (plan_model.c.name if isinstance(plan_model, Table) else plan_model.name),
            (plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code),
            func.count((key_model.c.client_id if isinstance(key_model, Table) else key_model.client_id)),
            (plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub),
            (plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days),
        )
        .join(
            plan_model,
            (key_model.c.tariff_id if isinstance(key_model, Table) else key_model.tariff_id)
            == (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
        )
    )

    expiry_col = (
        key_model.c.expiry_time if isinstance(key_model, Table) else key_model.expiry_time
    )
    stmt = stmt.where(expiry_col >= start_ms, expiry_col < end_ms)

    if flags.SKIP_FROZEN and (
        hasattr(key_model, "is_frozen")
        or (isinstance(key_model, Table) and "is_frozen" in key_model.c)
    ):
        frozen_col = (
            key_model.c.is_frozen if isinstance(key_model, Table) else key_model.is_frozen
        )
        stmt = stmt.where(frozen_col.is_(False))

    if getattr(flags, "EXCLUDE_TRIALS", False):
        price_col = (plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub)
        gc_col = (plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code)
        stmt = stmt.where(~( (gc_col == "trial") | (func.coalesce(price_col, 0) == 0) ))

    stmt = stmt.group_by(
        (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
        (plan_model.c.name if isinstance(plan_model, Table) else plan_model.name),
        (plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code),
        (plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub),
        (plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days),
    )

    result = await session.execute(stmt)
    data: dict[str, dict[str, Any]] = {}
    for _id, name, gcode, count, price, duration in result:
        bucket = _bucket_plan(gcode, duration)
        data[str(name)] = {
            "count": int(count or 0),
            "price": float(price or 0.0),
            "period_months": round((duration or 0) / 30) if duration else None,
            "group_code": gcode,
            "bucket": bucket,
        }
    return data

async def get_baseline_expiring_by_plan(
    session: AsyncSession,
    dt_start: datetime,
    dt_end: datetime,
    flags: Any,
) -> dict[str, dict[str, Any]]:
    key_model, plan_model, _ = await _get_models(session)

    start_ms = int(dt_start.timestamp() * 1000)
    end_ms = int(dt_end.timestamp() * 1000)

    current = await get_expiring_by_plan(session, dt_start, dt_end, flags)

    expiry_col = key_model.c.expiry_time if isinstance(key_model, Table) else key_model.expiry_time
    dur_col = plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days
    prev_expiry_ms = (
        expiry_col
        - (
            cast(func.coalesce(dur_col, 0), BigInteger)
            * literal(86400000, BigInteger)
        )
    )

    if isinstance(key_model, Table):
        created_candidates = [
            key_model.c.get(col) for col in ("created_at", "created", "created_ms") if col in key_model.c
        ]
        created_col = next((col for col in created_candidates if col is not None), None)
    else:
        created_col = None
        for attr in ("created_at", "created", "created_ms"):
            if hasattr(key_model, attr):
                created_col = getattr(key_model, attr)
                break

    stmt_prev = (
        select(
            (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
            (plan_model.c.name if isinstance(plan_model, Table) else plan_model.name),
            (plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code),
            func.count((key_model.c.client_id if isinstance(key_model, Table) else key_model.client_id)),
            (plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub),
            (plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days),
        )
        .join(
            plan_model,
            (key_model.c.tariff_id if isinstance(key_model, Table) else key_model.tariff_id)
            == (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
        )
        .where(prev_expiry_ms >= start_ms, prev_expiry_ms < end_ms)
    )

    if created_col is not None:
        stmt_prev = stmt_prev.where(created_col < start_ms)

    if flags.SKIP_FROZEN and (
        hasattr(key_model, "is_frozen")
        or (isinstance(key_model, Table) and "is_frozen" in key_model.c)
    ):
        frozen_col = key_model.c.is_frozen if isinstance(key_model, Table) else key_model.is_frozen
        stmt_prev = stmt_prev.where(frozen_col.is_(False))

    if getattr(flags, "EXCLUDE_TRIALS", False):
        price_col = plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub
        gc_col = plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code
        stmt_prev = stmt_prev.where(~((gc_col == "trial") | (func.coalesce(price_col, 0) == 0)))

    stmt_prev = stmt_prev.group_by(
        (plan_model.c.id if isinstance(plan_model, Table) else plan_model.id),
        (plan_model.c.name if isinstance(plan_model, Table) else plan_model.name),
        (plan_model.c.group_code if isinstance(plan_model, Table) else plan_model.group_code),
        (plan_model.c.price_rub if isinstance(plan_model, Table) else plan_model.price_rub),
        (plan_model.c.duration_days if isinstance(plan_model, Table) else plan_model.duration_days),
    )

    result_prev = await session.execute(stmt_prev)
    prev_data: dict[str, dict[str, Any]] = {}
    for _id, name, gcode, count, price, duration in result_prev:
        bucket = _bucket_plan(gcode, duration)
        entry = prev_data.get(str(name))
        if entry is None:
            prev_data[str(name)] = {
                "count": int(count or 0),
                "price": float(price or 0.0),
                "period_months": round((duration or 0) / 30) if duration else None,
                "group_code": gcode,
                "bucket": bucket,
            }
        else:
            entry["count"] += int(count or 0)
            if price and float(price) != entry.get("price", 0.0):
                entry["price"] = float(price)

    merged: dict[str, dict[str, Any]] = {name: dict(info) for name, info in prev_data.items()}
    for entry in merged.values():
        entry["count"] = int(entry.get("count", 0))

    for name, info in current.items():
        entry = merged.get(name)
        if entry is None:
            entry = dict(info)
            entry["count"] = 0
            merged[name] = entry
        else:
            if info.get("price") is not None:
                entry["price"] = float(info["price"])
            if info.get("period_months") is not None:
                entry["period_months"] = info["period_months"]
            if info.get("group_code") is not None:
                entry["group_code"] = info["group_code"]
            if info.get("bucket") is not None:
                entry["bucket"] = info["bucket"]
    return merged


async def get_received(
    session: AsyncSession,
    dt_start: datetime,
    dt_end: datetime,
    flags: Any,
) -> dict[str, float]:
    _, _, payment_model = await _get_models(session)

    paid_col = (
        payment_model.c.amount if isinstance(payment_model, Table) else payment_model.amount
    )
    status_col = (
        payment_model.c.status if isinstance(payment_model, Table) else payment_model.status
    )
    created_col = (
        payment_model.c.created_at if isinstance(payment_model, Table) else payment_model.created_at
    )

    payment_system_col = (
        payment_model.c.payment_system
        if isinstance(payment_model, Table)
        else payment_model.payment_system
    )
    excluded_systems = ("referral", "coupon", "cashback")

    stmt = (
        select(func.coalesce(func.sum(paid_col), 0))
        .where(
            created_col >= dt_start,
            created_col < dt_end,
            status_col == "success",
            payment_system_col.notin_(excluded_systems),
        )
    )
    result = await session.execute(stmt)
    paid = float(result.scalar() or 0.0)
    return {"paid": paid, "refunds": 0.0, "net": paid}


def compute_forecast(
    expiring: dict[str, dict[str, Any]],
    received_dict: dict[str, float],
    probs: dict[str, float] | None = None,
    global_prob: float | None = None,
) -> dict[str, Any]:
    overrides = probs or {}
    forecast = 0.0
    by_plans: dict[str, dict[str, Any]] = {}

    for code, info in expiring.items():
        price = info.get("price", 0.0)
        count = info.get("count", 0)
        prob = (
            overrides.get(code)
            or overrides.get(info.get("group_code"))
            or overrides.get(info.get("bucket"))
            or (global_prob if global_prob is not None else 1.0)
        )
        expected = price * count * prob
        forecast += expected
        by_plans[code] = {**info, "expected": expected, "prob": prob}

    received = received_dict.get("net", 0.0)
    to_earn = max(0.0, forecast - received)
    return {
        "forecast": forecast,
        "received": received,
        "to_earn": to_earn,
        "by_plans": by_plans,
    }



async def calc_kpis(
    session: AsyncSession,
    dt_start: datetime,
    dt_end: datetime,
    flags: Any,
    by_plans: dict[str, dict[str, Any]],
    probs: dict[str, float] | None = None,
    global_prob: float | None = None,
) -> dict[str, Any]:
    _, _, Payment = await _get_models(session)
    paid_col = Payment.c.amount if isinstance(Payment, Table) else Payment.amount
    status_col = Payment.c.status if isinstance(Payment, Table) else Payment.status
    created_col = Payment.c.created_at if isinstance(Payment, Table) else Payment.created_at

    q_pay = (
        select(
            func.coalesce(func.sum(case((status_col == "success", paid_col), else_=0.0)), 0.0),
            func.count().filter(status_col == "success"),
        )
        .where(created_col >= dt_start, created_col < dt_end)
    )
    paid_sum, paid_count = (await session.execute(q_pay)).one()
    paid_sum = float(paid_sum or 0.0)
    paid_count = int(paid_count or 0)
    avg_check = (paid_sum / paid_count) if paid_count > 0 else 0.0

    Key, _, _ = await _get_models(session)
    k_expiry = Key.c.expiry_time if isinstance(Key, Table) else Key.expiry_time  
    k_created = Key.c.created_at if isinstance(Key, Table) else Key.created_at   
    k_tg = Key.c.tg_id if isinstance(Key, Table) else Key.tg_id
    cond_frozen = True
    if hasattr(Key, "is_frozen") or (isinstance(Key, Table) and "is_frozen" in Key.c):
        k_frozen = Key.c.is_frozen if isinstance(Key, Table) else Key.is_frozen
        cond_frozen = k_frozen.is_(False) if flags.SKIP_FROZEN else True
    q_active = (
        select(func.count(func.distinct(k_tg)))
        .where(
            (k_created <= int(dt_end.timestamp() * 1000)),
            (k_expiry >= int(dt_start.timestamp() * 1000)),
            cond_frozen,
        )
    )
    active_users = int((await session.execute(q_active)).scalar() or 0)
    arpu = (paid_sum / active_users) if active_users > 0 else 0.0

    retention_block = await _calc_retention_churn(
        session, dt_start, dt_end, flags, probs=probs, global_prob=global_prob
    )

    active_paid_keys = await _count_active_paid_keys(session, flags)

    return {
        "avg_check": avg_check,
        "paid_count": paid_count,
        "active_users": active_users,
        "arpu": arpu,
        "mrr_active": await _calc_mrr_active_base(session, flags),
        "active_paid_keys": active_paid_keys,
        **retention_block,
    }


async def _calc_mrr_active_base(session: AsyncSession, flags: Any) -> float:
    Key, Plan, _ = await _get_models(session)

    now_ms = int(datetime.utcnow().timestamp() * 1000)

    expiry_col = Key.c.expiry_time if isinstance(Key, Table) else Key.expiry_time
    tg_col = Key.c.client_id if isinstance(Key, Table) else Key.client_id

    stmt = select(
        Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code,
        func.count(tg_col),
        Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub,
        Plan.c.duration_days if isinstance(Plan, Table) else Plan.duration_days,
    ).join(
        Plan,
        (Key.c.tariff_id if isinstance(Key, Table) else Key.tariff_id)
        == (Plan.c.id if isinstance(Plan, Table) else Plan.id),
    ).where(
        expiry_col > now_ms
    )

    if flags.SKIP_FROZEN and (
        hasattr(Key, "is_frozen")
        or (isinstance(Key, Table) and "is_frozen" in Key.c)
    ):
        frozen_col = Key.c.is_frozen if isinstance(Key, Table) else Key.is_frozen
        stmt = stmt.where(frozen_col.is_(False))

    if getattr(flags, "EXCLUDE_TRIALS", False):
        gc_col = Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code
        price_col = Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub
        stmt = stmt.where(~((gc_col == "trial") | (func.coalesce(price_col, 0) == 0)))

    stmt = stmt.group_by(
        (Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code),
        (Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub),
        (Plan.c.duration_days if isinstance(Plan, Table) else Plan.duration_days),
    )

    res = await session.execute(stmt)
    mrr_active = 0.0
    for code, count, price, duration in res:
        months = round((duration or 0) / 30) if duration else 1
        months = months if months and months > 0 else 1
        mrr_active += float(price or 0.0) / months * int(count or 0)
    return mrr_active


async def _count_active_paid_keys(session: AsyncSession, flags: Any) -> int:
    Key, Plan, _ = await _get_models(session)

    now_ms = int(datetime.utcnow().timestamp() * 1000)

    expiry_col = Key.c.expiry_time if isinstance(Key, Table) else Key.expiry_time
    join_condition = (
        (Key.c.tariff_id if isinstance(Key, Table) else Key.tariff_id)
        == (Plan.c.id if isinstance(Plan, Table) else Plan.id)
    )

    if isinstance(Key, Table):
        stmt = select(func.count()).select_from(Key.join(Plan, join_condition))
    else:
        stmt = select(func.count()).select_from(Key).join(Plan, join_condition)

    stmt = stmt.where(expiry_col > now_ms)

    if flags.SKIP_FROZEN and (
        hasattr(Key, "is_frozen")
        or (isinstance(Key, Table) and "is_frozen" in Key.c)
    ):
        frozen_col = Key.c.is_frozen if isinstance(Key, Table) else Key.is_frozen
        stmt = stmt.where(frozen_col.is_(False))

    if getattr(flags, "EXCLUDE_TRIALS", False):
        gc_col = Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code
        price_col = Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub
        stmt = stmt.where(~((gc_col == "trial") | (func.coalesce(price_col, 0) == 0)))

    result = await session.execute(stmt)
    return int(result.scalar() or 0)



async def _calc_retention_churn(
    session: AsyncSession,
    dt_start: datetime,
    dt_end: datetime,
    flags: Any,
    probs: dict[str, float] | None = None,
    global_prob: float | None = None,
) -> dict[str, Any]:
    Key, Plan, Payment = await _get_models(session)

    start_ms = int(dt_start.timestamp() * 1000)
    end_ms = int(dt_end.timestamp() * 1000)
    now_ms = int(datetime.utcnow().timestamp() * 1000)

    expiry_col = Key.c.expiry_time if isinstance(Key, Table) else Key.expiry_time
    dur_col = Plan.c.duration_days if isinstance(Plan, Table) else Plan.duration_days
    prev_expiry_ms = (
        expiry_col
        - (cast(func.coalesce(dur_col, 0), BigInteger) * literal(86400000, BigInteger))
    )

    q_candidates = (
        select(
            expiry_col.label("expiry_ms"),
            (Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code).label("gcode"),
            (Plan.c.duration_days if isinstance(Plan, Table) else Plan.duration_days).label("days"),
            (Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub).label("price"),
            (Key.c.tg_id if isinstance(Key, Table) else Key.tg_id).label("tg_id"),
        )
        .join(
            Plan,
            (Key.c.tariff_id if isinstance(Key, Table) else Key.tariff_id)
            == (Plan.c.id if isinstance(Plan, Table) else Plan.id),
        )
        .where(prev_expiry_ms >= start_ms, prev_expiry_ms < end_ms)
    )

    if flags.SKIP_FROZEN and (
        hasattr(Key, "is_frozen")
        or (isinstance(Key, Table) and "is_frozen" in Key.c)
    ):
        frozen_col = Key.c.is_frozen if isinstance(Key, Table) else Key.is_frozen
        q_candidates = q_candidates.where(frozen_col.is_(False))

    if getattr(flags, "EXCLUDE_TRIALS", False):
        gc_col = Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code
        price_col = Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub
        q_candidates = q_candidates.where(~((gc_col == "trial") | (func.coalesce(price_col, 0) == 0)))

    cand_rows = (await session.execute(q_candidates)).all()
    candidates_total = len(cand_rows)
    cand_tg_ids = {tg for *_rest, tg in cand_rows}  

    _, _, Payment = await _get_models(session)
    status_col = Payment.c.status if isinstance(Payment, Table) else Payment.status
    created_col = Payment.c.created_at if isinstance(Payment, Table) else Payment.created_at
    pay_tg_in_month = await session.execute(
        select((Payment.c.tg_id if isinstance(Payment, Table) else Payment.tg_id))
        .where(created_col >= dt_start, created_col < dt_end, status_col == "success")
        .group_by((Payment.c.tg_id if isinstance(Payment, Table) else Payment.tg_id))
    )
    paid_in_month_tg = {tg for (tg,) in pay_tg_in_month.all()}

    plan_map_rows = await session.execute(
        select(
            (Plan.c.price_rub if isinstance(Plan, Table) else Plan.price_rub),
            (Plan.c.duration_days if isinstance(Plan, Table) else Plan.duration_days),
            (Plan.c.group_code if isinstance(Plan, Table) else Plan.group_code),
        )
    )
    price_to_plan = {}
    for price_rub, dd, gcode in plan_map_rows.all():
        price_to_plan.setdefault(int(price_rub or 0), (int(dd or 30), gcode))

    p = Payment
    base = select(
        (p.c.tg_id if isinstance(p, Table) else p.tg_id).label("tg_id"),
        (p.c.amount if isinstance(p, Table) else p.amount).label("amount"),
        (p.c.created_at if isinstance(p, Table) else p.created_at).label("paid_at"),
        func.row_number().over(
            partition_by=(p.c.tg_id if isinstance(p, Table) else p.tg_id),
            order_by=(p.c.created_at if isinstance(p, Table) else p.created_at).desc(),
        ).label("rn"),
    ).where(created_col < dt_end, status_col == "success")

    subq = base.subquery("last_payments_ranked")
    last_pays = await session.execute(
        select(subq.c.tg_id, subq.c.amount, subq.c.paid_at).where(subq.c.rn == 1)
    )
    fallback_rows = []
    for tg_id, amount, paid_at in last_pays.all():
        if tg_id in cand_tg_ids:
            continue  
        price_key = int(round(float(amount or 0.0)))
        plan_info = price_to_plan.get(price_key)
        if not plan_info:
            continue  
        dd, gcode = plan_info
        prev_expiry_dt = paid_at + timedelta(days=dd or 30)
        if dt_start <= prev_expiry_dt < dt_end:
            fallback_rows.append((None, gcode, dd, price_key, tg_id))

    cand_rows.extend(fallback_rows)
    candidates_total = len(cand_rows)
    if candidates_total == 0:
        return {
            "retention_rate": None,
            "churn_rate": None,
            "renewed_count": 0,
            "not_renewed_yet": 0,
            "predicted_churn": 0.0,
        }

    paid_col = Payment.c.amount if isinstance(Payment, Table) else Payment.amount
    status_col = Payment.c.status if isinstance(Payment, Table) else Payment.status
    created_col = Payment.c.created_at if isinstance(Payment, Table) else Payment.created_at
    p_rows = await session.execute(
        select((Payment.c.tg_id if isinstance(Payment, Table) else Payment.tg_id))
        .where(created_col >= dt_start, created_col < dt_end, status_col == "success")
        .group_by((Payment.c.tg_id if isinstance(Payment, Table) else Payment.tg_id))
    )
    paid_tg_set = {tg for (tg,) in p_rows.all()}

    renewed = 0
    not_renewed = 0
    bucket_counts: dict[str, int] = {}
    for expiry_ms, gcode, days, price, tg_id in cand_rows:
        if expiry_ms is not None:
            if (expiry_ms or 0) >= end_ms:
                renewed += 1
            else:
                not_renewed += 1
                bucket = _bucket_plan(gcode, days)
                bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            continue
        if tg_id in paid_in_month_tg:
            renewed += 1
        else:
            not_renewed += 1
            bucket = _bucket_plan(gcode, days)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    retention_rate = renewed / candidates_total
    churn_rate = not_renewed / candidates_total

    p_map = probs or {}
    default_p = global_prob if global_prob is not None else 1.0
    predicted_churn = 0.0
    for bucket, cnt in bucket_counts.items():
        p = p_map.get(bucket, default_p)
        predicted_churn += (1.0 - float(p or 0.0)) * cnt

    return {
        "retention_rate": retention_rate,
        "churn_rate": churn_rate,
        "renewed_count": renewed,
        "not_renewed_yet": not_renewed,
        "predicted_churn": predicted_churn,
    }