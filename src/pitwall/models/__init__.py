"""Fitted models: fuel, pace, tyre degradation and safety-car hazard."""

from pitwall.models.fuel import (
    DEFAULT_SECONDS_PER_KG,
    DEFAULT_START_FUEL_KG,
    FuelModel,
)
from pitwall.models.pace import PaceFit, fit_pace
from pitwall.models.safety_car import (
    EventKind,
    HazardModel,
    bucket_for,
    fit_hazard,
    load_history,
)

__all__ = [
    "DEFAULT_SECONDS_PER_KG",
    "DEFAULT_START_FUEL_KG",
    "EventKind",
    "FuelModel",
    "HazardModel",
    "PaceFit",
    "bucket_for",
    "fit_hazard",
    "fit_pace",
    "load_history",
]
