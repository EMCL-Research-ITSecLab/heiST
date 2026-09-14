CREATE EXTENSION IF NOT EXISTS pgcrypto;


CREATE OR REPLACE FUNCTION generate_random_default_avatar()
RETURNS TEXT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN '/assets/avatars/avatar' || (FLOOR(1 + RANDOM() * 3))::BIGINT::TEXT || '.png';
END;
$$;



CREATE OR REPLACE FUNCTION assign_lowest_vpn_ip(user_id_param BIGINT)
RETURNS INET
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    selected_ip INET;
BEGIN
    WITH next_ip AS (
        SELECT vpn_static_ip
        FROM vpn_static_ips
        WHERE user_id IS NULL
        ORDER BY vpn_static_ip
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE vpn_static_ips
    SET user_id = user_id_param
    FROM next_ip
    WHERE vpn_static_ips.vpn_static_ip = next_ip.vpn_static_ip
    RETURNING vpn_static_ips.vpn_static_ip INTO selected_ip;

    RETURN selected_ip;
END;
$$;



CREATE OR REPLACE FUNCTION assign_challenge_subnet()
RETURNS INET
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    selected_subnet INET;
BEGIN
    WITH next_subnet AS (
        SELECT subnet
        FROM challenge_subnets
        WHERE available = TRUE
        ORDER BY subnet
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE challenge_subnets
    SET available = FALSE
    FROM next_subnet
    WHERE challenge_subnets.subnet = next_subnet.subnet
    RETURNING challenge_subnets.subnet INTO selected_subnet;

    RETURN selected_subnet;
END;
$$;



CREATE SEQUENCE users_id_seq
    START 1
    MINVALUE 1
    NO CYCLE;

CREATE TABLE user_id_reclaim (
    id BIGINT PRIMARY KEY
);

CREATE OR REPLACE FUNCTION allocate_user_id()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_id BIGINT;
BEGIN

    DELETE FROM user_id_reclaim
    WHERE id = (
        SELECT id FROM user_id_reclaim
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id INTO new_id;

    IF new_id IS NULL THEN
        new_id := nextval('users_id_seq');
    END IF;

    RETURN new_id::BIGINT;
END;
$$;

CREATE OR REPLACE FUNCTION reclaim_user_id()
RETURNS TRIGGER
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO user_id_reclaim (id) VALUES (OLD.id)
        ON CONFLICT DO NOTHING;
    RETURN OLD;
END;
$$;



CREATE SEQUENCE machines_id_seq
    START 100000001
    MINVALUE 100000001
    MAXVALUE 899999999
    NO CYCLE;

CREATE TABLE machine_id_reclaim (
    id BIGINT PRIMARY KEY
);

CREATE OR REPLACE FUNCTION allocate_machine_id()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_id BIGINT;
BEGIN
    DELETE FROM machine_id_reclaim
    WHERE id = (
        SELECT id FROM machine_id_reclaim
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id INTO new_id;

    IF new_id IS NULL THEN
        new_id := nextval('machines_id_seq');
    END IF;

    RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION reclaim_machine_id()
RETURNS TRIGGER
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO machine_id_reclaim (id) VALUES (OLD.id)
        ON CONFLICT DO NOTHING;
    RETURN OLD;
END;
$$;



CREATE SEQUENCE machine_templates_id_seq
    START 900000001
    MINVALUE 900000001
    MAXVALUE 999999999
    NO CYCLE;

CREATE TABLE machine_template_id_reclaim (
    id BIGINT PRIMARY KEY
);

CREATE OR REPLACE FUNCTION allocate_machine_template_id()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_id BIGINT;
BEGIN
    DELETE FROM machine_template_id_reclaim
    WHERE id = (
        SELECT id FROM machine_template_id_reclaim
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id INTO new_id;

    IF new_id IS NULL THEN
        new_id := nextval('machine_templates_id_seq');
    END IF;

    RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION reclaim_machine_template_id()
RETURNS TRIGGER
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO machine_template_id_reclaim (id) VALUES (OLD.id)
        ON CONFLICT DO NOTHING;
    RETURN OLD;
END;
$$;



CREATE SEQUENCE networks_id_seq
    START 1
    MINVALUE 1
    NO CYCLE;

CREATE TABLE network_id_reclaim (
    id BIGINT PRIMARY KEY
);

CREATE OR REPLACE FUNCTION allocate_network_id()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_id BIGINT;
BEGIN
    DELETE FROM network_id_reclaim
    WHERE id = (
        SELECT id FROM network_id_reclaim
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id INTO new_id;

    IF new_id IS NULL THEN
        new_id := nextval('networks_id_seq');
    END IF;

    RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION reclaim_network_id()
RETURNS TRIGGER
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO network_id_reclaim (id) VALUES (OLD.id)
        ON CONFLICT DO NOTHING;
    RETURN OLD;
END;
$$;



CREATE SEQUENCE challenges_id_seq
    START 1
    MINVALUE 1
    NO CYCLE;

CREATE TABLE challenge_id_reclaim (
    id BIGINT PRIMARY KEY
);

CREATE OR REPLACE FUNCTION allocate_challenge_id()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_id BIGINT;
BEGIN
    DELETE FROM challenge_id_reclaim
    WHERE id = (
        SELECT id FROM challenge_id_reclaim
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id INTO new_id;

    IF new_id IS NULL THEN
        new_id := nextval('challenges_id_seq');
    END IF;

    RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION reclaim_challenge_id()
RETURNS TRIGGER
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO challenge_id_reclaim (id) VALUES (OLD.id)
        ON CONFLICT DO NOTHING;
    RETURN OLD;
END;
$$;



CREATE TYPE challenge_category AS ENUM (
    'web',
    'crypto',
    'reverse',
    'forensics',
    'pwn',
    'misc'
);

CREATE TYPE challenge_difficulty AS ENUM (
    'easy',
    'medium',
    'hard'
);

CREATE TYPE announcement_importance AS ENUM (
    'critical',
    'important',
    'normal'
);

CREATE TYPE announcement_category AS ENUM (
    'general',
    'updates',
    'maintenance',
    'events',
    'security'
);

CREATE TYPE badge_rarity AS ENUM (
    'common',
    'uncommon',
    'rare',
    'epic',
    'legendary'
);

CREATE TYPE badge_color AS ENUM (
    'bronze',
    'silver',
    'gold',
    'platinum',
    'diamond',
    'red',
    'blue',
    'green',
    'rainbow'
);



CREATE SEQUENCE challenge_templates_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE network_templates_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE challenge_flags_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE challenge_hints_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE completed_challenges_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE badges_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE announcements_id_seq START 1 MINVALUE 1 NO CYCLE;
CREATE SEQUENCE disk_files_id_seq START 1 MINVALUE 1 NO CYCLE;



CREATE TABLE vpn_static_ips (
    vpn_static_ip INET PRIMARY KEY,
    user_id BIGINT
);


CREATE TABLE users (
    id BIGINT PRIMARY KEY DEFAULT allocate_user_id(),
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    avatar_url TEXT DEFAULT generate_random_default_avatar(),
    email_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL,
    last_ip TEXT,
    running_challenge BIGINT,
    is_admin BOOLEAN DEFAULT FALSE,
    vpn_static_ip INET REFERENCES vpn_static_ips(vpn_static_ip) ON DELETE SET NULL,
    unique_id TEXT UNIQUE,
    password_reset BOOLEAN DEFAULT False,
    password_reset_timestamp TIMESTAMP DEFAULT NULL
);


CREATE TRIGGER trg_reclaim_user_id
AFTER DELETE ON users
FOR EACH ROW
EXECUTE FUNCTION reclaim_user_id();


ALTER TABLE vpn_static_ips
ADD CONSTRAINT fk_user_id
FOREIGN KEY (user_id)
REFERENCES users(id) ON DELETE SET NULL;


CREATE TABLE challenge_templates (
    id BIGINT PRIMARY KEY DEFAULT nextval('challenge_templates_id_seq'),
    name TEXT NOT NULL,
    description TEXT,
    category challenge_category NOT NULL,
    difficulty challenge_difficulty NOT NULL,
    image_path TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    creator_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    hint TEXT,
    solution TEXT,
    marked_for_deletion BOOLEAN DEFAULT FALSE,
    ready_to_launch BOOLEAN DEFAULT FALSE
);


CREATE TABLE challenge_subnets
(
    subnet INET NOT NULL CONSTRAINT challenge_subnet_pkey PRIMARY KEY,
    available boolean NOT NULL
);

CREATE TABLE pool_sizes
(
    challenge_template_id BIGINT NOT NULL REFERENCES challenge_templates(id) ON DELETE CASCADE,
    effective_time TIMESTAMP NOT NULL,
    size INT NOT NULL,
    manual_override BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (challenge_template_id, effective_time)
);

CREATE TYPE challenge_lifecycle_state AS ENUM (
    'PROVISIONING',
    'READY',
    'ASSIGNED',
    'ACTIVE',
    'EXPIRED',
    'TERMINATING'
);


CREATE TABLE challenges (
    id BIGINT PRIMARY KEY DEFAULT allocate_challenge_id(),
    challenge_template_id BIGINT NOT NULL,
    subnet INET REFERENCES challenge_subnets(subnet) ON DELETE CASCADE DEFAULT assign_challenge_subnet(),
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '100 years'),
    used_extensions BIGINT DEFAULT 0,
    pre_assigned_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    lifecycle_state challenge_lifecycle_state NOT NULL,
    FOREIGN KEY (challenge_template_id) REFERENCES challenge_templates(id) ON DELETE CASCADE
);


CREATE TRIGGER trg_reclaim_challenge_id
AFTER DELETE ON challenges
FOR EACH ROW
EXECUTE FUNCTION reclaim_challenge_id();


ALTER TABLE users
ADD CONSTRAINT fk_running_challenge
FOREIGN KEY (running_challenge)
REFERENCES challenges(id) ON DELETE SET NULL;


CREATE TABLE user_profiles (
    user_id BIGINT PRIMARY KEY,
    full_name TEXT,
    bio TEXT,
    github_url TEXT,
    twitter_url TEXT,
    website_url TEXT,
    country TEXT,
    timezone TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);


CREATE TABLE machine_templates (
    id BIGINT PRIMARY KEY DEFAULT allocate_machine_template_id(),
    challenge_template_id BIGINT NOT NULL REFERENCES challenge_templates(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    disk_file_id BIGINT NOT NULL,
    cores BIGINT NOT NULL CHECK (cores > 0),
    ram_gb BIGINT NOT NULL CHECK (ram_gb > 0)
);


CREATE TRIGGER trg_reclaim_machine_template_id
AFTER DELETE ON machine_templates
FOR EACH ROW
EXECUTE FUNCTION reclaim_machine_template_id();


CREATE TABLE network_templates (
    id BIGINT PRIMARY KEY DEFAULT nextval('network_templates_id_seq'),
    challenge_template_id BIGINT NOT NULL REFERENCES challenge_templates(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    accessible BOOLEAN NOT NULL,
    is_dmz BOOLEAN NOT NULL DEFAULT FALSE
);


CREATE TABLE domain_templates (
    machine_template_id BIGINT NOT NULL REFERENCES machine_templates(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    PRIMARY KEY (machine_template_id, domain_name)
);


CREATE TABLE network_connection_templates (
    machine_template_id BIGINT NOT NULL REFERENCES machine_templates(id) ON DELETE CASCADE,
    network_template_id BIGINT NOT NULL REFERENCES network_templates(id) ON DELETE CASCADE,
    PRIMARY KEY (machine_template_id, network_template_id)
);


CREATE TABLE challenge_flags (
    id BIGINT PRIMARY KEY DEFAULT nextval('challenge_flags_id_seq'),
    challenge_template_id BIGINT NOT NULL REFERENCES challenge_templates(id) ON DELETE CASCADE,
    flag TEXT NOT NULL,
    description TEXT,
    points BIGINT NOT NULL,
    order_index BIGINT DEFAULT 0,
    user_specific BOOLEAN DEFAULT false,
    machine_template_id BIGINT REFERENCES machine_templates(id) ON DELETE CASCADE DEFAULT NULL
);


CREATE TABLE challenge_hints (
    id BIGINT PRIMARY KEY DEFAULT nextval('challenge_hints_id_seq'),
    challenge_template_id BIGINT NOT NULL REFERENCES challenge_templates(id) ON DELETE CASCADE,
    hint_text TEXT NOT NULL,
    unlock_points BIGINT DEFAULT 0,
    order_index BIGINT DEFAULT 0
);


CREATE TABLE completed_challenges (
    id BIGINT PRIMARY KEY DEFAULT nextval('completed_challenges_id_seq'),
    user_id BIGINT NOT NULL,
    challenge_template_id BIGINT NOT NULL,
    attempts BIGINT NOT NULL DEFAULT 1,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    flag_id BIGINT REFERENCES challenge_flags(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (challenge_template_id) REFERENCES challenge_templates(id) ON DELETE CASCADE
);


CREATE TABLE badges (
    id BIGINT PRIMARY KEY DEFAULT nextval('badges_id_seq'),
    name TEXT NOT NULL,
    description TEXT,
    icon TEXT,
    color badge_color,
    rarity badge_rarity NOT NULL,
    requirements TEXT NOT NULL
);


CREATE TABLE user_badges (
    user_id BIGINT NOT NULL,
    badge_id BIGINT NOT NULL,
    earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, badge_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (badge_id) REFERENCES badges(id) ON DELETE CASCADE
);


CREATE TABLE announcements (
    id BIGINT PRIMARY KEY DEFAULT nextval('announcements_id_seq'),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    short_description TEXT,
    importance announcement_importance NOT NULL,
    category announcement_category NOT NULL,
    author TEXT NOT NULL REFERENCES users(username) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TYPE guest_os AS ENUM ('linux', 'windows');


CREATE TABLE disk_files (
    id BIGINT PRIMARY KEY DEFAULT nextval('disk_files_id_seq'),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    proxmox_filename TEXT NOT NULL,
    guest_os guest_os NOT NULL DEFAULT 'linux',
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, display_name)
);


ALTER TABLE machine_templates
ADD CONSTRAINT fk_machine_templates_disk_file
FOREIGN KEY (disk_file_id)
REFERENCES disk_files(id) ON DELETE RESTRICT;


CREATE TABLE machines
(
    id BIGINT NOT NULL PRIMARY KEY DEFAULT allocate_machine_id(),
    machine_template_id BIGINT NOT NULL REFERENCES machine_templates(id) ON DELETE CASCADE,
    challenge_id BIGINT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE
);


CREATE TABLE user_network_trace (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP,
    subnet INET NOT NULL,
    CHECK (stopped_at IS NULL OR stopped_at >= started_at)
);


CREATE TABLE user_identification_history (
    id SERIAL PRIMARY KEY,
    username_old TEXT,
    username_new TEXT,
    email_old TEXT,
    email_new TEXT,
    ip_addr INET,
    deleted BOOLEAN DEFAULT false,
    created BOOLEAN DEFAULT false,
    changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE OR REPLACE FUNCTION update_network_traces_on_user_change()
    RETURNS TRIGGER AS $$
BEGIN
    UPDATE user_network_trace
    SET username = NEW.username,
        email = NEW.email
    WHERE username = OLD.username
      AND stopped_at IS NULL;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_network_traces
    AFTER UPDATE OF username, email ON users
    FOR EACH ROW
    WHEN (OLD.username IS DISTINCT FROM NEW.username
        OR OLD.email IS DISTINCT FROM NEW.email)
EXECUTE FUNCTION update_network_traces_on_user_change();


CREATE TRIGGER trg_reclaim_machine_id
AFTER DELETE ON machines
FOR EACH ROW
EXECUTE FUNCTION reclaim_machine_id();


CREATE TABLE networks
(
    id BIGINT NOT NULL PRIMARY KEY DEFAULT allocate_network_id(),
    network_template_id BIGINT NOT NULL REFERENCES network_templates(id) ON DELETE CASCADE,
    challenge_id BIGINT NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
    subnet INET NOT NULL,
    host_device TEXT NOT NULL
);


CREATE TRIGGER trg_reclaim_network_id
AFTER DELETE ON networks
FOR EACH ROW
EXECUTE FUNCTION reclaim_network_id();


CREATE TABLE network_connections
(
    machine_id BIGINT NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    network_id BIGINT NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
    client_mac MACADDR NOT NULL,
    client_ip  INET    NOT NULL,
    PRIMARY KEY (machine_id, network_id)
);


CREATE TABLE domains
(
    machine_id  BIGINT NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    domain_name TEXT NOT NULL,
    PRIMARY KEY (machine_id, domain_name)
);



CREATE INDEX idx_machine_templates_challenge ON machine_templates(challenge_template_id);
CREATE INDEX idx_machine_templates_disk_file ON machine_templates(disk_file_id);
CREATE INDEX idx_domain_templates_machine ON domain_templates(machine_template_id);
CREATE INDEX idx_network_connection_templates_machine ON network_connection_templates(machine_template_id);
CREATE INDEX idx_network_connection_templates_network ON network_connection_templates(network_template_id);
CREATE INDEX idx_challenge_flags_challenge ON challenge_flags(challenge_template_id);
CREATE INDEX idx_challenge_hints_challenge ON challenge_hints(challenge_template_id);
CREATE INDEX idx_completed_challenges_user_id ON completed_challenges(user_id);
CREATE INDEX idx_challenges_challenge_template_id ON challenges(challenge_template_id);
CREATE INDEX idx_announcements_importance ON announcements(importance);
CREATE INDEX idx_announcements_created_at ON announcements(created_at);
CREATE INDEX idx_disk_files_user_id ON disk_files(user_id);
CREATE INDEX idx_disk_files_upload_date ON disk_files(upload_date);


INSERT INTO badges (name, description, icon, color, rarity, requirements)
VALUES
    ('Web Warrior', 'Solved 5 web challenges', '🕸️', 'gold', 'common', 'Solve 5 web challenges'),
    ('Crypto Expert', 'Solved 5 crypto challenges', '🔐', 'silver', 'common', 'Solve 5 crypto challenges'),
    ('Reverse Engineer', 'Solved 5 reverse challenges', '👁️', 'bronze', 'common', 'Solve 5 reverse challenges'),
    ('Forensic Analyst', 'Solved 5 forensics challenges', '🕵️', 'gold', 'common', 'Solve 5 forensics challenges'),
    ('Binary Buster', 'Solved 5 pwn challenges', '💣', 'silver', 'common', 'Solve 5 pwn challenges'),
    ('Puzzle Master', 'Solved 5 misc challenges', '🧩', 'bronze', 'common', 'Solve 5 misc challenges'),
    ('First Blood', 'First to solve a challenge', '💉', 'red', 'rare', 'Be the first to solve any challenge'),
    ('Speed Runner', 'Solved a challenge in under 5 minutes', '⚡', 'blue', 'uncommon', 'Solve any challenge in under 5 minutes'),
    ('Master Hacker', 'Earn all other badges', '👑', 'rainbow', 'legendary', 'Earn all available badges');