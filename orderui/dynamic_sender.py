"""Send reply keyboards once, with a narrowly scoped text fallback."""

import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import quote

from .dynamic_models import message_payload
from .errors import OrderUIError, UncertainWrite


def capability_denied(error):
    if error.code != "upstream":
        return False
    code = str((error.details or {}).get("qq_code"))
    if code == "40034127":
        return True
    message = str(error).lower()
    return any(
        term in message for term in ("markdown", "keyboard", "自定义按钮", "内联键盘")
    ) and any(
        term in message
        for term in (
            "无权限",
            "没有权限",
            "无自定义按钮权限",
            "无内联键盘权限",
            "未开通",
            "不允许",
            "permission denied",
            "not allowed",
        )
    )


class DynamicMenuSender:
    def __init__(self, client, service, clock=time.monotonic):
        self.client, self.service, self.clock = client, service, clock
        self.seen = OrderedDict()

    async def send(self, credentials, scene, recipient, msg_id, menu, document):
        if scene not in ("c2c", "group") or not recipient or not msg_id:
            raise OrderUIError("菜单回复缺少有效的 QQ 场景、接收方或消息 ID")
        key = (credentials[0], scene, recipient, msg_id)
        now = self.clock()
        while self.seen and (
            now - next(iter(self.seen.values())) > 3600 or len(self.seen) >= 10000
        ):
            self.seen.popitem(last=False)
        if key in self.seen:
            return
        # Reserve before awaiting: concurrent duplicate deliveries must not send twice.
        self.seen[key] = now
        path = f"/v2/{'users' if scene == 'c2c' else 'groups'}/{quote(recipient, safe='')}/messages"
        payload, fallback = message_payload(menu, document, scene, msg_id, 1)
        status = {
            "menu_id": menu["id"],
            "scene": scene,
            "time": datetime.now(timezone.utc).isoformat(),
            "request_body": {
                "msg_type": payload["msg_type"],
                "content": payload.get("content", payload.get("markdown", {}).get("content")),
                "has_keyboard": True,
            },
        }
        try:
            try:
                response = await self.client.request(credentials, "POST", path, body=payload)
                if not response.get("id"):
                    raise UncertainWrite("QQ 未返回消息 ID，发送结果不明，请勿自动重发")
                status["result"] = "sent"
            except OrderUIError as exc:
                if not capability_denied(exc):
                    raise
                status["fallback_reason"] = exc.as_dict()
                status["request_body"] = {
                    "msg_type": 0,
                    "content": fallback,
                    "has_keyboard": False,
                }
                response = await self.client.request(
                    credentials,
                    "POST",
                    path,
                    body={
                        "msg_type": 0,
                        "content": fallback,
                        "msg_id": msg_id,
                        "msg_seq": 2,
                    },
                )
                if not response.get("id"):
                    raise UncertainWrite("文字菜单发送结果不明，请勿自动重发")
                status["result"] = "text_fallback"
        except OrderUIError as exc:
            status.update(result="failed", error=exc.as_dict())
        finally:
            self.service.status[credentials[0]] = status

    def close(self):
        self.seen.clear()
