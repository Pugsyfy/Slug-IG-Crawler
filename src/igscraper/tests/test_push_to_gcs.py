"""Tests for UploadAndEnqueue when [main].push_to_gcs is 0 vs 1.

Config validation for push_to_gcs lives in test_thor_worker_id (same import stack as load_config).
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

src_path = Path(__file__).resolve().parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from igscraper.services.enqueue_client import FileEnqueuer, PostgresConfig
from igscraper.services.upload_enqueue import GcsUploadConfig, UploadAndEnqueue


class TestUploadAndEnqueuePushToGcs(unittest.TestCase):
    def setUp(self):
        self.pg = PostgresConfig(
            host="localhost",
            port=5432,
            user="u",
            password="p",
            database="d",
        )
        self.enqueuer = FileEnqueuer(self.pg)
        self.enqueuer.thor_worker_id = "test-worker"

    def test_push_to_gcs_zero_enqueues_absolute_local_path_no_gcs_client_in_init(self):
        with patch("igscraper.services.upload_enqueue.storage.Client") as client_cls:
            gcs_cfg = GcsUploadConfig(bucket_name="my-bucket")
            uploader = UploadAndEnqueue(
                gcs_cfg,
                self.enqueuer,
                push_to_gcs=0,
            )
            client_cls.assert_not_called()

        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        local_file = Path(tmp) / "anywhere" / "batch.jsonl"
        local_file.parent.mkdir(parents=True)
        local_file.write_text("{}\n", encoding="utf-8")

        calls = []

        def capture_enqueue(*, kind, file_path, created_at=None):
            calls.append((kind, file_path))

        self.enqueuer.enqueue_file = capture_enqueue

        out = uploader.upload_and_enqueue(
            local_path=str(local_file),
            kind="post",
            sort_before_upload=False,
        )
        self.assertEqual(out, str(local_file.resolve()))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "post")
        self.assertEqual(calls[0][1], str(local_file.resolve()))

    def test_push_to_gcs_one_uploads_and_enqueues_gs_uri(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        outputs_dir = Path(tmp) / "outputs" / "20250101" / "user"
        outputs_dir.mkdir(parents=True)
        local_file = outputs_dir / "posts.jsonl"
        local_file.write_text('{"x":1}\n', encoding="utf-8")

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        gcs_cfg = GcsUploadConfig(bucket_name="my-bucket")
        uploader = UploadAndEnqueue(
            gcs_cfg,
            self.enqueuer,
            storage_client=mock_client,
            push_to_gcs=1,
        )

        calls = []

        def capture_enqueue(*, kind, file_path, created_at=None):
            calls.append(file_path)

        self.enqueuer.enqueue_file = capture_enqueue

        out = uploader.upload_and_enqueue(
            local_path=str(local_file),
            kind="post",
            sort_before_upload=False,
        )

        self.assertTrue(out.startswith("gs://my-bucket/"))
        mock_blob.upload_from_filename.assert_called_once()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("gs://my-bucket/"))


if __name__ == "__main__":
    unittest.main()
