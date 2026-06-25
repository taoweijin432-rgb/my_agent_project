import argparse
import sys
from pathlib import Path
from typing import Iterable

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import PROJECT_ROOT, get_settings
from app.models.test_case import KnowledgeDocument
from app.services.rag import RagService


SUPPORTED_SUFFIXES = {".md", ".txt"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PRD/history documents into Chroma.")
    parser.add_argument("paths", nargs="+", help="Text/markdown files or directories to ingest.")
    parser.add_argument("--chunk-size", type=int, default=900)
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively ingest supported files when a directory is provided.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the configured Chroma collection before ingesting.",
    )
    args = parser.parse_args()

    documents = [_document_from_path(path) for path in _iter_input_files(args.paths, args.recursive)]
    if not documents:
        raise SystemExit("No supported documents found. Supported suffixes: .md, .txt")

    settings = get_settings()
    service = RagService(settings)
    if args.reset:
        service.client.delete_collection(settings.chroma_collection)
        service = RagService(settings)

    added = service.ingest_documents(documents, chunk_size=args.chunk_size)
    print(f"Imported {len(documents)} documents.")
    print(f"Added {added} chunks.")
    print(f"Collection: {settings.chroma_collection}")
    for document in documents:
        print(
            " - "
            f"{document.source} "
            f"(type={document.document_type}, module={document.module}, tags={','.join(document.tags)})"
        )


def _iter_input_files(raw_paths: Iterable[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path)
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            files.extend(
                item
                for item in iterator
                if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES
            )
            continue
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return sorted(set(files), key=lambda item: str(item).lower())


def _document_from_path(path: Path) -> KnowledgeDocument:
    source = _relative_source(path)
    document_type, module = _infer_metadata(path)
    tags = [document_type]
    if module != "general":
        tags.append(module)

    return KnowledgeDocument(
        source=source,
        content=path.read_text(encoding="utf-8"),
        document_type=document_type,
        module=module,
        tags=tags,
    )


def _relative_source(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _infer_metadata(path: Path) -> tuple[str, str]:
    resolved = path.resolve()
    for root_name, use_file_stem_for_module in (
        ("knowledge", False),
        ("knowledge_export", True),
    ):
        try:
            relative = resolved.relative_to(PROJECT_ROOT / root_name)
            break
        except ValueError:
            continue
    else:
        return "manual", "general"

    parts = relative.parts
    document_type = _clean_metadata(parts[0]) if len(parts) >= 2 else "manual"
    if len(parts) >= 3:
        module = _clean_metadata(parts[1])
    elif use_file_stem_for_module and len(parts) >= 2:
        module = _clean_metadata(Path(parts[-1]).stem)
    else:
        module = "general"
    return document_type, module


def _clean_metadata(value: str) -> str:
    cleaned = value.strip().lower().replace(" ", "-")
    return cleaned or "general"


if __name__ == "__main__":
    main()
