"""Stop-aware host loops; app policies continue to decide when and what to collect."""

import logging
import threading
from contextlib import AbstractContextManager

logger = logging.getLogger(__name__)


class BackgroundHost(AbstractContextManager):
    def __init__(self, runtime, workers: int = 1):
        if workers < 0:
            raise ValueError("Worker count must be nonnegative")
        self.runtime = runtime
        self.workers = workers
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def _scheduler(self) -> None:
        while not self.stop.is_set():
            try:
                self.runtime.tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            self.stop.wait(0.5)

    def _worker(self, index: int) -> None:
        while not self.stop.is_set():
            try:
                worked = self.runtime.work_once(f"host-{index}")
            except Exception:
                logger.exception("Worker failed outside its execution boundary")
                worked = False
            if not worked:
                self.stop.wait(0.2)

    def __enter__(self):
        tasks = [(self._scheduler, ())] + [
            (self._worker, (index,)) for index in range(self.workers)
        ]
        for target, arguments in tasks:
            thread = threading.Thread(target=target, args=arguments, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def __exit__(self, *exc):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=5)
        return False
