#!/usr/bin/env python3
"""Inspect deployment disk space and optionally reclaim unused Docker build cache only."""
import argparse
import shlex
import subprocess
from runtime_publish import connection_arguments, ssh_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection_arguments(parser)
    parser.add_argument('--prune-build-cache', action='store_true')
    parser.add_argument('--reserve-mib', type=int, default=512)
    args = parser.parse_args()
    if args.reserve_mib < 256:
        parser.error('Keep at least 256 MiB of build cache')
    options = ssh_options(args)
    if args.prune_build_cache:
        command = shlex.join(['docker', 'builder', 'prune', '--all', '--force', '--keep-storage=' + str(args.reserve_mib) + 'MB'])
        subprocess.run(['ssh', *options, args.target, command], check=True)
    for command in ['df -h /', 'docker system df']:
        subprocess.run(['ssh', *options, args.target, command], check=True)


if __name__ == '__main__':
    main()
