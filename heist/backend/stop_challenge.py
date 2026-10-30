import subprocess
import os
from dotenv import find_dotenv
from heist.environment import load_backend_env as load_dotenv

from heist.backend.get_db_connection import db_connection_context

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
        user_static_ip, challenge_id = get_user_static_ip_and_challenge_id(user_id, db_conn)
        remove_user_iptables_rules(user_static_ip)
        mark_challenge_expired(challenge_id, db_conn)
        unassign_challenge_from_user(user_id, db_conn)


def get_user_static_ip_and_challenge_id(user_id, db_conn):
    """
    Get the running challenge ID for a user.
    """
    with db_conn.cursor() as cursor:
        cursor.execute("""
            SELECT vpn_static_ip, running_challenge
            FROM users
            WHERE id = %s
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
    result = subprocess.run(["sudo", "iptables", "-S"], capture_output=True, text=True)
    rules = result.stdout.splitlines()

    # Filter rules that contain the user's static IP
    rules_to_remove = [rule for rule in rules if user_static_ip in rule]

    # Remove each rule
    for rule in rules_to_remove:
        delete_rule = rule.replace("-A", "-D")  # Change -A to -D to delete the rule
        subprocess.run(["sudo", "iptables"] + delete_rule.split(), check=True, capture_output=True)


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
