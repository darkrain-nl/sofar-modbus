"""The BTS battery tower: its setup probe and the per-pack poll."""

from __future__ import annotations

import asyncio
from functools import partial

import pytest
from modbus_connection import (
    GatewayTargetError,
    IllegalDataAddressError,
    IllegalDataValueError,
    IllegalFunctionError,
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
    ServerDeviceBusyError,
    ServerDeviceFailureError,
)
from modbus_connection.mock import MockModbusUnit, WriteEvent

from sofar_modbus import SofarInverter
from sofar_modbus.model import UpdateReport
from sofar_modbus.modern import READING_COMPONENTS, SETTING_COMPONENTS
from sofar_modbus.modern.device import BATTERY_PACKS

from .conftest import MODERN_HOLDING, ascii_words, yield_before_reads

# The ESI-10K-T1 of the 2026-10-16 capture, behind an SH1 serial.
TOWER_SERIAL = "SH1ES000000001"

TOWER_HOLDING: dict[int, int | list[int]] = {
    0x9007: ascii_words("BTS 5K", 4),
    0x900B: 10033,  # BMS version
    0x900D: 0x0301,  # 3 parallel groups of 1 pack
    0x9022: 0x0007,  # groups 0, 1 and 2 online
}

# What each selection serves, keyed by the 0x9020 word.
PACK_HOLDING: dict[int, dict[int, int | list[int]]] = {
    0x0000: {
        0x9044: 0x0000,
        0x9048: ascii_words("2004400VE0", 9),
        0x9071: 0x10000 - 144,  # -14.4 A
        0x9074: 64,  # cycles
    },
    0x0100: {
        0x9044: 0x0100,
        0x9048: ascii_words("2004400VE1", 9),
        0x9071: 0x10000 - 149,  # -14.9 A
        0x9074: 77,
    },
    0x0200: {
        0x9044: 0x0200,
        0x9048: ascii_words("2004400VE2", 9),
        0x9071: 0x10000 - 228,  # -22.8 A
        0x9074: 78,
    },
}


def selection_writes(unit: MockModbusUnit) -> list[int]:
    """Record every word written to the selection register."""
    writes: list[int] = []
    unit.on_write(
        lambda event: (
            writes.append(event.values[0]) if event.address == 0x9020 else None
        )
    )
    return writes


def switch_on_selection(
    unit: MockModbusUnit, serves: dict[int, dict[int, int | list[int]]]
) -> None:
    """Serve a selection's pack once it is written, as a tower does."""

    def on_write(event: WriteEvent) -> None:
        if event.address == 0x9020 and event.values[0] in serves:
            unit.holding.update(serves[event.values[0]])

    unit.on_write(on_write)


@pytest.fixture
def tower_unit(mock_modbus_unit: MockModbusUnit) -> MockModbusUnit:
    """A three-group BTS tower serving whichever pack is selected."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding.update(TOWER_HOLDING)
    mock_modbus_unit.holding.update(PACK_HOLDING[0x0000])
    switch_on_selection(mock_modbus_unit, PACK_HOLDING)
    return mock_modbus_unit


@pytest.fixture
def tower(tower_unit: MockModbusUnit) -> SofarInverter:
    """An SH1 hybrid with a tower on its BMS port."""
    return SofarInverter(tower_unit, serial_number=TOWER_SERIAL)


def _answered(device: SofarInverter) -> dict[tuple[int, int], bool]:
    return {place: pack.answered for place, pack in device.battery_packs.items()}


# --- the setup probe -------------------------------------------------


async def test_a_three_group_tower_is_probed_once(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_update_readings()

    assert tower.has_battery_tower
    assert tower.battery_tower is not None
    assert tower.battery_tower.model == "BTS 5K"
    assert tower.battery_tower.bms_version == 10033
    assert tower.battery_tower.parallel_group_count == 3
    assert tower.battery_tower.packs_per_group == 1
    assert [(e.address, e.count) for e in tower_unit.read_events].count(
        (0x9007, 7)
    ) == 1
    assert list(tower.battery_packs) == [(0, 0), (1, 0), (2, 0)]
    assert BATTERY_PACKS in tower.expected_components


def test_battery_packs_are_in_neither_poll() -> None:
    assert BATTERY_PACKS not in READING_COMPONENTS
    assert BATTERY_PACKS not in SETTING_COMPONENTS


async def test_a_tower_is_predicted_from_the_type_before_setup(
    tower: SofarInverter,
) -> None:
    assert tower.has_battery_tower
    assert BATTERY_PACKS in tower.expected_components
    assert tower.battery_packs == {}


@pytest.mark.parametrize(
    "silence", [ModbusTimeoutError("no answer"), GatewayTargetError()]
)
async def test_a_silent_tower_is_no_tower(
    tower: SofarInverter, tower_unit: MockModbusUnit, silence: ModbusError
) -> None:
    """A hybrid running a CAN battery still carries the BTS serial."""
    tower_unit.fail_read(0x9007, silence)
    await tower.async_update_readings()

    assert not tower.has_battery_tower
    assert tower.battery_tower is None
    assert tower.battery_packs == {}
    assert BATTERY_PACKS not in tower.expected_components

    tower_unit.read_events.clear()
    assert await tower.async_update_packs() == UpdateReport()
    tower_unit.read_events.clear()
    await tower.async_read_masks()
    assert not any(e.address >= 0x9000 for e in tower_unit.read_events)


@pytest.mark.parametrize(
    "refusal",
    [IllegalFunctionError(), IllegalDataAddressError(), IllegalDataValueError()],
)
async def test_a_refused_tower_is_gone_even_once_stored(
    tower_unit: MockModbusUnit, refusal: ModbusError
) -> None:
    tower_unit.fail_read(0x9007, refusal)
    device = SofarInverter(
        tower_unit, serial_number=TOWER_SERIAL, has_battery_tower=True
    )
    await device.async_update_readings()

    assert not device.has_battery_tower
    assert BATTERY_PACKS not in device.expected_components


@pytest.mark.parametrize("layout", [0x0000, 0x0300, 0x0001])
@pytest.mark.parametrize("stored", [False, True])
async def test_a_layout_of_no_packs_is_no_tower(
    tower_unit: MockModbusUnit, layout: int, stored: bool
) -> None:
    """Another battery's BMS can answer the tower block with zeros."""
    tower_unit.holding[0x900D] = layout
    device = SofarInverter(
        tower_unit, serial_number=TOWER_SERIAL, has_battery_tower=stored
    )
    await device.async_update_readings()

    assert not device.has_battery_tower
    assert device.battery_tower is None
    assert BATTERY_PACKS not in device.expected_components
    assert await device.async_update_packs() == UpdateReport()


async def test_a_stored_tower_survives_a_timed_out_probe(
    tower_unit: MockModbusUnit,
) -> None:
    """Its layout is read on the first pack poll instead."""
    tower_unit.fail_read(0x9007, ModbusTimeoutError("asleep"))
    device = SofarInverter(
        tower_unit, serial_number=TOWER_SERIAL, has_battery_tower=True
    )
    await device.async_update_readings()

    assert device.has_battery_tower
    assert BATTERY_PACKS in device.expected_components
    assert device.battery_tower is not None
    assert device.battery_tower.parallel_group_count is None
    assert device.battery_packs == {}

    report = await device.async_update_packs()
    assert set(report.failed) == {BATTERY_PACKS}
    assert isinstance(report.failed[BATTERY_PACKS], ModbusTimeoutError)

    tower_unit.fail_read(0x9007, None)
    report = await device.async_update_packs()
    assert report.updated == {BATTERY_PACKS}
    assert device.battery_tower.parallel_group_count == 3
    assert _answered(device) == {(0, 0): True, (1, 0): True, (2, 0): True}


@pytest.mark.parametrize("layout", [0x0000, 0x0300, 0x0001])
async def test_a_stored_tower_laying_out_no_packs_is_dropped(
    tower_unit: MockModbusUnit, layout: int
) -> None:
    """The stored verdict kept it; the first layout read settles it."""
    tower_unit.fail_read(0x9007, ModbusTimeoutError("asleep"))
    device = SofarInverter(
        tower_unit, serial_number=TOWER_SERIAL, has_battery_tower=True
    )
    await device.async_update_readings()
    tower_unit.fail_read(0x9007, None)
    tower_unit.holding[0x900D] = layout
    writes = selection_writes(tower_unit)

    report = await device.async_update_packs()

    assert set(report.failed) == {BATTERY_PACKS}
    assert str(report.failed[BATTERY_PACKS]) == "the tower lays out no packs"
    assert not device.has_battery_tower
    assert device.battery_tower is None
    assert device.battery_packs == {}
    assert BATTERY_PACKS not in device.expected_components
    assert writes == []
    assert await device.async_update_packs() == UpdateReport()


async def test_a_retried_setup_that_finds_no_tower_keeps_no_packs(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """The first try laid the packs out before a later step failed."""
    tower_unit.fail_read(0x0680, ServerDeviceBusyError())
    with pytest.raises(ServerDeviceBusyError):
        await tower.async_update_readings()
    tower_unit.fail_read(0x0680, None)
    tower_unit.fail_read(0x9007, IllegalDataAddressError())

    await tower.async_update_readings()

    assert not tower.has_battery_tower
    assert tower.battery_packs == {}


async def test_a_busy_tower_fails_setup(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """Only a refusal or silence settles the tower; setup tries again."""
    tower_unit.fail_read(0x9007, ServerDeviceBusyError())
    with pytest.raises(ServerDeviceBusyError):
        await tower.async_update_readings()

    tower_unit.fail_read(0x9007, None)
    await tower.async_update_readings()
    assert tower.has_battery_tower


# --- the pack poll ---------------------------------------------------


async def test_every_pack_of_a_three_group_tower_is_read(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_ensure_setup()
    writes = selection_writes(tower_unit)
    tower_unit.read_events.clear()

    report = await tower.async_update_packs()

    assert report.updated == {BATTERY_PACKS}
    assert report.failed == {}
    assert tower_unit.read_events[0].address == 0x9022
    # Pack 0 of group 0 is already served, so it needs no write.
    assert writes == [0x0100, 0x0200]
    packs = tower.battery_packs
    assert _answered(tower) == {(0, 0): True, (1, 0): True, (2, 0): True}
    assert [(p.group_nr, p.pack_nr) for p in packs.values()] == [
        (0, 0),
        (1, 0),
        (2, 0),
    ]
    assert [p.pack_cycles for p in packs.values()] == [64, 77, 78]
    assert [p.pack_current for p in packs.values()] == pytest.approx(
        [-14.4, -14.9, -22.8]
    )
    assert packs[1, 0].pack_serial_number == "2004400VE1"
    assert len({id(pack) for pack in packs.values()}) == 3


async def test_a_sweep_starts_at_the_pack_the_tower_serves(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """The last sweep left group 2 selected, so it costs no write."""
    await tower.async_update_packs()
    writes = selection_writes(tower_unit)

    assert (await tower.async_update_packs()).updated == {BATTERY_PACKS}
    assert writes == [0x0000, 0x0100]
    assert _answered(tower) == {(0, 0): True, (1, 0): True, (2, 0): True}


async def test_a_tower_moved_by_another_client_still_reads_every_pack(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """A stale start costs the writes an unordered sweep would."""
    await tower.async_update_packs()
    tower_unit.holding.update(PACK_HOLDING[0x0100])
    writes = selection_writes(tower_unit)

    await tower.async_update_packs()

    assert writes == [0x0200, 0x0000, 0x0100]
    assert _answered(tower) == {(0, 0): True, (1, 0): True, (2, 0): True}


async def test_a_pack_the_tower_ignored_does_not_move_the_start(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """The tower still serves the last pack that answered."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding.update(TOWER_HOLDING)
    mock_modbus_unit.holding.update(PACK_HOLDING[0x0000])
    switch_on_selection(
        mock_modbus_unit, {k: v for k, v in PACK_HOLDING.items() if k != 0x0200}
    )
    device = SofarInverter(mock_modbus_unit, serial_number=TOWER_SERIAL)
    await device.async_update_packs()
    writes = selection_writes(mock_modbus_unit)

    await device.async_update_packs()

    assert writes == [0x0200, 0x0000]


async def test_the_layout_is_never_read_again(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_update_packs()
    tower_unit.holding[0x900D] = 0x0401

    await tower.async_update_packs()

    assert tower.battery_tower is not None
    assert tower.battery_tower.parallel_group_count == 3
    assert list(tower.battery_packs) == [(0, 0), (1, 0), (2, 0)]


async def test_a_pack_that_is_not_switched_to_fails_alone(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding.update(TOWER_HOLDING)
    mock_modbus_unit.holding.update(PACK_HOLDING[0x0000])
    switch_on_selection(
        mock_modbus_unit, {k: v for k, v in PACK_HOLDING.items() if k != 0x0100}
    )
    device = SofarInverter(mock_modbus_unit, serial_number=TOWER_SERIAL)

    report = await device.async_update_packs()

    assert report.updated == {BATTERY_PACKS}
    assert report.failed == {}
    assert _answered(device) == {(0, 0): True, (1, 0): False, (2, 0): True}


async def test_a_pack_whose_read_fails_fails_alone(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    def on_write(event: WriteEvent) -> None:
        tower_unit.fail_read(
            0x9048, ServerDeviceFailureError() if event.values[0] == 0x0200 else None
        )

    tower_unit.on_write(on_write)

    assert (await tower.async_update_packs()).updated == {BATTERY_PACKS}
    assert _answered(tower) == {(0, 0): True, (1, 0): True, (2, 0): False}


async def test_no_pack_answering_fails_the_poll_with_its_error(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_ensure_setup()
    tower_unit.fail_read(0x9048, ServerDeviceFailureError())

    report = await tower.async_update_packs()

    assert report.updated == set()
    assert set(report.failed) == {BATTERY_PACKS}
    assert isinstance(report.failed[BATTERY_PACKS], ServerDeviceFailureError)
    assert _answered(tower) == {(0, 0): False, (1, 0): False, (2, 0): False}


async def test_an_offline_group_is_never_selected(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_update_packs()
    tower_unit.holding[0x9022] = 0b101
    writes = selection_writes(tower_unit)

    assert (await tower.async_update_packs()).updated == {BATTERY_PACKS}
    assert 0x0100 not in writes
    assert _answered(tower) == {(0, 0): True, (1, 0): False, (2, 0): True}


async def test_a_tower_with_every_group_offline_fails_the_poll(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    tower_unit.holding[0x9022] = 0
    writes = selection_writes(tower_unit)

    report = await tower.async_update_packs()

    assert set(report.failed) == {BATTERY_PACKS}
    assert type(report.failed[BATTERY_PACKS]) is ModbusError
    assert writes == []


async def test_a_refused_online_bitmap_selects_every_group(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """Firmware older than the bitmap still has its packs checked."""
    tower_unit.fail_read(0x9022, IllegalDataAddressError())

    assert (await tower.async_update_packs()).updated == {BATTERY_PACKS}
    assert _answered(tower) == {(0, 0): True, (1, 0): True, (2, 0): True}


async def test_a_timed_out_online_bitmap_fails_the_poll(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_update_packs()
    error = ModbusTimeoutError("no answer")
    tower_unit.fail_read(0x9022, error)

    assert (await tower.async_update_packs()).failed == {BATTERY_PACKS: error}
    assert _answered(tower) == {(0, 0): False, (1, 0): False, (2, 0): False}


async def test_a_link_dropped_before_the_sweep_propagates(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_ensure_setup()
    tower_unit.fail_requests(ModbusConnectionError("link down"))

    with pytest.raises(ModbusConnectionError):
        await tower.async_update_packs()


async def test_a_link_dropped_mid_sweep_propagates(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_ensure_setup()
    tower_unit.on_write(
        lambda _event: tower_unit.fail_requests(ModbusConnectionError("link down"))
    )

    with pytest.raises(ModbusConnectionError):
        await tower.async_update_packs()


async def test_a_layout_past_the_inquiry_word_is_cut_to_it(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """Group and pack each get four bits of the selection word."""
    tower_unit.holding[0x900D] = 0x1411
    await tower.async_ensure_setup()

    assert len(tower.battery_packs) == 16 * 16
    assert max(tower.battery_packs) == (15, 15)


async def test_only_answered_packs_notify(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    await tower.async_update_packs()
    tower_unit.holding[0x9022] = 0b001
    notified: list[tuple[int, int]] = []
    for place, pack in tower.battery_packs.items():
        pack.add_update_listener(partial(notified.append, place))

    await tower.async_update_packs()

    assert notified == [(0, 0)]


async def test_overlapping_pack_polls_take_turns(
    tower: SofarInverter,
    tower_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every pack shares one selection register."""
    await tower.async_ensure_setup()
    yield_before_reads(monkeypatch, tower_unit)
    writes = selection_writes(tower_unit)

    reports = await asyncio.gather(
        tower.async_update_packs(),
        tower.async_read_pack(pack_nr=0, group_nr=1),
        tower.async_update_packs(),
    )

    assert [r.updated for r in (reports[0], reports[2])] == [{BATTERY_PACKS}] * 2
    assert tower.battery_pack.answered
    assert _answered(tower) == {(0, 0): True, (1, 0): True, (2, 0): True}
    # The second sweep starts at the pack the single read left selected.
    assert writes == [0x0100, 0x0200, 0x0100, 0x0200, 0x0000]


async def test_overlapping_single_pack_reads_keep_their_pack(
    tower: SofarInverter,
    tower_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both reads share ``battery_pack``; each must see its own pack."""
    yield_before_reads(monkeypatch, tower_unit)
    notified: list[tuple[int | None, int | None, bool]] = []
    tower.battery_pack.add_update_listener(
        lambda: notified.append(
            (
                tower.battery_pack.group_nr,
                tower.battery_pack.pack_cycles,
                tower.battery_pack.answered,
            )
        )
    )

    await asyncio.gather(
        tower.async_read_pack(pack_nr=0, group_nr=1),
        tower.async_read_pack(pack_nr=0, group_nr=2),
    )

    assert notified == [(1, 77, True), (2, 78, True)]


async def test_reading_one_pack_names_it(tower: SofarInverter) -> None:
    pack = await tower.async_read_pack(pack_nr=0, group_nr=2)

    assert (pack.group_nr, pack.pack_nr, pack.answered) == (2, 0, True)
    assert pack.pack_cycles == 78
    assert pack is tower.battery_pack


async def test_cell_voltages_are_in_cell_order(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    tower_unit.holding.update({0x9051 + i: 3001 + i for i in range(24)})

    assert (await tower.async_read_pack(pack_nr=0)).cell_voltages == pytest.approx(
        [
            3.001,
            3.002,
            3.003,
            3.004,
            3.005,
            3.006,
            3.007,
            3.008,
            3.009,
            3.010,
            3.011,
            3.012,
            3.013,
            3.014,
            3.015,
            3.016,
            3.017,
            3.018,
            3.019,
            3.020,
            3.021,
            3.022,
            3.023,
            3.024,
        ]
    )


async def test_cell_temperatures_are_in_sensor_order(
    tower: SofarInverter, tower_unit: MockModbusUnit
) -> None:
    """The MOS and environment sensors that follow are not cells."""
    tower_unit.holding.update(
        {0x906B: 211, 0x906C: 222, 0x906D: 233, 0x906E: 0x10000 - 15, 0x906F: 999}
    )

    assert (await tower.async_read_pack(pack_nr=0)).cell_temperatures == pytest.approx(
        (21.1, 22.2, 23.3, -1.5)
    )


def test_an_unread_pack_has_no_cell_values(tower: SofarInverter) -> None:
    assert tower.battery_pack.cell_voltages == (None,) * 24
    assert tower.battery_pack.cell_temperatures == (None,) * 4
