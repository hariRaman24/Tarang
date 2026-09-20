"""
TARANG - INCOIS Chlorophyll Value/Unit Probe
============================================

What we already know:
- Official INCOIS WMS exists.
- Chlorophyll layer name is: chl
- GetFeatureInfo works.
- At the exact Chennai test pixel, GRAY_INDEX was null.

This probe does TWO things:
1. Samples nearby sea pixels to find any non-null GRAY_INDEX values.
2. Inspects the same GeoServer's WCS metadata to determine whether the
   raster values can safely be interpreted as chlorophyll concentration.

IMPORTANT:
- GRAY_INDEX is NOT assumed to be mg/m3.
- No simulated fallback is used.
- SSL verification remains enabled.

Run:
    python -m app.services.incois_chlorophyll_value_probe --lat 13.05 --lon 80.28

Output:
    incois_chlorophyll_value_probe_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
WCS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wcs"
WMS_LAYER = "chl"

TIMEOUT = 35.0


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


async def _feature_info(
    client: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    half = 0.08

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": WMS_LAYER,
        "QUERY_LAYERS": WMS_LAYER,
        "STYLES": "",
        "SRS": "EPSG:4326",
        "BBOX": f"{lon-half},{lat-half},{lon+half},{lat+half}",
        "WIDTH": "101",
        "HEIGHT": "101",
        "X": "50",
        "Y": "50",
        "FORMAT": "image/png",
        "INFO_FORMAT": "application/json",
        "FEATURE_COUNT": "10",
    }

    response = await client.get(
        WMS_URL,
        params=params,
    )
    response.raise_for_status()

    payload = response.json()

    value = None

    features = payload.get("features") or []
    if features:
        properties = features[0].get("properties") or {}
        value = properties.get("GRAY_INDEX")

    return {
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "gray_index": value,
        "http_status": response.status_code,
        "url": str(response.url),
    }


def _offsets() -> list[tuple[float, float]]:
    """
    Search around the query point, biased eastward/offshore as well as
    north/south. This is only to identify valid raster pixels; it does not
    claim the nearest valid pixel is operationally the best location.
    """
    distances = [
        0.0,
        0.03,
        0.06,
        0.10,
        0.15,
        0.25,
        0.40,
    ]

    result: list[tuple[float, float]] = [(0.0, 0.0)]

    # East first (often offshore from Chennai), then N/S and west.
    for d in distances[1:]:
        result.extend(
            [
                (0.0, d),
                (d, d),
                (-d, d),
                (d, 0.0),
                (-d, 0.0),
                (0.0, -d),
            ]
        )

    return result


def _extract_wcs_coverages(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    names: list[str] = []

    for node in root.iter():
        tag = _local_name(node.tag).lower()

        if tag in {
            "name",
            "identifier",
            "coverageid",
        }:
            text = (node.text or "").strip()

            if "chl" in text.lower() and text not in names:
                names.append(text)

    return names


def _metadata_snippets(text: str) -> list[str]:
    keywords = [
        "chl",
        "chlor",
        "gray",
        "unit",
        "uom",
        "range",
        "nodata",
        "null",
        "datatype",
        "double",
        "float",
        "int",
        "band",
    ]

    snippets: list[str] = []
    lower = text.lower()

    for keyword in keywords:
        start = 0

        while True:
            index = lower.find(keyword, start)

            if index == -1:
                break

            left = max(0, index - 220)
            right = min(
                len(text),
                index + len(keyword) + 500,
            )

            snippet = " ".join(
                text[left:right]
                .replace("\r", " ")
                .replace("\n", " ")
                .split()
            )

            if snippet not in snippets:
                snippets.append(snippet)

            if len(snippets) >= 40:
                return snippets

            start = index + len(keyword)

    return snippets


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    args = parser.parse_args()

    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        )
    }

    report: dict[str, Any] = {
        "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer",
        "wms_url": WMS_URL,
        "wcs_url": WCS_URL,
        "layer": WMS_LAYER,
        "query": {
            "latitude": args.lat,
            "longitude": args.lon,
        },
        "samples": [],
        "non_null_samples": [],
        "wcs": {},
        "interpretation": (
            "Do not treat GRAY_INDEX as chlorophyll concentration until "
            "the WCS/coverage metadata confirms the measurement semantics."
        ),
    }

    print()
    print("TARANG — INCOIS CHLOROPHYLL VALUE / UNIT PROBE")
    print("=" * 82)

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:

        # ------------------------------------------------------------
        # 1. Search nearby pixels for non-null GRAY_INDEX
        # ------------------------------------------------------------
        print()
        print("STEP 1 — SEARCH NEARBY PIXELS")
        print("-" * 82)

        for dlat, dlon in _offsets():
            lat = args.lat + dlat
            lon = args.lon + dlon

            try:
                sample = await _feature_info(
                    client,
                    lat=lat,
                    lon=lon,
                )

                report["samples"].append(sample)

                value = sample["gray_index"]

                print(
                    f"{sample['latitude']:>10.5f}, "
                    f"{sample['longitude']:>10.5f}  ->  "
                    f"{value}"
                )

                if value is not None:
                    report[
                        "non_null_samples"
                    ].append(sample)

                    # We only need a few valid examples.
                    if len(
                        report["non_null_samples"]
                    ) >= 5:
                        break

            except Exception as exc:
                report["samples"].append(
                    {
                        "latitude": lat,
                        "longitude": lon,
                        "error": str(exc),
                    }
                )

                print(
                    f"{lat:>10.5f}, "
                    f"{lon:>10.5f}  ->  ERROR: {exc}"
                )

        print()
        print(
            f"Non-null samples found: "
            f"{len(report['non_null_samples'])}"
        )

        # ------------------------------------------------------------
        # 2. Inspect WCS GetCapabilities
        # ------------------------------------------------------------
        print()
        print("STEP 2 — WCS GETCAPABILITIES")
        print("-" * 82)

        try:
            cap = await client.get(
                WCS_URL,
                params={
                    "SERVICE": "WCS",
                    "REQUEST": "GetCapabilities",
                    "VERSION": "1.0.0",
                },
            )

            report["wcs"]["getcapabilities_status"] = (
                cap.status_code
            )

            print(
                f"GetCapabilities HTTP {cap.status_code}"
            )

            if cap.status_code == 200:
                coverages = _extract_wcs_coverages(
                    cap.text
                )

                report["wcs"]["chl_coverages"] = coverages

                print(
                    "Chlorophyll-like coverages:",
                    coverages or "NONE",
                )
            else:
                report["wcs"]["getcapabilities_preview"] = (
                    cap.text[:3000]
                )

        except Exception as exc:
            report["wcs"][
                "getcapabilities_error"
            ] = str(exc)

            print(
                f"WCS GetCapabilities ERROR: {exc}"
            )

        # ------------------------------------------------------------
        # 3. Describe likely chlorophyll coverage(s)
        # ------------------------------------------------------------
        coverage_candidates = (
            report["wcs"].get("chl_coverages")
            or [
                "chl",
                "PFZ-TUNA-SST-CHL:chl",
            ]
        )

        print()
        print("STEP 3 — WCS DESCRIBECOVERAGE")
        print("-" * 82)

        describe_results = []

        for coverage in coverage_candidates[:5]:
            try:
                response = await client.get(
                    WCS_URL,
                    params={
                        "SERVICE": "WCS",
                        "VERSION": "1.0.0",
                        "REQUEST": "DescribeCoverage",
                        "COVERAGE": coverage,
                    },
                )

                entry = {
                    "coverage": coverage,
                    "status_code": response.status_code,
                    "content_type": response.headers.get(
                        "content-type"
                    ),
                    "snippets": (
                        _metadata_snippets(
                            response.text
                        )
                        if response.status_code == 200
                        else []
                    ),
                    "preview": response.text[:4000],
                }

                describe_results.append(entry)

                print(
                    f"{coverage} -> HTTP "
                    f"{response.status_code}"
                )

                if (
                    response.status_code == 200
                    and entry["snippets"]
                ):
                    print(
                        "Metadata snippets:"
                    )

                    for snippet in entry[
                        "snippets"
                    ][:8]:
                        print(
                            "  ",
                            snippet,
                        )

            except Exception as exc:
                describe_results.append(
                    {
                        "coverage": coverage,
                        "error": str(exc),
                    }
                )

                print(
                    f"{coverage} -> ERROR: {exc}"
                )

        report["wcs"][
            "describe_coverage"
        ] = describe_results

    output = (
        Path.cwd()
        / "incois_chlorophyll_value_probe_report.json"
    )

    output.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 82)

    if report["non_null_samples"]:
        print(
            "RESULT: valid raster pixel(s) were found, "
            "but unit/meaning still must be verified from metadata."
        )
    else:
        print(
            "RESULT: no valid nearby chlorophyll raster pixel was found "
            "in this search window."
        )

    print()
    print("Saved report:")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
