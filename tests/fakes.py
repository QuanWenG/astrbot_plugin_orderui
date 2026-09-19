from copy import deepcopy

from orderui.errors import OrderUIError


class Store:
    def __init__(self):
        self.values = {}

    async def get_kv_data(self, key, default):
        return deepcopy(self.values.get(key, default))

    async def put_kv_data(self, key, value):
        self.values[key] = deepcopy(value)


def menu(name="帮助"):
    return {"menu": {"items": [{"type": "send_message", "name": name, "send_message": "/help"}]}}


def panel(scope="c2c", target_type="all", count=0):
    return {
        "scope": scope,
        "target_type": target_type,
        "panel": {
            "items": [{"type": "command", "name": "/help", "desc": "帮助", "only_admin": False}],
            "remark": "测试面板",
        },
        "user_openids": [f"u{i}" for i in range(count)] if scope == "c2c" else [],
        "group_openids": [f"g{i}" for i in range(count)] if scope == "group" else [],
    }


class FakeQQ:
    def __init__(self):
        self.menus = {}
        self.panels = {}
        self.calls = []
        self.counter = 0
        self.messages = []
        self.hook = lambda method, path, body, phase: None

    async def request(self, credentials, method, path, *, body=None, params=None):
        appid = credentials[0]
        self.calls.append((appid, method, path, deepcopy(body)))
        self.hook(method, path, body, "before")
        if path.startswith(("/v2/users/", "/v2/groups/")) and path.endswith("/messages"):
            self.messages.append((appid, path, deepcopy(body)))
            result = {"id": f"m{len(self.messages)}"}
        elif path == "/v2/menu":
            if method == "PUT":
                version = self.menus.get(appid, {}).get("version", 0) + 1
                self.menus[appid] = {**deepcopy(body), "version": version}
            result = self.menus.get(appid, {"menu": None, "version": 0})
        elif path == "/v2/panels":
            if method == "GET":
                result = {
                    "records": [
                        deepcopy(p)
                        for (a, _), p in self.panels.items()
                        if a == appid and p["scope"] == params["scope"]
                    ],
                    "is_end": True,
                    "next_cursor": "",
                }
            else:
                self.counter += 1
                panel_id = f"p{self.counter}"
                self.panels[(appid, panel_id)] = {
                    "user_openids": [],
                    "group_openids": [],
                    **deepcopy(body),
                    "panel_id": panel_id,
                    "version": 1,
                }
                result = {"panel_id": panel_id}
        else:
            panel_id = path.split("/")[3]
            if (appid, panel_id) not in self.panels:
                raise OrderUIError("面板不存在", "upstream", details={"qq_code": 40030006})
            record = self.panels[(appid, panel_id)]
            if path.endswith("/target"):
                field = "user_openids" if "user_openids" in body else "group_openids"
                previous, batch = set(record[field]), set(body[field])
                record[field] = sorted(
                    previous | batch if body["op"] == "add" else previous - batch
                )
                result = {}
            elif method == "PUT":
                record["panel"] = deepcopy(body["panel"])
                record["version"] += 1
                result = {"version": record["version"]}
            elif method == "DELETE":
                del self.panels[(appid, panel_id)]
                result = {}
            else:
                result = record
        self.hook(method, path, body, "after")
        return deepcopy(result)


async def commands():
    return {
        "items": [
            {
                "handler_full_name": "plugin.help",
                "effective_command": "help",
                "description": "查看帮助",
                "plugin": "测试插件",
                "permission": "everyone",
                "enabled": True,
                "has_conflict": False,
                "aliases": [],
            }
        ],
        "wake_prefix": ["/"],
    }
