#!/usr/bin/env python3
"""Qualify native local transports; enterprise writes require explicit scratch approval.

Run in compose: python scripts/qualify_remote.py --output /work/kctx/reports/remote
An enterprise config is never inferred from origin or replaced with a local URL.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from qualification_common import Qualification, commit, dolt_commit, dolt_init, git_repo


def query(q: Qualification, path: Path, revision: str) -> list[dict[str, object]]:
    result = q.run(['dolt', 'sql', '-r', 'json', '-q',
                    f"SELECT * FROM qualification AS OF '{revision}' ORDER BY id"], cwd=path)
    return json.loads(result.stdout).get('rows', [])


def exercise(q: Qualification, root: Path, git_url: str, dolt_url: str, prefix: str) -> dict[str, object]:
    a, b = root / 'a', root / 'b'
    da, db = root / 'dolt-a', root / 'dolt-b'
    git_repo(q, a)
    (a / 'evidence.txt').write_text('retained operational evidence v1\n')
    first_git = commit(q, a, 'qualification historical evidence')
    q.run(['git', 'remote', 'add', 'origin', git_url], cwd=a)
    q.run(['git', 'push', 'origin', f'HEAD:refs/heads/{prefix}-a'], cwd=a)
    q.run(['git', 'clone', '--branch', prefix + '-a', git_url, str(b)])
    assert (b / 'evidence.txt').read_text() == 'retained operational evidence v1\n'
    q.run(['git', 'config', 'user.name', 'qualification'], cwd=b)
    q.run(['git', 'config', 'user.email', 'qualification@invalid'], cwd=b)
    dolt_init(q, da)
    q.run(['dolt', 'sql', '-q', 'CREATE TABLE qualification (id INT PRIMARY KEY, evidence TEXT); INSERT INTO qualification VALUES (1, \'historical\')'], cwd=da)
    first_dolt = dolt_commit(q, da, 'qualification historical evidence')
    q.run(['dolt', 'branch', prefix + '-a'], cwd=da)
    q.run(['dolt', 'checkout', prefix + '-a'], cwd=da)
    q.run(['dolt', 'remote', 'add', 'origin', dolt_url], cwd=da)
    q.run(['dolt', 'push', '-u', 'origin', prefix + '-a'], cwd=da)
    q.run(['dolt', 'clone', '--branch', prefix + '-a', dolt_url, str(db)])
    assert query(q, db, first_dolt) == [{'id': 1, 'evidence': 'historical'}]
    q.run(['dolt', 'checkout', '-b', prefix + '-b'], cwd=db)
    q.run(['dolt', 'sql', '-q', "INSERT INTO qualification VALUES (2, 'client-b')"], cwd=db)
    b_dolt = dolt_commit(q, db, 'independent b')
    q.run(['dolt', 'sql', '-q', "INSERT INTO qualification VALUES (3, 'client-a')"], cwd=da)
    a_dolt = dolt_commit(q, da, 'independent a')
    # Concurrent native processes, separate checkouts; no monkeypatched transport.
    with ExitStack() as captures:
        processes = []
        for path, branch in ((da, prefix + '-a'), (db, prefix + '-b')):
            argv = ['dolt', 'push', '-u', 'origin', branch]
            processes.append(captures.enter_context(
                q.capture(argv, cwd=path, role=f'native-push-{branch}')))
        for process, _stdout, stderr in processes:
            process.wait(timeout=120)
            stderr.seek(0)
            assert process.returncode == 0, stderr.read()
    fresh = root / 'fresh'
    q.run(['dolt', 'clone', '--branch', prefix + '-a', dolt_url, str(fresh)])
    q.run(['dolt', 'fetch', 'origin'], cwd=fresh)
    assert query(q, fresh, a_dolt)[-1]['evidence'] == 'client-a'
    assert query(q, fresh, b_dolt)[-1]['evidence'] == 'client-b'
    assert query(q, fresh, first_dolt) == [{'id': 1, 'evidence': 'historical'}]
    # SQL working-set changes are not native historical commits.
    q.run(['dolt', 'sql', '-q', "INSERT INTO qualification VALUES (4, 'uncommitted')"], cwd=da)
    assert len(query(q, da, a_dolt)) == 2
    # Dirty Git work survives fetch, and a stale update to an existing ref fails.
    (b / 'evidence.txt').write_text('dirty independent client\n')
    q.run(['git', 'fetch', 'origin'], cwd=b)
    assert (b / 'evidence.txt').read_text() == 'dirty independent client\n'
    (a / 'evidence.txt').write_text('current evidence\n')
    current_git = commit(q, a, 'advance published fixture')
    q.run(['git', 'push', 'origin', f'HEAD:refs/heads/{prefix}-a'], cwd=a)
    rejected = q.run(['git', 'push', 'origin', f'{first_git}:refs/heads/{prefix}-a'], cwd=b, expected=None)
    assert rejected.returncode != 0
    historical = q.run(['git', 'show', f'{first_git}:evidence.txt'], cwd=b).stdout
    assert historical == 'retained operational evidence v1\n'
    return {'git_historical': first_git, 'git_current': current_git,
            'dolt_historical': first_dolt, 'dolt_a': a_dolt, 'dolt_b': b_dolt,
            'clients': [str(a), str(b), str(da), str(db)],
            'retention': 'native branch references; no claim about enterprise GC policy'}


def interrupted_dolt_push(q: Qualification, root: Path, remote: Path) -> dict[str, object]:
    client = root / 'local' / 'dolt-a'
    prior_result = q.run(['dolt', 'sql', '-r', 'json', '-q', "SELECT hashof('HEAD') AS h"], cwd=client)
    prior = json.loads(prior_result.stdout)['rows'][0]['h']
    q.run(['dolt', 'sql', '-q', 'ALTER TABLE qualification MODIFY evidence LONGTEXT'], cwd=client)
    payload = random.Random(40123).randbytes(8 * 1024 * 1024).hex()
    q.run(['dolt', 'sql'], cwd=client, stdin="INSERT INTO qualification VALUES (5, '" + payload + "')")
    current = dolt_commit(q, client, 'large interrupted candidate')
    argv = ['dolt', 'push', 'origin', 'kctx-qualification-local-a']
    process = subprocess.Popen(argv, cwd=client, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    time.sleep(.02)
    running = process.poll() is None
    if running:
        os.killpg(process.pid, signal.SIGKILL)
    stdout, stderr = process.communicate(timeout=30)
    q.commands.append({'argv': argv, 'returncode': process.returncode, 'stdout': stdout,
                       'stderr': stderr, 'interruption': 'SIGKILL native client 20ms after launch; transfer phase not asserted'})
    assert running, 'native push completed before interruption; no interruption evidence obtained'
    fresh = root / 'after-interruption'
    q.run(['dolt', 'clone', '--branch', 'kctx-qualification-local-a', remote.as_uri(), str(fresh)])
    head_result = q.run(['dolt', 'sql', '-r', 'json', '-q', "SELECT hashof('HEAD') AS h"], cwd=fresh)
    actual = json.loads(head_result.stdout)['rows'][0]['h']
    assert actual in (prior, current), 'remote reports an unrelated or partial publication identity'
    assert query(q, fresh, prior)[-1]['evidence'] == 'client-a'
    q.run(argv, cwd=client)
    q.run(['dolt', 'fetch', 'origin'], cwd=fresh)
    retained = q.run(['dolt', 'sql', '-r', 'json', '-q',
                     f"SELECT LENGTH(evidence) AS n, SHA2(evidence,256) AS digest FROM qualification AS OF '{current}' WHERE id=5"], cwd=fresh)
    expected_digest = hashlib.sha256(payload.encode()).hexdigest()
    assert json.loads(retained.stdout)['rows'][0] == {'n': len(payload), 'digest': expected_digest}
    return {'prior': prior, 'candidate': current, 'observed_before_retry': actual,
            'retried_after_independent_read': True, 'large_payload_bytes': len(payload), 'payload_sha256': expected_digest}


def interrupted_push(q: Qualification, root: Path) -> dict[str, object]:
    remote = root / 'interrupt.git'
    q.run(['git', 'init', '--bare', str(remote)])
    client = root / 'interrupt-client'
    git_repo(q, client)
    (client / 'value').write_text('old')
    old = commit(q, client, 'old')
    q.run(['git', 'push', str(remote), 'HEAD:refs/heads/main'], cwd=client)
    marker = root / 'receive-entered'
    hook = remote / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\nprintf entered > "' + str(marker) + '"\nsleep 30\n')
    hook.chmod(0o755)
    (client / 'value').write_text('new')
    new = commit(q, client, 'new')
    argv = ['git', 'push', str(remote), 'HEAD:refs/heads/main']
    process = subprocess.Popen(argv, cwd=client, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    deadline = time.monotonic() + 15
    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(.01)
    entered = marker.exists()
    os.killpg(process.pid, signal.SIGKILL)
    stdout, stderr = process.communicate(timeout=10)
    q.commands.append({'argv': argv, 'returncode': process.returncode, 'stdout': stdout,
                       'stderr': stderr, 'interruption': 'SIGKILL process group after real pre-receive hook entry'})
    assert entered, 'push never reached actual receive boundary'
    refs = q.run(['git', 'ls-remote', str(remote), 'refs/heads/main']).stdout
    assert refs.split()[0] == old
    hook.unlink()
    q.run(argv, cwd=client)
    assert q.run(['git', 'ls-remote', str(remote), 'refs/heads/main']).stdout.split()[0] == new
    return {'before': old, 'after_retry': new, 'prior_release_survived': True}


def enterprise(q: Qualification, root: Path, config_path: Path | None) -> None:
    if config_path is None:
        # Actual read-only HTTP/auth discovery; no guessed repository or writes.
        q.run(['getent', 'hosts', 'bbgithub.dev.bloomberg.com'], expected=None, timeout=20)
        gh = shutil.which('gh')
        if gh is not None:
            q.run([gh, 'auth', 'status', '--hostname', 'bbgithub.dev.bloomberg.com'], expected=None, timeout=30)
        else:
            q.report['enterprise_auth_probe'] = 'gh executable absent in this environment; authentication not established by this run'
        q.run(['curl', '--head', '--silent', '--show-error', '--max-time', '20',
               'https://bbgithub.dev.bloomberg.com/'], expected=None, timeout=25)
        origin = q.run(['git', 'remote', 'get-url', 'origin'], expected=None)
        if origin.returncode == 0:
            try:
                q.run(['git', 'ls-remote', origin.stdout.strip()], expected=None, timeout=30)
            except subprocess.TimeoutExpired:
                pass  # The real timeout is retained in commands, not classified as success.
        q.blocked('enterprise-scratch', ['Q61', 'Q62', 'D05', 'D06', 'D07', 'D08', 'D09', 'D10'],
                  'Missing --enterprise-config with independently approved scratch Git and Dolt endpoints, approval reference, isolated branch prefix, credentials, retention policy and policy-probe commands. Enterprise HTTP endpoint and configured origin were probed read-only; neither was substituted for an approved scratch repository.')
        return
    config = json.loads(config_path.read_text())
    required = {'schema_version', 'approved_scratch', 'approval_reference', 'git_url', 'dolt_url', 'branch_prefix', 'retention_policy', 'policy_probes'}
    assert set(config) == required and config['schema_version'] == 1 and config['approved_scratch'] is True
    assert config['approval_reference'] and config['retention_policy'] and config['policy_probes']
    prefix = config['branch_prefix']
    assert isinstance(prefix, str) and prefix.startswith('kctx-qualification-') and all(c.isalnum() or c == '-' for c in prefix)
    for key in ('git_url', 'dolt_url'):
        parsed = urlsplit(config[key])
        assert parsed.scheme not in ('', 'file') and not parsed.password and not parsed.query, 'real network URL without embedded credentials required'
    q.report['enterprise_approval'] = config
    q.case('enterprise-readonly-probe', ['Q61', 'D05'], lambda: q.run(['git', 'ls-remote', config['git_url']]).returncode)
    q.case('enterprise-independent-clients', ['Q61', 'D05', 'D07'], lambda: exercise(q, root / 'enterprise', config['git_url'], config['dolt_url'], prefix))
    for index, probe in enumerate(config['policy_probes']):
        def run_probe(probe: dict[str, object] = probe) -> dict[str, object]:
            assert set(probe) == {'name', 'argv', 'expected_exit', 'stdout_contains', 'scenarios'}
            argv = probe['argv']
            assert isinstance(argv, list) and all(isinstance(s, str) for s in argv)
            result = q.run(argv, expected=int(probe['expected_exit']), timeout=120)
            assert str(probe['stdout_contains']) in result.stdout
            return {'name': probe['name'], 'external_policy_probe': True}
        q.case(f'enterprise-policy-{index}', probe['scenarios'], run_probe)
    required_scenarios = {'Q62', 'D06', 'D08', 'D09', 'D10', 'D49'}
    supplied = {scenario for probe in config['policy_probes'] for scenario in probe['scenarios']}
    missing = sorted(required_scenarios - supplied)
    if missing:
        q.blocked('enterprise-interruption-retention', missing,
                  'Missing approved endpoint-specific policy/interruption/retention probes for these scenarios; local tests do not substitute.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--enterprise-config', type=Path)
    parser.add_argument('--local-only', action='store_true', help='Run local transport only; never qualifies G13 enterprise')
    args = parser.parse_args()
    q = Qualification('remote', args.output)
    q.case('prerequisites', [], q.prerequisites)
    if q.cases[-1]['status'] != 'passed':
        return q.finish()
    with tempfile.TemporaryDirectory(prefix='kctx-remote-') as directory:
        root = Path(directory)
        remote = root / 'git.git'
        q.run(['git', 'init', '--bare', str(remote)])
        dolt_remote = root / 'dolt-remote'
        dolt_remote.mkdir()
        q.case('local-independent-native-clients', ['Q61', 'Q62', 'D07', 'D28', 'D48'],
               lambda: exercise(q, root / 'local', str(remote), dolt_remote.as_uri(), 'kctx-qualification-local'))
        q.case('local-interrupted-push', ['Q62', 'D08', 'D52'], lambda: interrupted_push(q, root))
        q.case('local-interrupted-native-dolt-push', ['Q62', 'D08', 'D09'], lambda: interrupted_dolt_push(q, root, dolt_remote))
        if not args.local_only:
            q.case('enterprise-configuration', [], lambda: enterprise(q, root, args.enterprise_config))
        else:
            q.report['enterprise'] = 'not requested; local transport is not G13 enterprise qualification'
    return q.finish()


if __name__ == '__main__':
    raise SystemExit(main())
