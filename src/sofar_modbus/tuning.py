"""What a link is doing, measured through the unit a device reads from."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

from modbus_connection import ModbusError

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit

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
