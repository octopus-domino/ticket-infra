"""Internal remote half of runtime_publish.py. Run only through that command."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


def run(*arguments):
    return subprocess.run(arguments, check=True, capture_output=True)


def checked_members(archive, action):
    """Reject traversal, unexpected payloads and expanded archives above the deployment budget."""
    infos = archive.infolist()
    if not infos or sum(info.file_size for info in infos) > 512 * 1024 * 1024:
        raise ValueError('Invalid payload size')
    prefix = 'web/' if action == 'web' else 'BOOT-INF/classes/ru/ticket/'
    for info in infos:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in info.orig_filename or '\0' in info.orig_filename or not info.filename.startswith(prefix):
            raise ValueError('Invalid payload member')
        if action == 'backend' and not info.filename.endswith('.class'):
            raise ValueError('Only compiled classes may patch the backend')
    return infos


def backend_pid(container):
    candidates = run('docker', 'exec', container, 'pidof', 'java').stdout.split()
    matches = []
    for candidate in candidates:
        path = '/proc/' + candidate.decode() + '/cmdline'
        command = run('docker', 'exec', container, 'cat', path).stdout.split(b'\0')
        if command[1:3] == [b'-jar', b'/app/app.jar']:
            matches.append(candidate.decode())
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one supervised CoDoc Java process')
    return matches[0]


def ready(config):
    url = 'http://127.0.0.1:' + str(config['backend_port']) + config['health_path']
    for _ in range(40):
        result = subprocess.run(['docker', 'exec', config['container'], 'curl', '-s', '--max-time', '2',
                                 '-o', '/dev/null', '-w', '%{http_code}', url], capture_output=True)
        # A protected actuator's 401 is deliberately not used as a health signal.
        if result.returncode == 0 and result.stdout == b'200':
            return True
        time.sleep(2)
    return False


def build_image(stage, container, copy_lines, release):
    image = run('docker', 'inspect', '--format', '{{.Config.Image}}', container).stdout.decode().strip()
    if image != 'codoc-app:latest' and image != 'codoc-app':
        raise RuntimeError('Unexpected application image; refusing to replace another service')
    backup = 'codoc-app:before-runtime-' + release
    run('docker', 'tag', image, backup)
    (stage / 'Dockerfile').write_text('FROM ' + backup + '\n' + copy_lines, encoding='utf-8')
    run('docker', 'build', '--network', 'none', '-t', image, str(stage))
    return image, backup


def publish_web(config, stage, release):
    web = stage / 'web'
    if not (web / 'index.html').is_file():
        raise ValueError('Built index.html is required')
    destination = '/usr/share/nginx/html'
    if config['component'] == 'private-journey':
        destination += '/private-journey'
    build_image(stage, config['container'], 'COPY web/ ' + destination + '/\n', release)
    # Existing hashed assets remain available to browsers opened before the release.
    for item in sorted(web.iterdir(), key=lambda path: path.name == 'index.html'):
        if item.is_dir():
            run('docker', 'exec', config['container'], 'mkdir', '-p', destination + '/' + item.name)
            run('docker', 'cp', str(item) + '/.', config['container'] + ':' + destination + '/' + item.name + '/')
        else:
            run('docker', 'cp', str(item), config['container'] + ':' + destination + '/' + item.name)
    print('Frontend published and persisted. Java and Nginx were not restarted.', flush=True)


def patch_jar(config, stage, archive):
    original = stage / 'original.jar'
    patched = stage / 'app.jar'
    run('docker', 'cp', config['container'] + ':/app/app.jar', str(original))
    replacements = {info.filename: archive.read(info) for info in checked_members(archive, 'backend')}
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(patched, 'w') as target:
        # Preserve ZIP entry metadata needed by Spring Boot's executable nested JARs.
        for info in source.infolist():
            value = replacements.pop(info.filename, None)
            target.writestr(info, source.read(info.filename) if value is None else value)
        for name, value in replacements.items():
            target.writestr(name, value, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(patched) as verified:
        if verified.testzip() is not None:
            raise ValueError('Patched JAR verification failed')
    original.unlink()


def publish_backend(config, stage, archive, release):
    container = config['container']
    patch_jar(config, stage, archive)
    process = backend_pid(container)
    image, backup_image = build_image(stage, container, 'COPY app.jar /app/app.jar\n', release)
    backup_jar = '/app/app.jar.before-runtime-' + release
    run('docker', 'cp', str(stage / 'app.jar'), container + ':/app/app.jar.next')
    run('docker', 'exec', container, 'mv', '/app/app.jar', backup_jar)
    run('docker', 'exec', container, 'mv', '/app/app.jar.next', '/app/app.jar')
    run('docker', 'exec', container, 'kill', '-TERM', process)
    if not ready(config):
        run('docker', 'exec', container, 'mv', backup_jar, '/app/app.jar')
        run('docker', 'tag', backup_image, image)
        run('docker', 'exec', container, 'kill', '-TERM', backend_pid(container))
        restored = ready(config)
        raise RuntimeError('Backend publication failed; rollback ready=' + str(restored))
    run('docker', 'exec', container, 'rm', '-f', backup_jar)
    print('Backend API HTTP 200; JAR persisted. Frontend and Nginx unchanged.', flush=True)


def main():
    config = json.loads(base64.b64decode(sys.argv[1]))
    payload = Path(config['payload'])
    if payload.parent != Path('/tmp') or not payload.name.startswith('codoc-runtime-'):
        raise ValueError('Unexpected temporary payload path')
    if hashlib.sha256(payload.read_bytes()).hexdigest() != config['sha256']:
        raise ValueError('Payload checksum mismatch')
    required = 512 if config['action'] == 'backend' else 128
    if shutil.disk_usage('/').free < required * 1024 * 1024:
        raise RuntimeError('Insufficient deployment disk headroom; nothing was restarted')
    stage = Path(tempfile.mkdtemp(prefix='codoc-runtime-release-'))
    (stage / '.codoc-runtime-release').write_text('1')
    release = stage.name.removeprefix('codoc-runtime-release-')
    try:
        with zipfile.ZipFile(payload) as archive:
            checked_members(archive, config['action'])
            if config['action'] == 'web':
                archive.extractall(stage)
                publish_web(config, stage, release)
            else:
                publish_backend(config, stage, archive, release)
    finally:
        shutil.rmtree(stage)
        payload.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
