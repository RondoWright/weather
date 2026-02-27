from __future__ import annotations

import datetime as dt
import re
from typing import Any

import requests


CITY_RE = re.compile(r"\bin\s+([A-Za-z][A-Za-z\.\-'\s]{1,40})", re.IGNORECASE)
TEMP_RE = re.compile(
    r"(?:above|over|at\s+least|greater\s+than|below|under|at\s+most|less\s+than)\s+(-?\d{1,3})\s*(?:°?\s*([fc])|degrees?)?",
    re.IGNORECASE,
)
DATE_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_NATURAL_RE = re.compile(
    r"\b(?:on\s+)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})\b",
    re.IGNORECASE,
)


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _fahrenheit_to_celsius(value_f: float) -> float:
    return (value_f - 32.0) * 5.0 / 9.0


def _extract_city(question: str) -> str | None:
    match = CITY_RE.search(question)
    if not match:
        return None
    city = re.split(r"\b(by|before|after|on|for|at)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[
        0
    ].strip(" ,.?")
    return city or None


def _extract_date(question: str) -> dt.date | None:
    iso_match = DATE_ISO_RE.search(question)
    if iso_match:
        try:
            return dt.date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass

    natural_match = DATE_NATURAL_RE.search(question)
    if not natural_match:
        return None

    month_token = natural_match.group(1)[:3].lower()
    day = int(natural_match.group(2))
    month = MONTHS.get(month_token)
    if month is None:
        return None

    today = dt.datetime.utcnow().date()
    year = today.year
    try:
        candidate = dt.date(year, month, day)
    except ValueError:
        return None
    if candidate < today:
        try:
            candidate = dt.date(year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _extract_temp_rule(question: str) -> tuple[str, float] | None:
    match = TEMP_RE.search(question)
    if not match:
        return None

    phrase = match.group(0).lower()
    threshold_raw = float(match.group(1))
    unit = (match.group(2) or "").lower()
    threshold_c = _fahrenheit_to_celsius(threshold_raw) if unit == "f" else threshold_raw

    if any(token in phrase for token in ("above", "over", "at least", "greater than")):
        return (">=", threshold_c)
    return ("<=", threshold_c)


def _pick_window(
    timeline: list[dt.datetime], values: list[float], target_date: dt.date | None, lookahead_hours: int
) -> list[float]:
    now = dt.datetime.utcnow().replace(tzinfo=None)
    out: list[float] = []

    if target_date is not None:
        for ts, value in zip(timeline, values):
            if ts.date() == target_date:
                out.append(value)
        return out

    horizon = now + dt.timedelta(hours=lookahead_hours)
    for ts, value in zip(timeline, values):
        if now <= ts <= horizon:
            out.append(value)
    return out


def _calc_probability(temp_values: list[float], rule: tuple[str, float]) -> float:
    if not temp_values:
        return 0.5
    op, threshold = rule
    if op == ">=":
        hits = [v for v in temp_values if v >= threshold]
    else:
        hits = [v for v in temp_values if v <= threshold]
    return len(hits) / len(temp_values)


def _calc_confidence(prob: float, sample_count: int) -> float:
    dispersion = abs(prob - 0.5) * 2
    coverage = min(sample_count / 24.0, 1.0)
    confidence = 0.35 + 0.45 * dispersion + 0.2 * coverage
    return max(0.05, min(confidence, 0.98))


def estimate_yes_probability(question: str, cfg: dict[str, Any]) -> tuple[float, float, str]:
    weather_cfg = cfg["weather"]
    bot_cfg = cfg["bot"]
    timeout = int(bot_cfg["request_timeout_seconds"])
    lookahead_hours = int(weather_cfg["lookahead_hours"])

    city = _extract_city(question)
    if not city:
        return 0.5, 0.15, "Could not parse city from market question."

    geo_resp = requests.get(
        str(weather_cfg["geocode_url"]),
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=timeout,
    )
    geo_resp.raise_for_status()
    geo_results = geo_resp.json().get("results") or []
    if not geo_results:
        return 0.5, 0.15, f"Could not geocode city '{city}'."

    place = geo_results[0]
    latitude = float(place["latitude"])
    longitude = float(place["longitude"])
    normalized_city = str(place.get("name") or city)
    country = str(place.get("country") or "")
    location_label = f"{normalized_city}, {country}".strip(", ")

    forecast_resp = requests.get(
        str(weather_cfg["forecast_url"]),
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation_probability",
            "forecast_days": 16,
            "timezone": "UTC",
        },
        timeout=timeout,
    )
    forecast_resp.raise_for_status()
    hourly = forecast_resp.json().get("hourly") or {}

    timestamps = [dt.datetime.fromisoformat(x) for x in hourly.get("time") or []]
    temps = [float(x) for x in hourly.get("temperature_2m") or []]
    precip_probs = [float(x) for x in hourly.get("precipitation_probability") or []]

    if not timestamps or not temps:
        return 0.5, 0.2, f"No hourly forecast returned for {location_label}."

    target_date = _extract_date(question)
    rule = _extract_temp_rule(question)

    if rule:
        temp_window = _pick_window(timestamps, temps, target_date, lookahead_hours)
        model_prob = _calc_probability(temp_window, rule)
        confidence = _calc_confidence(model_prob, len(temp_window))
        op, threshold_c = rule
        rationale = (
            f"{location_label}: temp rule {op} {threshold_c:.1f}C, "
            f"window points={len(temp_window)}, model_prob={model_prob:.3f}"
        )
        return model_prob, confidence, rationale

    # Fallback for rain-style markets where no temperature threshold exists.
    precip_window = _pick_window(timestamps, precip_probs, target_date, lookahead_hours)
    if not precip_window:
        return 0.5, 0.2, f"{location_label}: no precipitation window available."
    model_prob = max(0.0, min(sum(precip_window) / len(precip_window) / 100.0, 1.0))
    confidence = _calc_confidence(model_prob, len(precip_window)) * 0.8
    rationale = (
        f"{location_label}: precip proxy used (no temp threshold parsed), "
        f"window points={len(precip_window)}, model_prob={model_prob:.3f}"
    )
    return model_prob, confidence, rationale

