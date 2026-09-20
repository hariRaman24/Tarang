"""
TARANG Weather Intelligence Agent.

This agent is responsible only for atmospheric + marine forecast evidence.

It receives:
    latitude
    longitude
    optional planner time_window

It returns structured machine-readable data for:
    - current atmospheric conditions
    - current marine conditions
    - hourly forecast series

Important:
The internal keys remain English because they are API/data-contract keys.
Tamil/Hindi translation will happen at the presentation/i18n layer later.
"""

from datetime import datetime, timezone

from app.services.openmeteo import (
    OpenMeteoError,
    fetch_forecast,
)


def _weather_code_text(code: int | None) -> str | None:
    """
    Convert WMO weather code to a simple readable condition.
    """

    if code is None:
        return None

    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",

        45: "Fog",
        48: "Rime fog",

        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",

        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",

        61: "Light rain",
        63: "Moderate rain",
        65: "Heavy rain",

        66: "Light freezing rain",
        67: "Heavy freezing rain",

        71: "Light snow",
        73: "Moderate snow",
        75: "Heavy snow",

        77: "Snow grains",

        80: "Light rain showers",
        81: "Moderate rain showers",
        82: "Heavy rain showers",

        85: "Light snow showers",
        86: "Heavy snow showers",

        95: "Thunderstorm",
        96: "Thunderstorm with light hail",
        99: "Thunderstorm with heavy hail",
    }

    return mapping.get(
        code,
        f"Weather code {code}"
    )



TIME_WINDOW_LABELS = {
    "today": "today",
    "tonight": "tonight",
    "tomorrow": "tomorrow",
    "tomorrow_morning": "tomorrow morning",
}


def _parse_hourly_times(
    values: list[str],
) -> list[datetime | None]:
    parsed: list[datetime | None] = []

    for value in values:
        try:
            parsed.append(
                datetime.fromisoformat(
                    value
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            parsed.append(
                None
            )

    return parsed


def _window_indices(
    hourly_time: list[str],
    time_window: str | None,
) -> list[int]:
    """
    Resolve the planner's relative time window against the local hourly
    forecast returned by Open-Meteo.

    Open-Meteo is requested with timezone=auto, so the hourly timestamps are
    location-local clock times. The first distinct forecast date is treated
    as today and the second as tomorrow.

    Current/no-window queries deliberately return no indices so the existing
    current-condition fields remain the assessment source.
    """

    if time_window not in TIME_WINDOW_LABELS:
        return []

    parsed = _parse_hourly_times(
        hourly_time
    )

    dates: list = []

    for value in parsed:
        if (
            value is not None
            and value.date() not in dates
        ):
            dates.append(
                value.date()
            )

    if not dates:
        return []

    if time_window in {
        "tomorrow",
        "tomorrow_morning",
    }:
        if len(dates) < 2:
            return []

        target_date = dates[1]

    else:
        target_date = dates[0]

    selected: list[int] = []

    for index, value in enumerate(
        parsed
    ):
        if value is None:
            continue

        if value.date() != target_date:
            continue

        hour = value.hour

        if (
            time_window
            == "tomorrow_morning"
            and not (
                6 <= hour < 12
            )
        ):
            continue

        if (
            time_window
            == "tonight"
            and not (
                18 <= hour < 24
            )
        ):
            continue

        selected.append(
            index
        )

    return selected


def _at(
    values: list,
    index: int,
):
    if (
        index < 0
        or index >= len(values)
    ):
        return None

    return values[index]


def _valid_numbers(
    values: list,
    indices: list[int],
) -> list[float]:
    result: list[float] = []

    for index in indices:
        value = _at(
            values,
            index,
        )

        if isinstance(
            value,
            (int, float),
        ):
            result.append(
                float(value)
            )

    return result


def _peak(
    values: list,
    times: list[str],
    indices: list[int],
) -> tuple[float | None, str | None]:
    candidates: list[
        tuple[float, int]
    ] = []

    for index in indices:
        value = _at(
            values,
            index,
        )

        if isinstance(
            value,
            (int, float),
        ):
            candidates.append(
                (
                    float(value),
                    index,
                )
            )

    if not candidates:
        return None, None

    value, index = max(
        candidates,
        key=lambda item: item[0],
    )

    return (
        value,
        _at(
            times,
            index,
        ),
    )


def _average(
    values: list,
    indices: list[int],
) -> float | None:
    numbers = _valid_numbers(
        values,
        indices,
    )

    if not numbers:
        return None

    return round(
        sum(numbers)
        / len(numbers),
        2,
    )


def _sum(
    values: list,
    indices: list[int],
) -> float | None:
    numbers = _valid_numbers(
        values,
        indices,
    )

    if not numbers:
        return None

    return round(
        sum(numbers),
        2,
    )


def _build_assessment_window(
    data: dict,
    time_window: str | None,
) -> dict:
    """
    Build conservative weather evidence for the user's requested period.

    Safety policy:
    - peak wave height across the selected period
    - peak wind speed across the selected period
    - peak gust across the selected period
    - average SST for context
    - accumulated rain/precipitation for context

    This does not change or overwrite the current-condition fields.
    """

    if time_window not in TIME_WINDOW_LABELS:
        return {
            "requested_time_window": None,
            "status": "CURRENT_CONDITIONS",
            "label": "current conditions",
            "sample_count": 0,
            "start_local": None,
            "end_local": None,
            "wave_height_m": (
                data.get(
                    "wave_height_m"
                )
            ),
            "wind_speed_kmh": (
                data.get(
                    "wind_speed_kmh"
                )
            ),
            "wind_gusts_kmh": (
                data.get(
                    "wind_gusts_kmh"
                )
            ),
            "sea_surface_temperature_c": (
                data.get(
                    "sea_surface_temperature_c"
                )
            ),
            "selection_policy": (
                "Current Open-Meteo values."
            ),
        }

    times = (
        data.get(
            "hourly_time"
        )
        or []
    )

    indices = _window_indices(
        times,
        time_window,
    )

    if not indices:
        return {
            "requested_time_window": (
                time_window
            ),
            "status": "UNAVAILABLE",
            "label": TIME_WINDOW_LABELS[
                time_window
            ],
            "sample_count": 0,
            "start_local": None,
            "end_local": None,
            "wave_height_m": None,
            "wind_speed_kmh": None,
            "wind_gusts_kmh": None,
            "sea_surface_temperature_c": None,
            "precipitation_mm_total": None,
            "rain_mm_total": None,
            "selection_policy": (
                "Requested forecast window was not present in the "
                "returned hourly series."
            ),
        }

    wave, wave_time = _peak(
        data.get(
            "hourly_wave"
        )
        or [],
        times,
        indices,
    )

    wind, wind_time = _peak(
        data.get(
            "hourly_wind"
        )
        or [],
        times,
        indices,
    )

    gust, gust_time = _peak(
        data.get(
            "hourly_wind_gusts"
        )
        or [],
        times,
        indices,
    )

    return {
        "requested_time_window": (
            time_window
        ),
        "status": "FORECAST_WINDOW_SELECTED",
        "label": TIME_WINDOW_LABELS[
            time_window
        ],
        "sample_count": len(
            indices
        ),
        "start_local": _at(
            times,
            indices[0],
        ),
        "end_local": _at(
            times,
            indices[-1],
        ),
        "wave_height_m": wave,
        "wave_peak_time_local": (
            wave_time
        ),
        "wind_speed_kmh": wind,
        "wind_peak_time_local": (
            wind_time
        ),
        "wind_gusts_kmh": gust,
        "wind_gust_peak_time_local": (
            gust_time
        ),
        "sea_surface_temperature_c": (
            _average(
                data.get(
                    "hourly_sst"
                )
                or [],
                indices,
            )
        ),
        "precipitation_mm_total": (
            _sum(
                data.get(
                    "hourly_precipitation"
                )
                or [],
                indices,
            )
        ),
        "rain_mm_total": (
            _sum(
                data.get(
                    "hourly_rain"
                )
                or [],
                indices,
            )
        ),
        "selection_policy": (
            "Peak wave/wind/gust across the requested period are "
            "used for conservative vessel-threshold screening; SST "
            "is averaged across the period."
        ),
    }


def _empty_weather_data() -> dict:
    """
    Stable response structure when upstream weather data fails.
    """

    return {

        # -------------------
        # Atmospheric
        # -------------------

        "air_temperature_c": None,
        "apparent_temperature_c": None,

        "relative_humidity_percent": None,

        "precipitation_mm": None,
        "rain_mm": None,

        "cloud_cover_percent": None,

        "pressure_msl_hpa": None,
        "surface_pressure_hpa": None,

        "visibility_m": None,
        "visibility_km": None,

        "wind_speed_kmh": None,
        "wind_direction_deg": None,
        "wind_gusts_kmh": None,

        "weather_code": None,
        "weather_condition": None,


        # -------------------
        # Marine
        # -------------------

        "sea_surface_temperature_c": None,

        "wave_height_m": None,
        "wave_direction_deg": None,
        "wave_period_s": None,

        "sea_level_height_msl_m": None,

        "ocean_current_velocity_kmh": None,
        "ocean_current_direction_deg": None,


        # -------------------
        # Hourly atmospheric
        # -------------------

        "hourly_time": [],

        "hourly_temperature": [],
        "hourly_apparent_temperature": [],

        "hourly_humidity": [],

        "hourly_precipitation": [],
        "hourly_rain": [],

        "hourly_cloud_cover": [],
        "hourly_pressure_msl": [],

        "hourly_visibility": [],

        "hourly_wind": [],
        "hourly_wind_gusts": [],

        "hourly_weather_code": [],


        # -------------------
        # Hourly marine
        # -------------------

        "hourly_wave": [],
        "hourly_sst": [],

        "hourly_wave_direction": [],
        "hourly_wave_period": [],

        "hourly_sea_level": [],

        "hourly_current_velocity": [],
        "hourly_current_direction": [],

        # -------------------
        # Requested period
        # -------------------

        "assessment": {
            "requested_time_window": None,
            "status": "UNAVAILABLE",
            "label": None,
            "sample_count": 0,
            "start_local": None,
            "end_local": None,
            "wave_height_m": None,
            "wind_speed_kmh": None,
            "wind_gusts_kmh": None,
            "sea_surface_temperature_c": None,
            "selection_policy": (
                "Weather source unavailable."
            ),
        },
    }


async def weather_agent(
    latitude: float,
    longitude: float,
    time_window: str | None = None,
) -> dict:

    try:

        reading = await fetch_forecast(
            latitude,
            longitude,
        )

        visibility_km = None

        if reading.visibility_m is not None:

            visibility_km = round(
                reading.visibility_m / 1000,
                2
            )

        data = {

            # =================================
            # Atmospheric current conditions
            # =================================

            "air_temperature_c":
                reading.air_temperature,

            "apparent_temperature_c":
                reading.apparent_temperature,

            "relative_humidity_percent":
                reading.relative_humidity,

            "precipitation_mm":
                reading.precipitation,

            "rain_mm":
                reading.rain,

            "cloud_cover_percent":
                reading.cloud_cover,

            "pressure_msl_hpa":
                reading.pressure_msl,

            "surface_pressure_hpa":
                reading.surface_pressure,

            "visibility_m":
                reading.visibility_m,

            "visibility_km":
                visibility_km,

            "wind_speed_kmh":
                reading.wind_speed,

            "wind_direction_deg":
                reading.wind_direction,

            "wind_gusts_kmh":
                reading.wind_gusts,

            "weather_code":
                reading.weather_code,

            "weather_condition":
                _weather_code_text(
                    reading.weather_code
                ),


            # =================================
            # Marine current conditions
            # =================================

            "sea_surface_temperature_c":
                reading.sst,

            "wave_height_m":
                reading.wave_height,

            "wave_direction_deg":
                reading.wave_direction,

            "wave_period_s":
                reading.wave_period,

            "sea_level_height_msl_m":
                reading.sea_level_height_msl,

            "ocean_current_velocity_kmh":
                reading.ocean_current_velocity,

            "ocean_current_direction_deg":
                reading.ocean_current_direction,


            # =================================
            # Hourly atmospheric forecast
            # =================================

            "hourly_time":
                reading.hourly_time,

            "hourly_temperature":
                reading.hourly_temperature,

            "hourly_apparent_temperature":
                reading.hourly_apparent_temperature,

            "hourly_humidity":
                reading.hourly_humidity,

            "hourly_precipitation":
                reading.hourly_precipitation,

            "hourly_rain":
                reading.hourly_rain,

            "hourly_cloud_cover":
                reading.hourly_cloud_cover,

            "hourly_pressure_msl":
                reading.hourly_pressure_msl,

            "hourly_visibility":
                reading.hourly_visibility,

            "hourly_wind":
                reading.hourly_wind,

            "hourly_wind_gusts":
                reading.hourly_wind_gusts,

            "hourly_weather_code":
                reading.hourly_weather_code,


            # =================================
            # Hourly marine forecast
            # =================================

            "hourly_wave":
                reading.hourly_wave,

            "hourly_sst":
                reading.hourly_sst,

            "hourly_wave_direction":
                reading.hourly_wave_direction,

            "hourly_wave_period":
                reading.hourly_wave_period,

            "hourly_sea_level":
                reading.hourly_sea_level,

            "hourly_current_velocity":
                reading.hourly_current_velocity,

            "hourly_current_direction":
                reading.hourly_current_direction,
        }

        data["assessment"] = (
            _build_assessment_window(
                data,
                time_window,
            )
        )

        return {
            "agent": "Weather Intelligence Agent",

            "source":
                "Open-Meteo Weather + Marine APIs",

            "live": True,

            "ok": True,

            "fetched_at": datetime.now(timezone.utc).isoformat(),

            "coordinates": {
                "latitude": latitude,
                "longitude": longitude,
            },

            "requested_time_window": (
                time_window
            ),

            "data": data,
        }


    except OpenMeteoError as exc:

        return {
            "agent": "Weather Intelligence Agent",

            "source":
                "Open-Meteo unavailable",

            "live": False,

            "ok": False,

            "fetched_at": datetime.now(timezone.utc).isoformat(),

            "coordinates": {
                "latitude": latitude,
                "longitude": longitude,
            },

            "requested_time_window": (
                time_window
            ),

            "error": str(exc),

            "data": _empty_weather_data(),
        }