"""
ecu_master/ui/main_window.py
MainWindow — CTkTabview with two tabs + floating Commands window.
All backend callbacks marshalled to the main thread via after(0, ...).
"""

import datetime
import threading

import obd
import customtkinter as ctk

from ..utils.logger import Logger
from ..core import (
    BluetoothScanner, ConnectionManager,
    LiveMonitor, MONITOR_COMMANDS,
    DTCReader, RawTerminal,
    AlertManager, SEVERITY_COLORS,
    VehicleDataFetcher,
)
from .vehicle_data_panel import VehicleDataPanel
from .commands_window    import CommandsWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class MainWindow(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("ECU MASTER — Professional Workshop Tool")
        self.geometry("1200x820")
        self.minsize(1000, 680)

        # ── Backend ──────────────────────────────────────────────────────────
        self.logger   = Logger()
        self.scanner  = BluetoothScanner(self.logger)
        self.cm       = ConnectionManager(self.logger)
        self.am       = AlertManager()
        self.monitor  = LiveMonitor(self.cm, self.logger, self.am)
        self.dtc      = DTCReader(self.cm, self.logger)
        self.terminal = RawTerminal(self.cm, self.logger)
        self.fetcher  = VehicleDataFetcher(self.cm, self.logger)

        # Callbacks
        self.am.on_alert               = lambda n, v, s: self.after(0, self._on_alert, n, v, s)
        self.cm.on_connected           = lambda: self.after(0, self._on_connected)
        self.cm.on_disconnected        = lambda: self.after(0, self._on_disconnected)
        self.cm.on_status_change       = lambda s: self.after(0, self._on_status_change, s)
        self.monitor.on_update         = lambda n, v, u, s: self.after(0, self._update_metric, n, v, u, s)
        self.monitor.on_connection_lost = lambda: self.after(0, self._on_disconnected)
        self.dtc.on_dtcs_ready         = lambda c: self.after(0, self._show_dtcs, c)
        self.fetcher.on_data_ready     = lambda d: self.after(0, self._on_data_ready, d)
        self.fetcher.on_progress       = lambda p: self.after(0, self._on_fetch_progress, p)

        # State
        self._selected_device: dict | None = None
        self._commands_win: CommandsWindow | None = None

        # UI
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

        self.logger.attach(self._terminal_box)
        self.logger.ok("ECU MASTER ready — click 'Scan Devices' to start.")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════════
    #  SIDEBAR
    # ═══════════════════════════════════════════════════════════════════════

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=272, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)

        ctk.CTkLabel(sb, text="ECU MASTER", font=("Consolas", 22, "bold")).pack(pady=(22, 2))
        ctk.CTkLabel(sb, text="OBD-II Workshop Tool",
                     font=("Consolas", 10), text_color="gray").pack(pady=(0, 18))

        self._section(sb, "DEVICE DISCOVERY")
        self._btn_scan = self._btn(sb, "🔍  Scan Devices", self._scan_devices)
        self._btn_scan.pack(pady=(4, 6), padx=18, fill="x")
        self._device_list = ctk.CTkScrollableFrame(sb, height=110)
        self._device_list.pack(padx=18, fill="x", pady=(0, 4))
        self._btn_auto = self._btn(sb, "⚙  Auto-Assign BT COM",
                                   self._auto_assign_com, fg="gray35", hover="gray25")
        self._btn_auto.pack(pady=(2, 10), padx=18, fill="x")
        self._btn_auto.configure(state="disabled")

        self._section(sb, "CONNECTION")
        ctk.CTkLabel(sb, text="Baud Rate", font=("Consolas", 10), text_color="gray").pack()
        self._baud = ctk.CTkComboBox(
            sb, values=["Auto", "38400", "9600", "115200", "57600"], width=232)
        self._baud.set("Auto")
        self._baud.pack(pady=(2, 8), padx=18)
        self._btn_connect = self._btn(sb, "⚡  Connect", self._connect,
                                      fg="#1a7a3c", hover="#145e2d", bold=True)
        self._btn_connect.pack(pady=(0, 4), padx=18, fill="x")
        self._btn_connect.configure(state="disabled")
        self._btn_disconnect = self._btn(sb, "✖  Disconnect", self._disconnect,
                                         fg="#7a1a1a", hover="#5e1414")
        self._btn_disconnect.pack(pady=(0, 10), padx=18, fill="x")
        self._btn_disconnect.configure(state="disabled")
        self._status_lbl = ctk.CTkLabel(
            sb, text="● OFFLINE", font=("Consolas", 12, "bold"), text_color="#e05555")
        self._status_lbl.pack(pady=(0, 10))

        ctk.CTkFrame(sb, height=1, fg_color="gray30").pack(fill="x", padx=18, pady=6)
        self._section(sb, "DIAGNOSTICS")
        self._btn_dtc = self._btn(sb, "🔴  Read DTCs", self.dtc.read)
        self._btn_dtc.pack(pady=4, padx=18, fill="x")
        self._btn_dtc.configure(state="disabled")
        self._btn_clear = self._btn(sb, "🧹  Clear DTCs", self.dtc.clear,
                                    fg="gray30", hover="gray20")
        self._btn_clear.pack(pady=(0, 4), padx=18, fill="x")
        self._btn_clear.configure(state="disabled")
        self._btn_monitor = self._btn(sb, "📊  Start Live Monitor",
                                      self._toggle_monitor, fg="gray30", hover="gray20")
        self._btn_monitor.pack(pady=(0, 4), padx=18, fill="x")
        self._btn_monitor.configure(state="disabled")

        ctk.CTkFrame(sb, height=1, fg_color="gray30").pack(fill="x", padx=18, pady=6)
        self._section(sb, "TOOLS")
        self._btn_commands = self._btn(sb, "📖  Commands Reference",
                                       self._open_commands_window,
                                       fg="gray30", hover="gray20")
        self._btn_commands.pack(pady=4, padx=18, fill="x")

    def _section(self, p, t):
        ctk.CTkLabel(p, text=t, font=("Consolas", 9), text_color="gray50").pack(pady=(4, 0))

    def _btn(self, p, t, cmd, fg="#1f538d", hover="#14375e", bold=False):
        return ctk.CTkButton(p, text=t, command=cmd, fg_color=fg, hover_color=hover,
                             height=36, font=("Consolas", 12, "bold") if bold else ("Consolas", 11))

    # ═══════════════════════════════════════════════════════════════════════
    #  MAIN — TABS
    # ═══════════════════════════════════════════════════════════════════════

    def _build_main(self):
        self._tabs = ctk.CTkTabview(self, anchor="nw")
        self._tabs.grid(row=0, column=1, padx=14, pady=14, sticky="nsew")
        self._tabs.add("Dashboard")
        self._tabs.add("Vehicle Data")
        self._tabs.tab("Dashboard").grid_columnconfigure(0, weight=1)
        self._tabs.tab("Dashboard").grid_rowconfigure(1, weight=1)
        self._tabs.tab("Vehicle Data").grid_columnconfigure(0, weight=1)
        self._tabs.tab("Vehicle Data").grid_rowconfigure(0, weight=1)
        self._build_dashboard(self._tabs.tab("Dashboard"))
        self._build_vehicle_tab(self._tabs.tab("Vehicle Data"))

    # ── Tab 1 ─────────────────────────────────────────────────────────────────

    def _build_dashboard(self, p):
        info = ctk.CTkFrame(p, height=72)
        info.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._vin_lbl   = ctk.CTkLabel(info, text="VIN: —", font=("Courier New", 16, "bold"))
        self._vin_lbl.pack(pady=(10, 2))
        self._proto_lbl = ctk.CTkLabel(info, text="Protocol: —  |  Status: OFFLINE",
                                       text_color="gray", font=("Consolas", 11))
        self._proto_lbl.pack()

        grid = ctk.CTkFrame(p)
        grid.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1)
        self._metrics: dict[str, dict] = {}
        for idx, (title, _, unit) in enumerate(MONITOR_COMMANDS):
            self._make_card(grid, title, unit, idx % 4, idx // 4)

        self._dtc_frame = ctk.CTkFrame(p)
        self._dtc_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._dtc_frame.grid_remove()
        self._dtc_box = ctk.CTkTextbox(self._dtc_frame, height=80, font=("Consolas", 11))
        self._dtc_box.pack(fill="x", padx=8, pady=6)

        self._build_terminal(p, row=3)

    def _make_card(self, p, title, unit, col, row):
        frame = ctk.CTkFrame(p, border_width=1, height=106, corner_radius=8)
        frame.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        frame.grid_propagate(False)
        ctk.CTkLabel(frame, text=title, font=("Arial", 11, "bold")).pack(pady=(8, 0))
        val_lbl = ctk.CTkLabel(frame, text="—", font=("Arial", 26, "bold"), text_color="#3b8ed0")
        val_lbl.pack()
        ctk.CTkLabel(frame, text=unit, font=("Arial", 9), text_color="gray").pack()
        self._metrics[title] = {"frame": frame, "val_lbl": val_lbl}

    def _build_terminal(self, p, row):
        term = ctk.CTkFrame(p)
        term.grid(row=row, column=0, sticky="ew")
        hdr = ctk.CTkFrame(term, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(6, 0))
        ctk.CTkLabel(hdr, text="TERMINAL / LOG",
                     font=("Consolas", 11, "bold"), text_color="gray").pack(side="left")
        ctk.CTkButton(hdr, text="Export", width=58, height=22,
                      fg_color="gray30", hover_color="gray20",
                      command=self._export_log).pack(side="right", padx=(4, 0))
        ctk.CTkButton(hdr, text="Clear", width=52, height=22,
                      fg_color="gray30", hover_color="gray20",
                      command=lambda: self._terminal_box.delete("1.0", "end")).pack(side="right")
        quick = ctk.CTkFrame(term, fg_color="transparent")
        quick.pack(fill="x", padx=10, pady=(4, 0))
        for cmd in ["ATZ", "ATRV", "ATI", "0100", "010C", "010D"]:
            ctk.CTkButton(quick, text=cmd, width=58, height=24,
                          fg_color="gray25", hover_color="gray20", font=("Consolas", 10),
                          command=lambda c=cmd: self.terminal.send(c)).pack(side="left", padx=2)
        self._terminal_box = ctk.CTkTextbox(term, height=150, font=("Consolas", 11), wrap="word")
        self._terminal_box.pack(fill="x", padx=10, pady=(4, 4))
        crow = ctk.CTkFrame(term, fg_color="transparent")
        crow.pack(fill="x", padx=10, pady=(0, 8))
        self._cmd_entry = ctk.CTkEntry(crow, placeholder_text="AT command or OBD HEX…")
        self._cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._cmd_entry.bind("<Return>", lambda e: self._send_cmd())
        ctk.CTkButton(crow, text="Send", width=76, command=self._send_cmd).pack(side="right")

    # ── Tab 2 ─────────────────────────────────────────────────────────────────

    def _build_vehicle_tab(self, p):
        self._vdp = VehicleDataPanel(p, self.am)
        self._vdp.grid(row=0, column=0, sticky="nsew")
        self._vdp.on_fetch_requested = self._fetch_all_data

    # ═══════════════════════════════════════════════════════════════════════
    #  ACTIONS
    # ═══════════════════════════════════════════════════════════════════════

    def _scan_devices(self):
        self._btn_scan.configure(state="disabled", text="Scanning…")
        for w in self._device_list.winfo_children():
            w.destroy()
        threading.Thread(target=lambda: self.after(0, self._populate_device_list,
                                                   self.scanner.scan()), daemon=True).start()

    def _populate_device_list(self, results):
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
                    font=("Consolas", 9), fg_color="transparent",
                    hover_color="gray20",
                    text_color="#3b8ed0" if is_obd else "gray",
                    anchor="w", command=lambda d=dev: self._select_device(d)
                ).pack(fill="x", pady=1)
            obd_devs = [d for d in results if d.get("is_obd")]
            if obd_devs:
                self._select_device(obd_devs[0])
        self._btn_scan.configure(state="normal", text="🔍  Scan Devices")

    def _select_device(self, dev):
        self._selected_device = dev
        self._btn_connect.configure(state="normal")
        self._btn_auto.configure(state="normal" if dev.get("bt_address") else "disabled")
        self.logger.info(f"Selected: {dev['label']}")

    def _auto_assign_com(self):
        dev = self._selected_device
        if not dev or not dev.get("bt_address"):
            self.logger.warn("No BT device with known address selected.")
            return
        self._btn_auto.configure(state="disabled", text="Assigning…")
        def _do():
            self.scanner.auto_assign_outgoing_com(dev["bt_address"], dev.get("label", "OBDII"))
            self.after(0, lambda: (
                self._btn_auto.configure(state="normal", text="⚙  Auto-Assign BT COM"),
                self._scan_devices()
            ))
        threading.Thread(target=_do, daemon=True).start()

    def _connect(self):
        dev = self._selected_device
        if not dev:
            return
        baud_str = self._baud.get()
        baud = None if baud_str == "Auto" else int(baud_str)
        self._btn_connect.configure(state="disabled", text="Connecting…")
        self.cm.connect(dev["port"], baud)

    def _disconnect(self):
        self.monitor.stop()
        self.fetcher.stop()
        self.cm.disconnect()

    def _toggle_monitor(self):
        if self.monitor.is_running:
            self.monitor.stop()
            self._btn_monitor.configure(text="📊  Start Live Monitor")
        else:
            self.monitor.start()
            self._btn_monitor.configure(text="⏹  Stop Monitor")

    def _fetch_all_data(self):
        if not self.cm.is_connected:
            self.logger.warn("Not connected.")
            return
        self.fetcher.fetch_all()

    def _open_commands_window(self):
        if self._commands_win is None or not self._commands_win.winfo_exists():
            self._commands_win = CommandsWindow(self)
            self._commands_win.on_command_selected = self._on_cmd_from_ref
        self._commands_win.show()

    def _on_cmd_from_ref(self, cmd):
        self.terminal.send(cmd)
        self._tabs.set("Dashboard")

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
            self.logger.ok(f"Log → {fname}")
        except Exception as e:
            self.logger.err(f"Export: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    #  CALLBACKS
    # ═══════════════════════════════════════════════════════════════════════

    def _on_connected(self):
        self._status_lbl.configure(text="● ONLINE", text_color="#3dcc6a")
        self._btn_connect.configure(state="disabled", text="⚡  Connect")
        self._btn_disconnect.configure(state="normal")
        self._btn_dtc.configure(state="normal")
        self._btn_clear.configure(state="normal")
        self._btn_monitor.configure(state="normal")
        self._vdp.set_fetch_enabled(True)
        self._vin_lbl.configure(text=f"VIN: {self.cm.get_vin()}")
        self._proto_lbl.configure(
            text=f"Protocol: {self.cm.get_protocol_name()}  |  Status: {self.cm.obd_status}")
        if self.cm.obd_status == obd.OBDStatus.CAR_CONNECTED:
            self.monitor.start()
            self._btn_monitor.configure(text="⏹  Stop Monitor")

    def _on_disconnected(self):
        self._status_lbl.configure(text="● OFFLINE", text_color="#e05555")
        self._btn_connect.configure(state="normal", text="⚡  Connect")
        self._btn_disconnect.configure(state="disabled")
        for b in (self._btn_dtc, self._btn_clear, self._btn_monitor):
            b.configure(state="disabled")
        self._btn_monitor.configure(text="📊  Start Live Monitor")
        self._vdp.set_fetch_enabled(False)
        self._vin_lbl.configure(text="VIN: —")
        self._proto_lbl.configure(text="Protocol: —  |  Status: OFFLINE")
        for c in self._metrics.values():
            c["val_lbl"].configure(text="—", text_color="#3b8ed0")
            c["frame"].configure(border_color="gray30", border_width=1)
        self.am.reset()

    def _on_status_change(self, status):
        if "not_connected" in status.lower() or "port_error" in status.lower():
            self._btn_connect.configure(state="normal", text="⚡  Connect")

    def _update_metric(self, name, value_str, unit, severity):
        card = self._metrics.get(name)
        if card:
            c = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["ok"])
            card["val_lbl"].configure(text=value_str, text_color=c["text"])
            card["frame"].configure(border_color=c["border"],
                                    border_width=2 if severity != "ok" else 1)
        self._vdp.update_value(name, value_str, unit, severity)

    def _on_alert(self, name, value, severity):
        if severity != "ok":
            icon = "⚠️" if severity == "warning" else "🔴"
            self.logger.warn(f"{icon} ALERT: {name} = {value:.1f} [{severity.upper()}]")

    def _show_dtcs(self, codes):
        if not codes:
            self._dtc_frame.grid_remove()
            return
        self._dtc_box.delete("1.0", "end")
        for code, desc in codes:
            self._dtc_box.insert("end", f"  {code}  →  {desc or 'No description'}\n")
        self._dtc_frame.grid()

    def _on_data_ready(self, data):
        self._vdp.populate(data)
        self._vdp.set_progress(100)
        self._tabs.set("Vehicle Data")

    def _on_fetch_progress(self, pct):
        self._vdp.set_progress(pct)

    def _on_close(self):
        self.logger.info("Shutting down…")
        self.monitor.stop()
        self.fetcher.stop()
        if self.cm.is_connected:
            self.cm.disconnect()
        self.scanner.cleanup()
        if self._commands_win and self._commands_win.winfo_exists():
            self._commands_win.destroy()
        self.destroy()
