"""Server-side address suggestions via configured geocoding provider."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from flask import current_app

logger = logging.getLogger(__name__)

_DIGITRANSIT_AUTOCOMPLETE_URL = "https://api.digitransit.fi/geocoding/v1/autocomplete"
_MIN_QUERY_LEN = 3
_MAX_LIMIT = 10
_CACHE_TTL_SECONDS = 600

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def suggest_addresses(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return normalized address suggestions or an empty list on misconfiguration/errors."""

    text = (query or "").strip()
    if len(text) < _MIN_QUERY_LEN:
        return []

    api_key = (current_app.config.get("GEOCODING_API_KEY") or "").strip()
    if not api_key:
        return []

    provider = (current_app.config.get("GEOCODING_PROVIDER") or "digitransit").strip().lower()
    safe_limit = max(1, min(int(limit), _MAX_LIMIT))

    cache_key = f"{provider}:{text.casefold()}:{safe_limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        if provider == "digitransit":
            results = _digitransit_suggest(text, safe_limit, api_key=api_key)
        else:
            logger.warning("Unsupported geocoding provider: %s", provider)
            results = []
    except Exception:  # noqa: BLE001
        logger.exception("Geocoding suggest failed for provider=%s", provider)
        results = []

    _cache_set(cache_key, results)
    return results


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() >= expires_at:
        _cache.pop(key, None)
        return None
    return list(value)


def _cache_set(key: str, value: list[dict[str, Any]]) -> None:
    _cache[key] = (time.time() + _CACHE_TTL_SECONDS, list(value))


def _digitransit_suggest(text: str, limit: int, *, api_key: str) -> list[dict[str, Any]]:
    timeout = int(current_app.config.get("GEOCODING_TIMEOUT_SECONDS", 5))
    response = requests.get(
        _DIGITRANSIT_AUTOCOMPLETE_URL,
        params={
            "text": text,
            "size": limit,
            "layers": "address",
            "lang": "fi",
        },
        headers={
            "Accept": "application/json",
            "digitransit-subscription-key": api_key,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        return []
    features = body.get("features")
    if not isinstance(features, list):
        return []

    out: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        parsed = _parse_digitransit_feature(feature)
        if parsed is not None:
            out.append(parsed)
        if len(out) >= limit:
            break
    return out


def _parse_digitransit_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = feature.get("properties")
    if not isinstance(props, dict):
        return None

    geometry = feature.get("geometry")
    coords: list[Any] = []
    if isinstance(geometry, dict) and isinstance(geometry.get("coordinates"), list):
        coords = geometry["coordinates"]

    lon = lat = None
    if len(coords) >= 2:
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            lon = lat = None

    housenumber = str(props.get("housenumber") or "").strip()
    street = str(props.get("street") or "").strip()
    if street and housenumber:
        street_line = f"{street} {housenumber}".strip()
    else:
        street_line = str(props.get("name") or street or housenumber or "").strip()

    postal_raw = props.get("postalcode")
    postal_code = str(postal_raw).strip() if postal_raw is not None else ""
    city = str(props.get("locality") or props.get("localadmin") or "").strip()
    label = str(props.get("label") or street_line or "").strip()

    if not label and not street_line:
        return None

    return {
        "label": label or street_line,
        "street": street_line or label,
        "postal_code": postal_code,
        "city": city,
        "lat": lat,
        "lon": lon,
    }
