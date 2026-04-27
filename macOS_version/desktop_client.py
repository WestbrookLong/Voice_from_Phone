import asyncio
import ssl
import subprocess
import sys
import queue
import secrets
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from aiohttp import web
from PIL import ImageTk
import qrcode

from server import DEFAULT_CERT_FILE, DEFAULT_KEY_FILE, build_ssl_context, create_app, get_lan_ip


ROOT = Path(__file__).resolve().parent
SETUP_HTTPS_SCRIPT = ROOT / "scripts" / "setup_https.py"


class BridgeServerThread(threading.Thread):
    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        events: queue.Queue[str],
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.token = token
        self.events = events
        self.ssl_context = ssl_context
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
        site = web.TCPSite(self.runner, self.host, self.port, ssl_context=self.ssl_context)
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

        self.events: queue.Queue[str] = queue.Queue()
        self.server_thread: BridgeServerThread | None = None
        self.lan_ip = get_lan_ip()

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="8787")
        self.status_var = tk.StringVar(value="未启动")
        self.url_var = tk.StringVar(value="")
        self.cert_url_var = tk.StringVar(value="")
        self.qr_image: ImageTk.PhotoImage | None = None

        self._build_ui()
        self._update_url()
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

        ttk.Label(root, text="手机证书安装").pack(anchor=tk.W, pady=(10, 4))
        cert_row = ttk.Frame(root)
        cert_row.pack(fill=tk.X)
        ttk.Entry(cert_row, textvariable=self.cert_url_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(cert_row, text="复制证书地址", command=self._copy_cert_url).pack(side=tk.LEFT, padx=(8, 0))

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
        ttk.Button(controls, text="生成/更新 HTTPS 证书", command=self._generate_https_cert).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="打开网页版", command=self._open_web_page).pack(side=tk.LEFT, padx=(8, 0))

        status = ttk.Label(root, textvariable=self.status_var, foreground="#0f6b5f")
        status.pack(anchor=tk.W, pady=(8, 0))

        note = ttk.Label(
            root,
            text="使用前先把 Mac 光标放到目标输入框。若输入无效，请在“系统设置 -> 隐私与安全性”中给 Terminal 或 Python 开启“辅助功能”和“输入监控”。",
            foreground="#666666",
            wraplength=590,
        )
        note.pack(anchor=tk.W, pady=(16, 0))

    def _https_available(self) -> bool:
        return DEFAULT_CERT_FILE.exists() and DEFAULT_KEY_FILE.exists()

    def _scheme(self) -> str:
        return "https" if self._https_available() else "http"

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

        ssl_context = None
        if self._https_available():
            try:
                ssl_context = build_ssl_context(DEFAULT_CERT_FILE, DEFAULT_KEY_FILE)
            except Exception as exc:
                messagebox.showerror("HTTPS 证书错误", str(exc))
                return
        else:
            messagebox.showinfo("HTTPS 未启用", "未找到本地证书，将以 HTTP 启动。语音输入需要先生成 HTTPS 证书。")

        self.status_var.set("启动中...")
        self.server_thread = BridgeServerThread("0.0.0.0", port, token, self.events, ssl_context=ssl_context)
        self.server_thread.start()
        self._update_url()

    def _stop_server(self) -> None:
        if self.server_thread is not None:
            self.server_thread.stop()
            self.server_thread = None
        self.status_var.set("已停止")
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)

    def _generate_https_cert(self) -> None:
        try:
            subprocess.run([sys.executable, str(SETUP_HTTPS_SCRIPT)], cwd=ROOT, check=True)
        except subprocess.CalledProcessError as exc:
            messagebox.showerror("证书生成失败", f"setup_https.py 退出码：{exc.returncode}")
            return
        except FileNotFoundError:
            messagebox.showerror("证书生成失败", "找不到 Python 或 setup_https.py。")
            return
        self.lan_ip = get_lan_ip()
        self._update_url()
        messagebox.showinfo("证书已生成", "HTTPS 证书已生成/更新。请重启服务后使用 HTTPS 地址。")

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

    def _copy_cert_url(self) -> None:
        self._update_url()
        url = self.cert_url_var.get()
        self.clipboard_clear()
        self.clipboard_append(url)
        self.status_var.set("证书地址已复制")

    def _open_web_page(self) -> None:
        import webbrowser

        self._update_url()
        webbrowser.open(self.url_var.get())

    def _update_url(self) -> None:
        port = self.port_var.get().strip() or "8787"
        token = self.token_var.get().strip()
        scheme = self._scheme()
        url = f"{scheme}://{self.lan_ip}:{port}/?token={token}"
        self.url_var.set(url)
        self.cert_url_var.set(f"{scheme}://{self.lan_ip}:{port}/cert/help")
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
