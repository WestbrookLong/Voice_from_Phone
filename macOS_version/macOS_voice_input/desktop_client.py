import asyncio
import queue
import secrets
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from aiohttp import web
from PIL import ImageTk
import qrcode

from server import create_app, get_lan_ip
from tunnel import CloudflaredTunnelThread, find_cloudflared


class BridgeServerThread(threading.Thread):
    def __init__(self, host: str, port: int, token: str, events: queue.Queue[str]) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.token = token
        self.events = events
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner: web.AppRunner | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._start())
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self._cleanup())
            self.loop.close()

    async def _start(self) -> None:
        app = create_app(self.token)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        self.events.put("started")

    async def _cleanup(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()

    def stop(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)


class DesktopClient(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("手机实时输入桥接 macOS")
        self.geometry("640x390")
        self.minsize(580, 360)

        self.events: queue.Queue[object] = queue.Queue()
        self.server_thread: BridgeServerThread | None = None
        self.tunnel_thread: CloudflaredTunnelThread | None = None
        self.lan_ip = get_lan_ip()

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8787")
        self.status_var = tk.StringVar(value="未启动")
        self.url_var = tk.StringVar(value="")
        self.public_url_var = tk.StringVar(value="")
        self.tunnel_status_var = tk.StringVar(value="公网: 未启动")
        self.qr_image: ImageTk.PhotoImage | None = None

        self._build_ui()
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(root, text="手机实时输入桥接 macOS", font=("Helvetica Neue", 18, "bold"))
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(root, text="启动后，手机 App 或网页输入会实时写入 Mac 当前光标位置。")
        subtitle.pack(anchor=tk.W, pady=(4, 16))

        form = ttk.Frame(root)
        form.pack(fill=tk.X)

        ttk.Label(form, text="端口").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(form, textvariable=self.port_var, width=12).grid(row=0, column=1, sticky=tk.W, pady=4)

        ttk.Label(form, text="Token").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(form, textvariable=self.token_var).grid(row=1, column=1, sticky=tk.EW, pady=4)
        ttk.Button(form, text="重新生成", command=self._regenerate_token).grid(row=1, column=2, padx=(8, 0), pady=4)
        form.columnconfigure(1, weight=1)

        ttk.Label(root, text="手机访问地址").pack(anchor=tk.W, pady=(16, 4))
        url_row = ttk.Frame(root)
        url_row.pack(fill=tk.X)
        ttk.Entry(url_row, textvariable=self.url_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(url_row, text="复制", command=self._copy_url).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(root, text="公网访问地址").pack(anchor=tk.W, pady=(12, 4))
        public_url_row = ttk.Frame(root)
        public_url_row.pack(fill=tk.X)
        ttk.Entry(public_url_row, textvariable=self.public_url_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(public_url_row, text="复制", command=self._copy_public_url).pack(side=tk.LEFT, padx=(8, 0))

        qr_panel = ttk.Frame(root)
        qr_panel.pack(fill=tk.X, pady=(14, 0))
        self.qr_label = ttk.Label(qr_panel)
        self.qr_label.pack(side=tk.LEFT)
        ttk.Label(
            qr_panel,
            text="手机 App 点击“扫码连接”，或用手机浏览器打开地址。macOS 需允许 Terminal/Python 控制输入。",
            foreground="#666666",
            wraplength=330,
        ).pack(side=tk.LEFT, padx=(14, 0), anchor=tk.N)

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=(18, 8))
        self.start_button = ttk.Button(controls, text="启动服务", command=self._start_server)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="停止服务", command=self._stop_server, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="打开网页版", command=self._open_web_page).pack(side=tk.LEFT, padx=(8, 0))
        self.public_start_button = ttk.Button(controls, text="启动公网", command=self._start_tunnel)
        self.public_start_button.pack(side=tk.LEFT, padx=(8, 0))
        self.public_stop_button = ttk.Button(controls, text="停止公网", command=self._stop_tunnel, state=tk.DISABLED)
        self.public_stop_button.pack(side=tk.LEFT, padx=(8, 0))

        status = ttk.Label(root, textvariable=self.status_var, foreground="#0f6b5f")
        status.pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(root, textvariable=self.tunnel_status_var, foreground="#666666").pack(anchor=tk.W, pady=(4, 0))

        note = ttk.Label(
            root,
            text="使用前先把 Mac 光标放到目标输入框。若输入无效，请在“系统设置 -> 隐私与安全性”中给 Terminal 或 Python 开启“辅助功能”和“输入监控”。",
            foreground="#666666",
            wraplength=590,
        )
        note.pack(anchor=tk.W, pady=(16, 0))

    def _start_server(self) -> None:
        if self.server_thread is not None:
            return

        try:
            port = int(self.port_var.get())
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("端口错误", "请输入 1-65535 之间的端口。")
            return

        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Token 错误", "Token 不能为空。")
            return

        self.status_var.set("启动中...")
        self.server_thread = BridgeServerThread("0.0.0.0", port, token, self.events)
        self.server_thread.start()
        self._update_url()

    def _stop_server(self) -> None:
        self._stop_tunnel()
        if self.server_thread is not None:
            self.server_thread.stop()
            self.server_thread = None
        self.status_var.set("已停止")
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def _regenerate_token(self) -> None:
        if self.server_thread is not None:
            messagebox.showinfo("服务运行中", "请先停止服务，再重新生成 Token。")
            return
        self.token_var.set(secrets.token_urlsafe(12))
        self._update_url()

    def _copy_url(self) -> None:
        url = self.url_var.get()
        if not url:
            self._update_url()
            url = self.url_var.get()
        self.clipboard_clear()
        self.clipboard_append(url)
        self.status_var.set("地址已复制")

    def _copy_public_url(self) -> None:
        url = self.public_url_var.get()
        if not url:
            self.status_var.set("公网地址尚未生成")
            return
        self.clipboard_clear()
        self.clipboard_append(url)
        self.status_var.set("公网地址已复制")

    def _open_web_page(self) -> None:
        import webbrowser

        self._update_url()
        webbrowser.open(self.url_var.get())

    def _update_url(self) -> None:
        port = self.port_var.get().strip() or "8787"
        token = self.token_var.get().strip()
        url = f"http://{self.lan_ip}:{port}/?token={token}"
        self.url_var.set(url)
        self._update_qr(url)

    def _current_port(self) -> int | None:
        try:
            port = int(self.port_var.get())
            if port <= 0 or port > 65535:
                raise ValueError
            return port
        except ValueError:
            messagebox.showerror("端口错误", "请输入 1-65535 之间的端口。")
            return None

    def _start_tunnel(self) -> None:
        if self.tunnel_thread is not None:
            return
        port = self._current_port()
        if port is None:
            return
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Token 错误", "Token 不能为空。")
            return
        cloudflared_path = find_cloudflared()
        if cloudflared_path is None:
            messagebox.showerror(
                "cloudflared 未找到",
                "未找到 cloudflared。请先执行 `brew install cloudflared`，或确保 cloudflared 在 PATH 中。",
            )
            return
        if self.server_thread is None:
            self._start_server()
        self.public_url_var.set("")
        self.tunnel_status_var.set("公网: 启动中...")
        self.tunnel_thread = CloudflaredTunnelThread(cloudflared_path, port, self.events)
        self.tunnel_thread.start()
        self.public_start_button.configure(state=tk.DISABLED)
        self.public_stop_button.configure(state=tk.NORMAL)

    def _stop_tunnel(self) -> None:
        if self.tunnel_thread is not None:
            self.tunnel_thread.stop()
            self.tunnel_thread = None
        self.public_url_var.set("")
        self.tunnel_status_var.set("公网: 未启动")
        if hasattr(self, "public_start_button"):
            self.public_start_button.configure(state=tk.NORMAL)
        if hasattr(self, "public_stop_button"):
            self.public_stop_button.configure(state=tk.DISABLED)

    def _update_public_url(self, base_url: str) -> None:
        token = self.token_var.get().strip()
        base = base_url.rstrip("/")
        url = f"{base}/?token={token}"
        self.public_url_var.set(url)
        self._update_qr(url)

    def _update_qr(self, url: str) -> None:
        image = qrcode.make(url).resize((180, 180))
        self.qr_image = ImageTk.PhotoImage(image)
        self.qr_label.configure(image=self.qr_image)

    def _poll_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "started":
                self.status_var.set("服务已启动")
                self.start_button.configure(state=tk.DISABLED)
                self.stop_button.configure(state=tk.NORMAL)
            elif isinstance(event, dict):
                event_type = event.get("type")
                if event_type == "tunnel_started":
                    self.tunnel_status_var.set("公网: 连接中...")
                elif event_type == "tunnel_url":
                    url = str(event.get("url", ""))
                    self._update_public_url(url)
                    self.tunnel_status_var.set("公网: 已连接")
                elif event_type == "tunnel_error":
                    self.tunnel_status_var.set("公网: 出错")
                    messagebox.showerror("Tunnel error", str(event.get("message", "Unknown tunnel error.")))
                    self._stop_tunnel()
                elif event_type == "tunnel_exit":
                    if self.tunnel_thread is not None:
                        self.tunnel_thread = None
                        self.public_start_button.configure(state=tk.NORMAL)
                        self.public_stop_button.configure(state=tk.DISABLED)
                        self.public_url_var.set("")
                        self.tunnel_status_var.set(f"公网: 已停止 ({event.get('code')})")
        self.after(200, self._poll_events)

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()


def main() -> None:
    app = DesktopClient()
    app.mainloop()


if __name__ == "__main__":
    main()
