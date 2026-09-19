"""Persist dynamic menu snapshots without writing QQ configuration."""

import asyncio
from collections import defaultdict
from copy import deepcopy

from .dynamic_models import catalogue_conflicts, validate_catalogue
from .errors import OrderUIError
from .models import object_value


class DynamicMenuService:
    def __init__(self, store, resolve, commands, source_warnings):
        self.store, self.resolve, self.commands = store, resolve, commands
        self.source_warnings = source_warnings
        self.locks = defaultdict(asyncio.Lock)
        self.snapshots = {}
        self.platforms = {}
        self.status = {}

    def key(self, appid):
        return f"orderui.dynamic.v1:{appid}"

    async def read(self, appid):
        return await self.store.get_kv_data(self.key(appid), None) or {
            "document": {"menus": []},
            "revision": 0,
        }

    async def prepare(self, platform_id):
        appid, _ = self.resolve(platform_id)
        async with self.locks[appid]:
            if appid not in self.snapshots:
                saved = await self.read(appid)
                self.snapshots[appid] = validate_catalogue(saved["document"])
            self.platforms[platform_id] = appid

    async def warnings(self, document, command_data=None):
        warnings = catalogue_conflicts(document, command_data or await self.commands())
        sources = [
            b["source"]
            for m in document["menus"]
            for row in m["rows"]
            for b in row
            if b.get("source")
        ]
        return warnings + await self.source_warnings(sources)

    async def get(self, platform_id):
        await self.prepare(platform_id)
        appid = self.platforms[platform_id]
        saved = await self.read(appid)
        return {
            **saved,
            "warnings": await self.warnings(saved["document"]),
            "status": deepcopy(self.status.get(appid)),
        }

    async def save_draft(self, body):
        appid, _ = self.resolve(body.get("platform_id"))
        document = object_value(body.get("document"), "动态菜单草稿")
        async with self.locks[appid]:
            saved = await self.read(appid)
            saved["draft"] = {"document": deepcopy(document), "revision": body.get("revision")}
            await self.store.put_kv_data(self.key(appid), saved)
        return {"saved": True}

    async def apply(self, body):
        appid, _ = self.resolve(body.get("platform_id"))
        document = validate_catalogue(body.get("document"))
        command_data = await self.commands()
        conflicts = catalogue_conflicts(document, command_data)
        if conflicts:
            raise OrderUIError("\n".join(conflicts), "command_conflict")
        warnings = await self.warnings(document, command_data)
        async with self.locks[appid]:
            saved = await self.read(appid)
            if type(body.get("revision")) is not int or body["revision"] != saved["revision"]:
                # Retain the submitted draft, including for direct API callers.
                saved["draft"] = {"document": deepcopy(document), "revision": body.get("revision")}
                await self.store.put_kv_data(self.key(appid), saved)
                raise OrderUIError(
                    "动态菜单已被其他页面修改，请载入已应用配置后核对",
                    "conflict",
                    details={"revision": saved["revision"]},
                )
            updated = {
                "document": document,
                "revision": saved["revision"] + 1,
                "backup": deepcopy(saved["document"]),
                "draft": {"document": deepcopy(document), "revision": saved["revision"] + 1},
            }
            await self.store.put_kv_data(self.key(appid), updated)
            self.snapshots[appid] = deepcopy(document)
            self.platforms[body["platform_id"]] = appid
        return {
            **updated,
            "warnings": warnings,
            "status": deepcopy(self.status.get(appid)),
        }

    def match(self, platform_id, scene, content):
        appid = self.platforms.get(platform_id)
        document = self.snapshots.get(appid, {"menus": []})
        for menu in document["menus"]:
            if (
                menu["enabled"]
                and scene in menu["scopes"]
                and content in [menu["trigger"], *menu["aliases"]]
            ):
                return appid, menu, document
        return None

    def close(self):
        self.platforms.clear()
        self.snapshots.clear()
