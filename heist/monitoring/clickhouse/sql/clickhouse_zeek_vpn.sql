CREATE DATABASE IF NOT EXISTS zeek;

CREATE TABLE IF NOT EXISTS zeek.logs
(
    -- Core timestamps
    ts DateTime64(6, 'UTC') CODEC(Delta, ZSTD),
    ingested_at DateTime64(6, 'UTC') DEFAULT now64() CODEC(Delta, ZSTD),

    -- Event classification
    event_type LowCardinality(String) CODEC(ZSTD),

    -- Connection identifiers
    uid String CODEC(ZSTD),

    -- Network 5-tuple
    id_orig_h IPv6 DEFAULT '::' CODEC(ZSTD),
    id_orig_p UInt16 DEFAULT 0 CODEC(ZSTD),
    id_resp_h IPv6 DEFAULT '::' CODEC(ZSTD),
    id_resp_p UInt16 DEFAULT 0 CODEC(ZSTD),
    proto LowCardinality(String) DEFAULT '' CODEC(ZSTD),

    -- Connection metadata (conn.log specific)
    service LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    duration Float32 DEFAULT 0 CODEC(ZSTD),

    -- Traffic volume
    orig_bytes UInt64 DEFAULT 0 CODEC(ZSTD),
    resp_bytes UInt64 DEFAULT 0 CODEC(ZSTD),
    orig_pkts UInt32 DEFAULT 0 CODEC(ZSTD),
    resp_pkts UInt32 DEFAULT 0 CODEC(ZSTD),
    orig_ip_bytes UInt64 DEFAULT 0 CODEC(ZSTD),
    resp_ip_bytes UInt64 DEFAULT 0 CODEC(ZSTD),

    -- Connection state
    conn_state LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    history LowCardinality(String) DEFAULT '' CODEC(ZSTD),

    -- Locality flags
    local_orig Bool DEFAULT false CODEC(ZSTD),
    local_resp Bool DEFAULT false CODEC(ZSTD),

    -- Missed bytes
    missed_bytes UInt32 DEFAULT 0 CODEC(ZSTD),

    -- DNS fields (dns.log)
    dns_query String DEFAULT '' CODEC(ZSTD),
    dns_qtype LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    dns_qtype_name LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    dns_rcode LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    dns_rcode_name LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    dns_AA Bool DEFAULT false CODEC(ZSTD),
    dns_TC Bool DEFAULT false CODEC(ZSTD),
    dns_RD Bool DEFAULT false CODEC(ZSTD),
    dns_RA Bool DEFAULT false CODEC(ZSTD),
    dns_answers Array(String) DEFAULT [] CODEC(ZSTD),
    dns_TTLs Array(UInt32) DEFAULT [] CODEC(ZSTD),

    -- HTTP fields (http.log)
    http_method LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    http_host String DEFAULT '' CODEC(ZSTD),
    http_uri String DEFAULT '' CODEC(ZSTD),
    http_referrer String DEFAULT '' CODEC(ZSTD),
    http_user_agent String DEFAULT '' CODEC(ZSTD),
    http_status_code UInt16 DEFAULT 0 CODEC(ZSTD),
    http_status_msg String DEFAULT '' CODEC(ZSTD),
    http_request_body_len UInt64 DEFAULT 0 CODEC(ZSTD),
    http_response_body_len UInt64 DEFAULT 0 CODEC(ZSTD),

    -- SSL/TLS fields (ssl.log)
    ssl_version LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    ssl_cipher LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    ssl_server_name String DEFAULT '' CODEC(ZSTD),  -- SNI
    ssl_subject String DEFAULT '' CODEC(ZSTD),
    ssl_issuer String DEFAULT '' CODEC(ZSTD),
    ssl_validation_status LowCardinality(String) DEFAULT '' CODEC(ZSTD),

    -- Files fields (files.log)
    file_fuid String DEFAULT '' CODEC(ZSTD),
    file_mime_type LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    file_filename String DEFAULT '' CODEC(ZSTD),
    file_total_bytes UInt64 DEFAULT 0 CODEC(ZSTD),
    file_md5 String DEFAULT '' CODEC(ZSTD),
    file_sha1 String DEFAULT '' CODEC(ZSTD),
    file_sha256 String DEFAULT '' CODEC(ZSTD),

    -- Notice fields (notice.log)
    zeek_notice_name String DEFAULT '' CODEC(ZSTD),
    zeek_notice_flag Bool DEFAULT false CODEC(ZSTD),
    zeek_notice_peer String DEFAULT '' CODEC(ZSTD),
    zeek_notice_uid String DEFAULT '' CODEC(ZSTD),
    zeek_notice_msg String DEFAULT '' CODEC(ZSTD),
    zeek_notice_sub String DEFAULT '' CODEC(ZSTD),
    zeek_notice_note LowCardinality(String) DEFAULT '' CODEC(ZSTD),

    -- Metric fields (stats.log)
    metric_name String DEFAULT '' CODEC(ZSTD),
    metric_type LowCardinality(String) DEFAULT '' CODEC(ZSTD),
    metric_peer String DEFAULT '' CODEC(ZSTD),
    metric_value Float64 DEFAULT 0.0 CODEC(ZSTD),

    -- Community ID
    community_id String DEFAULT '' CODEC(ZSTD),

    -- Raw JSON
    raw String CODEC(ZSTD),

    -- Materialized columns for fast queries
    is_internal_traffic Bool MATERIALIZED
        (startsWith(IPv6NumToString(id_orig_h), '::ffff:10.') AND
         startsWith(IPv6NumToString(id_resp_h), '::ffff:10.')) CODEC(ZSTD),

    has_external_endpoint Bool MATERIALIZED
        (NOT startsWith(IPv6NumToString(id_orig_h), '::ffff:10.') OR
         NOT startsWith(IPv6NumToString(id_resp_h), '::ffff:10.')) CODEC(ZSTD),

    is_failed_connection Bool MATERIALIZED (conn_state IN ('S0', 'REJ', 'RSTO', 'RSTOS0')) CODEC(ZSTD),

    total_bytes UInt64 MATERIALIZED (orig_bytes + resp_bytes) CODEC(ZSTD),
    total_pkts UInt32 MATERIALIZED (orig_pkts + resp_pkts) CODEC(ZSTD),

    -- Indexes for fast filtering
    INDEX idx_ts ts TYPE minmax GRANULARITY 8192,
    INDEX idx_event_type event_type TYPE set(0) GRANULARITY 8192,
    INDEX idx_id_orig_h id_orig_h TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_id_resp_h id_resp_h TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_uid uid TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_conn_state conn_state TYPE set(0) GRANULARITY 8192,
    INDEX idx_service service TYPE set(0) GRANULARITY 8192,
    INDEX idx_dns_query dns_query TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 8192,
    INDEX idx_http_host http_host TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 8192,
    INDEX idx_ssl_server_name ssl_server_name TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 8192,
    INDEX idx_community_id community_id TYPE bloom_filter(0.01) GRANULARITY 8192,
    INDEX idx_zeek_notice_name zeek_notice_name TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 8192,
    INDEX idx_zeek_notice_note zeek_notice_note TYPE set(0) GRANULARITY 8192,
    INDEX idx_metric_name metric_name TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 8192

) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (ts, event_type, conn_state, id_orig_h, id_resp_h)
TTL ts + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

-- Optional Materialized Views
/*
CREATE MATERIALIZED VIEW IF NOT EXISTS zeek.connection_summary
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (toStartOfHour(ts), id_orig_h, id_resp_h, id_resp_p, proto)
POPULATE
AS SELECT
    toStartOfHour(ts) as ts,
    id_orig_h,
    id_resp_h,
    id_resp_p,
    proto,
    service,
    count() as connection_count,
    sum(orig_bytes) as total_orig_bytes,
    sum(resp_bytes) as total_resp_bytes,
    sum(orig_pkts) as total_orig_pkts,
    sum(resp_pkts) as total_resp_pkts,
    countIf(conn_state = 'S0') as failed_connections,
    countIf(conn_state = 'SF') as successful_connections
FROM zeek.logs
WHERE event_type = 'conn'
GROUP BY ts, id_orig_h, id_resp_h, id_resp_p, proto, service;

CREATE MATERIALIZED VIEW IF NOT EXISTS zeek.dns_summary
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (toStartOfHour(ts), dns_query, dns_qtype_name)
POPULATE
AS SELECT
    toStartOfHour(ts) as ts,
    dns_query,
    dns_qtype_name,
    count() as query_count,
    uniq(id_orig_h) as unique_clients
FROM zeek.logs
WHERE event_type = 'dns'
  AND dns_query != ''
GROUP BY ts, dns_query, dns_qtype_name;
*/