"""Side panels, status bar, legend and event log."""
from __future__ import annotations

import pygame

from ui.renderer import BAD, DIM, GOOD, PANEL, PANEL_EDGE, TEXT, UNASSIGNED, robot_color

LOG_COLORS = {
    "robot_failure": BAD, "task_failed": BAD, "event_rejected": BAD, "block_cell": BAD,
    "recovery": GOOD, "delivery": (140, 190, 255), "task_unserved": (255, 190, 90),
    "task_unassignable": (255, 190, 90),
}


def fit(font, text: str, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "..")[0] > max_w:
        text = text[:-1]
    return text + ".."


def box(surf, rect, title, fonts) -> None:
    pygame.draw.rect(surf, PANEL, rect, border_radius=6)
    pygame.draw.rect(surf, PANEL_EDGE, rect, 1, border_radius=6)
    surf.blit(fonts["bold"].render(title, True, TEXT), (rect.x + 10, rect.y + 6))


def draw_status_bar(surf, rect, fonts, info: dict) -> None:
    pygame.draw.rect(surf, PANEL, rect)
    state = info["state"].upper()
    left = f"AEGIS | {info['scenario']} | strategy: {info['strategy'].upper()} | tick {info['tick']}"
    surf.blit(fonts["bold"].render(left, True, TEXT), (16, 13))
    right = f"{state} | speed {info['speed']} ticks/s"
    img = fonts["bold"].render(right, True, GOOD if state == "RUNNING" else TEXT)
    surf.blit(img, (rect.right - img.get_width() - 16, 13))
    if info.get("notice"):
        n = fonts["small"].render(info["notice"], True, (255, 210, 120))
        surf.blit(n, (rect.centerx - n.get_width() // 2 + 120, 15))


def draw_robots(surf, rect, fonts, snap, selected) -> None:
    box(surf, rect, "Robots", fonts)
    y = rect.y + 30
    rows = max(1, (rect.h - 34) // 19)
    shown = snap["robots"][:rows] if len(snap["robots"]) <= rows else snap["robots"][: rows - 1]
    for i, r in enumerate(shown):
        pygame.draw.rect(surf, robot_color(i), (rect.x + 10, y + 2, 12, 12), border_radius=3)
        mark = ">" if r["robot_id"] == selected else " "
        q = ",".join(r["queue"]) or "-"
        line = f"{mark}{r['robot_id']} {r['status']:<11} now:{r['current_task_id'] or '-'}  q:[{q}]"
        surf.blit(fonts["small"].render(fit(fonts["small"], line, rect.w - 40), True, TEXT), (rect.x + 28, y))
        y += 19
    hidden = len(snap["robots"]) - len(shown)
    if hidden > 0:
        surf.blit(fonts["small"].render(f"... +{hidden} more robots", True, DIM), (rect.x + 28, y))


def draw_tasks(surf, rect, fonts, snap) -> None:
    box(surf, rect, "Tasks", fonts)
    counts = {}
    for t in snap["tasks"]:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    summary = "  ".join(f"{k[:4]}:{v}" for k, v in sorted(counts.items()))
    surf.blit(fonts["small"].render(fit(fonts["small"], summary, rect.w - 20), True, DIM), (rect.x + 10, rect.y + 28))
    y = rect.y + 50
    order = {"IN_PROGRESS": 0, "ASSIGNED": 1, "PENDING": 2, "FAILED": 3, "COMPLETED": 4}
    for t in sorted(snap["tasks"], key=lambda t: (order[t["status"]], t["task_id"])):
        if y > rect.bottom - 18:
            surf.blit(fonts["tiny"].render("...", True, DIM), (rect.x + 10, y))
            break
        dl = f" dl{t['deadline']}" if t["deadline"] is not None else ""
        line = f"{t['task_id']:<4} {t['status']:<11} {t['assigned_robot_id'] or '-':<3} p{t['priority']}{dl}"
        col = DIM if t["status"] == "COMPLETED" else (BAD if t["status"] == "FAILED" else TEXT)
        surf.blit(fonts["small"].render(fit(fonts["small"], line, rect.w - 20), True, col), (rect.x + 10, y))
        y += 17


def draw_metrics(surf, rect, fonts, m: dict) -> None:
    box(surf, rect, "Metrics (live)", fonts)
    rows = [
        ("Completion", f"{m['completion_rate']:.0f}%  ({m['tasks_completed']}/{m['tasks_created']})"),
        ("Unserved tasks", m["unserved_tasks"]),
        ("Total distance", m["total_distance"]),
        ("Total delay (ticks)", m["total_delay"]),
        ("Recoveries run", m["recovery_count"]),
        ("Recovery duration (ticks)", m["recovery_duration_ticks"]),
        ("Unresolved disruptions", m["unresolved_disruptions"]),
        ("Collisions", m["collisions"]),
        ("Wait ticks", m["wait_ticks"]),
        ("Planning time", f"{m['planning_time_s'] * 1000:.1f} ms"),
    ]
    y = rect.y + 30
    for k, v in rows:
        surf.blit(fonts["small"].render(k, True, DIM), (rect.x + 10, y))
        val = fonts["small"].render(str(v), True, TEXT)
        surf.blit(val, (rect.right - val.get_width() - 12, y))
        y += 19


def draw_event_log(surf, rect, fonts, events) -> None:
    box(surf, rect, "Event log", fonts)
    lines = max(1, (rect.h - 32) // 16)
    y = rect.y + 28
    for e in events[-lines:]:
        text = f"t={e['tick']:<3} {e['type']:<16} {e['description']}"
        col = LOG_COLORS.get(e["type"], TEXT)
        surf.blit(fonts["small"].render(fit(fonts["small"], text, rect.w - 20), True, col), (rect.x + 10, y))
        y += 16


def draw_legend(surf, rect, fonts) -> None:
    x, y = rect.x + 4, rect.y + 4
    def item(label, draw):
        nonlocal x
        draw(x, y)
        img = fonts["tiny"].render(label, True, TEXT)
        surf.blit(img, (x + 16, y + 1))
        x += 16 + img.get_width() + 14
    item("pickup", lambda a, b: pygame.draw.polygon(surf, UNASSIGNED, [(a + 6, b), (a, b + 10), (a + 12, b + 10)]))
    item("delivery", lambda a, b: pygame.draw.rect(surf, UNASSIGNED, (a, b, 11, 11), 2))
    item("grey = unassigned", lambda a, b: pygame.draw.rect(surf, UNASSIGNED, (a, b, 11, 11)))
    item("route", lambda a, b: pygame.draw.line(surf, robot_color(0), (a, b + 6), (a + 12, b + 6), 3))
    item("blocked", lambda a, b: (pygame.draw.line(surf, BAD, (a, b), (a + 11, b + 11), 3), pygame.draw.line(surf, BAD, (a + 11, b), (a, b + 11), 3)))
    item("dot = carrying", lambda a, b: pygame.draw.circle(surf, (255, 255, 255), (a + 6, b + 6), 4))
    y += 18
    x = rect.x + 4
    surf.blit(fonts["tiny"].render("Robot letter: M moving, W waiting, I idle, X failed (red cross)", True, DIM), (x, y))
