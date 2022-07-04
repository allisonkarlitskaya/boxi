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

import argparse
import asyncio
import json
import logging
import os
import textwrap

logger = logging.getLogger('boxi.monitor')


class ContainerTracker:
    def __init__(self, filters=(), podman=None):
        self.filters = [f'--filter={item}' for item in filters]
        self.podman = podman or 'podman'

        self.containers = set()

    def update(self):
        raise NotImplementedError

    async def run(self):
        # We combine monitoring with an initial run of 'podman container list' in
        # order to build our view of the world and keep it in sync.  There is a
        # race here, though: although we start the monitoring before we query the
        # current list, we don't know if the monitoring was successfully
        # established before our list command ran.  To work around that race,
        # we request all events since 10s ago to be reported.
        events = await asyncio.create_subprocess_exec(self.podman,
                'events',
                '--format=json',
                '--since=10s',
                '--filter=type=container',
                *self.filters,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE)

        # Collect the initial list of containers
        container_list = await asyncio.create_subprocess_exec(self.podman,
                'container',
                'list',
                '--format=json',
                '--all',
                *self.filters,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE)

        stdout, _stderr = await container_list.communicate()
        for container in json.loads(stdout):
            try:
                self.containers.update(container['Names'])
            except KeyError:
                pass

        # Initial state synchronisation
        self.update()

        # Process the event queue
        while line := await events.stdout.readline():
            message = json.loads(line)
            try:
                object_type = message['Type']
                status = message['Status']
                name = message['Name']
            except KeyError:
                continue

            length_before = len(self.containers)

            if object_type == 'container' and name:
                if status == 'create':
                    self.containers.add(name)
                elif status == 'remove':
                    self.containers.remove(name)

            # Any possible change above changes the length
            if len(self.containers) != length_before:
                self.update()

        await events.wait()


class BoxiDesktopFileManager(ContainerTracker):
    def __init__(self, flatpak=False, appid=None, execbase=None, **kwargs):
        super().__init__(filters=['label=com.github.containers.toolbox=true'], **kwargs)

        self.appid = appid or 'dev.boxi.Boxi'
        self.execbase = execbase or (f'flatpak run {self.appid}' if flatpak else 'boxi')

        xdg_data_home = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
        self.private_dir = f'{xdg_data_home}/{self.appid}/launchers'
        self.public_dir = f'{xdg_data_home}/applications'

        self.have_files = set()

        os.makedirs(self.private_dir, exist_ok=True)
        for entry in os.scandir(self.private_dir):
            if entry.is_file(follow_symlinks=False):
                slices = entry.name.rsplit('.', 2)
                if len(slices) == 3 and slices[0] == self.appid and slices[2] == 'desktop':
                    self.have_files.add(slices[1])


    def install(self, container):
        if container.startswith('f'):
            icon = f'{self.appid}.fedora'
        else:
            icon = self.appid

        contents = f"""
            [Desktop Entry]
            Type=Application
            Name={container} Toolbox (Boxi)
            Icon={icon}
            StartupNotify=true
            Exec={self.execbase} -c {container}
        """

        basename = f'{self.appid}.{container}.desktop'
        private = f'{self.private_dir}/{basename}'
        public = f'{self.public_dir}/{basename}'

        os.makedirs(self.private_dir, exist_ok=True)
        try:
            with open(private, 'x', encoding='utf-8') as fp:
                fp.write(textwrap.dedent(contents).lstrip())
        except FileExistsError:
            pass

        os.makedirs(self.public_dir, exist_ok=True)
        try:
            os.symlink(os.path.relpath(private, start=self.public_dir), public)
        except FileExistsError:
            pass

        self.have_files.add(container)

    def uninstall(self, container):
        basename = f'{self.appid}.{container}.desktop'
        private = f'{self.private_dir}/{basename}'
        public = f'{self.public_dir}/{basename}'

        try:
            # should check if symlink points to us
            os.unlink(public)
        except FileNotFoundError:
            pass

        try:
            os.unlink(private)
        except FileNotFoundError:
            pass

        self.have_files.remove(container)

    def update(self):
        logger.debug('list of files is now %s', self.have_files)
        logger.debug('list of containers is now %s', self.containers)

        to_install = self.containers - self.have_files
        to_remove = self.have_files - self.containers

        for container in to_install:
            logger.debug('install %s', container)
            self.install(container)

        for container in to_remove:
            logger.debug('uninstall %s', container)
            self.uninstall(container)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--flatpak', action='store_true', help="Install desktop files for flatpaked Boxi?")
    parser.add_argument('--appid', required=False, help="Application ID [default: 'dev.boxi.Boxi']")
    parser.add_argument('--exec', required=False, help="The prefix for the Exec= line in created desktop files")
    parser.add_argument('--podman', required=False, help="Path to podman [default: 'podman']")
    args = parser.parse_args()

    manager = BoxiDesktopFileManager(flatpak=args.flatpak, appid=args.appid, execbase=args.exec, podman=args.podman)
    asyncio.run(manager.run())


if __name__ == '__main__':
    main()
