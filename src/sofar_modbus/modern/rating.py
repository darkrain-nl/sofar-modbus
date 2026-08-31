"""The inverter's nameplate power rating: register 0x06ED."""

from __future__ import annotations

from modbus_connection.model import gauge

from ..model import SofarComponent


class InverterRating(SofarComponent):
    """The inverter's factory-configured rated output power."""

    # 0 is not a real nameplate rating; some models leave it unpopulated.
    rated_power = gauge(0x06ED, 0.1, signed=False, unit="kW", nan=0)
