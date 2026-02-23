# src/where_the_plow/models.py
from pydantic import BaseModel, Field


class PointGeometry(BaseModel):
    type: str = Field(default="Point", json_schema_extra={"example": "Point"})
    coordinates: list[float] = Field(
        ...,
        description="[longitude, latitude]",
        json_schema_extra={"example": [-52.731, 47.564]},
    )


class FeatureProperties(BaseModel):
    vehicle_id: str = Field(..., description="Unique vehicle identifier")
    description: str = Field(
        ...,
        description="Human-readable vehicle label",
        json_schema_extra={"example": "2222 SA PLOW TRUCK"},
    )
    vehicle_type: str = Field(
        ...,
        description="Vehicle category",
        json_schema_extra={"example": "SA PLOW TRUCK"},
    )
    speed: float | None = Field(None, description="Speed in km/h")
    bearing: int | None = Field(None, description="Heading in degrees (0-360)")
    is_driving: str | None = Field(None, description="Driving status: 'maybe' or 'no'")
    timestamp: str = Field(..., description="Position timestamp (ISO 8601)")
    trail: list[list[float]] | None = Field(
        None, description="Recent trail coordinates [[lng, lat], ...]"
    )
    source: str = Field(
        "st_johns",
        description="Data source identifier",
        json_schema_extra={"example": "st_johns"},
    )


class Feature(BaseModel):
    type: str = Field(default="Feature")
    geometry: PointGeometry
    properties: FeatureProperties


class Pagination(BaseModel):
    limit: int = Field(..., description="Requested page size")
    count: int = Field(..., description="Number of features in this page")
    next_cursor: str | None = Field(
        None, description="Cursor for next page (ISO 8601 timestamp)"
    )
    has_more: bool = Field(
        ..., description="Whether more results exist beyond this page"
    )


class FeatureCollection(BaseModel):
    type: str = Field(default="FeatureCollection")
    features: list[Feature]
    pagination: Pagination


class LineStringGeometry(BaseModel):
    type: str = Field(default="LineString")
    coordinates: list[list[float]] = Field(
        ..., description="Array of [longitude, latitude] coordinate pairs"
    )


class CoverageProperties(BaseModel):
    vehicle_id: str = Field(..., description="Unique vehicle identifier")
    vehicle_type: str = Field(..., description="Vehicle category")
    description: str = Field(..., description="Human-readable vehicle label")
    timestamps: list[str] = Field(
        ...,
        description="ISO 8601 timestamps parallel to coordinates array",
    )
    source: str = Field(
        "st_johns",
        description="Data source identifier",
        json_schema_extra={"example": "st_johns"},
    )


class CoverageFeature(BaseModel):
    type: str = Field(default="Feature")
    geometry: LineStringGeometry
    properties: CoverageProperties


class CoverageFeatureCollection(BaseModel):
    type: str = Field(default="FeatureCollection")
    features: list[CoverageFeature]


class ViewportTrack(BaseModel):
    zoom: float = Field(..., description="Current map zoom level")
    center: list[float] = Field(
        ...,
        description="[longitude, latitude] of map center",
        min_length=2,
        max_length=2,
    )
    bounds: dict = Field(
        ...,
        description="Map bounds: {sw: [lng, lat], ne: [lng, lat]}",
    )


class StatsResponse(BaseModel):
    total_positions: int = Field(..., description="Total position records stored")
    total_vehicles: int = Field(..., description="Total unique vehicles seen")
    active_vehicles: int = Field(
        0, description="Vehicles currently active (isDriving='maybe')"
    )
    earliest: str | None = Field(None, description="Earliest position timestamp")
    latest: str | None = Field(None, description="Latest position timestamp")
    db_size_bytes: int | None = Field(None, description="Database file size in bytes")


class SignupRequest(BaseModel):
    email: str = Field(..., description="Email address", min_length=3, max_length=320)
    notify_plow: bool = Field(False, description="Notify when plow visits street")
    notify_projects: bool = Field(False, description="Notify about other projects")
    notify_siliconharbour: bool = Field(
        False, description="Sign up for Silicon Harbour newsletter"
    )
    note: str | None = Field(
        None, description="Optional note from user", max_length=2000
    )
