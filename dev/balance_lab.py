"""Balance Lab -- edit every tuning lever in the game, then measure the result.

    python dev/balance_lab.py

Two panes. On the left, every lever `app/core/tuning.py` knows about, grouped
the way the source groups them. On the right, the ones for whatever you picked,
each showing its current value and what the source default was. Edits apply to
the live tables IMMEDIATELY -- which is the point, because the tournament at the
bottom runs in this same process and therefore measures exactly what you just
typed, with no save, reload or restart in between.

Save writes only the levers that DIFFER from source defaults, to
`dev/balance.json`. The game applies that file at startup (see
app.core.tuning.load), so a set of numbers you like here is a set of numbers the
game plays with. Packaged builds do not ship `dev/`, so a release always runs on
source defaults.

Reading the tournament numbers:
  * Watch the SPREAD (best minus worst), not any one species' win rate. That is
    the number balance work actually moves.
  * At 3 seeds a species plays 24 games, so anything under ~10-15 points is
    noise. Matchups here are near-deterministic per seed, so small samples look
    far more decisive than they are.
  * Isolate mode runs a control with nobody's signature units and then one run
    per species. Turning several changes on at once produces a number no amount
    of staring can attribute.
"""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.battle import unit_types
from app.core import tuning
from app.ui import theme
from app.world import lexicon

import tournament as T

CHANGED = "• Changed"          # pseudo-section, always first in the tree
ROW_PAD = 3


class BalanceLab(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Shapes of War -- Balance Lab")
        self.geometry("1200x820")
        self.configure(bg=theme.BG)
        self._rows = {}          # path -> (StringVar, entry, default_label)
        self._current = None     # (section_key, group) currently shown
        self._log_q = queue.Queue()
        self._running = False
        self._build()
        self._populate_tree()
        tuning.load(quiet=True)
        self._refresh_tree_marks()
        self._select_first()
        self.after(120, self._drain_log)

    # --- layout ---------------------------------------------------------------
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=theme.PANEL, foreground=theme.INK,
                        fieldbackground=theme.PANEL, borderwidth=0, rowheight=22)
        style.map("Treeview", background=[("selected", theme.ACCENT)],
                  foreground=[("selected", "#06121f")])

        outer = tk.PanedWindow(self, orient="horizontal", bg=theme.BG,
                               sashwidth=6, bd=0)
        outer.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        left = tk.Frame(outer, bg=theme.PANEL)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        bar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        outer.add(left, minsize=250, width=290)

        right = tk.Frame(outer, bg=theme.BG)
        self.note = tk.Label(right, text="", bg=theme.BG, fg=theme.MUTED,
                             font=theme.FONT, justify="left", anchor="w",
                             wraplength=780)
        self.note.pack(fill="x", padx=10, pady=(4, 8))

        # Canvas + inner frame: Tk has no scrollable Frame, and a section can be
        # forty rows long.
        wrap = tk.Frame(right, bg=theme.BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=theme.BG, highlightthickness=0)
        fbar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=fbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        fbar.pack(side="right", fill="y")
        self.form = tk.Frame(self.canvas, bg=theme.BG)
        self._form_win = self.canvas.create_window((0, 0), window=self.form,
                                                   anchor="nw")
        self.form.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._form_win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        outer.add(right, minsize=520)

        self._build_bottom()

    def _build_bottom(self):
        bottom = tk.Frame(self, bg=theme.PANEL)
        bottom.pack(fill="x", side="bottom")

        row = tk.Frame(bottom, bg=theme.PANEL)
        row.pack(fill="x", padx=10, pady=8)

        def button(parent, text, cmd, accent=False):
            return tk.Button(parent, text=text, command=cmd, relief="flat",
                             font=theme.FONT, padx=10,
                             bg=theme.ACCENT if accent else "#232a36",
                             fg="#06121f" if accent else theme.INK,
                             activebackground=theme.ACCENT)

        button(row, "Save", self._save).pack(side="left")
        button(row, "Reload file", self._reload).pack(side="left", padx=(6, 0))
        button(row, "Reset all", self._reset_all).pack(side="left", padx=(6, 0))
        self.status = tk.Label(row, text="", bg=theme.PANEL, fg=theme.MUTED,
                               font=theme.FONT)
        self.status.pack(side="left", padx=12)

        tk.Label(row, text="seeds", bg=theme.PANEL, fg=theme.MUTED,
                 font=theme.FONT).pack(side="left", padx=(16, 4))
        self.seeds = tk.Spinbox(row, from_=1, to=15, width=3, font=theme.FONT,
                                bg="#232a36", fg=theme.INK, relief="flat",
                                buttonbackground="#232a36",
                                insertbackground=theme.INK)
        self.seeds.delete(0, "end")
        self.seeds.insert(0, "3")
        self.seeds.pack(side="left")

        self.mode = tk.StringVar(value="standard")
        for label, value in (("standard", "standard"), ("A/B specials", "ab"),
                             ("isolate", "isolate")):
            tk.Radiobutton(row, text=label, value=value, variable=self.mode,
                           bg=theme.PANEL, fg=theme.INK, selectcolor="#232a36",
                           activebackground=theme.PANEL,
                           activeforeground=theme.INK,
                           font=theme.FONT).pack(side="left", padx=(8, 0))

        self.run_btn = button(row, "Run tournament", self._run_tournament,
                              accent=True)
        self.run_btn.pack(side="left", padx=(14, 0))

        self.log = tk.Text(bottom, height=9, bg=theme.CANVAS, fg=theme.INK,
                           insertbackground=theme.INK, relief="flat",
                           font=("Consolas", 9), wrap="none")
        self.log.pack(fill="x", padx=10, pady=(0, 10))
        self.log.tag_configure("dim", foreground=theme.MUTED)
        self.log.tag_configure("good", foreground=theme.GOOD)
        self.log.tag_configure("bad", foreground=theme.BAD)
        self._say("Edits apply to the live tables at once -- Run tournament "
                  "measures exactly what is on screen.\n", "dim")

    def _on_wheel(self, event):
        if self.canvas.winfo_containing(event.x_root, event.y_root) is None:
            return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # --- tree -----------------------------------------------------------------
    def _populate_tree(self):
        self.tree.insert("", "end", iid=CHANGED, text=CHANGED)
        for section in tuning.SECTIONS:
            self.tree.insert("", "end", iid=section.key, text=section.label,
                             open=False)
            groups = []
            for path, _s, group, _k, _v in tuning.levers():
                if not path.startswith(section.key + "."):
                    continue
                if group and group not in groups:
                    groups.append(group)
            for group in groups:
                label = section.group_labels.get(group, group)
                self.tree.insert(section.key, "end",
                                 iid=f"{section.key}/{group}", text=label)

    def _refresh_tree_marks(self):
        """Mark every group holding an edit, so a change made twenty minutes
        ago is still findable without remembering where it was."""
        changed = tuning.changes()
        touched = set()
        for path in changed:
            section_key, _, rest = path.partition(".")
            group = rest.rpartition(".")[0]
            touched.add(section_key)
            if group:
                touched.add(f"{section_key}/{group}")
        for section in tuning.SECTIONS:
            self._mark(section.key, section.label, section.key in touched)
            for iid in self.tree.get_children(section.key):
                group = iid.split("/", 1)[1]
                label = section.group_labels.get(group, group)
                self._mark(iid, label, iid in touched)
        self.tree.item(CHANGED, text=f"{CHANGED} ({len(changed)})")
        self.status.config(
            text=f"{len(changed)} lever(s) changed from source defaults"
            if changed else "matching source defaults")

    def _mark(self, iid, label, on):
        self.tree.item(iid, text=("* " + label) if on else label)

    def _select_first(self):
        first = tuning.SECTIONS[0].key
        self.tree.item(first, open=True)
        kids = self.tree.get_children(first)
        target = kids[0] if kids else first
        self.tree.selection_set(target)
        self.tree.see(target)

    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        if sel:
            self._show(sel[0])

    # --- form -----------------------------------------------------------------
    def _show(self, iid):
        self._current = iid
        for child in self.form.winfo_children():
            child.destroy()
        self._rows.clear()

        if iid == CHANGED:
            self.note.config(text="Everything differing from the source "
                                  "defaults. This is exactly what Save writes.")
            rows = [(p, s, g, k, v) for p, s, g, k, v in tuning.levers()
                    if p in tuning.changes()]
            if not rows:
                tk.Label(self.form, text="Nothing changed yet.", bg=theme.BG,
                         fg=theme.MUTED, font=theme.FONT).pack(anchor="w",
                                                               padx=10, pady=10)
                return
            for path, section, group, key, value in rows:
                label = f"{section.label} / {section.group_labels.get(group, group)}" \
                    if group else section.label
                self._add_row(path, f"{key}", value, sub=label)
            return

        section_key, _, group = iid.partition("/")
        section = next(s for s in tuning.SECTIONS if s.key == section_key)
        title = section.label
        if group:
            title += "  →  " + section.group_labels.get(group, group)
        self.note.config(text=f"{title}\n{section.note}")
        for path, _s, g, key, value in tuning.levers():
            if not path.startswith(section_key + "."):
                continue
            if group and g != group:
                continue
            label = key if group else (f"{g}.{key}" if g else key)
            self._add_row(path, self._friendly(section_key, g, label), value)

    @staticmethod
    def _friendly(section_key, group, label):
        """`specials.0.of_archers` -> `Assassin: of_archers`.

        The index is how the data is shaped and says nothing about what you are
        editing -- and a species' specials shares are the strongest knob on the
        table, so they are the last place to make someone count list positions."""
        parts = label.split(".", 2)
        if section_key != "species" or parts[0] != "specials" or len(parts) < 3:
            return label
        try:
            spec = lexicon.SPECIES[group]["specials"][int(parts[1])]
            name = unit_types.UNIT_TYPES[spec["unit"]]["name"]
        except (KeyError, IndexError, ValueError):
            return label
        return f"{name}: {parts[2]}"

    def _add_row(self, path, label, value, sub=None):
        row = tk.Frame(self.form, bg=theme.BG)
        row.pack(fill="x", padx=10, pady=ROW_PAD)
        text = label if sub is None else f"{label}"
        tk.Label(row, text=text, bg=theme.BG, fg=theme.INK, font=theme.FONT,
                 width=30, anchor="w").pack(side="left")

        default = tuning.DEFAULTS.get(path)
        var = tk.StringVar(value=self._fmt(value))
        if isinstance(default, bool):
            widget = tk.Checkbutton(
                row, variable=var, onvalue="True", offvalue="False",
                bg=theme.BG, fg=theme.INK, selectcolor="#232a36",
                activebackground=theme.BG,
                command=lambda p=path, v=var: self._commit(p, v))
        else:
            widget = tk.Entry(row, textvariable=var, width=12, relief="flat",
                              bg="#232a36", fg=theme.INK, font=theme.FONT,
                              insertbackground=theme.INK, justify="right")
            widget.bind("<Return>", lambda e, p=path, v=var: self._commit(p, v))
            widget.bind("<FocusOut>", lambda e, p=path, v=var: self._commit(p, v))
        widget.pack(side="left")

        default_lbl = tk.Label(row, text="", bg=theme.BG, fg=theme.MUTED,
                               font=("Segoe UI", 9), anchor="w", width=14)
        default_lbl.pack(side="left", padx=(10, 0))
        tk.Button(row, text="reset", relief="flat", font=("Segoe UI", 8),
                  bg="#232a36", fg=theme.MUTED, activebackground=theme.ACCENT,
                  command=lambda p=path: self._reset_one(p)).pack(side="left")
        if sub:
            tk.Label(row, text=sub, bg=theme.BG, fg=theme.MUTED,
                     font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))

        self._rows[path] = (var, widget, default_lbl)
        self._paint(path)

    @staticmethod
    def _fmt(value):
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    def _commit(self, path, var):
        raw = var.get().strip()
        try:
            value = raw in ("True", "1") if isinstance(
                tuning.DEFAULTS.get(path), bool) else float(raw)
            applied = tuning.set(path, value)
        except (ValueError, KeyError):
            var.set(self._fmt(tuning.get(path)))     # reject, put it back
            return
        var.set(self._fmt(applied))
        self._paint(path)
        self._refresh_tree_marks()

    def _paint(self, path):
        var, widget, default_lbl = self._rows[path]
        default = tuning.DEFAULTS.get(path)
        changed = tuning.get(path) != default
        default_lbl.config(text=f"default {self._fmt(default)}" if changed else "",
                           fg=theme.WARN)
        try:
            widget.config(fg=theme.WARN if changed else theme.INK)
        except tk.TclError:
            pass

    def _reset_one(self, path):
        tuning.set(path, tuning.DEFAULTS[path])
        if path in self._rows:
            self._rows[path][0].set(self._fmt(tuning.get(path)))
            self._paint(path)
        self._refresh_tree_marks()
        if self._current == CHANGED:
            self._show(CHANGED)

    # --- file -----------------------------------------------------------------
    def _save(self):
        path, n = tuning.save()
        self._say(f"saved {n} override(s) -> {path}\n", "good")
        self._refresh_tree_marks()

    def _reload(self):
        tuning.reset()
        n = tuning.load(quiet=True)
        self._say(f"reloaded {n} override(s) from disk\n", "dim")
        self._refresh_tree_marks()
        self._show(self._current)

    def _reset_all(self):
        tuning.reset()
        self._say("reset every lever to its source default "
                  "(Save to make it stick)\n", "dim")
        self._refresh_tree_marks()
        self._show(self._current)

    # --- tournament -----------------------------------------------------------
    def _say(self, text, tag=None):
        self.log.insert("end", text, tag or ())
        self.log.see("end")

    def _drain_log(self):
        while True:
            try:
                text, tag = self._log_q.get_nowait()
            except queue.Empty:
                break
            if text is None:
                self._running = False
                self.run_btn.config(text="Run tournament", state="normal")
            else:
                self._say(text, tag)
        self.after(120, self._drain_log)

    def _run_tournament(self):
        if self._running:
            return
        try:
            n_seeds = max(1, int(self.seeds.get()))
        except ValueError:
            n_seeds = 3
        mode = self.mode.get()
        self._running = True
        self.run_btn.config(text="running...", state="disabled")
        n_changed = len(tuning.changes())
        self._say(f"\n--- {mode}, {n_seeds} seeds, orders on, "
                  f"{n_changed} lever(s) changed ---\n", "dim")
        # A worker thread, because a run is minutes long and a frozen window is
        # indistinguishable from a crash. It only ever touches the queue; every
        # widget call happens back on the Tk thread in _drain_log.
        threading.Thread(target=self._tournament_worker,
                         args=(n_seeds, mode), daemon=True).start()

    def _tournament_worker(self, n_seeds, mode):
        put = lambda text, tag=None: self._log_q.put((text, tag))
        try:
            seeds = [11 + 12 * i for i in range(n_seeds)]
            if mode == "isolate":
                base, _, _ = T.run(True, seeds, specials=False)
                put("control  : " + self._rates(base) + "\n")
                for species in T.SPECIES:
                    rates, _, _ = T.run(True, seeds, specials=True, only=species)
                    delta = rates[species] - base[species]
                    put(f"{species[:8]:<9s}: " + self._rates(rates)
                        + f" | {species} {base[species]:3.0f} ->"
                          f" {rates[species]:3.0f} ({delta:+.0f})\n",
                        "good" if delta > 0 else "bad")
            elif mode == "ab":
                for label, specials in (("-specials", False), ("+specials", True)):
                    rates, stale, total = T.run(True, seeds, specials=specials)
                    put(f"{label:<9s}: " + self._rates(rates)
                        + f" | stalemates {stale}/{total}\n")
            else:
                rates, stale, total = T.run(True, seeds)
                put("result   : " + self._rates(rates)
                    + f" | stalemates {stale}/{total}\n")
        except Exception as exc:                       # a lab, not a shipped path
            put(f"run failed: {type(exc).__name__}: {exc}\n", "bad")
        finally:
            self._log_q.put((None, None))

    @staticmethod
    def _rates(rates):
        spread = max(rates.values()) - min(rates.values())
        return ("  ".join(f"{s[:3]} {rates[s]:3.0f}%" for s in T.SPECIES)
                + f" | spread {spread:3.0f}pts")


if __name__ == "__main__":
    BalanceLab().mainloop()
