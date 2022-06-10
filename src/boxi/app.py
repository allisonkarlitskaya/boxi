# Boxi - Terminal emulator for use with Toolbox
#
# Copyright (C) 2022 Allison Karlitskaya <allison.karlitskaya@redhat.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import os
import signal
import socket
import subprocess
import sys

import gi

gi.require_version('Handy', '1')
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Vte', '2.91')

from gi.repository import GLib
from gi.repository import Gdk, Gio, Gtk, Handy, Vte

from .adwaita_palette import ADWAITA_PALETTE
from . import APP_ID, IS_FLATPAK, PKG_DIR


class Agent:
    def __init__(self, container=None):
        self.container = container
        self.connection, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        their_fd = theirs.fileno()

        def dup2_3_and_close_theirs():
            assert their_fd != 3  # second parameter of socketpair()?  can't be 3.
            os.dup2(their_fd, 3)
            os.close(their_fd)

        if container:
            cmd = [sys.executable, f'{PKG_DIR}/toolbox_run.py', container, '--', '/usr/bin/python3']
        elif IS_FLATPAK:
            cmd = ['flatpak-spawn', '--host', '--forward-fd=3', '/usr/bin/python3']
        else:
            cmd = [sys.executable]

        with open(f'{PKG_DIR}/agent.py', 'rb') as agent_py:
            subprocess.Popen(cmd, stdin=agent_py, pass_fds=[3], preexec_fn=dup2_3_and_close_theirs)

        theirs.close()

    def create_session(self, listener):
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        socket.send_fds(self.connection, [b' '], [theirs.fileno()])
        theirs.close()

        return Session(ours, listener)


class Session:
    def __init__(self, connection, listener):
        self.connection = connection
        self.listener = listener
        GLib.unix_fd_add_full(0, self.connection.fileno(), GLib.IOCondition.IN, Session.ready, self)

    def start_shell(self):
        self.connection.send(b'[]')

    def start_command(self, command):
        self.connection.send(json.dumps(command).encode('utf-8'))

    def open_editor(self):
        reader, writer = os.pipe()
        socket.send_fds(self.connection, [b'["vi", "-"]'], [reader])
        return Gio.UnixOutputStream.new(writer, True)

    @staticmethod
    def ready(fd, _condition, self):
        msg, fds, _flags, _addr = socket.recv_fds(self.connection, 10000, 1)
        if not msg:
            self.listener.session_eof(None)
            return False

        message = json.loads(msg)

        if message == 'pty':
            self.listener.session_created(Vte.Pty.new_foreign_sync(fds.pop()))
        elif isinstance(message, int):
            self.listener.session_exited(message)

        for fd in fds:
            os.close(fd)

        return True


class Terminal(Vte.Terminal):
    def __init__(self):
        super().__init__()
        self.set_audible_bell(False)
        self.set_scrollback_lines(-1)

    @staticmethod
    def parse_color(color):
        rgba = Gdk.RGBA()
        rgba.parse(color if color.startswith('#') else ADWAITA_PALETTE[color])
        return rgba

    def set_palette(self, fg=None, bg=None, palette=()):
        self.set_colors(fg and Terminal.parse_color(fg),
                        bg and Terminal.parse_color(bg),
                        [Terminal.parse_color(color) for color in palette])

    def do_style_updated(self):
        # See https://gitlab.gnome.org/Teams/Design/hig-www/-/issues/129 and
        # https://gitlab.gnome.org/Teams/Design/HIG-app-icons/-/commit/4e1dfe95748a6ee80cc9c0e6c40a891c0f4d534c
        palette = ['dark_4', 'red_4', 'green_4', 'yellow_4', 'blue_4', 'purple_4', '#0a8dcb', 'light_4',
                   'dark_2', 'red_2', 'green_2', 'yellow_2', 'blue_2', 'purple_2', '#4fd2fd', 'light_2']

        if Handy.StyleManager.get_default().get_dark():
            self.set_palette('light_1', 'dark_5', palette)
        else:
            self.set_palette('dark_5', 'light_1', palette)


class Window(Gtk.ApplicationWindow):
    def __init__(self, application, command_line=None):
        super().__init__(application=application)
        self.command_line = command_line
        header = Gtk.HeaderBar()
        if application.container:
            header.set_title(f'Boxi ({application.container})')
        else:
            header.set_title(f'Boxi')
        header.set_show_close_button(True)
        self.set_titlebar(header)
        self.terminal = Terminal()
        self.terminal.set_size(120, 48)
        self.session = application.agent.create_session(self)
        self.add(self.terminal)
        self.terminal.connect('eof', self.session_eof)
        Gio.ActionMap.add_action_entries(self, [
            ('new-window', self.new_window),
            ('edit-contents', self.edit_contents),
            ('copy', self.copy),
            ('paste', self.paste),
            ('zoom', self.zoom, 's'),
        ])

    def session_created(self, pty):
        self.terminal.set_pty(pty)

    def session_exited(self, returncode):
        if hasattr(self, 'command_line') and self.command_line:
            self.command_line.set_exit_status(returncode)
            del self.command_line
        self.destroy()

    def session_eof(self, terminal):
        self.destroy()

    def new_window(self, *_args):
        window = Window(self.get_application())
        window.session.start_shell()
        window.show_all()

    def edit_contents(self, *_args):
        window = Window(self.get_application())
        window.show_all()

        stream = window.session.open_editor()
        self.terminal.write_contents_sync(stream, Vte.WriteFlags.DEFAULT, None)
        stream.close()

    def copy(self, *_args):
        self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self, *_args):
        self.terminal.paste_clipboard()

    def zoom(self, action, parameter, *_args):
        current = self.terminal.get_font_scale()
        factors = {'in': current * 1.2, 'default': 1.0, 'out': current * 0.8}
        self.terminal.set_font_scale(factors[parameter.get_string()])


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

        self.add_option('version', description='Show version')
        self.add_option('container', 'c', arg=GLib.OptionArg.STRING, description='Toolbox container name')
        self.add_option('', arg=GLib.OptionArg.STRING_ARRAY, arg_description='COMMAND ARGS ...')

    def add_option(self, long_name, short_name=None, flags=GLib.OptionFlags.NONE,
            arg=GLib.OptionArg.NONE, description='', arg_description=None):
        short_char = ord(short_name) if short_name is not None else 0
        self.add_main_option(long_name, short_char, flags, arg, description, arg_description)

    def do_handle_local_options(self, options):
        if options.contains('version'):
            from . import __version__ as version
            print(f'Boxi {version}')
            return 0

        if options.contains('container'):
            self.container = options.lookup_value('container').get_string()
            self.set_application_id(f'{APP_ID}.{self.container}')
        else:
            self.set_application_id(APP_ID)
            self.container = None

        # Ideally, GApplication would have a flag for this, but it's a little
        # bit magic.  In case `--gapplication-service` wasn't given, we want to
        # first try to become a launcher.  If that fails then we fall back to
        # the standard hybrid mode where we might end up as the primary or
        # remote instance.  This allows the benefits of being a launcher (more
        # consistent commandline behaviour) opportunistically, without breaking
        # the partially-installed case.
        flags = self.get_flags()
        if not flags & Gio.ApplicationFlags.IS_SERVICE:
            try:
                self.set_flags(flags | Gio.ApplicationFlags.IS_LAUNCHER)
                self.register()
            except GLib.Error:
                # didn't work?  Put it back.
                self.set_flags(flags)

        return -1

    def do_startup(self):
        Gtk.Application.do_startup(self)

        Handy.StyleManager.get_default().set_color_scheme(Handy.ColorScheme.PREFER_LIGHT)

        self.set_accels_for_action("win.new-window", ["<Ctrl><Shift>N"])
        self.set_accels_for_action("win.edit-contents", ["<Ctrl><Shift>S"])
        self.set_accels_for_action("win.copy", ["<Ctrl><Shift>C"])
        self.set_accels_for_action("win.paste", ["<Ctrl><Shift>V"])
        self.set_accels_for_action("win.zoom::default", ["<Ctrl>0"])
        self.set_accels_for_action("win.zoom::in", ["<Ctrl>equal", "<Ctrl>plus"])
        self.set_accels_for_action("win.zoom::out", ["<Ctrl>minus"])

        self.agent = Agent(self.container)

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        argv = options.lookup_value('')

        window = Window(self, command_line)
        if argv:
            window.session.start_command(argv.get_strv())
        else:
            window.session.start_shell()
        window.show_all()

        return -1  # real return value comes later

    def do_activate(self):
        window = Window(self)
        window.session.start_shell()
        window.show_all()


def main():
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)  # because we don't clean up after the agent
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # because KeyboardInterrupt doesn't work with gmain
    sys.exit(Application().run(sys.argv))
