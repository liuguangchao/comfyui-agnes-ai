"""
Agnes Image-to-Image Node
=========================
Edit or transform images using Agnes AI image generation models.
Supports multi-image input - multiple reference images can be provided
to guide the generation process.
Supports quality (1K/2K/4K) and aspect ratio selection.
"""

import torch

from ..api import (
    AgnesClient,
    get_api_key,
    IMAGE_MODEL,
    AVAILABLE_IMAGE_MODELS,
    tensor_to_pil,
    pil_to_tensor,
)

# Quality → short-side pixels
QUALITY_MAP = {
    "1K": 1024,
    "2K": 2048,
    "4K": 4096,
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


def compute_size(quality: str, aspect_ratio: str) -> str:
    """
    Compute a WxH pixel size string from quality level and aspect ratio.

    quality: "1K" / "2K" / "4K" — determines the short-side pixel count.
    aspect_ratio: "W:H" — e.g. "16:9", "2:3".

    Returns: e.g. "1792x1024"
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


class AgnesImageToImage:
    """Agnes AI Image-to-Image (Image Editing) node for ComfyUI."""

    CATEGORY = "Agnes AI2"
    RETURN_TYPES = ("IMAGE", "STRING",)
    RETURN_NAMES = ("images", "resolution",)
    FUNCTION = "edit"

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
                    "tooltip": "Primary reference image for editing",
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Make it look like a watercolor painting...",
                    "tooltip": "Description of the desired transformation",
                }),
                "model": (AVAILABLE_IMAGE_MODELS, {
                    "default": IMAGE_MODEL,
                    "tooltip": "Image generation model",
                }),
                "quality": (["1K", "2K", "4K"], {
                    "default": "1K",
                    "tooltip": "Image quality / short-side resolution. 1K=1024px, 2K=2048px, 4K=4096px",
                }),
                "aspect_ratio": (ASPECT_RATIOS, {
                    "default": "1:1",
                    "tooltip": "Output aspect ratio (width:height). E.g. 16:9 for widescreen, 2:3 for portrait",
                }),
                "strength": ("FLOAT", {
                    "default": 0.75,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "How much to change from the original (higher = more creative freedom)",
                }),
                "n": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 4,
                    "step": 1,
                    "tooltip": "Number of images to generate",
                }),
            },
            "optional": {
                "reference_image_2": ("IMAGE", {
                    "tooltip": "Additional reference image (multi-image input)",
                }),
                "reference_image_3": ("IMAGE", {
                    "tooltip": "Additional reference image (multi-image input)",
                }),
                "reference_image_4": ("IMAGE", {
                    "tooltip": "Additional reference image (multi-image input)",
                }),
            },
        }

    def edit(
        self,
        api_key: str,
        image,
        prompt: str,
        model: str = IMAGE_MODEL,
        quality: str = "1K",
        aspect_ratio: str = "1:1",
        strength: float = 0.75,
        n: int = 1,
        reference_image_2=None,
        reference_image_3=None,
        reference_image_4=None,
    ):
        # Runtime fallback: try config file if widget value is empty
        if not api_key.strip():
            api_key = get_api_key()
        if not api_key.strip():
            raise ValueError("API key is required.")
        if not prompt.strip():
            raise ValueError("Prompt is empty.")

        size = compute_size(quality, aspect_ratio)

        # Collect all reference images
        ref_imgs = [tensor_to_pil(image)]

        for ref in [reference_image_2, reference_image_3, reference_image_4]:
            if ref is not None:
                ref_imgs.append(tensor_to_pil(ref))

        # Inject strength into prompt if needed
        full_prompt = prompt.strip()
        if strength < 1.0:
            full_prompt = (
                f"{full_prompt}\n"
                f"[Guidance: transformation strength = {strength:.0%}. "
                f"Lower strength means stay closer to the original.]"
            )

        client = AgnesClient(api_key)
        pil_images = client.generate_image(
            prompt=full_prompt,
            mode="img2img",
            reference_images=ref_imgs,
            size=size,
            n=n,
            model=model,
        )

        if not pil_images:
            raise RuntimeError("No images were generated. Check your inputs and try again.")

        # Convert to ComfyUI tensor batch
        tensors = [pil_to_tensor(img) for img in pil_images]
        batch = tensors[0] if len(tensors) == 1 else torch.cat(tensors, dim=0)

        return (batch, size)
