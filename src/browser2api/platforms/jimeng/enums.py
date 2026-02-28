"""Jimeng platform-specific enums and configuration mappings (image + video)."""

from enum import Enum


class JimengModel(str, Enum):
    """Available Jimeng image generation models.

    Values are internal API model identifiers used in the generation request.
    """
    JIMENG_3_0 = "high_aes_general_v30l:general_v3.0_18b"
    JIMENG_3_1 = "high_aes_general_v30l_art_fangzhou:general_v3.0_18b"
    JIMENG_4_0 = "high_aes_general_v40"
    JIMENG_4_1 = "high_aes_general_v41"
    JIMENG_4_5 = "high_aes_general_v40l"
    JIMENG_4_6 = "high_aes_general_v42"
    JIMENG_5_0 = "high_aes_general_v50"


class JimengRatio(str, Enum):
    """Aspect ratio options.

    Values are the display strings shown in the UI ratio selector.
    """
    SMART = "智能"
    RATIO_1_1 = "1:1"
    RATIO_3_4 = "3:4"
    RATIO_4_3 = "4:3"
    RATIO_16_9 = "16:9"
    RATIO_9_16 = "9:16"
    RATIO_2_3 = "2:3"
    RATIO_3_2 = "3:2"
    RATIO_21_9 = "21:9"


class JimengResolution(str, Enum):
    """Resolution/quality tiers.

    Values are the display strings shown in the UI resolution selector.
    """
    RES_2K = "高清 2K"
    RES_4K = "超清 4K"


# Model enum -> UI dropdown label text for matching.
# The dropdown options have labels like "图片5.0 Lite", "图片4.6", "图片 4.5", etc.
# We match by the version substring (e.g. "3.0", "4.5", "5.0").
MODEL_UI_LABELS: dict[JimengModel, str] = {
    JimengModel.JIMENG_3_0: "3.0",
    JimengModel.JIMENG_3_1: "3.1",
    JimengModel.JIMENG_4_0: "4.0",
    JimengModel.JIMENG_4_1: "4.1",
    JimengModel.JIMENG_4_5: "4.5",
    JimengModel.JIMENG_4_6: "4.6",
    JimengModel.JIMENG_5_0: "5.0",
}


# User-friendly name -> enum member mapping for CLI usage.
MODEL_NAMES: dict[str, JimengModel] = {
    "jimeng-3.0": JimengModel.JIMENG_3_0,
    "jimeng-3.1": JimengModel.JIMENG_3_1,
    "jimeng-4.0": JimengModel.JIMENG_4_0,
    "jimeng-4.1": JimengModel.JIMENG_4_1,
    "jimeng-4.5": JimengModel.JIMENG_4_5,
    "jimeng-4.6": JimengModel.JIMENG_4_6,
    "jimeng-5.0": JimengModel.JIMENG_5_0,
}


class JimengVideoModel(str, Enum):
    """Available Jimeng video generation models.

    Values are the internal API model_req_key / root_model sent in draft_content.
    """
    SEEDANCE_2_0_FAST = "dreamina_seedance_40"
    SEEDANCE_2_0 = "dreamina_seedance_40_pro"
    VIDEO_3_5_PRO = "dreamina_ic_generate_video_model_vgfm_3.5_pro"
    VIDEO_3_0_PRO = "dreamina_ic_generate_video_model_vgfm_3.0_pro"
    VIDEO_3_0_FAST = "dreamina_ic_generate_video_model_vgfm_3.0_fast"
    VIDEO_3_0 = "dreamina_ic_generate_video_model_vgfm_3.0"


class JimengVideoDuration(int, Enum):
    """Video duration in milliseconds (sent in API as duration_ms)."""
    FIVE = 5000
    TEN = 10000


class JimengVideoResolution(str, Enum):
    """Video resolution tiers."""
    RES_720P = "720p"
    RES_1080P = "1080p"


# Video model -> commerce benefit_type for credit deduction.
VIDEO_MODEL_BENEFIT_TYPE: dict[JimengVideoModel, str] = {
    JimengVideoModel.SEEDANCE_2_0_FAST: "dreamina_seedance_20_fast",
    JimengVideoModel.SEEDANCE_2_0: "dreamina_video_seedance_20_pro",
    JimengVideoModel.VIDEO_3_5_PRO: "dreamina_video_seedance_15_pro",
    JimengVideoModel.VIDEO_3_0_PRO: "basic_video_operation_vgfm_v_three",
    JimengVideoModel.VIDEO_3_0_FAST: "basic_video_operation_vgfm_v_three",
    JimengVideoModel.VIDEO_3_0: "basic_video_operation_vgfm_v_three",
}


# User-friendly name -> enum member mapping for CLI usage.
VIDEO_MODEL_NAMES: dict[str, JimengVideoModel] = {
    "seedance-2.0-fast": JimengVideoModel.SEEDANCE_2_0_FAST,
    "seedance-2.0": JimengVideoModel.SEEDANCE_2_0,
    "video-3.5-pro": JimengVideoModel.VIDEO_3_5_PRO,
    "video-3.0-pro": JimengVideoModel.VIDEO_3_0_PRO,
    "video-3.0-fast": JimengVideoModel.VIDEO_3_0_FAST,
    "video-3.0": JimengVideoModel.VIDEO_3_0,
}


# User-friendly display names.
VIDEO_MODEL_DISPLAY: dict[JimengVideoModel, str] = {
    JimengVideoModel.SEEDANCE_2_0_FAST: "Seedance 2.0 Fast",
    JimengVideoModel.SEEDANCE_2_0: "Seedance 2.0",
    JimengVideoModel.VIDEO_3_5_PRO: "视频 3.5 Pro",
    JimengVideoModel.VIDEO_3_0_PRO: "视频 3.0 Pro",
    JimengVideoModel.VIDEO_3_0_FAST: "视频 3.0 Fast",
    JimengVideoModel.VIDEO_3_0: "视频 3.0",
}


# Video model enum -> UI dropdown label substring for matching.
VIDEO_MODEL_UI_LABELS: dict[JimengVideoModel, str] = {
    JimengVideoModel.SEEDANCE_2_0_FAST: "Seedance 2.0 Fast",
    JimengVideoModel.SEEDANCE_2_0: "Seedance 2.0",
    JimengVideoModel.VIDEO_3_5_PRO: "3.5 Pro",
    JimengVideoModel.VIDEO_3_0_PRO: "3.0 Pro",
    JimengVideoModel.VIDEO_3_0_FAST: "3.0 Fast",
    JimengVideoModel.VIDEO_3_0: "3.0",
}
