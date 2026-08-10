"""Load Game popup: lists saves on disk, pick one, then Load, Delete or
Cancel.

Drawn on app/ui/parchment.py's Page -- a shelf of saved chronicles, which is
what a load screen is.
"""
import tkinter as tk
from tkinter import messagebox

from PIL import ImageTk

from app.ui import parchment
from app.ui import theme
from app.core.save import load_game
from app.ui.world_preview import render_world

_WIDTH = 460


class LoadGameMenuView(tk.Frame):
    def __init__(self, master, on_load, on_delete, on_cancel):
        super().__init__(master, bg=theme.BG)
        self.on_load = on_load
        self.on_delete = on_delete
        self.on_cancel = on_cancel
        self._selected_id = None
        self._selected_name = None
        self._saves = []

        holder = tk.Frame(self, bg=theme.BG)
        holder.place(relx=0.5, rely=0.5, anchor="center", width=_WIDTH, height=460)

        # The list scrolls internally: with enough saves an unscrolled list's
        # natural height used to exceed the fixed panel and push the action
        # row off-screen entirely. The page borrows this canvas, so it scrolls
        # for free -- the pinned action row stays a separate strip below it.
        list_container = tk.Frame(holder, bg=theme.PANEL)
        list_container.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_container, bg=theme.PANEL, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_container, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._list_canvas = canvas
        self._page = parchment.Page(None, _WIDTH - 20, seed=51, canvas=canvas)
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # The action row stays widgets: three fixed buttons whose enabled state
        # tracks the selection, which is exactly what a drawn plaque handles
        # worst (it has no disabled look). A page for the list, buttons for the
        # verbs -- each where it is strongest.
        self._actions = tk.Frame(holder, bg=theme.PANEL)
        self._actions.pack(fill="x", pady=(1, 0))
        tk.Button(self._actions, text="Cancel", command=self._cancel, width=10,
                  bg=theme.PANEL_ALT, fg=theme.INK, relief="flat", font=theme.FONT,
                  activebackground=theme.ACCENT).pack(side="left", padx=8, pady=8)
        self.delete_btn = tk.Button(self._actions, text="Delete Save",
                                    command=self._delete, width=12,
                                    bg=theme.PANEL_ALT, fg=theme.BAD, relief="flat",
                                    font=theme.FONT, activebackground=theme.ACCENT,
                                    state="disabled")
        self.delete_btn.pack(side="left")
        self.load_btn = tk.Button(self._actions, text="Load", command=self._load,
                                  width=12, bg=theme.ACCENT, fg="#241a0a",
                                  relief="flat", font=theme.FONT_BOLD,
                                  activebackground=theme.ACCENT, state="disabled")
        self.load_btn.pack(side="right", padx=8, pady=8)
        
        # Details panel for selected world
        self._details_frame = tk.Frame(holder, bg=theme.PANEL)
        self._details_frame.pack(fill="x", pady=(5, 0))
        self._details_frame.pack_forget()  # Initially hidden
        
        # Create details labels
        self._details_title = tk.Label(self._details_frame, text="", font=theme.FONT_BOLD, 
                                       bg=theme.PANEL, fg=theme.ACCENT)
        self._details_title.pack(pady=(5, 0))
        
        self._details_species = tk.Label(self._details_frame, text="", font=theme.FONT, 
                                         bg=theme.PANEL, fg=theme.INK)
        self._details_species.pack()
        
        self._details_date = tk.Label(self._details_frame, text="", font=theme.FONT, 
                                      bg=theme.PANEL, fg=theme.MUTED)
        self._details_date.pack()
        
        self._details_map_preview = tk.Label(self._details_frame, text="Map Preview", 
                                             bg=theme.PANEL, fg=theme.INK)
        self._details_map_preview.pack(pady=(5, 0))
        
        # Map preview canvas
        self._map_canvas = tk.Canvas(self._details_frame, width=120, height=120, 
                                     bg=theme.PANEL_ALT, highlightthickness=0)
        self._map_canvas.pack(pady=5)
        self._map_img = None  # Tk drops unreferenced PhotoImages, so keep it

    def refresh(self, saves):
        self._saves = list(saves)
        self._selected_id = None
        self._selected_name = None
        self.load_btn.config(state="disabled")
        self.delete_btn.config(state="disabled")
        self._render()

    def _render(self):
        page = self._page
        page.begin(max(320, self._list_canvas.winfo_height() or 320))
        page.title("Load Game", "choose a chronicle to return to")
        if not self._saves:
            page.text("No saved realms found.", fill=theme.MUTED)
            page.finish()
            return
        for meta in self._saves:
            save_id = meta["id"]
            name = meta.get("name", "Unnamed World")
            selected = save_id == self._selected_id
            top = page.mark()
            page.kv(f"{name}  ({meta.get('species', '?')})",
                    "‹ selected" if selected else "",
                    fg=theme.ACCENT if selected else theme.INK)
            page.text(f"Created {meta.get('created_at', 'unknown date')}",
                      fill=theme.MUTED, indent=6)
            page.hit_region(top, lambda sid=save_id, n=name: self._select(sid, n))
            page.gap(4)
        page.finish()

    def _select(self, save_id, name):
        self._selected_id = save_id
        self._selected_name = name
        self.load_btn.config(state="normal")
        self.delete_btn.config(state="normal")
        
        # Show details for the selected world
        if save_id:
            self._show_details(save_id)
        self._render()

    def _load(self):
        if self._selected_id is not None:
            self.on_load(self._selected_id)

    def _delete(self):
        if self._selected_id is None:
            return
        if messagebox.askyesno(
                "Delete Save",
                f'Permanently delete "{self._selected_name}"? '
                "This cannot be undone.", parent=self):
            self.on_delete(self._selected_id)

    def _cancel(self):
        self._selected_id = None
        self._selected_name = None
        self.on_cancel()

    def _show_details(self, save_id):
        """Show expanded details about the selected world"""
        # Get the metadata for display (before load_game, so the
        # except-fallback below can rely on `meta` being defined).
        meta = None
        for save_meta in self._saves:
            if save_meta["id"] == save_id:
                meta = save_meta
                break

        if meta is None:
            return

        try:
            # Load the world to get more information
            world = load_game(save_id)

            # Update details labels
            self._details_title.config(text=meta.get("name", "Unnamed World"))
            self._details_species.config(text=f"Species: {meta.get('species', '?')}")
            self._details_date.config(text=f"Created: {meta.get('created_at', 'unknown date')}")
            
            # Create map preview
            self._create_map_preview(world)
            
            # Show the details panel
            self._details_frame.pack(fill="x", pady=(5, 0))
            
        except Exception as e:
            print(f"Error loading world details: {e}")
            # If we can't load the world, just show basic info
            self._details_title.config(text="World Details")
            self._details_species.config(text=f"Species: {meta.get('species', '?') if meta else '?'}")
            self._details_date.config(text=f"Created: {meta.get('created_at', 'unknown date') if meta else 'unknown date'}")
            # Show a placeholder for the map
            self._map_canvas.delete("all")
            self._map_canvas.create_text(60, 60, text="Map Preview", fill=theme.MUTED)

    def _create_map_preview(self, world):
        """A real miniature of the world on the details canvas.

        Uses the same thumbnail pipeline as the New Game screen
        (world_preview.render_world), so the preview shows the actual
        geography -- ocean depth, lakes and rivers, the player's own realm
        in its colour, a ring on the capital. The naive per-cell loop this
        replaces could never scale: at 1 px per cell a default 1100x660
        world is bigger than the 120 px canvas, so it settled for drawing
        the top-left 30x30 cells -- a corner of the seam ocean, not a map.
        """
        self._map_canvas.delete("all")
        try:
            img = render_world(world, (120, 120))
            self._map_img = ImageTk.PhotoImage(img)
            self._map_canvas.create_image(60, 60, image=self._map_img)
        except Exception as e:
            print(f"Error creating map preview: {e}")
            # Draw a simple placeholder if there's an error; drop the stale
            # image reference so the canvas can never show yesterday's map.
            self._map_img = None
            self._map_canvas.create_text(60, 60, text="Map Preview", fill=theme.MUTED)
