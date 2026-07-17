import argparse
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_FILE = PROJECT_ROOT / "migrations" / "mysql" / "001_initial.sql"


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize MySQL schema.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="MySQL connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--schema-file",
        default=str(DEFAULT_SCHEMA_FILE),
        help="SQL schema file to apply.",
    )
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL is required.")

    schema_path = Path(args.schema_file)
    if not schema_path.exists():
        raise SystemExit(f"Schema file not found: {schema_path}")

    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyMySQL is not installed. Install optional dependencies with "
            "`uv pip install --python ./.venv/bin/python -r requirements.txt`."
        ) from exc

    config = _parse_mysql_url(args.database_url)
    schema_sql = schema_path.read_text(encoding="utf-8")
    connection = pymysql.connect(**config, cursorclass=DictCursor, autocommit=False)
    try:
        with connection.cursor() as cursor:
            skipped = 0
            for statement in _split_sql_statements(schema_sql):
                try:
                    cursor.execute(statement)
                except pymysql.err.OperationalError as exc:
                    if _is_idempotent_schema_error(exc):
                        skipped += 1
                        continue
                    raise
        connection.commit()
    finally:
        connection.close()

    suffix = f" skipped_existing={skipped}" if skipped else ""
    print(f"Applied MySQL schema: {schema_path}{suffix}")


def _parse_mysql_url(database_url: str) -> dict[str, object]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise SystemExit("DATABASE_URL must start with mysql:// or mysql+pymysql://.")
    database = parsed.path.lstrip("/")
    if not database:
        raise SystemExit("DATABASE_URL must include a database name.")
    query = parse_qs(parsed.query)
    charset = query.get("charset", ["utf8mb4"])[0]
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": charset,
    }


def _split_sql_statements(schema_sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in schema_sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    trailing = "\n".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _is_idempotent_schema_error(exc: Exception) -> bool:
    code = exc.args[0] if exc.args else None
    return code in {
        1061,  # Duplicate key name.
    }


if __name__ == "__main__":
    main()
