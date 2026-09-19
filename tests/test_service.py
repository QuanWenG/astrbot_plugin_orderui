import asyncio

import pytest

from orderui.errors import OrderUIError, UncertainWrite
from orderui.service import ManagementService
from tests.fakes import FakeQQ, Store, commands, menu, panel


@pytest.fixture
def setup():
    client, store = FakeQQ(), Store()
    service = ManagementService(client, store, lambda pid: (pid, "secret"), commands)
    return service, client, store


async def test_menu_publication_backup_conflict_and_isolation(setup):
    service, client, _ = setup
    initial = await service.get_menu("a")
    body = {"platform_id": "a", "document": menu(), "baseline": initial["baseline"]}
    await service.save_draft({**body, "resource": "menu"})
    assert (await service.get_menu("a"))["draft"]["document"] == menu()
    assert "draft" not in await service.get_menu("b")
    result = await service.publish_menu(body)
    assert result["document"]["menu"] == menu()["menu"]
    assert result["backup"]["menu"] == {"items": []}
    with pytest.raises(OrderUIError, match="远端配置已变化"):
        await service.publish_menu({**body, "document": menu("新帮助")})
    assert len([c for c in client.calls if c[1] == "PUT"]) == 1


async def test_menu_timeout_after_commit_recovers_without_retry(setup):
    service, client, _ = setup
    initial = await service.get_menu("a")

    def hook(method, path, body, phase):
        if method == "PUT" and phase == "after":
            raise UncertainWrite()

    client.hook = hook
    result = await service.publish_menu(
        {"platform_id": "a", "document": menu(), "baseline": initial["baseline"]}
    )
    assert result["recovered"]
    assert len([c for c in client.calls if c[1] == "PUT"]) == 1


async def test_same_app_concurrent_publication_only_one_writes(setup):
    service, client, _ = setup
    base = (await service.get_menu("a"))["baseline"]
    results = await asyncio.gather(
        *(
            service.publish_menu({"platform_id": "a", "document": menu(), "baseline": base})
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(r, OrderUIError) for r in results) == 1
    assert len([c for c in client.calls if c[1] == "PUT"]) == 1


async def test_command_change_requires_ack(setup):
    service, client, _ = setup
    base = (await service.get_menu("a"))["baseline"]
    body = {
        "platform_id": "a",
        "document": menu(),
        "baseline": base,
        "sources": [{"handler_full_name": "missing", "effective_command": "old"}],
    }
    with pytest.raises(OrderUIError) as exc:
        await service.publish_menu(body)
    assert exc.value.code == "command_changed"
    assert not any(c[1] == "PUT" for c in client.calls)
    assert (await service.publish_menu({**body, "ack_warnings": True}))["document"]


async def test_create_batches_targets_and_partial_retry_only_missing(setup):
    service, client, _ = setup
    failed = False

    def hook(method, path, body, phase):
        nonlocal failed
        if path.endswith("/target") and phase == "before" and not failed:
            failed = True
            raise OrderUIError("限流", "rate_limit")

    client.hook = hook
    desired = panel("group", "specific", 45)
    result = await service.create_panel({"platform_id": "a", "document": desired})
    assert result["partial"]
    assert len(result["document"]["group_openids"]) == 20
    assert len(result["draft"]["document"]["group_openids"]) == 45
    client.calls.clear()
    final = await service.update_panel(
        {"platform_id": "a", "panel_id": "p1", "baseline": result["baseline"], "document": desired}
    )
    assert not final["partial"]
    batches = [c[3]["group_openids"] for c in client.calls if c[2].endswith("/target")]
    assert sorted(map(len, batches)) == [5, 20]
    assert not set(sum(batches, [])).intersection(result["document"]["group_openids"])


async def test_create_timeout_recovers_and_never_repeats_post(setup):
    service, client, _ = setup

    def hook(method, path, body, phase):
        if method == "POST" and phase == "after":
            raise UncertainWrite()

    client.hook = hook
    result = await service.create_panel({"platform_id": "a", "document": panel()})
    assert result["recovered"] and result["document"]["panel_id"] == "p1"
    assert len([c for c in client.calls if c[1] == "POST"]) == 1


async def test_pending_creation_survives_restart_and_blocks_duplicate(setup):
    service, client, store = setup

    def hook(method, path, body, phase):
        if method == "POST" and phase == "before":
            raise UncertainWrite()

    client.hook = hook
    with pytest.raises(UncertainWrite):
        await service.create_panel({"platform_id": "a", "document": panel()})
    restarted = ManagementService(client, store, service.resolve, commands)
    with pytest.raises(OrderUIError) as exc:
        await restarted.create_panel({"platform_id": "a", "document": panel()})
    assert exc.value.code == "pending_create"
    assert len([c for c in client.calls if c[1] == "POST"]) == 1


async def test_create_quota_and_immutable_scope(setup):
    service, client, _ = setup
    result = await service.create_panel({"platform_id": "a", "document": panel()})
    sent = next(c[3] for c in client.calls if c[1] == "POST")
    assert "user_openids" not in sent and "group_openids" not in sent
    with pytest.raises(OrderUIError, match="不能修改"):
        await service.update_panel(
            {
                "platform_id": "a",
                "panel_id": "p1",
                "document": panel("dm"),
                "baseline": result["baseline"],
            }
        )
    for i in range(20):
        client.panels[("a", f"p{i}")] = {**panel(), "panel_id": f"p{i}"}
    with pytest.raises(OrderUIError, match="20"):
        await service.create_panel({"platform_id": "a", "document": panel()})


async def test_target_timeout_after_commit_readback_avoids_duplicate(setup):
    service, client, _ = setup

    def hook(method, path, body, phase):
        if path.endswith("/target") and phase == "after":
            raise UncertainWrite()

    client.hook = hook
    result = await service.create_panel(
        {"platform_id": "a", "document": panel("c2c", "specific", 25)}
    )
    assert not result["partial"]
    assert len([c for c in client.calls if c[2].endswith("/target")]) == 1


async def test_delete_timeout_readback(setup):
    service, client, _ = setup
    result = await service.create_panel({"platform_id": "a", "document": panel()})

    def hook(method, path, body, phase):
        if method == "DELETE" and phase == "after":
            raise UncertainWrite()

    client.hook = hook
    assert (
        await service.delete_panel(
            {"platform_id": "a", "panel_id": "p1", "baseline": result["baseline"]}
        )
    )["deleted"]


async def test_target_removal_and_persisted_backup(setup):
    service, _, _ = setup
    result = await service.create_panel(
        {"platform_id": "a", "document": panel("group", "specific", 25)}
    )
    desired = panel("group", "specific", 3)
    result = await service.update_panel(
        {"platform_id": "a", "panel_id": "p1", "document": desired, "baseline": result["baseline"]}
    )
    assert len(result["document"]["group_openids"]) == 3
    assert len(result["backup"]["group_openids"]) == 25


@pytest.mark.parametrize("operation", ["create_panel", "update_panel"])
async def test_empty_panel_publication_rejected_before_qq_request(setup, operation):
    service, client, _ = setup
    desired = panel("group")
    desired["panel"] = {"items": [], "remark": ""}
    with pytest.raises(OrderUIError, match="至少需要一个元素"):
        await getattr(service, operation)(
            {"platform_id": "a", "panel_id": "p1", "document": desired}
        )
    assert client.calls == []


async def test_empty_remote_panel_can_be_drafted_populated_and_deleted(setup):
    service, client, _ = setup
    empty = {**panel("group"), "panel_id": "p1", "version": 1}
    empty["panel"] = {"items": [], "remark": ""}
    client.panels[("a", "p1")] = empty
    initial = await service.get_panel("a", "p1")
    await service.save_draft({"platform_id": "a", "resource": "panel:p1", **initial})
    assert (await service.get_panel("a", "p1"))["draft"]["document"]["panel"]["items"] == []
    result = await service.update_panel(
        {
            "platform_id": "a",
            "panel_id": "p1",
            "document": panel("group"),
            "baseline": initial["baseline"],
        }
    )
    assert result["document"]["panel"]["items"] == panel("group")["panel"]["items"]
    client.panels[("a", "p1")] = empty
    initial = await service.get_panel("a", "p1")
    assert (
        await service.delete_panel(
            {"platform_id": "a", "panel_id": "p1", "baseline": initial["baseline"]}
        )
    )["deleted"]
