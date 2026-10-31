CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR PRIMARY KEY,
    mode VARCHAR NOT NULL CHECK (mode IN ('run', 'count')),
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status VARCHAR NOT NULL CHECK (status IN ('running', 'paused', 'failed', 'completed')),
    stage VARCHAR NOT NULL,
    config_hash VARCHAR NOT NULL,
    roles_filter VARCHAR,
    countries_filter VARCHAR,
    request_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    llm_calls INTEGER DEFAULT 0,
    llm_input_tokens BIGINT DEFAULT 0,
    llm_output_tokens BIGINT DEFAULT 0,
    llm_cache_read_tokens BIGINT DEFAULT 0,
    message VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_responses (
    url VARCHAR NOT NULL,
    scope VARCHAR NOT NULL CHECK (scope IN ('run', 'global')),
    run_id VARCHAR NOT NULL,
    status INTEGER NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    body_gz BLOB NOT NULL,
    PRIMARY KEY (url, run_id)
);

CREATE TABLE IF NOT EXISTS searches (
    search_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    country VARCHAR NOT NULL,
    keywords VARCHAR NOT NULL,
    time_window VARCHAR NOT NULL,
    displayed_count_raw VARCHAR,
    displayed_count INTEGER,
    is_lower_bound BOOLEAN
);

CREATE TABLE IF NOT EXISTS slices (
    slice_id VARCHAR PRIMARY KEY,
    search_id VARCHAR NOT NULL,
    parent_slice_id VARCHAR,
    depth INTEGER NOT NULL,
    filters_json VARCHAR NOT NULL,
    displayed_count_raw VARCHAR,
    displayed_count INTEGER,
    is_lower_bound BOOLEAN,
    pages_fetched INTEGER DEFAULT 0,
    cards_seen INTEGER DEFAULT 0,
    hit_cap BOOLEAN DEFAULT FALSE,
    done BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id VARCHAR PRIMARY KEY,
    title VARCHAR NOT NULL,
    company VARCHAR NOT NULL,
    company_url VARCHAR,
    location_text VARCHAR,
    posted_at DATE,
    url VARCHAR NOT NULL,
    first_seen_run VARCHAR NOT NULL,
    last_seen_run VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS job_roles (
    job_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    PRIMARY KEY (job_id, role)
);

CREATE TABLE IF NOT EXISTS job_sightings (
    job_id VARCHAR NOT NULL,
    slice_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    PRIMARY KEY (job_id, slice_id)
);

CREATE TABLE IF NOT EXISTS boundary_titles (
    run_id VARCHAR NOT NULL,
    job_id VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    near_role VARCHAR NOT NULL,
    PRIMARY KEY (run_id, job_id, near_role)
);

CREATE TABLE IF NOT EXISTS job_details (
    job_id VARCHAR PRIMARY KEY,
    fetched_at TIMESTAMP NOT NULL,
    fetched_ok BOOLEAN NOT NULL,
    http_status INTEGER,
    description_text VARCHAR,
    description_html_gz BLOB,
    seniority VARCHAR,
    employment_type VARCHAR,
    job_function VARCHAR,
    industries VARCHAR,
    applicants_text VARCHAR,
    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
    description_hash VARCHAR
);

CREATE TABLE IF NOT EXISTS classifications (
    job_id VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    remote_status VARCHAR NOT NULL CHECK (remote_status IN ('REMOTE', 'HYBRID', 'ONSITE', 'UNKNOWN')),
    eligibility_label VARCHAR NOT NULL CHECK (eligibility_label IN ('LATAM_FRIENDLY', 'US_CA_ONLY', 'UNCLEAR')),
    method VARCHAR NOT NULL CHECK (method IN ('rules', 'llm', 'rules-fallback')),
    confidence DECIMAL(3, 2),
    restriction_type VARCHAR NOT NULL,
    matched_phrases_json VARCHAR,
    evidence_json VARCHAR,
    quotes_verified BOOLEAN NOT NULL,
    rules_version VARCHAR NOT NULL,
    prompt_version VARCHAR,
    llm_model VARCHAR,
    reasoning VARCHAR,
    PRIMARY KEY (job_id, run_id),
    CHECK (eligibility_label <> 'LATAM_FRIENDLY' OR (method = 'llm' AND quotes_verified))
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key VARCHAR PRIMARY KEY,
    response_json VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER
);

CREATE TABLE IF NOT EXISTS technologies (
    tech_id INTEGER PRIMARY KEY,
    canonical VARCHAR UNIQUE NOT NULL,
    category VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS job_technologies (
    job_id VARCHAR NOT NULL,
    tech_id INTEGER NOT NULL,
    mention_count INTEGER NOT NULL CHECK (mention_count >= 1),
    requirement_level VARCHAR,
    PRIMARY KEY (job_id, tech_id)
);

CREATE OR REPLACE VIEW v_qualified AS
SELECT c.run_id, c.job_id, c.remote_status, c.eligibility_label, c.method, c.confidence,
       c.restriction_type, c.evidence_json, c.reasoning
FROM classifications c
JOIN job_details d ON d.job_id = c.job_id
WHERE d.fetched_ok AND NOT d.is_closed AND c.remote_status IN ('REMOTE', 'UNKNOWN');

CREATE OR REPLACE VIEW v_funnel AS
WITH srch AS (
    SELECT run_id, role, country,
           any_value(displayed_count_raw) AS displayed_count_raw,
           any_value(displayed_count) AS displayed_count,
           bool_or(is_lower_bound) AS is_lower_bound
    FROM searches
    GROUP BY run_id, role, country
),
sighted_search AS (
    SELECT DISTINCT s.run_id, s.role, s.country, js.job_id
    FROM searches s
    JOIN slices sl ON sl.search_id = s.search_id
    JOIN job_sightings js ON js.slice_id = sl.slice_id
),
collected AS (
    SELECT run_id, role, country, count(*) AS n
    FROM sighted_search
    GROUP BY run_id, role, country
),
matched AS (
    SELECT DISTINCT sc.run_id, jr.role, sc.country, sc.job_id
    FROM (SELECT DISTINCT run_id, country, job_id FROM sighted_search) sc
    JOIN job_roles jr ON jr.job_id = sc.job_id
)
SELECT srch.run_id, srch.role, srch.country,
       srch.displayed_count_raw, srch.displayed_count, srch.is_lower_bound,
       coalesce(any_value(c.n), 0) AS collected_count,
       count(DISTINCT m.job_id) AS role_matched_count,
       count(DISTINCT q.job_id) AS qualified_count,
       count(DISTINCT CASE WHEN q.eligibility_label = 'LATAM_FRIENDLY' THEN q.job_id END) AS latam_friendly,
       count(DISTINCT CASE WHEN q.eligibility_label = 'UNCLEAR' THEN q.job_id END) AS unclear,
       count(DISTINCT CASE WHEN q.eligibility_label = 'US_CA_ONLY' THEN q.job_id END) AS us_ca_only
FROM srch
LEFT JOIN collected c ON c.run_id = srch.run_id AND c.role = srch.role AND c.country = srch.country
LEFT JOIN matched m ON m.run_id = srch.run_id AND m.role = srch.role AND m.country = srch.country
LEFT JOIN v_qualified q ON q.job_id = m.job_id AND q.run_id = m.run_id
GROUP BY srch.run_id, srch.role, srch.country, srch.displayed_count_raw, srch.displayed_count, srch.is_lower_bound;

INSERT INTO schema_version (version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version = 1);
