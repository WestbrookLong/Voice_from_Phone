import argparse
import asyncio
import json
import secrets
import socket
import time
from pathlib import Path
from typing import Any

from aiohttp import web


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
IMAGES_DIR = DATA_DIR / "images"
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class ProjectRoom:
    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.clients: list[web.WebSocketResponse] = []
        self.last_activity = time.time()
        self.text_snapshot = ""
        self.text_path = PROJECTS_DIR / f"{project_id}.txt"
        self.last_state_b64: str | None = None
        if self.text_path.exists():
            self.text_snapshot = self.text_path.read_text(encoding="utf-8")
        else:
            self.text_snapshot = (
                "\\documentclass{article}\n"
                "\\usepackage[UTF8]{ctex}\n"
                "\\begin{document}\n"
                "Hello, LaTeX!\n"
                "\\end{document}\n"
            )
            self._save_text()

    def _save_text(self) -> None:
        self.text_path.write_text(self.text_snapshot, encoding="utf-8")

    def update_snapshot(self, text: str) -> None:
        self.text_snapshot = text
        self.last_activity = time.time()
        self._save_text()

    def add_client(self, ws: web.WebSocketResponse) -> None:
        if ws not in self.clients:
            self.clients.append(ws)
        self.last_activity = time.time()

    def remove_client(self, ws: web.WebSocketResponse) -> None:
        if ws in self.clients:
            self.clients.remove(ws)
        self.last_activity = time.time()

    async def broadcast(self, message: dict[str, Any], exclude: web.WebSocketResponse | None = None) -> None:
        data = json.dumps(message)
        dead: list[web.WebSocketResponse] = []
        for client in self.clients:
            if client is exclude:
                continue
            if client.closed:
                dead.append(client)
                continue
            try:
                await client.send_str(data)
            except Exception:
                dead.append(client)
        for d in dead:
            self.remove_client(d)


class CloudServer:
    def __init__(self) -> None:
        self.rooms: dict[str, ProjectRoom] = {}
        self.lock = asyncio.Lock()

    async def get_or_create_room(self, project_id: str) -> ProjectRoom:
        async with self.lock:
            if project_id not in self.rooms:
                self.rooms[project_id] = ProjectRoom(project_id)
            return self.rooms[project_id]

    async def remove_room_if_empty(self, project_id: str) -> None:
        async with self.lock:
            room = self.rooms.get(project_id)
            if room and not room.clients:
                del self.rooms[project_id]


server_state = CloudServer()


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=64 * 1024 * 1024)
    await ws.prepare(request)
    peer = request.remote or "unknown"
    print(f"[ws] connected: {peer}", flush=True)

    room: ProjectRoom | None = None

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                continue

            msg_type = payload.get("type")

            if msg_type == "auth":
                project_id = str(payload.get("project_id", "")).strip()
                if not project_id:
                    await ws.send_json({"type": "error", "message": "project_id required"})
                    await ws.close()
                    return ws
                room = await server_state.get_or_create_room(project_id)
                room.add_client(ws)
                # Send last known state if available
                if room.last_state_b64:
                    await ws.send_json({"type": "yjs_update", "data": room.last_state_b64})
                else:
                    # Ask another client to send full state
                    for client in room.clients:
                        if client is not ws and not client.closed:
                            await client.send_json({"type": "request_sync"})
                            break
                await ws.send_json({"type": "ready", "project_id": project_id})
                print(f"[ws] {peer} joined project {project_id}", flush=True)

            elif msg_type == "yjs_update" and room is not None:
                room.last_state_b64 = payload.get("data", "")
                await room.broadcast({"type": msg_type, "data": room.last_state_b64}, exclude=ws)

            elif msg_type == "yjs_awareness" and room is not None:
                await room.broadcast({"type": msg_type, "data": payload.get("data", "")}, exclude=ws)

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except Exception as exc:
        print(f"[ws] error: {exc}", flush=True)
    finally:
        if room is not None:
            room.remove_client(ws)
            if not room.clients:
                await server_state.remove_room_if_empty(room.project_id)
        print(f"[ws] disconnected: {peer}", flush=True)

    return ws


async def api_project_text(request: web.Request) -> web.Response:
    """Get current project text snapshot."""
    project_id = request.match_info.get("project_id", "").strip()
    if not project_id:
        return web.json_response({"error": "project_id required"}, status=400)
    room = await server_state.get_or_create_room(project_id)
    return web.json_response({"project_id": project_id, "text": room.text_snapshot})


async def api_project_snapshot(request: web.Request) -> web.Response:
    """Receive a text snapshot from a client (browser)."""
    project_id = request.match_info.get("project_id", "").strip()
    if not project_id:
        return web.json_response({"error": "project_id required"}, status=400)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)
    text = body.get("text", "")
    room = await server_state.get_or_create_room(project_id)
    room.update_snapshot(text)
    return web.json_response({"ok": True})


async def api_upload_image(request: web.Request) -> web.Response:
    project_id = request.match_info.get("project_id", "").strip()
    if not project_id:
        return web.json_response({"error": "project_id required"}, status=400)

    reader = await request.multipart()
    files: list[dict[str, str]] = []
    async for field in reader:
        if field.name != "image":
            continue
        filename = field.filename
        if not filename:
            continue
        filename = Path(filename).name
        project_img_dir = IMAGES_DIR / project_id
        project_img_dir.mkdir(parents=True, exist_ok=True)
        filepath = project_img_dir / filename
        with open(filepath, "wb") as f:
            while True:
                chunk = await field.read_chunk(size=8192)
                if not chunk:
                    break
                f.write(chunk)
        files.append({"filename": filename, "url": f"/api/projects/{project_id}/images/{filename}"})

    return web.json_response({"project_id": project_id, "files": files})


async def api_list_images(request: web.Request) -> web.Response:
    project_id = request.match_info.get("project_id", "").strip()
    if not project_id:
        return web.json_response({"error": "project_id required"}, status=400)
    project_img_dir = IMAGES_DIR / project_id
    if not project_img_dir.exists():
        return web.json_response({"project_id": project_id, "files": []})
    files = [
        {"filename": f.name, "url": f"/api/projects/{project_id}/images/{f.name}"}
        for f in project_img_dir.iterdir()
        if f.is_file()
    ]
    return web.json_response({"project_id": project_id, "files": files})


async def api_get_image(request: web.Request) -> web.Response:
    project_id = request.match_info.get("project_id", "").strip()
    filename = request.match_info.get("filename", "").strip()
    if not project_id or not filename:
        return web.json_response({"error": "missing parameters"}, status=400)
    filepath = IMAGES_DIR / project_id / filename
    if not filepath.exists():
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(filepath)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def create_app() -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/api/projects/{project_id}/text", api_project_text)
    app.router.add_post("/api/projects/{project_id}/snapshot", api_project_snapshot)
    app.router.add_post("/api/projects/{project_id}/images", api_upload_image)
    app.router.add_get("/api/projects/{project_id}/images", api_list_images)
    app.router.add_get("/api/projects/{project_id}/images/{filename}", api_get_image)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LaTeX Cloud Sync Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=9800, help="Bind port")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app()
    lan_ip = get_lan_ip()
    print("LaTeX Cloud Sync Server is running.", flush=True)
    print(f"Local:   http://127.0.0.1:{args.port}", flush=True)
    print(f"Network: http://{lan_ip}:{args.port}", flush=True)
    print(f"WebSocket: ws://{lan_ip}:{args.port}/ws", flush=True)
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
