"""
main.py  — ECU MASTER entry point
Run this file directly:  python main.py

On Windows, requests UAC elevation if not already running as Administrator
(needed for auto-COM-port registry writes).
"""

import sys
import ctypes

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _relaunch_as_admin():
    """Re-launch this script with elevation via ShellExecuteW."""
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )

if __name__ == "__main__":
    # ── Windows UAC check ────────────────────────────────────────────────────
    try:
        import winreg   # only exists on Windows
        if not _is_admin():
            print("[INFO] Requesting Administrator rights for COM port management…")
            try:
                _relaunch_as_admin()
                sys.exit(0)
            except Exception:
                print("[WARN] UAC declined — auto COM-port creation will be limited.")
    except ImportError:
        pass   # not Windows

    # ── Launch app ───────────────────────────────────────────────────────────
    from ecu_master.ui import MainWindow
    app = MainWindow()
    app.mainloop()
