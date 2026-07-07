"""Server-side address suggestions via configured geocoding provider."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from flask import current_app

logger = logging.getLogger(__name__)

_DIGITRANSIT_AUTOCOMPLETE_URL = "https://api.digitransit.fi/geocoding/v1/autocomplete"
_DIGITRANSIT_SEARCH_URL = "https://api.digitransit.fi/geocoding/v1/search"
_DIGITRANSIT_LAYERS = "address,street"
_MIN_QUERY_LEN = 3
_MAX_LIMIT = 10
_CACHE_TTL_SECONDS = 600
_RESPONSE_LOG_MAX_LEN = 800
_POSTAL_CODE_RE = re.compile(r"\b(\d{5})\b")

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_VALTION_DEV_FIXTURE: dict[str, Any] = {
    "label": "Valtiontie 1, 60800 Ilmajoki",
    "street": "Valtiontie 1",
    "postal_code": "60800",
    "city": "Ilmajoki",
    "lat": None,
    "lon": None,
}


def _mask_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return "missing"
    if len(key) <= 8:
        return f"set(len={len(key)})"
    return f"set({key[:4]}…{key[-4:]}, len={len(key)})"


def _truncate_for_log(value: Any, *, max_len: int = _RESPONSE_LOG_MAX_LEN) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(value)
    text = text.replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _dev_fallback_enabled() -> bool:
    if current_app.config.get("GEOCODING_DEV_FALLBACK"):
        return True
    return bool(current_app.debug)


def _dev_fallback_suggestions(query: str) -> list[dict[str, Any]]:
    if not _dev_fallback_enabled():
        return []
    q = (query or "").strip().casefold()
    if q.startswith("valtion") or q.startswith("valtio"):
        logger.info(
            "geocoding dev fallback used for query=%r (GEOCODING_DEV_FALLBACK or DEBUG)",
            query,
        )
        return [dict(_VALTION_DEV_FIXTURE)]
    return []


def suggest_addresses(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return normalized address suggestions or an empty list on misconfiguration/errors."""

    text = (query or "").strip()
    provider = (current_app.config.get("GEOCODING_PROVIDER") or "digitransit").strip().lower()
    api_key = (current_app.config.get("GEOCODING_API_KEY") or "").strip()
    has_api_key = bool(api_key)

    logger.info(
        "geocoding suggest query=%r provider=%s api_key=%s",
        text,
        provider,
        _mask_api_key(api_key),
    )

    if len(text) < _MIN_QUERY_LEN:
        logger.debug("geocoding skipped: query shorter than %d chars", _MIN_QUERY_LEN)
        return []

    if not has_api_key:
        logger.warning(
            "geocoding skipped: GEOCODING_API_KEY missing at runtime "
            "(set env on server, not only in .env.example)"
        )
        return _dev_fallback_suggestions(text)

    safe_limit = max(1, min(int(limit), _MAX_LIMIT))
    cache_key = f"{provider}:{text.casefold()}:{safe_limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("geocoding cache hit query=%r count=%d", text, len(cached))
        return cached

    results: list[dict[str, Any]] = []
    try:
        if provider == "digitransit":
            results = _digitransit_suggest(text, safe_limit, api_key=api_key)
        else:
            logger.warning("geocoding unsupported provider=%s query=%r", provider, text)
    except Exception:  # noqa: BLE001
        logger.exception("geocoding suggest failed provider=%s query=%r", provider, text)
        results = []

    if not results:
        logger.info(
            "geocoding empty result provider=%s query=%r parsed=0 "
            "(check Digitransit logs above for HTTP status, raw feature count, and parse drops)",
            provider,
            text,
        )
        results = _dev_fallback_suggestions(text)

    logger.info("geocoding suggest done query=%r count=%d", text, len(results))
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
    headers = {
        "Accept": "application/json",
        "digitransit-subscription-key": api_key,
    }
    timeout = int(current_app.config.get("GEOCODING_TIMEOUT_SECONDS", 5))

    for endpoint_name, url in (
        ("autocomplete", _DIGITRANSIT_AUTOCOMPLETE_URL),
        ("search", _DIGITRANSIT_SEARCH_URL),
    ):
        raw_features, parsed = _digitransit_request(
            endpoint_name=endpoint_name,
            url=url,
            text=text,
            limit=limit,
            headers=headers,
            timeout=timeout,
        )
        if parsed:
            return parsed
        if raw_features:
            logger.info(
                "geocoding digitransit %s had %d features but none parsed for query=%r",
                endpoint_name,
                len(raw_features),
                text,
            )

    return []


def _digitransit_request(
    *,
    endpoint_name: str,
    url: str,
    text: str,
    limit: int,
    headers: dict[str, str],
    timeout: int,
) -> tuple[list[Any], list[dict[str, Any]]]:
    params = {
        "text": text,
        "size": limit,
        "layers": _DIGITRANSIT_LAYERS,
        "lang": "fi",
    }
    logger.info(
        "geocoding digitransit %s request query=%r layers=%s",
        endpoint_name,
        text,
        params["layers"],
    )

    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    status = getattr(response, "status_code", 200)
    body_preview = _truncate_for_log(getattr(response, "text", ""))

    logger.info(
        "geocoding digitransit %s HTTP %s query=%r body=%s",
        endpoint_name,
        status,
        text,
        body_preview,
    )

    if status == 401:
        logger.warning(
            "geocoding digitransit %s unauthorized query=%r "
            "(invalid or missing digitransit-subscription-key header)",
            endpoint_name,
            text,
        )
        response.raise_for_status()

    response.raise_for_status()

    try:
        body = response.json()
    except ValueError as exc:
        logger.warning(
            "geocoding digitransit %s invalid JSON query=%r error=%s body=%s",
            endpoint_name,
            text,
            exc,
            body_preview,
        )
        return [], []

    if not isinstance(body, dict):
        logger.warning(
            "geocoding digitransit %s unexpected body type query=%r body=%s",
            endpoint_name,
            text,
            _truncate_for_log(body),
        )
        return [], []

    features = body.get("features")
    if not isinstance(features, list):
        logger.info(
            "geocoding digitransit %s no features array query=%r keys=%s",
            endpoint_name,
            text,
            list(body.keys()),
        )
        return [], []

    logger.info(
        "geocoding digitransit %s query=%r raw_features=%d",
        endpoint_name,
        text,
        len(features),
    )

    parsed = _parse_digitransit_features(features, limit=limit)
    logger.info(
        "geocoding digitransit %s query=%r parsed_features=%d",
        endpoint_name,
        text,
        len(parsed),
    )
    return features, parsed


def _parse_digitransit_features(
    features: list[Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
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


def _normalize_postal_code(raw: Any) -> str:
    if raw is None or raw == "":
        return ""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, (int, float)):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return ""
        return str(value).zfill(5) if 0 <= value < 100000 else str(value)
    text = str(raw).strip()
    if text.isdigit() and len(text) < 5:
        return text.zfill(5)
    return text


def _parse_label_postal_and_city(label: str) -> tuple[str, str]:
    match = _POSTAL_CODE_RE.search(label)
    if not match:
        return "", ""
    postal_code = match.group(1)
    tail = label[match.end() :].strip(" ,")
    city = tail.split(",")[-1].strip() if tail else ""
    return postal_code, city


def _digitransit_properties(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties")
    if not isinstance(props, dict):
        return {}

    parts = props.get("address_parts")
    if not isinstance(parts, dict):
        return props

    merged = dict(props)
    if not merged.get("street") and parts.get("street"):
        merged["street"] = parts["street"]
    if not merged.get("housenumber"):
        merged["housenumber"] = parts.get("number") or parts.get("housenumber")
    if merged.get("postalcode") in (None, ""):
        merged["postalcode"] = parts.get("zip") or parts.get("postalcode")
    return merged


def _street_line_from_props(props: dict[str, Any], *, layer: str) -> str:
    housenumber = str(props.get("housenumber") or props.get("number") or "").strip()
    street = str(props.get("street") or "").strip()
    name = str(props.get("name") or "").strip()

    if layer == "address" and name:
        return name
    if street and housenumber:
        return f"{street} {housenumber}".strip()
    if name and housenumber:
        return f"{name} {housenumber}".strip()
    if name:
        return name
    return street or housenumber


def _parse_digitransit_feature(feature: dict[str, Any]) -> dict[str, Any] | None:
    props = _digitransit_properties(feature)
    if not props:
        return None

    layer = str(props.get("layer") or "").strip().lower()

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

    street_line = _street_line_from_props(props, layer=layer)
    label = str(props.get("label") or street_line or "").strip()
    postal_code = _normalize_postal_code(props.get("postalcode"))
    city = str(
        props.get("locality") or props.get("localadmin") or props.get("region") or ""
    ).strip()

    if not postal_code or not city:
        label_postal, label_city = _parse_label_postal_and_city(label)
        if not postal_code:
            postal_code = label_postal
        if not city:
            city = label_city

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
