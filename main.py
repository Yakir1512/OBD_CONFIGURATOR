"""
main.py  — ECU MASTER entry point
Run this file directly:  python main.py
"""

import sys
import ctypes


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _check_dependencies() -> bool:
    """Verify all required packages are installed before touching any imports."""
    required = {
        "customtkinter": "pip install customtkinter",
        "serial":        "pip install pyserial",
        "obd":           "pip install obd",
    }
    missing = []
    for module, fix in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append((module, fix))

    if missing:
        print("=" * 58)
        print("  ECU MASTER — Missing dependencies")
        print("=" * 58)
        print("  The following packages are not installed:\n")
        for module, fix in missing:
            print(f"    ✗  {module:<20}  →  {fix}")
        print()
        print("  Fix — run this in your terminal:")
        print()
        modules = " ".join(m for m, _ in missing)
        print(f"    pip install {modules}")
        print()
        print("  Or install all at once:")
        print("    pip install customtkinter pyserial obd")
        print("=" * 58)
        input("\nPress Enter to close...")
        return False
    return True


if __name__ == "__main__":
    print("[DEBUG] Starting ECU MASTER...")

    # ── Dependency check (always first) ─────────────────────────────────────
    if not _check_dependencies():
        sys.exit(1)

    # ── Windows UAC elevation (optional — only for auto COM-port creation) ───
    # ShellExecuteW returns >32 if the new elevated process started successfully.
    # Only then do we exit this process. Every other case → continue normally.
    try:
        import winreg                           # presence confirms Windows
        if not _is_admin():
            print("[INFO] Requesting Administrator rights (optional — for auto COM port)...")
            try:
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, " ".join(sys.argv), None, 1
                )
                if ret > 32:
                    print("[INFO] Elevated process started — closing this instance.")
                    sys.exit(0)
                else:
                    print(f"[WARN] Elevation failed (code {ret}) — running without admin rights.")
            except Exception as e:
                print(f"[WARN] UAC declined ({e}) — running without admin rights.")
        else:
            print("[INFO] Running as Administrator.")
    except ImportError:
        print("[INFO] Not Windows — skipping UAC check.")

    # ── Launch app ───────────────────────────────────────────────────────────
    print("[DEBUG] Loading UI...")
    try:
        from ecu_master.ui import MainWindow
        print("[DEBUG] UI loaded — launching window.")
        app = MainWindow()
        app.mainloop()
    except Exception as e:
        import traceback
        print(f"\n[ERROR] Failed to launch UI:\n")
        traceback.print_exc()
        input("\nPress Enter to close...")
        sys.exit(1)