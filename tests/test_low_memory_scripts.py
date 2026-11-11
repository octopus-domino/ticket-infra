"""Exercise real Bash entrypoints with an isolated, stateful Docker CLI double.

Run: python ticket-infra/tests/test_low_memory_scripts.py
No Docker daemon, application data, production .env or DNS is accessed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import sys

WORKSPACE=Path(__file__).resolve().parents[2]
GIT_BASH=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/bin/bash.exe'
BASH=str(GIT_BASH) if os.name=='nt' and GIT_BASH.exists() else shutil.which('bash')

def posix(path):
    path=path.resolve()
    return '/'+path.drive[0].lower()+path.as_posix()[2:] if os.name=='nt' else str(path)

class ScriptsTest(unittest.TestCase):
    def fixture(self,mode='pg',**extra):
        (WORKSPACE/'temp').mkdir(exist_ok=True)
        root=Path(tempfile.mkdtemp(prefix='lowmem-',dir=WORKSPACE/'temp'))
        # Fixtures are deliberately retained for diagnosis; no recursive deletion is performed.
        self.assertTrue(root.resolve().is_relative_to((WORKSPACE/'temp').resolve()))
        files=['build.sh','build.ps1','deploy.sh','Dockerfile','buildkitd-low-memory.toml',
               'scripts/lib/low-memory-build.sh','scripts/migrate-postgres.sh',
               'scripts/deploy-postgres.sh','compose.api.yml','compose.postgres.yml','compose.gateway.yml']
        for name in files:
            dest=root/'ticket-infra'/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(WORKSPACE/'ticket-infra'/name,dest)
        (root/'ticket-editor').mkdir()
        sql=root/'ticket-pdf/src/main/resources/db';sql.mkdir(parents=True)
        for name in ['upgrade-journeys.sql','upgrade-workflows.sql']:
            shutil.copyfile(WORKSPACE/'ticket-pdf/src/main/resources/db'/name,sql/name)
        (root/'data').mkdir();(root/'data/ticket-db.mv.db').write_bytes(b'isolated fixture, not a database')
        values=dict(JWT_SECRET='test-only-secret-012345678901234567890123456789',
                    APP_FRONTEND_URL='https://codoc.test',DATABASE_PASSWORD='test-postgres',
                    TYK_ADMIN_SECRET='test-only-tyk-012345678901234567890123456789',
                    REDIS_PASSWORD='test-only-redis-012345678901234567890123456789',
                    GOOGLE_CLIENT_ID='test',GOOGLE_CLIENT_SECRET='test',SKIP_GIT_PULL='true',
                    DATA_DIR=posix(root/'data'),BACKUP_DIR=posix(root/'backups'))
        (root/'.env').write_bytes(('\n'.join(f"{k}='{v}'" for k,v in values.items())+'\n').encode())
        if mode=='pg':(root/'.postgres.env').write_bytes(b'SPRING_PROFILES_ACTIVE=prod,postgres\n')
        def c(name,service,project='codoc',managed=True):
            return dict(name=name,service=service,project=project,running=True,managed=managed)
        containers=dict(gateway=c('old-gateway','gateway','codoc-gateway'),redis=c('old-redis','redis','codoc-gateway'),
                        unrelated=c('unrelated','database','other-project',False))
        if mode=='pg':containers.update(pgapp=c('codoc-app-1','app'),pg=c('codoc-postgres-1','postgres'))
        else:containers['legacy']=c('ticket-app','','')
        state=dict(containers=containers,calls=[],targets=[],builder_running=False,builder_created=False,
                   import_started=False,sql_started=False,dumped=False,backed_up=False)
        (root/'state.json').write_text(json.dumps(state))
        (root/'meminfo').write_text('MemTotal: 4194304 kB\nMemAvailable: '+str(extra.pop('available',3200)*1024)+' kB\n')
        bindir=root/'bin';bindir.mkdir()
        (bindir/'docker').write_bytes(b'#!/usr/bin/env bash\nexec python "$FAKE_DOCKER_PY" "$@"\n')
        (bindir/'flock').write_bytes(b'#!/usr/bin/env bash\n[[ "${FAKE_LOCK_BUSY:-}" != 1 ]]\n')
        (bindir/'curl').write_bytes(b'#!/usr/bin/env bash\nif [[ "$*" == *http_code* ]]; then echo 401; else echo "{}"; fi\n')
        for command in bindir.iterdir():command.chmod(0o755)
        (root/'test-env.sh').write_bytes(b'export PATH="$FAKE_BIN_POSIX:$PATH"\n')
        env=dict(os.environ,PATH=str(bindir)+os.pathsep+os.environ['PATH'],
                 FAKE_DOCKER_PY=(WORKSPACE/'ticket-infra/tests/fake-docker.py').as_posix(),
                 FAKE_DOCKER_STATE=str(root/'state.json'),FAKE_ROOT_POSIX=posix(root),
                 CODOC_MEMINFO_FILE=(root/'meminfo').as_posix(),MSYS_NO_PATHCONV='1',
                 FAKE_BIN_POSIX=posix(bindir),BASH_ENV=(root/'test-env.sh').as_posix())
        env.update({k:str(v) for k,v in extra.items()})
        return root,env

    def run_script(self,root,env,script,*arguments):
        completed=subprocess.run([BASH,script,*arguments],cwd=root,env=env,capture_output=True,text=True,timeout=120)
        (root/'last-output.txt').write_text(completed.stdout+completed.stderr)
        return completed,json.loads((root/'state.json').read_text())

    def success(self,result):
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_standalone_build_stops_only_managed_stack_and_reuses_cache(self):
        root,env=self.fixture()
        for attempt in range(2):
            result,state=self.run_script(root,env,'ticket-infra/build.sh');self.success(result)
            self.assertFalse(state['builder_running'])
            self.assertTrue(all(c['running'] for c in state['containers'].values()))
        creates=[call for call in state['calls'] if call[:2]==['buildx','create']]
        self.assertEqual(len(creates),1)
        for setting in ['memory=2304m','memory-swap=2304m','cpu-period=100000','cpu-quota=200000']:
            self.assertIn(setting,creates[0])
        self.assertEqual(state['targets'],['runtime','runtime'])

    def test_not_enough_memory_restores_original_stack_without_building(self):
        root,env=self.fixture(available=1024)
        result,state=self.run_script(root,env,'ticket-infra/build.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('2816 MiB',result.stderr)
        self.assertFalse(state['targets'])
        self.assertTrue(all(c['running'] for c in state['containers'].values()))

    def test_unexpected_builder_limits_prevent_build_and_restore_stack(self):
        root,env=self.fixture(FAKE_BAD_LIMITS=1)
        result,state=self.run_script(root,env,'ticket-infra/build.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(state['targets'])
        self.assertFalse(state['builder_running'])
        self.assertTrue(all(c['running'] for c in state['containers'].values()))

    def test_builder_stop_failure_does_not_restart_runtime_alongside_builder(self):
        root,env=self.fixture(FAKE_FAIL_STOP=1)
        result,state=self.run_script(root,env,'ticket-infra/build.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(state['builder_running'])
        self.assertFalse(state['containers']['pgapp']['running'])

    def test_powershell_builder_stop_failure_also_keeps_runtime_offline(self):
        root,env=self.fixture(FAKE_FAIL_STOP=1)
        result,state=self.run_powershell(root,env)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(state['builder_running'])
        self.assertFalse(state['containers']['pgapp']['running'])

    def test_deployment_lock_failure_does_not_stop_application(self):
        root,env=self.fixture(FAKE_LOCK_BUSY=1)
        result,state=self.run_script(root,env,'ticket-infra/build.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(state['calls'])

    def test_migration_backs_up_before_build_and_loads_targets_sequentially(self):
        root,env=self.fixture('legacy',FAKE_REQUIRE_BACKUP=1)
        result,state=self.run_script(root,env,'ticket-infra/scripts/migrate-postgres.sh','--migrate');self.success(result)
        self.assertEqual(state['targets'],['runtime','migration'])
        self.assertFalse(state['builder_running'])
        self.assertFalse(state['containers']['legacy']['running'])
        self.assertTrue(state['containers']['pgapp']['running'])
        self.assertTrue(state['containers']['gateway']['running'])
        self.assertTrue(state['containers']['redis']['running'])
        self.assertTrue(state['containers']['unrelated']['running'])
        self.assertTrue((root/'.postgres.env').exists())
        self.assertEqual(len(list(root.glob('backups/*/h2-data.tar.gz'))),1)

    def test_migration_build_failure_resumes_h2_without_publishing_postgres_settings(self):
        root,env=self.fixture('legacy',FAKE_FAIL_BUILD=1,FAKE_REQUIRE_BACKUP=1)
        result,state=self.run_script(root,env,'ticket-infra/scripts/migrate-postgres.sh','--migrate')
        self.assertEqual(result.returncode,42,result.stdout+result.stderr)
        self.assertFalse(state['builder_running'])
        self.assertTrue(state['containers']['legacy']['running'])
        self.assertFalse(state['import_started'])
        self.assertFalse((root/'.postgres.env').exists())

    def test_import_failure_keeps_application_offline_instead_of_resuming_h2_writes(self):
        root,env=self.fixture('legacy',FAKE_FAIL_IMPORT=1)
        result,state=self.run_script(root,env,'ticket-infra/scripts/migrate-postgres.sh','--migrate')
        self.assertEqual(result.returncode,37,result.stdout+result.stderr)
        self.assertFalse(state['containers']['legacy']['running'])
        self.assertFalse((root/'.postgres.env').exists())
        self.assertFalse(state['builder_running'])

    def test_postgres_update_dumps_before_build_and_restarts_existing_gateway(self):
        root,env=self.fixture(FAKE_REQUIRE_BACKUP=1)
        result,state=self.run_script(root,env,'ticket-infra/scripts/deploy-postgres.sh');self.success(result)
        self.assertTrue(state['dumped'])
        self.assertTrue(state['sql_started'])
        self.assertEqual(state['targets'],['runtime'])
        self.assertTrue(state['containers']['pgapp']['running'])
        self.assertTrue(state['containers']['gateway']['running'])
        self.assertFalse(state['builder_running'])

    def test_postgres_build_failure_resumes_previous_app_without_schema_changes(self):
        root,env=self.fixture(FAKE_FAIL_BUILD=1)
        result,state=self.run_script(root,env,'ticket-infra/scripts/deploy-postgres.sh')
        self.assertEqual(result.returncode,42,result.stdout+result.stderr)
        self.assertFalse(state['sql_started'])
        self.assertTrue(state['containers']['pgapp']['running'])
        self.assertFalse(state['builder_running'])

    def test_postgres_sql_failure_keeps_app_stopped_for_review(self):
        root,env=self.fixture(FAKE_FAIL_SQL=1)
        result,state=self.run_script(root,env,'ticket-infra/scripts/deploy-postgres.sh')
        self.assertEqual(result.returncode,31,result.stdout+result.stderr)
        self.assertTrue(state['sql_started'])
        self.assertFalse(state['containers']['pgapp']['running'])
        self.assertFalse(state['builder_running'])

    def test_legacy_deploy_uses_same_capped_builder_and_stops_old_app(self):
        root,env=self.fixture('legacy',FAKE_REQUIRE_BACKUP=1)
        env['CODOC_DEPLOY_SNAPSHOT_ROOT']=posix(root)
        result,state=self.run_script(root,env,'ticket-infra/deploy.sh');self.success(result)
        self.assertFalse(state['containers']['legacy']['running'])
        self.assertTrue(state['containers']['new-app']['running'])
        self.assertFalse(state['builder_running'])

    def test_legacy_build_failure_restores_old_app(self):
        root,env=self.fixture('legacy',FAKE_FAIL_BUILD=1)
        env['CODOC_DEPLOY_SNAPSHOT_ROOT']=posix(root)
        result,state=self.run_script(root,env,'ticket-infra/deploy.sh')
        self.assertEqual(result.returncode,42,result.stdout+result.stderr)
        self.assertTrue(state['containers']['legacy']['running'])
        self.assertFalse(state['builder_running'])

    def run_powershell(self,root,env):
        shell=shutil.which('pwsh') or shutil.which('powershell')
        if not shell:self.skipTest('PowerShell is not installed on this host')
        driver=root/'test-powershell.ps1'
        driver.write_bytes(b'function docker { & $env:FAKE_PYTHON $env:FAKE_DOCKER_PY @args; $global:LASTEXITCODE=$LASTEXITCODE }\n& "$PSScriptRoot/ticket-infra/build.ps1"\nexit $LASTEXITCODE\n')
        env=dict(env,FAKE_PYTHON=sys.executable)
        result=subprocess.run([shell,'-NoProfile','-File',str(driver)],cwd=root,env=env,capture_output=True,text=True,timeout=120)
        (root/'last-output.txt').write_text(result.stdout+result.stderr)
        return result,json.loads((root/'state.json').read_text())

    def test_powershell_uses_same_limits_and_restores_original_containers(self):
        root,env=self.fixture()
        result,state=self.run_powershell(root,env);self.success(result)
        self.assertEqual(state['targets'],['runtime'])
        self.assertTrue(all(c['running'] for c in state['containers'].values()))
        self.assertFalse(state['builder_running'])
        create=next(call for call in state['calls'] if call[:2]==['buildx','create'])
        self.assertIn('memory=2304m',create)
        self.assertIn('cpu-quota=200000',create)

    def test_powershell_build_failure_also_restores_previous_containers(self):
        root,env=self.fixture(FAKE_FAIL_BUILD=1)
        result,state=self.run_powershell(root,env)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(any(call[:2]==['buildx','build'] for call in state['calls']))
        self.assertTrue(all(c['running'] for c in state['containers'].values()))
        self.assertFalse(state['builder_running'])

    def test_powershell_checks_daemon_host_memory_before_building(self):
        root,env=self.fixture(available=1024)
        result,state=self.run_powershell(root,env)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(state['targets'])
        self.assertTrue(all(c['running'] for c in state['containers'].values()))

if __name__=='__main__':
    unittest.main(verbosity=2)
