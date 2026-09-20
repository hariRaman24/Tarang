"""
TARANG - INCOIS Landing Centre Endpoint Probe v2
================================================

The original landing-centre WFS request returned HTTP 503.
This diagnostic tool does NOT assume the layer is gone.

It tries several official GeoServer access patterns and WFS versions,
logs exactly what each endpoint returns, and only downloads features
when a machine endpoint is actually available.

Run:

    python -m app.services.incois_landing_centres_probe_v2

It saves:

    incois_landing_centres_probe_v2_report.json
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx


LAYER = "PFZ_LandingCentres:LandingCenters_29Apr2024"

BASE_ENDPOINTS = [
    "https://incois.gov.in/geoserver/PFZ_LandingCentres/ows",
    "https://incois.gov.in/geoserver/PFZ_LandingCentres/wfs",
    "https://incois.gov.in/geoserver/wfs",
]

VERSIONS = ["1.1.0", "2.0.0"]

TIMEOUT_SECONDS = 30.0


async def request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str],
    attempts: int = 3,
) -> dict[str, Any]:
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(
                url,
                params=params,
            )

            content_type = response.headers.get(
                "content-type",
                "",
            )

            body_preview = response.text[:500]

            result: dict[str, Any] = {
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": content_type,
                "body_preview": body_preview,
                "attempt": attempt,
            }

            if response.status_code == 200:
                return {
                    **result,
                    "ok": True,
                    "response": response,
                }

            last_error = (
                f"HTTP {response.status_code}"
            )

        except httpx.TimeoutException:
            last_error = "timeout"

        except httpx.HTTPError as exc:
            last_error = str(exc)

        if attempt < attempts:
            await asyncio.sleep(
                1.5 * attempt
            )

    return {
        "ok": False,
        "url": url,
        "status_code": None,
        "content_type": None,
        "body_preview": None,
        "attempt": attempts,
        "error": last_error,
    }


async def probe() -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "*/*",
    }

    report: dict[str, Any] = {
        "layer": LAYER,
        "capabilities_tests": [],
        "feature_tests": [],
        "working_endpoint": None,
        "feature_collection": None,
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:

        # ------------------------------------------------------------
        # 1. Probe GetCapabilities
        # ------------------------------------------------------------
        print()
        print("STEP 1 — WFS GetCapabilities")
        print("=" * 76)

        working_candidates: list[
            tuple[str, str]
        ] = []

        for endpoint in BASE_ENDPOINTS:
            for version in VERSIONS:
                params = {
                    "service": "WFS",
                    "version": version,
                    "request": "GetCapabilities",
                }

                result = await request_with_retry(
                    client,
                    endpoint,
                    params=params,
                )

                printable = {
                    key: value
                    for key, value in result.items()
                    if key != "response"
                }

                report[
                    "capabilities_tests"
                ].append(printable)

                status = result.get(
                    "status_code"
                )

                print(
                    f"{endpoint} | WFS {version} "
                    f"-> {status if status is not None else result.get('error')}"
                )

                if result.get("ok"):
                    text = (
                        result["response"].text
                    )

                    if (
                        "WFS_Capabilities" in text
                        or "WFS_Capability" in text
                    ):
                        working_candidates.append(
                            (endpoint, version)
                        )
                        print(
                            "  ✓ WFS capabilities detected"
                        )
                    else:
                        print(
                            "  HTTP 200, but not recognised "
                            "as WFS capabilities"
                        )

        # ------------------------------------------------------------
        # 2. Try GetFeature against working capabilities first,
        #    otherwise try every official endpoint/version combination.
        # ------------------------------------------------------------
        print()
        print("STEP 2 — Landing-centre GetFeature")
        print("=" * 76)

        candidates = (
            working_candidates
            if working_candidates
            else [
                (endpoint, version)
                for endpoint in BASE_ENDPOINTS
                for version in VERSIONS
            ]
        )

        seen: set[
            tuple[str, str]
        ] = set()

        for endpoint, version in candidates:
            key = (
                endpoint,
                version,
            )

            if key in seen:
                continue

            seen.add(key)

            params = {
                "service": "WFS",
                "version": version,
                "request": "GetFeature",
                "typeName": LAYER,
                "outputFormat": "application/json",
            }

            # WFS 2 uses typeNames in the standard, but GeoServer
            # often still accepts typeName. Try both if needed.
            parameter_variants = [
                params,
            ]

            if version == "2.0.0":
                params_v2 = dict(params)
                params_v2.pop(
                    "typeName",
                    None,
                )
                params_v2["typeNames"] = LAYER
                parameter_variants.append(
                    params_v2
                )

            for query_params in parameter_variants:
                result = await request_with_retry(
                    client,
                    endpoint,
                    params=query_params,
                )

                printable = {
                    key: value
                    for key, value in result.items()
                    if key != "response"
                }

                printable[
                    "params"
                ] = query_params

                report[
                    "feature_tests"
                ].append(printable)

                status = result.get(
                    "status_code"
                )

                type_param = (
                    query_params.get("typeName")
                    or query_params.get("typeNames")
                )

                print(
                    f"{endpoint} | WFS {version} | "
                    f"{type_param} -> "
                    f"{status if status is not None else result.get('error')}"
                )

                if not result.get("ok"):
                    continue

                response = result[
                    "response"
                ]

                try:
                    payload = response.json()
                except ValueError:
                    print(
                        "  HTTP 200, but response is not JSON"
                    )
                    continue

                if (
                    isinstance(payload, dict)
                    and payload.get("type")
                    == "FeatureCollection"
                    and isinstance(
                        payload.get("features"),
                        list,
                    )
                ):
                    features = payload[
                        "features"
                    ]

                    print(
                        f"  ✓ WORKING — {len(features)} "
                        "landing-centre features"
                    )

                    report[
                        "working_endpoint"
                    ] = {
                        "url": endpoint,
                        "version": version,
                        "params": query_params,
                        "feature_count": len(
                            features
                        ),
                    }

                    # Save only compact inspection info, not necessarily
                    # the entire server payload.
                    property_keys: set[
                        str
                    ] = set()

                    samples = []

                    for feature in features:
                        props = (
                            feature.get(
                                "properties"
                            )
                            or {}
                        )

                        if isinstance(
                            props,
                            dict,
                        ):
                            property_keys.update(
                                props.keys()
                            )

                        if len(samples) < 10:
                            samples.append(
                                feature
                            )

                    report[
                        "feature_collection"
                    ] = {
                        "feature_count": len(
                            features
                        ),
                        "crs": payload.get(
                            "crs"
                        ),
                        "property_keys": sorted(
                            property_keys
                        ),
                        "sample_features": samples,
                    }

                    return report

    return report


async def main() -> None:
    report = await probe()

    print()
    print("RESULT")
    print("=" * 76)

    working = report.get(
        "working_endpoint"
    )

    if working:
        print(
            "Landing-centre machine endpoint FOUND."
        )
        print(
            json.dumps(
                working,
                indent=2,
                ensure_ascii=False,
            )
        )

        collection = report.get(
            "feature_collection"
        ) or {}

        print()
        print("PROPERTY KEYS")
        print("-" * 76)

        for key in collection.get(
            "property_keys",
            [],
        ):
            print(key)

        print()
        print("FIRST SAMPLE FEATURES")
        print("-" * 76)

        for feature in collection.get(
            "sample_features",
            [],
        )[:3]:
            print(
                json.dumps(
                    feature,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

    else:
        print(
            "No tested landing-centre WFS endpoint is "
            "currently returning usable GeoJSON."
        )
        print()
        print(
            "This does NOT affect the working live PFZ geometry "
            "connector. TARANG should keep PFZ numbers/state names "
            "and treat landing-centre enrichment as temporarily "
            "UNAVAILABLE rather than inventing names."
        )

    output_path = (
        Path.cwd()
        / "incois_landing_centres_probe_v2_report.json"
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
    print("Saved report:")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
