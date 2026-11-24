# SPDX-License-Identifier: GPL-3.0-or-later
"""Gambit's window: the board on one island, the bar for what you do in the game."""
from __future__ import annotations

import os
import random
from pathlib import Path

import chess
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from luma_appkit import (  # noqa: E402
    ActionCenter, AppWindow, BarAction, Command, CommandGroup, CommandRegistry, CornerPill, DestructiveDialog,
    DetailsPane, Island, ModeSwitch, PanelChoices, PanelHeading, PanelKey, SPACER, Toast, ToastHost, TypeLabel,
    panel_list,
)

from .board import BoardView  # noqa: E402
from .engine import LEVEL, LEVELS, Engine  # noqa: E402
from .game import COLOR_NAMES, Game, Setup  # noqa: E402
from .puzzle import START_RATING, PuzzleBook, PuzzleRun, rated  # noqa: E402
from .review import Openings, accuracy, review  # noqa: E402

APP_ID = "io.github.elomkdn.Gambit"
PHONE_MAX = 559
THINK_DELAY_MS = 220        # let the person's move land before the computer answers
PUZZLE_START_MS = 650       # the puzzle's position, a breath, then the opponent's move
PUZZLE_REPLY_MS = 420
MODES = (("play", "Play"), ("puzzles", "Puzzles"))
MOMENTS = 12                # key moments listed in a review; the rest are counted


def data_dir() -> Path:
    for candidate in (os.environ.get("GAMBIT_DATA"), "/app/share/gambit",
                      Path(__file__).resolve().parents[2] / "data"):
        if candidate and (Path(candidate) / "pieces" / "wK.svg").exists():
            return Path(candidate)
    raise FileNotFoundError("Gambit's pieces are missing")


class GambitWindow(AppWindow):
    def __init__(self, application):
        self.phone = False
        self.engine = Engine()
        self._think_source = 0
        self._puzzle_source = 0
        self.run: PuzzleRun | None = None
        self._rated = False
        self._note = None           # what the last puzzle move earned, shown until the next one
        self.verdicts = None        # the review of the finished game, once made
        self._review_token = 0      # a new game or an undo makes a running review stale
        self._review_progress = None
        groups = (
            CommandGroup("", (
                Command("mode.play", "Play", lambda: self.set_mode("play"), "gamepad-2", shortcut=("Ctrl", "1")),
                Command("mode.puzzles", "Puzzles", lambda: self.set_mode("puzzles"), "skip-forward",
                        shortcut=("Ctrl", "2")),
                Command("puzzle.next", "Next puzzle", self.next_puzzle, "skip-forward", shortcut=("Ctrl", "Right")),
                Command("puzzle.solution", "Show solution", self.show_solution, "eye"),
            )),
            CommandGroup("", (
                Command("game.new", "New game…", self.open_new_game, "plus", shortcut=("Ctrl", "N")),
                Command("game.undo", "Undo move", self.undo, "undo-2", shortcut=("Ctrl", "Z")),
                Command("game.hint", "Show a good move", self.hint, "wand-sparkles", shortcut=("Ctrl", "H")),
                Command("game.flip", "Flip board", lambda: self.set_flipped(not self.board.flipped),
                        "arrow-up-down", shortcut=("Ctrl", "R")),
                Command("game.resign", "Resign…", self.ask_resign, "flag"),
                Command("game.review", "Review game", self.start_review, "history"),
            )),
            CommandGroup("", (Command("game.quit", "Quit Gambit", self.close, "log-out", shortcut=("Ctrl", "Q")),)),
        )
        super().__init__(application=application, app_id=APP_ID, title="Gambit", icon_name=APP_ID,
                         commands=CommandRegistry(groups), default_width=980, default_height=780,
                         minimum_width=360, minimum_height=480)

        self.game = Game.from_saved(self.recall("game"))
        self.mode = self.recall("mode", "play") if self.recall("mode", "play") in dict(MODES) else "play"
        self.puzzles = PuzzleBook(data_dir() / "puzzles.json")
        self.openings = Openings(data_dir() / "openings.json")
        stats = self.recall("puzzle_stats", {})
        self.stats = {"rating": START_RATING, "played": 0, "solved": 0, "streak": 0, "seen": []}
        if isinstance(stats, dict):
            self.stats.update({k: v for k, v in stats.items() if k in self.stats})
        self.board = BoardView(data_dir() / "pieces")
        self.board.choose_promotion = self._choose_promotion
        self.board.connect("move", lambda _b, uci: self._board_moved(uci))
        self.board.set_margin_bottom(84)        # room for the floating bar

        self.status = TypeLabel("", role="title-2")
        self.status.set_halign(Gtk.Align.CENTER)
        self.status.set_margin_top(18)
        self.status.update_property([Gtk.AccessibleProperty.LABEL], ["Game status"])
        self.opening = TypeLabel("", role="caption")
        self.opening.set_halign(Gtk.Align.CENTER)
        self.opening.set_margin_top(2)
        self.opening.add_css_class("dim-label")
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        column.append(self.status)
        column.append(self.opening)
        column.append(self.board)

        self.details = DetailsPane("Game", closable=True)
        self.mode_switch = ModeSwitch(MODES, current=self.mode, on_change=self.set_mode, label="Mode")
        self.corner = CornerPill(modes=self.mode_switch, states=(
            ("arrow-up-down", "Flip board", bool(self.recall("flipped", self.game.setup.human == chess.BLACK)),
             self.set_flipped),
        ), info=self.details)
        self.corner.set_margin_top(12)
        self.corner.set_margin_end(12)
        overlay = Gtk.Overlay(child=column)
        overlay.add_overlay(self.corner)

        island = Island()
        island.set_hexpand(True)
        island.append(overlay)
        self.host = ToastHost(island)
        body = Gtk.Box(hexpand=True, vexpand=True)
        body.append(self.host)
        body.append(self.details)
        self.set_body(body)
        self.center = ActionCenter()
        self.center.attach(self.host)

        phone = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {PHONE_MAX}px"))
        phone.add_setter(self.corner, "visible", False)
        phone.connect("apply", lambda _b: self._set_phone(True))
        phone.connect("unapply", lambda _b: self._set_phone(False))
        self.add_breakpoint(phone)

        if not self.engine.start():
            self.game.setup.opponent = "human"
            GLib.idle_add(lambda: Toast.show(self.host, "The chess engine is missing: two-player games only",
                                             kind="warning") and False)
        self.board.set_flipped(bool(self.recall("flipped", self.game.setup.human == chess.BLACK)))
        self.details.show(open=False, subject=self.game)    # Information opens it; it shows this game or puzzle
        if self.mode == "puzzles":
            current = self.puzzles.by_id.get(self.recall("puzzle"))
            self._start_puzzle(current) if current else self.next_puzzle()
        else:
            self.refresh()
            self._maybe_think()
        self.connect("close-request", self._closing)
        from . import shots
        shots.prepare(self)

    # ── the game ──────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        if mode == self.mode or mode not in dict(MODES):
            return
        self.mode = mode
        self.remember("mode", mode)
        if self.mode_switch.current != mode:
            self.mode_switch.set_current(mode)
        if self.center.grown is not None:
            self.center.fold()
        if mode == "puzzles":
            if self._review_progress is not None:
                self._drop_review()
            self.engine.stop()
            self._cancel(think=True)
            if self.run is None:
                self.next_puzzle()
            else:
                self.board.set_flipped(self.run.player == chess.BLACK)
                self.refresh()
        else:
            self._cancel(puzzle=True)
            self.board.set_flipped(bool(self.recall("flipped", self.game.setup.human == chess.BLACK)))
            self.refresh()
            self._maybe_think()

    def _cancel(self, *, think=False, puzzle=False) -> None:
        if think and self._think_source:
            GLib.source_remove(self._think_source)
            self._think_source = 0
        if puzzle and self._puzzle_source:
            GLib.source_remove(self._puzzle_source)
            self._puzzle_source = 0

    def _board_moved(self, uci: str) -> None:
        (self.puzzle_moved if self.mode == "puzzles" else self.person_moved)(uci)

    def refresh(self, *, animate: chess.Move | None = None, before: chess.Board | None = None) -> None:
        if self.mode == "puzzles":
            self._refresh_puzzle(animate=animate, before=before)
            return
        board = self.game.board
        last = board.peek() if board.move_stack else None
        self.board.show(board, last=last, animate=animate, before=before)
        self.board.set_interactive(self.game.person_to_move and not self.engine.thinking)
        self.status.set_text(self.game.status(thinking=self.engine.thinking and not self.game.over))
        opening = self.openings.name(board)
        self.opening.set_text(opening[1] if opening else "")
        self.opening.set_visible(bool(opening))
        self.remember("game", self.game.saved())
        self.show_bar()
        self._fill_details()

    def person_moved(self, uci: str) -> None:
        if not self.game.person_to_move:
            return
        before = self.game.board.copy(stack=False)
        move = self.game.play(uci)
        if move is None:
            return
        self.refresh(animate=move, before=before)
        self._announce_end()
        self._maybe_think()

    def _maybe_think(self) -> None:
        if not self.game.computer_to_move or self.engine.thinking:
            return
        if self._think_source:
            GLib.source_remove(self._think_source)

        def think():
            self._think_source = 0
            if self.game.computer_to_move:
                level = LEVEL[self.game.setup.level]
                self.engine.think(self.game.moves, level, self._computer_moved)
                self.refresh()
            return False
        self._think_source = GLib.timeout_add(THINK_DELAY_MS, think)

    def _computer_moved(self, uci: str | None) -> None:
        if uci is None or not self.game.computer_to_move:
            self.refresh()
            return
        before = self.game.board.copy(stack=False)
        move = self.game.play(uci)
        self.refresh(animate=move, before=before)
        self._announce_end()

    def _announce_end(self) -> None:
        if self.game.over:
            Toast.show(self.host, self.game.status(), kind="done")

    def undo(self) -> None:
        if not self.game.board.move_stack and self.game.resigned is None:
            return
        self.engine.stop()
        if self._think_source:
            GLib.source_remove(self._think_source)
            self._think_source = 0
        self.game.undo()
        self._drop_review()
        self.refresh()
        self._maybe_think()

    def hint(self) -> None:
        if self.mode == "puzzles":
            self._puzzle_hint()
            return
        if not self.game.person_to_move or not self.engine.available:
            return
        self.status.set_text("Looking for a good move…")

        def found(uci):
            self.status.set_text(self.game.status())
            if uci and self.game.person_to_move:
                self.board.show_hint(chess.Move.from_uci(uci))
        self.engine.think(self.game.moves, LEVEL["master"], found, movetime=700, full_strength=True)

    def ask_resign(self) -> None:
        if self.game.over or not self.game.board.move_stack:
            return
        if self.center.grown is not None:
            self.center.fold()
        DestructiveDialog.in_bar(self.center, title="Resign this game?",
                                 body="It counts as a loss. Undo takes it back.", action="Resign",
                                 on_confirm=self._resign)

    def _resign(self) -> None:
        self.engine.stop()
        self.game.resign()
        self.refresh()
        self._announce_end()

    def start_game(self, setup: Setup) -> None:
        self.engine.stop()
        if self._think_source:
            GLib.source_remove(self._think_source)
            self._think_source = 0
        if setup.opponent == "computer" and not self.engine.available:
            setup.opponent = "human"
        self.game = Game(setup)
        self._drop_review()
        self.details.show(subject=self.game)
        self.set_flipped(setup.opponent == "computer" and setup.human == chess.BLACK)
        self.refresh()
        self._maybe_think()

    def set_flipped(self, flipped: bool) -> None:
        self.board.set_flipped(flipped)
        self.remember("flipped", flipped)
        button = self.corner.controls.get("states.0")
        if button is not None and button.get_active() != flipped:
            button.set_active(flipped)

    # ── puzzles ───────────────────────────────────────────────────────

    def next_puzzle(self) -> None:
        puzzle = self.puzzles.pick(self.stats["rating"], self.stats["seen"])
        if puzzle is None:
            Toast.show(self.host, "No puzzles found", kind="warning")
            return
        self._start_puzzle(puzzle)

    def _start_puzzle(self, puzzle) -> None:
        self._cancel(puzzle=True)
        self.run = PuzzleRun(puzzle)
        self._rated = False
        self._note = None
        self.stats["seen"] = (self.stats["seen"] + [puzzle.id])[-400:]
        self.remember("puzzle", puzzle.id)
        self._save_stats()
        self.board.set_flipped(self.run.player == chess.BLACK)
        self.details.show(subject=self.run)
        self.refresh()
        self._puzzle_source = GLib.timeout_add(PUZZLE_START_MS, self._puzzle_opponent)

    def _puzzle_opponent(self):
        self._puzzle_source = 0
        run = self.run
        if run is None or self.mode != "puzzles":
            return False
        before = run.board.copy(stack=False)
        move = run.opponent_move()
        if move is not None:
            self.refresh(animate=move, before=before)
        return False

    def puzzle_moved(self, uci: str) -> None:
        run = self.run
        if run is None or not run.your_turn:
            return
        before = run.board.copy(stack=False)
        result = run.try_move(uci)
        if result == "wrong":
            self._rate(False)
            self._note = "Not quite · try again"
            self.refresh()
            return
        move = run.board.peek()
        if result == "right":
            self._note = "Right · keep going"
            self.refresh(animate=move, before=before)
            self._puzzle_source = GLib.timeout_add(PUZZLE_REPLY_MS, self._puzzle_opponent)
            return
        change = self._rate(True)
        self._note = "Solved"
        self.refresh(animate=move, before=before)
        words = f"Solved · rating {round(self.stats['rating'])}"
        if change:
            words += f" ({'+' if change > 0 else ''}{round(change)})"
        Toast.show(self.host, words, kind="done")

    def _rate(self, won: bool) -> float:
        """Count the puzzle once: the first mistake, or solving it clean. A hint counts for nothing."""
        run = self.run
        if self._rated or run is None:
            return 0.0
        self._rated = True
        if run.helped:
            return 0.0
        before = self.stats["rating"]
        self.stats["rating"] = rated(before, run.puzzle, won, self.stats["played"])
        self.stats["played"] += 1
        self.stats["solved"] += 1 if won else 0
        self.stats["streak"] = self.stats["streak"] + 1 if won else 0
        self._save_stats()
        return self.stats["rating"] - before

    def _save_stats(self) -> None:
        self.remember("puzzle_stats", dict(self.stats))

    def _puzzle_hint(self) -> None:
        run = self.run
        if run is None or not run.your_turn:
            return
        move = run.next_expected()
        run.helped = True
        if self.board.selected != move.from_square and self.board.hint is None:
            self.board.show_selection(move.from_square)      # first, which piece
        else:
            self.board.show_hint(move)                        # then, where it goes
        self.show_bar()

    def show_solution(self) -> None:
        run = self.run
        if self.mode != "puzzles" or run is None or run.solved or run.shown:
            return
        self._cancel(puzzle=True)
        self._rate(False)
        self._note = "The solution"
        self._play_solution()

    def _play_solution(self):
        self._puzzle_source = 0
        run = self.run
        if run is None or self.mode != "puzzles":
            return False
        before = run.board.copy(stack=False)
        move = run.show_next()
        if move is None:
            self.refresh()
            return False
        self.refresh(animate=move, before=before)
        self._puzzle_source = GLib.timeout_add(700, self._play_solution)
        return False

    def _refresh_puzzle(self, *, animate=None, before=None) -> None:
        run = self.run
        if run is None:
            return
        board = run.board
        last = board.peek() if board.move_stack else None
        self.board.show(board, last=last, animate=animate, before=before)
        self.board.set_interactive(run.your_turn)
        if run.your_turn and self._note in (None, "Right · keep going", "Not quite · try again"):
            side = COLOR_NAMES[run.player]
            status = self._note or f"Find the best move for {side}"
        elif run.solved:
            status = "Solved"
        elif run.shown:
            status = "The solution"
        else:
            status = self._note or "Watch the opponent's move"
        self.status.set_text(status)
        self.opening.set_visible(False)
        self.show_bar()
        self._fill_details()

    # ── the review ────────────────────────────────────────────────────

    def start_review(self) -> None:
        game = self.game
        if self.mode != "play" or not game.over or not game.board.move_stack or not self.engine.available:
            return
        if self._review_progress is not None:       # already under way
            return
        if self.verdicts is not None:
            self.details.show(open=True, subject=game)
            return
        self._review_token += 1
        token = self._review_token
        moves = list(game.board.move_stack)
        ucis = [move.uci() for move in moves]
        count = len(moves) + 1
        scores, bests = [None] * count, [None] * count
        final = game.board
        if final.is_checkmate():
            scores[-1] = -10000.0
        elif final.is_game_over(claim_draw=True):
            scores[-1] = 0.0
        todo = [i for i in range(count) if not (i == count - 1 and scores[i] is not None)]
        progress = Toast.progress(self.host, "Reviewing the game", count=f"0 of {len(todo)}")
        self._review_progress = progress

        def next_position(done):
            if token != self._review_token:
                progress.finish(None)
                return
            if done == len(todo):
                self.verdicts = review(moves, scores, bests)
                self._review_progress = None
                progress.finish("Review ready")
                self.details.show(open=True, subject=self.game)
                self.refresh()
                return
            index = todo[done]

            def answered(best, score):
                bests[index], scores[index] = best, score
                progress.update("Reviewing the game", count=f"{done + 1} of {len(todo)}")
                next_position(done + 1)
            self.engine.analyse(ucis[:index], answered, movetime=300)
        next_position(0)

    def _drop_review(self) -> None:
        """Forget the review, and stop one that is running: the game it was about has changed."""
        self.verdicts = None
        self._review_token += 1
        if self._review_progress is not None:
            self._review_progress.finish(None)
            self._review_progress = None
            self.engine.stop()

    def _review_facts(self) -> None:
        verdicts = self.verdicts
        if not verdicts:
            return
        game = self.game
        names = {True: "White", False: "Black"}
        if game.against_computer:
            names = {game.setup.human: "You", not game.setup.human: "Gambit"}
        self.details.add_section("Accuracy")
        self.details.add_facts([(names[white], f"{accuracy(verdicts, white)}%")
                                for white in (True, False) if accuracy(verdicts, white) is not None])
        moments = [v for v in verdicts if v.label]
        self.details.add_section("Key moments")
        if not moments:
            self.details.add_facts([("", "No inaccuracies, mistakes or blunders")])
            return
        rows = [(f"{v.number} {v.san}", v.label + (f" · better was {v.best_san}" if v.best_san else ""))
                for v in moments[:MOMENTS]]
        if len(moments) > MOMENTS:
            rows.append(("", f"And {len(moments) - MOMENTS} more"))
        self.details.add_facts(rows)

    # ── the bar ───────────────────────────────────────────────────────

    def show_bar(self) -> None:
        if self.mode == "puzzles":
            self._show_puzzle_bar()
            return
        game = self.game
        has_moves = bool(game.board.move_stack) or game.resigned is not None
        self._new_action = BarAction("plus", "New game", primary=True, panel=self._new_game_panel, key="new")
        items = [
            BarAction("undo-2", tooltip="Undo move", sensitive=has_moves, on_activate=self.undo),
        ]
        if game.over and game.board.move_stack and self.engine.available:
            items.append(BarAction("history", "Review", on_activate=self.start_review))
        items += [
            BarAction("wand-sparkles", tooltip="Show a good move",
                      sensitive=game.person_to_move and self.engine.available, on_activate=self.hint),
            SPACER,
            self._new_action,
        ]
        more = []
        if not game.over and game.board.move_stack:
            more.append(BarAction("flag", "Resign…", danger=True, on_activate=self.ask_resign))
        if self.phone:      # the corner steps aside on a phone, so its choices come here
            more += [BarAction("arrow-up-down", "Flip board", active=self.board.flipped,
                               on_activate=lambda: (self.set_flipped(not self.board.flipped), self.show_bar())),
                     BarAction("list-ordered", "Moves", active=self.details.shown,
                               on_activate=self.toggle_details)]
        self._show(items, more)

    def _show_puzzle_bar(self) -> None:
        run = self.run
        items = [BarAction("wand-sparkles", tooltip="Show a hint", sensitive=bool(run and run.your_turn),
                           on_activate=self.hint),
                 SPACER,
                 BarAction("skip-forward", "Next puzzle", primary=True, on_activate=self.next_puzzle)]
        more = []
        if run is not None and not run.solved and not run.shown:
            more.append(BarAction("eye", "Show solution", on_activate=self.show_solution))
        if self.phone:
            more.append(BarAction("info", "Puzzle details", active=self.details.shown,
                                  on_activate=self.toggle_details))
        self._show(items, more)

    def _show(self, items, more) -> None:
        """On a phone the corner steps aside, so Play and Puzzles start the bar."""
        modes = ModeSwitch(MODES, current=self.mode, on_change=self.set_mode, label="Mode") if self.phone else None
        self.center.show_bar(items, more=more, modes=modes)

    def _new_game_panel(self):
        setup = self.game.setup
        opponent = PanelChoices((("computer", "Computer", "cpu"), ("human", "Two players", "users")),
                                selected=setup.opponent if self.engine.available else "human")
        side = PanelChoices((("white", "White"), ("black", "Black"), ("random", "Random")),
                            selected="white" if setup.human == chess.WHITE else "black")
        level = PanelChoices(tuple((item.key, item.label) for item in LEVELS), selected=setup.level)
        computer_only = [PanelHeading("You play"), side, PanelHeading("Level"), level]

        def show_computer_rows(key):        # sides and levels mean nothing between two people
            for row in computer_only:
                row.set_visible(key == "computer")
        opponent.on_choose = show_computer_rows
        show_computer_rows(opponent.selected)

        def start():
            human = {"white": chess.WHITE, "black": chess.BLACK}.get(side.selected, random.choice((True, False)))
            self.start_game(Setup(opponent.selected or "computer", human, level.selected or "casual"))

        rows = [PanelHeading("Play against"), opponent, *computer_only,
                PanelKey("Start game", icon="play", on_activate=start)]
        return panel_list(rows, label="New game")

    def open_new_game(self) -> None:
        self.center.grow("new", self._new_game_panel(), anchor=self._bar_widget(self._new_action))

    def _bar_widget(self, item):
        child = self.center.bar_row.get_first_child()
        while child is not None:
            if getattr(child, "bar_item", None) is item:
                return getattr(child, "bar_button", child)
            child = child.get_next_sibling()
        return None

    def _choose_promotion(self, origin, target, done) -> None:
        kinds = {"queen": chess.QUEEN, "rook": chess.ROOK, "bishop": chess.BISHOP, "knight": chess.KNIGHT}
        choices = PanelChoices(tuple((key, key.capitalize()) for key in kinds), selected="queen", closes=True,
                               on_choose=lambda key: done(kinds[key]))
        self.center.grow("promote", panel_list([PanelHeading("Promote the pawn to"), choices], label="Promotion"))

    # ── details ───────────────────────────────────────────────────────

    def toggle_details(self) -> None:
        subject = self.run if self.mode == "puzzles" and self.run is not None else self.game
        self.details.show(open=not self.details.shown, subject=subject)
        self.show_bar()

    def _fill_details(self) -> None:
        self.details.set_title("Puzzle" if self.mode == "puzzles" else "Game")
        if self.mode == "puzzles":
            self._fill_puzzle_details()
            return
        self.details.clear()
        self.details.add_hero(self.game.players(), self.game.status())
        opening = self.openings.name(self.game.board)
        if opening:
            self.details.add_facts([("Opening", opening[1])])
        self._review_facts()
        pairs = self.game.move_pairs()
        self.details.add_section("Moves")
        if pairs:
            self.details.add_facts([(f"{number}.", f"{white}    {black}".rstrip()) for number, white, black in pairs])
        else:
            self.details.add_facts([("", "No moves yet")])

    def _fill_puzzle_details(self) -> None:
        run = self.run
        self.details.clear()
        if run is None:
            return
        puzzle = run.puzzle
        self.details.add_hero(f"Puzzle rated {puzzle.rating}", " · ".join(puzzle.theme_words()) or "Find the best move")
        stats = self.stats
        self.details.add_section("You")
        self.details.add_facts([
            ("Your rating", str(round(stats["rating"]))),
            ("Solved", f"{stats['solved']} of {stats['played']}"),
            ("In a row", str(stats["streak"])),
        ])
        self.details.add_section("Source")
        self.details.add_facts([("Lichess puzzle", puzzle.id)])

    def _set_phone(self, phone: bool) -> None:
        self.phone = phone
        self.board.set_margin_bottom(76 if phone else 84)
        self.show_bar()

    def _closing(self, *_args):
        self.remember("game", self.game.saved())
        self.engine.quit()
        return False


class GambitApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        (self.props.active_window or GambitWindow(self)).present()


def main(argv=None):
    return GambitApplication().run(argv or [])
