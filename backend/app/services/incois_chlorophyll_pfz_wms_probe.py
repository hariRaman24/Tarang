"""
TARANG - Official INCOIS Chlorophyll WMS Probe
==============================================

This is a focused probe for the PFZ/TUNA satellite WMS that the INCOIS
fishery geoportals use for SST/Chlorophyll display.

It:
1. Reads WMS GetCapabilities.
2. Prints ONLY chlorophyll-related layer names.
3. If a chlorophyll layer is found, performs a small GetFeatureInfo query
   around the requested latitude/longitude.
4. Saves a compact JSON report.

No SSL bypass. No simulated values.

Run:
    python -m app.services.incois_chlorophyll_pfz_wms_probe --lat 13.05 --lon 80.28
"""

from __future__ import annotations

import argparse
import asyncio
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
TIMEOUT = 35.0


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find_child_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if _local_name(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def _extract_layers(xml_text: str) -> list[dict[str, str | None]]:
    root = ET.fromstring(xml_text)
    layers: list[dict[str, str | None]] = []

    for node in root.iter():
        if _local_name(node.tag) != "Layer":
            continue

        name = _find_child_text(node, "Name")
        title = _find_child_text(node, "Title")

        if name:
            layers.append(
                {
                    "name": name,
                    "title": title,
                }
            )

    return layers


def _is_chl_layer(item: dict[str, str | None]) -> bool:
    text = " ".join(
        [
            item.get("name") or "",
            item.get("title") or "",
        ]
    ).lower()

    return (
        "chlor" in text
        or "chl" in text
        or "chlor_a" in text
    )


async def _get_feature_info(
    client: httpx.AsyncClient,
    *,
    layer_name: str,
    lat: float,
    lon: float,
) -> dict[str, Any]:
    # Small geographic window centred on the query point.
    half = 0.15

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": layer_name,
        "QUERY_LAYERS": layer_name,
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

    result: dict[str, Any] = {
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "text_preview": response.text[:3000],
    }

    try:
        result["json"] = response.json()
    except Exception:
        result["json"] = None

    return result


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
        "source": "INCOIS PFZ/TUNA SST-CHL GeoServer WMS",
        "wms_url": WMS_URL,
        "query": {
            "latitude": args.lat,
            "longitude": args.lon,
        },
        "capabilities_ok": False,
        "chlorophyll_layers": [],
        "feature_info_tests": [],
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:

        print()
        print("INCOIS CHLOROPHYLL WMS PROBE")
        print("=" * 78)

        cap = await client.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetCapabilities",
            },
        )

        print(f"GetCapabilities: HTTP {cap.status_code}")

        cap.raise_for_status()

        layers = _extract_layers(cap.text)
        chl_layers = [
            item
            for item in layers
            if _is_chl_layer(item)
        ]

        report["capabilities_ok"] = True
        report["all_layer_count"] = len(layers)
        report["chlorophyll_layers"] = chl_layers

        print()
        print("Chlorophyll-related layers:")
        print("-" * 78)

        if not chl_layers:
            print("NONE FOUND")
        else:
            for index, item in enumerate(chl_layers, start=1):
                print(
                    f"{index}. {item['name']}"
                    + (
                        f"  |  {item['title']}"
                        if item.get("title")
                        else ""
                    )
                )

        for item in chl_layers[:5]:
            layer_name = item["name"]

            if not layer_name:
                continue

            print()
            print(
                f"GetFeatureInfo test: {layer_name}"
            )
            print("-" * 78)

            try:
                info = await _get_feature_info(
                    client,
                    layer_name=layer_name,
                    lat=args.lat,
                    lon=args.lon,
                )

                report[
                    "feature_info_tests"
                ].append(
                    {
                        "layer": layer_name,
                        **info,
                    }
                )

                print(
                    f"HTTP {info['status_code']}  "
                    f"{info.get('content_type')}"
                )

                if info.get("json") is not None:
                    print(
                        json.dumps(
                            info["json"],
                            indent=2,
                            ensure_ascii=False,
                        )[:2500]
                    )
                else:
                    print(
                        info["text_preview"][:2500]
                    )

            except Exception as exc:
                report[
                    "feature_info_tests"
                ].append(
                    {
                        "layer": layer_name,
                        "error": str(exc),
                    }
                )
                print(f"ERROR: {exc}")

    output = (
        Path.cwd()
        / "incois_chlorophyll_pfz_wms_probe_report.json"
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
