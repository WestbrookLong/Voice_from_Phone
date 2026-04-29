import asyncio
import ctypes
import queue
import secrets
import sys
import threading
import time
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
        self.title("Flow Bridge")
        self.geometry("920x680")
        self.minsize(820, 620)
        self.configure(bg="#1e1f22")

        self.events: queue.Queue[str] = queue.Queue()
        self.server_thread: BridgeServerThread | None = None
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8787")
        self.status_var = tk.StringVar(value="未启动")
        self.url_var = tk.StringVar(value="")
        self.tablet_url_var = tk.StringVar(value="")
        self.qr_title_var = tk.StringVar(value="语音输入二维码")
        self.qr_hint_var = tk.StringVar(value="扫码打开手机语音输入页")
        self.qr_image: ImageTk.PhotoImage | None = None

        self._build_ui()
        self.after(0, self._apply_window_chrome)
        self.after(250, self._apply_window_chrome)
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_window_chrome(self) -> None:
        if sys.platform != "win32":
            return

        try:
            hwnd = ctypes.c_void_p(self.winfo_id())
            dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

            def colorref(hex_color: str) -> int:
                value = hex_color.lstrip("#")
                red = int(value[0:2], 16)
                green = int(value[2:4], 16)
                blue = int(value[4:6], 16)
                return red | (green << 8) | (blue << 16)

            def set_dwm_attribute(attribute: int, value: int) -> None:
                data = ctypes.c_int(value)
                dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))

            # Windows 10/11 dark title bar. Attribute 20 is current; 19 is kept as fallback.
            set_dwm_attribute(20, 1)
            set_dwm_attribute(19, 1)
            set_dwm_attribute(34, colorref("#1e1f22"))  # border
            set_dwm_attribute(35, colorref("#1e1f22"))  # caption/title bar
            set_dwm_attribute(36, colorref("#d7d9de"))  # title text
        except Exception:
            # Older Windows builds may not support these DWM attributes.
            return

    def _build_ui(self) -> None:
        self._configure_style()

        root = ttk.Frame(self, padding=22, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="FLOW BRIDGE", style="Eyebrow.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="电脑连接控制台", style="Hero.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, rowspan=2, sticky=tk.NE)

        settings = ttk.Frame(root, padding=18, style="Card.TFrame")
        settings.pack(fill=tk.X, pady=(18, 14))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="端口", style="Meta.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.port_var, width=12, style="Input.TEntry").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))

        ttk.Label(settings, text="会话 Token", style="Meta.TLabel").grid(row=0, column=1, sticky=tk.W, padx=(18, 0))
        ttk.Entry(settings, textvariable=self.token_var, style="Input.TEntry").grid(row=1, column=1, sticky=tk.EW, padx=(18, 0), pady=(6, 0))
        ttk.Button(settings, text="重新生成", command=self._regenerate_token, style="Ghost.TButton").grid(
            row=1, column=2, sticky=tk.E, padx=(12, 0), pady=(6, 0)
        )

        ttk.Label(settings, text="本机局域网地址", style="Meta.TLabel").grid(row=0, column=3, sticky=tk.W, padx=(18, 0))
        ttk.Label(settings, text=self.lan_ip, style="Ip.TLabel").grid(row=1, column=3, sticky=tk.W, padx=(18, 0), pady=(6, 0))

        content = ttk.Frame(root, style="App.TFrame")
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=0)
        content.rowconfigure(0, weight=1)

        links = ttk.Frame(content, style="App.TFrame")
        links.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 14))
        links.columnconfigure(0, weight=1)

        self._build_link_card(
            links,
            title="语音输入",
            badge="VOICE",
            description="移动端输入内容实时写入电脑当前文字光标。",
            variable=self.url_var,
            qr_title="语音输入二维码",
            qr_hint="扫码打开手机语音输入页",
        ).pack(fill=tk.X, pady=(0, 14))

        self._build_link_card(
            links,
            title="移动端远程",
            badge="REMOTE",
            description="在手机或平板上查看电脑屏幕，并映射触控、滚轮和键盘输入。",
            variable=self.tablet_url_var,
            qr_title="移动端远程二维码",
            qr_hint="扫码打开移动端远程控制页",
        ).pack(fill=tk.X)

        qr_panel = ttk.Frame(content, padding=18, style="QrCard.TFrame")
        qr_panel.grid(row=0, column=1, sticky=tk.NS)
        ttk.Label(qr_panel, textvariable=self.qr_title_var, style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            qr_panel,
            textvariable=self.qr_hint_var,
            style="CardDesc.TLabel",
            wraplength=220,
        ).pack(anchor=tk.W, pady=(4, 14))
        self.qr_label = ttk.Label(qr_panel, style="Qr.TLabel")
        self.qr_label.pack(anchor=tk.CENTER, pady=(0, 12))
        ttk.Label(qr_panel, text="二维码只在当前 Token 和端口下有效", style="FineCard.TLabel", wraplength=220).pack(anchor=tk.W)

        controls = ttk.Frame(root, style="App.TFrame")
        controls.pack(fill=tk.X, pady=(18, 0))
        controls.columnconfigure(3, weight=1)
        self.start_button = ttk.Button(controls, text="启动服务", command=self._start_server, style="Primary.TButton")
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="停止服务", command=self._stop_server, state=tk.DISABLED, style="Danger.TButton")
        self.stop_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="打开语音输入页", command=self._open_web_page, style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(
            controls,
            text="管理员权限窗口需要用管理员权限运行本客户端。",
            style="Fine.TLabel",
        ).pack(side=tk.RIGHT)

        self._update_url()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        app_bg = "#1e1f22"
        panel = "#2b2d30"
        panel_soft = "#303236"
        border = "#3d4147"
        text = "#d7d9de"
        muted = "#9aa0a6"
        accent = "#89a889"
        accent_hover = "#9ab79a"
        accent_dark = "#233126"
        danger = "#b66a60"

        style.configure("App.TFrame", background=app_bg)
        style.configure("Card.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("QrCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("LinkCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        zh_font = "华文中宋"

        style.configure("Hero.TLabel", background=app_bg, foreground=text, font=(zh_font, 24, "bold"))
        style.configure("Eyebrow.TLabel", background=app_bg, foreground=accent, font=("Cascadia Mono", 10, "bold"))
        style.configure("Status.TLabel", background=accent_dark, foreground="#b7cdb7", font=(zh_font, 10, "bold"), padding=(14, 8))
        style.configure("Meta.TLabel", background=panel, foreground=muted, font=(zh_font, 8, "bold"))
        style.configure("Ip.TLabel", background=panel, foreground=text, font=("Cascadia Mono", 12, "bold"))
        style.configure("CardTitle.TLabel", background=panel, foreground=text, font=(zh_font, 14, "bold"))
        style.configure("CardDesc.TLabel", background=panel, foreground=muted, font=(zh_font, 9))
        style.configure("Fine.TLabel", background=app_bg, foreground="#7f858d", font=(zh_font, 8))
        style.configure("FineCard.TLabel", background=panel, foreground="#7f858d", font=(zh_font, 8))
        style.configure("Badge.TLabel", background=panel_soft, foreground="#b7cdb7", font=("Cascadia Mono", 9, "bold"), padding=(8, 4))
        style.configure("Qr.TLabel", background=panel)
        style.configure(
            "Input.TEntry",
            fieldbackground="#25272b",
            background="#25272b",
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            padding=8,
        )
        style.map(
            "Input.TEntry",
            fieldbackground=[("readonly", "#25272b"), ("focus", "#282b30")],
            foreground=[("readonly", text)],
        )
        style.configure("Primary.TButton", background=accent, foreground="#172016", font=(zh_font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", accent_hover), ("disabled", "#59635a")])
        style.configure("Ghost.TButton", background=panel_soft, foreground=text, font=(zh_font, 9, "bold"), padding=(12, 8), borderwidth=1)
        style.map("Ghost.TButton", background=[("active", "#393c42")], foreground=[("disabled", "#6f757d")])
        style.configure("Danger.TButton", background=danger, foreground="#f5eeee", font=(zh_font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#c2766b"), ("disabled", "#5f5555")])

    def _build_link_card(
        self,
        parent: ttk.Frame,
        *,
        title: str,
        badge: str,
        description: str,
        variable: tk.StringVar,
        qr_title: str,
        qr_hint: str,
    ) -> ttk.Frame:
        card = ttk.Frame(parent, padding=18, style="LinkCard.TFrame")
        head = ttk.Frame(card, style="LinkCard.TFrame")
        head.pack(fill=tk.X)
        ttk.Label(head, text=title, style="CardTitle.TLabel").pack(side=tk.LEFT)
        ttk.Label(head, text=badge, style="Badge.TLabel").pack(side=tk.RIGHT)
        ttk.Label(card, text=description, style="CardDesc.TLabel").pack(anchor=tk.W, pady=(6, 12))

        row = ttk.Frame(card, style="LinkCard.TFrame")
        row.pack(fill=tk.X)
        ttk.Entry(row, textvariable=variable, state="readonly", style="Input.TEntry").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="复制", command=lambda: self._copy_value(variable.get()), style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(
            row,
            text="二维码",
            command=lambda: self._show_qr(variable.get(), qr_title, qr_hint),
            style="Ghost.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        return card

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
        self._copy_value(self.url_var.get())

    def _copy_value(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set("地址已复制")

    def _show_qr(self, value: str, title: str = "语音输入二维码", hint: str = "扫码打开手机语音输入页") -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        self.qr_title_var.set(title)
        self.qr_hint_var.set(hint)
        self._update_qr(value)

    def _open_web_page(self) -> None:
        import webbrowser

        self._update_url()
        webbrowser.open(self.url_var.get())

    def _update_url(self) -> None:
        port = self.port_var.get().strip() or "8787"
        token = self.token_var.get().strip()
        self.url_var.set(f"http://{self.lan_ip}:{port}/?token={token}&v={self.page_version}")
        self.tablet_url_var.set(f"http://{self.lan_ip}:{port}/tablet?token={token}&v={self.page_version}")
        self._update_qr(self.url_var.get())

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
