-- ClickHouse Database Setup for Suricata EVE Logs

-- Create database
CREATE DATABASE IF NOT EXISTS suricata;

-- Use the database
USE suricata;

-- Main table for all EVE log events
CREATE TABLE IF NOT EXISTS backend_eve_logs (
    -- Core event fields
    timestamp DateTime64(6, 'UTC') CODEC(Delta, ZSTD),
    ingested_at DateTime64(6, 'UTC') DEFAULT now64() CODEC(Delta, ZSTD),
    event_type LowCardinality(String) CODEC(ZSTD),

    -- Network fields
    src_ip IPv6 DEFAULT '::' CODEC(ZSTD),
    dest_ip IPv6 DEFAULT '::' CODEC(ZSTD),
    src_port Nullable(UInt16) CODEC(ZSTD),
    dest_port Nullable(UInt16) CODEC(ZSTD),
    proto LowCardinality(String) DEFAULT '' CODEC(ZSTD),

    -- Flow identification
    flow_id String DEFAULT '' CODEC(ZSTD),
    community_id String DEFAULT '' CODEC(ZSTD),

    -- Payload fields (base64 encoded)
    payload String DEFAULT '' CODEC(ZSTD),
    payload_printable String DEFAULT '' CODEC(ZSTD),
    packet String DEFAULT '' CODEC(ZSTD),

    -- Event-specific data (JSON strings)
    alert_json String DEFAULT '' CODEC(ZSTD),
    http_json String DEFAULT '' CODEC(ZSTD),
    dns_json String DEFAULT '' CODEC(ZSTD),
    tls_json String DEFAULT '' CODEC(ZSTD),
    ssh_json String DEFAULT '' CODEC(ZSTD),
    flow_json String DEFAULT '' CODEC(ZSTD),
    netflow_json String DEFAULT '' CODEC(ZSTD),
    files_json String DEFAULT '' CODEC(ZSTD),
    smtp_json String DEFAULT '' CODEC(ZSTD),
    ftp_json String DEFAULT '' CODEC(ZSTD),
    rdp_json String DEFAULT '' CODEC(ZSTD),
    nfs_json String DEFAULT '' CODEC(ZSTD),
    smb_json String DEFAULT '' CODEC(ZSTD),
    tftp_json String DEFAULT '' CODEC(ZSTD),
    ike_json String DEFAULT '' CODEC(ZSTD),
    dcerpc_json String DEFAULT '' CODEC(ZSTD),
    krb5_json String DEFAULT '' CODEC(ZSTD),
    snmp_json String DEFAULT '' CODEC(ZSTD),
    rfb_json String DEFAULT '' CODEC(ZSTD),
    sip_json String DEFAULT '' CODEC(ZSTD),
    dhcp_json String DEFAULT '' CODEC(ZSTD),
    mqtt_json String DEFAULT '' CODEC(ZSTD),
    http2_json String DEFAULT '' CODEC(ZSTD),
    stats_json String DEFAULT '' CODEC(ZSTD),
    anomaly_json String DEFAULT '' CODEC(ZSTD),

    -- Extracted fields
    alert_signature String DEFAULT '' CODEC(ZSTD),
    alert_signature_id UInt32 DEFAULT 0 CODEC(ZSTD),
    alert_category String DEFAULT '' CODEC(ZSTD),
    alert_severity UInt8 DEFAULT 0 CODEC(ZSTD),
    alert_action String DEFAULT '' CODEC(ZSTD),
    dns_type String DEFAULT '' CODEC(ZSTD),
    dns_rrname String DEFAULT '' CODEC(ZSTD),
    dns_rrtype String DEFAULT '' CODEC(ZSTD),
    dns_id UInt32 DEFAULT 0 CODEC(ZSTD),
    http_hostname String DEFAULT '' CODEC(ZSTD),
    http_url String DEFAULT '' CODEC(ZSTD),
    http_method String DEFAULT '' CODEC(ZSTD),
    http_status UInt16 DEFAULT 0 CODEC(ZSTD),
    http_user_agent String DEFAULT '' CODEC(ZSTD),
    tls_subject String DEFAULT '' CODEC(ZSTD),
    tls_issuer String DEFAULT '' CODEC(ZSTD),
    tls_sni String DEFAULT '' CODEC(ZSTD),
    tls_version String DEFAULT '' CODEC(ZSTD),
    tls_ja3_hash String DEFAULT '' CODEC(ZSTD),
    flow_pkts_toserver UInt64 DEFAULT 0 CODEC(ZSTD),
    flow_pkts_toclient UInt64 DEFAULT 0 CODEC(ZSTD),
    flow_bytes_toserver UInt64 DEFAULT 0 CODEC(ZSTD),
    flow_bytes_toclient UInt64 DEFAULT 0 CODEC(ZSTD),
    flow_start String DEFAULT '' CODEC(ZSTD),
    flow_end String DEFAULT '' CODEC(ZSTD),

    -- Additional metadata
    app_proto LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    in_iface String DEFAULT '' CODEC(ZSTD),
    vlan Array(UInt16) DEFAULT [] CODEC(ZSTD),

    -- Indexes for common queries
    INDEX idx_timestamp timestamp TYPE minmax GRANULARITY 8192,
    INDEX idx_event_type event_type TYPE set(0) GRANULARITY 8192,
    INDEX idx_src_ip src_ip TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_dest_ip dest_ip TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_community_id community_id TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_alert_signature alert_signature TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_dns_rrname dns_rrname TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_http_hostname http_hostname TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_tls_sni tls_sni TYPE bloom_filter(0.01) GRANULARITY 8192
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (timestamp, event_type, src_ip, dest_ip)
TTL timestamp + INTERVAL 90 DAY
SETTINGS
    index_granularity = 8192,
    storage_policy = 'default';

-- Create materialized views for common event types

-- Alerts view
CREATE MATERIALIZED VIEW IF NOT EXISTS alerts_mv
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (timestamp, src_ip, dest_ip)
TTL timestamp + INTERVAL 90 DAY
AS SELECT
    timestamp,
    src_ip,
    dest_ip,
    src_port,
    dest_port,
    proto,
    flow_id,
    community_id,
    alert_signature as signature,
    alert_signature_id as signature_id,
    alert_category as category,
    alert_severity as severity,
    alert_action as action,
    payload_printable,
    alert_json
FROM backend_eve_logs
WHERE event_type = 'alert' AND alert_json != '';

-- DNS view
CREATE MATERIALIZED VIEW IF NOT EXISTS dns_mv
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (timestamp, src_ip, dest_ip)
TTL timestamp + INTERVAL 30 DAY
AS SELECT
    timestamp,
    src_ip,
    dest_ip,
    src_port,
    dest_port,
    flow_id,
    community_id,
    dns_type,
    dns_rrname as rrname,
    dns_rrtype as rrtype,
    dns_id,
    dns_json
FROM backend_eve_logs
WHERE event_type = 'dns' AND dns_json != '';

-- HTTP view
CREATE MATERIALIZED VIEW IF NOT EXISTS http_mv
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (timestamp, src_ip, dest_ip)
TTL timestamp + INTERVAL 30 DAY
AS SELECT
    timestamp,
    src_ip,
    dest_ip,
    src_port,
    dest_port,
    flow_id,
    community_id,
    http_hostname as hostname,
    http_url as url,
    http_method,
    http_status as status_code,
    http_user_agent as user_agent,
    http_json
FROM backend_eve_logs
WHERE event_type = 'http' AND http_json != '';

-- TLS view
CREATE MATERIALIZED VIEW IF NOT EXISTS tls_mv
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (timestamp, src_ip, dest_ip)
TTL timestamp + INTERVAL 30 DAY
AS SELECT
    timestamp,
    src_ip,
    dest_ip,
    src_port,
    dest_port,
    flow_id,
    community_id,
    tls_subject as subject,
    tls_issuer as issuer,
    tls_sni as sni,
    tls_version,
    tls_ja3_hash as ja3_hash,
    tls_json
FROM backend_eve_logs
WHERE event_type = 'tls' AND tls_json != '';

-- Flow view for netflow data
CREATE MATERIALIZED VIEW IF NOT EXISTS flow_mv
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (timestamp, src_ip, dest_ip)
TTL timestamp + INTERVAL 7 DAY
AS SELECT
    timestamp,
    src_ip,
    dest_ip,
    src_port,
    dest_port,
    proto,
    flow_id,
    community_id,
    flow_pkts_toserver as pkts_toserver,
    flow_pkts_toclient as pkts_toclient,
    flow_bytes_toserver as bytes_toserver,
    flow_bytes_toclient as bytes_toclient,
    flow_start,
    flow_end,
    flow_json
FROM backend_eve_logs
WHERE event_type = 'flow' AND flow_json != '';