"""In-game reference: a Toplevel overlay window listing every implemented
mechanic (see app/ui/compendium_data.py for the actual content) — openable
and closable without disturbing the map underneath, so it reads like
alt-tabbing to a reference doc rather than leaving the game.
"""
import tkinter as tk
from tkinter import ttk

from app.ui import theme
from app.ui import compendium_data as CD


class CompendiumWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Compendium")
        self.geometry("900x620")
        self.minsize(620, 420)
        self.configure(bg=theme.BG)
        self.transient(master)

        self._item_content = {}   # item_id -> (title, body)
        self._order = []          # (item_id, parent_id, is_category) in insertion order

        self._build_ui()
        self._populate_tree()
        self.bind("<Escape>", lambda e: self.destroy())
        self._select_item("a:overview")
        self._search_entry.focus_set()

    # --- construction --------------------------------------------------
    def _build_ui(self):
        top = tk.Frame(self, bg=theme.PANEL)
        top.pack(fill="x")
        tk.Label(top, text="Compendium", bg=theme.PANEL, fg=theme.INK,
                 font=theme.FONT_TITLE).pack(side="left", padx=14, pady=8)
        tk.Button(top, text="Close (Esc)", command=self.destroy, bg=theme.PANEL_ALT,
                  fg=theme.INK, activebackground=theme.ACCENT, relief="flat",
                  font=theme.FONT).pack(side="right", padx=10, pady=8)

        search_row = tk.Frame(self, bg=theme.BG)
        search_row.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(search_row, text="Search:", bg=theme.BG, fg=theme.MUTED,
                 font=theme.FONT).pack(side="left", padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._on_search_changed())
        self._search_entry = tk.Entry(search_row, textvariable=self._search_var,
                                      bg=theme.CANVAS, fg=theme.INK,
                                      insertbackground=theme.INK, relief="flat")
        self._search_entry.pack(side="left", fill="x", expand=True, ipady=3)

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(6, 14))

        nav_frame = tk.Frame(body, bg=theme.PANEL, width=270)
        nav_frame.pack(side="left", fill="y")
        nav_frame.pack_propagate(False)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Compendium.Treeview", background=theme.PANEL,
                        fieldbackground=theme.PANEL, foreground=theme.INK,
                        borderwidth=0, rowheight=24)
        style.map("Compendium.Treeview",
                 background=[("selected", theme.ACCENT)],
                 foreground=[("selected", theme.INK)])

        self.tree = ttk.Treeview(nav_frame, show="tree", style="Compendium.Treeview",
                                 selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=4)
        tree_scroll = ttk.Scrollbar(nav_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        content_frame = tk.Frame(body, bg=theme.BG)
        content_frame.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.title_lbl = tk.Label(content_frame, text="", bg=theme.BG, fg=theme.INK,
                                  font=theme.FONT_TITLE, anchor="w")
        self.title_lbl.pack(fill="x", pady=(0, 8))

        text_frame = tk.Frame(content_frame, bg=theme.BG)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", bg=theme.CANVAS, fg=theme.INK,
                            font=theme.FONT, relief="flat", padx=14, pady=12,
                            state="disabled", spacing3=4)
        self.text.pack(side="left", fill="both", expand=True)
        text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        text_scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=text_scroll.set)
        self.text.tag_configure("header", font=theme.FONT_BOLD, foreground=theme.ACCENT,
                                spacing1=6)

    def _populate_tree(self):
        for nav_id, title, kind in CD.NAV:
            if kind == "article":
                item = f"a:{nav_id}"
                self.tree.insert("", "end", iid=item, text=title)
                self._item_content[item] = CD.ARTICLES[nav_id]
                self._order.append((item, "", False))
            else:
                category = CD.category_for_nav_id(nav_id)
                item = f"c:{nav_id}"
                self.tree.insert("", "end", iid=item, text=title)
                self._item_content[item] = (title, CD.category_overview_text(category))
                self._order.append((item, "", True))
                for name in CD.resource_children(category):
                    child = f"r:{name}"
                    self.tree.insert(item, "end", iid=child, text=name)
                    self._item_content[child] = (name, CD.resource_entry_text(name))
                    self._order.append((child, item, False))

    # --- selection / rendering ------------------------------------------
    def _select_item(self, item_id):
        if self.tree.exists(item_id):
            self.tree.selection_set(item_id)
            self.tree.see(item_id)
            self._show_item(item_id)

    def _on_tree_select(self, event):
        sel = self.tree.selection()
        if sel:
            self._show_item(sel[0])

    def _show_item(self, item_id):
        title, body = self._item_content.get(item_id, ("", ""))
        self.title_lbl.config(text=title)
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        for line in body.split("\n"):
            stripped = line.strip()
            is_header = (bool(stripped) and not line.startswith("  ")
                        and stripped == stripped.upper()
                        and any(c.isalpha() for c in stripped))
            start = self.text.index("end-1c")
            self.text.insert("end", line + "\n")
            if is_header:
                self.text.tag_add("header", start, self.text.index("end-1c"))
        self.text.config(state="disabled")
        self.text.see("1.0")

    # --- search filtering -------------------------------------------------
    def _on_search_changed(self):
        query = self._search_var.get().strip().lower()
        matched = None if not query else self._matching_items(query)
        for item, parent, _is_cat in self._order:
            if matched is None or item in matched:
                self.tree.move(item, parent, "end")
            else:
                self.tree.detach(item)
        if matched is not None:
            for item, _parent, is_cat in self._order:
                if is_cat and self.tree.exists(item):
                    self.tree.item(item, open=True)

    def _matching_items(self, query):
        matched = set()
        for nav_id, title, kind in CD.NAV:
            if kind == "article":
                if query in title.lower():
                    matched.add(f"a:{nav_id}")
                continue
            category = CD.category_for_nav_id(nav_id)
            cat_item = f"c:{nav_id}"
            any_child = False
            for name in CD.resource_children(category):
                if query in name.lower():
                    matched.add(f"r:{name}")
                    any_child = True
            if any_child or query in title.lower():
                matched.add(cat_item)
        return matched
