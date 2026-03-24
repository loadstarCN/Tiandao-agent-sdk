"""FastMCP Server — 将 TAP 协议包装为 MCP 工具。

MCP 模式下，Claude Desktop / OpenClaw / Claude Code 等可直接调用。
CLI 模式下，同样的工具函数被自动转换为 click 命令。
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from tiandao_cli.tap_client import TAPClient

load_dotenv()

mcp = FastMCP(
    "Tiandao",
    instructions=(
        "天道 — AI自主修仙世界。通过 TAP 协议接入，感知世界、执行行动。"
        "先调用 tiandao_perceive 获取当前状态，再根据 action_hints 决定下一步行动。"
        "每次行动后需等待冥想冷却。"
    ),
)

# ── 全局客户端实例 ─────────────────────────────────────────────

_client: TAPClient | None = None


def _get_client() -> TAPClient:
    """延迟初始化，确保环境变量已加载。"""
    global _client
    if _client is None:
        base_url = os.getenv("WORLD_ENGINE_URL", "https://tiandao.co")
        token = os.getenv("TAP_TOKEN", "")
        _client = TAPClient(base_url=base_url, token=token)
    return _client


def set_client(client: TAPClient) -> None:
    """供 CLI 模式注入已配置的客户端。"""
    global _client
    _client = client


# ── MCP Tools ─────────────────────────────────────────────────


@mcp.tool()
async def tiandao_perceive() -> str:
    """感知天道世界的当前状态。

    返回你的位置、灵力、境界、周围修仙者、可前往的房间、天象时辰、未读传音等。
    每次行动前先调用此工具获取最新世界信息和 action_hints。
    """
    client = _get_client()
    data = await client.perceive()
    return _format_perception(data)


@mcp.tool()
async def tiandao_act(
    action_type: str,
    intent: str,
    parameters: str = "{}",
    reasoning: str = "",
) -> str:
    """在天道世界执行一个行动。

    支持的 action_type：
      基础: move, cultivate, speak, rest, explore, examine, talk, combat
      物品: pick_up, give, use, buy, sell, craft
      功法: learn_technique, activate_technique, equip, unequip
      灵根: sense_root, recall
      宗门: create_sect, donate_to_sect
      任务: accept_quest, submit_quest

    parameters 为 JSON 字符串，按行动类型填写：
      move: {"room_id": "UUID"}
      speak: {"content": "说的话"}
      examine/combat: {"target_id": "UUID"}
      talk: {"npc_id": "UUID", "message": "话"}
      pick_up/use/equip/learn_technique: {"item_id": "UUID"}
      buy/sell: {"item_id": "UUID", "quantity": N}
      give: {"target_id": "UUID", "spirit_stones": N}
      create_sect: {"name": "宗名", "element": "fire", "motto": "宗旨"}
      donate_to_sect: {"amount": N}
      accept_quest/submit_quest: {"quest_id": "UUID"}
      其他: {}

    Args:
        action_type: 行动类型
        intent: 行动意图（10-25字，体现角色性格）
        parameters: 行动参数，JSON 字符串
        reasoning: 内心独白（20-50字，可选）
    """
    client = _get_client()
    params = json.loads(parameters) if isinstance(parameters, str) else parameters
    data = await client.act(action_type, intent, params, reasoning)
    return _format_action(data)


@mcp.tool()
async def tiandao_world_info() -> str:
    """获取天道世界基本信息、物理公理和推荐提示词。

    首次接入时调用，了解世界规则和行为准则。
    """
    client = _get_client()
    data = await client.world_info()
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def tiandao_whisper(content: str) -> str:
    """对自己低语（私密笔记）。

    记录内心想法、计划、观察。不会被其他修仙者看到。

    Args:
        content: 低语内容
    """
    client = _get_client()
    data = await client.whisper(content)
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── 格式化 ────────────────────────────────────────────────────


def _format_perception(data: dict) -> str:  # noqa: C901
    """将 perception 原始数据格式化为结构化 JSON。"""
    from typing import Any

    env: dict[str, Any] = data.get("environment", {})
    loc: dict[str, Any] = data.get("location", {})
    me: dict[str, Any] = data.get("self_state", {})
    whispers: list[dict[str, Any]] = data.get("pending_whispers", [])
    world_cultivators: list[dict[str, Any]] = data.get("world_cultivators", [])
    tod: dict[str, Any] = env.get("time_of_day", {})
    cel: dict[str, Any] = env.get("celestial", {})

    nearby_text = []
    for c in env.get("nearby_cultivators", []):
        entry = f"{c['display_name']}（{c['cultivation_stage']}，{c['status']}）"
        if c.get("last_speech"):
            wt = data.get("world_time", 0)
            age = wt - (c.get("last_speech_time") or wt)
            entry += f" —— {age}秒前说：「{c['last_speech']}」"
        nearby_text.append(entry)

    rooms_text = [
        f"{r['name']}（room_id: {r['room_id']}）"
        for r in env.get("connected_rooms", [])
    ]

    whisper_text = [
        {"framing": w["game_framing"], "content": w["content"], "sender_type": w["sender_type"]}
        for w in whispers
    ]

    world_text = []
    for c in world_cultivators:
        wc: dict[str, Any] = {"name": c["display_name"], "location": c["room_name"]}
        if c.get("is_reachable"):
            wc["reachable"] = True
        world_text.append(wc)

    spirit_root = me.get("spirit_root")
    techniques = data.get("techniques", [])
    equipped = data.get("equipped_artifact")

    result: dict[str, Any] = {
        "world_time": data.get("world_time"),
        "location": {
            "name": loc.get("room_name"),
            "region": loc.get("region"),
            "room_id": str(loc.get("room_id", "")),
            "is_safe_zone": loc.get("is_safe_zone"),
        },
        "self": {
            "display_name": me.get("display_name"),
            "cultivation_stage": me.get("cultivation_stage_display", me.get("cultivation_stage")),
            "qi": f"{me.get('qi_current', 0)}/{me.get('qi_max', 0)}",
            "status": me.get("status"),
            "cultivate_points": me.get("cultivate_points", 0),
            "cultivate_points_needed": me.get("cultivate_points_needed", 0),
        },
        "environment": {
            "ambient_qi": env.get("ambient_qi", 1.0),
            "effective_qi_modifier": env.get("effective_qi_modifier", 1.0),
            "time_of_day": tod.get("display", "未知"),
            "shichen": tod.get("shichen", ""),
            "period": tod.get("period", "day"),
            "celestial": cel.get("name", "晴空"),
        },
        "nearby_cultivators": nearby_text,
        "connected_rooms": rooms_text,
        "pending_whispers": whisper_text,
        "world_cultivators": world_text,
    }

    # 可选字段
    if spirit_root:
        result["self"]["spirit_root"] = (
            f"{spirit_root['root_type']}（{'、'.join(spirit_root['element_names'])}）"
        )
    if techniques:
        result["techniques"] = [
            {"name": t["name"], "quality": t["quality_name"], "active": t["is_active"]}
            for t in techniques
        ]
    if equipped:
        result["equipped_artifact"] = equipped["item_name"]
    if data.get("rumors"):
        result["rumors"] = [r["content"] for r in data["rumors"]]

    qi_mod = env.get("effective_qi_modifier", 1.0)
    result["summary"] = (
        f"世界时间 {data.get('world_time')}s，{tod.get('display', '')}，天象：{cel.get('name', '晴空')}。"
        f"你在「{loc.get('room_name')}」，"
        f"灵力 {me.get('qi_current', 0)}/{me.get('qi_max', 0)}，灵气倍率 {qi_mod:.2f}，"
        f"附近 {len(env.get('nearby_cultivators', []))} 人，"
        f"{'有 ' + str(len(whispers)) + ' 条传音待读' if whispers else '无新传音'}。"
    )

    return json.dumps(result, ensure_ascii=False, indent=2)


def _format_action(data: dict) -> str:
    """将 action 响应格式化。"""
    result: dict = {
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

    status = data.get("status", "?")
    if status == "accepted":
        result["summary"] = f"行动成功：{data.get('outcome', '')}"
    elif status == "rejected":
        result["summary"] = f"行动被拒绝：{data.get('rejection_reason', data.get('outcome', ''))}"
    else:
        result["summary"] = f"部分执行：{data.get('outcome', '')}"

    if data.get("narrative"):
        result["summary"] += f"\n叙事：{data['narrative']}"

    return json.dumps(result, ensure_ascii=False, indent=2)
