import pytest

from orderui.errors import OrderUIError
from orderui.models import canonical_panel, https_url, validate_menu, validate_panel, width
from tests.fakes import panel


def test_full_menu_roundtrip():
    menu = {
        "items": [
            {"type": "send_message", "name": "帮助", "send_message": "/help 参数"},
            {"type": "link", "name": "官网", "link": "https://example.com"},
            {
                "type": "menu",
                "name": "更多",
                "sub_menu_items": [
                    {"type": "send_message", "name": "子菜单", "send_message": "/sub"}
                ],
            },
            {"type": "switch", "name": "搜索", "switch": {"switch_id": "search", "default": True}},
        ]
    }
    assert validate_menu(menu) == menu
    assert width("帮助abc😀") == 9
    assert validate_menu(
        {"items": [{"type": "send_message", "name": "中文中文中", "send_message": "任意内容"}]}
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://",
        "javascript:alert(1)",
        "https://user:pass@example.com",
        "https://example.com:bad",
        "https://exam ple.com",
    ],
)
def test_invalid_links(url):
    with pytest.raises(OrderUIError):
        https_url(url)


@pytest.mark.parametrize(
    "value",
    [
        {"items": [{"type": "send_message", "name": "中文中文中文", "send_message": "/help"}]},
        {"items": [{"type": "link", "name": "a", "link": "https://a.com"}] * 11},
        {
            "items": [
                {"type": "menu", "name": "a", "sub_menu_items": [{"type": "menu", "name": "b"}]}
            ]
        },
        {
            "items": [
                {"type": "switch", "name": "a", "switch": {"switch_id": "s", "default": "false"}}
            ]
        },
        {"items": [{"type": "switch", "name": "a", "switch": {"switch_id": "s"}}] * 2},
    ],
)
def test_invalid_menus(value):
    with pytest.raises(OrderUIError):
        validate_menu(value)


@pytest.mark.parametrize("scope", ["c2c", "group", "channel", "dm"])
def test_panel_scopes(scope):
    assert validate_panel(panel(scope)) == panel(scope)
    if scope in ("channel", "dm"):
        with pytest.raises(OrderUIError):
            validate_panel(panel(scope, "specific"))


def test_target_dedup_and_panel_limits():
    value = panel("c2c", "specific")
    value["user_openids"] = " a \na\nb\n"
    assert validate_panel(value)["user_openids"] == ["a", "b"]
    value["panel"]["items"][0]["name"] = "中文" * 4
    with pytest.raises(OrderUIError):
        validate_panel(value)
    value = panel()
    value["panel"]["items"] *= 21
    with pytest.raises(OrderUIError):
        validate_panel(value)


def test_remote_optional_fields_normalized():
    value = {
        "scope": "c2c",
        "target_type": "all",
        "panel_id": "p",
        "panel": {"items": [{"type": "command", "name": "help"}]},
    }
    normalized = canonical_panel(value)
    assert normalized["panel"]["items"][0]["only_admin"] is False
    assert normalized["user_openids"] == []
