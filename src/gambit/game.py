# SPDX-License-Identifier: GPL-3.0-or-later
"""A game: who plays which side, the moves so far, and how it stands, in words.

No GTK here; the rules are python-chess's.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import chess

from .engine import LEVEL

COLOR_NAMES = {chess.WHITE: "White", chess.BLACK: "Black"}


@dataclass
class Setup:
    opponent: str = "computer"          # "computer" or "human" (two people on one device)
    human: bool = chess.WHITE           # the side the person plays against the computer
    level: str = "casual"

    def saved(self) -> dict:
        return {"opponent": self.opponent, "human": "white" if self.human else "black", "level": self.level}

    @classmethod
    def from_saved(cls, value) -> "Setup":
        if not isinstance(value, dict):
            return cls()
        opponent = value.get("opponent") if value.get("opponent") in ("computer", "human") else "computer"
        level = value.get("level") if value.get("level") in LEVEL else "casual"
        return cls(opponent, value.get("human") != "black", level)


@dataclass
class Game:
    setup: Setup = field(default_factory=Setup)
    board: chess.Board = field(default_factory=chess.Board)
    resigned: bool | None = None        # the side that resigned

    # ── who moves ─────────────────────────────────────────────────────

    @property
    def against_computer(self) -> bool:
        return self.setup.opponent == "computer"

    @property
    def over(self) -> bool:
        return self.resigned is not None or self.board.is_game_over(claim_draw=True)

    @property
    def computer_to_move(self) -> bool:
        return self.against_computer and not self.over and self.board.turn != self.setup.human

    @property
    def person_to_move(self) -> bool:
        return not self.over and not self.computer_to_move

    @property
    def moves(self) -> list[str]:
        return [move.uci() for move in self.board.move_stack]

    # ── changing it ───────────────────────────────────────────────────

    def play(self, uci: str) -> chess.Move | None:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return None
        if move not in self.board.legal_moves:
            return None
        self.board.push(move)
        return move

    def undo(self) -> int:
        """Take back the person's last move (and the computer's reply). Returns how many moves went."""
        if self.resigned is not None:
            self.resigned = None
        count = 0
        if self.against_computer:
            # Back to the person's turn, with at least their own move taken back.
            while self.board.move_stack and (count == 0 or self.board.turn != self.setup.human):
                self.board.pop()
                count += 1
        elif self.board.move_stack:
            self.board.pop()
            count = 1
        return count

    def resign(self) -> None:
        self.resigned = self.setup.human if self.against_computer else self.board.turn

    # ── in words ──────────────────────────────────────────────────────

    def players(self) -> str:
        if not self.against_computer:
            return "Two players"
        level = LEVEL[self.setup.level].label
        return f"You ({COLOR_NAMES[self.setup.human]}) against Gambit · {level}"

    def status(self, thinking: bool = False) -> str:
        board = self.board
        if self.resigned is not None:
            if self.against_computer:
                return "You resigned"
            return f"{COLOR_NAMES[self.resigned]} resigned · {COLOR_NAMES[not self.resigned]} wins"
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            return self._result(outcome)
        if thinking or self.computer_to_move:
            return "Gambit is thinking…"
        check = board.is_check()
        if self.against_computer:
            return "Check · your move" if check else "Your move"
        side = COLOR_NAMES[board.turn]
        return f"Check · {side} to move" if check else f"{side} to move"

    def _result(self, outcome: chess.Outcome) -> str:
        reasons = {
            chess.Termination.STALEMATE: "Draw · stalemate",
            chess.Termination.INSUFFICIENT_MATERIAL: "Draw · not enough pieces to mate",
            chess.Termination.SEVENTYFIVE_MOVES: "Draw · seventy-five moves without a capture",
            chess.Termination.FIVEFOLD_REPETITION: "Draw · the same position five times",
            chess.Termination.FIFTY_MOVES: "Draw · fifty moves without a capture",
            chess.Termination.THREEFOLD_REPETITION: "Draw · the same position three times",
        }
        if outcome.winner is None:
            return reasons.get(outcome.termination, "Draw")
        if self.against_computer:
            return "Checkmate · you win" if outcome.winner == self.setup.human else "Checkmate · Gambit wins"
        return f"Checkmate · {COLOR_NAMES[outcome.winner]} wins"

    def move_pairs(self) -> list[tuple[int, str, str]]:
        """The moves in notation, two to a line: [(1, "e4", "e5"), (2, "Nf3", "")]."""
        replay = chess.Board()
        pairs = []
        for index, move in enumerate(self.board.move_stack):
            san = replay.san(move)
            replay.push(move)
            if index % 2 == 0:
                pairs.append([index // 2 + 1, san, ""])
            else:
                pairs[-1][2] = san
        return [tuple(pair) for pair in pairs]

    # ── kept between runs ─────────────────────────────────────────────

    def saved(self) -> dict:
        return {"setup": self.setup.saved(), "moves": self.moves,
                "resigned": None if self.resigned is None else ("white" if self.resigned else "black")}

    @classmethod
    def from_saved(cls, value) -> "Game":
        game = cls(Setup.from_saved(value.get("setup") if isinstance(value, dict) else None))
        if isinstance(value, dict):
            for uci in value.get("moves", []) if isinstance(value.get("moves"), list) else []:
                if not isinstance(uci, str) or game.play(uci) is None:
                    break
            if value.get("resigned") in ("white", "black"):
                game.resigned = value["resigned"] == "white"
        return game
