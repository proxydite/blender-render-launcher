#!/usr/bin/env python3
"""
Blender Render Launcher
-----------------------
A tiny GTK3 app for Pop!_OS: drag a .blend file in, hit Render, and it
kicks off a *terminal* render (faster than the GUI) in a real terminal
window so you can watch the progress.

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


CSS = b"""
.drop-area {
    border: 2px dashed alpha(@theme_fg_color, 0.35);
    border-radius: 12px;
    padding: 24px;
}
.drop-area.active {
    border-color: @theme_selected_bg_color;
    background: alpha(@theme_selected_bg_color, 0.10);
}
.file-name { font-weight: bold; }
.hint { opacity: 0.6; font-size: 90%; }
"""


class Launcher(Gtk.Window):
    def __init__(self, initial_file=None):
        super().__init__(title="Blender Render Launcher")
        self.set_default_size(480, 420)
        self.set_border_width(16)

        self.blend_path = None
        cfg = load_config()

        # --- CSS ---
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(vbox)

        # --- Drop area ---
        self.drop_event = Gtk.EventBox()
        self.drop_event.get_style_context().add_class("drop-area")
        self.drop_label = Gtk.Label(label="Drop a .blend file here")
        self.drop_label.set_justify(Gtk.Justification.CENTER)
        self.drop_event.add(self.drop_label)
        vbox.pack_start(self.drop_event, True, True, 0)

        # Drag & drop on the whole window
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drag_received)

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
        self.keep_open = Gtk.CheckButton(label="Keep terminal open after render finishes")
        self.keep_open.set_active(cfg.get("keep_open", True))
        vbox.pack_start(self.keep_open, False, False, 0)

        # --- Buttons ---
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        browse_btn = Gtk.Button(label="Browse\u2026")
        browse_btn.connect("clicked", self.on_browse)
        self.render_btn = Gtk.Button(label="Render")
        self.render_btn.get_style_context().add_class("suggested-action")
        self.render_btn.set_sensitive(False)
        self.render_btn.connect("clicked", self.on_render)
        btn_box.pack_start(browse_btn, True, True, 0)
        btn_box.pack_start(self.render_btn, True, True, 0)
        vbox.pack_start(btn_box, False, False, 0)

        if initial_file:
            self.set_file(initial_file)

    # -- helpers ------------------------------------------------------------
    def on_mode_toggled(self, _btn):
        self.frame_spin.set_sensitive(self.still_radio.get_active())

    def set_file(self, path):
        if not path or not path.lower().endswith(".blend"):
            self.error("That doesn't look like a .blend file.")
            return
        self.blend_path = path
        self.drop_label.set_text(os.path.basename(path))
        self.drop_label.get_style_context().add_class("file-name")
        self.render_btn.set_sensitive(True)

    def error(self, msg):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=msg,
        )
        dlg.run()
        dlg.destroy()

    # -- events -------------------------------------------------------------
    def on_drag_received(self, _widget, ctx, _x, _y, data, _info, time):
        chosen = None
        for uri in data.get_uris():
            path = uri_to_path(uri)
            if path and path.lower().endswith(".blend"):
                chosen = path
                break
        Gtk.drag_finish(ctx, chosen is not None, False, time)
        if chosen:
            self.set_file(chosen)
        elif data.get_uris():
            self.error("Please drop a .blend file.")

    def on_browse(self, _btn):
        dlg = Gtk.FileChooserDialog(
            title="Choose a .blend file", parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("_Open", Gtk.ResponseType.OK)
        flt = Gtk.FileFilter()
        flt.set_name("Blender files")
        flt.add_pattern("*.blend")
        dlg.add_filter(flt)
        if dlg.run() == Gtk.ResponseType.OK:
            self.set_file(dlg.get_filename())
        dlg.destroy()

    def on_render(self, _btn):
        if not self.blend_path or not os.path.isfile(self.blend_path):
            self.error("Please choose a .blend file first.")
            return

        blender = self.blender_entry.get_text().strip() or "blender"
        workdir = os.path.dirname(self.blend_path)
        qfile = shlex.quote(self.blend_path)

        if self.still_radio.get_active():
            render_args = "-f %d" % int(self.frame_spin.get_value())
        else:
            render_args = "-a"

        # Build the command. We cd into the .blend's folder first so that
        # relative output paths set inside the file resolve as expected.
        inner = "%s -b %s %s" % (blender, qfile, render_args)
        tail = '; status=$?; echo; echo "\u2500\u2500 Render exited with status $status \u2500\u2500"'
        if self.keep_open.get_active():
            tail += '; echo "Press Enter to close\u2026"; read'
        bash_cmd = "cd %s && %s%s" % (shlex.quote(workdir), inner, tail)

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
        })


def main():
    initial = None
    for arg in sys.argv[1:]:
        if arg.lower().endswith(".blend"):
            initial = arg
            break
    win = Launcher(initial)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
