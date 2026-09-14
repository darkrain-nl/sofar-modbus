"""What the device objects ask the link for, and what they measure of it."""

from __future__ import annotations

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusTimeoutError,
    ModbusUnit,
)
from modbus_connection.mock import MockModbusUnit
from modbus_connection.model import UpdateReport

from sofar_modbus import SofarInverter, SofarLegacyInverter
from sofar_modbus.tuning import (
    CLEAN_POLLS,
    FLOOR,
    LinkTuner,
    LinkTuning,
    TimedUnit,
    target_timeout,
)

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


async def _poll(inverter: SofarInverter, tuner: LinkTuner) -> None:
    """One clean poll, observed the way a coordinator would."""
    tuner.observe(await inverter.async_update())


def _timed_out() -> UpdateReport:
    return UpdateReport({"grid"}, {"state": ModbusTimeoutError("no answer")})


@pytest.fixture
def tuned(mock_modbus_unit: MockModbusUnit) -> tuple[SofarInverter, LinkTuner]:
    """An inverter polling through a timed unit, with a tuner watching."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    timed = TimedUnit(mock_modbus_unit)
    return SofarInverter(timed, read_pm=True), LinkTuner(timed)


def test_a_target_leaves_room_over_the_slowest_answer() -> None:
    assert target_timeout(0.4) == pytest.approx(1.6)


def test_a_quick_link_still_gets_the_floor() -> None:
    """Four times nothing is not a timeout to hold a device to."""
    assert target_timeout(0.01) == FLOOR


def test_a_slow_link_is_left_its_own_default() -> None:
    assert target_timeout(3.0) is None
    assert target_timeout(None) is None


async def test_nothing_is_asked_until_the_link_has_been_quiet(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    inverter, tuner = tuned
    for _ in range(CLEAN_POLLS - 1):
        await _poll(inverter, tuner)

    assert tuner.tuning.timeout is None
    assert mock_modbus_unit.required_timeout is None


async def test_a_quiet_link_is_asked_for_what_it_measured(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    inverter, tuner = tuned
    for _ in range(CLEAN_POLLS):
        await _poll(inverter, tuner)

    assert tuner.tuning.timeout == FLOOR  # the mock answers instantly
    assert mock_modbus_unit.required_timeout == FLOOR


async def test_a_timeout_hands_the_link_back_its_own(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    inverter, tuner = tuned
    for _ in range(CLEAN_POLLS):
        await _poll(inverter, tuner)
    tuner.observe(_timed_out())

    assert tuner.tuning == LinkTuning(timeout=None, withdrawals=1)
    assert mock_modbus_unit.required_timeout is None


async def test_a_withdrawal_makes_the_next_attempt_wait_longer(
    tuned: tuple[SofarInverter, LinkTuner],
) -> None:
    inverter, tuner = tuned
    for _ in range(CLEAN_POLLS):
        await _poll(inverter, tuner)
    tuner.observe(_timed_out())
    for _ in range(CLEAN_POLLS):
        await _poll(inverter, tuner)

    assert tuner.tuning.timeout is None  # five clean polls no longer earn it
    for _ in range(CLEAN_POLLS):
        await _poll(inverter, tuner)
    assert tuner.tuning.timeout == FLOOR


async def test_a_timeout_the_tuner_did_not_cause_is_not_its_own(
    tuned: tuple[SofarInverter, LinkTuner],
) -> None:
    """Nothing was asked, so the device timing out says nothing about us."""
    inverter, tuner = tuned
    tuner.observe(_timed_out())
    for _ in range(CLEAN_POLLS):
        await _poll(inverter, tuner)

    assert tuner.tuning == LinkTuning(timeout=FLOOR, withdrawals=0)


async def test_a_refused_register_is_not_a_slow_link(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """An inverter answering "no such register" answered, and quickly."""
    inverter, tuner = tuned
    for _ in range(CLEAN_POLLS - 1):
        await _poll(inverter, tuner)
    tuner.observe(UpdateReport({"grid"}, {"eps": IllegalDataAddressError()}))

    assert mock_modbus_unit.required_timeout == FLOOR
