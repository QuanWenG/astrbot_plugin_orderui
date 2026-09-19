"""Dynamic menu documents and QQ keyboard serialization."""

from copy import deepcopy

from .errors import OrderUIError
from .models import boolean, https_url, items, object_value, text


def entry(value):
    value = text(value, "完整入口指令", 64, weighted=False).strip()
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise OrderUIError("入口指令不能包含空白或参数")
    return value


def validate_catalogue(document):
    object_value(document, "动态菜单配置")
    menus, ids, triggers = [], set(), set()
    for raw in items(document.get("menus"), 100, "动态菜单"):
        object_value(raw, "动态菜单")
        mid = text(raw.get("id"), "菜单 ID", 100, weighted=False)
        if mid in ids:
            raise OrderUIError("菜单 ID 重复")
        ids.add(mid)
        message_format = raw.get("message_format", "markdown")
        if message_format not in ("markdown", "text"):
            raise OrderUIError("消息格式只支持 Markdown 或文本")
        scopes = raw.get("scopes")
        if (
            not isinstance(scopes, list)
            or not scopes
            or any(s not in ("c2c", "group") for s in scopes)
        ):
            raise OrderUIError("请选择单聊或群聊场景")
        menu = {
            "id": mid,
            "name": text(raw.get("name"), "菜单名称", 100, weighted=False),
            "trigger": entry(raw.get("trigger")),
            "aliases": [entry(a) for a in items(raw.get("aliases", []), 20, "别名")],
            "enabled": boolean(raw.get("enabled", True), "启用状态"),
            "scopes": list(dict.fromkeys(scopes)),
            "message_format": message_format,
            "title": text(raw.get("title"), "回复标题", 200, weighted=False),
            "description": text(
                raw.get("description", ""), "说明", 2000, empty=True, weighted=False
            ),
            "rows": [],
        }
        for trigger in [menu["trigger"], *menu["aliases"]]:
            if trigger in triggers:
                raise OrderUIError(f"入口指令或别名重复：{trigger}")
            triggers.add(trigger)
        button_ids = set()
        for row in items(raw.get("rows"), 5, "按钮行"):
            buttons = []
            for button in items(row, 5, "每行按钮"):
                object_value(button, "按钮")
                bid = text(button.get("id"), "按钮 ID", 100, weighted=False)
                if bid in button_ids:
                    raise OrderUIError("同一菜单内按钮 ID 不能重复")
                button_ids.add(bid)
                kind = button.get("type")
                if kind not in ("command", "menu", "link"):
                    raise OrderUIError("按钮只支持指令、菜单跳转和链接")
                style = button.get("style", 0)
                if type(style) is not int or style not in (0, 1):
                    raise OrderUIError("按钮样式无效")
                result = {
                    "id": bid,
                    "label": text(button.get("label"), "按钮名称", 10, weighted=False),
                    "style": style,
                    "type": kind,
                    "enter": boolean(button.get("enter", False), "单聊自动发送"),
                }
                if kind == "command":
                    result["command"] = text(
                        button.get("command"), "按钮指令", 2000, weighted=False
                    )
                    if button.get("source"):
                        result["source"] = deepcopy(object_value(button["source"], "指令来源"))
                elif kind == "menu":
                    result["menu_id"] = text(button.get("menu_id"), "目标菜单", 100, weighted=False)
                else:
                    result["url"] = https_url(button.get("url"))
                buttons.append(result)
            if not buttons:
                raise OrderUIError("按钮行不能为空，请删除空行或添加按钮")
            menu["rows"].append(buttons)
        if not menu["rows"]:
            raise OrderUIError("每个菜单至少需要一个按钮")
        menus.append(menu)
    by_id = {m["id"]: m for m in menus}
    for menu in menus:
        for row in menu["rows"]:
            for button in row:
                if button["type"] != "menu":
                    continue
                target = by_id.get(button["menu_id"])
                if target is None:
                    raise OrderUIError(f"{menu['name']} 的跳转目标不存在")
                if menu["enabled"] and (
                    not target["enabled"] or not set(menu["scopes"]) <= set(target["scopes"])
                ):
                    raise OrderUIError(f"{menu['name']} 的跳转目标未启用或场景不兼容")
    return {"menus": menus}


def conflicting_trigger(trigger, names, prefixes):
    candidates = {trigger}
    for prefix in prefixes:
        if prefix and trigger.startswith(prefix):
            candidates.add(trigger[len(prefix) :].strip())
    return any(c == name or c.startswith(name + " ") for c in candidates for name in names if name)


def catalogue_conflicts(document, commands):
    names = {
        name
        for c in commands["items"]
        for name in [c.get("effective_command"), *(c.get("aliases") or [])]
        if name
    }
    return [
        f"入口 {trigger} 与 AstrBot 已注册指令冲突"
        for menu in document["menus"]
        if menu["enabled"]
        for trigger in [menu["trigger"], *menu["aliases"]]
        if conflicting_trigger(trigger, names, commands.get("wake_prefix", ["/"]))
    ]


def message_payload(menu, document, scene, msg_id, seq):
    targets = {m["id"]: m for m in document["menus"]}
    rows, lines = [], [menu["title"], menu["description"]]
    for row in menu["rows"]:
        buttons = []
        for button in row:
            kind = button["type"]
            data = (
                targets[button["menu_id"]]["trigger"]
                if kind == "menu"
                else button["command"]
                if kind == "command"
                else button["url"]
            )
            action = {
                "type": 0 if kind == "link" else 2,
                "data": data,
                "permission": {"type": 2},
                "unsupport_tips": "请使用下方对应指令或更新 QQ 客户端",
            }
            if kind != "link":
                action["enter"] = scene == "c2c" and button["enter"]
            buttons.append(
                {
                    "id": button["id"],
                    "render_data": {
                        "label": button["label"],
                        "visited_label": button["label"],
                        "style": button["style"],
                    },
                    "action": action,
                }
            )
            lines.append(f"{button['label']}：{data}")
        rows.append({"buttons": buttons})
    content = menu["title"] + ("\n\n" + menu["description"] if menu["description"] else "")
    payload = {
        "keyboard": {"content": {"rows": rows}},
        "msg_id": msg_id,
        "msg_seq": seq,
    }
    if menu.get("message_format", "markdown") == "text":
        payload.update(msg_type=0, content=content)
    else:
        payload.update(msg_type=2, markdown={"content": content})
    return payload, "\n".join(line for line in lines if line)
