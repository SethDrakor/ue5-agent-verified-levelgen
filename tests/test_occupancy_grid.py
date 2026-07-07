"""Real unit tests for OccupancyGrid (ue5_utils.py).

Unlike test_import_smoke.py, these check actual behavior. They can, because
OccupancyGrid is pure 2D grid math — its only touch point with the engine is
a single `unreal.log(...)` call in `__init__`, which the stub absorbs
harmlessly. This mirrors (independently — not a copy of) the "OccupancyGrid
unitaire" coverage in the in-editor test_suite.py, so the same logic gets a
second, engine-free check on every push.
"""
from ue5_utils import OccupancyGrid


def test_empty_grid_is_free_everywhere_within_bounds():
    grid = OccupancyGrid(0, 1000, 0, 1000, cell_size=50)
    assert grid.is_free(500, 500, radius=60)


def test_mark_occupied_blocks_the_marked_disc():
    grid = OccupancyGrid(0, 1000, 0, 1000, cell_size=50)
    grid.mark_occupied(500, 500, radius=100)
    assert not grid.is_free(500, 500, radius=60)
    assert not grid.is_free(550, 500, radius=60)


def test_mark_occupied_does_not_leak_to_distant_cells():
    grid = OccupancyGrid(0, 1000, 0, 1000, cell_size=50)
    grid.mark_occupied(100, 100, radius=50)
    assert grid.is_free(900, 900, radius=60)


def test_find_nearest_free_returns_a_position_actually_free():
    grid = OccupancyGrid(0, 2000, 0, 2000, cell_size=50)
    grid.mark_occupied(1000, 1000, radius=200)
    x, y = grid.find_nearest_free(1000, 1000, radius=60, max_dist=600)
    assert x is not None and y is not None
    assert grid.is_free(x, y, radius=60)


def test_find_nearest_free_gives_up_on_a_saturated_grid():
    grid = OccupancyGrid(0, 200, 0, 200, cell_size=50)
    grid.mark_occupied(100, 100, radius=5000)  # fully occupies this small grid
    x, y = grid.find_nearest_free(100, 100, radius=60, max_dist=100)
    assert x is None and y is None
