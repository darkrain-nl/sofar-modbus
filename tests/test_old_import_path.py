"""The old ``sofar_modbus.modern`` path Core still imports from."""

from __future__ import annotations

import sofar_modbus
from sofar_modbus import modern
from sofar_modbus.modern import battery_pack, device, enums, fault_log, faults


def test_every_name_core_imports_is_the_same_object() -> None:
    assert modern.BatConfigCellType is sofar_modbus.BatConfigCellType
    assert modern.BatConfigWriteStatus is sofar_modbus.BatConfigWriteStatus
    assert battery_pack.BatteryPack is sofar_modbus.BatteryPack
    assert device.BATTERY_PACKS is sofar_modbus.BATTERY_PACKS
    assert device.BATTERY_STRING_COMPONENTS is sofar_modbus.BATTERY_STRING_COMPONENTS
    assert device.PV_STRING_COMPONENTS is sofar_modbus.PV_STRING_COMPONENTS
    assert device.READING_COMPONENTS is sofar_modbus.READING_COMPONENTS
    assert device.BatteryTowerSilentError is sofar_modbus.BatteryTowerSilentError
    assert device.InverterSilentError is sofar_modbus.InverterSilentError
    assert device.SofarInverter is sofar_modbus.SofarInverter
    assert enums.BatConfigCellType is sofar_modbus.BatConfigCellType
    assert enums.BatConfigProtocol is sofar_modbus.BatConfigProtocol
    assert enums.ChargerUseMode is sofar_modbus.ChargerUseMode
    assert enums.EpsControlMode is sofar_modbus.EpsControlMode
    assert enums.FeedinLimitationMode is sofar_modbus.FeedinLimitationMode
    assert enums.PassiveModeTimeoutAction is sofar_modbus.PassiveModeTimeoutAction
    assert enums.PowerControlFlags is sofar_modbus.PowerControlFlags
    assert enums.RemoteSwitchOnOff is sofar_modbus.RemoteSwitchOnOff
    assert enums.SyncRtcResult is sofar_modbus.SyncRtcResult
    assert enums.SystemState is sofar_modbus.SystemState
    assert fault_log.FaultLog is sofar_modbus.FaultLog
    assert faults.FAULTS is sofar_modbus.FAULTS
    assert faults.FaultCategory is sofar_modbus.FaultCategory
    assert faults.FaultLogEntry is sofar_modbus.FaultLogEntry
