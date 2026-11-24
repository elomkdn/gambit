# SPDX-License-Identifier: GPL-3.0-or-later
"""Puzzles from the Lichess puzzle database (CC0), and a rating that follows you.

A puzzle starts one move early: the opponent's move plays itself, then you find
yours; the opponent answers, and so on to the end. Any move that mates is
right, as on Lichess. Solving moves your rating up and failing moves it down by
how surprising the result was (Elo); a puzzle you needed a hint for counts for
nothing either way.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import chess

THEMES = {
    "mateIn1": "Mate in 1", "mateIn2": "Mate in 2", "mateIn3": "Mate in 3", "mateIn4": "Mate in 4",
    "mateIn5": "Mate in 5", "fork": "Fork", "pin": "Pin", "skewer": "Skewer", "sacrifice": "Sacrifice",
    "discoveredAttack": "Discovered attack", "discoveredCheck": "Discovered check", "doubleCheck": "Double check",
    "deflection": "Deflection", "attraction": "Attraction", "clearance": "Clearance", "interference": "Interference",
    "hangingPiece": "Hanging piece", "trappedPiece": "Trapped piece", "capturingDefender": "Remove the defender",
    "backRankMate": "Back-rank mate", "smotheredMate": "Smothered mate", "anastasiaMate": "Anastasia's mate",
    "arabianMate": "Arabian mate", "bodenMate": "Boden's mate", "hookMate": "Hook mate",
    "doubleBishopMate": "Two-bishop mate", "dovetailMate": "Dovetail mate", "promotion": "Promotion",
    "underPromotion": "Underpromotion", "advancedPawn": "Advanced pawn", "quietMove": "Quiet move",
    "defensiveMove": "Defensive move", "zugzwang": "Zugzwang", "intermezzo": "In-between move",
    "xRayAttack": "X-ray", "exposedKing": "Exposed king", "kingsideAttack": "Kingside attack",
    "queensideAttack": "Queenside attack", "enPassant": "En passant", "castling": "Castling",
    "rookEndgame": "Rook endgame", "pawnEndgame": "Pawn endgame", "queenEndgame": "Queen endgame",
    "bishopEndgame": "Bishop endgame", "knightEndgame": "Knight endgame", "queenRookEndgame": "Queen and rook endgame",
    "endgame": "Endgame", "opening": "Opening",
}
START_RATING = 1200


@dataclass(frozen=True)
class Puzzle:
    id: str
    fen: str
    moves: tuple[str, ...]
    rating: int
    themes: tuple[str, ...]

    def theme_words(self, most: int = 3) -> list[str]:
        named = [THEMES[t] for t in self.themes if t in THEMES and t not in ("endgame", "opening")]
        phase = [THEMES[t] for t in self.themes if t in ("endgame", "opening")]
        return (named + phase)[:most]

    @property
    def url(self) -> str:
        return f"https://lichess.org/training/{self.id}"


class PuzzleBook:
    def __init__(self, path: Path):
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))["puzzles"]
        except (OSError, ValueError, KeyError):
            rows = []
        self.puzzles = [Puzzle(r[0], r[1], tuple(r[2].split()), int(r[3]), tuple(r[4].split())) for r in rows]
        self.by_id = {p.id: p for p in self.puzzles}

    def pick(self, rating: float, seen=()) -> Puzzle | None:
        """A puzzle near `rating` that was not seen lately: one of the closest few, at random."""
        fresh = [p for p in self.puzzles if p.id not in set(seen)] or self.puzzles
        if not fresh:
            return None
        closest = sorted(fresh, key=lambda p: abs(p.rating - rating))[:24]
        return random.choice(closest)


@dataclass
class PuzzleRun:
    puzzle: Puzzle
    board: chess.Board = field(init=False)
    step: int = 0                 # the index of the next move in the solution
    failed: bool = False
    helped: bool = False
    solved: bool = False
    shown: bool = False           # the solution was shown

    def __post_init__(self):
        self.board = chess.Board(self.puzzle.fen)

    @property
    def player(self) -> bool:
        """The side you play: the one to move after the opponent's first move."""
        return not chess.Board(self.puzzle.fen).turn

    @property
    def your_turn(self) -> bool:
        return not self.solved and not self.shown and self.step % 2 == 1 and self.step < len(self.puzzle.moves)

    def opponent_move(self) -> chess.Move | None:
        """Play the opponent's next move (the first one, or the answer to yours)."""
        if self.solved or self.step >= len(self.puzzle.moves) or self.step % 2 == 1:
            return None
        move = chess.Move.from_uci(self.puzzle.moves[self.step])
        self.board.push(move)
        self.step += 1
        return move

    def try_move(self, uci: str) -> str:
        """"right" (the opponent answers next), "solved", or "wrong" (the board stays as it was)."""
        if not self.your_turn:
            return "wrong"
        move = chess.Move.from_uci(uci)
        if move not in self.board.legal_moves:
            return "wrong"
        expected = self.puzzle.moves[self.step]
        self.board.push(move)
        if uci == expected or self.board.is_checkmate():
            self.step += 1
            if self.step >= len(self.puzzle.moves) or self.board.is_checkmate():
                self.solved = True
                return "solved"
            return "right"
        self.board.pop()
        self.failed = True
        return "wrong"

    def next_expected(self) -> chess.Move | None:
        if self.step < len(self.puzzle.moves):
            return chess.Move.from_uci(self.puzzle.moves[self.step])
        return None

    def show_next(self) -> chess.Move | None:
        """Play the next move of the solution, whoever's it is."""
        move = self.next_expected()
        if move is None:
            return None
        self.shown = True
        self.board.push(move)
        self.step += 1
        return move


def rated(rating: float, puzzle: Puzzle, won: bool, played: int) -> float:
    """Elo: the step shrinks as you settle in (K 48 for the first 20 puzzles, then 24)."""
    k = 48 if played < 20 else 24
    expected = 1 / (1 + 10 ** ((puzzle.rating - rating) / 400))
    return max(400.0, min(3000.0, rating + k * ((1 if won else 0) - expected)))
