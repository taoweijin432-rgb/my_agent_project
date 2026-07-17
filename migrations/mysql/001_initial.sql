CREATE TABLE IF NOT EXISTS generation_records (
    id varchar(64) PRIMARY KEY,
    created_at datetime(6) NOT NULL,
    request_id varchar(128),
    status varchar(16) NOT NULL,
    description text NOT NULL,
    request_json json NOT NULL,
    response_json json,
    error text,
    duration_ms double NOT NULL,
    model varchar(255),
    attempts int,
    retrieved_chunks int,
    retrieved_sources_json json NOT NULL,
    case_count int NOT NULL,
    usage_json json NOT NULL,
    gate_detail_json json,
    gate_status varchar(16),
    gate_resolved_at datetime(6),
    gate_resolved_by varchar(255),
    gate_resolution_comment text,
    CONSTRAINT chk_generation_records_status
        CHECK (status IN ('success', 'failed')),
    CONSTRAINT chk_generation_records_gate_status
        CHECK (gate_status IS NULL OR gate_status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT chk_generation_records_case_count
        CHECK (case_count >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_generation_records_created_at
    ON generation_records (created_at DESC);

CREATE INDEX idx_generation_records_status
    ON generation_records (status);

CREATE INDEX idx_generation_records_gate_status
    ON generation_records (gate_status);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id varchar(64) PRIMARY KEY,
    queue_backend varchar(32) NOT NULL,
    queue_job_id varchar(128),
    status varchar(16) NOT NULL,
    created_at datetime(6) NOT NULL,
    updated_at datetime(6) NOT NULL,
    started_at datetime(6),
    finished_at datetime(6),
    created_epoch double NOT NULL,
    started_epoch double,
    finished_epoch double,
    request_json json NOT NULL,
    response_json json,
    error_json json,
    record_id varchar(64),
    worker_id varchar(255),
    attempts int NOT NULL DEFAULT 0,
    CONSTRAINT chk_generation_jobs_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    CONSTRAINT chk_generation_jobs_attempts
        CHECK (attempts >= 0),
    CONSTRAINT fk_generation_jobs_record_id
        FOREIGN KEY (record_id) REFERENCES generation_records (id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_generation_jobs_created_at
    ON generation_jobs (created_at DESC);

CREATE INDEX idx_generation_jobs_created_epoch
    ON generation_jobs (created_epoch DESC);

CREATE INDEX idx_generation_jobs_status
    ON generation_jobs (status);

CREATE INDEX idx_generation_jobs_active
    ON generation_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS test_plan_execution_jobs (
    id varchar(64) PRIMARY KEY,
    status varchar(16) NOT NULL,
    created_at datetime(6) NOT NULL,
    updated_at datetime(6) NOT NULL,
    started_at datetime(6),
    finished_at datetime(6),
    created_epoch double NOT NULL,
    started_epoch double,
    finished_epoch double,
    request_json json NOT NULL,
    report_json json,
    error_json json,
    CONSTRAINT chk_test_plan_execution_jobs_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_test_plan_execution_jobs_created_epoch
    ON test_plan_execution_jobs (created_epoch DESC);

CREATE INDEX idx_test_plan_execution_jobs_status
    ON test_plan_execution_jobs (status);

CREATE INDEX idx_test_plan_execution_jobs_active
    ON test_plan_execution_jobs (status, created_epoch);

CREATE TABLE IF NOT EXISTS test_agent_workflow_jobs (
    id varchar(64) PRIMARY KEY,
    status varchar(16) NOT NULL,
    created_at datetime(6) NOT NULL,
    updated_at datetime(6) NOT NULL,
    started_at datetime(6),
    finished_at datetime(6),
    created_epoch double NOT NULL,
    started_epoch double,
    finished_epoch double,
    request_json json NOT NULL,
    result_json json,
    error_json json,
    CONSTRAINT chk_test_agent_workflow_jobs_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_test_agent_workflow_jobs_created_epoch
    ON test_agent_workflow_jobs (created_epoch DESC);

CREATE INDEX idx_test_agent_workflow_jobs_status
    ON test_agent_workflow_jobs (status);

CREATE INDEX idx_test_agent_workflow_jobs_active
    ON test_agent_workflow_jobs (status, created_epoch);
