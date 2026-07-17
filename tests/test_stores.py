import pytest

from app.core.config import Settings
from app.services.generation_job_store import GenerationJobStore
from app.services.history import GenerationHistoryStore
from app.services.mysql_stores import (
    MySQLConfigurationError,
    MySQLGenerationHistoryStore,
    MySQLGenerationJobStore,
    MySQLTestAgentWorkflowJobStore,
    MySQLTestPlanExecutionJobStore,
    _parse_mysql_url,
)
from app.services.stores import (
    create_generation_history_store,
    create_generation_job_store,
    create_test_agent_workflow_job_store,
    create_test_plan_execution_job_store,
)
from app.services.test_agent_workflow_store import (
    TestAgentWorkflowJobStore as SQLiteTestAgentWorkflowJobStore,
)
from app.services.test_plan_execution_store import (
    TestPlanExecutionJobStore as SQLiteTestPlanExecutionJobStore,
)


def test_store_factories_return_sqlite_stores(tmp_path) -> None:
    settings = Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))

    history_store = create_generation_history_store(settings)
    job_store = create_generation_job_store(settings)
    execution_job_store = create_test_plan_execution_job_store(settings)
    workflow_job_store = create_test_agent_workflow_job_store(settings)

    assert isinstance(history_store, GenerationHistoryStore)
    assert isinstance(job_store, GenerationJobStore)
    assert isinstance(execution_job_store, SQLiteTestPlanExecutionJobStore)
    assert isinstance(workflow_job_store, SQLiteTestAgentWorkflowJobStore)


def test_store_factories_return_mysql_stores_without_connecting() -> None:
    settings = Settings(
        database_backend="mysql",
        database_url="mysql://qa:secret@localhost:3306/agent",
    )

    history_store = create_generation_history_store(settings)
    job_store = create_generation_job_store(settings)
    execution_job_store = create_test_plan_execution_job_store(settings)
    workflow_job_store = create_test_agent_workflow_job_store(settings)

    assert isinstance(history_store, MySQLGenerationHistoryStore)
    assert isinstance(job_store, MySQLGenerationJobStore)
    assert isinstance(execution_job_store, MySQLTestPlanExecutionJobStore)
    assert isinstance(workflow_job_store, MySQLTestAgentWorkflowJobStore)


def test_store_factories_reject_mysql_without_database_url() -> None:
    settings = Settings(database_backend="mysql", database_url=None)

    with pytest.raises(MySQLConfigurationError, match="DATABASE_URL"):
        create_generation_history_store(settings)
    with pytest.raises(MySQLConfigurationError, match="DATABASE_URL"):
        create_generation_job_store(settings)
    with pytest.raises(MySQLConfigurationError, match="DATABASE_URL"):
        create_test_plan_execution_job_store(settings)
    with pytest.raises(MySQLConfigurationError, match="DATABASE_URL"):
        create_test_agent_workflow_job_store(settings)


def test_mysql_connection_options_include_configured_timeouts() -> None:
    settings = Settings(
        database_backend="mysql",
        database_url="mysql://qa:secret@localhost:3306/agent?charset=utf8mb4",
        mysql_connect_timeout_seconds=7,
        mysql_read_timeout_seconds=11,
        mysql_write_timeout_seconds=13,
    )

    history_store = MySQLGenerationHistoryStore(settings)

    assert history_store.connection_options["connect_timeout"] == 7
    assert history_store.connection_options["read_timeout"] == 11
    assert history_store.connection_options["write_timeout"] == 13


def test_mysql_url_timeout_query_overrides_config_defaults() -> None:
    options = _parse_mysql_url(
        "mysql://qa:secret@localhost:3306/agent?"
        "charset=utf8mb4&connect_timeout=3&read_timeout=5&write_timeout=7",
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )

    assert options["connect_timeout"] == 3
    assert options["read_timeout"] == 5
    assert options["write_timeout"] == 7
