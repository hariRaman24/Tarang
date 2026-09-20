"""
Route Agent.

Wires app/geo/engine.py's compute_route() (already tested — IDW risk
interpolation across candidate corridors, hard penalty for crossing a
restricted zone) into the pipeline. This existed in the engine since
Layer 1 but was never exposed through an agent or the API — that gap is
closed here.

Destination defaults to the best-recommended PFZ (productivity-weighted),
not just the closest one — consistent with how the Geospatial Agent
already treats "best" vs "closest" as separate, both-valid answers.
"""

from app.agents.decision_engine import VesselProfile
from app.data.stations import STATIONS
from app.data.zones import ALL_ZONES
from app.geo.engine import Station, best_pfz, compute_route


async def route_agent(latitude: float, longitude: float, vessel: VesselProfile) -> dict:
    candidates = best_pfz(latitude, longitude, STATIONS, max_results=1)
    if not candidates:
        return {
            "agent": "Geospatial Reasoning Agent (Route)",
            "source": "TARANG IDW route risk optimizer",
            "ok": False,
            "error": "No PFZ-flagged destination available in the curated dataset.",
            "data": {},
        }

    origin = Station(name="Query location", lat=latitude, lon=longitude)
    destination: Station = candidates[0]["station"]

    result = compute_route(
        origin, destination, stations=STATIONS, zones=ALL_ZONES,
        vessel_max_wave=vessel.max_wave, vessel_max_wind=vessel.max_wind,
    )

    def serialize(candidate):
        return {
            "waypoints": [[round(lat, 4), round(lon, 4)] for lat, lon in candidate.waypoints],
            "risk_score": candidate.risk_score,
            "crosses_restricted": candidate.crosses_restricted,
        }

    return {
        "agent": "Geospatial Reasoning Agent (Route)",
        "source": "TARANG IDW route risk optimizer",
        "ok": True,
        "data": {
            "start": result["start"],
            "end": result["end"],
            "chosen": serialize(result["chosen"]),
            "rejected": serialize(result["rejected"]),
        },
    }
