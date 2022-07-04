<img align="left" width="64" height="64" src="data/share/icons/hicolor/scalable/apps/dev.boxi.Boxi.svg">

# Boxi

 - [Boxi on Flathub (recommended way to install)](https://flathub.org/apps/details/dev.boxi.Boxi)
 - [GitHub Project Page](https://github.com/allisonkarlitskaya/boxi/)
 - [PyPI Project Page](https://pypi.org/project/boxi/)

A terminal emulator for use with Toolbox.

This is a thought-experiment app based around the idea of having a terminal emulator running in a separate container from the session inside of it, with the kernel as the only intermediary.

This is accomplished by means of file descriptor passing of the pseudo-terminal device from a small "agent" program running on the other side of a container boundary.  The agent is started using the usual container tools (`flatpak-spawn`, `toolbox`, `podman`), but creating a session is done purely via sockets.

The recommended way to install Boxi is from Flathub, but it's also possible to install via `pip`:

```
pip install boxi
```

The install comes with a `.desktop` file, so Boxi can be launched from the desktop shell.  It can also be launched from the command line:

```
boxi
```

By default, Boxi will create sessions on the host system.  If you'd like to create sessions in a named Toolbox container, use `-c`:

```
boxi -c f36
```

Boxi uses different application identifiers when it is run for different containers.  This allows creating individual launcher icons for each container.  For example, `~/.local/share/applications/dev.boxi.Boxi.f36.desktop`:

```
[Desktop Entry]
Type=Application
Name=Fedora 36 (Boxi)
Icon=fedora
StartupNotify=true
Exec=boxi -c f36
```
