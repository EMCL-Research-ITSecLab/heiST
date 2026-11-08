"""Versioned, checksum-bound migrations executed under a database transaction lock."""
from contextlib import closing
from .manifest import blob


def migrate(settings, plan, *, web_role=None, web_password=None, previous_web_role=None, legacy_web_role=None):
    if plan.schema == 3:
        from .browser_role import validate
        validate(web_role,web_password)
        if previous_web_role is not None:
            validate(previous_web_role,'a'*64)
        if legacy_web_role is not None:
            from .browser_role import validate_legacy
            validate_legacy(legacy_web_role)
            if previous_web_role is not None:
                raise ValueError('Declare either a legacy PHP role or a previous browser role')
    elif web_role is not None or web_password is not None or previous_web_role is not None or legacy_web_role is not None:
        raise ValueError('Browser role provisioning requires the browser-runtime release protocol')
    with closing(settings.connect()) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(1801801801)')
                if plan.schema == 3:
                    if legacy_web_role is not None:
                        from .browser_role import retire_legacy
                        retire_legacy(cursor,legacy_web_role)
                    from .browser_role import create
                    create(cursor,web_role,web_password)
                    if previous_web_role is not None:
                        from .browser_role import transfer_permissions
                        transfer_permissions(cursor,previous_web_role,web_role)
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
                if plan.schema == 3:
                    if previous_web_role is not None:
                        from .browser_role import retire_previous
                        retire_previous(cursor,previous_web_role)
                    cursor.execute("SELECT pg_catalog.to_regclass('public.web_sessions')")
                    if cursor.fetchone()[0] is not None:
                        cursor.execute('DELETE FROM public.web_sessions')
            connection.commit()
            if legacy_web_role is not None:
                # NOLOGIN is committed first, closing the race with new logins.
                # Existing PHP connections must also lose their old authority.
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename=%s AND pid<>pg_backend_pid()',
                                   (legacy_web_role,))
                connection.commit()
        except BaseException:
            connection.rollback()
            raise
