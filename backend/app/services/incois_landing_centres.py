"""
TARANG - Live INCOIS Landing Centre Service
===========================================

Official source:
    PFZ_LandingCentres:LandingCenters_29Apr2024

This version is resilient to temporary INCOIS 503 responses.

Key behaviour:
- Downloads the landing-centre layer once and keeps it in memory.
- Retries transient 429 / 502 / 503 / 504 responses.
- Applies sector filtering locally after download.
- Uses only stable geographic fields:
    LC_NAME, DIST_NAME, SECTOR_NAM, SECTOR_ID, LC_UNIQUE_,
    Point geometry / latitude / longitude.
- Historical forecast fields in this 2024 layer are NOT treated as
  current fishing advice.

Examples:

    python -m app.services.incois_landing_centres \
        --lat 12.968598 --lon 80.35032 --limit 5

    python -m app.services.incois_landing_centres \
        --lat 12.968598 --lon 80.35032 \
        --limit 5 --sector "NORTH TAMILNADU"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


WFS_URL = "https://incois.gov.in/geoserver/PFZ_LandingCentres/ows"

WFS_PARAMS = {
    "service": "WFS",
    "version": "1.1.0",
    "request": "GetFeature",
    "typeName": "PFZ_LandingCentres:LandingCenters_29Apr2024",
    "outputFormat": "application/json",
}

TIMEOUT_SECONDS = 30.0
EARTH_RADIUS_KM = 6371.0088

# The landing-centre layer itself is a relatively static reference layer.
# Avoid repeatedly downloading 1223 features during one TARANG process.
CACHE_TTL_SECONDS = 6 * 60 * 60

_TRANSIENT_STATUS_CODES = {
    429,
    502,
    503,
    504,
}

_CACHE_PAYLOAD: dict[str, Any] | None = None
_CACHE_FETCHED_AT_MONOTONIC: float | None = None


class IncoisLandingCentreError(RuntimeError):
    """Raised when the official landing-centre WFS cannot be read safely."""


@dataclass(frozen=True)
class LandingCentreCandidate:
    name: str
    district: str | None
    sector_name: str | None
    sector_id: str | None
    unique_id: str | None

    latitude: float
    longitude: float
    distance_km: float

    source_feature_id: str | None


@dataclass(frozen=True)
class LandingCentreResult:
    ok: bool

    query_latitude: float
    query_longitude: float

    source_name: str
    source_url: str
    official: bool

    feature_count: int
    nearest: LandingCentreCandidate | None
    ranked_candidates: list[LandingCentreCandidate]

    sector_filter: str | None
    cache_used: bool

    note: str
    retrieved_at_utc: str


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2.0) ** 2
    )

    c = 2.0 * math.atan2(
        math.sqrt(a),
        math.sqrt(1.0 - a),
    )

    return EARTH_RADIUS_KM * c


def _cache_valid() -> bool:
    if (
        _CACHE_PAYLOAD is None
        or _CACHE_FETCHED_AT_MONOTONIC is None
    ):
        return False

    age = (
        time.monotonic()
        - _CACHE_FETCHED_AT_MONOTONIC
    )

    return age < CACHE_TTL_SECONDS


async def _request_geojson(
    client: httpx.AsyncClient,
    *,
    attempts: int = 4,
) -> dict[str, Any]:
    """
    Fetch the official WFS with retry for transient server failures.
    """

    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(
                WFS_URL,
                params=WFS_PARAMS,
            )

            if (
                response.status_code
                in _TRANSIENT_STATUS_CODES
            ):
                if attempt < attempts:
                    await asyncio.sleep(
                        1.5 * attempt
                    )
                    continue

                raise IncoisLandingCentreError(
                    "INCOIS landing-centre WFS remained temporarily "
                    f"unavailable after {attempts} attempts "
                    f"(HTTP {response.status_code})."
                )

            response.raise_for_status()

            try:
                payload = response.json()
            except ValueError as exc:
                raise IncoisLandingCentreError(
                    "INCOIS landing-centre WFS did not return valid JSON."
                ) from exc

            if not isinstance(payload, dict):
                raise IncoisLandingCentreError(
                    "Unexpected landing-centre JSON structure."
                )

            if payload.get("type") != "FeatureCollection":
                raise IncoisLandingCentreError(
                    "Expected GeoJSON FeatureCollection."
                )

            features = payload.get("features")

            if not isinstance(features, list):
                raise IncoisLandingCentreError(
                    "FeatureCollection has no valid features list."
                )

            return payload

        except httpx.TimeoutException as exc:
            last_error = exc

            if attempt < attempts:
                await asyncio.sleep(
                    1.5 * attempt
                )
                continue

        except httpx.HTTPStatusError as exc:
            last_error = exc

            if attempt < attempts:
                await asyncio.sleep(
                    1.5 * attempt
                )
                continue

        except httpx.HTTPError as exc:
            last_error = exc

            if attempt < attempts:
                await asyncio.sleep(
                    1.5 * attempt
                )
                continue

    raise IncoisLandingCentreError(
        "Unable to read INCOIS landing-centre WFS after retries: "
        f"{last_error}"
    )


async def fetch_landing_centres(
    *,
    client: httpx.AsyncClient | None = None,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], bool]:
    """
    Return:
        payload,
        cache_used
    """

    global _CACHE_PAYLOAD
    global _CACHE_FETCHED_AT_MONOTONIC

    if (
        not force_refresh
        and _cache_valid()
        and _CACHE_PAYLOAD is not None
    ):
        return _CACHE_PAYLOAD, True

    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "application/json,application/geo+json,*/*",
    }

    owns_client = client is None

    if client is None:
        client = httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        )

    try:
        payload = await _request_geojson(
            client
        )

        _CACHE_PAYLOAD = payload
        _CACHE_FETCHED_AT_MONOTONIC = (
            time.monotonic()
        )

        return payload, False

    finally:
        if owns_client:
            await client.aclose()


def rank_landing_centres(
    payload: dict[str, Any],
    *,
    latitude: float,
    longitude: float,
    limit: int = 5,
    sector_name: str | None = None,
) -> list[LandingCentreCandidate]:
    """
    Rank landing centres by distance.

    Sector filtering is intentionally done locally so TARANG does not make
    another WFS request for every PFZ candidate.
    """

    features = payload.get(
        "features",
        [],
    )

    candidates: list[
        LandingCentreCandidate
    ] = []

    wanted_sector = (
        sector_name.strip().upper()
        if sector_name
        else None
    )

    for feature in features:
        geometry = (
            feature.get("geometry")
            or {}
        )

        if geometry.get("type") != "Point":
            continue

        coords = geometry.get(
            "coordinates"
        )

        if (
            not isinstance(coords, list)
            or len(coords) < 2
            or not isinstance(
                coords[0],
                (int, float),
            )
            or not isinstance(
                coords[1],
                (int, float),
            )
        ):
            continue

        lon = float(coords[0])
        lat = float(coords[1])

        props = (
            feature.get("properties")
            or {}
        )

        if not isinstance(
            props,
            dict,
        ):
            continue

        current_sector = str(
            props.get("SECTOR_NAM")
            or ""
        ).strip()

        if (
            wanted_sector
            and current_sector.upper()
            != wanted_sector
        ):
            continue

        name = str(
            props.get("LC_NAME")
            or ""
        ).strip()

        if not name:
            continue

        distance = haversine_km(
            latitude,
            longitude,
            lat,
            lon,
        )

        candidates.append(
            LandingCentreCandidate(
                name=name,
                district=(
                    str(
                        props.get(
                            "DIST_NAME"
                        )
                    ).strip()
                    if props.get(
                        "DIST_NAME"
                    ) is not None
                    else None
                ),
                sector_name=(
                    current_sector
                    or None
                ),
                sector_id=(
                    str(
                        props.get(
                            "SECTOR_ID"
                        )
                    ).strip()
                    if props.get(
                        "SECTOR_ID"
                    ) is not None
                    else None
                ),
                unique_id=(
                    str(
                        props.get(
                            "LC_UNIQUE_"
                        )
                    ).strip()
                    if props.get(
                        "LC_UNIQUE_"
                    ) is not None
                    else None
                ),
                latitude=round(
                    lat,
                    6,
                ),
                longitude=round(
                    lon,
                    6,
                ),
                distance_km=round(
                    distance,
                    2,
                ),
                source_feature_id=(
                    str(
                        feature.get("id")
                    )
                    if feature.get("id")
                    is not None
                    else None
                ),
            )
        )

    candidates.sort(
        key=lambda item: item.distance_km
    )

    return candidates[
        : max(1, limit)
    ]


async def nearest_landing_centres(
    latitude: float,
    longitude: float,
    *,
    limit: int = 5,
    sector_name: str | None = None,
    client: httpx.AsyncClient | None = None,
    force_refresh: bool = False,
) -> LandingCentreResult:
    if not (-90 <= latitude <= 90):
        raise ValueError(
            "latitude must be between -90 and 90"
        )

    if not (-180 <= longitude <= 180):
        raise ValueError(
            "longitude must be between -180 and 180"
        )

    payload, cache_used = (
        await fetch_landing_centres(
            client=client,
            force_refresh=force_refresh,
        )
    )

    ranked = rank_landing_centres(
        payload,
        latitude=latitude,
        longitude=longitude,
        limit=limit,
        sector_name=sector_name,
    )

    nearest = (
        ranked[0]
        if ranked
        else None
    )

    return LandingCentreResult(
        ok=nearest is not None,
        query_latitude=latitude,
        query_longitude=longitude,
        source_name=(
            "INCOIS Landing Centres GeoServer WFS"
        ),
        source_url=WFS_URL,
        official=True,
        feature_count=len(
            payload.get(
                "features",
                [],
            )
        ),
        nearest=nearest,
        ranked_candidates=ranked,
        sector_filter=sector_name,
        cache_used=cache_used,
        note=(
            "Landing-centre names and coordinates are used only as "
            "geographic reference labels. Historical forecast attributes "
            "inside this reference layer are not treated as current "
            "PFZ advice."
        ),
        retrieved_at_utc=(
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find nearest official INCOIS landing centres "
            "to a latitude/longitude."
        )
    )

    parser.add_argument(
        "--lat",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--lon",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--sector",
        type=str,
        default=None,
        help=(
            "Optional exact INCOIS SECTOR_NAM filter, "
            "for example 'NORTH TAMILNADU'."
        ),
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help=(
            "Ignore in-process cache and refetch "
            "the WFS layer."
        ),
    )

    args = parser.parse_args()

    try:
        result = await nearest_landing_centres(
            args.lat,
            args.lon,
            limit=args.limit,
            sector_name=args.sector,
            force_refresh=args.force_refresh,
        )

        print(
            json.dumps(
                asdict(result),
                indent=2,
                ensure_ascii=False,
            )
        )

    except (
        IncoisLandingCentreError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "ERROR",
                    "error": str(exc),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(_main())
