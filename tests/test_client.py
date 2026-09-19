import asyncio
from unittest.mock import AsyncMock

import pytest

from orderui.client import QQClient
from orderui.errors import OrderUIError, UncertainWrite


class Response:
    def __init__(self, status, data):
        self.status = status
        self.data = data
        self.headers = {"X-Tps-trace-ID": "trace-header"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


async def test_token_single_flight_refresh_and_secret_rotation():
    now = [0]
    client = QQClient(clock=lambda: now[0])
    client._send = AsyncMock(return_value={"access_token": "token", "expires_in": "7200"})
    assert (
        await asyncio.gather(*(client.token("app", "secret") for _ in range(10))) == ["token"] * 10
    )
    assert client._send.await_count == 1
    now[0] = 7141
    await client.token("app", "secret")
    assert client._send.await_count == 2
    await client.token("app", "new-secret")
    assert client._send.await_count == 3


def test_quotas_are_per_app_and_per_endpoint():
    now = [0]
    client = QQClient(clock=lambda: now[0])
    for _ in range(5):
        client.reserve("app", "PUT", "/v2/menu")
    with pytest.raises(OrderUIError) as exc:
        client.reserve("app", "PUT", "/v2/menu")
    assert exc.value.code == "rate_limit"
    client.reserve("other", "PUT", "/v2/menu")
    client.reserve("app", "GET", "/v2/menu")
    client.reserve("app", "PUT", "/v2/panels/p/target")
    now[0] = 60
    client.reserve("app", "PUT", "/v2/menu")


@pytest.mark.parametrize(
    ("status", "payload", "code"),
    [
        (200, {"code": 100016, "message": "bad secret"}, "auth"),
        (
            200,
            {"err_code": 40030020, "message": "rejected", "trace_id": "trace-body"},
            "content_rejected",
        ),
        (429, {}, "rate_limit"),
        (401, {}, "auth"),
        (500, {}, "uncertain"),
    ],
)
async def test_http_and_business_errors(status, payload, code):
    client = QQClient(Session(Response(status, payload)))
    with pytest.raises(OrderUIError) as exc:
        await client._send("PUT", "/v2/menu", token="private")
    assert exc.value.code == code
    assert exc.value.trace_id == payload.get("trace_id", "trace-header")


@pytest.mark.parametrize("payload", [ValueError("bad JSON"), TimeoutError(), []])
async def test_write_unknown_outcomes_are_not_retried(payload):
    session = Session(Response(200, payload))
    client = QQClient(session)
    with pytest.raises(UncertainWrite):
        await client._send("POST", "/v2/panels")
    assert len(session.calls) == 1


async def test_delete_no_content_and_no_frontend_credentials():
    session = Session(Response(204, None))
    client = QQClient(session)
    assert await client._send("DELETE", "/v2/panels/p", token="private") == {}
    assert session.calls[0][1]["headers"] == {"Authorization": "QQBot private"}


async def test_auth_error_invalidates_cached_token_without_retrying_write():
    client = QQClient()
    client.tokens["a"] = ("s", "old", float("inf"))
    client._send = AsyncMock(side_effect=OrderUIError("expired", "auth"))
    with pytest.raises(OrderUIError):
        await client.request(("a", "s"), "PUT", "/v2/menu")
    assert "a" not in client.tokens
    assert client._send.await_count == 1


def test_message_quota_is_independent_of_panel_writes():
    now = [0]
    client = QQClient(clock=lambda: now[0])
    for _ in range(100):
        client.reserve("a", "POST", "/v2/users/u/messages")
    with pytest.raises(OrderUIError):
        client.reserve("a", "POST", "/v2/groups/g/messages")
    client.reserve("a", "POST", "/v2/panels")
    client.reserve("b", "POST", "/v2/users/u/messages")
    now[0] = 1
    client.reserve("a", "POST", "/v2/groups/g/messages")
