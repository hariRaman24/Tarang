"""
TARANG - Official IMD Marine Warning Probe
==========================================

Purpose:
Validate live official IMD marine-warning sources before production integration.

This probe checks:
1. IMD central Marine Forecast page.
2. IMD central Text Bulletins page.
3. RMC Chennai's fixed Fishermen Warning PDF endpoint.

It does NOT yet convert warnings into a TARANG GO/NO-GO verdict.
It only verifies source availability, freshness clues, and warning text.

Install once if needed:
    pip install pypdf

Run:
    python -m app.services.imd_marine_warning_probe
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    from pypdf import PdfReader
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: pypdf\n"
        "Install it with:\n"
        "    pip install pypdf"
    ) from exc


CENTRAL_MARINE_URL = (
    "https://mausam.imd.gov.in/responsive/marine_forecast.php"
)

CENTRAL_TEXT_URL = (
    "https://mausam.imd.gov.in/responsive/text_bulletins.php"
)

CHENNAI_FISHERMEN_PDF = (
    "https://mausam.imd.gov.in/chennai/mcdata/fishermen.pdf"
)

TIMEOUT_SECONDS = 40.0

WARNING_TERMS = [
    "fishermen are advised not to venture",
    "squally wind",
    "squally weather",
    "high wave alert",
    "swell surge alert",
    "ocean current alert",
    "cyclone",
    "rough sea",
    "very rough sea",
    "storm",
]

COAST_TERMS = [
    "north tamil nadu coast",
    "south tamil nadu coast",
    "tamil nadu coast",
    "tamilnadu coast",
    "southwest bay of bengal",
    "west central bay of bengal",
    "westcentral bay of bengal",
    "comorin area",
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_pdf_text(pdf_bytes: bytes) -> tuple[str, int]:
    reader = PdfReader(io.BytesIO(pdf_bytes))

    pages: list[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)

    return "\n".join(pages), len(reader.pages)


def _extract_dates(text: str) -> list[str]:
    patterns = [
        r"\b\d{2}-\d{2}-\d{4}\b",
        r"\b\d{2}\.\d{2}\.\d{4}\b",
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
    ]

    values: list[str] = []

    for pattern in patterns:
        for match in re.findall(pattern, text):
            if match not in values:
                values.append(match)

    return values[:20]


def _extract_issue_times(text: str) -> list[str]:
    patterns = [
        r"\b\d{4}\s*hrs\.?\s*IST\b",
        r"\b\d{4}\s*hours?\s*IST\b",
        r"Time of Issue\s*:\s*[^\n]{0,80}",
    ]

    values: list[str] = []

    for pattern in patterns:
        for match in re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            cleaned = " ".join(match.split())
            if cleaned not in values:
                values.append(cleaned)

    return values[:10]


def _matched_terms(
    text: str,
    terms: list[str],
) -> list[str]:
    lower = text.lower()

    return [
        term
        for term in terms
        if term in lower
    ]


def _clean_preview(
    text: str,
    limit: int = 1400,
) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


async def _fetch_text(
    client: httpx.AsyncClient,
    url: str,
) -> dict[str, Any]:
    response = await client.get(url)

    return {
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": response.headers.get(
            "content-type",
            "",
        ),
        "text": response.text,
    }


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        )
    }

    report: dict[str, Any] = {
        "retrieved_at_utc": _now_utc(),
        "sources": {},
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:

        print()
        print("TARANG — IMD MARINE WARNING PROBE")
        print("=" * 76)

        # ------------------------------------------------------------
        # 1. Central marine page
        # ------------------------------------------------------------
        try:
            central = await _fetch_text(
                client,
                CENTRAL_MARINE_URL,
            )

            lower = central["text"].lower()

            central_result = {
                "url": central["url"],
                "status_code": central["status_code"],
                "content_type": central["content_type"],
                "mentions_fishermen_warnings": (
                    "fishermen warning" in lower
                ),
                "mentions_north_tamil_nadu": (
                    "north tamil nadu coast" in lower
                ),
                "mentions_south_tamil_nadu": (
                    "south tamil nadu coast" in lower
                ),
            }

            report["sources"]["central_marine_page"] = (
                central_result
            )

            print()
            print("1) IMD CENTRAL MARINE PAGE")
            print(f"HTTP: {central_result['status_code']}")
            print(
                "Fishermen warnings section:",
                central_result[
                    "mentions_fishermen_warnings"
                ],
            )
            print(
                "Tamil Nadu coast coverage:",
                (
                    central_result[
                        "mentions_north_tamil_nadu"
                    ]
                    or central_result[
                        "mentions_south_tamil_nadu"
                    ]
                ),
            )

        except Exception as exc:
            report["sources"]["central_marine_page"] = {
                "url": CENTRAL_MARINE_URL,
                "error": str(exc),
            }

            print()
            print("1) IMD CENTRAL MARINE PAGE")
            print("ERROR:", exc)

        # ------------------------------------------------------------
        # 2. Central text bulletins
        # ------------------------------------------------------------
        try:
            bulletin = await _fetch_text(
                client,
                CENTRAL_TEXT_URL,
            )

            lower = bulletin["text"].lower()

            bulletin_result = {
                "url": bulletin["url"],
                "status_code": bulletin["status_code"],
                "content_type": bulletin["content_type"],
                "mentions_fishermen_warnings": (
                    "fishermen warnings" in lower
                ),
                "mentions_bay_of_bengal": (
                    "bay of bengal" in lower
                ),
            }

            report["sources"]["central_text_bulletins"] = (
                bulletin_result
            )

            print()
            print("2) IMD CENTRAL TEXT BULLETINS")
            print(f"HTTP: {bulletin_result['status_code']}")
            print(
                "Fishermen warnings listed:",
                bulletin_result[
                    "mentions_fishermen_warnings"
                ],
            )

        except Exception as exc:
            report["sources"]["central_text_bulletins"] = {
                "url": CENTRAL_TEXT_URL,
                "error": str(exc),
            }

            print()
            print("2) IMD CENTRAL TEXT BULLETINS")
            print("ERROR:", exc)

        # ------------------------------------------------------------
        # 3. Chennai fishermen warning PDF
        # ------------------------------------------------------------
        try:
            response = await client.get(
                CHENNAI_FISHERMEN_PDF
            )

            response.raise_for_status()

            pdf_text, page_count = _extract_pdf_text(
                response.content
            )

            dates = _extract_dates(pdf_text)
            issue_times = _extract_issue_times(
                pdf_text
            )

            warning_matches = _matched_terms(
                pdf_text,
                WARNING_TERMS,
            )

            coast_matches = _matched_terms(
                pdf_text,
                COAST_TERMS,
            )

            pdf_result = {
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": response.headers.get(
                    "content-type",
                    "",
                ),
                "content_length_bytes": len(
                    response.content
                ),
                "page_count": page_count,
                "dates_found": dates,
                "issue_times_found": issue_times,
                "warning_terms_found": warning_matches,
                "coast_terms_found": coast_matches,
                "contains_do_not_venture_advice": (
                    "fishermen are advised not to venture"
                    in pdf_text.lower()
                ),
                "text_preview": _clean_preview(
                    pdf_text
                ),
            }

            report["sources"][
                "rmc_chennai_fishermen_warning"
            ] = pdf_result

            print()
            print("3) RMC CHENNAI FISHERMEN WARNING PDF")
            print(f"HTTP: {pdf_result['status_code']}")
            print(f"Pages: {page_count}")
            print("Dates found:", dates[:5])
            print(
                "Issue times:",
                issue_times[:3],
            )
            print(
                "Warning terms:",
                warning_matches,
            )
            print(
                "Tamil Nadu/Bay sectors:",
                coast_matches,
            )
            print(
                '"Do not venture" advice present:',
                pdf_result[
                    "contains_do_not_venture_advice"
                ],
            )

        except Exception as exc:
            report["sources"][
                "rmc_chennai_fishermen_warning"
            ] = {
                "url": CHENNAI_FISHERMEN_PDF,
                "error": str(exc),
            }

            print()
            print("3) RMC CHENNAI FISHERMEN WARNING PDF")
            print("ERROR:", exc)

    output_path = (
        Path.cwd()
        / "imd_marine_warning_probe_report.json"
    )

    output_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 76)
    print("Saved report:")
    print(output_path)
    print()
    print(
        "NEXT: send me only this terminal output. "
        "Do not use the result as a safety verdict yet."
    )


if __name__ == "__main__":
    asyncio.run(main())
