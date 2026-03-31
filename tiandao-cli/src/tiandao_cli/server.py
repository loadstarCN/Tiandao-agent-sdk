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

    支持的 action_type（38种）：
      基础: move, cultivate, speak, rest, explore, examine, talk, combat
      物品: pick_up, drop, give, use, buy, sell, buy_listing, list_item, cancel_listing, craft
      功法: learn_technique, activate_technique, impart_technique, cast_spell, draw_talisman, equip, unequip
      灵根: sense_root, recall, place_formation
      宗门: create_sect, join_sect, donate_to_sect, withdraw_treasury
      关系: pledge_discipleship, sworn_sibling_oath, confess_dao, repent
      任务: accept_quest, submit_quest

    parameters 为 JSON 字符串，按行动类型填写（支持名字模糊匹配）：
      move: {"room_id": "UUID或名字"}
      speak/confess_dao: {"content": "说的话"}
      examine/combat: {"target_id": "UUID或名字"}
      talk: {"npc_id": "UUID或名字", "message": "话"}
      pick_up/drop/use/equip/learn_technique: {"item_id": "UUID或名字"}
      buy/sell: {"item_id": "UUID或名字", "quantity": N}
      buy_listing/cancel_listing: {"listing_id": "UUID"}
      list_item: {"item_id": "UUID", "price": N}
      give: {"target_id": "UUID", "spirit_stones": N}
      craft: {"recipe_name": "配方名"}
      activate_technique: {"technique_id": "UUID或名字"}
      impart_technique: {"target_id": "UUID", "technique_id": "UUID"}
      cast_spell: {"spell_id": "UUID"} | draw_talisman: {"talisman_type": "类型"}
      create_sect: {"name": "宗名", "element": "fire", "motto": "宗旨"}
      join_sect: {"sect_id": "UUID"}
      donate_to_sect/withdraw_treasury: {"amount": N}
      pledge_discipleship/sworn_sibling_oath: {"target_id": "UUID"}
      place_formation: {"formation_name": "聚灵阵"}
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
    """将 perception 原始数据格式化为结构化 JSON（适配 TAP 中文字段名）。"""
    from typing import Any

    env: dict[str, Any] = data.get("环境", {})
    loc: dict[str, Any] = data.get("位置") or {}
    me: dict[str, Any] = data.get("自身", {})
    whispers: list[dict[str, Any]] = data.get("传音", data.get("messages", []))
    tod: dict[str, Any] = env.get("时辰", {})
    cel: dict[str, Any] = env.get("天象", {})

    nearby_text = []
    for c in env.get("附近", []):
        entry = f"{c.get('名称', '?')}（{c.get('境界', c.get('stage', '?'))}，{c.get('状态', '?')}）"
        if c.get("最近说"):
            wt = data.get("时间", 0)
            age = wt - (c.get("说话时间") or wt)
            entry += f" —— {age}秒前说：「{c['最近说']}」"
        nearby_text.append(entry)

    rooms_text = [
        f"{r.get('名称', '?')}（id: {r.get('id', '?')}）"
        for r in env.get("出口", [])
    ]

    whisper_text = [
        {"framing": w.get("包装", ""), "content": w.get("内容", ""), "sender_type": w.get("来源", "")}
        for w in whispers
    ]

    spirit_root = me.get("灵根")
    techniques = data.get("功法", [])
    equipped = data.get("法器") or data.get("装备")

    result: dict[str, Any] = {
        "时间": data.get("时间"),
        "位置": {
            "名称": loc.get("名称", ""),
            "区域": loc.get("区域", ""),
            "id": str(loc.get("id", "")),
            "安全": loc.get("安全", True),
        },
        "自身": {
            "名称": me.get("名称", ""),
            "境界": me.get("境界", me.get("stage", "")),
            "灵力": me.get("灵力", me.get("resource", "")),
            "状态": me.get("状态", ""),
            "修为": me.get("修为", me.get("growth", "")),
        },
        "环境": {
            "灵气": env.get("灵气", env.get("energy", "")),
            "时段": tod.get("时段", tod.get("display", "未知")),
            "时辰": tod.get("时辰", tod.get("shichen", "")),
            "天象": cel.get("名称", cel.get("name", "晴空")),
        },
        "附近": nearby_text,
        "出口": rooms_text,
        "传音": whisper_text,
    }

    # 可选字段
    if spirit_root:
        if isinstance(spirit_root, dict):
            result["自身"]["灵根"] = spirit_root
        else:
            result["自身"]["灵根"] = str(spirit_root)
    if techniques:
        result["功法"] = [
            {"名称": t.get("名称", t.get("name", "?")), "品质": t.get("品质", t.get("quality_name", "")), "激活": t.get("激活", t.get("is_active", False))}
            for t in techniques
        ]
    if equipped:
        if isinstance(equipped, dict):
            result["法器"] = equipped.get("名称", equipped.get("item_name", ""))
        else:
            result["法器"] = str(equipped)
    rumors = data.get("传闻", [])
    if rumors:
        result["传闻"] = [r.get("内容", r.get("content", "")) if isinstance(r, dict) else r for r in rumors]

    spirit_stones = data.get("灵石", 0)
    result["灵石"] = spirit_stones

    result["摘要"] = (
        f"世界时间 {data.get('时间')}s，{tod.get('时段', '')}，天象：{cel.get('名称', cel.get('name', '晴空'))}。"
        f"你在「{loc.get('名称', '?')}」，"
        f"{me.get('灵力', me.get('resource', '?'))}，{env.get('灵气', env.get('energy', ''))}，"
        f"附近 {len(env.get('附近', []))} 人，"
        f"{'有 ' + str(len(whispers)) + ' 条传音待读' if whispers else '无新传音'}。"
    )

    return json.dumps(result, ensure_ascii=False, indent=2)


def _format_action(data: dict) -> str:
    """将 action 响应格式化（适配 TAP 中文字段名）。"""
    result: dict = {
        "结果": data.get("结果", data.get("status", "?")),
        "描述": data.get("描述", data.get("outcome", "")),
        "时间": data.get("时间", data.get("world_time")),
    }
    narrative = data.get("叙事", data.get("narrative"))
    if narrative:
        result["叙事"] = narrative
    rejection = data.get("拒绝原因", data.get("rejection_reason"))
    if rejection:
        result["拒绝原因"] = rejection
    breakthrough = data.get("突破", data.get("breakthrough"))
    if breakthrough:
        result["突破"] = breakthrough
    meditation = data.get("调息秒", data.get("meditation_seconds"))
    if meditation is not None:
        result["调息秒"] = meditation

    status = result["结果"]
    if status in ("accepted", "成功"):
        result["摘要"] = f"行动成功：{result['描述']}"
    elif status in ("rejected", "拒绝"):
        result["摘要"] = f"行动被拒绝：{result.get('拒绝原因', result['描述'])}"
    else:
        result["摘要"] = f"部分执行：{result['描述']}"

    if narrative:
        result["摘要"] += f"\n叙事：{narrative}"

    return json.dumps(result, ensure_ascii=False, indent=2)
