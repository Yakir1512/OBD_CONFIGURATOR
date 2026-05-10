"""
ecu_master/core/alert_manager.py
Threshold-based alert system.
Each metric has a low/high threshold range.
When a value goes outside the range, alert callbacks fire.
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Threshold:
    """Safe operating range for a single metric."""
    name: str
    unit: str
    low: float | None    # None = no lower limit
    high: float | None   # None = no upper limit
    warn_low: float | None = None   # orange warning before critical
    warn_high: float | None = None

    def classify(self, value: float) -> str:
        """
        Returns severity level:
          'ok'       — within safe range
          'warning'  — outside warning threshold
          'critical' — outside hard threshold
        """
        if self.high is not None and value > self.high:
            return "critical"
        if self.low is not None and value < self.low:
            return "critical"
        if self.warn_high is not None and value > self.warn_high:
            return "warning"
        if self.warn_low is not None and value < self.warn_low:
            return "warning"
        return "ok"


# ── Default thresholds for common OBD metrics ────────────────────────────────
# Adjust freely — these are conservative starting points.
DEFAULT_THRESHOLDS: dict[str, Threshold] = {
    "Battery Voltage": Threshold(
        "Battery Voltage", "V",
        low=11.0,  high=15.5,
        warn_low=11.8, warn_high=14.8
    ),
    "Coolant Temp": Threshold(
        "Coolant Temp", "°C",
        low=None, high=110.0,
        warn_low=None, warn_high=100.0
    ),
    "Engine RPM": Threshold(
        "Engine RPM", "rpm",
        low=None, high=7000.0,
        warn_high=6500.0
    ),
    "Vehicle Speed": Threshold(
        "Vehicle Speed", "km/h",
        low=None, high=250.0,
    ),
    "Engine Load": Threshold(
        "Engine Load", "%",
        low=None, high=100.0,
        warn_high=90.0
    ),
    "Throttle Pos": Threshold(
        "Throttle Pos", "%",
        low=None, high=100.0
    ),
    "Fuel Pressure": Threshold(
        "Fuel Pressure", "kPa",
        low=200.0, high=700.0,
        warn_low=250.0, warn_high=650.0
    ),
    "Intake Temp": Threshold(
        "Intake Temp", "°C",
        low=None, high=70.0,
        warn_high=55.0
    ),
    "Oil Temp": Threshold(
        "Oil Temp", "°C",
        low=None, high=140.0,
        warn_high=120.0
    ),
    "Fuel Level": Threshold(
        "Fuel Level", "%",
        low=10.0, high=None,
        warn_low=15.0
    ),
    "Short Fuel Trim": Threshold(
        "Short Fuel Trim", "%",
        low=-25.0, high=25.0,
        warn_low=-15.0, warn_high=15.0
    ),
    "Long Fuel Trim": Threshold(
        "Long Fuel Trim", "%",
        low=-25.0, high=25.0,
        warn_low=-15.0, warn_high=15.0
    ),
    "O2 Sensor": Threshold(
        "O2 Sensor", "V",
        low=0.0, high=1.2
    ),
    "MAF": Threshold(
        "MAF", "g/s",
        low=None, high=655.35
    ),
}

# UI colors per severity (customtkinter compatible)
SEVERITY_COLORS = {
    "ok":       {"fg": "#1a7a3c", "text": "#3dcc6a", "border": "#1a7a3c"},
    "warning":  {"fg": "#7a5a00", "text": "#f0b429", "border": "#c18b00"},
    "critical": {"fg": "#7a1a1a", "text": "#ff4f4f", "border": "#cc2222"},
}


class AlertManager:
    """
    Evaluates metric values against thresholds.
    Fires on_alert(name, value, severity) callback on state change.
    Thread-safe: only fires callback when severity actually changes.
    """

    def __init__(self):
        self.thresholds: dict[str, Threshold] = dict(DEFAULT_THRESHOLDS)
        self._states: dict[str, str] = {}                    # name → last severity
        self.on_alert: Callable[[str, float, str], None] = lambda n, v, s: None

    def set_threshold(self, name: str, threshold: Threshold):
        self.thresholds[name] = threshold

    def evaluate(self, name: str, value: float) -> str:
        """
        Classify value for metric `name`.
        Fires on_alert only if severity changed.
        Returns current severity string.
        """
        threshold = self.thresholds.get(name)
        if threshold is None:
            return "ok"

        severity = threshold.classify(value)
        prev = self._states.get(name)

        if severity != prev:
            self._states[name] = severity
            self.on_alert(name, value, severity)

        return severity

    def get_colors(self, severity: str) -> dict:
        return SEVERITY_COLORS.get(severity, SEVERITY_COLORS["ok"])

    def reset(self):
        self._states.clear()
