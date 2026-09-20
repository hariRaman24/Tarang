"""
TARANG - INCOIS SST GetFeatureInfo Response Probe
=================================================

Purpose:
The SST WMS layer/style/unit are already verified.
The previous probe failed only because the GetFeatureInfo response was not JSON.

This script tests a few GetFeatureInfo formats and prints:
- HTTP status
- content type
- first part of the raw response

Run:
    python -m app.services.incois_sst_featureinfo_probe
"""

from __future__ import annotations

import asyncio
import httpx


WMS_URL = "https://incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/wms"
LAYER = "sst"
STYLE = "PFZ-TUNA-CHL-SST"
LAT = 12.967294
LON = 80.460044
TIMEOUT = 35.0


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        )
    }

    tests = [
        ("JSON + style", "application/json", STYLE),
        ("JSON no style", "application/json", ""),
        ("TEXT + style", "text/plain", STYLE),
        ("HTML + style", "text/html", STYLE),
        ("GML + style", "application/vnd.ogc.gml", STYLE),
    ]

    half = 0.06

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:

        print()
        print("TARANG — INCOIS SST GETFEATUREINFO RESPONSE PROBE")
        print("=" * 78)

        for label, info_format, style in tests:
            params = {
                "SERVICE": "WMS",
                "VERSION": "1.1.1",
                "REQUEST": "GetFeatureInfo",
                "LAYERS": LAYER,
                "QUERY_LAYERS": LAYER,
                "STYLES": style,
                "SRS": "EPSG:4326",
                "BBOX": (
                    f"{LON-half},{LAT-half},"
                    f"{LON+half},{LAT+half}"
                ),
                "WIDTH": "101",
                "HEIGHT": "101",
                "X": "50",
                "Y": "50",
                "FORMAT": "image/png",
                "INFO_FORMAT": info_format,
                "FEATURE_COUNT": "10",
            }

            try:
                response = await client.get(
                    WMS_URL,
                    params=params,
                )

                print()
                print(label)
                print("-" * 78)
                print("HTTP:", response.status_code)
                print(
                    "Content-Type:",
                    response.headers.get("content-type"),
                )

                raw = response.text.strip()

                if not raw:
                    print("Body: <EMPTY>")
                else:
                    print("Body preview:")
                    print(raw[:1200])

            except Exception as exc:
                print()
                print(label)
                print("-" * 78)
                print("ERROR:", exc)


if __name__ == "__main__":
    asyncio.run(main())
