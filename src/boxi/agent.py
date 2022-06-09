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

import fcntl
import json
import os
import pty
import socket
import subprocess
import termios
import threading

class Session(threading.Thread):
    def __init__(self, connection):
        super().__init__(daemon=True)
        self.connection = connection

    def run(self):
        command = json.loads(self.connection.recv(10000))
        theirs, ours = pty.openpty()
        socket.send_fds(self.connection, [b'"pty"'], [theirs])
        os.close(theirs)

        result = subprocess.run(command,
                check=False, start_new_session=True,
                stdin=ours, stdout=ours, stderr=ours,
                preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))

        self.connection.send(json.dumps(result.returncode).encode('ascii'))
        self.connection.close()
        os.close(ours)


def socket_from_fd(fd):
    sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_SEQPACKET)
    os.close(fd)
    return sock


def accept(listener):
    _msg, fds, _flags, _addr = socket.recv_fds(listener, 1, 1)
    if not fds:
        return None
    fd, = fds
    return socket_from_fd(fd)


def main():
    listener = socket_from_fd(3)
    while connection := accept(listener):
        Session(connection).start()


if __name__ == '__main__':
    main()
