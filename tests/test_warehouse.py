import pytest
from simulation.warehouse import Warehouse

def wh():
    return Warehouse.from_layout(["...", ".#.", "..."])

def test_bounds_and_shelves():
    w = wh()
    assert w.is_walkable((0, 0))
    assert not w.is_walkable((1, 1))      # shelf
    assert not w.is_walkable((3, 0))      # out of bounds
    assert not w.is_walkable((-1, 0))

def test_block_unblock_and_neighbors():
    w = wh()
    assert (1, 0) in list(w.neighbors((0, 0)))
    assert w.block((1, 0)) is True
    assert w.block((1, 0)) is False
    assert (1, 0) not in list(w.neighbors((0, 0)))
    assert w.unblock((1, 0)) is True
    assert w.unblock((1, 0)) is False

def test_cannot_block_shelf_or_outside():
    w = wh()
    with pytest.raises(ValueError):
        w.block((1, 1))
    with pytest.raises(ValueError):
        w.block((9, 9))

def test_bad_layouts():
    with pytest.raises(ValueError):
        Warehouse.from_layout(["..", "..."])
    with pytest.raises(ValueError):
        Warehouse.from_layout([".?"])
