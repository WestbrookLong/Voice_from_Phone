from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from chastream.audio import list_input_devices
from chastream.config import APP_ROOT, configure_local_caches


configure_local_caches()

import webview  # noqa: E402

from chastream.manager import ChastreamManager  # noqa: E402


def copy_to_clipboard(text: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Clipboard copy is only implemented for Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    cf_unicode_text = 13
    gmem_moveable = 0x0002
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p
    if not user32.OpenClipboard(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        user32.EmptyClipboard()
        buffer = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buffer)
        handle = kernel32.GlobalAlloc(gmem_moveable, size)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(locked, buffer, size)
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(cf_unicode_text, handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        user32.CloseClipboard()


class DesktopApi:
    def __init__(self) -> None:
        self.manager = ChastreamManager()
        self.window: webview.Window | None = None

    def get_state(self) -> dict:
        return self._result(data={**self.manager.state(), "inputDevices": list_input_devices()})

    def save_settings(self, payload: dict | None = None) -> dict:
        try:
            return self._result("设置已保存", self.manager.update_settings(payload or {}))
        except Exception as exc:
            return self._result(error=str(exc))

    def start_recording(self, payload: dict | None = None) -> dict:
        value = payload or {}
        try:
            device = value.get("device")
            device = int(device) if device not in (None, "") else None
            state = self.manager.start_recording(
                str(value.get("title", "")).strip(),
                str(value.get("speakerMode", "two")),
                list(value.get("selectedSpeakerIds") or []),
                device=device,
                analysis_style=str(value.get("analysisStyle", "chat")),
            )
            return self._result("录音已开始", state)
        except Exception as exc:
            return self._result(error=str(exc))

    def pause_recording(self) -> dict:
        try:
            return self._result("录音已暂停", self.manager.pause_recording())
        except Exception as exc:
            return self._result(error=str(exc))

    def resume_recording(self) -> dict:
        try:
            return self._result("继续录音", self.manager.resume_recording())
        except Exception as exc:
            return self._result(error=str(exc))

    def stop_recording(self) -> dict:
        try:
            return self._result("录音结束，已进入处理队列", self.manager.stop_and_process())
        except Exception as exc:
            return self._result(error=str(exc))

    def import_audio(self, payload: dict | None = None) -> dict:
        if not self.window:
            return self._result(error="Window is not ready.")
        files = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("WAV audio (*.wav)",),
        )
        if not files:
            return self._result("已取消")
        selected = Path(files if isinstance(files, str) else files[0])
        value = payload or {}
        try:
            state = self.manager.process_existing(
                selected,
                str(value.get("title", "")).strip() or selected.stem,
                str(value.get("speakerMode", "two")),
                list(value.get("selectedSpeakerIds") or []),
                analysis_style=str(value.get("analysisStyle", "chat")),
            )
            return self._result("已导入录音并开始处理", state)
        except Exception as exc:
            return self._result(error=str(exc))

    def enroll_profile(self, name: str) -> dict:
        if not self.window:
            return self._result(error="Window is not ready.")
        files = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("WAV audio (*.wav)",),
        )
        if not files:
            return self._result("已取消")
        selected = [Path(files)] if isinstance(files, str) else [Path(item) for item in files]
        try:
            profile = self.manager.enroll_profile(name, selected)
            return self._result(f"已注册声纹：{profile['name']}", self.manager.state())
        except Exception as exc:
            return self._result(error=str(exc))

    def start_voiceprint_sample(self, payload: dict | None = None) -> dict:
        value = payload or {}
        try:
            device = value.get("device")
            device = int(device) if device not in (None, "") else None
            state = self.manager.start_voiceprint_sample(str(value.get("name", "")), device)
            return self._result("声纹样本录制已开始，请自然说话 5～15 秒", state)
        except Exception as exc:
            return self._result(error=str(exc))

    def stop_voiceprint_sample(self) -> dict:
        try:
            state = self.manager.stop_voiceprint_sample()
            count = state["voiceprintDraft"]["sampleCount"]
            return self._result(f"样本已保存，当前共 {count} 段", state)
        except Exception as exc:
            return self._result(error=str(exc), data=self.manager.state())

    def finish_voiceprint_enrollment(self) -> dict:
        try:
            state = self.manager.finish_voiceprint_enrollment()
            return self._result("声纹注册已在后台开始", state)
        except Exception as exc:
            return self._result(error=str(exc), data=self.manager.state())

    def clear_voiceprint_draft(self) -> dict:
        try:
            return self._result("声纹录制草稿已清空", self.manager.clear_voiceprint_draft())
        except Exception as exc:
            return self._result(error=str(exc))

    def delete_profile(self, profile_id: str) -> dict:
        try:
            return self._result("声纹档案已删除", self.manager.delete_profile(profile_id))
        except Exception as exc:
            return self._result(error=str(exc))

    def load_session(self, session_id: str) -> dict:
        try:
            state = self.manager.load_session(session_id)
            title = state["activeSession"]["title"]
            return self._result(f"已打开历史对话：{title}", state)
        except Exception as exc:
            return self._result(error=str(exc))

    def copy_result(self, kind: str) -> dict:
        try:
            copy_to_clipboard(self.manager.copy_markdown(kind))
            return self._result("已复制到剪贴板")
        except Exception as exc:
            return self._result(error=str(exc))

    def open_data_folder(self) -> dict:
        try:
            path = Path(self.manager.state()["dataRoot"])
            os.startfile(path)
            return self._result("已打开数据目录")
        except Exception as exc:
            return self._result(error=str(exc))

    @staticmethod
    def _result(message: str = "", data=None, error: str | None = None) -> dict:
        return {"ok": error is None, "message": message, "error": error, "data": data}


def main() -> None:
    api = DesktopApi()
    index_path = APP_ROOT / "ui" / "index.html"
    if not index_path.exists():
        raise SystemExit(f"UI file not found: {index_path}")
    window = webview.create_window(
        "Chastream",
        index_path.as_uri(),
        js_api=api,
        width=1240,
        height=820,
        min_size=(940, 640),
        background_color="#101412",
    )
    api.window = window
    webview.start(debug=os.environ.get("CHASTREAM_DEBUG") == "1")


if __name__ == "__main__":
    main()
