"""
TARANG - IMD Chennai Fishermen Warning Detail Probe
===================================================

Purpose:
The first probe confirmed that the official RMC Chennai fishermen bulletin
is live and contains warning language. This second probe determines exactly
which Tamil Nadu marine sector(s) the current warning applies to.

It prints only short context blocks around:
- FOR TAMIL NADU COAST
- North Tamil Nadu coast
- South Tamil Nadu coast
- Fishermen are advised not to venture
- High wave / swell / ocean-current alert

Run:
    python -m app.services.imd_chennai_warning_detail_probe
"""

from __future__ import annotations

import asyncio
import io
import re

import httpx
from pypdf import PdfReader


PDF_URL = "https://mausam.imd.gov.in/chennai/mcdata/fishermen.pdf"
TIMEOUT_SECONDS = 40.0

TARGET_PATTERNS = [
    "FOR TAMIL NADU COAST",
    "North Tamil Nadu coast",
    "South Tamil Nadu coast",
    "Fishermen are advised not to venture",
    "HIGH WAVE ALERT",
    "SWELL SURGE ALERT",
    "OCEAN CURRENT ALERT",
]


def _extract_lines(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))

    lines: list[str] = []

    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""

        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()

            if line:
                lines.append(f"[P{page_no}] {line}")

    return lines


def _contexts(
    lines: list[str],
    pattern: str,
    before: int = 3,
    after: int = 6,
    max_hits: int = 5,
) -> list[list[str]]:
    target = pattern.lower()
    results: list[list[str]] = []

    for index, line in enumerate(lines):
        if target not in line.lower():
            continue

        start = max(0, index - before)
        end = min(len(lines), index + after + 1)

        results.append(lines[start:end])

        if len(results) >= max_hits:
            break

    return results


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        )
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.get(PDF_URL)
        response.raise_for_status()

    lines = _extract_lines(response.content)

    print()
    print("TARANG — IMD CHENNAI WARNING DETAIL PROBE")
    print("=" * 78)
    print("HTTP:", response.status_code)
    print("Extracted non-empty lines:", len(lines))

    for pattern in TARGET_PATTERNS:
        hits = _contexts(lines, pattern)

        print()
        print(f'PATTERN: "{pattern}"')
        print("-" * 78)

        if not hits:
            print("NO MATCH")
            continue

        for hit_no, block in enumerate(hits, start=1):
            print(f"Context {hit_no}:")
            for line in block:
                print(line)
            print()

    print("=" * 78)
    print(
        "NEXT: send me this terminal output. "
        "We will use it to determine whether the current warning applies "
        "to North Tamil Nadu/Chennai before wiring it into the Risk Agent."
    )


if __name__ == "__main__":
    asyncio.run(main())
