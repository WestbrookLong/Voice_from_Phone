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


class ControllerServerThread(threading.Thread):
    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        lan_ip: str,
        sensitivity: float,
        events: queue.Queue[str],
    ) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.token = token
        self.lan_ip = lan_ip
        self.sensitivity = sensitivity
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
        app = create_app(
            token=self.token,
            lan_ip=self.lan_ip,
            port=self.port,
            sensitivity=self.sensitivity,
        )
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


class ControllerClient(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Mobile FPS Controller")
        self.geometry("920x640")
        self.minsize(820, 560)
        self.configure(bg="#06030c")

        self.events: queue.Queue[str] = queue.Queue()
        self.server_thread: ControllerServerThread | None = None
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))
        self.canvas_window: int | None = None
        self.qr_image: ImageTk.PhotoImage | None = None

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8792")
        self.sensitivity_var = tk.StringVar(value="1.0")
        self.status_var = tk.StringVar(value="Not started")
        self.url_var = tk.StringVar(value="")

        self._build_ui()
        self._update_url()
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self._configure_style()

        self.bg_canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg="#06030c")
        self.bg_canvas.pack(fill=tk.BOTH, expand=True)
        self.bg_canvas.bind("<Configure>", self._on_canvas_resize)

        root = ttk.Frame(self.bg_canvas, padding=22, style="App.TFrame")
        self.canvas_window = self.bg_canvas.create_window(24, 24, anchor=tk.NW, window=root)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="MOBILE FPS", style="Eyebrow.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="Touch Controller Bridge", style="Hero.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, rowspan=2, sticky=tk.NE)

        settings = ttk.Frame(root, padding=18, style="Card.TFrame")
        settings.pack(fill=tk.X, pady=(18, 14))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(4, weight=1)

        ttk.Label(settings, text="PORT", style="Meta.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.port_var, width=12, style="Input.TEntry").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))

        ttk.Label(settings, text="SESSION TOKEN", style="Meta.TLabel").grid(row=0, column=1, sticky=tk.W, padx=(18, 0))
        ttk.Entry(settings, textvariable=self.token_var, style="Input.TEntry").grid(row=1, column=1, sticky=tk.EW, padx=(18, 0), pady=(6, 0))
        ttk.Button(settings, text="Regenerate", command=self._regenerate_token, style="Ghost.TButton").grid(
            row=1, column=2, sticky=tk.E, padx=(12, 0), pady=(6, 0)
        )

        ttk.Label(settings, text="SENSITIVITY", style="Meta.TLabel").grid(row=0, column=3, sticky=tk.W, padx=(18, 0))
        ttk.Entry(settings, textvariable=self.sensitivity_var, width=10, style="Input.TEntry").grid(
            row=1, column=3, sticky=tk.W, padx=(18, 0), pady=(6, 0)
        )

        ttk.Label(settings, text="LAN ADDRESS", style="Meta.TLabel").grid(row=0, column=4, sticky=tk.W, padx=(18, 0))
        ttk.Label(settings, text=self.lan_ip, style="Ip.TLabel").grid(row=1, column=4, sticky=tk.W, padx=(18, 0), pady=(6, 0))

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
            title="Mobile Controller URL",
            badge="PHONE",
            description="Open this exact URL on the phone. The page sends mouse look, WASD joystick, and virtual buttons to this PC.",
            variable=self.url_var,
        ).pack(fill=tk.X)

        info = ttk.Frame(links, padding=18, style="InfoCard.TFrame")
        info.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        ttk.Label(info, text="Input Map", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            info,
            text="Right-side swipe controls relative mouse look. The lower-left joystick maps to WASD. Virtual buttons map to mouse buttons, Space, Shift, Ctrl, R, E, F, Tab, and Esc.",
            style="CardDesc.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(
            info,
            text="Use EDIT on the phone page to move controls and resize each button. Layout data is saved in the phone browser.",
            style="FineCard.TLabel",
            wraplength=500,
        ).pack(anchor=tk.W, pady=(12, 0))

        qr_panel = ttk.Frame(content, padding=18, style="QrCard.TFrame")
        qr_panel.grid(row=0, column=1, sticky=tk.NS)
        ttk.Label(qr_panel, text="Pairing QR", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            qr_panel,
            text="Scan with the phone on the same LAN. Landscape orientation is recommended.",
            style="CardDesc.TLabel",
            wraplength=220,
        ).pack(anchor=tk.W, pady=(4, 14))
        self.qr_label = ttk.Label(qr_panel, style="Qr.TLabel")
        self.qr_label.pack(anchor=tk.CENTER, pady=(0, 12))
        ttk.Label(qr_panel, text="The QR code is valid only for the current token and port.", style="FineCard.TLabel", wraplength=220).pack(anchor=tk.W)

        controls = ttk.Frame(root, style="App.TFrame")
        controls.pack(fill=tk.X, pady=(18, 0))
        self.start_button = ttk.Button(controls, text="Start Service", command=self._start_server, style="Primary.TButton")
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="Stop Service", command=self._stop_server, state=tk.DISABLED, style="Danger.TButton")
        self.stop_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="Open Page", command=self._open_web_page, style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(
            controls,
            text="If port 8792 is busy, change the port before starting.",
            style="Fine.TLabel",
        ).pack(side=tk.RIGHT)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        app_bg = "#0b0712"
        panel = "#151020"
        panel_soft = "#211833"
        border = "#3c2c59"
        text = "#f5efff"
        muted = "#a99abb"
        accent = "#a855f7"
        accent_hover = "#c084fc"
        accent_dark = "#27123e"
        danger = "#be3455"

        style.configure("App.TFrame", background=app_bg)
        style.configure("Card.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("QrCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("LinkCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("InfoCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)

        ui_font = "Microsoft YaHei UI"
        style.configure("Hero.TLabel", background=app_bg, foreground=text, font=(ui_font, 24, "bold"))
        style.configure("Eyebrow.TLabel", background=app_bg, foreground=accent_hover, font=("Cascadia Mono", 10, "bold"))
        style.configure("Status.TLabel", background=accent_dark, foreground="#e9d5ff", font=("Cascadia Mono", 10, "bold"), padding=(14, 8))
        style.configure("Meta.TLabel", background=panel, foreground=muted, font=("Cascadia Mono", 8, "bold"))
        style.configure("Ip.TLabel", background=panel, foreground=text, font=("Cascadia Mono", 12, "bold"))
        style.configure("CardTitle.TLabel", background=panel, foreground=text, font=(ui_font, 14, "bold"))
        style.configure("CardDesc.TLabel", background=panel, foreground=muted, font=(ui_font, 9))
        style.configure("Fine.TLabel", background=app_bg, foreground="#7e708f", font=(ui_font, 8))
        style.configure("FineCard.TLabel", background=panel, foreground="#857593", font=(ui_font, 8))
        style.configure("Badge.TLabel", background=panel_soft, foreground="#e9d5ff", font=("Cascadia Mono", 9, "bold"), padding=(8, 4))
        style.configure("Qr.TLabel", background=panel)
        style.configure(
            "Input.TEntry",
            fieldbackground="#0f0a18",
            background="#0f0a18",
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            insertcolor=text,
            padding=8,
        )
        style.map(
            "Input.TEntry",
            fieldbackground=[("readonly", "#0f0a18"), ("focus", "#171021")],
            foreground=[("readonly", text)],
            bordercolor=[("focus", accent)],
        )
        style.configure("Primary.TButton", background=accent, foreground="#11071c", font=(ui_font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", accent_hover), ("disabled", "#574169")])
        style.configure("Ghost.TButton", background=panel_soft, foreground=text, font=(ui_font, 9, "bold"), padding=(12, 8), borderwidth=1)
        style.map("Ghost.TButton", background=[("active", "#2d2144")], foreground=[("disabled", "#6f617d")])
        style.configure("Danger.TButton", background=danger, foreground="#fff1f5", font=(ui_font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#d64668"), ("disabled", "#60404a")])

    def _build_link_card(
        self,
        parent: ttk.Frame,
        *,
        title: str,
        badge: str,
        description: str,
        variable: tk.StringVar,
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
        ttk.Button(row, text="Copy", command=lambda: self._copy_value(variable.get()), style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(row, text="QR", command=lambda: self._show_qr(variable.get()), style="Ghost.TButton").pack(side=tk.LEFT, padx=(8, 0))
        return card

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self._draw_background(event.width, event.height)
        if self.canvas_window is not None:
            self.bg_canvas.coords(self.canvas_window, 24, 24)
            self.bg_canvas.itemconfigure(self.canvas_window, width=max(1, event.width - 48), height=max(1, event.height - 48))

    def _draw_background(self, width: int, height: int) -> None:
        self.bg_canvas.delete("bg")
        if width <= 0 or height <= 0:
            return
        center = "#0b0712"
        purple = "#3b0f68"
        edge = 34
        self.bg_canvas.create_rectangle(0, 0, width, height, fill=center, outline="", tags="bg")
        for i in range(edge):
            ratio = i / max(1, edge - 1)
            color = self._blend_hex(purple, center, ratio)
            self.bg_canvas.create_rectangle(i, i, width - i, height - i, outline=color, tags="bg")
        self.bg_canvas.tag_lower("bg")

    def _blend_hex(self, left: str, right: str, ratio: float) -> str:
        left_rgb = tuple(int(left[i : i + 2], 16) for i in (1, 3, 5))
        right_rgb = tuple(int(right[i : i + 2], 16) for i in (1, 3, 5))
        mixed = tuple(round(a + (b - a) * ratio) for a, b in zip(left_rgb, right_rgb))
        return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"

    def _start_server(self) -> None:
        if self.server_thread is not None:
            return
        try:
            port = int(self.port_var.get())
            sensitivity = float(self.sensitivity_var.get())
            if port <= 0 or port > 65535 or sensitivity < 1 or sensitivity > 30:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid settings", "Enter a valid port and sensitivity between 1 and 30.")
            return

        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Invalid token", "Token cannot be empty.")
            return

        self.status_var.set("Starting...")
        self.server_thread = ControllerServerThread("0.0.0.0", port, token, self.lan_ip, sensitivity, self.events)
        self.server_thread.start()
        self._update_url()

    def _stop_server(self) -> None:
        if self.server_thread is not None:
            self.server_thread.stop()
            self.server_thread = None
        self.status_var.set("Stopped")
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def _regenerate_token(self) -> None:
        if self.server_thread is not None:
            messagebox.showinfo("Service running", "Stop the service before regenerating the token.")
            return
        self.token_var.set(secrets.token_urlsafe(12))
        self.page_version = str(int(time.time()))
        self._update_url()

    def _update_url(self) -> None:
        port = self.port_var.get().strip() or "8792"
        token = self.token_var.get().strip()
        self.url_var.set(f"http://{self.lan_ip}:{port}/?token={token}&v={self.page_version}")
        self._update_qr(self.url_var.get())

    def _copy_value(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set("URL copied")

    def _show_qr(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        self._update_qr(value)

    def _open_web_page(self) -> None:
        import webbrowser

        self._update_url()
        webbrowser.open(self.url_var.get())

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
            elif event.startswith("error:"):
                self.server_thread = None
                self.status_var.set(event)
                self.start_button.configure(state=tk.NORMAL)
                self.stop_button.configure(state=tk.DISABLED)
        self.after(200, self._poll_events)

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()


def main() -> None:
    app = ControllerClient()
    app.mainloop()


if __name__ == "__main__":
    main()
