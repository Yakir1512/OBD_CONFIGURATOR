"""
ecu_master/core/dtc_reader.py
Read and clear Diagnostic Trouble Codes via python-obd.
"""

import threading
import obd

from ..utils.logger import Logger
from .connection_manager import ConnectionManager


class DTCReader:
    """
    Public API:
        read()   → spawns thread, fires on_dtcs_ready(codes)
        clear()  → spawns thread

    Callback:
        on_dtcs_ready(codes: list[tuple[str, str]])
    """

    def __init__(self, cm: ConnectionManager, logger: Logger):
        self.cm     = cm
        self.logger = logger
        self.on_dtcs_ready: callable = lambda codes: None

    def read(self):
        threading.Thread(target=self._read_thread, daemon=True, name="DTC-Read").start()

    def clear(self):
        threading.Thread(target=self._clear_thread, daemon=True, name="DTC-Clear").start()

    # ═══════════════════════════════════════════════════════════════════════
    #  PRIVATE
    # ═══════════════════════════════════════════════════════════════════════

    def _read_thread(self):
        self.logger.info("Reading DTCs…")
        resp = self.cm.query(obd.commands.GET_DTC)
        if resp is None:
            self.logger.err("Not connected.")
            return
        if resp.is_null() or not resp.value:
            self.logger.ok("No DTCs — vehicle is clean.")
            self.on_dtcs_ready([])
            return
        codes = list(resp.value)
        self.logger.warn(f"{len(codes)} DTC(s) found:")
        for code, desc in codes:
            self.logger.warn(f"  {code}  →  {desc or 'No description'}")
        self.on_dtcs_ready(codes)

    def _clear_thread(self):
        self.logger.info("Clearing DTCs…")
        resp = self.cm.query(obd.commands.CLEAR_DTC)
        if resp is None:
            self.logger.err("Not connected.")
        elif resp.is_null():
            self.logger.warn("Clear sent — no ECU confirmation (may still have applied).")
        else:
            self.logger.ok("DTCs cleared successfully.")
