from pathlib import Path

import scripts.ingest_documents as ingest_documents
from scripts.ingest_documents import _document_from_path, _iter_input_files


def test_iter_input_files_recursively_finds_supported_documents(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    (root / "prd" / "login").mkdir(parents=True)
    (root / "prd" / "login" / "phone-login.md").write_text("登录 PRD", encoding="utf-8")
    (root / "api" / "login").mkdir(parents=True)
    (root / "api" / "login" / "login-api.txt").write_text("接口文档", encoding="utf-8")
    (root / "api" / "login" / "ignore.pdf").write_text("ignore", encoding="utf-8")

    files = _iter_input_files([str(root)], recursive=True)

    assert [item.name for item in files] == ["login-api.txt", "phone-login.md"]


def test_document_from_path_infers_metadata_from_knowledge_tree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ingest_documents, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "knowledge" / "prd" / "login" / "phone-login.md"
    path.parent.mkdir(parents=True)
    path.write_text("手机号验证码登录", encoding="utf-8")

    document = _document_from_path(path)

    assert document.source == "knowledge/prd/login/phone-login.md"
    assert document.document_type == "prd"
    assert document.module == "login"
    assert document.tags == ["prd", "login"]
    assert document.content == "手机号验证码登录"


def test_document_from_path_infers_metadata_from_knowledge_export_tree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(ingest_documents, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "knowledge_export" / "api" / "auth_permissions.md"
    path.parent.mkdir(parents=True)
    path.write_text("认证与权限 API", encoding="utf-8")

    document = _document_from_path(path)

    assert document.source == "knowledge_export/api/auth_permissions.md"
    assert document.document_type == "api"
    assert document.module == "auth_permissions"
    assert document.tags == ["api", "auth_permissions"]
