import os
import tempfile
from pathlib import Path


FALSE_VALUES = {"0", "false", "no", "off"}


def main() -> None:
    if os.environ.get("RUNTIME_PATH_CHECK_ENABLED", "true").strip().lower() in FALSE_VALUES:
        print("Runtime path check skipped.")
        return

    errors: list[str] = []
    for label, path in _paths_to_check():
        error = _check_writable_path(label, path)
        if error:
            errors.append(error)

    if errors:
        print("Runtime path check failed:")
        for error in errors:
            print(f"- {error}")
        print(
            "Fix host bind mount ownership or permissions so the container user can write "
            "to the mounted runtime directories."
        )
        raise SystemExit(1)

    print("Runtime path check passed.")


def _paths_to_check() -> list[tuple[str, Path]]:
    paths = [
        ("CHROMA_PATH", Path(os.environ.get("CHROMA_PATH", "data/chroma"))),
        (
            "EMBEDDING_CACHE_DIR",
            Path(os.environ.get("EMBEDDING_CACHE_DIR", ".model_cache/huggingface")),
        ),
    ]

    if os.environ.get("DATABASE_BACKEND", "sqlite").strip().lower() == "sqlite":
        history_path = Path(
            os.environ.get("GENERATION_HISTORY_DB_PATH", "data/app.sqlite3")
        )
        paths.append(("GENERATION_HISTORY_DB_PATH parent", history_path.parent))

    return paths


def _check_writable_path(label: str, path: Path) -> str | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"{label}={path} cannot be created: {exc}"

    if not path.is_dir():
        return f"{label}={path} is not a directory."

    try:
        with tempfile.NamedTemporaryFile(
            prefix=".runtime-write-test-",
            dir=path,
            delete=True,
        ) as temp_file:
            temp_file.write(b"ok")
            temp_file.flush()
    except OSError as exc:
        return f"{label}={path} is not writable: {exc}"

    return None


if __name__ == "__main__":
    main()
