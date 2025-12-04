from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional, Tuple
import logging
from pathlib import Path

from google.cloud import storage 
from igscraper.services.enqueue_client import FileEnqueuer

from igscraper.services.sorter import sort_jsonl_folder

logger = logging.getLogger(__name__)


@dataclass
class GcsUploadConfig:
    bucket_name: str
    # Marker in local path after which the relative path is kept.
    # Example:
    #   local_path  = /mnt/shared/outputs/20251012/creator_handle/posts_entity_2023101201.jsonl
    #   marker      = "/outputs/"
    #   object_name = "20251012/creator_handle/posts_entity_2023101201.jsonl"
    outputs_marker: str = "/outputs/"


class UploadAndEnqueue:
    """
    Small helper:

        local_path -> (optional sort) -> GCS upload -> enqueue_file(kind, gcs_uri)

    Integration notes:
    - If `sort_before_upload` is True, we call sort_jsonl_folder on the file's parent
      directory with a single-pattern of the filename (non-recursive). That writes
      `<name>_sorted.jsonl` next to the original file.
    - If sorting succeeds, we upload the sorted file. If sorting fails and
      `fail_on_sort_error` is True, we raise; otherwise we fall back to the original.
    """

    def __init__(
        self,
        gcs_config: GcsUploadConfig,
        enqueuer: FileEnqueuer,
        storage_client: Optional[storage.Client] = None,
    ) -> None:
        self._cfg = gcs_config
        self._enqueuer = enqueuer
        self._storage_client = storage_client or storage.Client()
        logger.info("[upload_enqueue] Initialized with bucket: %s", self._cfg.bucket_name)

    def upload_and_enqueue(
        self,
        *,
        local_path: str,
        kind: Literal["post", "comment"],
        sort_before_upload: bool = True,
        fail_on_sort_error: bool = True,
        sort_key: str = "timestamp",
        use_json5: Optional[bool] = None,
    ) -> str:
        """
        1. Optionally sort the local file (writes <name>_sorted.jsonl next to it).
        2. Derive GCS object name from the file actually uploaded.
        3. Upload file to GCS.
        4. Enqueue file path (gs://...).
        5. Return the gs:// URI.

        Args:
            local_path: local filename to upload
            kind: "post" or "comment" for enqueuer
            sort_before_upload: if True, attempt to sort file first (in-place write of _sorted.jsonl)
            fail_on_sort_error: if True, raise when sorting fails; if False, proceed with original file
            sort_key: key to sort by (passed to sorter)
            use_json5: control json5 usage (None = auto)
        """
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        to_upload_path = path  # default - may be swapped to sorted file

        if sort_before_upload:
            try:
                # Sort only the single file (non-recursive, pattern = filename)
                logger.info("[upload_enqueue] Sorting before upload: %s", local_path)
                summary = sort_jsonl_folder(
                    path.parent,
                    key=sort_key,
                    patterns=[path.name],
                    recursive=False,
                    dry_run=False,
                    use_json5=use_json5,
                    logger=logger,
                )

                # If sorter wrote a sorted file, prefer it.
                sorted_name = f"{path.stem}_sorted.jsonl"
                candidate = path.with_name(sorted_name)
                if candidate.exists() and summary.get("sorted", 0) > 0:
                    logger.info("[upload_enqueue] Using sorted file: %s", str(candidate))
                    to_upload_path = candidate
                else:
                    # No sorted output produced; decide behaviour
                    logger.warning(
                        "[upload_enqueue] Sort finished but sorted file not found or zero sorted records; "
                        "falling back to original file: %s", str(path)
                    )

            except Exception as e:
                logger.exception("[upload_enqueue] Sorting failed for %s: %s", local_path, e)
                if fail_on_sort_error:
                    raise
                logger.warning("[upload_enqueue] Proceeding with original file despite sort error: %s", local_path)
                to_upload_path = path

        # Build GCS URI for the file we will upload
        gcs_uri, object_name = self._build_gcs_uri(str(to_upload_path))

        # Upload
        self._upload_to_gcs(local_path=str(to_upload_path), object_name=object_name)

        # Enqueue the GCS uri
        self._enqueuer.enqueue_file(kind=kind, file_path=gcs_uri)
        logger.info("[upload_enqueue] Enqueued %s -> %s", str(to_upload_path), gcs_uri)
        return gcs_uri

    # ---------- internals ---------- #

    def _build_gcs_uri(self, local_path: str) -> Tuple[str, str]:
        marker = self._cfg.outputs_marker
        idx = local_path.find(marker)
        if idx == -1:
            raise ValueError(
                f"outputs_marker '{marker}' not found in path: {local_path}"
            )

        rel = local_path[idx + len(marker) :].lstrip(os.sep)
        if not rel:
            raise ValueError(f"Cannot derive GCS object name from path: {local_path}")

        object_name = rel.replace(os.sep, "/")
        gcs_uri = f"gs://{self._cfg.bucket_name}/{object_name}"
        return gcs_uri, object_name

    def _upload_to_gcs(self, *, local_path: str, object_name: str) -> None:
        try:
            bucket = self._storage_client.bucket(self._cfg.bucket_name)
            blob = bucket.blob(object_name)
            blob.upload_from_filename(local_path)
            logger.info("[upload_enqueue] Uploaded file to GCS: %s", f"gs://{self._cfg.bucket_name}/{object_name}")
        except Exception as e:
            logger.error(f"[upload_enqueue] Failed to upload {local_path} to GCS: {e}")
            raise
