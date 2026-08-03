# -*- coding: utf-8 -*-
"""deepseek-eyes：末影龙娘调度小队（Minecrew）的生图 MCP（经硅基流动 SiliconFlow API）。

能力：
  - generate_image  文生图（Qwen-Image）
  - edit_image      图生图（Qwen-Image-Edit）

识图类工具已移除：视觉识别/区域识别/空间描述改由小白娘（Fable 模型）承担。

运行：python server.py（stdio 模式），再接入 Claude / Codex / Cursor 等 MCP 客户端。

参数设计：每个工具都有推荐参数（同时也是默认参数），传入的非法参数自动退化为默认。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from mcp.server.fastmcp import Context, FastMCP
from openai import OpenAI
from PIL import Image

# MCP 走 stdio 协议，标准输出必须纯净：把 SDK 日志全部压到 stderr，且降噪
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# 配置：环境变量优先，项目 .env 兜底
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载器（不依赖 python-dotenv），已存在的环境变量优先。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.environ.get("SILICONFLOW_API_KEY", "").strip()
BASE_URL = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")

# 翻译模型：中文生图/编辑指令在执行前先用它翻成英文（Qwen 生图模型对英文指令执行最可靠）
VL_MODEL = os.environ.get("EYES_VL_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

# 文生图 / 图生图模型（按模型广场实际在架名称）
T2I_MODEL = os.environ.get("EYES_T2I_MODEL", "Qwen/Qwen-Image")
T2I_FALLBACK = os.environ.get("EYES_T2I_FALLBACK", "Qwen/Qwen-Image")
EDIT_MODEL = os.environ.get("EYES_EDIT_MODEL", "Qwen/Qwen-Image-Edit")
EDIT_FALLBACK = os.environ.get("EYES_EDIT_FALLBACK", "Qwen/Qwen-Image-Edit")

# 推荐参数（同时也是默认参数）
DEFAULT_IMAGE_SIZE = "1328x1328"
DEFAULT_STEPS = 30
MAX_IMAGE_SIDE = 2048

QWEN_IMAGE_SIZES = {
    "1328x1328",  # 1:1
    "1664x928",   # 16:9
    "928x1664",   # 9:16
    "1472x1140",  # 4:3
    "1140x1472",  # 3:4
    "1584x1056",  # 3:2
    "1056x1584",  # 2:3
}


def _pick_writable_dir(name: str) -> Path:
    """挑选一个可写的目录：项目目录优先，不行就 AppData，再不行就临时目录。"""
    bases = [
        PROJECT_ROOT,
        Path(os.environ.get("LOCALAPPDATA", "")) / "deepseek-eyes",
        Path(os.environ.get("TEMP", "")) / "deepseek-eyes",
    ]
    for base in bases:
        if not base:
            continue
        try:
            d = base / name
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return d
        except Exception:
            continue
    raise RuntimeError(f"无法创建可写的 {name} 目录（已尝试项目目录、AppData、临时目录）")


def _resolve_work_dir(env_key: str, name: str) -> Path:
    env = os.environ.get(env_key, "").strip()
    if env:
        d = Path(env)
        d.mkdir(parents=True, exist_ok=True)
        return d
    return _pick_writable_dir(name)


OUTPUT_DIR = _resolve_work_dir("EYES_OUTPUT_DIR", "generated")

if not API_KEY:
    print(
        "[deepseek-eyes] 未配置 SILICONFLOW_API_KEY：请在系统环境变量或项目 .env 中设置后重启。",
        file=sys.stderr,
    )
    sys.exit(1)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 参数校验：非法参数一律退化为默认
# ---------------------------------------------------------------------------


def _image_size(value: Optional[str]) -> str:
    v = (value or "").strip()
    return v if v in QWEN_IMAGE_SIZES else DEFAULT_IMAGE_SIZE


def _steps(value: Optional[int]) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return DEFAULT_STEPS
    return v if 1 <= v <= 50 else DEFAULT_STEPS


def _seed(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return v if 0 <= v <= 9999999999 else None


# ---------------------------------------------------------------------------
# 图片处理
# ---------------------------------------------------------------------------


def _image_to_data_url(image_path: str, max_side: int = MAX_IMAGE_SIDE) -> str:
    """本地图片转 base64 data URI，超长边自动缩放，统一转 RGB+JPEG。"""
    with Image.open(image_path) as im:
        if im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _is_url(value: str) -> bool:
    return re.match(r"^https?://", value, re.IGNORECASE) is not None


def _resolve_local(path: str) -> str:
    p = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.isfile(p):
        raise FileNotFoundError(f"图片文件不存在：{p}")
    return p


# ---------------------------------------------------------------------------
# 中文提示翻译（生图/编辑前转英文）
# ---------------------------------------------------------------------------

_client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120.0, max_retries=1)


def _contains_cjk(text: str) -> bool:
    """检测是否包含中日韩统一表意文字（中文等）。"""
    return re.search(r"[㐀-䶿一-鿿]", text) is not None


def _translate_prompt(prompt: str) -> str:
    """把非英文（主要是中文）的生图/编辑指令翻译成英文。

    Qwen 生图/编辑模型对英文指令的执行最可靠（实测中文改色指令可能不生效），
    因此发送前先用翻译模型做文本翻译。翻译失败时原样返回。
    """
    if not _contains_cjk(prompt):
        return prompt
    try:
        resp = _client.chat.completions.create(
            model=VL_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a translator for an image generation/edit model. "
                        "Translate the user's instruction into concise, natural English. "
                        "Output only the translation, no explanations, no quotes."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        translated = (resp.choices[0].message.content or "").strip().strip('"')
        return translated if translated else prompt
    except Exception:  # noqa: BLE001
        return prompt


# ---------------------------------------------------------------------------
# 生图 / 图生图（Qwen-Image / Qwen-Image-Edit，/images/generations）
# ---------------------------------------------------------------------------


def _post_json(endpoint: str, payload: dict, timeout: int = 180) -> dict:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download_image(img_url: str, out_dir: Path | None = None) -> str:
    """硅基流动返回的图片链接 1 小时有效，必须立即下载到本地。"""
    out_dir = out_dir or OUTPUT_DIR
    with urllib.request.urlopen(img_url, timeout=180) as resp:
        content = resp.read()
    name = f"generated_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
    path = out_dir / name
    path.write_bytes(content)
    return str(path)


async def _resolve_generated_dir(ctx: Context | None = None) -> Path:
    """生成图片的保存位置：优先取 MCP 客户端宣告的工作区根目录（即当前项目），
    其次取进程工作目录（与插件目录不同时），最后回退到默认输出目录。"""
    # 1) MCP roots：客户端宣告的项目根目录
    if ctx is not None:
        try:
            session = getattr(ctx, "session", None)
            if session is not None and hasattr(session, "list_roots"):
                result = await session.list_roots()
                for root in getattr(result, "roots", []) or []:
                    uri = getattr(root, "uri", None)
                    if uri is None:
                        continue
                    uri_str = str(uri)
                    if uri_str.startswith("file://"):
                        parsed = urlparse(uri_str)
                        path = unquote(parsed.path)
                        if re.match(r"^/[A-Za-z]:", path):  # Windows: /C:/xxx -> C:/xxx
                            path = path[1:]
                        if path:
                            cand = Path(path) / "generated"
                            cand.mkdir(parents=True, exist_ok=True)
                            probe = cand / ".write_probe"
                            probe.write_text("ok", encoding="utf-8")
                            probe.unlink()
                            return cand
        except Exception:
            pass
    # 2) 进程工作目录（与插件目录不同时才用，避免把文件写进插件本体）
    try:
        cwd = Path.cwd()
        if cwd.resolve() != PROJECT_ROOT.resolve():
            cand = cwd / "generated"
            cand.mkdir(parents=True, exist_ok=True)
            probe = cand / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return cand
    except Exception:
        pass
    # 3) 默认输出目录
    return OUTPUT_DIR


def _generate(payload: dict, candidates: list[str], kind: str, out_dir: Path) -> tuple[str, str]:
    endpoint = f"{BASE_URL}/images/generations"
    last_error = ""
    for model in candidates:
        body = dict(payload)
        body["model"] = model
        try:
            data = _post_json(endpoint, body)
            images = data.get("images") or [{}]
            img_url = images[0].get("url")
            if not img_url:
                raise RuntimeError(
                    f"响应中没有图片 URL：{json.dumps(data, ensure_ascii=False)[:300]}"
                )
            return _download_image(img_url, out_dir), img_url
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            last_error = f"{exc.code}: {err_body[:300]}"
            if exc.code == 404 and model != candidates[-1]:
                continue
            raise RuntimeError(f"{kind}请求失败：{last_error}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{kind}请求失败：{exc}") from exc
    raise RuntimeError(f"所有{kind}模型均调用失败：{last_error}")


# ---------------------------------------------------------------------------
# MCP 工具（2 个）
# ---------------------------------------------------------------------------

mcp = FastMCP("deepseek-eyes")


@mcp.tool()
async def generate_image(
    prompt: str,
    negative_prompt: str = "",
    image_size: str = "1328x1328",
    seed: Optional[int] = None,
    steps: int = 30,
    ctx: Context = None,
) -> str:
    """文生图（Qwen-Image）。中文 prompt 会自动翻译成英文再生成（模型对英文指令执行最可靠）；image_size 仅接受官方推荐值，非法值自动退化为默认 1328x1328。图片保存到当前项目根目录的 generated/（拿不到项目根目录时保存到插件目录）。"""
    if not (prompt or "").strip():
        return "文生图失败：prompt 不能为空"
    try:
        raw_prompt = (prompt or "").strip()
        translated = _translate_prompt(raw_prompt)
        payload = {
            "prompt": translated,
            "negative_prompt": negative_prompt or "",
            "image_size": _image_size(image_size),
            "num_inference_steps": _steps(steps),
        }
        s = _seed(seed)
        if s is not None:
            payload["seed"] = s
        out_dir = await _resolve_generated_dir(ctx)
        path, url = _generate(payload, list(dict.fromkeys([T2I_MODEL, T2I_FALLBACK])), "文生图", out_dir)
        note = ""
        if translated != raw_prompt:
            note = f"\n（原中文提示已自动翻译为英文：{translated}）"
        return f"图片已生成并保存到：{path}\n（临时链接 1 小时有效：{url}）{note}"
    except Exception as exc:  # noqa: BLE001
        return f"文生图失败：{exc}"


@mcp.tool()
async def edit_image(
    image_ref: str,
    prompt: str,
    negative_prompt: str = "",
    seed: Optional[int] = None,
    steps: int = 30,
    ctx: Context = None,
) -> str:
    """图生图编辑（Qwen-Image-Edit）。image_ref 为本地路径或 URL；中文 prompt 会自动翻译成英文再编辑（实测该模型只可靠执行英文指令）。结果保存到当前项目根目录的 generated/（拿不到项目根目录时保存到插件目录）。"""
    if not (prompt or "").strip():
        return "图生图失败：prompt 不能为空"
    try:
        p = (image_ref or "").strip()
        if not p:
            raise ValueError("image_ref 不能为空")
        raw_prompt = (prompt or "").strip()
        translated = _translate_prompt(raw_prompt)
        if _is_url(p):
            image_value = p
        else:
            image_value = _image_to_data_url(_resolve_local(p))
        payload = {
            "image": image_value,
            "prompt": translated,
            "negative_prompt": negative_prompt or "",
            "num_inference_steps": _steps(steps),
        }
        s = _seed(seed)
        if s is not None:
            payload["seed"] = s
        out_dir = await _resolve_generated_dir(ctx)
        path, url = _generate(payload, list(dict.fromkeys([EDIT_MODEL, EDIT_FALLBACK])), "图生图", out_dir)
        note = ""
        if translated != raw_prompt:
            note = f"\n（原中文提示已自动翻译为英文：{translated}）"
        return f"图片已生成并保存到：{path}\n（临时链接 1 小时有效：{url}）{note}"
    except Exception as exc:  # noqa: BLE001
        return f"图生图失败：{exc}"


if __name__ == "__main__":
    mcp.run()
