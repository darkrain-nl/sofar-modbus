"""Battery cut-off writes, on a hybrid seeded from a real BTS 5K."""

from __future__ import annotations

import asyncio

import pytest
from modbus_connection import ModbusError
from modbus_connection.mock import MockModbusUnit, WriteEvent

from sofar_modbus import (
    BatConfigWriteStatus,
    BatteryConfig,
    BatteryConfigWriteError,
    InverterType,
    SofarInverter,
)
from sofar_modbus import device as device_module
from sofar_modbus.variants import GEN, HYBRID, PV, X1, X3

from .conftest import HYBRID_SERIAL

# rzirzi's BTS 5K, 0x1044-0x105B: cut-offs 30/10, recovery 15.
CAPTURE = dict(
    enumerate(
        [0, 1, 11, 5000, 0, 0, 420, 3500, 3500, 70, 90, 300]
        + [4500, 0, 5, 0, 2, 3, 4, 65497, 1, 0, 2700, 100],
        0x1044,
    )
)
# The 0x1040 mask block with 0x105B declared.
CHARGE_CUTOFF_MASK = [0x0068, 0xFE35, 0x0FFF, 0xFFFF]
STATUS = 0x1053


@pytest.fixture(autouse=True)
def instant_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Poll the commit status without the inverter's real wait."""
    monkeypatch.setattr(device_module, "_BAT_CONFIG_POLL_STEP", 0)


@pytest.fixture
def writes(hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit) -> list[WriteEvent]:
    """Seed the capture over the hybrid's; each write then succeeds."""
    mock_modbus_unit.holding.update(CAPTURE)
    writes: list[WriteEvent] = []

    def commit(event: WriteEvent) -> None:
        writes.append(event)
        mock_modbus_unit.holding[STATUS] = BatConfigWriteStatus.SUCCESS

    mock_modbus_unit.on_write(commit)
    return writes


def report(unit: MockModbusUnit, status: int) -> None:
    """Make the status read after each write answer ``status``."""
    unit.on_write(lambda _: unit.holding.__setitem__(STATUS, status))


def report_in_turn(
    monkeypatch: pytest.MonkeyPatch, unit: MockModbusUnit, *statuses: int
) -> None:
    """Answer the status reads with ``statuses``, then the last for good."""
    pending = list(statuses)
    read = unit.read_holding_registers

    async def read_status(address: int, count: int) -> list[int]:
        if address == STATUS and pending:
            unit.holding[STATUS] = pending.pop(0)
        return await read(address, count)

    monkeypatch.setattr(unit, "read_holding_registers", read_status)


def status_reads(unit: MockModbusUnit) -> int:
    return sum(event.address == STATUS for event in unit.read_events)


async def test_the_cutoffs_go_out_as_19_words(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    """Only DOD changes; the control word commits, the rest is as read."""
    await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert [(event.address, event.values) for event in writes] == [
        (
            0x1044,
            [0, 1, 11, 5000, 0, 0, 420, 3500, 3500, 69, 90, 300]
            + [4500, 0, 5, 1, 2, 3, 4],
        )
    ]


async def test_each_cutoff_maps_to_its_register(
    hybrid: SofarInverter, writes: list[WriteEvent]
) -> None:
    """DOD = 100 - on-grid, EOD = 100 - off-grid, buffer = the gap."""
    await hybrid.async_write_battery_cutoffs(60, 20, 45)
    assert writes[0].values[9:15] == [40, 80, 300, 4500, 0, 25]


async def test_the_charge_cutoff_goes_out_as_24_words(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    """The exact block the BTS 5K took on 2026-11-08."""
    mock_modbus_unit.holding[0x1040] = CHARGE_CUTOFF_MASK
    await hybrid.async_write_battery_cutoffs(30, 10, 15, 95)
    assert [(event.address, event.values) for event in writes] == [
        (
            0x1044,
            [0, 1, 11, 5000, 0, 0, 420, 3500, 3500, 70, 90, 300]
            + [4500, 0, 5, 1, 2, 3, 4, 65497, 1, 0, 2700, 95],
        )
    ]
    assert mock_modbus_unit.holding[0x105B] == 95


async def test_the_selected_battery_is_kept(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    """Writing another ID would load that battery's parameters instead."""
    mock_modbus_unit.holding.update({0x1044: 2, 0x1045: 7, 0x1046: 1})
    mock_modbus_unit.holding[0x1051] = 1
    await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert writes[0].values[:3] == [2, 7, 1]
    assert writes[0].values[13] == 1


@pytest.mark.parametrize("stale", [2, 0xFFFF])
async def test_the_control_word_always_commits(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    stale: int,
) -> None:
    """2 resets to defaults; a read status must never go back out."""
    mock_modbus_unit.holding[STATUS] = stale
    await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert writes[0].values[STATUS - 0x1044] == 1


@pytest.mark.parametrize(
    ("on_grid", "off_grid", "recovery", "charge"),
    [
        (9, 9, 15, None),
        (101, 10, 15, None),
        (30, 9, 15, None),
        (30, 100, 100, None),
        (40, 31, 36, None),
        (20, 30, 40, None),
        (30, 10, 14, None),
        (30, 10, 101, None),
        (30, 10, 15, 59),
        (30, 10, 15, 101),
    ],
)
async def test_values_outside_the_rules_are_refused(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    on_grid: int,
    off_grid: int,
    recovery: int,
    charge: int | None,
) -> None:
    mock_modbus_unit.holding[0x1040] = CHARGE_CUTOFF_MASK
    with pytest.raises(ValueError):
        await hybrid.async_write_battery_cutoffs(on_grid, off_grid, recovery, charge)
    assert not writes


async def test_the_broken_rule_is_named(
    hybrid: SofarInverter, writes: list[WriteEvent]
) -> None:
    with pytest.raises(ValueError, match="on-grid cut-off 9% is outside 10-100"):
        await hybrid.async_write_battery_cutoffs(9, 9, 15)


@pytest.mark.parametrize(
    ("on_grid", "off_grid", "recovery", "charge"),
    [(10, 10, 15, 60), (100, 30, 100, 100), (30, 30, 35, None), (100, 10, 100, None)],
)
async def test_values_on_the_edges_are_written(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    on_grid: int,
    off_grid: int,
    recovery: int,
    charge: int | None,
) -> None:
    mock_modbus_unit.holding[0x1040] = CHARGE_CUTOFF_MASK
    await hybrid.async_write_battery_cutoffs(on_grid, off_grid, recovery, charge)
    assert len(writes) == 1


async def test_on_grid_full_is_depth_of_discharge_zero(
    hybrid: SofarInverter, writes: list[WriteEvent]
) -> None:
    """SofarCloud stores on-grid 100 as DOD 0, so the library does too."""
    await hybrid.async_write_battery_cutoffs(100, 10, 15)
    assert writes[0].values[0x104D - 0x1044] == 0


async def test_an_undeclared_charge_cutoff_is_refused(
    hybrid: SofarInverter, writes: list[WriteEvent]
) -> None:
    """0x105B is reserved in the spec; only the mask says it is real."""
    with pytest.raises(ValueError, match="does not declare a charge cut-off"):
        await hybrid.async_write_battery_cutoffs(30, 10, 15, 95)
    assert not writes


@pytest.mark.parametrize("cell_type", [0, 4, 5, 6])
async def test_a_lead_acid_battery_is_refused(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    cell_type: int,
) -> None:
    """Lead-acid takes 23 words; only the 19-word path is proven."""
    mock_modbus_unit.holding.update({0x1046: 1, 0x1051: cell_type})
    with pytest.raises(ValueError, match="lead-acid"):
        await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert not writes


@pytest.mark.parametrize("cell_type", [1, 2, 3])
async def test_a_lithium_battery_is_written(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    cell_type: int,
) -> None:
    mock_modbus_unit.holding.update({0x1046: 1, 0x1051: cell_type})
    await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert len(writes) == 1


async def test_a_bts_5k_reading_lead_acid_is_written(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    """The BTS 5K reports cell type 0 and took the 19-word write."""
    assert mock_modbus_unit.holding[0x1051] == 0
    assert mock_modbus_unit.holding[0x1046] == 11
    await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert len(writes) == 1


@pytest.mark.parametrize(
    ("inverter_type", "message"),
    [
        (HYBRID | X1 | GEN, "single-phase"),
        (PV | X3 | GEN, "no battery config"),
    ],
)
async def test_an_unproven_or_batteryless_inverter_is_refused(
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    inverter_type: InverterType,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await SofarInverter(
            mock_modbus_unit, serial_number=HYBRID_SERIAL, inverter_type=inverter_type
        ).async_write_battery_cutoffs(31, 10, 15)
    assert not writes


@pytest.mark.parametrize("charge", [None, 100])
async def test_values_already_set_are_not_written(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    charge: int | None,
) -> None:
    """Each commit is a stored write, so an unchanged one is skipped."""
    mock_modbus_unit.holding[0x1040] = CHARGE_CUTOFF_MASK
    await hybrid.async_write_battery_cutoffs(30, 10, 15, charge)
    assert not writes


async def test_a_changed_charge_cutoff_alone_is_written(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    mock_modbus_unit.holding[0x1040] = CHARGE_CUTOFF_MASK
    await hybrid.async_write_battery_cutoffs(30, 10, 15, 95)
    assert len(writes) == 1


@pytest.mark.parametrize("status", list(BatConfigWriteStatus)[2:])
async def test_a_failed_commit_raises_its_status(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    status: BatConfigWriteStatus,
) -> None:
    report(mock_modbus_unit, status)
    with pytest.raises(BatteryConfigWriteError) as err:
        await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert err.value.status is status
    assert status_reads(mock_modbus_unit) == 1


def test_every_documented_failure_is_covered() -> None:
    assert [int(status) for status in BatConfigWriteStatus][2:] == [
        0xFFFB,
        0xFFFC,
        0xFFFD,
        0xFFFE,
        0xFFFF,
    ]


async def test_a_busy_commit_is_waited_for(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_in_turn(monkeypatch, mock_modbus_unit, 1, 1, 0)
    await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert status_reads(mock_modbus_unit) == 3
    assert mock_modbus_unit.holding[0x104D] == 69


async def test_a_commit_busy_for_good_raises(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    """The poll is bounded, so a stuck inverter cannot hang the caller."""
    report(mock_modbus_unit, BatConfigWriteStatus.BUSY)
    with pytest.raises(BatteryConfigWriteError) as err:
        await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert err.value.status is BatConfigWriteStatus.BUSY
    assert status_reads(mock_modbus_unit) == 20


async def test_an_unknown_status_raises(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    report(mock_modbus_unit, 2)
    with pytest.raises(BatteryConfigWriteError, match="0x0002") as err:
        await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert err.value.status is None


async def test_a_stale_success_is_caught_by_the_read_back(
    hybrid: SofarInverter, mock_modbus_unit: MockModbusUnit, writes: list[WriteEvent]
) -> None:
    """The BTS 5K read 0 from the first poll, so 0 proves nothing."""
    mock_modbus_unit.on_write(lambda _: mock_modbus_unit.holding.update(CAPTURE))
    with pytest.raises(BatteryConfigWriteError, match="kept its old") as err:
        await hybrid.async_write_battery_cutoffs(31, 10, 15)
    assert err.value.status is None


def test_a_battery_config_write_error_is_a_modbus_error() -> None:
    """Callers that catch ``ModbusError`` report it as a failed write."""
    assert issubclass(BatteryConfigWriteError, ModbusError)


async def test_overlapping_writes_take_turns(
    hybrid: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    writes: list[WriteEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second read-modify-write must not read before the first commits."""
    await hybrid.async_ensure_setup()
    steps: list[str] = []
    read = mock_modbus_unit.read_holding_registers

    async def read_later(address: int, count: int) -> list[int]:
        await asyncio.sleep(0)
        steps.append(f"read {address:04X}")
        return await read(address, count)

    monkeypatch.setattr(mock_modbus_unit, "read_holding_registers", read_later)
    mock_modbus_unit.on_write(lambda event: steps.append(f"write {event.address:04X}"))
    await asyncio.gather(
        hybrid.async_write_battery_cutoffs(31, 10, 15),
        hybrid.async_write_battery_cutoffs(32, 10, 15),
    )
    assert (
        steps
        == [
            "read 1044",
            "write 1044",
            "read 1053",
            "read 1044",
        ]
        * 2
    )
    assert mock_modbus_unit.holding[0x104D] == 68


async def read_config(
    unit: MockModbusUnit, fields: tuple[str, ...] | None = None
) -> BatteryConfig:
    """A battery config read from the capture, limited to ``fields``."""
    unit.holding.update(CAPTURE)
    config = BatteryConfig(unit)
    if fields is not None:
        config.restrict_fields(fields)
    await config.async_update()
    return config


async def test_the_cutoffs_read_as_charge_left(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """DOD 70, EOD 90 and buffer 5 read back as 30, 10 and 15."""
    config = await read_config(mock_modbus_unit)
    assert config.on_grid_discharge_cutoff_soc == 30
    assert config.off_grid_discharge_cutoff_soc == 10
    assert config.off_grid_recovery_soc == 15


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (("bat_config_end_of_discharge", "bat_config_eps_buffer"), (None, 10, 15)),
        (("bat_config_depth_of_discharge", "bat_config_eps_buffer"), (30, None, None)),
        (
            ("bat_config_depth_of_discharge", "bat_config_end_of_discharge"),
            (30, 10, None),
        ),
    ],
)
async def test_a_cutoff_with_an_unread_input_is_none(
    mock_modbus_unit: MockModbusUnit,
    fields: tuple[str, ...],
    expected: tuple[int | None, int | None, int | None],
) -> None:
    """A missing register leaves its cut-off unknown, not a guess."""
    config = await read_config(mock_modbus_unit, fields)
    assert (
        config.on_grid_discharge_cutoff_soc,
        config.off_grid_discharge_cutoff_soc,
        config.off_grid_recovery_soc,
    ) == expected


async def test_written_cutoffs_read_back(
    hybrid: SofarInverter, writes: list[WriteEvent]
) -> None:
    """A poll after a write reads the values that were written."""
    await hybrid.async_write_battery_cutoffs(60, 20, 45)
    await hybrid.async_update_settings()
    assert hybrid.battery_config.on_grid_discharge_cutoff_soc == 60
    assert hybrid.battery_config.off_grid_discharge_cutoff_soc == 20
    assert hybrid.battery_config.off_grid_recovery_soc == 45
