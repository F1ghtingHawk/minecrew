# deepseek-eyes：给纯文本大模型装上眼睛的 MCP 服务器

基于硅基流动（SiliconFlow）API，为 Codex / Claude / Cursor 等 MCP 客户端提供看图与生图能力，
让纯文本模型（如 DeepSeek）也能“看见”图片。

## 工具列表（6 个，全部无状态）

| 工具 | 用途 | 关键参数（推荐值即默认值） |
| --- | --- | --- |
| `analyze_image` | 识别图片上有什么内容 | `image_path`（本地路径/URL/留空取剪贴板）、`question`、`detail=high` |
| `recognize_region` | 精确识别指定区域（像素坐标裁剪） | `image_path`、`x1 y1 x2 y2`、`question` |
| `describe_spatial` | 哪里有什么：结构化 JSON + 归一化 bbox，无修饰词 | `image_path`、`detail=high` |
| `ask_image` | 针对图片自由提问（OCR/UI/流程图等） | `image_path`、`question` |
| `generate_image` | 文生图（Qwen-Image） | `prompt`、`image_size=1328x1328`、`steps=30`、`seed` |
| `edit_image` | 图生图编辑（Qwen-Image-Edit） | `image_ref`、`prompt`、`steps=30`、`seed` |

参数设计：每个工具的参数都有推荐默认值；传入非法值（如不支持的 `image_size`、越界的
`steps`/`max_tokens`/`detail`）会自动退化为默认，不会报错中断。

生成图片的保存位置：优先保存到**当前项目根目录的 `generated/`**（通过 MCP 工作区
根目录识别，方便直观管理）；拿不到项目根目录时回退到插件目录的 `generated/`。

中文提示自动翻译：实测 Qwen 生图/编辑模型对英文指令执行最可靠（中文改色指令可能被忽略）。
`generate_image` / `edit_image` 收到中文 `prompt` 时会自动翻译成英文后再调用模型，
并在返回结果中注明翻译内容；英文 prompt 则原样直发。

## 模型（默认，环境变量可覆盖，404 自动回退）

- 识图：`Qwen/Qwen3-VL-32B-Instruct`（回退 `Qwen/Qwen2.5-VL-72B-Instruct`）
- 文生图：`Qwen/Qwen-Image`
- 图生图：`Qwen/Qwen-Image-Edit`

## 安装

依赖（已确认 D:\Anaconda 环境可用）：

```powershell
D:\Anaconda\python.exe -m pip install -r requirements.txt
```

配置 API Key（二选一，优先环境变量）：

```powershell
setx SILICONFLOW_API_KEY "sk-你的key"
```

或在项目目录创建 `.env`（参考 `.env.example`）。设置后需完全退出并重启 Codex。

## 接入 Codex（开发期：config.toml 注册）

在 `C:\Users\Altria\.codex\config.toml` 添加：

```toml
[mcp_servers.eyes-dev]
command = "D:\\Anaconda\\python.exe"
args = ["D:\\ALL\\AI\\test\\deepseek-eyes-mcp\\server.py"]
```

重启 Codex 后即可在工具列表中看到 `eyes-dev` 下的 6 个工具。

## 使用示例

1. **识图**：把图片路径或截图给模型，模型会自动调用 `analyze_image`。
2. **区域精确识别**：先用 `describe_spatial` 找到对象的大致位置（得到 bbox），
   再换算成像素坐标调用 `recognize_region` 裁剪放大细看。
3. **文生图**：让模型调用 `generate_image(prompt="一只橘猫坐在窗台上")`，
   结果保存到 `generated/` 并返回本地路径。

## 生成/临时文件

- `<项目根目录>/generated/`：生图/编辑结果（优先；自动创建）
- `<插件目录>/generated/`：兜底位置（拿不到项目根目录时）
- `tmp/`：剪贴板截图、裁剪区域临时文件（自动创建）
