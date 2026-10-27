from algorithms.astar import find_path
from simulation.warehouse import Warehouse

def legal(path, w):
    return all(
        abs(a[0]-b[0]) + abs(a[1]-b[1]) == 1 and w.is_walkable(b)
        for a, b in zip(path, path[1:])
    )

def test_start_equals_goal():
    assert find_path(Warehouse(3, 3), (1, 1), (1, 1)) == [(1, 1)]

def test_direct_route_is_shortest():
    w = Warehouse(5, 5)
    p = find_path(w, (0, 0), (4, 3))
    assert len(p) - 1 == 7 and legal(p, w)

def test_detour_around_shelf():
    w = Warehouse.from_layout([".....", "..#..", "....."])
    p = find_path(w, (0, 1), (4, 1))
    assert p is not None and (2, 1) not in p and len(p) - 1 == 6 and legal(p, w)

def test_no_path():
    w = Warehouse.from_layout([".#.", ".#.", ".#."])
    assert find_path(w, (0, 0), (2, 0)) is None

def test_blocked_goal_and_extra_blocked():
    w = Warehouse(3, 1)
    w.block((2, 0))
    assert find_path(w, (0, 0), (2, 0)) is None
    w.unblock((2, 0))
    assert find_path(w, (0, 0), (2, 0), extra_blocked={(1, 0)}) is None

def test_start_on_blocked_cell_can_leave():
    w = Warehouse(3, 1)
    w.block((0, 0))
    assert find_path(w, (0, 0), (2, 0)) == [(0, 0), (1, 0), (2, 0)]
