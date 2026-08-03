"""Fitted models: fuel, pace, tyre degradation and safety-car hazard."""

from pitwall.models.attrition import AttritionModel, fit_attrition
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
    "AttritionModel",
    "DEFAULT_SECONDS_PER_KG",
    "DEFAULT_START_FUEL_KG",
    "EventKind",
    "FuelModel",
    "HazardModel",
    "PaceFit",
    "bucket_for",
    "fit_attrition",
    "fit_hazard",
    "fit_pace",
    "load_history",
]
