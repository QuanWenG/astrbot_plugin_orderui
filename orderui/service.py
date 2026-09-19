"""Drafts, conflict detection, publication and target reconciliation."""

import asyncio
from collections import defaultdict
from copy import deepcopy
from urllib.parse import quote

from .errors import OrderUIError, UncertainWrite
from .models import (
    SCOPES,
    canonical_menu,
    canonical_panel,
    fingerprint,
    object_value,
    state,
    text,
    validate_menu,
    validate_panel,
)


class ManagementService:
    def __init__(self, client, store, resolve, commands):
        self.client = client
        self.store = store
        self.resolve = resolve
        self.commands = commands
        self.locks = defaultdict(asyncio.Lock)

    def key(self, appid, resource):
        return f"orderui.v1:{appid}:{resource}"

    async def local(self, appid, resource):
        return await self.store.get_kv_data(self.key(appid, resource), {}) or {}

    async def put_local(self, appid, resource, value):
        await self.store.put_kv_data(self.key(appid, resource), deepcopy(value))

    def resource(self, value):
        text(value, "资源标识", 180, weighted=False)
        if value != "menu" and not value.startswith(("panel:", "new:")):
            raise OrderUIError("资源标识无效")
        return value

    async def command_warnings(self, sources):
        if not sources:
            return []
        current = {item["handler_full_name"]: item for item in (await self.commands())["items"]}
        warnings = []
        for source in sources:
            if not isinstance(source, dict):
                raise OrderUIError("指令来源格式无效")
            name = source.get("effective_command", "")
            item = current.get(source.get("handler_full_name"))
            if not item:
                warnings.append(f"指令 {name} 已消失")
            elif not item.get("enabled"):
                warnings.append(f"指令 {name} 已停用")
            elif item.get("effective_command") != name:
                warnings.append(f"指令 {name} 已改名为 {item.get('effective_command')}")
            elif item.get("has_conflict"):
                warnings.append(f"指令 {name} 存在冲突")
            elif item.get("permission") != source.get("permission"):
                warnings.append(f"指令 {name} 的 AstrBot 权限已变化")
        return warnings

    async def check_sources(self, body):
        sources = body.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 200:
            raise OrderUIError("指令来源列表无效")
        warnings = await self.command_warnings(sources)
        if warnings and body.get("ack_warnings") is not True:
            raise OrderUIError(
                "关联指令已变化，请核对后确认发布",
                "command_changed",
                details={"warnings": warnings},
            )
        return sources

    async def draft(self, platform_id, resource):
        appid, _ = self.resolve(platform_id)
        return await self.local(appid, self.resource(resource))

    async def save_draft(self, body):
        appid, _ = self.resolve(body.get("platform_id"))
        resource = self.resource(body.get("resource"))
        document = object_value(body.get("document"), "草稿")
        sources = body.get("sources", [])
        if (
            not isinstance(sources, list)
            or len(sources) > 200
            or not all(isinstance(s, dict) for s in sources)
        ):
            raise OrderUIError("指令来源列表无效")
        async with self.locks[appid]:
            saved = await self.local(appid, resource)
            saved["draft"] = {
                "document": document,
                "baseline": body.get("baseline"),
                "sources": sources,
            }
            await self.put_local(appid, resource, saved)
        return {"saved": True}

    async def menu_remote(self, credentials):
        return canonical_menu(await self.client.request(credentials, "GET", "/v2/menu"))

    async def panel_remote(self, credentials, panel_id):
        text(panel_id, "面板 ID", 160, weighted=False)
        return canonical_panel(
            await self.client.request(credentials, "GET", f"/v2/panels/{quote(panel_id, safe='')}")
        )

    async def get_menu(self, platform_id):
        credentials = self.resolve(platform_id)
        result = state(await self.menu_remote(credentials))
        result.update(await self.local(credentials[0], "menu"))
        result["warnings"] = await self.command_warnings(
            (result.get("draft") or {}).get("sources", [])
        )
        return result

    async def get_panel(self, platform_id, panel_id):
        credentials = self.resolve(platform_id)
        result = state(await self.panel_remote(credentials, panel_id))
        result.update(await self.local(credentials[0], f"panel:{panel_id}"))
        result["warnings"] = await self.command_warnings(
            (result.get("draft") or {}).get("sources", [])
        )
        return result

    def conflict(self, remote, baseline):
        if not baseline or fingerprint(remote) != baseline:
            raise OrderUIError(
                "远端配置已变化，请保存草稿并重新载入核对",
                "conflict",
                details={"remote": state(remote)},
            )

    async def remember(self, appid, resource, remote):
        saved = await self.local(appid, resource)
        saved["backup"] = deepcopy(remote)
        await self.put_local(appid, resource, saved)

    async def complete(self, appid, resource, remote, sources):
        saved = await self.local(appid, resource)
        saved["draft"] = {**state(remote), "sources": sources}
        await self.put_local(appid, resource, saved)
        return {**state(remote), **saved}

    async def publish_menu(self, body):
        credentials = self.resolve(body.get("platform_id"))
        appid = credentials[0]
        menu = validate_menu(object_value(body.get("document"), "菜单配置").get("menu"))
        sources = await self.check_sources(body)
        async with self.locks[appid]:
            remote = await self.menu_remote(credentials)
            self.conflict(remote, body.get("baseline"))
            await self.remember(appid, "menu", remote)
            try:
                await self.client.request(credentials, "PUT", "/v2/menu", body={"menu": menu})
            except UncertainWrite as exc:
                try:
                    current = await self.menu_remote(credentials)
                except OrderUIError:
                    raise exc from None
                if current["menu"] != menu:
                    raise exc from None
                return {**await self.complete(appid, "menu", current, sources), "recovered": True}
            current = await self.menu_remote(credentials)
            if current["menu"] != menu:
                raise UncertainWrite("QQ 已接受更新，但回读内容尚未一致，请稍后刷新核对")
            return await self.complete(appid, "menu", current, sources)

    async def list_remote(self, credentials, scope):
        if scope not in SCOPES:
            raise OrderUIError("面板场景无效")
        records, seen, cursor = [], set(), ""
        while True:
            response = await self.client.request(
                credentials,
                "GET",
                "/v2/panels",
                params={"scope": scope, "limit": 50, "cursor": cursor},
            )
            page = response.get("records", [])
            if not isinstance(page, list):
                raise OrderUIError("QQ 面板列表格式无效", "upstream")
            records.extend(page)
            cursor = response.get("next_cursor", "")
            if response.get("is_end") or not cursor:
                return records
            if cursor in seen or len(seen) >= 50:
                raise OrderUIError("QQ 返回重复或过多的分页游标", "upstream")
            seen.add(cursor)

    async def panels(self, platform_id, scope):
        credentials = self.resolve(platform_id)
        pending = await self.local(credentials[0], "pending_create")
        return {
            "records": await self.list_remote(credentials, scope),
            "pending_create": bool(pending),
        }

    async def create_panel(self, body):
        credentials = self.resolve(body.get("platform_id"))
        appid = credentials[0]
        desired = validate_panel(body.get("document"), for_publish=True)
        sources = await self.check_sources(body)
        async with self.locks[appid]:
            pending = await self.local(appid, "pending_create")
            if pending:
                raise OrderUIError(
                    "上次创建结果尚待核对，请先恢复创建结果或人工核对解除锁定", "pending_create"
                )
            all_records = []
            for scope in SCOPES:
                all_records.extend(await self.list_remote(credentials, scope))
            if len(all_records) >= 20:
                raise OrderUIError("该机器人已达到 20 个指令面板上限")
            request = {key: deepcopy(desired[key]) for key in ("scope", "target_type", "panel")}
            if desired["target_type"] == "specific":
                field = "user_openids" if desired["scope"] == "c2c" else "group_openids"
                if desired[field]:
                    request[field] = desired[field][:20]
            pending = {
                "desired": desired,
                "request": request,
                "before_ids": [r["panel_id"] for r in all_records],
                "sources": sources,
                "resource": f"new:{desired['scope']}",
            }
            await self.put_local(appid, "pending_create", pending)
            try:
                response = await self.client.request(
                    credentials, "POST", "/v2/panels", body=request
                )
            except UncertainWrite:
                return await self._recover_create(credentials, pending)
            except OrderUIError:
                await self.put_local(appid, "pending_create", {})
                raise
            panel_id = response.get("panel_id")
            if not panel_id:
                return await self._recover_create(credentials, pending)
            pending["panel_id"] = panel_id
            await self.put_local(appid, "pending_create", pending)
            return await self._finish_create(credentials, pending)

    async def _recover_create(self, credentials, pending):
        if not pending.get("panel_id"):
            candidates = []
            for record in await self.list_remote(credentials, pending["desired"]["scope"]):
                if record.get("panel_id") in pending["before_ids"]:
                    continue
                candidate = await self.panel_remote(credentials, record["panel_id"])
                expected = canonical_panel({**pending["request"], "panel_id": record["panel_id"]})
                if all(
                    candidate[k] == expected[k]
                    for k in ("scope", "target_type", "panel", "user_openids", "group_openids")
                ):
                    candidates.append(candidate)
            if len(candidates) != 1:
                raise UncertainWrite(
                    "无法唯一确认创建结果。新建已锁定，请刷新列表核对，不要重复创建。"
                )
            pending["panel_id"] = candidates[0]["panel_id"]
            await self.put_local(credentials[0], "pending_create", pending)
        return {**await self._finish_create(credentials, pending), "recovered": True}

    async def recover_create(self, body):
        credentials = self.resolve(body.get("platform_id"))
        async with self.locks[credentials[0]]:
            pending = await self.local(credentials[0], "pending_create")
            if not pending:
                raise OrderUIError("没有待核对的创建操作")
            return await self._recover_create(credentials, pending)

    async def unlock_create(self, body):
        credentials = self.resolve(body.get("platform_id"))
        if body.get("confirmed_checked") is not True:
            raise OrderUIError("请先人工核对 QQ 面板列表")
        async with self.locks[credentials[0]]:
            pending = await self.local(credentials[0], "pending_create")
            if pending.get("panel_id"):
                raise OrderUIError("QQ 已返回面板 ID，请使用恢复创建结果完成回读")
            await self.put_local(credentials[0], "pending_create", {})
        return {"unlocked": True}

    async def _finish_create(self, credentials, pending):
        panel_id = pending["panel_id"]
        remote = await self.panel_remote(credentials, panel_id)
        result = await self._targets(credentials, remote, pending["desired"])
        response = await self._finish_panel(
            credentials[0], panel_id, result, pending["desired"], pending["sources"]
        )
        await self.put_local(credentials[0], pending["resource"], {})
        await self.put_local(credentials[0], "pending_create", {})
        return response

    async def update_panel(self, body):
        credentials = self.resolve(body.get("platform_id"))
        desired = validate_panel(body.get("document"), for_publish=True)
        sources = await self.check_sources(body)
        panel_id = text(body.get("panel_id"), "面板 ID", 160, weighted=False)
        async with self.locks[credentials[0]]:
            remote = await self.panel_remote(credentials, panel_id)
            self.conflict(remote, body.get("baseline"))
            if any(remote[k] != desired[k] for k in ("scope", "target_type")):
                raise OrderUIError("已有面板不能修改场景或作用范围，请新建面板")
            await self.remember(credentials[0], f"panel:{panel_id}", remote)
            if remote["panel"] != desired["panel"]:
                try:
                    await self.client.request(
                        credentials,
                        "PUT",
                        f"/v2/panels/{quote(panel_id, safe='')}",
                        body={"panel": desired["panel"]},
                    )
                except UncertainWrite as exc:
                    current = await self.panel_remote(credentials, panel_id)
                    if current["panel"] != desired["panel"]:
                        raise exc from None
                remote = await self.panel_remote(credentials, panel_id)
                if remote["panel"] != desired["panel"]:
                    raise UncertainWrite("QQ 已接受面板更新，但回读尚未一致，请刷新核对")
            result = await self._targets(credentials, remote, desired)
            return await self._finish_panel(credentials[0], panel_id, result, desired, sources)

    async def _targets(self, credentials, remote, desired):
        field = "user_openids" if remote["scope"] == "c2c" else "group_openids"
        current = deepcopy(remote)
        failures = []
        if remote["target_type"] == "specific":
            for op in ("del", "add"):
                existing, wanted = set(current[field]), set(desired[field])
                delta = sorted(existing - wanted if op == "del" else wanted - existing)
                for offset in range(0, len(delta), 20):
                    batch = delta[offset : offset + 20]
                    try:
                        await self.client.request(
                            credentials,
                            "PUT",
                            f"/v2/panels/{quote(remote['panel_id'], safe='')}/target",
                            body={"op": op, field: batch},
                        )
                    except OrderUIError as exc:
                        try:
                            current = await self.panel_remote(credentials, remote["panel_id"])
                        except OrderUIError:
                            failures.append(
                                {
                                    "op": op,
                                    "openids": batch,
                                    "error": exc.as_dict(),
                                    "unverified": True,
                                }
                            )
                            return {"document": current, "partial": True, "failures": failures}
                        unfinished = sorted(
                            set(batch) - set(current[field])
                            if op == "add"
                            else set(batch) & set(current[field])
                        )
                        if unfinished:
                            failures.append(
                                {"op": op, "openids": unfinished, "error": exc.as_dict()}
                            )
                            return {"document": current, "partial": True, "failures": failures}
                    else:
                        current[field] = sorted(
                            set(current[field]) | set(batch)
                            if op == "add"
                            else set(current[field]) - set(batch)
                        )
        try:
            current = await self.panel_remote(credentials, remote["panel_id"])
        except OrderUIError as exc:
            return {
                "document": current,
                "partial": True,
                "failures": [{"error": exc.as_dict(), "unverified": True}],
            }
        partial = set(current[field]) != set(desired[field])
        return {"document": current, "partial": partial, "failures": failures}

    async def _finish_panel(self, appid, panel_id, result, desired, sources):
        resource = f"panel:{panel_id}"
        response = await self.complete(appid, resource, result["document"], sources)
        if result["partial"]:
            saved = await self.local(appid, resource)
            saved["draft"] = {
                "document": {**desired, "panel_id": panel_id},
                "baseline": response["baseline"],
                "sources": sources,
            }
            await self.put_local(appid, resource, saved)
            response.update(saved)
        field = "user_openids" if desired["scope"] == "c2c" else "group_openids"
        current, wanted = set(result["document"][field]), set(desired[field])
        return {
            **response,
            "partial": result["partial"],
            "failures": result["failures"],
            "targets": {
                "current": sorted(current),
                "remaining_add": sorted(wanted - current),
                "remaining_remove": sorted(current - wanted),
                "verified": not any(f.get("unverified") for f in result["failures"]),
            },
        }

    async def targets(self, body):
        return await self.update_panel(body)

    async def delete_panel(self, body):
        credentials = self.resolve(body.get("platform_id"))
        panel_id = text(body.get("panel_id"), "面板 ID", 160, weighted=False)
        async with self.locks[credentials[0]]:
            remote = await self.panel_remote(credentials, panel_id)
            self.conflict(remote, body.get("baseline"))
            await self.remember(credentials[0], f"panel:{panel_id}", remote)
            try:
                await self.client.request(
                    credentials, "DELETE", f"/v2/panels/{quote(panel_id, safe='')}"
                )
            except UncertainWrite as exc:
                records = await self.list_remote(credentials, remote["scope"])
                if any(r.get("panel_id") == panel_id for r in records):
                    raise exc from None
            await self.put_local(credentials[0], f"panel:{panel_id}", {"backup": remote})
        return {"deleted": True}
