"""The old ``sofar_modbus.modern`` path Core still imports from."""

from __future__ import annotations

import sofar_modbus
from sofar_modbus.modern import BatConfigCellType, BatConfigWriteStatus
from sofar_modbus.modern.battery_pack import BatteryPack
from sofar_modbus.modern.device import InverterSilentError, SofarInverter
from sofar_modbus.modern.enums import ChargerUseMode, PowerControlFlags
from sofar_modbus.modern.fault_log import FaultLog
from sofar_modbus.modern.faults import FAULTS, FaultCategory, FaultLogEntry


def test_the_old_path_hands_out_the_same_objects() -> None:
    assert BatConfigCellType is sofar_modbus.BatConfigCellType
    assert BatConfigWriteStatus is sofar_modbus.BatConfigWriteStatus
    assert BatteryPack is sofar_modbus.BatteryPack
    assert InverterSilentError is sofar_modbus.InverterSilentError
    assert SofarInverter is sofar_modbus.SofarInverter
    assert ChargerUseMode is sofar_modbus.ChargerUseMode
    assert PowerControlFlags is sofar_modbus.PowerControlFlags
    assert FaultLog is sofar_modbus.FaultLog
    assert FAULTS is sofar_modbus.FAULTS
    assert FaultCategory is sofar_modbus.FaultCategory
    assert FaultLogEntry is sofar_modbus.FaultLogEntry
