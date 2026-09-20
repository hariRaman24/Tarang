"""
Curated coastal stations — the same 15 ports from the JS prototype, now as
real data instead of a hardcoded array buried in a <script> tag.

Baseline values here (sst/chl/wave/wind) are used until services/openmeteo.py
overwrites sst/wave/wind with a live reading. Chlorophyll stays as the
baseline always — there's no free live source for it (see README).
"""

from __future__ import annotations

from app.geo.engine import Station

STATIONS: list[Station] = [
    Station(name="Chennai", lat=13.05, lon=80.28, sst=29.4, chlorophyll=0.62, wave_height=1.1, wind_speed=18, is_pfz=False),
    Station(name="Cuddalore", lat=11.75, lon=79.77, sst=29.8, chlorophyll=1.35, wave_height=1.4, wind_speed=22, is_pfz=True, lightning=True),
    Station(name="Nagapattinam", lat=10.76, lon=79.84, sst=29.9, chlorophyll=1.68, wave_height=1.6, wind_speed=26, is_pfz=True, cyclone=True, lightning=True),
    Station(name="Rameswaram", lat=9.29, lon=79.31, sst=29.1, chlorophyll=0.48, wave_height=0.9, wind_speed=15, is_pfz=False),
    Station(name="Tuticorin", lat=8.76, lon=78.13, sst=28.7, chlorophyll=0.91, wave_height=1.0, wind_speed=17, is_pfz=True),
    Station(name="Kanyakumari", lat=8.08, lon=77.55, sst=28.5, chlorophyll=0.55, wave_height=1.3, wind_speed=20, is_pfz=False),
    Station(name="Kochi", lat=9.93, lon=76.26, sst=29.0, chlorophyll=0.88, wave_height=1.2, wind_speed=19, is_pfz=True),
    Station(name="Mangalore", lat=12.87, lon=74.84, sst=28.9, chlorophyll=0.74, wave_height=1.3, wind_speed=18, is_pfz=False),
    Station(name="Goa (Mormugao)", lat=15.40, lon=73.80, sst=28.6, chlorophyll=0.66, wave_height=1.1, wind_speed=16, is_pfz=False),
    Station(name="Mumbai", lat=18.95, lon=72.83, sst=28.2, chlorophyll=0.58, wave_height=1.4, wind_speed=21, is_pfz=False),
    Station(name="Veraval", lat=20.90, lon=70.37, sst=27.6, chlorophyll=0.71, wave_height=1.5, wind_speed=23, is_pfz=True),
    Station(name="Visakhapatnam", lat=17.69, lon=83.22, sst=29.5, chlorophyll=0.80, wave_height=1.3, wind_speed=20, is_pfz=True),
    Station(name="Paradip", lat=20.32, lon=86.61, sst=29.2, chlorophyll=0.69, wave_height=1.4, wind_speed=22, is_pfz=False),
    Station(name="Kolkata (Sagar)", lat=21.65, lon=88.05, sst=28.8, chlorophyll=0.77, wave_height=1.2, wind_speed=19, is_pfz=False),
    Station(name="Port Blair", lat=11.62, lon=92.72, sst=29.6, chlorophyll=0.42, wave_height=0.9, wind_speed=14, is_pfz=False),
]


def find_station(name: str) -> Station | None:
    """Case-insensitive, substring-tolerant lookup — 'nagapattinam' or
    'Nagapattinam district' both resolve to the Nagapattinam station."""
    if not name:
        return None
    needle = name.strip().lower()
    for s in STATIONS:
        haystack = s.name.lower()
        if haystack == needle or needle in haystack or haystack in needle:
            return s
    return None
