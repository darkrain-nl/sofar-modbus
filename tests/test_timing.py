"""What the two device objects ask the link for."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit

from sofar_modbus import SofarInverter, SofarLegacyInverter

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
