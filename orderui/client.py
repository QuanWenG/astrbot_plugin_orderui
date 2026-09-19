"""Small QQ OpenAPI client with per-AppID credentials and quotas."""

import asyncio
import time
from collections import defaultdict, deque

import aiohttp

from .errors import OrderUIError, UncertainWrite

API_ROOT = "https://api.bot.qq.com"


class QQClient:
    def __init__(self, session=None, clock=time.monotonic):
        self.session = session
        self.clock = clock
        self.tokens = {}
        self.token_locks = defaultdict(asyncio.Lock)
        self.quotas = defaultdict(deque)

    async def start(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))

    async def close(self):
        if self.session:
            await self.session.close()
        self.tokens.clear()

    def reserve(self, appid, method, path):
        window = 60
        if path.startswith(("/v2/users/", "/v2/groups/")) and path.endswith("/messages"):
            bucket, limit, window = "messages", 100, 1
        elif path == "/v2/menu":
            bucket, limit = "menu", 30 if method == "GET" else 5
        elif path.endswith("/target"):
            bucket, limit = "target", 60
        else:
            bucket = "panels" if path == "/v2/panels" else "panel"
            limit = 30 if method == "GET" else 10
        history = self.quotas[(appid, method, bucket)]
        now = self.clock()
        while history and now - history[0] >= window:
            history.popleft()
        if len(history) >= limit:
            wait = max(1, int(window - (now - history[0])) + 1)
            raise OrderUIError(
                f"请求过于频繁，请在 {wait} 秒后重试", "rate_limit", details={"retry_after": wait}
            )
        history.append(now)

    async def _send(self, method, path, *, token=None, body=None, params=None):
        await self.start()
        headers = {"Authorization": f"QQBot {token}"} if token else {}
        writing = method != "GET" and path != "/app/getAppAccessToken"
        try:
            async with self.session.request(
                method, API_ROOT + path, headers=headers, json=body, params=params
            ) as response:
                trace = response.headers.get("X-Tps-trace-ID")
                try:
                    data = await response.json(content_type=None) if response.status != 204 else {}
                except (ValueError, aiohttp.ContentTypeError):
                    if writing and response.status != 401 and response.status != 429:
                        raise UncertainWrite(trace_id=trace) from None
                    raise OrderUIError(
                        "QQ 返回了非 JSON 响应", "upstream", trace_id=trace
                    ) from None
                if not isinstance(data, dict):
                    if writing:
                        raise UncertainWrite(trace_id=trace)
                    raise OrderUIError("QQ 响应结构无效", "upstream", trace_id=trace)
                trace = data.get("trace_id") or trace
                code = data.get("err_code", data.get("code", 0))
                if response.status >= 500 and writing:
                    raise UncertainWrite(trace_id=trace)
                if response.status >= 400 or code not in (None, 0, "0"):
                    category = "upstream"
                    if response.status == 401 or str(code) in ("100016", "11243", "11241", "11242"):
                        category = "auth"
                    elif response.status == 429 or str(code) == "100001":
                        category = "rate_limit"
                    elif str(code) in ("40030020", "40034006"):
                        category = "content_rejected"
                    message = str(
                        data.get("message") or data.get("msg") or f"QQ HTTP {response.status}"
                    )
                    raise OrderUIError(
                        message,
                        category,
                        trace_id=trace,
                        details={"qq_code": code, "http_status": response.status},
                    )
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if writing:
                raise UncertainWrite() from None
            raise OrderUIError("无法连接 QQ API 或请求超时", "network") from None

    async def token(self, appid, secret):
        async with self.token_locks[appid]:
            cached = self.tokens.get(appid)
            if cached and cached[0] == secret and self.clock() < cached[2] - 60:
                return cached[1]
            data = await self._send(
                "POST", "/app/getAppAccessToken", body={"appId": appid, "clientSecret": secret}
            )
            try:
                access = data["access_token"]
                expires = float(data["expires_in"])
                if not isinstance(access, str) or not access or expires <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise OrderUIError("QQ 访问凭证响应无效", "auth") from None
            self.tokens[appid] = (secret, access, self.clock() + expires)
            return access

    async def request(self, credentials, method, path, *, body=None, params=None):
        appid, secret = credentials
        token = await self.token(appid, secret)
        self.reserve(appid, method, path)
        try:
            return await self._send(method, path, token=token, body=body, params=params)
        except OrderUIError as exc:
            if exc.code == "auth":
                self.tokens.pop(appid, None)
            raise
