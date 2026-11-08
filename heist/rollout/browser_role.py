"""Create the browser's restricted login inside the release SQL transaction."""
import base64
import hashlib
import hmac
import re
import secrets


def validate(name, password):
    if not isinstance(name,str) or re.fullmatch(r'heist_web_[a-z0-9_]{1,48}',name) is None:
        raise ValueError('Declare a dedicated browser database role')
    if not isinstance(password,str) or re.fullmatch(r'[A-Za-z0-9_-]{32,256}',password) is None:
        raise ValueError('Use a generated high-entropy browser database password')


def verifier(password):
    """Send a SCRAM verifier to PostgreSQL rather than a plaintext SQL password."""
    salt=secrets.token_bytes(16)
    salted=hashlib.pbkdf2_hmac('sha256',password.encode('ascii'),salt,4096)
    stored=hashlib.sha256(hmac.digest(salted,b'Client Key','sha256')).digest()
    server=hmac.digest(salted,b'Server Key','sha256')
    encode=lambda data:base64.b64encode(data).decode('ascii')
    return 'SCRAM-SHA-256$4096:'+encode(salt)+'$'+encode(stored)+':'+encode(server)


def create(cursor,name,password):
    from psycopg2 import sql
    validate(name,password)
    cursor.execute('SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s',(name,))
    if cursor.fetchone() is not None:
        raise RuntimeError('Browser role already exists; reconcile the release before reusing it')
    cursor.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 32 PASSWORD {}').format(sql.Identifier(name),sql.Literal(verifier(password))))
    cursor.execute('CREATE SCHEMA IF NOT EXISTS api')
    cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA api TO {}').format(sql.Identifier(name)))
    cursor.execute('SELECT current_database()')
    database=cursor.fetchone()[0]
    cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database),sql.Identifier(name)))
    cursor.execute("SELECT set_config('heist.web_api_role',%s,true)",(name,))


def transfer_permissions(cursor, previous, current):
    """Carry forward only explicit API function grants from the stopped web role.

    A later release may have no pending DDL. Its new login still needs the
    previous role's approved function grants, including existing exclusions.
    No memberships, ownership, table access or grant options are inherited.
    """
    from psycopg2 import sql
    validate(previous, 'a'*64)
    validate(current, 'a'*64)
    cursor.execute('''SELECT r.oid FROM pg_roles r WHERE r.rolname=%s AND r.rolcanlogin
        AND NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls)
        AND NOT EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid)
        AND NOT EXISTS(SELECT 1 FROM pg_database d WHERE d.datname=current_database() AND d.datdba=r.oid)
        AND NOT has_schema_privilege(r.oid,'api','CREATE')
        AND NOT has_schema_privilege(r.oid,'public','CREATE')''', (previous,))
    value=cursor.fetchone()
    if value is None:
        raise RuntimeError('Previous browser role is absent or privileged; reconcile before transferring grants')
    cursor.execute('''SELECT p.proname,pg_get_function_identity_arguments(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,
             LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
        WHERE n.nspname='api' AND a.grantee=%s AND a.privilege_type='EXECUTE' ''',(value[0],))
    for name, arguments in cursor.fetchall():
        cursor.execute(sql.SQL('GRANT EXECUTE ON FUNCTION api.{}({}) TO {}').format(
            sql.Identifier(name),sql.SQL(arguments),sql.Identifier(current)))


def retire_previous(cursor, previous):
    """Stop new logins with the old credential; VM recovery restores its old state."""
    from psycopg2 import sql
    validate(previous,'a'*64)
    cursor.execute(sql.SQL('ALTER ROLE {} NOLOGIN').format(sql.Identifier(previous)))


def validate_legacy(name):
    if (not isinstance(name,str) or re.fullmatch('[a-z_][a-z0-9_]{0,62}',name) is None
            or name=='postgres' or name.startswith(('pg_','heist_web_'))):
        raise ValueError('Declare the dedicated legacy PHP database role')


def inspect_legacy(cursor, name):
    """Refuse privileged/shared identities before entering maintenance."""
    validate_legacy(name)
    cursor.execute('''SELECT r.oid FROM pg_roles r WHERE r.rolname=%s AND r.rolcanlogin
        AND r.rolname<>current_user AND r.rolname<>session_user
        AND NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls)
        AND NOT EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid OR m.roleid=r.oid)
        AND NOT EXISTS(SELECT 1 FROM pg_database d WHERE d.datdba=r.oid)''',(name,))
    if cursor.fetchone() is None:
        raise RuntimeError('Legacy PHP role is absent, shared or privileged; review before retirement')


def retire_legacy(cursor, name):
    """Retire the distinct PHP login without changing function ownership."""
    from psycopg2 import sql
    inspect_legacy(cursor,name)
    cursor.execute(sql.SQL('ALTER ROLE {} NOLOGIN PASSWORD NULL').format(sql.Identifier(name)))
