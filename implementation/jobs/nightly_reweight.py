"""Entrypoint for the C9 nightly forgetting job. Intended to be invoked by an
external cron/scheduler (none is wired up in this codebase — deployment
scheduling is out of scope for M4's file boundary). Run directly with
`python -m jobs.nightly_reweight`.
"""
from db.connection import job_connection
from forgetting.reweight import run_reweight_job


def main() -> None:
    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_reweight_job(cur)
    print(f"reweight job: evaluated {result.evaluated}, archived {len(result.archived_ids)}")


if __name__ == "__main__":
    main()
