"""Entrypoint for the C11/INV-4 deletion-purge job. Runs far more often than
the nightly reweight job (INV-4's 60-second window) — intended to be invoked
by an external scheduler on a short interval (none is wired up in this
codebase). Run directly with `python -m jobs.purge_deleted`.
"""
from db.connection import job_connection
from forgetting.purge import run_purge_job


def main() -> None:
    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_purge_job(cur)
    print(f"purge job: purged {len(result.purged_ids)}")


if __name__ == "__main__":
    main()
