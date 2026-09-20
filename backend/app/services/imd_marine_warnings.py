"""
TARANG - Official IMD Marine / Fishermen Warning Service
========================================================

Production connector for the official RMC Chennai fishermen-warning PDF.

Source:
    https://mausam.imd.gov.in/chennai/mcdata/fishermen.pdf

Safety policy
-------------
This connector distinguishes warning TEXT from warning TIME.

A phrase found anywhere in a multi-day bulletin is NOT automatically treated
as a current warning. TARANG classifies sector evidence as one of:

    ACTIVE_CURRENT_WARNING
    FUTURE_WARNING
    EXPIRED_WARNING
    NO_CURRENT_MATCH
    AMBIGUOUS_VALIDITY
    SOURCE_UNAVAILABLE

Important:
- "warning present somewhere in bulletin" != "warning applies now".
- "warning applies to South Tamil Nadu" != "warning applies to North Tamil Nadu".
- "no current matched warning" != "safe".
- a stale bulletin is never used as proof of current safety.
- simulated cyclone/lightning flags are never substituted.

CLI:
    python -m app.services.imd_marine_warnings --sector north_tamilnadu
    python -m app.services.imd_marine_warnings --sector south_tamilnadu
    python -m app.services.imd_marine_warnings --sector north_tamilnadu --full
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pypdf import PdfReader


PDF_URL = "https://mausam.imd.gov.in/chennai/mcdata/fishermen.pdf"

TIMEOUT_SECONDS = 40.0

TRANSIENT_STATUS_CODES = {
    429,
    502,
    503,
    504,
}

IST = ZoneInfo("Asia/Kolkata")

# Conservative freshness threshold for the bulletin issue timestamp.
# This is NOT the validity of an individual warning. Warning validity is
# evaluated separately from explicit dates/times in the bulletin.
BULLETIN_FRESHNESS_HOURS = 36.0


SECTOR_ALIASES = {
    "north_tamilnadu": [
        "north tamil nadu coast",
        "north tamilnadu coast",
    ],
    "south_tamilnadu": [
        "south tamil nadu coast",
        "south tamilnadu coast",
    ],
    "tamilnadu": [
        "tamil nadu coast",
        "tamilnadu coast",
    ],
}


WARNING_TERMS = [
    "squally wind",
    "squally weather",
    "rough sea",
    "very rough sea",
    "high wave alert",
    "swell surge alert",
    "ocean current alert",
    "fishermen are advised not to venture",
    "cyclone",
    "storm",
]


DO_NOT_VENTURE_PHRASE = (
    "fishermen are advised not to venture"
)


DATE_TOKEN_RE = (
    r"(?:"
    r"\d{1,2}[-./]\d{1,2}[-./]\d{4}"
    r"|"
    r"\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r")"
)

TIME_TOKEN_RE = (
    r"(?:"
    r"\d{1,2}:\d{2}"
    r"|"
    r"\d{3,4}"
    r")"
)


class ImdMarineWarningError(RuntimeError):
    """Raised when the official IMD bulletin cannot be read safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ist(
    now_utc: datetime | None = None,
) -> datetime:
    current = (
        now_utc
        if now_utc is not None
        else datetime.now(timezone.utc)
    )

    if current.tzinfo is None:
        current = current.replace(
            tzinfo=timezone.utc
        )

    return current.astimezone(IST)


def _normalize_text(
    text: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _extract_pdf_text(
    pdf_bytes: bytes,
) -> tuple[str, list[str], int]:
    reader = PdfReader(
        io.BytesIO(pdf_bytes)
    )

    page_texts: list[str] = []
    lines: list[str] = []

    for page_no, page in enumerate(
        reader.pages,
        start=1,
    ):
        text = page.extract_text() or ""

        page_texts.append(text)

        for raw in text.splitlines():
            line = _normalize_text(
                raw
            )

            if line:
                lines.append(
                    f"[P{page_no}] {line}"
                )

    return (
        "\n".join(page_texts),
        lines,
        len(reader.pages),
    )


def _parse_date_token(
    value: str,
) -> date | None:
    cleaned = _normalize_text(
        value
    )

    formats = (
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d %B %Y",
        "%d %b %Y",
    )

    for fmt in formats:
        try:
            return datetime.strptime(
                cleaned,
                fmt,
            ).date()
        except ValueError:
            continue

    return None


def _parse_time_token(
    value: str,
) -> time | None:
    cleaned = (
        value.strip()
        .lower()
        .replace("hrs.", "")
        .replace("hrs", "")
        .replace("hours", "")
        .replace("hour", "")
        .replace("ist", "")
        .strip()
    )

    if re.fullmatch(
        r"\d{1,2}:\d{2}",
        cleaned,
    ):
        try:
            hour_s, minute_s = (
                cleaned.split(":", 1)
            )
            hour = int(hour_s)
            minute = int(minute_s)

            if (
                0 <= hour <= 23
                and 0 <= minute <= 59
            ):
                return time(
                    hour,
                    minute,
                )
        except ValueError:
            return None

    if re.fullmatch(
        r"\d{3,4}",
        cleaned,
    ):
        number = cleaned.zfill(4)

        try:
            hour = int(
                number[:2]
            )
            minute = int(
                number[2:]
            )
        except ValueError:
            return None

        if (
            0 <= hour <= 23
            and 0 <= minute <= 59
        ):
            return time(
                hour,
                minute,
            )

    return None


def _extract_dates(
    text: str,
) -> list[str]:
    patterns = [
        r"\b\d{2}-\d{2}-\d{4}\b",
        r"\b\d{2}\.\d{2}\.\d{4}\b",
        r"\b\d{2}/\d{2}/\d{4}\b",
        r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
    ]

    found: list[str] = []

    for pattern in patterns:
        for value in re.findall(
            pattern,
            text,
        ):
            if value not in found:
                found.append(
                    value
                )

    return found[:30]


def _parsed_dates_in_text(
    text: str,
) -> list[date]:
    parsed: list[date] = []

    for raw in _extract_dates(
        text
    ):
        value = _parse_date_token(
            raw
        )

        if (
            value is not None
            and value not in parsed
        ):
            parsed.append(
                value
            )

    return parsed


def _extract_issue_date(
    text: str,
) -> date | None:
    # Prefer an explicit DATE: label.
    match = re.search(
        rf"\bDATE\s*:\s*({DATE_TOKEN_RE})",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        parsed = _parse_date_token(
            match.group(1)
        )

        if parsed is not None:
            return parsed

    # Conservative fallback: only inspect the beginning of the bulletin.
    early_dates = _parsed_dates_in_text(
        text[:3500]
    )

    if early_dates:
        return early_dates[0]

    return None


def _extract_issue_times(
    text: str,
) -> list[str]:
    """
    Return only numeric issue times.

    This deliberately rejects malformed extraction such as:
        "Time of Issue: FISHERMEN WARNING"
    """

    found: list[str] = []

    patterns = (
        rf"Time\s+of\s+Issue\s*:\s*({TIME_TOKEN_RE})"
        r"\s*(?:hrs?\.?|hours?)?\s*(?:IST)?",
        rf"\b({TIME_TOKEN_RE})\s*(?:hrs?\.?|hours?)\s*IST\b",
    )

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            text,
            flags=re.IGNORECASE,
        ):
            raw_time = match.group(1)

            parsed = _parse_time_token(
                raw_time
            )

            if parsed is None:
                continue

            formatted = (
                f"{parsed.hour:02d}:"
                f"{parsed.minute:02d} IST"
            )

            if formatted not in found:
                found.append(
                    formatted
                )

    return found[:10]


def _extract_issue_time(
    text: str,
) -> time | None:
    times = _extract_issue_times(
        text
    )

    if not times:
        return None

    return _parse_time_token(
        times[0]
    )


def _bulletin_timing(
    text: str,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    evaluated_at = _now_ist(
        now_utc
    )

    issue_date = _extract_issue_date(
        text
    )

    issue_time = _extract_issue_time(
        text
    )

    issue_datetime: datetime | None = None
    age_hours: float | None = None

    if (
        issue_date is not None
        and issue_time is not None
    ):
        issue_datetime = datetime.combine(
            issue_date,
            issue_time,
            tzinfo=IST,
        )

        age_hours = (
            evaluated_at
            - issue_datetime
        ).total_seconds() / 3600.0

        if age_hours < -2.0:
            freshness = "FUTURE_TIMESTAMP"
            current_enough = False

        elif (
            age_hours
            <= BULLETIN_FRESHNESS_HOURS
        ):
            freshness = "CURRENT"
            current_enough = True

        else:
            freshness = "STALE"
            current_enough = False

    elif issue_date is not None:
        day_delta = (
            evaluated_at.date()
            - issue_date
        ).days

        if day_delta == 0:
            freshness = (
                "CURRENT_DATE_TIME_UNKNOWN"
            )
            current_enough = True

        elif day_delta > 0:
            freshness = "STALE"
            current_enough = False

        else:
            freshness = "FUTURE_DATE"
            current_enough = False

    else:
        freshness = "UNKNOWN"
        current_enough = False

    return {
        "evaluated_at_ist": (
            evaluated_at.isoformat()
        ),
        "issue_date": (
            issue_date.isoformat()
            if issue_date
            else None
        ),
        "issue_time_ist": (
            f"{issue_time.hour:02d}:"
            f"{issue_time.minute:02d}"
            if issue_time
            else None
        ),
        "issue_datetime_ist": (
            issue_datetime.isoformat()
            if issue_datetime
            else None
        ),
        "age_hours": (
            round(age_hours, 2)
            if age_hours is not None
            else None
        ),
        "freshness": freshness,
        "current_enough_for_current_section": (
            current_enough
        ),
        "freshness_threshold_hours": (
            BULLETIN_FRESHNESS_HOURS
        ),
    }


def _clean_line_prefix(
    line: str,
) -> str:
    return re.sub(
        r"^\[P\d+\]\s*",
        "",
        line,
    )


def _line_lower(
    line: str,
) -> str:
    return _clean_line_prefix(
        line
    ).lower()


def _context_block(
    lines: list[str],
    index: int,
    *,
    before: int = 5,
    after: int = 10,
) -> list[str]:
    start = max(
        0,
        index - before,
    )

    end = min(
        len(lines),
        index + after + 1,
    )

    return [
        _clean_line_prefix(
            line
        )
        for line in lines[
            start:end
        ]
    ]


def _generic_tn_phrase_match(
    lower_line: str,
    phrase: str,
) -> bool:
    """
    Match generic Tamil Nadu coast without incorrectly matching
    'North Tamil Nadu coast' or 'South Tamil Nadu coast'.
    """

    if phrase not in lower_line:
        return False

    if re.search(
        r"\b(?:north|south)\s+tamil\s*nadu\s+coast\b",
        lower_line,
    ):
        return False

    if re.search(
        r"\b(?:north|south)\s+tamilnadu\s+coast\b",
        lower_line,
    ):
        return False

    return True


def _find_phrase_hits(
    lines: list[str],
    phrases: list[str],
    *,
    generic_tn_only: bool = False,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []

    for index, line in enumerate(
        lines
    ):
        lower = _line_lower(
            line
        )

        matched: list[str] = []

        for phrase in phrases:
            if generic_tn_only:
                if _generic_tn_phrase_match(
                    lower,
                    phrase,
                ):
                    matched.append(
                        phrase
                    )
            elif phrase in lower:
                matched.append(
                    phrase
                )

        if not matched:
            continue

        block = _context_block(
            lines,
            index,
        )

        block_lower = " ".join(
            block
        ).lower()

        warning_terms = [
            term
            for term in WARNING_TERMS
            if term in block_lower
        ]

        hits.append(
            {
                "line_index": index,
                "line": (
                    _clean_line_prefix(
                        line
                    )
                ),
                "matched_phrases": (
                    matched
                ),
                "warning_terms_nearby": (
                    warning_terms
                ),
                "context": block,
            }
        )

    return hits


def _current_tn_coast_section_nil(
    lines: list[str],
) -> bool:
    """
    Detect:
        FOR TAMIL NADU COAST
        NIL

    The caller must separately verify bulletin freshness before treating
    this as a current-section finding.
    """

    for index, line in enumerate(
        lines
    ):
        lower = _line_lower(
            line
        )

        if (
            "for tamil nadu coast"
            not in lower
            and "for tamilnadu coast"
            not in lower
        ):
            continue

        following = [
            _line_lower(
                item
            )
            for item in lines[
                index + 1:
                index + 5
            ]
        ]

        if any(
            item == "nil"
            for item in following
        ):
            return True

    return False


def _bulletin_warning_terms(
    text: str,
) -> list[str]:
    lower = text.lower()

    return [
        term
        for term in WARNING_TERMS
        if term in lower
    ]


def _combine_ist(
    day_value: date,
    time_value: time,
) -> datetime:
    return datetime.combine(
        day_value,
        time_value,
        tzinfo=IST,
    )


def _extract_explicit_validity_windows(
    text: str,
) -> list[dict[str, Any]]:
    """
    Parse common IMD/INCOIS validity expressions from a local context.

    Examples:
      till 23:30 hours on 19-09-2026
      during 22:00 hours on 18-09-2026 to 04:00 hours on 19-09-2026
    """

    windows: list[dict[str, Any]] = []

    # Explicit start -> end interval.
    interval_pattern = re.compile(
        rf"(?:during|from)\s+"
        rf"({TIME_TOKEN_RE})"
        rf"\s*(?:hrs?\.?|hours?)?\s*(?:IST)?\s*"
        rf"(?:on\s+)?"
        rf"({DATE_TOKEN_RE})"
        rf"\s+(?:to|-)\s+"
        rf"({TIME_TOKEN_RE})"
        rf"\s*(?:hrs?\.?|hours?)?\s*(?:IST)?\s*"
        rf"(?:on\s+)?"
        rf"({DATE_TOKEN_RE})",
        flags=re.IGNORECASE,
    )

    for match in interval_pattern.finditer(
        text
    ):
        start_time = _parse_time_token(
            match.group(1)
        )
        start_date = _parse_date_token(
            match.group(2)
        )
        end_time = _parse_time_token(
            match.group(3)
        )
        end_date = _parse_date_token(
            match.group(4)
        )

        if not all(
            (
                start_time,
                start_date,
                end_time,
                end_date,
            )
        ):
            continue

        start_dt = _combine_ist(
            start_date,
            start_time,
        )
        end_dt = _combine_ist(
            end_date,
            end_time,
        )

        windows.append(
            {
                "kind": "EXPLICIT_INTERVAL",
                "start_ist": (
                    start_dt.isoformat()
                ),
                "end_ist": (
                    end_dt.isoformat()
                ),
                "_start": start_dt,
                "_end": end_dt,
            }
        )

    # "till/until HH:MM ... on DATE"
    till_pattern = re.compile(
        rf"(?:till|until)\s+"
        rf"({TIME_TOKEN_RE})"
        rf"\s*(?:hrs?\.?|hours?)?\s*(?:IST)?\s*"
        rf"(?:on\s+)?"
        rf"({DATE_TOKEN_RE})",
        flags=re.IGNORECASE,
    )

    for match in till_pattern.finditer(
        text
    ):
        end_time = _parse_time_token(
            match.group(1)
        )
        end_date = _parse_date_token(
            match.group(2)
        )

        if (
            end_time is None
            or end_date is None
        ):
            continue

        end_dt = _combine_ist(
            end_date,
            end_time,
        )

        windows.append(
            {
                "kind": "VALID_UNTIL",
                "start_ist": None,
                "end_ist": (
                    end_dt.isoformat()
                ),
                "_start": None,
                "_end": end_dt,
            }
        )

    return windows


def _extract_day_dates(
    text: str,
) -> list[date]:
    found: list[date] = []

    pattern = re.compile(
        rf"\bDay\s*\d+\s*\(\s*({DATE_TOKEN_RE})\s*\)",
        flags=re.IGNORECASE,
    )

    for match in pattern.finditer(
        text
    ):
        parsed = _parse_date_token(
            match.group(1)
        )

        if (
            parsed is not None
            and parsed not in found
        ):
            found.append(
                parsed
            )

    return found


def _classify_hit_temporally(
    hit: dict[str, Any],
    *,
    bulletin_timing: dict[str, Any],
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    evaluated_at = _now_ist(
        now_utc
    )

    context_text = " ".join(
        hit.get(
            "context",
            [],
        )
    )

    windows = (
        _extract_explicit_validity_windows(
            context_text
        )
    )

    if windows:
        active = False
        future = True
        expired = True

        serializable_windows: list[
            dict[str, Any]
        ] = []

        for window in windows:
            start_dt = window[
                "_start"
            ]
            end_dt = window[
                "_end"
            ]

            if (
                start_dt is None
                and end_dt is not None
            ):
                issue_dt_raw = (
                    bulletin_timing.get(
                        "issue_datetime_ist"
                    )
                )

                issue_dt = (
                    datetime.fromisoformat(
                        issue_dt_raw
                    )
                    if issue_dt_raw
                    else None
                )

                if (
                    evaluated_at
                    <= end_dt
                    and bulletin_timing.get(
                        "current_enough_for_current_section"
                    )
                ):
                    active = True

                if evaluated_at <= end_dt:
                    expired = False

                # A VALID_UNTIL expression is not considered a future-only
                # warning when the bulletin itself is already issued/current.
                if (
                    issue_dt is None
                    or issue_dt <= evaluated_at
                ):
                    future = False

            elif (
                start_dt is not None
                and end_dt is not None
            ):
                if (
                    start_dt
                    <= evaluated_at
                    <= end_dt
                ):
                    active = True

                if evaluated_at >= start_dt:
                    future = False

                if evaluated_at <= end_dt:
                    expired = False

            serializable_windows.append(
                {
                    key: value
                    for key, value
                    in window.items()
                    if not key.startswith("_")
                }
            )

        if active:
            status = (
                "ACTIVE_CURRENT_WARNING"
            )
            confidence = "HIGH"

        elif future:
            status = "FUTURE_WARNING"
            confidence = "HIGH"

        elif expired:
            status = "EXPIRED_WARNING"
            confidence = "HIGH"

        else:
            status = "AMBIGUOUS_VALIDITY"
            confidence = "MEDIUM"

        return {
            "status": status,
            "confidence": confidence,
            "basis": "EXPLICIT_VALIDITY_WINDOW",
            "validity_windows": (
                serializable_windows
            ),
            "dates_in_context": [
                d.isoformat()
                for d in _parsed_dates_in_text(
                    context_text
                )
            ],
        }

    # Prefer Day N(...) dates because the bulletin issue date may also be
    # present near a warning and must not falsely make a future Day 2 warning
    # look current.
    context_dates = _extract_day_dates(
        context_text
    )

    date_basis = "DAY_HEADER"

    if not context_dates:
        context_dates = (
            _parsed_dates_in_text(
                context_text
            )
        )
        date_basis = "CONTEXT_DATE"

    if context_dates:
        today = evaluated_at.date()
        minimum = min(
            context_dates
        )
        maximum = max(
            context_dates
        )

        if (
            minimum
            <= today
            <= maximum
        ):
            if bulletin_timing.get(
                "freshness"
            ) == "STALE":
                status = (
                    "EXPIRED_WARNING"
                )
                confidence = "MEDIUM"
            else:
                status = (
                    "ACTIVE_CURRENT_WARNING"
                )
                confidence = "MEDIUM"

        elif today < minimum:
            status = "FUTURE_WARNING"
            confidence = "HIGH"

        else:
            status = "EXPIRED_WARNING"
            confidence = "HIGH"

        return {
            "status": status,
            "confidence": confidence,
            "basis": date_basis,
            "validity_windows": [],
            "dates_in_context": [
                d.isoformat()
                for d in context_dates
            ],
        }

    if bulletin_timing.get(
        "freshness"
    ) == "STALE":
        return {
            "status": "EXPIRED_WARNING",
            "confidence": "LOW",
            "basis": "STALE_BULLETIN_NO_LOCAL_TIME",
            "validity_windows": [],
            "dates_in_context": [],
        }

    return {
        "status": "AMBIGUOUS_VALIDITY",
        "confidence": "LOW",
        "basis": "NO_LOCAL_TIME_SCOPE",
        "validity_windows": [],
        "dates_in_context": [],
    }


def _sector_status(
    *,
    sector: str,
    lines: list[str],
    full_text: str,
    bulletin_timing: dict[str, Any],
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    if sector not in SECTOR_ALIASES:
        raise ValueError(
            "sector must be one of: "
            + ", ".join(
                sorted(
                    SECTOR_ALIASES
                )
            )
        )

    exact_hits = _find_phrase_hits(
        lines,
        SECTOR_ALIASES[
            sector
        ],
        generic_tn_only=(
            sector == "tamilnadu"
        ),
    )

    generic_hits = _find_phrase_hits(
        lines,
        SECTOR_ALIASES[
            "tamilnadu"
        ],
        generic_tn_only=True,
    )

    current_tn_nil_raw = (
        _current_tn_coast_section_nil(
            lines
        )
    )

    current_tn_nil = bool(
        current_tn_nil_raw
        and bulletin_timing.get(
            "current_enough_for_current_section"
        )
    )

    do_not_venture_anywhere = (
        DO_NOT_VENTURE_PHRASE
        in full_text.lower()
    )

    exact_warning_hits: list[
        dict[str, Any]
    ] = []

    for hit in exact_hits:
        if not hit.get(
            "warning_terms_nearby"
        ):
            continue

        temporal = (
            _classify_hit_temporally(
                hit,
                bulletin_timing=(
                    bulletin_timing
                ),
                now_utc=now_utc,
            )
        )

        enriched = {
            **hit,
            "temporal": temporal,
        }

        exact_warning_hits.append(
            enriched
        )

    active_hits = [
        hit
        for hit in exact_warning_hits
        if (
            hit.get(
                "temporal",
                {},
            ).get("status")
            == "ACTIVE_CURRENT_WARNING"
        )
    ]

    future_hits = [
        hit
        for hit in exact_warning_hits
        if (
            hit.get(
                "temporal",
                {},
            ).get("status")
            == "FUTURE_WARNING"
        )
    ]

    expired_hits = [
        hit
        for hit in exact_warning_hits
        if (
            hit.get(
                "temporal",
                {},
            ).get("status")
            == "EXPIRED_WARNING"
        )
    ]

    ambiguous_hits = [
        hit
        for hit in exact_warning_hits
        if (
            hit.get(
                "temporal",
                {},
            ).get("status")
            == "AMBIGUOUS_VALIDITY"
        )
    ]

    # ------------------------------------------------------------
    # CURRENT-sector interpretation
    # ------------------------------------------------------------
    if active_hits:
        status = (
            "OFFICIAL_ACTIVE_SECTOR_WARNING"
        )
        temporal_status = (
            "ACTIVE_CURRENT_WARNING"
        )
        sector_warning_match = True
        confidence = "HIGH"

    elif current_tn_nil:
        # Explicit current Tamil Nadu coast section is NIL.
        # Future/expired text may still exist elsewhere in the bulletin.
        status = (
            "OFFICIAL_CURRENT_TN_COAST_SECTION_NIL"
        )
        temporal_status = (
            "NO_CURRENT_MATCH"
        )
        sector_warning_match = False
        confidence = "MEDIUM"

    elif ambiguous_hits:
        status = (
            "OFFICIAL_SECTOR_WARNING_TIME_AMBIGUOUS"
        )
        temporal_status = (
            "AMBIGUOUS_VALIDITY"
        )
        sector_warning_match = None
        confidence = "LOW"

    elif future_hits:
        status = (
            "OFFICIAL_FUTURE_SECTOR_WARNING_ONLY"
        )
        temporal_status = (
            "FUTURE_WARNING"
        )
        sector_warning_match = False
        confidence = "HIGH"

    elif expired_hits:
        if (
            bulletin_timing.get(
                "freshness"
            ) == "STALE"
        ):
            status = (
                "OFFICIAL_BULLETIN_STALE_WITH_EXPIRED_SECTOR_WARNING"
            )
            sector_warning_match = None
            confidence = "LOW"
            temporal_status = (
                "EXPIRED_WARNING"
            )
        else:
            status = (
                "OFFICIAL_EXPIRED_SECTOR_WARNING_ONLY"
            )
            sector_warning_match = False
            confidence = "HIGH"
            temporal_status = (
                "EXPIRED_WARNING"
            )

    elif (
        bulletin_timing.get(
            "freshness"
        )
        == "STALE"
    ):
        status = (
            "OFFICIAL_BULLETIN_STALE_OR_TIME_AMBIGUOUS"
        )
        temporal_status = (
            "AMBIGUOUS_VALIDITY"
        )
        sector_warning_match = None
        confidence = "LOW"

    elif generic_hits:
        status = (
            "OFFICIAL_BULLETIN_AVAILABLE_SCOPE_OR_TIME_AMBIGUOUS"
        )
        temporal_status = (
            "AMBIGUOUS_VALIDITY"
        )
        sector_warning_match = None
        confidence = "LOW"

    else:
        status = (
            "OFFICIAL_BULLETIN_AVAILABLE_NO_CURRENT_SECTOR_MATCH"
        )
        temporal_status = (
            "NO_CURRENT_MATCH"
        )
        sector_warning_match = False
        confidence = "MEDIUM"

    active_dnv = any(
        DO_NOT_VENTURE_PHRASE
        in " ".join(
            hit.get(
                "context",
                [],
            )
        ).lower()
        for hit in active_hits
    )

    return {
        "requested_sector": sector,
        "status": status,
        "temporal_status": (
            temporal_status
        ),
        "sector_warning_match": (
            sector_warning_match
        ),
        "match_confidence": (
            confidence
        ),

        # Full evidence is retained for debugging/audit.
        "exact_sector_hits": (
            exact_warning_hits
        ),
        "generic_tamilnadu_hits": (
            generic_hits
        ),

        # Compact categorized views.
        "active_warning_hit_count": (
            len(active_hits)
        ),
        "future_warning_hit_count": (
            len(future_hits)
        ),
        "expired_warning_hit_count": (
            len(expired_hits)
        ),
        "ambiguous_warning_hit_count": (
            len(ambiguous_hits)
        ),

        "active_warning_hits": (
            active_hits
        ),
        "future_warning_hits": (
            future_hits
        ),
        "expired_warning_hits": (
            expired_hits
        ),
        "ambiguous_warning_hits": (
            ambiguous_hits
        ),

        "current_tamilnadu_coast_section_nil": (
            current_tn_nil
        ),
        "current_tamilnadu_coast_section_nil_raw_text_found": (
            current_tn_nil_raw
        ),

        "do_not_venture_text_present_somewhere_in_bulletin": (
            do_not_venture_anywhere
        ),
        "do_not_venture_applies_to_requested_sector_now": (
            True
            if active_dnv
            else None
        ),

        # Backward-compatible field name used by current Risk Agent.
        "do_not_venture_applies_to_requested_sector": (
            True
            if active_dnv
            else None
        ),

        "interpretation_note": (
            "Only time-valid sector evidence can set "
            "sector_warning_match=true. Future, expired, stale, or "
            "time-ambiguous warning text is not treated as an active current "
            "warning. A missing current match must not be interpreted as "
            "overall voyage safety."
        ),
    }


async def _fetch_pdf(
    *,
    client: httpx.AsyncClient,
    attempts: int = 4,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(
        1,
        attempts + 1,
    ):
        try:
            response = await client.get(
                PDF_URL,
                headers={
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )

            if (
                response.status_code
                in TRANSIENT_STATUS_CODES
            ):
                if attempt < attempts:
                    await asyncio.sleep(
                        1.5 * attempt
                    )
                    continue

                raise ImdMarineWarningError(
                    "IMD fishermen-warning PDF remained temporarily "
                    f"unavailable after {attempts} attempts "
                    f"(HTTP {response.status_code})."
                )

            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                ).lower()
            )

            if (
                "pdf"
                not in content_type
                and not response.content.startswith(
                    b"%PDF"
                )
            ):
                raise ImdMarineWarningError(
                    "IMD fishermen-warning endpoint did not return a PDF."
                )

            return response

        except ImdMarineWarningError:
            raise

        except (
            httpx.TimeoutException,
            httpx.HTTPError,
        ) as exc:
            last_error = exc

            if attempt < attempts:
                await asyncio.sleep(
                    1.5 * attempt
                )
                continue

    raise ImdMarineWarningError(
        "Unable to retrieve official IMD fishermen warning "
        f"after {attempts} attempts: {last_error}"
    )


async def marine_warning_for_sector(
    sector: str,
) -> dict[str, Any]:
    """
    Read the official RMC Chennai fishermen-warning bulletin and determine
    whether time-valid warning evidence currently matches the requested
    Tamil Nadu marine sector.

    Supported sectors:
        north_tamilnadu
        south_tamilnadu
        tamilnadu
    """

    sector = sector.strip().lower()

    if sector not in SECTOR_ALIASES:
        raise ValueError(
            "sector must be one of: "
            + ", ".join(
                sorted(
                    SECTOR_ALIASES
                )
            )
        )

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
        response = await _fetch_pdf(
            client=client
        )

    retrieved_at_utc = _utc_now()

    try:
        (
            full_text,
            lines,
            page_count,
        ) = _extract_pdf_text(
            response.content
        )

    except Exception as exc:
        raise ImdMarineWarningError(
            f"Unable to parse official IMD warning PDF: {exc}"
        ) from exc

    timing = _bulletin_timing(
        full_text
    )

    sector_result = _sector_status(
        sector=sector,
        lines=lines,
        full_text=full_text,
        bulletin_timing=timing,
    )

    return {
        "source": (
            "India Meteorological Department / "
            "Regional Meteorological Centre Chennai"
        ),
        "source_type": "official",
        "official": True,
        "source_url": PDF_URL,
        "parameter": (
            "marine_fishermen_warning"
        ),
        "retrieved_at_utc": (
            retrieved_at_utc
        ),
        "http_last_modified": (
            response.headers.get(
                "last-modified"
            )
        ),
        "page_count": page_count,

        # Backward-compatible diagnostics.
        "dates_found": _extract_dates(
            full_text
        ),
        "issue_times_found": (
            _extract_issue_times(
                full_text
            )
        ),

        # New timing/freshness diagnostics.
        "bulletin_timing": timing,
        "temporal_status": (
            sector_result.get(
                "temporal_status"
            )
        ),

        "bulletin_warning_terms": (
            _bulletin_warning_terms(
                full_text
            )
        ),
        "bulletin_available": True,
        "sector": sector_result,
        "safety_interpretation": (
            "OFFICIAL_WARNING_EVIDENCE_ONLY"
        ),
        "navigation_grade": False,
        "note": (
            "This connector reports official warning evidence with sector "
            "and time-validity checks. Only ACTIVE_CURRENT_WARNING evidence "
            "can produce sector_warning_match=true. Future, expired, stale, "
            "or ambiguous warning text is not promoted to an active warning. "
            "A missing current match is not a declaration that conditions "
            "are safe."
        ),
    }


def _compact_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    sector = (
        result.get("sector")
        or {}
    )

    return {
        "source": result.get(
            "source"
        ),
        "official": result.get(
            "official"
        ),
        "bulletin_available": (
            result.get(
                "bulletin_available"
            )
        ),
        "retrieved_at_utc": (
            result.get(
                "retrieved_at_utc"
            )
        ),
        "bulletin_timing": (
            result.get(
                "bulletin_timing"
            )
        ),
        "requested_sector": (
            sector.get(
                "requested_sector"
            )
        ),
        "status": sector.get(
            "status"
        ),
        "temporal_status": (
            sector.get(
                "temporal_status"
            )
        ),
        "sector_warning_match": (
            sector.get(
                "sector_warning_match"
            )
        ),
        "match_confidence": (
            sector.get(
                "match_confidence"
            )
        ),
        "current_tamilnadu_coast_section_nil": (
            sector.get(
                "current_tamilnadu_coast_section_nil"
            )
        ),
        "warning_hit_counts": {
            "active": sector.get(
                "active_warning_hit_count",
                0,
            ),
            "future": sector.get(
                "future_warning_hit_count",
                0,
            ),
            "expired": sector.get(
                "expired_warning_hit_count",
                0,
            ),
            "ambiguous": sector.get(
                "ambiguous_warning_hit_count",
                0,
            ),
        },
        "do_not_venture_text_present_somewhere_in_bulletin": (
            sector.get(
                "do_not_venture_text_present_somewhere_in_bulletin"
            )
        ),
        "do_not_venture_applies_to_requested_sector_now": (
            sector.get(
                "do_not_venture_applies_to_requested_sector_now"
            )
        ),
        "dates_found": result.get(
            "dates_found",
            [],
        ),
        "issue_times_found": (
            result.get(
                "issue_times_found",
                [],
            )
        ),
        "navigation_grade": False,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Query official IMD/RMC Chennai fishermen-warning bulletin "
            "for a Tamil Nadu marine sector."
        )
    )

    parser.add_argument(
        "--sector",
        required=True,
        choices=sorted(
            SECTOR_ALIASES
        ),
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help=(
            "Print the complete evidence payload including hit contexts. "
            "Default output is compact."
        ),
    )

    args = parser.parse_args()

    try:
        result = await marine_warning_for_sector(
            args.sector
        )

        output = (
            result
            if args.full
            else _compact_result(
                result
            )
        )

    except ImdMarineWarningError as exc:
        output = {
            "official": True,
            "bulletin_available": False,
            "status": "UNAVAILABLE",
            "temporal_status": (
                "SOURCE_UNAVAILABLE"
            ),
            "error": str(exc),
            "source_url": PDF_URL,
            "navigation_grade": False,
        }

    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
