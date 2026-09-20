"""Derived marine analytics built only from returned forecast evidence."""

from __future__ import annotations

from typing import Any


def _range(values: list[Any]) -> dict[str, float | None]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return {
        "min": round(min(numeric), 2) if numeric else None,
        "max": round(max(numeric), 2) if numeric else None,
    }


def build_marine_analytics(weather_result: dict) -> dict:
    data = weather_result.get("data") or {}
    return {
        "status": "AVAILABLE" if weather_result.get("ok") else "DEGRADED",
        "current": {
            "wave_height_m": data.get("wave_height_m"),
            "wave_period_s": data.get("wave_period_s"),
            "sea_surface_temperature_c": data.get("sea_surface_temperature_c"),
            "sea_level_height_m": data.get("sea_level_height_msl_m"),
            "current_velocity_kmh": data.get("ocean_current_velocity_kmh"),
            "current_direction_deg": data.get("ocean_current_direction_deg"),
            "wind_speed_kmh": data.get("wind_speed_kmh"),
        },
        "forecast_ranges": {
            "wave_height_m": _range(data.get("hourly_wave") or []),
            "sea_surface_temperature_c": _range(data.get("hourly_sst") or []),
            "sea_level_height_m": _range(data.get("hourly_sea_level") or []),
            "current_velocity_kmh": _range(
                data.get("hourly_current_velocity") or []
            ),
        },
        "hourly": {
            "time": data.get("hourly_time") or [],
            "wave_height_m": data.get("hourly_wave") or [],
            "sea_surface_temperature_c": data.get("hourly_sst") or [],
            "sea_level_height_m": data.get("hourly_sea_level") or [],
            "current_velocity_kmh": data.get("hourly_current_velocity") or [],
            "current_direction_deg": data.get("hourly_current_direction") or [],
        },
        "provenance": {
            "source": weather_result.get("source"),
            "fetched_at": weather_result.get("fetched_at"),
            "sea_level_note": (
                "Open-Meteo sea-level values are model estimates, not "
                "navigation-grade coastal tide predictions."
            ),
            "current_note": (
                "Ocean currents are model forecast evidence and should not "
                "replace official nautical information."
            ),
        },
    }
