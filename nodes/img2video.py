"""
Agnes Image-to-Video Node
=========================
Generate videos from still images using Agnes AI video generation models.
Supports multi-image input for keyframe-based animation.
Uses async API with polling - can take several minutes.

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
    tensor_to_pil,
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
    """Compute a WxH pixel size string from quality level and aspect ratio."""
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


# Detect video output type (priority: comfy_api VIDEO > VHS > STRING).
_VIDEO_OUTPUT_TYPE = "STRING"
_VIDEO_MODE = "string"  # "comfy_api" | "vhs" | "string"

# 1. Try native VIDEO type from comfy_api (ships with ComfyUI v1.7+)
try:
    from comfy_api.latest import InputImpl as _ApiInput
    if hasattr(_ApiInput, "VideoFromFile"):
        _VIDEO_OUTPUT_TYPE = "VIDEO"
        _VIDEO_MODE = "comfy_api"
except Exception:
    pass

# 2. Fallback to VHS_VIDEOINFO
if _VIDEO_MODE == "string":
    try:
        import nodes as _comfy_nodes
        if hasattr(_comfy_nodes, "NODE_CLASS_MAPPINGS"):
            if "VHS_VIDEOINFO" in str(_comfy_nodes.NODE_CLASS_MAPPINGS):
                _VIDEO_OUTPUT_TYPE = "VHS_VIDEOINFO"
                _VIDEO_MODE = "vhs"
    except Exception:
        pass


class AgnesImageToVideo:
    """Agnes AI Image-to-Video node for ComfyUI."""

    CATEGORY = "Agnes AI2"
    RETURN_TYPES = (_VIDEO_OUTPUT_TYPE, "STRING",)
    RETURN_NAMES = ("video", "resolution",)
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
                "image1": ("IMAGE", {
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
                "quality": (["1K", "2K"], {
                    "default": "1K",
                    "tooltip": "Video quality / short-side resolution. 1K=1024px, 2K=2048px",
                }),
                "aspect_ratio": (ASPECT_RATIOS, {
                    "default": "9:16",
                    "tooltip": "Output aspect ratio (width:height). E.g. 16:9 for widescreen, 9:16 for portrait",
                }),
                "time_seconds": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 10,
                    "step": 1,
                    "tooltip": "时长秒",
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
                "image2": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }),
                "image3": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }),
                "image4": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }), 
                "image5": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }), 
                "image6": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }), 
                "image7": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }), 
                "image8": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }), 
                "image9": ("IMAGE", {
                    "tooltip": "Optional end frame for keyframe-based animation (image -> image transition)",
                }), 
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "负向提示词",
                    "tooltip": "负向提示词",
                }),
                "num_inference_steps": ("INT", {
                    "default": 25,
                    "min": 1,
                    "max": 50,
                    "step": 1,
                    "tooltip": "Number of inference steps for image-to-video generation",
                }),
            },
        }

    def generate(
        self,
        api_key: str,
        image1,
        prompt: str,
        model: str = VIDEO_MODEL,
        quality: str = "1K",
        aspect_ratio: str = "9:16",
        time_seconds: int = 5,
        frame_rate: int = DEFAULT_VIDEO_FPS,
        seed: int = 0,
        max_wait_seconds: int = 600,
        image2=None,
        image3=None,
        image4=None,
        image5=None,
        image6=None,
        image7=None,
        image8=None,
        image9=None,
        negative_prompt=None,
        num_inference_steps: int = 25,
    ) -> Tuple:
        # Runtime fallback: try config file if widget value is empty
        if not api_key.strip():
            api_key = get_api_key()
        if not api_key.strip():
            return _error("API key is required")
        if not prompt.strip():
            return _error("Prompt is empty")

        size = compute_size(quality, aspect_ratio)
        output_dir = _get_output_dir()

        try:
            # Collect reference images
            ref_imgs = [tensor_to_pil(image1)]
            if image2 is not None:
                ref_imgs.append(tensor_to_pil(image2))
            if image3 is not None:
                ref_imgs.append(tensor_to_pil(image3))
            if image4 is not None:
                ref_imgs.append(tensor_to_pil(image4))
            if image5 is not None:
                ref_imgs.append(tensor_to_pil(image5))
            if image6 is not None:
                ref_imgs.append(tensor_to_pil(image6))
            if image7 is not None:
                ref_imgs.append(tensor_to_pil(image7))
            if image8 is not None:
                ref_imgs.append(tensor_to_pil(image8))
            if image9 is not None:
                ref_imgs.append(tensor_to_pil(image9))

            client = AgnesClient(api_key)
            video_path = client.generate_video(
                prompt=prompt.strip(),
                mode="img2video",
                reference_images=ref_imgs,
                model=model,
                num_frames=time_seconds * frame_rate+1,
                frame_rate=frame_rate,
                seed=seed if seed > 0 else None,
                size=size,
                max_wait=max_wait_seconds,
                output_dir=output_dir,
                num_inference_steps=num_inference_steps,
                negative_prompt=negative_prompt.strip()
,
            )

            if video_path:
                return _make_result(video_path, size)
            return _error("No video returned", size)

        except Exception as e:
            return _error(str(e), size)


# ---- Result builders (shared) ----

def _make_result(video_path: str, size: str) -> Tuple:
    """Build a (video_output, resolution) tuple based on available output type."""
    filename = os.path.basename(video_path)

    if _VIDEO_MODE == "comfy_api":
        video_output = _ApiInput.VideoFromFile(video_path)
        return (video_output, size)

    if _VIDEO_MODE == "vhs":
        return ({"filename": filename, "subfolder": "agnes_videos", "type": "output"}, size)

    return (video_path, size)


def _error(msg: str, size: str = "") -> Tuple:
    """Build an error. Raises in comfy_api VIDEO mode (string would crash SaveVideo)."""
    text = f"[Error] {msg}"
    if _VIDEO_MODE == "comfy_api":
        raise RuntimeError(text)
    if _VIDEO_MODE == "vhs":
        return ({"filename": "", "subfolder": "", "type": "output"}, text)
    return (text, text) if not size else (text, size)
