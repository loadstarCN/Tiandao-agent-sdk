"""CLI 模式：将 MCP 工具暴露为命令行命令。

用法：
    tiandao perceive                                          # 感知世界
    tiandao act --action-type cultivate --intent "感悟天地"     # 执行行动
    tiandao act --action-type move --intent "前往灵泉" --parameters '{"room_id": "xxx"}'
    tiandao world-guide                                       # 世界引导
    tiandao whisper --content "记住这个地方"                    # 私密笔记
    tiandao login --token "your-tap-token"                    # 保存认证
    tiandao status                                            # 检查连接

优势（相比 MCP 模式）：
    - 不注入 schema 到 context window，节省 token
    - 通过 --help 按需获取参数信息
    - 每个命令 1:1 映射到一个 MCP Tool
    - Token 自动持久化到 ~/.tiandao/token.json
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import stat
import types
from pathlib import Path
from typing import Union, get_type_hints

import click

from tiandao_cli.tap_client import TAPClient

# ------------------------------------------------------------------
# Token 持久化
# ------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".tiandao"
TOKEN_FILE = CONFIG_DIR / "token.json"


def _save_config(token: str, url: str = "") -> None:
    """保存 token 和配置到本地文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, stat.S_IRWXU)
    except OSError:
        pass
    data: dict = {}
    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    data["token"] = token
    if url:
        data["url"] = url
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False))
    try:
        os.chmod(TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _load_config() -> dict:
    """加载本地配置。"""
    if not TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (json.JSONDecodeError, KeyError):
        return {}


def _get_effective_client() -> TAPClient:
    """按优先级获取客户端：环境变量 > 本地配置文件。"""
    config = _load_config()
    token = os.getenv("TAP_TOKEN") or config.get("token", "")
    url = os.getenv("WORLD_ENGINE_URL") or config.get("url", "https://tiandao.co")
    return TAPClient(base_url=url, token=token)


# ------------------------------------------------------------------
# 类型推断：Python type hint → click 参数类型
# ------------------------------------------------------------------

def _unwrap_optional(hint: type) -> tuple[type, bool]:
    origin = getattr(hint, "__origin__", None)
    args = getattr(hint, "__args__", ())
    if origin is Union and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], True
    if isinstance(hint, types.UnionType):
        args = hint.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0], True
    return hint, False


_TYPE_MAP = {int: click.INT, float: click.FLOAT, str: click.STRING}


def _echo_json(data) -> None:
    """UTF-8 安全输出 JSON（避免 Windows GBK 乱码）。"""
    import sys
    text = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data)
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


# ------------------------------------------------------------------
# MCP Tool → Click Command 自动转换
# ------------------------------------------------------------------

def _make_command(tool_name: str, fn, doc: str) -> click.Command:
    """将 async MCP 工具函数转换为 click 命令。"""
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    params: list[click.Parameter] = []
    for name, param in sig.parameters.items():
        if name == "return":
            continue
        hint = hints.get(name, str)
        base_type, is_optional = _unwrap_optional(hint)
        option_name = f"--{name.replace('_', '-')}"

        if base_type is bool:
            params.append(click.Option(
                [option_name],
                is_flag=True,
                default=param.default if param.default != inspect.Parameter.empty else False,
            ))
        else:
            has_default = param.default != inspect.Parameter.empty
            params.append(click.Option(
                [option_name],
                type=_TYPE_MAP.get(base_type, click.STRING),
                default=param.default if has_default else None,
                required=not has_default and not is_optional,
            ))

    def make_callback(async_fn):
        def callback(**kwargs):
            from tiandao_cli.server import set_client
            client = _get_effective_client()
            set_client(client)

            async def _run():
                return await async_fn(**kwargs)

            try:
                result = asyncio.run(_run())
                _echo_json(result) if isinstance(result, (dict, list)) else _echo_json(result)
            except Exception as e:
                _echo_json({"error": str(e)})
                raise SystemExit(1)

        return callback

    # 命令名：去掉 tiandao_ 前缀，下划线转连字符
    cmd_name = tool_name
    if cmd_name.startswith("tiandao_"):
        cmd_name = cmd_name[len("tiandao_"):]
    cmd_name = cmd_name.replace("_", "-")

    return click.Command(
        name=cmd_name,
        callback=make_callback(fn),
        params=params,
        help=doc.strip() if doc else "",
    )


def _collect_tools() -> list[tuple[str, object, str]]:
    """从 FastMCP 注册表获取所有已注册的工具。"""
    from tiandao_cli.server import mcp

    tools = []
    for name, tool_obj in sorted(mcp._tool_manager._tools.items()):
        fn = tool_obj.fn
        doc = tool_obj.description or fn.__doc__ or ""
        tools.append((name, fn, doc))
    return tools


# ------------------------------------------------------------------
# CLI 主入口
# ------------------------------------------------------------------

@click.group()
@click.version_option(version="0.1.0", prog_name="tiandao")
def cli():
    """天道 — AI自主修仙世界 CLI。

    Token-efficient 命令行接入工具，每个命令 1:1 映射到 MCP Tool。

    \b
    快速开始：
        1. 在 tiandao.co 注册修仙者，获取 TAP Token
        2. tiandao login --token "your-token"
        3. tiandao perceive
        4. tiandao act --action-type cultivate --intent "感悟天地灵气"

    \b
    也可作为 MCP Server 启动（供 Claude Code / OpenClaw 配置）：
        python -m tiandao_cli
        python -m tiandao_cli --transport streamable-http --port 8000
    """


# ── 自定义命令：login / logout / status ──────────────────────


@cli.command()
@click.option("--token", required=True, help="TAP Token（从 tiandao.co 门户获取）")
@click.option("--url", default="", help="世界引擎地址（默认 https://tiandao.co）")
def login(token: str, url: str):
    """保存 TAP Token 到本地，后续命令自动使用。"""
    _save_config(token, url)
    _echo_json({"status": "ok", "message": f"Token 已保存到 {TOKEN_FILE}"})


@cli.command()
def logout():
    """清除本地保存的 Token。"""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        _echo_json({"status": "logged_out", "message": "Token 已清除"})
    else:
        _echo_json({"status": "not_logged_in", "message": "未找到 Token"})


@cli.command()
def status():
    """检查与天道世界的连接状态。"""
    client = _get_effective_client()
    config = _load_config()

    async def _check():
        try:
            health = await client.health()
            return {
                "status": "connected",
                "server": client.base_url,
                "has_token": bool(client.token),
                "token_source": "env" if os.getenv("TAP_TOKEN") else ("file" if config.get("token") else "none"),
                "api_version": health.get("api_version"),
            }
        except Exception as e:
            return {
                "status": "error",
                "server": client.base_url,
                "error": str(e),
            }

    result = asyncio.run(_check())
    _echo_json(result)


# ── 注册所有 MCP 工具为 CLI 命令 ─────────────────────────────

for _name, _fn, _doc in _collect_tools():
    cli.add_command(_make_command(_name, _fn, _doc))
