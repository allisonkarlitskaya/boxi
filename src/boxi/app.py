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
import pty
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

sys.dont_write_bytecode = True

from .adwaita_palette import ADWAITA_PALETTE


class Agent:
    def __init__(self, container):
        self.container = container
        self.connection, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        their_fd = theirs.fileno()

        def dup2_3_and_close_theirs():
            assert their_fd != 3  # second parameter of socketpair()?  can't be 3.
            os.dup2(their_fd, 3)
            os.close(their_fd)

        toolbox_run = os.path.realpath(f'{__file__}/../toolbox_run.py')
        subprocess.Popen([sys.executable, toolbox_run, container, '--', '/usr/bin/python3', '-m', 'boxi.agent'],
                stdin=subprocess.DEVNULL,
                pass_fds=[3],
                preexec_fn=dup2_3_and_close_theirs)

        theirs.close()

    def create_session(self, listener, command):
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        socket.send_fds(self.connection, [b' '], [theirs.fileno()])
        theirs.close()

        session = Session(ours, listener)
        session.send_command(command)
        return session


class Session:
    def __init__(self, connection, listener):
        self.connection = connection
        self.listener = listener
        GLib.unix_fd_add_full(0, self.connection.fileno(), GLib.IOCondition.IN, Session.ready, self)

    def send_command(self, command):
        self.connection.send(json.dumps(command).encode('utf-8'))

    @staticmethod
    def ready(fd, condition, self):
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
        header.set_title(f'Boxi ({application.agent.container})')
        self.set_titlebar(header)
        self.terminal = Terminal()
        self.terminal.set_size(120, 48)
        self.session = application.agent.create_session(self, ['/usr/bin/fish'])
        self.add(self.terminal)
        self.terminal.connect('eof', self.session_eof)

    def session_created(self, pty):
        self.terminal.set_pty(pty)

    def session_exited(self, returncode):
        if hasattr(self, 'command_line') and self.command_line:
            self.command_line.set_exit_status(returncode)
            del self.command_line
        self.destroy()

    def session_eof(self, terminal):
        self.destroy()


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.boxi', flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        Handy.StyleManager.get_default().set_color_scheme(Handy.ColorScheme.PREFER_LIGHT)

    def create_agent(self):
        # A rough heuristic to find a reasonable container to run, until we get something better
        cmd = [
            'podman', 'container', 'list',
            '--filter', 'label=com.github.containers.toolbox',
            '--format', '{{.Names}}'
        ]

        # Prefer running containers, then check all.
        output = subprocess.check_output(cmd, text=True)
        if not output:
            cmd.append('--all')
            output = subprocess.check_output(cmd, text=True)

        if not output:
            sys.exit("Can't decide which container to run")

        container = output.split('\n')[0]
        self.agent = Agent(container)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.create_agent()

    def do_command_line(self, command_line):
        Window(self, command_line).show_all()
        return 0

    def do_activate(self):
        Window(self).show_all()


if __name__ == '__main__':
    app = Application()
    sys.exit(app.run(sys.argv))
