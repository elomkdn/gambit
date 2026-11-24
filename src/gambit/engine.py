# SPDX-License-Identifier: GPL-3.0-or-later
"""Stockfish, spoken to over UCI from the main loop: no threads, nothing blocks.

Stockfish 11 is the last version that needs no neural network file, and it is
still far stronger than any person; its own strength limit (UCI_Elo, 1350 to
2850) and Skill Level give the gentler levels. Each search answers with one
`bestmove`; a search that is stopped still answers, so callbacks are queued in
order and a stopped search's answer is dropped.
"""
from __future__ import annotations

import os
import shutil
from collections import deque
from dataclasses import dataclass

from gi.repository import Gio, GLib


@dataclass(frozen=True)
class Level:
    key: str
    label: str
    detail: str
    options: tuple          # (name, value) pairs sent before each search
    movetime: int           # milliseconds


LEVELS = (
    Level("easy", "Easy", "Learning the moves", (("Skill Level", 0),), 60),
    Level("casual", "Casual", "Plays like a newcomer, about 1350",
          (("UCI_LimitStrength", "true"), ("UCI_Elo", 1350)), 250),
    Level("club", "Club", "A good club player, about 1700",
          (("UCI_LimitStrength", "true"), ("UCI_Elo", 1700)), 400),
    Level("hard", "Hard", "A strong player, about 2200",
          (("UCI_LimitStrength", "true"), ("UCI_Elo", 2200)), 600),
    Level("master", "Master", "Stockfish at full strength", (), 900),
)
LEVEL = {level.key: level for level in LEVELS}
# Every option a level may change, reset before each search so levels never leak into each other.
DEFAULTS = (("UCI_LimitStrength", "false"), ("Skill Level", 20))


def engine_path() -> str | None:
    for candidate in (os.environ.get("GAMBIT_ENGINE"), "/app/bin/stockfish", shutil.which("stockfish")):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    return None


class Engine:
    def __init__(self):
        self.process = None
        self._stdin = None
        self._stdout = None
        self._waiting = deque()     # one entry per search not yet answered: a callback, or None to drop it
        self._score = None          # the deepest evaluation the current search has given
        self.available = False

    def start(self) -> bool:
        path = engine_path()
        if path is None:
            return False
        try:
            self.process = Gio.Subprocess.new(
                [path], Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
                | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return False
        self._stdin = self.process.get_stdin_pipe()
        self._stdout = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        self.available = True
        self._read()
        self._send("uci")
        self._send("setoption name Threads value 1")
        self._send("setoption name Hash value 32")
        self._send("isready")
        return True

    # ── searching ─────────────────────────────────────────────────────

    def think(self, moves, level: Level, callback, *, movetime: int | None = None, full_strength=False) -> None:
        """Ask for the best move after `moves` (UCI, from the start); `callback(uci or None)` gets it."""
        if not self.available:
            GLib.idle_add(lambda: callback(None) and False)
            return
        self.stop()
        for name, value in DEFAULTS + (() if full_strength else level.options):
            self._send(f"setoption name {name} value {value}")
        self._send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
        self._waiting.append(callback)
        self._send(f"go movetime {movetime or level.movetime}")

    def analyse(self, moves, callback, *, movetime: int = 150) -> None:
        """Evaluate the position after `moves` at full strength: `callback(best uci or None, score)`.

        `score` is in centipawns for the side to move (a mate is ±10000 less its distance), or None.
        """
        if not self.available:
            GLib.idle_add(lambda: callback(None, None) and False)
            return
        self.stop()
        for name, value in DEFAULTS:
            self._send(f"setoption name {name} value {value}")
        self._send("position startpos" + (" moves " + " ".join(moves) if moves else ""))
        self._waiting.append(lambda move, score: callback(move, score))
        self._waiting[-1].wants_score = True
        self._send(f"go movetime {movetime}")

    def stop(self) -> None:
        """Stop a search in progress; its answer, when it comes, is dropped."""
        if self._waiting and self._waiting[-1] is not None:
            self._waiting[-1] = None
            self._send("stop")

    @property
    def thinking(self) -> bool:
        return any(callback is not None for callback in self._waiting)

    def quit(self) -> None:
        if self.process is None:
            return
        self._waiting.clear()
        self._send("quit")
        process, self.process = self.process, None
        GLib.timeout_add(500, lambda: (process.force_exit(), False)[1])
        self.available = False

    # ── the pipe ──────────────────────────────────────────────────────

    def _send(self, line: str) -> None:
        if self._stdin is None:
            return
        try:
            self._stdin.write_all((line + "\n").encode(), None)
        except GLib.Error:
            self.available = False

    def _read(self) -> None:
        self._stdout.read_line_async(GLib.PRIORITY_DEFAULT, None, self._got_line)

    def _got_line(self, stream, result) -> None:
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:            # the engine is gone
            self.available = False
            while self._waiting:
                callback = self._waiting.popleft()
                if callback is not None:
                    callback(None)
            return
        if line.startswith("info") and " score " in line and "bound" not in line:
            parts = line.split()
            at = parts.index("score")
            try:
                kind, value = parts[at + 1], int(parts[at + 2])
            except (IndexError, ValueError):
                kind = None
            if kind == "cp":
                self._score = value
            elif kind == "mate":
                self._score = (10000 - abs(value)) * (1 if value > 0 else -1)
        elif line.startswith("bestmove"):
            parts = line.split()
            move = parts[1] if len(parts) > 1 and parts[1] != "(none)" else None
            callback = self._waiting.popleft() if self._waiting else None
            score, self._score = self._score, None
            if callback is not None:
                if getattr(callback, "wants_score", False):
                    callback(move, score)
                else:
                    callback(move)
        self._read()
