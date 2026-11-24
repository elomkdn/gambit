# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening names, and the review of a finished game: what each move cost.

Openings come from Lichess's chess-openings list (CC0), keyed by the position a
line reaches, so a transposition still finds its name. The review measures each
move by the winning chances it gave away, as Lichess does: a drop of 0.1 is an
inaccuracy, 0.2 a mistake, 0.3 a blunder (on a scale from -1 to 1), and accuracy
is Lichess's curve of the same drop.

Lichess's curve was fitted to newer Stockfish, whose pawn is worth about twice
Stockfish 11's: 11 gives the starting position +0.5 to +0.8, the newer ones about
+0.2. Without halving its scores, 1.f3 would count as a blunder.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import chess

ENGINE_PAWN = 0.5       # one Stockfish 11 centipawn, in the centipawns Lichess's curve expects


class Openings:
    def __init__(self, path: Path):
        try:
            self.table = json.loads(Path(path).read_text(encoding="utf-8"))["openings"]
        except (OSError, ValueError, KeyError):
            self.table = {}

    def name(self, board: chess.Board) -> tuple[str, str] | None:
        """The deepest named opening along the game: (ECO code, name)."""
        replay = board.copy()
        while True:
            found = self.table.get(replay.epd())
            if found:
                return found[0], found[1]
            if not replay.move_stack:
                return None
            replay.pop()


def chances(cp: float) -> float:
    """Winning chances from -1 to 1 for a Stockfish 11 score in centipawns (Lichess's curve)."""
    return 2 / (1 + math.exp(-0.00368208 * cp * ENGINE_PAWN)) - 1


@dataclass(frozen=True)
class Verdict:
    ply: int            # 0 for White's first move
    san: str
    best_san: str | None
    drop: float         # winning chances given away, 0 to 2
    label: str | None   # "Inaccuracy", "Mistake", "Blunder" or None

    @property
    def white(self) -> bool:
        return self.ply % 2 == 0

    @property
    def number(self) -> str:
        return f"{self.ply // 2 + 1}{'.' if self.white else '…'}"


def review(moves: list[chess.Move], scores: list[float | None], bests: list[str | None]) -> list[Verdict]:
    """`scores[i]` and `bests[i]` are the engine's view of the position after `i` moves, for the side to move."""
    board = chess.Board()
    verdicts = []
    for ply, move in enumerate(moves):
        before, after = scores[ply], scores[ply + 1]
        best = bests[ply]
        best_san = board.san(chess.Move.from_uci(best)) if best else None
        san = board.san(move)
        board.push(move)
        if before is None or after is None:
            verdicts.append(Verdict(ply, san, best_san, 0.0, None))
            continue
        drop = max(0.0, chances(before) - chances(-after))
        label = "Blunder" if drop >= 0.3 else "Mistake" if drop >= 0.2 else "Inaccuracy" if drop >= 0.1 else None
        if best_san == san:
            label = None
        verdicts.append(Verdict(ply, san, best_san, drop, label))
    return verdicts


def accuracy(verdicts: list[Verdict], white: bool) -> int | None:
    """Lichess's move accuracy, averaged over one side's moves, in percent."""
    values = []
    for verdict in verdicts:
        if verdict.white != white:
            continue
        win_drop = verdict.drop * 50          # the drop in win percentage points
        values.append(max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * win_drop) - 3.1669)))
    return round(sum(values) / len(values)) if values else None
