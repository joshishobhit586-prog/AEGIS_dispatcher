"""Central configuration for AEGIS.

All cost-function terms are expressed in "tick-equivalent" units: distance is
grid steps (1 step == 1 tick), delay is ticks late, congestion is a queue-length
spread (tasks) scaled by CONGESTION_WEIGHT into tick-equivalents.
"""

# Recovery cost function weights
DISTANCE_WEIGHT = 1.0
DELAY_WEIGHT = 2.0
CONGESTION_WEIGHT = 3.0
PRIORITY_WEIGHT = 2.0
UNSERVED_PENALTY = 100.0  # per task a candidate plan cannot serve

# Simulation behaviour
REPLAN_AFTER_WAIT_TICKS = 3  # blocked this long -> try a detour around other robots
STALL_LIMIT = 30             # ticks without any change before a run is ended
MAX_TICKS = 500

STRATEGIES = ("baseline", "aegis")
