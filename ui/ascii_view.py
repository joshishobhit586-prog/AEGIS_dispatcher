"""Tiny text renderer for quick inspection before the Pygame UI exists."""


def render_ascii(snap: dict) -> str:
    grid = [["." for _ in range(snap["width"])] for _ in range(snap["height"])]
    for x, y in snap["shelves"]:
        grid[y][x] = "#"
    for x, y in snap["blocked"]:
        grid[y][x] = "X"
    for r in snap["robots"]:
        x, y = r["position"]
        mark = r["robot_id"][-1]
        grid[y][x] = mark.lower() if r["status"] == "UNAVAILABLE" else mark
    header = f"tick {snap['tick']}  strategy={snap['strategy']}  (#=shelf X=blocked, lowercase=failed robot)"
    return header + "\n" + "\n".join("".join(row) for row in grid)
