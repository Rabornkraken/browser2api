"""Google Flow platform-specific enums and configuration mappings."""

from enum import Enum


class FlowModel(str, Enum):
    """Available Google Flow image generation models.

    Values are identifiers used internally; UI matching uses MODEL_UI_LABELS.
    """
    NANO_BANANA_PRO = "nano_banana_pro"
    NANO_BANANA_2 = "nano_banana_2"
    IMAGEN_4 = "imagen_4"


class FlowOrientation(str, Enum):
    """Image orientation / aspect ratio."""
    LANDSCAPE = "landscape"   # 16:9
    PORTRAIT = "portrait"     # 9:16


class FlowCount(int, Enum):
    """Number of images to generate per request."""
    X1 = 1
    X2 = 2
    X3 = 3
    X4 = 4


class FlowVideoModel(str, Enum):
    """Available Google Flow video generation models."""
    VEO_3_1_FAST = "veo_3.1_fast"
    VEO_3_1_QUALITY = "veo_3.1_quality"
    VEO_2_FAST = "veo_2_fast"
    VEO_2_QUALITY = "veo_2_quality"


class FlowVideoMode(str, Enum):
    """Video creation mode."""
    FRAMES = "frames"
    INGREDIENTS = "ingredients"


# ── Image model mappings ──

# Model enum -> UI dropdown label text for matching.
MODEL_UI_LABELS: dict[FlowModel, str] = {
    FlowModel.NANO_BANANA_PRO: "Nano Banana Pro",
    FlowModel.NANO_BANANA_2: "Nano Banana 2",
    FlowModel.IMAGEN_4: "Imagen 4",
}

# User-friendly name -> enum member mapping for CLI usage.
MODEL_NAMES: dict[str, FlowModel] = {
    "nano-banana-pro": FlowModel.NANO_BANANA_PRO,
    "nano-banana-2": FlowModel.NANO_BANANA_2,
    "imagen-4": FlowModel.IMAGEN_4,
}

# ── Orientation mappings ──

ORIENTATION_UI_LABELS: dict[FlowOrientation, str] = {
    FlowOrientation.LANDSCAPE: "Landscape",
    FlowOrientation.PORTRAIT: "Portrait",
}

# ── Count mappings ──

COUNT_UI_LABELS: dict[FlowCount, str] = {
    FlowCount.X1: "x1",
    FlowCount.X2: "x2",
    FlowCount.X3: "x3",
    FlowCount.X4: "x4",
}

# ── Video model mappings ──

VIDEO_MODEL_UI_LABELS: dict[FlowVideoModel, str] = {
    FlowVideoModel.VEO_3_1_FAST: "Veo 3.1 - Fast",
    FlowVideoModel.VEO_3_1_QUALITY: "Veo 3.1 - Quality",
    FlowVideoModel.VEO_2_FAST: "Veo 2 - Fast",
    FlowVideoModel.VEO_2_QUALITY: "Veo 2 - Quality",
}

VIDEO_MODEL_NAMES: dict[str, FlowVideoModel] = {
    "veo-3.1-fast": FlowVideoModel.VEO_3_1_FAST,
    "veo-3.1-quality": FlowVideoModel.VEO_3_1_QUALITY,
    "veo-2-fast": FlowVideoModel.VEO_2_FAST,
    "veo-2-quality": FlowVideoModel.VEO_2_QUALITY,
}
