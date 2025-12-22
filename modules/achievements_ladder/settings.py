ACHV = {
    "ENABLED": True,
    "BUTTON_VISIBILITY": {
        "MODE": "RESTRICTED",  # ALL | RESTRICTED
        "ALLOWED_IDS": [],
    },
    "WEIGHTS": {
        "INVITE": 1,
        "SELF_PAY": {1: 1, 3: 3, 6: 6, 12: 12},
        "REF_PAY": {1: 1, 3: 3, 6: 6, 12: 12},
        "JOIN_CHANNEL": 2,
        "DAILY": 0.1,
        "STREAK7": 1,
    },
    "THRESHOLDS": [
        {"steps": 5, "reward": {"type": "days", "value": 3}},
        {"steps": 10, "reward": {"type": "days", "value": 7}},
        {"steps": 20, "reward": {"type": "days", "value": 30}},
        {"steps": 35, "reward": {"type": "days", "value": 14}},
        {"steps": 50, "reward": {"type": "days", "value": 30}, "announce": True},
    ],
    "CAPS": {
        "USER_DAYS_CAP_PER_MONTH": 30,
        "REF_SHARE_CAP_PCT": 30,
        "DAILY_STEPS_CAP_PER_MONTH": 3,
    },
    "DAY_PRICE": 5,  # руб/день
    "AFTER_50": {"MODE": "NONE"},  # NONE | SOFT_RESET | HARD_RESET
    "SEASON": {"MODE": "ALL_TIME", "LENGTH_WEEKS": 8},
    "DAILY": {"ENABLED": True, "REQUIRE_REDIS_PERSISTENCE": True},
    "NOTIFY": {
        "REMAIN_MAX": 2,
        "PERIOD_HOURS": 24,
        "MAX_PER_WEEK": 3,
        "ACTIVE_DAYS": 30,
        "WEEKLY_SUMMARY_DOW": 1,
        "HOUR_MSK": 10,
        "MINUTE": 0,
    },
    "ANNOUNCE_CHANNEL_ID": -1002289096114,
    # Необязательно, но нужно для кнопки "Открыть канал" и текстовых подсказок
    "ANNOUNCE_CHANNEL_LINK": "https://t.me/vlesswb",
    "ANNOUNCE_TEMPLATE": "🏆 @{{username}} дошёл до 50‑й ступени! Дарим +{{days}} дней ✨",
}
