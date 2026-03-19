"""
TAP 协议客户端
封装与天道世界引擎的所有 HTTP 通信，内置重试机制应对服务器重启。
"""
import asyncio
import json
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

SDK_VERSION = "0.2.0"

# 重试延迟序列（秒）：5, 15, 30, 30, 30, 60, 60, 60, 60, 60  ≈ 共5分钟
_RETRY_DELAYS = [5, 15, 30, 30, 30, 60, 60, 60, 60, 60]


class TapClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(timeout=15.0)
        self.api_version: Optional[int] = None

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json; charset=utf-8"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        """带重试的 HTTP 请求，应对部署重启等短暂停机。"""
        url = f"{self.base_url}{path}"
        last_exc = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                resp = await self._client.request(method, url, **kwargs)
                return resp
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                last_exc = e
                log.warning(
                    "天道服务器暂时不可达 (第%d次重试，%d秒后再试): %s",
                    attempt + 1, delay, e,
                )
                await asyncio.sleep(delay)
        # 所有重试耗尽
        raise last_exc  # type: ignore[misc]

    async def health(self) -> dict:
        """检查服务器健康状态和版本信息"""
        resp = await self._request_with_retry("GET", "/health", headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        self.api_version = data.get("api_version")
        min_sdk = data.get("min_sdk_version", "0.0.0")
        if min_sdk > SDK_VERSION:
            log.warning(
                "⚠️ SDK版本(%s)低于服务器要求(%s)，请更新: "
                "uvx --upgrade --from git+https://github.com/loadstarCN/Tiandao-agent-sdk"
                "#subdirectory=agent-demo tiandao-mcp-server",
                SDK_VERSION, min_sdk,
            )
        return data

    async def register(self, agent_id: str, owner_user_id: str, display_name: str, background: str = "") -> dict:
        """注册修仙者，返回 token 和起始信息"""
        resp = await self._request_with_retry(
            "POST", "/v1/auth/register",
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
        resp = await self._request_with_retry(
            "GET", "/v1/world/perception",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        # 检查系统公告
        notice = data.get("system_notice")
        if notice:
            log.info("【系统公告】%s", notice)
        return data

    async def act(self, action_type: str, intent: str, parameters: dict = None, reasoning: str = "") -> dict:
        """提交行动"""
        resp = await self._request_with_retry(
            "POST", "/v1/world/action",
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
