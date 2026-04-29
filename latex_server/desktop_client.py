import asyncio
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import aiohttp
from aiohttp import web
from PIL import ImageTk
import qrcode


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
LOCAL_PROJECTS_DIR = ROOT / "local_projects"
LOCAL_PROJECTS_DIR.mkdir(exist_ok=True)


MIKTEX_CANDIDATES = [
    Path(r"C:\Program Files\MiKTeX\miktex\bin\x64"),
    Path(r"C:\Program Files\MiKTeX 2.9\miktex\bin\x64"),
    Path(r"C:\Program Files (x86)\MiKTeX 2.9\miktex\bin"),
    Path(r"C:\ProgramData\MiKTeX\miktex\bin\x64"),
    Path.home() / r"AppData\Local\Programs\MiKTeX\miktex\bin\x64",
    Path.home() / r"AppData\Local\MiKTeX\miktex\bin\x64",
]


def find_miktex_bin() -> Path | None:
    """Search common MiKTeX installation directories."""
    for p in MIKTEX_CANDIDATES:
        if (p / "latexmk.exe").exists() or (p / "pdflatex.exe").exists():
            return p
    # Also try Windows registry hint
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MiKTeX.org\MiKTeX") as key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        install_root, _ = winreg.QueryValueEx(subkey, "Install Root")
                        candidate = Path(install_root) / "miktex" / "bin" / "x64"
                        if (candidate / "latexmk.exe").exists() or (candidate / "pdflatex.exe").exists():
                            return candidate
                except OSError:
                    break
                i += 1
    except Exception:
        pass
    return None


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "Access-Control-Allow-Origin": "*",
    }


def parse_latex_log(log_path: Path) -> list[dict[str, Any]]:
    """Simple LaTeX log parser extracting errors and warnings with line numbers."""
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    errors: list[dict[str, Any]] = []
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        # Error lines start with !
        if line.startswith("!"):
            msg = line[1:].strip()
            line_no = 0
            # Look ahead for l.XXX line number indicator
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.match(r"l\.(\d+)(\s|$)", lines[j])
                if m:
                    line_no = int(m.group(1))
                    break
            errors.append({"line": line_no, "message": msg, "severity": "error"})
            i += 1
            continue

        # Warnings
        m = re.match(r"LaTeX Warning:\s*(.+)", line)
        if m:
            msg = m.group(1)
            line_no = 0
            # Try to extract line number from warning
            m2 = re.search(r"on input line (\d+)", msg)
            if m2:
                line_no = int(m2.group(1))
            errors.append({"line": line_no, "message": msg, "severity": "warning"})
            i += 1
            continue

        # Package warnings
        m = re.match(r"Package \w+ Warning:\s*(.+)", line)
        if m:
            msg = m.group(1)
            line_no = 0
            m2 = re.search(r"on input line (\d+)", msg)
            if m2:
                line_no = int(m2.group(1))
            errors.append({"line": line_no, "message": msg, "severity": "warning"})
            i += 1
            continue

        i += 1

    return errors


class LocalBridge:
    def __init__(
        self,
        project_id: str,
        project_dir: Path,
        cloud_base_url: str,
        miktex_bin: Path | None = None,
    ) -> None:
        self.project_id = project_id
        self.project_dir = project_dir
        self.cloud_base_url = cloud_base_url.rstrip("/")
        self.figures_dir = project_dir / "figures"
        self.figures_dir.mkdir(exist_ok=True)
        self.last_text: str | None = None
        self.last_compile_time = 0.0
        self.session: aiohttp.ClientSession | None = None
        self.miktex_bin = miktex_bin

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def sync_from_cloud(self) -> bool:
        """Poll cloud text and write to local main.tex if changed."""
        try:
            session = await self._get_session()
            url = f"{self.cloud_base_url}/api/projects/{self.project_id}/text"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                text = data.get("text", "")
        except Exception as exc:
            print(f"[sync] poll error: {exc}", flush=True)
            return False

        if text == self.last_text:
            return False

        self.last_text = text
        tex_path = self.project_dir / "main.tex"
        tex_path.write_text(text, encoding="utf-8")
        print(f"[sync] wrote main.tex ({len(text)} chars)", flush=True)
        return True

    async def download_images(self) -> None:
        """Download all images from cloud to local figures/ dir."""
        try:
            session = await self._get_session()
            url = f"{self.cloud_base_url}/api/projects/{self.project_id}/images"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                files = data.get("files", [])
        except Exception as exc:
            print(f"[images] list error: {exc}", flush=True)
            return

        for fmeta in files:
            filename = fmeta["filename"]
            file_url = fmeta["url"]
            if file_url.startswith("/"):
                file_url = self.cloud_base_url + file_url
            local_path = self.figures_dir / filename
            try:
                async with session.get(file_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        local_path.write_bytes(data)
                        print(f"[images] downloaded {filename}", flush=True)
            except Exception as exc:
                print(f"[images] download error for {filename}: {exc}", flush=True)

    def _resolve_exe(self, name: str) -> str | None:
        """Find executable, preferring custom miktex bin path."""
        if self.miktex_bin and self.miktex_bin.exists():
            candidate = self.miktex_bin / (name + ".exe")
            if candidate.exists():
                return str(candidate)
        return shutil.which(name)

    async def compile(self) -> dict[str, Any]:
        """Run latexmk and return PDF + errors."""
        await self.sync_from_cloud()
        await self.download_images()

        tex_path = self.project_dir / "main.tex"
        if not tex_path.exists():
            return {"ok": False, "errors": [{"line": 0, "message": "main.tex not found", "severity": "error"}]}

        latexmk = self._resolve_exe("latexmk")
        if latexmk is None:
            pdflatex = self._resolve_exe("pdflatex")
            if pdflatex is None:
                hint = ""
                if self.miktex_bin:
                    hint = f" (checked {self.miktex_bin})"
                return {"ok": False, "errors": [{"line": 0, "message": f"latexmk/pdflatex not found.{hint} 请检查 MiKTeX 安装路径或系统 PATH。", "severity": "error"}]}
            cmd = [pdflatex, "-interaction=nonstopmode", "-file-line-error", "main.tex"]
        else:
            cmd = [latexmk, "-pdf", "-interaction=nonstopmode", "-file-line-error", "-synctex=1", "main.tex"]

        log_path = self.project_dir / "main.log"
        pdf_path = self.project_dir / "main.pdf"

        # Clean old log to avoid stale errors
        if log_path.exists():
            log_path.unlink()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            print(f"[compile] latexmk exited with {proc.returncode}", flush=True)
        except asyncio.TimeoutError:
            return {"ok": False, "errors": [{"line": 0, "message": "Compilation timed out after 120s", "severity": "error"}]}
        except Exception as exc:
            return {"ok": False, "errors": [{"line": 0, "message": f"Compilation failed: {exc}", "severity": "error"}]}

        errors = parse_latex_log(log_path)
        ok = pdf_path.exists() and pdf_path.stat().st_size > 0
        if not ok and not errors:
            errors.append({"line": 0, "message": "PDF was not generated. Check log.", "severity": "error"})

        return {"ok": ok, "errors": errors}

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()


class BridgeServerThread(threading.Thread):
    def __init__(self, host: str, port: int, app: web.Application, events: queue.Queue[object]) -> None:
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.events = events
        self.loop: asyncio.AbstractEventLoop | None = None
        self.runner: web.AppRunner | None = None
        self.app = app

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
        self.runner = web.AppRunner(self.app, access_log=None)
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
        self.title("LaTeX Local Bridge")
        self.geometry("980x720")
        self.minsize(900, 620)
        self.configure(bg="#1e1f22")

        self.events: queue.Queue[object] = queue.Queue()
        self.server_thread: BridgeServerThread | None = None
        self.sync_task: asyncio.Task | None = None
        self.lan_ip = get_lan_ip()
        self.page_version = str(int(time.time()))

        self.token_var = tk.StringVar(value=secrets.token_urlsafe(12))
        self.port_var = tk.StringVar(value="9801")
        self.cloud_url_var = tk.StringVar(value="http://127.0.0.1:9800")
        self.project_id_var = tk.StringVar(value="demo-project")
        self.project_dir_var = tk.StringVar(value=str(LOCAL_PROJECTS_DIR / "demo-project"))
        self.status_var = tk.StringVar(value="Stopped")
        self.url_var = tk.StringVar(value="")
        self.qr_image: ImageTk.PhotoImage | None = None
        self.bridge: LocalBridge | None = None

        # Detect MiKTeX
        detected = find_miktex_bin()
        self.miktex_bin_var = tk.StringVar(value=str(detected) if detected else "")
        self.miktex_status_var = tk.StringVar()
        self._update_miktex_status()

        self._build_ui()
        self.after(0, self._apply_window_chrome)
        self.after(250, self._apply_window_chrome)
        self.after(200, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_window_chrome(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.c_void_p(self.winfo_id())
            dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            def colorref(hex_color: str) -> int:
                value = hex_color.lstrip("#")
                return int(value[0:2], 16) | (int(value[2:4], 16) << 8) | (int(value[4:6], 16) << 16)
            def set_dwm_attribute(attribute: int, value: int) -> None:
                data = ctypes.c_int(value)
                dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
            set_dwm_attribute(20, 1)
            set_dwm_attribute(19, 1)
            set_dwm_attribute(34, colorref("#1e1f22"))
            set_dwm_attribute(35, colorref("#1e1f22"))
            set_dwm_attribute(36, colorref("#d7d9de"))
        except Exception:
            return

    def _build_ui(self) -> None:
        self._configure_style()

        root = ttk.Frame(self, padding=22, style="App.TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill=tk.X)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="LATEX BRIDGE", style="Eyebrow.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="本地编译桥接", style="Hero.TLabel").grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
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

        ttk.Label(settings, text="本机地址", style="Meta.TLabel").grid(row=0, column=3, sticky=tk.W, padx=(18, 0))
        ttk.Label(settings, text=self.lan_ip, style="Ip.TLabel").grid(row=1, column=3, sticky=tk.W, padx=(18, 0), pady=(6, 0))

        row2 = ttk.Frame(settings, style="Card.TFrame")
        row2.grid(row=2, column=0, columnspan=4, sticky=tk.EW, pady=(14, 0))
        row2.columnconfigure(1, weight=1)
        row2.columnconfigure(3, weight=1)

        ttk.Label(row2, text="云端地址", style="Meta.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(row2, textvariable=self.cloud_url_var, style="Input.TEntry").grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))

        ttk.Label(row2, text="项目 ID", style="Meta.TLabel").grid(row=0, column=2, sticky=tk.W, padx=(18, 0))
        ttk.Entry(row2, textvariable=self.project_id_var, width=20, style="Input.TEntry").grid(row=1, column=2, sticky=tk.W, padx=(18, 0), pady=(6, 0))

        ttk.Label(row2, text="本地目录", style="Meta.TLabel").grid(row=0, column=3, sticky=tk.W, padx=(18, 0))
        ttk.Entry(row2, textvariable=self.project_dir_var, style="Input.TEntry").grid(row=1, column=3, sticky=tk.EW, padx=(18, 0), pady=(6, 0))

        row3 = ttk.Frame(settings, style="Card.TFrame")
        row3.grid(row=3, column=0, columnspan=4, sticky=tk.EW, pady=(10, 0))
        ttk.Label(row3, text="MiKTeX 路径 (可选)", style="Meta.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(row3, textvariable=self.miktex_bin_var, style="Input.TEntry").grid(row=1, column=0, sticky=tk.EW, pady=(6, 0))
        ttk.Label(row3, textvariable=self.miktex_status_var, style="FineCard.TLabel").grid(row=1, column=1, sticky=tk.W, padx=(10, 0), pady=(6, 0))
        row3.columnconfigure(0, weight=1)

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
            title="LaTeX 编辑器",
            badge="EDITOR",
            description="在浏览器中打开编辑器，连接云端协同服务并在本地编译预览。",
            variable=self.url_var,
            qr_title="编辑器二维码",
            qr_hint="扫码打开 LaTeX 编辑器",
        ).pack(fill=tk.X)

        qr_panel = ttk.Frame(content, padding=18, style="QrCard.TFrame")
        qr_panel.grid(row=0, column=1, sticky=tk.NS)
        ttk.Label(qr_panel, text="二维码", style="CardTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(qr_panel, text="扫码在浏览器中打开编辑器", style="CardDesc.TLabel", wraplength=220).pack(anchor=tk.W, pady=(4, 14))
        self.qr_label = ttk.Label(qr_panel, style="Qr.TLabel")
        self.qr_label.pack(anchor=tk.CENTER, pady=(0, 12))
        ttk.Label(qr_panel, text="二维码只在当前 Token 和端口下有效", style="FineCard.TLabel", wraplength=220).pack(anchor=tk.W)

        controls = ttk.Frame(root, style="App.TFrame")
        controls.pack(fill=tk.X, pady=(18, 0))
        self.start_button = ttk.Button(controls, text="启动服务", command=self._start_server, style="Primary.TButton")
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(controls, text="停止服务", command=self._stop_server, state=tk.DISABLED, style="Danger.TButton")
        self.stop_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="打开编辑器", command=self._open_web_page, style="Ghost.TButton").pack(side=tk.LEFT, padx=(10, 0))

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
        style.configure("Input.TEntry", fieldbackground="#25272b", background="#25272b", foreground=text, bordercolor=border, lightcolor=border, darkcolor=border, padding=8)
        style.map("Input.TEntry", fieldbackground=[("readonly", "#25272b"), ("focus", "#282b30")], foreground=[("readonly", text)])
        style.configure("Primary.TButton", background=accent, foreground="#172016", font=(zh_font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", accent_hover), ("disabled", "#59635a")])
        style.configure("Ghost.TButton", background=panel_soft, foreground=text, font=(zh_font, 9, "bold"), padding=(12, 8), borderwidth=1)
        style.map("Ghost.TButton", background=[("active", "#393c42")], foreground=[("disabled", "#6f757d")])
        style.configure("Danger.TButton", background=danger, foreground="#f5eeee", font=(zh_font, 10, "bold"), padding=(16, 10), borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#c2766b"), ("disabled", "#5f5555")])

    def _build_link_card(self, parent: ttk.Frame, *, title: str, badge: str, description: str, variable: tk.StringVar, qr_title: str, qr_hint: str) -> ttk.Frame:
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
        ttk.Button(row, text="二维码", command=lambda: self._show_qr(variable.get(), qr_title, qr_hint), style="Ghost.TButton").pack(side=tk.LEFT, padx=(8, 0))
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

        project_id = self.project_id_var.get().strip() or "demo-project"
        project_dir = Path(self.project_dir_var.get().strip() or str(LOCAL_PROJECTS_DIR / project_id))
        project_dir.mkdir(parents=True, exist_ok=True)
        cloud_url = self.cloud_url_var.get().strip() or "http://127.0.0.1:9800"

        self.status_var.set("启动中...")
        app = self._create_app(token, project_id, project_dir, cloud_url)
        self.server_thread = BridgeServerThread("0.0.0.0", port, app, self.events)
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

    def _copy_value(self, value: str) -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set("地址已复制")

    def _show_qr(self, value: str, title: str = "二维码", hint: str = "扫码打开") -> None:
        if not value:
            self._update_url()
            value = self.url_var.get()
        # No title/hint labels in this simplified version, just update QR
        self._update_qr(value)

    def _open_web_page(self) -> None:
        import webbrowser
        self._update_url()
        webbrowser.open(self.url_var.get())

    def _update_url(self) -> None:
        port = self.port_var.get().strip() or "9801"
        token = self.token_var.get().strip()
        self.url_var.set(f"http://{self.lan_ip}:{port}/?token={token}&v={self.page_version}")
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
                self.status_var.set("运行中")
                self.start_button.configure(state=tk.DISABLED)
                self.stop_button.configure(state=tk.NORMAL)
        self.after(200, self._poll_events)

    def _on_close(self) -> None:
        self._stop_server()
        self.destroy()

    def _update_miktex_status(self) -> None:
        path_str = self.miktex_bin_var.get().strip()
        if not path_str:
            # Try auto-detect again
            detected = find_miktex_bin()
            if detected:
                self.miktex_bin_var.set(str(detected))
                path_str = str(detected)
            else:
                self.miktex_status_var.set("未检测到 MiKTeX，请手动填写 bin 目录路径或配置系统 PATH")
                return
        p = Path(path_str)
        if (p / "latexmk.exe").exists() or (p / "pdflatex.exe").exists():
            self.miktex_status_var.set("✓ MiKTeX 已识别")
        else:
            self.miktex_status_var.set("× 该路径下未找到 latexmk.exe / pdflatex.exe")

    def _create_app(self, token: str, project_id: str, project_dir: Path, cloud_url: str) -> web.Application:
        miktex_str = self.miktex_bin_var.get().strip()
        miktex_bin = Path(miktex_str) if miktex_str else None
        bridge = LocalBridge(project_id=project_id, project_dir=project_dir, cloud_base_url=cloud_url, miktex_bin=miktex_bin)
        self.bridge = bridge

        async def index(request: web.Request) -> web.StreamResponse:
            if request.query.get("token") != token:
                return web.Response(text="Invalid token", status=401)
            return web.FileResponse(STATIC_DIR / "index.html", headers=no_cache_headers())

        async def health(_: web.Request) -> web.Response:
            return web.json_response({"ok": True})

        async def api_compile(request: web.Request) -> web.Response:
            result = await bridge.compile()
            return web.json_response(result, headers={"Access-Control-Allow-Origin": "*"})

        async def api_pdf(request: web.Request) -> web.Response:
            pdf_path = project_dir / "main.pdf"
            if not pdf_path.exists():
                return web.json_response({"error": "PDF not found"}, status=404, headers={"Access-Control-Allow-Origin": "*"})
            return web.FileResponse(pdf_path, headers={**no_cache_headers(), "Access-Control-Allow-Origin": "*", "Content-Type": "application/pdf"})

        async def api_upload_image(request: web.Request) -> web.Response:
            # Forward to cloud or save locally then upload to cloud
            reader = await request.multipart()
            files: list[dict[str, str]] = []
            async for field in reader:
                if field.name != "image":
                    continue
                filename = field.filename
                if not filename:
                    continue
                filename = Path(filename).name
                # Save to local figures dir
                local_path = bridge.figures_dir / filename
                with open(local_path, "wb") as f:
                    while True:
                        chunk = await field.read_chunk(size=8192)
                        if not chunk:
                            break
                        f.write(chunk)
                # Upload to cloud
                try:
                    session = await bridge._get_session()
                    cloud_upload_url = f"{bridge.cloud_base_url}/api/projects/{bridge.project_id}/images"
                    file_bytes = local_path.read_bytes()
                    data = aiohttp.FormData()
                    data.add_field("image", file_bytes, filename=filename, content_type="application/octet-stream")
                    async with session.post(cloud_upload_url, data=data) as resp:
                        if resp.status == 200:
                            cloud_data = await resp.json()
                            files.extend(cloud_data.get("files", []))
                        else:
                            files.append({"filename": filename, "url": f"/api/projects/{bridge.project_id}/images/{filename}"})
                except Exception as exc:
                    print(f"[upload] cloud upload error: {exc}", flush=True)
                    files.append({"filename": filename, "url": f"/api/projects/{bridge.project_id}/images/{filename}"})
            return web.json_response({"project_id": bridge.project_id, "files": files}, headers={"Access-Control-Allow-Origin": "*"})

        # Background sync loop runs in the bridge server thread event loop
        async def sync_loop() -> None:
            while True:
                try:
                    await bridge.sync_from_cloud()
                except Exception as exc:
                    print(f"[sync_loop] error: {exc}", flush=True)
                await asyncio.sleep(3)

        app = web.Application(client_max_size=64 * 1024 * 1024)
        app.router.add_get("/", index)
        app.router.add_get("/health", health)
        app.router.add_post("/api/compile", api_compile)
        app.router.add_get("/api/pdf", api_pdf)
        app.router.add_post("/api/upload_image", api_upload_image)
        app.router.add_static("/static", STATIC_DIR)

        # Start background sync after app starts
        async def on_startup(_: web.Application) -> None:
            asyncio.create_task(sync_loop())

        app.on_startup.append(on_startup)
        return app


def main() -> None:
    app = DesktopClient()
    app.mainloop()


if __name__ == "__main__":
    main()
