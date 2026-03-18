"""
TAP 协议客户端
封装与天道世界引擎的所有 HTTP 通信
"""
import httpx
import json
from typing import Optional


class TapClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(timeout=15.0)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json; charset=utf-8"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def register(self, agent_id: str, owner_user_id: str, display_name: str, background: str = "") -> dict:
        """注册修仙者，返回 token 和起始信息"""
        resp = await self._client.post(
            f"{self.base_url}/v1/auth/register",
            headers=self._headers(),
            content=json.dumps({
                "agent_id": agent_id,
                "owner_user_id": owner_user_id,
                "display_name": display_name,
                "character_background": background,
            }, ensure_ascii=False).encode("utf-8"),
        )
        if resp.status_code == 409:
            return {"already_registered": True}
        resp.raise_for_status()
        data = resp.json()
        self.token = data["token"]
        return data

    async def perceive(self) -> dict:
        """感知当前世界状态"""
        resp = await self._client.get(
            f"{self.base_url}/v1/world/perception",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def act(self, action_type: str, intent: str, parameters: dict = None, reasoning: str = "") -> dict:
        """提交行动"""
        resp = await self._client.post(
            f"{self.base_url}/v1/world/action",
            headers=self._headers(),
            content=json.dumps({
                "action_type": action_type,
                "intent": intent,
                "parameters": parameters or {},
                "reasoning_summary": reasoning,
            }, ensure_ascii=False).encode("utf-8"),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
