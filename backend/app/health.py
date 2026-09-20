"""Operational health metadata for the TARANG API."""

from __future__ import annotations

from app.data.zones import ZONE_CATALOGUE
from app.services.source_registry import all_sources


def source_health_snapshot() -> list[dict]:
    return [
        {
            "key": source.key,
            "name": source.name,
            "organisation": source.organisation,
            "base_url": source.base_url,
            "official": source.official,
            "tier": int(source.tier),
            "capabilities": sorted(source.capabilities),
            "configured": True,
            "probe_status": "NOT_PROBED",
        }
        for source in all_sources()
    ]


def platform_health() -> dict:
    sources = source_health_snapshot()
    return {
        "platform": "TARANG",
        "status": "degraded" if not ZONE_CATALOGUE.get(
            "authoritative_dataset_loaded", False
        ) else "operational",
        "checks": {
            "source_registry": "ok",
            "conversation_store": "ok",
            "geofence_catalogue": (
                "authoritative"
                if ZONE_CATALOGUE.get("authoritative_dataset_loaded")
                else "approximate_fallback"
            ),
        },
        "sources": sources,
        "source_count": len(sources),
    }
