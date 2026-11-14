"""Tune a link to what its own traffic says it needs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from modbus_connection import (
    ModbusDesyncError,
    ModbusTimeoutError,
    ServerDeviceBusyError,
)

from .tuning import LinkTuning, TimedUnit

if TYPE_CHECKING:
    from modbus_connection.model import UpdateReport

_LOGGER = logging.getLogger(__name__)

SPACING_STEPS = (0.02, 0.03, 0.05, 0.1, 0.2)
"""Gaps to try between this unit's own frames, narrowest first.

HA's YAML modbus spaces serial at 30 ms and TCP at 0; this spans both.
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


class LinkTuner:
    """Hold a link to the timing its own traffic says it needs."""

    def __init__(self, unit: TimedUnit, *, budget: float = BUDGET) -> None:
        self._unit = unit
        self._budget = budget
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
        return LinkTuning(spacing=self._spacing, connect_delay=self._delay)

    def observe(self, report: UpdateReport) -> None:
        """Take one poll's outcome in, between polls and nowhere else."""
        self._count_reads()
        self._observe_spacing(report)
        self._observe_opening()
        # A component has to have answered once for its silence to mean
        # anything, so this trails the poll that is being judged.
        self._answered |= report.updated

    def observe_failure(self) -> None:
        """Take in a poll that raised rather than reporting.

        It named no component, so only its reads and opens count.
        """
        self._count_reads()
        self._observe_opening()

    def _count_reads(self) -> None:
        """Take this poll's reads into the mark the gap's budget divides."""
        polled, self._reads = self._unit.reads - self._reads, self._unit.reads
        # A high-water mark: a poll carrying no reads of its own must not
        # read as a cheap one and hand the budget out to a single wide gap.
        self._reads_per_poll = max(self._reads_per_poll, polled)

    def _observe_spacing(self, report: UpdateReport) -> None:
        """Widen the gap for a line dropping frames, narrow it for a quiet one."""
        if any(isinstance(err, ModbusDesyncError) for err in report.failed.values()):
            # A reply to another exchange is never ambiguous.
            self._widen("a reply desynced")
            return
        if self._crowding(report):
            self._quiet = 0
            self._crowded += 1
            if self._crowded >= CROWDED_POLLS:
                self._widen("the line is crowded")
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

    def _widen(self, why: str) -> None:
        """Take the next gap the budget allows, and grow more patient."""
        self._crowded = self._quiet = 0
        cap = self._budget / self._reads_per_poll
        wider = [gap for gap in SPACING_STEPS if self._spacing < gap <= cap]
        if not wider:
            _LOGGER.debug(
                "Not widening the %s s frame gap (%s): the budget caps it at %.3f s",
                self._spacing,
                why,
                cap,
            )
            return
        _LOGGER.debug("Widening the frame gap to %s s: %s", wider[0], why)
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
        _LOGGER.debug(
            "Narrowing the frame gap to %s s after %d quiet polls",
            self._spacing,
            self._required_quiet,
        )
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
        bad_opens, self._bad_opens = self._bad_opens, 0
        longer = [pause for pause in CONNECT_DELAYS if pause > self._delay]
        if not longer:
            _LOGGER.debug(
                "Not lengthening the %s s connect delay (%d unanswered opens): "
                "it is the longest",
                self._delay,
                bad_opens,
            )
            return
        _LOGGER.debug(
            "Pausing %s s after the link opens: %d opening requests went unanswered",
            longer[0],
            bad_opens,
        )
        self._delay = longer[0]
        self._unit.require_connect_delay(self._delay)
