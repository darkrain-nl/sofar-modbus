"""Measure a link through a device's unit, and ask it for what it needs."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

from modbus_connection import (
    ModbusDesyncError,
    ModbusError,
    ModbusTimeoutError,
    ServerDeviceBusyError,
)

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit
    from modbus_connection.model import UpdateReport

WINDOW = 200
"""Requests kept for the statistics, roughly twenty polls of an inverter."""


@dataclass(frozen=True)
class LinkStats:
    """How the requests still in the window went."""

    requests: int
    answered: int
    failures: dict[str, int]
    median: float | None
    p95: float | None
    slowest: float | None


class TimedUnit:
    """Wrap a ``ModbusUnit``, timing every request that reaches the wire.

    A unit is all a library holds, so its own traffic is all it sees.
    """

    def __init__(self, unit: ModbusUnit, window: int = WINDOW) -> None:
        self._unit = unit
        self._samples: deque[tuple[float, str | None]] = deque(maxlen=window)
        self.reads = 0
        self.opens = 0
        self.failed_opens = 0

    @property
    def stats(self) -> LinkStats:
        """The window's latency and failures, both empty before the first read."""
        answered = sorted(seconds for seconds, failed in self._samples if not failed)
        failures: dict[str, int] = {}
        for _, failed in self._samples:
            if failed:
                failures[failed] = failures.get(failed, 0) + 1
        return LinkStats(
            requests=len(self._samples),
            answered=len(answered),
            failures=failures,
            median=median(answered) if answered else None,
            p95=_percentile(answered, 0.95),
            slowest=answered[-1] if answered else None,
        )

    async def _timed[T](self, request: Awaitable[T]) -> T:
        """Await one request, recording how long it took and how it ended.

        One made while the link is down opens it, and pays for that.
        """
        opening = not self._unit.connected
        self.opens += opening
        started = time.monotonic()
        try:
            answer = await request
        except ModbusError as err:
            self.failed_opens += opening
            self._samples.append((time.monotonic() - started, type(err).__name__))
            raise
        self._samples.append((time.monotonic() - started, None))
        return answer

    @property
    def connected(self) -> bool:
        return self._unit.connected

    # -- timed block reads --------------------------------------------

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        self.reads += 1
        return await self._timed(self._unit.read_holding_registers(address, count))

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        self.reads += 1
        return await self._timed(self._unit.read_input_registers(address, count))

    async def read_coils(self, address: int, count: int) -> list[bool]:
        self.reads += 1
        return await self._timed(self._unit.read_coils(address, count))

    async def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        self.reads += 1
        return await self._timed(self._unit.read_discrete_inputs(address, count))

    # -- other wire traffic, timed but not counted as a block read -----

    async def write_register(self, address: int, value: int) -> None:
        await self._timed(self._unit.write_register(address, value))

    async def write_registers(self, address: int, values: list[int]) -> None:
        await self._timed(self._unit.write_registers(address, values))

    async def write_coil(self, address: int, value: bool) -> None:
        await self._timed(self._unit.write_coil(address, value))

    async def write_coils(self, address: int, values: list[bool]) -> None:
        await self._timed(self._unit.write_coils(address, values))

    async def read_exception_status(self) -> int:
        return await self._timed(self._unit.read_exception_status())

    async def report_server_id(self) -> bytes:
        return await self._timed(self._unit.report_server_id())

    async def mask_write_register(
        self, address: int, and_mask: int, or_mask: int
    ) -> None:
        await self._timed(self._unit.mask_write_register(address, and_mask, or_mask))

    async def read_write_registers(
        self,
        read_address: int,
        read_count: int,
        write_address: int,
        write_values: list[int],
    ) -> list[int]:
        return await self._timed(
            self._unit.read_write_registers(
                read_address, read_count, write_address, write_values
            )
        )

    async def read_fifo_queue(self, address: int) -> list[int]:
        return await self._timed(self._unit.read_fifo_queue(address))

    async def read_device_identification(self) -> dict[int, bytes]:
        return await self._timed(self._unit.read_device_identification())

    async def read_file_record(self, file: int, record: int, length: int) -> list[int]:
        return await self._timed(self._unit.read_file_record(file, record, length))

    async def write_file_record(
        self, file: int, record: int, values: list[int]
    ) -> None:
        await self._timed(self._unit.write_file_record(file, record, values))

    async def diagnostics(self, sub_function: int, data: int = 0) -> int:
        return await self._timed(self._unit.diagnostics(sub_function, data))

    async def get_comm_event_counter(self) -> tuple[bool, int]:
        return await self._timed(self._unit.get_comm_event_counter())

    async def get_comm_event_log(self) -> bytes:
        return await self._timed(self._unit.get_comm_event_log())

    # -- link settings, which cost no request --------------------------

    def set_message_spacing(self, seconds: float) -> None:
        self._unit.set_message_spacing(seconds)

    def require_timeout(self, seconds: float | None) -> None:
        self._unit.require_timeout(seconds)

    def require_connect_delay(self, seconds: float | None) -> None:
        self._unit.require_connect_delay(seconds)

    def on_connection_lost(self, callback: Callable[[], None]) -> Callable[[], None]:
        return self._unit.on_connection_lost(callback)

    async def disconnect(self) -> None:
        await self._unit.disconnect()


def _percentile(answered: list[float], fraction: float) -> float | None:
    """The value at ``fraction`` of a sorted run, by nearest rank."""
    if not answered:
        return None
    return answered[min(len(answered) - 1, int(len(answered) * fraction))]


MARGIN = 4.0
"""Headroom over the slowest request that answered.

The slowest, not a percentile: a gateway that caches blocks answers most
reads in about a millisecond and a real fetch in hundreds, so a median
describes the cache rather than the device behind it.
"""

FLOOR = 0.5
"""The shortest timeout worth asking for, whatever the window says."""

MAX_ASK = 10.0
"""The link's own default: asking for this or more would change nothing."""

MIN_ANSWERED = 20
"""Answered requests before the window says anything about the link."""

CLEAN_POLLS = 5
"""Polls without a timeout before the tuner acts on what it measured."""

MAX_CLEAN_POLLS = 80
"""The longest wait a link that keeps timing out is made to serve."""

WORTH_ASKING = 0.75
"""A new target is only asked for below this much of the standing one."""

SPACING_STEPS = (0.02, 0.03, 0.05, 0.1, 0.2)
"""Gaps to try between this unit's own frames, narrowest first.

30 ms is what Home Assistant's YAML modbus integration has long given a
serial line by default, and nothing at all to a TCP one, so the ladder
steps through it rather than starting there.
"""

BUDGET = 1.0
"""Seconds of gap a poll may grow by, which caps how wide a step gets."""

CROWDED_POLLS = 3
"""Polls carrying a crowded line before widening; a desync needs one."""

QUIET_POLLS = 20
"""Polls without a sign of crowding before trying one step narrower."""

MAX_QUIET_POLLS = 160
"""The most patience a line that keeps crowding is allowed to earn."""

CONNECT_DELAYS = (0.25, 0.5, 1.0, 2.0)
"""Pauses to try after the link opens, shortest first."""

FAILED_OPENS = 2
"""Opening requests that went unanswered before asking for a pause."""


def target_timeout(slowest: float | None) -> float | None:
    """The timeout this slowest answer earns, or ``None`` to ask nothing.

    Nothing measured, or a link whose own default is the honest answer.
    """
    if slowest is None:
        return None
    target = max(slowest * MARGIN, FLOOR)
    # Rounded because this value is read by people, in logs and diagnostics.
    return None if target >= MAX_ASK else round(target, 2)


@dataclass(frozen=True)
class LinkTuning:
    """What the tuner asks of a link, and how often it has withdrawn."""

    timeout: float | None = None
    spacing: float = 0.0
    connect_delay: float = 0.0
    withdrawals: int = 0


class LinkTuner:
    """Hold a link to the timing its own traffic says it needs.

    The timeout only comes down; the gap only widens on a crowded line.
    """

    def __init__(self, unit: TimedUnit, *, budget: float = BUDGET) -> None:
        self._unit = unit
        self._budget = budget
        self._asked: float | None = None
        self._withdrawals = 0
        self._clean = 0
        self._required = CLEAN_POLLS
        self._spacing = 0.0
        self._crowded = 0
        self._quiet = 0
        self._required_quiet = QUIET_POLLS
        self._answered: set[str] = set()
        self._reads = 0
        self._reads_per_poll = 1
        self._delay = 0.0
        self._opens = 0
        self._failed_opens = 0
        self._bad_opens = 0

    @property
    def tuning(self) -> LinkTuning:
        """What is being asked of the link as things stand."""
        return LinkTuning(self._asked, self._spacing, self._delay, self._withdrawals)

    def observe(self, report: UpdateReport) -> None:
        """Take one poll's outcome in, between polls and nowhere else."""
        polled, self._reads = self._unit.reads - self._reads, self._unit.reads
        # A high-water mark: a report carrying no reads of its own must not
        # read as a cheap poll and hand the budget out to one wide gap.
        self._reads_per_poll = max(self._reads_per_poll, polled)
        self._observe_spacing(report)
        self._observe_timeout(report)
        self._observe_opening()
        # A component has to have answered once for its silence to mean
        # anything, so this trails the poll that is being judged.
        self._answered |= report.updated

    def _observe_spacing(self, report: UpdateReport) -> None:
        """Widen the gap for a line dropping frames, narrow it for a quiet one."""
        if any(isinstance(err, ModbusDesyncError) for err in report.failed.values()):
            self._widen()  # a reply to another exchange is never ambiguous
            return
        if self._crowding(report):
            self._quiet = 0
            self._crowded += 1
            if self._crowded >= CROWDED_POLLS:
                self._widen()
            return
        self._crowded = 0
        self._quiet += 1
        if self._quiet >= self._required_quiet:
            self._narrow()

    def _crowding(self, report: UpdateReport) -> bool:
        """Whether the failures read as a line that cannot keep up.

        Silence from a component that never answered is a model's.
        """
        return any(
            isinstance(err, ServerDeviceBusyError)
            or (isinstance(err, ModbusTimeoutError) and name in self._answered)
            for name, err in report.failed.items()
        )

    def _widen(self) -> None:
        """Take the next gap the budget allows, and grow more patient."""
        self._crowded = self._quiet = 0
        cap = self._budget / self._reads_per_poll
        wider = [gap for gap in SPACING_STEPS if self._spacing < gap <= cap]
        if not wider:
            return
        self._spacing = wider[0]
        self._unit.set_message_spacing(self._spacing)
        self._required_quiet = min(self._required_quiet * 2, MAX_QUIET_POLLS)

    def _narrow(self) -> None:
        """Give one step of the gap back to a line that has stayed quiet."""
        self._quiet = 0
        if not self._spacing:
            return
        narrower = [gap for gap in SPACING_STEPS if gap < self._spacing]
        self._spacing = narrower[-1] if narrower else 0.0
        self._unit.set_message_spacing(self._spacing)

    def _observe_opening(self) -> None:
        """Pause after the link opens for a device that needs one.

        Never given back: one wait per connect is cheap to keep paying.
        """
        opens = self._unit.opens - self._opens
        failed = self._unit.failed_opens - self._failed_opens
        self._opens, self._failed_opens = self._unit.opens, self._unit.failed_opens
        if not failed:
            if opens:
                self._bad_opens = 0
            return
        self._bad_opens += failed
        if self._bad_opens < FAILED_OPENS:
            return
        self._bad_opens = 0
        longer = [pause for pause in CONNECT_DELAYS if pause > self._delay]
        if not longer:
            return
        self._delay = longer[0]
        self._unit.require_connect_delay(self._delay)

    def restore(self, tuning: LinkTuning) -> None:
        """Take up what an earlier run settled on, before polling starts.

        Patience comes back with it, or a restart resets every backoff.
        """
        self._asked = tuning.timeout
        self._spacing = tuning.spacing
        self._delay = tuning.connect_delay
        self._withdrawals = tuning.withdrawals
        self._required = min(CLEAN_POLLS * 2**tuning.withdrawals, MAX_CLEAN_POLLS)
        steps = sum(1 for gap in SPACING_STEPS if gap <= tuning.spacing)
        self._required_quiet = min(QUIET_POLLS * 2**steps, MAX_QUIET_POLLS)
        if tuning.timeout is not None:
            self._unit.require_timeout(tuning.timeout)
        if tuning.spacing:
            self._unit.set_message_spacing(tuning.spacing)
        if tuning.connect_delay:
            self._unit.require_connect_delay(tuning.connect_delay)

    def _observe_timeout(self, report: UpdateReport) -> None:
        """Lower the timeout a quiet link has earned, or hand its own back."""
        if any(isinstance(err, ModbusTimeoutError) for err in report.failed.values()):
            self._withdraw()
            return
        self._clean += 1
        if self._clean < self._required:
            return
        stats = self._unit.stats
        if stats.answered < MIN_ANSWERED:
            return
        target = target_timeout(stats.slowest)
        if target is None:
            return
        if self._asked is None or target < self._asked * WORTH_ASKING:
            self._ask(target)

    def _ask(self, seconds: float) -> None:
        """Lower the link's timeout, and earn the next lowering again."""
        self._unit.require_timeout(seconds)
        self._asked = seconds
        self._clean = 0

    def _withdraw(self) -> None:
        """Hand the link back its own timeout, and wait longer next time.

        A timeout while nothing was asked is the device's, not ours.
        """
        self._clean = 0
        if self._asked is None:
            return
        self._unit.require_timeout(None)
        self._asked = None
        self._withdrawals += 1
        self._required = min(self._required * 2, MAX_CLEAN_POLLS)
