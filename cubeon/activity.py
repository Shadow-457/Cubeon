"""Bounded local activity history, honest period summaries, and display badges."""
from datetime import date, datetime, time as day_time, timedelta
import math
import time

HISTORY_DAYS = 400
METRICS = ("seconds_played", "sessions_played", "sessions_hosted")
PERIODS = (
    ("recent_week", "Last 7 days"),
    ("previous_week", "Previous 7 days"),
    ("recent_month", "Last 30 days"),
    ("previous_month", "Previous 30 days"),
)


def nonnegative(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def clean_history(value):
    history = {}
    if not isinstance(value, dict):
        return history
    for key, bucket in value.items():
        if not isinstance(key, str) or not isinstance(bucket, dict):
            continue
        try:
            if date.fromisoformat(key).isoformat() != key:
                continue
        except ValueError:
            continue
        history[key] = {metric: nonnegative(bucket.get(metric)) for metric in METRICS}
    return {key: history[key] for key in sorted(history)[-HISTORY_DAYS:]}


def record_playtime(state, seconds, started_at=None, *, completed=False):
    seconds = min(nonnegative(seconds), 86400 * 14)
    if not seconds:
        return
    started = time.time() - seconds if started_at is None else started_at
    try:
        started = float(started)
        datetime.fromtimestamp(started)
        datetime.fromtimestamp(started + seconds)
    except (TypeError, ValueError, OverflowError, OSError):
        started = time.time() - seconds
    history = clean_history(state.get("activity"))
    cursor, finish = started, started + seconds
    last_day = None
    while cursor < finish:
        current_day = datetime.fromtimestamp(cursor).date()
        next_midnight = datetime.combine(current_day + timedelta(days=1), day_time.min).timestamp()
        stop = min(finish, next_midnight)
        last_day = current_day.isoformat()
        bucket = history.setdefault(last_day, dict.fromkeys(METRICS, 0))
        bucket["seconds_played"] += stop - cursor
        cursor = stop
    if completed:
        history[last_day]["sessions_played"] += 1
        state["sessions_played"] = int(nonnegative(state.get("sessions_played"))) + 1
    state["activity"] = clean_history(history)


def record_hosting(state, timestamp=None):
    history = clean_history(state.get("activity"))
    key = datetime.fromtimestamp(time.time() if timestamp is None else timestamp).date().isoformat()
    bucket = history.setdefault(key, dict.fromkeys(METRICS, 0))
    bucket["sessions_hosted"] += 1
    state["activity"] = clean_history(history)


def period_summary(state, period="recent_week", *, today=None):
    today = today or date.today()
    windows = {"recent_week": (7, 0), "previous_week": (7, 7),
               "recent_month": (30, 0), "previous_month": (30, 30)}
    days, offset = windows.get(period, windows["recent_week"])
    end = today - timedelta(days=offset)
    start = end - timedelta(days=days - 1)
    history = clean_history(state.get("activity"))
    dates = [(start + timedelta(days=index)).isoformat() for index in range(days)]
    rows = [history.get(key, {}) for key in dates]
    summary = {metric: sum(nonnegative(row.get(metric)) for row in rows) for metric in METRICS}
    summary.update(label=dict(PERIODS).get(period, dict(PERIODS)["recent_week"]),
                   dates=dates, hours=[nonnegative(row.get("seconds_played")) / 3600 for row in rows],
                   active_days=sum(nonnegative(row.get("seconds_played")) > 0 for row in rows))
    return summary


def earned_badges(state, collections=None):
    tracks = (
        ("playtime", "seconds_played", ((3600, "Explorer", "1 hour in game"),
         (36000, "Regular", "10 hours in game"), (360000, "Veteran", "100 hours in game"))),
        ("hosting", "sessions_hosted", ((1, "Host", "Hosted a session"),
         (10, "World builder", "Hosted 10 sessions"), (50, "Community host", "Hosted 50 sessions"))),
        ("friends", "friends_count_high", ((1, "Connected", "Made a friend"),
         (5, "Social", "Reached 5 friends"), (20, "Community", "Reached 20 friends"))),
    )
    badges = []
    for key, metric, tiers in tracks:
        value = nonnegative(state.get(metric))
        eligible = [tier for tier in tiers if value >= tier[0]]
        if eligible:
            threshold, label, detail = eligible[-1]
            badges.append({"key": key, "label": label, "detail": detail, "threshold": threshold})
    collections = collections or {}
    for key, label, noun in (
        ("versions", "Version explorer", "versions installed"),
        ("mods", "Mod collector", "mods installed"),
        ("packs", "Pack player", "modpacks installed"),
        ("content", "Pack collector", "packs and shaders"),
        ("plugins", "Server builder", "server plugins"),
        ("skins", "Skin stylist", "custom skins"),
        ("capes", "Cape collector", "custom capes"),
    ):
        count = int(nonnegative(collections.get(key)))
        if count:
            badges.append({"key": key, "label": label, "detail": f"{count:,} {noun}", "threshold": 1})
    first_seen = nonnegative(state.get("first_seen_at"))
    if first_seen:
        try:
            detail = "Playing since " + datetime.fromtimestamp(first_seen).strftime("%b %d, %Y")
            badges.append({"key": "member", "label": "Member", "detail": detail, "threshold": 0})
        except (ValueError, OverflowError, OSError):
            pass
    return badges
