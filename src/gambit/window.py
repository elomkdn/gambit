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
    DetailsPane, Island, PanelChoices, PanelHeading, PanelKey, SPACER, Toast, ToastHost, TypeLabel, panel_list,
)

from .board import BoardView  # noqa: E402
from .engine import LEVEL, LEVELS, Engine  # noqa: E402
from .game import Game, Setup  # noqa: E402

APP_ID = "io.github.elomkdn.Gambit"
PHONE_MAX = 559
THINK_DELAY_MS = 220        # let the person's move land before the computer answers


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
        groups = (
            CommandGroup("", (
                Command("game.new", "New game…", self.open_new_game, "plus", shortcut=("Ctrl", "N")),
                Command("game.undo", "Undo move", self.undo, "undo-2", shortcut=("Ctrl", "Z")),
                Command("game.hint", "Show a good move", self.hint, "wand-sparkles", shortcut=("Ctrl", "H")),
                Command("game.flip", "Flip board", lambda: self.set_flipped(not self.board.flipped),
                        "arrow-up-down", shortcut=("Ctrl", "R")),
                Command("game.resign", "Resign…", self.ask_resign, "flag"),
            )),
            CommandGroup("", (Command("game.quit", "Quit Gambit", self.close, "log-out", shortcut=("Ctrl", "Q")),)),
        )
        super().__init__(application=application, app_id=APP_ID, title="Gambit", icon_name=APP_ID,
                         commands=CommandRegistry(groups), default_width=980, default_height=780,
                         minimum_width=360, minimum_height=480)

        self.game = Game.from_saved(self.recall("game"))
        self.board = BoardView(data_dir() / "pieces")
        self.board.choose_promotion = self._choose_promotion
        self.board.connect("move", lambda _b, uci: self.person_moved(uci))
        self.board.set_margin_bottom(84)        # room for the floating bar

        self.status = TypeLabel("", role="title-2")
        self.status.set_halign(Gtk.Align.CENTER)
        self.status.set_margin_top(18)
        self.status.update_property([Gtk.AccessibleProperty.LABEL], ["Game status"])
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        column.append(self.status)
        column.append(self.board)

        self.details = DetailsPane("Game", closable=True)
        self.corner = CornerPill(states=(
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
        self.refresh()
        self.details.show(open=False, subject=self.game)    # Information opens it; it shows this game
        self._maybe_think()
        self.connect("close-request", self._closing)
        from . import shots
        shots.prepare(self)

    # ── the game ──────────────────────────────────────────────────────

    def refresh(self, *, animate: chess.Move | None = None, before: chess.Board | None = None) -> None:
        board = self.game.board
        last = board.peek() if board.move_stack else None
        self.board.show(board, last=last, animate=animate, before=before)
        self.board.set_interactive(self.game.person_to_move and not self.engine.thinking)
        self.status.set_text(self.game.status(thinking=self.engine.thinking and not self.game.over))
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
        self.refresh()
        self._maybe_think()

    def hint(self) -> None:
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

    # ── the bar ───────────────────────────────────────────────────────

    def show_bar(self) -> None:
        game = self.game
        has_moves = bool(game.board.move_stack) or game.resigned is not None
        self._new_action = BarAction("plus", "New game", primary=True, panel=self._new_game_panel, key="new")
        items = [
            BarAction("undo-2", tooltip="Undo move", sensitive=has_moves, on_activate=self.undo),
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
        self.center.show_bar(items, more=more)

    def _new_game_panel(self):
        setup = self.game.setup
        opponent = PanelChoices((("computer", "Computer", "cpu"), ("human", "Two players", "users")),
                                selected=setup.opponent if self.engine.available else "human")
        side = PanelChoices((("white", "White"), ("black", "Black"), ("random", "Random")),
                            selected="white" if setup.human == chess.WHITE else "black")
        level = PanelChoices(tuple((item.key, item.label) for item in LEVELS), selected=setup.level)

        def start():
            human = {"white": chess.WHITE, "black": chess.BLACK}.get(side.selected, random.choice((True, False)))
            self.start_game(Setup(opponent.selected or "computer", human, level.selected or "casual"))

        rows = [PanelHeading("Play against"), opponent, PanelHeading("You play"), side,
                PanelHeading("Level"), level, PanelKey("Start game", icon="play", on_activate=start)]
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
        self.details.show(open=not self.details.shown, subject=self.game)
        self.show_bar()

    def _fill_details(self) -> None:
        self.details.clear()
        self.details.add_hero(self.game.players(), self.game.status())
        pairs = self.game.move_pairs()
        self.details.add_section("Moves")
        if pairs:
            self.details.add_facts([(f"{number}.", f"{white}    {black}".rstrip()) for number, white, black in pairs])
        else:
            self.details.add_facts([("", "No moves yet")])

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
