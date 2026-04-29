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
        self.title("Mobile Computer")
        self.geometry("980x820")
        self.minsize(900, 720)
        self.configure(bg="#171b20")

        self.events: queue.Queue[object] = queue.Queue()
        self.server_thread: BridgeServerThread | None = None
        self.tunnel_thread: CloudflaredTunnelThread | None = None
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8788")
        self.status_var = tk.StringVar(value="Stopped")
        self.url_var = tk.StringVar(value="")
        self.tablet_url_var = tk.StringVar(value="")
        self.public_url_var = tk.StringVar(value="")
        self.public_tablet_url_var = tk.StringVar(value="")
        self.tunnel_status_var = tk.StringVar(value="Public: stopped")
        self.qr_title_var = tk.StringVar(value="Phone controller QR")
        self.qr_hint_var = tk.StringVar(value="Scan to open the phone computer controller.")
        self.qr_image: ImageTk.PhotoImage | None = None

        self._build_ui()
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self._configure_style()
        root = ttk.Frame(self, padding=22, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="MOBILE COMPUTER", style="Eyebrow.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="Remote input console", style="Hero.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, rowspan=2, sticky=tk.NE)

        settings = ttk.Frame(root, padding=18, style="Card.TFrame")
        settings.pack(fill=tk.X, pady=(18, 14))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Port", style="Meta.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(settings, textvariable=self.port_var, width=12, style="Input.TEntry").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        ttk.Label(settings, text="Session token", style="Meta.TLabel").grid(row=0, column=1, sticky=tk.W, padx=(18, 0))
        ttk.Entry(settings, textvariable=self.token_var, style="Input.TEntry").grid(row=1, column=1, sticky=tk.EW, padx=(18, 0), pady=(6, 0))
        ttk.Button(settings, text="New", command=self._regenerate_token, style="Ghost.TButton").grid(row=1, column=2, sticky=tk.E, padx=(12, 0), pady=(6, 0))
        ttk.Label(settings, text="LAN address", style="Meta.TLabel").grid(row=0, column=3, sticky=tk.W, padx=(18, 0))
        ttk.Label(settings, text=self.lan_ip, style="Ip.TLabel").grid(row=1, column=3, sticky=tk.W, padx=(18, 0), pady=(6, 0))

        content = ttk.Frame(root, style="App.TFrame")
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        links = ttk.Frame(content, style="App.TFrame")
        links.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 14))
        links.columnconfigure(0, weight=1)

        self._build_link_card(
            links,
            title="Phone computer control",
            badge="PHONE",
            description="Phone keyboard maps to PC keys by default. Toggle IME mode to inject text at the PC cursor.",
            variable=self.url_var,
            qr_title="Phone controller QR",
            qr_hint="Scan to open the phone computer controller.",
        ).pack(fill=tk.X, pady=(0, 14))

        self._build_link_card(
            links,
            title="iPad display remote",
            badge="REMOTE",
            description="Tablet display and touch remote, aligned with the FlowBridge screen function.",
            variable=self.tablet_url_var,
            qr_title="iPad remote QR",
            qr_hint="Scan to open the tablet display remote.",
        ).pack(fill=tk.X)

        self._build_link_card(
            links,
            title="Public phone control",
            badge="CLOUD",
            description="Optional Cloudflare Tunnel URL for access outside the local network.",
            variable=self.public_url_var,
            qr_title="Public phone QR",
            qr_hint="Scan when the public tunnel is connected.",
        ).pack(fill=tk.X, pady=(14, 0))

        self._build_link_card(
            links,
            title="Public iPad remote",
            badge="CLOUD",
            description="Public tunnel URL for the iPad screen view.",
            variable=self.public_tablet_url_var,
            qr_title="Public iPad QR",
            qr_hint="Scan when the public tunnel is connected.",
        ).pack(fill=tk.X, pady=(14, 0))

        qr_panel = ttk.Frame(content, padding=18, style="QrCard.TFrame")
        qr_panel.grid(row=0, column=1, sticky=tk.NS)
        ttk.Label(qr_panel, textvariable=self.qr_title_var, style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(qr_panel, textvariable=self.qr_hint_var, style="CardDesc.TLabel", wraplength=220).pack(anchor=tk.W, pady=(4, 14))
        self.qr_label = ttk.Label(qr_panel, style="Qr.TLabel")
        self.qr_label.pack(anchor=tk.CENTER, pady=(0, 12))
        ttk.Label(qr_panel, text="QR codes are valid only for the current token and port.", style="FineCard.TLabel", wraplength=220).pack(anchor=tk.W)

        controls = ttk.Frame(root, style="App.TFrame")
        controls.pack(fill=tk.X, pady=(18, 0))
        self.start_button = ttk.Button(controls, text="Start service", command=self._start_server, style="Primary.TButton")
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="Stop service", command=self._stop_server, state=tk.DISABLED, style="Danger.TButton")
        self.stop_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="Open phone page", command=self._open_web_page, style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))
        self.public_start_button = ttk.Button(controls, text="Start public", command=self._start_tunnel, style="Ghost.TButton")
        self.public_start_button.pack(side=tk.LEFT, padx=(10, 0))
        self.public_stop_button = ttk.Button(controls, text="Stop public", command=self._stop_tunnel, state=tk.DISABLED, style="Danger.TButton")
        self.public_stop_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(controls, textvariable=self.tunnel_status_var, style="Fine.TLabel").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(controls, text="Run as administrator when controlling elevated Windows apps.", style="Fine.TLabel").pack(side=tk.RIGHT)
        self._update_url()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        app_bg = "#171b20"
        panel = "#242a31"
        panel_soft = "#303842"
        border = "#46515d"
        text = "#edf2f7"
        muted = "#98a6b5"
        accent = "#7dd3fc"
        accent_dark = "#123041"
        danger = "#f87171"

        style.configure("App.TFrame", background=app_bg)
        style.configure("Card.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("QrCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("LinkCard.TFrame", background=panel, borderwidth=1, relief=tk.SOLID)
        style.configure("Hero.TLabel", background=app_bg, foreground=text, font=("Segoe UI", 24, "bold"))
        style.configure("Eyebrow.TLabel", background=app_bg, foreground=accent, font=("Cascadia Mono", 10, "bold"))
        style.configure("Status.TLabel", background=accent_dark, foreground="#c7e9f7", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("Meta.TLabel", background=panel, foreground=muted, font=("Segoe UI", 8, "bold"))
        style.configure("Ip.TLabel", background=panel, foreground=text, font=("Cascadia Mono", 12, "bold"))
        style.configure("CardTitle.TLabel", background=panel, foreground=text, font=("Segoe UI", 14, "bold"))
        style.configure("CardDesc.TLabel", background=panel, foreground=muted, font=("Segoe UI", 9))
        style.configure("Fine.TLabel", background=app_bg, foreground="#7f8b98", font=("Segoe UI", 8))
        style.configure("FineCard.TLabel", background=panel, foreground="#7f8b98", font=("Segoe UI", 8))
        style.configure("Badge.TLabel", background=panel_soft, foreground="#d9f4ff", font=("Cascadia Mono", 9, "bold"), padding=(8, 4))
        style.configure("Qr.TLabel", background=panel)
        style.configure("Input.TEntry", fieldbackground="#1b2026", background="#1b2026", foreground=text, bordercolor=border, padding=8)
        style.configure("Primary.TButton", background=accent, foreground="#0c1720", font=("Segoe UI", 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#a5e6ff"), ("disabled", "#53616b")])
        style.configure("Ghost.TButton", background=panel_soft, foreground=text, font=("Segoe UI", 9, "bold"), padding=(12, 8), borderwidth=1)
        style.map("Ghost.TButton", background=[("active", "#3b4652")], foreground=[("disabled", "#6f7b86")])
        style.configure("Danger.TButton", background=danger, foreground="#fff5f5", font=("Segoe UI", 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#fb9999"), ("disabled", "#605454")])

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
        ttk.Button(row, text="Copy", command=lambda: self._copy_value(variable.get()), style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(row, text="QR", command=lambda: self._show_qr(variable.get(), qr_title, qr_hint), style="Ghost.TButton").pack(side=tk.LEFT, padx=(8, 0))
        return card

    def _start_server(self) -> None:
        if self.server_thread is not None:
            return
        try:
            port = int(self.port_var.get())
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Port error", "Enter a port between 1 and 65535.")
            return
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Token error", "Token cannot be empty.")
            return
        self.status_var.set("Starting...")
        self.server_thread = BridgeServerThread("0.0.0.0", port, token, self.events)
        self.server_thread.start()
        self._update_url()

    def _stop_server(self) -> None:
        self._stop_tunnel()
        if self.server_thread is not None:
            self.server_thread.stop()
            self.server_thread = None
        self.status_var.set("Stopped")
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def _current_port(self) -> int | None:
        try:
            port = int(self.port_var.get())
            if port <= 0 or port > 65535:
                raise ValueError
            return port
        except ValueError:
            messagebox.showerror("Port error", "Enter a port between 1 and 65535.")
            return None

    def _start_tunnel(self) -> None:
        if self.tunnel_thread is not None:
            return
        port = self._current_port()
        if port is None:
            return
        token = self.token_var.get().strip()
        if not token:
            messagebox.showerror("Token error", "Token cannot be empty.")
            return
        cloudflared_path = find_cloudflared()
        if cloudflared_path is None:
            messagebox.showerror(
                "cloudflared not found",
                "cloudflared.exe was not found. Expected D:\\download_program\\cloudflared.exe or a PATH installation.",
            )
            return
        if self.server_thread is None:
            self._start_server()
        self.public_url_var.set("")
        self.public_tablet_url_var.set("")
        self.tunnel_status_var.set("Public: starting...")
        self.tunnel_thread = CloudflaredTunnelThread(cloudflared_path, port, self.events)
        self.tunnel_thread.start()
        self.public_start_button.configure(state=tk.DISABLED)
        self.public_stop_button.configure(state=tk.NORMAL)

    def _stop_tunnel(self) -> None:
        if self.tunnel_thread is not None:
            self.tunnel_thread.stop()
            self.tunnel_thread = None
        self.public_url_var.set("")
        self.public_tablet_url_var.set("")
        self.tunnel_status_var.set("Public: stopped")
        if hasattr(self, "public_start_button"):
            self.public_start_button.configure(state=tk.NORMAL)
        if hasattr(self, "public_stop_button"):
            self.public_stop_button.configure(state=tk.DISABLED)

    def _regenerate_token(self) -> None:
        if self.server_thread is not None:
            messagebox.showinfo("Service running", "Stop the service before generating a new token.")
            return
        self.token_var.set(secrets.token_urlsafe(12))
        self._update_url()

    def _copy_value(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set("URL copied")

    def _show_qr(self, value: str, title: str, hint: str) -> None:
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
        port = self.port_var.get().strip() or "8788"
        token = self.token_var.get().strip()
        self.url_var.set(f"http://{self.lan_ip}:{port}/?token={token}&v={self.page_version}")
        self.tablet_url_var.set(f"http://{self.lan_ip}:{port}/tablet?token={token}&v={self.page_version}")
        self._update_qr(self.url_var.get())

    def _update_public_url(self, base_url: str) -> None:
        token = self.token_var.get().strip()
        version = self.page_version
        base = base_url.rstrip("/")
        self.public_url_var.set(f"{base}/?token={token}&v={version}")
        self.public_tablet_url_var.set(f"{base}/tablet?token={token}&v={version}")
        self._show_qr(self.public_url_var.get(), "Public phone QR", "Scan to open through Cloudflare Tunnel.")

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
                self.status_var.set("Running")
                self.start_button.configure(state=tk.DISABLED)
                self.stop_button.configure(state=tk.NORMAL)
            elif isinstance(event, dict):
                event_type = event.get("type")
                if event_type == "tunnel_started":
                    self.tunnel_status_var.set("Public: connecting...")
                elif event_type == "tunnel_url":
                    url = str(event.get("url", ""))
                    self._update_public_url(url)
                    self.tunnel_status_var.set("Public: connected")
                elif event_type == "tunnel_error":
                    self.tunnel_status_var.set("Public: error")
                    messagebox.showerror("Tunnel error", str(event.get("message", "Unknown tunnel error.")))
                    self._stop_tunnel()
                elif event_type == "tunnel_exit":
                    if self.tunnel_thread is not None:
                        self.tunnel_thread = None
                        self.public_start_button.configure(state=tk.NORMAL)
                        self.public_stop_button.configure(state=tk.DISABLED)
                        self.public_url_var.set("")
                        self.public_tablet_url_var.set("")
                        self.tunnel_status_var.set(f"Public: stopped ({event.get('code')})")
        self.after(200, self._poll_events)

    def _on_close(self) -> None:
        self._stop_tunnel()
        self._stop_server()
        self.destroy()


def main() -> None:
    app = DesktopClient()
    app.mainloop()


if __name__ == "__main__":
    main()
