# ComfyUI Agnes AI Extension

ComfyUI 自定义节点插件，让你在 ComfyUI 中直接调用 Agnes AI 的全模态模型。

## 功能节点

| 节点名称 | 功能 | 模型 |
|---------|------|------|
| **Agnes API Key Config** | 🔑 持久化保存 API Key（推荐首次运行） | — |
| **Agnes LLM Chat** | LLM 文本对话 | agnes-2.0-flash |
| **Agnes Image Reverse Prompt** | 图像反推提示词 | agnes-2.0-flash (vision) |
| **Agnes Image-to-Image** | 图生图 / 图片编辑（支持多图输入） | agnes-image-2.1-flash |
| **Agnes Text-to-Image** | 文生图 | agnes-image-2.1-flash |
| **Agnes Image-to-Video** | 图生视频（支持多图/关键帧） | agnes-video-v2.0 |
| **Agnes Text-to-Video** | 文生视频 | agnes-video-v2.0 |

## 安装方法

### 方法一：Git 克隆

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/yourusername/comfyui_agnes_ai.git
cd comfyui_agnes_ai
pip install -r requirements.txt
```

### 方法二：手动安装

1. 下载此插件文件夹
2. 将其放入 `ComfyUI/custom_nodes/` 目录
3. 安装依赖：`pip install -r requirements.txt`
4. 重启 ComfyUI

## 获取 API Key

1. 访问 [https://platform.agnes-ai.com/](https://platform.agnes-ai.com/)
2. 注册/登录账号
3. 创建 API Key（目前免费）

## 快速开始：配置 API Key

**推荐方式** — 使用 `Agnes API Key Config` 节点：

1. 在节点菜单 → **Agnes AI** → 添加 **Agnes API Key Config**
2. 在 `api_key` 输入框填入你的 API Key（例如 `sk-xxx...`）
3. 运行一次（Ctrl+Enter / Queue Prompt）
4. Key 会自动保存到插件目录的 `api_key_config.json` 文件中
5. 之后所有其他 Agnes 节点的 `api_key` 字段留空即可自动加载

**备用方式** — 环境变量或直接输入：
- 环境变量：设置 `AGNES_API_KEY`（优先级最高）
- 直接输入：在每个节点的 `api_key` 字段手动填写

### API Key 加载优先级

```
环境变量 AGNES_API_KEY  >  api_key_config.json  >  运行时回退加载  >  节点输入框手动填写
```

> 注意：`api_key` widget 始终显示灰色 placeholder `sk-...`，不会明文显示真实 Key。

## 节点使用说明

### 🔑 Agnes API Key Config
- **首次运行即可**，将 API Key 持久化保存
- Key 以明文存储在 `api_key_config.json`（仅本机可访问）
- 设置 `clear_key = YES` 可清除已保存的 Key
- 输出 `status` 和 `masked_key` 供确认

### Agnes LLM Chat
- 输入文本消息，获取 LLM 回复
- 可选设置 System Prompt 控制 AI 行为
- 可调节 temperature（0.0-2.0）和 max_tokens

### Agnes Image Reverse Prompt
- 输入图片，自动分析并生成可复现该图片的提示词
- 同时输出详细版和简洁版提示词

### Agnes Image-to-Image（支持多图输入）
- 输入参考图 + 文本描述，生成编辑后的图片
- **支持最多 4 张参考图同时输入**
- **画质选择**：1K / 2K / 4K
- **宽高比**：1:1, 2:3, 3:4, 4:5, 9:16, 9:21, 3:2, 4:3, 5:4, 16:9, 21:9
- Strength 控制修改程度（0=尽量保持原图，1=自由发挥）
- 输出：`images` (IMAGE) + `resolution` (STRING)

### Agnes Text-to-Image
- 纯文本描述生成图片
- **画质选择**：1K / 2K / 4K
- **宽高比**：1:1, 2:3, 3:4, 4:5, 9:16, 9:21, 3:2, 4:3, 5:4, 16:9, 21:9
- 可一次生成最多 4 张
- 输出：`images` (IMAGE) + `resolution` (STRING)

### Agnes Image-to-Video（支持多图/关键帧）
- 一张图或多张图生成视频动画
- 支持设置关键帧（start -> end）
- **画质选择**：1K / 2K
- **宽高比**：1:1, 2:3, 3:4, 4:5, 9:16, 9:21, 3:2, 4:3, 5:4, 16:9, 21:9
- 可调节帧数（9-441，8n+1 格式）、帧率（8-60fps）
- 输出：`video` (VIDEO) + `resolution` (STRING)
- 视频保存到 `ComfyUI/output/agnes_videos/` 目录

### Agnes Text-to-Video
- 纯文本描述生成视频
- **画质选择**：1K / 2K
- **宽高比**：1:1, 2:3, 3:4, 4:5, 9:16, 9:21, 3:2, 4:3, 5:4, 16:9, 21:9
- 可调节帧数（9-441，8n+1）、帧率（8-60fps）、seed
- 输出：`video` (VIDEO) + `resolution` (STRING)
- 视频保存到 `ComfyUI/output/agnes_videos/` 目录

## 视频输出类型

视频节点输出类型按优先级自动选择：

| 环境 | 输出类型 | 说明 |
|------|---------|------|
| ComfyUI v1.7+ 自带 | `VIDEO` | 原生 VideoFromFile，可直连 `SaveVideo` |
| 安装了 VHS | `VHS_VIDEOINFO` | dict 格式，兼容视频工作流 |
| 都没有 | `STRING` | 文件路径字符串 |

## 画质 × 宽高比对照表

### 图片生成（1K / 2K / 4K）

| 比例 | 1K | 2K | 4K |
|------|------|------|------|
| 1:1 | 1024×1024 | 2048×2048 | 4096×4096 |
| 16:9 | 1816×1024 | 3640×2048 | 7280×4096 |
| 9:16 | 1024×1816 | 2048×3640 | 4096×7280 |
| 21:9 | 2384×1024 | 4776×2048 | 9552×4096 |
| 9:21 | 1024×2384 | 2048×4776 | 4096×9552 |

### 视频生成（1K / 2K）

| 比例 | 1K | 2K |
|------|------|------|
| 1:1 | 1024×1024 | 2048×2048 |
| 16:9 | 1816×1024 | 3640×2048 |
| 9:16 | 1024×1816 | 2048×3640 |

## 错误处理

- **API 5xx 错误**（502/503/504/524）：自动重试 3 次，指数退避（3s/6s/12s）
- **连接超时**：自动重试 + 中文错误提示
- **Cloudflare 错误页**：自动解析为中文可读提示
- **CUDA OOM（服务器端）**：自动识别并给出降参数建议

## 技术架构

```
comfyui_agnes_ai/
├── __init__.py              # 插件入口，注册 7 个节点
├── config.yaml              # 默认配置
├── requirements.txt         # 依赖
├── README.md                # 本文档
├── api/
│   └── __init__.py          # AgnesClient API 封装（Chat / Image / Video）
├── nodes/
│   ├── __init__.py
│   ├── api_key_config.py    # API Key 持久化节点
│   ├── llm_chat.py          # LLM 对话
│   ├── image_reverse.py     # 图像反推
│   ├── text2img.py          # 文生图
│   ├── img2img.py           # 图生图（多图）
│   ├── text2video.py        # 文生视频
│   └── img2video.py         # 图生视频（多图/关键帧）
└── web/js/                  # 前端扩展目录（预留）
```

## 更新日志

### v1.6.0 — 原生 VIDEO 类型输出
- 视频节点输出口支持 ComfyUI 原生 `VIDEO` 类型（v1.7+）
- 三级检测链：comfy_api VIDEO → VHS_VIDEOINFO → STRING
- 修复 `remixed_from_video_id` 字段名（API 实际返回的 URL 字段）
- VIDEO 类型出错时 raise 而非返回字符串（避免下游 `SaveVideo` 崩溃）

### v1.4.0 — API 错误处理优化
- HTML 错误页（Cloudflare 5xx）自动解析为中文提示
- 5xx/429 自动重试 3 次，连接超时自动重试
- Chat / Image / Video 三个 API 统一使用重试机制

### v1.3.0 — 图片节点画质与分辨率
- `text2img` / `img2img` 新增 quality（1K/2K/4K）+ aspect_ratio（11种）
- 自动计算实际像素（对齐 8 的倍数）
- 新增 `resolution` 输出口

### v1.2.0 — 视频输出路径优化
- 视频从系统临时目录 → `ComfyUI/output/agnes_videos/`
- `generate_video()` 新增 `output_dir` 参数

### v1.1.0 — API Key 持久化
- 新增 `AgnesAPIKeyConfig` 节点，Key 保存到 `api_key_config.json`
- `api_key` widget 统一为空字符串，运行时从 config 自动加载

### v1.0.0 — 初始版本
- 7 个节点：API Key Config、LLM Chat、Image Reverse、Text-to-Image、Image-to-Image、Text-to-Video、Image-to-Video

## 注意事项

- 视频生成是异步任务，通常需要 2-6 分钟
- 免费 API 高峰期可能有排队（503）或 GPU OOM（500），降低画质/帧数可提高成功率
- 建议首次使用先测试文生图，确认 API Key 正常工作
- 多张图片同时生成会增加等待时间

## 许可证

MIT License
