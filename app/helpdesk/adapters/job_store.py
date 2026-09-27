import threading
import uuid

from ..ports import JobStore
from ..schemas import ReportJob


class InMemoryJobStore(JobStore):
    """Tarefas em memória do processo. Um reinício da aplicação perde as tarefas em andamento
    (fora de escopo no desafio); persistir é implementar o mesmo port com um banco."""

    def __init__(self):
        self._jobs: dict[str, ReportJob] = {}
        self._lock = threading.Lock()

    def create(self) -> ReportJob:
        job = ReportJob(id=uuid.uuid4().hex[:12])
        self.save(job)
        return job

    def save(self, job: ReportJob) -> None:
        with self._lock:
            self._jobs[job.id] = job.model_copy()

    def get(self, job_id: str) -> ReportJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy() if job else None
