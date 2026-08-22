"""Fitted models: fuel, pace, tyre degradation, safety-car hazard and pit loss."""

from pitwall.models.attrition import AttritionModel, fit_attrition
from pitwall.models.fuel import (
    DEFAULT_SECONDS_PER_KG,
    DEFAULT_START_FUEL_KG,
    FuelModel,
)
from pitwall.models.pace import PaceFit, fit_pace
from pitwall.models.pit_loss import (
    DEFAULT_PIT_LOSS,
    PitLossModel,
    fit_pit_loss,
    load_pit_loss,
)
from pitwall.models.safety_car import (
    EventKind,
    HazardModel,
    bucket_for,
    fit_hazard,
    load_history,
    normalise_circuit,
)

__all__ = [
    "AttritionModel",
    "DEFAULT_PIT_LOSS",
    "DEFAULT_SECONDS_PER_KG",
    "DEFAULT_START_FUEL_KG",
    "EventKind",
    "FuelModel",
    "HazardModel",
    "PaceFit",
    "PitLossModel",
    "bucket_for",
    "fit_attrition",
    "fit_hazard",
    "fit_pace",
    "fit_pit_loss",
    "load_history",
    "load_pit_loss",
    "normalise_circuit",
]
