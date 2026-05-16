from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueuedTask:
    task: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class BackgroundTaskQueue:
    def __init__(self, *, workers: int, queue_size: int) -> None:
        self.worker_count = max(1, int(workers))
        self.q: queue.Queue[QueuedTask | None] = queue.Queue(maxsize=max(1, int(queue_size)))
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._threads = [
                threading.Thread(
                    target=self._worker_loop,
                    daemon=True,
                    name=f"background-task-worker-{index + 1}",
                )
                for index in range(self.worker_count)
            ]
            for thread in self._threads:
                thread.start()

    def enqueue(self, task: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.start()
        item = QueuedTask(task=task, args=tuple(args), kwargs=dict(kwargs))
        try:
            self.q.put_nowait(item)
        except queue.Full as exc:
            raise RuntimeError("background task queue is full") from exc

    def close(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._started:
                return
            threads = list(self._threads)
            self._started = False
            self._threads = []

        for _ in threads:
            try:
                self.q.put(None, timeout=timeout)
            except queue.Full:
                break
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=timeout)

    def _worker_loop(self) -> None:
        while True:
            item = self.q.get()
            try:
                if item is None:
                    return
                item.task(*item.args, **item.kwargs)
            except Exception:
                logger.exception("Background task failed")
            finally:
                self.q.task_done()


background_task_queue = BackgroundTaskQueue(
    workers=settings.BACKGROUND_TASK_WORKERS,
    queue_size=settings.BACKGROUND_TASK_QUEUE_SIZE,
)


class BackgroundTaskRunner:
    def enqueue(self, task: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        background_task_queue.enqueue(task, *args, **kwargs)
