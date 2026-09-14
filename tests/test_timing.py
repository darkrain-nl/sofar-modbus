"""What the two device objects ask the link for."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter, SofarLegacyInverter

Inverter = type[SofarInverter] | type[SofarLegacyInverter]

INVERTERS = (SofarInverter, SofarLegacyInverter)


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_a_new_inverter_asks_for_five_seconds(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    inverter_class(mock_modbus_unit)
    assert mock_modbus_unit.required_timeout == 5.0


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_a_caller_can_ask_for_another_timeout(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    inverter_class(mock_modbus_unit, timeout=2.5)
    assert mock_modbus_unit.required_timeout == 2.5


@pytest.mark.parametrize("inverter_class", INVERTERS)
def test_none_leaves_the_link_to_its_own_default(
    inverter_class: Inverter, mock_modbus_unit: MockModbusUnit
) -> None:
    """A caller who wants the link's 10s says so, and nothing is asked."""
    inverter_class(mock_modbus_unit, timeout=None)
    assert mock_modbus_unit.required_timeout is None
