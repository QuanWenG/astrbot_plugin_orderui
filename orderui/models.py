"""Validation and canonical representations shared by services."""

import hashlib
import json
from urllib.parse import urlsplit

from .errors import OrderUIError

SCOPES = ("c2c", "group", "channel", "dm")


def width(value):
    return sum(1 if ord(char) < 128 else 2 for char in value)


def object_value(value, label):
    if not isinstance(value, dict):
        raise OrderUIError(f"{label}必须是对象")
    return value


def text(value, label, limit=None, *, empty=False, weighted=True):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise OrderUIError(f"请填写{label}")
    if limit and (width(value) if weighted else len(value)) > limit:
        raise OrderUIError(f"{label}超过 {limit} 的长度限制")
    return value


def boolean(value, label):
    if not isinstance(value, bool):
        raise OrderUIError(f"{label}必须为布尔值")
    return value


def https_url(value):
    text(value, "链接")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError
        parsed.port
    except ValueError:
        raise OrderUIError("链接必须是有效的 HTTPS 地址，且不能包含账号密码") from None
    return value


def items(value, limit, label):
    if not isinstance(value, list) or len(value) > limit:
        raise OrderUIError(f"{label}必须为列表，最多 {limit} 项")
    return value


def validate_menu(menu):
    object_value(menu, "菜单")
    switches = set()

    def validate_item(item, child=False):
        object_value(item, "菜单项")
        kind = item.get("type")
        allowed = ("send_message", "link") if child else ("send_message", "link", "menu", "switch")
        if kind not in allowed:
            raise OrderUIError("不支持的菜单类型或层级")
        result = {"name": text(item.get("name"), "按钮名称", 14 if child else 10), "type": kind}
        if kind == "send_message":
            result["send_message"] = text(item.get("send_message"), "填入内容")
        elif kind == "link":
            result["link"] = https_url(item.get("link"))
        elif kind == "menu":
            children = items(item.get("sub_menu_items", []), 5, "二级菜单")
            if not children:
                raise OrderUIError("折叠菜单至少需要一个子项")
            result["sub_menu_items"] = [validate_item(sub, True) for sub in children]
        else:
            switch = object_value(item.get("switch"), "开关")
            sid = text(switch.get("switch_id"), "开关标识")
            if sid in switches:
                raise OrderUIError("开关标识不能重复")
            switches.add(sid)
            result["switch"] = {
                "switch_id": sid,
                "default": boolean(switch.get("default", False), "默认状态"),
            }
        return result

    return {"items": [validate_item(item) for item in items(menu.get("items", []), 10, "一级菜单")]}


def openids(value):
    if isinstance(value, str):
        value = value.splitlines()
    if not isinstance(value, list):
        raise OrderUIError("OpenID 必须是列表或多行文本")
    result = []
    for entry in value:
        if not isinstance(entry, str):
            raise OrderUIError("OpenID 必须为文本")
        entry = entry.strip()
        if entry and entry not in result:
            result.append(entry)
    return result


def validate_panel(document, *, for_publish=False):
    object_value(document, "面板")
    scope = document.get("scope")
    target_type = document.get("target_type", "all")
    if scope not in SCOPES or target_type not in ("all", "specific"):
        raise OrderUIError("面板场景或作用范围无效")
    if scope in ("channel", "dm") and target_type != "all":
        raise OrderUIError("文字子频道和频道私信仅支持全局面板")
    panel = object_value(document.get("panel"), "面板内容")
    panel_items = items(panel.get("items", []), 20, "面板元素")
    if for_publish and not panel_items:
        raise OrderUIError("发布指令面板至少需要一个元素；如需移除整个面板，请使用“删除面板”")
    result_items = []
    for item in panel_items:
        object_value(item, "面板元素")
        kind = item.get("type")
        if kind not in ("command", "link"):
            raise OrderUIError("面板只支持指令或链接")
        entry = {
            "type": kind,
            "name": text(item.get("name"), "面板名称", 14),
            "desc": text(item.get("desc", ""), "元素描述", 30, empty=True),
            "only_admin": boolean(item.get("only_admin", False), "仅 QQ 管理员"),
        }
        if kind == "link":
            entry["link"] = https_url(item.get("link"))
        result_items.append(entry)
    result = {
        "scope": scope,
        "target_type": target_type,
        "panel": {
            "items": result_items,
            "remark": text(panel.get("remark", ""), "备注", 255, empty=True, weighted=False),
        },
    }
    for field in ("user_openids", "group_openids"):
        values = openids(document.get(field, []))
        valid_field = (
            "user_openids" if scope == "c2c" else "group_openids" if scope == "group" else None
        )
        if values and (target_type != "specific" or field != valid_field):
            raise OrderUIError("当前场景和作用范围不支持这些关联对象")
        result[field] = values
    return result


def canonical_menu(record):
    return {
        "menu": validate_menu(record.get("menu") or {"items": []}),
        "version": record.get("version"),
    }


def canonical_panel(record):
    result = validate_panel(record)
    result["panel_id"] = record.get("panel_id")
    result["version"] = record.get("version", (record.get("panel") or {}).get("version"))
    result["user_openids"].sort()
    result["group_openids"].sort()
    return result


def fingerprint(document):
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def state(document):
    return {"document": document, "baseline": fingerprint(document)}
