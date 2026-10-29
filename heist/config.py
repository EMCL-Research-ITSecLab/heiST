"""Explicit configuration values; importing this module never reads .env files."""
from dataclasses import dataclass, field
import os
from typing import Mapping


@dataclass(frozen=True)
class DatabaseSettings:
    host: str = 'localhost'
    name: str = 'heist'
    user: str = 'postgres'
    password: str | None = field(default=None, repr=False)
    port: int = 5432
    connect_timeout: int = 5

    def __post_init__(self):
        if not self.host or not self.name or not self.user:
            raise ValueError('Database host, name and user must be nonempty')
        if not 1 <= self.port <= 65535 or not 1 <= self.connect_timeout <= 300:
            raise ValueError('Invalid database port or connection timeout')

    @classmethod
    def from_mapping(cls, values: Mapping[str, str | None] | None = None, *, prefix='DB_', timeout=5):
        values = os.environ if values is None else values
        return cls(host=values.get(prefix + 'HOST') or 'localhost',
                   name=values.get(prefix + 'NAME') or 'heist',
                   user=values.get(prefix + 'USER') or 'postgres',
                   password=values.get(prefix + 'PASSWORD'),
                   port=int(values.get(prefix + 'PORT') or 5432), connect_timeout=timeout)

    def connect(self, *, autocommit=False):
        import psycopg2
        connection = psycopg2.connect(host=self.host, dbname=self.name, user=self.user,
            password=self.password, port=self.port, connect_timeout=self.connect_timeout)
        try:
            connection.autocommit = autocommit
        except BaseException:
            connection.close()
            raise
        return connection
