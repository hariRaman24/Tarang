"""
TARANG Open-Meteo service.

Provides:
- Location geocoding
- Real atmospheric weather
- Real marine forecast
- Current conditions
- Hourly forecast

Atmospheric variables:
temperature, apparent temperature, humidity, precipitation,
rain, cloud cover, pressure, visibility, wind and gusts.

Marine variables:
wave height, direction, period, SST,
ocean current and sea-level-height including tides.

Open-Meteo sea-level/tide estimates are modelled values and
must NOT be treated as navigation-grade coastal tide information.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass, field

import httpx


GEOCODING_URL = (
    "https://geocoding-api.open-meteo.com/v1/search"
)

MARINE_URL = (
    "https://marine-api.open-meteo.com/v1/marine"
)

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

TIMEOUT_SECONDS = 10.0


class OpenMeteoError(Exception):
    """
    Raised when Open-Meteo cannot be reached
    or returns an invalid response.
    """


@dataclass
class GeocodeResult:

    name: str
    lat: float
    lon: float

    country: str | None = None
    admin1: str | None = None

    @property
    def label(self) -> str:

        parts = [
            self.name,
            self.admin1,
            self.country,
        ]

        return ", ".join(
            value
            for value in parts
            if value
        )


@dataclass
class ForecastReading:

    # Existing values — keep these for backwards compatibility
    sst: float | None
    wave_height: float | None
    wind_speed: float | None
    wind_direction: float | None

    hourly_time: list[str]
    hourly_wind: list[float]
    hourly_wave: list[float]
    hourly_sst: list[float]

    # Atmospheric current conditions
    air_temperature: float | None = None
    apparent_temperature: float | None = None

    relative_humidity: float | None = None

    precipitation: float | None = None
    rain: float | None = None

    cloud_cover: float | None = None

    pressure_msl: float | None = None
    surface_pressure: float | None = None

    visibility_m: float | None = None

    wind_gusts: float | None = None

    weather_code: int | None = None

    # Marine conditions
    wave_direction: float | None = None
    wave_period: float | None = None

    sea_level_height_msl: float | None = None

    ocean_current_velocity: float | None = None
    ocean_current_direction: float | None = None

    # Extended hourly atmospheric forecast
    hourly_temperature: list[float] = field(
        default_factory=list
    )

    hourly_apparent_temperature: list[float] = field(
        default_factory=list
    )

    hourly_humidity: list[float] = field(
        default_factory=list
    )

    hourly_precipitation: list[float] = field(
        default_factory=list
    )

    hourly_rain: list[float] = field(
        default_factory=list
    )

    hourly_cloud_cover: list[float] = field(
        default_factory=list
    )

    hourly_pressure_msl: list[float] = field(
        default_factory=list
    )

    hourly_visibility: list[float] = field(
        default_factory=list
    )

    hourly_wind_gusts: list[float] = field(
        default_factory=list
    )

    hourly_weather_code: list[int] = field(
        default_factory=list
    )

    # Extended hourly marine forecast
    hourly_wave_direction: list[float] = field(
        default_factory=list
    )

    hourly_wave_period: list[float] = field(
        default_factory=list
    )

    hourly_sea_level: list[float] = field(
        default_factory=list
    )

    hourly_current_velocity: list[float] = field(
        default_factory=list
    )

    hourly_current_direction: list[float] = field(
        default_factory=list
    )


def _first(values):

    if values:
        return values[0]

    return None


def _current_or_first(
    current: dict,
    current_key: str,
    hourly: dict,
    hourly_key: str,
):

    value = current.get(current_key)

    if value is not None:
        return value

    return _first(
        hourly.get(hourly_key) or []
    )


async def geocode_location(
    query: str,
    count: int = 1,
    language: str = "en",
) -> list[GeocodeResult]:

    try:

        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS
        ) as client:

            response = await client.get(
                GEOCODING_URL,
                params={
                    "name": query,
                    "count": count,
                    "language": language,
                    "format": "json",
                },
            )

            response.raise_for_status()

            data = response.json()

    except httpx.HTTPError as exc:

        raise OpenMeteoError(
            f"Geocoding request failed: {exc}"
        ) from exc

    results = data.get("results") or []

    return [

        GeocodeResult(
            name=result["name"],
            lat=result["latitude"],
            lon=result["longitude"],
            country=result.get("country"),
            admin1=result.get("admin1"),
        )

        for result in results
    ]


async def fetch_forecast(
    lat: float,
    lon: float,
    forecast_days: int = 3,
) -> ForecastReading:

    """
    Retrieve real atmospheric and marine conditions.

    Weather and marine requests execute concurrently.
    """

    weather_variables = ",".join([
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "precipitation",
        "rain",
        "weather_code",
        "cloud_cover",
        "pressure_msl",
        "surface_pressure",
        "visibility",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
    ])

    marine_variables = ",".join([
        "wave_height",
        "wave_direction",
        "wave_period",
        "sea_surface_temperature",
        "sea_level_height_msl",
        "ocean_current_velocity",
        "ocean_current_direction",
    ])

    async def get_weather(
        client: httpx.AsyncClient
    ):

        response = await client.get(
            WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,

                "current": weather_variables,
                "hourly": weather_variables,

                "forecast_days": forecast_days,

                "timezone": "auto",
            },
        )

        response.raise_for_status()

        return response.json()


    async def get_marine(
        client: httpx.AsyncClient
    ):

        response = await client.get(
            MARINE_URL,
            params={
                "latitude": lat,
                "longitude": lon,

                "current": marine_variables,
                "hourly": marine_variables,

                "forecast_days": forecast_days,

                "timezone": "auto",

                # Prefer an ocean cell rather than nearby land
                "cell_selection": "sea",
            },
        )

        response.raise_for_status()

        return response.json()


    try:

        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS
        ) as client:

            marine, weather = await asyncio.gather(
                get_marine(client),
                get_weather(client),
            )

    except httpx.HTTPError as exc:

        raise OpenMeteoError(
            f"Forecast request failed: {exc}"
        ) from exc


    marine_current = (
        marine.get("current") or {}
    )

    marine_hourly = (
        marine.get("hourly") or {}
    )

    weather_current = (
        weather.get("current") or {}
    )

    weather_hourly = (
        weather.get("hourly") or {}
    )


    # -------------------------
    # Core marine readings
    # -------------------------

    wave_height = _current_or_first(
        marine_current,
        "wave_height",
        marine_hourly,
        "wave_height",
    )

    sst = _current_or_first(
        marine_current,
        "sea_surface_temperature",
        marine_hourly,
        "sea_surface_temperature",
    )


    # -------------------------
    # Core atmospheric readings
    # -------------------------

    wind_speed = _current_or_first(
        weather_current,
        "wind_speed_10m",
        weather_hourly,
        "wind_speed_10m",
    )

    wind_direction = _current_or_first(
        weather_current,
        "wind_direction_10m",
        weather_hourly,
        "wind_direction_10m",
    )


    return ForecastReading(

        # Existing fields
        sst=sst,
        wave_height=wave_height,
        wind_speed=wind_speed,
        wind_direction=wind_direction,

        hourly_time=(
            weather_hourly.get("time")
            or marine_hourly.get("time")
            or []
        ),

        hourly_wind=(
            weather_hourly.get(
                "wind_speed_10m"
            ) or []
        ),

        hourly_wave=(
            marine_hourly.get(
                "wave_height"
            ) or []
        ),

        hourly_sst=(
            marine_hourly.get(
                "sea_surface_temperature"
            ) or []
        ),


        # ----------------------------------
        # Current atmospheric conditions
        # ----------------------------------

        air_temperature=_current_or_first(
            weather_current,
            "temperature_2m",
            weather_hourly,
            "temperature_2m",
        ),

        apparent_temperature=_current_or_first(
            weather_current,
            "apparent_temperature",
            weather_hourly,
            "apparent_temperature",
        ),

        relative_humidity=_current_or_first(
            weather_current,
            "relative_humidity_2m",
            weather_hourly,
            "relative_humidity_2m",
        ),

        precipitation=_current_or_first(
            weather_current,
            "precipitation",
            weather_hourly,
            "precipitation",
        ),

        rain=_current_or_first(
            weather_current,
            "rain",
            weather_hourly,
            "rain",
        ),

        cloud_cover=_current_or_first(
            weather_current,
            "cloud_cover",
            weather_hourly,
            "cloud_cover",
        ),

        pressure_msl=_current_or_first(
            weather_current,
            "pressure_msl",
            weather_hourly,
            "pressure_msl",
        ),

        surface_pressure=_current_or_first(
            weather_current,
            "surface_pressure",
            weather_hourly,
            "surface_pressure",
        ),

        visibility_m=_current_or_first(
            weather_current,
            "visibility",
            weather_hourly,
            "visibility",
        ),

        wind_gusts=_current_or_first(
            weather_current,
            "wind_gusts_10m",
            weather_hourly,
            "wind_gusts_10m",
        ),

        weather_code=_current_or_first(
            weather_current,
            "weather_code",
            weather_hourly,
            "weather_code",
        ),


        # ----------------------------------
        # Current marine conditions
        # ----------------------------------

        wave_direction=_current_or_first(
            marine_current,
            "wave_direction",
            marine_hourly,
            "wave_direction",
        ),

        wave_period=_current_or_first(
            marine_current,
            "wave_period",
            marine_hourly,
            "wave_period",
        ),

        sea_level_height_msl=_current_or_first(
            marine_current,
            "sea_level_height_msl",
            marine_hourly,
            "sea_level_height_msl",
        ),

        ocean_current_velocity=_current_or_first(
            marine_current,
            "ocean_current_velocity",
            marine_hourly,
            "ocean_current_velocity",
        ),

        ocean_current_direction=_current_or_first(
            marine_current,
            "ocean_current_direction",
            marine_hourly,
            "ocean_current_direction",
        ),


        # ----------------------------------
        # Hourly atmospheric forecast
        # ----------------------------------

        hourly_temperature=(
            weather_hourly.get(
                "temperature_2m"
            ) or []
        ),

        hourly_apparent_temperature=(
            weather_hourly.get(
                "apparent_temperature"
            ) or []
        ),

        hourly_humidity=(
            weather_hourly.get(
                "relative_humidity_2m"
            ) or []
        ),

        hourly_precipitation=(
            weather_hourly.get(
                "precipitation"
            ) or []
        ),

        hourly_rain=(
            weather_hourly.get(
                "rain"
            ) or []
        ),

        hourly_cloud_cover=(
            weather_hourly.get(
                "cloud_cover"
            ) or []
        ),

        hourly_pressure_msl=(
            weather_hourly.get(
                "pressure_msl"
            ) or []
        ),

        hourly_visibility=(
            weather_hourly.get(
                "visibility"
            ) or []
        ),

        hourly_wind_gusts=(
            weather_hourly.get(
                "wind_gusts_10m"
            ) or []
        ),

        hourly_weather_code=(
            weather_hourly.get(
                "weather_code"
            ) or []
        ),


        # ----------------------------------
        # Hourly marine forecast
        # ----------------------------------

        hourly_wave_direction=(
            marine_hourly.get(
                "wave_direction"
            ) or []
        ),

        hourly_wave_period=(
            marine_hourly.get(
                "wave_period"
            ) or []
        ),

        hourly_sea_level=(
            marine_hourly.get(
                "sea_level_height_msl"
            ) or []
        ),

        hourly_current_velocity=(
            marine_hourly.get(
                "ocean_current_velocity"
            ) or []
        ),

        hourly_current_direction=(
            marine_hourly.get(
                "ocean_current_direction"
            ) or []
        ),
    )