import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./storage/traffic.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("storage")
    model_path: str = "models/yolo11n.pt"
    device: str = "cpu"
    plate_model_path: str = "models/license_plate.pt"
    max_upload_mb: int = Field(default=250, ge=1, le=2048)
    max_duration_seconds: int = Field(default=600, ge=1, le=3600)
    max_pixels: int = 3840 * 2160
    inference_fps: float = Field(default=5, ge=0.5, le=30)
    retention_days: int = Field(default=7, ge=1, le=3650)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    ocr_enabled: bool = True
    model_download_allowed: bool = False
    analysis_config: Path = Path("config/analysis.json")
    rate_limit_per_minute: int = 120
    max_samples: int = Field(default=6000, ge=1, le=30000)
    max_observations: int = Field(default=200000, ge=100, le=1000000)


@lru_cache
def settings() -> Settings:
    return Settings()


def thresholds() -> dict[str, Any]:
    return json.loads(settings().analysis_config.read_text())
