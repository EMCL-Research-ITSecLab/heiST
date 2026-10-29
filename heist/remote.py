"""OpenSSH transport with explicit host trust, bounded operations and shell quoting."""
from dataclasses import dataclass
import re
import shlex
import subprocess


@dataclass(frozen=True)
class SSH:
    host: str
    user: str = 'root'
    timeout: int = 3600

    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_:][A-Za-z0-9_.:-]*', self.host):
            raise ValueError('Invalid SSH hostname')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_-]*', self.user):
            raise ValueError('Invalid SSH username')
        if self.timeout <= 0:
            raise ValueError('SSH timeout must be positive')

    def run(self, arguments, *, stdin=None, stdout=subprocess.PIPE, input=None, timeout=None):
        command = ['ssh', '-T', '-o', 'ForwardAgent=no', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
                   '-o', 'ServerAliveCountMax=3', '-l', self.user, '--', self.host,
                   shlex.join([str(value) for value in arguments])]
        return subprocess.run(command, stdin=stdin, stdout=stdout, input=input,
                              stderr=subprocess.PIPE, check=True, timeout=timeout or self.timeout)
