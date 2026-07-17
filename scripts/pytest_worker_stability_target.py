import os
import time


def test_worker_stability_pass_fast() -> None:
    _sleep(0.5)


def test_worker_stability_pass_slow() -> None:
    _sleep(2.0)


def test_worker_stability_fail_expected() -> None:
    _sleep(1.0)
    raise AssertionError("intentional worker stability smoke failure")


def _sleep(multiplier: float) -> None:
    raw_value = os.getenv("WORKER_STABILITY_SLEEP_SECONDS", "0.5")
    try:
        seconds = float(raw_value)
    except ValueError:
        seconds = 0.5
    time.sleep(max(seconds, 0) * multiplier)
