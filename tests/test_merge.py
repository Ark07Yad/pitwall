"""Delta merge semantics.

These are the tests that matter most. A merge bug does not crash - it quietly
drops a field, and the timing screen still looks reasonable, so it survives all
the way to a wrong strategy call during a live race.
"""

from __future__ import annotations

from pitwall.state.merge import as_mapping, deep_merge


def test_partial_update_preserves_siblings():
    state = {"Lines": {"1": {"Position": "1", "GapToLeader": "+0.0"}}}
    deep_merge(state, {"Lines": {"1": {"Position": "2"}}})
    assert state["Lines"]["1"] == {"Position": "2", "GapToLeader": "+0.0"}


def test_update_does_not_drop_other_cars():
    state = {"Lines": {"1": {"Position": "1"}, "4": {"Position": "2"}}}
    deep_merge(state, {"Lines": {"4": {"Position": "1"}}})
    assert set(state["Lines"]) == {"1", "4"}
    assert state["Lines"]["1"]["Position"] == "1"


def test_nested_three_levels_deep():
    state = {"Lines": {"1": {"Sectors": {"0": {"Value": "24.1", "Status": 0}}}}}
    deep_merge(state, {"Lines": {"1": {"Sectors": {"0": {"Value": "23.9"}}}}})
    sector = state["Lines"]["1"]["Sectors"]["0"]
    assert sector == {"Value": "23.9", "Status": 0}


def test_index_keyed_dict_patches_a_list():
    state = {"Sectors": [{"Value": "24.1"}, {"Value": "31.0"}, {"Value": "22.5"}]}
    deep_merge(state, {"Sectors": {"1": {"Value": "30.4"}}})
    assert state["Sectors"] == [{"Value": "24.1"}, {"Value": "30.4"}, {"Value": "22.5"}]


def test_index_map_can_append_next_element():
    state = {"Stints": [{"Compound": "SOFT"}]}
    deep_merge(state, {"Stints": {"1": {"Compound": "HARD"}}})
    assert state["Stints"] == [{"Compound": "SOFT"}, {"Compound": "HARD"}]


def test_new_keys_are_added():
    state = {"Lines": {"1": {"Position": "1"}}}
    deep_merge(state, {"Lines": {"77": {"Position": "12"}}})
    assert state["Lines"]["77"] == {"Position": "12"}


def test_merging_into_nothing_returns_update():
    assert deep_merge(None, {"a": 1}) == {"a": 1}


def test_scalars_overwrite():
    assert deep_merge({"Status": "1"}, {"Status": "4"}) == {"Status": "4"}


def test_false_and_zero_are_not_swallowed():
    state = {"InPit": True, "Laps": 5}
    deep_merge(state, {"InPit": False, "Laps": 0})
    assert state == {"InPit": False, "Laps": 0}


def test_as_mapping_normalises_both_shapes():
    assert as_mapping({"0": "a", "1": "b"}) == {"0": "a", "1": "b"}
    assert as_mapping(["a", "b"]) == {"0": "a", "1": "b"}
    assert as_mapping(None) == {}
