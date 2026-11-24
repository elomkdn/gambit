# SPDX-License-Identifier: GPL-3.0-or-later
"""Check runs, never used in normal use.

APP_WIDTH / APP_HEIGHT size the window, APP_ACTION calls a window method
(steps joined by "+": "new:human+play:e2e4,e7e5+select:g1"), and APP_SHOT renders the window
to a PNG, then quits (APP_SHOT_SCALE renders it at 2x or 3x, as on a denser screen).
"""
import os

import chess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import GLib, Graphene, Gtk  # noqa: E402

from .game import Setup  # noqa: E402


def screenshot(window, path):
    """Render the window to a PNG; APP_SHOT_SCALE renders it as a denser screen would (3 for a phone)."""
    width, height = window.get_width(), window.get_height()
    scale = float(os.environ.get("APP_SHOT_SCALE", "1"))
    snapshot = Gtk.Snapshot()
    snapshot.scale(scale, scale)
    Gtk.WidgetPaintable.new(window).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        return
    texture = window.get_renderer().render_texture(
        node, Graphene.Rect().init(0, 0, round(width * scale), round(height * scale)))
    texture.save_to_png(path)


def prepare(window):
    if os.environ.get("APP_WIDTH"):
        window.unmaximize()
        window.set_default_size(int(os.environ["APP_WIDTH"]), int(os.environ.get("APP_HEIGHT", "760")))
    action = os.environ.get("APP_ACTION")
    shot = os.environ.get("APP_SHOT")

    def act(steps=None):
        steps = list(filter(None, (action or "").split("+"))) if steps is None else steps
        while steps:
            step = steps.pop(0)
            if step.startswith("wait:"):            # wait:800 lets the board settle before the next step
                GLib.timeout_add(int(step[5:]), lambda rest=steps: act(rest))
                return False
            elif step.startswith("play:"):            # moves for the person, in UCI: play:e2e4,e7e5
                for uci in step[5:].split(","):
                    window._board_moved(uci)
            elif step.startswith("new:"):           # new:computer,black,club
                opponent, side, level = (step[4:].split(",") + ["computer", "white", "casual"])[:3]
                window.start_game(Setup(opponent, side != "black", level))
            elif step.startswith("puzzle:"):        # puzzle:yd6eW starts that puzzle
                window.set_mode("puzzles")
                window._start_puzzle(window.puzzles.by_id[step[7:]])
            elif step.startswith("attempt:"):       # attempt:b7a8 moves as a tap-tap would (promotion asks)
                window.board._attempt(chess.parse_square(step[8:10]), chess.parse_square(step[10:12]))
            elif step.startswith("select:"):        # select:e2 shows that piece's moves
                window.board._tap(chess.parse_square(step[7:]))
            elif hasattr(window, step):
                getattr(window, step)()
        return False

    def capture():
        screenshot(window, shot)
        window.close()
        return False

    if action:
        GLib.timeout_add(int(os.environ.get("APP_ACT_MS", "1200")), act)
    if shot:
        GLib.timeout_add(int(os.environ.get("APP_SHOT_MS", "2600")), capture)
