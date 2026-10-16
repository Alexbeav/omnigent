"""The real session store and runner transport, without any provider requests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from omnigent.entities.conversation import MessageData, NewConversationItem
from omnigent.server.routes.sessions.routes_reply_suggestions import (
    register_reply_suggestion_routes,
)
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

pytestmark = pytest.mark.asyncio


def append(store, session_id, response_id, role="assistant", text="Here is the diff."):
    return store.append(
        session_id,
        [
            NewConversationItem(
                type="message",
                response_id=response_id,
                data=MessageData(
                    role=role,
                    agent="test-agent" if role == "assistant" else None,
                    content=[
                        {
                            "type": "output_text" if role == "assistant" else "input_text",
                            "text": text,
                        }
                    ],
                ),
            )
        ],
    )


@pytest.mark.parametrize("late", [False, True])
async def test_singleflight_cache_usage_and_late_turn(db_uri, late):
    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(kind="default")
    append(store, conv.id, "r1", "user", "Please inspect this change.")
    append(store, conv.id, "r1")
    calls = []
    entered, finish = asyncio.Event(), asyncio.Event()

    async def handle(request):
        calls.append(request)
        entered.set()
        await finish.wait()
        body = json.loads(request.content)
        assert "Here is the diff." in body["prompt"] and len(body["prompt"]) <= 6000
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "text": "Show the tests.",
                "model": "economy-test",
                "usage": {"input_tokens": 20, "output_tokens": 5},
            },
        )

    runner = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://runner")
    router = APIRouter()
    register_reply_suggestion_routes(
        router,
        conversation_store=store,
        runner_router=SimpleNamespace(
            client_for_existing_conversation=lambda _: SimpleNamespace(client=runner)
        ),
        auth_provider=None,
        permission_store=None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    async with (
        runner,
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://server") as client,
    ):
        url = f"/v1/sessions/{conv.id}/next-reply"
        body = {"enabled": True, "source_response_id": "r1", "request_id": "one"}
        first = asyncio.create_task(client.post(url, json=body))
        await entered.wait()
        second = asyncio.create_task(client.post(url, json={**body, "request_id": "two"}))
        if late:
            append(store, conv.id, "r2", "user", "My next instruction.")
        finish.set()
        results = await asyncio.gather(first, second)
        assert len(calls) == 1
        assert results[0].json()["status"] == ("stale" if late else "ready")
        if not late:
            assert results[1].json()["text"] == "Show the tests."
            assert (await client.post(url, json=body)).json()["text"] == "Show the tests."
            assert len(calls) == 1
        usage = (await client.get(url + "/usage")).json()
        assert usage["usage"] == {"input_tokens": 20, "output_tokens": 5}
        assert store.get_conversation(conv.id).session_usage == {}
        assert len(store.list_items(conv.id).data) == (3 if late else 2)
        assert (await client.post(url, json={**body, "enabled": False})).status_code == 422


async def test_missing_runner_and_stale_turn_are_graceful(db_uri):
    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(kind="default")
    append(store, conv.id, "r1")
    router = APIRouter()
    register_reply_suggestion_routes(
        router,
        conversation_store=store,
        runner_router=None,
        auth_provider=None,
        permission_store=None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://server"
    ) as client:
        url = f"/v1/sessions/{conv.id}/next-reply"
        body = {"enabled": True, "source_response_id": "r1", "request_id": "one"}
        assert (await client.post(url, json=body)).json()["status"] == "unsupported"
        assert (await client.post(url, json={**body, "source_response_id": "old"})).json()[
            "status"
        ] == "stale"


async def test_async_question_and_preemptive_cancel_never_generate(db_uri, monkeypatch):
    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(kind="default")
    append(store, conv.id, "r1")
    real_list = store.list_items
    outstanding = True

    def question_items(*args, **kwargs):
        page = real_list(*args, **kwargs)
        if outstanding:
            # The question branch adds this typed field; preserve the base-branch boundary.
            page.data[0].data = page.data[0].data.model_copy(
                update={"async_user_input": {"questions": [{"title": "May I proceed?"}]}}
            )
        return page

    monkeypatch.setattr(store, "list_items", question_items)

    def no_runner(_):
        raise AssertionError("No request may answer a pending async question")

    router = APIRouter()
    register_reply_suggestion_routes(
        router,
        conversation_store=store,
        runner_router=SimpleNamespace(client_for_existing_conversation=no_runner),
        auth_provider=None,
        permission_store=None,
    )
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://server"
    ) as client:
        url = f"/v1/sessions/{conv.id}/next-reply"
        body = {"enabled": True, "source_response_id": "r1", "request_id": "cancel-first"}
        assert (await client.post(url, json=body)).json()["status"] == "stale"
        outstanding = False
        await client.delete(url + "/cancel-first")
        assert (await client.post(url, json=body)).json()["status"] == "unavailable"


async def test_read_only_user_cannot_generate_or_cancel(db_uri):
    from omnigent.entities.permission import ResolvedAccess
    from omnigent.errors import ErrorCode, OmnigentError

    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(kind="default")
    append(store, conv.id, "r1")
    router = APIRouter()
    register_reply_suggestion_routes(
        router,
        conversation_store=store,
        runner_router=None,
        auth_provider=SimpleNamespace(get_user_id=lambda _: "read-user"),
        permission_store=SimpleNamespace(resolve_access=lambda *_: ResolvedAccess(False, 1, None)),
    )
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://server"
    ) as client:
        url = f"/v1/sessions/{conv.id}/next-reply"
        for method, endpoint, kwargs in (
            (
                "POST",
                url,
                {"json": {"enabled": True, "source_response_id": "r1", "request_id": "one"}},
            ),
            ("DELETE", url + "/one", {}),
            ("GET", url + "/usage", {}),
        ):
            with pytest.raises(OmnigentError) as error:
                await client.request(method, endpoint, **kwargs)
            assert error.value.code == ErrorCode.FORBIDDEN


async def test_question_reply_resolves_only_its_correlated_source():
    from omnigent.server.routes.sessions.routes_reply_suggestions import pending_async_question

    question = SimpleNamespace(
        id="question-1",
        data=MessageData(role="assistant", agent="test", content=[]).model_copy(
            update={"async_user_input": {"questions": []}}
        ),
    )
    reply = SimpleNamespace(
        id="reply",
        data=MessageData(role="user", content=[]).model_copy(
            update={"async_question_reply": {"source_item_id": "question-1", "cancelled": True}}
        ),
    )
    assert pending_async_question([question], set())
    assert not pending_async_question([reply, question], set())
