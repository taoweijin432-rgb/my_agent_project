import sys
from pathlib import Path

from rq import Queue, Worker
from redis import Redis

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import get_settings
from app.workers.generation_rq import recover_stale_generation_jobs
from app.workers.test_plan_execution_rq import recover_stale_test_plan_execution_jobs


def main() -> None:
    settings = get_settings()
    recovered_job_ids = recover_stale_generation_jobs()
    if recovered_job_ids:
        print(f"Marked {len(recovered_job_ids)} stale generation jobs as failed.")
    recovered_execution_job_ids = recover_stale_test_plan_execution_jobs()
    if recovered_execution_job_ids:
        print(
            "Marked "
            f"{len(recovered_execution_job_ids)} stale test plan execution jobs as failed."
        )
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(
        settings.rq_queue_name,
        connection=connection,
        default_timeout=settings.rq_job_timeout_seconds,
    )
    worker = Worker([queue], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
