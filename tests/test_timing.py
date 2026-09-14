"""What the device objects ask the link for, and what they measure of it."""

from __future__ import annotations

import pytest
from modbus_connection import ModbusTimeoutError, ModbusUnit
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter, SofarLegacyInverter
from sofar_modbus.tuning import TimedUnit

from .conftest import MODERN_HOLDING

Inverter = type[SofarInverter] | type[SofarLegacyInverter]

INVERTERS = (SofarInverter, SofarLegacyInverter)


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_an_inverter_requires_nothing_of_the_link_by_itself(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Guessing a timeout for an unmeasured link is what this avoids."""
    inverter_class(mock_modbus_unit)
    assert mock_modbus_unit.required_timeout is None


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_a_caller_that_knows_its_link_states_the_timeout(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    inverter_class(mock_modbus_unit, timeout=2.5)
    assert mock_modbus_unit.required_timeout == 2.5


def test_a_timed_unit_is_a_unit(mock_modbus_unit: MockModbusUnit) -> None:
    """Components take whatever satisfies the protocol, wrapper included."""
    assert isinstance(TimedUnit(mock_modbus_unit), ModbusUnit)


def test_nothing_is_measured_before_the_first_request(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    stats = TimedUnit(mock_modbus_unit).stats
    assert (stats.requests, stats.answered, stats.failures) == (0, 0, {})
    assert (stats.median, stats.p95, stats.slowest) == (None, None, None)


async def test_every_answered_read_is_counted_and_timed(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding[0x0404] = 2
    timed = TimedUnit(mock_modbus_unit)
    for _ in range(3):
        await timed.read_holding_registers(0x0404, 1)

    stats = timed.stats
    assert timed.reads == 3
    assert (stats.requests, stats.answered, stats.failures) == (3, 3, {})
    assert stats.median is not None and stats.median >= 0
    assert stats.slowest is not None and stats.slowest >= stats.median


async def test_a_refused_read_is_recorded_under_its_error_and_still_raises(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding[0x0404] = 2
    mock_modbus_unit.fail_read(0x0480, ModbusTimeoutError("no answer"))
    timed = TimedUnit(mock_modbus_unit)
    await timed.read_holding_registers(0x0404, 1)
    with pytest.raises(ModbusTimeoutError):
        await timed.read_holding_registers(0x0480, 1)

    stats = timed.stats
    assert stats.failures == {"ModbusTimeoutError": 1}
    assert (stats.requests, stats.answered) == (2, 1)


async def test_the_window_keeps_only_the_last_requests(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A long-running poller must not grow a sample list forever."""
    mock_modbus_unit.holding[0x0404] = 2
    timed = TimedUnit(mock_modbus_unit, window=4)
    for _ in range(10):
        await timed.read_holding_registers(0x0404, 1)

    assert timed.stats.requests == 4
    assert timed.reads == 10  # the count is of the whole run, not the window


async def test_an_inverter_polls_through_the_wrapper(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    timed = TimedUnit(mock_modbus_unit)
    inverter = SofarInverter(timed, read_pm=True)
    report = await inverter.async_update()

    assert report.complete
    assert timed.stats.answered == timed.reads > 0


def test_link_settings_reach_the_wrapped_unit(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    timed = TimedUnit(mock_modbus_unit)
    timed.set_message_spacing(0.05)
    timed.require_timeout(3.0)
    timed.require_connect_delay(1.0)

    assert mock_modbus_unit.message_spacing == 0.05
    assert mock_modbus_unit.required_timeout == 3.0
    assert mock_modbus_unit.required_connect_delay == 1.0
