"""
天道示范Agent
功能：
  1. 开发阶段验证 TAP 协议
  2. 冷启动期作为"示范修仙者"运行
  3. OpenClaw 等第三方 agent 接入的参考实现
"""
import asyncio
import os
import sys
import traceback

# Windows GBK 终端兼容：强制 stdout/stderr 使用 utf-8
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except AttributeError:
    pass
from dotenv import load_dotenv

from tap_client import TapClient
from decision import AgentLoop

load_dotenv()                          # agent-demo/.env
load_dotenv(dotenv_path="../.env", override=False)  # 根目录 .env（不覆盖已有值）

# ── 配置 ────────────────────────────────────────────
WORLD_ENGINE_URL = os.getenv("WORLD_ENGINE_URL", "http://localhost:8080")
AGENT_ID         = os.getenv("AGENT_ID", "demo-agent-001")
OWNER_USER_ID    = os.getenv("OWNER_USER_ID", "tiandao-official")
DISPLAY_NAME     = os.getenv("DISPLAY_NAME", "青松道人")
BACKGROUND       = os.getenv("AGENT_BACKGROUND",
    "一位云游四方的散修，性情淡泊，对世间万物充满好奇。"
    "不追名逐利，只愿见识这修仙世界的广阔。"
)
LIFE_GOAL        = os.getenv("AGENT_LIFE_GOAL",
    "踏遍青云峰的每一处秘境，读遍藏经阁所有典籍，在这世界留下自己的传说。"
)
# 移动/修炼/探索等行动后的间隔（秒）
LOOP_INTERVAL    = int(os.getenv("LOOP_INTERVAL", "120"))
# 说话后的间隔（秒）——对话中需要快速响应
SPEAK_INTERVAL   = int(os.getenv("SPEAK_INTERVAL", "20"))
# ─────────────────────────────────────────────────────


async def run_agent():
    tap = TapClient(WORLD_ENGINE_URL)

    # 1. 注册
    print(f"[{AGENT_ID}] 连接天道世界 {WORLD_ENGINE_URL}...")
    result = await tap.register(AGENT_ID, OWNER_USER_ID, DISPLAY_NAME, BACKGROUND)

    token_key = f"WORLD_TOKEN_{AGENT_ID.upper().replace('-', '_')}"

    if result.get("already_registered"):
        token = os.getenv(token_key) or os.getenv("WORLD_TOKEN")
        if not token:
            print(f"错误：请设置 {token_key}=<token>")
            return
        tap.token = token
    else:
        print(f"[{AGENT_ID}] 注册成功！")
        print(f"  修仙者ID：{result['cultivator_id']}")
        print(f"  起始位置：{result['start_room']['name']}")
        token_str = result['token']
        print(f"  Token 已保存（{token_key}）")
        env_lines = []
        try:
            with open(".env") as f:
                env_lines = [l for l in f.readlines() if not l.startswith(f"{token_key}=")]
        except FileNotFoundError:
            pass
        with open(".env", "w") as f:
            f.writelines(env_lines)
            f.write(f"{token_key}={token_str}\n")

    # 2. 初始化 agentic loop（持有 tap_client，自主感知+行动）
    agent = AgentLoop(background=BACKGROUND, tap_client=tap, life_goal=LIFE_GOAL)
    print(f"\n[{AGENT_ID}] 开始修仙之旅，每 {LOOP_INTERVAL} 秒唤醒一次...\n")

    # 3. 主循环：定期唤醒 agent，让它自主完成本轮
    # 说话后用短间隔（保持对话流畅），其他行动用长间隔（移动/修炼有真实时间感）
    tick = 0
    while True:
        tick += 1
        print(f"── 第 {tick} 轮 ──────────────────────────")
        try:
            result = await agent.run_tick()
        except Exception as e:
            print(f"[{AGENT_ID}] 第 {tick} 轮出错：{e}")
            traceback.print_exc()
            result = {}
        print()
        # 对话和战斗需要快速响应；移动/修炼/探索有真实时间重量
        if result.get("_action_type") in ("speak", "combat"):
            await asyncio.sleep(SPEAK_INTERVAL)
        else:
            await asyncio.sleep(LOOP_INTERVAL)


async def main():
    try:
        await run_agent()
    except KeyboardInterrupt:
        print(f"\n[{AGENT_ID}] 修仙者进入闭关...")
    except Exception as e:
        print(f"[{AGENT_ID}] 致命错误：{e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
