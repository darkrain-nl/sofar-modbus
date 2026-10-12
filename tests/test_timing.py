"""What the device objects ask the link for, and what they measure of it."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from unittest.mock import patch

import pytest
from modbus_connection import (
    ModbusConnectionError,
    ModbusDesyncError,
    ModbusError,
    ModbusTimeoutError,
    ModbusUnit,
    ServerDeviceBusyError,
)
from modbus_connection.mock import MockModbusUnit
from modbus_connection.model import UpdateReport

from sofar_modbus import SofarInverter, SofarLegacyInverter
from sofar_modbus.tuning import (
    CONNECT_DELAYS,
    CROWDED_POLLS,
    FAILED_OPENS,
    QUIET_POLLS,
    SPACING_STEPS,
    LinkTuner,
    LinkTuning,
    TimedUnit,
)

from .conftest import HYBRID_SERIAL, MODERN_HOLDING, fail_then

Inverter = type[SofarInverter] | type[SofarLegacyInverter]

INVERTERS = (SofarInverter, SofarLegacyInverter)


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_an_inverter_requires_nothing_of_the_link_by_itself(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """Guessing a timeout for an unmeasured link is what this avoids."""
    inverter_class(mock_modbus_unit, serial_number=HYBRID_SERIAL)
    assert mock_modbus_unit.required_timeout is None


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_a_caller_that_knows_its_link_states_the_timeout(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    inverter_class(mock_modbus_unit, serial_number=HYBRID_SERIAL, timeout=2.5)
    assert mock_modbus_unit.required_timeout == 2.5


@pytest.mark.parametrize("inverter_class", INVERTERS)
async def test_detection_states_the_timeout_before_it_reads(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.fail_requests(ModbusTimeoutError("asleep"))
    with pytest.raises(ModbusTimeoutError):
        await inverter_class.async_detect(mock_modbus_unit, timeout=2.5)
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


async def test_an_inverter_times_its_own_requests(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(
        mock_modbus_unit, serial_number=HYBRID_SERIAL, read_pm=True
    )
    report = await inverter.async_update()

    assert report.complete
    stats = inverter.link_stats
    assert stats.answered == stats.requests == len(mock_modbus_unit.read_events)
    assert stats.requests > 0


async def test_an_inverter_reports_whether_its_link_is_open(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(mock_modbus_unit, serial_number=HYBRID_SERIAL)
    await inverter.async_update()
    assert inverter.connected

    await mock_modbus_unit.disconnect()
    assert not inverter.connected


def test_an_inverter_starts_untuned(mock_modbus_unit: MockModbusUnit) -> None:
    inverter = SofarInverter(mock_modbus_unit, serial_number=HYBRID_SERIAL)
    assert inverter.link_tuning == LinkTuning()


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


def _timed_out() -> UpdateReport:
    return UpdateReport({"grid"}, {"state": ModbusTimeoutError("no answer")})


@pytest.fixture
def tuned(mock_modbus_unit: MockModbusUnit) -> tuple[SofarInverter, LinkTuner]:
    """An inverter and the tuner its own polls report to."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    inverter = SofarInverter(
        mock_modbus_unit, serial_number=HYBRID_SERIAL, read_pm=True
    )
    return inverter, inverter._tuner


async def test_the_tuner_leaves_the_timeout_alone(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """Asking for less would undercut any unit sharing the link."""
    inverter, tuner = tuned
    for _ in range(QUIET_POLLS):
        await inverter.async_update()
    tuner.observe(_timed_out())
    tuner.observe_failure(ModbusTimeoutError("asleep"))

    assert mock_modbus_unit.required_timeout is None
    assert (tuner.tuning.timeout, tuner.tuning.withdrawals) == (None, 0)


def _desynced() -> UpdateReport:
    return UpdateReport({"grid"}, {"state": ModbusDesyncError("wrong reply")})


def _busy() -> UpdateReport:
    return UpdateReport({"grid"}, {"state": ServerDeviceBusyError()})


async def test_a_desynced_poll_widens_the_gap_by_itself(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """No caller has to hand the inverter its own report."""
    inverter, _ = tuned
    await inverter.async_update()
    mock_modbus_unit.fail_read(0x0484, ModbusDesyncError("wrong reply"))
    await inverter.async_update_readings()

    assert inverter.link_tuning.spacing == SPACING_STEPS[0]
    assert mock_modbus_unit.message_spacing == SPACING_STEPS[0]


SLOW = ModbusTimeoutError("slow")
BUSY = ServerDeviceBusyError()


@pytest.mark.parametrize(
    ("first", "retry", "heard"),
    [
        pytest.param(SLOW, BUSY, SLOW, id="timeout_then_busy"),
        pytest.param(BUSY, SLOW, SLOW, id="busy_then_timeout"),
        pytest.param(SLOW, None, SLOW, id="the_retry_recovered"),
        pytest.param(BUSY, None, BUSY, id="busy_then_recovered"),
    ],
)
async def test_the_tuner_hears_a_timeout_either_attempt_hit(
    tuned: tuple[SofarInverter, LinkTuner],
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    first: ModbusError,
    retry: ModbusError | None,
    heard: ModbusError,
) -> None:
    """A timeout healed by the retry still says the line is struggling."""
    inverter, tuner = tuned
    await inverter.async_update()
    fail_then(monkeypatch, mock_modbus_unit, 0x0484, first, retry)

    with patch.object(tuner, "observe") as observe:
        await inverter.async_update_readings()

    observe.assert_called_once()
    heard_report = observe.call_args.args[0]
    assert {name: type(err) for name, err in heard_report.failed.items()} == {
        "grid": type(heard)
    }
    assert "state" in heard_report.updated


async def test_only_the_retry_timing_out_reaches_the_tuner(
    tuned: tuple[SofarInverter, LinkTuner],
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inverter, tuner = tuned
    await inverter.async_update()
    fail_then(monkeypatch, mock_modbus_unit, 0x0484, BUSY, SLOW)

    with patch.object(tuner, "observe") as observe:
        report = await inverter.async_update_readings()

    assert report.failed == {"grid": SLOW}
    assert observe.call_args.args[0].failed == {"grid": SLOW}


async def test_a_desync_widens_the_gap_on_the_spot(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """A reply to another exchange is the one unambiguous sign of crowding."""
    inverter, tuner = tuned
    await inverter.async_update()
    tuner.observe(_desynced())

    assert tuner.tuning.spacing == SPACING_STEPS[0]
    assert mock_modbus_unit.message_spacing == SPACING_STEPS[0]


async def test_a_busy_device_has_to_say_so_more_than_once(
    tuned: tuple[SofarInverter, LinkTuner],
) -> None:
    inverter, tuner = tuned
    await inverter.async_update()
    for _ in range(CROWDED_POLLS - 1):
        tuner.observe(_busy())
    assert tuner.tuning.spacing == 0.0

    tuner.observe(_busy())
    assert tuner.tuning.spacing == SPACING_STEPS[0]


async def test_a_register_the_model_never_served_is_not_crowding(
    tuned: tuple[SofarInverter, LinkTuner],
) -> None:
    """Chasing an absent register would widen the gap forever."""
    _, tuner = tuned
    for _ in range(CROWDED_POLLS + 2):
        tuner.observe(UpdateReport({"grid"}, {"eps": ModbusTimeoutError("silent")}))

    assert tuner.tuning.spacing == 0.0


async def test_a_component_that_did_answer_going_quiet_is_crowding(
    tuned: tuple[SofarInverter, LinkTuner],
) -> None:
    _, tuner = tuned
    tuner.observe(UpdateReport({"state"}, {}))
    for _ in range(CROWDED_POLLS):
        tuner.observe(UpdateReport({"grid"}, {"state": ModbusTimeoutError("silent")}))

    assert tuner.tuning.spacing == SPACING_STEPS[0]


async def test_the_budget_caps_how_wide_a_poll_may_get(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """Thirty reads at fifty milliseconds would cost more than the budget."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    timed = TimedUnit(mock_modbus_unit)
    inverter = SofarInverter(timed, serial_number=HYBRID_SERIAL, read_pm=True)
    tuner = LinkTuner(timed, budget=1.0)
    tuner.observe(await inverter.async_update())

    for _ in range(3):
        tuner.observe(_desynced())

    # A second of budget over this many reads caps the gap under 30 ms, so
    # the step the ladder would take next does not fit.
    assert timed.reads > 33
    assert tuner.tuning.spacing == 0.02


async def test_a_wider_budget_lets_the_ladder_climb(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """The same three desyncs, with room to answer them."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    timed = TimedUnit(mock_modbus_unit)
    inverter = SofarInverter(timed, serial_number=HYBRID_SERIAL, read_pm=True)
    tuner = LinkTuner(timed, budget=10.0)
    tuner.observe(await inverter.async_update())

    for _ in range(3):
        tuner.observe(_desynced())

    assert tuner.tuning.spacing == SPACING_STEPS[2]


async def test_a_quiet_line_gets_a_step_back(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    inverter, tuner = tuned
    await inverter.async_update()
    tuner.observe(_desynced())
    widened = tuner.tuning.spacing

    for _ in range(QUIET_POLLS * 2):
        await inverter.async_update()

    assert widened == SPACING_STEPS[0]
    assert tuner.tuning.spacing == 0.0
    assert mock_modbus_unit.message_spacing == 0.0


async def test_widening_buys_patience_before_the_next_narrowing(
    tuned: tuple[SofarInverter, LinkTuner],
) -> None:
    """A line that crowded once is not asked the same question as often."""
    inverter, tuner = tuned
    await inverter.async_update()
    tuner.observe(_desynced())

    for _ in range(QUIET_POLLS):
        await inverter.async_update()

    assert tuner.tuning.spacing == SPACING_STEPS[0]


async def test_a_request_that_opens_the_link_is_marked_as_one(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.holding[0x0404] = 2
    timed = TimedUnit(mock_modbus_unit)
    await timed.read_holding_registers(0x0404, 1)
    await timed.read_holding_registers(0x0404, 1)

    assert (timed.opens, timed.failed_opens) == (1, 0)


async def test_an_opening_request_that_goes_unanswered_is_counted(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    mock_modbus_unit.fail_read(0x0404, ModbusTimeoutError("not ready yet"))
    timed = TimedUnit(mock_modbus_unit)
    with pytest.raises(ModbusTimeoutError):
        await timed.read_holding_registers(0x0404, 1)

    assert (timed.opens, timed.failed_opens) == (1, 1)


async def test_a_device_that_answers_no_opening_request_earns_a_pause(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    inverter, tuner = tuned
    mock_modbus_unit.fail_read(0x0404, ModbusTimeoutError("not ready yet"))
    for _ in range(FAILED_OPENS):
        with pytest.raises(ModbusTimeoutError):
            await inverter.state.async_update()
        await mock_modbus_unit.disconnect()
    tuner.observe(UpdateReport({"grid"}, {}))

    assert tuner.tuning.connect_delay == CONNECT_DELAYS[0]
    assert mock_modbus_unit.required_connect_delay == CONNECT_DELAYS[0]


async def test_one_bad_open_among_good_ones_is_not_a_pattern(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """A link that opens cleanly in between was never the problem."""
    inverter, tuner = tuned

    async def open_and_read(answering: bool) -> None:
        await mock_modbus_unit.disconnect()
        failure = None if answering else ModbusTimeoutError("not ready yet")
        mock_modbus_unit.fail_read(0x0404, failure)
        if answering:
            await inverter.state.async_update()
        else:
            with pytest.raises(ModbusTimeoutError):
                await inverter.state.async_update()
        tuner.observe(UpdateReport({"grid"}, {}))

    await open_and_read(answering=False)
    await open_and_read(answering=True)
    await open_and_read(answering=False)

    assert tuner.tuning.connect_delay == 0.0


async def test_what_a_run_settled_on_comes_back(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    timed = TimedUnit(mock_modbus_unit)
    settled = LinkTuning(spacing=0.05, connect_delay=0.5)
    LinkTuner(timed).restore(settled)

    assert mock_modbus_unit.message_spacing == 0.05
    assert mock_modbus_unit.required_connect_delay == 0.5


async def test_a_raised_poll_still_feeds_the_connect_delay_ladder(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """The reads happened, so what they say about opening the link stands."""
    inverter, _ = tuned
    mock_modbus_unit.fail_requests(ModbusTimeoutError("not ready yet"))
    for _ in range(FAILED_OPENS):
        await mock_modbus_unit.disconnect()
        with pytest.raises(ModbusTimeoutError):
            await inverter.async_update_readings()

    assert inverter.link_tuning.connect_delay == CONNECT_DELAYS[0]
    assert mock_modbus_unit.required_connect_delay == CONNECT_DELAYS[0]


async def test_a_raised_poll_is_not_a_quiet_one(
    tuned: tuple[SofarInverter, LinkTuner], mock_modbus_unit: MockModbusUnit
) -> None:
    """Or a link too broken to poll would earn a narrower gap by failing."""
    inverter, tuner = tuned
    await inverter.async_update()
    tuner.observe(_desynced())
    widened = tuner.tuning.spacing

    for _ in range(QUIET_POLLS * 2):
        tuner.observe_failure(ModbusConnectionError("link down"))

    assert widened == SPACING_STEPS[0]
    assert tuner.tuning.spacing == widened
    assert mock_modbus_unit.message_spacing == widened


# --- what the tuner logs ---------------------------------------------


def _logged(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "sofar_modbus.tuning"]


@pytest.mark.parametrize(
    ("crowding", "polls", "reason"),
    [
        (_desynced, 1, "a reply desynced"),
        (_busy, CROWDED_POLLS, "the line is crowded"),
    ],
)
async def test_widening_logs_what_crowded_the_line(
    tuned: tuple[SofarInverter, LinkTuner],
    caplog: pytest.LogCaptureFixture,
    crowding: Callable[[], UpdateReport],
    polls: int,
    reason: str,
) -> None:
    inverter, tuner = tuned
    await inverter.async_update()
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    for _ in range(polls):
        tuner.observe(crowding())

    assert _logged(caplog) == [f"Widening the frame gap to 0.02 s: {reason}"]


async def test_narrowing_is_logged(
    tuned: tuple[SofarInverter, LinkTuner], caplog: pytest.LogCaptureFixture
) -> None:
    inverter, tuner = tuned
    await inverter.async_update()
    tuner.observe(_desynced())
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    for _ in range(QUIET_POLLS * 2):
        await inverter.async_update()

    narrowed = [m for m in _logged(caplog) if m.startswith("Narrowing")]
    assert narrowed == ["Narrowing the frame gap to 0.0 s after 40 quiet polls"]


async def test_a_gap_the_budget_caps_is_logged(
    mock_modbus_unit: MockModbusUnit, caplog: pytest.LogCaptureFixture
) -> None:
    """A line that stays crowded at the cap is worth seeing in a log."""
    mock_modbus_unit.holding.update(MODERN_HOLDING)
    timed = TimedUnit(mock_modbus_unit)
    inverter = SofarInverter(timed, serial_number=HYBRID_SERIAL, read_pm=True)
    tuner = LinkTuner(timed, budget=1.0)
    tuner.observe(await inverter.async_update())
    tuner.observe(_desynced())
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    tuner.observe(_desynced())

    (capped,) = _logged(caplog)
    assert re.fullmatch(
        r"Not widening the 0\.02 s frame gap \(a reply desynced\): "
        r"the budget caps it at 0\.02\d s",
        capped,
    )


async def _fail_opens(
    inverter: SofarInverter, tuner: LinkTuner, unit: MockModbusUnit
) -> None:
    """Enough unanswered opens to move the connect delay one step."""
    unit.fail_read(0x0404, ModbusTimeoutError("not ready yet"))
    for _ in range(FAILED_OPENS):
        with pytest.raises(ModbusTimeoutError):
            await inverter.state.async_update()
        await unit.disconnect()
    tuner.observe(UpdateReport({"grid"}, {}))


async def test_a_connect_delay_is_logged(
    tuned: tuple[SofarInverter, LinkTuner],
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    inverter, tuner = tuned
    await _fail_opens(inverter, tuner, mock_modbus_unit)

    assert _logged(caplog) == [
        "Pausing 0.25 s after the link opens: 2 opening requests went unanswered"
    ]


async def test_the_longest_connect_delay_is_logged_as_kept(
    tuned: tuple[SofarInverter, LinkTuner],
    mock_modbus_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    inverter, tuner = tuned
    tuner.restore(LinkTuning(connect_delay=CONNECT_DELAYS[-1]))
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    await _fail_opens(inverter, tuner, mock_modbus_unit)

    assert _logged(caplog) == [
        "Not lengthening the 2.0 s connect delay (2 unanswered opens): "
        "it is the longest"
    ]


def test_a_restore_is_logged(
    mock_modbus_unit: MockModbusUnit, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="sofar_modbus")
    settled = LinkTuning(spacing=0.05, connect_delay=0.5)
    LinkTuner(TimedUnit(mock_modbus_unit)).restore(settled)

    assert _logged(caplog) == [
        "Restoring LinkTuning(spacing=0.05, connect_delay=0.5, timeout=None, "
        "withdrawals=0)"
    ]
