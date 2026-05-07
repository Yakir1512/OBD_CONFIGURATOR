"""
ecu_master/utils/logger.py
Thread-safe logger — writes to CTkTextbox + stdout.
Levels: INFO | OK | WARN | ERR
"""

import threading
import datetime
import customtkinter as ctk


class Logger:
    LEVELS = {"INFO": "      ", "OK": "[ OK ]", "WARN": "[WARN]", "ERR": "[ERR ]"}

    def __init__(self):
        self._widget: ctk.CTkTextbox | None = None
        self._lock = threading.Lock()
        self._buffer: list[tuple[str, str]] = []   # (line, level) before widget ready

    def attach(self, widget: ctk.CTkTextbox):
        """Call once after the CTkTextbox is created."""
        self._widget = widget
        with self._lock:
            for line, level in self._buffer:
                self._write(line)
            self._buffer.clear()

    def log(self, text: str, level: str = "INFO"):
        prefix = self.LEVELS.get(level, "      ")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {prefix} {text}"
        print(line, flush=True)
        with self._lock:
            if self._widget:
                self._write(line)
            else:
                self._buffer.append((line, level))

    def _write(self, line: str):
        try:
            self._widget.insert("end", line + "\n")
            self._widget.see("end")
        except Exception:
            pass

    # ── Shortcuts ────────────────────────────────────────────────────────────
    def info(self, t: str): self.log(t, "INFO")
    def ok(self, t: str):   self.log(t, "OK")
    def warn(self, t: str): self.log(t, "WARN")
    def err(self, t: str):  self.log(t, "ERR")
