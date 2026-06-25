import pytest

from app.core.config import Settings
from app.services.generation_job_store import GenerationJobStore
from app.services.history import GenerationHistoryStore
from app.services.mysql_stores import (
    MySQLConfigurationError,
    MySQLGenerationHistoryStore,
    MySQLGenerationJobStore,
)
from app.services.stores import (
    create_generation_history_store,
    create_generation_job_store,
)


def test_store_factories_return_sqlite_stores(tmp_path) -> None:
    settings = Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))

    history_store = create_generation_history_store(settings)
    job_store = create_generation_job_store(settings)

    assert isinstance(history_store, GenerationHistoryStore)
    assert isinstance(job_store, GenerationJobStore)


def test_store_factories_return_mysql_stores_without_connecting() -> None:
    settings = Settings(
        database_backend="mysql",
        database_url="mysql://qa:secret@localhost:3306/agent",
    )

    history_store = create_generation_history_store(settings)
    job_store = create_generation_job_store(settings)

    assert isinstance(history_store, MySQLGenerationHistoryStore)
    assert isinstance(job_store, MySQLGenerationJobStore)


def test_store_factories_reject_mysql_without_database_url() -> None:
    settings = Settings(database_backend="mysql", database_url=None)

    with pytest.raises(MySQLConfigurationError, match="DATABASE_URL"):
        create_generation_history_store(settings)
    with pytest.raises(MySQLConfigurationError, match="DATABASE_URL"):
        create_generation_job_store(settings)
