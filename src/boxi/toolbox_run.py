import argparse
import subprocess
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('container')
    parser.add_argument('cmd', nargs='+')
    args = parser.parse_args()

    # We do this first, for two reasons:
    #   - give toolbox a chance to start the container if it's not running
    #   - get the exact environment that toolbox would have sent in
    env = subprocess.check_output(['toolbox', 'run', '--container', args.container, 'env', '-0'])
    env_args = [b'--env=' + key_val for key_val in env.split(b'\0') if key_val]

    os.execvp('podman', [
        'podman', 'exec',

        '--preserve-fds=1',

        '--user', os.getlogin(),
        '--workdir', os.getcwd(),

        *env_args,

        args.container,

        # toolbox does this, so let's do it too!
        'capsh', '--caps=', '--', '-c', 'exec "$@"', '/bin/bash',

        *args.cmd
    ])


if __name__ == '__main__':
    main()
