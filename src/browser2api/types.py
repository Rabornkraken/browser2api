"""Data types for browser-to-API image and video generation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Platform(str, Enum):
    """Supported image generation platforms."""
    JIMENG = "jimeng"    # 即梦AI (ByteDance)
    FLOW = "flow"        # Google Flow (labs.google)


class GenerationStatus(str, Enum):
    """Status of an image generation request."""
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class GeneratedImage:
    """A single generated image."""
    url: str
    local_path: str | None = None
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    is_highres: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "local_path": self.local_path,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "is_highres": self.is_highres,
        }


@dataclass
class GenerationResult:
    """Result of an image generation request."""
    platform: Platform
    prompt: str
    images: list[GeneratedImage] = field(default_factory=list)
    status: GenerationStatus = GenerationStatus.PENDING
    error: str | None = None
    duration_ms: int = 0
    model: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "prompt": self.prompt,
            "images": [img.to_dict() for img in self.images],
            "status": self.status.value,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class GeneratedVideo:
    """A single generated video."""
    url: str
    local_path: str | None = None
    filename: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "local_path": self.local_path,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration_seconds,
            "size_bytes": self.size_bytes,
        }


@dataclass
class VideoGenerationResult:
    """Result of a video generation request."""
    platform: Platform
    prompt: str
    video: GeneratedVideo | None = None
    status: GenerationStatus = GenerationStatus.PENDING
    error: str | None = None
    duration_ms: int = 0
    model: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "prompt": self.prompt,
            "video": self.video.to_dict() if self.video else None,
            "status": self.status.value,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
        }
