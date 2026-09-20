"""
TARANG - Official INCOIS SST Service
====================================

Production connector for the official INCOIS PFZ-TUNA-SST-CHL GeoServer
sea-surface-temperature raster.

Verified behavior:
- WMS layer: sst
- Unit: degC (the INCOIS layer/legend is Sea Surface Temperature in °C)
- GetFeatureInfo works with STYLES left blank.
- Supplying the advertised style name in GetFeatureInfo currently causes
  an INCOIS GeoServer StyleNotDefined exception, so TARANG intentionally
  queries the raster without a style.
- No simulated or nearest-pixel fallback is used.

Important coastal-mask rule:
The GeoServer can return numeric raster values at coastal/land-mask pixels
that must not automatically be treated as valid sea-surface temperature.
TARANG therefore validates returned values against a conservative physical
range for this Indian marine SST product. Values outside that range remain
UNAVAILABLE rather than being exposed as official SST.

Run:
    python -m app.services.incois_sst --lat 12.967294 --lon 80.460044
    python -m app.services.incois_sst --lat 13.05 --lon 80.28
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
WMS_LAYER = "sst"
UNIT = "degC"

TIMEOUT_SECONDS = 30.0

# This connector is for the INCOIS Indian marine/PFZ SST product, not a
# polar/global SST service. A returned value below 0 °C or above 45 °C is
# treated as an invalid/masked raster value, not as usable SST evidence.
#
# This catches values such as -1.0 observed at a coastal Chennai query point
# while preserving the valid ~29 °C offshore PFZ values already verified.
MIN_VALID_SST_C = 0.0
MAX_VALID_SST_C = 45.0

# Common explicit NoData-like sentinels. Physical-range validation below
# remains the final guard even if the server uses another numeric mask value.
KNOWN_NODATA_SENTINELS = {
    -9999.0,
    -99999.0,
}


class IncoisSSTError(RuntimeError):
    """Raised when the official INCOIS SST endpoint cannot be queried."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_like_service_exception(
    response: httpx.Response,
) -> bool:
    content_type = (
        response.headers.get(
            "content-type",
            "",
        )
        or ""
    ).lower()

    text = response.text.lstrip()

    return (
        "application/vnd.ogc.se_xml"
        in content_type
        or (
            text.startswith("<?xml")
            and "ServiceException"
            in text[:1000]
        )
    )


def _extract_gray_index(
    payload: dict[str, Any],
) -> tuple[float | None, str | None, float | None]:
    """
    Extract and validate GRAY_INDEX.

    Returns:
        (value, reason, raw_numeric_value)

    reason is None for a valid SST.
    """

    features = payload.get(
        "features"
    ) or []

    if not features:
        return (
            None,
            "NO_FEATURE_AT_REQUESTED_PIXEL",
            None,
        )

    properties = (
        features[0].get(
            "properties"
        )
        or {}
    )

    raw_value = properties.get(
        "GRAY_INDEX"
    )

    if raw_value is None:
        return (
            None,
            "NO_DATA_AT_REQUESTED_PIXEL",
            None,
        )

    try:
        value = float(
            raw_value
        )
    except (
        TypeError,
        ValueError,
    ):
        return (
            None,
            "NON_NUMERIC_RASTER_VALUE",
            None,
        )

    if value in KNOWN_NODATA_SENTINELS:
        return (
            None,
            "NODATA_SENTINEL_AT_REQUESTED_PIXEL",
            value,
        )

    if not (
        MIN_VALID_SST_C
        <= value
        <= MAX_VALID_SST_C
    ):
        return (
            None,
            "INVALID_OR_MASKED_RASTER_VALUE",
            value,
        )

    return (
        value,
        None,
        value,
    )


async def sst_at(
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    """
    Query official INCOIS SST at one exact coordinate.

    If the exact raster pixel is null, masked, an invalid numeric mask value,
    or otherwise outside the conservative valid range, TARANG returns
    UNAVAILABLE. No nearest-neighbour substitution is performed.
    """

    half_window_deg = 0.06

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": WMS_LAYER,
        "QUERY_LAYERS": WMS_LAYER,

        # IMPORTANT:
        # Leave STYLES blank. INCOIS currently returns StyleNotDefined
        # when the advertised SST style name is supplied to GetFeatureInfo.
        "STYLES": "",

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
        "Accept": (
            "application/json,*/*"
        ),
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

            if _looks_like_service_exception(
                response
            ):
                raise IncoisSSTError(
                    "INCOIS returned an OGC ServiceException "
                    "instead of SST data."
                )

            payload = response.json()

    except IncoisSSTError:
        raise

    except Exception as exc:
        raise IncoisSSTError(
            f"INCOIS SST request failed: {exc}"
        ) from exc

    (
        value,
        invalid_reason,
        raw_numeric_value,
    ) = _extract_gray_index(
        payload
    )

    base = {
        "parameter": (
            "sea_surface_temperature"
        ),
        "latitude": round(
            float(latitude),
            6,
        ),
        "longitude": round(
            float(longitude),
            6,
        ),
        "unit": UNIT,
        "source": (
            "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS"
        ),
        "source_type": "official",
        "official": True,
        "source_url": WMS_URL,
        "layer": WMS_LAYER,
        "retrieved_at_utc": (
            retrieved_at
        ),
        "observation_time": None,
    }

    if value is None:
        return {
            **base,
            "available": False,
            "value": None,
            "status": "UNAVAILABLE",
            "reason": (
                invalid_reason
                or "NO_DATA_AT_REQUESTED_PIXEL"
            ),
            "raw_raster_value": (
                raw_numeric_value
            ),
            "validation": {
                "minimum_valid_sst_c": (
                    MIN_VALID_SST_C
                ),
                "maximum_valid_sst_c": (
                    MAX_VALID_SST_C
                ),
            },
            "note": (
                "INCOIS did not return a usable SST value at this exact "
                "raster pixel. The pixel may be coastal/land masked, NoData, "
                "or outside the valid range for this Indian marine SST "
                "product. TARANG does not substitute a simulated or distant "
                "value."
            ),
        }

    return {
        **base,
        "available": True,
        "value": round(
            value,
            6,
        ),
        "status": "OFFICIAL",
        "reason": None,
        "raw_raster_value": (
            raw_numeric_value
        ),
        "validation": {
            "minimum_valid_sst_c": (
                MIN_VALID_SST_C
            ),
            "maximum_valid_sst_c": (
                MAX_VALID_SST_C
            ),
        },
        "note": (
            "Official INCOIS SST raster value at the requested coordinate. "
            "The GetFeatureInfo response did not expose a trustworthy "
            "observation timestamp, so retrieval time is reported separately."
        ),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Query official INCOIS SST "
            "at one coordinate."
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

    args = parser.parse_args()

    try:
        result = await sst_at(
            args.lat,
            args.lon,
        )

    except IncoisSSTError as exc:
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
