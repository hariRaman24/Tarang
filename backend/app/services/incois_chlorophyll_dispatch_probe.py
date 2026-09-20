"""
TARANG - INCOIS Chlorophyll Dispatch Probe
==========================================

This probe focuses on the BetterWMS plugin itself.

Why:
The previous trace confirmed that chlorophyll click handling calls:
    getFeatureInfoUrl4(...)
    showGetFeatureInfochl(...)

We now need the exact condition that selects that chlorophyll handler,
because that condition often reveals the real WMS layer name.

This script prints:
1. Context around every call to getFeatureInfoUrl4
2. The full getFeatureInfoUrl4 function definition
3. Context around showGetFeatureInfochl
4. Any layer-name comparisons near those blocks

Run:
    python -m app.services.incois_chlorophyll_dispatch_probe

Output:
    incois_chlorophyll_dispatch_probe_report.json
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx


JS_URL = (
    "https://www.incois.gov.in/oceanservices/"
    "L.TileLayer.BetterWMS.Pacific2.js"
)

TIMEOUT_SECONDS = 30.0

TARGETS = [
    "getFeatureInfoUrl4",
    "showGetFeatureInfochl",
    "Chlorophyll",
]

# Common layer comparison forms:
# this.wmsParams.layers == '...'
# this.wmsParams.layers === "..."
LAYER_COMPARE_RE = re.compile(
    r"""(?:this\.)?wmsParams\.layers\s*={2,3}\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

# Any layers: '...' declaration nearby.
LAYER_DECL_RE = re.compile(
    r"""layers\s*:\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


async def main() -> None:
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
        response = await client.get(JS_URL)
        response.raise_for_status()
        text = response.text

    report: dict[str, Any] = {
        "url": JS_URL,
        "status_code": 200,
        "contexts": [],
        "layer_comparisons": [],
        "layer_declarations": [],
    }

    print()
    print("INCOIS CHLOROPHYLL DISPATCH TRACE")
    print("=" * 100)
    print(f"Source: {JS_URL}")
    print()

    # Large context because the important condition may be several
    # statements before the actual function call.
    before_chars = 7000
    after_chars = 4500

    for target in TARGETS:
        print()
        print(f"TARGET: {target}")
        print("-" * 100)

        start = 0
        hit_number = 0

        while True:
            index = text.find(target, start)

            if index == -1:
                break

            hit_number += 1

            left = max(
                0,
                index - before_chars,
            )
            right = min(
                len(text),
                index + len(target) + after_chars,
            )

            raw = text[left:right]

            # Keep formatting somewhat readable.
            readable = (
                raw.replace(";", ";\n")
                .replace("{", "{\n")
                .replace("}", "}\n")
            )

            print()
            print(f"HIT {hit_number}")
            print(readable)

            layer_comparisons = list(
                dict.fromkeys(
                    LAYER_COMPARE_RE.findall(raw)
                )
            )

            layer_declarations = list(
                dict.fromkeys(
                    LAYER_DECL_RE.findall(raw)
                )
            )

            if layer_comparisons:
                print()
                print(
                    "Nearby wmsParams.layers comparisons:",
                    layer_comparisons,
                )

            if layer_declarations:
                print()
                print(
                    "Nearby layers declarations:",
                    layer_declarations,
                )

            report["contexts"].append(
                {
                    "target": target,
                    "hit": hit_number,
                    "context": raw,
                    "layer_comparisons": layer_comparisons,
                    "layer_declarations": layer_declarations,
                }
            )

            for value in layer_comparisons:
                if value not in report[
                    "layer_comparisons"
                ]:
                    report[
                        "layer_comparisons"
                    ].append(value)

            for value in layer_declarations:
                if value not in report[
                    "layer_declarations"
                ]:
                    report[
                        "layer_declarations"
                    ].append(value)

            start = index + len(target)

    print()
    print("=" * 100)
    print("ALL DISCOVERED WMS LAYER COMPARISONS")
    print("=" * 100)

    if report["layer_comparisons"]:
        for layer in report[
            "layer_comparisons"
        ]:
            print(layer)
    else:
        print("No direct wmsParams.layers == '...' comparisons found.")

    print()
    print("ALL NEARBY LAYER DECLARATIONS")
    print("=" * 100)

    if report["layer_declarations"]:
        for layer in report[
            "layer_declarations"
        ]:
            print(layer)
    else:
        print("No nearby layers: '...' declarations found.")

    output_path = (
        Path.cwd()
        / "incois_chlorophyll_dispatch_probe_report.json"
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
    print("=" * 100)
    print("Saved report:")
    print(output_path)


if __name__ == "__main__":
    asyncio.run(main())
