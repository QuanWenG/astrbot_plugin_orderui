import asyncio
import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orderui.dynamic_models import message_payload, validate_catalogue
from orderui.dynamic_sender import DynamicMenuSender
from orderui.dynamic_service import DynamicMenuService
from orderui.errors import OrderUIError, UncertainWrite
from tests.fakes import Store, commands


def catalogue():
    return {
        "menus": [
            {
                "id": "tools",
                "name": "工具箱",
                "trigger": "/工具箱",
                "aliases": ["/工具"],
                "enabled": True,
                "scopes": ["c2c", "group"],
                "title": "请选择功能",
                "description": "工具说明",
                "rows": [
                    [
                        {
                            "id": "help",
                            "label": "帮助",
                            "type": "command",
                            "command": "/help ",
                            "style": 1,
                            "enter": True,
                        }
                    ]
                ],
            }
        ]
    }


def linked_catalogue():
    doc = catalogue()
    entertainment = deepcopy(doc["menus"][0])
    entertainment.update(id="fun", name="娱乐", trigger="/娱乐", aliases=[])
    doc["menus"].append(entertainment)
    doc["menus"][0]["rows"][0].append(
        {"id": "next", "label": "娱乐", "type": "menu", "menu_id": "fun", "style": 0, "enter": True}
    )
    entertainment["rows"][0].append(
        {
            "id": "back",
            "label": "返回",
            "type": "menu",
            "menu_id": "tools",
            "style": 0,
            "enter": False,
        }
    )
    entertainment["rows"].append(
        [
            {
                "id": "site",
                "label": "官网",
                "type": "link",
                "url": "https://example.com",
                "style": 0,
                "enter": False,
            }
        ]
    )
    return doc


@pytest.fixture
def service():
    return DynamicMenuService(
        Store(), lambda pid: (pid, "secret"), commands, AsyncMock(return_value=[])
    )


def test_dynamic_keyboard_uses_live_target_and_scene_specific_enter():
    doc = validate_catalogue(linked_catalogue())
    doc["menus"][1]["trigger"] = "/新娱乐"
    for scene, enter in (("c2c", True), ("group", False)):
        payload, text = message_payload(doc["menus"][0], doc, scene, "msg", 9)
        assert "content" not in payload and payload["msg_type"] == 2
        buttons = payload["keyboard"]["content"]["rows"][0]["buttons"]
        assert buttons[0]["action"]["data"] == "/help "
        assert buttons[0]["action"]["enter"] is enter
        assert buttons[1]["action"]["data"] == "/新娱乐"
        assert "娱乐：/新娱乐" in text
    assert validate_catalogue({"menus": []}) == {"menus": []}


@pytest.mark.parametrize("scene", ["c2c", "group"])
@pytest.mark.parametrize("message_format", ["text", "markdown"])
def test_message_format_body_and_keyboard(scene, message_format):
    doc = linked_catalogue()
    menu = doc["menus"][0]
    menu.update(message_format=message_format, description="")
    doc = validate_catalogue(doc)
    payload, _ = message_payload(doc["menus"][0], doc, scene, "msg", 1)
    if message_format == "text":
        assert payload["msg_type"] == 0 and "markdown" not in payload
        assert payload["content"] == "请选择功能"
    else:
        assert payload["msg_type"] == 2 and "content" not in payload
        assert payload["markdown"]["content"] == "请选择功能"
    assert len(payload["keyboard"]["content"]["rows"][0]["buttons"]) == 2
    assert payload["msg_id"] == "msg" and payload["msg_seq"] == 1
    assert validate_catalogue(catalogue())["menus"][0]["message_format"] == "markdown"


async def test_text_format_persistence_and_diagnostics(service):
    doc = catalogue()
    doc["menus"][0].update(message_format="text", description="")
    await service.apply({"platform_id": "a", "document": doc, "revision": 0})
    restarted = DynamicMenuService(
        service.store, service.resolve, commands, service.source_warnings
    )
    await restarted.prepare("a")
    _, menu, restored = restarted.match("a", "group", "/工具箱")
    assert menu["message_format"] == "text"
    client = SimpleNamespace(request=AsyncMock(return_value={"id": "reply"}))
    await DynamicMenuSender(client, restarted).send(
        ("a", "secret"), "group", "recipient", "msg", menu, restored
    )
    body = client.request.call_args.kwargs["body"]
    assert body["content"] == "请选择功能" and "keyboard" in body and "markdown" not in body
    assert restarted.status["a"]["request_body"] == {
        "msg_type": 0,
        "content": "请选择功能",
        "has_keyboard": True,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["menus"][0].update(trigger="/工具 参数"),
        lambda d: d["menus"][0].update(aliases=["/工具箱"]),
        lambda d: d["menus"][0].update(rows=[]),
        lambda d: d["menus"][0].update(rows=d["menus"][0]["rows"] * 6),
        lambda d: d["menus"][0]["rows"][0][0].update(label="中" * 11),
        lambda d: d["menus"][0]["rows"][0][0].update(type="link", url="http://example.com"),
        lambda d: d["menus"][0]["rows"][0][0].update(type="menu", menu_id="missing"),
        lambda d: d["menus"][0].update(scopes=["channel"]),
        lambda d: d["menus"][0].update(message_format="invalid"),
        lambda d: d["menus"][0].update(message_format=None),
    ],
)
def test_dynamic_validation(mutation):
    doc = catalogue()
    mutation(doc)
    with pytest.raises(OrderUIError):
        validate_catalogue(doc)


def test_target_validation_and_character_boundary():
    doc = linked_catalogue()
    doc["menus"][0]["rows"][0][0]["label"] = "中" * 9 + "😀"
    validate_catalogue(doc)
    doc["menus"][1]["enabled"] = False
    with pytest.raises(OrderUIError, match="未启用"):
        validate_catalogue(doc)
    doc["menus"][1]["enabled"] = True
    doc["menus"][1]["scopes"] = ["c2c"]
    with pytest.raises(OrderUIError, match="场景不兼容"):
        validate_catalogue(doc)


async def test_draft_apply_hot_reload_backup_restart_and_isolation(service):
    doc = catalogue()
    await service.prepare("a")
    assert service.match("a", "group", "/工具箱") is None
    body = {"platform_id": "a", "document": doc, "revision": 0}
    await service.save_draft(body)
    assert service.match("a", "group", "/工具箱") is None
    assert "draft" not in await service.get("b")
    first = await service.apply(body)
    assert first["revision"] == 1
    assert service.match("a", "c2c", "/工具")[1]["id"] == "tools"
    doc["menus"][0]["trigger"] = "/新工具"
    second = await service.apply({**body, "revision": 1})
    assert not service.match("a", "group", "/工具箱")
    assert service.match("a", "group", "/新工具")
    assert second["backup"]["menus"][0]["trigger"] == "/工具箱"
    restarted = DynamicMenuService(
        service.store, service.resolve, commands, service.source_warnings
    )
    await restarted.prepare("a")
    assert restarted.match("a", "group", "/新工具")
    doc["menus"][0]["enabled"] = False
    await service.apply({**body, "revision": 2})
    assert not service.match("a", "group", "/新工具")
    await service.apply({**body, "document": {"menus": []}, "revision": 3})
    assert not (await service.get("a"))["document"]["menus"]


async def test_concurrent_apply_conflict_retains_draft(service):
    body = {"platform_id": "a", "document": catalogue(), "revision": 0}
    results = await asyncio.gather(service.apply(body), service.apply(body), return_exceptions=True)
    assert sum(isinstance(r, OrderUIError) for r in results) == 1
    saved = await service.get("a")
    assert saved["revision"] == 1 and saved["draft"]["revision"] == 0


async def test_native_command_conflict_is_blocked_before_apply(service):
    doc = catalogue()
    doc["menus"][0]["aliases"] = ["/help"]
    with pytest.raises(OrderUIError, match="冲突"):
        await service.apply({"platform_id": "a", "document": doc, "revision": 0})
    assert (await service.get("a"))["revision"] == 0


async def test_incomplete_draft_survives_without_becoming_active(service):
    doc = catalogue()
    doc["menus"][0]["rows"] = []
    await service.save_draft({"platform_id": "a", "document": doc, "revision": 0})
    result = await service.get("a")
    assert not result["document"]["menus"]
    assert result["draft"]["document"] == doc


@pytest.mark.parametrize(
    "error,fallback",
    [
        (OrderUIError("无markdown模板权限", "upstream", details={"qq_code": 40034127}), True),
        (OrderUIError("无自定义按钮权限", "upstream"), True),
        (OrderUIError("未登录", "auth"), False),
        (OrderUIError("内容违规", "content_rejected"), False),
        (OrderUIError("限流", "rate_limit"), False),
        (OrderUIError("参数错误", "upstream"), False),
        (UncertainWrite(), False),
    ],
)
async def test_sender_only_falls_back_for_explicit_capability_errors(service, error, fallback):
    client = SimpleNamespace(request=AsyncMock(side_effect=[error, {"id": "sent"}]))
    sender = DynamicMenuSender(client, service)
    doc = validate_catalogue(catalogue())
    await sender.send(("a", "secret"), "group", "real/group", "msg", doc["menus"][0], doc)
    assert client.request.await_count == (2 if fallback else 1)
    assert client.request.call_args_list[0].args[2] == "/v2/groups/real%2Fgroup/messages"
    if fallback:
        body = client.request.call_args.kwargs["body"]
        assert body["msg_type"] == 0 and "帮助：/help" in body["content"]
        assert "keyboard" not in body and body["msg_seq"] == 2
    assert service.status["a"]["result"] == ("text_fallback" if fallback else "failed")
    await sender.send(("a", "secret"), "group", "real/group", "msg", doc["menus"][0], doc)
    assert client.request.await_count == (2 if fallback else 1)


async def test_sender_deduplicates_concurrent_deliveries_and_retains_unknown_result(service):
    client = SimpleNamespace(request=AsyncMock(return_value={}))
    sender = DynamicMenuSender(client, service)
    doc = validate_catalogue(catalogue())
    await asyncio.gather(
        *(sender.send(("a", "s"), "c2c", "user", "msg", doc["menus"][0], doc) for _ in range(3))
    )
    assert client.request.await_count == 1
    assert service.status["a"]["error"]["code"] == "uncertain"


@pytest.fixture
def runtime_module(monkeypatch):
    # Load only our integration seam; avoid importing the full AstrBot application in unit tests.
    stub = ModuleType("astrbot.api.event.filter")
    stub.CustomFilter = object
    monkeypatch.setitem(sys.modules, "astrbot.api.event.filter", stub)
    spec = importlib.util.spec_from_file_location(
        "orderui._runtime_test", Path(__file__).parents[1] / "orderui/dynamic_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(scene="group", content=" /工具箱 ", platform="a"):
    extra = {}
    raw = (
        SimpleNamespace(group_openid="actual_group")
        if scene == "group"
        else SimpleNamespace(author=SimpleNamespace(user_openid="actual_user"))
    )
    return SimpleNamespace(
        message_str="工具箱",
        message_obj=SimpleNamespace(raw_message=raw, message_str=content, message_id="m"),
        get_platform_name=lambda: "qq_official",
        get_platform_id=lambda: platform,
        set_extra=lambda k, v: extra.update({k: v}),
        get_extra=lambda k, d=None: extra.get(k, d),
        stop_event=lambda: extra.update(stopped=True),
        extra=extra,
    )


async def test_runtime_matches_original_text_hot_updates_and_respects_scene(
    runtime_module, service
):
    doc = catalogue()
    await service.apply({"platform_id": "a", "document": doc, "revision": 0})
    sender = SimpleNamespace(send=AsyncMock(), close=lambda: None)
    runtime = runtime_module.DynamicMenuRuntime(
        service, sender, service.resolve, names=lambda: set()
    )
    ev = event()
    assert runtime.matches(ev, {"wake_prefix": ["/"]})
    await runtime.handle(ev)
    assert sender.send.call_args.args[2] == "actual_group"
    assert ev.extra["stopped"]
    assert not runtime.matches(event(content="/工具箱 参数"), {})
    assert not runtime.matches(event(platform="other"), {})
    guild = event()
    guild.message_obj.raw_message = SimpleNamespace(author=SimpleNamespace(id="guild-user"))
    assert not runtime.matches(guild, {})
    doc["menus"][0]["scopes"] = ["c2c"]
    await service.apply({"platform_id": "a", "document": doc, "revision": 1})
    assert not runtime.matches(event(), {})
    assert runtime.matches(event("c2c"), {})
    runtime.close()
    assert not runtime.matches(event("c2c"), {})


async def test_runtime_new_native_conflict_does_not_consume_event(runtime_module, service):
    await service.apply({"platform_id": "a", "document": catalogue(), "revision": 0})
    sender = SimpleNamespace(send=AsyncMock(), close=lambda: None)
    names = set()
    runtime = runtime_module.DynamicMenuRuntime(
        service, sender, service.resolve, names=lambda: names
    )
    ev = event()
    assert runtime.matches(ev, {"wake_prefix": ["/"]})
    names.add("工具箱")
    await runtime.handle(ev)
    assert sender.send.await_count == 0 and not ev.extra.get("stopped")
    assert service.status["a"]["result"] == "conflict"


async def test_old_runtime_cleanup_does_not_unbind_reloaded_instance(runtime_module, service):
    sender = SimpleNamespace(send=AsyncMock(), close=lambda: None)
    old = runtime_module.DynamicMenuRuntime(service, sender, service.resolve, names=lambda: set())
    new = runtime_module.DynamicMenuRuntime(service, sender, service.resolve, names=lambda: set())
    runtime_module.DynamicEntryFilter.runtime = new
    old.close()
    assert runtime_module.DynamicEntryFilter.runtime is new
