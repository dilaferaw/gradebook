"""In-memory job store for the Gradebook Report Service.

Every job the service knows about lives in a Python dict, in RAM,
in this one process. There is no database and no disk involvement.
Restart the process and every job is gone. That is a deliberate
trade-off: simplicity now, durability thrown away.

The one piece of subtlety in this file is the lock. Read the
docstring on `JobStore` before changing anything.
"""

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


# How long a job is allowed to sit around. Defined here so the
# numbers live in one place. Enforcement comes later (Step 10).
IDLE_TTL = timedelta(minutes=30)   # refreshed on every activity
HARD_TTL = timedelta(hours=4)      # never refreshed


def _utcnow() -> datetime:
    """Single source of 'now', always timezone-aware UTC.

    Mixing local time and UTC is the classic source of bugs where
    two timestamps differ by hours. We store UTC, and format for
    humans on the way out if we ever need to.
    """
    return datetime.now(timezone.utc)


class Job(BaseModel):
    """One short-lived collection of grade submissions.

    Pydantic is the same library FastAPI uses to validate incoming
    requests. Reusing it here gives us free JSON serialization and
    one canonical definition of what a job looks like.
    """

    job_id: str
    status: Literal["collecting", "ready", "computed"] = "collecting"

    class_name: str
    semester_a: str
    semester_b: str

    expected_subjects: list[str] = Field(default_factory=list)
    received_subjects: list[str] = Field(default_factory=list)
    students_seen: int = 0
    row_count: int = 0
    options: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime
    expires_at: datetime
    hard_expires_at: datetime

    # Bookkeeping for the idle-timeout logic. `exclude=True` keeps
    # it out of every API response; we still need it internally.
    last_activity_at: datetime = Field(exclude=True)

    @computed_field
    @property
    def missing_subjects(self) -> list[str]:
        """Subjects we were told to expect but have not seen yet."""
        received = set(self.received_subjects)
        return [s for s in self.expected_subjects if s not in received]


class JobStore:
    """Thread-safe map from `job_id` to `Job`.

    Storage is one plain dict. A dict is a hash table: hand it a
    key, get the value back in constant time on average. That is
    all we need for this project.

    The lock matters because FastAPI serves requests on more than
    one thread. Two requests that touch the dict at the same
    moment, one of them writing, can corrupt the store or raise
    confusing errors. Every read and write below goes through the
    lock, so each operation behaves as if it were alone in the
    process.

    We use a threading lock rather than an asyncio lock because
    our endpoints are ordinary `def` functions, and FastAPI runs
    those in a thread pool. A threading lock is the right tool for
    threads.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        class_name: str,
        semester_a: str,
        semester_b: str,
        expected_subjects: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> Job:
        """Make a fresh job, store it, and hand it back."""
        now = _utcnow()
        job = Job(
            job_id=uuid4().hex,
            class_name=class_name,
            semester_a=semester_a,
            semester_b=semester_b,
            expected_subjects=list(expected_subjects or []),
            options=dict(options or {}),
            created_at=now,
            expires_at=now + IDLE_TTL,
            hard_expires_at=now + HARD_TTL,
            last_activity_at=now,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        """Return the job, or None if we have never heard of it."""
        with self._lock:
            return self._jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        """Forget a job. Returns True if something was there."""
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def _reset(self) -> None:
        """Test hook: drop everything. Not part of the public API."""
        with self._lock:
            self._jobs.clear()


# The one store this process uses. Everything that needs the store
# imports this name.
store = JobStore()