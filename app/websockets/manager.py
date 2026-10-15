from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class TicketConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, list[tuple[WebSocket, int, str]]] = defaultdict(list)

    async def connect(self, ticket_id: int, websocket: WebSocket, user_id: int, role: str) -> None:
        await websocket.accept()
        self.connections[ticket_id].append((websocket, user_id, role))

    def disconnect(self, ticket_id: int, websocket: WebSocket) -> None:
        entries = self.connections.get(ticket_id, [])
        self.connections[ticket_id] = [item for item in entries if item[0] is not websocket]
        if not self.connections[ticket_id]:
            self.connections.pop(ticket_id, None)

    def is_connected(self, ticket_id: int, user_id: int) -> bool:
        return any(uid == user_id for _, uid, _ in self.connections.get(ticket_id, []))

    async def broadcast(self, ticket_id: int, payload: dict[str, Any], internal: bool = False) -> None:
        stale: list[WebSocket] = []
        for websocket, _user_id, role in list(self.connections.get(ticket_id, [])):
            if internal and role == "Customer":
                continue
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(ticket_id, websocket)


class NotificationConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self.connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        self.connections[user_id] = [ws for ws in self.connections.get(user_id, []) if ws is not websocket]
        if not self.connections[user_id]:
            self.connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self.connections.get(user_id, [])):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket, user_id)

    async def broadcast_role(self, user_ids: list[int], payload: dict[str, Any]) -> None:
        for user_id in set(user_ids):
            await self.send_to_user(user_id, payload)


ticket_manager = TicketConnectionManager()
notification_manager = NotificationConnectionManager()
