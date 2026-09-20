"""
TARANG Ocean Analytics Agent
============================

Real-data-only ocean evidence layer.

This agent now knows about the production INCOIS chlorophyll and SST
connectors. It does not fabricate, interpolate, or silently substitute
ocean-colour values.

Design
------
- Official chlorophyll:
    INCOIS PFZ-TUNA-SST-CHL GeoServer WMS, layer "chl"
- Official SST:
    INCOIS PFZ-TUNA-SST-CHL GeoServer WMS, layer "sst"
- Model SST fallback/evidence:
    Open-Meteo marine forecast, supplied by the Weather Intelligence Agent
- PFZ discovery:
    remains the responsibility of the Geospatial Reasoning Agent

Important provenance rules
--------------------------
- INCOIS raster observation time is currently unverified, so this agent
  NEVER labels the official raster values as "LIVE".
- If an exact INCOIS pixel is NoData, it remains UNAVAILABLE.
- Open-Meteo SST is model data and is kept separate from official INCOIS SST.
- If latitude/longitude are not passed, the official connectors are reported
  as connected but NOT_QUERIED. No arbitrary location is substituted.

Compatibility
-------------
The function still works with the old call:

    await ocean_agent()

For direct official point queries, the orchestrator can later call:

    await ocean_agent(
        latitude=13.05,
        longitude=80.28,
        weather=weather_result,
    )

CLI validation:
    python -m app.agents.ocean_agent --lat 13.05 --lon 80.28 --model-sst 30.7
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.services.incois_chlorophyll import (
    IncoisChlorophyllError,
    chlorophyll_at,
)
from app.services.incois_sst import (
    IncoisSSTError,
    sst_at,
)


INCOIS_WMS_SOURCE = "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS"
INCOIS_WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"


def _model_sst_from_weather(
    weather: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Extract the Open-Meteo model SST without confusing it with
    official INCOIS SST.
    """

    if not weather:
        return {
            "value": None,
            "unit": "degC",
            "status": "NOT_PROVIDED",
            "source": "Weather Intelligence Agent / Open-Meteo Marine API",
            "source_type": "model",
            "official": False,
            "note": (
                "No Weather Intelligence Agent result was passed to the "
                "Ocean Analytics Agent in this call."
            ),
        }

    data = weather.get("data") if isinstance(weather, dict) else None

    if not isinstance(data, dict):
        data = weather if isinstance(weather, dict) else {}

    value = data.get("sea_surface_temperature_c")

    return {
        "value": value,
        "unit": "degC",
        "status": (
            "MODEL"
            if value is not None
            else "UNAVAILABLE"
        ),
        "source": (
            weather.get("source")
            if isinstance(weather, dict)
            and weather.get("source")
            else "Weather Intelligence Agent / Open-Meteo Marine API"
        ),
        "source_type": "model",
        "official": False,
        "note": (
            "Open-Meteo SST is model/forecast evidence. It is kept separate "
            "from official INCOIS raster SST and is not presented as an "
            "official observation."
        ),
    }


def _not_queried_chlorophyll() -> dict[str, Any]:
    return {
        "parameter": "chlorophyll_a",
        "value": None,
        "unit": "mg/m3",
        "status": "NOT_QUERIED",
        "available": False,
        "queried": False,
        "source": INCOIS_WMS_SOURCE,
        "source_type": "official",
        "official": True,
        "source_url": INCOIS_WMS_URL,
        "layer": "chl",
        "observation_time": None,
        "note": (
            "The official INCOIS chlorophyll connector is integrated, but "
            "this Ocean Agent call did not receive latitude/longitude. "
            "No arbitrary location was queried."
        ),
    }


def _not_queried_sst() -> dict[str, Any]:
    return {
        "parameter": "sea_surface_temperature",
        "value": None,
        "unit": "degC",
        "status": "NOT_QUERIED",
        "available": False,
        "queried": False,
        "source": INCOIS_WMS_SOURCE,
        "source_type": "official",
        "official": True,
        "source_url": INCOIS_WMS_URL,
        "layer": "sst",
        "observation_time": None,
        "note": (
            "The official INCOIS SST connector is integrated, but this "
            "Ocean Agent call did not receive latitude/longitude. "
            "No arbitrary location was queried."
        ),
    }


def _source_error(
    *,
    parameter: str,
    unit: str,
    layer: str,
    error: Exception,
) -> dict[str, Any]:
    return {
        "parameter": parameter,
        "value": None,
        "unit": unit,
        "status": "UNAVAILABLE",
        "available": False,
        "queried": True,
        "source": INCOIS_WMS_SOURCE,
        "source_type": "official",
        "official": True,
        "source_url": INCOIS_WMS_URL,
        "layer": layer,
        "observation_time": None,
        "reason": "SOURCE_REQUEST_FAILED",
        "error": str(error),
        "note": (
            "The official INCOIS source could not be retrieved. "
            "TARANG did not substitute a simulated value."
        ),
    }


async def _query_official_ocean(
    latitude: float,
    longitude: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Query official chlorophyll and SST concurrently for the same exact point.
    """

    results = await asyncio.gather(
        chlorophyll_at(
            latitude,
            longitude,
        ),
        sst_at(
            latitude,
            longitude,
        ),
        return_exceptions=True,
    )

    chlorophyll_result = results[0]
    sst_result = results[1]

    if isinstance(
        chlorophyll_result,
        BaseException,
    ):
        chlorophyll = _source_error(
            parameter="chlorophyll_a",
            unit="mg/m3",
            layer="chl",
            error=chlorophyll_result,
        )
    else:
        chlorophyll = {
            **chlorophyll_result,
            "queried": True,
        }

    if isinstance(
        sst_result,
        BaseException,
    ):
        sst = _source_error(
            parameter="sea_surface_temperature",
            unit="degC",
            layer="sst",
            error=sst_result,
        )
    else:
        sst = {
            **sst_result,
            "queried": True,
        }

    return chlorophyll, sst


async def ocean_agent(
    latitude: float | None = None,
    longitude: float | None = None,
    weather: dict[str, Any] | None = None,
) -> dict:
    """
    Return official ocean evidence for one exact coordinate when provided.

    Old orchestrator calls with no arguments remain valid. In that case,
    the response explicitly says the official connectors are connected
    but were not queried because no coordinate was supplied.
    """

    coordinate_query = (
        latitude is not None
        and longitude is not None
    )

    if coordinate_query:
        chlorophyll, official_sst = (
            await _query_official_ocean(
                float(latitude),
                float(longitude),
            )
        )
    else:
        chlorophyll = (
            _not_queried_chlorophyll()
        )
        official_sst = (
            _not_queried_sst()
        )

    model_sst = _model_sst_from_weather(
        weather
    )

    official_available_count = sum(
        1
        for item in (
            chlorophyll,
            official_sst,
        )
        if item.get("available") is True
    )

    official_query_failures = sum(
        1
        for item in (
            chlorophyll,
            official_sst,
        )
        if item.get("reason")
        == "SOURCE_REQUEST_FAILED"
    )

    if not coordinate_query:
        overall_status = (
            "OFFICIAL_CONNECTORS_AVAILABLE_NOT_QUERIED"
        )
    elif official_query_failures == 2:
        overall_status = (
            "OFFICIAL_SOURCES_UNAVAILABLE"
        )
    elif official_available_count > 0:
        overall_status = (
            "OFFICIAL_DATA_AVAILABLE"
        )
    else:
        overall_status = (
            "OFFICIAL_NO_DATA_AT_REQUESTED_PIXEL"
        )

    return {
        "agent": "Ocean Analytics Agent",
        "source": (
            "Official INCOIS Chlorophyll/SST WMS + "
            "Open-Meteo model SST provenance"
        ),
        "ok": True,
        "live": False,
        "status": overall_status,
        "coordinates": (
            {
                "latitude": round(
                    float(latitude),
                    6,
                ),
                "longitude": round(
                    float(longitude),
                    6,
                ),
            }
            if coordinate_query
            else None
        ),
        "data": {
            "chlorophyll": chlorophyll,

            # Primary SST record = official INCOIS raster when queried.
            "sst": official_sst,

            # Model SST remains available separately as supporting/fallback
            # evidence and is never labelled official.
            "model_sst": model_sst,

            # PFZ discovery belongs to the Geospatial Reasoning Agent.
            "pfz_locations": [],
            "pfz_status": (
                "PROVIDED_BY_GEOSPATIAL_AGENT"
            ),

            "connector_status": {
                "incois_chlorophyll": (
                    "CONNECTED"
                ),
                "incois_sst": "CONNECTED",
                "openmeteo_model_sst": (
                    "PROVIDED_BY_WEATHER_AGENT"
                ),
            },

            "data_policy": {
                "simulated_values_allowed": False,
                "nearest_pixel_substitution_allowed": False,
                "missing_data_behavior": "UNAVAILABLE",
                "official_raster_observation_time_verified": False,
                "official_status_wording": (
                    "OFFICIAL, never LIVE, until a trustworthy "
                    "observation timestamp is available"
                ),
            },

            "note": (
                "Official INCOIS chlorophyll and SST are now connected. "
                "Exact-pixel NoData remains UNAVAILABLE. Open-Meteo SST is "
                "kept separately as model evidence. PFZ geometry and PFZ-point "
                "enrichment remain the responsibility of the Geospatial Agent."
            ),
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Query TARANG Ocean Analytics Agent "
            "with optional exact coordinates."
        )
    )

    parser.add_argument(
        "--lat",
        type=float,
    )

    parser.add_argument(
        "--lon",
        type=float,
    )

    parser.add_argument(
        "--model-sst",
        type=float,
        default=None,
        help=(
            "Optional Open-Meteo model SST for provenance testing."
        ),
    )

    args = parser.parse_args()

    if (
        (args.lat is None)
        != (args.lon is None)
    ):
        raise SystemExit(
            "--lat and --lon must be supplied together."
        )

    weather = None

    if args.model_sst is not None:
        weather = {
            "agent": "Weather Intelligence Agent",
            "source": (
                "Open-Meteo Weather + Marine APIs"
            ),
            "data": {
                "sea_surface_temperature_c": (
                    args.model_sst
                ),
            },
        }

    result = await ocean_agent(
        latitude=args.lat,
        longitude=args.lon,
        weather=weather,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
