"""
ecu_master/core/bt_scanner.py
Discovers paired Bluetooth devices and serial COM ports.
Auto-creates Outgoing COM ports on Windows (7/8/10/11).
Cleans up auto-created ports on exit.
"""

import re
import time
import threading
import subprocess
import serial
import serial.tools.list_ports

from ..utils.logger import Logger

# ── Optional Windows imports ──────────────────────────────────────────────────
try:
    import winreg
    _WINDOWS = True
except ImportError:
    _WINDOWS = False

try:
    import wmi as _wmi_module
    _WMI_AVAILABLE = True
except ImportError:
    _WMI_AVAILABLE = False

# OBD-related keywords for auto-detection
_OBD_KEYWORDS = ["obd", "elm", "obdii", "v-link", "vlink", "bluetooth", "bt", "serial"]


class BluetoothScanner:
    """
    Public API:
        scan()                          → list[dict]
        auto_assign_outgoing_com(...)   → str | None
        cleanup()                       → None
    """

    def __init__(self, logger: Logger):
        self.logger = logger
        self._auto_ports: list[str] = []      # ports we created — cleaned on exit
        self._lock = threading.Lock()

    # ═══════════════════════════════════════════════════════════════════════
    #  PUBLIC
    # ═══════════════════════════════════════════════════════════════════════

    def scan(self) -> list[dict]:
        """
        Returns list of device dicts:
          { label, port, source, is_obd, bt_address }
        Sources: 'serial' | 'wmi' | 'bt_registry'
        """
        results: list[dict] = []
        seen: set[str] = set()

        self._scan_serial_ports(results, seen)
        if _WINDOWS and _WMI_AVAILABLE:
            self._scan_wmi(results, seen)
        if _WINDOWS:
            self._scan_bt_registry(results, seen)

        self.logger.ok(f"Scan complete — {len(results)} device(s) found.")
        return results

    def auto_assign_outgoing_com(self, bt_address: str, device_name: str) -> str | None:
        """
        Creates a temporary Outgoing COM port for a Bluetooth device.
        Tries (in order): PowerShell PnP → Registry write.
        Returns COM port string or None.
        """
        if not _WINDOWS:
            self.logger.warn("auto_assign_outgoing_com: Windows only.")
            return None

        self.logger.info(f"Auto-assigning COM for {device_name} [{bt_address}]…")

        port = self._assign_via_powershell(bt_address, device_name)
        if not port:
            port = self._assign_via_registry(bt_address)

        if port:
            with self._lock:
                self._auto_ports.append(port)
            self.logger.ok(f"Auto-assigned {port} → {device_name}")
        else:
            self.logger.warn(
                "Could not auto-assign. "
                "Add Outgoing port manually via Bluetooth Settings → COM Ports."
            )
        return port

    def cleanup(self):
        """Remove all auto-created COM ports. Call on application exit."""
        with self._lock:
            ports = list(self._auto_ports)
            self._auto_ports.clear()
        for p in ports:
            self._remove_com_port(p)

    # ═══════════════════════════════════════════════════════════════════════
    #  SCAN HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _scan_serial_ports(self, results: list, seen: set):
        for p in serial.tools.list_ports.comports():
            desc  = p.description or "Unknown device"
            is_obd = self._is_obd(desc, p.hwid or "")
            results.append({
                "label":      f"{desc}  [{p.device}]",
                "port":       p.device,
                "source":     "serial",
                "is_obd":     is_obd,
                "bt_address": None,
            })
            seen.add(p.device)
            self.logger.info(f"  Serial: {p.device} | {desc} | HWID: {p.hwid}")

    def _scan_wmi(self, results: list, seen: set):
        try:
            c = _wmi_module.WMI()
            for port in c.Win32_SerialPort():
                if port.DeviceID in seen:
                    continue
                desc   = port.Description or port.Name or "BT Serial"
                is_obd = self._is_obd(desc, "")
                results.append({
                    "label":      f"{desc}  [{port.DeviceID}]  (WMI)",
                    "port":       port.DeviceID,
                    "source":     "wmi",
                    "is_obd":     is_obd,
                    "bt_address": None,
                })
                seen.add(port.DeviceID)
                self.logger.info(f"  WMI: {port.DeviceID} | {desc}")
        except Exception as e:
            self.logger.warn(f"WMI scan skipped: {e}")

    def _scan_bt_registry(self, results: list, seen: set):
        bt_devices = self._read_bt_paired_devices()
        self._read_bt_enum_ports(results, seen, bt_devices)

    def _read_bt_paired_devices(self) -> dict[str, str]:
        """Returns {address_hex_upper: friendly_name}."""
        devices: dict[str, str] = {}
        path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                i = 0
                while True:
                    try:
                        addr = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, addr) as dev_key:
                            try:
                                raw, _ = winreg.QueryValueEx(dev_key, "Name")
                                name = (raw.rstrip(b'\x00').decode("utf-8", errors="replace")
                                        if isinstance(raw, bytes) else str(raw))
                            except FileNotFoundError:
                                name = addr
                        devices[addr.upper()] = name
                        self.logger.info(f"  BT paired: {name} [{addr}]")
                        i += 1
                    except OSError:
                        break
        except Exception as e:
            self.logger.info(f"  BT paired-devices registry: {e}")
        return devices

    def _read_bt_enum_ports(self, results: list, seen: set, bt_devices: dict):
        path = r"SYSTEM\CurrentControlSet\Enum\BTHENUM"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as enum_key:
                i = 0
                while True:
                    try:
                        class_name = winreg.EnumKey(enum_key, i)
                        with winreg.OpenKey(enum_key, class_name) as class_key:
                            j = 0
                            while True:
                                try:
                                    inst = winreg.EnumKey(class_key, j)
                                    self._extract_enum_port(
                                        path, class_name, inst, bt_devices, results, seen
                                    )
                                    j += 1
                                except OSError:
                                    break
                        i += 1
                    except OSError:
                        break
        except Exception as e:
            self.logger.info(f"  BTHENUM registry: {e}")

    def _extract_enum_port(self, base, class_name, inst, bt_devices, results, seen):
        try:
            param_path = f"{base}\\{class_name}\\{inst}\\Device Parameters"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, param_path) as pk:
                port_name, _ = winreg.QueryValueEx(pk, "PortName")
            if port_name in seen:
                return
            addr = class_name.split("_")[-1].upper()
            dev_name = bt_devices.get(addr, class_name)
            results.append({
                "label":      f"{dev_name}  [{port_name}]  (BT-Registry)",
                "port":       port_name,
                "source":     "bt_registry",
                "is_obd":     self._is_obd(dev_name, addr),
                "bt_address": addr,
            })
            seen.add(port_name)
            self.logger.info(f"  BT-Registry: {port_name} | {dev_name}")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════════
    #  COM PORT AUTO-ASSIGNMENT
    # ═══════════════════════════════════════════════════════════════════════

    def _assign_via_powershell(self, bt_address: str, device_name: str) -> str | None:
        ps = (
            f"$d = Get-PnpDevice | Where-Object {{ $_.FriendlyName -like '*{device_name}*' }} "
            f"| Select-Object -First 1; "
            f"if ($d) {{ Write-Output $d.InstanceId }} else {{ Write-Output 'NOTFOUND' }}"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=8
            )
            out = r.stdout.strip()
            self.logger.info(f"  PS PnP lookup: {out}")
            if out and out != "NOTFOUND":
                return self._enable_pnp_device(out)
        except Exception as e:
            self.logger.info(f"  PS assign: {e}")
        return None

    def _enable_pnp_device(self, instance_id: str) -> str | None:
        last = instance_id.split("\\")[-1]
        ps = (
            f"Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false "
            f"-ErrorAction SilentlyContinue; "
            f"(Get-WmiObject Win32_SerialPort | "
            f"Where-Object {{ $_.PNPDeviceID -like '*{last}*' }}).DeviceID"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, timeout=10
            )
            port = r.stdout.strip()
            if re.match(r"COM\d+", port, re.IGNORECASE):
                return port.upper()
        except Exception as e:
            self.logger.info(f"  PnP enable: {e}")
        return None

    def _assign_via_registry(self, bt_address: str) -> str | None:
        """Windows 7/8/10 fallback — writes registry key."""
        try:
            existing = {p.device for p in serial.tools.list_ports.comports()}
            n = 10
            while f"COM{n}" in existing:
                n += 1
            port = f"COM{n}"

            key_path = (
                r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices\\"
                + bt_address.replace(":", "").lower()
                + r"\OutgoingComPort"
            )
            with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
                winreg.SetValueEx(k, "PortName",     0, winreg.REG_SZ,    port)
                winreg.SetValueEx(k, "AutoCreated",  0, winreg.REG_DWORD, 1)

            subprocess.run(["net", "stop", "bthserv"], capture_output=True, timeout=5)
            time.sleep(1)
            subprocess.run(["net", "start", "bthserv"], capture_output=True, timeout=5)
            time.sleep(2)

            if port in {p.device for p in serial.tools.list_ports.comports()}:
                return port
            self.logger.warn(f"  Registry written but {port} didn't appear — may need Admin.")
        except PermissionError:
            self.logger.warn("  Registry COM assign needs Administrator rights.")
        except Exception as e:
            self.logger.warn(f"  Registry assign: {e}")
        return None

    def _remove_com_port(self, port: str):
        if not _WINDOWS:
            return
        self.logger.info(f"Removing auto-created port {port}…")
        try:
            ps = (
                f"Get-WmiObject Win32_SerialPort | "
                f"Where-Object {{ $_.DeviceID -eq '{port}' }} | "
                f"ForEach-Object {{ $_.Delete() }}"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, timeout=8
            )
            self.logger.ok(f"Port {port} removed.")
        except Exception as e:
            self.logger.warn(f"  Remove {port}: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    #  UTILITIES
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _is_obd(desc: str, hwid: str) -> bool:
        combined = (desc + hwid).lower()
        return any(k in combined for k in _OBD_KEYWORDS)
