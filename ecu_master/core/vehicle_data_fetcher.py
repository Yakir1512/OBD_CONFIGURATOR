"""
ecu_master/core/vehicle_data_fetcher.py
Queries ALL supported OBD commands from the ECU and categorises the results.
Runs in a background thread. Fires on_data_ready(categories) when done.
"""

import threading
import obd
from typing import Callable

from ..utils.logger import Logger
from .connection_manager import ConnectionManager


# ── Category definitions (strings only — resolved safely at runtime) ─────────
# Using string names instead of obd.commands.X directly prevents AttributeError
# crashes when a command doesn't exist in the installed python-obd version.

_CATEGORY_NAMES: dict[str, list[str]] = {
    "Engine": [
        "RPM", "ENGINE_LOAD", "COOLANT_TEMP", "INTAKE_TEMP",
        "INTAKE_PRESSURE", "MAF", "THROTTLE_POS", "THROTTLE_POS_B",
        "THROTTLE_POS_C", "THROTTLE_ACTUATOR", "TIMING_ADVANCE", "RUN_TIME",
    ],
    "Fuel": [
        "FUEL_PRESSURE", "FUEL_RAIL_PRESSURE_VAC", "FUEL_RAIL_PRESSURE_DIRECT",
        "FUEL_LEVEL", "FUEL_STATUS", "SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1",
        "SHORT_FUEL_TRIM_2", "LONG_FUEL_TRIM_2", "FUEL_INJECT_TIMING",
        "WARMUPS_SINCE_DTC_CLEAR", "DISTANCE_SINCE_DTC_CLEAR", "DISTANCE_W_MIL",
    ],
    "Emissions / O2": [
        "O2_B1S1", "O2_B1S2", "O2_B1S3", "O2_B1S4",
        "O2_B2S1", "O2_B2S2", "O2_B2S3", "O2_B2S4",
        "O2_SENSORS", "COMMANDED_EGR", "EGR_ERROR", "EVAPORATIVE_PURGE",
        "ETHANOL_PERCENT", "CATALYST_TEMP_B1S1", "CATALYST_TEMP_B1S2",
        "CATALYST_TEMP_B2S1", "CATALYST_TEMP_B2S2",
    ],
    "Transmission": [
        "SPEED", "RELATIVE_THROTTLE_POS", "TRANSMISSION_ACTUAL_GEAR",
        "GEAR", "TRANSMISSION_ACTUAL_GEAR",
    ],
    "Electrical": [
        "ELM_VOLTAGE", "CONTROL_MODULE_VOLTAGE", "HYBRID_BATTERY_REMAINING",
    ],
    "Diagnostics": [
        "STATUS", "FREEZE_DTC", "OBD_COMPLIANCE",
        "PIDS_A", "PIDS_B", "PIDS_C",
        "VIN", "ECU_NAME", "CALIBRATION_ID",
    ],
}


def _resolve_categories() -> dict[str, list]:
    """
    Build CATEGORIES at runtime by resolving string names against obd.commands.
    Commands missing from the installed python-obd version are silently skipped.
    """
    resolved: dict[str, list] = {}
    skipped: list[str] = []
    seen: set[str] = set()          # deduplicate within a category

    for cat, names in _CATEGORY_NAMES.items():
        cmds = []
        for name in names:
            if name in seen:
                continue
            cmd = getattr(obd.commands, name, None)
            if cmd is not None:
                cmds.append(cmd)
                seen.add(name)
            else:
                skipped.append(name)
        resolved[cat] = cmds

    if skipped:
        import warnings
        warnings.warn(
            f"python-obd: {len(skipped)} command(s) not available in this version "
            f"and will be skipped: {', '.join(skipped)}",
            RuntimeWarning, stacklevel=2
        )
    return resolved


# Built once at import time — safe because _resolve_categories never raises.
CATEGORIES: dict[str, list] = _resolve_categories()


class VehicleDataFetcher:
    """
    Queries all supported OBD commands.

    Public API:
        fetch_all()  → spawns thread, fires on_data_ready(result)
        result dict: { category: [(cmd_name, value_str, unit), ...], ... }

    Callback:
        on_data_ready(data: dict[str, list[tuple]])
        on_progress(pct: int)
    """

    def __init__(self, cm: ConnectionManager, logger: Logger):
        self.cm     = cm
        self.logger = logger
        self._running = False

        self.on_data_ready: Callable[[dict], None] = lambda d: None
        self.on_progress: Callable[[int], None]    = lambda p: None

    def fetch_all(self):
        if self._running:
            self.logger.warn("Fetch already in progress.")
            return
        threading.Thread(target=self._fetch_thread, daemon=True,
                         name="VehicleDataFetch").start()

    def stop(self):
        self._running = False

    # ── Private ───────────────────────────────────────────────────────────────

    def _fetch_thread(self):
        self._running = True
        self.logger.info("Fetching all vehicle data…")

        # Flatten all commands
        all_cmds: list[tuple[str, object]] = []
        for cat, cmds in CATEGORIES.items():
            for cmd in cmds:
                all_cmds.append((cat, cmd))

        total = len(all_cmds)
        result: dict[str, list] = {cat: [] for cat in CATEGORIES}
        done = 0

        for cat, cmd in all_cmds:
            if not self._running:
                break
            if not self.cm.is_connected:
                self.logger.warn("Connection lost during data fetch.")
                break

            try:
                if self.cm.connection and self.cm.connection.supports(cmd):
                    resp = self.cm.query(cmd)
                    if resp and not resp.is_null():
                        val    = resp.value
                        unit   = str(getattr(val, "units", ""))
                        numval = val.magnitude if hasattr(val, "magnitude") else val
                        try:
                            val_str = f"{float(numval):.2f}"
                        except (TypeError, ValueError):
                            val_str = str(val)
                        result[cat].append((cmd.name, val_str, unit))
                        self.logger.info(f"  {cmd.name}: {val_str} {unit}")
            except Exception as e:
                self.logger.warn(f"  {cmd.name}: {e}")

            done += 1
            self.on_progress(int(done / total * 100))

        self._running = False
        supported_total = sum(len(v) for v in result.values())
        self.logger.ok(f"Data fetch complete — {supported_total} values from ECU.")
        self.on_data_ready(result)