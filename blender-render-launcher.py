#!/usr/bin/env python3
"""
Blender Render Launcher
-----------------------
A tiny GTK3 app for Pop!_OS: drop one or more .blend files (or a folder of
them) into the queue, hit Render, and it runs a *terminal* render of each in
turn (faster than the GUI) in a real terminal window so you can watch progress.

Batch renders run sequentially. If a file fails, the batch carries on and you
get a summary popup at the end listing what succeeded and what failed — handy
for unattended overnight queues.

No third-party dependencies — uses PyGObject (GTK3), which ships with
Pop!_OS by default.
"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

import os
import sys
import json
import shlex
import shutil
import tempfile
import subprocess
from urllib.parse import urlparse, unquote

# ---------------------------------------------------------------------------
# Config persistence (remembers your Blender command + last-used options)
# ---------------------------------------------------------------------------
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "blender-render-launcher")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Terminal detection. We try common emulators in order and use whichever
# one is installed. Each lambda turns a bash command string into an argv list.
# ---------------------------------------------------------------------------
TERMINALS = [
    ("gnome-terminal", lambda c: ["gnome-terminal", "--", "bash", "-lc", c]),
    ("kgx",            lambda c: ["kgx", "--", "bash", "-lc", c]),            # GNOME Console
    ("cosmic-term",    lambda c: ["cosmic-term", "--", "bash", "-lc", c]),    # Pop!_OS COSMIC
    ("tilix",          lambda c: ["tilix", "-e", "bash -lc " + shlex.quote(c)]),
    ("konsole",        lambda c: ["konsole", "-e", "bash", "-lc", c]),
    ("xterm",          lambda c: ["xterm", "-e", "bash", "-lc", c]),
]


def find_terminal(bash_cmd):
    for exe, builder in TERMINALS:
        if shutil.which(exe):
            return builder(bash_cmd)
    return None


def uri_to_path(uri):
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return unquote(parsed.path)
    return None


def collect_blend_files(path, recursive):
    """Given a dropped path, return a list of .blend files.

    A file path returns itself (if it's a .blend). A directory is scanned —
    just the top level, or every subfolder too when recursive is True.
    """
    found = []
    if os.path.isfile(path):
        if path.lower().endswith(".blend"):
            found.append(path)
    elif os.path.isdir(path):
        if recursive:
            for root, _dirs, files in os.walk(path):
                for name in sorted(files):
                    if name.lower().endswith(".blend"):
                        found.append(os.path.join(root, name))
        else:
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isfile(full) and name.lower().endswith(".blend"):
                    found.append(full)
    return found


CSS = b"""
.queue-frame {
    border: 2px dashed alpha(@theme_fg_color, 0.35);
    border-radius: 12px;
}
.hint { opacity: 0.6; }
"""


class Launcher(Gtk.Window):
    def __init__(self, initial_files=None):
        super().__init__(title="Blender Render Launcher")
        self.set_default_size(560, 560)
        self.set_border_width(16)

        # The render queue: an ordered list of absolute .blend paths.
        self.queue = []
        cfg = load_config()

        # --- CSS ---
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(vbox)

        # --- Queue list (scrollable) ---
        self.store = Gtk.ListStore(str)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(False)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("File", renderer)
        col.set_cell_data_func(renderer, self._render_row)
        self.tree.append_column(col)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self.tree)
        scroller.get_style_context().add_class("queue-frame")
        vbox.pack_start(scroller, True, True, 0)

        self.hint = Gtk.Label(label="Drop .blend files or a folder here")
        self.hint.get_style_context().add_class("hint")
        vbox.pack_start(self.hint, False, False, 0)

        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drag_received)

        # --- Queue management buttons (reorder / remove / clear) ---
        list_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        up_btn = Gtk.Button(label="\u25b2 Up")
        down_btn = Gtk.Button(label="\u25bc Down")
        remove_btn = Gtk.Button(label="\u2715 Remove")
        clear_btn = Gtk.Button(label="Clear all")
        up_btn.connect("clicked", self.on_move_up)
        down_btn.connect("clicked", self.on_move_down)
        remove_btn.connect("clicked", self.on_remove_selected)
        clear_btn.connect("clicked", self.on_clear)
        for b in (up_btn, down_btn, remove_btn):
            list_btns.pack_start(b, False, False, 0)
        list_btns.pack_end(clear_btn, False, False, 0)
        vbox.pack_start(list_btns, False, False, 0)

        # --- Folder scan depth toggle ---
        self.recursive_check = Gtk.CheckButton(
            label="When dropping a folder, include subfolders"
        )
        self.recursive_check.set_active(cfg.get("recursive", False))
        vbox.pack_start(self.recursive_check, False, False, 0)

        # --- Blender command row ---
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cmd_label = Gtk.Label(label="Blender command:")
        self.blender_entry = Gtk.Entry()
        self.blender_entry.set_text(cfg.get("blender_cmd", "blender"))
        self.blender_entry.set_tooltip_text(
            "Usually just 'blender'. For a Flatpak install use:\n"
            "flatpak run org.blender.Blender"
        )
        cmd_box.pack_start(cmd_label, False, False, 0)
        cmd_box.pack_start(self.blender_entry, True, True, 0)
        vbox.pack_start(cmd_box, False, False, 0)

        # --- Render mode ---
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.anim_radio = Gtk.RadioButton.new_with_label_from_widget(None, "Animation (-a)")
        self.still_radio = Gtk.RadioButton.new_with_label_from_widget(self.anim_radio, "Single frame")
        self.frame_spin = Gtk.SpinButton.new_with_range(0, 1_000_000, 1)
        self.frame_spin.set_value(1)
        self.frame_spin.set_sensitive(False)
        self.anim_radio.connect("toggled", self.on_mode_toggled)

        if cfg.get("mode") == "still":
            self.still_radio.set_active(True)
            self.frame_spin.set_sensitive(True)

        mode_box.pack_start(self.anim_radio, False, False, 0)
        mode_box.pack_start(self.still_radio, False, False, 0)
        mode_box.pack_start(Gtk.Label(label="frame:"), False, False, 0)
        mode_box.pack_start(self.frame_spin, False, False, 0)
        vbox.pack_start(mode_box, False, False, 0)

        # --- Keep terminal open ---
        self.keep_open = Gtk.CheckButton(label="Keep terminal open after batch finishes")
        self.keep_open.set_active(cfg.get("keep_open", True))
        vbox.pack_start(self.keep_open, False, False, 0)

        # --- Buttons ---
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_btn = Gtk.Button(label="Add files\u2026")
        add_btn.connect("clicked", self.on_browse)
        self.render_btn = Gtk.Button(label="Render")
        self.render_btn.get_style_context().add_class("suggested-action")
        self.render_btn.set_sensitive(False)
        self.render_btn.connect("clicked", self.on_render)
        btn_box.pack_start(add_btn, True, True, 0)
        btn_box.pack_start(self.render_btn, True, True, 0)
        vbox.pack_start(btn_box, False, False, 0)

        self._results_path = None
        self._expected_count = 0

        if initial_files:
            self.add_paths(initial_files)

    # -- queue helpers ------------------------------------------------------
    def _render_row(self, _col, cell, model, it, _data):
        path = model[it][0]
        idx = model.get_path(it).get_indices()[0] + 1
        cell.set_property("text", "%d.  %s" % (idx, os.path.basename(path)))

    def _refresh(self):
        self.store.clear()
        for p in self.queue:
            self.store.append([p])
        empty = not self.queue
        self.hint.set_visible(empty)
        self.render_btn.set_sensitive(not empty)
        if empty:
            self.render_btn.set_label("Render")
        elif len(self.queue) == 1:
            self.render_btn.set_label("Render 1 file")
        else:
            self.render_btn.set_label("Render %d files" % len(self.queue))

    def add_paths(self, paths):
        recursive = self.recursive_check.get_active()
        added = 0
        skipped_nonblend = False
        for p in paths:
            blends = collect_blend_files(p, recursive)
            if not blends and os.path.isfile(p):
                skipped_nonblend = True
            for b in blends:
                if b not in self.queue:
                    self.queue.append(b)
                    added += 1
        self._refresh()
        if added == 0 and skipped_nonblend:
            self.error("Please drop .blend files or a folder containing them.")

    def selected_rows(self):
        model, paths = self.tree.get_selection().get_selected_rows()
        return sorted(p.get_indices()[0] for p in paths)

    def _reselect(self, indices):
        sel = self.tree.get_selection()
        sel.unselect_all()
        for i in indices:
            if 0 <= i < len(self.queue):
                sel.select_path(Gtk.TreePath(i))

    # -- button handlers ----------------------------------------------------
    def on_move_up(self, _btn):
        rows = self.selected_rows()
        if not rows or rows[0] == 0:
            return
        new_sel = []
        for i in rows:
            self.queue[i - 1], self.queue[i] = self.queue[i], self.queue[i - 1]
            new_sel.append(i - 1)
        self._refresh()
        self._reselect(new_sel)

    def on_move_down(self, _btn):
        rows = self.selected_rows()
        if not rows or rows[-1] == len(self.queue) - 1:
            return
        new_sel = []
        for i in reversed(rows):
            self.queue[i + 1], self.queue[i] = self.queue[i], self.queue[i + 1]
            new_sel.append(i + 1)
        self._refresh()
        self._reselect(new_sel)

    def on_remove_selected(self, _btn):
        rows = self.selected_rows()
        for i in reversed(rows):
            del self.queue[i]
        self._refresh()

    def on_clear(self, _btn):
        self.queue = []
        self._refresh()

    def on_mode_toggled(self, _btn):
        self.frame_spin.set_sensitive(self.still_radio.get_active())

    def error(self, msg):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=msg,
        )
        dlg.run()
        dlg.destroy()

    # -- drag & drop / browse ----------------------------------------------
    def on_drag_received(self, _widget, ctx, _x, _y, data, _info, time):
        paths = []
        for uri in data.get_uris():
            p = uri_to_path(uri)
            if p:
                paths.append(p)
        Gtk.drag_finish(ctx, bool(paths), False, time)
        if paths:
            self.add_paths(paths)

    def on_browse(self, _btn):
        dlg = Gtk.FileChooserDialog(
            title="Add .blend files", parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Add", Gtk.ResponseType.OK)
        dlg.set_select_multiple(True)
        flt = Gtk.FileFilter()
        flt.set_name("Blender files")
        flt.add_pattern("*.blend")
        dlg.add_filter(flt)
        if dlg.run() == Gtk.ResponseType.OK:
            self.add_paths(dlg.get_filenames())
        dlg.destroy()

    # -- rendering ----------------------------------------------------------
    def on_render(self, _btn):
        if not self.queue:
            self.error("Add at least one .blend file first.")
            return

        blender = self.blender_entry.get_text().strip() or "blender"
        if self.still_radio.get_active():
            render_args = "-f %d" % int(self.frame_spin.get_value())
        else:
            render_args = "-a"

        fd, results_path = tempfile.mkstemp(prefix="brl-results-", suffix=".tsv")
        os.close(fd)
        self._results_path = results_path
        self._expected_count = len(self.queue)

        total = len(self.queue)
        lines = ["set +e"]
        for i, path in enumerate(self.queue, start=1):
            qpath = shlex.quote(path)
            qdir = shlex.quote(os.path.dirname(path))
            header = "[%d/%d] Rendering %s" % (i, total, os.path.basename(path))
            lines.append('echo; echo "\u2500\u2500\u2500 %s \u2500\u2500\u2500"'
                         % header.replace('"', '\\"'))
            lines.append("( cd %s && %s -b %s %s )"
                         % (qdir, blender, qpath, render_args))
            lines.append("st=$?")
            lines.append('printf "%%s\\t%%s\\n" "$st" %s >> %s'
                         % (qpath, shlex.quote(results_path)))
            lines.append('if [ "$st" -ne 0 ]; then '
                         'echo ">>> FAILED (exit $st): %s"; fi'
                         % os.path.basename(path).replace('"', '\\"'))
        lines.append('echo; echo "\u2500\u2500\u2500 Batch complete \u2500\u2500\u2500"')
        if self.keep_open.get_active():
            lines.append('echo "Press Enter to close\u2026"; read')

        bash_cmd = "\n".join(lines)

        argv = find_terminal(bash_cmd)
        if not argv:
            self.error(
                "No supported terminal emulator found.\n"
                "Tried: gnome-terminal, kgx, cosmic-term, tilix, konsole, xterm."
            )
            return

        try:
            subprocess.Popen(argv)
        except Exception as e:
            self.error("Failed to launch the terminal:\n%s" % e)
            return

        save_config({
            "blender_cmd": blender,
            "mode": "still" if self.still_radio.get_active() else "anim",
            "keep_open": self.keep_open.get_active(),
            "recursive": self.recursive_check.get_active(),
        })

        GLib.timeout_add(500, self._poll_results)

    def _poll_results(self):
        path = self._results_path
        if not path or not os.path.exists(path):
            return True
        try:
            with open(path) as f:
                rows = [ln.rstrip("\n") for ln in f if ln.strip()]
        except Exception:
            return True

        if len(rows) < self._expected_count:
            return True

        succeeded, failed = [], []
        for row in rows:
            parts = row.split("\t", 1)
            if len(parts) != 2:
                continue
            status, fpath = parts
            name = os.path.basename(fpath)
            if status == "0":
                succeeded.append(name)
            else:
                failed.append((name, status))

        try:
            os.remove(path)
        except Exception:
            pass
        self._results_path = None
        self._show_summary(succeeded, failed)
        return False

    def _show_summary(self, succeeded, failed):
        total = len(succeeded) + len(failed)
        if failed:
            msg_type = Gtk.MessageType.WARNING
            heading = "Batch finished: %d of %d rendered, %d failed" % (
                len(succeeded), total, len(failed))
        else:
            msg_type = Gtk.MessageType.INFO
            heading = "Batch finished: all %d rendered successfully" % total

        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=msg_type, buttons=Gtk.ButtonsType.OK,
            text=heading,
        )
        if failed:
            detail_lines = ["Failed files (exit code):"]
            for name, status in failed:
                detail_lines.append("  \u2022 %s  (exit %s)" % (name, status))
            detail_lines.append("")
            detail_lines.append(
                "Re-render these, or open them in Blender to investigate. "
                "A non-zero exit usually means a Python/script error, a "
                "missing linked asset, or an output path that can't be written."
            )
            dlg.format_secondary_text("\n".join(detail_lines))
        dlg.run()
        dlg.destroy()


def main():
    initial = [a for a in sys.argv[1:]
               if a.lower().endswith(".blend") or os.path.isdir(a)]
    win = Launcher(initial or None)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    win.hint.set_visible(not win.queue)
    Gtk.main()


if __name__ == "__main__":
    main()
