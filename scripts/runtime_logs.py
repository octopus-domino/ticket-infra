#!/usr/bin/env python3
"""Read bounded backend logs over SSH and omit lines containing credential fields."""
import argparse
import re
import shlex
import subprocess
from runtime_publish import connection_arguments, ssh_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection_arguments(parser)
    parser.add_argument('--minutes', type=int, default=30)
    parser.add_argument('--tail', type=int, default=300)
    parser.add_argument('--match', default='journey|overpass|photon|brouter|error|exception|429|503')
    args = parser.parse_args()
    if not 1 <= args.minutes <= 1440 or not 1 <= args.tail <= 3000:
        parser.error('Minutes must be 1..1440, tail 1..3000')
    command = shlex.join(['docker', 'logs', '--since', str(args.minutes) + 'm', '--tail', str(args.tail), args.container])
    result = subprocess.run(['ssh', *ssh_options(args), args.target, command], capture_output=True, check=True)
    sensitive = re.compile(r'api.?key|authorization|cookie|access.?token|refresh.?token|password|secret', re.I)
    for line in (result.stdout + result.stderr).decode('utf-8', 'replace').splitlines():
        if re.search(args.match, line, re.I):
            print('[sensitive log line omitted]' if sensitive.search(line) else line)


if __name__ == '__main__':
    main()
