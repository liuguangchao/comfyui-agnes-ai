"""
Agnes Text-to-Video Node
========================
Generate videos from text descriptions using Agnes AI video generation models.
Uses async API with polling - can take several minutes to complete.

Supports quality (1K/2K) and aspect ratio selection.

Output: Saves MP4 to ComfyUI's output/agnes_videos/ directory so users can
preview and download from the web UI.
"""

import os
from typing import Tuple

from ..api import (
    AgnesClient,
    get_api_key,
    VIDEO_MODEL,
    AVAILABLE_VIDEO_MODELS,
    DEFAULT_VIDEO_FRAMES,
    DEFAULT_VIDEO_FPS,
)

# Quality → short-side pixels
QUALITY_MAP = {
    "1K": 1024,
    "2K": 2048,
}

# Supported aspect ratios (width:height)
ASPECT_RATIOS = [
    "1:1",
    "2:3",
    "3:4",
    "4:5",
    "9:16",
    "9:21",
    "3:2",
    "4:3",
    "5:4",
    "16:9",
    "21:9",
]

# Try to get ComfyUI's output directory (available inside ComfyUI runtime).
_COMFYUI_OUTPUT_DIR = None


def compute_size(quality: str, aspect_ratio: str) -> str:
    """
    Compute a WxH pixel size string from quality level and aspect ratio.
    """
    base = QUALITY_MAP.get(quality, 1024)
    w_ratio, h_ratio = map(int, aspect_ratio.split(":"))

    if w_ratio >= h_ratio:
        height = base
        width = base * w_ratio // h_ratio
    else:
        width = base
        height = base * h_ratio // w_ratio

    width = max(64, (width // 8) * 8)
    height = max(64, (height // 8) * 8)

    return f"{width}x{height}"


def _get_output_dir() -> str:
    """Get ComfyUI's output directory for saving video files."""
    global _COMFYUI_OUTPUT_DIR
    if _COMFYUI_OUTPUT_DIR is not None:
        return _COMFYUI_OUTPUT_DIR

    try:
        from folder_paths import get_output_directory
        base = get_output_directory()
    except ImportError:
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

    _COMFYUI_OUTPUT_DIR = os.path.join(base, "agnes_videos")
    return _COMFYUI_OUTPUT_DIR


class AgnesTextToVideo:
    """Agnes AI Text-to-Video node for ComfyUI."""

    CATEGORY = "Agnes AI"
    RETURN_TYPES = ("STRING", "STRING", "STRING",)
    RETURN_NAMES = ("video_path", "filename", "resolution",)
    FUNCTION = "generate"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "placeholder": "sk-...",
                    "tooltip": "Your Agnes AI API key",
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "A cinematic drone shot flying over a misty forest at sunrise...",
                    "tooltip": "Text description of the video to generate",
                }),
                "model": (AVAILABLE_VIDEO_MODELS, {
                    "default": VIDEO_MODEL,
                    "tooltip": "Video generation model",
                }),
                "quality": (["1K", "2K"], {
                    "default": "1K",
                    "tooltip": "Video quality / short-side resolution. 1K=1024px, 2K=2048px",
                }),
                "aspect_ratio": (ASPECT_RATIOS, {
                    "default": "16:9",
                    "tooltip": "Output aspect ratio (width:height). E.g. 16:9 for widescreen, 9:16 for portrait",
                }),
                "num_frames": ("INT", {
                    "default": DEFAULT_VIDEO_FRAMES,
                    "min": 9,
                    "max": 441,
                    "step": 8,
                    "tooltip": "Number of frames (must be 8n+1). 121=~5s @24fps, 241=~10s",
                }),
                "frame_rate": ("INT", {
                    "default": DEFAULT_VIDEO_FPS,
                    "min": 8,
                    "max": 60,
                    "step": 1,
                    "tooltip": "Frame rate in fps",
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 2147483647,
                    "step": 1,
                    "tooltip": "Random seed (0 = random). Set to reuse for reproducible results.",
                }),
                "max_wait_seconds": ("INT", {
                    "default": 600,
                    "min": 60,
                    "max": 3600,
                    "step": 30,
                    "tooltip": "Maximum time to wait for video generation (in seconds)",
                }),
            },
        }

    def generate(
        self,
        api_key: str,
        prompt: str,
        model: str = VIDEO_MODEL,
        quality: str = "1K",
        aspect_ratio: str = "16:9",
        num_frames: int = DEFAULT_VIDEO_FRAMES,
        frame_rate: int = DEFAULT_VIDEO_FPS,
        seed: int = 0,
        max_wait_seconds: int = 600,
    ) -> Tuple[str, str, str]:
        if not prompt.strip():
            return ("[Error: Prompt is empty]", "", "")

        # Runtime fallback: try config file if widget value is empty
        if not api_key.strip():
            api_key = get_api_key()
        if not api_key.strip():
            return ("[Error: API key is required]", "", "")

        size = compute_size(quality, aspect_ratio)
        output_dir = _get_output_dir()

        try:
            client = AgnesClient(api_key)
            video_path = client.generate_video(
                prompt=prompt.strip(),
                mode="text2video",
                model=model,
                num_frames=num_frames,
                frame_rate=frame_rate,
                seed=seed if seed > 0 else None,
                size=size,
                max_wait=max_wait_seconds,
                output_dir=output_dir,
            )

            if video_path:
                filename = os.path.basename(video_path)
                return (video_path, filename, size)
            return ("[Error: No video returned]", "", size)

        except Exception as e:
            return (f"[Error] {str(e)}", "", size)
