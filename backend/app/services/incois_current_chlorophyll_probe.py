"""
TARANG - Current INCOIS Chlorophyll Endpoint Probe
==================================================

Why this probe exists:
- The older INCOIS ERDDAP chlorophyll datasets are historical archives.
- TARANG needs a current/operational chlorophyll source.
- The INCOIS Ocean State Forecast (OSF) page currently exposes a
  Chlorophyll layer, so this probe inspects the official page and its
  JavaScript for the machine-readable endpoint actually used by the map.

This probe does NOT invent chlorophyll values and does NOT bypass TLS
certificate verification.

Run:
    python -m app.services.incois_current_chlorophyll_probe

Output:
    incois_current_chlorophyll_probe_report.json
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


START_URLS = [
    "https://www.incois.gov.in/oceanservices/osfforecast.jsp",
    "https://incois.gov.in/oceanservices/osfforecast.jsp",
]

KNOWN_CANDIDATES = [
    "https://incois.gov.in/geoportal/pfzjsondata/OSF_Json/",
]

TIMEOUT_SECONDS = 30.0

URL_RE = re.compile(
    r"""https?://[^\s"'<>\\)]+""",
    re.IGNORECASE,
)

SCRIPT_RE = re.compile(
    r"""<script[^>]+src=["']([^"']+)["']""",
    re.IGNORECASE,
)

KEYWORDS = [
    "chlorophyll",
    "chl",
    "wms",
    "thredds",
    "geoserver",
    "osf_json",
    ".nc",
    ".json",
    "getmap",
    "layers",
]


def _interesting_snippets(
    text: str,
    *,
    radius: int = 220,
    max_snippets: int = 80,
) -> list[dict[str, str]]:
    lower = text.lower()
    snippets: list[dict[str, str]] = []
    seen: set[str] = set()

    for keyword in KEYWORDS:
        start = 0

        while True:
            index = lower.find(keyword.lower(), start)

            if index == -1:
                break

            left = max(0, index - radius)
            right = min(
                len(text),
                index + len(keyword) + radius,
            )

            snippet = text[left:right].replace(
                "\r",
                " ",
            ).replace(
                "\n",
                " ",
            )

            compact = " ".join(
                snippet.split()
            )

            fingerprint = compact[:250]

            if fingerprint not in seen:
                seen.add(fingerprint)
                snippets.append(
                    {
                        "keyword": keyword,
                        "snippet": compact,
                    }
                )

            if len(snippets) >= max_snippets:
                return snippets

            start = index + len(keyword)

    return snippets


def _urls_from_text(
    text: str,
) -> list[str]:
    urls = []

    for match in URL_RE.findall(text):
        cleaned = match.rstrip(
            ".,;]}"
        )

        if cleaned not in urls:
            urls.append(cleaned)

    return urls


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, Any]:
    try:
        response = await client.get(url)

        result = {
            "url": str(response.url),
            "status_code": response.status_code,
            "content_type": response.headers.get(
                "content-type",
                "",
            ),
            "text": response.text,
            "error": None,
        }

        return result

    except Exception as exc:
        return {
            "url": url,
            "status_code": None,
            "content_type": None,
            "text": "",
            "error": str(exc),
        }


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "*/*",
    }

    report: dict[str, Any] = {
        "page_tests": [],
        "script_tests": [],
        "known_candidate_tests": [],
        "discovered_urls": [],
        "interesting_snippets": [],
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:

        # ------------------------------------------------------------
        # 1. Fetch the official OSF page
        # ------------------------------------------------------------
        selected_page = None

        print()
        print("STEP 1 — INCOIS OSF PAGE")
        print("=" * 80)

        for url in START_URLS:
            result = await _fetch(
                client,
                url,
            )

            printable = {
                key: value
                for key, value in result.items()
                if key != "text"
            }

            report["page_tests"].append(
                printable
            )

            print(
                f"{url} -> "
                f"{result['status_code'] if result['status_code'] is not None else result['error']}"
            )

            if (
                result["status_code"] == 200
                and "chlorophyll"
                in result["text"].lower()
            ):
                selected_page = result
                print(
                    "  ✓ Chlorophyll layer text found"
                )
                break

        if selected_page is None:
            print()
            print(
                "Could not read a usable OSF page. "
                "No machine endpoint will be guessed."
            )
        else:
            page_url = selected_page["url"]
            html = selected_page["text"]

            page_snippets = _interesting_snippets(
                html,
            )

            for item in page_snippets:
                report[
                    "interesting_snippets"
                ].append(
                    {
                        "source": page_url,
                        **item,
                    }
                )

            # --------------------------------------------------------
            # 2. Discover and inspect JavaScript files
            # --------------------------------------------------------
            print()
            print("STEP 2 — LINKED JAVASCRIPT")
            print("=" * 80)

            script_urls: list[str] = []

            for src in SCRIPT_RE.findall(
                html
            ):
                script_url = urljoin(
                    page_url,
                    src,
                )

                host = urlparse(
                    script_url
                ).hostname or ""

                if "incois.gov.in" not in host:
                    continue

                if script_url not in script_urls:
                    script_urls.append(
                        script_url
                    )

            print(
                f"Found {len(script_urls)} INCOIS-hosted script(s)."
            )

            for script_url in script_urls:
                result = await _fetch(
                    client,
                    script_url,
                )

                text = result["text"]

                printable = {
                    "url": result["url"],
                    "status_code": (
                        result["status_code"]
                    ),
                    "content_type": (
                        result["content_type"]
                    ),
                    "error": result["error"],
                }

                report[
                    "script_tests"
                ].append(printable)

                print(
                    f"{script_url} -> "
                    f"{result['status_code'] if result['status_code'] is not None else result['error']}"
                )

                if result["status_code"] != 200:
                    continue

                for found_url in _urls_from_text(
                    text
                ):
                    if (
                        "incois.gov.in"
                        in found_url
                        and found_url
                        not in report[
                            "discovered_urls"
                        ]
                    ):
                        report[
                            "discovered_urls"
                        ].append(
                            found_url
                        )

                snippets = _interesting_snippets(
                    text,
                )

                for item in snippets:
                    report[
                        "interesting_snippets"
                    ].append(
                        {
                            "source": script_url,
                            **item,
                        }
                    )

        # ------------------------------------------------------------
        # 3. Probe the known OSF JSON directory clue
        # ------------------------------------------------------------
        print()
        print("STEP 3 — KNOWN OSF MACHINE-DATA CLUES")
        print("=" * 80)

        for url in KNOWN_CANDIDATES:
            result = await _fetch(
                client,
                url,
            )

            preview = " ".join(
                result["text"][:1000].split()
            )

            entry = {
                "url": result["url"],
                "status_code": (
                    result["status_code"]
                ),
                "content_type": (
                    result["content_type"]
                ),
                "preview": preview,
                "error": result["error"],
            }

            report[
                "known_candidate_tests"
            ].append(entry)

            print(
                f"{url} -> "
                f"{result['status_code'] if result['status_code'] is not None else result['error']}"
            )

    # ------------------------------------------------------------
    # 4. Print the useful discoveries
    # ------------------------------------------------------------
    print()
    print("DISCOVERED INCOIS URLS")
    print("=" * 80)

    if report["discovered_urls"]:
        for url in report[
            "discovered_urls"
        ]:
            print(url)
    else:
        print(
            "No absolute machine-data URL was discovered directly."
        )

    print()
    print("CHLOROPHYLL / WMS / THREDDS / JSON SNIPPETS")
    print("=" * 80)

    for index, item in enumerate(
        report["interesting_snippets"][:50],
        start=1,
    ):
        print()
        print(
            f"[{index}] Source: {item['source']}"
        )
        print(
            f"Keyword: {item['keyword']}"
        )
        print(
            item["snippet"]
        )

    output_path = (
        Path.cwd()
        / "incois_current_chlorophyll_probe_report.json"
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
    print("=" * 80)
    print("Saved report:")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
