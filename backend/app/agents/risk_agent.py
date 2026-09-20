"""
Risk Assessment Agent.

Uses:
- live weather/marine conditions,
- vessel operating thresholds,
- geospatial/PFZ evidence,
- official IMD/RMC Chennai fishermen-warning bulletin,
- official INCOIS landing-centre sectors as a fallback sector resolver.

Safety policy
-------------
- Simulated curated cyclone/lightning flags are ignored.
- Official warnings override benign model conditions.
- "No matched warning" is NOT interpreted as "safe".
- Cyclone/lightning remain UNKNOWN unless a dedicated official connector
  explicitly provides them.
- TARANG does not emit a navigation-grade GO decision.
- IMD warning-sector resolution must not depend solely on PFZ availability.

Compatibility
-------------
The hazard_station argument is kept temporarily so the existing orchestrator
does not break. Its simulated hazard fields are ignored.
"""

from __future__ import annotations

from app.agents.decision_engine import VesselProfile
from app.data.stations import Station
from app.services.imd_marine_warnings import (
    ImdMarineWarningError,
    marine_warning_for_sector,
)
from app.services.incois_landing_centres import (
    IncoisLandingCentreError,
    nearest_landing_centres,
)


def _get_weather_value(
    weather: dict,
    key: str,
):
    return (weather.get("data") or {}).get(key)


def _weather_screening_context(
    weather: dict,
) -> dict:
    """
    Select the weather evidence Risk Agent should screen.

    If Weather Agent successfully selected a planner-requested forecast
    window, use that period instead of current conditions. Otherwise keep
    the existing current-condition behavior.

    The selected forecast window is already conservative:
    - peak wave height,
    - peak wind speed,
    - peak wind gust,
    across the requested period.
    """

    data = weather.get("data") or {}
    assessment = (
        data.get("assessment")
        or {}
    )

    if (
        assessment.get("status")
        == "FORECAST_WINDOW_SELECTED"
        and assessment.get(
            "requested_time_window"
        )
    ):
        return {
            "mode": "FORECAST_WINDOW",
            "requested_time_window": (
                assessment.get(
                    "requested_time_window"
                )
            ),
            "label": assessment.get(
                "label"
            ),
            "start_local": assessment.get(
                "start_local"
            ),
            "end_local": assessment.get(
                "end_local"
            ),
            "sample_count": assessment.get(
                "sample_count",
                0,
            ),
            "wave_height_m": (
                assessment.get(
                    "wave_height_m"
                )
            ),
            "wind_speed_kmh": (
                assessment.get(
                    "wind_speed_kmh"
                )
            ),
            "wind_gusts_kmh": (
                assessment.get(
                    "wind_gusts_kmh"
                )
            ),
            "sea_surface_temperature_c": (
                assessment.get(
                    "sea_surface_temperature_c"
                )
            ),
            "selection_policy": (
                assessment.get(
                    "selection_policy"
                )
            ),
        }

    return {
        "mode": "CURRENT_CONDITIONS",
        "requested_time_window": None,
        "label": "current conditions",
        "start_local": None,
        "end_local": None,
        "sample_count": 0,
        "wave_height_m": data.get(
            "wave_height_m"
        ),
        "wind_speed_kmh": data.get(
            "wind_speed_kmh"
        ),
        "wind_gusts_kmh": data.get(
            "wind_gusts_kmh"
        ),
        "sea_surface_temperature_c": (
            data.get(
                "sea_surface_temperature_c"
            )
        ),
        "selection_policy": (
            "Current Open-Meteo values."
        ),
    }


def _vessel_dict(
    vessel: VesselProfile,
) -> dict:
    return {
        "type": vessel.vessel_type,
        "label": vessel.label,
        "max_wave": vessel.max_wave,
        "max_wind": vessel.max_wind,
        "range_km": vessel.range_km,
    }


def _map_incois_sector(
    sector_name: str | None,
) -> str | None:
    normalized = str(
        sector_name or ""
    ).strip().upper()

    if normalized == "NORTH TAMILNADU":
        return "north_tamilnadu"

    if normalized == "SOUTH TAMILNADU":
        return "south_tamilnadu"

    return None


async def _resolve_warning_sector(
    weather: dict,
    geo: dict,
) -> dict:
    """
    Resolve the RMC Chennai warning sector without making IMD depend on PFZ.

    Priority:
    1. Official nearest PFZ sector, when PFZ WFS is available.
    2. Official nearest INCOIS landing-centre sector at the query coordinate.

    The landing-centre layer is used only as a geographic sector reference.
    It is not treated as current fishing advice.
    """

    geo_data = geo.get("data") or {}
    closest_pfz = geo_data.get(
        "closest_pfz"
    ) or {}

    pfz_sector_name = closest_pfz.get(
        "state_name"
    )

    mapped = _map_incois_sector(
        pfz_sector_name
    )

    if mapped is not None:
        return {
            "sector": mapped,
            "resolved": True,
            "method": "INCOIS_PFZ_SECTOR",
            "official": True,
            "source": "INCOIS PFZ GeoServer WFS",
            "reference_name": closest_pfz.get(
                "name"
            ),
            "reference_distance_km": (
                closest_pfz.get(
                    "distance_km"
                )
            ),
            "raw_sector_name": (
                pfz_sector_name
            ),
        }

    coords = weather.get(
        "coordinates"
    ) or {}

    latitude = coords.get(
        "latitude"
    )
    longitude = coords.get(
        "longitude"
    )

    if (
        latitude is None
        or longitude is None
    ):
        return {
            "sector": None,
            "resolved": False,
            "method": "UNAVAILABLE",
            "official": None,
            "reason": "QUERY_COORDINATES_UNAVAILABLE",
        }

    try:
        landing_result = (
            await nearest_landing_centres(
                float(latitude),
                float(longitude),
                limit=1,
            )
        )
    except (
        IncoisLandingCentreError,
        ValueError,
    ) as exc:
        return {
            "sector": None,
            "resolved": False,
            "method": "INCOIS_LANDING_CENTRE_FALLBACK_FAILED",
            "official": True,
            "source": "INCOIS Landing Centres GeoServer WFS",
            "reason": "SOURCE_REQUEST_FAILED",
            "error": str(exc),
        }

    nearest = landing_result.nearest

    if nearest is None:
        return {
            "sector": None,
            "resolved": False,
            "method": "INCOIS_LANDING_CENTRE_FALLBACK",
            "official": True,
            "source": landing_result.source_name,
            "reason": "NO_LANDING_CENTRE_FOUND",
        }

    mapped = _map_incois_sector(
        nearest.sector_name
    )

    if mapped is None:
        return {
            "sector": None,
            "resolved": False,
            "method": "INCOIS_LANDING_CENTRE_FALLBACK",
            "official": True,
            "source": landing_result.source_name,
            "reference_name": nearest.name,
            "reference_district": nearest.district,
            "reference_distance_km": (
                nearest.distance_km
            ),
            "raw_sector_name": (
                nearest.sector_name
            ),
            "reason": "NEAREST_OFFICIAL_SECTOR_NOT_SUPPORTED_BY_RMC_CHENNAI_CONNECTOR",
        }

    return {
        "sector": mapped,
        "resolved": True,
        "method": "INCOIS_LANDING_CENTRE_FALLBACK",
        "official": True,
        "source": landing_result.source_name,
        "reference_name": nearest.name,
        "reference_district": nearest.district,
        "reference_distance_km": (
            nearest.distance_km
        ),
        "raw_sector_name": (
            nearest.sector_name
        ),
        "cache_used": (
            landing_result.cache_used
        ),
        "note": (
            "Official INCOIS landing-centre sector is used only to resolve "
            "the coastal warning sector when PFZ geometry is unavailable."
        ),
    }


async def _official_marine_warning(
    weather: dict,
    geo: dict,
) -> dict:
    sector_resolution = (
        await _resolve_warning_sector(
            weather,
            geo,
        )
    )

    sector = sector_resolution.get(
        "sector"
    )

    if sector is None:
        return {
            "available": False,
            "applicable": False,
            "status": "WARNING_SECTOR_UNRESOLVED",
            "sector": None,
            "sector_warning_match": None,
            "sector_resolution": (
                sector_resolution
            ),
            "source": (
                "India Meteorological Department / "
                "Regional Meteorological Centre Chennai"
            ),
            "official": True,
            "note": (
                "The current validated RMC Chennai warning connector is "
                "used only when TARANG can resolve a North/South Tamil Nadu "
                "sector from official geographic evidence."
            ),
        }

    try:
        result = await marine_warning_for_sector(
            sector
        )

    except ImdMarineWarningError as exc:
        return {
            "available": False,
            "applicable": True,
            "status": "UNAVAILABLE",
            "sector": sector,
            "sector_warning_match": None,
            "sector_resolution": (
                sector_resolution
            ),
            "source": (
                "India Meteorological Department / "
                "Regional Meteorological Centre Chennai"
            ),
            "official": True,
            "error": str(exc),
        }

    sector_data = result.get(
        "sector"
    ) or {}

    return {
        "available": bool(
            result.get(
                "bulletin_available"
            )
        ),
        "applicable": True,
        "status": sector_data.get(
            "status",
            "UNAVAILABLE",
        ),
        "sector": sector,
        "sector_warning_match": (
            sector_data.get(
                "sector_warning_match"
            )
        ),
        "match_confidence": (
            sector_data.get(
                "match_confidence"
            )
        ),
        "sector_resolution": (
            sector_resolution
        ),
        "current_tamilnadu_coast_section_nil": (
            sector_data.get(
                "current_tamilnadu_coast_section_nil"
            )
        ),
        "do_not_venture_text_present_somewhere_in_bulletin": (
            sector_data.get(
                "do_not_venture_text_present_somewhere_in_bulletin"
            )
        ),
        "do_not_venture_applies_to_requested_sector": (
            sector_data.get(
                "do_not_venture_applies_to_requested_sector"
            )
        ),
        "dates_found": result.get(
            "dates_found",
            [],
        ),
        "issue_times_found": (
            result.get(
                "issue_times_found",
                [],
            )
        ),
        "bulletin_warning_terms": (
            result.get(
                "bulletin_warning_terms",
                [],
            )
        ),
        "source": result.get(
            "source"
        ),
        "source_url": result.get(
            "source_url"
        ),
        "official": True,
        "retrieved_at_utc": (
            result.get(
                "retrieved_at_utc"
            )
        ),
        "navigation_grade": False,
        "note": result.get(
            "note"
        ),
    }


async def risk_agent(
    weather: dict,
    geo: dict,
    vessel: VesselProfile,
    hazard_station: Station | None,
) -> dict:
    """
    Perform conservative vessel-condition screening and official
    fishermen-warning checking.

    The legacy hazard_station is ignored because its cyclone/lightning
    flags are simulated prototype data.
    """

    _ = hazard_station

    screening = (
        _weather_screening_context(
            weather
        )
    )

    wave = screening.get(
        "wave_height_m"
    )

    wind = screening.get(
        "wind_speed_kmh"
    )

    gust = screening.get(
        "wind_gusts_kmh"
    )

    requested_time_window = (
        screening.get(
            "requested_time_window"
        )
    )

    is_requested_forecast_window = (
        screening.get("mode")
        == "FORECAST_WINDOW"
    )

    # A requested forecast window and a genuinely future warning-validity
    # question are not the same thing.
    #
    # "today" may use a selected hourly window for wave/wind screening while
    # still allowing a CURRENT official warning to apply. Future periods such
    # as tonight/tomorrow require separate warning-validity confirmation.
    requires_future_warning_revalidation = (
        requested_time_window
        in {
            "tonight",
            "tomorrow",
            "tomorrow_morning",
        }
    )

    weather_ok = bool(
        weather.get(
            "ok",
            True,
        )
    )

    wave_exceeds = (
        wave is not None
        and wave > vessel.max_wave
    )

    wind_exceeds = (
        wind is not None
        and wind > vessel.max_wind
    )

    reasons: list[dict] = []

    if not weather_ok:
        reasons.append(
            {
                "code": "weather_unavailable",
            }
        )

    if wave_exceeds:
        reasons.append(
            {
                "code": "wave_exceeds",
                "wave": wave,
                "threshold": vessel.max_wave,
                "vessel_type": (
                    vessel.vessel_type
                ),
            }
        )

    if wind_exceeds:
        reasons.append(
            {
                "code": "wind_exceeds",
                "wind": wind,
                "threshold": vessel.max_wind,
                "vessel_type": (
                    vessel.vessel_type
                ),
            }
        )

    # ------------------------------------------------------------
    # OFFICIAL IMD MARINE WARNING
    # ------------------------------------------------------------
    marine_warning = (
        await _official_marine_warning(
            weather,
            geo,
        )
    )

    warning_available = bool(
        marine_warning.get(
            "available"
        )
    )

    current_warning_match = (
        marine_warning.get(
            "sector_warning_match"
        )
    )

    warning_applicable = bool(
        marine_warning.get(
            "applicable"
        )
    )

    # The current RMC Chennai connector validates warning timing relative
    # to bulletin/current time. It does not yet evaluate arbitrary future
    # forecast windows such as "tomorrow morning".
    #
    # Therefore, for a requested future/time-bounded forecast window we
    # preserve the current warning as context but do not silently claim it
    # applies to that requested period.
    if requires_future_warning_revalidation:
        warning_match = None
        warning_time_applicability = (
            "NOT_EVALUATED_FOR_REQUESTED_FORECAST_WINDOW"
        )
    else:
        warning_match = (
            current_warning_match
        )
        warning_time_applicability = (
            "CURRENT_TIME_VALIDATED"
        )

    if (
        warning_available
        and warning_match is True
    ):
        reasons.append(
            {
                "code": "official_marine_warning",
                "sector": (
                    marine_warning.get(
                        "sector"
                    )
                ),
                "source": (
                    "IMD/RMC Chennai"
                ),
            }
        )

    elif (
        warning_applicable
        and not warning_available
    ):
        reasons.append(
            {
                "code": "no_hazard_data",
            }
        )

    if (
        requires_future_warning_revalidation
        and warning_available
        and current_warning_match is True
    ):
        reasons.append(
            {
                "code": (
                    "current_official_warning_future_applicability_unverified"
                ),
                "sector": (
                    marine_warning.get(
                        "sector"
                    )
                ),
                "requested_time_window": (
                    requested_time_window
                ),
                "source": "IMD/RMC Chennai",
            }
        )

    # ------------------------------------------------------------
    # GEO / RANGE
    # ------------------------------------------------------------
    geo_data = geo.get(
        "data"
    ) or {}

    closest_pfz = (
        geo_data.get(
            "closest_pfz"
        )
    )

    if (
        closest_pfz
        and not closest_pfz.get(
            "within_vessel_range",
            True,
        )
    ):
        reasons.append(
            {
                "code": "best_pfz_out_of_range",
                "name": closest_pfz.get(
                    "name",
                    "PFZ",
                ),
                "distance_km": (
                    closest_pfz.get(
                        "distance_km"
                    )
                ),
                "range_km": (
                    vessel.range_km
                ),
            }
        )

    for hit in geo_data.get(
        "geofence_hits",
        [],
    ):
        reasons.append(
            {
                "code": "geofence_hit",
                "zone": hit.get(
                    "zone"
                ),
                "kind": hit.get(
                    "kind"
                ),
                "inside": hit.get(
                    "inside"
                ),
                "distance_km": (
                    hit.get(
                        "distance_km"
                    )
                ),
            }
        )

    # ------------------------------------------------------------
    # DECISION POLICY
    # ------------------------------------------------------------
    safety_score = None
    suitability_score = None

    if wave_exceeds or wind_exceeds:
        verdict = "CAUTION"

        if is_requested_forecast_window:
            decision_status = (
                "VESSEL_THRESHOLD_EXCEEDED_FOR_REQUESTED_WINDOW"
            )
        else:
            decision_status = (
                "VESSEL_THRESHOLD_EXCEEDED"
            )

    elif warning_match is True:
        verdict = "CAUTION"
        decision_status = (
            "OFFICIAL_MARINE_WARNING_MATCHED"
        )

    elif requires_future_warning_revalidation:
        verdict = "UNAVAILABLE"
        decision_status = (
            "REQUESTED_WINDOW_HAZARD_COVERAGE_INCOMPLETE"
        )

    elif (
        warning_available
        and warning_applicable
        and warning_match is False
    ):
        verdict = "UNAVAILABLE"
        decision_status = (
            "OFFICIAL_WARNING_CHECKED_NO_EXPLICIT_SECTOR_MATCH"
        )

    else:
        verdict = "UNAVAILABLE"
        decision_status = (
            "INCOMPLETE_OFFICIAL_HAZARD_DATA"
        )

    if requires_future_warning_revalidation:
        hazard_status = (
            "REQUESTED_WINDOW_OFFICIAL_WARNING_VALIDITY_NOT_EVALUATED"
        )

    elif warning_match is True:
        hazard_status = (
            "OFFICIAL_WARNING_MATCHED"
        )

    elif (
        warning_available
        and warning_applicable
        and warning_match is False
    ):
        hazard_status = (
            "OFFICIAL_WARNING_CHECKED_NO_EXPLICIT_SECTOR_MATCH"
        )

    elif (
        warning_available
        and warning_applicable
        and warning_match is None
    ):
        hazard_status = (
            "OFFICIAL_WARNING_SCOPE_OR_TIME_AMBIGUOUS"
        )

    elif (
        marine_warning.get("status")
        == "WARNING_SECTOR_UNRESOLVED"
    ):
        hazard_status = (
            "WARNING_SECTOR_UNRESOLVED"
        )

    else:
        hazard_status = "UNAVAILABLE"

    return {
        "agent": "Risk Assessment Agent",
        "source": (
            "TARANG vessel-threshold screening + "
            "official IMD/RMC Chennai fishermen warning + "
            "official INCOIS sector resolution"
        ),
        "ok": True,
        "live": weather_ok,
        "degraded": True,
        "data": {
            "safety_score": (
                safety_score
            ),
            "suitability_score": (
                suitability_score
            ),
            "verdict": verdict,
            "decision_status": (
                decision_status
            ),
            "navigation_grade": False,

            "vessel": _vessel_dict(
                vessel
            ),

            "conditions": {
                "evidence_mode": (
                    screening.get(
                        "mode"
                    )
                ),
                "requested_time_window": (
                    requested_time_window
                ),
                "requires_future_warning_revalidation": (
                    requires_future_warning_revalidation
                ),
                "window_label": (
                    screening.get(
                        "label"
                    )
                ),
                "window_start_local": (
                    screening.get(
                        "start_local"
                    )
                ),
                "window_end_local": (
                    screening.get(
                        "end_local"
                    )
                ),
                "window_sample_count": (
                    screening.get(
                        "sample_count"
                    )
                ),
                "wave_height_m": wave,
                "wind_speed_kmh": wind,
                "wind_gusts_kmh": gust,
                "sea_surface_temperature_c": (
                    screening.get(
                        "sea_surface_temperature_c"
                    )
                ),
                "wave_within_vessel_limit": (
                    None
                    if wave is None
                    else not wave_exceeds
                ),
                "wind_within_vessel_limit": (
                    None
                    if wind is None
                    else not wind_exceeds
                ),
                "selection_policy": (
                    screening.get(
                        "selection_policy"
                    )
                ),
            },

            "reasons": reasons,

            "hazard_data_available": (
                warning_available
                and warning_applicable
            ),

            "hazard_coverage_complete": False,
            "hazard_status": (
                hazard_status
            ),

            "cyclone": None,
            "lightning": None,

            "official_marine_warning": {
                **marine_warning,
                "current_sector_warning_match": (
                    current_warning_match
                ),
                "applies_to_requested_time_window": (
                    warning_match
                ),
                "requested_time_window": (
                    requested_time_window
                ),
                "time_applicability": (
                    warning_time_applicability
                ),
            },

            "productivity_status": (
                "AVAILABLE"
                if geo_data.get(
                    "best_pfz"
                )
                is not None
                else "UNAVAILABLE"
            ),

            "note": (
                "Official IMD fishermen-warning evidence is checked where "
                "a supported Tamil Nadu warning sector can be resolved from "
                "official INCOIS geographic evidence. PFZ failure does not "
                "automatically disable warning checks. A missing matched "
                "warning does not mean conditions are safe. For planner-"
                "requested forecast windows, vessel thresholds use the selected "
                "forecast period. The current warning connector is not silently "
                "assumed to apply to a future period unless that period is "
                "explicitly validated."
            ),
        },
    }
