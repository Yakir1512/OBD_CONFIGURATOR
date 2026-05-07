"""
ecu_master/core/connection_manager.py
Manages the OBD-II connection lifecycle.
Tries multiple baud rates. Thread-safe. Callback-driven.
"""

import threading
import obd
import serial

from ..utils.logger import Logger

_BAUD_RATES = [38400, 9600, 115200, 57600]   # 38400 first — most BT ELM327 adapters


class ConnectionManager:
    """
    Public API:
        connect(port, baudrate)   → spawns daemon thread
        disconnect()
        query(cmd)                → obd.OBDResponse | None
        get_protocol_name()       → str
        get_vin()                 → str
        is_connected              → bool  (property)
        obd_status                → obd.OBDStatus  (property)

    Callbacks (assign before calling connect):
        on_connected()
        on_disconnected()
        on_status_change(status_str)
    """

    def __init__(self, logger: Logger):
        self.logger = logger
        self.connection: obd.OBD | None = None
        self._lock = threading.Lock()

        # Callbacks — replaced by MainWindow after instantiation
        self.on_connected:    callable = lambda: None
        self.on_disconnected: callable = lambda: None
        self.on_status_change: callable = lambda s: None

    # ═══════════════════════════════════════════════════════════════════════
    #  PROPERTIES
    # ═══════════════════════════════════════════════════════════════════════

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self.connection is not None and self.connection.is_connected()

    @property
    def obd_status(self):
        with self._lock:
            return self.connection.status() if self.connection else obd.OBDStatus.NOT_CONNECTED

    # ═══════════════════════════════════════════════════════════════════════
    #  PUBLIC
    # ═══════════════════════════════════════════════════════════════════════

    def connect(self, port: str, baudrate: int | None = None):
        """Non-blocking — spawns a daemon thread."""
        threading.Thread(
            target=self._connect_thread,
            args=(port, baudrate),
            daemon=True,
            name="OBD-Connect"
        ).start()

    def disconnect(self):
        with self._lock:
            if self.connection:
                try:
                    self.connection.close()
                    self.logger.ok("Connection closed.")
                except Exception as e:
                    self.logger.warn(f"Close error: {e}")
                self.connection = None
        self.on_disconnected()

    def query(self, cmd) -> obd.OBDResponse | None:
        with self._lock:
            if not self.connection:
                return None
            try:
                return self.connection.query(cmd)
            except Exception as e:
                self.logger.warn(f"Query {getattr(cmd, 'name', cmd)} failed: {e}")
                return None

    def get_protocol_name(self) -> str:
        with self._lock:
            if self.connection:
                try:
                    return self.connection.protocol_name()
                except Exception:
                    pass
        return "Unknown"

    def get_vin(self) -> str:
        with self._lock:
            if not self.connection:
                return "—"
            try:
                if self.connection.supports(obd.commands.VIN):
                    r = self.connection.query(obd.commands.VIN)
                    return str(r.value) if not r.is_null() else "N/A"
            except Exception:
                pass
        return "—"

    # ═══════════════════════════════════════════════════════════════════════
    #  PRIVATE — connection thread
    # ═══════════════════════════════════════════════════════════════════════

    def _connect_thread(self, port: str, baudrate: int | None):
        self.logger.info("=" * 50)
        self.logger.info(f"Connecting → {port}")

        # Step 1 — verify port is openable
        if not self._verify_port(port):
            self.on_status_change("port_error")
            return

        # Step 2 — try baud rates
        bauds = [baudrate] if baudrate else _BAUD_RATES
        conn  = None
        for baud in bauds:
            conn = self._try_connect(port, baud)
            if conn and conn.status() != obd.OBDStatus.NOT_CONNECTED:
                break
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None

        if not conn:
            self._report_failure()
            self.on_status_change("not_connected")
            return

        # Step 3 — connected
        with self._lock:
            self.connection = conn

        status = conn.status()
        self.logger.info(f"Status: {status}")
        self.on_status_change(str(status))

        if status == obd.OBDStatus.ELM_CONNECTED:
            self.logger.warn("ELM327 found — car ECU not responding.")
            self.logger.warn("→ Turn ignition to ON (position II) and retry.")
            self.on_connected()
            return

        if status == obd.OBDStatus.CAR_CONNECTED:
            self._log_vehicle_info(conn)
            self.on_connected()

    def _verify_port(self, port: str) -> bool:
        self.logger.info(f"[1/3] Verifying {port}…")
        try:
            s = serial.Serial(port, 9600, timeout=1)
            s.close()
            self.logger.ok(f"[1/3] {port} accessible.")
            return True
        except serial.SerialException as e:
            self.logger.err(f"[1/3] Cannot open {port}: {e}")
            self.logger.warn("  → Is another app using this port?")
            self.logger.warn("  → Is the Bluetooth device still connected?")
            return False

    def _try_connect(self, port: str, baud: int) -> obd.OBD | None:
        self.logger.info(f"[2/3] Trying {port} @ {baud} baud…")
        try:
            conn = obd.OBD(
                portstr=port,
                baudrate=baud,
                fast=False,     # required for Bluetooth — sends full ELM init
                timeout=15,     # 15 s per attempt
                protocol=None,  # auto-detect OBD protocol
            )
            self.logger.info(f"      Status @ {baud}: {conn.status()}")
            return conn
        except Exception as e:
            self.logger.warn(f"      {baud} baud: {e}")
            return None

    def _log_vehicle_info(self, conn: obd.OBD):
        self.logger.info("[3/3] Querying vehicle metadata…")
        try:
            self.logger.ok(f"  Protocol : {conn.protocol_name()}")
        except Exception:
            pass
        try:
            if conn.supports(obd.commands.VIN):
                r   = conn.query(obd.commands.VIN)
                vin = str(r.value) if not r.is_null() else "Not available"
            else:
                vin = "Not supported by ECU"
            self.logger.ok(f"  VIN      : {vin}")
        except Exception as e:
            self.logger.warn(f"  VIN: {e}")

    def _report_failure(self):
        self.logger.err("All baud rates failed — ELM327 not found.")
        self.logger.warn("Possible causes:")
        self.logger.warn("  • Wrong COM port (need OUTGOING, not Incoming)")
        self.logger.warn("  • Another app is using the port")
        self.logger.warn("  • Adapter not powered / not paired")
        self.logger.warn("  • Try: Bluetooth Settings → More BT options → COM Ports → Add Outgoing")
