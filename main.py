from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .orderui.client import QQClient
from .orderui.commands import command_catalogue
from .orderui.dynamic_runtime import DynamicEntryFilter, DynamicMenuRuntime
from .orderui.dynamic_sender import DynamicMenuSender
from .orderui.dynamic_service import DynamicMenuService
from .orderui.errors import OrderUIError
from .orderui.routes import Routes
from .orderui.service import ManagementService


class OrderUIPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.client = QQClient()
        self.service = ManagementService(self.client, self, self.resolve, self.commands)
        self.dynamic = DynamicMenuService(
            self, self.resolve, self.commands, self.service.command_warnings
        )
        self.runtime = DynamicMenuRuntime(
            self.dynamic, DynamicMenuSender(self.client, self.dynamic), self.resolve
        )
        self.routes = Routes(context, self.service, self.bots, self.commands, logger, self.dynamic)

    async def initialize(self):
        self.routes.register()
        await self.prepare_dynamic()
        DynamicEntryFilter.runtime = self.runtime

    async def prepare_dynamic(self):
        for platform in self.platforms():
            try:
                await self.dynamic.prepare(platform.meta().id)
            except Exception:
                logger.exception("OrderUI dynamic menu configuration could not be loaded")

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        await self.prepare_dynamic()

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        await self.prepare_dynamic()

    @filter.custom_filter(DynamicEntryFilter, priority=100)
    async def dynamic_entry(self, event):
        await self.runtime.handle(event)

    def platforms(self):
        return [
            p for p in self.context.platform_manager.get_insts() if p.meta().name == "qq_official"
        ]

    def bots(self):
        return [
            {
                "platform_id": p.meta().id,
                "appid": str(p.config.get("appid", "")),
                "name": p.config.get("id", p.meta().id),
                "status": p.status.value,
            }
            for p in self.platforms()
        ]

    def resolve(self, platform_id):
        platform = self.context.get_platform_inst(platform_id)
        if platform is None or platform.meta().name != "qq_official":
            raise OrderUIError("未找到该 QQ 官方机器人，请检查平台是否启用", "unavailable")
        appid, secret = platform.config.get("appid"), platform.config.get("secret")
        if not appid or not secret:
            raise OrderUIError("该机器人缺少 AppID 或 Secret", "auth")
        return str(appid), str(secret)

    async def commands(self):
        from astrbot.core.star.command_management import list_commands
        from astrbot.core.star.star import star_map

        return {
            "items": command_catalogue(await list_commands(), star_map),
            "wake_prefix": self.context.get_config().get("wake_prefix", ["/"]),
        }

    async def terminate(self):
        self.runtime.close()
        self.routes.close()
        await self.client.close()
