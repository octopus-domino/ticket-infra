#!/usr/bin/env python3
"""Publish one runtime component over system SSH; credentials stay outside the repository."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import uuid
import zipfile


def connection_arguments(parser):
    """Use the user's SSH agent/config by default; never read or copy private key contents."""
    parser.add_argument('--target', required=True, help='SSH alias or user@host from your SSH configuration')
    parser.add_argument('--identity', type=Path, help='Optional external SSH private key path')
    parser.add_argument('--container', default='codoc-app-1')


def ssh_options(args):
    if not re.fullmatch(r'[\w.@:-]+', args.target) or not re.fullmatch(r'[\w.-]+', args.container):
        raise ValueError('Invalid SSH target or container name')
    options = ['-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=10']
    return options + (['-i', str(args.identity.resolve())] if args.identity else [])


def run_remote(args, config):
    """Send a versioned remote program through stdin without installing a server or editing Nginx."""
    encoded = base64.b64encode(json.dumps(config).encode()).decode()
    source = Path(__file__).with_name('runtime_publish_remote.py').read_text(encoding='utf-8')
    command = 'python3 - ' + shlex.quote(encoded)
    subprocess.run(['ssh', *ssh_options(args), args.target, command], input=source, text=True, check=True)


def pack_web(source, archive):
    source = source.resolve(strict=True)
    if not (source / 'index.html').is_file():
        raise ValueError('Use a built frontend directory containing index.html')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlinks are not allowed in a published frontend')
            if path.is_file():
                relative = path.relative_to(source)
                if any(part.startswith('.') for part in relative.parts):
                    continue
                output.write(path, 'web/' + relative.as_posix())


def pack_classes(source, prefixes, archive):
    """Patch only explicitly selected Java packages/classes, including their nested classes."""
    source = source.resolve(strict=True)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        count = 0
        for path in sorted(source.rglob('*.class')):
            relative = path.relative_to(source).as_posix()
            if not any(relative.startswith(prefix) for prefix in prefixes):
                continue
            if int.from_bytes(path.read_bytes()[6:8], 'big') != 61:
                raise ValueError('The production Java 17 runtime requires class-file version 61')
            output.write(path, 'BOOT-INF/classes/' + relative)
            count += 1
    if not count:
        raise ValueError('No classes matched the selected prefixes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection_arguments(parser)
    actions = parser.add_subparsers(dest='action', required=True)
    web = actions.add_parser('web', help='Publish built editor or private-journey frontend without restarting Java')
    web.add_argument('--component', choices=['editor', 'private-journey'], required=True)
    web.add_argument('--dist', type=Path, required=True)
    backend = actions.add_parser('backend', help='Patch selected compiled classes and restart only Java')
    backend.add_argument('--classes', type=Path, required=True)
    backend.add_argument('--class-prefix', action='append', required=True,
                         help='For example ru/ticket/journey/walk/AreaSearchCoordinator')
    backend.add_argument('--health-path', default='/api/journeys/routes/places/themes')
    backend.add_argument('--backend-port', type=int, default=8080)
    args = parser.parse_args()
    if not re.fullmatch(r'[\w.@:-]+', args.target) or not re.fullmatch(r'[\w.-]+', args.container):
        parser.error('Invalid SSH target or container name')
    if args.action == 'backend' and any(not re.fullmatch(r'ru/ticket/[\w/$-]+', value) for value in args.class_prefix):
        parser.error('Class prefixes must be explicit ru/ticket paths')
    with tempfile.TemporaryDirectory(prefix='codoc-publish-') as temporary:
        archive = Path(temporary) / 'payload.zip'
        if args.action == 'web':
            pack_web(args.dist, archive)
        else:
            pack_classes(args.classes, args.class_prefix, archive)
        remote_file = '/tmp/codoc-runtime-' + uuid.uuid4().hex + '.zip'
        subprocess.run(['scp', *ssh_options(args), str(archive), args.target + ':' + remote_file], check=True)
        config = dict(action=args.action, container=args.container, payload=remote_file,
                      sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        if args.action == 'web':
            config['component'] = args.component
        else:
            config.update(health_path=args.health_path, backend_port=args.backend_port)
        run_remote(args, config)


if __name__ == '__main__':
    main()
