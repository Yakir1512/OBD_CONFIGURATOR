"""
ecu_master/ui/vehicle_data_panel.py
Tab 2 — Full vehicle data panel.
Shows all ECU-reported values grouped by category.
Metric cards change color when AlertManager fires.
"""

import customtkinter as ctk
from ..core.alert_manager import AlertManager, SEVERITY_COLORS


class VehicleDataPanel(ctk.CTkFrame):
    """
    Drop-in CTkFrame for Tab 2.
    Call update_value(name, value_str, unit, severity) from the main thread.
    Call populate(data_dict) once after a full VehicleDataFetcher run.
    """

    # Category colors (header accent)
    _CAT_COLORS = {
        "Engine":          "#1a5c9e",
        "Fuel":            "#7a4a00",
        "Emissions / O2":  "#1a6b3c",
        "Transmission":    "#4a1a7a",
        "Electrical":      "#1a4a7a",
        "Diagnostics":     "#555",
    }

    def __init__(self, parent, alert_manager: AlertManager, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.am = alert_manager

        # {metric_name: {"frame": ..., "val_lbl": ..., "unit_lbl": ...}}
        self._cards: dict[str, dict] = {}

        self._build_toolbar()
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True)
        self._scroll.grid_columnconfigure((0, 1, 2), weight=1)

        self._no_data_lbl = ctk.CTkLabel(
            self._scroll,
            text="Connect to vehicle and click  'Fetch All Data'  to populate this view.",
            font=("Consolas", 13), text_color="gray"
        )
        self._no_data_lbl.grid(row=0, column=0, columnspan=3, pady=60)

        self._row_offset = 0   # current grid row inside scroll frame

    # ═══════════════════════════════════════════════════════════════════════
    #  TOOLBAR
    # ═══════════════════════════════════════════════════════════════════════

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, height=44, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))

        self._btn_fetch = ctk.CTkButton(
            bar, text="⟳  Fetch All Data",
            font=("Consolas", 12), height=34,
            command=self._on_fetch_click
        )
        self._btn_fetch.pack(side="left", padx=(0, 10))

        self._progress_lbl = ctk.CTkLabel(
            bar, text="", font=("Consolas", 11), text_color="gray"
        )
        self._progress_lbl.pack(side="left")

        self._progress_bar = ctk.CTkProgressBar(bar, width=200, height=10)
        self._progress_bar.set(0)
        self._progress_bar.pack(side="left", padx=10)
        self._progress_bar.pack_forget()

        # Search
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        ctk.CTkEntry(
            bar, placeholder_text="Search metric…",
            textvariable=self._search_var, width=200, height=34,
            font=("Consolas", 11)
        ).pack(side="right")

        # Callback placeholder — wired by MainWindow
        self.on_fetch_requested: callable = lambda: None

    # ═══════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ═══════════════════════════════════════════════════════════════════════

    def set_progress(self, pct: int):
        """Called on main thread during fetch."""
        self._progress_bar.pack(side="left", padx=10)
        self._progress_bar.set(pct / 100)
        self._progress_lbl.configure(text=f"Fetching…  {pct}%")
        if pct >= 100:
            self._progress_bar.pack_forget()
            self._progress_lbl.configure(text="Done.")
            self._btn_fetch.configure(state="normal", text="⟳  Fetch All Data")

    def populate(self, data: dict[str, list[tuple]]):
        """
        Rebuild the entire grid from a VehicleDataFetcher result.
        data: { category: [(cmd_name, value_str, unit), ...] }
        """
        self._no_data_lbl.grid_remove()
        # Clear previous
        for w in self._scroll.winfo_children():
            if w is not self._no_data_lbl:
                w.destroy()
        self._cards.clear()
        self._row_offset = 0

        for cat, entries in data.items():
            if not entries:
                continue
            self._add_category_header(cat)
            col = 0
            for name, val_str, unit in entries:
                self._add_metric_card(cat, name, val_str, unit, col)
                col = (col + 1) % 3
            # Fill remaining columns
            if col > 0:
                self._row_offset += 1

    def update_value(self, name: str, value_str: str, unit: str, severity: str):
        """Update a single card value and apply alert color. Call on main thread."""
        card = self._cards.get(name)
        if not card:
            return
        colors = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["ok"])
        card["val_lbl"].configure(text=value_str, text_color=colors["text"])
        card["frame"].configure(border_color=colors["border"],
                                border_width=2 if severity != "ok" else 1)

    def set_fetch_enabled(self, enabled: bool):
        self._btn_fetch.configure(state="normal" if enabled else "disabled")

    # ═══════════════════════════════════════════════════════════════════════
    #  PRIVATE BUILDERS
    # ═══════════════════════════════════════════════════════════════════════

    def _add_category_header(self, cat: str):
        color = self._CAT_COLORS.get(cat, "#444")
        header = ctk.CTkFrame(self._scroll, fg_color=color, height=32, corner_radius=6)
        header.grid(row=self._row_offset, column=0, columnspan=3,
                    sticky="ew", padx=4, pady=(14, 2))
        ctk.CTkLabel(
            header, text=f"  {cat.upper()}",
            font=("Consolas", 11, "bold"), text_color="white"
        ).pack(side="left", padx=8)
        self._row_offset += 1

    def _add_metric_card(self, cat: str, name: str, val_str: str, unit: str, col: int):
        frame = ctk.CTkFrame(
            self._scroll, border_width=1, height=84, corner_radius=8
        )
        frame.grid(row=self._row_offset, column=col, padx=4, pady=4, sticky="nsew")
        frame.grid_propagate(False)

        ctk.CTkLabel(frame, text=self._clean_name(name),
                     font=("Consolas", 10, "bold"),
                     text_color="gray70", wraplength=160).pack(pady=(8, 0))

        val_lbl = ctk.CTkLabel(frame, text=val_str,
                               font=("Arial", 22, "bold"), text_color="#3b8ed0")
        val_lbl.pack()

        unit_lbl = ctk.CTkLabel(frame, text=unit,
                                font=("Arial", 9), text_color="gray")
        unit_lbl.pack()

        self._cards[name] = {"frame": frame, "val_lbl": val_lbl, "unit_lbl": unit_lbl}

        if col == 2:
            self._row_offset += 1

    @staticmethod
    def _clean_name(name: str) -> str:
        return name.replace("_", " ").title()

    # ═══════════════════════════════════════════════════════════════════════
    #  TOOLBAR ACTIONS
    # ═══════════════════════════════════════════════════════════════════════

    def _on_fetch_click(self):
        self._btn_fetch.configure(state="disabled", text="Fetching…")
        self._progress_bar.set(0)
        self._progress_bar.pack(side="left", padx=10)
        self._progress_lbl.configure(text="Starting…")
        self.on_fetch_requested()

    def _on_search(self, *_):
        query = self._search_var.get().lower()
        for name, card in self._cards.items():
            match = query in name.lower() or query in self._clean_name(name).lower()
            frame = card["frame"]
            if match or not query:
                frame.grid()
            else:
                frame.grid_remove()
