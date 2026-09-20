"""
TARANG Real Data Source Registry
================================

Central registry for all external real-data providers used by TARANG.

Important design rules:

1. Indian official operational sources have highest priority.
2. Trusted scientific/global sources are fallbacks.
3. Agents should NOT hard-code websites directly.
4. Agents/services should ask this registry which source is preferred.
5. If a source is unavailable, TARANG should fall back or report
   UNAVAILABLE — never silently invent operational marine data.

This file contains metadata only.
Actual downloading/parsing happens inside dedicated service connectors:

    incois_pfz.py
    incois_osf.py
    imd_marine.py
    bhoonidhi.py
    openmeteo.py
    etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


# ============================================================
# SOURCE PRIORITY
# ============================================================


class SourceTier(IntEnum):
    """
    Lower number = higher preference.

    Tier 1:
        Official Indian operational authority.

    Tier 2:
        Official Indian scientific/satellite source.

    Tier 3:
        Trusted international scientific source.

    Tier 4:
        General fallback service.
    """

    INDIA_OPERATIONAL = 1

    INDIA_SCIENTIFIC = 2

    INTERNATIONAL_SCIENTIFIC = 3

    FALLBACK = 4


# ============================================================
# SOURCE DEFINITION
# ============================================================


@dataclass(frozen=True)
class SourceSpec:

    key: str

    name: str

    organisation: str

    tier: SourceTier

    base_url: str

    capabilities: frozenset[str]

    official: bool = True

    authentication_required: bool = False

    live_or_near_real_time: bool = False

    notes: str = ""


# ============================================================
# CAPABILITY NAMES
# ============================================================

# Keep these machine-readable and stable.
#
# Do not translate these keys.
#
# Translation belongs in synthesis/frontend i18n.


PFZ = "pfz"

SST = "sst"

CHLOROPHYLL = "chlorophyll"

OCEAN_COLOUR = "ocean_colour"

WAVE_HEIGHT = "wave_height"

WAVE_DIRECTION = "wave_direction"

WAVE_PERIOD = "wave_period"

SWELL_HEIGHT = "swell_height"

SWELL_PERIOD = "swell_period"

SURFACE_CURRENT = "surface_current"

WIND = "wind"

MIXED_LAYER_DEPTH = "mixed_layer_depth"

D20 = "d20"

EEZ = "eez"

LANDING_CENTRES = "landing_centres"

BATHYMETRY = "bathymetry"

FISHERMEN_WARNING = "fishermen_warning"

CYCLONE_WARNING = "cyclone_warning"

THUNDERSTORM_WARNING = "thunderstorm_warning"

HIGH_WAVE_WARNING = "high_wave_warning"

SEA_STATE = "sea_state"

AIR_TEMPERATURE = "air_temperature"

APPARENT_TEMPERATURE = "apparent_temperature"

HUMIDITY = "humidity"

RAIN = "rain"

CLOUD_COVER = "cloud_cover"

PRESSURE = "pressure"

VISIBILITY = "visibility"

WIND_GUST = "wind_gust"

SATELLITE_CHLOROPHYLL = "satellite_chlorophyll"

SATELLITE_SST = "satellite_sst"

ARGO = "argo"

BUOY_DATA = "buoy_data"


# ============================================================
# SOURCE REGISTRY
# ============================================================


SOURCES: dict[str, SourceSpec] = {


    # --------------------------------------------------------
    # INCOIS — PFZ advisory text
    # --------------------------------------------------------

    "incois_pfz_text": SourceSpec(

        key="incois_pfz_text",

        name="INCOIS Potential Fishing Zone Advisory Text",

        organisation=(
            "Indian National Centre for Ocean "
            "Information Services"
        ),

        tier=SourceTier.INDIA_OPERATIONAL,

        base_url=(
            "https://www.incois.gov.in/"
            "MarineFisheries/TextDataHome"
            "?mfid=1&request_locale=en"
        ),

        capabilities=frozenset({
            PFZ,
        }),

        official=True,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "Official sector-wise PFZ advisory. "
            "The connector should obtain the latest "
            "forecast date, validity date and PFZ text."
        ),
    ),


    # --------------------------------------------------------
    # INCOIS — PFZ interactive WebGIS
    # --------------------------------------------------------

    "incois_pfz_webgis": SourceSpec(

        key="incois_pfz_webgis",

        name="INCOIS PFZ WebGIS",

        organisation=(
            "Indian National Centre for Ocean "
            "Information Services"
        ),

        tier=SourceTier.INDIA_OPERATIONAL,

        base_url=(
            "https://www.incois.gov.in/"
            "MarineFisheries/PfzWebGis"
        ),

        capabilities=frozenset({
            PFZ,
        }),

        official=True,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "Interactive PFZ WebGIS. "
            "Use only documented/stable machine endpoints "
            "discovered from the official service."
        ),
    ),


    # --------------------------------------------------------
    # INCOIS PFZ geospatial portal
    # --------------------------------------------------------

    "incois_pfz_geoportal": SourceSpec(

        key="incois_pfz_geoportal",

        name="INCOIS PFZ Geoportal",

        organisation=(
            "Indian National Centre for Ocean "
            "Information Services"
        ),

        tier=SourceTier.INDIA_OPERATIONAL,

        base_url=(
            "https://incois.gov.in/"
            "geoportal/MFASPFZ/index.html"
        ),

        capabilities=frozenset({
            PFZ,
            SST,
            CHLOROPHYLL,
            EEZ,
            LANDING_CENTRES,
            BATHYMETRY,
        }),

        official=True,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "Official PFZ map portal containing "
            "SST, chlorophyll, PFZ advisory, EEZ, "
            "sectors, landing centres and bathymetry layers."
        ),
    ),


    # --------------------------------------------------------
    # INCOIS Ocean State Forecast
    # --------------------------------------------------------

    "incois_osf": SourceSpec(

        key="incois_osf",

        name="INCOIS Ocean State Forecast",

        organisation=(
            "Indian National Centre for Ocean "
            "Information Services"
        ),

        tier=SourceTier.INDIA_OPERATIONAL,

        base_url=(
            "https://www.incois.gov.in/"
            "oceanservices/osfforecast.jsp"
        ),

        capabilities=frozenset({
            WIND,
            WAVE_HEIGHT,
            WAVE_DIRECTION,
            WAVE_PERIOD,
            SWELL_HEIGHT,
            SWELL_PERIOD,
            SURFACE_CURRENT,
            SST,
            MIXED_LAYER_DEPTH,
            D20,
            SEA_STATE,
        }),

        official=True,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "Primary Indian ocean-state forecast source. "
            "Dedicated connector should normalize values "
            "into TARANG units."
        ),
    ),


    # --------------------------------------------------------
    # INCOIS ERDDAP
    # --------------------------------------------------------

    "incois_erddap": SourceSpec(

        key="incois_erddap",

        name="INCOIS ERDDAP",

        organisation=(
            "Indian National Centre for Ocean "
            "Information Services"
        ),

        tier=SourceTier.INDIA_SCIENTIFIC,

        base_url=(
            "https://erddap.incois.gov.in/erddap"
        ),

        capabilities=frozenset({
            ARGO,
            BUOY_DATA,
        }),

        official=True,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "Machine-readable scientific-data server. "
            "Capabilities should be expanded only after "
            "specific datasets have been verified."
        ),
    ),


    # --------------------------------------------------------
    # IMD marine forecast / fishermen warning
    # --------------------------------------------------------

    "imd_marine": SourceSpec(

        key="imd_marine",

        name="IMD Marine Forecast and Fishermen Warning",

        organisation=(
            "India Meteorological Department"
        ),

        tier=SourceTier.INDIA_OPERATIONAL,

        base_url=(
            "https://mausam.imd.gov.in/"
            "responsive/marine_forecast.php"
        ),

        capabilities=frozenset({
            FISHERMEN_WARNING,
            CYCLONE_WARNING,
            THUNDERSTORM_WARNING,
            HIGH_WAVE_WARNING,
            SEA_STATE,
            WIND,
        }),

        official=True,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "Official marine/fishermen warning source. "
            "Warnings should override benign model forecasts "
            "in safety decisions."
        ),
    ),


    # --------------------------------------------------------
    # ISRO / NRSC Bhoonidhi
    # --------------------------------------------------------

    "bhoonidhi": SourceSpec(

        key="bhoonidhi",

        name="ISRO NRSC Bhoonidhi",

        organisation=(
            "National Remote Sensing Centre / ISRO"
        ),

        tier=SourceTier.INDIA_SCIENTIFIC,

        base_url=(
            "https://bhoonidhi-api.nrsc.gov.in"
        ),

        capabilities=frozenset({
            SATELLITE_CHLOROPHYLL,
            CHLOROPHYLL,
            OCEAN_COLOUR,
            SATELLITE_SST,
        }),

        official=True,

        authentication_required=True,

        live_or_near_real_time=False,

        notes=(
            "Authenticated satellite catalogue/API. "
            "EOS-06 OCM chlorophyll collections are available. "
            "Credentials must stay server-side in environment "
            "variables and never be exposed to frontend JS."
        ),
    ),


    # --------------------------------------------------------
    # Open-Meteo
    # --------------------------------------------------------

    "openmeteo": SourceSpec(

        key="openmeteo",

        name="Open-Meteo Weather and Marine",

        organisation="Open-Meteo",

        tier=SourceTier.FALLBACK,

        base_url=(
            "https://api.open-meteo.com"
        ),

        capabilities=frozenset({
            AIR_TEMPERATURE,
            APPARENT_TEMPERATURE,
            HUMIDITY,
            RAIN,
            CLOUD_COVER,
            PRESSURE,
            VISIBILITY,
            WIND,
            WIND_GUST,
            SST,
            WAVE_HEIGHT,
            WAVE_DIRECTION,
            WAVE_PERIOD,
            SURFACE_CURRENT,
        }),

        official=False,

        authentication_required=False,

        live_or_near_real_time=True,

        notes=(
            "General weather/marine fallback. "
            "Already integrated in TARANG. "
            "Indian official operational advisories should "
            "take priority when available."
        ),
    ),
}


# ============================================================
# CAPABILITY PRIORITY
# ============================================================

#
# Order matters.
#
# First source = preferred source.
# Following sources = fallback sources.
#


SOURCE_PRIORITY: dict[str, tuple[str, ...]] = {


    PFZ: (
        "incois_pfz_text",
        "incois_pfz_webgis",
        "incois_pfz_geoportal",
    ),


    CHLOROPHYLL: (
        "incois_pfz_geoportal",
        "bhoonidhi",
    ),


    SATELLITE_CHLOROPHYLL: (
        "bhoonidhi",
    ),


    SST: (
        "incois_osf",
        "incois_pfz_geoportal",
        "openmeteo",
    ),


    WAVE_HEIGHT: (
        "incois_osf",
        "openmeteo",
    ),


    WAVE_DIRECTION: (
        "incois_osf",
        "openmeteo",
    ),


    WAVE_PERIOD: (
        "incois_osf",
        "openmeteo",
    ),


    SWELL_HEIGHT: (
        "incois_osf",
    ),


    SWELL_PERIOD: (
        "incois_osf",
    ),


    SURFACE_CURRENT: (
        "incois_osf",
        "openmeteo",
    ),


    WIND: (
        "imd_marine",
        "incois_osf",
        "openmeteo",
    ),


    FISHERMEN_WARNING: (
        "imd_marine",
    ),


    CYCLONE_WARNING: (
        "imd_marine",
    ),


    THUNDERSTORM_WARNING: (
        "imd_marine",
    ),


    HIGH_WAVE_WARNING: (
        "imd_marine",
    ),


    SEA_STATE: (
        "imd_marine",
        "incois_osf",
    ),


    MIXED_LAYER_DEPTH: (
        "incois_osf",
    ),


    D20: (
        "incois_osf",
    ),


    EEZ: (
        "incois_pfz_geoportal",
    ),


    LANDING_CENTRES: (
        "incois_pfz_geoportal",
    ),


    BATHYMETRY: (
        "incois_pfz_geoportal",
    ),


    AIR_TEMPERATURE: (
        "openmeteo",
    ),


    APPARENT_TEMPERATURE: (
        "openmeteo",
    ),


    HUMIDITY: (
        "openmeteo",
    ),


    RAIN: (
        "openmeteo",
    ),


    CLOUD_COVER: (
        "openmeteo",
    ),


    PRESSURE: (
        "openmeteo",
    ),


    VISIBILITY: (
        "openmeteo",
    ),


    WIND_GUST: (
        "openmeteo",
    ),


    ARGO: (
        "incois_erddap",
    ),


    BUOY_DATA: (
        "incois_erddap",
    ),
}


# ============================================================
# REGISTRY API
# ============================================================


def get_source(
    key: str,
) -> SourceSpec:
    """
    Return one registered source by key.
    """

    try:

        return SOURCES[key]

    except KeyError as exc:

        raise KeyError(
            f"Unknown TARANG data source: {key}"
        ) from exc


def all_sources() -> list[SourceSpec]:
    """
    Return every registered source sorted by priority tier.
    """

    return sorted(
        SOURCES.values(),
        key=lambda source: (
            source.tier,
            source.name,
        ),
    )


def sources_for(
    capability: str,
) -> list[SourceSpec]:
    """
    Return sources for a capability in TARANG priority order.

    Example:

        sources_for("wave_height")

    returns roughly:

        INCOIS OSF
        Open-Meteo
    """

    priority_keys = (
        SOURCE_PRIORITY.get(
            capability,
            (),
        )
    )


    return [
        SOURCES[key]
        for key in priority_keys
        if key in SOURCES
    ]


def best_source(
    capability: str,
) -> SourceSpec | None:
    """
    Return TARANG's preferred source for a capability.
    """

    candidates = sources_for(
        capability
    )


    if not candidates:

        return None


    return candidates[0]


def source_supports(
    source_key: str,
    capability: str,
) -> bool:
    """
    Return True when a registered source claims support
    for a capability.
    """

    source = get_source(
        source_key
    )


    return (
        capability
        in source.capabilities
    )


def capabilities_for(
    source_key: str,
) -> set[str]:
    """
    Return capabilities supported by a source.
    """

    return set(
        get_source(
            source_key
        ).capabilities
    )


def registered_capabilities() -> set[str]:
    """
    Return every capability known by TARANG.
    """

    capabilities: set[str] = set()


    for source in SOURCES.values():

        capabilities.update(
            source.capabilities
        )


    return capabilities


def validate_registry() -> list[str]:
    """
    Validate registry consistency.

    Returns:
        [] if everything is valid.

    Otherwise returns human-readable validation problems.
    """

    problems: list[str] = []


    for capability, source_keys in SOURCE_PRIORITY.items():

        if not source_keys:

            problems.append(
                f"{capability}: no sources configured"
            )

            continue


        for source_key in source_keys:

            if source_key not in SOURCES:

                problems.append(
                    f"{capability}: unknown source "
                    f"{source_key}"
                )

                continue


            source = SOURCES[source_key]


            if capability not in source.capabilities:

                problems.append(
                    f"{capability}: source "
                    f"{source_key} does not declare "
                    f"this capability"
                )


    return problems


def describe_registry() -> str:
    """
    Return a compact human-readable source summary.

    Useful for debugging from terminal.
    """

    lines: list[str] = []


    for capability in sorted(
        SOURCE_PRIORITY
    ):

        names = [
            source.name
            for source in sources_for(
                capability
            )
        ]


        lines.append(
            f"{capability}: "
            + " -> ".join(names)
        )


    return "\n".join(
        lines
    )


# ============================================================
# STARTUP SELF-CHECK
# ============================================================


_REGISTRY_PROBLEMS = (
    validate_registry()
)


if _REGISTRY_PROBLEMS:

    raise RuntimeError(
        "Invalid TARANG source registry:\n"
        + "\n".join(
            _REGISTRY_PROBLEMS
        )
    )