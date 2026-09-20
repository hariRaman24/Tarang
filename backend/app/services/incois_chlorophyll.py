"""
TARANG - Official INCOIS Chlorophyll Service
============================================

Production connector for the official INCOIS GeoServer chlorophyll raster.

Verified from the INCOIS WMS:
    Workspace/layer: PFZ-TUNA-SST-CHL:chl
    WMS layer name:  chl
    Style:           pfz_tuna_chl_sld
    Style title:     Chlorophyll Concentration
    Unit:            mg/m3
    NoData:          -9999

Important:
- This service never invents or interpolates a value.
- It queries the exact requested sea coordinate.
- If INCOIS returns NoData/null, TARANG returns UNAVAILABLE.
- The WMS response does not currently expose a trustworthy observation
  timestamp, so this connector records retrieval time separately and does
  not claim an observation time that was not supplied.

Run directly:
    python -m app.services.incois_chlorophyll --lat 12.968598 --lon 80.35032
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
WMS_LAYER = "chl"
WMS_STYLE = "pfz_tuna_chl_sld"
UNIT = "mg/m3"
NODATA_VALUE = -9999.0

TIMEOUT_SECONDS = 30.0


class IncoisChlorophyllError(RuntimeError):
    """Raised when the official INCOIS chlorophyll endpoint cannot be queried."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_gray_index(payload: dict[str, Any]) -> float | None:
    features = payload.get("features") or []

    if not features:
        return None

    properties = features[0].get("properties") or {}
    raw_value = properties.get("GRAY_INDEX")

    if raw_value is None:
        return None

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    if value <= -9990:
        return None

    return value


async def chlorophyll_at(
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """
    Query official INCOIS chlorophyll at one exact coordinate.

    Returns:
        {
            "available": bool,
            "value": float | None,
            "unit": "mg/m3",
            "status": "OFFICIAL" | "UNAVAILABLE",
            ...
        }

    No nearest-neighbour search is performed here. If the requested raster
    pixel is NoData/cloud-masked, the result remains UNAVAILABLE.
    """

    half_window_deg = 0.06

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": WMS_LAYER,
        "QUERY_LAYERS": WMS_LAYER,
        "STYLES": WMS_STYLE,
        "SRS": "EPSG:4326",
        "BBOX": (
            f"{longitude-half_window_deg},"
            f"{latitude-half_window_deg},"
            f"{longitude+half_window_deg},"
            f"{latitude+half_window_deg}"
        ),
        "WIDTH": "101",
        "HEIGHT": "101",
        "X": "50",
        "Y": "50",
        "FORMAT": "image/png",
        "INFO_FORMAT": "application/json",
        "FEATURE_COUNT": "10",
    }

    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "application/json,*/*",
    }

    retrieved_at = _utc_now()

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(
                WMS_URL,
                params=params,
            )

            response.raise_for_status()
            payload = response.json()

    except Exception as exc:
        raise IncoisChlorophyllError(
            f"INCOIS chlorophyll request failed: {exc}"
        ) from exc

    value = _extract_gray_index(payload)

    base = {
        "parameter": "chlorophyll_a",
        "latitude": round(float(latitude), 6),
        "longitude": round(float(longitude), 6),
        "unit": UNIT,
        "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS",
        "source_type": "official",
        "official": True,
        "source_url": WMS_URL,
        "layer": WMS_LAYER,
        "style": WMS_STYLE,
        "retrieved_at_utc": retrieved_at,
        "observation_time": None,
    }

    if value is None:
        return {
            **base,
            "available": False,
            "value": None,
            "status": "UNAVAILABLE",
            "reason": "NO_DATA_AT_REQUESTED_PIXEL",
            "note": (
                "INCOIS returned no chlorophyll value at this exact pixel. "
                "This can occur because of cloud/no-data/coastal masking. "
                "TARANG does not substitute a fabricated or distant value."
            ),
        }

    return {
        **base,
        "available": True,
        "value": round(value, 6),
        "status": "OFFICIAL",
        "reason": None,
        "note": (
            "Official INCOIS chlorophyll raster value at the requested "
            "coordinate. The WMS response did not provide an observation "
            "timestamp, so retrieval time is reported separately."
        ),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query official INCOIS chlorophyll at one coordinate."
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

    args = parser.parse_args()

    try:
        result = await chlorophyll_at(
            args.lat,
            args.lon,
        )

    except IncoisChlorophyllError as exc:
        result = {
            "available": False,
            "status": "UNAVAILABLE",
            "error": str(exc),
        }

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
