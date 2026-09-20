"""
Geospatial Reasoning Agent.

Uses live official INCOIS PFZ geometry for fishing-zone proximity,
enriches each PFZ with the nearest official INCOIS landing centre,
and queries official INCOIS chlorophyll + SST at each PFZ sea point.

Important:
- PFZ geometry comes from PFZ_Automation:pfzlines.
- Landing-centre names/coordinates come from
  PFZ_LandingCentres:LandingCenters_29Apr2024.
- Chlorophyll comes from the official INCOIS PFZ-TUNA-SST-CHL WMS
  layer "chl" in mg/m3.
- SST comes from the official INCOIS PFZ-TUNA-SST-CHL WMS
  layer "sst" in degC.
- Null raster pixels remain UNAVAILABLE.
- TARANG does not substitute simulated or distant raster values.
- Simulated STATIONS are NOT used for PFZ recommendations.
- PFZ suitability ranking uses an explicit, transparent heuristic and
  reports its components and evidence coverage. It is advisory, not a
  fisheries forecast or guarantee of catch.
"""

from __future__ import annotations

import asyncio

from app.data.zones import ALL_ZONES, ZONE_CATALOGUE
from app.geo.engine import geofence_check

from app.services.incois_pfz_live import (
    IncoisPFZWfsError,
    nearest_pfz,
)

from app.services.incois_landing_centres import (
    IncoisLandingCentreError,
    fetch_landing_centres,
    rank_landing_centres,
)

from app.services.incois_chlorophyll import (
    IncoisChlorophyllError,
    chlorophyll_at,
)

from app.services.incois_sst import (
    IncoisSSTError,
    sst_at,
)


def _serialize_live_candidate(candidate) -> dict:
    state = candidate.state_name or "UNKNOWN"
    serial = candidate.serial_number or "—"

    return {
        "name": f"INCOIS PFZ {serial} — {state}",
        "uid": candidate.uid,
        "state_name": candidate.state_name,
        "serial_number": candidate.serial_number,
        "feature_date": candidate.feature_date,
        "lat": candidate.nearest_latitude,
        "lon": candidate.nearest_longitude,
        "distance_km": candidate.distance_km,
        "within_vessel_range": candidate.within_vessel_range,
        "geometry_type": candidate.geometry_type,
        "source_feature_id": candidate.source_feature_id,
        "source": "INCOIS PFZ GeoServer WFS",
        "official": True,
        "landing_centre": None,
        "chlorophyll": None,
        "sst": None,
    }


def _enrich_with_landing_centre(
    candidate_dict: dict,
    landing_payload: dict,
) -> dict:
    """
    Attach the nearest landing centre in the same INCOIS sector/state
    whenever possible.

    distance_from_pfz_km is:
        PFZ sea point -> landing centre

    It is NOT:
        user location -> landing centre
    """

    lat = candidate_dict.get("lat")
    lon = candidate_dict.get("lon")
    sector_name = candidate_dict.get("state_name")

    if lat is None or lon is None:
        return candidate_dict

    ranked = rank_landing_centres(
        landing_payload,
        latitude=float(lat),
        longitude=float(lon),
        limit=1,
        sector_name=sector_name,
    )

    if not ranked:
        ranked = rank_landing_centres(
            landing_payload,
            latitude=float(lat),
            longitude=float(lon),
            limit=1,
            sector_name=None,
        )

    if not ranked:
        return candidate_dict

    centre = ranked[0]

    candidate_dict["landing_centre"] = {
        "name": centre.name,
        "district": centre.district,
        "sector_name": centre.sector_name,
        "sector_id": centre.sector_id,
        "unique_id": centre.unique_id,
        "lat": centre.latitude,
        "lon": centre.longitude,
        "distance_from_pfz_km": centre.distance_km,
        "source_feature_id": centre.source_feature_id,
        "source": "INCOIS Landing Centres GeoServer WFS",
        "official": True,
    }

    return candidate_dict


async def _enrich_ocean_rasters(candidate_dict: dict) -> dict:
    """
    Query both official chlorophyll and SST at the exact PFZ coordinate.

    Both calls are independent and run concurrently.
    """

    lat = candidate_dict.get("lat")
    lon = candidate_dict.get("lon")

    if lat is None or lon is None:
        candidate_dict["chlorophyll"] = {
            "parameter": "chlorophyll_a",
            "value": None,
            "unit": "mg/m3",
            "status": "UNAVAILABLE",
            "available": False,
            "official": True,
            "reason": "PFZ_COORDINATE_UNAVAILABLE",
            "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS",
        }

        candidate_dict["sst"] = {
            "parameter": "sea_surface_temperature",
            "value": None,
            "unit": "degC",
            "status": "UNAVAILABLE",
            "available": False,
            "official": True,
            "reason": "PFZ_COORDINATE_UNAVAILABLE",
            "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS",
        }

        return candidate_dict

    chl_task = chlorophyll_at(float(lat), float(lon))
    sst_task = sst_at(float(lat), float(lon))

    chl_result, sst_result = await asyncio.gather(
        chl_task,
        sst_task,
        return_exceptions=True,
    )

    if isinstance(chl_result, Exception):
        candidate_dict["chlorophyll"] = {
            "parameter": "chlorophyll_a",
            "value": None,
            "unit": "mg/m3",
            "status": "UNAVAILABLE",
            "available": False,
            "official": True,
            "reason": "SOURCE_REQUEST_FAILED",
            "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS",
            "error": str(chl_result),
        }
    else:
        candidate_dict["chlorophyll"] = chl_result

    if isinstance(sst_result, Exception):
        candidate_dict["sst"] = {
            "parameter": "sea_surface_temperature",
            "value": None,
            "unit": "degC",
            "status": "UNAVAILABLE",
            "available": False,
            "official": True,
            "reason": "SOURCE_REQUEST_FAILED",
            "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS",
            "error": str(sst_result),
        }
    else:
        candidate_dict["sst"] = sst_result

    return candidate_dict


def _source_summary(
    candidates: list[dict],
    field_name: str,
    *,
    parameter: str,
    unit: str,
    source_name: str,
    layer: str,
) -> dict:
    """
    Summarize official INCOIS raster evidence without calling it LIVE.

    The GeoServer endpoint may respond successfully, but the chlorophyll/SST
    GetFeatureInfo payload does not currently expose a trustworthy observation
    timestamp. Therefore availability is described as OFFICIAL rather than LIVE.
    """

    queried = 0
    available = 0
    no_data = 0
    source_failures = 0

    for candidate in candidates:
        item = candidate.get(field_name)

        if not isinstance(item, dict):
            continue

        queried += 1

        if item.get("available") is True:
            available += 1
            continue

        if item.get("reason") == "SOURCE_REQUEST_FAILED":
            source_failures += 1
        else:
            no_data += 1

    if queried == 0:
        status = "NOT_QUERIED"

    elif source_failures == queried:
        status = "UNAVAILABLE"

    elif source_failures > 0:
        # Some candidate pixels were checked successfully while one or more
        # source requests failed. Do not collapse this to either fully
        # available or fully unavailable.
        status = "OFFICIAL_PARTIAL_SOURCE_FAILURE"

    elif available > 0:
        status = "OFFICIAL_AVAILABLE"

    else:
        status = "OFFICIAL_NO_DATA_AT_CANDIDATE_PIXELS"

    return {
        "name": source_name,
        "url": (
            "https://incois.gov.in/"
            "geoserver/PFZ-TUNA-SST-CHL/wms"
        ),
        "layer": layer,
        "parameter": parameter,
        "unit": unit,
        "official": True,
        "status": status,
        "observation_time_verified": False,
        "queried_candidate_count": queried,
        "available_value_count": available,
        "no_data_count": no_data,
        "source_failure_count": source_failures,
        "usage_note": (
            "Values are queried at the exact PFZ sea coordinates. "
            "NoData pixels remain UNAVAILABLE; TARANG does not substitute "
            "a distant or simulated value. The raster observation timestamp "
            "is not currently verified, so successful values are labelled "
            "OFFICIAL rather than LIVE."
        ),
    }


def _productivity_evidence_summary(
    candidates: list[dict],
    vessel_range_km: float,
) -> dict:
    """
    Summarize available PFZ evidence without creating an unsupported
    productivity/suitability ranking.

    TARANG currently has official PFZ geometry plus exact-pixel INCOIS
    chlorophyll/SST evidence. Those inputs are useful context, but no
    validated fisheries methodology has yet been adopted for converting
    them into a universal "best PFZ" or catch/productivity score.

    Therefore:
    - no arbitrary weights,
    - no synthetic productivity score,
    - no "best PFZ" winner,
    - missing raster values remain missing.
    """

    both_available = 0
    chlorophyll_only = 0
    sst_only = 0
    neither = 0

    for candidate in candidates:
        chl = candidate.get("chlorophyll") or {}
        sst = candidate.get("sst") or {}

        chl_ok = chl.get("available") is True
        sst_ok = sst.get("available") is True

        if chl_ok and sst_ok:
            both_available += 1
        elif chl_ok:
            chlorophyll_only += 1
        elif sst_ok:
            sst_only += 1
        else:
            neither += 1

    return {
        "candidate_count": len(candidates),
        "both_chlorophyll_and_sst_available": both_available,
        "chlorophyll_only_available": chlorophyll_only,
        "sst_only_available": sst_only,
        "neither_available": neither,
        "ranking_performed": False,
        "ranking_method": None,
        "ranking_weights": None,
        "ranked_candidates": [],
        "note": (
            "TARANG does not currently assign a productivity or suitability "
            "score to official PFZ candidates. A best-PFZ ranking is withheld "
            "until a validated, documented fisheries methodology is adopted. "
            "Official chlorophyll/SST values are displayed only as evidence."
        ),
    }


async def geospatial_agent(
    latitude: float,
    longitude: float,
    vessel_range_km: float,
) -> dict:
    """
    Live geospatial analysis using official INCOIS PFZ, landing-centre,
    chlorophyll, and SST data.
    """

    zone_hits = geofence_check(
        latitude,
        longitude,
        ALL_ZONES,
    )

    try:
        live_result = await nearest_pfz(
            latitude,
            longitude,
            vessel_range_km=vessel_range_km,
            limit=5,
        )

        closest_serialized = [
            _serialize_live_candidate(candidate)
            for candidate in live_result.ranked_candidates
        ]

        # ------------------------------------------------------------
        # Landing-centre enrichment
        # ------------------------------------------------------------
        landing_source = {
            "name": "INCOIS Landing Centres GeoServer WFS",
            "official": True,
            "status": "UNAVAILABLE",
        }

        try:
            landing_payload, cache_used = await fetch_landing_centres()

            for candidate_dict in closest_serialized:
                _enrich_with_landing_centre(
                    candidate_dict,
                    landing_payload,
                )

            landing_source = {
                "name": "INCOIS Landing Centres GeoServer WFS",
                "url": (
                    "https://incois.gov.in/"
                    "geoserver/PFZ_LandingCentres/ows"
                ),
                "official": True,
                "status": "LIVE",
                "feature_count": len(
                    landing_payload.get("features", [])
                ),
                "cache_used": cache_used,
                "usage_note": (
                    "Only stable landing-centre names and coordinates "
                    "are used. Historical forecast attributes in this "
                    "reference layer are not treated as current advice."
                ),
            }

        except IncoisLandingCentreError as exc:
            landing_source = {
                "name": "INCOIS Landing Centres GeoServer WFS",
                "official": True,
                "status": "UNAVAILABLE",
                "error": str(exc),
            }

        # ------------------------------------------------------------
        # Official chlorophyll + SST enrichment
        # ------------------------------------------------------------
        await asyncio.gather(
            *[
                _enrich_ocean_rasters(candidate_dict)
                for candidate_dict in closest_serialized
            ]
        )

        chlorophyll_source = _source_summary(
            closest_serialized,
            "chlorophyll",
            parameter="chlorophyll_a",
            unit="mg/m3",
            source_name="INCOIS Chlorophyll GeoServer WMS",
            layer="chl",
        )

        sst_source = _source_summary(
            closest_serialized,
            "sst",
            parameter="sea_surface_temperature",
            unit="degC",
            source_name="INCOIS SST GeoServer WMS",
            layer="sst",
        )

        productivity_evidence = _productivity_evidence_summary(
            closest_serialized,
            vessel_range_km,
        )

        # Scientific policy:
        # do not manufacture a "best" PFZ from arbitrary SST/chlorophyll
        # weights. Keep closest official PFZ/range evidence separate from
        # any future validated productivity model.
        ranked_best: list[dict] = []
        best_pfz = None

        closest_pfz = (
            closest_serialized[0]
            if closest_serialized
            else None
        )

        return {
            "agent": "Geospatial Reasoning Agent",
            "source": (
                "INCOIS PFZ GeoServer WFS + "
                "INCOIS Landing Centres WFS + "
                "INCOIS Chlorophyll/SST WMS + "
                "TARANG spatial analysis"
            ),
            "ok": live_result.ok,
            "data": {
                "closest_pfz": closest_pfz,

                "best_pfz": best_pfz,
                "closest_and_best_differ": bool(
                    best_pfz
                    and closest_pfz
                    and best_pfz.get("uid") != closest_pfz.get("uid")
                ),

                "ranked_closest": closest_serialized,
                "ranked_best": ranked_best,

                "geofence_hits": zone_hits,
                "geofence_catalogue": ZONE_CATALOGUE,

                "pfz_source": {
                    "name": live_result.source_name,
                    "url": live_result.source_url,
                    "official": live_result.official,
                    "advisory_forecast_date": (
                        live_result.advisory_forecast_date
                    ),
                    "advisory_valid_upto": (
                        live_result.advisory_valid_upto
                    ),
                    "feature_count": live_result.feature_count,
                    "status": live_result.status,
                    "retrieved_at_utc": (
                        live_result.retrieved_at_utc
                    ),
                },

                "landing_centre_source": landing_source,
                "chlorophyll_source": chlorophyll_source,
                "sst_source": sst_source,
                "productivity_evidence": productivity_evidence,

                "pfz_within_vessel_range": (
                    live_result.pfz_within_vessel_range
                ),
                "pfz_actionable": (
                    live_result.actionable
                ),
                "pfz_note": live_result.note,

                "best_pfz_status": (
                    "ADVISORY_RANKING_AVAILABLE"
                    if ranked_best
                    else "UNAVAILABLE_OFFICIAL_OCEAN_EVIDENCE"
                ),
                "best_pfz_note": (
                    "The displayed score is an advisory heuristic. Verify "
                    "official fisheries advisories and local conditions."
                ),
            },
        }

    except IncoisPFZWfsError as exc:
        return {
            "agent": "Geospatial Reasoning Agent",
            "source": "INCOIS PFZ GeoServer WFS",
            "ok": False,
            "error": str(exc),
            "data": {
                "closest_pfz": None,
                "best_pfz": None,
                "closest_and_best_differ": False,
                "ranked_closest": [],
                "ranked_best": [],
                "geofence_hits": zone_hits,
                "geofence_catalogue": ZONE_CATALOGUE,

                "pfz_source": {
                    "name": "INCOIS PFZ GeoServer WFS",
                    "official": True,
                    "status": "UNAVAILABLE",
                },

                "landing_centre_source": {
                    "name": "INCOIS Landing Centres GeoServer WFS",
                    "official": True,
                    "status": "NOT_QUERIED",
                },

                "chlorophyll_source": {
                    "name": "INCOIS Chlorophyll GeoServer WMS",
                    "official": True,
                    "status": "NOT_QUERIED",
                },

                "sst_source": {
                    "name": "INCOIS SST GeoServer WMS",
                    "official": True,
                    "status": "NOT_QUERIED",
                },

                "productivity_evidence": {
                    "candidate_count": 0,
                    "both_chlorophyll_and_sst_available": 0,
                    "ranking_performed": False,
                },

                "pfz_within_vessel_range": None,
                "pfz_actionable": False,

                "pfz_note": (
                    "Official INCOIS PFZ data is temporarily "
                    "unavailable. TARANG did not substitute simulated "
                    "PFZ coordinates."
                ),

                "best_pfz_status": (
                    "UNAVAILABLE_PFZ_SOURCE_FAILURE"
                ),
            },
        }
