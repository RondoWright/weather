from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

import requests


DATE_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_MDY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
DATE_NATURAL_RE = re.compile(
    r"\b(?:on\s+)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:,\s*(\d{4}))?\b",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|today|tomorrow)\b",
    re.IGNORECASE,
)

CITY_PATTERNS = [
    re.compile(
        r"\b(?:in|at|for)\s+([A-Za-z][A-Za-z\.\-'\s]{1,60}?)(?=\s+(?:on|by|before|after|through|during|if|when|will|with|above|below|over|under|this|next|tomorrow|today)\b|[?.!,]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwill\s+([A-Za-z][A-Za-z\.\-'\s]{1,50}?)\s+(?:hit|reach|get|see|have)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b([A-Za-z][A-Za-z\.\-']+(?:\s+[A-Za-z][A-Za-z\.\-']+){0,3}),\s*([A-Z]{2})\b"),
]

TEMP_SYMBOL_RE = re.compile(r"(>=|<=|>|<)\s*(-?\d{1,3})\s*°?\s*([fc])?", re.IGNORECASE)
TEMP_WORD_RE = re.compile(
    r"(?:above|over|at\s+least|greater\s+than|below|under|at\s+most|less\s+than)\s+(-?\d{1,3})\s*(?:°?\s*([fc])|degrees?)?",
    re.IGNORECASE,
)
TEMP_REACH_RE = re.compile(r"(?:hit|reach|get to|top|high of)\s+(-?\d{1,3})\s*(?:°?\s*([fc]))?", re.IGNORECASE)

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

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

STOP_TOKENS = {
    "temperature",
    "temp",
    "rain",
    "snow",
    "weather",
    "degrees",
    "degree",
    "will",
    "be",
    "is",
}


def _fahrenheit_to_celsius(value_f: float) -> float:
    return (value_f - 32.0) * 5.0 / 9.0


def _candidate_cities(question: str) -> list[str]:
    out: list[str] = []
    for pattern in CITY_PATTERNS:
        for match in pattern.finditer(question):
            if pattern is CITY_PATTERNS[2]:
                city = f"{match.group(1).strip()}, {match.group(2).strip()}"
            else:
                city = match.group(1).strip(" ,.?")
            if not city:
                continue
            lower_city = city.lower()
            if lower_city in STOP_TOKENS:
                continue
            if len(city) < 2:
                continue
            out.append(city)

    # Last fallback: title-case sequence before "weather/rain/temp" tokens.
    fallback = re.search(
        r"\b([A-Z][A-Za-z\.\-']+(?:\s+[A-Z][A-Za-z\.\-']+){0,3})\b(?=\s+(?:weather|rain|snow|temperature|temp)\b)",
        question,
    )
    if fallback:
        out.append(fallback.group(1).strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for city in out:
        key = city.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(city)
    return deduped


def _parse_weekday_date(token: str, today: dt.date) -> list[dt.date]:
    token = token.lower()
    if token == "today":
        return [today]
    if token == "tomorrow":
        return [today + dt.timedelta(days=1)]
    if token == "weekend":
        # Next Saturday/Sunday window.
        delta_to_sat = (5 - today.weekday()) % 7
        sat = today + dt.timedelta(days=delta_to_sat)
        return [sat, sat + dt.timedelta(days=1)]
    target_weekday = WEEKDAY_MAP.get(token)
    if target_weekday is None:
        return []
    delta = (target_weekday - today.weekday()) % 7
    return [today + dt.timedelta(days=delta)]


def _extract_target_dates(question: str) -> list[dt.date] | None:
    today = dt.datetime.utcnow().date()

    iso_match = DATE_ISO_RE.search(question)
    if iso_match:
        try:
            return [dt.date.fromisoformat(iso_match.group(1))]
        except ValueError:
            pass

    natural_match = DATE_NATURAL_RE.search(question)
    if natural_match:
        month_token = natural_match.group(1)[:3].lower()
        day = int(natural_match.group(2))
        explicit_year = natural_match.group(3)
        month = MONTHS.get(month_token)
        if month is not None:
            year = int(explicit_year) if explicit_year else today.year
            try:
                candidate = dt.date(year, month, day)
                if not explicit_year and candidate < today:
                    candidate = dt.date(year + 1, month, day)
                return [candidate]
            except ValueError:
                pass

    mdy_match = DATE_MDY_RE.search(question)
    if mdy_match:
        month = int(mdy_match.group(1))
        day = int(mdy_match.group(2))
        year_raw = mdy_match.group(3)
        year = today.year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        try:
            candidate = dt.date(year, month, day)
            if not year_raw and candidate < today:
                candidate = dt.date(year + 1, month, day)
            return [candidate]
        except ValueError:
            pass

    weekday_match = WEEKDAY_RE.search(question)
    if weekday_match:
        dates = _parse_weekday_date(weekday_match.group(1), today)
        return dates or None
    return None


def _infer_temp_unit(raw_value: float, raw_unit: str | None, question: str) -> str:
    if raw_unit:
        return raw_unit.lower()
    q = question.lower()
    if "fahrenheit" in q:
        return "f"
    if "celsius" in q or "centigrade" in q:
        return "c"
    # Numeric heuristic: very high thresholds are usually Fahrenheit.
    if abs(raw_value) > 55:
        return "f"
    return "c"


def _extract_temp_rule(question: str) -> tuple[str, float] | None:
    q = question.lower()
    if "below freezing" in q or "under freezing" in q:
        return ("<=", 0.0)
    if "above freezing" in q:
        return (">=", 0.0)

    symbol_match = TEMP_SYMBOL_RE.search(question)
    if symbol_match:
        op = symbol_match.group(1)
        value_raw = float(symbol_match.group(2))
        unit = _infer_temp_unit(value_raw, symbol_match.group(3), question)
        value_c = _fahrenheit_to_celsius(value_raw) if unit == "f" else value_raw
        op_norm = ">=" if op in {">", ">="} else "<="
        return op_norm, value_c

    word_match = TEMP_WORD_RE.search(question)
    if word_match:
        phrase = word_match.group(0).lower()
        value_raw = float(word_match.group(1))
        unit = _infer_temp_unit(value_raw, word_match.group(2), question)
        value_c = _fahrenheit_to_celsius(value_raw) if unit == "f" else value_raw
        if any(token in phrase for token in ("above", "over", "at least", "greater than")):
            return (">=", value_c)
        return ("<=", value_c)

    reach_match = TEMP_REACH_RE.search(question)
    if reach_match:
        value_raw = float(reach_match.group(1))
        unit = _infer_temp_unit(value_raw, reach_match.group(2), question)
        value_c = _fahrenheit_to_celsius(value_raw) if unit == "f" else value_raw
        return (">=", value_c)

    return None


def _is_precip_market(question: str) -> bool:
    q = question.lower()
    return any(token in q for token in ("rain", "precip", "storm", "thunder", "shower"))


def _is_snow_market(question: str) -> bool:
    q = question.lower()
    return any(token in q for token in ("snow", "blizzard", "sleet", "flurr"))


def _pick_window(
    timeline: list[dt.datetime],
    values: list[float],
    target_dates: list[dt.date] | None,
    lookahead_hours: int,
) -> list[float]:
    now = dt.datetime.utcnow().replace(tzinfo=None)
    out: list[float] = []

    if target_dates:
        date_set = set(target_dates)
        for ts, value in zip(timeline, values):
            if ts.date() in date_set:
                out.append(value)
        return out

    horizon = now + dt.timedelta(hours=lookahead_hours)
    for ts, value in zip(timeline, values):
        if now <= ts <= horizon:
            out.append(value)
    return out


def _calc_confidence(prob: float, sample_count: int, boost: float = 1.0) -> float:
    dispersion = abs(prob - 0.5) * 2
    coverage = min(sample_count / 24.0, 1.0)
    confidence = (0.35 + 0.45 * dispersion + 0.2 * coverage) * boost
    return max(0.05, min(confidence, 0.98))


def _temperature_probability(temp_values: list[float], rule: tuple[str, float]) -> float:
    if not temp_values:
        return 0.5
    op, threshold = rule
    if op == ">=":
        extreme = max(temp_values)
        satisfied = [v for v in temp_values if v >= threshold]
        margin = extreme - threshold
    else:
        extreme = min(temp_values)
        satisfied = [v for v in temp_values if v <= threshold]
        margin = threshold - extreme

    frequency_prob = len(satisfied) / len(temp_values)
    margin_prob = 1.0 / (1.0 + math.exp(-margin / 2.0))
    return max(0.0, min(0.6 * margin_prob + 0.4 * frequency_prob, 1.0))


def _precip_probability(precip_probs: list[float]) -> float:
    if not precip_probs:
        return 0.5
    hourly = [max(0.0, min(v / 100.0, 1.0)) for v in precip_probs]
    any_prob = 1.0
    for p in hourly:
        any_prob *= (1.0 - p)
    any_prob = 1.0 - any_prob
    max_prob = max(hourly)
    avg_prob = sum(hourly) / len(hourly)
    return max(0.0, min(0.55 * max_prob + 0.35 * any_prob + 0.10 * avg_prob, 1.0))


def _resolve_location(question: str, cfg: dict[str, Any], timeout: int) -> tuple[dict[str, Any] | None, str]:
    weather_cfg = cfg["weather"]
    city_candidates = _candidate_cities(question)
    if not city_candidates:
        return None, "Could not parse city from market question."

    for city in city_candidates:
        geo_resp = requests.get(
            str(weather_cfg["geocode_url"]),
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=timeout,
        )
        geo_resp.raise_for_status()
        geo_results = geo_resp.json().get("results") or []
        if geo_results:
            return geo_results[0], city

    return None, f"Could not geocode parsed city candidates: {city_candidates}"


def estimate_yes_probability(question: str, cfg: dict[str, Any]) -> tuple[float, float, str]:
    weather_cfg = cfg["weather"]
    bot_cfg = cfg["bot"]
    timeout = int(bot_cfg["request_timeout_seconds"])
    lookahead_hours = int(weather_cfg["lookahead_hours"])

    place, parsed_city = _resolve_location(question, cfg, timeout)
    if not place:
        return 0.5, 0.15, parsed_city

    latitude = float(place["latitude"])
    longitude = float(place["longitude"])
    normalized_city = str(place.get("name") or parsed_city)
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

    target_dates = _extract_target_dates(question)
    temp_rule = _extract_temp_rule(question)
    precip_market = _is_precip_market(question)
    snow_market = _is_snow_market(question)

    if temp_rule and not precip_market and not snow_market:
        temp_window = _pick_window(timestamps, temps, target_dates, lookahead_hours)
        model_prob = _temperature_probability(temp_window, temp_rule)
        confidence = _calc_confidence(model_prob, len(temp_window), boost=1.0)
        op, threshold_c = temp_rule
        rationale = (
            f"{location_label}: temp rule {op} {threshold_c:.1f}C, "
            f"points={len(temp_window)}, dates={target_dates or 'next-window'}, model_prob={model_prob:.3f}"
        )
        return model_prob, confidence, rationale

    precip_window = _pick_window(timestamps, precip_probs, target_dates, lookahead_hours)
    if not precip_window:
        return 0.5, 0.2, f"{location_label}: no precipitation window available."

    model_prob = _precip_probability(precip_window)
    confidence_boost = 0.85

    if snow_market:
        temp_window = _pick_window(timestamps, temps, target_dates, lookahead_hours)
        if temp_window:
            freezing_share = len([t for t in temp_window if t <= 0.0]) / len(temp_window)
            model_prob *= max(0.15, min(1.0, freezing_share * 1.3))
        confidence_boost = 0.75

    confidence = _calc_confidence(model_prob, len(precip_window), boost=confidence_boost)
    market_type = "snow proxy" if snow_market else "precip proxy"
    rationale = (
        f"{location_label}: {market_type}, points={len(precip_window)}, "
        f"dates={target_dates or 'next-window'}, model_prob={model_prob:.3f}"
    )
    return model_prob, confidence, rationale

