"""
多 Agent 快速启动器
用法: python launch_multi.py [agent数量, 默认3]
每个 agent 有不同性格和执念，共同在天道世界中生活
"""
import asyncio
import os
import sys
import traceback

try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from dotenv import load_dotenv
load_dotenv()
load_dotenv(dotenv_path="../.env", override=False)

from tap_client import TapClient
from decision import AgentLoop

WORLD_ENGINE_URL = os.getenv("WORLD_ENGINE_URL", "http://localhost:8080")

# 预设角色（可扩展）
AGENT_PROFILES = [
    {
        "agent_id": "demo-agent-001",
        "display_name": "青松道人",
        "background": "一位云游四方的散修，性情淡泊，对世间万物充满好奇。不追名逐利，只愿见识这修仙世界的广阔。",
        "life_goal": "踏遍青云峰的每一处秘境，读遍藏经阁所有典籍，在这世界留下自己的传说。",
    },
    {
        "agent_id": "demo-agent-002",
        "display_name": "赤霄",
        "background": "出身寒微的孤儿，被游方道人捡回山门。性格刚烈果决，不服输，渴望以实力证明自己。对弱者心怀同情，对欺压者毫不留情。",
        "life_goal": "成为最强的修仙者。击败所有挡路的敌人，积累灵石和法宝，站到修仙界的顶端。",
    },
    {
        "agent_id": "demo-agent-003",
        "display_name": "月婵",
        "background": "一位温婉聪慧的女修，精通丹术与阵法。她相信万物有灵，修炼不在于力量的堆叠，而在于对天地法则的领悟。喜欢与人交谈，善于察言观色。",
        "life_goal": "寻找志同道合的同修，建立深厚的人际关系。她希望能帮助更多人，同时探索丹药和灵材的奥秘。",
    },
    {
        "agent_id": "demo-agent-004",
        "display_name": "玄铁老人",
        "background": "一位沉默寡言的老修士，曾经是某个大宗门的长老，因一场变故隐姓埋名。他行事低调，但偶尔流露出的见识表明他绝非凡人。",
        "life_goal": "寻找隐藏在世界角落的秘密，探索每一个危险区域。他在寻找某种失落已久的东西。",
    },
    {
        "agent_id": "demo-agent-005",
        "display_name": "灵犀",
        "background": "一位年轻而天赋异禀的修仙者，对一切新鲜事物充满热情。她喜欢收集奇珍异宝，对灵石有着近乎执念的热爱。精于交易和商业往来。",
        "life_goal": "成为天道世界最富有的修仙者。收集所有珍稀物品，在集市中买卖积累财富，与每一个修仙者建立贸易关系。",
    },
]

LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", "60"))
SPEAK_INTERVAL = int(os.getenv("SPEAK_INTERVAL", "15"))


async def run_single_agent(profile: dict, index: int):
    """运行单个 agent 的生命循环"""
    agent_id = profile["agent_id"]
    tap = TapClient(WORLD_ENGINE_URL)

    # 注册
    print(f"[{profile['display_name']}] 正在入世...")
    result = await tap.register(
        agent_id, "tiandao-official",
        profile["display_name"], profile["background"]
    )

    token_key = f"WORLD_TOKEN_{agent_id.upper().replace('-', '_')}"

    if result.get("already_registered"):
        token = os.getenv(token_key) or os.getenv("WORLD_TOKEN")
        if not token:
            print(f"[{profile['display_name']}] 需要 token: {token_key}")
            return
        tap.token = token
        print(f"[{profile['display_name']}] 已重新连接")
    else:
        print(f"[{profile['display_name']}] 入世成功 → {result['start_room']['name']}")
        token_str = result["token"]
        # 保存 token
        env_lines = []
        try:
            with open(".env") as f:
                env_lines = [l for l in f.readlines() if not l.startswith(f"{token_key}=")]
        except FileNotFoundError:
            pass
        with open(".env", "a" if env_lines else "w") as f:
            if not env_lines:
                f.write("")
            f.write(f"{token_key}={token_str}\n")

        # 检测前世
        if result.get("past_life"):
            pl = result["past_life"]
            print(f"  ✦ 前世：{pl['display_name']}（{pl['final_stage']}），因{pl['death_cause']}而亡")

    # 启动 agent loop
    agent = AgentLoop(
        background=profile["background"],
        tap_client=tap,
        life_goal=profile["life_goal"],
    )

    # 错开启动时间，避免所有 agent 同时行动
    await asyncio.sleep(index * 5)

    tick = 0
    while True:
        tick += 1
        print(f"\n── [{profile['display_name']}] 第 {tick} 轮 ──")
        try:
            result = await agent.run_tick()
        except Exception as e:
            print(f"[{profile['display_name']}] 出错：{e}")
            traceback.print_exc()
            result = {}

        # 服务器调息机制：优先使用服务器返回的调息时间
        meditation_secs = result.get("_meditation_seconds")
        if meditation_secs and meditation_secs > 0:
            wait = meditation_secs + 3
            print(f"  [{profile['display_name']}] [调息] 等待 {wait}s")
            await asyncio.sleep(wait)
        elif result.get("_action_type") in ("speak", "combat"):
            await asyncio.sleep(SPEAK_INTERVAL)
        else:
            await asyncio.sleep(LOOP_INTERVAL)


async def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    count = min(count, len(AGENT_PROFILES))

    profiles = AGENT_PROFILES[:count]
    print(f"=== 天道多 Agent 启动器 ===")
    print(f"启动 {count} 个修仙者：{', '.join(p['display_name'] for p in profiles)}")
    print(f"世界引擎：{WORLD_ENGINE_URL}")
    print(f"行动间隔：{LOOP_INTERVAL}s / 对话间隔：{SPEAK_INTERVAL}s")
    print()

    tasks = [
        asyncio.create_task(run_single_agent(profile, i))
        for i, profile in enumerate(profiles)
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("\n所有修仙者进入闭关...")
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n天道归寂。")
