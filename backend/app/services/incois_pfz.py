"""
TARANG - INCOIS PFZ Connector
==============================

First real-data connector for TARANG.

This module connects to the official INCOIS Potential Fishing Zone (PFZ)
advisory page and retrieves the current advisory metadata.

IMPORTANT:
- This file does NOT invent PFZ coordinates.
- If the public landing page does not expose machine-readable PFZ coordinates,
  TARANG reports that explicitly.
- A later connector step will attach to a verified official sector/WebGIS
  machine endpoint for the actual PFZ geometry/coordinates.

Official source:
https://www.incois.gov.in/MarineFisheries/TextDataHome?mfid=1&request_locale=en
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

from app.services.source_registry import get_source


PFZ_SOURCE_KEY = "incois_pfz_text"

PFZ_URL = (
    "https://www.incois.gov.in/"
    "MarineFisheries/TextDataHome"
    "?mfid=1&request_locale=en"
)

DEFAULT_TIMEOUT_SECONDS = 20.0


class IncoisPFZError(RuntimeError):
    """Raised when the INCOIS PFZ service cannot be read safely."""


class _VisibleTextParser(HTMLParser):
    """
    Minimal HTML-to-visible-text parser using only Python stdlib.

    This avoids adding BeautifulSoup as a dependency just for the first
    INCOIS connector.
    """

    def __init__(self) -> None:
        super().__init__()
        self._ignore_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignore_depth == 0:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)

    def text(self) -> str:
        return " ".join(self.parts)


@dataclass(frozen=True)
class PFZAdvisoryMetadata:
    """
    Provenance-aware metadata for the current INCOIS PFZ advisory page.
    """

    source_key: str
    source_name: str
    organisation: str
    source_url: str
    official: bool

    forecast_date: str | None
    valid_upto: str | None

    retrieved_at_utc: str

    http_status: int
    status: str

    advisory_available: bool

    # The landing page proves a current advisory exists, but we do not
    # pretend it exposes coordinates until a verified endpoint is wired.
    coordinates_available_from_this_endpoint: bool

    note: str


DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\s+"
    r"(JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|"
    r"MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|"
    r"OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
    r"\s+(\d{4})\b",
    flags=re.IGNORECASE,
)


def _visible_text(raw_html: str) -> str:
    parser = _VisibleTextParser()

    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:
        # Even if HTML is malformed, preserve best-effort text.
        pass

    return html.unescape(parser.text())


def _normalise_date(match: re.Match[str] | None) -> str | None:
    if not match:
        return None

    day = int(match.group(1))
    month = match.group(2).upper()
    year = int(match.group(3))

    month_aliases = {
        "JAN": "JAN", "JANUARY": "JAN",
        "FEB": "FEB", "FEBRUARY": "FEB",
        "MAR": "MAR", "MARCH": "MAR",
        "APR": "APR", "APRIL": "APR",
        "MAY": "MAY",
        "JUN": "JUN", "JUNE": "JUN",
        "JUL": "JUL", "JULY": "JUL",
        "AUG": "AUG", "AUGUST": "AUG",
        "SEP": "SEP", "SEPTEMBER": "SEP",
        "OCT": "OCT", "OCTOBER": "OCT",
        "NOV": "NOV", "NOVEMBER": "NOV",
        "DEC": "DEC", "DECEMBER": "DEC",
    }

    return f"{day:02d} {month_aliases[month]} {year:04d}"


def _find_date_after_label(
    text: str,
    labels: tuple[str, ...],
) -> str | None:
    """
    Find a date occurring shortly after one of the expected labels.
    """

    lower = text.lower()

    for label in labels:
        pos = lower.find(label.lower())

        if pos == -1:
            continue

        # Search only a limited window after the label so we don't
        # accidentally pick some unrelated date from the page footer.
        fragment = text[pos : pos + 180]
        match = DATE_PATTERN.search(fragment)

        if match:
            return _normalise_date(match)

    return None


def parse_pfz_metadata_html(
    raw_html: str,
    *,
    http_status: int = 200,
) -> PFZAdvisoryMetadata:
    """
    Parse advisory dates from the official INCOIS PFZ page.

    This function is deliberately separate from networking so it is
    easy to unit-test with saved HTML.
    """

    source = get_source(PFZ_SOURCE_KEY)

    text = _visible_text(raw_html)

    forecast_date = _find_date_after_label(
        text,
        (
            "Forecast Date",
            "Forecast date",
        ),
    )

    valid_upto = _find_date_after_label(
        text,
        (
            "Valid upto",
            "Valid up to",
            "Valid Until",
            "Valid until",
        ),
    )

    advisory_available = bool(
        forecast_date
        or valid_upto
        or "Potential Fishing Zone" in text
    )

    if forecast_date and valid_upto:
        status = "LIVE"
        note = (
            "Current INCOIS PFZ advisory metadata was read from the "
            "official public advisory page. PFZ coordinates are not "
            "yet consumed from this landing-page connector."
        )
    elif advisory_available:
        status = "PARTIAL"
        note = (
            "The official INCOIS PFZ page was reachable, but the "
            "forecast/validity dates could not both be parsed. "
            "No PFZ coordinate is invented."
        )
    else:
        status = "UNAVAILABLE"
        note = (
            "The page responded, but no recognisable PFZ advisory "
            "content was found."
        )

    return PFZAdvisoryMetadata(
        source_key=source.key,
        source_name=source.name,
        organisation=source.organisation,
        source_url=PFZ_URL,
        official=source.official,
        forecast_date=forecast_date,
        valid_upto=valid_upto,
        retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
        http_status=http_status,
        status=status,
        advisory_available=advisory_available,
        coordinates_available_from_this_endpoint=False,
        note=note,
    )


async def fetch_pfz_metadata(
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    client: httpx.AsyncClient | None = None,
) -> PFZAdvisoryMetadata:
    """
    Fetch the current official INCOIS PFZ advisory metadata.

    If INCOIS is unreachable, raise IncoisPFZError.
    """

    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    owns_client = client is None

    if client is None:
        client = httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers=headers,
        )

    try:
        response = await client.get(PFZ_URL)

        response.raise_for_status()

        return parse_pfz_metadata_html(
            response.text,
            http_status=response.status_code,
        )

    except httpx.TimeoutException as exc:
        raise IncoisPFZError(
            "INCOIS PFZ request timed out."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise IncoisPFZError(
            "INCOIS PFZ returned HTTP "
            f"{exc.response.status_code}."
        ) from exc

    except httpx.HTTPError as exc:
        raise IncoisPFZError(
            f"Unable to reach INCOIS PFZ service: {exc}"
        ) from exc

    finally:
        if owns_client:
            await client.aclose()


async def healthcheck() -> dict[str, Any]:
    """
    Small health-check helper for terminal/debugging use.
    """

    try:
        metadata = await fetch_pfz_metadata()

        return {
            "ok": metadata.status in {"LIVE", "PARTIAL"},
            "service": "INCOIS PFZ",
            "status": metadata.status,
            "forecast_date": metadata.forecast_date,
            "valid_upto": metadata.valid_upto,
            "source": metadata.source_name,
            "source_url": metadata.source_url,
            "official": metadata.official,
            "coordinates_ready": (
                metadata.coordinates_available_from_this_endpoint
            ),
            "note": metadata.note,
        }

    except IncoisPFZError as exc:
        return {
            "ok": False,
            "service": "INCOIS PFZ",
            "status": "UNAVAILABLE",
            "error": str(exc),
            "source_url": PFZ_URL,
        }


async def _main() -> None:
    result = await healthcheck()
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
