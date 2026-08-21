"""PalSchematics -- tkinter front end."""
from __future__ import annotations

import datetime
import os
import queue
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import inventory, saveio
from .catalog import GROUPINGS, Catalog, Schematic

APP = "PalSchematics"
VERSION = "1.1"
CHECKED, UNCHECKED = "☑", "☐"

# A Palworld save is ~48 MB of GVAS once unpacked; parsing takes a while, so
# every save operation runs on a worker thread and reports back through a queue.


class PlayerPicker(tk.Toplevel):
    """Asks which character the schematics are for.

    A dedicated server world holds every player who has ever joined, so after
    loading one there is a real choice to make. Showing each character's level
    and how full their bag is makes it obvious which one is yours.
    """

    def __init__(self, master, players, containers, preselect: int = 0):
        super().__init__(master)
        self.title("Which player?")
        self.resizable(False, False)
        self.transient(master)
        self.result: int | None = None

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="This save has several characters. "
                              "Who are the schematics for?",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 10))

        cols = ("level", "bag")
        self.tree = ttk.Treeview(frame, columns=cols, show="tree headings",
                                 height=min(10, max(3, len(players))), selectmode="browse")
        self.tree.heading("#0", text="Player")
        self.tree.heading("level", text="Level")
        self.tree.heading("bag", text="Backpack")
        self.tree.column("#0", width=230, stretch=False)
        self.tree.column("level", width=60, anchor="center", stretch=False)
        self.tree.column("bag", width=190, anchor="w", stretch=False)
        self.tree.pack(fill="both", expand=True)

        for i, p in enumerate(players):
            bag = "player file not found"
            cont = containers.get(p.backpack_id) if p.backpack_id else None
            if cont is not None:
                free = len(cont.free_indices())
                bag = f"{cont.slot_num - free} of {cont.slot_num} used, {free} free"
            self.tree.insert("", "end", iid=str(i), text="  " + p.name,
                             values=(p.level if p.level else "?", bag))
        if players:
            iid = str(min(preselect, len(players) - 1))
            self.tree.selection_set(iid)
            self.tree.focus(iid)

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="Use this player", command=self._ok).pack(side="right")
        ttk.Button(row, text="Cancel", command=self._cancel).pack(side="right", padx=(0, 8))
        self.tree.bind("<Double-1>", lambda _e: self._ok())
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())

        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + 140
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.tree.focus_set()

    def _ok(self):
        sel = self.tree.selection()
        self.result = int(sel[0]) if sel else None
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=8)
        self.master.title(f"{APP} {VERSION}")
        # wide enough that the 330px side panel is not clipped by the tree columns
        self.master.geometry("1440x820")
        self.master.minsize(1120, 620)
        self.pack(fill="both", expand=True)

        self.catalog = Catalog.load()
        self.save: saveio.Save | None = None
        self.players: list[inventory.Player] = []
        self.player: inventory.Player | None = None
        self.owned: set[str] = set()
        self.selected: set[str] = set()
        self.node_code: dict[str, str] = {}
        self.code_node: dict[str, str] = {}
        self._icons: dict[str, tk.PhotoImage] = {}
        self._queue: queue.Queue = queue.Queue()
        self._busy = False

        self.var_backup = tk.BooleanVar(value=True)
        self.var_safe = tk.BooleanVar(value=True)
        self.var_search = tk.StringVar()
        self.var_group = tk.StringVar(value="Category")
        self.var_cat = tk.StringVar(value="All")
        self.var_tier = tk.StringVar(value="All")
        self.var_rarity = tk.StringVar(value="All")
        self.var_container = tk.StringVar(value="Backpack")
        self.var_status = tk.StringVar(value="Open a Level.sav to begin.")

        self._build_menu()
        self._build_top()
        self._build_filters()
        self._build_body()
        self._build_status()
        self.refresh_tree()
        self.after(100, self._drain)

    # ------------------------------------------------------------------ UI
    def _build_menu(self) -> None:
        bar = tk.Menu(self.master)
        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="Open Level.sav...", command=self.open_save, accelerator="Ctrl+O")
        m.add_command(label="Choose player...", command=self.choose_player)
        m.add_separator()
        m.add_command(label="Exit", command=self.master.destroy)
        bar.add_cascade(label="File", menu=m)
        h = tk.Menu(bar, tearoff=0)
        h.add_command(label="How this works", command=self.show_help)
        h.add_command(label="About", command=self.show_about)
        bar.add_cascade(label="Help", menu=h)
        self.master.config(menu=bar)
        self.master.bind("<Control-o>", lambda _e: self.open_save())

    def _build_top(self) -> None:
        bar = ttk.LabelFrame(self, text="Save", padding=6)
        bar.pack(fill="x")
        self.lbl_path = ttk.Label(bar, text="no save loaded", width=70, anchor="w")
        self.lbl_path.grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(bar, text="Open Level.sav...", command=self.open_save).grid(row=0, column=1)
        ttk.Label(bar, text="Player:").grid(row=0, column=2, padx=(16, 4))
        self.cmb_player = ttk.Combobox(bar, state="disabled", width=26, values=[])
        self.cmb_player.grid(row=0, column=3)
        self.cmb_player.bind("<<ComboboxSelected>>", self.on_player_change)
        ttk.Label(bar, text="Add to:").grid(row=0, column=4, padx=(16, 4))
        self.cmb_container = ttk.Combobox(bar, state="disabled", width=18,
                                          textvariable=self.var_container,
                                          values=["Backpack", "Key items"])
        self.cmb_container.grid(row=0, column=5)
        self.cmb_container.bind("<<ComboboxSelected>>", lambda _e: self.refresh_owned())
        self.lbl_slots = ttk.Label(bar, text="", foreground="#1565c0",
                                   font=("Segoe UI", 9, "bold"))
        self.lbl_slots.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))
        bar.columnconfigure(0, weight=1)

    def _build_filters(self) -> None:
        f = ttk.Frame(self, padding=(0, 8, 0, 4))
        f.pack(fill="x")
        ttk.Label(f, text="Search:").pack(side="left")
        e = ttk.Entry(f, textvariable=self.var_search, width=26)
        e.pack(side="left", padx=(4, 12))
        e.bind("<KeyRelease>", lambda _e: self.refresh_tree())

        def combo(label, var, values, width=17):
            ttk.Label(f, text=label).pack(side="left")
            c = ttk.Combobox(f, textvariable=var, values=values, width=width, state="readonly")
            c.pack(side="left", padx=(4, 12))
            c.bind("<<ComboboxSelected>>", lambda _e: self.refresh_tree())
            return c

        combo("Group by:", self.var_group, list(GROUPINGS))
        combo("Category:", self.var_cat, ["All"] + self.catalog.categories())
        combo("Tier:", self.var_tier, ["All"] + [str(t) if t else "none" for t in self.catalog.tiers()], 7)
        combo("Rarity:", self.var_rarity, ["All"] + self.catalog.rarities(), 11)
        ttk.Button(f, text="Reset", command=self.reset_filters).pack(side="left")

    def _build_body(self) -> None:
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # The side panel is packed first on purpose: pack gives space in order,
        # so an expanding widget packed before it would squeeze it off-screen.
        right = ttk.Frame(body, width=330)
        right.pack(side="right", fill="y", padx=(8, 0))
        right.pack_propagate(False)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        cols = ("tier", "rarity", "unlocks", "status")
        self.tree = ttk.Treeview(left, columns=cols, selectmode="none")
        self.tree.heading("#0", text="Schematic")
        self.tree.column("#0", width=380, stretch=True)
        for key, label, width in (("tier", "Tier", 50), ("rarity", "Rarity", 90),
                                  ("unlocks", "Unlocks", 190), ("status", "", 90)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w", stretch=False)
        vs = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("owned", foreground="#2e7d32")
        self.tree.tag_configure("group", font=("Segoe UI", 9, "bold"))
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<space>", lambda _e: self.toggle_focused())
        self.tree.bind("<Double-1>", self.on_tree_double)

        sel = ttk.LabelFrame(right, text="Selected", padding=6)
        sel.pack(fill="both", expand=True)
        self.lst_sel = tk.Listbox(sel, height=12, activestyle="none")
        self.lst_sel.pack(fill="both", expand=True)
        row = ttk.Frame(sel)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Remove", command=self.remove_selected).pack(side="left")
        ttk.Button(row, text="Clear all", command=self.clear_selection).pack(side="left", padx=6)

        saf = ttk.LabelFrame(right, text="Safety", padding=6)
        saf.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(saf, text="Back up the save first (recommended)",
                        variable=self.var_backup).pack(anchor="w")
        ttk.Checkbutton(saf, text="Keep inventory limits", variable=self.var_safe,
                        command=self.on_safety_toggle).pack(anchor="w")
        self.lbl_policy = ttk.Label(saf, text=inventory.Policy().describe(),
                                    wraplength=300, foreground="#555", justify="left")
        self.lbl_policy.pack(anchor="w", pady=(4, 0))

        self.btn_apply = ttk.Button(right, text="Apply to save", command=self.apply,
                                    state="disabled")
        self.btn_apply.pack(fill="x", pady=8, ipady=4)

        log = ttk.LabelFrame(right, text="Log", padding=4)
        log.pack(fill="both", expand=True)
        self.txt_log = tk.Text(log, height=8, wrap="word", state="disabled",
                               font=("Consolas", 8))
        self.txt_log.pack(fill="both", expand=True)

    def _build_status(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Label(bar, textvariable=self.var_status, anchor="w").pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="right")

    # -------------------------------------------------------------- helpers
    def log(self, msg: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"{stamp}  {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def icon_for(self, s: Schematic):
        path = s.icon_path
        if not path:
            return None
        if path not in self._icons:
            try:
                self._icons[path] = tk.PhotoImage(file=path)
            except Exception:  # noqa: BLE001 - a bad icon must never break the list
                self._icons[path] = None
        return self._icons[path]

    def set_busy(self, busy: bool, msg: str = "") -> None:
        self._busy = busy
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        if msg:
            self.var_status.set(msg)
        state = "disabled" if busy else "normal"
        self.cmb_player.configure(state="readonly" if (not busy and self.players) else "disabled")
        self.btn_apply.configure(
            state="normal" if (not busy and self.player and self.selected) else "disabled")
        self.master.configure(cursor="watch" if busy else "")
        self.master.update_idletasks()
        _ = state

    def run_worker(self, fn, on_done) -> None:
        """Run fn() off the UI thread; on_done(result, error) back on it."""
        def body():
            try:
                self._queue.put((on_done, fn(), None))
            except Exception as exc:  # noqa: BLE001 - reported in the dialog
                self._queue.put((on_done, None, exc))
        threading.Thread(target=body, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                on_done, result, error = self._queue.get_nowait()
                on_done(result, error)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    # ----------------------------------------------------------- save loading
    def open_save(self) -> None:
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Open Level.sav",
            filetypes=[("Palworld level save", "Level.sav"), ("Save files", "*.sav"),
                       ("All files", "*.*")])
        if not path:
            return
        self.load_save(path)

    def load_save(self, path: str, keep_player: str | None = None) -> None:
        self.set_busy(True, f"Loading {os.path.basename(path)} ... this takes a moment")
        self.log(f"loading {path}")

        def work():
            save = saveio.Save.load(path)
            save.verify_roundtrip()
            players_dir = os.path.join(os.path.dirname(path), "Players")
            players = inventory.find_players(save, players_dir)
            return save, players

        def done(result, error):
            self.set_busy(False)
            if error:
                self.report_error("Could not open that save", error)
                self.var_status.set("Open a Level.sav to begin.")
                return
            self.save, self.players = result
            self.lbl_path.configure(text=path)
            fmt = self.save.magic.decode(errors="replace")
            self.log(f"loaded OK ({fmt}, type {self.save.save_type:#x}), "
                     f"round-trip verified, {len(self.players)} player(s)")
            if not self.players:
                messagebox.showwarning(
                    APP, "No player characters found in that save.\n\n"
                         "Make sure you picked the world's Level.sav.")
                return
            labels = [p.label() for p in self.players]
            self.cmb_player.configure(values=labels, state="readonly")
            names = [p.name for p in self.players]
            chosen = names.index(keep_player) if keep_player in names else 0
            self.cmb_player.current(chosen)
            self.cmb_container.configure(state="readonly")
            self.on_player_change()
            # With more than one character in the world there is a real choice
            # to make, so ask outright rather than silently picking the first.
            if len(self.players) > 1 and keep_player is None:
                self.choose_player(preselect=chosen)
            kind = "dedicated server world" if len(self.players) > 1 else "save"
            self.var_status.set(f"Loaded {kind}: {len(self.players)} player(s).")

        self.run_worker(work, done)


    def choose_player(self, preselect: int | None = None) -> None:
        """Open the player picker. Also reachable from File > Choose player."""
        if not (self.save and self.players):
            messagebox.showinfo(APP, "Open a Level.sav first.")
            return
        if preselect is None:
            preselect = max(0, self.cmb_player.current())
        containers = inventory.containers_by_guid(self.save)
        dlg = PlayerPicker(self.master, self.players, containers, preselect)
        self.master.wait_window(dlg)
        if dlg.result is not None:
            self.cmb_player.current(dlg.result)
            self.on_player_change()
            self.log(f"player: {self.players[dlg.result].name}")

    def on_player_change(self, _event=None) -> None:
        idx = self.cmb_player.current()
        if idx < 0 or idx >= len(self.players):
            return
        self.player = self.players[idx]
        if not self.player.backpack_id:
            messagebox.showwarning(
                APP,
                f"{self.player.name}'s player file was not found next to Level.sav, "
                "so their inventory cannot be located.\n\n"
                "The Players folder must sit beside Level.sav.")
        self.refresh_owned()

    def current_container(self) -> inventory.Container | None:
        if not (self.save and self.player):
            return None
        key = ("EssentialContainerId" if self.var_container.get() == "Key items"
               else "CommonContainerId")
        guid = self.player.container_ids.get(key)
        if not guid:
            return None
        return inventory.containers_by_guid(self.save).get(guid)

    def refresh_owned(self) -> None:
        cont = self.current_container()
        if cont is None:
            self.owned = set()
            self.lbl_slots.configure(text="")
        else:
            self.owned = {s.static_id for s in cont.slots()}
            free = len(cont.free_indices())
            room = self.policy().budget(free)
            where = self.var_container.get().lower()
            self.lbl_slots.configure(
                text=f"{self.player.name}'s {where}: {cont.slot_num - free} of "
                     f"{cont.slot_num} slots used - {free} free - "
                     f"room for {room} schematic(s) this apply")
            self.log(f"{self.player.name}: {where} {cont.slot_num - free}/"
                     f"{cont.slot_num} used, {free} free, room for {room}")
        self.refresh_tree()
        self.update_policy_label()
        self.update_apply_state()

    def free_slots(self) -> int | None:
        cont = self.current_container()
        return None if cont is None else len(cont.free_indices())

    def update_policy_label(self) -> None:
        self.lbl_policy.configure(text=self.policy().describe(self.free_slots()))

    # ---------------------------------------------------------------- tree
    def reset_filters(self) -> None:
        self.var_search.set("")
        for v in (self.var_cat, self.var_tier, self.var_rarity):
            v.set("All")
        self.refresh_tree()

    def refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.node_code.clear()
        self.code_node.clear()

        tier = self.var_tier.get()
        entries = self.catalog.filter(
            text=self.var_search.get(),
            category=None if self.var_cat.get() == "All" else self.var_cat.get(),
            tier=None if tier == "All" else (0 if tier == "none" else int(tier)),
            rarity=None if self.var_rarity.get() == "All" else self.var_rarity.get(),
        )
        for group, items in self.catalog.grouped(entries, self.var_group.get()):
            gnode = self.tree.insert("", "end", text=f"{group}  ({len(items)})",
                                     open=False, tags=("group",))
            for s in items:
                owned = s.code in self.owned
                mark = CHECKED if s.code in self.selected else UNCHECKED
                node = self.tree.insert(
                    gnode, "end", text=f" {mark}  {s.name}",
                    image=self.icon_for(s) or "",
                    values=(s.tier_label, s.rarity, s.unlocks or "",
                            "in bag" if owned else ""),
                    tags=("owned",) if owned else ())
                self.node_code[node] = s.code
                self.code_node[s.code] = node
        self.var_status.set(f"{len(entries)} of {len(self.catalog)} schematics shown"
                            + (f" - {len(self.selected)} selected" if self.selected else ""))

    def on_tree_click(self, event) -> None:
        node = self.tree.identify_row(event.y)
        if not node:
            return
        if node in self.node_code:
            self.toggle(self.node_code[node])
        else:
            self.toggle_group(node)

    def on_tree_double(self, event) -> None:
        node = self.tree.identify_row(event.y)
        code = self.node_code.get(node)
        if code:
            webbrowser.open(self.catalog.by_code[code].paldb_url)

    def toggle_focused(self) -> None:
        node = self.tree.focus()
        if node in self.node_code:
            self.toggle(self.node_code[node])

    def toggle(self, code: str) -> None:
        if code in self.selected:
            self.selected.discard(code)
        else:
            if code in self.owned:
                self.log(f"{self.catalog.by_code[code].name} is already in the bag")
                return
            self.selected.add(code)
        self.redraw_node(code)
        self.refresh_selection_list()

    def toggle_group(self, gnode: str) -> None:
        codes = [self.node_code[c] for c in self.tree.get_children(gnode)
                 if c in self.node_code]
        addable = [c for c in codes if c not in self.owned]
        turn_on = not all(c in self.selected for c in addable) if addable else False
        for code in addable:
            if turn_on:
                self.selected.add(code)
            else:
                self.selected.discard(code)
            self.redraw_node(code)
        self.refresh_selection_list()

    def redraw_node(self, code: str) -> None:
        node = self.code_node.get(code)
        if not node:
            return
        s = self.catalog.by_code[code]
        mark = CHECKED if code in self.selected else UNCHECKED
        self.tree.item(node, text=f" {mark}  {s.name}")

    def refresh_selection_list(self) -> None:
        self.lst_sel.delete(0, "end")
        for code in sorted(self.selected, key=lambda c: self.catalog.by_code[c].name):
            self.lst_sel.insert("end", self.catalog.by_code[code].name)
        self.update_apply_state()
        self.var_status.set(f"{len(self.selected)} selected")

    def remove_selected(self) -> None:
        for i in reversed(self.lst_sel.curselection()):
            name = self.lst_sel.get(i)
            for code in list(self.selected):
                if self.catalog.by_code[code].name == name:
                    self.selected.discard(code)
                    self.redraw_node(code)
        self.refresh_selection_list()

    def clear_selection(self) -> None:
        codes = list(self.selected)
        self.selected.clear()
        for c in codes:
            self.redraw_node(c)
        self.refresh_selection_list()

    def update_apply_state(self) -> None:
        ok = bool(self.save and self.player and self.selected and not self._busy)
        self.btn_apply.configure(state="normal" if ok else "disabled")

    def on_safety_toggle(self) -> None:
        policy = self.policy()
        self.update_policy_label()
        self.refresh_owned()
        if not policy.enabled:
            messagebox.showwarning(
                APP,
                "Inventory limits are off.\n\n"
                "PalSchematics will now fill every free slot in the container. "
                "A completely full Palworld inventory can drop or swallow items "
                "when you next pick something up.\n\n"
                "The backup option is your way back if that happens.")

    def policy(self) -> inventory.Policy:
        return inventory.Policy(enabled=self.var_safe.get())

    # --------------------------------------------------------------- apply
    def apply(self) -> None:
        if self._busy or not (self.save and self.player):
            return
        cont = self.current_container()
        if cont is None:
            messagebox.showerror(APP, "That player's container was not found in this save.")
            return
        if self.save.changed_on_disk():
            messagebox.showerror(
                APP,
                "Level.sav changed on disk since it was opened.\n\n"
                "That usually means the server is still running or the game is open. "
                "Stop it, then open the save again -- otherwise your edit would be "
                "overwritten by the next autosave.")
            return

        policy = self.policy()
        codes = sorted(self.selected, key=lambda c: self.catalog.by_code[c].name)
        plan = inventory.plan_add(cont, codes, policy)
        if plan.blocked:
            messagebox.showerror(APP, plan.blocked)
            return
        if not plan.to_add:
            messagebox.showinfo(APP, "Nothing to add.\n\n" + plan.summary())
            return

        lines = [self.catalog.by_code[c].name for c in plan.to_add]
        msg = [f"Add {len(plan.to_add)} schematic(s) to {self.player.name}'s "
               f"{self.var_container.get().lower()}:", ""]
        msg += ["  - " + n for n in lines[:12]]
        if len(lines) > 12:
            msg.append(f"  ... and {len(lines) - 12} more")
        if plan.already_present:
            msg.append(f"\n{len(plan.already_present)} already in the bag (skipped).")
        if plan.over_limit:
            msg.append(f"{len(plan.over_limit)} left for a later run "
                       f"(limit {policy.max_per_apply} per apply).")
        if plan.no_space:
            msg.append(f"{len(plan.no_space)} do not fit in the free slots.")
        msg.append("\nA backup will be written first." if self.var_backup.get()
                   else "\nNO BACKUP will be written.")
        msg.append("Make sure the game and server are closed.")
        if not messagebox.askokcancel(APP, "\n".join(msg)):
            return

        self.set_busy(True, "Writing save ...")

        def work():
            return self.write_save(plan)

        def done(result, error):
            self.set_busy(False)
            if error:
                self.report_error("The save was NOT modified", error)
                return
            placed, backup = result
            for code, slot in placed:
                self.log(f"added {code} -> slot {slot}")
                self.selected.discard(code)
            if backup:
                self.log(f"backup: {os.path.basename(backup)}")
            self.refresh_selection_list()
            path, name = self.save.path, self.player.name
            messagebox.showinfo(
                APP,
                f"Added {len(placed)} schematic(s) to {name}.\n\n"
                + (f"Backup: {os.path.basename(backup)}\n\n" if backup else "")
                + "Start the game or server and check the inventory.")
            # Encoding consumes the in-memory tree, so re-read the file we just
            # wrote; that also re-checks it and refreshes what the player owns.
            self.load_save(path, keep_player=name)

        self.run_worker(work, done)

    def write_save(self, plan: inventory.Plan) -> tuple[list, str | None]:
        """Apply the plan in memory, then hand it to the verified writer."""
        assert self.save is not None
        placed = inventory.execute(plan)
        backup = saveio.write_save(
            self.save,
            backup=self.var_backup.get(),
            expect=(plan.container.guid, [c for c, _ in placed]),
        )
        return placed, backup

    # ---------------------------------------------------------------- misc
    def report_error(self, headline: str, error: Exception) -> None:
        self.log(f"ERROR: {error}")
        detail = str(error)
        if not isinstance(error, (saveio.SaveError, inventory.InventoryError)):
            detail += "\n\n" + "".join(
                traceback.format_exception_only(type(error), error)).strip()
        messagebox.showerror(APP, f"{headline}\n\n{detail}")

    def show_help(self) -> None:
        messagebox.showinfo(APP, HELP_TEXT)

    def show_about(self) -> None:
        messagebox.showinfo(
            APP,
            f"{APP} {VERSION}\n\n"
            f"Adds Palworld schematics to a save file.\n"
            f"{len(self.catalog)} schematics in the catalog.\n\n"
            "Schematic data from paldb.cc. Save parsing uses the MIT-licensed\n"
            "palworld-save-tools library. Oodle decompression uses the game's\n"
            "own oo2core_9_win64.dll, which is not distributed with this app.")


HELP_TEXT = """\
1. Close Palworld, or stop your dedicated server. A running server keeps the
   world in memory and will overwrite anything written here on its next save.

2. File > Open Level.sav.
     Single player: %LOCALAPPDATA%\\Pal\\Saved\\SaveGames\\<id>\\<world>\\Level.sav
     Dedicated server: Pal\\Saved\\SaveGames\\0\\<world>\\Level.sav
   The Players folder must sit next to it -- that is where inventories are found.

3. Pick the player, tick schematics, press Apply.

Safety
  - The save is checked before anything is written: it must survive a full
    load/save cycle byte-for-byte, or the app refuses to touch it.
  - The new file is written to a temporary file, re-opened and checked for the
    items, and only then swapped in.
  - A timestamped .bak is written next to the save by default.
  - Inventory limits: as many schematics as there are free slots, always
    leaving 5 of them empty so the bag is never filled to the brim. The bar
    under the save path tells you how many fit right now. You can switch this
    off, in which case every free slot is fair game.

Schematics are ordinary items. They sit in the backpack, are not consumed, and
unlock the matching recipe at the workbench while they are carried.
"""


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:  # noqa: BLE001 - cosmetic only
        pass
    App(root)
    root.mainloop()
