from scripts.run_server import parse_args


def test_run_server_defaults_to_console_output() -> None:
    args = parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.reload is False
    assert args.log_to_file is False


def test_run_server_supports_background_logging_and_reload() -> None:
    args = parse_args(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--reload",
            "--log-to-file",
        ]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.reload is True
    assert args.log_to_file is True
