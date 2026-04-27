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
        self.title("手机实时输入桥接")
        self.geometry("620x360")
        self.minsize(560, 330)

        self.events: queue.Queue[str] = queue.Queue()
        self.server_thread: BridgeServerThread | None = None
        self.lan_ip = get_lan_ip()

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8787")
        self.status_var = tk.StringVar(value="未启动")
        self.url_var = tk.StringVar(value="")
        self.qr_image: ImageTk.PhotoImage | None = None

        self._build_ui()
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(root, text="手机实时输入桥接", font=("Microsoft YaHei UI", 18, "bold"))
        title.pack(anchor=tk.W)

        subtitle = ttk.Label(root, text="启动后，手机 App 或网页输入会实时写入电脑当前光标位置。")
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

        qr_panel = ttk.Frame(root)
        qr_panel.pack(fill=tk.X, pady=(14, 0))
        self.qr_label = ttk.Label(qr_panel)
        self.qr_label.pack(side=tk.LEFT)
        ttk.Label(
            qr_panel,
            text="手机 App 点击“扫码连接”，扫描这里即可自动填充地址和 Token。",
            foreground="#666666",
            wraplength=300,
        ).pack(side=tk.LEFT, padx=(14, 0), anchor=tk.N)

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=(18, 8))
        self.start_button = ttk.Button(controls, text="启动服务", command=self._start_server)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="停止服务", command=self._stop_server, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="打开网页版", command=self._open_web_page).pack(side=tk.LEFT, padx=(8, 0))

        status = ttk.Label(root, textvariable=self.status_var, foreground="#0f6b5f")
        status.pack(anchor=tk.W, pady=(8, 0))

        note = ttk.Label(
            root,
            text="使用前先把电脑光标放到目标输入框。若要向管理员窗口输入，请用管理员权限运行本客户端。",
            foreground="#666666",
            wraplength=560,
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
        self.after(200, self._poll_events)

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()


def main() -> None:
    app = DesktopClient()
    app.mainloop()


if __name__ == "__main__":
    main()
