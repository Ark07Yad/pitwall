"""Identify which model made a call, so two ledgers can be compared honestly.

Every ledger row already records where its *data* came from — live, a replay, a
backtest. Nothing recorded which *model* produced it, and on 7 September that
cost an hour: an archive backtest compared against `2026-hungarian-gp.jsonl`
showed 27 of 28 calls differing, which reads as a data-fidelity fault and was
five weeks of model change. That file was written on 3 August, before the
stay-out option, before per-circuit pit loss, before the degradation rebuild, and
before the alias fix that made `Hungaroring` resolve to Budapest at all.

Provenance that stops at the data is half of it. A stored prediction is only
comparable with another one if the same model made both, and nothing in the file
said so.

**What goes into the hash.** The parameters that actually reach a decision: the
pooled degradation shape, the four per-circuit factors for the circuit being
raced, the pit-loss baseline and its botched-stop tail, and each model's race
count. Not the warnings, which are prose, and not `n_laps`, which moves without
changing an answer.

**Why the circuit is in it.** The same code and the same files still give a
different model at a different track, and a fingerprint that ignored that would
call two incomparable rows comparable — the exact failure this exists to prevent.

**Absence is named, never hashed.** A missing model contributes the literal
string `none` rather than being skipped. Skipping it would make "no pit-loss
model" and "a pit-loss model that happens to hash to nothing" the same value,
and this codebase's recurring fault is precisely the silent default that looks
like a real answer.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from pitwall.models.safety_car import normalise_circuit

UNKNOWN = "unknown"


def code_version(repo: Path | str | None = None) -> str:
    """The commit the engine is running, with a marker when the tree is dirty.

    A dirty tree means the code is not any commit, and saying `4c8f425` for it
    would be a lie of exactly the kind this module exists to stop. Returns
    `unknown` when git cannot answer rather than inventing a value.
    """
    cwd = Path(repo) if repo else Path.cwd()
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return UNKNOWN
    if not sha:
        return UNKNOWN
    return f"{sha}+dirty" if dirty else sha


def _round(value: Any) -> Any:
    """Round floats so simulation-irrelevant drift does not change the hash."""
    return round(float(value), 6) if isinstance(value, (int, float)) else value


def _flat(value: Any) -> str:
    """Canonical text for a scalar or a mapping.

    A mapping is sorted by key rather than left in insertion order: `repr` of a
    dict is stable within one process and is not a promise across versions, and a
    fingerprint that changes when nothing changed is as useless as one that does
    not change when something does.
    """
    if isinstance(value, dict):
        return ",".join(f"{k}:{_round(v)}" for k, v in sorted(value.items()))
    return str(_round(value))


def model_terms(
    *,
    circuit: str,
    hazard: Any = None,
    attrition: Any = None,
    pit_loss: Any = None,
    degradation: Any = None,
) -> list[str]:
    """The model parameters that reach a decision, as readable `key=value` terms.

    Readable rather than opaque because "these two differ" is much less useful
    than "these two differ in the degradation factor", and a hash alone cannot
    say the second.
    """
    key = normalise_circuit(circuit)
    terms: list[str] = [f"circuit={key or '?'}"]

    if hazard is None:
        terms.append("sc=none")
    else:
        terms.append(
            f"sc={_round(hazard.circuit_factor.get(key, 1.0))}"
            f"/{_flat(hazard.baseline)}/{hazard.n_races}"
        )
    if attrition is None:
        terms.append("at=none")
    else:
        terms.append(
            f"at={_round(attrition.circuit_factor.get(key, 1.0))}"
            f"/{_flat(attrition.rate_per_car)}/{attrition.n_races}"
        )
    if pit_loss is None:
        terms.append("pl=none")
    else:
        terms.append(
            f"pl={_round(pit_loss.circuit_loss.get(key, pit_loss.baseline))}"
            f"/{_round(pit_loss.baseline)}/{_round(pit_loss.botch_rate)}"
            f"/{_round(pit_loss.botch_scale)}/{pit_loss.n_races}"
        )
    if degradation is None:
        terms.append("dg=none")
    else:
        shape = ",".join(
            f"{c.short}:{_round(degradation.linear[c])}"
            f":{_round(degradation.curvature.get(c, 0.0))}"
            f":{degradation.reliable_max_age.get(c, 0)}"
            for c in sorted(degradation.linear, key=lambda c: c.short)
        )
        terms.append(
            f"dg={_round(degradation.circuit_factor.get(key, 1.0))}/{degradation.n_races}/{shape}"
        )
    return terms


def unfitted_models(
    *,
    circuit: str,
    hazard: Any = None,
    attrition: Any = None,
    pit_loss: Any = None,
    degradation: Any = None,
) -> str:
    """Which per-circuit models have no history here, as a sorted string.

    Lives beside the fingerprint because both answer "what model made this" and
    both are needed on every path that writes a ledger row. It was a method on
    the engine first, which left the backtest path writing an empty string -
    and a backtest is the file most likely to be compared against another one.

    Named for what is missing, so the ordinary case is empty and anything
    non-empty is always worth reading.
    """
    models = {
        "safety_car": hazard,
        "attrition": attrition,
        "pit_loss": pit_loss,
        "degradation": degradation,
    }
    return ",".join(
        sorted(
            name
            for name, model in models.items()
            if model is not None and not model.known_circuit(circuit)
        )
    )


def model_fingerprint(
    *,
    circuit: str,
    hazard: Any = None,
    attrition: Any = None,
    pit_loss: Any = None,
    degradation: Any = None,
    code: str | None = None,
) -> str:
    """A short, stable id for the model that made a call: `<commit>/<params>`.

    Two rows sharing this were produced by the same code against the same fitted
    models at the same circuit, and are comparable. Two rows that differ are not,
    however similar their numbers look.
    """
    terms = model_terms(
        circuit=circuit,
        hazard=hazard,
        attrition=attrition,
        pit_loss=pit_loss,
        degradation=degradation,
    )
    digest = hashlib.sha256("|".join(terms).encode("utf-8")).hexdigest()[:8]
    return f"{code if code is not None else code_version()}/{digest}"
