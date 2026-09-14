"""Measure a link through a device's unit, and ask it for what it needs."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

from modbus_connection import ModbusError, ModbusTimeoutError

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
        """Await one request, recording how long it took and how it ended."""
        started = time.monotonic()
        try:
            answer = await request
        except ModbusError as err:
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
"""Headroom over the slowest request that answered."""

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
    withdrawals: int = 0


class LinkTuner:
    """Ask a link for the timeout its own traffic says it needs.

    It only lowers; a timeout under a lowered value withdraws the ask.
    """

    def __init__(self, unit: TimedUnit) -> None:
        self._unit = unit
        self._asked: float | None = None
        self._withdrawals = 0
        self._clean = 0
        self._required = CLEAN_POLLS

    @property
    def tuning(self) -> LinkTuning:
        """What is being asked of the link as things stand."""
        return LinkTuning(self._asked, self._withdrawals)

    def observe(self, report: UpdateReport) -> None:
        """Take one poll's outcome in, between polls and nowhere else."""
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
