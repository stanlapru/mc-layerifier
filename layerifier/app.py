from __future__ import annotations

import datetime as dt
import gzip
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .constants import APP_NAME, CONFIG_DIR, LOG_PATH
from .gui_locale import GuiLocale, available_languages
from .localization import BlockNames
from .nbt import parse_nbt
from .settings import as_float, as_int, load_config, save_config
from .textures import Image, ImageDraw, ImageTk, TextureSource, block_color, generated_tile, parse_exclusions
from .world import Bounds, MinecraftWorld


class Tooltip:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.window: tk.Toplevel | None = None
        self.label: tk.Label | None = None

    def show(self, text: str, x: int, y: int, dark: bool) -> None:
        if not text:
            self.hide()
            return
        if self.window is None:
            self.window = tk.Toplevel(self.root)
            self.window.withdraw()
            self.window.overrideredirect(True)
            self.label = tk.Label(self.window, padx=7, pady=4, justify="left")
            self.label.pack()
        assert self.label is not None and self.window is not None
        self.label.configure(text=text, bg="#20242a" if dark else "#fff7d7", fg="#f3f3f3" if dark else "#1f1f1f", relief="solid", bd=1)
        self.window.geometry(f"+{x + 14}+{y + 16}")
        self.window.deiconify()

    def hide(self) -> None:
        if self.window is not None:
            self.window.withdraw()


class LayerifierApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1280x820")
        self.config = load_config()
        self.settings = self.config["settings"]
        self.locale = GuiLocale(str(self.settings.get("app_language", "en")))
        self.world: MinecraftWorld | None = None
        self.level_dat: Path | None = None
        self.bounds: Bounds | None = None
        self.blocks: dict[tuple[int, int, int], str] = {}
        self.exclusions: set[str] = set()
        self.axis_var = tk.StringVar(value="Y")
        self.layer_var = tk.IntVar(value=0)
        self.zoom = 1.0
        self.base_cell = as_int(self.settings.get("base_cell_size"), 16, 4, 64)
        self.atlas = TextureSource()
        self.block_names = BlockNames()
        self.canvas_images: list[Any] = []
        self.exclusion_images: list[Any] = []
        self.drag_origin: tuple[int, int] | None = None
        self.dragging_canvas = False
        self.status_var = tk.StringVar(value=self.t("status.select_world"))
        self.summary_var = tk.StringVar(value=self.t("status.no_structure"))
        self.recent_var = tk.StringVar(value="")
        self.recent_world_lookup: dict[str, str] = {}
        self.region_var = tk.StringVar(value="")
        self.region_recent_lookup: dict[str, dict[str, Any]] = {}
        self.coord_vars = {name: tk.StringVar(value="0") for name in ("x1", "y1", "z1", "x2", "y2", "z2")}
        self.structure_name_var = tk.StringVar(value="")
        self.exclusion_var = tk.StringVar(value="minecraft:air")
        self.tooltip = Tooltip(root)
        self.style = ttk.Style(root)
        self.build_menu()
        self.build_ui()
        self.apply_theme()
        self.bind_events()
        self.refresh_recents()
        self.load_default_textures()
        self.show_first_launch_info()

    def t(self, key: str) -> str:
        return self.locale.t(key)

    def guard(self, func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                logging.exception("Unhandled UI error")
                messagebox.showerror(APP_NAME, f"{exc}\n\nDetails were written to:\n{LOG_PATH}")
        return wrapped

    def save_config(self) -> None:
        self.config["settings"] = self.settings
        save_config(self.config)

    def show_first_launch_info(self) -> None:
        if self.config.get("first_launch_complete"):
            return
        messagebox.showinfo(self.t("dialog.first_launch.title"), self.t("dialog.first_launch.body"))
        self.config["first_launch_complete"] = True
        self.save_config()

    def is_dark(self) -> bool:
        return self.settings.get("theme") != "Light"

    def apply_theme(self) -> None:
        dark = self.is_dark()
        bg = "#15171a" if dark else "#f3f4f6"
        fg = "#eeeeee" if dark else "#222222"
        panel = "#20242a" if dark else "#ffffff"
        self.root.configure(bg=bg)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=panel)
        self.style.configure("TLabel", background=panel, foreground=fg)
        self.style.configure("TLabelframe", background=panel, foreground=fg)
        self.style.configure("TLabelframe.Label", background=panel, foreground=fg)
        self.style.configure("TButton", padding=4)
        if hasattr(self, "paned"):
            self.paned.configure(bg="#30343a" if dark else "#cbd5e1")
        self.canvas.configure(bg=bg)
        self.render_layer()

    def build_menu(self) -> None:
        menu = tk.Menu(self.root)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label=self.t("menu.options"), command=self.guard(self.open_options))
        tools.add_command(label=self.t("menu.set_export_folder"), command=self.guard(self.set_export_folder))
        tools.add_command(label=self.t("menu.open_log"), command=self.guard(self.open_log))
        tools.add_separator()
        tools.add_command(label=self.t("menu.about"), command=self.guard(self.open_about))
        menu.add_cascade(label=self.t("menu.tools"), menu=tools)
        self.root.configure(menu=menu)

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)
        self.paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6, bg="#30343a" if self.is_dark() else "#cbd5e1")
        self.paned.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(self.paned, padding=10)
        controls.columnconfigure(0, weight=1)
        self.paned.add(controls, minsize=240, width=300)

        ttk.Button(controls, text=self.t("button.open_level"), command=self.guard(self.open_level_dat)).grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text=self.t("label.recent_worlds")).grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.recents_combo = ttk.Combobox(controls, textvariable=self.recent_var, width=44, state="readonly")
        self.recents_combo.grid(row=2, column=0, sticky="ew")
        self.recents_combo.bind("<<ComboboxSelected>>", self.guard(lambda _e: self.open_recent()))

        coords = ttk.LabelFrame(controls, text=self.t("bounds.title"), padding=8)
        coords.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for col, label in enumerate((self.t("bounds.min"), self.t("bounds.max"))):
            ttk.Label(coords, text=label).grid(row=0, column=col + 1, padx=4)
        for row, axis in enumerate(("x", "y", "z"), start=1):
            ttk.Label(coords, text=axis.upper()).grid(row=row, column=0, sticky="w")
            ttk.Entry(coords, textvariable=self.coord_vars[f"{axis}1"], width=10).grid(row=row, column=1, padx=2, pady=2)
            ttk.Entry(coords, textvariable=self.coord_vars[f"{axis}2"], width=10).grid(row=row, column=2, padx=2, pady=2)
        ttk.Label(coords, text=self.t("bounds.name")).grid(row=4, column=0, sticky="w", pady=(6, 2))
        ttk.Entry(coords, textvariable=self.structure_name_var).grid(row=4, column=1, columnspan=2, sticky="ew", padx=2, pady=(6, 2))
        ttk.Label(coords, text=self.t("bounds.recent")).grid(row=5, column=0, sticky="w", pady=(6, 2))
        self.region_combo = ttk.Combobox(coords, textvariable=self.region_var, width=24, state="readonly")
        self.region_combo.grid(row=5, column=1, columnspan=2, sticky="ew", padx=2, pady=(6, 2))
        self.region_combo.bind("<<ComboboxSelected>>", self.guard(lambda _e: self.apply_recent_region()))

        ttk.Label(controls, text=self.t("axis.label")).grid(row=4, column=0, sticky="w", pady=(10, 0))
        axis_frame = ttk.Frame(controls)
        axis_frame.grid(row=5, column=0, sticky="ew")
        for col, axis in enumerate(("X", "Y", "Z")):
            ttk.Radiobutton(axis_frame, text=axis, value=axis, variable=self.axis_var, command=self.guard(self.configure_layer_slider)).grid(row=0, column=col, sticky="w", padx=(0, 12))
        ttk.Button(controls, text=self.t("button.load_structure"), command=self.guard(self.load_structure)).grid(row=6, column=0, sticky="ew", pady=(10, 4))
        ttk.Button(controls, text=self.t("button.load_texture_json"), command=self.guard(self.load_texture_file)).grid(row=7, column=0, sticky="ew")
        ttk.Button(controls, text=self.t("button.load_texture_folder"), command=self.guard(self.load_texture_folder)).grid(row=8, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(controls, text=self.t("label.exclusions")).grid(row=9, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(controls, textvariable=self.exclusion_var, width=36).grid(row=10, column=0, sticky="ew")
        ttk.Button(controls, text=self.t("button.choose_exclusions"), command=self.guard(self.open_exclusion_picker)).grid(row=11, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(controls, text=self.t("button.apply_exclusions"), command=self.guard(self.apply_exclusions)).grid(row=12, column=0, sticky="ew", pady=(4, 10))

        export_frame = ttk.LabelFrame(controls, text=self.t("export.title"), padding=8)
        export_frame.grid(row=13, column=0, sticky="ew")
        export_frame.columnconfigure(0, weight=1)
        ttk.Button(export_frame, text=self.t("export.individual"), command=self.guard(lambda: self.export_layers(False))).grid(row=0, column=0, sticky="ew")
        ttk.Button(export_frame, text=self.t("export.combined"), command=self.guard(lambda: self.export_layers(True))).grid(row=1, column=0, sticky="ew", pady=(4, 0))

        ttk.Label(controls, textvariable=self.status_var, wraplength=260).grid(row=14, column=0, sticky="ew", pady=(12, 0))

        view = ttk.Frame(self.paned)
        self.paned.add(view, minsize=500)
        view.rowconfigure(0, weight=1)
        view.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(view, bg="#15171a", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll = ttk.Scrollbar(view, orient="vertical", command=self.canvas.yview)
        self.h_scroll = ttk.Scrollbar(view, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")
        self.layer_slider = ttk.Scale(view, orient="vertical", command=self.guard(self.layer_slider_changed))
        self.layer_slider.grid(row=0, column=2, sticky="ns", padx=(8, 8), pady=8)

        summary_frame = ttk.Frame(self.root, padding=(8, 4))
        summary_frame.grid(row=1, column=0, sticky="ew")
        summary_frame.columnconfigure(0, weight=1)
        ttk.Label(summary_frame, textvariable=self.summary_var, wraplength=1200, justify="left").grid(row=0, column=0, sticky="ew")
        ttk.Button(summary_frame, text=self.t("button.copy_summary"), command=self.guard(self.copy_summary)).grid(row=0, column=1, padx=(8, 0))

    def bind_events(self) -> None:
        self.canvas.bind("<Motion>", self.guard(self.on_canvas_motion))
        self.canvas.bind("<Leave>", self.guard(lambda _e: self.tooltip.hide()))
        self.canvas.bind("<ButtonPress-1>", self.guard(self.on_canvas_press))
        self.canvas.bind("<B1-Motion>", self.guard(self.on_canvas_drag))
        self.canvas.bind("<ButtonRelease-1>", self.guard(self.on_canvas_release))
        self.canvas.bind("<ButtonPress-2>", self.guard(self.on_canvas_press))
        self.canvas.bind("<B2-Motion>", self.guard(self.on_canvas_drag))
        self.canvas.bind("<ButtonRelease-2>", self.guard(self.on_canvas_release))
        self.canvas.bind("<ButtonPress-3>", self.guard(self.on_canvas_press))
        self.canvas.bind("<B3-Motion>", self.guard(self.on_canvas_drag))
        self.canvas.bind("<ButtonRelease-3>", self.guard(self.on_canvas_release))
        self.canvas.bind("<MouseWheel>", self.guard(self.on_mouse_wheel))
        self.canvas.bind("<Button-4>", self.guard(lambda _e: self.zoom_by(as_float(self.settings.get("zoom_step"), 1.15, 1.01, 3.0))))
        self.canvas.bind("<Button-5>", self.guard(lambda _e: self.zoom_by(1 / as_float(self.settings.get("zoom_step"), 1.15, 1.01, 3.0))))
        self.root.bind("<Right>", self.guard(lambda _e: self.step_layer(1)))
        self.root.bind("<Up>", self.guard(lambda _e: self.step_layer(1)))
        self.root.bind("<Prior>", self.guard(lambda _e: self.step_layer(1)))
        self.root.bind("<Left>", self.guard(lambda _e: self.step_layer(-1)))
        self.root.bind("<Down>", self.guard(lambda _e: self.step_layer(-1)))
        self.root.bind("<Next>", self.guard(lambda _e: self.step_layer(-1)))

    def refresh_recents(self) -> None:
        recents = [path for path in self.config.get("recents", []) if Path(path).exists()]
        self.config["recents"] = recents
        self.recent_world_lookup.clear()
        labels = []
        for path in recents:
            label = self.world_recent_label(Path(path))
            labels.append(label)
            self.recent_world_lookup[label] = path
        self.recents_combo["values"] = labels
        if labels and not self.recent_var.get():
            self.recent_var.set(labels[0])
        if labels and self.level_dat is None:
            self.root.after(0, self.guard(lambda: self.set_level_dat(Path(self.recent_world_lookup[labels[0]]))))

    def refresh_region_recents(self) -> None:
        self.region_recent_lookup.clear()
        self.region_var.set("")
        if not self.level_dat:
            self.region_combo["values"] = []
            return
        regions = self.config.get("regions", {}).get(str(self.level_dat), [])
        labels = []
        for region in regions:
            try:
                label = self.region_label(region)
                labels.append(label)
                self.region_recent_lookup[label] = region
            except Exception:
                logging.exception("Skipping invalid recent region: %r", region)
        self.region_combo["values"] = labels
        if labels:
            self.region_var.set(labels[0])
            self.apply_recent_region()

    def add_recent(self, path: Path) -> None:
        value = str(path)
        recents = [item for item in self.config.get("recents", []) if item != value]
        recents.insert(0, value)
        self.config["recents"] = recents[:12]
        self.save_config()
        self.refresh_recents()
        label = self.world_recent_label(path)
        self.recent_world_lookup[label] = value
        self.recent_var.set(label)

    def world_recent_label(self, level_dat: Path) -> str:
        name = self.world_name(level_dat)
        return f"{name} [level.dat] - {level_dat}"

    def world_name(self, level_dat: Path | None = None) -> str:
        path = level_dat or self.level_dat
        if path is None:
            return "world"
        try:
            data = gzip.decompress(path.read_bytes())
            root = parse_nbt(data)
            level_name = root.get("Data", {}).get("LevelName") if isinstance(root.get("Data"), dict) else None
            if level_name:
                return str(level_name)
        except Exception:
            logging.exception("Failed to read world name from %s", path)
        return path.parent.name

    def region_label(self, region: dict[str, Any]) -> str:
        axis = region.get("axis", "Y")
        name = str(region.get("name") or "").strip()
        prefix = f"{name} - " if name else ""
        return f"{prefix}{axis} X{region['x1']}..{region['x2']} Y{region['y1']}..{region['y2']} Z{region['z1']}..{region['z2']}"

    def region_key(self, region: dict[str, Any]) -> tuple[Any, ...]:
        return (region.get("axis", "Y"), region.get("x1"), region.get("y1"), region.get("z1"), region.get("x2"), region.get("y2"), region.get("z2"))

    def add_recent_region(self, bounds: Bounds) -> None:
        if not self.level_dat:
            return
        world_key = str(self.level_dat)
        region = {
            "axis": self.axis_var.get(),
            "name": self.structure_name_var.get().strip(),
            "x1": bounds.x1,
            "y1": bounds.y1,
            "z1": bounds.z1,
            "x2": bounds.x2,
            "y2": bounds.y2,
            "z2": bounds.z2,
        }
        regions = [item for item in self.config.setdefault("regions", {}).get(world_key, []) if self.region_key(item) != self.region_key(region)]
        regions.insert(0, region)
        self.config["regions"][world_key] = regions[:24]
        self.save_config()
        self.refresh_region_recents()

    def apply_recent_region(self) -> None:
        region = self.region_recent_lookup.get(self.region_var.get())
        if not region:
            return
        for name in ("x1", "y1", "z1", "x2", "y2", "z2"):
            self.coord_vars[name].set(str(region[name]))
        self.structure_name_var.set(str(region.get("name") or ""))
        self.axis_var.set(str(region.get("axis", "Y")))
        self.configure_layer_slider()
        self.status_var.set("Applied recent region")

    def open_level_dat(self) -> None:
        path = filedialog.askopenfilename(title="Select level.dat", filetypes=(("Minecraft level.dat", "level.dat"), ("DAT files", "*.dat"), ("All files", "*.*")))
        if path:
            self.set_level_dat(Path(path))

    def open_recent(self) -> None:
        selected = self.recent_var.get()
        path = self.recent_world_lookup.get(selected, selected)
        if path:
            self.set_level_dat(Path(path))

    def set_level_dat(self, path: Path) -> None:
        if self.world:
            self.world.close()
        self.world = MinecraftWorld(path)
        self.level_dat = path
        self.add_recent(path)
        self.refresh_region_recents()
        self.status_var.set(f"World selected: {path.parent.name}")
        logging.info("Opened world %s", path)

    def read_bounds(self) -> Bounds:
        values = {name: int(var.get().strip()) for name, var in self.coord_vars.items()}
        return Bounds.normalized(values["x1"], values["y1"], values["z1"], values["x2"], values["y2"], values["z2"])

    def load_structure(self) -> None:
        if not self.world:
            raise RuntimeError("Open a level.dat file first")
        bounds = self.read_bounds()
        volume = (bounds.x2 - bounds.x1 + 1) * (bounds.y2 - bounds.y1 + 1) * (bounds.z2 - bounds.z1 + 1)
        if volume > 5_000_000 and not messagebox.askyesno(APP_NAME, f"This selection contains {volume:,} block positions and may be slow. Continue?"):
            return
        self.add_recent_region(bounds)
        self.bounds = bounds
        self.blocks.clear()
        self.status_var.set("Loading chunks...")
        self.root.update_idletasks()

        def progress(done: int, total: int) -> None:
            if done == 1 or done == total or done % 10 == 0:
                self.status_var.set(f"Loading chunks {done}/{total}...")
                self.root.update_idletasks()

        self.blocks = self.world.load_blocks(bounds, progress)
        self.zoom = 1.0
        self.configure_layer_slider()
        self.render_layer()
        failed = self.world.failed_chunks if self.world else 0
        suffix = f"; {failed} chunk(s) failed, see log" if failed else ""
        self.status_var.set(f"Loaded {len(self.blocks):,} non-air blocks{suffix}")

    def configure_layer_slider(self) -> None:
        if not self.bounds:
            return
        min_layer, max_layer = self.bounds.axis_range(self.axis_var.get())
        self.layer_slider.configure(from_=max_layer, to=min_layer)
        if self.layer_var.get() < min_layer or self.layer_var.get() > max_layer:
            self.layer_var.set(min_layer)
        self.layer_slider.set(self.layer_var.get())
        self.render_layer()

    def layer_slider_changed(self, value: str) -> None:
        self.layer_var.set(int(round(float(value))))
        self.render_layer()

    def step_layer(self, delta: int) -> None:
        if not self.bounds:
            return
        min_layer, max_layer = self.bounds.axis_range(self.axis_var.get())
        self.layer_var.set(max(min_layer, min(max_layer, self.layer_var.get() + delta)))
        self.layer_slider.set(self.layer_var.get())
        self.render_layer()

    def on_canvas_press(self, event: tk.Event) -> None:
        self.drag_origin = (event.x, event.y)
        self.dragging_canvas = False
        self.canvas.scan_mark(event.x, event.y)

    def on_canvas_drag(self, event: tk.Event) -> None:
        if self.drag_origin is None:
            return
        if abs(event.x - self.drag_origin[0]) > 3 or abs(event.y - self.drag_origin[1]) > 3:
            self.dragging_canvas = True
            self.tooltip.hide()
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_canvas_release(self, event: tk.Event) -> None:
        if getattr(event, "num", 1) == 1 and not self.dragging_canvas and self.settings.get("click_advance"):
            self.step_layer(1)
        self.drag_origin = None

    def apply_exclusions(self) -> None:
        self.exclusions = parse_exclusions(self.exclusion_var.get())
        self.render_layer()
        self.status_var.set(f"Excluded {len(self.exclusions)} block type(s)")

    def sync_exclusion_text(self) -> None:
        self.exclusion_var.set(", ".join(sorted(self.exclusions)))

    def available_block_ids(self) -> list[str]:
        ids = set(self.blocks.values())
        ids.update(self.atlas.model_texture_aliases.keys())
        for key in self.atlas.files:
            namespace, name = key.split(":", 1)
            if name.startswith("item/"):
                continue
            ids.add(f"{namespace}:{name.removeprefix('block/')}")
        for key in self.block_names.names:
            parts = key.split(".", 2)
            if len(parts) == 3:
                ids.add(f"{parts[1]}:{parts[2].replace('.', '_')}")
        return sorted(ids)

    def block_preview_image(self, block: str, size: int = 24) -> Any | None:
        image = self.atlas.tk_tile(block, size) if self.atlas.loaded else None
        if image is not None:
            self.exclusion_images.append(image)
            return image
        if ImageTk is None:
            return None
        tile = generated_tile(block, size)
        if tile is None:
            return None
        image = ImageTk.PhotoImage(tile)
        self.exclusion_images.append(image)
        return image

    def open_exclusion_picker(self) -> None:
        self.exclusions = parse_exclusions(self.exclusion_var.get())
        win = tk.Toplevel(self.root)
        win.title(self.t("exclusions.title"))
        win.geometry("860x640")
        win.transient(self.root)
        win.rowconfigure(1, weight=1)
        win.columnconfigure(0, weight=1)

        search_var = tk.StringVar(value="")
        search_frame = ttk.Frame(win, padding=8)
        search_frame.grid(row=0, column=0, sticky="ew")
        search_frame.columnconfigure(1, weight=1)
        ttk.Label(search_frame, text=self.t("exclusions.search")).grid(row=0, column=0, padx=(0, 6))
        search_entry = ttk.Entry(search_frame, textvariable=search_var)
        search_entry.grid(row=0, column=1, sticky="ew")

        tree_frame = ttk.Frame(win, padding=(8, 0, 8, 8))
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(tree_frame, columns=("id", "name"), show="tree headings", selectmode="extended")
        tree.heading("#0", text=self.t("exclusions.excluded"))
        tree.heading("id", text=self.t("exclusions.id"))
        tree.heading("name", text=self.t("exclusions.name"))
        tree.column("#0", width=90, stretch=False)
        tree.column("id", width=330)
        tree.column("name", width=300)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        yscroll.grid(row=0, column=1, sticky="ns")
        tree.tag_configure("excluded", background="#3a2d2d" if self.is_dark() else "#ffe8e8")

        blocks = self.available_block_ids()

        def matches(block: str, query: str) -> bool:
            if not query:
                return True
            name = self.block_names.name_for(block)
            query = query.lower()
            return query in block.lower() or query in name.lower()

        def populate() -> None:
            self.exclusion_images.clear()
            tree.delete(*tree.get_children())
            query = search_var.get().strip()
            for block in blocks:
                if not matches(block, query):
                    continue
                excluded = block in self.exclusions
                tree.insert("", "end", iid=block, text="X" if excluded else "", image=self.block_preview_image(block), values=(block, self.block_names.name_for(block)), tags=("excluded",) if excluded else ())

        def toggle_selected() -> None:
            selected = tree.selection()
            if not selected:
                return
            for block in selected:
                if block in self.exclusions:
                    self.exclusions.remove(block)
                else:
                    self.exclusions.add(block)
            self.sync_exclusion_text()
            populate()
            self.render_layer()

        def clear_all() -> None:
            self.exclusions.clear()
            self.sync_exclusion_text()
            populate()
            self.render_layer()

        search_var.trace_add("write", lambda *_args: populate())
        tree.bind("<Double-1>", self.guard(lambda _event: toggle_selected()))

        buttons = ttk.Frame(win, padding=(8, 0, 8, 8))
        buttons.grid(row=2, column=0, sticky="ew")
        ttk.Button(buttons, text=self.t("exclusions.toggle"), command=self.guard(toggle_selected)).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text=self.t("exclusions.clear"), command=self.guard(clear_all)).grid(row=0, column=1, padx=6)
        ttk.Button(buttons, text=self.t("exclusions.close"), command=win.destroy).grid(row=0, column=2, padx=6)
        populate()
        search_entry.focus_set()

    def load_default_textures(self) -> None:
        path = Path(str(self.settings.get("default_texture_path", ""))).expanduser()
        if path.exists():
            try:
                count = self.atlas.load(path)
                self.load_language(path)
                self.status_var.set(f"Loaded default textures: {count} mappings from {self.atlas.source_description}")
            except Exception:
                logging.exception("Failed to load default textures from %s", path)
                self.atlas.clear()
                self.status_var.set("Default textures failed to load; using generated colors")

    def load_texture_path(self, path: Path) -> None:
        self.settings["default_texture_path"] = str(path)
        self.add_texture_source_recent(path)
        self.save_config()
        try:
            count = self.atlas.load(path)
            lang_count = self.load_language(path)
            lang_text = f"; {lang_count} localized names" if lang_count else ""
            self.status_var.set(f"Loaded {count} texture mappings from {self.atlas.source_description}{lang_text}")
        except Exception:
            logging.exception("Failed to load textures from %s", path)
            self.atlas.clear()
            self.status_var.set("Textures failed to load; using generated colors")
        self.render_layer()

    def load_language(self, path: Path) -> int:
        try:
            return self.block_names.load_from_path(path, self.minecraft_locale_code())
        except Exception:
            logging.exception("Failed to load language from %s", path)
            return 0

    def minecraft_locale_code(self) -> str:
        app_language = str(self.settings.get("app_language", "en"))
        if app_language == "ru":
            return "ru_ru"
        return "en_us"

    def add_texture_source_recent(self, path: Path) -> None:
        value = str(path)
        sources = [item for item in self.settings.get("texture_sources", []) if item != value]
        sources.insert(0, value)
        self.settings["texture_sources"] = sources[:12]

    def load_texture_file(self) -> None:
        start = Path(str(self.settings.get("default_texture_path", ""))).expanduser()
        selected = filedialog.askopenfilename(
            title="Select texture JSON",
            initialdir=str(start.parent if start.is_file() else start if start.exists() else Path.cwd()),
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if selected:
            self.load_texture_path(Path(selected))

    def load_texture_folder(self) -> None:
        start = Path(str(self.settings.get("default_texture_path", ""))).expanduser()
        selected = filedialog.askdirectory(title="Select texture folder", initialdir=str(start if start.is_dir() else Path.cwd()))
        if selected:
            self.load_texture_path(Path(selected))

    def set_export_folder(self) -> None:
        current = Path(str(self.settings.get("export_root", "exports"))).expanduser()
        selected = filedialog.askdirectory(title=self.t("options.export_folder"), initialdir=str(current if current.exists() else Path.cwd()))
        if not selected:
            return
        self.settings["export_root"] = selected
        self.save_config()
        self.status_var.set(f"{self.t('status.export_folder_set')}: {selected}")

    def plane_info(self) -> tuple[str, tuple[int, int], tuple[int, int]]:
        if not self.bounds:
            raise RuntimeError("No bounds loaded")
        axis = self.axis_var.get()
        if axis == "Y":
            return axis, (self.bounds.x1, self.bounds.x2), (self.bounds.z1, self.bounds.z2)
        if axis == "Z":
            return axis, (self.bounds.x1, self.bounds.x2), (self.bounds.y1, self.bounds.y2)
        return axis, (self.bounds.z1, self.bounds.z2), (self.bounds.y1, self.bounds.y2)

    def block_to_cell(self, pos: tuple[int, int, int]) -> tuple[int, int] | None:
        if not self.bounds:
            return None
        x, y, z = pos
        axis = self.axis_var.get()
        if axis == "Y":
            return (x - self.bounds.x1, z - self.bounds.z1) if y == self.layer_var.get() else None
        if axis == "Z":
            return (x - self.bounds.x1, self.bounds.y2 - y) if z == self.layer_var.get() else None
        return (z - self.bounds.z1, self.bounds.y2 - y) if x == self.layer_var.get() else None

    def cell_to_block_pos(self, col: int, row: int) -> tuple[int, int, int]:
        if not self.bounds:
            raise RuntimeError("No bounds loaded")
        layer = self.layer_var.get()
        axis = self.axis_var.get()
        if axis == "Y":
            return self.bounds.x1 + col, layer, self.bounds.z1 + row
        if axis == "Z":
            return self.bounds.x1 + col, self.bounds.y2 - row, layer
        return layer, self.bounds.y2 - row, self.bounds.z1 + col

    def visible_layer_blocks(self) -> list[tuple[tuple[int, int, int], str, int, int]]:
        result = []
        for pos, block in self.blocks.items():
            if block in self.exclusions:
                continue
            cell = self.block_to_cell(pos)
            if cell:
                result.append((pos, block, cell[0], cell[1]))
        return result

    def layer_display_text(self, axis: str | None = None, layer: int | None = None) -> str:
        axis = axis or self.axis_var.get()
        layer = self.layer_var.get() if layer is None else layer
        if not self.bounds:
            return f"{axis} layer {layer}"
        min_layer, _max_layer = self.bounds.axis_range(axis)
        number = layer - min_layer + 1
        return f"Layer {number} ({axis}={layer})"

    def visible_total_counts(self) -> Counter[str]:
        return Counter(block for block in self.blocks.values() if block not in self.exclusions)

    def block_counts_for_layer(self, axis: str, layer: int) -> Counter[str]:
        counts: Counter[str] = Counter()
        for (x, y, z), block in self.blocks.items():
            if block in self.exclusions:
                continue
            if (axis == "X" and x == layer) or (axis == "Y" and y == layer) or (axis == "Z" and z == layer):
                counts[block] += 1
        return counts

    def stack_text(self, count: int) -> str:
        stacks, remainder = divmod(count, 64)
        if stacks and remainder:
            return f"{stacks} stack{'s' if stacks != 1 else ''} + {remainder}"
        if stacks:
            return f"{stacks} stack{'s' if stacks != 1 else ''}"
        return f"0 stacks + {remainder}"

    def summary_lines(self, counts: Counter[str], title: str = "Summary") -> list[str]:
        total = sum(counts.values())
        lines = [f"{title}: {total} block{'s' if total != 1 else ''}"]
        for block, count in counts.most_common():
            lines.append(f"{self.block_names.name_for(block)} ({block}): {count} ({self.stack_text(count)})")
        return lines

    def copy_summary(self) -> None:
        if not self.blocks:
            text = self.t("status.no_structure")
        else:
            text = "\n".join(self.summary_lines(self.visible_total_counts(), self.t("summary.total_title")))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set(self.t("status.summary_copied"))

    def update_summary(self) -> None:
        if not self.blocks:
            self.summary_var.set("No structure loaded")
            return
        lines = self.summary_lines(self.visible_total_counts(), self.t("summary.total_title"))
        self.summary_var.set(" | ".join(lines))

    def safe_name(self, value: str, fallback: str) -> str:
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
        return value or fallback

    def colors(self) -> dict[str, str]:
        return {"bg": "#15171a", "grid": "#30343a", "text": "#f0f0f0"} if self.is_dark() else {"bg": "#f3f4f6", "grid": "#cbd5e1", "text": "#111827"}

    def render_layer(self) -> None:
        self.canvas.delete("all")
        self.canvas_images.clear()
        colors = self.colors()
        self.canvas.configure(bg=colors["bg"])
        if not self.bounds:
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            return
        axis, col_range, row_range = self.plane_info()
        cols = col_range[1] - col_range[0] + 1
        rows = row_range[1] - row_range[0] + 1
        cell = max(4, min(96, int(round(self.base_cell * self.zoom))))
        width = cols * cell
        height = rows * cell
        self.canvas.configure(scrollregion=(0, 0, width + 1, height + 1))
        if self.settings.get("show_grid", True) and cell >= 6:
            for col in range(cols + 1):
                x = col * cell
                self.canvas.create_line(x, 0, x, height, fill=colors["grid"])
            for row in range(rows + 1):
                y = row * cell
                self.canvas.create_line(0, y, width, y, fill=colors["grid"])
        for _pos, block, col, row in self.visible_layer_blocks():
            x1 = col * cell
            y1 = row * cell
            tile = self.atlas.tk_tile(block, cell) if self.atlas.loaded and cell >= 8 else None
            if tile:
                self.canvas.create_image(x1, y1, image=tile, anchor="nw")
                self.canvas_images.append(tile)
            else:
                self.canvas.create_rectangle(x1 + 1, y1 + 1, x1 + cell - 1, y1 + cell - 1, fill=block_color(block), outline="")
        self.canvas.create_text(8, 8, text=f"{self.layer_display_text(axis)} | zoom {self.zoom:.2f}x", fill=colors["text"], anchor="nw", font=("Segoe UI", 10, "bold"))
        self.update_summary()

    def on_canvas_motion(self, event: tk.Event) -> None:
        if self.dragging_canvas or not self.bounds or not self.settings.get("show_hover_tooltip", True):
            self.tooltip.hide()
            return
        cell = max(4, min(96, int(round(self.base_cell * self.zoom))))
        col = int(self.canvas.canvasx(event.x) // cell)
        row = int(self.canvas.canvasy(event.y) // cell)
        pos = self.cell_to_block_pos(col, row)
        block = self.blocks.get(pos)
        text = f"{self.block_label(block)}\nX={pos[0]} Y={pos[1]} Z={pos[2]}" if block and block not in self.exclusions else f"X={pos[0]} Y={pos[1]} Z={pos[2]}"
        self.tooltip.show(text, event.x_root, event.y_root, self.is_dark())

    def block_label(self, block: str) -> str:
        mode = str(self.settings.get("block_label_mode", "ID + Name"))
        name = self.block_names.name_for(block)
        if mode == "Name":
            return name
        if mode == "ID":
            return block
        return f"{name} ({block})"

    def on_mouse_wheel(self, event: tk.Event) -> None:
        step = as_float(self.settings.get("zoom_step"), 1.15, 1.01, 3.0)
        self.zoom_by(step if event.delta > 0 else 1 / step)

    def zoom_by(self, factor: float) -> None:
        old_zoom = self.zoom
        self.zoom = max(0.25, min(6.0, self.zoom * factor))
        if abs(self.zoom - old_zoom) > 0.001:
            self.render_layer()

    def export_layers(self, combined: bool) -> None:
        if Image is None or ImageDraw is None:
            raise RuntimeError("Pillow is required for PNG export. Install with: python -m pip install -r requirements.txt")
        if not self.bounds or not self.level_dat:
            raise RuntimeError("Load a structure before exporting")
        axis = self.axis_var.get()
        min_layer, max_layer = self.bounds.axis_range(axis)
        target_root = Path(str(self.settings.get("export_root", "exports"))).expanduser()
        world_part = self.safe_name(self.world_name(), "world")
        structure_part = self.safe_name(self.structure_name_var.get(), "structure") if self.structure_name_var.get().strip() else ""
        name_parts = [world_part]
        if structure_part:
            name_parts.append(structure_part)
        name_parts.extend([self.bounds.descriptor(), dt.datetime.now().strftime("%Y%m%d_%H%M%S")])
        folder_name = "_".join(name_parts)
        target = target_root / folder_name
        target.mkdir(parents=True, exist_ok=True)
        self.exclusions = parse_exclusions(self.exclusion_var.get())
        if combined:
            path = target / "combined_layers.png"
            self.render_combined_export(axis, min_layer, max_layer).save(path)
            self.status_var.set(f"Exported combined PNG: {path}")
        else:
            layers_dir = target / "layers"
            layers_dir.mkdir(exist_ok=True)
            tile_size = as_int(self.settings.get("export_tile_size"), 16, 4, 128)
            for layer in range(min_layer, max_layer + 1):
                self.render_export_layer(axis, layer, tile_size=tile_size, label=True).save(layers_dir / f"{axis}_{layer}.png")
            self.status_var.set(f"Exported layer PNGs: {layers_dir}")

    def draw_summary_panel(self, image: Any, lines: list[str], top: int, draw: Any) -> None:
        draw.rectangle((0, top, image.width, image.height), fill=(24, 27, 31, 255))
        y = top + 6
        for line in lines:
            draw.text((6, y), line, fill=(245, 245, 245, 255))
            y += 14

    def render_export_layer(self, axis: str, layer: int, tile_size: int = 16, label: bool = True, include_summary: bool = True) -> Any:
        if not self.bounds:
            raise RuntimeError("No bounds loaded")
        old_axis = self.axis_var.get()
        old_layer = self.layer_var.get()
        self.axis_var.set(axis)
        self.layer_var.set(layer)
        _, col_range, row_range = self.plane_info()
        cols = col_range[1] - col_range[0] + 1
        rows = row_range[1] - row_range[0] + 1
        label_h = 22 if label else 0
        summary_lines = self.summary_lines(self.block_counts_for_layer(axis, layer), self.layer_display_text(axis, layer)) if include_summary else []
        summary_h = 12 + 14 * len(summary_lines) if include_summary else 0
        image_w = max(1, cols * tile_size, 680)
        image_h = max(1, rows * tile_size + label_h + summary_h)
        image = Image.new("RGBA", (image_w, image_h), (21, 23, 26, 255))
        draw = ImageDraw.Draw(image)
        if label:
            draw.rectangle((0, 0, image.width, label_h), fill=(34, 37, 42, 255))
            draw.text((4, 3), self.layer_display_text(axis, layer), fill=(245, 245, 245, 255))
        for _pos, block, col, row in self.visible_layer_blocks():
            x = col * tile_size
            y = label_h + row * tile_size
            tile = self.atlas.pil_tile(block, tile_size) if self.atlas.loaded else None
            if tile is None:
                tile = generated_tile(block, tile_size)
            if tile:
                image.alpha_composite(tile, (x, y))
            else:
                draw.rectangle((x, y, x + tile_size - 1, y + tile_size - 1), fill=block_color(block))
        if self.settings.get("show_grid", True) and tile_size >= 8:
            for col in range(cols + 1):
                x = col * tile_size
                draw.line((x, label_h, x, label_h + rows * tile_size), fill=(48, 52, 58, 255))
            for row in range(rows + 1):
                y = label_h + row * tile_size
                draw.line((0, y, cols * tile_size, y), fill=(48, 52, 58, 255))
        if include_summary:
            self.draw_summary_panel(image, summary_lines, label_h + rows * tile_size, draw)
        self.axis_var.set(old_axis)
        self.layer_var.set(old_layer)
        return image

    def render_combined_export(self, axis: str, min_layer: int, max_layer: int) -> Any:
        tile_size = as_int(self.settings.get("combined_tile_size"), 12, 4, 128)
        previews = [self.render_export_layer(axis, layer, tile_size=tile_size, label=True, include_summary=False) for layer in range(min_layer, max_layer + 1)]
        if not previews:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        n = len(previews)
        tile_w = max(img.width for img in previews)
        tile_h = max(img.height for img in previews)
        best_cols = min(range(1, n + 1), key=lambda cols: (cols * tile_w * math.ceil(n / cols) * tile_h, abs(cols * tile_w - math.ceil(n / cols) * tile_h)))
        rows = math.ceil(n / best_cols)
        combined = Image.new("RGBA", (best_cols * tile_w, rows * tile_h), (15, 17, 20, 255))
        for index, preview in enumerate(previews):
            combined.alpha_composite(preview, ((index % best_cols) * tile_w, (index // best_cols) * tile_h))
        lines = self.summary_lines(self.visible_total_counts(), "Total visible blocks")
        summary_h = 12 + 14 * len(lines)
        final = Image.new("RGBA", (max(combined.width, 760), combined.height + summary_h), (15, 17, 20, 255))
        final.alpha_composite(combined, (0, 0))
        draw = ImageDraw.Draw(final)
        self.draw_summary_panel(final, lines, combined.height, draw)
        return final

    def open_options(self) -> None:
        win = tk.Toplevel(self.root)
        win.title(self.t("options.title"))
        win.geometry("620x500")
        win.transient(self.root)
        win.columnconfigure(1, weight=1)
        vars_: dict[str, tk.Variable] = {
            "click_advance": tk.BooleanVar(value=bool(self.settings.get("click_advance"))),
            "show_grid": tk.BooleanVar(value=bool(self.settings.get("show_grid", True))),
            "show_hover_tooltip": tk.BooleanVar(value=bool(self.settings.get("show_hover_tooltip", True))),
            "theme": tk.StringVar(value=str(self.settings.get("theme", "Dark"))),
            "default_texture_path": tk.StringVar(value=str(self.settings.get("default_texture_path", ""))),
            "export_root": tk.StringVar(value=str(self.settings.get("export_root", ""))),
            "base_cell_size": tk.StringVar(value=str(self.settings.get("base_cell_size", 16))),
            "export_tile_size": tk.StringVar(value=str(self.settings.get("export_tile_size", 16))),
            "combined_tile_size": tk.StringVar(value=str(self.settings.get("combined_tile_size", 12))),
            "zoom_step": tk.StringVar(value=str(self.settings.get("zoom_step", 1.15))),
            "block_label_mode": tk.StringVar(value=str(self.settings.get("block_label_mode", "ID + Name"))),
            "app_language": tk.StringVar(value=str(self.settings.get("app_language", "en"))),
        }
        ttk.Checkbutton(win, text=self.t("options.click_advance"), variable=vars_["click_advance"]).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 4))
        ttk.Checkbutton(win, text=self.t("options.show_grid"), variable=vars_["show_grid"]).grid(row=1, column=0, columnspan=3, sticky="w", padx=12, pady=4)
        ttk.Checkbutton(win, text=self.t("options.hover_tooltip"), variable=vars_["show_hover_tooltip"]).grid(row=2, column=0, columnspan=3, sticky="w", padx=12, pady=4)
        ttk.Label(win, text=self.t("options.theme")).grid(row=3, column=0, sticky="w", padx=12, pady=6)
        ttk.Combobox(win, textvariable=vars_["theme"], values=("Dark", "Light"), state="readonly").grid(row=3, column=1, sticky="ew", padx=6, pady=6)
        self.option_path_row(win, 4, self.t("options.default_textures"), vars_["default_texture_path"], files=True)
        self.option_path_row(win, 5, self.t("options.export_folder"), vars_["export_root"], files=False)
        ttk.Label(win, text=self.t("options.block_label")).grid(row=6, column=0, sticky="w", padx=12, pady=6)
        ttk.Combobox(win, textvariable=vars_["block_label_mode"], values=("ID + Name", "Name", "ID"), state="readonly").grid(row=6, column=1, sticky="ew", padx=6, pady=6)
        ttk.Label(win, text=self.t("options.app_language")).grid(row=7, column=0, sticky="w", padx=12, pady=6)
        ttk.Combobox(win, textvariable=vars_["app_language"], values=available_languages(), state="readonly").grid(row=7, column=1, sticky="ew", padx=6, pady=6)
        for row, (key, label) in enumerate((("base_cell_size", self.t("options.viewer_cell_size")), ("export_tile_size", self.t("options.export_tile_size")), ("combined_tile_size", self.t("options.combined_tile_size")), ("zoom_step", self.t("options.zoom_step"))), start=8):
            ttk.Label(win, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=6)
            ttk.Entry(win, textvariable=vars_[key]).grid(row=row, column=1, sticky="ew", padx=6, pady=6)

        def apply() -> None:
            self.settings["click_advance"] = bool(vars_["click_advance"].get())
            self.settings["show_grid"] = bool(vars_["show_grid"].get())
            self.settings["show_hover_tooltip"] = bool(vars_["show_hover_tooltip"].get())
            self.settings["theme"] = str(vars_["theme"].get())
            self.settings["default_texture_path"] = str(vars_["default_texture_path"].get())
            if self.settings["default_texture_path"]:
                self.add_texture_source_recent(Path(self.settings["default_texture_path"]))
            self.settings["export_root"] = str(vars_["export_root"].get())
            self.settings["base_cell_size"] = as_int(vars_["base_cell_size"].get(), 16, 4, 64)
            self.settings["export_tile_size"] = as_int(vars_["export_tile_size"].get(), 16, 4, 128)
            self.settings["combined_tile_size"] = as_int(vars_["combined_tile_size"].get(), 12, 4, 128)
            self.settings["zoom_step"] = as_float(vars_["zoom_step"].get(), 1.15, 1.01, 3.0)
            self.settings["block_label_mode"] = str(vars_["block_label_mode"].get())
            self.settings["app_language"] = str(vars_["app_language"].get()).strip() or "en"
            self.locale.load(self.settings["app_language"])
            self.base_cell = self.settings["base_cell_size"]
            self.save_config()
            texture_path = Path(str(self.settings.get("default_texture_path", ""))).expanduser()
            if texture_path.exists():
                try:
                    count = self.atlas.load(texture_path)
                    lang_count = self.load_language(texture_path)
                    self.status_var.set(f"Options saved; loaded {count} texture mappings; {lang_count} localized names")
                except Exception:
                    logging.exception("Failed to load configured texture path %s", texture_path)
                    self.atlas.clear()
                    self.status_var.set("Options saved; configured texture path could not be loaded")
            else:
                self.status_var.set("Options saved")
            self.apply_theme()
            win.destroy()

        ttk.Button(win, text=self.t("options.save"), command=self.guard(apply)).grid(row=12, column=1, sticky="e", padx=6, pady=14)
        ttk.Button(win, text=self.t("options.cancel"), command=win.destroy).grid(row=12, column=2, sticky="e", padx=12, pady=14)

    def option_path_row(self, win: tk.Toplevel, row: int, label: str, var: tk.Variable, files: bool) -> None:
        ttk.Label(win, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=6)
        ttk.Entry(win, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6, pady=6)
        def browse() -> None:
            if files:
                selected = filedialog.askopenfilename(title="Choose JSON texture source or cancel for folder", filetypes=(("JSON files", "*.json"), ("All files", "*.*")))
                if not selected:
                    selected = filedialog.askdirectory(title="Choose texture folder")
            else:
                selected = filedialog.askdirectory(title="Choose export folder")
            if selected:
                var.set(selected)
        ttk.Button(win, text="Browse", command=self.guard(browse)).grid(row=row, column=2, sticky="ew", padx=12, pady=6)

    def open_about(self) -> None:
        window = tk.Toplevel(self.root)
        window.title(self.t("about.title"))
        window.geometry("520x380")
        window.transient(self.root)
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        text = f"Minecraft Layerifier\n\n{self.t('about.body')}"
        ttk.Label(frame, text=text, wraplength=470, justify="left").pack(anchor="w")
        ttk.Button(frame, text=self.t("about.close"), command=window.destroy).pack(anchor="e", pady=(18, 0))

    def open_log(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not LOG_PATH.exists():
            LOG_PATH.write_text("No log entries yet.\n", encoding="utf-8")
        window = tk.Toplevel(self.root)
        window.title("Layerifier Log")
        window.geometry("900x520")
        window.rowconfigure(0, weight=1)
        window.columnconfigure(0, weight=1)
        text = tk.Text(window, wrap="none")
        text.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(window, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        text.insert("1.0", LOG_PATH.read_text(encoding="utf-8", errors="replace"))
        text.configure(state="disabled")
