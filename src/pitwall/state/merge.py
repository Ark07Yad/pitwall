"""Delta merging for the live timing feed.

The feed sends a full snapshot on subscribe and *partial* updates thereafter. A
message like `{"Lines": {"4": {"Position": "3"}}}` means "car 4 moved to P3", not
"the timing table now contains only car 4". Overwriting instead of merging is the
single easiest way to silently destroy state, and it fails in a way that still
looks plausible on screen - so this is the most heavily tested code in the repo.

One quirk needs special handling: the feed patches arrays by sending an object
whose keys are stringified indices. `{"0": {"Value": "23.4"}}` against a
three-element list means "update element 0", not "replace the list with a dict".
"""

from __future__ import annotations

from typing import Any


def _is_index_map(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(k.isdigit() for k in value)


def deep_merge(target: Any, update: Any) -> Any:
    """Merge `update` into `target`, returning the merged value.

    Mutates `target` in place where possible - these merges run at feed rate and
    copying the whole timing tree per message is wasted work. Callers that need
    an unshared snapshot should copy explicitly.
    """
    if isinstance(target, dict) and isinstance(update, dict):
        for key, value in update.items():
            target[key] = deep_merge(target.get(key), value) if key in target else value
        return target

    if isinstance(target, list) and _is_index_map(update):
        for key, value in update.items():
            index = int(key)
            if 0 <= index < len(target):
                target[index] = deep_merge(target[index], value)
            elif index == len(target):
                target.append(value)
            else:
                target.extend([None] * (index - len(target)))
                target.append(value)
        return target

    if isinstance(target, list) and isinstance(update, list):
        return update

    return update


def as_mapping(value: Any) -> dict[str, Any]:
    """Normalise a field that may arrive as either a list or an index-keyed dict.

    `Stints` and `Sectors` switch between the two shapes depending on whether the
    message is a snapshot or a delta.
    """
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    if isinstance(value, list):
        return {str(i): v for i, v in enumerate(value) if v is not None}
    return {}
