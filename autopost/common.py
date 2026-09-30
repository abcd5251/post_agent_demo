"""Shared helpers: env vars, logging, time."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

import config

BASE_DIR = Path(__file__).resolve().parent.parent
TZ = ZoneInfo(config.TIMEZONE)

load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    pass


def env(name, required=True):
    value = os.getenv(name, "").strip()
    if required and not value:
        raise ConfigError(f"missing environment variable: {name}")
    return value


def now():
    return datetime.now(TZ)


def log(msg):
    print(f"[{now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def at_time(day, hhmm):
    """datetime for `day` (a date) at "HH:MM" in TZ."""
    hour, minute = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def post_time_for(style, day):
    """The post time string ("YYYY-MM-DD HH:MM") for a copy style generated on `day`."""
    return at_time(day + timedelta(days=style["post_day_offset"]), style["post_time"]).strftime(
        "%Y-%m-%d %H:%M")


def parse_post_time(value):
    """Parse a post_time cell: "YYYY-MM-DD HH:MM" (also "/" and seconds), or a Google
    Sheets date serial number (what a hand-typed date becomes)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        naive = datetime(1899, 12, 30) + timedelta(minutes=round(value * 24 * 60))
        return naive.replace(tzinfo=TZ)
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    raise ValueError(f"post_time {text!r} is not in YYYY-MM-DD HH:MM format")
