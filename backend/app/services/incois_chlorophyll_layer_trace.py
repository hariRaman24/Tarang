"""
TARANG - INCOIS Chlorophyll Layer Trace
=======================================

Purpose
-------
The earlier probe confirmed that INCOIS has a Chlorophyll UI and that its
BetterWMS plugin parses a chlorophyll GetFeatureInfo response, but the exact
layer URL was not exposed by the simple WMS-constructor regex.

This trace performs a deeper search across:
    - the OSF HTML
    - every linked INCOIS JavaScript file

It looks for:
    - variables/assignments containing "chl"
    - tdWmsLayer* objects
    - timeDimension.layer.wms(...)
    - BetterWMS layers
    - THREDDS / GeoServer / NetCDF / WMS strings
    - GetFeatureInfo dispatch involving chlorophyll

It does NOT disable SSL verification and does NOT invent any data.

Run:
    python -m app.services.incois_chlorophyll_layer_trace

Output:
    incois_chlorophyll_layer_trace_report.json
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
TIMEOUT_SECONDS = 35.0

SCRIPT_RE = re.compile(
    r"""<script[^>]+src=["']([^"']+)["']""",
    re.IGNORECASE,
)

ASSIGNMENT_PATTERNS = [
    re.compile(
        r"""(?:var|let|const)\s+
            (?P<name>[A-Za-z0-9_$]*chl[A-Za-z0-9_$]*)
            \s*=\s*
            (?P<expr>.*?);""",
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    ),
    re.compile(
        r"""(?P<name>[A-Za-z0-9_$]*chl[A-Za-z0-9_$]*)
            \s*=\s*
            (?P<expr>.*?);""",
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    ),
]

INTERESTING_STRING_RE = re.compile(
    r"""["']([^"']*(?:
        chlorophyll|
        chl|
        thredds|
        geoserver|
        \.nc|
        wms|
        osf
    )[^"']*)["']""",
    re.IGNORECASE | re.VERBOSE,
)

ABS_URL_RE = re.compile(
    r"""https?://[^\s"'<>\\)]+""",
    re.IGNORECASE,
)

REL_ENDPOINT_RE = re.compile(
    r"""["'](
        /[^"']*(?:
            thredds|
            geoserver|
            wms|
            osf|
            \.nc
        )[^"']*
    )["']""",
    re.IGNORECASE | re.VERBOSE,
)


async def fetch(
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


def pseudo_lines(text: str) -> list[str]:
    """
    JavaScript is often minified into one physical line. Split common
    statement boundaries to make nearby logic readable.
    """
    prepared = (
        text.replace(";", ";\n")
        .replace("{", "{\n")
        .replace("}", "}\n")
    )

    return prepared.splitlines()


def contexts_for_term(
    text: str,
    term: str,
    *,
    before: int = 12,
    after: int = 20,
    max_hits: int = 25,
) -> list[str]:
    lines = pseudo_lines(text)
    hits: list[str] = []
    term_lower = term.lower()

    for index, line in enumerate(lines):
        if term_lower not in line.lower():
            continue

        left = max(0, index - before)
        right = min(
            len(lines),
            index + after + 1,
        )

        block = "\n".join(
            lines[left:right]
        )

        hits.append(
            compact(block)
        )

        if len(hits) >= max_hits:
            break

    return hits


def extract_chl_assignments(
    text: str,
) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for pattern in ASSIGNMENT_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group("name")
            expr = compact(
                match.group("expr")
            )

            # Prevent enormous accidental regex captures.
            expr = expr[:4000]

            key = (
                name,
                expr,
            )

            if key in seen:
                continue

            seen.add(key)

            found.append(
                {
                    "name": name,
                    "expression": expr,
                }
            )

    return found


def extract_endpoint_strings(
    text: str,
) -> dict[str, list[str]]:
    interesting_strings = []
    absolute_urls = []
    relative_endpoints = []

    for value in INTERESTING_STRING_RE.findall(
        text
    ):
        value = compact(value)

        if value not in interesting_strings:
            interesting_strings.append(
                value
            )

    for value in ABS_URL_RE.findall(
        text
    ):
        cleaned = value.rstrip(
            ".,;]}"
        )

        if cleaned not in absolute_urls:
            absolute_urls.append(
                cleaned
            )

    for value in REL_ENDPOINT_RE.findall(
        text
    ):
        value = compact(value)

        if value not in relative_endpoints:
            relative_endpoints.append(
                value
            )

    return {
        "interesting_strings": interesting_strings,
        "absolute_urls": absolute_urls,
        "relative_endpoints": relative_endpoints,
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
        "page_url": PAGE_URL,
        "sources": [],
        "chlorophyll_assignments": [],
        "chlorophyll_contexts": [],
        "tdwms_contexts": [],
        "timedimension_wms_contexts": [],
        "betterwms_contexts": [],
        "getfeatureinfo_contexts": [],
        "endpoint_strings": [],
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:

        page = await fetch(
            client,
            PAGE_URL,
        )

        print()
        print("STEP 1 — OSF PAGE")
        print("=" * 92)
        print(
            f"{PAGE_URL} -> "
            f"{page['status_code'] if page['status_code'] is not None else page['error']}"
        )

        if page["status_code"] != 200:
            print(
                "OSF page could not be read. Stopping without guessing."
            )
            return

        source_docs: list[
            tuple[str, str]
        ] = [
            (
                page["url"],
                page["text"],
            )
        ]

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
        print("STEP 2 — FETCHING INCOIS JAVASCRIPT")
        print("=" * 92)

        for script_url in script_urls:
            result = await fetch(
                client,
                script_url,
            )

            report["sources"].append(
                {
                    "url": result["url"],
                    "status_code": (
                        result["status_code"]
                    ),
                    "error": result["error"],
                }
            )

            if result["status_code"] == 200:
                source_docs.append(
                    (
                        result["url"],
                        result["text"],
                    )
                )

        print(
            f"Loaded {len(source_docs)} source document(s)."
        )

        print()
        print("STEP 3 — TRACE CHLOROPHYLL LAYER")
        print("=" * 92)

        for source_url, text in source_docs:

            assignments = (
                extract_chl_assignments(
                    text
                )
            )

            for item in assignments:
                record = {
                    "source": source_url,
                    **item,
                }

                report[
                    "chlorophyll_assignments"
                ].append(record)

            for context in contexts_for_term(
                text,
                "chlorophyll",
            ):
                report[
                    "chlorophyll_contexts"
                ].append(
                    {
                        "source": source_url,
                        "context": context,
                    }
                )

            for context in contexts_for_term(
                text,
                "tdWmsLayer",
            ):
                report[
                    "tdwms_contexts"
                ].append(
                    {
                        "source": source_url,
                        "context": context,
                    }
                )

            for context in contexts_for_term(
                text,
                "timeDimension.layer.wms",
            ):
                report[
                    "timedimension_wms_contexts"
                ].append(
                    {
                        "source": source_url,
                        "context": context,
                    }
                )

            for context in contexts_for_term(
                text,
                "BetterWMS",
            ):
                report[
                    "betterwms_contexts"
                ].append(
                    {
                        "source": source_url,
                        "context": context,
                    }
                )

            for context in contexts_for_term(
                text,
                "GetFeatureInfo",
            ):
                if (
                    "chl" in context.lower()
                    or "chlorophyll"
                    in context.lower()
                ):
                    report[
                        "getfeatureinfo_contexts"
                    ].append(
                        {
                            "source": source_url,
                            "context": context,
                        }
                    )

            endpoints = extract_endpoint_strings(
                text
            )

            # Only retain source records with potentially useful endpoint
            # strings to keep the report readable.
            useful_strings = [
                value
                for value in endpoints[
                    "interesting_strings"
                ]
                if (
                    "chl" in value.lower()
                    or "chlorophyll" in value.lower()
                    or "thredds" in value.lower()
                    or ".nc" in value.lower()
                )
            ]

            if useful_strings:
                report[
                    "endpoint_strings"
                ].append(
                    {
                        "source": source_url,
                        "strings": useful_strings[:150],
                        "absolute_urls": endpoints[
                            "absolute_urls"
                        ][:100],
                        "relative_endpoints": endpoints[
                            "relative_endpoints"
                        ][:100],
                    }
                )

    # ------------------------------------------------------------
    # Human-readable output
    # ------------------------------------------------------------

    print()
    print("CHL-CONTAINING ASSIGNMENTS")
    print("=" * 92)

    if not report["chlorophyll_assignments"]:
        print("No explicit chl variable assignment found.")
    else:
        for index, item in enumerate(
            report["chlorophyll_assignments"],
            start=1,
        ):
            print()
            print(
                f"[{index}] {item['source']}"
            )
            print(
                f"{item['name']} = {item['expression']}"
            )

    print()
    print("TIMEDIMENSION / WMS CONTEXTS")
    print("=" * 92)

    combined_contexts = (
        report["tdwms_contexts"]
        + report[
            "timedimension_wms_contexts"
        ]
    )

    for index, item in enumerate(
        combined_contexts[:40],
        start=1,
    ):
        context_lower = (
            item["context"].lower()
        )

        # Print the most relevant contexts first.
        if (
            "chl" in context_lower
            or "chlorophyll" in context_lower
            or "/thredds/" in context_lower
            or ".nc" in context_lower
        ):
            print()
            print(
                f"[{index}] {item['source']}"
            )
            print(
                item["context"]
            )

    print()
    print("CHLOROPHYLL GETFEATUREINFO CONTEXTS")
    print("=" * 92)

    for index, item in enumerate(
        report["getfeatureinfo_contexts"][:30],
        start=1,
    ):
        print()
        print(
            f"[{index}] {item['source']}"
        )
        print(
            item["context"]
        )

    print()
    print("ENDPOINT STRINGS")
    print("=" * 92)

    for entry in report[
        "endpoint_strings"
    ]:
        print()
        print(
            f"Source: {entry['source']}"
        )

        for value in entry[
            "strings"
        ]:
            print(
                "  STRING:",
                value,
            )

        for value in entry[
            "relative_endpoints"
        ]:
            if (
                "chl" in value.lower()
                or "thredds" in value.lower()
                or ".nc" in value.lower()
            ):
                print(
                    "  ENDPOINT:",
                    value,
                )

    output_path = (
        Path.cwd()
        / "incois_chlorophyll_layer_trace_report.json"
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
    print("=" * 92)
    print("Saved report:")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
