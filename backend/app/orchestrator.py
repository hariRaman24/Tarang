"""
TARANG Orchestrator
===================

Coordinates the specialised TARANG agents without pretending that one model
call is multiple agents.

Execution order
---------------
1. Planner classifies the user's intent.
2. Location and vessel profile are resolved.
3. Weather Agent runs first because its Open-Meteo marine result is useful
   provenance for the Ocean Agent's separate model-SST field. Planner
   time-window intent is forwarded to Weather so requested periods such as
   tomorrow morning are selected from the hourly forecast.
4. Ocean Agent and Geospatial Agent then run concurrently:
      - Ocean: official INCOIS chlorophyll/SST at the USER query coordinate,
        plus Open-Meteo model SST kept separately.
      - Geospatial: official INCOIS PFZ geometry, landing centres, and
        PFZ-coordinate chlorophyll/SST enrichment.
5. Risk Agent runs after Weather + Geospatial so it can combine vessel
   thresholds with official warning evidence.
6. Route Agent runs only for route intent.
7. Synthesis Agent composes the user-facing answer.

Important separation
--------------------
- Ocean Agent point data describes the user's/query coordinate.
- Geospatial PFZ enrichment describes individual PFZ coordinates.
- PFZ-point SST must never be presented as if it were user-location SST.
- The old curated Station object is retained only for compatibility and
  display of matched_station. Risk Agent ignores its simulated hazard flags.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.agents.decision_engine import VesselProfile
from app.agents.geo_agent import geospatial_agent
from app.agents.ocean_agent import ocean_agent
from app.agents.planner import plan_query
from app.agents.risk_agent import risk_agent
from app.agents.route_agent import route_agent
from app.agents.synthesis_agent import synthesize
from app.agents.weather_agent import weather_agent
from app.conversation_store import conversation_store
from app.analytics import build_marine_analytics
from app.data.stations import find_station
from app.schemas import MarineQuery
from app.telemetry import log_query_completed, timed_call


def resolve_location(
    request: MarineQuery,
    previous_messages: list[dict] | None = None,
    planned_location_name: str | None = None,
):
    """
    Resolve the query coordinate.

    Explicit latitude/longitude always win. If they are not supplied,
    location_name is resolved against the existing curated station list.

    The returned Station object is retained for backward compatibility and
    matched_station display only. It must not be treated as official hazard
    evidence.
    """

    if (
        request.latitude is not None
        and request.longitude is not None
    ):
        station = (
            find_station(
                request.location_name
            )
            if request.location_name
            else None
        )

        return (
            request.latitude,
            request.longitude,
            station,
        )

    location_name = request.location_name or planned_location_name
    if location_name:
        station = find_station(
            location_name
        )

        if station:
            return (
                station.lat,
                station.lon,
                station,
            )

    for message in reversed(previous_messages or []):
        if message.get("role") != "user":
            continue
        payload = message.get("payload") or {}
        location = payload.get("location") or {}
        previous_lat = location.get("latitude")
        previous_lon = location.get("longitude")
        if previous_lat is not None and previous_lon is not None:
            return previous_lat, previous_lon, None

    raise ValueError(
        "Provide latitude+longitude, a location_name matching a curated "
        "port, or continue an existing conversation with a known location."
    )


async def orchestrate(
    request: MarineQuery,
    request_id: str | None = None,
) -> dict:
    query_started = time.perf_counter()
    agent_telemetry: list[dict] = []
    conversation_id = conversation_store.ensure_conversation(
        request.conversation_id
    )
    previous_messages = conversation_store.history(conversation_id)

    # ------------------------------------------------------------
    # PLAN + LOCATION + VESSEL
    # ------------------------------------------------------------
    planner_started = time.perf_counter()
    plan = await plan_query(request.query, previous_messages)
    agent_telemetry.append({
        "agent": "planner",
        "duration_ms": round(
            (time.perf_counter() - planner_started) * 1000,
            2,
        ),
        "ok": True,
        "degraded": plan.get("planner_status") is not None,
    })

    (
        lat,
        lon,
        matched_station,
    ) = resolve_location(
        request,
        previous_messages,
        (plan.get("entities") or {}).get("location_name"),
    )

    vessel = VesselProfile.from_type(
        request.vessel.vessel_type,
        request.vessel.range_km,
    )

    # ------------------------------------------------------------
    # WEATHER
    # ------------------------------------------------------------
    # Run Weather first because Ocean Agent keeps the Open-Meteo SST
    # separately as MODEL evidence alongside official INCOIS SST.
    #
    # When the planner detects a supported relative period such as
    # "tomorrow morning", forward that period to Weather Agent so it can
    # select the correct location-local hourly forecast window.
    requested_time_window = (
        plan.get("time_window")
    )

    if requested_time_window:
        weather_call = lambda: weather_agent(
            lat,
            lon,
            time_window=(
                requested_time_window
            ),
        )
    else:
        weather_call = lambda: weather_agent(
            lat,
            lon,
        )

    weather_result, weather_timing = await timed_call(
        "weather",
        weather_call,
    )
    agent_telemetry.append(weather_timing)

    # ------------------------------------------------------------
    # OCEAN + GEOSPATIAL IN PARALLEL
    # ------------------------------------------------------------
    # These are now independent:
    #
    # Ocean Agent:
    #   exact USER/query coordinate -> official INCOIS CHL/SST
    #
    # Geospatial Agent:
    #   official PFZ geometry + PFZ-point enrichment + landing centres
    #
    # Do not use PFZ-point SST as user-location SST.
    (
        ocean_result_with_timing,
        geo_result_with_timing,
    ) = await asyncio.gather(
        timed_call(
            "ocean",
            lambda: ocean_agent(
                latitude=lat,
                longitude=lon,
                weather=weather_result,
            ),
        ),
        timed_call(
            "geospatial",
            lambda: geospatial_agent(
                lat,
                lon,
                vessel.range_km,
            ),
        ),
    )
    ocean_result, ocean_timing = ocean_result_with_timing
    geo_result, geo_timing = geo_result_with_timing
    agent_telemetry.extend([ocean_timing, geo_timing])

    # ------------------------------------------------------------
    # RISK
    # ------------------------------------------------------------
    # The final positional argument is kept for compatibility with the
    # existing Risk Agent signature. The Risk Agent ignores simulated
    # hazard flags from this legacy station object.
    risk_result, risk_timing = await timed_call(
        "risk",
        lambda: risk_agent(
            weather_result,
            geo_result,
            vessel,
            matched_station,
        ),
    )
    agent_telemetry.append(risk_timing)

    # ------------------------------------------------------------
    # COMMON RESPONSE CONTEXT
    # ------------------------------------------------------------
    location = {
        "latitude": lat,
        "longitude": lon,
        "matched_station": (
            matched_station.name
            if matched_station
            else None
        ),
    }

    agents = {
        "weather": weather_result,
        "ocean": ocean_result,
        "geospatial": geo_result,
        "risk": risk_result,
    }

    # ------------------------------------------------------------
    # ROUTE — ONLY WHEN REQUESTED
    # ------------------------------------------------------------
    if plan["intent"] == "route":
        agents["route"], route_timing = await timed_call(
            "route",
            lambda: route_agent(
                lat,
                lon,
                vessel,
            )
        )
        agent_telemetry.append(route_timing)

    # ------------------------------------------------------------
    # SYNTHESIS
    # ------------------------------------------------------------
    synthesis = synthesize(
        plan,
        location,
        agents,
        query_text=request.query,
    )

    response = {
        "conversation_id": conversation_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution": {
            "total_duration_ms": round(
                (time.perf_counter() - query_started) * 1000,
                2,
            ),
            "requested_time_window": (
                requested_time_window
            ),
            "weather_assessment_status": (
                (
                    weather_result.get(
                        "data"
                    )
                    or {}
                ).get(
                    "assessment",
                    {},
                ).get(
                    "status"
                )
            ),
            "agents": agent_telemetry,
        },
        "plan": plan,
        "location": location,
        "agents": agents,
        "marine_analytics": build_marine_analytics(weather_result),
        "answer": synthesis["answer"],
        "alerts": synthesis["alerts"],
        "language": synthesis["language"],
        "data_quality": {
            "live_agents": [
                name
                for name, result in agents.items()
                if result.get("live") is True
            ],
            "degraded_agents": [
                name
                for name, result in agents.items()
                if result.get("ok") is False
                or result.get("degraded") is True
            ],
            "source_timestamps": {
                name: result.get("fetched_at")
                for name, result in agents.items()
                if result.get("fetched_at")
            },
            "advisory_only": True,
        },
        "conversation": {
            "message_count_before_request": len(previous_messages),
            "history": previous_messages,
        },
    }

    conversation_store.add_message(
        conversation_id,
        "user",
        request.query,
        {
            "location": location,
            "vessel": request.vessel.model_dump(),
            "plan": plan,
        },
    )
    conversation_store.add_message(
        conversation_id,
        "assistant",
        response["answer"],
        {
            "alerts": response["alerts"],
            "language": response["language"],
            "plan": response["plan"],
        },
    )
    log_query_completed(
        request_id,
        response["execution"]["total_duration_ms"],
        agent_telemetry,
    )
    return response
