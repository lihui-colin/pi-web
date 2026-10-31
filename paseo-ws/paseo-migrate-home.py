#!/usr/bin/env python3
"""Move the legacy daemon home during an explicitly requested maintenance window."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


# These files belong to the deployment, not the official daemon home.
DEPLOYMENT = {
    '.paseo', 'paseo.conf', 'tls', 'nginx', 'nginx.conf', 'connection-check.html',
    'service.lock', 'paseo.pid', 'home-migration.json', 'home-migration.log',
    'home-migration.config-backup', 'home-migration.tmp',
}


class Migration:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.data = self.root / 'data'
        self.home = self.data / '.paseo'
        self.cli = self.root / 'runtime/bin/paseo'
        self.manager = self.root / 'paseo_web_run.sh'
        self.journal = self.data / 'home-migration.json'

    @contextlib.contextmanager
    def lock(self):
        if self.data.is_symlink() or not self.data.is_dir():
            raise RuntimeError('data 必须是实际存在的目录。')
        fd = os.open(self.data / 'service.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('已有服务管理或维护进程持锁，请稍后重试。') from error
            if fd != 9:
                os.dup2(fd, 9)
                os.close(fd)
            fd = 9
            os.set_inheritable(fd, True)
            yield
        finally:
            os.close(fd)

    def query(self, home, *args):
        result = subprocess.run(
            [str(self.cli), '--home', str(home), *args, '--json'],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, 'PASEO_HOME': str(home)},
        )
        if result.returncode:
            raise RuntimeError(f'无法查询 {home} 的 {args[0]} 状态，停止迁移。')
        return json.loads(result.stdout)

    def preflight(self):
        if not (self.data / 'config.json').is_file() or (self.data / 'config.json').is_symlink():
            raise RuntimeError('未找到独立的旧 config.json；无需迁移或需先人工检查。')
        if self.home.is_symlink() or (self.home.exists() and
                (not self.home.is_dir() or any(self.home.iterdir()))):
            raise RuntimeError('目标 data/.paseo 已有内容或是符号链接，拒绝覆盖。')
        state = self.query(self.data, 'daemon', 'status')
        if state.get('localDaemon') not in ('running', 'stopped'):
            raise RuntimeError('无法确认旧服务状态，停止迁移。')
        agents = []
        if state['localDaemon'] == 'running':
            agents = self.query(self.data, 'ls', '--all', '--global')
            self.require_idle(agents)
            # Even an apparently idle daemon must not stop the process hosting this command.
            ancestors = set()
            pid = os.getpid()
            while pid > 1:
                ancestors.add(pid)
                pid = int((Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[1])
            if ancestors.intersection({state.get('pid'), state.get('workerPid')}):
                raise RuntimeError('当前命令依赖 Paseo 服务，请从独立终端执行迁移。')
        return state, agents

    @staticmethod
    def require_idle(agents):
        if not isinstance(agents, list) or any(
                not isinstance(agent, dict) or not isinstance(agent.get('id'), str) or
                agent.get('status') not in ('idle', 'error', 'closed') for agent in agents):
            raise RuntimeError('存在运行中、初始化中或状态不明的会话，停止迁移；服务保持原状。')

    def lifecycle(self, action, home, mode='proxy'):
        env = {**os.environ, 'PASEO_MAINTENANCE_HOME': str(home)}
        args = ['bash', str(self.manager), action]
        if action == 'start':
            args.append('--proxy' if mode == 'proxy' else '--no-proxy')
        # Descriptor 9 carries the same service lock into the management script.
        subprocess.run(args, env=env, pass_fds=(9,), check=True, timeout=180)

    def record(self, phase, **values):
        state = json.loads(self.journal.read_text()) if self.journal.exists() else {}
        state.update(values, phase=phase, source=str(self.data), target=str(self.home), pid=os.getpid())
        state['recovery'] = (
            '先确认服务已停止，再按 moved 清单逆序将目标条目移回 source；'
            '从 home-migration.config-backup 恢复旧 config.json；'
            '重新执行迁移前检查，不要直接覆盖任一已有条目。'
        )
        temp = self.journal.with_suffix('.tmp')
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
        temp.chmod(0o600)
        temp.replace(self.journal)
        print(f'home migration: {phase}', flush=True)

    def migrate(self):
        state, agents = self.preflight()
        legacy_config = (self.data / 'config.json').read_bytes()
        listen = state.get('listen') if state['localDaemon'] == 'running' else json.loads(legacy_config).get('daemon', {}).get('listen')
        if not isinstance(listen, str):
            raise RuntimeError('无法确定旧监听模式，停止迁移。')
        mode = 'proxy' if listen == '127.0.0.1:25226' else 'direct'
        # Verify the configured direct listener before allowing a restart.
        expected = subprocess.check_output(
            ['node', str(self.root / 'paseo-config.cjs'), 'endpoint', str(self.data), mode], text=True,
        ).splitlines()[0]
        if listen != expected:
            raise RuntimeError('访问配置与旧监听地址不匹配，请先核对配置。')
        original_ids = {agent['id'] for agent in agents}
        identity = {name: hashlib.sha256((self.data / name).read_bytes()).hexdigest()
                    for name in ('server-id', 'daemon-keypair.json') if (self.data / name).exists()}
        backup = self.data / 'home-migration.config-backup'
        backup.write_bytes(legacy_config)
        backup.chmod(0o600)
        moved = []
        stopped = False
        start_attempted = False
        self.record('prepared', moved=moved, mode=mode, original_ids=sorted(original_ids), identity=identity)
        try:
            stopped = True
            self.lifecycle('stop', self.data, mode)
            if self.query(self.data, 'daemon', 'status').get('localDaemon') != 'stopped':
                raise RuntimeError('未确认旧服务停止，拒绝移动数据。')
            self.record('stopped')
            self.home.mkdir(mode=0o700, exist_ok=True)
            self.home.chmod(0o700)
            for entry in sorted(self.data.iterdir()):
                if entry.name in DEPLOYMENT:
                    continue
                target = self.home / entry.name
                if target.exists() or target.is_symlink():
                    raise RuntimeError(f'目标条目冲突：{entry.name}')
                self.record('moving', next=entry.name, moved=moved)
                entry.rename(target)
                moved.append(entry.name)
                self.record('moving', next=None, moved=moved)
            for name, digest in identity.items():
                if hashlib.sha256((self.home / name).read_bytes()).hexdigest() != digest:
                    raise RuntimeError(f'身份文件校验失败：{name}')
            self.record('starting')
            start_attempted = True
            self.lifecycle('start', self.home, mode)
            current = self.query(self.home, 'daemon', 'status')
            if current.get('localDaemon') != 'running' or current.get('home') != str(self.home) or current.get('listen') != listen:
                raise RuntimeError('新数据目录的运行状态或监听地址不正确。')
            current_agents = self.query(self.home, 'ls', '--all', '--global')
            if not isinstance(current_agents, list) or not original_ids.issubset({agent['id'] for agent in current_agents}):
                raise RuntimeError('迁移后的会话列表不完整。')
            for name, digest in identity.items():
                if hashlib.sha256((self.home / name).read_bytes()).hexdigest() != digest:
                    raise RuntimeError(f'启动后身份文件发生变化：{name}')
            self.record('complete')
        except Exception as error:
            self.record('rolling-back', error=str(error), moved=moved)
            try:
                if start_attempted:
                    self.lifecycle('stop', self.home, mode)
                    if self.query(self.home, 'daemon', 'status').get('localDaemon') != 'stopped':
                        raise RuntimeError('新实例停止状态不明，保留数据等待人工恢复。')
                for name in reversed(moved):
                    target = self.data / name
                    if target.exists() or target.is_symlink():
                        raise RuntimeError(f'回滚源条目冲突：{name}')
                    (self.home / name).rename(target)
                (self.data / 'config.json').write_bytes(legacy_config)
                if self.home.exists() and not any(self.home.iterdir()):
                    self.home.rmdir()
                if stopped and state['localDaemon'] == 'running':
                    self.lifecycle('start', self.data, mode)
                self.record('rolled-back', moved=[])
            except Exception as recovery_error:
                self.record('recovery-required', recovery_error=str(recovery_error))
                raise RuntimeError('自动恢复未完成，请查看 data/home-migration.json 和日志；不要覆盖数据。') from recovery_error
            raise


def main():
    action, root, *extra = sys.argv[1:]
    migration = Migration(root)
    if action == 'launch':
        with migration.lock():
            migration.preflight()
            log = migration.data / 'home-migration.log'
            with log.open('a') as output:
                log.chmod(0o600)
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), 'worker', str(migration.root), str(os.getpid())],
                    start_new_session=True, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                )
        print(f'已启动独立迁移进程，查看进度：{log}')
    elif action == 'worker':
        # The launcher exits before maintenance; the worker must be reparented first.
        parent = int(extra[0])
        deadline = time.monotonic() + 10
        while os.getppid() == parent and time.monotonic() < deadline:
            time.sleep(0.05)
        if os.getppid() == parent:
            raise RuntimeError('维护进程未脱离启动会话，停止迁移。')
        def interrupted(signum, frame):
            raise RuntimeError(f'维护进程收到信号 {signum}，尝试恢复。')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        with migration.lock():
            migration.migrate()
    else:
        raise RuntimeError('未知迁移操作。')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'迁移未完成：{error}', file=sys.stderr)
        sys.exit(1)
