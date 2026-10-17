"""The historical event log: decoding, ordering and setup-time checks."""

from __future__ import annotations

import logging
from datetime import datetime

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter
from sofar_modbus.modern import FAULTS_BY_ID, FaultLogEntry

from .conftest import MODERN_HOLDING

LOG = 0x1480

# The newest 10 entries of the maintainer's 4.4 KTLX-G3, 2026-10-17.
KTLX_G3_LOG = [
    *(0x0003, 0x1A0A, 0x1011, 0x0F1F),
    *(0x0003, 0x1A0A, 0x0911, 0x0117),
    *(0x0003, 0x190B, 0x0111, 0x013A),
    *(0x0052, 0x1907, 0x040C, 0x0037),
    *(0x0001, 0x1905, 0x0D0D, 0x2C3B),
    *(0x0001, 0x1905, 0x0D0D, 0x192D),
    *(0x0001, 0x1905, 0x0D0C, 0x1338),
    *(0x0001, 0x1905, 0x0D0B, 0x2337),
    *(0x0003, 0x1905, 0x0606, 0x0020),
    *(0x0001, 0x1903, 0x0C0D, 0x0813),
]


def _entry(fault_id: int, *when: int) -> FaultLogEntry:
    year, month, day, hour, minute, second = when
    return FaultLogEntry(
        FAULTS_BY_ID[fault_id], datetime(year, month, day, hour, minute, second)
    )


@pytest.fixture
def ktlx(mock_modbus_unit: MockModbusUnit) -> SofarInverter:
    """A three-phase PV inverter whose log reads as the hardware's."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    mock_modbus_unit.holding[LOG] = KTLX_G3_LOG
    return SofarInverter(mock_modbus_unit, serial_number="SS2ES104N5S445")


async def test_the_hardware_log_decodes_newest_first(ktlx: SofarInverter) -> None:
    await ktlx.async_update()
    assert ktlx.fault_log.entries == (
        _entry(3, 2026, 10, 16, 17, 15, 31),
        _entry(3, 2026, 10, 9, 17, 1, 23),
        _entry(3, 2025, 11, 1, 17, 1, 58),
        _entry(82, 2025, 7, 4, 12, 0, 55),
        _entry(1, 2025, 5, 13, 13, 44, 59),
        _entry(1, 2025, 5, 13, 13, 25, 45),
        _entry(1, 2025, 5, 13, 12, 19, 56),
        _entry(1, 2025, 5, 13, 11, 35, 55),
        _entry(3, 2025, 5, 6, 6, 0, 32),
        _entry(1, 2025, 3, 12, 13, 8, 19),
    )


async def test_the_log_is_one_forty_register_read(
    ktlx: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """The spec only returns a whole entry when its four words share a read."""
    await ktlx.async_update()
    mock_modbus_unit.read_events.clear()
    await ktlx.async_update_readings()
    assert [
        (event.address, event.count)
        for event in mock_modbus_unit.read_events
        if event.address >= LOG
    ] == [(LOG, 40)]


async def test_entries_are_empty_before_the_first_read(ktlx: SofarInverter) -> None:
    assert ktlx.fault_log.entries == ()


async def test_an_empty_log_keeps_the_component(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Unused slots read as zeros on the KTLX-G3; no faults yet is no reason."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(mock_modbus_unit, serial_number="SS2ES104N5S445")
    await inverter.async_update()
    assert "fault_log" in inverter.readings_components
    assert inverter.fault_log.entries == ()


async def test_an_unknown_id_is_skipped_but_keeps_the_log(
    ktlx: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A newer firmware may log ids the table lacks; the log is still real."""
    # ID056 replaces the newest entry.
    mock_modbus_unit.holding[LOG] = [0x0038, 0x1A0A, 0x1112, 0, *KTLX_G3_LOG[4:]]
    await ktlx.async_update()
    assert "fault_log" in ktlx.readings_components
    assert ktlx.fault_log.entries[0] == _entry(3, 2026, 10, 9, 17, 1, 23)
    assert len(ktlx.fault_log.entries) == 9


async def test_a_bad_date_is_skipped_after_setup(
    ktlx: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await ktlx.async_update()
    # Month 13 replaces the newest entry.
    mock_modbus_unit.holding[LOG] = [0x0002, 0x1A0D, 0x1112, 0, *KTLX_G3_LOG[4:]]
    await ktlx.async_update_readings()
    assert ktlx.fault_log.entries[0] == _entry(3, 2026, 10, 9, 17, 1, 23)
    assert len(ktlx.fault_log.entries) == 9


async def test_a_later_read_moves_the_log_down(
    ktlx: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await ktlx.async_update()
    mock_modbus_unit.holding[LOG] = [0x0002, 0x1A0A, 0x1112, 0x0000, *KTLX_G3_LOG[:36]]
    await ktlx.async_update_readings()
    entries = ktlx.fault_log.entries
    assert entries[0] == _entry(2, 2026, 10, 17, 18, 0, 0)
    assert entries[1] == _entry(3, 2026, 10, 16, 17, 15, 31)
    assert len(entries) == 10


@pytest.mark.parametrize(
    "error",
    [ModbusTimeoutError("no such block"), IllegalDataAddressError()],
)
async def test_setup_drops_a_log_that_does_not_answer(
    ktlx: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    mock_modbus_unit.fail_read(LOG, error)
    report = await ktlx.async_update()
    assert "fault_log" not in ktlx.readings_components
    assert "fault_log" not in ktlx.expected_components
    assert not report.failed
    assert any(
        message.startswith("Inverter SS2ES104N5S445: the event log does not answer")
        and message.endswith("dropping fault_log")
        for message in caplog.messages
    )


async def test_setup_drops_a_log_that_reads_as_junk(
    ktlx: SofarInverter,
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A valid first slot does not vouch for junk further down."""
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    # What the battery totals block reads on a KTLX-G3 without one.
    mock_modbus_unit.holding[LOG + 36] = [2, 2, 0, 47954]
    await ktlx.async_update()
    assert "fault_log" not in ktlx.readings_components
    assert (
        "Inverter SS2ES104N5S445: the event log reads as junk, dropping fault_log"
        in caplog.messages
    )


async def test_setup_raises_on_a_dead_link(
    ktlx: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.fail_read(LOG, ModbusConnectionError("gone"))
    with pytest.raises(ModbusConnectionError):
        await ktlx.async_ensure_setup()


async def test_a_failed_poll_fails_the_log_alone(
    ktlx: SofarInverter, mock_modbus_unit: MockModbusUnit
) -> None:
    await ktlx.async_update()
    mock_modbus_unit.fail_read(LOG, ModbusTimeoutError("busy"))
    report = await ktlx.async_update_readings()
    assert set(report.failed) == {"fault_log"}
    assert "fault_log" in ktlx.readings_components
    assert ktlx.fault_log.entries[0] == _entry(3, 2026, 10, 16, 17, 15, 31)
