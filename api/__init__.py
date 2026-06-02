"""
Agnes AI API Client
==================
Wrapper for all Agnes AI API endpoints.

Endpoints:
- Chat Completions:  POST /v1/chat/completions
- Image Generation:  POST /v1/images/generations
- Video Generation:  POST /v1/video/generations (async with polling)

Supported Models:
- agnes-2.0-flash        : LLM chat / vision
- agnes-image-2.1-flash  : Text-to-image, image-to-image
- agnes-video-v2.0      : Text-to-video, image-to-video
"""

import base64
import json
import os
import re
import time
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from PIL import Image

# torch / numpy are only needed inside ComfyUI (tensor conversions).
# Lazy-import them to allow the API module to be tested standalone.
_torch = None
_np = None

def _get_torch():
    global _torch
    if _torch is None:
        import torch as _t
        _torch = _t
    return _torch

def _get_np():
    global _np
    if _np is None:
        import numpy as _n
        _np = _n
    return _np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://apihub.agnes-ai.com/v1"

CHAT_MODEL = "agnes-2.0-flash"
IMAGE_MODEL = "agnes-image-2.1-flash"
VIDEO_MODEL = "agnes-video-v2"

DEFAULT_SIZE = "1024x1024"
DEFAULT_VIDEO_FRAMES = 121
DEFAULT_VIDEO_FPS = 24
VIDEO_TIMEOUT = 600  # video generation can take 2-5 minutes

AVAILABLE_CHAT_MODELS = [CHAT_MODEL]
AVAILABLE_IMAGE_MODELS = [IMAGE_MODEL]
AVAILABLE_VIDEO_MODELS = [VIDEO_MODEL]

MIME_MAP = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def tensor_to_pil(tensor) -> Image.Image:
    """
    Convert a ComfyUI IMAGE tensor [B, H, W, C] (float32, 0..1) to a PIL Image.
    Returns the first image in the batch.
    """
    np = _get_np()
    # Take first image: [H, W, C]
    img = tensor[0].cpu().numpy()
    img = (img * 255).astype(np.uint8)
    return Image.fromarray(img)


def pil_to_tensor(pil_img: Image.Image):
    """Convert a PIL Image to a ComfyUI IMAGE tensor [1, H, W, C] float32."""
    torch = _get_torch()
    np = _get_np()
    img = np.array(pil_img.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(img).unsqueeze(0)


def pil_to_base64_uri(pil_img: Image.Image, fmt: str = "png") -> str:
    """Convert a PIL Image to a base64 data URI string."""
    buf = BytesIO()
    pil_img.save(buf, format=fmt.upper())
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    mime = MIME_MAP.get(fmt.lower(), "image/png")
    return f"data:{mime};base64,{b64}"


def download_url_to_pil(url: str, timeout: int = 120) -> Optional[Image.Image]:
    """Download an image from a URL and return as PIL Image."""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception:
        pass
    return None


def download_url_to_bytes(url: str, timeout: int = 120) -> Optional[bytes]:
    """Download content from a URL and return raw bytes."""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

class AgnesClient:
    """Unified client for all Agnes AI API endpoints."""

    # HTTP statuses that trigger an automatic retry.
    _RETRY_STATUSES = {429, 500, 502, 503, 504, 524}
    _MAX_RETRIES = 3
    _RETRY_BASE_DELAY = 3  # seconds (exponential backoff: 3, 6, 12)

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------
    # Error helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_error(status_code: int, body_text: str, api_name: str = "API") -> str:
        """Parse an error response and return a clean, human-readable message."""
        text = body_text.strip() if body_text else ""

        # Cloudflare HTML error page
        if text.startswith("<!DOCTYPE") or text.startswith("<html"):
            # Try to extract Cloudflare error info
            title_match = re.search(r"<title>[^<]*?(\d{3}):\s*([^<]*)</title>", text)
            if title_match:
                code = title_match.group(1)
                desc = title_match.group(2)
            else:
                code = str(status_code)
                desc = "server error"

            # Map Cloudflare codes to Chinese messages
            cf_map = {
                "520": "服务器返回未知错误",
                "521": "服务器已宕机",
                "522": "连接超时（服务器未响应）",
                "523": "服务器不可达",
                "524": "服务器处理超时（任务过重）",
                "525": "SSL 握手失败",
                "526": "SSL 证书无效",
                "530": "服务器错误",
            }

            extra = cf_map.get(code, desc)
            return (
                f"[{api_name} 错误] 服务器 {extra} (HTTP {status_code})。\n"
                f"原因：Agnes AI 服务器繁忙或请求处理超时。\n"
                f"建议：稍等 1-2 分钟后重试。"
            )

        # JSON error response
        try:
            if text:
                error_data = json.loads(text)
                error_msg = error_data.get("error", {}).get("message", "")
                if not error_msg and isinstance(error_data.get("error"), str):
                    error_msg = error_data["error"]
                if error_msg:
                    return f"[{api_name} 错误] {error_msg} (HTTP {status_code})"
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fallback: truncate long responses
        if len(text) > 300:
            text = text[:300] + "..."
        return f"[{api_name} 错误] HTTP {status_code}: {text}" if text else f"[{api_name} 错误] HTTP {status_code}"

    def _request_with_retry(self, method: str, url: str, api_name: str,
                            json_payload: dict = None, timeout: int = 300) -> requests.Response:
        """Make an HTTP request with automatic retry on transient server errors."""
        last_error = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                if method == "POST":
                    resp = self.session.post(url, json=json_payload, timeout=timeout)
                else:
                    resp = self.session.get(url, timeout=timeout)

                if resp.status_code == 200:
                    return resp

                if resp.status_code in self._RETRY_STATUSES and attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    last_error = (resp.status_code, resp.text)
                    time.sleep(delay)
                    continue

                # Not retryable or last attempt → raise
                raise RuntimeError(self._clean_error(resp.status_code, resp.text, api_name))

            except requests.exceptions.Timeout:
                if attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"[{api_name} 错误] 请求超时 (>{timeout}秒)。\n"
                    f"建议：Agnes 服务器可能繁忙，请稍后重试。"
                )
            except requests.exceptions.ConnectionError:
                if attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"[{api_name} 错误] 无法连接到 Agnes 服务器。\n"
                    f"建议：请检查网络连接或访问 https://platform.agnes-ai.com/ 确认服务状态。"
                )

        # Should not reach here, but handle gracefully
        if last_error:
            raise RuntimeError(self._clean_error(last_error[0], last_error[1], api_name))
        raise RuntimeError(f"[{api_name} 错误] 请求失败（已重试 {self._MAX_RETRIES} 次）")

    # ------------------------------------------------------------------
    # Chat / LLM
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str = CHAT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> str:
        """Call the chat completions endpoint."""
        url = f"{BASE_URL}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        resp = self._request_with_retry("POST", url, "Chat", json_payload=payload)

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise RuntimeError(f"[Chat 错误] 意外的响应格式: {data}")

    # ------------------------------------------------------------------
    # Image Generation
    # ------------------------------------------------------------------

    def generate_image(
        self,
        prompt: str,
        mode: str = "text2img",
        reference_images: Optional[List[Image.Image]] = None,
        size: str = DEFAULT_SIZE,
        n: int = 1,
        model: str = IMAGE_MODEL,
    ) -> List[Image.Image]:
        """Generate images via the Agnes image generation API."""
        url = f"{BASE_URL}/images/generations"
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": n,
        }

        if mode == "img2img" and reference_images:
            image_uris = [pil_to_base64_uri(img) for img in reference_images]
            payload["extra_body"] = {
                "image": image_uris,
                "response_format": "url",
            }

        resp = self._request_with_retry("POST", url, "Image", json_payload=payload)

        data = resp.json()
        images = []
        for item in data.get("data", []):
            image_url = item.get("url")
            if image_url:
                pil_img = download_url_to_pil(image_url)
                if pil_img:
                    images.append(pil_img)

        if not images:
            raise RuntimeError("[Image 错误] 服务器未返回任何图片，请尝试修改提示词或重试。")

        return images

    # ------------------------------------------------------------------
    # Video Generation (async with polling)
    # ------------------------------------------------------------------

    def generate_video(
        self,
        prompt: str,
        mode: str = "text2video",
        reference_images: Optional[List[Image.Image]] = None,
        model: str = VIDEO_MODEL,
        num_frames: int = DEFAULT_VIDEO_FRAMES,
        frame_rate: int = DEFAULT_VIDEO_FPS,
        seed: Optional[int] = None,
        size: Optional[str] = None,
        max_wait: int = 600,
        output_dir: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a video via the Agnes chat/completions API.

        Video generation goes through the chat completions endpoint with the
        video model. The response contains a video URL/base64 which we download.

        Args:
            prompt: Video description.
            mode: "text2video" or "img2video".
            reference_images: List of PIL Images for img2video.
            model: Model identifier (agnes-video-v2).
            num_frames: Desired frame count (embedded in prompt).
            frame_rate: Desired frame rate (embedded in prompt).
            seed: Optional seed (embedded in prompt).
            size: Output resolution (embedded in prompt).
            max_wait: Maximum wait for the HTTP request (video gen is synchronous
                      but can take several minutes).
            output_dir: Directory to save the video.
        """
        # Validate num_frames
        if (num_frames - 1) % 8 != 0:
            raise ValueError("num_frames must satisfy (num_frames - 1) % 8 == 0")
        if num_frames > 441:
            raise ValueError("num_frames must be <= 441")

        # --- Build the prompt with parameter hints ---
        full_prompt = prompt
        hints = []
        if size:
            hints.append(f"resolution: {size}")
        hints.append(f"{num_frames} frames at {frame_rate}fps")
        if seed:
            hints.append(f"seed: {seed}")
        if hints:
            full_prompt = f"{prompt}\n\n[Technical specs: {', '.join(hints)}]"

        # --- Build messages in OpenAI chat format ---
        if mode == "img2video" and reference_images:
            # Vision format with images
            content_parts = []
            for img in reference_images:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": pil_to_base64_uri(img), "detail": "high"},
                })
            content_parts.append({"type": "text", "text": full_prompt})
            messages = [{"role": "user", "content": content_parts}]
        else:
            messages = [{"role": "user", "content": full_prompt}]

        # --- Call chat/completions ---
        url = f"{BASE_URL}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
        }

        resp = self._request_with_retry("POST", url, "Video", json_payload=payload, timeout=max_wait)

        data = resp.json()

        # --- Extract video from response ---
        # The video model returns video data through the chat completions format.
        # Try multiple possible locations for the video URL/base64.

        video_url = None
        video_b64 = None

        # 1. Check choices[0].message.content for URL
        try:
            content = data["choices"][0]["message"]["content"]
            if content:
                # Could be a direct URL or JSON with url field
                content_stripped = content.strip()
                if content_stripped.startswith("http"):
                    video_url = content_stripped
                elif content_stripped.startswith("{"):
                    try:
                        import json as _json
                        content_data = _json.loads(content_stripped)
                        video_url = content_data.get("url") or content_data.get("video_url")
                        if not video_url and "data" in content_data:
                            video_url = content_data["data"][0].get("url")
                    except Exception:
                        pass
        except (KeyError, IndexError):
            pass

        # 2. Check top-level fields
        if not video_url:
            for key in ("url", "video_url", "output_url", "video"):
                val = data.get(key)
                if val and isinstance(val, str):
                    if val.startswith("http"):
                        video_url = val
                        break
                    elif val.startswith("data:video") or len(val) > 1000:
                        video_b64 = val
                        break

        # 3. Check data[] array
        if not video_url and not video_b64:
            for item in data.get("data", []):
                video_url = item.get("url")
                if video_url:
                    break

        if not video_url and not video_b64:
            raise RuntimeError(
                "[Video 错误] 服务器未返回视频数据。\n"
                f"响应原文: {str(data)[:500]}"
            )

        # --- Download and save ---
        save_dir = output_dir if output_dir else tempfile.gettempdir()
        os.makedirs(save_dir, exist_ok=True)
        timestamp = int(time.time())
        filename = f"agnes_video_{mode}_{timestamp}.mp4"
        save_path = os.path.join(save_dir, filename)

        if video_url:
            video_bytes = download_url_to_bytes(video_url, timeout=120)
        else:
            # base64 data URI
            import base64 as _b64
            b64_data = video_b64
            if b64_data.startswith("data:"):
                b64_data = b64_data.split(",", 1)[1]
            video_bytes = _b64.b64decode(b64_data)

        if not video_bytes:
            raise RuntimeError("[Video 错误] 视频下载失败。")

        with open(save_path, "wb") as f:
            f.write(video_bytes)

        return save_path

    # ------------------------------------------------------------------
    # Image Understanding / Reverse Prompt (via vision chat)
    # ------------------------------------------------------------------

    def reverse_prompt(
        self,
        image: Image.Image,
        model: str = CHAT_MODEL,
        detail: str = "detailed",
    ) -> str:
        """
        Analyze an image and generate a prompt that could reproduce it.

        Args:
            image: Input PIL Image.
            model: Vision-capable model identifier.
            detail: "brief" or "detailed" analysis level.

        Returns:
            Generated prompt / description.
        """
        image_uri = pil_to_base64_uri(image)

        if detail == "detailed":
            system_prompt = (
                "You are an expert at analyzing images and writing prompts for "
                "AI image generation models. Describe the image in extreme detail: "
                "subject, composition, lighting, color palette, style, mood, camera angle, "
                "depth of field, textures, and any distinctive elements. "
                "Output ONLY the prompt, no additional commentary."
            )
        else:
            system_prompt = (
                "You are an expert at analyzing images and writing prompts for "
                "AI image generation models. Write a concise prompt describing the key "
                "elements of this image. Output ONLY the prompt, no additional commentary."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_uri}},
                    {
                        "type": "text",
                        "text": "Please describe this image as an AI image generation prompt.",
                    },
                ],
            },
        ]

        return self.chat(messages, model=model, temperature=0.3, max_tokens=2048)


# ---------------------------------------------------------------------------
# Global state helper (shared across nodes)
# ---------------------------------------------------------------------------

# Path to the persistent API key config file (in plugin root).
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_API_KEY_CONFIG_FILE = os.path.join(_PLUGIN_DIR, "api_key_config.json")

_GLOBAL_CONFIG: Dict[str, Any] = {
    "api_key": os.environ.get("AGNES_API_KEY", ""),
    "chat_model": CHAT_MODEL,
    "image_model": IMAGE_MODEL,
    "video_model": VIDEO_MODEL,
}

# Attempt to load API key from config file on module init.
# Priority: env var > config file.
def _load_key_from_config_file() -> str:
    """Try to load the API key from the plugin's api_key_config.json."""
    try:
        if os.path.exists(_API_KEY_CONFIG_FILE):
            with open(_API_KEY_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("api_key", "")
    except Exception:
        pass
    return ""

# Load from config file if env var not set.
if not _GLOBAL_CONFIG["api_key"]:
    _GLOBAL_CONFIG["api_key"] = _load_key_from_config_file()


def get_api_key() -> str:
    """Get the current API key. Checks: env var → config file → fallback."""
    key = _GLOBAL_CONFIG["api_key"]
    if not key:
        key = _load_key_from_config_file()
        if key:
            _GLOBAL_CONFIG["api_key"] = key
    return key


def set_api_key(key: str) -> None:
    _GLOBAL_CONFIG["api_key"] = key


def get_client() -> AgnesClient:
    key = get_api_key()
    if not key:
        raise ValueError(
            "Agnes API key is not set. Please provide your API key in the node settings.\n"
            "Get a free key at: https://platform.agnes-ai.com/"
        )
    return AgnesClient(key)


def get_global_config() -> Dict[str, Any]:
    return dict(_GLOBAL_CONFIG)


def set_global_model(model_type: str, model_name: str) -> None:
    _GLOBAL_CONFIG[model_type] = model_name
