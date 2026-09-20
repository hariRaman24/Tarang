"""
TARANG - INCOIS Endpoint Probe
==============================

Purpose
-------
Inspect the current official INCOIS PFZ pages and discover the real
machine-readable endpoints used by their WebGIS.

Why this file exists
--------------------
We do NOT want to guess hidden endpoint names or invent PFZ coordinates.
This probe downloads the official public HTML/JS and reports:

- forms and actions
- select/input field names
- sector option values
- script URLs
- iframe URLs
- URLs containing geoserver / WMS / WFS / MapServer / PFZ keywords

It also saves a compact JSON report to:
    backend/incois_probe_report.json

Run:
    python -m app.services.incois_probe

This is a diagnostic/development tool, not an operational agent connector.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


TEXT_PAGE = (
    "https://www.incois.gov.in/"
    "MarineFisheries/TextDataHome?mfid=1&request_locale=en"
)

WEBGIS_PAGE = (
    "https://www.incois.gov.in/"
    "MarineFisheries/PfzWebGis"
)

GEOPORTAL_PAGE = (
    "https://incois.gov.in/"
    "geoportal/MFASPFZ/index.html"
)

TIMEOUT_SECONDS = 25.0
MAX_SCRIPT_FETCHES = 40


INTERESTING_PATTERN = re.compile(
    r"("
    r"https?://[^\s\"'<>\\]+"
    r"|(?:/|\.\.?/)[^\s\"'<>\\]+"
    r")",
    re.IGNORECASE,
)

KEYWORDS = (
    "pfz",
    "geoserver",
    "wms",
    "wfs",
    "ows",
    "mapserver",
    "featureserver",
    "getfeature",
    "getmap",
    "service=",
    "request=",
    "layer",
    "marinefisheries",
    "geoportal",
)


@dataclass
class FormInfo:
    method: str
    action: str
    inputs: list[dict[str, str]]
    selects: list[dict[str, Any]]


class ProbeHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url

        self.forms: list[FormInfo] = []
        self.scripts: list[str] = []
        self.iframes: list[str] = []
        self.links: list[str] = []

        self._current_form: dict[str, Any] | None = None
        self._current_select: dict[str, Any] | None = None
        self._current_option: dict[str, Any] | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {
            str(k).lower(): "" if v is None else str(v)
            for k, v in attrs
        }

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        a = self._attrs(attrs)

        if tag == "form":
            self._current_form = {
                "method": a.get("method", "GET").upper(),
                "action": urljoin(self.base_url, a.get("action", "")),
                "inputs": [],
                "selects": [],
            }

        elif tag == "input" and self._current_form is not None:
            self._current_form["inputs"].append(
                {
                    "name": a.get("name", ""),
                    "type": a.get("type", ""),
                    "value": a.get("value", ""),
                    "id": a.get("id", ""),
                }
            )

        elif tag == "select" and self._current_form is not None:
            self._current_select = {
                "name": a.get("name", ""),
                "id": a.get("id", ""),
                "options": [],
            }

        elif tag == "option" and self._current_select is not None:
            self._current_option = {
                "value": a.get("value", ""),
                "text": "",
            }

        elif tag == "script":
            src = a.get("src")
            if src:
                self.scripts.append(urljoin(self.base_url, src))

        elif tag == "iframe":
            src = a.get("src")
            if src:
                self.iframes.append(urljoin(self.base_url, src))

        elif tag in {"a", "link"}:
            href = a.get("href")
            if href:
                self.links.append(urljoin(self.base_url, href))

    def handle_data(self, data: str) -> None:
        if self._current_option is not None:
            self._current_option["text"] += " ".join(data.split())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "option" and self._current_option is not None:
            if self._current_select is not None:
                self._current_select["options"].append(
                    self._current_option
                )
            self._current_option = None

        elif tag == "select" and self._current_select is not None:
            if self._current_form is not None:
                self._current_form["selects"].append(
                    self._current_select
                )
            self._current_select = None

        elif tag == "form" and self._current_form is not None:
            self.forms.append(
                FormInfo(
                    method=self._current_form["method"],
                    action=self._current_form["action"],
                    inputs=self._current_form["inputs"],
                    selects=self._current_form["selects"],
                )
            )
            self._current_form = None


def _interesting(value: str) -> bool:
    low = value.lower()
    return any(keyword in low for keyword in KEYWORDS)


def _clean_url(base_url: str, candidate: str) -> str | None:
    candidate = candidate.strip().rstrip("),;]")
    candidate = candidate.replace("\\/", "/")

    if candidate.startswith(("http://", "https://", "/", "./", "../")):
        try:
            return urljoin(base_url, candidate)
        except Exception:
            return None

    return None


def extract_interesting_strings(
    text: str,
    base_url: str,
) -> list[str]:
    found: set[str] = set()

    for match in INTERESTING_PATTERN.finditer(text):
        raw = match.group(1)
        if not _interesting(raw):
            continue

        value = _clean_url(base_url, raw)
        if value:
            found.add(value)

    # Also catch quoted relative strings that do not begin with slash.
    for quoted in re.findall(r"""["']([^"'<>]{3,400})["']""", text):
        if not _interesting(quoted):
            continue

        if any(
            token in quoted.lower()
            for token in (
                ".js",
                ".json",
                ".xml",
                "wms",
                "wfs",
                "geoserver",
                "mapserver",
                "getfeature",
                "getmap",
            )
        ):
            value = urljoin(base_url, quoted)
            found.add(value)

    return sorted(found)


async def fetch_text(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[int, str, str]:
    response = await client.get(url)
    response.raise_for_status()

    return (
        response.status_code,
        str(response.url),
        response.text,
    )


async def inspect_page(
    client: httpx.AsyncClient,
    label: str,
    url: str,
) -> dict[str, Any]:
    status, final_url, html = await fetch_text(client, url)

    parser = ProbeHTMLParser(final_url)

    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    interesting_html = extract_interesting_strings(
        html,
        final_url,
    )

    return {
        "label": label,
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "forms": [asdict(x) for x in parser.forms],
        "scripts": sorted(set(parser.scripts)),
        "iframes": sorted(set(parser.iframes)),
        "links": sorted(
            x for x in set(parser.links)
            if _interesting(x)
        ),
        "interesting_html_urls": interesting_html,
    }


async def inspect_scripts(
    client: httpx.AsyncClient,
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    script_urls: list[str] = []

    for page in pages:
        for url in page.get("scripts", []):
            if url not in script_urls:
                script_urls.append(url)

    results: list[dict[str, Any]] = []

    for script_url in script_urls[:MAX_SCRIPT_FETCHES]:
        try:
            status, final_url, text = await fetch_text(
                client,
                script_url,
            )

            hits = extract_interesting_strings(
                text,
                final_url,
            )

            # Keep only scripts that reveal something interesting.
            if hits or _interesting(final_url):
                results.append(
                    {
                        "script_url": final_url,
                        "http_status": status,
                        "interesting_urls": hits,
                    }
                )

        except Exception as exc:
            results.append(
                {
                    "script_url": script_url,
                    "error": str(exc),
                }
            )

    return results


def print_forms(page: dict[str, Any]) -> None:
    forms = page.get("forms", [])

    if not forms:
        print("  Forms: none found")
        return

    print(f"  Forms: {len(forms)}")

    for i, form in enumerate(forms, 1):
        print(
            f"    [{i}] {form['method']} "
            f"{form['action']}"
        )

        inputs = [
            x for x in form.get("inputs", [])
            if x.get("name") or x.get("id")
        ]

        if inputs:
            print("       Inputs:")
            for item in inputs:
                print(
                    "         - "
                    f"name={item.get('name')!r} "
                    f"id={item.get('id')!r} "
                    f"type={item.get('type')!r} "
                    f"value={item.get('value')!r}"
                )

        selects = form.get("selects", [])

        if selects:
            print("       Selects:")
            for select in selects:
                print(
                    "         - "
                    f"name={select.get('name')!r} "
                    f"id={select.get('id')!r}"
                )

                options = select.get("options", [])
                for option in options[:50]:
                    print(
                        "             "
                        f"value={option.get('value')!r} "
                        f"text={option.get('text')!r}"
                    )


async def main() -> None:
    headers = {
        "User-Agent": (
            "TARANG-Marine-Intelligence/1.0 "
            "(educational decision-support prototype)"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/javascript,text/javascript,*/*"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
    }

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
    ) as client:

        targets = [
            ("PFZ Text", TEXT_PAGE),
            ("PFZ WebGIS", WEBGIS_PAGE),
            ("PFZ Geoportal", GEOPORTAL_PAGE),
        ]

        pages: list[dict[str, Any]] = []

        print("\nTARANG INCOIS ENDPOINT PROBE")
        print("=" * 60)

        for label, url in targets:
            print(f"\nChecking: {label}")
            print(f"  {url}")

            try:
                page = await inspect_page(
                    client,
                    label,
                    url,
                )
                pages.append(page)

                print(
                    f"  HTTP: {page['http_status']}"
                )
                print(
                    f"  Final URL: {page['final_url']}"
                )

                print_forms(page)

                if page["iframes"]:
                    print("  Iframes:")
                    for x in page["iframes"]:
                        print(f"    - {x}")

                if page["interesting_html_urls"]:
                    print("  Interesting URLs in HTML:")
                    for x in page["interesting_html_urls"]:
                        print(f"    - {x}")

            except Exception as exc:
                print(f"  ERROR: {exc}")
                pages.append(
                    {
                        "label": label,
                        "requested_url": url,
                        "error": str(exc),
                    }
                )

        print("\nScanning referenced JavaScript for GIS endpoints...")
        script_results = await inspect_scripts(
            client,
            pages,
        )

        discovered: set[str] = set()

        for item in script_results:
            for value in item.get(
                "interesting_urls",
                [],
            ):
                discovered.add(value)

        print("\nDISCOVERED MACHINE-ENDPOINT CANDIDATES")
        print("=" * 60)

        if discovered:
            for value in sorted(discovered):
                print(value)
        else:
            print(
                "No WMS/WFS/GeoServer endpoint was automatically "
                "identified. The saved report still contains form, "
                "script, iframe and link information for inspection."
            )

        report = {
            "pages": pages,
            "scripts": script_results,
            "discovered_candidates": sorted(discovered),
        }

        output_path = (
            Path.cwd()
            / "incois_probe_report.json"
        )

        output_path.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print("\nSaved report:")
        print(output_path)
        print(
            "\nSend me the terminal output, especially the "
            "'DISCOVERED MACHINE-ENDPOINT CANDIDATES' section."
        )


if __name__ == "__main__":
    asyncio.run(main())
