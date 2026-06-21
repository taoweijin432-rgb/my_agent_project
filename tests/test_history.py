from pathlib import Path

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationGateDetail,
    GenerationMetadata,
    GenerationUsage,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.history import (
    GenerationGateAlreadyResolvedError,
    GenerationHistoryStore,
)


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
            usage=GenerationUsage(
                prompt_characters=100,
                completion_characters=40,
                total_characters=140,
                prompt_tokens_estimate=50,
                completion_tokens_estimate=20,
                total_tokens_estimate=70,
                estimated_cost=0.001,
                currency="CNY",
            ),
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
    assert records[0].usage.total_tokens_estimate == 70
    assert records[0].usage.estimated_cost == 0.001
    assert detail is not None
    assert detail.request.description == "生成 JWT 登录测试用例"
    assert detail.response is not None
    assert detail.response.cases[0].title == "JWT 登录成功"
    assert detail.usage.total_characters == 140
    assert detail.quality is not None
    assert detail.quality.case_count == 1
    assert detail.quality.knowledge_grounded is True


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
        usage=GenerationUsage(
            prompt_characters=80,
            total_characters=80,
            prompt_tokens_estimate=40,
            total_tokens_estimate=40,
        ),
        gate=GenerationGateDetail(
            code="budget_exceeded",
            gate="budget",
            message="budget exceeded",
            action_required="human_confirmation",
            usage=GenerationUsage(prompt_tokens_estimate=40),
        ),
    )

    failed_records = store.list_records(status="failed")
    gate_records = store.list_gate_records()
    detail = store.get_record(failed_id or "")

    assert [record.status for record in failed_records] == ["failed"]
    assert failed_records[0].error == "upstream failed"
    assert failed_records[0].usage.prompt_tokens_estimate == 40
    assert failed_records[0].gate is not None
    assert failed_records[0].gate.code == "budget_exceeded"
    assert failed_records[0].gate_resolution is not None
    assert failed_records[0].gate_resolution.status == "pending"
    assert [record.id for record in gate_records] == [failed_id]
    assert detail is not None
    assert detail.status == "failed"
    assert detail.response is None
    assert detail.quality is None
    assert detail.usage.total_tokens_estimate == 40
    assert detail.error == "upstream failed"
    assert detail.gate is not None
    assert detail.gate.action_required == "human_confirmation"
    assert detail.gate_resolution is not None
    assert detail.gate_resolution.status == "pending"

    resolved = store.resolve_gate_record(
        failed_id or "",
        decision="approved",
        resolved_by="qa-owner",
        comment="allowed for test import",
    )

    pending_gate_records = store.list_gate_records()
    approved_gate_records = store.list_gate_records(gate_status="approved")
    all_gate_records = store.list_gate_records(gate_status=None)

    assert resolved is not None
    assert resolved.gate_resolution is not None
    assert resolved.gate_resolution.status == "approved"
    assert resolved.gate_resolution.resolved_at is not None
    assert resolved.gate_resolution.resolved_by == "qa-owner"
    assert resolved.gate_resolution.comment == "allowed for test import"
    assert pending_gate_records == []
    assert [record.id for record in approved_gate_records] == [failed_id]
    assert [record.id for record in all_gate_records] == [failed_id]

    try:
        store.resolve_gate_record(failed_id or "", decision="rejected")
    except GenerationGateAlreadyResolvedError as exc:
        assert "already approved" in str(exc)
    else:
        raise AssertionError("resolved gate records should not be resolved twice")


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
    assert store.list_gate_records() == []
    assert store.get_record("missing") is None
    assert store.resolve_gate_record("missing", decision="approved") is None
    assert not (tmp_path / "history.sqlite3").exists()
