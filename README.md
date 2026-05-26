# Blender Render Launcher

A tiny drag-and-drop launcher for **terminal renders** in Blender, built for
Pop!_OS and other GNOME-based Linux desktops.

Rendering from the terminal is faster than the GUI, but starting one means
hunting for the command, opening the right folder, and typing it all out every
time. This app removes that friction: drag a `.blend` file onto the window (or
straight onto its dock icon), click **Render**, and it fires off the terminal
render for you in a real terminal window so you can watch the progress exactly
as you would by hand.

## Features

- Drag-and-drop a `.blend` file, or drop it onto the dock icon to load it instantly
- One-click **Render** that launches a proper terminal render
- Choose between rendering the full **animation** (`-a`) or a **single frame** (`-f`)
- Renders run from the `.blend` file's own folder, so relative output paths behave as expected
- Remembers your Blender command and last-used options between sessions
- Auto-detects your terminal (gnome-terminal, GNOME Console, cosmic-term, tilix, konsole, xterm)
- No third-party dependencies — just Python and GTK, which ship with Pop!_OS

## Requirements

- A GNOME-based Linux desktop (built and tested on Pop!_OS)
- Python 3 with GTK 3 bindings (PyGObject)
- Blender installed and runnable from the command line

If you ever see `No module named 'gi'`, install the GTK bindings:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0
```

## Install

Clone the repository and run the installer:

```bash
git clone https://github.com/<yourusername>/blender-render-launcher.git
cd blender-render-launcher
chmod +x install.sh
./install.sh
```

The installer copies the app into your user folders, registers the icon, and
generates a desktop entry with the correct path for your machine. After it
finishes, open your applications menu (Super key), search for "Blender Render
Launcher", then right-click it and choose **Add to Favourites** to pin it to
your dock.

## Usage

1. Launch the app from your dock or applications menu.
2. Drag a `.blend` file into the window, or use **Browse…**. (You can also drag
   a `.blend` straight onto the dock icon to open it pre-loaded.)
3. Choose **Animation** (renders the full frame range) or **Single frame**.
4. Click **Render**. A terminal opens and runs the render.

Output location, format, samples and so on are all taken from the settings
saved inside the `.blend` file itself — identical to running the command by hand.

### Using a Flatpak or Snap Blender

If Blender is installed as a Flatpak, replace the text in the "Blender command"
box with:

```
flatpak run org.blender.Blender
```

The app remembers it for next time. For most apt or Snap installs, the default
`blender` works as-is.

## Uninstall

```bash
./uninstall.sh
```

## How it works

The app is a small GTK3 window. When you click Render it builds the same
command you'd type yourself — for example `blender -b yourfile.blend -a` —
changes into the file's folder, and hands it to whichever terminal emulator it
finds installed. The render itself is unchanged; only the faff of starting it
is automated.

## License

Released under the MIT License. See [LICENSE](LICENSE).
