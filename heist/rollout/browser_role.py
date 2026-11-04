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
