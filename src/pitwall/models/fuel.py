"""Fuel-load correction.

A car burns fuel and gets lighter, so lap times fall through a stint for reasons
that have nothing to do with tyres. The effect is roughly the same size as
degradation itself and points the opposite way, so leaving it in does not merely
add noise - it cancels part of the signal and biases every degradation estimate
towards zero.

Two ways to get the correction, and the project needs both:

* **This module** - physics from published constants. Works from lap 1 of a race
  with no data at all, which is exactly the situation the live engine is in when
  a strategy call matters most.
* **`pitwall.models.pace`** - estimated from the race itself. More accurate and
  circuit-specific, but needs a completed race, so it is an offline calibration
  that feeds better constants back into this model.

2026 numbers: the race fuel allowance dropped from 110 kg to 70 kg, and the
accepted sensitivity is 0.30-0.40 s per 10 kg.
"""

from __future__ import annotations

from dataclasses import dataclass

# FIA 2026 race fuel allowance.
DEFAULT_START_FUEL_KG = 70.0
# Midpoint of the published 0.30-0.40 s per 10 kg range.
DEFAULT_SECONDS_PER_KG = 0.035


@dataclass(frozen=True)
class FuelModel:
    """Converts race lap number into the lap-time penalty from fuel aboard."""

    total_laps: int
    start_fuel_kg: float = DEFAULT_START_FUEL_KG
    seconds_per_kg: float = DEFAULT_SECONDS_PER_KG

    def __post_init__(self) -> None:
        if self.total_laps <= 0:
            raise ValueError("total_laps must be positive to model fuel burn")

    @property
    def burn_per_lap_kg(self) -> float:
        """Assumes an even burn. Real consumption varies with lift-and-coast and
        safety car periods, but the deviation is small next to the total range."""
        return self.start_fuel_kg / self.total_laps

    @property
    def seconds_per_lap(self) -> float:
        """How much faster each successive lap is, from fuel burn alone."""
        return self.burn_per_lap_kg * self.seconds_per_kg

    def fuel_during_lap(self, lap: int) -> float:
        """Mean fuel aboard while running `lap`, in kg.

        Uses the midpoint of the lap rather than either end - the car burns fuel
        continuously, so a lap run between 40 kg and 39 kg behaves like 39.5 kg.
        """
        remaining = self.start_fuel_kg - self.burn_per_lap_kg * (lap - 0.5)
        return max(0.0, remaining)

    def penalty(self, lap: int) -> float:
        """Seconds this lap was slowed by the fuel still aboard."""
        return self.fuel_during_lap(lap) * self.seconds_per_kg

    def correct(self, lap_time: float, lap: int) -> float:
        """Normalise a lap time to an empty-tank equivalent.

        Corrected times are directly comparable across the race, which is what
        makes a degradation fit meaningful. They are faster than anything
        actually driven - the zero point is a reference, not a prediction.
        """
        return lap_time - self.penalty(lap)

    def calibrated(self, seconds_per_lap: float) -> FuelModel:
        """Rebuild this model from a measured per-lap trend.

        Takes the magnitude: `pace.fit_pace` reports the race-lap coefficient as
        negative (cars get faster), while this model holds the effect as a
        positive penalty.
        """
        measured = abs(seconds_per_lap)
        return FuelModel(
            total_laps=self.total_laps,
            start_fuel_kg=self.start_fuel_kg,
            seconds_per_kg=measured / self.burn_per_lap_kg,
        )
