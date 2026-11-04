import subprocess
import os
import ipaddress
import shlex
from dotenv import find_dotenv
from heist.environment import load_backend_env as load_dotenv

from heist.infrastructure.database import db_connection_context

load_dotenv(find_dotenv())

CHALLENGES_ROOT_SUBNET = os.getenv("CHALLENGES_ROOT_SUBNET", "10.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK = os.getenv("CHALLENGES_ROOT_SUBNET_MASK", "255.128.0.0")
CHALLENGES_ROOT_SUBNET_MASK_INT = sum(bin(int(x)).count('1') for x in CHALLENGES_ROOT_SUBNET_MASK.split('.'))
CHALLENGES_ROOT_SUBNET_CIDR = f"{CHALLENGES_ROOT_SUBNET}/{CHALLENGES_ROOT_SUBNET_MASK_INT}"


def stop_challenge(user_id):
    """
    Stop a challenge for a user.
    """

    with db_connection_context() as db_conn:
        db_conn.autocommit = False
        try:
            with db_conn.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '10s'")
            user_static_ip, challenge_id = get_user_static_ip_and_challenge_id(user_id, db_conn)
            if challenge_id is not None:
                remove_user_iptables_rules(user_static_ip)
                with db_conn.cursor() as cursor:
                    # Finish the trace before clearing the user's assignment.
                    cursor.execute("""
                        UPDATE user_network_trace trace SET stopped_at = CURRENT_TIMESTAMP
                        FROM users u WHERE u.id = %s AND trace.username = u.username
                          AND trace.stopped_at IS NULL AND trace.subnet IN
                              (SELECT subnet FROM networks WHERE challenge_id = %s)
                    """, (user_id, challenge_id))
                    cursor.execute("""
                        UPDATE completed_challenges attempt SET completed_at = CURRENT_TIMESTAMP
                        FROM challenges c WHERE c.id = %s AND attempt.user_id = %s
                          AND attempt.challenge_template_id = c.challenge_template_id
                          AND attempt.completed_at IS NULL
                    """, (challenge_id, user_id))
                mark_challenge_expired(challenge_id, db_conn)
                unassign_challenge_from_user(user_id, db_conn)
            db_conn.commit()
        except BaseException:
            db_conn.rollback()
            raise


def get_user_static_ip_and_challenge_id(user_id, db_conn):
    """
    Get the running challenge ID for a user.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("""
            SELECT vpn_static_ip, running_challenge
            FROM users
            WHERE id = %s FOR UPDATE
        """, (user_id,))

        result = cursor.fetchone()
        if not result:
            raise Exception(f"No running challenge found for user ID {user_id}")

        return result[0], result[1]


def mark_challenge_expired(challenge_id, db_conn):
    """
    Mark the challenge as expired in the database.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("""
            UPDATE challenges
            SET lifecycle_state = 'EXPIRED'
            WHERE id = %s
        """, (challenge_id,))


def remove_user_iptables_rules(user_static_ip):
    """
    Remove all iptables rules that contain the user's static IP.
    """
    # Get all iptables rules
    address = ipaddress.ip_address(user_static_ip)
    result = subprocess.run(["sudo", "iptables", "-S"], capture_output=True, text=True, check=True, timeout=15)
    rules = result.stdout.splitlines()

    # Filter rules that contain the user's static IP
    for rule in rules:
        arguments = shlex.split(rule)
        if not arguments or arguments[0] != '-A':
            continue
        matches = False
        for index, value in enumerate(arguments[:-1]):
            if value not in ('-s', '--source', '-d', '--destination') or (index > 0 and arguments[index-1] == '!'):
                continue
            network = ipaddress.ip_network(arguments[index+1], strict=False)
            if network.prefixlen == address.max_prefixlen and network.network_address == address:
                matches = True
        if matches:
            subprocess.run(['sudo', 'iptables', '-D', *arguments[1:]], check=True, capture_output=True, timeout=15)


def unassign_challenge_from_user(user_id, db_conn):
    """
    Unassign the challenge from the user in the database.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("""
            UPDATE users
            SET running_challenge = NULL
            WHERE id = %s
        """, (user_id,))
