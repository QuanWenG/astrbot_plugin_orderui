"""AstrBot event integration; no synthetic events or cross-plugin invocation."""

from astrbot.api.event.filter import CustomFilter

from .dynamic_models import conflicting_trigger
from .errors import OrderUIError


def native_names():
    from astrbot.core.star.filter.command import CommandFilter
    from astrbot.core.star.filter.command_group import CommandGroupFilter
    from astrbot.core.star.star_handler import star_handlers_registry

    names = set()
    for handler in star_handlers_registry:
        for candidate in handler.event_filters:
            if isinstance(candidate, (CommandFilter, CommandGroupFilter)):
                names.update(candidate.get_complete_command_names())
    return names


def event_context(event):
    if event.get_platform_name() != "qq_official":
        return None
    raw = event.message_obj.raw_message
    # Guild messages and synthetic session IDs must never become C2C recipients.
    recipient = getattr(raw, "group_openid", None)
    if recipient:
        scene = "group"
    else:
        recipient = getattr(getattr(raw, "author", None), "user_openid", None)
        scene = "c2c"
    if not recipient:
        return None
    # The adapter's message object retains text from before WakingCheck mutates event.message_str.
    content = event.message_obj.message_str.strip()
    return scene, recipient, content, event.message_obj.message_id


class DynamicEntryFilter(CustomFilter):
    runtime = None

    def filter(self, event, cfg):
        return bool(self.runtime and self.runtime.matches(event, cfg))


class DynamicMenuRuntime:
    def __init__(self, service, sender, resolve, names=native_names):
        self.service, self.sender, self.resolve, self.names = service, sender, resolve, names
        self.active = True

    def matches(self, event, cfg):
        if not self.active:
            return False
        context = event_context(event)
        if not context:
            return False
        scene, _, content, _ = context
        match = self.service.match(event.get_platform_id(), scene, content)
        if not match:
            return False
        try:
            if self.resolve(event.get_platform_id())[0] != match[0]:
                return False
        except OrderUIError:
            return False
        if conflicting_trigger(content, self.names(), cfg.get("wake_prefix", ["/"])):
            self.service.status[match[0]] = {
                "result": "conflict",
                "menu_id": match[1]["id"],
                "message": f"入口 {content} 与 AstrBot 指令冲突，已让已有指令处理",
            }
            return False
        event.set_extra("orderui_dynamic_prefixes", cfg.get("wake_prefix", ["/"]))
        return True

    async def handle(self, event):
        cfg = {"wake_prefix": event.get_extra("orderui_dynamic_prefixes", ["/"])}
        if not self.matches(event, cfg):
            return
        scene, recipient, content, msg_id = event_context(event)
        _, menu, document = self.service.match(event.get_platform_id(), scene, content)
        try:
            await self.sender.send(
                self.resolve(event.get_platform_id()), scene, recipient, msg_id, menu, document
            )
        finally:
            event.stop_event()

    def close(self):
        self.active = False
        if DynamicEntryFilter.runtime is self:
            DynamicEntryFilter.runtime = None
        self.sender.close()
        self.service.close()
