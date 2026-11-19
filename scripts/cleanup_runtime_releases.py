#!/usr/bin/env python3
"""List or delete only old, marked release directories created by runtime_publish.py."""
import argparse
import subprocess
from runtime_publish import connection_arguments, ssh_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection_arguments(parser)
    parser.add_argument('--older-hours', type=int, default=24)
    parser.add_argument('--execute', action='store_true', help='Default is inspection only')
    args = parser.parse_args()
    if args.older_hours < 1:
        parser.error('Keep at least one hour of release files')
    source = '''from pathlib import Path
import shutil, time
root = Path('/tmp').resolve()
for path in root.glob('codoc-runtime-release-*'):
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root:
        continue
    marker = path / '.codoc-runtime-release'
    if not marker.is_file() or marker.read_text() != '1' or time.time() - marker.stat().st_mtime < AGE:
        continue
    print(('remove ' if EXECUTE else 'candidate ') + str(path), flush=True)
    if EXECUTE:
        shutil.rmtree(path)
'''.replace('AGE', str(args.older_hours * 3600)).replace('EXECUTE', repr(args.execute))
    subprocess.run(['ssh', *ssh_options(args), args.target, 'python3 -'], input=source, text=True, check=True)


if __name__ == '__main__':
    main()
