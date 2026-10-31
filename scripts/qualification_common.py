"""Real-process qualification evidence shared by the runnable harnesses."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_identity(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts
            and p.suffix in {'.py', '.json', '.jsonl', '.toml', '.sql'}}


def redacted(value: object) -> object:
    """Keep process evidence, but never retain recognizable credential material."""
    if isinstance(value, str):
        value = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', value)
        value = re.sub(r'(?i)(authorization:\s*bearer\s+|password[=:]\s*|token[=:]\s*)[^\s,;]+',
                       r'\1[REDACTED]', value)
        return re.sub(r'\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{12,}\b', '[REDACTED]', value)
    if isinstance(value, list):
        result = []
        secret_next = False
        for item in value:
            result.append('[REDACTED]' if secret_next else redacted(item))
            secret_next = isinstance(item, str) and item in ('--token', '--password', '--secret')
        return result
    if isinstance(value, dict):
        return {str(key): redacted(item) for key, item in value.items()}
    return value


class Qualification:
    def __init__(self, kind: str, output: Path) -> None:
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        previous = self.output / 'report.json'
        if previous.exists():
            history = self.output / 'attempts'
            history.mkdir(exist_ok=True)
            shutil.copy2(previous, history / f'{time.time_ns()}-{digest(previous)[:12]}.json')
        self.report: dict[str, object] = {
            'schema_version': 1, 'kind': kind, 'started_ns': time.time_ns(),
            'host': platform.platform(), 'commands': [], 'cases': [],
            'source_files': tree_identity(ROOT / 'src'),
            'harness_files': tree_identity(ROOT / 'scripts'),
            'fixture_files': tree_identity(ROOT / 'fixtures' / 'qualification'),
            'test_files': tree_identity(ROOT / 'tests'),
            'python_version': platform.python_version(),
            'execution_checkout': str(ROOT),
            'source_snapshot_manifest': os.environ.get('KCTX_QUALIFICATION_SOURCE_MANIFEST'),
            'gate_pass': False,
        }
        self.commands: list[dict[str, object]] = []
        self.cases: list[dict[str, object]] = []
        self.report['commands'] = self.commands
        self.report['cases'] = self.cases

    def run(self, argv: list[str], *, cwd: Path | None = None,
            env: dict[str, str] | None = None, expected: int | None = 0,
            timeout: float = 120, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        start = time.monotonic_ns()
        if Path(argv[0]).name == 'git' and cwd is None:
            # Compose's root user reads a user-owned bind mount. Trust only this
            # explicitly selected checkout for this command, never global paths.
            argv = [argv[0], '-c', f'safe.directory={ROOT}', *argv[1:]]
        entry: dict[str, object] = {'argv': argv, 'cwd': str(cwd or ROOT),
                                    'timeout_seconds': timeout}
        if '--worker' in argv:
            request_path = Path(argv[argv.index('--worker') + 1])
            entry['worker_request'] = json.loads(request_path.read_text())
            entry['worker_request_sha256'] = digest(request_path)
        if stdin is not None:
            entry['stdin_sha256'] = hashlib.sha256(stdin.encode('utf-8')).hexdigest()
            entry['stdin_bytes'] = len(stdin.encode('utf-8'))
        self.commands.append(entry)
        try:
            result = subprocess.run(argv, cwd=cwd or ROOT, env=env, input=stdin,
                                    text=True, capture_output=True, timeout=timeout)
            entry.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            if expected is not None and result.returncode != expected:
                raise AssertionError(f'command {argv[0]} exited {result.returncode}, expected {expected}: {result.stderr}')
            return result
        except subprocess.TimeoutExpired as exc:
            entry.update(returncode=None, interrupted='timeout; subprocess killed and waited',
                         stdout=str(exc.stdout or ''), stderr=str(exc.stderr or ''))
            raise
        finally:
            entry['duration_ns'] = time.monotonic_ns() - start
            self.save()

    def case(self, name: str, scenarios: list[str], action: Callable[[], object]) -> None:
        entry: dict[str, object] = {'name': name, 'scenarios': scenarios,
                                    'first_command': len(self.commands)}
        self.cases.append(entry)
        try:
            detail = action()
            entry.update(status='passed', evidence=detail)
        except Exception as exc:
            entry.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        finally:
            entry['last_command_exclusive'] = len(self.commands)
            self.save()

    def blocked(self, name: str, scenarios: list[str], reason: str) -> None:
        self.cases.append({'name': name, 'scenarios': scenarios, 'status': 'blocked', 'reason': reason})
        self.save()

    def prerequisites(self) -> None:
        for binary in ('git', 'dolt'):
            executable = shutil.which(binary)
            if executable is None:
                raise RuntimeError(f'missing required real executable: {binary}; run in compose verify')
            result = self.run([executable, '--version' if binary == 'git' else 'version'])
            self.report[binary] = {'path': executable, 'sha256': digest(Path(executable)),
                                   'version': result.stdout.strip()}
        self.run(['git', 'rev-parse', 'HEAD'])
        if self.report['kind'] != 'remote':
            self.report['python_dependencies'] = {
                package: version(package) for package in ('pydantic', 'structlog', 'cryptography', 'PyMySQL')
            }

    def save(self) -> None:
        temporary = self.output / 'report.json.tmp'
        temporary.write_text(json.dumps(redacted(self.report), indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.replace(temporary, self.output / 'report.json')

    def finish(self) -> int:
        self.report['finished_ns'] = time.time_ns()
        final_sources = tree_identity(ROOT / 'src')
        self.report['source_files_final'] = final_sources
        self.report['source_stable_during_run'] = final_sources == self.report['source_files']
        if final_sources != self.report['source_files']:
            self.blocked('source-revision-changed-during-run', [],
                         'Production source changed during qualification; results cannot qualify one immutable revision.')
        success = bool(self.cases) and all(c['status'] == 'passed' for c in self.cases)
        self.report['executed_cases_passed'] = success
        self.report['gate_pass'] = False  # A gate requires the parent-reviewed complete evidence matrix.
        self.save()
        print(json.dumps({'report': str(self.output / 'report.json'), 'executed_cases_passed': success}))
        return 0 if success else 1


def git_repo(q: Qualification, path: Path) -> None:
    path.mkdir(parents=True)
    q.run(['git', 'init', '-q', '--initial-branch=main', str(path)])
    q.run(['git', 'config', 'user.name', 'kctx qualification'], cwd=path)
    q.run(['git', 'config', 'user.email', 'qualification@invalid'], cwd=path)


def commit(q: Qualification, path: Path, message: str) -> str:
    q.run(['git', 'add', '-A'], cwd=path)
    q.run(['git', 'commit', '-qm', message], cwd=path)
    return q.run(['git', 'rev-parse', 'HEAD'], cwd=path).stdout.strip()


def dolt_init(q: Qualification, path: Path) -> None:
    path.mkdir(parents=True)
    q.run(['dolt', 'init', '--name', 'kctx qualification', '--email', 'qualification@invalid'], cwd=path)


def dolt_commit(q: Qualification, path: Path, message: str) -> str:
    q.run(['dolt', 'add', '-A'], cwd=path)
    q.run(['dolt', 'commit', '--author', 'kctx qualification <qualification@invalid>', '-m', message], cwd=path)
    result = q.run(['dolt', 'sql', '-r', 'json', '-q', "SELECT hashof('HEAD') AS h"], cwd=path)
    return str(json.loads(result.stdout)['rows'][0]['h'])
