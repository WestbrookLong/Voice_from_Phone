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
        self.title("iPad Whiteboard Bridge")
        self.geometry("900x620")
        self.minsize(820, 560)
        self.configure(bg="#0f0f0f")

        self.events: queue.Queue[str] = queue.Queue()
        self.server_thread: WhiteboardServerThread | None = None
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))
        self.qr_image: ImageTk.PhotoImage | None = None

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8791")
        self.monitor_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Not started")
        self.url_var = tk.StringVar(value="")

        self._configure_style()
        self._build_ui()
        self._update_url()
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        bg = "#0f0f0f"
        panel = "#181818"
        panel_soft = "#202020"
        panel_lift = "#25221e"
        border = "#34302a"
        text = "#f3eee8"
        muted = "#a99f93"
        fine = "#746c64"
        orange = "#ff8a00"
        orange_hover = "#ffa12b"
        orange_dark = "#3a2208"
        danger = "#b84224"

        self.colors = {
            "bg": bg,
            "panel": panel,
            "panel_soft": panel_soft,
            "text": text,
            "orange": orange,
            "orange_dark": orange_dark,
        }

        style.configure("App.TFrame", background=bg)
        style.configure("Card.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("Panel.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("QrCard.TFrame", background=panel_lift, borderwidth=1, relief=tk.SOLID)
        style.configure("Toolbar.TFrame", background=bg)

        font = "Microsoft YaHei UI"
        style.configure("Eyebrow.TLabel", background=bg, foreground=orange, font=("Cascadia Mono", 10, "bold"))
        style.configure("Hero.TLabel", background=bg, foreground=text, font=(font, 24, "bold"))
        style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=(font, 10))
        style.configure("CardTitle.TLabel", background=panel, foreground=text, font=(font, 13, "bold"))
        style.configure("QrTitle.TLabel", background=panel_lift, foreground=text, font=(font, 13, "bold"))
        style.configure("Meta.TLabel", background=panel, foreground=muted, font=(font, 8, "bold"))
        style.configure("Desc.TLabel", background=panel, foreground=muted, font=(font, 9))
        style.configure("QrDesc.TLabel", background=panel_lift, foreground=muted, font=(font, 9))
        style.configure("Fine.TLabel", background=bg, foreground=fine, font=(font, 8))
        style.configure("FineCard.TLabel", background=panel_lift, foreground=fine, font=(font, 8))
        style.configure("Status.TLabel", background=orange_dark, foreground=orange, font=(font, 10, "bold"), padding=(14, 8))
        style.configure("Ip.TLabel", background=panel, foreground=text, font=("Cascadia Mono", 12, "bold"))
        style.configure("Qr.TLabel", background=panel_lift)

        style.configure(
            "Input.TEntry",
            fieldbackground="#111111",
            background="#111111",
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            padding=8,
        )
        style.map(
            "Input.TEntry",
            fieldbackground=[("readonly", "#111111"), ("focus", "#171717")],
            foreground=[("readonly", text), ("disabled", "#746c64")],
            bordercolor=[("focus", orange)],
        )

        style.configure("Primary.TButton", background=orange, foreground="#160d02", font=(font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", orange_hover), ("disabled", "#684514")], foreground=[("disabled", "#a58763")])
        style.configure("Ghost.TButton", background=panel_soft, foreground=text, font=(font, 9, "bold"), padding=(12, 8), borderwidth=1)
        style.map("Ghost.TButton", background=[("active", "#2c2a27"), ("disabled", "#1c1c1c")], foreground=[("disabled", "#70685e")])
        style.configure("Danger.TButton", background=danger, foreground="#fff5ef", font=(font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#d04e2a"), ("disabled", "#4a2c23")], foreground=[("disabled", "#8f736b")])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=24, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="WHITEBOARD BRIDGE", style="Eyebrow.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="iPad Whiteboard Control", style="Hero.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, rowspan=2, sticky=tk.NE)
        ttk.Label(
            root,
            text="Scan the QR code on iPad. Local strokes stay smooth, and the PC receives mapped mouse strokes.",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(8, 18))

        form = ttk.Frame(root, padding=18, style="Card.TFrame")
        form.pack(fill=tk.X)
        form.columnconfigure(4, weight=1)
        ttk.Label(form, text="PORT", style="Meta.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(form, textvariable=self.port_var, width=12, style="Input.TEntry").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Label(form, text="MONITOR", style="Meta.TLabel").grid(row=0, column=1, sticky=tk.W, padx=(18, 0))
        ttk.Entry(form, textvariable=self.monitor_var, width=8, style="Input.TEntry").grid(row=1, column=1, sticky=tk.W, padx=(18, 0), pady=(6, 0))
        ttk.Label(form, text="LAN ADDRESS", style="Meta.TLabel").grid(row=0, column=2, sticky=tk.W, padx=(18, 0))
        ttk.Label(form, text=self.lan_ip, style="Ip.TLabel").grid(row=1, column=2, sticky=tk.W, padx=(18, 0), pady=(6, 0))
        ttk.Label(form, text="SESSION TOKEN", style="Meta.TLabel").grid(row=0, column=4, sticky=tk.W, padx=(18, 0))
        ttk.Entry(form, textvariable=self.token_var, style="Input.TEntry").grid(row=1, column=4, sticky=tk.EW, padx=(18, 0), pady=(6, 0))
        ttk.Button(form, text="Regenerate", command=self._regenerate_token, style="Ghost.TButton").grid(row=1, column=5, padx=(10, 0), pady=(6, 0))

        content = ttk.Frame(root, style="App.TFrame")
        content.pack(fill=tk.BOTH, expand=True, pady=(16, 0))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        link_panel = ttk.Frame(content, padding=18, style="Panel.TFrame")
        link_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 16))
        link_panel.columnconfigure(0, weight=1)
        ttk.Label(link_panel, text="iPad whiteboard URL", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            link_panel,
            text="The link includes the current token and page version. Use the latest QR after changing port or token.",
            style="Desc.TLabel",
        ).pack(anchor=tk.W, pady=(5, 14))

        url_row = ttk.Frame(link_panel, style="Card.TFrame")
        url_row.pack(fill=tk.X)
        ttk.Entry(url_row, textvariable=self.url_var, state="readonly", style="Input.TEntry").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(url_row, text="Copy", command=lambda: self._copy_value(self.url_var.get()), style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(url_row, text="Refresh QR", command=lambda: self._show_qr(self.url_var.get()), style="Ghost.TButton").pack(side=tk.LEFT, padx=(8, 0))

        notes = ttk.Frame(link_panel, padding=(0, 22, 0, 0), style="Card.TFrame")
        notes.pack(fill=tk.X)
        ttk.Label(notes, text="Pointer mapping", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            notes,
            text="Pen, line and eraser actions are handled locally on iPad first. Only the final pointer path is sent to this PC client.",
            style="Desc.TLabel",
            wraplength=520,
        ).pack(anchor=tk.W, pady=(5, 0))

        qr_panel = ttk.Frame(content, padding=18, style="QrCard.TFrame")
        qr_panel.grid(row=0, column=1, sticky=tk.NS)
        ttk.Label(qr_panel, text="Scan on iPad", style="QrTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(qr_panel, text="Keep both devices on the same LAN.", style="QrDesc.TLabel", wraplength=220).pack(anchor=tk.W, pady=(5, 14))
        self.qr_label = ttk.Label(qr_panel, style="Qr.TLabel")
        self.qr_label.pack(anchor=tk.CENTER, pady=(0, 12))
        ttk.Label(qr_panel, text="If connection fails, restart service and scan the regenerated code.", style="FineCard.TLabel", wraplength=220).pack(anchor=tk.W)

        controls = ttk.Frame(root, style="Toolbar.TFrame")
        controls.pack(fill=tk.X, pady=(18, 0))
        self.start_button = ttk.Button(controls, text="Start service", command=self._start_server, style="Primary.TButton")
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="Stop service", command=self._stop_server, state=tk.DISABLED, style="Danger.TButton")
        self.stop_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(controls, text="Run as administrator when controlling elevated apps.", style="Fine.TLabel").pack(side=tk.RIGHT)

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
        self.server_thread = WhiteboardServerThread("0.0.0.0", port, token, monitor, self.lan_ip, self.events)
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
        port = self.port_var.get().strip() or "8791"
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

    def _update_qr(self, url: str) -> None:
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color="#101010", back_color="#fff1de").resize((190, 190))
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
    app = WhiteboardClient()
    app.mainloop()


if __name__ == "__main__":
    main()
