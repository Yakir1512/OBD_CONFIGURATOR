"""
ecu_master/ui/commands_window.py
Floating, collapsible reference window listing all OBD-II commands.
Can be minimised to a compact title bar (140×30) or expanded (380×600).
Clicking any command sends it to the terminal via on_command_selected callback.
"""

import obd
import customtkinter as ctk


# Full command catalogue with descriptions
_COMMAND_CATALOGUE = {
    "ELM Adapter": [
        ("ATZ",   "Reset adapter"),
        ("ATRV",  "Read battery voltage"),
        ("ATI",   "Adapter version info"),
        ("AT@1",  "Adapter description"),
        ("ATSP0", "Auto-detect protocol"),
        ("ATDP",  "Display current protocol"),
        ("ATMA",  "Monitor all messages"),
        ("ATH1",  "Show headers ON"),
        ("ATH0",  "Show headers OFF"),
        ("ATS0",  "Spaces OFF"),
        ("ATS1",  "Spaces ON"),
    ],
    "Engine": [
        ("010C", "Engine RPM"),
        ("0111", "Throttle position"),
        ("0104", "Calculated engine load"),
        ("010B", "Intake manifold pressure"),
        ("010F", "Intake air temperature"),
        ("0110", "MAF air flow rate"),
        ("010E", "Timing advance"),
        ("011F", "Engine run time"),
    ],
    "Fuel": [
        ("010A", "Fuel pressure"),
        ("012F", "Fuel tank level"),
        ("0103", "Fuel system status"),
        ("0106", "Short term fuel trim bank 1"),
        ("0107", "Long term fuel trim bank 1"),
        ("0108", "Short term fuel trim bank 2"),
        ("0109", "Long term fuel trim bank 2"),
        ("0122", "Fuel rail pressure (vac)"),
        ("0123", "Fuel rail pressure (direct)"),
    ],
    "Vehicle": [
        ("010D", "Vehicle speed"),
        ("0133", "Barometric pressure"),
        ("013C", "Catalyst temperature B1S1"),
        ("013D", "Catalyst temperature B2S1"),
        ("014D", "Distance with MIL on"),
        ("014E", "Time with MIL on"),
    ],
    "Diagnostics": [
        ("0101", "Monitor status (DTCs)"),
        ("0102", "Freeze frame DTC"),
        ("03",   "Read stored DTCs"),
        ("04",   "Clear DTCs"),
        ("09 02","Read VIN"),
        ("0100", "Supported PIDs 01-20"),
        ("0120", "Supported PIDs 21-40"),
        ("0140", "Supported PIDs 41-60"),
    ],
    "O2 Sensors": [
        ("0114", "O2 sensor B1S1"),
        ("0115", "O2 sensor B1S2"),
        ("0116", "O2 sensor B1S3"),
        ("0117", "O2 sensor B1S4"),
        ("0118", "O2 sensor B2S1"),
        ("0119", "O2 sensor B2S2"),
    ],
}


class CommandsWindow(ctk.CTkToplevel):
    """
    Floating reference window.
    on_command_selected(cmd_str) fires when the user clicks a command.
    """

    _EXPANDED_SIZE  = (380, 600)
    _COLLAPSED_SIZE = (240, 36)

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.title("OBD Commands Reference")
        self.geometry(f"{self._EXPANDED_SIZE[0]}x{self._EXPANDED_SIZE[1]}+80+80")
        self.resizable(True, True)
        self.attributes("-topmost", True)     # always on top

        self._expanded = True
        self.on_command_selected: callable = lambda cmd: None

        self._build()

    # ═══════════════════════════════════════════════════════════════════════
    #  BUILD
    # ═══════════════════════════════════════════════════════════════════════

    def _build(self):
        # Title bar
        title_bar = ctk.CTkFrame(self, height=36, fg_color="gray20", corner_radius=0)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        ctk.CTkLabel(
            title_bar, text="  OBD-II Command Reference",
            font=("Consolas", 11, "bold"), text_color="gray80"
        ).pack(side="left", padx=4)

        self._toggle_btn = ctk.CTkButton(
            title_bar, text="▲", width=30, height=24,
            fg_color="transparent", hover_color="gray30",
            font=("Consolas", 12), text_color="gray70",
            command=self._toggle_expand
        )
        self._toggle_btn.pack(side="right", padx=4)

        ctk.CTkButton(
            title_bar, text="✕", width=28, height=24,
            fg_color="transparent", hover_color="#7a1a1a",
            font=("Consolas", 12), text_color="gray70",
            command=self.withdraw
        ).pack(side="right")

        # Body (hidden when collapsed)
        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="both", expand=True)

        self._build_search()
        self._build_list()

    def _build_search(self):
        bar = ctk.CTkFrame(self._body, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(6, 4))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        ctk.CTkEntry(
            bar, placeholder_text="Search commands…",
            textvariable=self._search_var,
            font=("Consolas", 11), height=30
        ).pack(fill="x")

    def _build_list(self):
        self._scroll = ctk.CTkScrollableFrame(self._body, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._row_widgets: list[tuple[str, str, ctk.CTkFrame]] = []  # (cmd, desc, widget)

        for category, commands in _COMMAND_CATALOGUE.items():
            # Category header
            hdr = ctk.CTkFrame(self._scroll, fg_color="gray25", height=24, corner_radius=4)
            hdr.pack(fill="x", pady=(8, 2))
            ctk.CTkLabel(
                hdr, text=f"  {category}",
                font=("Consolas", 10, "bold"), text_color="gray60"
            ).pack(side="left", padx=4)

            for cmd, desc in commands:
                row = self._make_row(cmd, desc)
                self._row_widgets.append((cmd.lower(), desc.lower(), row))

    def _make_row(self, cmd: str, desc: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self._scroll, height=34, corner_radius=6, fg_color="transparent")
        row.pack(fill="x", pady=1)

        ctk.CTkLabel(
            row, text=cmd,
            font=("Consolas", 11, "bold"), text_color="#3b8ed0",
            width=80, anchor="w"
        ).pack(side="left", padx=(6, 0))

        ctk.CTkLabel(
            row, text=desc,
            font=("Consolas", 10), text_color="gray70", anchor="w"
        ).pack(side="left", padx=4, fill="x", expand=True)

        ctk.CTkButton(
            row, text="Send", width=46, height=24,
            fg_color="gray30", hover_color="gray20",
            font=("Consolas", 10),
            command=lambda c=cmd: self.on_command_selected(c)
        ).pack(side="right", padx=6)

        return row

    # ═══════════════════════════════════════════════════════════════════════
    #  COLLAPSE / EXPAND
    # ═══════════════════════════════════════════════════════════════════════

    def _toggle_expand(self):
        if self._expanded:
            self._body.pack_forget()
            w, h = self._COLLAPSED_SIZE
            self._toggle_btn.configure(text="▼")
        else:
            self._body.pack(fill="both", expand=True)
            w, h = self._EXPANDED_SIZE
            self._toggle_btn.configure(text="▲")
        x = self.winfo_x()
        y = self.winfo_y()
        self.geometry(f"{w}x{h}+{x}+{y}")
        self._expanded = not self._expanded

    def show(self):
        self.deiconify()
        self.lift()
        self.focus()

    # ═══════════════════════════════════════════════════════════════════════
    #  SEARCH
    # ═══════════════════════════════════════════════════════════════════════

    def _on_search(self, *_):
        q = self._search_var.get().lower()
        for cmd_l, desc_l, row in self._row_widgets:
            match = not q or q in cmd_l or q in desc_l
            if match:
                row.pack(fill="x", pady=1)
            else:
                row.pack_forget()
