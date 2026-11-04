"""Keep allocation history outside VM snapshots so rollback cannot recycle IDs."""
from contextlib import closing
import json
from pathlib import Path
import re

from heist.files import write_json

RESOURCES = ('user', 'machine', 'machine_template', 'network', 'challenge')


def validate(values):
    if not isinstance(values, dict) or any(
            not isinstance(name, str) or re.fullmatch('[a-z_][a-z0-9_]{0,62}', name) is None or
            type(value) is not int or not 0 < value < 2**63
            for name, value in values.items()):
        raise RuntimeError('Invalid persisted identifier allocation history')
    return values


def capture(settings):
    from psycopg2 import sql
    values = {}
    with closing(settings.connect()) as connection:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT sequencename, increment_by FROM pg_catalog.pg_sequences WHERE schemaname='public'")
            for name, increment in cursor.fetchall():
                if increment != 1:
                    raise RuntimeError('Unsupported sequence allocation policy')
                cursor.execute(sql.SQL('SELECT last_value FROM public.{}').format(sql.Identifier(name)))
                values[name] = cursor.fetchone()[0]
    return validate(values)


def preserve(settings, path):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('Identifier history must not be a symlink')
    previous = validate(json.loads(path.read_text())) if path.exists() else {}
    for name, value in capture(settings).items():
        previous[name] = max(previous.get(name, 0), value)
    write_json(path, previous)
    return previous


def reconcile(settings, values):
    """Advance a restored DB and disable legacy reclaimers with writers stopped.

    Sequence changes are deliberately monotonic even if another SQL statement
    fails. This safety repair changes allocation policy, not student/grade rows.
    """
    from psycopg2 import sql
    values = validate(values)
    with closing(settings.connect()) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(1801801801)')
                cursor.execute("SELECT sequencename FROM pg_catalog.pg_sequences WHERE schemaname='public'")
                present = {row[0] for row in cursor.fetchall()}
                for name, value in values.items():
                    if name in present:
                        cursor.execute(sql.SQL('SELECT last_value FROM public.{}').format(sql.Identifier(name)))
                        highest = max(value, cursor.fetchone()[0])
                        cursor.execute('SELECT pg_catalog.setval(%s::regclass,%s,true)', ('public.'+name, highest))
                for resource in RESOURCES:
                    table = resource+'s'
                    sequence = table+'_id_seq'
                    if sequence not in present:
                        raise RuntimeError('Restored database is missing a resource identifier sequence')
                    cursor.execute(sql.SQL('LOCK TABLE public.{} IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(table)))
                    cursor.execute(sql.SQL('SELECT GREATEST(COALESCE((SELECT max(id) FROM public.{}),0), COALESCE((SELECT max(id) FROM public.{}),0))').format(sql.Identifier(table),sql.Identifier(resource+'_id_reclaim')))
                    highest = cursor.fetchone()[0]
                    cursor.execute(sql.SQL('SELECT last_value FROM public.{}').format(sql.Identifier(sequence)))
                    cursor.execute('SELECT pg_catalog.setval(%s::regclass,%s,true)', ('public.'+sequence,max(highest,cursor.fetchone()[0])))
                    body = "SELECT nextval('public."+sequence+"'::regclass)"
                    cursor.execute(sql.SQL('CREATE OR REPLACE FUNCTION public.{}() RETURNS BIGINT LANGUAGE sql SET search_path=pg_catalog,public AS {}').format(sql.Identifier('allocate_'+resource+'_id'),sql.Literal(body)))
                    cursor.execute(sql.SQL('DROP TRIGGER IF EXISTS {} ON public.{}').format(sql.Identifier('trg_reclaim_'+resource+'_id'),sql.Identifier(table)))
                cursor.execute("SELECT pg_catalog.to_regclass('public.web_sessions')")
                if cursor.fetchone()[0] is not None:
                    cursor.execute('DELETE FROM public.web_sessions')
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
