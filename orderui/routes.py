"""Bridge-compatible routes; domain errors retain structured details."""

from functools import wraps

from quart import request

from .errors import OrderUIError

PLUGIN_NAME = "astrbot_plugin_orderui"


class Routes:
    def __init__(self, context, service, bots, commands, logger, dynamic=None):
        self.context = context
        self.service = service
        self.bots = bots
        self.commands = commands
        self.logger = logger
        self.dynamic = dynamic
        self.owned = []
        self.active = True

    def register(self):
        reads = {
            "bots": self.get_bots,
            "commands": self.get_commands,
            "menu": self.get_menu,
            "panels": self.get_panels,
            "panel": self.get_panel,
            "draft": self.get_draft,
        }
        writes = {
            "draft/save": self.service.save_draft,
            "menu/publish": self.service.publish_menu,
            "panels/create": self.service.create_panel,
            "panels/update": self.service.update_panel,
            "panels/delete": self.service.delete_panel,
            "panels/targets": self.service.targets,
            "panels/recover": self.service.recover_create,
            "panels/unlock": self.service.unlock_create,
        }
        if self.dynamic:
            reads["dynamic-menus"] = self.get_dynamic
            writes["dynamic-menus/draft"] = self.dynamic.save_draft
            writes["dynamic-menus/apply"] = self.dynamic.apply
        for method, operations in (("GET", reads), ("POST", writes)):
            for name, operation in operations.items():
                handler = self.wrap(operation, method)
                self.owned.append(handler)
                self.context.register_web_api(
                    f"/{PLUGIN_NAME}/{name}", handler, [method], f"QQ 菜单管理：{name}"
                )

    def wrap(self, operation, method):
        @wraps(operation)
        async def handle():
            try:
                if not self.active:
                    raise OrderUIError("插件已停用", "unavailable")
                if method == "POST":
                    if len(await request.get_data()) > 256 * 1024:
                        raise OrderUIError("请求过大，最多 256 KiB")
                    body = await request.get_json(silent=True)
                    if not isinstance(body, dict):
                        raise OrderUIError("请求必须是 JSON 对象")
                    result = await operation(body)
                else:
                    result = await operation()
                payload = {"ok": True, "result": result}
            except OrderUIError as exc:
                payload = {"ok": False, "error": exc.as_dict()}
            except Exception:
                self.logger.exception("OrderUI request failed")
                payload = {
                    "ok": False,
                    "error": {"code": "internal", "message": "插件内部错误，请查看 AstrBot 日志"},
                }
            # The host bridge discards details for status=error envelopes.
            return {"status": "ok", "data": payload}

        return handle

    def close(self):
        self.active = False
        self.context.registered_web_apis[:] = [
            entry for entry in self.context.registered_web_apis if entry[1] not in self.owned
        ]
        self.owned.clear()

    async def get_bots(self):
        return {"items": self.bots()}

    async def get_dynamic(self):
        return await self.dynamic.get(request.args.get("platform_id"))

    async def get_commands(self):
        return await self.commands()

    async def get_menu(self):
        return await self.service.get_menu(request.args.get("platform_id"))

    async def get_panels(self):
        return await self.service.panels(
            request.args.get("platform_id"), request.args.get("scope", "c2c")
        )

    async def get_panel(self):
        return await self.service.get_panel(
            request.args.get("platform_id"), request.args.get("panel_id")
        )

    async def get_draft(self):
        return await self.service.draft(
            request.args.get("platform_id"), request.args.get("resource")
        )
