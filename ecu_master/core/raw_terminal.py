"""
ecu_master/core/raw_terminal.py
Sends raw AT / HEX commands directly to the ELM327 serial port,
bypassing python-obd's command layer.
"""

import time
import threading
import obd
import serial

from ..utils.logger import Logger
from .connection_manager import ConnectionManager


class RawTerminal:
    """
    Public API:
        send(cmd_str)  → spawns thread

    Sends the raw string to the ELM327 and logs the response.
    Falls back to python-obd named commands if the serial port
    cannot be accessed directly.
    """

    _RESPONSE_TIMEOUT = 5.0   # seconds to wait for ELM '>' prompt

    def __init__(self, cm: ConnectionManager, logger: Logger):
        self.cm     = cm
        self.logger = logger

    def send(self, cmd_str: str):
        threading.Thread(
            target=self._send_thread,
            args=(cmd_str.strip(),),
            daemon=True,
            name="RawTerminal-Send"
        ).start()

    # ═══════════════════════════════════════════════════════════════════════
    #  PRIVATE
    # ═══════════════════════════════════════════════════════════════════════

    def _send_thread(self, cmd_str: str):
        self.logger.info(f"TX → {cmd_str}")
        conn = self.cm.connection
        if not conn:
            self.logger.err("Not connected.")
            return

        port_obj = self._find_serial_port(conn)
        if port_obj:
            self._send_via_serial(port_obj, cmd_str)
        else:
            self.logger.warn("Direct serial access unavailable — trying OBD named command.")
            self._send_via_obd(cmd_str)

    def _find_serial_port(self, conn: obd.OBD) -> serial.Serial | None:
        """Walk python-obd internals to find the underlying Serial object."""
        for attr in ("interface", "_port", "port"):
            obj = getattr(conn, attr, None)
            if obj is None:
                continue
            if isinstance(obj, serial.Serial) and obj.is_open:
                return obj
            for inner in ("port", "_port", "serial"):
                inner_obj = getattr(obj, inner, None)
                if isinstance(inner_obj, serial.Serial) and inner_obj.is_open:
                    return inner_obj
        return None

    def _send_via_serial(self, port: serial.Serial, cmd_str: str):
        try:
            port.reset_input_buffer()
            port.write((cmd_str + "\r").encode("ascii"))

            buf      = b""
            deadline = time.time() + self._RESPONSE_TIMEOUT
            while time.time() < deadline:
                if port.in_waiting:
                    buf += port.read(port.in_waiting)
                    if b">" in buf:
                        break
                time.sleep(0.05)

            response = (
                buf.decode("ascii", errors="replace")
                   .replace("\r", " ")
                   .replace(">", "")
                   .strip()
            )
            self.logger.ok(f"RX ← {response}")
        except Exception as e:
            self.logger.err(f"Serial send error: {e}")

    def _send_via_obd(self, cmd_str: str):
        """Fallback: match against python-obd command names."""
        key = cmd_str.upper().replace(" ", "_")
        if hasattr(obd.commands, key):
            resp = self.cm.query(getattr(obd.commands, key))
            self.logger.ok(f"RX ← {resp.value if resp else 'no response'}")
        else:
            self.logger.warn(
                f"Unknown command '{cmd_str}'. "
                "Try: ATZ · ATRV · ATI · 0100 · 010C · 010D"
            )
