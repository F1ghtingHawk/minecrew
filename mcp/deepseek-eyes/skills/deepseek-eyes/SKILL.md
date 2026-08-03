---
name: deepseek-eyes
description: 通过 MCP 提供识图、区域精读、空间定位、文生图与图生图能力（基于硅基流动 Qwen 模型），给纯文本模型（如 DeepSeek）装上眼睛。
---

# DeepSeek Eyes：识图与生图工具

本插件通过 MCP 提供 6 个工具，给纯文本模型（如 DeepSeek）装上“眼睛”。模型是纯文本
模型时，先调用这些工具拿到文字结果，再基于结果继续回答。

## 使用规则

1. 用户粘贴图片或截图后，先用 `analyze_image` 获取整体描述；要精读某块区域时：
   先 `describe_spatial` 拿归一化 bbox 定位 → 换算像素坐标 → `recognize_region` 裁剪细看。
2. 所有识图工具的 `image_path` 支持本地路径或 URL；留空时自动读取剪贴板截图。
3. 生图用 `generate_image`（图片优先保存到当前项目根目录的 `generated/`（拿不到时保存到插件目录）并返回本地路径，
   临时链接 1 小时有效）；基于已有图片修改用 `edit_image`。
4. `generate_image` / `edit_image` 的 prompt 若为中文会自动翻译成英文（Qwen 生图模型
   对英文指令执行最可靠），返回结果中会注明翻译内容。
5. `image_size` 只接受官方推荐值（1328x1328 / 1664x928 / 928x1664 / 1472x1140 /
   1140x1472 / 1584x1056 / 1056x1584），非法值自动退化为默认 1328x1328。

## 工具列表（参数默认值即推荐值）

| 工具 | 用途 |
| --- | --- |
| `analyze_image` | 识别图片上有什么内容（第一层理解） |
| `recognize_region` | 精确识别指定区域（像素坐标裁剪后单独喂模型，语言描述输出） |
| `describe_spatial` | 哪里有什么：结构化 JSON（label + 归一化 bbox），无修饰词，必须详细 |
| `ask_image` | 针对图片自由提问（OCR、UI 分析、流程图解读等） |
| `generate_image` | 文生图（Qwen-Image） |
| `edit_image` | 图生图编辑（Qwen-Image-Edit） |

## 环境要求

- 依赖：`mcp`、`openai`、`Pillow`（D:\Anaconda 已装好）。
- API Key：系统环境变量 `SILICONFLOW_API_KEY`，或插件根目录 `.env` 文件（二选一，
  环境变量优先）。Key 在 https://cloud.siliconflow.cn 注册获取。
- 默认模型：识图 `Qwen/Qwen3-VL-32B-Instruct`，生图 `Qwen/Qwen-Image`，
  编辑 `Qwen/Qwen-Image-Edit`；模型 404 时自动回退。
