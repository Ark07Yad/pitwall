"""Fitted models: fuel, pace and tyre degradation."""

from pitwall.models.fuel import (
    DEFAULT_SECONDS_PER_KG,
    DEFAULT_START_FUEL_KG,
    FuelModel,
)
from pitwall.models.pace import PaceFit, fit_pace

__all__ = [
    "DEFAULT_SECONDS_PER_KG",
    "DEFAULT_START_FUEL_KG",
    "FuelModel",
    "PaceFit",
    "fit_pace",
]
