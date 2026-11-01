"""Canonical knowledge production-path cases, invoked by qualify_storage.py."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from qualification_common import ROOT, Qualification, commit, git_repo

sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tests'/'semantics'))


def worker(request_path: Path) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from kctx.domain.ids import AuthorityKeyId, ContextId, DoltCommitId, PlanId, PolicyDigest, ReleaseId, SourceId, SourceRevision
    from kctx.services.knowledge import KnowledgeEngine
    from kctx.services.knowledge_models import Approval, CaptureKind
    from kctx.semantics.wire import dec_context
    from kctx.semantics.workflow_models import NamedContext
    from examples import wire_kb, wire_context
    request=json.loads(request_path.read_text())
    from kctx.observability import init_logging
    init_logging(verbose=True)
    root=Path(request['root'])
    state_path=root/'fixture-state.json'
    action=request['action']
    if action=='initialize':
        key=Ed25519PrivateKey.generate()
        private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        (root/'private.pem').write_bytes(private)
        (root/'private.pem').chmod(0o600)
        policy={'schema_version':2,'kb_id':'qualification','policy_version':'review-policy','trusted_keys':{'reviewer-key':{'public_key':key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex(),'target_uses':['review']}}}
        path=root/'repo'/'.kctx'/'knowledge-policy.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(policy))
        state={'policy':hashlib.sha256(path.read_bytes()).hexdigest(),'plans':{},'releases':{},'captures':[],
               'current_kb':None,'candidates':{}}
        state_path.write_text(json.dumps(state))
        print(json.dumps({'policy_digest':state['policy']}))
        return 0
    state=json.loads(state_path.read_text())
    phase=request.get('phase')
    def fault(actual: str) -> None:
        if actual==phase:
            (root/'crash-phase').write_text(actual)
            os._exit(86)
    engine=KnowledgeEngine(root/'repo',root/'dolt',PolicyDigest(state['policy']),fault=fault)
    result: object
    if action=='prepare':
        name=request['name']
        base=state['current_kb']
        kb=copy.deepcopy(base) if base else wire_kb('unused')
        if base is None:
            for collection in ('observations','claims','attestations','enumerations','derivations','corrections','receipts'):
                kb[collection]=[]
        kb['snapshot']='snapshot-'+name
        captures=list(state['captures'])
        assignments = []
        for kind in CaptureKind:
            suffix=name+'-'+kind.value
            payload=('Synthetic retained '+suffix+' evidence; statements require explicit reviewer attestation.').encode()
            capture=engine.capture(kind,SourceId('source:'+suffix),SourceRevision('revision:'+suffix),payload,100)
            captures.append(capture.id.val)
            template=wire_kb()
            observation=template['observations'][0]
            observation.update(id='observation-'+suffix,source=capture.source.val,revision=capture.revision.val,content=capture.content.val)
            claim=template['claims'][0]
            claim.update(id='claim-'+suffix,revision='r1')
            ref={'id':claim['id'],'revision':'r1'}
            attestation=template['attestations'][0]
            attestation.update(id='attestation-'+suffix,claim=ref,observation=observation['id'],authority='reviewer-key')
            derivation=template['derivations'][0]
            derivation.update(id='derivation-'+suffix,claim=ref,witness={'tag':'attest','attestation':attestation['id']})
            assignments.append({'claim':ref,'context':'review','witness':derivation['witness']})
            for collection,item in (('observations',observation),('claims',claim),('attestations',attestation),('derivations',derivation)):
                kb[collection].append(item)
        if request.get('retract_initial'):
            target = kb['claims'][0]
            kb['corrections'].append({'id':'correction-'+name,'kind':'retract',
                'target':{'id':target['id'],'revision':target['revision']},
                'replacement':None,'recorded_at':110})
        context=wire_context(kb['snapshot'])
        context['policy']['authorized_actors'] = ['reviewer-key']
        context['sources'] = [{key: observation[key] for key in ('source','revision','content')}
                              for observation in kb['observations']]
        candidate={'schema_version':3,'expected_snapshot':base['snapshot'] if base else 'bootstrap:qualification',
                   'kb':kb,'capture_ids':captures,'contexts':[{'id':'review','context':context}],
                   'assignments':assignments,'retired_contexts':[],'authority_key':'reviewer-key'}
        plan=engine.propose(candidate,'review',110)
        approval=engine.sign(plan.id,root/'private.pem',AuthorityKeyId('reviewer-key'))
        state['plans'][name]={'plan':plan.id.val,'approval':approval.wire(),'captures':captures}
        state['candidates'][name]=candidate
        result={'plan':plan.id.val,'approval':approval.wire(),'snapshot':kb['snapshot']}
    elif action=='select':
        name=request['name']
        context_wire=wire_context(state['current_kb']['snapshot'])
        context_wire['policy']['authorized_actors']=['reviewer-key']
        context_wire['sources'] = [{key: observation[key] for key in ('source','revision','content')}
                                   for observation in state['current_kb']['observations']]
        retained=request.get('release') or state['releases'][request['target']]
        plan=engine.rollback(ReleaseId(retained),(NamedContext(ContextId('review'),dec_context(context_wire)),),AuthorityKeyId('reviewer-key'),target_use='review')
        approval=engine.sign(plan.id,root/'private.pem',AuthorityKeyId('reviewer-key'))
        kb=copy.deepcopy(state['current_kb'])
        kb['snapshot']=plan.semantic.new_snapshot.val
        state['plans'][name]={'plan':plan.id.val,'approval':approval.wire(),'captures':state['captures']}
        state['candidates'][name]={'kb':kb}
        result={'plan':plan.id.val,'snapshot':kb['snapshot'],'retained':retained}
    elif action=='admit':
        name=request['name']
        plan=state['plans'][name]
        result=engine.admit(PlanId(plan['plan']),Approval.decode(plan['approval']))
        state['releases'][name]=result['release']
        state['current_kb']=state['candidates'][name]['kb']
        state['captures']=plan['captures']
    elif action=='recover':
        result=engine.recover()
    elif action=='context':
        name=request['name']
        context_wire = wire_context(state['candidates'][name]['kb']['snapshot'],now=request.get('now',110))
        context_wire['policy']['authorized_actors'] = ['reviewer-key']
        context_wire['sources'] = [{key: observation[key] for key in ('source','revision','content')}
                                   for observation in state['candidates'][name]['kb']['observations']]
        context=dec_context(context_wire)
        selected=request.get('release') or state['releases'].get(name)
        result=engine.context((),context,limit=request.get('limit',100),
                              continuation=request.get('continuation'),
                              release=ReleaseId(selected) if selected else None,context_id=ContextId('review'))
    elif action=='backup':
        result=engine.backup(Path(request['destination']))
    elif action=='restore':
        result=engine.restore(Path(request['source']))
    elif action=='migrate':
        migration_phase = request.get('migration_phase')
        def migration_trace(frame, event, arg):
            if event == 'return' and frame.f_code.co_filename.endswith('/adapters/files/knowledge.py'):
                name = frame.f_code.co_name
                path = frame.f_locals.get('path')
                actual = None
                if isinstance(path, Path):
                    if name == 'durable_write' and path.name == 'source.bytes':
                        actual = 'migration-source'
                    elif name == 'save' and path.parent.name == 'migration-candidates':
                        actual = 'migration-candidate'
                    elif name == 'save' and path.name == 'receipt.json':
                        actual = {'candidate': 'migration-receipt', 'rolling_back': 'rollback-intent',
                                  'rolled_back': 'rollback-complete'}.get(frame.f_locals['value'].get('state'))
                    elif name == 'durable_unlink' and path.parent.name == 'migration-candidates':
                        actual = 'rollback-unlink'
                if actual is not None and actual == migration_phase:
                    (root / 'migration-crash-phase').write_text(actual)
                    os._exit(86)
            return migration_trace
        if migration_phase:
            sys.settrace(migration_trace)
        result=engine.migrate(Path(request['source']),apply=request.get('apply',False),
                              rollback=PlanId(request['rollback']) if request.get('rollback') else None)
        sys.settrace(None)
    elif action=='restore-migration':
        result=engine.restore_migration(PlanId(request['migration']),Path(request['destination']))
    elif action=='tamper-plan':
        plan=state['plans'][request['name']]['plan']
        path=engine.root/'plans'/(plan+'.json')
        raw=json.loads(path.read_text())
        raw['plan']['candidate']['snapshot']='tampered-after-approval'
        path.write_text(json.dumps(raw))
        result={'tampered':plan}
    elif action=='audit':
        release=engine.git.current()
        if release is None:
            raise RuntimeError('no current audit generation')
        manifest=engine.git.manifest(release)
        result={'release':release,'manifest':manifest,
                'admissions':engine.store.rows('admissions',DoltCommitId(manifest['dolt_commit']))}
    elif action=='current':
        result={'release':engine.git.current()}
    else:
        raise ValueError(action)
    if action in ('prepare','admit','select'):
        state_path.write_text(json.dumps(state))
    print(json.dumps(result))
    return 0


class Fixture:
    def __init__(self,q: Qualification,root: Path,*,initial: bool=True) -> None:
        self.q=q
        self.root=root
        self.counter=0
        git_repo(q,root/'repo')
        from kctx.config import write_config
        binary = shutil.which('dolt')
        if binary is None:
            raise RuntimeError('real Dolt prerequisite missing')
        config = write_config(root/'config.toml', root=str(root/'repo'), dolt_bin=binary,
                              knowledge_dir=str(root/'dolt'), log_dir=str(root/'logs'))
        self.env = dict(os.environ, KCTX_CONFIG=str(config), PYTHONPATH=str(ROOT/'src'))
        self.call('initialize')
        if initial:
            self.call('prepare',name='initial')
            self.first=self.call('admit',name='initial')
            self.original=self.call('context',name='initial')

    def command(self,action: str,**kwargs: object) -> list[str]:
        self.counter+=1
        request=self.root/f'command-{self.counter}.json'
        request.write_text(json.dumps({'action':action,'root':str(self.root),**kwargs}))
        return [sys.executable,str(Path(__file__).resolve()),'--worker',str(request)]

    def call(self,action: str,*,expected: int|None=0,**kwargs: object) -> object:
        result=self.q.run(self.command(action,**kwargs),env=self.env,expected=expected,timeout=180)
        return json.loads(result.stdout) if result.returncode==0 else {'exit':result.returncode,'stderr':result.stderr}


def crash(q: Qualification,root: Path,phase: str) -> dict[str,object]:
    fixture=Fixture(q,root/('knowledge-'+phase))
    fixture.call('prepare',name='second')
    fixture.call('admit',name='second',phase=phase,expected=86)
    assert (fixture.root/'crash-phase').read_text()==phase
    selected=fixture.call('current')['release']
    if phase not in ('published', 'after_publish_cas'):
        assert selected==fixture.first['release']
    assert fixture.call('context',name='initial')==fixture.original
    if phase == 'manifest':
        state = json.loads((fixture.root/'fixture-state.json').read_text())
        plan_id = state['plans']['second']['plan']
        journal = json.loads((fixture.root/'repo'/'.git'/'kctx-knowledge'/'journal'/(plan_id+'.json')).read_text())
        denied = fixture.call('context', name='second', release=journal['release'], expected=None)
        assert denied.get('exit', 0) != 0, 'prepared Git manifest was readable before publication'
    recovery=fixture.call('recover')
    assert all(item['outcome'] in ('applied','already_applied') for item in recovery['operations'])
    replay=fixture.call('admit',name='second')
    assert replay['outcome']=='already_applied'
    current=fixture.call('context',name='second')
    assert len(current['records'])==6 and current['complete'] is True
    assert fixture.call('context',name='initial')==fixture.original
    return {'phase':phase,'recovery':recovery,'replay':replay,'historical_unchanged':True}


def competing(q: Qualification,root: Path) -> dict[str,object]:
    fixture=Fixture(q,root/'knowledge-competing')
    fixture.call('prepare',name='left')
    fixture.call('prepare',name='right')
    page=fixture.call('context',name='initial',limit=1)
    assert page['continuation'] is not None and page['omitted']==2
    codes = []
    with ExitStack() as captures:
        processes = []
        for name in ('left', 'right'):
            argv = fixture.command('admit', name=name)
            processes.append(captures.enter_context(
                q.capture(argv, env=fixture.env, role=f'knowledge-writer-{name}')))
        for process, _stdout, _stderr in processes:
            codes.append(process.wait(timeout=180))
    assert sorted(codes)==[0,1],codes
    following=fixture.call('context',name='initial',limit=1,continuation=page['continuation'])
    assert following['release']==page['release'] and following['records'][0]!=page['records'][0]
    assert fixture.call('context',name='initial')==fixture.original
    fixture.call('prepare',name='tampered')
    fixture.call('tamper-plan',name='tampered')
    rejected=fixture.call('admit',name='tampered',expected=None)
    assert rejected.get('exit',0)!=0
    return {'writers':codes,'pinned_continuation':following['release'],'tamper_exit':rejected['exit']}


def migration(q: Qualification,root: Path) -> dict[str,object]:
    fixture=Fixture(q,root/'knowledge-migration')
    state=json.loads((fixture.root/'fixture-state.json').read_text())
    source=fixture.root/'migration.json'
    source.write_text(json.dumps({'schema_version':2,'semantic_version':'2.0.0','candidate':state['candidates']['initial']},ensure_ascii=False))
    before={str(p.relative_to(fixture.root/'repo')):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (fixture.root/'repo').rglob('*') if p.is_file()}
    dry=fixture.call('migrate',source=str(source))
    after={str(p.relative_to(fixture.root/'repo')):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in (fixture.root/'repo').rglob('*') if p.is_file()}
    assert before==after and dry['state']=='dry_run'
    applied=fixture.call('migrate',source=str(source),apply=True)
    repeated=fixture.call('migrate',source=str(source),apply=True)
    assert applied==repeated and applied['accepted']==1 and applied['published'] is False
    retained=fixture.root/'repo'/'.git'/'kctx-knowledge'/'migrations'/applied['migration']/'source.bytes'
    assert retained.read_bytes()==source.read_bytes()
    rolled=fixture.call('migrate',source=str(source),rollback=applied['migration'])
    assert rolled['state']=='rolled_back'
    assert fixture.call('current')['release']==fixture.first['release']
    unknown=fixture.root/'unknown-schema.json'
    unknown.write_text('{"schema_version":999,"narrative":"preserve Unicode λ, commas, and old citations"}')
    quarantined=fixture.call('migrate',source=str(unknown),apply=True)
    assert quarantined['accepted']==0 and quarantined['quarantined']==1 and quarantined['state']=='quarantined'
    unknown_restored = fixture.root/'unknown-restored'
    fixture.call('restore-migration',migration=quarantined['migration'],destination=str(unknown_restored))
    assert (unknown_restored/unknown.name).read_bytes()==unknown.read_bytes()
    crash_results = []
    for index, phase in enumerate(('migration-source', 'migration-candidate', 'migration-receipt',
                                   'rollback-intent', 'rollback-unlink', 'rollback-complete'), 1):
        interrupted = fixture.root / (phase + '.json')
        interrupted.write_text(json.dumps(json.loads(source.read_text()), indent=index))
        identity = hashlib.sha256(interrupted.read_bytes()).hexdigest()
        if phase.startswith('rollback'):
            fixture.call('migrate', source=str(interrupted), apply=True)
            fixture.call('migrate', source=str(interrupted), rollback=identity,
                         migration_phase=phase, expected=86)
            recovered = fixture.call('migrate', source=str(interrupted), rollback=identity)
            assert recovered['state'] == 'rolled_back'
            assert not (fixture.root/'repo'/'.git'/'kctx-knowledge'/'migration-candidates'/(identity+'.json')).exists()
        else:
            fixture.call('migrate', source=str(interrupted), apply=True,
                         migration_phase=phase, expected=86)
            recovered = fixture.call('migrate', source=str(interrupted), apply=True)
            staged = fixture.root/'repo'/'.git'/'kctx-knowledge'/'migration-candidates'/(identity+'.json')
            assert json.loads(staged.read_text()) == json.loads(source.read_text())['candidate']
            assert recovered['state'] == 'candidate'
        assert (fixture.root/'migration-crash-phase').read_text() == phase
        assert fixture.call('current')['release'] == fixture.first['release']
        crash_results.append({'phase': phase, 'recovered': recovered})
    return {'dry':dry,'apply':applied,'repeat':repeated,'rollback':rolled,'unknown':quarantined,'crash_recovery':crash_results}


def restore(q: Qualification,root: Path) -> dict[str,object]:
    fixture=Fixture(q,root/'knowledge-original')
    fixture.call('prepare',name='second')
    fixture.call('admit',name='second')
    latest=fixture.call('context',name='second')
    backup=root/'knowledge-backup'
    fixture.call('backup',destination=str(backup))
    state=(fixture.root/'fixture-state.json').read_bytes()
    original=fixture.original
    # Delete both copies of one current-only evidence object after the independent
    # backup exists. Older release remains readable; current retrieval must deny.
    decoded_state = json.loads(state)
    content_id = decoded_state['current_kb']['observations'][-1]['content']
    release = decoded_state['releases']['second']
    blob = q.run(['git', 'rev-parse', f'{release}:artifacts/{content_id}'], cwd=fixture.root/'repo').stdout.strip()
    retained = fixture.root/'repo'/'.git'/'kctx-knowledge'/'artifacts'/content_id
    native_blob = fixture.root/'repo'/'.git'/'objects'/blob[:2]/blob[2:]
    assert retained.is_file() and native_blob.is_file(), 'fixture expected independently retained loose Git evidence'
    retained.unlink()
    native_blob.unlink()
    missing_source = fixture.call('context', name='second', expected=None)
    assert missing_source.get('exit', 0) != 0
    assert fixture.call('context', name='initial') == original
    shutil.rmtree(fixture.root)
    destination=Fixture(q,root/'knowledge-restored',initial=False)
    (destination.root/'fixture-state.json').write_bytes(state)
    result=destination.call('restore',source=str(backup))
    assert destination.call('context',name='initial')==original
    assert destination.call('context',name='second')==latest
    # A distinct incomplete independent backup cannot be mistaken for a restore.
    incomplete=root/'knowledge-incomplete-backup'
    shutil.copytree(backup,incomplete)
    shutil.rmtree(incomplete/'dolt')
    denied=Fixture(q,root/'knowledge-denied',initial=False)
    (denied.root/'fixture-state.json').write_bytes(state)
    failure=denied.call('restore',source=str(incomplete),expected=None)
    assert failure.get('exit',0)!=0
    assert denied.call('current')['release'] is None
    return {'restore':result,'original_removed':True,'historical_identical':True,'current_identical':True,'missing_dolt_denied':True,'missing_current_evidence_denied':missing_source['exit']}


def legacy_migration(q: Qualification, root: Path) -> dict[str, object]:
    fixture = Fixture(q, root/'legacy-migration')
    source_repo = root/'legacy-code-source'
    git_repo(q, source_repo)
    (source_repo/'module.py').write_text('MAX_BATCH = 500\n')
    revision = commit(q, source_repo, 'retained source used by legacy citations')
    authored = root/'legacy-authored'
    authored.mkdir()
    for identity in ('service-one', 'service-two'):
        (authored/(identity+'.json')).write_text(json.dumps({
            'id':identity,'kind':'service','name':'Similar name','aliases':['shared-alias']}))
    (authored/'unsupported.json').write_text('{"schema_version":999,"id":"unknown","kind":"service","name":"Unknown"}')
    (authored/'duplicate.json').write_text('{"id":"service-dup","id":"service-other","kind":"service","name":"Duplicate key"}')
    note = ('---\nid: legacy-note\ncustom: preserve-me\n---\n\n# Historical note\n\n'
            f'Exact ⟦cite kind=code repo={source_repo} rev={revision} path=module.py L=1-1⟧\n'
            f'Unique ⟦cite kind=code repo={source_repo} rev={revision[:12]} path=module.py L=1-1⟧\n'
            'Ambiguous ⟦cite kind=record id=shared-alias⟧\n'
            f'Unavailable ⟦cite kind=code repo={source_repo} rev={"0"*40} path=module.py L=1-1⟧\n'
            '\n## Custom section\n\nUnicode λ, commas, quotes and original bytes remain authored.\n')
    (authored/'note.md').write_bytes(note.replace('\n','\r\n').encode())
    original = {str(p.relative_to(authored)):p.read_bytes() for p in authored.rglob('*') if p.is_file()}
    before = fixture.call('current')
    dry = fixture.call('migrate',source=str(authored))
    assert dry['historical_identity_inferred'] is False and dry['published'] is False
    assert all(dry['counts'][category] > 0 for category in ('exact','uniquely_resolvable','ambiguous','unavailable','malformed'))
    assert {str(p.relative_to(authored)):p.read_bytes() for p in authored.rglob('*') if p.is_file()} == original
    fixture.call('migrate',source=str(authored),apply=True,migration_phase='migration-candidate',expected=86)
    applied = fixture.call('migrate',source=str(authored),apply=True)
    repeated = fixture.call('migrate',source=str(authored),apply=True)
    assert applied == repeated and applied['counts'] == dry['counts']
    restored = root/'legacy-restored'
    restored_receipt = fixture.call('restore-migration',migration=applied['migration'],destination=str(restored))
    assert {str(p.relative_to(restored)):p.read_bytes() for p in restored.rglob('*') if p.is_file()} == original
    candidate = json.loads((fixture.root/'repo'/'.git'/'kctx-knowledge'/'migration-candidates'/(applied['migration']+'.json')).read_text())
    assert candidate['claims'] == [] and candidate['requires_structured_proposal'] is True
    assert {item['authored_id'] for item in applied['items'] if item['kind']=='asset' and item['disposition']=='exact'} == {'service-one','service-two'}
    rolled = fixture.call('migrate',source=str(authored),rollback=applied['migration'])
    assert rolled['state'] == 'rolled_back' and fixture.call('current') == before
    return {'counts':applied['counts'],'migration':applied['migration'],'restore':restored_receipt,
            'exact_bytes_preserved':True,'ids_preserved':True,'interrupted_candidate_recovered':True,
            'ambiguous_unavailable_malformed_quarantined':True,'admitted_claims':0}


def retained_selection(q: Qualification, root: Path) -> dict[str, object]:
    fixture=Fixture(q,root/'retained-selection')
    fixture.call('prepare',name='corrected',retract_initial=True)
    corrected_release=fixture.call('admit',name='corrected')
    corrected=fixture.call('context',name='corrected')
    assert corrected['records'][0]['assessment']['support']=='none'
    audit_before=fixture.call('audit')
    fixture.call('select',name='rollback',target='initial')
    rollback=fixture.call('admit',name='rollback')
    assert rollback['release'] not in (fixture.first['release'],corrected_release['release'])
    selected=fixture.call('context',name='rollback',now=111)
    assert len(selected['records'])==3 and selected['selection_omitted']==3
    assert selected['records'][0]['assessment']['support']=='none'
    assert all(record['assessment']['freshness']!='fresh' for record in selected['records'])
    assert selected['provenance']['corrections']==corrected['provenance']['corrections']
    assert fixture.call('context',name='initial')==fixture.original
    audit_rollback=fixture.call('audit')
    prior_ids={row['id'] for row in audit_before['admissions']}
    assert prior_ids < {row['id'] for row in audit_rollback['admissions']}
    fixture.call('select',name='rollforward',target='corrected')
    rollforward=fixture.call('admit',name='rollforward')
    current=fixture.call('context',name='rollforward',now=111)
    assert len(current['records'])==6 and current['selection_omitted']==0
    assert current['records'][0]['assessment']['support']=='none'
    assert current['provenance']['corrections']==corrected['provenance']['corrections']
    assert all(record['assessment']['freshness']!='fresh' for record in current['records'])
    audit_after=fixture.call('audit')
    assert len(audit_after['admissions'])==len(audit_before['admissions'])+2
    assert prior_ids <= {row['id'] for row in audit_after['admissions']}
    missing=fixture.call('select',name='missing',release='0'*40,expected=None)
    assert missing.get('exit',0)!=0 and fixture.call('current')['release']==rollforward['release']
    return {'rollback':rollback,'rollforward':rollforward,'preserved_admissions':sorted(prior_ids),
            'corrections_preserved':True,'retraction_not_resurrected':True,
            'evidence_age_not_renewed':True,'historical_replay_unchanged':True,'missing_snapshot_denied':True}


def qualify(q: Qualification,root: Path) -> None:
    q.report['knowledge_fixture']={'reviewed_source':str(ROOT/'tests'/'semantics'/'examples.py'),
                                    'capture_kinds':['source','pr','document']}
    for phase in ('prepared','after_candidate_commit','candidate','after_manifest_commit','manifest','after_publish_cas','published'):
        q.case('knowledge-crash-'+phase,['Q30','Q36','Q47','D35','D40','D41'],lambda phase=phase:crash(q,root,phase))
    q.case('knowledge-competing-and-tampered-input',['Q30','Q46','Q47','Q56','D37','D39','D42','D45'],lambda:competing(q,root))
    q.case('migration-dry-apply-repeat-rollback-unknown',['Q37','Q65','Q66','Q67','Q76','D13','D14','D18'],lambda:migration(q,root))
    q.case('legacy-accounted-migration',['Q65','Q66','Q67','D11','D12','D13','D14','D16','D18'],lambda:legacy_migration(q,root))
    q.case('knowledge-clean-independent-restore',['Q23','Q63','Q64','D17','D50','D51','D70'],lambda:restore(q,root))
    q.case('authorized-retained-rollback-rollforward',['Q23','Q76','D44','D59','D70'],lambda:retained_selection(q,root))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',type=Path,required=True)
    raise SystemExit(worker(parser.parse_args().worker))
