from simulation.robot import Robot, PHASE_TO_PICKUP
from simulation.simulator import Simulator
from simulation.task import Task, TaskStatus
from simulation.warehouse import Warehouse


def test_pickup_decreases_source_shelf_and_delivery_increases_destination_shelf():
    warehouse = Warehouse(5, 3, shelves=[(1, 1), (3, 1)])
    source_before = warehouse.inventory[(1, 1)]
    destination_before = warehouse.inventory[(3, 1)]
    robot = Robot("R1", (1, 2))
    task = Task("T1", pickup=(1, 2), delivery=(3, 2))
    sim = Simulator(warehouse, [robot], [task])
    task.assign("R1")
    robot.current_task_id = "T1"
    robot.phase = PHASE_TO_PICKUP

    sim._process_arrivals(robot)
    assert task.status is TaskStatus.IN_PROGRESS
    assert warehouse.inventory[(1, 1)] == source_before - 1
    assert warehouse.inventory[(3, 1)] == destination_before

    robot.position = (3, 2)
    sim._process_arrivals(robot)
    assert task.status is TaskStatus.COMPLETED
    assert warehouse.inventory[(1, 1)] == source_before - 1
    assert warehouse.inventory[(3, 1)] == destination_before + 1


def test_inventory_is_included_in_snapshot():
    warehouse = Warehouse(3, 2, shelves=[(1, 0)])
    sim = Simulator(warehouse, [Robot("R1", (0, 0))], [])
    item = sim.snapshot()["inventory"][0]
    assert tuple(item["cell"]) == (1, 0)
    assert item["quantity"] == warehouse.inventory[(1, 0)]
