from pathlib import Path

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.history import GenerationHistoryStore


def _request() -> GenerateRequest:
    return GenerateRequest(
        description="生成 JWT 登录测试用例",
        max_cases=3,
        knowledge_top_k=2,
        include_context=False,
    )


def _response() -> GenerateResponse:
    return GenerateResponse(
        cases=[
            CaseModel(
                id="TC-001",
                title="JWT 登录成功",
                precondition="管理员账号存在",
                steps=["输入账号密码", "点击登录"],
                expected=["登录成功"],
                type=CaseType.functional,
            )
        ],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=1,
            retrieved_sources=["knowledge_export/api/auth_permissions.md"],
            prompt_version="test-case-generation-v1",
        ),
    )


def test_generation_history_records_success_and_detail(tmp_path: Path) -> None:
    store = GenerationHistoryStore(
        Settings(generation_history_db_path=str(tmp_path / "history.sqlite3"))
    )

    record_id = store.record_success(
        _request(),
        _response(),
        duration_ms=123.4,
        request_id="req-001",
    )

    records = store.list_records()
    detail = store.get_record(record_id or "")

    assert len(records) == 1
    assert records[0].id == record_id
    assert records[0].status == "success"
    assert records[0].request_id == "req-001"
    assert records[0].case_count == 1
    assert records[0].retrieved_sources == ["knowledge_export/api/auth_permissions.md"]
    assert detail is not None
    assert detail.request.description == "生成 JWT 登录测试用例"
    assert detail.response is not None
    assert detail.response.cases[0].title == "JWT 登录成功"


def test_generation_history_records_failure_and_filters_by_status(tmp_path: Path) -> None:
    store = GenerationHistoryStore(
        Settings(generation_history_db_path=str(tmp_path / "history.sqlite3"))
    )

    store.record_success(_request(), _response(), duration_ms=100)
    failed_id = store.record_failure(
        _request(),
        "upstream failed",
        duration_ms=50,
        request_id="req-failed",
    )

    failed_records = store.list_records(status="failed")
    detail = store.get_record(failed_id or "")

    assert [record.status for record in failed_records] == ["failed"]
    assert failed_records[0].error == "upstream failed"
    assert detail is not None
    assert detail.status == "failed"
    assert detail.response is None
    assert detail.error == "upstream failed"


def test_generation_history_returns_empty_when_disabled(tmp_path: Path) -> None:
    store = GenerationHistoryStore(
        Settings(
            generation_history_enabled=False,
            generation_history_db_path=str(tmp_path / "history.sqlite3"),
        )
    )

    record_id = store.record_success(_request(), _response(), duration_ms=1)

    assert record_id is None
    assert store.list_records() == []
    assert store.get_record("missing") is None
    assert not (tmp_path / "history.sqlite3").exists()
