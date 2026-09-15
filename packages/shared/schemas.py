from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CauseType(StrEnum):
    stalled_vehicle = "stalled_vehicle"
    collision = "collision"
    vehicle_blocking_lane = "vehicle_blocking_lane"
    illegal_parking_or_stopping = "illegal_parking_or_stopping"
    pedestrian_obstruction = "pedestrian_obstruction"
    animal_obstruction = "animal_obstruction"
    road_debris = "road_debris"
    roadwork_or_barricade = "roadwork_or_barricade"
    pothole_or_road_damage = "pothole_or_road_damage"
    flooded_road = "flooded_road"
    traffic_signal_failure = "traffic_signal_failure"
    unknown = "unknown"


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Region(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    polygon: list[Point] = Field(min_length=3, max_length=32)
    direction: tuple[float, float]
    meters_per_pixel: float | None = Field(default=None, gt=0, le=10)

    @model_validator(mode="after")
    def valid_geometry(self) -> "Region":
        import math

        import cv2
        import numpy as np

        pts = np.array([[p.x, p.y] for p in self.polygon], dtype=np.float32)
        if cv2.contourArea(pts) < 0.001 or not cv2.isContourConvex(pts):
            raise ValueError("Use a convex, nonzero-area road polygon")
        if not all(math.isfinite(v) for v in self.direction) or math.hypot(*self.direction) < 0.01:
            raise ValueError("Traffic direction must be a nonzero finite vector")
        return self


class CameraConfig(BaseModel):
    regions: list[Region] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def unique_ids(self) -> "CameraConfig":
        if len({r.id for r in self.regions}) != len(self.regions):
            raise ValueError("Region IDs must be unique")
        return self


class Observation(BaseModel):
    track_id: int
    object_type: str
    bbox: tuple[float, float, float, float]
    confidence: float = Field(ge=0, le=1)
    timestamp: float
    frame_index: int
    region: str = "whole_road"
    speed: float = 0
    stationary_duration: float = 0
    movement: str = "moving_normally"
    kmh: float | None = None


class Congestion(BaseModel):
    detected: bool = False
    start_seconds: float | None = None
    end_seconds: float | None = None
    region: str | None = None
    severity: float = Field(default=0, ge=0, le=1)
    peak_queue_size: int = 0


class Candidate(BaseModel):
    candidate_track_id: int
    cause_type: CauseType
    object_type: str
    cause_confidence: float = Field(ge=0, le=1)
    first_relevant_timestamp: float
    evidence_scores: dict[str, float]
    explanation: str


class Cause(BaseModel):
    type: CauseType = CauseType.unknown
    confidence: float = Field(default=0, ge=0, le=1)
    suspected_track_id: int | None = None
    object_type: str | None = None
    first_relevant_timestamp: float | None = None
    explanation: str = "No reliable cause could be identified."
    evidence_scores: dict[str, float] = Field(default_factory=dict)


class Plate(BaseModel):
    status: Literal["recognized", "unreadable", "not_applicable"] = "unreadable"
    text: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_asset_id: str | None = None
    raw_readings: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def recognized_has_text(self) -> "Plate":
        if self.status == "recognized" and not self.text:
            raise ValueError("Recognized plate needs text")
        if self.status != "recognized" and self.text is not None:
            raise ValueError("Unreliable plate must be null")
        return self


class Asset(BaseModel):
    id: str
    asset_type: str
    url: str
    timestamp: float
    track_id: int | None = None
    quality_score: float = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Report(BaseModel):
    schema_version: str = "1.0"
    analysis_id: str
    incident_id: str
    video: dict[str, Any]
    congestion: Congestion
    cause: Cause
    license_plate: Plate = Field(default_factory=Plate)
    fallback_subject_frame: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Asset] = Field(default_factory=list)
    alternative_candidates: list[Candidate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    review_status: str = "pending"
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    tracks: list[dict[str, Any]] = Field(default_factory=list)
    stage_timings: dict[str, float] = Field(default_factory=dict)


class ReviewInput(BaseModel):
    action: Literal["confirmed", "rejected", "corrected"]
    corrected_cause: CauseType | None = None
    corrected_plate: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9 -]*$")
    corrected_track: int | None = None
    notes: str = Field(default="", max_length=4000)


class AnalyzeInput(BaseModel):
    camera_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    redact: bool = False
