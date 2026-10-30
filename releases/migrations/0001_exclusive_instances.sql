-- Stop launch/pool workers before migrating an existing installation.
-- Resolve existing shared instances manually; this migration never reassigns users.
LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (
        SELECT running_challenge FROM users WHERE running_challenge IS NOT NULL
        GROUP BY running_challenge HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Shared running instances exist; stop workers and resolve ownership before migration';
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS users_running_challenge_exclusive
    ON users (running_challenge) WHERE running_challenge IS NOT NULL;
