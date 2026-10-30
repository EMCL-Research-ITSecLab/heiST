from dotenv import load_dotenv
import os
import threading
import datetime
import math
import subprocess
import time
import traceback
import fcntl

from backend.get_db_connection import get_db_connection
from heist.runtime import cleanup_is_complete
from backend.warmup_challenge import warmup_challenge as warmup_challenge_backend
from backend.teardown_challenge import teardown_challenge as teardown_challenge_backend

load_dotenv()

POOL_MANAGER_LOGGING_DIR = os.getenv("POOL_MANAGER_LOGGING_DIR", "/var/log/pool_manager")

MONITORING_VPN_INTERFACE = os.getenv("MONITORING_VPN_INTERFACE", "ctf_monitoring")
MONITORING_DMZ_INTERFACE = os.getenv("MONITORING_DMZ_INTERFACE", "dmz_monitoring")
MONITORING_VM_ID = int(os.getenv("MONITORING_VM_ID", "9000"))
WAZUH_NETWORK_DEVICE = os.getenv("WAZUH_NETWORK_DEVICE", "vrtmon")

CLEANUP_COMPLETE_FILE_PATH = "/var/lock/cleanup_complete.lock"

def system_is_ready_for_warmup():
    """
    Check if the monitoring is sufficiently set up and the cleanup process is complete
    """
    print("[CHECK] Verifying monitoring readiness")

    try:
        print(f"[CHECK] Checking network device: {WAZUH_NETWORK_DEVICE}")
        result = subprocess.run(
            ["ip", "link", "show", WAZUH_NETWORK_DEVICE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            print(f"[CHECK][FAIL] Network device missing: {result.stderr.strip()}")
            return False

        print(f"[CHECK] Checking VM status: {MONITORING_VM_ID}")
        result = subprocess.run(
            ["qm", "status", str(MONITORING_VM_ID)],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"[CHECK][FAIL] VM status command failed: {result.stderr.strip()}")
            return False

        if "status: running" not in result.stdout:
            print(f"[CHECK][WAIT] VM not running yet: {result.stdout.strip()}")
            return False

    except Exception as e:
        print("[CHECK][ERROR] Exception while checking monitoring readiness")
        traceback.print_exc()
        return False

    print("[CHECK][OK] Monitoring is ready")

    return cleanup_is_complete(CLEANUP_COMPLETE_FILE_PATH)


class PoolManager:
    """
    PoolManager class to manage the hot pool of challenges.
    """

    def __init__(self, minimal_pool_size=1, maximal_pool_size=10, check_interval_seconds=10):
        print("[POOL] Initializing PoolManager")

        self.running_warmups = {}     # thread_id -> challenge_template_id
        self.running_teardowns = {}   # thread_id -> challenge_template_id

        self.minimal_pool_size = minimal_pool_size
        self.maximal_pool_size = maximal_pool_size
        self.check_interval_seconds = check_interval_seconds
        self.pool_maintenance_db_conn = get_db_connection()
        self.expired_challenge_teardown_db_conn = get_db_connection()

        print(f"[POOL] min={minimal_pool_size} max={maximal_pool_size} interval={check_interval_seconds}s")

    def start(self):
        """
        Start the pool manager loop in a separate thread.
        """
        print("[POOL] Starting PoolManager")

        self.cleanup_leftover_from_crashed_processes()

        threading.Thread(
            target=self.pool_manager_loop,
            daemon=True,
            name="pool-manager-loop"
        ).start()

    def pool_manager_loop(self):
        """
        Main loop of the pool manager
        """
        print("[LOOP] Pool manager loop started")

        while True:
            try:
                print("[LOOP] Running maintenance cycle")

                threads = [
                    threading.Thread(
                        target=self.check_and_maintain_pool,
                        daemon=True,
                        name="check-and-maintain"
                    ),
                    threading.Thread(
                        target=self.teardown_expired_challenges,
                        daemon=True,
                        name="teardown-expired"
                    )
                ]

                for t in threads:
                    print(f"[LOOP] Starting thread: {t.name}")
                    t.start()

                for t in threads:
                    t.join()
                    print(f"[LOOP] Thread finished: {t.name}")

            except Exception:
                print("[LOOP][ERROR] Exception in pool manager loop")
                traceback.print_exc()
            finally:
                print(f"[LOOP] Sleeping {self.check_interval_seconds}s")
                time.sleep(self.check_interval_seconds)

    def check_and_maintain_pool(self):
        """
        Check the current pool sizes and maintain the hot pool.
        """
        print("[POOL] Checking and maintaining pool")

        with self.pool_maintenance_db_conn.cursor() as cursor:
            cursor.execute("SELECT id FROM challenge_templates WHERE ready_to_launch = TRUE")
            challenge_template_ids = [row[0] for row in cursor.fetchall()]

        print(f"[POOL] Found {len(challenge_template_ids)} active challenge templates")

        for challenge_template_id in challenge_template_ids:
            print(f"[POOL] Evaluating template {challenge_template_id}")

            current_pool_size = self.get_current_pool_size(challenge_template_id)
            target_pool_size = self.get_target_pool_size(challenge_template_id)

            target_pool_size = max(self.minimal_pool_size, target_pool_size)
            target_pool_size = min(self.maximal_pool_size, target_pool_size)

            running_warmups_count = self.get_current_provisioning_for_pool_count(challenge_template_id)
            total_effective_pool_size = current_pool_size + running_warmups_count

            print(
                f"[POOL] Template={challenge_template_id} "
                f"current={current_pool_size} "
                f"running_warmups={running_warmups_count} "
                f"target={target_pool_size}"
            )

            if total_effective_pool_size < target_pool_size:
                warmups_needed = target_pool_size - total_effective_pool_size
                print(f"[POOL] Scheduling {warmups_needed} warmups")

                for _ in range(warmups_needed):
                    threading.Thread(
                        target=self.managed_warmup,
                        args=(challenge_template_id,),
                        daemon=True
                    ).start()

            elif current_pool_size > target_pool_size:
                teardowns_needed = current_pool_size - target_pool_size
                print(f"[POOL] Scheduling {teardowns_needed} teardowns")

                with self.pool_maintenance_db_conn.cursor() as cursor:
                    cursor.execute("""
                        WITH candidates AS (
                            SELECT id
                            FROM challenges
                            WHERE challenge_template_id = %s
                            AND lifecycle_state = 'READY'
                            AND pre_assigned_user_id IS NULL
                            LIMIT %s
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE challenges
                        SET lifecycle_state = 'TERMINATING'
                        WHERE id IN (SELECT id FROM candidates)
                        RETURNING id
                    """, (challenge_template_id, teardowns_needed))

                    challenge_instance_ids = [row[0] for row in cursor.fetchall()]

                print(f"[POOL] Selected instances for teardown: {challenge_instance_ids}")

                for cid in challenge_instance_ids:
                    threading.Thread(
                        target=self.managed_teardown,
                        args=(challenge_template_id, cid),
                        daemon=True
                    ).start()

    def managed_teardown(self, challenge_template_id, challenge_instance_id):
        thread_id = threading.current_thread().ident
        print(f"[TEARDOWN][START] thread={thread_id} instance={challenge_instance_id}")

        self.running_teardowns[thread_id] = challenge_template_id

        try:
            teardown_challenge_backend(challenge_instance_id)
            print(f"[TEARDOWN][DONE] instance={challenge_instance_id}")
        except Exception:
            print(f"[TEARDOWN][ERROR] instance={challenge_instance_id}")
            traceback.print_exc()
        finally:
            self.running_teardowns.pop(thread_id, None)

            print(f"[TEARDOWN][CLEANUP] thread={thread_id}")

    def managed_warmup(self, challenge_template_id):
        thread_id = threading.current_thread().ident
        print(f"[WARMUP][START] thread={thread_id} template={challenge_template_id}")

        self.running_warmups[thread_id] = challenge_template_id

        try:
            warmup_challenge_backend(
                None,
                challenge_template_id,
                MONITORING_VPN_INTERFACE,
                MONITORING_DMZ_INTERFACE
            )
            print(f"[WARMUP][DONE] template={challenge_template_id}")
        except Exception:
            print(f"[WARMUP][ERROR] template={challenge_template_id}")
            traceback.print_exc()
        finally:
            self.running_warmups.pop(thread_id, None)
            print(f"[WARMUP][CLEANUP] thread={thread_id}")

    def get_current_provisioning_for_pool_count(self, challenge_template_id):
        with self.pool_maintenance_db_conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM challenges
                WHERE challenge_template_id = %s
                AND lifecycle_state = 'PROVISIONING'
                AND pre_assigned_user_id IS NULL
            """, (challenge_template_id,))
            count = cursor.fetchone()[0]

        print(f"[POOL] Current provisioning count for {challenge_template_id}: {count}")
        return count

    def get_current_pool_size(self, challenge_template_id):
        with self.pool_maintenance_db_conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM challenges
                WHERE challenge_template_id = %s
                  AND lifecycle_state = 'READY'
                  AND pre_assigned_user_id IS NULL
            """, (challenge_template_id,))
            size = cursor.fetchone()[0]

        print(f"[POOL] Current pool size for {challenge_template_id}: {size}")
        return size

    def get_target_pool_size(self, challenge_template_id):
        current_time = datetime.datetime.now()
        print(f"[POOL] Calculating target pool size for {challenge_template_id} at {current_time}")

        with self.pool_maintenance_db_conn.cursor() as cursor:
            cursor.execute("""
                SELECT effective_time, size
                FROM pool_sizes
                WHERE challenge_template_id = %s
                  AND effective_time > %s
                ORDER BY effective_time ASC
                LIMIT 1
            """, (challenge_template_id, current_time))
            future = cursor.fetchone()

            cursor.execute("""
                SELECT effective_time, size
                FROM pool_sizes
                WHERE challenge_template_id = %s
                  AND effective_time <= %s
                ORDER BY effective_time DESC
                LIMIT 1
            """, (challenge_template_id, current_time))
            past = cursor.fetchone()

        print(f"[POOL] Future pool size rule: {future}", flush=True)
        print(f"[POOL] Past pool size rule: {past}", flush=True)

        if not past and not future:
            print("[POOL] No pool size rules found")
            return 0

        if not past:
            print(f"[POOL] Using future size={future[1]}")
            return future[1]

        if not future:
            print(f"[POOL] Using past size={past[1]}")
            return past[1]

        total = (future[0] - past[0]).total_seconds()
        elapsed = (current_time - past[0]).total_seconds()
        ratio = elapsed / total if total > 0 else 0

        interpolated = past[1] + (future[1] - past[1]) * ratio
        result = math.ceil(interpolated)

        print(f"[POOL] Interpolated target size={result}")
        return result

    def cleanup_leftover_from_crashed_processes(self):
        print("[CLEANUP] Checking for orphaned challenges")

        cleanup_db_conn = get_db_connection()
        ids = []
        with cleanup_db_conn.cursor() as cursor:
            cursor.execute("""
                UPDATE challenges
                SET lifecycle_state = 'TERMINATING'
                WHERE lifecycle_state IN ('PROVISIONING', 'TERMINATING')
                RETURNING id
            """)
            ids = [row[0] for row in cursor.fetchall()]

        print(f"[CLEANUP] Found {len(ids)} orphaned challenges")

        for cid in ids:
            print(f"[CLEANUP] Scheduling teardown for orphaned instance {cid}")
            threading.Thread(
                target=teardown_challenge_backend,
                args=(cid,),
                daemon=True
            ).start()

    def teardown_expired_challenges(self):
        print("[EXPIRED] Checking for expired challenges")

        with self.expired_challenge_teardown_db_conn.cursor() as cursor:
            cursor.execute("""
                WITH expired AS (
                    SELECT id
                    FROM challenges
                    WHERE lifecycle_state = 'EXPIRED'
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE challenges
                SET lifecycle_state = 'TERMINATING'
                WHERE id IN (SELECT id FROM expired)
                RETURNING id
            """)
            ids = [row[0] for row in cursor.fetchall()]

        print(f"[EXPIRED] Found {len(ids)} expired challenges")

        for cid in ids:
            print(f"[EXPIRED] Scheduling teardown for {cid}")
            threading.Thread(
                target=teardown_challenge_backend,
                args=(cid,),
                daemon=True
            ).start()


if __name__ == "__main__":
    os.makedirs(POOL_MANAGER_LOGGING_DIR, exist_ok=True)
    # Initial wait to allow cleanup process to remove old flag
    time.sleep(10)

    while not system_is_ready_for_warmup():
        print("[MAIN] Waiting for monitoring machine to be ready...")
        time.sleep(10)

    print("[MAIN] Monitoring machine ready, starting PoolManager")

    pool_manager = PoolManager(minimal_pool_size=1, maximal_pool_size=10, check_interval_seconds=5)
    pool_manager.start()

    print("[MAIN] PoolManager started, entering idle loop")
    threading.Event().wait()
