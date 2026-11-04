"""Persistent temporary-address leases; imports never reset the pool on restart."""
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import sqlite3
import time

from heist.files import private_directory


class IPPoolManager:
    def __init__(self, directory=None, *, network='10.32.0.0/20'):
        self.directory=Path(directory) if directory else None
        self.network=ipaddress.ip_network(network)
        if self.network.version!=4 or not 4<=self.network.num_addresses<=4096:
            raise ValueError('Cloud-init pool must be a bounded IPv4 network')
        gateway=self.network.network_address+1
        self.addresses=tuple(str(address) for address in self.network.hosts() if address!=gateway)

    def state_directory(self):
        return self.directory or Path(os.environ.get('HEIST_CLOUD_INIT_STATE','/var/lib/heist/cloud-init'))

    @contextmanager
    def connection(self):
        directory=private_directory(self.state_directory())
        path=directory/'leases.sqlite3'
        if path.is_symlink():
            raise ValueError('Lease database must not be a symlink')
        connection=sqlite3.connect(path,timeout=5,isolation_level=None)
        path.chmod(0o600)
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS configuration(network TEXT PRIMARY KEY)')
            connection.execute('CREATE TABLE IF NOT EXISTS leases(vm_id INTEGER PRIMARY KEY, ip TEXT UNIQUE NOT NULL, allocated_at TEXT NOT NULL)')
            values=connection.execute('SELECT network FROM configuration').fetchall()
            if values and values!=[(str(self.network),)]:
                raise ValueError('Existing cloud-init leases use another network')
            connection.execute('INSERT OR IGNORE INTO configuration(network) VALUES(?)',(str(self.network),))
            connection.commit()
            yield connection
        finally:
            connection.close()

    def validate_vm(self,vm_id):
        if type(vm_id) is not int or not 0<vm_id<2**63:
            raise ValueError('A positive VM identifier is required')

    def allocate_ip(self,vm_id,timeout=300.0,reuse_existing=True):
        self.validate_vm(vm_id)
        if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0<=timeout<=3600:
            raise ValueError('Use a bounded lease wait')
        deadline=time.monotonic()+timeout
        while True:
            with self.connection() as connection:
                connection.execute('BEGIN IMMEDIATE')
                existing=connection.execute('SELECT ip FROM leases WHERE vm_id=?',(vm_id,)).fetchone()
                if existing:
                    if not reuse_existing:
                        raise ValueError('VM already has a lease; reconcile before replacing it')
                    connection.commit()
                    return existing[0]
                used={row[0] for row in connection.execute('SELECT ip FROM leases')}
                if not used.issubset(set(self.addresses)):
                    raise ValueError('Lease inventory contains an address outside this pool')
                available=next((address for address in self.addresses if address not in used),None)
                if available is not None:
                    connection.execute('INSERT INTO leases(vm_id,ip,allocated_at) VALUES(?,?,?)',(vm_id,available,datetime.now(timezone.utc).isoformat()))
                    connection.commit()
                    return available
                connection.rollback()
            if time.monotonic()>=deadline:
                return None
            time.sleep(min(.1,max(0,deadline-time.monotonic())))

    def release_ip(self,vm_id):
        """Caller must have confirmed NIC detachment or native VM absence."""
        self.validate_vm(vm_id)
        with self.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            removed=connection.execute('DELETE FROM leases WHERE vm_id=?',(vm_id,)).rowcount
            connection.commit()
            return bool(removed)

    def get_allocated_ip(self,vm_id):
        self.validate_vm(vm_id)
        with self.connection() as connection:
            row=connection.execute('SELECT ip FROM leases WHERE vm_id=?',(vm_id,)).fetchone()
            return row[0] if row else None

    def get_pool_status(self):
        with self.connection() as connection:
            leases=connection.execute('SELECT vm_id FROM leases ORDER BY vm_id').fetchall()
            return {'total_ips':len(self.addresses),'available_ips':len(self.addresses)-len(leases),
                    'allocated_ips':len(leases),'allocated_vms':[row[0] for row in leases]}

    def is_ip_allocated(self,ip):
        with self.connection() as connection:
            return connection.execute('SELECT 1 FROM leases WHERE ip=?',(str(ip),)).fetchone() is not None

    def cleanup(self):
        if self.get_pool_status()['allocated_ips']:
            raise RuntimeError('Outstanding leases require independent VM/NIC reconciliation; bulk reset is refused')


# Constructing the service performs no filesystem access or database connection.
ip_pool=IPPoolManager()
