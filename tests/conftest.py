"""Fixtures: Sofar inverters on modbus-connection's in-memory mock backend."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter, SofarLegacyInverter


def ascii_words(text: str, length: int) -> list[int]:
    """Pack ASCII into ``length`` registers, two characters each (hi, lo)."""
    padded = text.ljust(length * 2, "\0")[: length * 2]
    return [(ord(padded[i]) << 8) | ord(padded[i + 1]) for i in range(0, length * 2, 2)]


def packed_timestamp(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> list[int]:
    """Pack a BTS pack timestamp into its two registers, second field lowest."""
    raw = 0
    shift = 0
    for value, width in (
        (second, 6),
        (minute, 6),
        (hour, 5),
        (day, 5),
        (month, 4),
        (year, 6),
    ):
        raw |= value << shift
        shift += width
    return [(raw >> 16) & 0xFFFF, raw & 0xFFFF]


# A three-phase HYD hybrid: selects HYBRID | X3 | GEN | BAT_BTS.
HYBRID_SERIAL = "SP1ES12345678"

MODERN_HOLDING: dict[int, int | list[int]] = {
    # -- state and faults --
    0x0404: 2,  # system state -> Grid-connected
    0x0405: 0,  # fault 1 -> none
    0x0409: 0x0030,  # fault 5 -> PV overvoltage (0x10) + battery over-voltage (0x20)
    0x0411: 0x0001,  # fault 13 -> string fuse open circuit 1-1
    0x0417: 30,  # waiting time -> 30 s
    0x0418: 45,  # inverter temperature 1
    0x041A: 52,  # heatsink temperature 1
    0x041F: 48,  # heatsink temperature 6
    0x0420: 0xFFF6,  # module temperature 1 -> -10 (signed)
    0x0422: 33,  # module temperature 3
    0x0426: 15,  # generation time today -> 15 min
    0x0427: [0, 100],  # generation time total -> 100 min
    0x0429: [0, 200],  # service time total -> 200 min
    0x042B: 500,  # insulation resistance -> 500 kOhm
    0x0432: 0x0001,  # fault 19 -> combiner overcurrent channel 17
    0x0433: 7,  # fault 20 -> reserved, read as a raw integer
    0x043D: 0x0001,  # fault 30 -> DCDC fault
    # -- identity: clock, serial, versions --
    0x042C: [25, 8, 12, 14, 30, 5],  # 2025-08-12 14:30:05
    0x0445: ascii_words(HYBRID_SERIAL, 7),
    0x044D: ascii_words("V1", 2),
    0x044F: ascii_words("V210", 4),
    # -- on-grid output --
    0x0484: 5001,  # grid frequency -> 50.01 Hz
    0x0485: 1234,  # active power output total -> 12.34 kW
    0x0486: 0xFF9C,  # reactive power output total -> -1.00 kvar (signed)
    0x0487: 1250,  # apparent power output total -> 12.50 kVA
    0x0488: 200,  # active power PCC total -> 2.00 kW
    0x048B: 20,  # active power PCC total (0.1 kW scale) -> 2.0 kW
    0x04BD: 995,  # overall power factor -> 0.995
    0x048D: 2301,  # voltage L1 -> 230.1 V
    0x048E: 543,  # current output L1 -> 5.43 A
    0x0491: 998,  # power factor output L1 -> 0.998
    0x04A3: 2299,  # voltage L3 -> 229.9 V
    0x04BC: 3981,  # line voltage L3 -> 398.1 V
    # -- off-grid (EPS) --
    0x0504: 300,  # off-grid active power total -> 3.00 kW
    0x0507: 4998,  # off-grid frequency -> 49.98 Hz
    0x050A: 2295,  # off-grid voltage L1 -> 229.5 V
    0x0512: 2288,  # off-grid voltage L2 -> 228.8 V
    # -- PV strings --
    0x0584: 3805,  # PV voltage 1 -> 380.5 V
    0x0585: 812,  # PV current 1 -> 8.12 A
    0x0586: 309,  # PV power 1 -> 3.09 kW
    0x0587: 3712,  # PV voltage 2 -> 371.2 V
    0x0589: 275,  # PV power 2 -> 2.75 kW
    0x05C4: 58,  # total PV power -> 5.8 kW
    # -- battery string 1 --
    0x0604: 2048,  # battery voltage 1 -> 204.8 V
    0x0605: 0xFC18,  # battery current 1 -> -10.00 A (signed, discharging)
    0x0606: 0xF830,  # battery power 1 -> -20.00 kW (signed)
    0x0607: 24,  # battery temperature 1
    0x0608: 87,  # battery capacity 1 -> 87 %
    0x0609: 99,  # battery state of health 1
    0x060A: 412,  # battery charge cycles 1
    0x060B: 2044,  # battery voltage 2 -> 204.4 V
    0x0612: 2040,  # battery voltage 3 -> 204.0 V
    0x0667: 0xFFC4,  # battery power total -> -6.0 kW (signed)
    0x066A: 2,  # number of battery strings currently connected
    0x0668: 87,  # battery capacity total
    # -- energy counters --
    0x0684: [0, 1234],  # solar generation today -> 12.34 kWh (uint32)
    0x0686: [0x0001, 0x86A0],  # solar generation total -> 10000.0 kWh
    0x0688: [0, 987],  # load consumption today -> 9.87 kWh
    0x0694: [0, 550],  # battery charge today -> 5.50 kWh
    # -- rating --
    0x06ED: 150,  # rated power -> 15.0 kW
    # -- settings --
    0x100A: 0,  # last clock write -> Successful
    0x1023: 1,  # feed-in limitation -> Enabled
    0x1024: 50,  # feed-in maximum power -> 5000 W (raw * 100)
    0x1029: 2,  # EPS -> Turn On, Enable Cold Start
    0x102A: 60,  # EPS wait time
    0x102B: 1,  # battery active control -> on
    0x1035: 1,  # parallel control -> on
    0x1036: 1,  # parallel role -> Master
    0x1037: 3,  # parallel address
    0x1044: 1,  # battery config id
    0x1046: 1,  # battery protocol -> PYLON
    0x1048: 2560,  # charging voltage -> 256.0 V
    0x1051: 1,  # cell type -> Lithium iron phosphate
    0x1104: 1,  # remote switch -> On
    0x1105: 1,  # power control -> Active_Power flag set
    0x1106: 700,  # active power export limit -> 70.0 %
    0x1110: 1,  # charger mode -> Time of Use
    0x1184: 600,  # passive timeout -> 600 s
    0x1185: 1,  # passive timeout action -> Return to Previous Mode
    0x1187: [0xFFFF, 0xF830],  # passive grid power -> -2000 W (int32)
    0x1189: [0, 500],  # passive battery power min -> 500 W
    0x118B: [0, 3000],  # passive battery power max -> 3000 W
}

# A BTS battery tower: two strings of three packs, pack 0/0 selected.
BATTERY_PACK_HOLDING: dict[int, int | list[int]] = {
    0x9007: ascii_words("BTS5K", 4),
    0x900B: 102,  # BMS version
    0x900D: (3 << 8) | 2,  # 3 packs per string, 2 strings
    0x900E: 95,  # realtime capacity
    0x900F: 512,  # total voltage -> 51.2 V
    0x9010: 0xFFCE,  # total current -> -5.0 A (signed)
    0x9012: 88,  # SOC
    0x9013: 99,  # SOH
    0x9044: 0,  # pack id -> string 0, pack 0
    0x9045: packed_timestamp(25, 8, 12, 14, 30, 5),  # 2025-08-12 14:30:05
    0x9048: ascii_words("BTSPACK000000001", 9),
    0x9051: 3300,  # cell 1 -> 3.300 V
    0x9060: 3298,  # cell 16 -> 3.298 V
    0x9069: 3305,  # cell max
    0x906A: 3295,  # cell min
    0x906B: 245,  # pack temperature 1 -> 24.5 °C
    0x9071: 0xFFCE,  # pack current -> -5.0 A
    0x9072: 1000,  # remaining capacity -> 100.0 Ah
    0x9074: 137,  # cycles
}

LEGACY_HYBRID_SERIAL = "SM1E1234567890"
LEGACY_THREE_PHASE_PV_SERIAL = "SC1E1234567890"

LEGACY_HOLDING: dict[int, int | list[int]] = {
    # -- 0x0000 block: PV inverter --
    0x0000: 2,  # run mode -> Normal Mode
    0x0006: 3805,  # PV voltage 1 -> 380.5 V
    0x0007: 812,  # PV current 1 -> 8.12 A
    0x0008: 3712,  # PV voltage 2 -> 371.2 V
    0x000C: 250,  # three-phase: PV power 1 -> 2.50
    0x000F: 480,  # three-phase: active power -> 4.80
    0x0012: 2301,  # voltage R -> 230.1 V
    0x0013: 1050,  # current R -> 10.50 A
    0x0014: 2299,  # voltage S -> 229.9 V
    0x0018: [0, 5000],  # total production -> 5000 kWh
    0x001E: 41,  # heatsink temperature (three-phase)
    0x0020: 6501,  # bus voltage -> 650.1 V
    # -- 0x0200 block: storage inverter --
    0x0200: 2,  # run mode -> Normal Mode
    0x0206: 2302,  # voltage R -> 230.2 V
    0x020D: 0xF830,  # battery power charge -> -20.00 (discharging)
    0x020E: 512,  # battery voltage -> 51.2 V
    0x0210: 76,  # battery capacity -> 76 %
    0x0212: 0xFF38,  # measured power -> -2.00 kW (importing)
    0x0213: 350,  # house load -> 3.50 kW
    0x0216: 2280,  # EPS voltage -> 228.0 V
    0x021C: [0, 4321],  # generation total -> 4321 kWh
    0x0242: 315,  # generation time today -> 315 min
    # -- 0x0250 block: hybrid PV strings --
    0x0250: 3801,  # PV voltage 1 -> 380.1 V
    0x0251: 800,  # PV current 1 -> 8.00 A
    0x0252: 300,  # PV power 1 -> 3000 W (raw * 10)
    0x0253: 3702,  # PV voltage 2 -> 370.2 V
    0x0255: 250,  # PV power 2 -> 2500 W
}


@pytest.fixture
def hybrid(mock_modbus_unit: MockModbusUnit) -> SofarInverter:
    """A three-phase HYD hybrid; EPS is auto-probed, PM enabled."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding.update(BATTERY_PACK_HOLDING)
    return SofarInverter(mock_modbus_unit, read_pm=True)


@pytest.fixture
def legacy_hybrid(mock_modbus_unit: MockModbusUnit) -> SofarLegacyInverter:
    """An older single-phase storage inverter; EPS is auto-probed."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_HYBRID_SERIAL, 6)
    return SofarLegacyInverter(mock_modbus_unit)


@pytest.fixture
def legacy_three_phase_pv(mock_modbus_unit: MockModbusUnit) -> SofarLegacyInverter:
    """An older three-phase PV inverter."""
    mock_modbus_unit.holding.update(LEGACY_HOLDING)
    mock_modbus_unit.input[0x2002] = ascii_words(LEGACY_THREE_PHASE_PV_SERIAL, 6)
    return SofarLegacyInverter(mock_modbus_unit)
