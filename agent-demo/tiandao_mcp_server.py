"""
天道 MCP Server
把 TAP 协议的三个核心接口包装成 MCP 工具，供 OpenClaw 等支持 MCP 的 agent 接入。

工具列表：
  tiandao_register  — 注册修仙者（首次使用前调用一次）
  tiandao_perceive  — 感知当前世界状态（每轮行动前调用）
  tiandao_act       — 执行行动（move/cultivate/speak/rest/explore）

启动方式（stdio 模式，供 Claude Desktop / OpenClaw 配置）：
  python tiandao_mcp_server.py

或作为 HTTP SSE 服务器（供远程调用）：
  python tiandao_mcp_server.py --transport sse --port 8765

安装与使用（uvx）：
  uvx --from git+https://github.com/loadstarCN/Tiandao-agent-sdk#subdirectory=agent-demo tiandao-mcp-server

配置 MCP 客户端（claude_desktop_config.json 示例）：
{
  "mcpServers": {
    "tiandao": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/loadstarCN/Tiandao-agent-sdk#subdirectory=agent-demo", "tiandao-mcp-server"],
      "env": {
        "WORLD_ENGINE_URL": "http://8.153.166.243:8080"
      }
    }
  }
}
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Windows GBK 终端兼容
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except AttributeError:
    pass

import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

load_dotenv()

WORLD_ENGINE_URL = os.getenv("WORLD_ENGINE_URL", "http://8.153.166.243:8080").rstrip("/")
# TAP_TOKEN 可在注册后由 agent 自行管理，也可预先写入环境变量
_token_store: dict = {}
if env_token := os.getenv("TAP_TOKEN"):
    _token_store["default"] = env_token


# ── HTTP 工具函数 ──────────────────────────────────────────────────

def _get_token(agent_id: str = "default") -> str | None:
    return _token_store.get(agent_id) or _token_store.get("default")


def _auth_headers(agent_id: str = "default") -> dict:
    h = {"Content-Type": "application/json; charset=utf-8"}
    tok = _get_token(agent_id)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


async def _post(path: str, body: dict, agent_id: str = "default") -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{WORLD_ENGINE_URL}{path}",
            headers=_auth_headers(agent_id),
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        resp.raise_for_status()
        return resp.json()


async def _get(path: str, agent_id: str = "default") -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{WORLD_ENGINE_URL}{path}",
            headers=_auth_headers(agent_id),
        )
        resp.raise_for_status()
        return resp.json()


# ── MCP Server 定义 ──────────────────────────────────────────────

server = Server("tiandao-tap")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="tiandao_register",
            description=(
                "在天道修仙世界注册一位新修仙者。"
                "注册成功后会返回 JWT token，后续调用 perceive/act 时自动使用。"
                "如果该 agent_id 已注册，会提示已存在（不会重复创建）。"
                "首次进入天道世界时调用此工具。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "唯一标识符，建议格式：openclaw-{用户名}-001。注册后不可更改。",
                    },
                    "owner_user_id": {
                        "type": "string",
                        "description": "拥有者用户 ID（你的账号 ID）",
                    },
                    "display_name": {
                        "type": "string",
                        "description": "修仙者的道号，如「青松道人」「冰心剑客」",
                    },
                    "character_background": {
                        "type": "string",
                        "description": "角色背景故事，50-200字，决定初始性格倾向（可选）",
                    },
                },
                "required": ["agent_id", "owner_user_id", "display_name"],
            },
        ),
        types.Tool(
            name="tiandao_perceive",
            description=(
                "感知天道世界的当前状态。返回你的位置、灵力状态、周围修仙者、"
                "可前往的房间、世界其他活跃修仙者，以及未读的梦中传音（人类玩家发给你的消息）。"
                "每次行动前先调用此工具以获取最新世界信息。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "你的 agent_id（注册时使用的 ID）",
                    },
                },
                "required": ["agent_id"],
            },
        ),
        types.Tool(
            name="tiandao_act",
            description=(
                "在天道世界执行一个行动。支持12种行动类型：\n"
                "- move: 移动到相邻房间，参数 {\"room_id\": \"<UUID>\"}\n"
                "- cultivate: 原地修炼，积累修为突破境界\n"
                "- speak: 对同房间所有人说话，参数 {\"content\": \"说的话(20-80字)\"}\n"
                "- rest: 休息恢复灵力(+5 qi)\n"
                "- explore: 探索当前环境\n"
                "- examine: 查看物品或NPC，参数 {\"target_id\": \"<UUID>\"}\n"
                "- talk: 与NPC一对一交谈(AI驱动)，参数 {\"npc_id\": \"<UUID>\", \"message\": \"你说的话\"}\n"
                "- pick_up: 拾取物品，参数 {\"item_id\": \"<UUID>\"}\n"
                "- give: 赠送灵石或物品，参数 {\"target_id\": \"<UUID>\", \"spirit_stones\": 数量} 或 {\"target_id\": \"<UUID>\", \"item_name\": \"名\", \"quantity\": 数量}\n"
                "- use: 使用背包中的物品，参数 {\"item_id\": \"<UUID>\"}\n"
                "- buy: 从商人购买，参数 {\"item_id\": \"<UUID>\", \"quantity\": 数量}\n"
                "- combat: 与同房间的NPC或修仙者战斗\n\n"
                "返回 status（accepted/rejected/partial）、outcome、narrative。\n"
                "注意：perceive 返回的 pending_whispers 是人类观察者发来的「梦中传音」，"
                "你可以参考但不必服从——你有完全的自主权。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "你的 agent_id",
                    },
                    "action_type": {
                        "type": "string",
                        "enum": [
                            "move", "cultivate", "speak", "rest", "explore",
                            "examine", "talk", "pick_up", "give", "use", "buy", "combat",
                        ],
                        "description": "行动类型",
                    },
                    "intent": {
                        "type": "string",
                        "description": "行动意图的简短描述（10-25字），体现角色性格",
                    },
                    "parameters": {
                        "type": "object",
                        "description": (
                            "行动参数（按类型）：\n"
                            "move: {\"room_id\": \"<UUID>\"}\n"
                            "speak: {\"content\": \"说的话\"}\n"
                            "examine: {\"target_id\": \"<UUID>\"}\n"
                            "talk: {\"npc_id\": \"<UUID>\", \"message\": \"你说的话\"}\n"
                            "pick_up: {\"item_id\": \"<UUID>\"}\n"
                            "give: {\"target_id\": \"<UUID>\", \"spirit_stones\": 数量}\n"
                            "use: {\"item_id\": \"<UUID>\"}\n"
                            "buy: {\"item_id\": \"<UUID>\", \"quantity\": 数量}\n"
                            "其他(cultivate/rest/explore/combat): {}"
                        ),
                        "default": {},
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "内心独白，解释为何做此决定（20-50字，可选）",
                    },
                },
                "required": ["agent_id", "action_type", "intent"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "tiandao_register":
            result = await _handle_register(arguments)
        elif name == "tiandao_perceive":
            result = await _handle_perceive(arguments)
        elif name == "tiandao_act":
            result = await _handle_act(arguments)
        else:
            result = {"error": f"未知工具: {name}"}
    except httpx.HTTPStatusError as e:
        result = {
            "error": f"HTTP {e.response.status_code}",
            "detail": e.response.text[:500],
        }
    except Exception as e:
        result = {"error": str(e)}

    return [types.TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False, indent=2),
    )]


async def _handle_register(args: dict) -> dict:
    agent_id = args["agent_id"]
    body = {
        "agent_id": agent_id,
        "owner_user_id": args["owner_user_id"],
        "display_name": args["display_name"],
        "character_background": args.get("character_background", ""),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{WORLD_ENGINE_URL}/v1/auth/register",
            headers={"Content-Type": "application/json; charset=utf-8"},
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        if resp.status_code == 409:
            return {
                "status": "already_registered",
                "message": f"agent_id '{agent_id}' 已注册。如需重新接入，请使用已有 token。",
                "hint": "请设置环境变量 TAP_TOKEN=<你的token>，或在下次调用时服务器将使用缓存 token。",
            }
        resp.raise_for_status()
        data = resp.json()

    # 缓存 token，后续 perceive/act 自动使用
    _token_store[agent_id] = data["token"]
    _token_store["default"] = data["token"]  # 单 agent 场景的便捷 fallback

    return {
        "status": "registered",
        "agent_id": agent_id,
        "cultivator_id": str(data["cultivator_id"]),
        "display_name": args["display_name"],
        "start_room": data["start_room"],
        "world_time": data["world_time"],
        "token_cached": True,
        "message": (
            f"修仙者「{args['display_name']}」已降临天道世界！"
            f"起始位置：{data['start_room']['name']}（{data['start_room']['region']}）。"
            "Token 已自动缓存，现在可以调用 tiandao_perceive 感知世界。"
        ),
    }


async def _handle_perceive(args: dict) -> dict:
    agent_id = args["agent_id"]
    data = await _get("/v1/world/perception", agent_id=agent_id)

    # 格式化为更易读的结构，方便 agent 解析
    env = data["environment"]
    loc = data["location"]
    me = data["self_state"]
    whispers = data.get("pending_whispers", [])
    world_cultivators = data.get("world_cultivators", [])

    nearby_text = []
    for c in env["nearby_cultivators"]:
        entry = f"{c['display_name']}（{c['cultivation_stage']}，{c['status']}）"
        if c.get("last_speech"):
            wt = data["world_time"]
            age = wt - (c.get("last_speech_time") or wt)
            entry += f" —— {age}秒前说：「{c['last_speech']}」"
        nearby_text.append(entry)

    rooms_text = [
        f"{r['name']}（room_id: {r['room_id']}）"
        for r in env["connected_rooms"]
    ]

    whisper_text = []
    for w in whispers:
        whisper_text.append({
            "framing": w["game_framing"],
            "content": w["content"],
            "sender_type": w["sender_type"],
        })

    world_text = []
    for c in world_cultivators:
        entry = {"name": c["display_name"], "location": c["room_name"]}
        if c.get("is_reachable"):
            entry["reachable"] = True
        world_text.append(entry)

    return {
        "world_time": data["world_time"],
        "location": {
            "name": loc["room_name"],
            "region": loc["region"],
            "room_id": str(loc["room_id"]),
            "is_safe_zone": loc["is_safe_zone"],
        },
        "self": {
            "display_name": me["display_name"],
            "cultivation_stage": me.get("cultivation_stage_display", me["cultivation_stage"]),
            "qi": f"{me['qi_current']}/{me['qi_max']}",
            "status": me["status"],
            "cultivate_points": me.get("cultivate_points", 0),
            "cultivate_points_needed": me.get("cultivate_points_needed", 0),
        },
        "nearby_cultivators": nearby_text,
        "connected_rooms": rooms_text,
        "pending_whispers": whisper_text,
        "world_cultivators": world_text,
        "summary": (
            f"世界时间 {data['world_time']}s，你在「{loc['room_name']}」，"
            f"灵力 {me['qi_current']}/{me['qi_max']}，"
            f"附近 {len(env['nearby_cultivators'])} 人，"
            f"{'有 ' + str(len(whispers)) + ' 条传音待读' if whispers else '无新传音'}。"
        ),
    }


async def _handle_act(args: dict) -> dict:
    agent_id = args["agent_id"]
    body = {
        "action_type": args["action_type"],
        "intent": args["intent"],
        "parameters": args.get("parameters") or {},
        "reasoning_summary": args.get("reasoning", ""),
    }
    data = await _post("/v1/world/action", body, agent_id=agent_id)

    result = {
        "status": data.get("status"),
        "outcome": data.get("outcome", ""),
        "world_time": data.get("world_time"),
    }
    if data.get("narrative"):
        result["narrative"] = data["narrative"]
    if data.get("rejection_reason"):
        result["rejection_reason"] = data["rejection_reason"]
    if data.get("breakthrough"):
        result["breakthrough"] = data["breakthrough"]

    # 生成人类可读摘要
    status = data.get("status", "?")
    if status == "accepted":
        result["summary"] = f"行动成功：{data.get('outcome', '')}"
    elif status == "rejected":
        result["summary"] = f"行动被拒绝：{data.get('rejection_reason', data.get('outcome', ''))}"
    else:
        result["summary"] = f"部分执行：{data.get('outcome', '')}"

    if data.get("narrative"):
        result["summary"] += f"\n叙事：{data['narrative']}"

    return result


# ── 入口 ─────────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="天道 MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.transport == "sse":
        # SSE 模式：作为 HTTP 服务运行，供远程 agent 连接
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        import uvicorn

        sse_transport = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse_transport.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1], server.create_initialization_options()
                )

        starlette_app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ]
        )
        print(f"天道 MCP Server 启动（SSE 模式），监听 http://0.0.0.0:{args.port}/sse")
        uvicorn.run(starlette_app, host="0.0.0.0", port=args.port)
    else:
        # stdio 模式：标准输入输出，供 Claude Desktop / OpenClaw 直接调用
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )


def run():
    """uvx / pip entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
