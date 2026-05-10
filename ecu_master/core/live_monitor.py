"""
ecu_master/core/live_monitor.py
Polls OBD commands in a background thread.
Calls on_update(name, value_str, unit, severity) — wire to UI via after().
Evaluates each value through AlertManager.
"""

import time
import threading
import obd

from ..utils.logger import Logger
from .connection_manager import ConnectionManager
from .alert_manager import AlertManager


# Commands polled in every cycle — add / remove freely
MONITOR_COMMANDS = [
    ("Battery Voltage",  obd.commands.ELM_VOLTAGE,   "V"),
    ("Coolant Temp",     obd.commands.COOLANT_TEMP,  "°C"),
    ("Engine RPM",       obd.commands.RPM,           "rpm"),
    ("Vehicle Speed",    obd.commands.SPEED,         "km/h"),
    ("Engine Load",      obd.commands.ENGINE_LOAD,   "%"),
    ("Throttle Pos",     obd.commands.THROTTLE_POS,  "%"),
    ("Fuel Pressure",    obd.commands.FUEL_PRESSURE, "kPa"),
    ("Intake Temp",      obd.commands.INTAKE_TEMP,   "°C"),
]


class LiveMonitor:
    """
    Public API:
        start(interval_ms)
        stop()
        is_running  → bool

    Callback:
        on_update(metric_name: str, value_str: str, unit: str, severity: str)
        on_connection_lost()
    """

    def __init__(self, cm: ConnectionManager, logger: Logger,
                 alert_manager: AlertManager | None = None):
        self.cm           = cm
        self.logger       = logger
        self.am           = alert_manager or AlertManager()
        self._running     = False
        self._thread: threading.Thread | None = None
        self._interval    = 1.0

        # Callbacks
        self.on_update: callable           = lambda name, val, unit, sev: None
        self.on_connection_lost: callable  = lambda: None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, interval_ms: int = 1000):
        if self._running:
            self.logger.warn("Monitor already running.")
            return
        self._interval = interval_ms / 1000.0
        self._running  = True
        self._thread   = threading.Thread(
            target=self._loop, daemon=True, name="OBD-Monitor"
        )
        self._thread.start()
        self.logger.ok("Live monitoring started.")

    def stop(self):
        if not self._running:
            return
        self._running = False
        self.logger.info("Live monitoring stopped.")

    # ═══════════════════════════════════════════════════════════════════════
    #  PRIVATE
    # ═══════════════════════════════════════════════════════════════════════

    def _loop(self):
        while self._running:
            if not self.cm.is_connected:
                self.logger.warn("Monitor: connection lost.")
                self._running = False
                self.on_connection_lost()
                break

            for name, cmd, unit in MONITOR_COMMANDS:
                if not self._running:
                    break
                try:
                    resp = self.cm.query(cmd)
                    if resp and not resp.is_null():
                        val = resp.value
                        num = val.magnitude if hasattr(val, "magnitude") else float(val)
                        val_str  = f"{num:.1f}"
                        severity = self.am.evaluate(name, num)
                        self.on_update(name, val_str, unit, severity)
                    else:
                        self.on_update(name, "—", unit, "ok")
                except Exception as e:
                    self.logger.warn(f"Monitor [{name}]: {e}")
                    self.on_update(name, "ERR", unit, "ok")

            time.sleep(self._interval)
