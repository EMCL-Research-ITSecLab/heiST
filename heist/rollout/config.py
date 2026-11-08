"""A deployment description contains paths and host identities, never credentials."""
from dataclasses import dataclass, field
import json
from pathlib import Path

from heist.remote import SSH


@dataclass(frozen=True)
class VM:
    role: str
    vmid: int
    name: str
    host: str
    user: str = 'root'

    def __post_init__(self):
        if self.role not in ('web', 'database', 'monitoring') or self.vmid < 100 or not self.name:
            raise ValueError('Invalid infrastructure VM identity')
        SSH(self.host, self.user)

    @property
    def ssh(self):
        return SSH(self.host, self.user)


@dataclass(frozen=True)
class Deployment:
    installation: str
    state_directory: str
    backup_directory: str
    backend_env: str
    api_url: str
    api_certificate: str
    web_root: str
    web_certificate: str
    vms: tuple[VM, ...]
    monitoring_checks: tuple[tuple[str, ...], ...]
    timeout: int = 600
    web_certificate_key: str | None = None
    web_hostname: str | None = None
    wazuh_container: str | None = None
    reviewed_source_files: dict[str,str] = field(default_factory=dict)
    reviewed_source_commit: str | None = None

    def __post_init__(self):
        from .source_overrides import validate
        validate(self.reviewed_source_files)
        import re
        if bool(self.reviewed_source_files)!=(self.reviewed_source_commit is not None) or (
                self.reviewed_source_commit is not None and re.fullmatch('[a-f0-9]{40}',self.reviewed_source_commit) is None):
            raise ValueError('Bind reviewed source files to their full original commit')
        for name in ('installation','state_directory','backup_directory','backend_env','api_certificate','web_root','web_certificate'):
            path=Path(getattr(self,name))
            if not path.is_absolute() or '..' in path.parts or '\n' in str(path):
                raise ValueError('Deployment paths must be absolute and normalized: '+name)
        if {vm.role for vm in self.vms}!={'web','database','monitoring'} or len(self.vms)!=3 or len({vm.vmid for vm in self.vms})!=3:
            raise ValueError('Declare three distinct infrastructure VMs')
        if self.vm('web').user!='root' or self.vm('database').user!='root':
            raise ValueError('Protocol v1 requires root SSH on web/database VMs')
        if not self.api_url.startswith('https://') or not 30<=self.timeout<=3600:
            raise ValueError('HTTPS API URL and bounded timeout required')
        if self.web_hostname is not None:
            from heist.security.tls import server_name
            server_name(self.web_hostname)
        if self.web_certificate_key is not None:
            path = Path(self.web_certificate_key)
            if not path.is_absolute() or '..' in path.parts or str(path) != self.web_certificate_key:
                raise ValueError('Declare a normalized web certificate key path')
        if self.wazuh_container is not None:
            import re
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', self.wazuh_container) is None:
                raise ValueError('Declare a valid monitoring container name')
        if not self.monitoring_checks:
            raise ValueError('Declare real monitoring health checks')

    def vm(self, role):
        return next(vm for vm in self.vms if vm.role==role)

    @classmethod
    def load(cls,path):
        data=json.loads(Path(path).read_text())
        if data.pop('schema',None)!=1:
            raise ValueError('Unknown deployment configuration schema')
        data['vms']=tuple(VM(**item) for item in data['vms'])
        data['monitoring_checks']=tuple(tuple(command) for command in data['monitoring_checks'])
        return cls(**data)
