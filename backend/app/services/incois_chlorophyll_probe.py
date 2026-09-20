"""
TARANG - INCOIS Chlorophyll ERDDAP Probe
========================================

Purpose:
    Verify which official INCOIS ERDDAP chlorophyll dataset can provide
    usable chlorophyll-a values near a requested marine position.

Important:
    This is a diagnostic/probe file only.
    TARANG must NOT call a dataset "current/live" until this probe confirms
    the latest available observation time.

Official INCOIS ERDDAP datasets tested:
    1) incois_oceansat2_datasets
       variable: CHL
    2) IRS_chlorophyll_datasets
       variable: CHLOROPHYLL

Example:
    python -m app.services.incois_chlorophyll_probe \
        --lat 13.05 --lon 80.28

The report is saved as:
    incois_chlorophyll_probe_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


ERDDAP_BASE = "https://erddap.incois.gov.in/erddap"

TIMEOUT_SECONDS = 40.0

DATASETS = [
    {
        "dataset_id": "incois_oceansat2_datasets",
        "variable": "CHL",
        "label": "INCOIS Oceansat 2 OCM Data",
        "unit": "mg/m3",
    },
    {
        "dataset_id": "IRS_chlorophyll_datasets",
        "variable": "CHLOROPHYLL",
        "label": "IRS P4 OCM-Chlorophyll",
        "unit": "mg/m^3",
    },
]


async def _get(
    client: httpx.AsyncClient,
    url: str,
) -> httpx.Response:
    response = await client.get(url)
    response.raise_for_status()
    return response


def _parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _valid_chl(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return None

    if number <= -1e30:
        return None

    return number


def _build_latest_box_query(
    *,
    dataset_id: str,
    variable: str,
    latitude: float,
    longitude: float,
    half_window_deg: float = 0.12,
) -> str:
    """
    Request the latest time slice over a small lat/lon box.

    ERDDAP griddap value constraints use parentheses, e.g.
        [(12.93):(13.17)]
    """

    lat_min = latitude - half_window_deg
    lat_max = latitude + half_window_deg
    lon_min = longitude - half_window_deg
    lon_max = longitude + half_window_deg

    expression = (
        f"{variable}"
        f"[(last)]"
        f"[({lat_min:.5f}):({lat_max:.5f})]"
        f"[({lon_min:.5f}):({lon_max:.5f})]"
    )

    return (
        f"{ERDDAP_BASE}/griddap/"
        f"{dataset_id}.csv?"
        f"{quote(expression, safe='[]():,._-')}"
    )


async def probe_dataset(
    client: httpx.AsyncClient,
    spec: dict[str, str],
    *,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    dataset_id = spec["dataset_id"]
    variable = spec["variable"]

    result: dict[str, Any] = {
        "dataset_id": dataset_id,
        "label": spec["label"],
        "variable": variable,
        "expected_unit": spec["unit"],
        "official": True,
        "metadata_ok": False,
        "data_ok": False,
        "latest_time": None,
        "valid_value_count": 0,
        "chlorophyll_min": None,
        "chlorophyll_max": None,
        "chlorophyll_mean": None,
        "sample_rows": [],
        "error": None,
    }

    info_url = (
        f"{ERDDAP_BASE}/info/"
        f"{dataset_id}/index.json"
    )

    try:
        metadata_response = await _get(
            client,
            info_url,
        )

        metadata = metadata_response.json()

        result["metadata_ok"] = True
        result["metadata_url"] = info_url

        # Keep a compact copy of rows mentioning the variable or time.
        table = metadata.get("table") or {}
        rows = table.get("rows") or []

        compact_metadata = []

        for row in rows:
            text = " ".join(
                str(item)
                for item in row
            )

            if (
                variable.lower() in text.lower()
                or "actual_range" in text.lower()
                or (
                    len(row) > 1
                    and str(row[1]).lower() == "time"
                )
            ):
                if len(compact_metadata) < 50:
                    compact_metadata.append(row)

        result["metadata_excerpt"] = compact_metadata

    except Exception as exc:
        result["metadata_error"] = str(exc)

    data_url = _build_latest_box_query(
        dataset_id=dataset_id,
        variable=variable,
        latitude=latitude,
        longitude=longitude,
    )

    result["data_url"] = data_url

    try:
        response = await _get(
            client,
            data_url,
        )

        rows = _parse_csv(
            response.text
        )

        # ERDDAP CSV usually includes a second units row.
        usable_rows = []

        for row in rows:
            chl = _valid_chl(
                row.get(variable)
            )

            if chl is None:
                continue

            usable_rows.append(
                {
                    "time": row.get("time"),
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    variable: chl,
                }
            )

        values = [
            row[variable]
            for row in usable_rows
        ]

        times = [
            row.get("time")
            for row in usable_rows
            if row.get("time")
        ]

        result["data_ok"] = bool(
            usable_rows
        )
        result["valid_value_count"] = len(
            usable_rows
        )
        result["sample_rows"] = usable_rows[:10]

        if times:
            result["latest_time"] = max(times)

        if values:
            result["chlorophyll_min"] = round(
                min(values),
                6,
            )
            result["chlorophyll_max"] = round(
                max(values),
                6,
            )
            result["chlorophyll_mean"] = round(
                sum(values) / len(values),
                6,
            )

    except Exception as exc:
        result["error"] = str(exc)

    return result


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Probe official INCOIS ERDDAP chlorophyll datasets."
        )
    )

    parser.add_argument(
        "--lat",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--lon",
        type=float,
        required=True,
    )

    args = parser.parse_args()

    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:
        results = []

        for spec in DATASETS:
            result = await probe_dataset(
                client,
                spec,
                latitude=args.lat,
                longitude=args.lon,
            )

            results.append(result)

    report = {
        "query_latitude": args.lat,
        "query_longitude": args.lon,
        "source": "INCOIS ERDDAP",
        "official": True,
        "retrieved_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "datasets": results,
    }

    print()
    print("TARANG — INCOIS CHLOROPHYLL ERDDAP PROBE")
    print("=" * 78)

    for result in results:
        print()
        print(result["label"])
        print("-" * 78)
        print(
            f"Dataset ID:        {result['dataset_id']}"
        )
        print(
            f"Variable:          {result['variable']}"
        )
        print(
            f"Metadata OK:       {result['metadata_ok']}"
        )
        print(
            f"Data OK:           {result['data_ok']}"
        )
        print(
            f"Latest data time:  {result['latest_time']}"
        )
        print(
            f"Valid values:      {result['valid_value_count']}"
        )
        print(
            f"CHL min:           {result['chlorophyll_min']}"
        )
        print(
            f"CHL max:           {result['chlorophyll_max']}"
        )
        print(
            f"CHL mean:          {result['chlorophyll_mean']}"
        )

        if result.get("error"):
            print(
                f"Data error:        {result['error']}"
            )

        if result.get("metadata_error"):
            print(
                f"Metadata error:    {result['metadata_error']}"
            )

        if result["sample_rows"]:
            print()
            print("Sample valid rows:")
            print(
                json.dumps(
                    result["sample_rows"][:5],
                    indent=2,
                    ensure_ascii=False,
                )
            )

    output_path = (
        Path.cwd()
        / "incois_chlorophyll_probe_report.json"
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
    print("=" * 78)
    print("Saved report:")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
