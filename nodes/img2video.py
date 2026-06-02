"""
Agnes Image-to-Video Node
=========================
Generate videos from still images using Agnes AI video generation models.
Supports multi-image input for keyframe-based animation.
Uses async API with polling - can take several minutes.

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
    tensor_to_pil,
)

# Try to get ComfyUI's output directory (available inside ComfyUI runtime).
_COMFYUI_OUTPUT_DIR = None


def _get_output_dir() -> str:
    """Get ComfyUI's output directory for saving video files."""
    global _COMFYUI_OUTPUT_DIR
    if _COMFYUI_OUTPUT_DIR is not None:
        return _COMFYUI_OUTPUT_DIR

    # Try the standard ComfyUI way first
    try:
        from folder_paths import get_output_directory
        base = get_output_directory()
    except ImportError:
        # Fallback: use plugin-relative or temp
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

    _COMFYUI_OUTPUT_DIR = os.path.join(base, "agnes_videos")
    return _COMFYUI_OUTPUT_DIR


class AgnesImageToVideo:
    """Agnes AI Image-to-Video node for ComfyUI."""

    CATEGORY = "Agnes AI"
    RETURN_TYPES = ("STRING", "STRING",)
    RETURN_NAMES = ("video_path", "filename",)
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
                "image": ("IMAGE", {
                    "tooltip": "Primary input image to animate",
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Smooth camera pan with gentle motion...",
                    "tooltip": "Description of the desired animation/motion",
                }),
                "model": (AVAILABLE_VIDEO_MODELS, {
                    "default": VIDEO_MODEL,
                    "tooltip": "Video generation model",
                }),
                "num_frames": ("INT", {
                    "default": DEFAULT_VIDEO_FRAMES,
                    "min": 9,
                    "max": 441,
                    "step": 8,
                    "tooltip": "Number of frames (must be 8n+1). 121=~5s @24fps",
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
            "optional": {
                "end_frame_image": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }),
            },
        }

    def generate(
        self,
        api_key: str,
        image,
        prompt: str,
        model: str = VIDEO_MODEL,
        num_frames: int = DEFAULT_VIDEO_FRAMES,
        frame_rate: int = DEFAULT_VIDEO_FPS,
        seed: int = 0,
        max_wait_seconds: int = 600,
        end_frame_image=None,
    ) -> Tuple[str, str]:
        # Runtime fallback: try config file if widget value is empty
        if not api_key.strip():
            api_key = get_api_key()
        if not api_key.strip():
            return ("[Error: API key is required]", "")
        if not prompt.strip():
            return ("[Error: Prompt is empty]", "")

        output_dir = _get_output_dir()

        try:
            # Collect reference images
            ref_imgs = [tensor_to_pil(image)]
            if end_frame_image is not None:
                ref_imgs.append(tensor_to_pil(end_frame_image))

            client = AgnesClient(api_key)
            video_path = client.generate_video(
                prompt=prompt.strip(),
                mode="img2video",
                reference_images=ref_imgs,
                model=model,
                num_frames=num_frames,
                frame_rate=frame_rate,
                seed=seed if seed > 0 else None,
                max_wait=max_wait_seconds,
                output_dir=output_dir,
            )

            if video_path:
                filename = os.path.basename(video_path)
                return (video_path, filename)
            return ("[Error: No video returned]", "")

        except Exception as e:
            return (f"[Error] {str(e)}", "")
