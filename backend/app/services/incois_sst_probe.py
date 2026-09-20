"""
TARANG - Official INCOIS SST Probe
==================================

Focused validation probe for the INCOIS PFZ-TUNA-SST-CHL GeoServer SST layer.

This probe:
1. Confirms the WMS layer name "sst".
2. Prints the configured style name/title.
3. Reads the SLD to discover the SST unit / scale.
4. Queries SST at:
   - current Chennai PFZ 045 point
   - one offshore validation point

No simulated values. No SSL bypass.

Run:
    python -m app.services.incois_sst_probe
"""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
LAYER = "sst"
TIMEOUT = 35.0

TEST_POINTS = [
    ("PFZ 045 Chennai", 12.967294, 80.460044),
    ("Offshore validation", 8.00, 82.00),
]


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if _local(child.tag) == name:
            value = (child.text or "").strip()
            if value:
                return value
    return None


def _layer_info(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)

    result: dict[str, Any] = {
        "layer_found": False,
        "title": None,
        "abstract": None,
        "styles": [],
    }

    for node in root.iter():
        if _local(node.tag) != "Layer":
            continue

        if _child_text(node, "Name") != LAYER:
            continue

        result["layer_found"] = True
        result["title"] = _child_text(node, "Title")
        result["abstract"] = _child_text(node, "Abstract")

        for child in node:
            if _local(child.tag) != "Style":
                continue

            result["styles"].append(
                {
                    "name": _child_text(child, "Name"),
                    "title": _child_text(child, "Title"),
                    "abstract": _child_text(child, "Abstract"),
                }
            )

        break

    return result


def _parse_sld(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "titles": [],
        "abstracts": [],
        "color_map_entries": [],
        "detected_keywords": [],
    }

    try:
        root = ET.fromstring(text)
    except Exception:
        return result

    for node in root.iter():
        tag = _local(node.tag)

        if tag == "Title":
            value = (node.text or "").strip()
            if value and value not in result["titles"]:
                result["titles"].append(value)

        elif tag == "Abstract":
            value = (node.text or "").strip()
            if value and value not in result["abstracts"]:
                result["abstracts"].append(value)

        elif tag == "ColorMapEntry":
            result["color_map_entries"].append(
                {
                    "quantity": node.attrib.get("quantity"),
                    "label": node.attrib.get("label"),
                    "color": node.attrib.get("color"),
                    "opacity": node.attrib.get("opacity"),
                }
            )

    lower = text.lower()

    for keyword in [
        "sst",
        "temperature",
        "degc",
        "degree",
        "celsius",
        "°c",
        "no data",
        "nodata",
    ]:
        if keyword in lower:
            result["detected_keywords"].append(keyword)

    return result


async def _feature_info(
    client: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
    style: str | None,
) -> dict[str, Any]:
    half = 0.06

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": LAYER,
        "QUERY_LAYERS": LAYER,
        "STYLES": style or "",
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

    response = await client.get(WMS_URL, params=params)
    response.raise_for_status()

    payload = response.json()

    props = None
    value = None

    features = payload.get("features") or []

    if features:
        props = features[0].get("properties") or {}

        # GeoServer raster feature info commonly exposes GRAY_INDEX.
        value = props.get("GRAY_INDEX")

        if value is None:
            # Keep any other single raster attribute visible for debugging.
            numeric_candidates = [
                v
                for v in props.values()
                if isinstance(v, (int, float))
            ]

            if numeric_candidates:
                value = numeric_candidates[0]

    return {
        "status_code": response.status_code,
        "properties": props,
        "value": value,
        "url": str(response.url),
    }


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        )
    }

    report: dict[str, Any] = {
        "source": "INCOIS PFZ-TUNA-SST-CHL GeoServer WMS",
        "wms_url": WMS_URL,
        "layer": LAYER,
        "layer_info": {},
        "style": {},
        "samples": [],
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:

        print()
        print("TARANG — INCOIS SST PROBE")
        print("=" * 78)

        print()
        print("STEP 1 — WMS LAYER METADATA")
        print("-" * 78)

        cap = await client.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetCapabilities",
            },
        )
        cap.raise_for_status()

        info = _layer_info(cap.text)
        report["layer_info"] = info

        print(f"Layer found: {info['layer_found']}")
        print(f"Title:       {info['title']}")
        print(f"Abstract:    {info['abstract']}")
        print("Styles:")

        if info["styles"]:
            for style in info["styles"]:
                print(
                    f"  - name={style.get('name')} "
                    f"title={style.get('title')}"
                )
        else:
            print("  NONE")

        style_name = (
            info["styles"][0].get("name")
            if info["styles"]
            else None
        )

        print()
        print("STEP 2 — GETSTYLES / SLD")
        print("-" * 78)

        style_response = await client.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetStyles",
                "LAYERS": LAYER,
            },
        )

        print(f"GetStyles HTTP {style_response.status_code}")

        if style_response.status_code == 200:
            parsed = _parse_sld(style_response.text)
            report["style"] = parsed

            if parsed["titles"]:
                print("SLD titles:", parsed["titles"])

            if parsed["abstracts"]:
                print("SLD abstracts:", parsed["abstracts"])

            if parsed["detected_keywords"]:
                print(
                    "Detected keywords:",
                    parsed["detected_keywords"],
                )

            entries = parsed["color_map_entries"]

            print(f"ColorMap entries: {len(entries)}")

            for entry in entries[:20]:
                print(
                    "  "
                    f"quantity={entry.get('quantity')}  "
                    f"label={entry.get('label')}  "
                    f"color={entry.get('color')}"
                )
        else:
            report["style"] = {
                "status_code": style_response.status_code,
                "preview": style_response.text[:3000],
            }

        print()
        print("STEP 3 — SST PIXEL TESTS")
        print("-" * 78)

        for name, lat, lon in TEST_POINTS:
            try:
                sample = await _feature_info(
                    client,
                    lat=lat,
                    lon=lon,
                    style=style_name,
                )

                record = {
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    **sample,
                }

                report["samples"].append(record)

                print(
                    f"{name:<24} "
                    f"({lat:.6f}, {lon:.6f}) -> "
                    f"{sample['value']}"
                )

                print(
                    f"  properties: {sample['properties']}"
                )

            except Exception as exc:
                report["samples"].append(
                    {
                        "name": name,
                        "latitude": lat,
                        "longitude": lon,
                        "error": str(exc),
                    }
                )

                print(
                    f"{name:<24} "
                    f"({lat:.6f}, {lon:.6f}) -> ERROR: {exc}"
                )

    output = (
        Path.cwd()
        / "incois_sst_probe_report.json"
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
    print("=" * 78)
    print("Saved report:")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
