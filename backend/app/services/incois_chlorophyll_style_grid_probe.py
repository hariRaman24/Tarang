"""
TARANG - INCOIS Chlorophyll Style + Offshore Grid Probe
=======================================================

Purpose
-------
The previous tests proved that the official INCOIS GeoServer exposes a
chlorophyll raster named "chl", but:
- Chennai-area GetFeatureInfo returned only NoData/null.
- WCS metadata did not state a physical unit.

This probe now checks TWO missing pieces:
1. Does the WMS style/SLD reveal the raster value scale or labels?
2. Are there any non-null chlorophyll pixels elsewhere in Indian waters?

It prints only a compact summary.

Run:
    python -m app.services.incois_chlorophyll_style_grid_probe

Output:
    incois_chlorophyll_style_grid_probe_report.json
"""

from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
LAYER = "chl"
TIMEOUT = 35.0


# A small set of offshore points across Indian waters.
# These are diagnostic sample points only.
TEST_POINTS = [
    ("Chennai offshore", 13.00, 81.50),
    ("North Tamil Nadu offshore", 12.00, 81.50),
    ("Nagapattinam offshore", 10.75, 81.50),
    ("Bay of Bengal central", 13.00, 84.00),
    ("Odisha offshore", 19.00, 86.50),
    ("Andhra offshore", 16.00, 83.50),
    ("South Bay of Bengal", 8.00, 82.00),
    ("Kochi offshore", 10.00, 75.00),
    ("Kerala offshore", 9.00, 74.00),
    ("Goa offshore", 15.50, 72.50),
    ("Arabian Sea central", 15.00, 69.00),
    ("Gujarat offshore", 20.00, 68.00),
    ("Lakshadweep area", 11.00, 72.00),
    ("Indian Ocean south", 5.00, 80.00),
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


def _layer_style_info(xml_text: str) -> dict[str, Any]:
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

        name = _child_text(node, "Name")
        if name != LAYER:
            continue

        result["layer_found"] = True
        result["title"] = _child_text(node, "Title")
        result["abstract"] = _child_text(node, "Abstract")

        for child in node:
            if _local(child.tag) != "Style":
                continue

            style = {
                "name": _child_text(child, "Name"),
                "title": _child_text(child, "Title"),
                "abstract": _child_text(child, "Abstract"),
                "legend_url": None,
            }

            for item in child.iter():
                if _local(item.tag) == "OnlineResource":
                    for key, value in item.attrib.items():
                        if key.endswith("href"):
                            style["legend_url"] = value
                            break

            result["styles"].append(style)

        break

    return result


def _parse_sld(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "color_map_entries": [],
        "titles": [],
        "abstracts": [],
        "raw_keywords": [],
    }

    try:
        root = ET.fromstring(text)
    except Exception:
        return result

    for node in root.iter():
        tag = _local(node.tag)

        if tag == "ColorMapEntry":
            result["color_map_entries"].append(
                {
                    "color": node.attrib.get("color"),
                    "quantity": node.attrib.get("quantity"),
                    "label": node.attrib.get("label"),
                    "opacity": node.attrib.get("opacity"),
                }
            )

        elif tag == "Title":
            value = (node.text or "").strip()
            if value and value not in result["titles"]:
                result["titles"].append(value)

        elif tag == "Abstract":
            value = (node.text or "").strip()
            if value and value not in result["abstracts"]:
                result["abstracts"].append(value)

    lower = text.lower()
    for word in ["mg/m3", "mg m-3", "chlorophyll", "chlor_a", "chl", "log"]:
        if word in lower:
            result["raw_keywords"].append(word)

    return result


async def _feature_info(
    client: httpx.AsyncClient,
    *,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    half = 0.12

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": LAYER,
        "QUERY_LAYERS": LAYER,
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

    response = await client.get(WMS_URL, params=params)
    response.raise_for_status()

    payload = response.json()

    value = None
    props = None

    features = payload.get("features") or []
    if features:
        props = features[0].get("properties") or {}
        value = props.get("GRAY_INDEX")

    return {
        "status_code": response.status_code,
        "gray_index": value,
        "properties": props,
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
        "capabilities": {},
        "style": {},
        "samples": [],
        "non_null_samples": [],
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:

        print()
        print("TARANG — CHLOROPHYLL STYLE + OFFSHORE GRID PROBE")
        print("=" * 78)

        # ------------------------------------------------------------
        # 1. WMS capabilities / style info
        # ------------------------------------------------------------
        print()
        print("STEP 1 — WMS LAYER + STYLE METADATA")
        print("-" * 78)

        capabilities = await client.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetCapabilities",
            },
        )
        capabilities.raise_for_status()

        info = _layer_style_info(capabilities.text)
        report["capabilities"] = info

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

        # ------------------------------------------------------------
        # 2. GetStyles / SLD
        # ------------------------------------------------------------
        print()
        print("STEP 2 — GETSTYLES / SLD")
        print("-" * 78)

        try:
            style_response = await client.get(
                WMS_URL,
                params={
                    "SERVICE": "WMS",
                    "VERSION": "1.1.1",
                    "REQUEST": "GetStyles",
                    "LAYERS": LAYER,
                },
            )

            report["style"]["status_code"] = style_response.status_code
            report["style"]["content_type"] = style_response.headers.get(
                "content-type"
            )

            print(f"GetStyles HTTP {style_response.status_code}")

            if style_response.status_code == 200:
                parsed_sld = _parse_sld(style_response.text)
                report["style"]["parsed_sld"] = parsed_sld

                entries = parsed_sld["color_map_entries"]

                print(f"ColorMap entries: {len(entries)}")

                for entry in entries[:20]:
                    print(
                        "  "
                        f"quantity={entry.get('quantity')}  "
                        f"label={entry.get('label')}  "
                        f"color={entry.get('color')}"
                    )

                if parsed_sld["titles"]:
                    print("SLD titles:", parsed_sld["titles"])

                if parsed_sld["abstracts"]:
                    print("SLD abstracts:", parsed_sld["abstracts"])

                if parsed_sld["raw_keywords"]:
                    print("Detected keywords:", parsed_sld["raw_keywords"])
            else:
                report["style"]["preview"] = style_response.text[:3000]

        except Exception as exc:
            report["style"]["error"] = str(exc)
            print(f"GetStyles ERROR: {exc}")

        # ------------------------------------------------------------
        # 3. Broad offshore sampling
        # ------------------------------------------------------------
        print()
        print("STEP 3 — OFFSHORE PIXEL TESTS")
        print("-" * 78)

        for name, lat, lon in TEST_POINTS:
            try:
                sample = await _feature_info(
                    client,
                    lat=lat,
                    lon=lon,
                )

                record = {
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    **sample,
                }

                report["samples"].append(record)

                value = sample["gray_index"]

                print(
                    f"{name:<28} "
                    f"({lat:6.2f}, {lon:6.2f}) -> {value}"
                )

                if value is not None:
                    report["non_null_samples"].append(record)

            except Exception as exc:
                record = {
                    "name": name,
                    "latitude": lat,
                    "longitude": lon,
                    "error": str(exc),
                }

                report["samples"].append(record)

                print(
                    f"{name:<28} "
                    f"({lat:6.2f}, {lon:6.2f}) -> ERROR"
                )

        print()
        print(
            "Non-null offshore samples: "
            f"{len(report['non_null_samples'])}"
        )

    output = (
        Path.cwd()
        / "incois_chlorophyll_style_grid_probe_report.json"
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

    if report["non_null_samples"]:
        print(
            "RESULT: non-null chlorophyll raster pixels exist. "
            "Use the SLD metadata above to decide whether the values "
            "can be interpreted physically."
        )
    else:
        print(
            "RESULT: the exposed 'chl' raster returned NoData at all "
            "tested offshore points. Do not integrate a chlorophyll "
            "number from this layer yet."
        )

    print()
    print("Saved report:")
    print(output)


if __name__ == "__main__":
    asyncio.run(main())
