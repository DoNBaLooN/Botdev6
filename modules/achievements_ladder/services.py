from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil
from typing import Any

from aiogram import Bot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import Payment, Referral, User
from logger import logger

from . import settings, texts
from .db import (
    active_users,
    add_offset,
    get_offset,
    get_progress_anchor,
    has_channel_bonus,
    last_notification,
    log_notification,
    monthly_daily_count,
    weekly_notification_count,
)
from .models import AchvDailyLog, AchvReward


_STEP_CACHE: dict[int, tuple[int, datetime]] = {}


async def calculate_steps(
    session: AsyncSession,
    tg_id: int,
    *,
    until: datetime | None = None,
    apply_payment_anchor: bool = True,
) -> int:
    """Calculate current steps for user."""

    breakdown = await calculate_steps_breakdown(
        session,
        tg_id,
        until=until,
        apply_payment_anchor=apply_payment_anchor,
    )
    return int(breakdown["total"])


async def calculate_steps_breakdown(
    session: AsyncSession,
    tg_id: int,
    *,
    until: datetime | None = None,
    apply_payment_anchor: bool = True,
) -> dict[str, Any]:
    """Return a detailed breakdown of steps for the user."""

    until = until or datetime.utcnow()
    include_until_day = until.time() != datetime.min.time()
    today = until.date()
    if settings.ACHV["SEASON"]["MODE"] == "SEASON":
        since_date = today - timedelta(weeks=settings.ACHV["SEASON"]["LENGTH_WEEKS"])
    else:
        since_date = date.min
    since_dt = datetime.combine(since_date, datetime.min.time())

    data: dict[str, Any] = {
        "total": 0,
        "raw_total": 0.0,
        "invites": {"count": 0, "steps": 0.0},
        "self_pay": {"counts": {}, "steps": 0.0},
        "ref_pay": {"counts": {}, "steps": 0.0},
        "channel": {"received": False, "steps": 0.0},
        "daily": {
            "recorded_days": 0,
            "applied_days": 0,
            "cap": settings.ACHV["CAPS"]["DAILY_STEPS_CAP_PER_MONTH"],
            "steps": 0.0,
        },
        "streak": {"bonuses": 0, "steps": 0.0},
        "offset": {"value": 0},
    }

    payment_since_dt = since_dt
    if apply_payment_anchor:
        anchor = await get_progress_anchor(session, tg_id)
        if anchor is not None:
            payment_since_dt = max(since_dt, anchor)

    try:
        invited = await session.execute(
            select(func.count())
            .select_from(Referral)
            .join(User, User.tg_id == Referral.referred_tg_id)
            .where(
                Referral.referrer_tg_id == tg_id,
                User.created_at >= since_dt,
                User.created_at < until,
            )
        )
        invited_count = invited.scalar_one()
        invite_steps = invited_count * settings.ACHV["WEIGHTS"]["INVITE"]
        data["invites"] = {"count": invited_count, "steps": float(invite_steps)}

        plan_months_column = getattr(Payment, "plan_months", None)

        if plan_months_column is not None:
            self_pays_query = (
                select(plan_months_column, func.count())
                .where(
                    Payment.tg_id == tg_id,
                    Payment.created_at >= payment_since_dt,
                    Payment.created_at < until,
                    Payment.status == "paid",
                )
                .group_by(plan_months_column)
            )
        else:
            self_pays_query = select(func.count()).select_from(Payment).where(
                Payment.tg_id == tg_id,
                Payment.created_at >= payment_since_dt,
                Payment.created_at < until,
                Payment.status == "paid",
            )

        self_pays = await session.execute(self_pays_query)

        self_pay_steps = 0.0
        self_pay_counts: dict[str, int] = {}
        if plan_months_column is not None:
            for tier, cnt in self_pays:
                weight = settings.ACHV["WEIGHTS"]["SELF_PAY"].get(tier, 0)
                self_pay_steps += cnt * weight
                self_pay_counts[str(tier)] = cnt
        else:
            count = self_pays.scalar_one()
            weight_map = settings.ACHV["WEIGHTS"]["SELF_PAY"]
            default_weight = weight_map.get(1)
            if default_weight is None and weight_map:
                default_weight = next(iter(weight_map.values()))
            weight = float(default_weight or 0)
            self_pay_steps += count * weight
            self_pay_counts["any"] = count
        data["self_pay"] = {"counts": self_pay_counts, "steps": float(self_pay_steps)}

        if plan_months_column is not None:
            ref_pays_query = (
                select(plan_months_column, func.count())
                .join(Referral, Referral.referred_tg_id == Payment.tg_id)
                .where(
                    Referral.referrer_tg_id == tg_id,
                    Payment.created_at >= payment_since_dt,
                    Payment.created_at < until,
                    Payment.status == "paid",
                )
                .group_by(plan_months_column)
            )
        else:
            ref_pays_query = (
                select(func.count())
                .select_from(Payment)
                .join(Referral, Referral.referred_tg_id == Payment.tg_id)
                .where(
                    Referral.referrer_tg_id == tg_id,
                    Payment.created_at >= payment_since_dt,
                    Payment.created_at < until,
                    Payment.status == "paid",
                )
            )

        ref_pays = await session.execute(ref_pays_query)

        ref_pay_steps = 0.0
        ref_pay_counts: dict[str, int] = {}
        if plan_months_column is not None:
            for tier, cnt in ref_pays:
                weight = settings.ACHV["WEIGHTS"]["REF_PAY"].get(tier, 0)
                ref_pay_steps += cnt * weight
                ref_pay_counts[str(tier)] = cnt
        else:
            count = ref_pays.scalar_one()
            weight_map = settings.ACHV["WEIGHTS"]["REF_PAY"]
            default_weight = weight_map.get(1)
            if default_weight is None and weight_map:
                default_weight = next(iter(weight_map.values()))
            weight = float(default_weight or 0)
            ref_pay_steps += count * weight
            ref_pay_counts["any"] = count
        data["ref_pay"] = {"counts": ref_pay_counts, "steps": float(ref_pay_steps)}

        channel_received = await has_channel_bonus(session, tg_id)
        channel_steps = settings.ACHV["WEIGHTS"]["JOIN_CHANNEL"] if channel_received else 0
        data["channel"] = {"received": channel_received, "steps": float(channel_steps)}

        month_start = today.replace(day=1)
        daily_count = await monthly_daily_count(
            session,
            tg_id,
            max(month_start, since_date),
            until.date(),
            include_until=include_until_day,
        )
        daily_cap = settings.ACHV["CAPS"]["DAILY_STEPS_CAP_PER_MONTH"]
        applied_days = min(daily_count, daily_cap)
        daily_steps = applied_days * settings.ACHV["WEIGHTS"]["DAILY"]
        data["daily"] = {
            "recorded_days": daily_count,
            "applied_days": applied_days,
            "cap": daily_cap,
            "steps": float(daily_steps),
        }

        day_boundary = (
            AchvDailyLog.day <= until.date()
            if include_until_day
            else AchvDailyLog.day < until.date()
        )
        logs = await session.execute(
            select(AchvDailyLog.day)
            .where(
                AchvDailyLog.tg_id == tg_id,
                day_boundary,
            )
            .order_by(AchvDailyLog.day)
        )
        days = [row[0] for row in logs]
        streak = 0
        bonus = 0.0
        bonuses_count = 0
        prev = None
        for d in days:
            if prev and d == prev + timedelta(days=1):
                streak += 1
            else:
                streak = 1
            if streak and streak % 7 == 0:
                bonus += settings.ACHV["WEIGHTS"]["STREAK7"]
                bonuses_count += 1
            prev = d
        data["streak"] = {"bonuses": bonuses_count, "steps": float(bonus)}

        offset = await get_offset(session, tg_id)
        data["offset"] = {"value": int(offset)}

        raw_total = (
            invite_steps
            + self_pay_steps
            + ref_pay_steps
            + channel_steps
            + daily_steps
            + bonus
        )
        data["raw_total"] = float(raw_total)
        data["total"] = int(max(0.0, raw_total - offset))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"[ACHV_CALC] failed to compute steps for {tg_id}: {exc}")

    return data


async def get_claimed_steps(session: AsyncSession, tg_id: int) -> set[int]:
    rows = await session.execute(select(AchvReward.steps).where(AchvReward.tg_id == tg_id))
    return {row[0] for row in rows.all()}


def next_claimable_threshold(steps: int, claimed: set[int]) -> dict[str, Any] | None:
    for threshold in settings.ACHV["THRESHOLDS"]:
        if steps >= threshold["steps"] and threshold["steps"] not in claimed:
            return threshold
    return None


def next_unreached_threshold(steps: int, claimed: set[int]) -> dict[str, Any] | None:
    """Return the next threshold that user hasn't reached yet."""

    for threshold in settings.ACHV["THRESHOLDS"]:
        if threshold["steps"] > steps:
            return threshold
        if threshold["steps"] not in claimed:
            return threshold
    return None


async def check_thresholds_and_grant(
    session: AsyncSession,
    tg_id: int,
    steps: int,
    bot: Any | None = None,
    username: str | None = None,
    first_name: str | None = None,
) -> dict[str, Any] | None:
    claimed = await get_claimed_steps(session, tg_id)
    threshold = next_claimable_threshold(steps, claimed)
    if not threshold:
        return None

    reward = threshold["reward"]
    if not await _check_caps(session, tg_id, reward):
        logger.info(f"[ACHV_CAP_BLOCK] tg_id={tg_id} steps={threshold['steps']}")
        return None

    try:
        session.add(
            AchvReward(
                tg_id=tg_id,
                steps=threshold["steps"],
                reward_type=reward["type"],
                reward_value=reward["value"],
            )
        )
        await session.commit()
        logger.info(f"[ACHV_GRANT] tg_id={tg_id} steps={threshold['steps']}")
    except Exception as exc:  # pragma: no cover
        await session.rollback()
        logger.error(f"[ACHV_GRANT] failed tg_id={tg_id}: {exc}")
        return None

    await grant_reward(session, tg_id, threshold)

    if threshold.get("announce") and bot:
        mention = f"@{username}" if username else (first_name or str(tg_id))
        try:
            msg = settings.ACHV["ANNOUNCE_TEMPLATE"].replace("@{{username}}", mention).replace(
                "{{days}}", str(reward["value"])
            )
            await bot.send_message(settings.ACHV["ANNOUNCE_CHANNEL_ID"], msg)
            logger.info(f"[ACHV_ANNOUNCE] tg_id={tg_id}")
        except Exception as exc:  # pragma: no cover
            logger.error(f"[ACHV_ANNOUNCE] failed {exc}")

    if threshold["steps"] >= 50 and settings.ACHV["AFTER_50"]["MODE"] in {"SOFT_RESET", "HARD_RESET"}:
        leftover = max(0, steps - 50)
        if settings.ACHV["AFTER_50"]["MODE"] == "SOFT_RESET":
            await add_offset(session, tg_id, 50 - leftover)
        else:
            await add_offset(session, tg_id, steps)

    return threshold


async def grant_reward(session: AsyncSession, tg_id: int, threshold: dict[str, Any]):
    """Grant reward specified by threshold."""

    reward = threshold.get("reward", {})
    try:
        if reward.get("type") == "days":
            from database.users import get_trial, update_trial

            current = await get_trial(session, tg_id)
            await update_trial(session, tg_id, current + reward.get("value", 0))
    except Exception as exc:  # pragma: no cover
        logger.error(f"[ACHV_GRANT] failed to apply reward for {tg_id}: {exc}")
    else:
        logger.info(f"[ACHV_GRANT] reward for tg_id={tg_id}: {reward}")


async def periodic_notifications(
    bot: Bot,
    *,
    session: AsyncSession | None = None,
    sessionmaker: async_sessionmaker | None = None,
) -> None:
    if session is not None:
        await _periodic_notifications(bot, session)
        return

    if sessionmaker is None:
        raise ValueError("`session` or `sessionmaker` must be provided")

    async with sessionmaker() as session_obj:
        await _periodic_notifications(bot, session_obj)


async def _periodic_notifications(bot: Bot, session: AsyncSession) -> None:
    cfg = settings.ACHV["NOTIFY"]
    now = datetime.utcnow()
    tg_ids = await active_users(session, (now - timedelta(days=cfg["ACTIVE_DAYS"])).date())
    week_ago = now - timedelta(days=7)
    for tg_id in tg_ids:
        steps = await calculate_steps(session, tg_id)
        claimed = await get_claimed_steps(session, tg_id)
        next_thr = next_claimable_threshold(steps, claimed)
        if next_thr:
            remain = next_thr["steps"] - steps
            if remain <= cfg["REMAIN_MAX"]:
                last = await last_notification(session, tg_id, "remain")
                if not last or last.date() != now.date():
                    cnt = await weekly_notification_count(session, tg_id, "remain", week_ago)
                    if cnt < cfg["MAX_PER_WEEK"]:
                        await bot.send_message(tg_id, texts.announce_remain(remain))
                        await log_notification(session, tg_id, "remain")
        if now.weekday() == cfg["WEEKLY_SUMMARY_DOW"]:
            last_weekly = await last_notification(session, tg_id, "weekly")
            week_start_date = now.date() - timedelta(days=now.weekday())
            week_start = datetime.combine(week_start_date, datetime.min.time())
            if not last_weekly or last_weekly < week_start:
                prev_steps = await calculate_steps(session, tg_id, until=week_start)
                delta = steps - prev_steps
                await bot.send_message(
                    tg_id,
                    texts.WEEKLY_SUMMARY.format(steps=steps, delta=delta),
                )
                await log_notification(session, tg_id, "weekly")


async def _check_caps(session: AsyncSession, tg_id: int, reward: dict[str, Any]) -> bool:
    if reward.get("type") == "days":
        start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        res = await session.execute(
            select(func.coalesce(func.sum(AchvReward.reward_value), 0)).where(
                AchvReward.tg_id == tg_id,
                AchvReward.reward_type == "days",
                AchvReward.granted_at >= start,
            )
        )
        total = res.scalar_one()
        cap = settings.ACHV["CAPS"]["USER_DAYS_CAP_PER_MONTH"]
        if total + reward.get("value", 0) > cap:
            return False

        share_pct = settings.ACHV["CAPS"].get("REF_SHARE_CAP_PCT")
        if share_pct:
            ref_sum = await session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Referral, Referral.referred_tg_id == Payment.tg_id)
                .where(
                    Referral.referrer_tg_id == tg_id,
                    Payment.created_at >= start,
                    Payment.status == "paid",
                )
            )
            ref_total = ref_sum.scalar_one()
            day_price = settings.ACHV.get("DAY_PRICE", 1)
            limit = ceil(ref_total * share_pct / 100 / day_price)
            if total + reward.get("value", 0) > limit:
                return False
    return True


async def _cached_steps(
    session: AsyncSession, tg_id: int, *, now: datetime | None = None
) -> int:
    now = now or datetime.utcnow()
    cached = _STEP_CACHE.get(tg_id)
    if cached and now - cached[1] < timedelta(days=1):
        return cached[0]
    steps = await calculate_steps(
        session,
        tg_id,
        until=now,
        apply_payment_anchor=False,
    )
    _STEP_CACHE[tg_id] = (steps, now)
    return steps


async def get_top(session: AsyncSession, limit: int = 5) -> list[dict[str, Any]]:
    """Return top users sorted by steps."""
    since = datetime.utcnow().date() - timedelta(days=30)
    tg_ids = await active_users(session, since)
    if not tg_ids:
        return []
    rows = await session.execute(
        select(User.tg_id, User.username).where(User.tg_id.in_(tg_ids))
    )
    now = datetime.utcnow()
    leaders: list[dict[str, Any]] = []
    for tg_id, username in rows.all():
        steps = await _cached_steps(session, tg_id, now=now)
        leaders.append({"tg_id": tg_id, "username": username, "steps": steps})
    leaders.sort(key=lambda x: x["steps"], reverse=True)
    return leaders[:limit]
