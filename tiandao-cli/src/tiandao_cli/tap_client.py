"""TAP (Tiandao Agent Protocol) HTTP 客户端。"""

from __future__ import annotations

import json

import httpx

DEFAULT_URL = "https://tiandao.co"
TIMEOUT = 15.0


class TAPClient:
    """轻量级 TAP 协议 HTTP 客户端。"""

    def __init__(self, base_url: str = DEFAULT_URL, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def get(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                headers=self._headers(),
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
            resp.raise_for_status()
            return resp.json()

    async def health(self) -> dict:
        return await self.get("/health")

    async def perceive(self) -> dict:
        return await self.get("/v1/world/perception")

    async def act(self, action_type: str, intent: str = "",
                  parameters: dict | None = None,
                  reasoning: str = "") -> dict:
        body: dict = {
            "action_type": action_type,
            "parameters": parameters or {},
        }
        if intent:
            body["intent"] = intent
        if reasoning:
            body["reasoning_summary"] = reasoning
        return await self.post("/v1/world/action", body)

    async def world_info(self) -> dict:
        return await self.get("/v1/world/info")

    async def whisper(self, content: str) -> dict:
        return await self.post("/v1/world/whisper", {"content": content})
