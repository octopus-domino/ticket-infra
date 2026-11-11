#!/usr/bin/env python3
"""Stateful Docker double: only used by script tests, never contacts a Docker daemon."""
import json
import os
import sys
from pathlib import Path
sys.stdout.reconfigure(newline='\n')

path = Path(os.environ['FAKE_DOCKER_STATE'])
state = json.loads(path.read_text())
args = sys.argv[1:]
state['calls'].append(args)

def save():
    path.write_text(json.dumps(state))

def done(text='', code=0):
    save()
    if text:
        print(text)
    sys.exit(code)

def find(ref):
    return state['containers'].get(ref) or next((c for c in state['containers'].values() if c['name'] == ref.lstrip('/')), None)

def managed_running():
    return [c for c in state['containers'].values() if c['managed'] and c['running']]

def compose():
    if args[-1]=='version':done('Docker Compose test version')
    verbs = ['ps', 'up', 'stop', 'run', 'exec', 'config']
    verb = next((v for v in args[1:] if v in verbs), None)
    if verb == 'config':
        done()
    if verb == 'ps':
        if args[-1] == 'app' and 'pgapp' in state['containers']:
            done('pgapp')
        done()
    if verb == 'stop':
        for ref in args[args.index('stop') + 1:]:
            for c in state['containers'].values():
                if c['project'] == 'codoc' and c['service'] == ref:
                    c['running'] = False
        done()
    if verb == 'up':
        if any('compose.gateway.yml' in a for a in args):
            state['containers']['gateway']['running']=True
            state['containers']['redis']['running']=True
            done()
        if 'postgres' in args:
            state['containers'].setdefault('pg', container('codoc-postgres-1', 'postgres'))['running'] = True
        if args[-1] in ['app', 'gateway']:
            if os.environ.get('FAKE_FAIL_START'):
                done(code=39)
            if state['builder_running']:
                done('Builder is still using memory during app startup', 99)
            state['containers']['pgapp'] = container('codoc-app-1', 'app')
            if args[-1] == 'gateway':
                state['containers']['new-gateway'] = container('codoc-gateway-1', 'gateway')
                state['containers']['new-redis'] = container('codoc-redis-1', 'redis')
        done()
    if verb == 'run':
        if args[-1] == 'migration':
            if state['builder_running']:
                done('Builder is still using memory during import', 98)
            state['import_started'] = True
            if os.environ.get('FAKE_FAIL_IMPORT'):
                done(code=37)
            done('Imported test database')
        if '--name' in args:
            name = args[args.index('--name') + 1]
            state['containers'][name] = container(name, 'app')
            done(name)
        done()
    if verb == 'exec':
        if 'pg_dump' in ' '.join(args):
            if any(c['running'] and (c['service']=='app' or c['name']=='ticket-app') for c in managed_running()):
                done('Dump started while Java is writing', 93)
            state['dumped'] = True
            state['backed_up'] = True
            done('TEST DATABASE DUMP')
        if 'psql' in ' '.join(args):
            state['sql_started'] = True
            if os.environ.get('FAKE_FAIL_SQL'):
                done(code=31)
            done()
    done('Unsupported compose call: ' + repr(args), 80)

def container(name, service, project='codoc', running=True, managed=True):
    return dict(name=name, service=service, project=project, running=running, managed=managed)

if not args:
    done(code=1)
if args[0] == 'info':
    done('4294967296' if '--format' in args else 'Fake Docker')
if args[0] == 'compose':
    compose()
if args[0] == 'ps':
    entries = list(state['containers'].items())
    if '-a' not in args:
        entries = [(k, c) for k, c in entries if c['running']]
    filters = [args[i+1] for i, value in enumerate(args) if value == '--filter']
    for item in filters:
        if item.startswith('label=com.docker.compose.project='):
            entries = [(k,c) for k,c in entries if c['project'] == item.split('=',2)[2]]
        elif item.startswith('label=com.docker.compose.service='):
            entries = [(k,c) for k,c in entries if c['service'] == item.split('=',2)[2]]
        elif item.startswith('name='):
            name=item[5:].removeprefix('^/').removesuffix('$')
            if name.startswith('buildx_buildkit_'):
                done('builder-container' if state['builder_created'] else '')
            entries = [(k,c) for k,c in entries if c['name'] == name]
    done('\n'.join(k for k,c in entries))
if args[:2] == ['container', 'inspect']:
    done(code=0 if find(args[-1]) else 1)
if args[0] == 'inspect':
    fmt = args[args.index('--format')+1] if '--format' in args else args[args.index('-f')+1]
    if args[-1]=='builder-container' and '.State.Running' in fmt:done(str(state['builder_running']).lower())
    if 'HostConfig.Memory' in fmt:
        done('0:0:0:0' if os.environ.get('FAKE_BAD_LIMITS') else '2415919104:2415919104:100000:200000')
    c = find(args[-1])
    if c is None:
        done(code=1)
    if 'Config.Labels' in fmt:
        if 'json' in fmt:done(json.dumps({'com.docker.compose.service':c['service']}))
        done(c['service'])
    if '.State.Running' in fmt:
        done(str(c['running']).lower())
    if '.Name' in fmt:
        done('/'+c['name'])
    if '.Image' in fmt:
        done('sha256:old-image')
    if '.Type' in fmt:
        done('bind')
    if '.Source' in fmt:
        done(os.environ['FAKE_ROOT_POSIX']+'/data')
    done('Unsupported inspect format: '+fmt, 81)
if args[0] in ['stop', 'start']:
    c = find(args[-1])
    if c:
        if args[0] == 'start' and state['builder_running']:
            done('Builder still running on restore', 97)
        c['running'] = args[0] == 'start'
    done()
if args[0] == 'buildx':
    verb = args[1]
    if verb == 'version':
        done('fake-buildx')
    if verb == 'inspect':
        if '--bootstrap' in args:
            state['builder_running'] = True
            done('Driver: docker-container')
        done(code=0 if state['builder_created'] else 1)
    if verb == 'create':
        state['builder_created'] = True
        done('codoc-lowmem-v1')
    if verb == 'stop':
        if os.environ.get('FAKE_FAIL_STOP') and state['targets']:done(code=55)
        state['builder_running'] = False
        done()
    if verb == 'build':
        if managed_running():
            done('Managed runtime containers overlap with build', 96)
        if not state['backed_up'] and os.environ.get('FAKE_REQUIRE_BACKUP'):
            done('Build started before backup', 95)
        if os.environ.get('FAKE_FAIL_BUILD'):
            done(code=42)
        state['targets'].append(args[args.index('--target')+1])
        done()
if args[0] == 'run':
    if 'MemAvailable:' in ' '.join(args):
        info=Path(os.environ['CODOC_MEMINFO_FILE']).read_text()
        done(str(int(next(line.split()[1] for line in info.splitlines() if line.startswith('MemAvailable:')))//1024))
    if '--name' in args:
        name=args[args.index('--name')+1]
        state['containers']['new-app'] = container(name,'app','legacy')
    else:
        if any((c['service']=='app' or c['name']=='ticket-app') and c['running'] for c in managed_running()):
            done('Backup started before stopping Java', 94)
        state['backed_up'] = True
        for backup in path.parent.glob('backups/*'):
            if backup.is_dir():
                (backup/('data.tgz' if '/backup/data.tgz' in ' '.join(args) else 'h2-data.tar.gz')).write_text('test-backup')
    done('new-app')
if args[0] == 'exec':
    if 'tesseract' in args:
        done('List of available languages:\neng\nrus')
    done('200')
if args[0] == 'rename':
    c=find(args[1])
    if c:
        c['name']=args[2]
    done()
if args[0] == 'rm':
    c=find(args[-1])
    if c:
        c['running']=False
    done()
if args[0] in ['network','tag','image','volume','logs']:
    done()
done('Unsupported Docker call: '+repr(args), 82)
