"""Run Pocket Recall's shared background service."""

import fcntl
import logging
import os
import socketserver
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import RLock, Thread, Timer
from typing import Any

from pocket_recall.config import MemoryConfig
from pocket_recall.errors import (
    ConcurrentUpdateError,
    EmbeddingError,
    MemoryLookupError,
)
from pocket_recall.storage.memory_store import MemoryStore
from pocket_recall.transport.operation_dispatcher import OperationDispatcher
from pocket_recall.transport.service_protocol import (
    decode_message,
    encode_message,
    error_message,
    success_message,
    validate_request,
)

logger = logging.getLogger(__name__)
INDEX_BATCH_SIZE = 100
SERVICE_LOG_MAX_BYTES = 1_000_000
SERVICE_LOG_BACKUP_COUNT = 2


class _ConcurrentUnixSocketServer(socketserver.UnixStreamServer):
    """Run socket requests with a fixed number of worker threads."""

    def __init__(self, socket_path: Path, handler: type[socketserver.StreamRequestHandler], workers: int) -> None:
        self.worker_pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pocket-recall-request")
        super().__init__(str(socket_path), handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        self.worker_pool.submit(self._process_request, request, client_address)

    def _process_request(self, request: Any, client_address: Any) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self) -> None:
        super().server_close()
        self.worker_pool.shutdown(wait=True, cancel_futures=True)

    def handle_error(self, request: Any, client_address: Any) -> None:
        logger.exception("Request handler failed")


class _ServiceRequestHandler(socketserver.StreamRequestHandler):
    """Read one JSON request and return one JSON response."""

    def handle(self) -> None:
        daemon: PocketRecallService = self.server.daemon_owner  # type: ignore[attr-defined]
        line = self.rfile.readline(daemon.config.max_socket_request_bytes + 1)
        if len(line) > daemon.config.max_socket_request_bytes or not line.endswith(b"\n"):
            self.wfile.write(encode_message(error_message("unknown", "invalid_request", "Request is too large")))
            return
        request_id = "unknown"
        try:
            message = decode_message(line)
            supplied_id = message.get("request_id")
            if isinstance(supplied_id, str) and supplied_id:
                request_id = supplied_id
            request_id, operation, arguments = validate_request(message)
            logger.info("request_id=%s operation=%s", request_id, operation)
            result = daemon.dispatcher.dispatch(operation, arguments)
            response = success_message(request_id, result)
        except ValueError as error:
            response = error_message(request_id, "invalid_request", str(error))
        except MemoryLookupError as error:
            response = error_message(request_id, "not_found", str(error))
        except ConcurrentUpdateError as error:
            response = error_message(request_id, "conflict", str(error))
        except EmbeddingError as error:
            response = error_message(request_id, "unavailable", str(error))
        except (OSError, sqlite3.Error) as error:
            response = error_message(request_id, "unavailable", str(error))
        except Exception:
            logger.exception("request_id=%s failed", request_id)
            response = error_message(request_id, "internal_error", "Internal service error")
        self.wfile.write(encode_message(response))


class PocketRecallService:
    """Keep one shared store and embedding model available to local clients."""

    def __init__(self, config: MemoryConfig | None = None) -> None:
        self.config = config or MemoryConfig()
        self.store = MemoryStore(self.config)
        self.dispatcher = OperationDispatcher(
            self.store,
            index_changed=self.schedule_index_retries,
            stop_service=self.request_stop,
        )
        self._server: _ConcurrentUnixSocketServer | None = None
        self._lock_file: Any = None
        self._retry_timer: Timer | None = None
        self._retry_lock = RLock()

    def serve_forever(self) -> bool:
        self.config.data_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._acquire_service_lock():
            return False
        try:
            self._configure_logging()
            self._remove_stale_socket()
            self._server = _ConcurrentUnixSocketServer(
                self.config.service_socket, _ServiceRequestHandler, self.config.max_concurrent_requests
            )
            self._server.daemon_owner = self  # type: ignore[attr-defined]
            os.chmod(self.config.service_socket, 0o600)
            logger.info("Pocket Recall service started pid=%s", os.getpid())
            self._schedule_retry(immediate=True)
            self._server.serve_forever(poll_interval=0.2)
            return True
        finally:
            self.close()

    def request_stop(self) -> None:
        if self._server is not None:
            Thread(target=self._server.shutdown, name="pocket-recall-stop", daemon=True).start()

    def schedule_index_retries(self) -> None:
        try:
            if not self.store.index_update_pending():
                return
        except (OSError, sqlite3.Error, ValueError):
            pass
        self._schedule_retry(immediate=False)

    def _schedule_retry(self, *, immediate: bool, next_delay: int = 0) -> None:
        with self._retry_lock:
            if self._retry_timer is not None:
                self._retry_timer.cancel()
            delay = 0 if immediate else self.config.index_retry_delays_seconds[next_delay]
            following_delay = next_delay if immediate else next_delay + 1
            self._retry_timer = Timer(delay, self._retry_pending_index, args=(following_delay,))
            self._retry_timer.daemon = True
            self._retry_timer.start()

    def _retry_pending_index(self, next_delay: int) -> None:
        try:
            if not self.config.memory_database.is_file() or not self.config.search_database.is_file():
                return
            while self.store.index_synchronizer.synchronize(limit=INDEX_BATCH_SIZE) == INDEX_BATCH_SIZE:
                pass
            if not self.store.index_update_pending():
                return
        except (OSError, sqlite3.Error, ValueError, EmbeddingError) as error:
            logger.warning("Search index retry failed: %s", error)
        if next_delay < len(self.config.index_retry_delays_seconds):
            logger.info(
                "Search index retry scheduled in %s seconds", self.config.index_retry_delays_seconds[next_delay]
            )
            self._schedule_retry(immediate=False, next_delay=next_delay)

    def _acquire_service_lock(self) -> bool:
        descriptor = os.open(self.config.service_lock, os.O_CREAT | os.O_RDWR, 0o600)
        lock_file = os.fdopen(descriptor, "r+")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            return False
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        os.chmod(self.config.service_lock, 0o600)
        self._lock_file = lock_file
        return True

    def _remove_stale_socket(self) -> None:
        try:
            self.config.service_socket.unlink()
        except FileNotFoundError:
            pass

    def _configure_logging(self) -> None:
        handler = RotatingFileHandler(
            self.config.service_log,
            maxBytes=SERVICE_LOG_MAX_BYTES,
            backupCount=SERVICE_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        os.chmod(self.config.service_log, 0o600)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    def close(self) -> None:
        with self._retry_lock:
            if self._retry_timer is not None:
                self._retry_timer.cancel()
                self._retry_timer = None
        self.store.model_lifecycle_manager.close()
        if self._server is not None:
            self._server.server_close()
            self._server = None
        self._remove_stale_socket()
        if self._lock_file is not None:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
        logger.info("Pocket Recall service stopped")
