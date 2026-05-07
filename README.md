# ECU MASTER — OBD-II Workshop Tool

## Project Structure

```
ecu_master_project/
├── main.py                        ← Entry point (run this)
├── requirements.txt
└── ecu_master/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── bt_scanner.py          ← BluetoothScanner
    │   ├── connection_manager.py  ← ConnectionManager
    │   ├── live_monitor.py        ← LiveMonitor
    │   ├── dtc_reader.py          ← DTCReader
    │   └── raw_terminal.py        ← RawTerminal
    ├── ui/
    │   ├── __init__.py
    │   └── main_window.py         ← MainWindow (CTk UI)
    └── utils/
        ├── __init__.py
        └── logger.py              ← Logger
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Debug Guide

| Symptom | File to check | What to look for |
|---------|--------------|-----------------|
| No ports found | `bt_scanner.py` | `_scan_serial_ports`, `_scan_bt_registry` |
| Port opens but ELM not found | `connection_manager.py` | `_try_connect` — check baud order |
| ELM found but ECU not responding | `connection_manager.py` | `ELM_CONNECTED` branch — ignition ON? |
| Metrics stuck at `—` | `live_monitor.py` | `_loop` — check `on_update` callback |
| DTC read fails | `dtc_reader.py` | `_read_thread` |
| Raw command no response | `raw_terminal.py` | `_find_serial_port` — inspect conn internals |
| UI freezes | `main_window.py` | Ensure all backend calls use `after(0, ...)` |

## Bluetooth Connection Tips

1. Pair the OBDII adapter in Windows Bluetooth settings first.
2. Go to **Bluetooth Settings → More Bluetooth options → COM Ports**.
3. Ensure an **Outgoing** COM port exists for the device.
4. Run `main.py` **as Administrator** to allow auto COM-port creation.
5. Select the device in the app → click **Connect**.

## Baud Rate Guide

| Adapter type | Recommended baud |
|-------------|-----------------|
| Generic BT ELM327 (most common) | 38400 |
| USB ELM327 | 115200 |
| Old clone adapters | 9600 |
| High-speed clones | 57600 |

Use **Auto** to try all rates automatically.
