"""
TARANG - INCOIS Landing Centre WFS Inspector
=============================================

Reads the official INCOIS landing-centre WFS layer discovered from the
INCOIS PFZ Geoportal:

    PFZ_LandingCentres:LandingCenters_29Apr2024

Purpose:
    1. Confirm the official landing-centre GeoJSON endpoint.
    2. Inspect property names such as landing-centre name/state/district.
    3. Inspect coordinates and feature count.
    4. Save a report for the next TARANG integration step.

Run from backend:

    python -m app.services.incois_landing_centres_probe
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
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


class IncoisLandingCentreError(RuntimeError):
    pass


async def fetch_landing_centres() -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "application/json,application/geo+json,*/*",
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            response = await client.get(
                WFS_URL,
                params=WFS_PARAMS,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise IncoisLandingCentreError(
                "INCOIS landing-centre WFS timed out."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise IncoisLandingCentreError(
                f"INCOIS landing-centre WFS returned HTTP "
                f"{exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise IncoisLandingCentreError(
                f"Could not reach INCOIS landing-centre WFS: {exc}"
            ) from exc

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

    if not isinstance(payload.get("features"), list):
        raise IncoisLandingCentreError(
            "FeatureCollection has no valid features array."
        )

    return payload


def build_report(payload: dict[str, Any]) -> dict[str, Any]:
    features = payload.get("features", [])

    geometry_types = Counter()
    property_keys: set[str] = set()
    examples: dict[str, list[Any]] = {}

    min_lon = None
    min_lat = None
    max_lon = None
    max_lat = None

    samples: list[dict[str, Any]] = []

    for feature in features:
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type", "None")
        geometry_types[geometry_type] += 1

        props = feature.get("properties") or {}

        if isinstance(props, dict):
            for key, value in props.items():
                property_keys.add(key)

                if value is not None and value != "":
                    bucket = examples.setdefault(key, [])
                    if len(bucket) < 8 and value not in bucket:
                        bucket.append(value)

        coords = geometry.get("coordinates")

        if (
            geometry_type == "Point"
            and isinstance(coords, list)
            and len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            lon = float(coords[0])
            lat = float(coords[1])

            min_lon = lon if min_lon is None else min(min_lon, lon)
            max_lon = lon if max_lon is None else max(max_lon, lon)
            min_lat = lat if min_lat is None else min(min_lat, lat)
            max_lat = lat if max_lat is None else max(max_lat, lat)

        if len(samples) < 10:
            samples.append(
                {
                    "id": feature.get("id"),
                    "geometry": geometry,
                    "properties": props,
                }
            )

    bounds = None

    if None not in (min_lon, min_lat, max_lon, max_lat):
        bounds = {
            "min_lon": round(min_lon, 6),
            "min_lat": round(min_lat, 6),
            "max_lon": round(max_lon, 6),
            "max_lat": round(max_lat, 6),
        }

    return {
        "source": "INCOIS Landing Centres GeoServer WFS",
        "endpoint": WFS_URL,
        "layer": WFS_PARAMS["typeName"],
        "feature_count": len(features),
        "crs": payload.get("crs"),
        "geometry_types": dict(geometry_types),
        "bounds": bounds,
        "property_keys": sorted(property_keys),
        "property_examples": {
            key: examples.get(key, [])
            for key in sorted(property_keys)
        },
        "sample_features": samples,
    }


def print_report(report: dict[str, Any]) -> None:
    print()
    print("TARANG — INCOIS LANDING CENTRE WFS INSPECTION")
    print("=" * 72)

    print(f"Source:   {report['source']}")
    print(f"Layer:    {report['layer']}")
    print(f"Features: {report['feature_count']}")
    print(f"CRS:      {report['crs']}")
    print(f"Geometry: {report['geometry_types']}")
    print(f"Bounds:   {report['bounds']}")

    print()
    print("PROPERTY KEYS")
    print("-" * 72)

    for key in report["property_keys"]:
        print(
            f"{key}: "
            f"{report['property_examples'].get(key, [])}"
        )

    print()
    print("SAMPLE FEATURES")
    print("-" * 72)

    for index, feature in enumerate(
        report["sample_features"],
        start=1,
    ):
        print()
        print(f"Feature {index}")
        print(
            json.dumps(
                feature,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )


async def main() -> None:
    try:
        payload = await fetch_landing_centres()
        report = build_report(payload)

        print_report(report)

        output_path = (
            Path.cwd()
            / "incois_landing_centres_report.json"
        )

        output_path.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        print()
        print("=" * 72)
        print("Saved report:")
        print(output_path)
        print()
        print(
            "NEXT: Send me the PROPERTY KEYS and first few SAMPLE FEATURES. "
            "Then TARANG can attach real landing-centre names to nearby PFZs."
        )

    except IncoisLandingCentreError as exc:
        print()
        print("INCOIS LANDING CENTRE ERROR")
        print("=" * 72)
        print(str(exc))


if __name__ == "__main__":
    asyncio.run(main())
