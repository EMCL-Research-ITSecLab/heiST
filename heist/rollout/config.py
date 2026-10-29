"""A deployment description contains paths and host identities, never credentials."""
from dataclasses import asdict, dataclass
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

    def __post_init__(self):
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
