import logging

import pytest
from quart import Quart, request

from orderui.dynamic_service import DynamicMenuService
from orderui.routes import Routes
from orderui.service import ManagementService
from tests.fakes import FakeQQ, Store, commands, menu


class Context:
    def __init__(self):
        self.registered_web_apis = []

    def register_web_api(self, route, handler, methods, desc):
        for index, entry in enumerate(self.registered_web_apis):
            if entry[0] == route and entry[2] == methods:
                self.registered_web_apis[index] = (route, handler, methods, desc)
                return
        self.registered_web_apis.append((route, handler, methods, desc))


def fixture_app():
    context, qq, store = Context(), FakeQQ(), Store()
    service = ManagementService(qq, store, lambda pid: (pid, "secret"), commands)
    dynamic = DynamicMenuService(store, service.resolve, commands, service.command_warnings)
    routes = Routes(
        context,
        service,
        lambda: [
            {"platform_id": "a", "appid": "a", "name": "测试机器人", "status": "running"},
            {"platform_id": "b", "appid": "b", "name": "第二个机器人", "status": "running"},
        ],
        commands,
        logging.getLogger("test"),
        dynamic,
    )
    routes.register()
    app = Quart(__name__)

    @app.before_request
    async def host_auth_fixture():
        if request.headers.get("Authorization") != "Bearer fixture":
            return {"status": "error", "message": "未授权"}, 401

    @app.route("/api/plug/<path:subpath>", methods=["GET", "POST"])
    async def plugin_gateway(subpath):
        for route, handler, methods, _ in context.registered_web_apis:
            if route.lstrip("/") == subpath and request.method in methods:
                return await handler()
        return {}, 404

    return app, routes, service, qq, context


@pytest.fixture
def setup():
    return fixture_app()


async def test_routes_host_auth_and_structured_errors(setup):
    app, _, _, qq, _ = setup
    client = app.test_client()
    url = "/api/plug/astrbot_plugin_orderui/"
    assert (await client.get(url + "bots")).status_code == 401
    headers = {"Authorization": "Bearer fixture"}
    result = await (await client.get(url + "menu?platform_id=a", headers=headers)).get_json()
    baseline = result["data"]["result"]["baseline"]
    result = await (
        await client.post(
            url + "menu/publish",
            headers=headers,
            json={"platform_id": "a", "document": menu(), "baseline": baseline},
        )
    ).get_json()
    assert result["data"]["ok"]
    result = await (
        await client.post(
            url + "menu/publish",
            headers=headers,
            json={"platform_id": "a", "document": menu(), "baseline": "stale"},
        )
    ).get_json()
    assert result["status"] == "ok"
    assert result["data"]["error"]["code"] == "conflict"
    assert len([c for c in qq.calls if c[1] == "PUT"]) == 1


async def test_invalid_request_and_disabled_routes(setup):
    app, routes, _, _, context = setup
    client = app.test_client()
    path = "/api/plug/astrbot_plugin_orderui/draft/save"
    headers = {"Authorization": "Bearer fixture"}
    data = await (await client.post(path, headers=headers, json=[])).get_json()
    assert data["data"]["error"]["code"] == "validation"
    context.register_web_api("/another/ping", lambda: None, ["GET"], "other plugin")
    routes.close()
    assert len(context.registered_web_apis) == 1
    assert (await client.post(path, headers=headers, json={})).status_code == 404


async def test_reload_cleanup_does_not_remove_new_instance_routes(setup):
    _, old, service, _, context = setup
    newer = Routes(context, service, old.bots, commands, old.logger)
    newer.register()
    old.close()
    assert len(context.registered_web_apis) == len(newer.owned)


async def test_dynamic_routes_require_auth_and_never_write_qq_configuration(setup):
    from tests.test_dynamic import catalogue

    app, routes, _, qq, _ = setup
    client = app.test_client()
    path = "/api/plug/astrbot_plugin_orderui/dynamic-menus"
    assert (await client.get(path + "?platform_id=a")).status_code == 401
    headers = {"Authorization": "Bearer fixture"}
    body = {"platform_id": "a", "document": catalogue(), "revision": 0}
    for endpoint in ("/draft", "/apply"):
        response = await (await client.post(path + endpoint, headers=headers, json=body)).get_json()
        assert response["data"]["ok"]
    assert qq.calls == []
    assert routes.dynamic.match("a", "group", "/工具箱")
