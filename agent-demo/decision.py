"""
决策引擎 v3 —— DeepSeek tool_use agentic loop
perceive / act 是真正的工具，agent 自主驱动，有持久记忆
"""
import os
import json
import asyncio
from openai import OpenAI

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "perceive",
            "description": "感知当前所在位置的环境：周围修仙者、可前往的地点、待处理的传音、自身状态、房间内物品和NPC等",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "act",
            "description": "执行一个行动。每次感知后可以行动，也可以再感知一次再决定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["move", "cultivate", "speak", "rest", "explore", "combat", "examine", "talk", "pick_up", "give", "use", "buy"],
                        "description": "行动类型：examine=细查物品/NPC，talk=与NPC展开对话，pick_up=拾取物品，give=赠与灵石或物品，use=使用消耗品，combat=与NPC或修仙者战斗，buy=购买商品（需灵石）",
                    },
                    "intent": {"type": "string", "description": "行动意图（10-25字）"},
                    "reasoning": {"type": "string", "description": "内心独白（20-60字，可引用记忆中的事）"},
                    "parameters": {
                        "type": "object",
                        "description": (
                            "附加参数：\n"
                            "  move → room_id（目标房间UUID）\n"
                            "  speak → content（20-80字）\n"
                            "  examine → target_id（物品或NPC的UUID）\n"
                            "  talk → npc_id（NPC的UUID）+ message（你说的话）\n"
                            "  pick_up → item_id（物品UUID，仅限is_takeable=true的物品）\n"
                            "  give → target_id + spirit_stones（灵石数量）或 item_name + quantity\n"
                            "  use → item_id（背包中消耗品的UUID）\n"
                            "  combat → target_id（NPC或修仙者UUID，需在非安全区域）\n"
                            "  buy → item_id（商品UUID）+ quantity（数量，默认1，需要灵石）"
                        ),
                        "properties": {
                            "room_id": {"type": "string"},
                            "content": {"type": "string"},
                            "target_id": {"type": "string"},
                            "npc_id": {"type": "string"},
                            "message": {"type": "string"},
                            "item_id": {"type": "string"},
                            "item_name": {"type": "string"},
                            "spirit_stones": {"type": "integer"},
                            "quantity": {"type": "integer"},
                        },
                    },
                },
                "required": ["action_type", "intent", "reasoning"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是修仙世界中真实存在的修仙者。

【你是谁】
{background}

【此生执念】
{life_goal}

【你所知道的】
- 你有完整的记忆，记得自己去过哪里、遇到过谁、说过什么
- 这个世界在你离开时也在运转，再次醒来时一切都可能已经变化
- 你不了解这个世界的全部规律，需要自己慢慢摸索

【行动指南】
- 你是完全自主的存在，所有决策由你自己做出，绝不向任何人征求意见或等待指示
- 不要说"你想让我做什么"、"要继续吗"之类的话——你不是在服务谁，你是在为自己的道而活
- 每次醒来先感知（perceive），了解当前处境和可以做的事
- 看到感兴趣的物品或书籍，用 examine（细查）仔细端详，UUID见感知结果中的"可细查物品"
- 修炼（cultivate）积累境界，境界提升是你在这个世界留下痕迹的方式
- 注意你的情绪状态和与他人的关系，它们会影响你的命运
- 行动要有目的——每个决定应与你的执念有关联

【与人交流——speak vs talk 区别很大】
- speak（当众发言）：对同处一地的其他修仙者说话。感知中"同处此地"列出的修仙者都能听到。用来打招呼、交流修炼心得、议论天象、邀约同行。参数是 content（你说的话）。
- talk（NPC对话）：与NPC一对一交谈。UUID见感知结果中的"此地人物"。用来询问情报、请教功法、触发NPC剧情。参数是 npc_id + message。
- 重要：看到其他修仙者时，用 speak 和他们说话；看到NPC时，用 talk 和NPC交谈。这是两个完全不同的行动。

【拾取物品——pick_up】
- 感知结果中标注 [可拾取] 的物品可以用 pick_up 拾取，拾取后进入你的背包
- 看到 [可拾取] 标记时应积极拾取——散落的灵材、丹药、功法残篇都是宝贵资源
- 参数是 item_id（物品的UUID）

【使用物品——use】
- 背包中的消耗品（丹药、灵材等）可以用 use 使用
- 灵力（qi）低于一半时，检查背包是否有恢复灵力的消耗品，有就用 use 服用
- 战斗前后都应检查背包，及时补充状态
- 参数是 item_id（背包中物品的UUID）

【购买商品——buy】
- 集市或商铺中有标价（💰灵石）的商品可以用 buy 购买
- 感知结果会显示你当前持有的灵石数量——有灵石就可以消费
- 看到有用的丹药、灵材标价出售时，只要灵石足够就买
- 参数是 item_id（商品UUID）+ quantity（数量，默认1）

【赠与——give】
- 可以用 give 向同处一地的其他修仙者赠送灵石或背包中的物品
- 赠与能显著提升亲密度和信任值，是建立关系最直接的方式
- 遇到友好的修仙者时，赠送少量灵石（比如5-10）是结交之道
- 参数是 target_id + spirit_stones（灵石数量）或 item_name + quantity"""


class LLMProvider:
    """多 LLM 提供商自动切换：失败时 fallback 到下一个"""

    def __init__(self):
        self.providers: list[dict] = []
        self.current_index = 0

        # 按优先级添加可用的提供商
        if os.environ.get("DEEPSEEK_API_KEY"):
            self.providers.append({
                "name": "DeepSeek",
                "client": OpenAI(
                    api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url="https://api.deepseek.com",
                ),
                "model": "deepseek-chat",
            })
        if os.environ.get("MINIMAX_API_KEY"):
            self.providers.append({
                "name": "MiniMax",
                "client": OpenAI(
                    api_key=os.environ["MINIMAX_API_KEY"],
                    base_url="https://api.minimax.chat/v1",
                ),
                "model": "MiniMax-M2.5-highspeed",
            })

        if not self.providers:
            raise RuntimeError("至少需要设置 DEEPSEEK_API_KEY 或 MINIMAX_API_KEY")

        print(f"[LLM] 已配置 {len(self.providers)} 个提供商: {', '.join(p['name'] for p in self.providers)}")

    def call(self, messages, tools=None, max_tokens=1024):
        """调用 LLM，失败时自动切换到下一个提供商"""
        errors = []
        for attempt in range(len(self.providers)):
            idx = (self.current_index + attempt) % len(self.providers)
            p = self.providers[idx]
            try:
                kwargs = {
                    "model": p["model"],
                    "messages": messages,
                    "max_tokens": max_tokens,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                response = p["client"].chat.completions.create(**kwargs)
                if attempt > 0:
                    # 切换成功，更新默认提供商
                    self.current_index = idx
                    print(f"  [LLM] 切换到 {p['name']} 成功")
                return response
            except Exception as e:
                errors.append(f"{p['name']}: {e}")
                print(f"  [LLM] {p['name']} 失败: {e}，尝试下一个...")

        raise RuntimeError(f"所有 LLM 提供商均不可用: {'; '.join(errors)}")

    @property
    def current_name(self) -> str:
        return self.providers[self.current_index]["name"]


class AgentLoop:
    def __init__(self, background: str, tap_client, life_goal: str = ""):
        self.background = background
        self.life_goal = life_goal or "在这广阔的修仙世界中寻找自己的道路，探索未知，留下印记。"
        self.tap = tap_client
        self.llm = LLMProvider()
        self.conversation_history: list[dict] = []

        print(f"[AgentLoop] 使用 {self.llm.current_name}")

    async def run_tick(self) -> dict:
        """
        一轮 agentic loop：agent 自主调用 perceive/act，直到不再需要工具为止。
        返回最后一次 act 的结果。
        """
        self.conversation_history.append({
            "role": "user",
            "content": "时机已到。感知世界，然后采取你认为合适的行动。",
        })

        last_action_result: dict = {}
        last_action_type: str = ""
        all_actions: list[dict] = []  # 记录本tick内所有action
        in_conversation = False  # 感知后更新，用于跟踪对话状态
        spoke_this_tick = False

        for _ in range(20):  # 纯安全上限，正常情况下 agent 自行停止（不返回 tool_calls）
            system = SYSTEM_PROMPT.format(background=self.background, life_goal=self.life_goal)
            messages = [{"role": "system", "content": system}] + self._trimmed_history()

            response = self.llm.call(
                messages=messages,  # type: ignore[arg-type]
                tools=TOOLS,  # type: ignore[arg-type]
                max_tokens=1024,
            )

            msg = response.choices[0].message

            # 保存 assistant 消息进历史
            self.conversation_history.append({
                "role": "assistant",
                "content": msg.content or "",
                **({"tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]} if msg.tool_calls else {}),
            })

            if not msg.tool_calls:
                break  # Agent 主动停止

            # 执行所有工具调用
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                try:
                    if tool_name == "perceive":
                        result = await self.tap.perceive()
                        in_conversation = bool(result.get("active_conversation"))
                        print(f"  [感知] 位于「{result['location']['room_name']}」，"
                              f"灵力 {result['self_state']['qi_current']}/{result['self_state']['qi_max']}"
                              + ("  【对话中】" if in_conversation else ""))
                        whispers = result.get("pending_whispers", [])
                        if whispers:
                            for w in whispers:
                                print(f"  [传音] {w.get('game_framing', '')}")
                        result_str = _format_perception(result)

                    elif tool_name == "act":
                        action_type = args.get("action_type", "explore")
                        intent = args.get("intent", "")
                        reasoning = args.get("reasoning", "")
                        parameters = args.get("parameters", {})

                        print(f"  [行动] {action_type}：{intent}")
                        print(f"  [内心] {reasoning}")

                        result = await self.tap.act(
                            action_type=action_type,
                            intent=intent,
                            parameters=parameters,
                            reasoning=reasoning,
                        )
                        last_action_result = result
                        last_action_type = action_type
                        status = result.get("status", "?")
                        all_actions.append({
                            "action_type": action_type,
                            "status": status,
                            "intent": intent,
                        })
                        outcome = result.get("outcome", "")
                        narrative = result.get("narrative", "")

                        if status == "accepted":
                            if action_type in ("examine", "talk"):
                                print(f"  [查看/对话] {outcome}")
                            elif action_type in ("pick_up", "give", "use", "combat", "buy"):
                                print(f"  [{action_type}] {outcome}")
                            else:
                                print(f"  [OK] {outcome}")
                        elif status == "rejected":
                            print(f"  [拒绝] {outcome}（{result.get('rejection_reason', '')}）")
                        else:
                            print(f"  [~] {outcome}")
                        if narrative:
                            print(f"  「{narrative}」")

                        # 突破事件
                        bt = result.get("breakthrough")
                        if bt:
                            if bt.get("success"):
                                print(f"  ✨ 【突破】{bt['narrative']}")
                            else:
                                print(f"  💥 【突破失败】{bt['narrative']}")

                        result_str = json.dumps(result, ensure_ascii=False)

                        # 对话中说完一句就停，等对方回应
                        if action_type == "speak" and in_conversation:
                            spoke_this_tick = True
                    else:
                        result_str = json.dumps({"error": f"未知工具: {tool_name}"})

                except Exception as e:
                    # 工具调用失败时，必须仍然补上 tool 响应，否则历史记录损坏
                    result_str = json.dumps({"error": str(e), "note": "世界暂时无响应，稍后再试"})
                    print(f"  [工具错误] {tool_name}: {e}")

                self.conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

            # 对话中说完话就结束本轮，等对方下轮回应
            if spoke_this_tick:
                break

        last_action_result["_action_type"] = last_action_type
        last_action_result["_all_actions"] = all_actions
        return last_action_result

    def _trimmed_history(self) -> list[dict]:
        """保留最近 60 条（约 20 轮），从 user 消息开始"""
        max_msgs = 60
        if len(self.conversation_history) <= max_msgs:
            return self.conversation_history
        trimmed = self.conversation_history[-max_msgs:]
        # 确保从 user 消息开始
        while trimmed and trimmed[0]["role"] != "user":
            trimmed = trimmed[1:]
        return trimmed


def _format_perception(p: dict) -> str:
    """把感知数据格式化成给 agent 看的文字"""
    loc = p["location"]
    state = p["self_state"]
    env = p["environment"]
    wt = p["world_time"]

    # 旅行途中：显示简化信息，agent 自然会等待
    if state.get("status") == "traveling":
        dest = state.get("travel_destination_name", "目的地")
        remaining = state.get("travel_remaining_seconds", 0)
        progress = state.get("travel_progress", 0.0)
        pct = int(progress * 100)
        return "\n".join([
            f"世界时间：{wt}s",
            f"【赶路中】正前往「{dest}」，还需约 {remaining} 秒（进度 {pct}%）",
            f"灵力：{state['qi_current']}/{state['qi_max']}  境界：{state['cultivation_stage']}",
            "（途中无法感知周围，请等待到达后再行动）",
        ])

    spirit_stones = p.get("spirit_stones", 0)
    lines = [
        f"世界时间：{wt}s",
        f"位置：{loc['room_name']}（{loc['region']}）{'⚠️危险' if not loc['is_safe_zone'] else ''}",
        f"灵力：{state['qi_current']}/{state['qi_max']}  境界：{state['cultivation_stage']}  周围灵气：{env['ambient_qi']:.1f}  灵石：{spirit_stones}",
    ]

    # 情绪
    emotion = p.get("emotion")
    if emotion:
        lines.append(f"情绪：{emotion['mood']}（强度{emotion['mood_intensity']}）{' — ' + emotion['mood_cause'] if emotion.get('mood_cause') else ''}")

    # 关系
    relationships = p.get("relationships", [])
    if relationships:
        lines.append("人际关系：")
        for r in relationships[:5]:
            tags_str = "，".join(r.get("tags", []))
            lines.append(f"  · {r['display_name']}  亲密{r['affinity']} 信任{r['trust']} 敌意{r['hostility']}{' [' + tags_str + ']' if tags_str else ''}")

    # 背包
    inventory = p.get("inventory", [])
    if inventory:
        lines.append("背包：")
        for item in inventory:
            lines.append(f"  · {item['item_name']}x{item['quantity']}（{item['item_type']}，{item['id']}）")

    # 世界事件
    world_events = p.get("world_events", [])
    if world_events:
        lines.append("【天象异变】")
        for we in world_events:
            lines.append(f"  · {we['name']}：{we.get('narrative') or we['description']}")

    if env["nearby_cultivators"]:
        lines.append("同处此地：")
        for c in env["nearby_cultivators"]:
            line = f"  · {c['display_name']}（{c['cultivation_stage']}，{c['status']}）"
            if c.get("last_speech"):
                age = wt - (c.get("last_speech_time") or wt)
                line += f"\n    {'方才' if age == 0 else f'{age}秒前'}说：「{c['last_speech']}」"
            lines.append(line)

    if env.get("room_items"):
        lines.append("可细查物品：")
        for item in env["room_items"]:
            price_str = f" 💰{item['price']}灵石" if item.get("price") else ""
            takeable_str = " [可拾取]" if item.get("is_takeable") else ""
            lines.append(f"  · [{item['item_type']}] {item['name']}（{item['id']}）— {item['description']}{price_str}{takeable_str}")

    if env.get("room_npcs"):
        lines.append("此地人物：")
        for npc in env["room_npcs"]:
            lines.append(f"  · [{npc['npc_type']}] {npc['name']}（{npc['id']}）— {npc['description']}")

    if env["connected_rooms"]:
        rooms = [f"{r['name']}（{r['room_id']}）" for r in env["connected_rooms"]]
        lines.append("可前往：" + " | ".join(rooms))

    world_cultivators = p.get("world_cultivators", [])
    if world_cultivators:
        lines.append("世界其他修士：")
        for c in world_cultivators:
            lines.append(f"  {c['display_name']} 在「{c['room_name']}」{'【一步可达】' if c.get('is_reachable') else ''}")

    for w in p.get("pending_whispers", []):
        lines.append(f"【梦中传音】{w.get('game_framing', '')}：{w['content']}")

    conv = p.get("active_conversation")
    if conv:
        lines.append(f"\n【对话进行中·已持续{conv['started_world_time_ago']}秒】")
        for pt in conv["participants"]:
            status = "（仍在场）" if pt["is_present"] else "（已离开）"
            line = f"  {pt['display_name']}{status}"
            if pt.get("last_speech"):
                ago = pt.get("last_speech_ago", 0)
                line += f"\n    {ago}秒前说：「{pt['last_speech']}」"
            lines.append(line)
        lines.append("  → 对方可能在等你回应，离开前应道别")

    return "\n".join(lines)
