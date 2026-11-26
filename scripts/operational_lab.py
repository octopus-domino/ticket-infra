#!/usr/bin/env python3
"""Run small operational drills using only local Docker images and disposable data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import tempfile
import tarfile
import time


def docker(*args, data=None):
    return subprocess.run(('docker', '--context', 'default', *args), input=data,
                          stdout=subprocess.PIPE, check=True, timeout=90).stdout


class Lab:
    def __init__(self):
        endpoint = json.loads(docker('context', 'inspect', 'default'))[0]['Endpoints']['docker']['Host']
        if endpoint != 'unix:///var/run/docker.sock' or os.environ.get('DOCKER_HOST'):
            raise RuntimeError('The drill requires the explicitly local Docker socket')
        self.root = Path(tempfile.mkdtemp(prefix='codoc-ps12-', dir='/tmp')).resolve()
        self.name = self.root.name.lower().replace('_', '-')
        if not re.fullmatch(r'codoc-ps12-[a-z0-9-]{8}', self.name):
            raise RuntimeError('Unexpected disposable project name')
        (self.root / 'empty.env').touch()
        print(f'Disposable project {self.name}; artifacts {self.root}', flush=True)

    def compose(self, *args, data=None):
        return docker('compose', '--project-name', self.name, '--project-directory', str(self.root),
                      '--env-file', str(self.root / 'empty.env'), '-f', str(self.root / 'compose.json'), *args, data=data)

    def define(self, services, volumes=()):
        shared = {'pull_policy': 'never', 'restart': 'no', 'networks': ['lab'],
                  'labels': {'io.codoc.operational-lab': self.name},
                  'logging': {'driver': 'local', 'options': {'max-size': '5m', 'max-file': '2'}}}
        config = {'services': {name: shared | definition for name, definition in services.items()},
                  'networks': {'lab': {'internal': True}}, 'volumes': {name: {} for name in volumes}}
        (self.root / 'compose.json').write_text(json.dumps(config), encoding='utf-8')
        self.compose('config', '--quiet')

    def ids(self):
        return self.compose('ps', '-aq').decode().split()

    def verify(self):
        for container in self.ids():
            inspected = json.loads(docker('inspect', container))[0]
            labels = inspected['Config']['Labels']
            if labels.get('com.docker.compose.project') != self.name or labels.get('io.codoc.operational-lab') != self.name:
                raise RuntimeError('Wrong container ownership')
            for mount in inspected['Mounts']:
                if mount['Type'] == 'volume':
                    info = json.loads(docker('volume', 'inspect', mount['Name']))[0]
                    if info['Labels'].get('com.docker.compose.project') != self.name:
                        raise RuntimeError('Wrong volume ownership')
                elif mount['Type'] == 'tmpfs' or (mount['Type'] == 'bind' and
                      Path(mount['Source']).resolve().is_relative_to(self.root)):
                    continue
                else:
                    raise RuntimeError('Unexpected container mount')
            for network in inspected['NetworkSettings']['Networks']:
                info = json.loads(docker('network', 'inspect', network))[0]
                if not info['Internal'] or info['Labels'].get('com.docker.compose.project') != self.name:
                    raise RuntimeError('Wrong network ownership')

    def start(self, *services):
        self.compose('create', '--no-build', *services)
        self.verify()
        self.compose('up', '-d', '--no-build', *services)

    def close(self):
        self.verify()
        self.compose('down', '--volumes')

    def request(self, service, port, path, headers=None, body=None, *, local=False, method=None, timeout=3):
        if not re.fullmatch(r'[a-z]+', service) or not path.startswith('/') or path.startswith('//'):
            raise ValueError('Invalid internal test destination')
        client = service if local else 'client'
        host = '127.0.0.1' if local else service
        args = ['exec', '-T', client, 'curl', '-sS', '--max-time', str(timeout), '--noproxy', '*',
                '-w', '\n%{http_code} %{time_total}']
        for name, value in (headers or {}).items():
            args += ['-H', f'{name}: {value}']
        if method:
            args += ['-X', method]
        if body is not None:
            args += ['--data-binary', '@-']
        try:
            output = self.compose(*args, f'http://{host}:{port}{path}', data=body)
        except subprocess.CalledProcessError:
            return 0, b'', 0
        response, _, trailer = output.rpartition(b'\n')
        status, duration = trailer.split()
        return int(status), response, float(duration) * 1000


CLIENT = {'image': 'codoc-app', 'mem_limit': '32m', 'cpus': 0.10,
          'tmpfs': ['/app/data:size=1m'], 'entrypoint': ['sh', '-ec', 'exec sleep 1800']}
RESTORE_DATABASE = 'codoc_restore_test'


def wait_ready(lab, name, port):
    for _ in range(60):
        status, body, _ = lab.request(name, port, '/actuator/health/readiness', local=True)
        if status == 200 and json.loads(body) == {'status': 'UP'}:
            return
        time.sleep(1)
    raise RuntimeError(f'{name} did not become ready')


def application(lab, name, path, database, *, travel):
    shutil.copyfile(path, lab.root / f'{name}.jar')
    (lab.root / name).mkdir(mode=0o755)
    routing = name.startswith('routing')
    prefix = 'WALKS_DATABASE' if routing else 'SPRING_DATASOURCE'
    env = {'ENABLE_TRIP_PLANNER': str(travel).lower(),
           'APP_JOURNEYS_TRIP_PLANNER_ENABLED': str(travel).lower(),
           'MANAGEMENT_SERVER_PORT': '9093' if routing else '9080',
           'MANAGEMENT_SERVER_ADDRESS': '127.0.0.1',
           'SPRING_DATASOURCE_HIKARI_CONNECTION_TIMEOUT': '1800',
           'SPRING_DATASOURCE_HIKARI_VALIDATION_TIMEOUT': '1000',
           'TRIP_ROUTING_URL': 'http://routing:8093', 'TRIPS_DOCUMENT_URL': 'http://document:8080',
           'SPRING_SQL_INIT_MODE': 'never', 'SPRING_JPA_HIBERNATE_DDL_AUTO': 'update',
           'JWT_SECRET': 'lab-synthetic-signing-key-only-000000000000000000',
           'GOOGLE_CLIENT_ID': 'lab', 'GOOGLE_CLIENT_SECRET': 'lab',
           'SMTP_HOST': '127.0.0.1', 'SMTP_USER': 'lab@example.invalid',
           'APP_FRONTEND_URL': 'http://lab.invalid', 'BROUTER_ENABLED': 'false',
           'BROUTER_HTTP_ENABLED': 'false', 'VALHALLA_ENABLED': 'false',
           'OSM_MCP_ENABLED': 'false', 'COMMONS_MCP_ENABLED': 'false'}
    if database:
        db_name = RESTORE_DATABASE if database == 'restored' else 'codoc_lab'
        url = f'jdbc:postgresql://{database}:5432/{db_name}?currentSchema=' + ('routing,public' if routing else 'public')
        user, password = 'lab_owner', 'lab-db-credentials'
        env['SPRING_DATASOURCE_DRIVER_CLASS_NAME'] = 'org.postgresql.Driver'
        if routing:
            env['WALKS_DB_SCHEMA'] = 'routing'
    else:
        url = 'jdbc:h2:file:/app/data/operational'
        user, password = 'sa', ''
    env.update({prefix + '_URL': url, prefix + ('_USER' if routing else '_USERNAME'): user,
                prefix + '_PASSWORD': password})
    return {'image': 'codoc-app', 'mem_limit': '580m' if not routing else '400m',
            'cpus': 0.85,
            'entrypoint': ['java', '-Xms32m', '-Xmx256m' if not routing else '-Xmx176m',
                           '-XX:MaxDirectMemorySize=64m', '-XX:ActiveProcessorCount=1',
                           '-jar', '/lab/service.jar'],
            'environment': env,
            'volumes': [f'./{name}.jar:/lab/service.jar:ro', f'./{name}:/app/data']}


def database(volume):
    return {'image': 'postgis/postgis:17-3.5-alpine', 'mem_limit': '512m', 'cpus': 0.4,
            'environment': {'POSTGRES_DB': 'codoc_lab', 'POSTGRES_USER': 'lab_owner',
                            'POSTGRES_PASSWORD': 'lab-db-credentials'},
            'volumes': [f'{volume}:/var/lib/postgresql/data'],
            'healthcheck': {'test': ['CMD', 'pg_isready', '-h', '127.0.0.1', '-U', 'lab_owner', '-d', 'codoc_lab'],
                            'interval': '5s', 'retries': 20}}


def sql(lab, service, statement, *, target=False):
    if service not in {'postgres', 'restored'}:
        raise RuntimeError('Refusing to run SQL outside the disposable database')
    if target and service != 'restored':
        raise RuntimeError('The restore database belongs to the independent target service')
    lab.verify()
    return lab.compose('exec', '-T', service, 'psql', '-XAt', '-v', 'ON_ERROR_STOP=1',
                       '-U', 'lab_owner', '-d', RESTORE_DATABASE if target else 'codoc_lab', '-c', statement)


def require_empty_restore_target(lab):
    if sql(lab, 'restored', 'SELECT current_database()', target=True).decode().strip() != RESTORE_DATABASE:
        raise RuntimeError('Wrong restore database')
    if sql(lab, 'restored', "SELECT to_regclass('public.documents') IS NULL", target=True) != b't\n':
        raise RuntimeError('Restore target already contains application data')


def artifact_sha256(path):
    with path.open('rb') as artifact:
        return hashlib.file_digest(artifact, 'sha256').hexdigest()


def require_restore_inputs(manifest, artifacts):
    if set(manifest) != set(artifacts):
        raise RuntimeError('The backup manifest has an incomplete artifact list')
    for name, path in artifacts.items():
        if not path.is_file():
            raise RuntimeError(f'Restore artifact missing: {name}')
        if artifact_sha256(path) != manifest[name]:
            raise RuntimeError(f'Restore artifact checksum mismatch: {name}')


def postgis_contract(lab, fixture):
    shutil.copytree(fixture, lab.root / 'contract')
    client = CLIENT | {'volumes': ['./contract:/contract:ro'], 'working_dir': '/contract',
                       'mem_limit': '128m'}
    lab.define({'client': client, 'postgres': database('source')}, ('source',))
    try:
        lab.start('postgres')
        lab.compose('up', '-d', '--wait', 'postgres')
        sql(lab, 'postgres', 'CREATE DATABASE codoc_lab_test')
        lab.start('client')
        result = lab.compose('exec', '-T',
                             '-e', 'CODOC_POSTGIS_TEST_URL=jdbc:postgresql://postgres:5432/codoc_lab_test',
                             '-e', 'CODOC_POSTGIS_TEST_USER=lab_owner',
                             '-e', 'CODOC_POSTGIS_TEST_PASSWORD=lab-db-credentials',
                             'client', 'java', '-Xmx64m', '-cp', 'classes:lib/*', 'ru.ticket.walks.NativePostgisAcceptance')
        print(result.decode(), flush=True)
    finally:
        lab.close()


def seed_document(lab):
    headers = {'Content-Type': 'application/json'}

    def post(path, body, method=None):
        result, response, elapsed = lab.request('document', 8080, path, headers, json.dumps(body).encode(), method=method, timeout=15)
        if not 200 <= result < 300:
            raise RuntimeError(f'{path} returned {result}')
        print(f'{path} HTTP {result} ({elapsed:.0f} ms)', flush=True)
        return json.loads(response)

    login = post('/api/auth/register', {'email': 'owner@example.test', 'name': 'Lab Owner',
                                        'password': 'lab-test-password-123'})
    headers['Authorization'] = 'Bearer ' + login['accessToken']
    document = post('/api/workspace/documents', {'name': 'Synthetic workspace document'})
    schema = post('/api/schemas', {'name': 'Synthetic schema', 'fields': []})
    model = post('/api/data-models', {'name': 'Synthetic set', 'schemaId': schema['id'], 'values': {}})
    slide = {'id': 'lab', 'name': 'Lab', 'width': 595, 'height': 842, 'background': '#ffffff', 'elements': []}
    template = post('/api/templates', {'name': 'Synthetic template', 'slides': [slide], 'bindings': []})
    resource = f"/api/workspace/documents/{document['id']}"
    for version in (1, 2):
        post(resource + '/content', {'content': json.dumps({'labVersion': version})}, method='PUT')
    public = post('/api/journeys', {'kind': 'INVITATION', 'title': 'Lab invitation',
                                   'data': {'description': 'Synthetic publication', 'theme': 'rose'}, 'recipients': []})
    image = 'iVBORw0KGgoAAAANSUhEUgAAABgAAAAQCAIAAACDRijCAAAAG0lEQVR4nGO4IaVCFcQwatCoQaMGjRokRZFBAJJYoRAUt2lSAAAAAElFTkSuQmCC'
    media = post('/api/journeys/media', {'image': 'data:image/png;base64,' + image})
    status, pdf, _ = lab.request('document', 8080, '/api/guest/export/pdf', headers,
                                 json.dumps({'slides': [slide]}).encode(), timeout=15)
    if status != 200 or not pdf.startswith(b'%PDF'):
        raise RuntimeError(f'PDF smoke returned {status}')
    print('Document independent smoke: registration, workspace, schema, set, template and PDF', flush=True)
    return headers, (document['id'], schema['id'], model['id'], template['id']), public[0]['document']['id'], media['id']


def seed_trip(lab, headers, photo):
    payload = {
        'version': 2, 'id': 'synthetic-trip', 'title': 'Synthetic itinerary',
        'startDate': '2027-01-01', 'endDate': '2027-01-02', 'travelers': [],
        'cities': [{'id': 'city', 'name': 'Lab City'}], 'accommodations': [], 'documents': [], 'legs': [],
        'days': [{'date': '2027-01-02', 'cityId': 'city', 'note': 'Lab walk', 'segments': [
            {'id': 'first', 'title': 'Start', 'walkId': 'lab-walk', 'photoRefs': [photo], 'photoCredits': [{
                'stopId': 'first', 'imageId': photo, 'author': 'Synthetic photographer', 'license': 'CC BY 4.0',
                'licenseUrl': 'https://creativecommons.org/licenses/by/4.0/',
                'sourceUrl': 'https://commons.wikimedia.org/wiki/File:Synthetic.jpg'}]},
            {'id': 'second', 'title': 'Finish', 'walkId': 'lab-walk'}],
            'walkingSections': [{'fromSegmentId': 'first', 'toSegmentId': 'second', 'geometry': [
                {'longitude': 13.40, 'latitude': 52.50}, {'longitude': 13.41, 'latitude': 52.51}]}]}],
        'meta': {'mode': 'TRIP', 'source': 'PRIVATE_JOURNEY'},
    }
    status, _, _ = lab.request('routing', 8093, '/api/routing/v1/trips', headers,
                               json.dumps(payload).encode(), timeout=12)
    assert status == 201, status


def service_drill(lab, document, routing, profile, travel):
    pg = profile == 'postgres'
    services = {'client': CLIENT,
                'document': application(lab, 'document', document, 'postgres' if pg else None, travel=travel),
                'routing': application(lab, 'routing', routing, 'postgres' if pg else None, travel=travel)}
    if pg:
        services['postgres'] = database('source')
        services['restored'] = database('target')
        services['documentrestore'] = application(lab, 'documentrestore', document, 'restored', travel=travel)
        services['routingrestore'] = application(lab, 'routingrestore', routing, 'restored', travel=travel)
        services['documentrestore']['environment'].update(TRIP_ROUTING_URL='http://routingrestore:8093',
                                                        SPRING_JPA_HIBERNATE_DDL_AUTO='validate')
        services['routingrestore']['environment'].update(TRIPS_DOCUMENT_URL='http://documentrestore:8080',
                                                       WALKS_DB_SCHEMA_MODE='validate')
    lab.define(services, ('source', 'target') if pg else ())
    try:
        if pg:
            lab.start('postgres')
            lab.compose('up', '-d', '--wait', 'postgres')
            sql(lab, 'postgres', 'CREATE SCHEMA routing; CREATE EXTENSION IF NOT EXISTS postgis')
        lab.start('client', 'document')
        wait_ready(lab, 'document', 9080)
        headers, ids, publication, photo = seed_document(lab)
        routing_down = lab.request('document', 8080, '/api/trips/synthetic-trip/pdf', headers, timeout=12)[0]
        if travel and routing_down not in (502, 503):
            raise RuntimeError(f'Document did not report upstream unavailability (HTTP {routing_down})')
        print(f'routing stopped, Document trip PDF HTTP {routing_down}', flush=True)
        lab.start('routing')
        wait_ready(lab, 'routing', 9093)
        assert lab.request('routing', 8093, '/api/walks/v1/places/themes')[0] == 200
        if travel:
            seed_trip(lab, headers, photo)
        lab.verify()
        lab.compose('stop', 'routing')
        assert lab.request('document', 8080, f'/api/workspace/documents/{ids[0]}', headers)[0] == 200
        lab.compose('start', 'routing')
        wait_ready(lab, 'routing', 9093)
        lab.verify()
        lab.compose('stop', 'document', 'routing')
        lab.compose('start', 'routing')
        wait_ready(lab, 'routing', 9093)
        assert lab.request('routing', 8093, '/api/walks/v1/places/themes')[0] == 200
        account_status = lab.request('routing', 8093, '/api/routing/v1/trips', headers, timeout=10)[0]
        if 200 <= account_status < 400:
            raise RuntimeError('Routing authorized an account request with Document stopped')
        print(f'document stopped, Routing trip list HTTP {account_status}', flush=True)
        lab.compose('start', 'document')
        wait_ready(lab, 'document', 9080)
        if travel:
            assert lab.request('routing', 8093, '/api/routing/v1/trips', headers)[0] == 200
        if pg:
            lab.verify()
            lab.compose('stop', 'postgres')
            for service, management in (('document', 9080), ('routing', 9093)):
                status, _, _ = lab.request(service, management, '/actuator/health/readiness', local=True)
                assert status in (0, 503), (service, status)
                assert lab.request(service, management, '/actuator/health/liveness', local=True)[0] == 200
            lab.compose('start', 'postgres')
            wait_ready(lab, 'document', 9080)
            wait_ready(lab, 'routing', 9093)
            sql(lab, 'postgres', 'ALTER TABLE public.documents RENAME TO documents_unavailable')
            try:
                assert lab.request('document', 9080, '/actuator/health/readiness', local=True)[0] == 503
                assert lab.request('document', 9080, '/actuator/health/liveness', local=True)[0] == 200
            finally:
                sql(lab, 'postgres', 'ALTER TABLE public.documents_unavailable RENAME TO documents')
            wait_ready(lab, 'document', 9080)
            print('PostgreSQL loss and missing schema rejected; liveness and readiness recovery verified', flush=True)
            restore_database(lab, ids, document, routing, headers, publication, photo, travel)
        print(f'services profile={profile} travel={travel} passed', flush=True)
    finally:
        for service in services:
            if lab.compose('ps', '-aq', service).strip():
                (lab.root / f'{service}.log').write_bytes(lab.compose('logs', '--no-color', service))
        lab.close()
        for name in ('document', 'routing', 'documentrestore', 'routingrestore'):
            (lab.root / f'{name}.jar').unlink(missing_ok=True)


def restore_database(lab, ids, document, routing, headers, publication, photo, travel):
    checks = [('document', 8080, f'/api/workspace/documents/{ids[0]}'),
              ('document', 8080, f'/api/history/document/{ids[0]}'),
              ('document', 8080, f'/api/journeys/{publication}'),
              ('document', 8080, f'/api/journeys/media/{photo}')]
    if travel:
        checks.append(('routing', 8093, '/api/routing/v1/trips/synthetic-trip'))
    before = {}
    for name, port, path in checks:
        status, content, _ = lab.request(name, port, path, headers, timeout=10)
        assert status == 200, (path, status)
        before[path] = content
    assert json.loads(before[checks[1][2]]), 'Expected a document revision'
    # Stop both writers for a consistent database/files snapshot.
    lab.verify()
    lab.compose('stop', 'document', 'routing')
    start = time.monotonic()
    backup = lab.root / 'codoc-lab.dump'
    payload = lab.compose('exec', '-T', 'postgres', 'pg_dump', '-U', 'lab_owner', '-Fc', 'codoc_lab')
    backup.write_bytes(payload)
    shutil.make_archive(str(lab.root / 'lab-files'), 'gztar', lab.root, 'document')
    archive = lab.root / 'lab-files.tar.gz'
    manifest = {name: artifact_sha256(path) for name, path in {
        'database': backup, 'files': archive, 'document': document, 'routing': routing,
    }.items()}
    (lab.root / 'manifest.json').write_text(json.dumps(manifest))
    print(f'dump_bytes={backup.stat().st_size} backup_ms={(time.monotonic()-start)*1000:.0f}', flush=True)
    start = time.monotonic()
    require_restore_inputs(manifest, {'database': backup, 'files': archive,
                           'document': lab.root / 'documentrestore.jar', 'routing': lab.root / 'routingrestore.jar'})
    lab.verify()
    lab.compose('stop', 'postgres')
    lab.start('restored')
    lab.compose('up', '-d', '--wait', 'restored')
    # The image initializes its default database with PostGIS/Tiger. The archive owns those schemas.
    sql(lab, 'restored', f'CREATE DATABASE {RESTORE_DATABASE} TEMPLATE template0')
    require_empty_restore_target(lab)
    restore = ('exec', '-T', 'restored', 'pg_restore', '-U', 'lab_owner')
    lab.compose(*restore, '--list', data=payload)
    try:
        lab.compose(*restore, '--list', data=b'intentionally damaged dump')
    except subprocess.CalledProcessError:
        print('Damaged dump rejected in preflight', flush=True)
    else:
        raise RuntimeError('Damaged dump passed preflight')
    lab.compose(*restore, '--exit-on-error', '--single-transaction', '--no-owner', '-d', RESTORE_DATABASE, data=payload)
    try:
        require_empty_restore_target(lab)
    except RuntimeError as error:
        if str(error) != 'Restore target already contains application data':
            raise
        print('Repeated restore refused for the populated database', flush=True)
    else:
        raise RuntimeError('Repeated restore guard did not detect application data')
    for table, identifier in zip(('documents', 'schemas', 'data_models', 'templates'), ids, strict=True):
        if not re.fullmatch(r'[\w-]{1,64}', identifier):
            raise RuntimeError('Unexpected test object identifier')
        assert sql(lab, 'restored', f"SELECT id FROM public.{table} WHERE id = '{identifier}'", target=True).decode().strip() == identifier
    assert sql(lab, 'restored', "SELECT to_regclass('routing.journey_trip_drafts') IS NOT NULL", target=True) == b't\n'
    assert sql(lab, 'restored', "SELECT postgis_version() IS NOT NULL", target=True) == b't\n'
    print(f'restore_ms={(time.monotonic()-start)*1000:.0f}', flush=True)
    files = lab.root / 'recovered'
    files.mkdir()
    with tarfile.open(archive) as snapshot:
        snapshot.extractall(files, filter='data')
    shutil.copytree(files / 'document', lab.root / 'documentrestore', dirs_exist_ok=True)
    lab.start('documentrestore')
    wait_ready(lab, 'documentrestore', 9080)
    lab.start('routingrestore')
    wait_ready(lab, 'routingrestore', 9093)
    for name, port, path in checks:
        status, content, _ = lab.request(name + 'restore', port, path, headers, timeout=10)
        assert status == 200 and content == before[path], (path, status)
    status, _, _ = lab.request('documentrestore', 8080, checks[0][2], {'Authorization': 'Bearer wrong-key'})
    assert status == 401
    auth_headers = {'Content-Type': 'application/json'}
    status, account, _ = lab.request('documentrestore', 8080, '/api/auth/register', auth_headers, json.dumps({
        'email': 'unrelated@example.test', 'name': 'Unrelated Lab User', 'password': 'lab-test-password-123',
    }).encode(), timeout=15)
    assert status == 201, status
    auth_headers['Authorization'] = 'Bearer ' + json.loads(account)['accessToken']
    assert lab.request('documentrestore', 8080, checks[0][2], auth_headers)[0] == 404
    if travel:
        assert lab.request('routingrestore', 8093, '/api/routing/v1/trips/synthetic-trip', auth_headers)[0] == 404
        status, pdf, _ = lab.request('documentrestore', 8080, '/api/trips/synthetic-trip/pdf', headers, timeout=15)
        assert status == 200 and pdf.startswith(b'%PDF')
    print(f'restored endpoints match, app_rto_ms={(time.monotonic()-start)*1000:.0f}', flush=True)


def gateway(lab, soft, hard):
    directory = Path(__file__).resolve().parents[1] / 'tyk'
    config = json.loads((directory / 'tyk.conf').read_text(encoding='utf-8'))
    api = json.loads((directory / 'apps' / 'codoc.json').read_text(encoding='utf-8'))
    api['proxy']['target_url'] = 'http://upstream:8080/'
    api['disable_rate_limit'] = True
    (lab.root / 'tyk.conf').write_text(json.dumps(config))
    (lab.root / 'apps').mkdir()
    (lab.root / 'apps' / 'codoc.json').write_text(json.dumps(api))
    (lab.root / 'upstream.conf').write_text(
        'pid /tmp/nginx-lab.pid; events {} http { access_log off; '
        'server { listen 8080; location = /probe { return 200 "lab"; } } }')
    lab.define({
        'client': CLIENT,
        'gateway': {'image': 'tykio/tyk-gateway:v5.16.0',
                    'mem_limit': f'{hard}m', 'memswap_limit': f'{hard}m', 'cpus': 0.5,
                    'environment': {'GOMEMLIMIT': f'{soft}MiB', 'GOMAXPROCS': '1',
                                    'TYK_GW_SECRET': 'lab-gateway-secret', 'TYK_GW_STORAGE_PASSWORD': 'lab-redis-secret',
                                    'GODEBUG': 'gctrace=1'},
                    'volumes': ['./tyk.conf:/opt/tyk-gateway/tyk.conf:ro', './apps:/opt/tyk-gateway/apps:ro'],
                    'depends_on': {'redis': {'condition': 'service_healthy'}}},
        'redis': {'image': 'redis:7.2-alpine', 'mem_limit': '96m', 'cpus': 0.15, 'tmpfs': ['/data:size=16m'],
                  'command': ['redis-server', '--requirepass', 'lab-redis-secret', '--save', ''],
                  'healthcheck': {'test': ['CMD', 'redis-cli', '-a', 'lab-redis-secret', 'ping'], 'interval': '1s'}},
        'upstream': {'image': 'codoc-app', 'mem_limit': '32m', 'cpus': 0.10, 'tmpfs': ['/app/data:size=1m'],
                     'volumes': ['./upstream.conf:/lab/nginx.conf:ro'],
                     'entrypoint': ['nginx', '-c', '/lab/nginx.conf', '-g', 'daemon off;']},
    })
    started = time.monotonic()
    try:
        lab.start()
        headers = {'x-tyk-authorization': 'lab-gateway-secret', 'Content-Type': 'application/json'}
        for _ in range(30):
            probe, _, _ = lab.request('gateway', 8081, '/tyk/apis', headers)
            if probe == 200:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f'Gateway control API did not respond with HTTP 200 (last HTTP {probe})')
        print(f'gateway startup_ms={(time.monotonic()-started)*1000:.0f}', flush=True)
        key = json.dumps({'org_id': 'codoc', 'rate': 1000, 'per': 1, 'quota_max': -1,
                          'access_rights': {'codoc-client': {'api_id': 'codoc-client', 'versions': ['Default']}}}).encode()
        status, response, _ = lab.request('gateway', 8081, '/tyk/keys/lab-client-key', headers, key)
        if status != 200:
            raise RuntimeError(f'Test key creation returned {status}')
        authorized = {'X-API-Key': json.loads(response).get('key', 'lab-client-key')}
        if lab.request('gateway', 8080, '/client-api/probe')[0] not in (401, 403):
            raise RuntimeError('Gateway accepted a request without an API key')
        for count, delay in ((30, .06), (120, .005)):
            times = []
            for _ in range(count):
                status, body, elapsed = lab.request('gateway', 8080, '/client-api/probe', authorized)
                if status != 200 or body.strip() != b'lab':
                    raise RuntimeError(f'Test route returned {status}')
                times.append(elapsed)
                time.sleep(delay)
            cid = lab.compose('ps', '-q', 'gateway').decode().strip()
            usage = docker('stats', '--no-stream', '--format', '{{.MemUsage}} {{.CPUPerc}}', cid).decode().strip()
            pid = int(docker('inspect', '--format', '{{.State.Pid}}', cid))
            process = Path('/proc') / str(pid)
            rss = next(line for line in (process / 'status').read_text().splitlines() if line.startswith('VmRSS:'))
            cgroup = (process / 'cgroup').read_text().split('0::', 1)[-1].strip().lstrip('/')
            peak_path = Path('/sys/fs/cgroup', cgroup, 'memory.peak')
            peak = peak_path.read_text().strip() if peak_path.is_file() else 'unavailable'
            print(f'requests={count} p50_ms={statistics.median(times):.2f} p95_ms={sorted(times)[int(count*.95)-1]:.2f} {usage} {rss} memory_peak_bytes={peak}', flush=True)
        lab.verify()
        lab.compose('stop', 'redis')
        statuses = [lab.request('gateway', 8080, '/client-api/probe', hdr)[0] for hdr in (None, authorized)]
        if any(200 <= code < 400 for code in statuses):
            raise RuntimeError('Gateway accepted a request with Redis stopped')
        print(f'redis_down_http={statuses}', flush=True)
        cid = lab.compose('ps', '-aq', 'gateway').decode().strip()
        oom = docker('inspect', '--format', '{{.State.OOMKilled}}', cid).decode().strip()
        if oom != 'false':
            raise RuntimeError('Gateway was OOM-killed')
        logs = lab.compose('logs', '--no-color', 'gateway').decode(errors='replace')
        (lab.root / 'gc.log').write_text('\n'.join(line for line in logs.splitlines() if re.search(r'\bgc \d+ @', line)))
        print(f'oom_killed={oom} gc_events={(lab.root / "gc.log").read_text().count(chr(10)) + bool((lab.root / "gc.log").stat().st_size)}')
    finally:
        (lab.root / 'gateway.log').write_bytes(lab.compose('logs', '--no-color', 'gateway'))
        lab.close()


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('Run acceptance drills with Python assertions enabled')
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--gateway-soft-mib', type=int)
    parser.add_argument('--gateway-hard-mib', type=int, choices=[160, 384])
    parser.add_argument('--profile', choices=['h2', 'postgres'])
    parser.add_argument('--document-jar', type=Path)
    parser.add_argument('--routing-jar', type=Path)
    parser.add_argument('--travel', action='store_true')
    parser.add_argument('--postgis-fixture', type=Path)
    args = parser.parse_args()
    if args.postgis_fixture:
        postgis_contract(Lab(), args.postgis_fixture)
    elif args.profile:
        if not args.document_jar or not args.routing_jar:
            parser.error('The service drill needs two built jars')
        service_drill(Lab(), args.document_jar, args.routing_jar, args.profile, args.travel)
    elif not args.gateway_soft_mib or not args.gateway_hard_mib or not 32 <= args.gateway_soft_mib <= args.gateway_hard_mib:
        parser.error('Choose a soft limit between 32 MiB and the hard limit')
    else:
        gateway(Lab(), args.gateway_soft_mib, args.gateway_hard_mib)
