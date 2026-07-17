import time
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import HttpResponseError

from batchjobs_runner.overlap import AzureBlobLeaseLock


class AzureBlobLeaseLockTests(unittest.TestCase):
    @patch("azure.identity.DefaultAzureCredential")
    @patch("azure.storage.blob.BlobClient.from_blob_url")
    def test_existing_lease_returns_not_acquired(self, from_blob_url, credential):
        blob = from_blob_url.return_value
        response = Mock()
        response.status_code = 409
        blob.acquire_lease.side_effect = HttpResponseError(response=response)
        overlap_lock = AzureBlobLeaseLock(
            "https://locks.blob.core.windows.net/job-locks", "pilot-job"
        )

        acquired = overlap_lock.acquire()

        self.assertFalse(acquired)
        from_blob_url.assert_called_once_with(
            "https://locks.blob.core.windows.net/job-locks/pilot-job",
            credential=credential.return_value,
        )

    @patch("azure.identity.DefaultAzureCredential")
    @patch("azure.storage.blob.BlobClient.from_blob_url")
    def test_acquired_lease_is_renewed_and_released(self, from_blob_url, _credential):
        lease = Mock()
        from_blob_url.return_value.acquire_lease.return_value = lease
        overlap_lock = AzureBlobLeaseLock(
            "https://locks.blob.core.windows.net/job-locks",
            "pilot-job",
            renew_interval=0.01,
        )

        self.assertTrue(overlap_lock.acquire())
        time.sleep(0.03)
        overlap_lock.release()

        lease.renew.assert_called()
        lease.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()