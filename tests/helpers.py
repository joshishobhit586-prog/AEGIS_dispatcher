from simulation.robot import Robot
from simulation.simulator import Simulator
from simulation.task import Task
from simulation.warehouse import Warehouse

def make_sim(strategy, tasks, events=(), robots=None, layout=None):
    wh = Warehouse.from_layout(layout or ["........"] * 4)
    robots = robots or [Robot("R1", (0, 0)), Robot("R2", (7, 0))]
    return Simulator(wh, robots, tasks, list(events), strategy)
