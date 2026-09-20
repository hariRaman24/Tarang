"""
TARANG - Focused INCOIS Chlorophyll WMS Probe
=============================================

The broad OSF probe confirmed that the current INCOIS OSF page contains a
Chlorophyll layer, but it did not print the exact chlorophyll WMS definition.

This focused probe searches the OSF HTML + linked INCOIS JavaScript for:
    tdWmsLayerchl
    chlorophyll
    legendchl
    chlft
    chlparam
    boxchl
    CHL

It also extracts nearby:
    WMS URLs
    layer names
    THREDDS/NetCDF references
    GetFeatureInfo clues

Run:
    python -m app.services.incois_chlorophyll_wms_probe

Output:
    incois_chlorophyll_wms_probe_report.json
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


PAGE_URL = "https://www.incois.gov.in/oceanservices/osfforecast.jsp"
TIMEOUT_SECONDS = 30.0

SCRIPT_RE = re.compile(
    r"""<script[^>]+src=["']([^"']+)["']""",
    re.IGNORECASE,
)

TARGET_PATTERNS = [
    "tdWmsLayerchl",
    "chlorophyll",
    "legendchl",
    "chlft",
    "chlparam",
    "boxchl",
]

# Look for the common Leaflet WMS constructor pattern.
WMS_CONSTRUCTOR_RE = re.compile(
    r"""(?P<var>(?:var|let|const)\s+[A-Za-z0-9_$]+\s*=\s*)?
        (?P<ctor>L\.(?:tileLayer|nonTiledLayer)\.wms)
        \(\s*
        ["'](?P<url>[^"']+)["']
        \s*,\s*
        \{(?P<options>.*?)\}
        \s*\)""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

LAYER_OPTION_RE = re.compile(
    r"""layers\s*:\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

ABS_URL_RE = re.compile(
    r"""https?://[^\s"'<>\\)]+""",
    re.IGNORECASE,
)

THREDDS_RE = re.compile(
    r"""[^\s"'<>]*thredds[^\s"'<>]*""",
    re.IGNORECASE,
)

NC_RE = re.compile(
    r"""[^\s"'<>]+\.nc(?:\?[^\s"'<>]*)?""",
    re.IGNORECASE,
)


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, Any]:
    try:
        response = await client.get(url)

        return {
            "url": str(response.url),
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "text": response.text,
            "error": None,
        }

    except Exception as exc:
        return {
            "url": url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "error": str(exc),
        }


def compact(text: str) -> str:
    return " ".join(
        text.replace("\r", " ").replace("\n", " ").split()
    )


def target_windows(
    text: str,
    *,
    source: str,
    radius: int = 1800,
) -> list[dict[str, Any]]:
    lower = text.lower()
    windows: list[dict[str, Any]] = []
    fingerprints: set[str] = set()

    for target in TARGET_PATTERNS:
        start = 0
        target_lower = target.lower()

        while True:
            index = lower.find(target_lower, start)

            if index == -1:
                break

            left = max(0, index - radius)
            right = min(
                len(text),
                index + len(target) + radius,
            )

            raw = text[left:right]
            clean = compact(raw)
            fingerprint = clean[:500]

            if fingerprint not in fingerprints:
                fingerprints.add(fingerprint)

                urls = list(
                    dict.fromkeys(
                        ABS_URL_RE.findall(raw)
                    )
                )

                thredds = list(
                    dict.fromkeys(
                        THREDDS_RE.findall(raw)
                    )
                )

                netcdf = list(
                    dict.fromkeys(
                        NC_RE.findall(raw)
                    )
                )

                windows.append(
                    {
                        "source": source,
                        "target": target,
                        "snippet": clean,
                        "absolute_urls": urls,
                        "thredds_refs": thredds,
                        "netcdf_refs": netcdf,
                    }
                )

            start = index + len(target)

    return windows


def extract_wms_definitions(
    text: str,
    *,
    source: str,
) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []

    for match in WMS_CONSTRUCTOR_RE.finditer(text):
        full = match.group(0)
        variable_prefix = match.group("var") or ""
        url = match.group("url")
        options = match.group("options")

        layer_match = LAYER_OPTION_RE.search(options)
        layer = (
            layer_match.group(1)
            if layer_match
            else None
        )

        # Keep anything whose variable/options/URL mentions chl/chlorophyll.
        searchable = (
            variable_prefix
            + " "
            + url
            + " "
            + options
        ).lower()

        if (
            "chl" not in searchable
            and "chlorophyll" not in searchable
        ):
            continue

        definitions.append(
            {
                "source": source,
                "definition": compact(full),
                "url": url,
                "layer": layer,
            }
        )

    return definitions


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "*/*",
    }

    report: dict[str, Any] = {
        "page_url": PAGE_URL,
        "sources_checked": [],
        "target_windows": [],
        "chlorophyll_wms_definitions": [],
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:

        page = await fetch_text(
            client,
            PAGE_URL,
        )

        print()
        print("STEP 1 — OSF PAGE")
        print("=" * 88)
        print(
            f"{PAGE_URL} -> "
            f"{page['status_code'] if page['status_code'] is not None else page['error']}"
        )

        if page["status_code"] != 200:
            print("OSF page unavailable; stopping.")
            return

        sources: list[tuple[str, str]] = [
            (page["url"], page["text"])
        ]

        # Discover linked INCOIS JavaScript files.
        script_urls: list[str] = []

        for src in SCRIPT_RE.findall(
            page["text"]
        ):
            script_url = urljoin(
                page["url"],
                src,
            )

            host = (
                urlparse(script_url).hostname
                or ""
            )

            if (
                "incois.gov.in" in host
                and script_url
                not in script_urls
            ):
                script_urls.append(
                    script_url
                )

        print()
        print("STEP 2 — FETCH LINKED INCOIS JAVASCRIPT")
        print("=" * 88)

        for script_url in script_urls:
            result = await fetch_text(
                client,
                script_url,
            )

            report["sources_checked"].append(
                {
                    "url": result["url"],
                    "status_code": result["status_code"],
                    "error": result["error"],
                }
            )

            # Only print scripts that actually contain a chlorophyll clue.
            text_lower = result["text"].lower()

            if (
                result["status_code"] == 200
                and (
                    "chlorophyll" in text_lower
                    or "tdwmslayerchl" in text_lower
                    or "legendchl" in text_lower
                    or "chlft" in text_lower
                )
            ):
                print(
                    f"MATCH: {script_url}"
                )
                sources.append(
                    (
                        result["url"],
                        result["text"],
                    )
                )

        print()
        print("STEP 3 — EXACT CHLOROPHYLL MATCHES")
        print("=" * 88)

        for source_url, text in sources:
            windows = target_windows(
                text,
                source=source_url,
            )

            definitions = extract_wms_definitions(
                text,
                source=source_url,
            )

            report["target_windows"].extend(
                windows
            )

            report[
                "chlorophyll_wms_definitions"
            ].extend(definitions)

        if report["chlorophyll_wms_definitions"]:
            print()
            print("EXACT/LIKELY CHLOROPHYLL WMS DEFINITIONS")
            print("-" * 88)

            for index, item in enumerate(
                report[
                    "chlorophyll_wms_definitions"
                ],
                start=1,
            ):
                print()
                print(f"[{index}] Source: {item['source']}")
                print(f"URL:   {item['url']}")
                print(f"Layer: {item['layer']}")
                print(item["definition"])
        else:
            print(
                "No direct WMS constructor containing 'chl' was found."
            )

        print()
        print("TARGETED SNIPPETS")
        print("-" * 88)

        for index, item in enumerate(
            report["target_windows"],
            start=1,
        ):
            print()
            print(
                f"[{index}] Source: {item['source']}"
            )
            print(
                f"Target: {item['target']}"
            )
            print(
                item["snippet"]
            )

            if item["absolute_urls"]:
                print(
                    "URLs:",
                    item["absolute_urls"],
                )

            if item["thredds_refs"]:
                print(
                    "THREDDS:",
                    item["thredds_refs"],
                )

            if item["netcdf_refs"]:
                print(
                    "NetCDF:",
                    item["netcdf_refs"],
                )

    output_path = (
        Path.cwd()
        / "incois_chlorophyll_wms_probe_report.json"
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
    print("=" * 88)
    print("Saved report:")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
