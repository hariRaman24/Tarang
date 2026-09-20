"""Versioned geofence catalogue.

The current public prototype geometry is deliberately marked approximate.
It must not be presented as a legal boundary or navigation-grade chart.
Authoritative polygons can replace these entries without changing callers.
""" 

import json
import os
from pathlib import Path

from shapely.geometry import shape

from app.geo.engine import GeoZone, circle_zone

GULF_OF_MANNAR_MPA: GeoZone = circle_zone(
    name="Gulf of Mannar Marine Park",
    center_lat=9.15,
    center_lon=79.15,
    radius_km=14,
    kind="protected",
)
GULF_OF_MANNAR_MPA.source = "TARANG prototype approximation"
GULF_OF_MANNAR_MPA.source_url = (
    "https://www.wii.gov.in/gulf-of-mannar-marine-biosphere-reserve"
)
GULF_OF_MANNAR_MPA.dataset_version = "prototype-2026-09"
GULF_OF_MANNAR_MPA.geometry_status = "APPROXIMATE_PUBLIC_REFERENCE"
GULF_OF_MANNAR_MPA.authoritative = False

FALLBACK_ZONES: list[GeoZone] = [GULF_OF_MANNAR_MPA]


def load_geojson_zones(path: str | Path) -> tuple[list[GeoZone], dict]:
    """Load validated GeoJSON FeatureCollection zone polygons."""
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    if document.get("type") != "FeatureCollection":
        raise ValueError("Geofence file must be a GeoJSON FeatureCollection.")

    metadata = document.get("metadata") or {}
    source = metadata.get("source")
    version = metadata.get("version")
    source_url = metadata.get("source_url")
    if not source or not version:
        raise ValueError(
            "Authoritative geofence GeoJSON must include metadata.source and metadata.version."
        )

    zones: list[GeoZone] = []
    for index, feature in enumerate(document.get("features") or []):
        geometry = feature.get("geometry")
        properties = feature.get("properties") or {}
        name = properties.get("name")
        if not name or not geometry:
            raise ValueError(
                f"Geofence feature {index} requires geometry and properties.name."
            )
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid:
            raise ValueError(f"Geofence feature {index} has invalid geometry.")
        if polygon.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Geofence feature {index} must be Polygon or MultiPolygon."
            )
        zones.append(
            GeoZone(
                name=name,
                polygon=polygon,
                kind=properties.get("kind", "protected"),
                source=source,
                source_url=source_url,
                dataset_version=version,
                authoritative=True,
                geometry_status="AUTHORITATIVE_GEOJSON",
            )
        )

    if not zones:
        raise ValueError("Authoritative geofence GeoJSON contains no features.")

    catalogue = {
        "dataset_name": metadata.get("name", source),
        "dataset_version": version,
        "authoritative_dataset_loaded": True,
        "source": source,
        "source_url": source_url,
        "coverage_note": (
            "Authoritative GeoJSON polygons are loaded. Confirm the dataset "
            "scope and validity dates with the publishing authority."
        ),
    }
    return zones, catalogue


def _load_configured_catalogue() -> tuple[list[GeoZone], dict]:
    configured_path = os.getenv("TARANG_GEOFENCE_GEOJSON", "").strip()
    if not configured_path:
        return FALLBACK_ZONES, {
            "dataset_name": "TARANG public geofence catalogue",
            "dataset_version": "prototype-2026-09",
            "authoritative_dataset_loaded": False,
            "coverage_note": (
                "Only an approximate Gulf of Mannar reference geometry is loaded. "
                "This is not a complete list of protected, restricted or boundary zones."
            ),
        }
    try:
        return load_geojson_zones(configured_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return FALLBACK_ZONES, {
            "dataset_name": "TARANG public geofence catalogue",
            "dataset_version": "prototype-2026-09",
            "authoritative_dataset_loaded": False,
            "configuration_error": str(exc),
            "coverage_note": (
                "Configured authoritative geofence data could not be loaded; "
                "the approximate fallback is active."
            ),
        }


ALL_ZONES, ZONE_CATALOGUE = _load_configured_catalogue()
