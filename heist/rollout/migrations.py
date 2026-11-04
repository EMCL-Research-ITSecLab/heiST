"""Versioned, checksum-bound migrations executed under a database transaction lock."""
from contextlib import closing
from .manifest import blob


def migrate(settings, plan, *, web_role=None, web_password=None):
    if plan.schema == 3:
        from .browser_role import validate
        validate(web_role,web_password)
    elif web_role is not None or web_password is not None:
        raise ValueError('Browser role provisioning requires the browser-runtime release protocol')
    with closing(settings.connect()) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(1801801801)')
                if plan.schema == 3:
                    from .browser_role import create
                    create(cursor,web_role,web_password)
                cursor.execute('''CREATE TABLE IF NOT EXISTS public.heist_schema_migrations (
                    id text PRIMARY KEY, sha256 text NOT NULL, release_commit text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now())''')
                for migration in plan.migrations:
                    cursor.execute('SELECT sha256 FROM public.heist_schema_migrations WHERE id=%s',(migration.identifier,))
                    previous=cursor.fetchone()
                    if previous:
                        if previous[0]!=migration.sha256:
                            raise RuntimeError('An applied migration checksum changed: '+migration.identifier)
                        continue
                    cursor.execute(blob(plan.installation,plan.target,migration.path).decode())
                    cursor.execute('INSERT INTO public.heist_schema_migrations(id,sha256,release_commit) VALUES(%s,%s,%s)',
                        (migration.identifier,migration.sha256,plan.target))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
