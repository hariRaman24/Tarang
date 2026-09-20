"""
Request/response schemas. Pydantic validates every request automatically
and FastAPI uses these to generate the /docs page — you get a working
interactive API tester for free.
"""

from typing import Optional

from pydantic import BaseModel, Field


class VesselProfileIn(BaseModel):
    vessel_type: str = Field(default="motorized", pattern="^(traditional|motorized|mechanized)$")
    range_km: float = Field(default=25.0, ge=1, le=1000)


class MarineQuery(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    vessel: VesselProfileIn = VesselProfileIn()
