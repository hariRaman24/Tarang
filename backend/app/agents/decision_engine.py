"""
Marine Decision Engine — pure scoring functions, no I/O. Vessel-aware:
every threshold comes from the VesselProfile, not a hardcoded constant, so
a traditional catamaran and a mechanized trawler genuinely get different
verdicts on identical weather data.
"""

from __future__ import annotations

from dataclasses import dataclass


VESSEL_PRESETS: dict[str, dict] = {
    "traditional": {"max_wave": 1.0, "max_wind": 18.0, "label": "Traditional (catamaran / canoe)"},
    "motorized": {"max_wave": 1.5, "max_wind": 22.0, "label": "Motorized boat"},
    "mechanized": {"max_wave": 2.2, "max_wind": 30.0, "label": "Mechanized trawler"},
}


@dataclass
class VesselProfile:
    vessel_type: str = "motorized"
    max_wave: float = 1.5
    max_wind: float = 22.0
    range_km: float = 25.0

    @classmethod
    def from_type(cls, vessel_type: str, range_km: float = 25.0) -> "VesselProfile":
        preset = VESSEL_PRESETS.get(vessel_type, VESSEL_PRESETS["motorized"])
        return cls(vessel_type=vessel_type, max_wave=preset["max_wave"], max_wind=preset["max_wind"], range_km=range_km)

    @property
    def label(self) -> str:
        return VESSEL_PRESETS.get(self.vessel_type, VESSEL_PRESETS["motorized"])["label"]


def safety_score(wave: float | None, wind: float | None, cyclone: bool, lightning: bool, vessel: VesselProfile) -> int:
    score = 100
    if wave is not None and wave > vessel.max_wave:
        score -= 30
    if wind is not None and wind > vessel.max_wind:
        score -= 30
    if cyclone:
        score -= 40
    if lightning:
        score -= 15
    return max(0, min(100, score))


def suitability_score(chlorophyll: float | None, sst: float | None) -> int:
    chl = 0.0 if chlorophyll is None else chlorophyll
    chl_score = max(0.0, min(100.0, (chl / 2.0) * 100.0))
    sst_score = 50.0 if sst is None else max(0.0, 100.0 - abs(sst - 28.5) * 20.0)
    return round(chl_score * 0.6 + sst_score * 0.4)


def overall_recommendation(safety: int, suitability: int) -> str:
    if safety < 40:
        return "AVOID"
    if safety < 70 or suitability < 40:
        return "CAUTION"
    return "GO"
