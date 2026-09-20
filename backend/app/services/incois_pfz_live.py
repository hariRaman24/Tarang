"""
TARANG - Live INCOIS Nearest PFZ Service
========================================

Uses the official INCOIS GeoServer WFS layer:

    PFZ_Automation:pfzlines

to answer questions such as:

    "Where is the nearest PFZ?"
    "Is there a PFZ within my vessel's operating range?"

Important:
- PFZ coordinates/lines come from the real INCOIS WFS.
- No simulated PFZ station list is used.
- "Nearest" means shortest geodesic distance from the user's position to
  the nearest point on an INCOIS PFZ line.
- This service does NOT yet compute "best/productive PFZ". That needs real
  chlorophyll/SST evidence, which will be integrated separately.
- If no PFZ lies within vessel range, TARANG still reports the nearest
  official PFZ, but marks it as NOT ACTIONABLE.

CLI examples:

    python -m app.services.incois_pfz_live --lat 15.40 --lon 73.80 --range 25

    python -m app.services.incois_pfz_live --lat 13.05 --lon 80.28 --range 25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx

from app.services.incois_pfz import (
    IncoisPFZError,
    fetch_pfz_metadata,
)
from app.services.incois_pfz_wfs import (
    IncoisPFZWfsError,
    fetch_pfz_geojson,
)


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class PFZCandidate:
    uid: str | None
    state_name: str | None
    serial_number: str | None

    feature_date: str | None

    nearest_latitude: float
    nearest_longitude: float
    distance_km: float

    within_vessel_range: bool | None

    geometry_type: str
    source_feature_id: str | None


@dataclass(frozen=True)
class NearestPFZResult:
    ok: bool

    query_latitude: float
    query_longitude: float
    vessel_range_km: float | None

    source_name: str
    source_url: str
    official: bool

    advisory_forecast_date: str | None
    advisory_valid_upto: str | None

    feature_count: int

    nearest: PFZCandidate | None
    ranked_candidates: list[PFZCandidate]

    pfz_within_vessel_range: bool | None
    actionable: bool

    status: str
    note: str

    retrieved_at_utc: str


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    Great-circle distance between two points in kilometres.
    """

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


def _iter_lines(
    geometry: dict[str, Any],
) -> Iterable[list[list[float]]]:
    """
    Yield LineString coordinate arrays from LineString/MultiLineString GeoJSON.
    """

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if not isinstance(coordinates, list):
        return

    if geometry_type == "LineString":
        yield coordinates
        return

    if geometry_type == "MultiLineString":
        for line in coordinates:
            if isinstance(line, list):
                yield line


def _local_xy_km(
    query_lat: float,
    query_lon: float,
    lat: float,
    lon: float,
) -> tuple[float, float]:
    """
    Local equirectangular coordinates centred on the query point.

    This is used only to project onto a nearby line segment.
    Final distance is recalculated with Haversine.
    """

    lat0_rad = math.radians(query_lat)

    x = (
        math.radians(lon - query_lon)
        * EARTH_RADIUS_KM
        * math.cos(lat0_rad)
    )

    y = (
        math.radians(lat - query_lat)
        * EARTH_RADIUS_KM
    )

    return x, y


def _xy_to_latlon(
    query_lat: float,
    query_lon: float,
    x_km: float,
    y_km: float,
) -> tuple[float, float]:
    lat = (
        query_lat
        + math.degrees(
            y_km / EARTH_RADIUS_KM
        )
    )

    cos_lat = math.cos(
        math.radians(query_lat)
    )

    if abs(cos_lat) < 1e-12:
        lon = query_lon
    else:
        lon = (
            query_lon
            + math.degrees(
                x_km
                / (
                    EARTH_RADIUS_KM
                    * cos_lat
                )
            )
        )

    return lat, lon


def _nearest_point_on_segment(
    query_lat: float,
    query_lon: float,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> tuple[float, float, float]:
    """
    Return:
        nearest_lat,
        nearest_lon,
        final_haversine_distance_km
    """

    x1, y1 = _local_xy_km(
        query_lat,
        query_lon,
        lat1,
        lon1,
    )

    x2, y2 = _local_xy_km(
        query_lat,
        query_lon,
        lat2,
        lon2,
    )

    dx = x2 - x1
    dy = y2 - y1

    segment_sq = dx * dx + dy * dy

    if segment_sq <= 1e-18:
        nearest_x = x1
        nearest_y = y1
    else:
        # Query point is local origin (0, 0).
        t = -(
            x1 * dx
            + y1 * dy
        ) / segment_sq

        t = max(
            0.0,
            min(1.0, t),
        )

        nearest_x = x1 + t * dx
        nearest_y = y1 + t * dy

    nearest_lat, nearest_lon = _xy_to_latlon(
        query_lat,
        query_lon,
        nearest_x,
        nearest_y,
    )

    distance = haversine_km(
        query_lat,
        query_lon,
        nearest_lat,
        nearest_lon,
    )

    return (
        nearest_lat,
        nearest_lon,
        distance,
    )


def _nearest_point_on_geometry(
    query_lat: float,
    query_lon: float,
    geometry: dict[str, Any],
) -> tuple[float, float, float] | None:
    best: tuple[float, float, float] | None = None

    for line in _iter_lines(geometry):
        points: list[tuple[float, float]] = []

        for coordinate in line:
            if (
                isinstance(coordinate, list)
                and len(coordinate) >= 2
                and isinstance(
                    coordinate[0],
                    (int, float),
                )
                and isinstance(
                    coordinate[1],
                    (int, float),
                )
            ):
                # GeoJSON = longitude, latitude
                points.append(
                    (
                        float(coordinate[1]),
                        float(coordinate[0]),
                    )
                )

        if not points:
            continue

        if len(points) == 1:
            lat, lon = points[0]

            candidate = (
                lat,
                lon,
                haversine_km(
                    query_lat,
                    query_lon,
                    lat,
                    lon,
                ),
            )

            if (
                best is None
                or candidate[2] < best[2]
            ):
                best = candidate

            continue

        for index in range(
            len(points) - 1
        ):
            lat1, lon1 = points[index]
            lat2, lon2 = points[index + 1]

            candidate = _nearest_point_on_segment(
                query_lat,
                query_lon,
                lat1,
                lon1,
                lat2,
                lon2,
            )

            if (
                best is None
                or candidate[2] < best[2]
            ):
                best = candidate

    return best


def _feature_date(
    properties: dict[str, Any],
) -> str | None:
    """
    Convert Year + Julian_day to YYYY-MM-DD.
    """

    year = properties.get("Year")
    julian_day = properties.get("Julian_day")

    try:
        year_int = int(year)
        day_int = int(julian_day)
    except (TypeError, ValueError):
        return None

    if day_int < 1 or day_int > 366:
        return None

    try:
        date_value = (
            datetime(
                year_int,
                1,
                1,
                tzinfo=timezone.utc,
            )
            + timedelta(
                days=day_int - 1
            )
        )

        return date_value.date().isoformat()

    except ValueError:
        return None


def rank_pfz_features(
    payload: dict[str, Any],
    *,
    latitude: float,
    longitude: float,
    vessel_range_km: float | None = None,
    limit: int = 5,
) -> list[PFZCandidate]:
    """
    Rank real INCOIS PFZ features by distance from the query point.
    """

    features = payload.get(
        "features",
        [],
    )

    candidates: list[PFZCandidate] = []

    for feature in features:
        geometry = (
            feature.get("geometry")
            or {}
        )

        nearest = _nearest_point_on_geometry(
            latitude,
            longitude,
            geometry,
        )

        if nearest is None:
            continue

        nearest_lat, nearest_lon, distance = nearest

        properties = (
            feature.get("properties")
            or {}
        )

        within_range: bool | None

        if vessel_range_km is None:
            within_range = None
        else:
            within_range = (
                distance
                <= vessel_range_km
            )

        candidates.append(
            PFZCandidate(
                uid=(
                    str(properties.get("UID"))
                    if properties.get("UID") is not None
                    else None
                ),
                state_name=(
                    str(
                        properties.get(
                            "State_Name"
                        )
                    ).strip()
                    if properties.get(
                        "State_Name"
                    ) is not None
                    else None
                ),
                serial_number=(
                    str(
                        properties.get(
                            "Sno"
                        )
                    )
                    if properties.get(
                        "Sno"
                    ) is not None
                    else None
                ),
                feature_date=_feature_date(
                    properties
                ),
                nearest_latitude=round(
                    nearest_lat,
                    6,
                ),
                nearest_longitude=round(
                    nearest_lon,
                    6,
                ),
                distance_km=round(
                    distance,
                    2,
                ),
                within_vessel_range=(
                    within_range
                ),
                geometry_type=str(
                    geometry.get(
                        "type",
                        "Unknown",
                    )
                ),
                source_feature_id=(
                    str(feature.get("id"))
                    if feature.get("id") is not None
                    else None
                ),
            )
        )

    candidates.sort(
        key=lambda item: item.distance_km
    )

    return candidates[: max(1, limit)]


async def nearest_pfz(
    latitude: float,
    longitude: float,
    *,
    vessel_range_km: float | None = None,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> NearestPFZResult:
    """
    Retrieve current INCOIS PFZ geometry and calculate the nearest real PFZ.

    This is the main function that later agents should call.
    """

    if not (-90 <= latitude <= 90):
        raise ValueError(
            "latitude must be between -90 and 90"
        )

    if not (-180 <= longitude <= 180):
        raise ValueError(
            "longitude must be between -180 and 180"
        )

    if (
        vessel_range_km is not None
        and vessel_range_km <= 0
    ):
        raise ValueError(
            "vessel_range_km must be positive"
        )

    metadata = None

    try:
        metadata = await fetch_pfz_metadata(
            client=client
        )
    except IncoisPFZError:
        # Geometry can still be useful if the metadata page is temporarily down.
        metadata = None

    payload = await fetch_pfz_geojson(
        client=client
    )

    features = payload.get(
        "features",
        [],
    )

    ranked = rank_pfz_features(
        payload,
        latitude=latitude,
        longitude=longitude,
        vessel_range_km=vessel_range_km,
        limit=limit,
    )

    nearest = (
        ranked[0]
        if ranked
        else None
    )

    if vessel_range_km is None:
        within_range = None
        actionable = nearest is not None

        if nearest is not None:
            status = "LIVE"
            note = (
                "Nearest PFZ was calculated from the current official "
                "INCOIS PFZ WFS geometry. No vessel-range constraint "
                "was supplied."
            )
        else:
            status = "UNAVAILABLE"
            note = (
                "INCOIS WFS returned no usable PFZ geometry."
            )

    else:
        within_range = bool(
            nearest
            and nearest.within_vessel_range
        )

        actionable = within_range

        if nearest is None:
            status = "UNAVAILABLE"
            note = (
                "INCOIS WFS returned no usable PFZ geometry."
            )

        elif within_range:
            status = "LIVE"
            note = (
                "A current official INCOIS PFZ is within the "
                "configured vessel operating range."
            )

        else:
            status = "OUT_OF_RANGE"
            note = (
                "The nearest official INCOIS PFZ is outside the "
                "configured vessel operating range. TARANG should "
                "report it for awareness but must not present it as "
                "an actionable fishing recommendation."
            )

    return NearestPFZResult(
        ok=nearest is not None,
        query_latitude=latitude,
        query_longitude=longitude,
        vessel_range_km=vessel_range_km,
        source_name="INCOIS PFZ GeoServer WFS",
        source_url=(
            "https://incois.gov.in/"
            "geoserver/PFZ_Automation/ows"
        ),
        official=True,
        advisory_forecast_date=(
            metadata.forecast_date
            if metadata
            else None
        ),
        advisory_valid_upto=(
            metadata.valid_upto
            if metadata
            else None
        ),
        feature_count=len(features),
        nearest=nearest,
        ranked_candidates=ranked,
        pfz_within_vessel_range=within_range,
        actionable=actionable,
        status=status,
        note=note,
        retrieved_at_utc=(
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find the nearest real INCOIS PFZ "
            "to a latitude/longitude."
        )
    )

    parser.add_argument(
        "--lat",
        type=float,
        required=True,
        help="Query latitude",
    )

    parser.add_argument(
        "--lon",
        type=float,
        required=True,
        help="Query longitude",
    )

    parser.add_argument(
        "--range",
        dest="vessel_range_km",
        type=float,
        default=None,
        help=(
            "Optional vessel operating range "
            "in kilometres"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of nearest PFZ candidates",
    )

    args = parser.parse_args()

    try:
        result = await nearest_pfz(
            args.lat,
            args.lon,
            vessel_range_km=(
                args.vessel_range_km
            ),
            limit=args.limit,
        )

        print(
            json.dumps(
                asdict(result),
                indent=2,
                ensure_ascii=False,
            )
        )

    except (
        IncoisPFZWfsError,
        IncoisPFZError,
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
