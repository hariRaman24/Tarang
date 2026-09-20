"""
TARANG - INCOIS PFZ WFS Service / Inspector
===========================================

Connects to the official INCOIS GeoServer PFZ WFS layer:

    PFZ_Automation:pfzlines

This module is used by TARANG's live PFZ service and can also be run
directly as an endpoint inspector.

Reliability policy:
- Real INCOIS data only.
- No simulated PFZ fallback.
- HTTP 429/502/503/504 and timeouts are treated as transient.
- Transient failures are retried up to 4 times with short backoff.
- If the source still fails, TARANG returns UNAVAILABLE rather than
  inventing coordinates.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx


WFS_URL = (
    "https://incois.gov.in/geoserver/PFZ_Automation/ows"
)

WFS_PARAMS = {
    "service": "WFS",
    "version": "1.1.0",
    "request": "GetFeature",
    "typeName": "PFZ_Automation:pfzlines",
    "outputFormat": "application/json",
}

TIMEOUT_SECONDS = 30.0

_TRANSIENT_STATUS_CODES = {
    429,
    502,
    503,
    504,
}


class IncoisPFZWfsError(RuntimeError):
    """Raised when the INCOIS PFZ WFS cannot be read safely."""


def _iter_positions(
    coords: Any,
) -> Iterable[tuple[float, float]]:
    """
    Recursively yield coordinate pairs from GeoJSON coordinates.

    GeoJSON normally uses:
        [longitude, latitude]
    """

    if not isinstance(coords, list):
        return

    if (
        len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        yield float(coords[0]), float(coords[1])
        return

    for item in coords:
        yield from _iter_positions(item)


def _feature_bounds(
    features: list[dict[str, Any]],
) -> dict[str, float] | None:
    min_x = None
    min_y = None
    max_x = None
    max_y = None

    for feature in features:
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates")

        for x, y in _iter_positions(coords):
            min_x = x if min_x is None else min(min_x, x)
            min_y = y if min_y is None else min(min_y, y)
            max_x = x if max_x is None else max(max_x, x)
            max_y = y if max_y is None else max(max_y, y)

    if None in (min_x, min_y, max_x, max_y):
        return None

    return {
        "min_x": round(min_x, 6),
        "min_y": round(min_y, 6),
        "max_x": round(max_x, 6),
        "max_y": round(max_y, 6),
    }


def _property_summary(
    features: list[dict[str, Any]],
) -> dict[str, Any]:
    keys: set[str] = set()
    non_null_counts: Counter[str] = Counter()
    examples: dict[str, list[Any]] = {}

    for feature in features:
        props = feature.get("properties") or {}

        if not isinstance(props, dict):
            continue

        for key, value in props.items():
            keys.add(key)

            if value is not None and value != "":
                non_null_counts[key] += 1

                bucket = examples.setdefault(key, [])

                if len(bucket) < 5 and value not in bucket:
                    bucket.append(value)

    return {
        "keys": sorted(keys),
        "non_null_counts": dict(
            sorted(non_null_counts.items())
        ),
        "examples": {
            key: examples.get(key, [])
            for key in sorted(keys)
        },
    }


def _sample_feature(
    feature: dict[str, Any],
) -> dict[str, Any]:
    geometry = feature.get("geometry") or {}

    positions = list(
        _iter_positions(
            geometry.get("coordinates")
        )
    )

    return {
        "id": feature.get("id"),
        "geometry_type": geometry.get("type"),
        "first_coordinates": positions[:5],
        "properties": feature.get("properties") or {},
    }


def _validate_payload(
    payload: Any,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IncoisPFZWfsError(
            "INCOIS PFZ WFS returned an unexpected JSON structure."
        )

    if payload.get("type") != "FeatureCollection":
        raise IncoisPFZWfsError(
            "Expected a GeoJSON FeatureCollection, got "
            f"{payload.get('type')!r}."
        )

    features = payload.get("features")

    if not isinstance(features, list):
        raise IncoisPFZWfsError(
            "GeoJSON FeatureCollection has no valid features list."
        )

    return payload


async def _request_geojson(
    client: httpx.AsyncClient,
    *,
    attempts: int = 4,
) -> dict[str, Any]:
    """
    Fetch the official PFZ WFS with retry for temporary server failures.
    """

    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "application/json,application/geo+json,*/*",
    }

    last_error: Exception | None = None
    last_status: int | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(
                WFS_URL,
                params=WFS_PARAMS,
                headers=headers,
            )

            last_status = response.status_code

            if (
                response.status_code
                in _TRANSIENT_STATUS_CODES
            ):
                if attempt < attempts:
                    await asyncio.sleep(
                        1.5 * attempt
                    )
                    continue

                raise IncoisPFZWfsError(
                    "INCOIS PFZ WFS remained temporarily unavailable "
                    f"after {attempts} attempts "
                    f"(HTTP {response.status_code})."
                )

            response.raise_for_status()

            try:
                payload = response.json()
            except ValueError as exc:
                preview = response.text[:500]

                raise IncoisPFZWfsError(
                    "INCOIS PFZ WFS did not return valid JSON. "
                    f"Response preview: {preview!r}"
                ) from exc

            return _validate_payload(payload)

        except IncoisPFZWfsError:
            raise

        except httpx.TimeoutException as exc:
            last_error = exc

            if attempt < attempts:
                await asyncio.sleep(
                    1.5 * attempt
                )
                continue

        except httpx.HTTPStatusError as exc:
            last_error = exc

            # Non-transient HTTP errors should not be repeatedly hammered.
            raise IncoisPFZWfsError(
                "INCOIS PFZ WFS returned HTTP "
                f"{exc.response.status_code}."
            ) from exc

        except httpx.HTTPError as exc:
            last_error = exc

            if attempt < attempts:
                await asyncio.sleep(
                    1.5 * attempt
                )
                continue

    if isinstance(last_error, httpx.TimeoutException):
        raise IncoisPFZWfsError(
            "INCOIS PFZ WFS request timed out after "
            f"{attempts} attempts."
        ) from last_error

    if last_error is not None:
        raise IncoisPFZWfsError(
            "Unable to reach INCOIS PFZ WFS after "
            f"{attempts} attempts: {last_error}"
        ) from last_error

    raise IncoisPFZWfsError(
        "INCOIS PFZ WFS request failed"
        + (
            f" with HTTP {last_status}"
            if last_status is not None
            else ""
        )
        + "."
    )


async def fetch_pfz_geojson(
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """
    Fetch current PFZ line features as GeoJSON from official INCOIS WFS.

    Transient INCOIS/GeoServer errors are retried. No cached or simulated
    geometry is silently substituted.
    """

    owns_client = client is None

    if client is None:
        client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    try:
        return await _request_geojson(
            client,
            attempts=4,
        )

    finally:
        if owns_client:
            await client.aclose()


def build_report(
    payload: dict[str, Any],
) -> dict[str, Any]:
    features = payload.get("features", [])

    geometry_types = Counter(
        (feature.get("geometry") or {}).get(
            "type",
            "None",
        )
        for feature in features
    )

    return {
        "source": "INCOIS PFZ GeoServer WFS",
        "endpoint": WFS_URL,
        "layer": WFS_PARAMS["typeName"],
        "retrieved_at_utc": (
            datetime.now(timezone.utc).isoformat()
        ),
        "feature_collection_type": payload.get("type"),
        "feature_count": len(features),
        "numberMatched": payload.get("numberMatched"),
        "numberReturned": payload.get("numberReturned"),
        "crs": payload.get("crs"),
        "geometry_types": dict(geometry_types),
        "bounds": _feature_bounds(features),
        "properties": _property_summary(features),
        "sample_features": [
            _sample_feature(feature)
            for feature in features[:3]
        ],
    }


def print_report(
    report: dict[str, Any],
) -> None:
    print()
    print("TARANG — REAL INCOIS PFZ WFS INSPECTION")
    print("=" * 68)

    print(f"Source:        {report['source']}")
    print(f"Layer:         {report['layer']}")
    print(f"Features:      {report['feature_count']}")
    print(f"CRS:           {report['crs']}")
    print(f"Geometry:      {report['geometry_types']}")
    print(f"Bounds:        {report['bounds']}")

    print()
    print("PROPERTY KEYS")
    print("-" * 68)

    keys = report["properties"]["keys"]

    if keys:
        for key in keys:
            examples = (
                report["properties"]["examples"].get(
                    key,
                    [],
                )
            )
            count = (
                report["properties"]["non_null_counts"].get(
                    key,
                    0,
                )
            )

            print(
                f"{key}: non-null={count}; examples={examples}"
            )
    else:
        print("No properties were exposed.")

    print()
    print("SAMPLE FEATURES")
    print("-" * 68)

    for index, feature in enumerate(
        report["sample_features"],
        start=1,
    ):
        print(f"\nFeature {index}")
        print(
            json.dumps(
                feature,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )


async def main() -> None:
    try:
        payload = await fetch_pfz_geojson()
        report = build_report(payload)

        print_report(report)

        output_path = (
            Path.cwd()
            / "incois_pfz_wfs_report.json"
        )

        output_path.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        print()
        print("=" * 68)
        print("Saved report:")
        print(output_path)

    except IncoisPFZWfsError as exc:
        print()
        print("INCOIS PFZ WFS ERROR")
        print("=" * 68)
        print(str(exc))


if __name__ == "__main__":
    asyncio.run(main())
