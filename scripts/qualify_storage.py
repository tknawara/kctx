#!/usr/bin/env python3
"""Disposable real filesystem/Git/Dolt qualification with process death at boundaries.

No Dolt mock or fake transport is used. Trace hooks only kill the Python process;
all writes leading to the selected boundary are production calls to native Dolt.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from qualification_common import ROOT, Qualification, commit, git_repo

sys.path.insert(0, str(ROOT / 'src'))
GRAPH_PHASES = ('intent', 'candidate-ready', 'nodes-imported', 'edges-imported',
                'data-ready', 'data-committed', 'metadata-ready', 'metadata-committed',
                'validated', 'native-published', 'activation-ready', 'activation-journaled',
                'active-written', 'activated')


def worker(request_path: Path) -> int:
    request = json.loads(request_path.read_text())
    action = request['action']
    if action != 'suite':
        from kctx.observability import init_logging
        init_logging(verbose=True)
    if action == 'suite':
        sys.path.insert(0, str(ROOT / 'tests'))
        suite = unittest.defaultTestLoader.loadTestsFromNames(request['modules'])
        class RecordedResult(unittest.TextTestResult):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.passed = []

            def addSuccess(self, test):
                super().addSuccess(test)
                self.passed.append(test.id())

        captured = io.StringIO()
        with redirect_stdout(captured):
            result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite)
        print(json.dumps({'tests':result.testsRun,'skipped':[(test.id(), reason) for test, reason in result.skipped],
                          'passed':result.passed,'test_stdout':captured.getvalue(),
                          'failures':[(test.id(), detail) for test, detail in result.failures],
                          'errors':[(test.id(), detail) for test, detail in result.errors]}))
        return 0 if result.wasSuccessful() and not result.skipped and result.testsRun else 1
    if action == 'immutable':
        from kctx.adapters.files.storage import exclusive_write_json
        phase = request.get('phase')
        def profile(frame, event, arg):
            if event == ('c_call' if phase == 'before-link' else 'c_return') and arg is os.link:
                os._exit(86)
        if phase:
            sys.setprofile(profile)
        exclusive_write_json(Path(request['path']), {'writer':request['writer'],'payload':'x'*100000})
        return 0
    if action == 'restore-native':
        from kctx.adapters.dolt.native import restore_backup
        binary = shutil.which('dolt')
        if binary is None:
            raise RuntimeError('real Dolt prerequisite missing')
        restore_backup(Path(request['source']), Path(request['destination']), dolt_bin=binary)
        print(json.dumps({'restored': request['destination']}))
        return 0
    from kctx.graph import sync
    from kctx.graph.dolt_store import DoltStore
    from kctx.graph.generation import completed_snapshot
    from kctx.graph.quoting import sql_quote
    repo = Path(request['repo'])
    store = DoltStore(sync.dolt_db_dir())
    if action == 'sync':
        selected = request.get('phase')
        commit_calls = 0
        def trace(frame, event, arg):
            nonlocal commit_calls
            name = frame.f_code.co_name
            filename = frame.f_code.co_filename
            phase = None
            if filename.endswith('/graph/dolt_store.py'):
                if name == 'replace_table' and event == 'return':
                    phase = {'nodes':'nodes-imported','edges':'edges-imported'}.get(frame.f_locals['table'])
                if name == 'commit' and event == 'call':
                    commit_calls += 1
                    phase = 'data-ready' if commit_calls == 1 else 'metadata-ready'
                if name == 'commit' and event == 'return':
                    phase = 'data-committed' if commit_calls == 1 else 'metadata-committed'
            if filename.endswith('/graph/generation.py'):
                if name == 'snapshot_at' and event == 'return' and frame.f_back.f_code.co_name == 'publish':
                    phase = 'validated'
                if name == 'publish' and event == 'return':
                    phase = 'native-published'
            if filename.endswith('/adapters/files/storage.py') and name == 'exclusive_write_json' and event == 'return' and frame.f_back.f_code.co_name == 'start':
                phase = 'intent'
            if filename.endswith('/graph/operations.py'):
                if name == 'start' and event == 'return':
                    phase = 'candidate-ready'
                elif name == 'activate' and event == 'call':
                    phase = 'activation-ready'
                elif name == 'save' and event == 'return' and frame.f_locals['status'] == 'ready':
                    phase = 'activation-journaled'
                elif name == '_write_active' and event == 'return':
                    phase = 'active-written'
                elif name == 'activate' and event == 'return':
                    phase = 'activated'
            if selected is not None and phase == selected:
                Path(request['marker']).write_text(phase)
                os._exit(86)
            return trace
        if selected:
            sys.settrace(trace)
        result = sync.sync(repo, rebuild=request.get('rebuild',False))
        sys.settrace(None)
        print(json.dumps(result))
        return 0
    snapshot = completed_snapshot(store)
    if action == 'snapshot':
        if snapshot is None:
            raise RuntimeError('no completed native snapshot')
        rows = store.sql_read(f'SELECT * FROM edges AS OF {sql_quote(snapshot.data_commit.val)} ORDER BY edge_id')
        print(json.dumps({'metadata':snapshot.metadata_commit.val,'data':snapshot.data_commit.val,
                          'state':snapshot.state.to_wire(),'rows':rows,'db_dir':str(store.db_dir)}))
        return 0
    if action == 'pinned-reader':
        assert snapshot is not None
        query = f'SELECT * FROM edges AS OF {sql_quote(snapshot.data_commit.val)} ORDER BY edge_id'
        original = store.sql_read(query)
        Path(request['marker']).write_text(snapshot.data_commit.val)
        count=0
        while not Path(request['stop']).exists() and count < 100:
            assert store.sql_read(query)==original, 'mixed generation read'
            count+=1
        assert count>0
        print(json.dumps({'pinned':snapshot.data_commit.val,'reads':count,'rows':original}))
        return 0
    raise ValueError(f'unknown worker action: {action}')


class StorageFixture:
    def __init__(self, q: Qualification, root: Path) -> None:
        from kctx.config import write_config
        self.q=q
        self.root=root
        self.repo=root/'kb'
        self.graph=root/'graph'
        git_repo(q,self.repo)
        (self.repo/'inventory'/'relationships').mkdir(parents=True)
        self.relation=self.repo/'inventory'/'relationships'/'uses.json'
        self.relation.write_text('{"from":"service","to":"old","type":"consumes"}\n')
        (self.repo/'note.md').write_text('Operational evidence ⟦cite kind=ticket id=QUAL-1 seen=2026-10-30T00:00Z⟧\n')
        self.old_git=commit(q,self.repo,'initial retained source')
        self.config=write_config(root/'config.toml',root=str(self.repo),graph_dir=str(self.graph),log_dir=str(root/'logs'))
        self.env=dict(os.environ,KCTX_CONFIG=str(self.config),PYTHONPATH=str(ROOT/'src'))
        self.serial=0
        self.call('sync')
        self.before=self.call('snapshot')

    def request(self, action: str, **extra: object) -> tuple[list[str],Path]:
        self.serial+=1
        path=self.root/f'request-{self.serial}.json'
        path.write_text(json.dumps({'action':action,'repo':str(self.repo),**extra}))
        return [sys.executable,str(Path(__file__).resolve()),'--worker',str(path)],path

    def call(self, action: str, *, expected: int = 0, **extra: object) -> object:
        argv,_=self.request(action,**extra)
        result=self.q.run(argv,env=self.env,expected=expected)
        return json.loads(result.stdout) if result.stdout.strip() and expected==0 else result.returncode

    def change(self) -> str:
        self.relation.write_text('{"from":"service","to":"new","type":"consumes"}\n')
        return commit(self.q,self.repo,'new source')


def graph_crash(q: Qualification, root: Path, phase: str) -> dict[str,object]:
    fixture=StorageFixture(q,root/phase)
    fixture.change()
    marker=fixture.root/'phase'
    fixture.call('sync',expected=86,phase=phase,marker=str(marker),rebuild=True)
    assert marker.read_text()==phase
    after=fixture.call('snapshot')
    if phase in ('active-written', 'activated'):
        assert after['metadata']!=fixture.before['metadata']
        assert any(row['dst_node']=='new' for row in after['rows'])
    else:
        assert after==fixture.before, 'failed rebuild altered completed generation'
    # Historical native rows survive even when the working tables are dirty.
    native=q.run(['dolt','sql','-r','json','-q',f"SELECT * FROM edges AS OF '{fixture.before['data']}' ORDER BY edge_id"],cwd=Path(fixture.before['db_dir']))
    assert json.loads(native.stdout)['rows']==fixture.before['rows']
    recovery = fixture.call('sync', rebuild=True)
    completed = fixture.call('snapshot')
    assert any(row['dst_node'] == 'new' for row in completed['rows'])
    replay = fixture.call('sync')
    assert replay['status'] == 'up-to-date'
    assert fixture.call('snapshot') == completed
    return {'phase':phase,'before':fixture.before,'after_crash':after,'recovery':recovery,'replay':replay,'exit':86}


def concurrent_graph(q: Qualification, root: Path) -> dict[str,object]:
    fixture=StorageFixture(q,root/'concurrent')
    fixture.change()
    marker=fixture.root/'pinned'
    stop=fixture.root/'stop'
    argv,_=fixture.request('pinned-reader',marker=str(marker),stop=str(stop))
    reader=subprocess.Popen(argv,env=fixture.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    deadline=time.monotonic()+30
    while not marker.exists() and reader.poll() is None and time.monotonic()<deadline:
        time.sleep(.01)
    assert marker.exists(),'reader failed to select native snapshot'
    writers=[]
    for _ in range(2):
        command,_=fixture.request('sync')
        writers.append((command,subprocess.Popen(command,env=fixture.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)))
    results=[]
    try:
        for command,process in writers:
            stdout,stderr=process.communicate(timeout=180)
            q.commands.append({'argv':command,'returncode':process.returncode,'stdout':stdout,'stderr':stderr,'concurrent':True})
            assert process.returncode==0,stderr
            results.append(json.loads(stdout))
    finally:
        stop.write_text('done')
    stdout,stderr=reader.communicate(timeout=120)
    q.commands.append({'argv':argv,'returncode':reader.returncode,'stdout':stdout,'stderr':stderr,'concurrent_reader':True})
    assert reader.returncode==0,stderr
    assert sorted(r['status'] for r in results)==['synced','up-to-date']
    assert json.loads(stdout)['pinned']==fixture.before['data']
    return {'writers':results,'reader':json.loads(stdout)}


def graph_restore(q: Qualification, root: Path) -> dict[str,object]:
    fixture=StorageFixture(q,root/'restore-source')
    fixture.change()
    fixture.call('sync')
    current=fixture.call('snapshot')
    backup=root/'independent-backup'
    backup.mkdir()
    q.run(['git','bundle','create',str(backup/'sources.bundle'),'--all'],cwd=fixture.repo)
    native_backup = backup / 'dolt-backup'
    native_backup.mkdir()
    q.run(['dolt', 'backup', 'sync-url', native_backup.as_uri()], cwd=Path(current['db_dir']))
    # Remove all original sources and caches before restoring independent copies.
    shutil.rmtree(fixture.root)
    restored=root/'restored'
    restored.mkdir()
    q.run(['git','clone',str(backup/'sources.bundle'),str(restored/'kb')])
    restore_request = root/'restore-native.json'
    restore_request.write_text(json.dumps({'action':'restore-native','source':str(native_backup),'destination':str(restored/'dolt')}))
    q.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(restore_request)])
    historical={}
    for name,snapshot in [('historical',fixture.before),('current',current)]:
        result=q.run(['dolt','sql','-r','json','-q',f"SELECT * FROM edges AS OF '{snapshot['data']}' ORDER BY edge_id"],cwd=restored/'dolt')
        assert json.loads(result.stdout)['rows']==snapshot['rows']
        source=q.run(['git','show',f"{snapshot['state']['kb_sha']}:note.md"],cwd=restored/'kb')
        assert 'QUAL-1' in source.stdout
        historical[name]={'native':snapshot['data'],'git':snapshot['state']['kb_sha']}
    q.run(['dolt','gc'],cwd=restored/'dolt',timeout=180)
    q.run(['git','gc','--prune=now'],cwd=restored/'kb')
    for snapshot in (fixture.before,current):
        result=q.run(['dolt','sql','-r','json','-q',f"SELECT * FROM edges AS OF '{snapshot['data']}' ORDER BY edge_id"],cwd=restored/'dolt')
        assert json.loads(result.stdout)['rows']==snapshot['rows']
    missing=root/'git-only'
    q.run(['git','clone',str(backup/'sources.bundle'),str(missing)])
    from kctx.config import write_config
    config=write_config(root/'missing.toml',root=str(missing),graph_dir=str(root/'missing-graph'))
    env=dict(os.environ,KCTX_CONFIG=str(config),PYTHONPATH=str(ROOT/'src'))
    failed=q.run([sys.executable,'-m','kctx','graph','uses','old'],env=env,expected=None)
    assert failed.returncode!=0,'Git-only restore falsely returned complete structured knowledge'
    return {'restored':historical,'original_removed':True,'native_gc_executed':True,'missing_dolt_exit':failed.returncode}


def immutable_files(q: Qualification, root: Path) -> dict[str,object]:
    for phase in ('before-link','after-link'):
        request=root/(phase+'.json')
        destination=root/(phase+'-published.json')
        request.write_text(json.dumps({'action':'immutable','path':str(destination),'phase':phase,'writer':'crash'}))
        q.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(request)],expected=86)
        if phase=='before-link':
            assert not destination.exists()
        else:
            assert json.loads(destination.read_text())['payload']=='x'*100000
    destination=root/'race.json'
    processes=[]
    for writer in ('one','two'):
        request=root/(writer+'.json')
        request.write_text(json.dumps({'action':'immutable','path':str(destination),'writer':writer}))
        argv=[sys.executable,str(Path(__file__).resolve()),'--worker',str(request)]
        processes.append((argv,subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)))
    codes=[]
    for argv,process in processes:
        stdout,stderr=process.communicate(timeout=30)
        codes.append(process.returncode)
        q.commands.append({'argv':argv,'returncode':process.returncode,'stdout':stdout,'stderr':stderr,'concurrent':True})
    assert sorted(codes)==[0,1]
    assert json.loads(destination.read_text())['writer'] in ('one','two')
    return {'boundaries':['before hard-link','after hard-link'],'competing_creators':codes}


def native_failures(q: Qualification, root: Path) -> dict[str, object]:
    fixture = StorageFixture(q, root / 'native-contract')
    db = Path(fixture.before['db_dir'])
    q.run(['dolt', 'sql', '-q', "CREATE TABLE qualification_types (id INT PRIMARY KEY, label TEXT, enabled BOOLEAN); INSERT INTO qualification_types VALUES (1, 'λ,quoted', TRUE)"], cwd=db)
    result = q.run(['dolt', 'sql', '-r', 'json', '-q', 'SELECT * FROM qualification_types'], cwd=db)
    rows = json.loads(result.stdout)['rows']
    assert rows[0]['id'] == 1 and rows[0]['label'] == 'λ,quoted' and rows[0]['enabled'] == 1
    failures = []
    for query in ("INSERT INTO qualification_types VALUES (1, 'duplicate', FALSE)",
                  'THIS IS NOT SQL',
                  "SELECT * FROM nodes AS OF '00000000000000000000000000000000'"):
        failure = q.run(['dolt', 'sql', '-r', 'json', '-q', query], cwd=db, expected=None)
        assert failure.returncode != 0
        failures.append({'query': query, 'exit': failure.returncode})
    q.run(['dolt', 'sql', '-q', "START TRANSACTION; INSERT INTO qualification_types VALUES (2,'rolled back',FALSE); ROLLBACK"], cwd=db)
    result = q.run(['dolt', 'sql', '-r', 'json', '-q', 'SELECT COUNT(*) AS n FROM qualification_types'], cwd=db)
    assert json.loads(result.stdout)['rows'][0]['n'] == 1
    assert fixture.call('snapshot') == fixture.before
    return {'typed_rows': rows, 'failures': failures, 'sql_did_not_publish_snapshot': True}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=False,type=Path)
    parser.add_argument('--worker',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--section',choices=['all','graph','files','knowledge'],default='all')
    args=parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if args.output is None:
        parser.error('--output is required')
    q=Qualification('storage',args.output)
    q.report['failure_injection']='sys.settrace/profile observes real production boundaries; os._exit(86), no mocked storage calls'
    q.case('prerequisites',[],q.prerequisites)
    if q.cases[-1]['status']!='passed':
        return q.finish()
    with tempfile.TemporaryDirectory(prefix='kctx-storage-') as directory:
        root=Path(directory)
        if args.section in ('all','files'):
            q.case('immutable-filesystem-publication',['Q45','Q46'],lambda:immutable_files(q,root))
        if args.section in ('all','graph'):
            for phase in GRAPH_PHASES:
                q.case('graph-crash-'+phase,['Q47','Q50','Q58','D40'],lambda phase=phase:graph_crash(q,root,phase))
            q.case('competing-writers-pinned-reader',['Q47','Q57','D27','D42','D45'],lambda:concurrent_graph(q,root))
            q.case('independent-restore-native-history',['Q63','Q64','D49','D50'],lambda:graph_restore(q,root))
            q.case('native-sql-failure-contracts',['Q59','Q60','D28','D34','D69','D71'],lambda:native_failures(q,root))
            request=root/'regressions.json'
            request.write_text(json.dumps({'action':'suite','modules':['test_graph_integration','test_graph_identity','test_graph_extract','test_graph_quoting','test_graph_parity','test_graph_inputs','test_graph_recovery','test_qualification_protocol']}))
            q.case('production-graph-regressions',['Q48','Q49','Q51','Q52','Q53','Q54','Q55','Q56','D32'],
                   lambda:json.loads(q.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(request)],timeout=600).stdout))
        if args.section in ('all','knowledge'):
            from qualification_knowledge import qualify
            qualify(q,root)
    return q.finish()


if __name__=='__main__':
    raise SystemExit(main())
