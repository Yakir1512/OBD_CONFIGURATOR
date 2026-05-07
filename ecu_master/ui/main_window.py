"""
ecu_master/ui/main_window.py
CustomTkinter UI — wires all core classes together.
All backend callbacks are marshalled to the main thread via after(0, ...).
"""

import datetime
import threading
import ctypes
import sys

import obd
import customtkinter as ctk

from ..utils.logger      import Logger
from ..core              import (
    BluetoothScanner, ConnectionManager,
    LiveMonitor, MONITOR_COMMANDS,
    DTCReader, RawTerminal,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

try:
    import winreg as _winreg
    _WINDOWS = True
except ImportError:
    _WINDOWS = False


class MainWindow(ctk.CTk):
    """Root application window."""

    def __init__(self):
        super().__init__()
        self.title("ECU MASTER — Professional Workshop Tool")
        self.geometry("1160x780")
        self.minsize(960, 660)

        # ── Backend objects ──────────────────────────────────────────────────
        self.logger   = Logger()
        self.scanner  = BluetoothScanner(self.logger)
        self.cm       = ConnectionManager(self.logger)
        self.monitor  = LiveMonitor(self.cm, self.logger)
        self.dtc      = DTCReader(self.cm, self.logger)
        self.terminal = RawTerminal(self.cm, self.logger)

        # Wire callbacks — all wrapped in after(0) to reach the main thread
        self.cm.on_connected       = lambda: self.after(0, self._on_connected)
        self.cm.on_disconnected    = lambda: self.after(0, self._on_disconnected)
        self.cm.on_status_change   = lambda s: self.after(0, self._on_status_change, s)
        self.monitor.on_update     = lambda n, v: self.after(0, self._update_metric, n, v)
        self.monitor.on_connection_lost = lambda: self.after(0, self._on_disconnected)
        self.dtc.on_dtcs_ready     = lambda c: self.after(0, self._show_dtcs, c)

        # State
        self._scan_results: list[dict] = []
        self._selected_device: dict | None = None

        # Build UI
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

        # Attach logger AFTER terminal widget exists
        self.logger.attach(self._terminal_box)
        self.logger.ok("ECU MASTER ready — click 'Scan Devices' to start.")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════════════
    #  SIDEBAR
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=272, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)

        ctk.CTkLabel(sb, text="ECU MASTER",
                     font=("Consolas", 22, "bold")).pack(pady=(22, 2))
        ctk.CTkLabel(sb, text="OBD-II Workshop Tool",
                     font=("Consolas", 10), text_color="gray").pack(pady=(0, 18))

        # ── Device discovery ─────────────────────────────────────────────────
        self._section(sb, "DEVICE DISCOVERY")

        self._btn_scan = self._btn(sb, "🔍  Scan Devices", self._scan_devices)
        self._btn_scan.pack(pady=(4, 6), padx=18, fill="x")

        self._device_list = ctk.CTkScrollableFrame(sb, height=110)
        self._device_list.pack(padx=18, fill="x", pady=(0, 4))

        self._btn_auto = self._btn(sb, "⚙  Auto-Assign BT COM Port",
                                   self._auto_assign_com,
                                   fg="gray35", hover="gray25")
        self._btn_auto.pack(pady=(2, 10), padx=18, fill="x")
        self._btn_auto.configure(state="disabled")

        # ── Connection ────────────────────────────────────────────────────────
        self._section(sb, "CONNECTION")

        ctk.CTkLabel(sb, text="Baud Rate",
                     font=("Consolas", 10), text_color="gray").pack()
        self._baud = ctk.CTkComboBox(
            sb, values=["Auto", "38400", "9600", "115200", "57600"], width=232
        )
        self._baud.set("Auto")
        self._baud.pack(pady=(2, 8), padx=18)

        self._btn_connect = self._btn(sb, "⚡  Connect", self._connect,
                                      fg="#1a7a3c", hover="#145e2d", bold=True)
        self._btn_connect.pack(pady=(0, 4), padx=18, fill="x")
        self._btn_connect.configure(state="disabled")

        self._btn_disconnect = self._btn(sb, "✖  Disconnect", self._disconnect,
                                         fg="#7a1a1a", hover="#5e1414")
        self._btn_disconnect.pack(pady=(0, 14), padx=18, fill="x")
        self._btn_disconnect.configure(state="disabled")

        self._status_lbl = ctk.CTkLabel(
            sb, text="● OFFLINE",
            font=("Consolas", 12, "bold"), text_color="#e05555"
        )
        self._status_lbl.pack(pady=(0, 14))

        # ── Diagnostics ───────────────────────────────────────────────────────
        ctk.CTkFrame(sb, height=1, fg_color="gray30").pack(fill="x", padx=18, pady=8)
        self._section(sb, "DIAGNOSTICS")

        self._btn_dtc = self._btn(sb, "🔴  Read DTCs", self.dtc.read)
        self._btn_dtc.pack(pady=4, padx=18, fill="x")
        self._btn_dtc.configure(state="disabled")

        self._btn_clear = self._btn(sb, "🧹  Clear DTCs", self.dtc.clear,
                                    fg="gray30", hover="gray20")
        self._btn_clear.pack(pady=(0, 4), padx=18, fill="x")
        self._btn_clear.configure(state="disabled")

        self._btn_monitor = self._btn(sb, "📊  Start Live Monitor",
                                      self._toggle_monitor,
                                      fg="gray30", hover="gray20")
        self._btn_monitor.pack(pady=(0, 8), padx=18, fill="x")
        self._btn_monitor.configure(state="disabled")

    # ── Sidebar helpers ───────────────────────────────────────────────────────

    def _section(self, parent, text: str):
        ctk.CTkLabel(parent, text=text,
                     font=("Consolas", 9), text_color="gray50").pack(pady=(4, 0))

    def _btn(self, parent, text: str, cmd,
             fg="#1f538d", hover="#14375e", bold=False):
        return ctk.CTkButton(
            parent, text=text, command=cmd,
            fg_color=fg, hover_color=hover,
            height=36,
            font=("Consolas", 12, "bold") if bold else ("Consolas", 11)
        )

    # ═══════════════════════════════════════════════════════════════════════════
    #  MAIN CONTENT
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, padx=18, pady=18, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # ── VIN / protocol bar ────────────────────────────────────────────────
        info = ctk.CTkFrame(main, height=72)
        info.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self._vin_lbl = ctk.CTkLabel(info, text="VIN: —",
                                     font=("Courier New", 16, "bold"))
        self._vin_lbl.pack(pady=(10, 2))
        self._proto_lbl = ctk.CTkLabel(info, text="Protocol: —  |  Status: OFFLINE",
                                       text_color="gray", font=("Consolas", 11))
        self._proto_lbl.pack()

        # ── Metric cards ──────────────────────────────────────────────────────
        grid = ctk.CTkFrame(main)
        grid.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1)

        self._metrics: dict[str, ctk.CTkLabel] = {}
        for idx, (title, _, unit) in enumerate(MONITOR_COMMANDS):
            self._make_card(grid, title, unit, col=idx % 4, row=idx // 4)

        # ── DTC panel (hidden until codes arrive) ─────────────────────────────
        self._dtc_frame = ctk.CTkFrame(main)
        self._dtc_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._dtc_frame.grid_remove()
        self._dtc_box = ctk.CTkTextbox(self._dtc_frame, height=80, font=("Consolas", 11))
        self._dtc_box.pack(fill="x", padx=8, pady=6)

        # ── Terminal ─────────────────────────────────────────────────────────
        term = ctk.CTkFrame(main)
        term.grid(row=3, column=0, sticky="ew")

        # Header row
        hdr = ctk.CTkFrame(term, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(6, 0))
        ctk.CTkLabel(hdr, text="TERMINAL / LOG",
                     font=("Consolas", 11, "bold"), text_color="gray").pack(side="left")
        ctk.CTkButton(hdr, text="Export", width=58, height=22,
                      fg_color="gray30", hover_color="gray20",
                      command=self._export_log).pack(side="right", padx=(4, 0))
        ctk.CTkButton(hdr, text="Clear", width=52, height=22,
                      fg_color="gray30", hover_color="gray20",
                      command=lambda: self._terminal_box.delete("1.0", "end")
                      ).pack(side="right")

        # Quick-send buttons
        quick = ctk.CTkFrame(term, fg_color="transparent")
        quick.pack(fill="x", padx=10, pady=(4, 0))
        for cmd in ["ATZ", "ATRV", "ATI", "0100", "010C", "010D"]:
            ctk.CTkButton(
                quick, text=cmd, width=58, height=24,
                fg_color="gray25", hover_color="gray20",
                font=("Consolas", 10),
                command=lambda c=cmd: self.terminal.send(c)
            ).pack(side="left", padx=2)

        # Log textbox
        self._terminal_box = ctk.CTkTextbox(term, height=160,
                                            font=("Consolas", 11), wrap="word")
        self._terminal_box.pack(fill="x", padx=10, pady=(4, 4))

        # Command entry
        cmd_row = ctk.CTkFrame(term, fg_color="transparent")
        cmd_row.pack(fill="x", padx=10, pady=(0, 8))
        self._cmd_entry = ctk.CTkEntry(
            cmd_row,
            placeholder_text="Enter AT command or OBD HEX  (e.g. ATZ, ATRV, 010C)"
        )
        self._cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._cmd_entry.bind("<Return>", lambda e: self._send_cmd())
        ctk.CTkButton(cmd_row, text="Send", width=76,
                      command=self._send_cmd).pack(side="right")

    def _make_card(self, parent, title: str, unit: str, col: int, row: int):
        card = ctk.CTkFrame(parent, border_width=1, height=106)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        card.grid_propagate(False)
        ctk.CTkLabel(card, text=title, font=("Arial", 11, "bold")).pack(pady=(8, 0))
        val = ctk.CTkLabel(card, text="—", font=("Arial", 26, "bold"),
                           text_color="#3b8ed0")
        val.pack()
        ctk.CTkLabel(card, text=unit, font=("Arial", 9), text_color="gray").pack()
        self._metrics[title] = val

    # ═══════════════════════════════════════════════════════════════════════════
    #  ACTIONS
    # ═══════════════════════════════════════════════════════════════════════════

    def _scan_devices(self):
        self._btn_scan.configure(state="disabled", text="Scanning…")
        for w in self._device_list.winfo_children():
            w.destroy()
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        results = self.scanner.scan()
        self.after(0, self._populate_device_list, results)

    def _populate_device_list(self, results: list[dict]):
        self._scan_results = results
        for w in self._device_list.winfo_children():
            w.destroy()

        if not results:
            ctk.CTkLabel(self._device_list, text="No devices found",
                         text_color="gray", font=("Consolas", 10)).pack()
        else:
            for dev in results:
                is_obd = dev.get("is_obd", False)
                ctk.CTkButton(
                    self._device_list,
                    text=("◉ " if is_obd else "○ ") + dev["label"],
                    font=("Consolas", 9),
                    fg_color="transparent",
                    hover_color="gray20",
                    text_color="#3b8ed0" if is_obd else "gray",
                    anchor="w",
                    command=lambda d=dev: self._select_device(d)
                ).pack(fill="x", pady=1)
            # Auto-select first OBD device
            obd_devs = [d for d in results if d.get("is_obd")]
            if obd_devs:
                self._select_device(obd_devs[0])

        self._btn_scan.configure(state="normal", text="🔍  Scan Devices")

    def _select_device(self, dev: dict):
        self._selected_device = dev
        self._btn_connect.configure(state="normal")
        has_bt = bool(dev.get("bt_address"))
        self._btn_auto.configure(state="normal" if has_bt else "disabled")
        self.logger.info(f"Selected: {dev['label']}")

    def _auto_assign_com(self):
        dev = self._selected_device
        if not dev or not dev.get("bt_address"):
            self.logger.warn("No BT device with known address selected.")
            return
        self._btn_auto.configure(state="disabled", text="Assigning…")

        def _do():
            self.scanner.auto_assign_outgoing_com(
                dev["bt_address"], dev.get("label", "OBDII")
            )
            self.after(0, lambda: (
                self._btn_auto.configure(state="normal",
                                         text="⚙  Auto-Assign BT COM Port"),
                self._scan_devices()
            ))

        threading.Thread(target=_do, daemon=True).start()

    def _connect(self):
        dev = self._selected_device
        if not dev:
            self.logger.warn("No device selected.")
            return
        baud_str = self._baud.get()
        baud = None if baud_str == "Auto" else int(baud_str)
        self._btn_connect.configure(state="disabled", text="Connecting…")
        self.cm.connect(dev["port"], baud)

    def _disconnect(self):
        self.monitor.stop()
        self.cm.disconnect()

    def _toggle_monitor(self):
        if self.monitor.is_running:
            self.monitor.stop()
            self._btn_monitor.configure(text="📊  Start Live Monitor")
        else:
            self.monitor.start()
            self._btn_monitor.configure(text="⏹  Stop Monitor")

    def _send_cmd(self):
        cmd = self._cmd_entry.get().strip()
        if cmd:
            self._cmd_entry.delete(0, "end")
            self.terminal.send(cmd)

    def _export_log(self):
        content = self._terminal_box.get("1.0", "end")
        fname   = f"ecu_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.ok(f"Log saved → {fname}")
        except Exception as e:
            self.logger.err(f"Export failed: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    #  BACKEND CALLBACKS  (all called on main thread via after())
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_connected(self):
        self._status_lbl.configure(text="● ONLINE", text_color="#3dcc6a")
        self._btn_connect.configure(state="disabled", text="⚡  Connect")
        self._btn_disconnect.configure(state="normal")
        self._btn_dtc.configure(state="normal")
        self._btn_clear.configure(state="normal")
        self._btn_monitor.configure(state="normal")
        self._vin_lbl.configure(text=f"VIN: {self.cm.get_vin()}")
        self._proto_lbl.configure(
            text=f"Protocol: {self.cm.get_protocol_name()}  |  Status: {self.cm.obd_status}"
        )
        if self.cm.obd_status == obd.OBDStatus.CAR_CONNECTED:
            self.monitor.start()
            self._btn_monitor.configure(text="⏹  Stop Monitor")

    def _on_disconnected(self):
        self._status_lbl.configure(text="● OFFLINE", text_color="#e05555")
        self._btn_connect.configure(state="normal", text="⚡  Connect")
        self._btn_disconnect.configure(state="disabled")
        self._btn_dtc.configure(state="disabled")
        self._btn_clear.configure(state="disabled")
        self._btn_monitor.configure(state="disabled", text="📊  Start Live Monitor")
        self._vin_lbl.configure(text="VIN: —")
        self._proto_lbl.configure(text="Protocol: —  |  Status: OFFLINE")
        for lbl in self._metrics.values():
            lbl.configure(text="—")

    def _on_status_change(self, status: str):
        if "not_connected" in status.lower() or "port_error" in status.lower():
            self._btn_connect.configure(state="normal", text="⚡  Connect")

    def _update_metric(self, name: str, value: str):
        if name in self._metrics:
            self._metrics[name].configure(text=value)

    def _show_dtcs(self, codes: list):
        if not codes:
            self._dtc_frame.grid_remove()
            return
        self._dtc_box.delete("1.0", "end")
        for code, desc in codes:
            self._dtc_box.insert("end", f"  {code}  →  {desc or 'No description'}\n")
        self._dtc_frame.grid()

    # ═══════════════════════════════════════════════════════════════════════════
    #  CLOSE
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_close(self):
        self.logger.info("Shutting down…")
        self.monitor.stop()
        if self.cm.is_connected:
            self.cm.disconnect()
        self.scanner.cleanup()   # delete auto-created COM ports
        self.destroy()
