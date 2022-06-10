import argparse
import subprocess
import os

from boxi import IS_FLATPAK

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('container')
    parser.add_argument('cmd', nargs='+')
    args = parser.parse_args()

    # We do this first, for two reasons:
    #   - give toolbox a chance to start the container if it's not running
    #   - get the exact environment that toolbox would have sent in
    cmd = [
        *(['flatpak-spawn', '--host'] if IS_FLATPAK else []),
        'toolbox', 'run',
        '--container', args.container,
        'env', '-0'
    ]
    env = subprocess.check_output(cmd, stdin=subprocess.DEVNULL)
    env_args = [b'--env=' + key_val for key_val in env.split(b'\0') if key_val]

    cmd = [
        *(['flatpak-spawn', '--host', '--forward-fd=3'] if IS_FLATPAK else []),
        'podman', 'exec',

        '--interactive',
        '--preserve-fds=1',

        '--user', os.getlogin(),
        '--workdir', os.getcwd(),

        *env_args,

        args.container,

        # toolbox does this, so let's do it too!
        'capsh', '--caps=', '--', '-c', 'exec "$@"', '/bin/bash',

        *args.cmd
    ]
    os.execvp(cmd[0], cmd)


if __name__ == '__main__':
    main()
