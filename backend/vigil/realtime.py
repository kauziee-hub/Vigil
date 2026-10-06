"""WebSocket topic hub. Push only — no client polling anywhere.

Topics: `console` (bank / command center), `pay:<account_id>` (payer screen),
`contact:<token>` (trusted contact phone). Envelope: {type, ts, data}.

`publish()` is synchronous and non-blocking (queue put), so domain code can
call it from inside a DB transaction without awaiting.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket

from vigil import clock


class Hub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self.published = 0

    def subscribe(self, topics: list[str]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        for topic in topics:
            self._subs.setdefault(topic, set()).add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        for subs in self._subs.values():
            subs.discard(queue)

    def publish(self, topic: str, event_type: str, data: Any) -> None:
        envelope = {"type": event_type, "topic": topic, "ts": clock.now_iso(), "data": data}
        self.published += 1
        for queue in list(self._subs.get(topic, ())):
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                pass  # slow client: drop rather than block the decision path

    def clients(self) -> int:
        return len({id(q) for subs in self._subs.values() for q in subs})


HUB = Hub()


async def serve(ws: WebSocket, topics: list[str]) -> None:
    await ws.accept()
    queue = HUB.subscribe(topics)
    await ws.send_json({"type": "hello", "topic": "*", "ts": clock.now_iso(), "data": {"topics": topics}})

    async def pump() -> None:
        while True:
            await ws.send_json(await queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive_text()  # keep-alive pings from client
            if msg == "ping":
                await ws.send_json({"type": "pong", "topic": "*", "ts": clock.now_iso(), "data": {}})
    except Exception:
        pass
    finally:
        sender.cancel()
        HUB.unsubscribe(queue)
