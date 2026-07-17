from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote


class OverlapLock(Protocol):
    def acquire(self) -> bool: ...

    def release(self) -> None: ...


class NoopLock:
    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        return None


@dataclass
class AzureBlobLeaseLock:
    container_url: str
    job_id: str
    lease_duration: int = 60
    renew_interval: int = 30
    _lease: object | None = field(default=None, init=False, repr=False)
    _stop_renewal: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _renewal_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _renewal_error: BaseException | None = field(default=None, init=False, repr=False)

    def acquire(self) -> bool:
        from azure.core.exceptions import HttpResponseError, ResourceExistsError
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobClient

        blob_url = f"{self.container_url.rstrip('/')}/{quote(self.job_id, safe='')}"
        blob = BlobClient.from_blob_url(blob_url, credential=DefaultAzureCredential())
        try:
            blob.upload_blob(b"", overwrite=False)
        except ResourceExistsError:
            pass

        try:
            lease = blob.acquire_lease(lease_duration=self.lease_duration)
        except HttpResponseError as error:
            if error.status_code == 409:
                return False
            raise

        self._lease = lease
        self._stop_renewal.clear()
        self._renewal_thread = threading.Thread(
            target=self._renew_lease,
            name=f"lease-renewal-{self.job_id}",
            daemon=True,
        )
        self._renewal_thread.start()
        return True

    def _renew_lease(self) -> None:
        while not self._stop_renewal.wait(self.renew_interval):
            try:
                self._lease.renew()
            except BaseException as error:
                self._renewal_error = error
                return

    def release(self) -> None:
        self._stop_renewal.set()
        if self._renewal_thread is not None:
            self._renewal_thread.join(timeout=self.renew_interval)
        if self._lease is not None:
            self._lease.release()
        if self._renewal_error is not None:
            raise RuntimeError("Blob lease renewal failed") from self._renewal_error


def lock_from_environment() -> OverlapLock:
    container_url = os.environ.get("BATCHJOBS_LOCK_CONTAINER_URL")
    if not container_url:
        return NoopLock()

    job_id = os.environ.get("BATCHJOBS_JOB_ID")
    if not job_id:
        raise RuntimeError("BATCHJOBS_JOB_ID is required when overlap locking is enabled")
    return AzureBlobLeaseLock(container_url=container_url, job_id=job_id)
