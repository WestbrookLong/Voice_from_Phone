import asyncio
import queue
import secrets
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from aiohttp import web
from PIL import ImageTk
import qrcode

from server import create_app, get_lan_ip


class WhiteboardServerThread(threading.Thread):
    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        monitor: int,
        lan_ip: str,
        events: queue.Queue[str],
    ) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.token = token
        self.monitor = monitor
        self.lan_ip = lan_ip
        self.events = events
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner: web.AppRunner | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._start())
            self.loop.run_forever()
        except Exception as exc:
            self.events.put(f"error:{exc}")
        finally:
            self.loop.run_until_complete(self._cleanup())
            self.loop.close()

    async def _start(self) -> None:
        app = create_app(token=self.token, monitor_id=self.monitor, lan_ip=self.lan_ip, port=self.port)
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


class WhiteboardClient(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("iPad Whiteboard Bridge for macOS")
        self.geometry("820x560")
        self.minsize(760, 520)

        self.events: queue.Queue[str] = queue.Queue()
        self.server_thread: WhiteboardServerThread | None = None
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))
        self.qr_image: ImageTk.PhotoImage | None = None

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8791")
        self.monitor_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Not started")
        self.browser_url_var = tk.StringVar(value="")
        self.app_url_var = tk.StringVar(value="")

        self._build_ui()
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="iPad Whiteboard Bridge for macOS", font=("Helvetica Neue", 18, "bold")).pack(anchor=tk.W)
        ttk.Label(
            root,
            text="Start one Mac bridge, then choose either browser whiteboard control or the native iPad app.",
            foreground="#555555",
        ).pack(anchor=tk.W, pady=(4, 16))

        form = ttk.Frame(root)
        form.pack(fill=tk.X)
        ttk.Label(form, text="Port").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(form, textvariable=self.port_var, width=12).grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Label(form, text="Monitor").grid(row=0, column=2, sticky=tk.W, padx=(16, 0), pady=4)
        ttk.Entry(form, textvariable=self.monitor_var, width=8).grid(row=0, column=3, sticky=tk.W, pady=4)
        ttk.Label(form, text="Token").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(form, textvariable=self.token_var).grid(row=1, column=1, columnspan=3, sticky=tk.EW, pady=4)
        ttk.Button(form, text="Regenerate", command=self._regenerate_token).grid(row=1, column=4, padx=(8, 0), pady=4)
        form.columnconfigure(1, weight=1)

        self.url_panel = ttk.Frame(root)
        ttk.Label(self.url_panel, text="方式 A: 网页白板（Safari/浏览器直接打开）").pack(anchor=tk.W, pady=(0, 4))
        browser_url_row = ttk.Frame(self.url_panel)
        browser_url_row.pack(fill=tk.X)
        ttk.Entry(browser_url_row, textvariable=self.browser_url_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(browser_url_row, text="Copy", command=lambda: self._copy_value(self.browser_url_var.get())).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(browser_url_row, text="Show QR", command=lambda: self._show_qr(self.browser_url_var.get())).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            self.url_panel,
            text="浏览器方式：iPad 直接打开这个网址即可，本机会把网页白板上的笔迹映射到当前前台 Mac 应用。",
            foreground="#666666",
            wraplength=700,
        ).pack(anchor=tk.W, pady=(6, 0))

        ttk.Label(self.url_panel, text="方式 B: iPad 原生 App（ipad_whiteboard_app）").pack(anchor=tk.W, pady=(14, 4))
        app_url_row = ttk.Frame(self.url_panel)
        app_url_row.pack(fill=tk.X)
        ttk.Entry(app_url_row, textvariable=self.app_url_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(app_url_row, text="Copy", command=lambda: self._copy_value(self.app_url_var.get())).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            self.url_panel,
            text="原生 App 方式：在 iPad App 的 Connect 弹窗里粘贴这个地址。App 可额外使用 PC Shot 和 Stream。",
            foreground="#666666",
            wraplength=700,
        ).pack(anchor=tk.W, pady=(6, 0))

        qr_panel = ttk.Frame(self.url_panel)
        qr_panel.pack(fill=tk.X, pady=(14, 0))
        self.qr_label = ttk.Label(qr_panel)
        self.qr_label.pack(side=tk.LEFT)
        ttk.Label(
            qr_panel,
            text="二维码对应的是网页白板入口。原生 App 不扫码，直接粘贴上面的 App 地址。",
            foreground="#666666",
            wraplength=440,
        ).pack(side=tk.LEFT, padx=(14, 0), anchor=tk.N)

        self.controls = ttk.Frame(root)
        self.controls.pack(fill=tk.X, pady=(18, 8))
        self.start_button = ttk.Button(self.controls, text="Start service", command=self._start_server)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(self.controls, text="Stop service", command=self._stop_server, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(root, textvariable=self.status_var, foreground="#0f6b5f").pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(
            root,
            text="macOS needs Accessibility permission for Terminal, iTerm, Python, or the packaged app. Switch drawing tools in the target Mac app manually; this bridge only maps strokes.",
            foreground="#666666",
            wraplength=680,
        ).pack(anchor=tk.W, pady=(12, 0))

    def _start_server(self) -> None:
        if self.server_thread is not None:
            return
        try:
            port = int(self.port_var.get())
            monitor = int(self.monitor_var.get())
            if port <= 0 or port > 65535 or monitor <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid settings", "Enter a valid port and monitor number.")
            return

        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Invalid token", "Token cannot be empty.")
            return

        self.status_var.set("Starting...")
        self.lan_ip = get_lan_ip()
        self.server_thread = WhiteboardServerThread("0.0.0.0", port, token, monitor, self.lan_ip, self.events)
        self.server_thread.start()

    def _stop_server(self) -> None:
        if self.server_thread is not None:
            self.server_thread.stop()
            self.server_thread = None
        self.status_var.set("Stopped")
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self._hide_urls()

    def _regenerate_token(self) -> None:
        if self.server_thread is not None:
            messagebox.showinfo("Service running", "Stop the service before regenerating the token.")
            return
        self.token_var.set(secrets.token_urlsafe(12))
        self.page_version = str(int(time.time()))
        self._hide_urls()

    def _update_url(self) -> None:
        port = self.port_var.get().strip() or "8791"
        token = self.token_var.get().strip()
        self.browser_url_var.set(f"http://{self.lan_ip}:{port}/?token={token}&v={self.page_version}")
        self.app_url_var.set(f"http://{self.lan_ip}:{port}/?token={token}")
        self._update_qr(self.browser_url_var.get())

    def _show_urls(self) -> None:
        self._update_url()
        self.url_panel.pack(fill=tk.X, pady=(16, 0), before=self.controls)

    def _hide_urls(self) -> None:
        self.url_panel.pack_forget()
        self.browser_url_var.set("")
        self.app_url_var.set("")
        self.qr_label.configure(image="")
        self.qr_image = None

    def _copy_value(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.browser_url_var.get()
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set("URL copied")

    def _show_qr(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.browser_url_var.get()
        self._update_qr(value)

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
                self.status_var.set("Service started")
                self.start_button.configure(state=tk.DISABLED)
                self.stop_button.configure(state=tk.NORMAL)
                self._show_urls()
            elif event.startswith("error:"):
                self.server_thread = None
                self.status_var.set(event)
                self.start_button.configure(state=tk.NORMAL)
                self.stop_button.configure(state=tk.DISABLED)
                self._hide_urls()
        self.after(200, self._poll_events)

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()


def main() -> None:
    app = WhiteboardClient()
    app.mainloop()


if __name__ == "__main__":
    main()
