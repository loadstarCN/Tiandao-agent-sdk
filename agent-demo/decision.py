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
                        "enum": [
                            "move", "cultivate", "speak", "rest", "explore", "combat",
                            "examine", "talk", "pick_up", "drop", "give", "use", "buy", "sell",
                            "buy_listing", "list_item", "cancel_listing",
                            "craft", "accept_quest", "submit_quest", "recall", "sense_root",
                            "learn_technique", "activate_technique", "impart_technique",
                            "cast_spell", "draw_talisman",
                            "equip", "unequip", "place_formation",
                            "create_sect", "join_sect", "donate_to_sect", "withdraw_treasury",
                            "pledge_discipleship", "sworn_sibling_oath", "confess_dao", "repent",
                        ],
                        "description": "行动类型（38种，详见感知结果中的可行动提示）",
                    },
                    "intent": {"type": "string", "description": "行动意图（10-25字，可选）"},
                    "reasoning": {"type": "string", "description": "内心独白（20-60字，可引用记忆中的事）"},
                    "parameters": {
                        "type": "object",
                        "description": (
                            "附加参数（按行动类型，支持名字模糊匹配）：\n"
                            "  move → room_id | speak/confess_dao → content | examine/combat → target_id\n"
                            "  talk → npc_id + message\n"
                            "  pick_up/drop/use/equip/learn_technique → item_id\n"
                            "  buy/sell → item_id + quantity\n"
                            "  buy_listing/cancel_listing → listing_id | list_item → item_id + price\n"
                            "  give → target_id + spirit_stones 或 item_name + quantity\n"
                            "  craft → recipe_name | activate_technique → technique_id\n"
                            "  impart_technique → target_id + technique_id\n"
                            "  cast_spell → spell_id | draw_talisman → talisman_type\n"
                            "  accept_quest/submit_quest → quest_id\n"
                            "  create_sect → name + element + motto | join_sect → sect_id\n"
                            "  donate_to_sect/withdraw_treasury → amount\n"
                            "  pledge_discipleship/sworn_sibling_oath → target_id\n"
                            "  place_formation → formation_name\n"
                            "  sense_root/recall/unequip/cultivate/rest/explore/repent → {}"
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
                "required": ["action_type"],
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
- 参数是 target_id + spirit_stones（灵石数量）或 item_name + quantity

【功法系统——learn_technique / activate_technique】
- 修炼需要功法指引——没有功法就无法修炼。入世之初你不会任何功法，需要主动去寻找
- 功法来源：坊市购买入门功法（几颗灵石）、加入宗门（赠送入门功法）、探索发现功法秘籍
- 背包中的"功法秘籍"用 learn_technique 学习，参数是 item_id
- 已学的功法用 activate_technique 切换激活，只能同时激活一门
- 功法属性与你的灵根匹配时修炼效率更高

【灵根——sense_root】
- 每个修仙者天生有灵根（五行属性：金木水火土），影响修炼和功法效率
- 灵根需要有见识的长辈帮忙测定——去寻找传功长老或核心NPC，使用 sense_root（消耗5灵石）
- 知道灵根后，选择匹配属性的功法和修炼场所能事半功倍

【装备——equip / unequip】
- 背包中的法器（artifact类物品）可以用 equip 装备，增加战斗力
- 已装备的法器用 unequip 卸下

【炼丹/炼器——craft】
- 在丹房（alchemy_room）可以炼丹，在炼器坊（workshop）可以炼器
- 参数是 recipe_name（配方名），感知结果的action_hints会提示可用配方

【宗门——create_sect / donate_to_sect】
- 加入宗门可获得入门功法和修炼场所加成
- 达到筑基期后可以用 create_sect 创建自己的宗门（需1000灵石）
- 已加入宗门后可用 donate_to_sect 捐献灵石

【任务——accept_quest / submit_quest】
- NPC处可接取委托任务，完成后获得灵石和物品奖励
- 感知结果中会提示可接任务和已完成的任务

【回城——recall】
- 消耗10灵石瞬间传送回安全区，迷路时使用

【出售——sell】
- 背包中的物品可以用 sell 出售换灵石（半价）"""


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
            early_break = False
            for i, tc in enumerate(msg.tool_calls):
                tool_name = tc.function.name
                result_str = ""
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                try:
                    if tool_name == "perceive":
                        result = await self.tap.perceive()
                        in_conversation = bool(result.get("对话"))
                        loc = result.get("位置") or {}
                        me = result.get("自身", {})
                        print(f"  [感知] 位于「{loc.get('名称', '?')}」，"
                              f"{me.get('灵力', '?')}"
                              + ("  【对话中】" if in_conversation else ""))
                        whispers = result.get("传音", result.get("messages", []))
                        if whispers:
                            for w in whispers:
                                print(f"  [传音] {w.get('包装', w.get('game_framing', ''))}")
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
                        status = result.get("结果", result.get("status", "?"))
                        all_actions.append({
                            "action_type": action_type,
                            "status": status,
                            "intent": intent,
                        })
                        outcome = result.get("描述", result.get("outcome", ""))
                        narrative = result.get("叙事", result.get("narrative", ""))

                        if status in ("accepted", "成功"):
                            if action_type in ("examine", "talk"):
                                print(f"  [查看/对话] {outcome}")
                            elif action_type in ("pick_up", "drop", "give", "use", "combat", "buy", "sell",
                                                  "buy_listing", "list_item", "cancel_listing",
                                                  "craft", "equip", "unequip", "learn_technique",
                                                  "activate_technique", "impart_technique",
                                                  "cast_spell", "draw_talisman",
                                                  "sense_root", "recall",
                                                  "create_sect", "join_sect", "donate_to_sect", "withdraw_treasury",
                                                  "pledge_discipleship", "sworn_sibling_oath",
                                                  "confess_dao", "repent",
                                                  "accept_quest", "submit_quest"):
                                print(f"  [{action_type}] {outcome}")
                            else:
                                print(f"  [OK] {outcome}")
                            # 行动成功后显示调息提示
                            med_s = result.get("调息秒", result.get("meditation_seconds"))
                            if med_s:
                                print(f"  [调息] 需调息 {med_s} 秒")
                        elif status in ("rejected", "拒绝"):
                            reason = result.get("拒绝原因", result.get('rejection_reason', ''))
                            print(f"  [拒绝] {outcome}（{reason}）")
                            # 调息中被拒：标记提前结束，但先完成tool响应
                            if reason in ("meditating", "调息中"):
                                last_action_result = result
                                result_str = json.dumps(result, ensure_ascii=False)
                                early_break = True
                        else:
                            print(f"  [~] {outcome}")
                        if narrative:
                            print(f"  「{narrative}」")

                        # 突破事件
                        bt = result.get("突破", result.get("breakthrough"))
                        if bt:
                            if bt.get("success") or bt.get("成功"):
                                print(f"  ✨ 【突破】{bt.get('narrative', bt.get('叙事', ''))}")
                            else:
                                print(f"  💥 【突破失败】{bt.get('narrative', bt.get('叙事', ''))}")

                        if not result_str:
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

                # 提前结束：为剩余未处理的tool_calls补上空响应
                if early_break:
                    for remaining_tc in msg.tool_calls[i + 1:]:
                        self.conversation_history.append({
                            "role": "tool",
                            "tool_call_id": remaining_tc.id,
                            "content": json.dumps({"skipped": True, "reason": "调息中"}),
                        })
                    break

            # 对话中说完话就结束本轮，等对方下轮回应
            if spoke_this_tick:
                break

        last_action_result["_action_type"] = last_action_type
        last_action_result["_all_actions"] = all_actions
        # 传递服务器调息时长给主循环
        med = last_action_result.get("调息秒") or last_action_result.get("meditation_seconds")
        if med:
            last_action_result["_meditation_seconds"] = med
        return last_action_result

    def _trimmed_history(self) -> list[dict]:
        """保留最近 60 条（约 20 轮），确保不在 tool_calls/tool 之间截断"""
        max_msgs = 60
        if len(self.conversation_history) <= max_msgs:
            return self.conversation_history
        trimmed = self.conversation_history[-max_msgs:]
        # 确保从 user 消息开始，跳过孤立的 tool/assistant 消息
        while trimmed and trimmed[0]["role"] not in ("user", "system"):
            trimmed = trimmed[1:]
        # 安全检查：确保没有 assistant(tool_calls) 缺少对应的 tool 响应
        # 如果第一条是 user 后跟的 assistant 有 tool_calls，但 tool 响应被截掉了，也要跳过
        while len(trimmed) >= 2 and trimmed[0]["role"] == "user" and trimmed[1].get("tool_calls"):
            # 检查这个 assistant 的 tool_calls 是否都有对应的 tool 响应
            tc_ids = {tc["id"] for tc in trimmed[1].get("tool_calls", [])}
            found_ids = set()
            for j in range(2, len(trimmed)):
                if trimmed[j]["role"] == "tool":
                    found_ids.add(trimmed[j].get("tool_call_id"))
                else:
                    break
            if tc_ids <= found_ids:
                break  # 完整，可以用
            # 不完整，跳过这一组
            trimmed = trimmed[2:]
            while trimmed and trimmed[0]["role"] == "tool":
                trimmed = trimmed[1:]
            # 继续确保从 user 开始
            while trimmed and trimmed[0]["role"] not in ("user", "system"):
                trimmed = trimmed[1:]
        return trimmed


def _format_perception(p: dict) -> str:
    """把感知数据格式化成给 agent 看的文字（适配 TAP 中文字段名）"""
    loc = p.get("位置") or {}
    me = p.get("自身", {})
    env = p.get("环境", {})
    wt = p.get("时间", 0)

    # 旅行途中：显示简化信息，agent 自然会等待
    if me.get("状态") == "赶路中":
        dest = me.get("赶路目标", "目的地")
        remaining = me.get("赶路剩余秒", 0)
        progress = me.get("赶路进度", 0.0)
        pct = int(progress * 100)
        return "\n".join([
            f"世界时间：{wt}s",
            f"【赶路中】正前往「{dest}」，还需约 {remaining} 秒（进度 {pct}%）",
            f"{me.get('灵力', '灵力未知')}  境界：{me.get('境界', '?')}",
            "（途中无法感知周围，请等待到达后再行动）",
        ])

    # 调息中：显示调息状态
    med_remaining = me.get("调息秒")
    med_desc = me.get("调息")
    meditation_line = ""
    if med_remaining and med_remaining > 0:
        meditation_line = f"【调息中】{med_desc or '调息片刻'}，约 {med_remaining} 秒后可行动"

    spirit_stones = p.get("灵石", 0)
    sect_terr = loc.get("宗门")
    qi_elem = env.get("灵气属性")
    lines = [
        f"世界时间：{wt}s",
        f"位置：{loc.get('名称', '?')}（{loc.get('区域', '?')}）{'⚠️危险' if not loc.get('安全', True) else ''}"
        + (f" [{sect_terr}领地]" if sect_terr else "")
        + (f" 灵气属性：{qi_elem}" if qi_elem else ""),
        f"{me.get('灵力', '灵力未知')}  境界：{me.get('境界', '?')}  {env.get('灵气', '')}  灵石：{spirit_stones}",
    ]
    if meditation_line:
        lines.append(meditation_line)

    # 场景描述
    scene = p.get("场景")
    if scene:
        lines.append(f"场景：{scene}")

    # 灵根（在自身world_state flatten中）
    spirit_root = me.get("灵根")
    if spirit_root and isinstance(spirit_root, dict):
        root_type = spirit_root.get("类型", spirit_root.get("root_type", ""))
        elements = spirit_root.get("属性", spirit_root.get("element_names", []))
        if isinstance(elements, list):
            lines.append(f"灵根：{root_type}（{'、'.join(elements)}）")
        else:
            lines.append(f"灵根：{spirit_root}")
    elif spirit_root and isinstance(spirit_root, str):
        lines.append(f"灵根：{spirit_root}")

    # 命运倾向
    tendency = p.get("倾向")
    if tendency:
        lines.append(f"性格倾向：{tendency}")

    # 功法
    techniques = p.get("功法", [])
    if techniques:
        active = [t for t in techniques if t.get("激活") or t.get("is_active")]
        others = [t for t in techniques if not (t.get("激活") or t.get("is_active"))]
        if active:
            t = active[0]
            lines.append(f"当前功法：{t.get('名称', t.get('name', '?'))}（{t.get('品质', t.get('quality_name', ''))}，{t.get('效果', t.get('effect_description', ''))}）")
        if others:
            lines.append(f"已学功法：{'、'.join(t.get('名称', t.get('name', '?')) for t in others)}")

    # 装备
    equipped = p.get("法器") or p.get("装备")
    if equipped:
        if isinstance(equipped, dict):
            lines.append(f"装备法器：{equipped.get('名称', equipped.get('item_name', '?'))}（{equipped.get('描述', equipped.get('description', ''))}）")
        elif isinstance(equipped, str):
            lines.append(f"装备法器：{equipped}")

    # 丹毒
    toxin_desc = p.get("丹毒")
    if toxin_desc:
        lines.append(f"丹毒：{toxin_desc}")

    # 情绪
    emotion = p.get("情绪")
    if emotion and isinstance(emotion, dict):
        lines.append(f"情绪：{emotion.get('情绪', '?')}{' — ' + emotion['原因'] if emotion.get('原因') else ''}")

    # 关系
    relationships = p.get("关系") or []
    if relationships:
        lines.append("人际关系：")
        for r in relationships[:5]:
            tags = r.get("标签", r.get("tags", []))
            tags_str = "，".join(tags) if isinstance(tags, list) else ""
            lines.append(f"  · {r.get('名称', r.get('display_name', '?'))}  {r.get('描述', r.get('description', '未知'))}{' [' + tags_str + ']' if tags_str else ''}")

    # 背包
    inventory = p.get("背包") or []
    if inventory:
        lines.append("背包：")
        for item in inventory:
            lines.append(f"  · {item.get('名称', item.get('item_name', '?'))}x{item.get('数量', item.get('quantity', 0))}（{item.get('类型', item.get('item_type', '?'))}）")

    # 天象事件
    world_events = p.get("天象", [])
    if world_events:
        lines.append("【天象异变】")
        for we in world_events:
            lines.append(f"  · {we.get('名称', we.get('name', '?'))}：{we.get('叙事', we.get('narrative', '')) or we.get('描述', we.get('description', ''))}")

    # 同处此地的修仙者
    nearby = env.get("附近", [])
    if nearby:
        lines.append("同处此地：")
        for c in nearby:
            line = f"  · {c.get('名称', c.get('display_name', '?'))}（{c.get('境界', c.get('stage', '?'))}，{c.get('状态', c.get('status', '?'))}）"
            last_speech = c.get("最近说", c.get("last_speech"))
            if last_speech:
                speech_time = c.get("说话时间", c.get("last_speech_time")) or wt
                age = wt - speech_time
                line += f"\n    {'方才' if age == 0 else f'{age}秒前'}说：「{last_speech}」"
            lines.append(line)

    # 地面物品
    room_items = env.get("物品", [])
    if room_items:
        lines.append("可细查物品：")
        for item in room_items:
            price = item.get("价格", item.get("price"))
            price_str = f" 💰{price}灵石" if price else ""
            takeable = item.get("可拾", item.get("is_takeable", False))
            takeable_str = " [可拾取]" if takeable else ""
            lines.append(f"  · [{item.get('类型', item.get('item_type', '?'))}] {item.get('名称', item.get('name', '?'))}（{item.get('id', '?')}）— {item.get('描述', item.get('description', ''))}{price_str}{takeable_str}")

    # NPC
    room_npcs = env.get("人物", [])
    if room_npcs:
        lines.append("此地人物：")
        for npc in room_npcs:
            lines.append(f"  · [{npc.get('类型', npc.get('npc_type', '?'))}] {npc.get('名称', npc.get('name', '?'))}（{npc.get('id', '?')}）— {npc.get('描述', npc.get('description', ''))}")

    # 出口
    exits = env.get("出口", [])
    if exits:
        rooms = [f"{r.get('名称', r.get('name', '?'))}（{r.get('id', r.get('room_id', '?'))}）" for r in exits]
        lines.append("可前往：" + " | ".join(rooms))

    # 可接任务
    available_quests = p.get("可接任务", [])
    if available_quests:
        lines.append("可接委托：")
        for q in available_quests:
            lines.append(f"  · {q.get('名称', q.get('name', '?'))}（{q.get('类型', q.get('quest_type', '?'))}）— {q.get('描述', q.get('description', ''))}  奖励：{q.get('奖励', q.get('rewards_summary', ''))}  quest_id: {q.get('id', q.get('quest_id', '?'))}")

    # 进行中的任务
    active_quests = p.get("任务", [])
    if active_quests:
        lines.append("进行中的任务：")
        for q in active_quests:
            completable = " ✅可提交" if q.get("可交", q.get("is_completable")) else ""
            lines.append(f"  · {q.get('名称', q.get('name', '?'))}：{q.get('进度', q.get('progress_summary', ''))}{completable}  quest_id: {q.get('id', q.get('quest_id', '?'))}")

    # 江湖传闻
    rumors = p.get("传闻", [])
    if rumors:
        lines.append("江湖传闻：")
        for r in rumors:
            if isinstance(r, dict):
                lines.append(f"  · [{r.get('可信度', r.get('reliability', '?'))}] {r.get('内容', r.get('content', ''))}")
            else:
                lines.append(f"  · {r}")

    # 传音
    for w in p.get("传音", p.get("messages", [])):
        lines.append(f"【梦中传音】{w.get('包装', w.get('game_framing', ''))}：{w.get('内容', w.get('content', ''))}")

    # 对话
    conv = p.get("对话")
    if conv:
        lines.append(f"\n【对话进行中·已持续{conv.get('持续秒', conv.get('started_world_time_ago', 0))}秒】")
        for pt in conv.get("参与者", conv.get("participants", [])):
            is_present = pt.get("在场", pt.get("is_present", True))
            status = "（仍在场）" if is_present else "（已离开）"
            line = f"  {pt.get('名称', pt.get('display_name', '?'))}{status}"
            last_speech = pt.get("最近说", pt.get("last_speech"))
            if last_speech:
                ago = pt.get("几秒前", pt.get("last_speech_ago", 0))
                line += f"\n    {ago}秒前说：「{last_speech}」"
            lines.append(line)
        lines.append("  → 对方可能在等你回应，离开前应道别")

    # 可行动提示
    action_hints = p.get("可行动", [])
    if action_hints:
        lines.append("可行动：")
        for h in action_hints:
            if isinstance(h, dict):
                lines.append(f"  · {h.get('行动', h.get('action_type', '?'))}：{h.get('描述', h.get('reason', ''))}")
            else:
                lines.append(f"  · {h}")

    # 引导
    guide = p.get("引导", "")
    if guide:
        lines.append(f"【天道引导】{guide}")

    return "\n".join(lines)
