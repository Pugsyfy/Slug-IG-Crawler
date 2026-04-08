"""Tests for thor_worker_id propagation in igscraper.

Tests config validation, pipeline initialization, logging, and SQL inserts.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import toml

# Adjust path to import from src
import sys
src_path = Path(__file__).resolve().parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

try:
    from pydantic import ValidationError
    from igscraper.config import load_config, Config, TraceConfig
    from igscraper.services.enqueue_client import FileEnqueuer, PostgresConfig

    import igscraper.pipeline  # noqa: F401 — registers igscraper.pipeline for @patch("igscraper.pipeline.…")
except ImportError:
    # If running from different path, adjust imports
    import sys
    src_path = Path(__file__).resolve().parent.parent.parent.parent
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path / "src"))
    from pydantic import ValidationError  # noqa: F401
    from igscraper.config import load_config, Config, TraceConfig
    from igscraper.services.enqueue_client import FileEnqueuer, PostgresConfig
    import igscraper.pipeline  # noqa: F401


class TestPushToGcsConfigValidation(unittest.TestCase):
    """load_config: [main].push_to_gcs must be 0 or 1."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.config_path = self.test_dir / "test_config.toml"

    def tearDown(self):
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def _base_config(self, push_to_gcs):
        return {
            "main": {
                "target_profiles": [{"name": "testuser", "num_posts": 10}],
                "push_to_gcs": push_to_gcs,
            },
            "data": {
                "output_dir": "outputs",
                "shot_dir": "shots",
                "posts_path": "posts.txt",
                "metadata_path": "metadata.jsonl",
                "skipped_path": "skipped.txt",
                "tmp_path": "tmp.jsonl",
                "cookie_file": "cookie.json",
                "media_path": "media",
                "schema_path": "schema.yaml",
                "models_path": "models.jsonl",
                "extracted_data_path": "extracted.jsonl",
                "graphql_keys_path": "keys.jsonl",
                "profile_page_data_key": ["key1"],
                "post_page_data_key": ["key2"],
                "post_entity_path": "post_entity.jsonl",
                "profile_path": "profile.jsonl",
            },
            "logging": {
                "level": "INFO",
                "log_dir": "logs",
                "log_format": "%(message)s",
                "date_format": "%Y-%m-%d",
            },
            "trace": {"thor_worker_id": "w1"},
        }

    def test_push_to_gcs_zero_loads(self):
        with open(self.config_path, "w") as f:
            toml.dump(self._base_config(0), f)
        cfg = load_config(str(self.config_path))
        self.assertEqual(cfg.main.push_to_gcs, 0)

    def test_push_to_gcs_one_loads(self):
        with open(self.config_path, "w") as f:
            toml.dump(self._base_config(1), f)
        cfg = load_config(str(self.config_path))
        self.assertEqual(cfg.main.push_to_gcs, 1)

    def test_push_to_gcs_invalid_raises(self):
        with open(self.config_path, "w") as f:
            toml.dump(self._base_config(2), f)
        with self.assertRaises(ValidationError):
            load_config(str(self.config_path))


class TestTraceConfigValidation(unittest.TestCase):
    """Test that config validation requires [trace].thor_worker_id."""
    
    def setUp(self):
        """Set up temporary test files."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.config_path = self.test_dir / "test_config.toml"
        
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def _create_config_file(self, config_data):
        """Helper to create a config file."""
        with open(self.config_path, "w") as f:
            toml.dump(config_data, f)
    
    def test_config_with_trace_section_success(self):
        """Test that config loads successfully when [trace] section exists."""
        config_data = {
            "main": {
                "target_profiles": [{"name": "testuser", "num_posts": 10}],
                "consumer_id": "test_consumer"
            },
            "data": {
                "output_dir": "outputs",
                "shot_dir": "shots",
                "posts_path": "posts.txt",
                "metadata_path": "metadata.jsonl",
                "skipped_path": "skipped.txt",
                "tmp_path": "tmp.jsonl",
                "cookie_file": "cookie.json",
                "media_path": "media",
                "schema_path": "schema.yaml",
                "models_path": "models.jsonl",
                "extracted_data_path": "extracted.jsonl",
                "graphql_keys_path": "keys.jsonl",
                "profile_page_data_key": ["key1"],
                "post_page_data_key": ["key2"],
                "post_entity_path": "post_entity.jsonl",
                "profile_path": "profile.jsonl"
            },
            "logging": {
                "level": "INFO",
                "log_dir": "logs",
                "log_format": "%(message)s",
                "date_format": "%Y-%m-%d"
            },
            "trace": {
                "thor_worker_id": "worker-test-123"
            }
        }
        self._create_config_file(config_data)
        
        config = load_config(str(self.config_path))
        
        self.assertIsInstance(config, Config)
        self.assertIsInstance(config.trace, TraceConfig)
        self.assertEqual(config.trace.thor_worker_id, "worker-test-123")
    
    def test_config_missing_trace_section_gets_placeholder(self):
        """Missing [trace] is satisfied with a placeholder so loaders can parse; Pipeline validates later."""
        config_data = {
            "main": {
                "target_profiles": [{"name": "testuser", "num_posts": 10}],
            },
            "data": {
                "output_dir": "outputs",
                "shot_dir": "shots",
                "posts_path": "posts.txt",
                "metadata_path": "metadata.jsonl",
                "skipped_path": "skipped.txt",
                "tmp_path": "tmp.jsonl",
                "cookie_file": "cookie.json",
                "media_path": "media",
                "schema_path": "schema.yaml",
                "models_path": "models.jsonl",
                "extracted_data_path": "extracted.jsonl",
                "graphql_keys_path": "keys.jsonl",
                "profile_page_data_key": ["key1"],
                "post_page_data_key": ["key2"],
                "post_entity_path": "post_entity.jsonl",
                "profile_path": "profile.jsonl"
            },
            "logging": {
                "level": "INFO",
                "log_dir": "logs",
                "log_format": "%(message)s",
                "date_format": "%Y-%m-%d"
            }
        }
        self._create_config_file(config_data)

        config = load_config(str(self.config_path))
        self.assertEqual(config.trace.thor_worker_id, "not-validated-yet")
    
    def test_config_missing_thor_worker_id_fails(self):
        """Empty [trace] cannot satisfy TraceConfig (thor_worker_id required)."""
        config_data = {
            "main": {
                "target_profiles": [{"name": "testuser", "num_posts": 10}],
            },
            "data": {
                "output_dir": "outputs",
                "shot_dir": "shots",
                "posts_path": "posts.txt",
                "metadata_path": "metadata.jsonl",
                "skipped_path": "skipped.txt",
                "tmp_path": "tmp.jsonl",
                "cookie_file": "cookie.json",
                "media_path": "media",
                "schema_path": "schema.yaml",
                "models_path": "models.jsonl",
                "extracted_data_path": "extracted.jsonl",
                "graphql_keys_path": "keys.jsonl",
                "profile_page_data_key": ["key1"],
                "post_page_data_key": ["key2"],
                "post_entity_path": "post_entity.jsonl",
                "profile_path": "profile.jsonl"
            },
            "logging": {
                "level": "INFO",
                "log_dir": "logs",
                "log_format": "%(message)s",
                "date_format": "%Y-%m-%d"
            },
            "trace": {}
        }
        self._create_config_file(config_data)

        with self.assertRaises(ValidationError):
            load_config(str(self.config_path))
    
    def test_config_empty_thor_worker_id_fails(self):
        """Empty or whitespace-only thor_worker_id: load_config may succeed; Pipeline rejects."""
        from igscraper.pipeline import Pipeline

        for empty_value in ['', '   ', '\t\n']:
            config_data = {
                "main": {
                    "target_profiles": [{"name": "testuser", "num_posts": 10}],
                },
                "data": {
                    "output_dir": "outputs",
                    "shot_dir": "shots",
                    "posts_path": "posts.txt",
                    "metadata_path": "metadata.jsonl",
                    "skipped_path": "skipped.txt",
                    "tmp_path": "tmp.jsonl",
                    "cookie_file": "cookie.json",
                    "media_path": "media",
                    "schema_path": "schema.yaml",
                    "models_path": "models.jsonl",
                    "extracted_data_path": "extracted.jsonl",
                    "graphql_keys_path": "keys.jsonl",
                    "profile_page_data_key": ["key1"],
                    "post_page_data_key": ["key2"],
                    "post_entity_path": "post_entity.jsonl",
                    "profile_path": "profile.jsonl"
                },
                "logging": {
                    "level": "INFO",
                    "log_dir": "logs",
                    "log_format": "%(message)s",
                    "date_format": "%Y-%m-%d"
                },
                "trace": {
                    "thor_worker_id": empty_value
                }
            }
            self._create_config_file(config_data)

            try:
                load_config(str(self.config_path))
            except ValidationError:
                continue

            with self.assertRaises(ValueError) as context:
                Pipeline(str(self.config_path))
            self.assertIn("thor_worker_id", str(context.exception).lower())


class TestPipelineInitialization(unittest.TestCase):
    """Test that Pipeline stores thor_worker_id correctly."""
    
    def setUp(self):
        """Set up temporary test files."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.config_path = self.test_dir / "test_config.toml"
        
        config_data = {
            "main": {
                "target_profiles": [{"name": "testuser", "num_posts": 10}],
            },
            "data": {
                "output_dir": "outputs",
                "shot_dir": "shots",
                "posts_path": "posts.txt",
                "metadata_path": "metadata.jsonl",
                "skipped_path": "skipped.txt",
                "tmp_path": "tmp.jsonl",
                "cookie_file": "cookie.json",
                "media_path": "media",
                "schema_path": "schema.yaml",
                "models_path": "models.jsonl",
                "extracted_data_path": "extracted.jsonl",
                "graphql_keys_path": "keys.jsonl",
                "profile_page_data_key": ["key1"],
                "post_page_data_key": ["key2"],
                "post_entity_path": "post_entity.jsonl",
                "profile_path": "profile.jsonl"
            },
            "logging": {
                "level": "INFO",
                "log_dir": "logs",
                "log_format": "%(message)s",
                "date_format": "%Y-%m-%d"
            },
            "trace": {
                "thor_worker_id": "worker-pipeline-789"
            }
        }
        
        with open(self.config_path, "w") as f:
            toml.dump(config_data, f)
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    @patch('igscraper.pipeline.SeleniumBackend')
    @patch('igscraper.pipeline.GraphQLModelRegistry')
    def test_pipeline_stores_thor_worker_id(self, mock_registry, mock_backend_class):
        """Test that Pipeline stores thor_worker_id from config."""
        from igscraper.pipeline import Pipeline

        mock_backend_instance = MagicMock()
        mock_backend_class.return_value = mock_backend_instance
        mock_registry.return_value = MagicMock()

        pipeline = Pipeline(str(self.config_path))
        
        # Verify thor_worker_id is stored
        self.assertEqual(pipeline.thor_worker_id, "worker-pipeline-789")
        
        # Verify it's set on backend
        self.assertEqual(pipeline.backend.thor_worker_id, "worker-pipeline-789")
        
        # Verify it's set on FileEnqueuer
        self.assertEqual(pipeline.backend._enqueuer.thor_worker_id, "worker-pipeline-789")


class TestFileEnqueuerThorWorkerId(unittest.TestCase):
    """Test FileEnqueuer thor_worker_id handling."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.pg_config = PostgresConfig(
            host="localhost",
            port=5432,
            user="test_user",
            password="test_pass",
            database="test_db"
        )
    
    @patch('igscraper.services.enqueue_client.psycopg.connect')
    def test_enqueue_file_includes_thor_worker_id(self, mock_connect):
        """Test that enqueue_file includes thor_worker_id in INSERT."""
        enqueuer = FileEnqueuer(self.pg_config)
        enqueuer.thor_worker_id = "worker-enqueue-456"
        
        # Mock database connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        
        enqueuer.enqueue_file(kind="post", file_path="gs://bucket/file.jsonl")
        
        # Verify SQL was called with thor_worker_id
        mock_cur.execute.assert_called_once()
        call_args = mock_cur.execute.call_args
        
        # Check SQL includes thor_worker_id column
        sql = call_args[0][0]
        self.assertIn("thor_worker_id", sql)
        self.assertIn("INSERT INTO", sql)
        self.assertIn("crawled_posts", sql)
        
        # Check params include thor_worker_id
        params = call_args[0][1]
        self.assertEqual(len(params), 5)  # file_path, created_at, is_ingested, ingest_attempts, thor_worker_id
        self.assertEqual(params[4], "worker-enqueue-456")  # thor_worker_id is last param
    
    @patch('igscraper.services.enqueue_client.psycopg.connect')
    def test_enqueue_file_missing_thor_worker_id_raises(self, mock_connect):
        """Test that missing thor_worker_id raises RuntimeError."""
        enqueuer = FileEnqueuer(self.pg_config)
        # Don't set thor_worker_id (or set to None/empty)
        
        for bad_value in [None, '', '   ']:
            enqueuer.thor_worker_id = bad_value
            
            with self.assertRaises(RuntimeError) as context:
                enqueuer.enqueue_file(kind="comment", file_path="gs://bucket/file.jsonl")
            
            self.assertIn("thor_worker_id", str(context.exception).lower())
            exception_msg = str(context.exception).lower()
            self.assertTrue("missing" in exception_msg or "empty" in exception_msg)
    
    @patch('igscraper.services.enqueue_client.psycopg.connect')
    def test_enqueue_file_comment_table(self, mock_connect):
        """Test that comments use crawled_comments table."""
        enqueuer = FileEnqueuer(self.pg_config)
        enqueuer.thor_worker_id = "worker-comment-789"
        
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        
        enqueuer.enqueue_file(kind="comment", file_path="gs://bucket/comments.jsonl")
        
        # Verify SQL uses crawled_comments table
        call_args = mock_cur.execute.call_args
        sql = call_args[0][0]
        self.assertIn("crawled_comments", sql)
        self.assertNotIn("crawled_posts", sql)
        
        # Verify thor_worker_id is included
        params = call_args[0][1]
        self.assertEqual(params[4], "worker-comment-789")


class TestLoggingThorWorkerId(unittest.TestCase):
    """Test that logging includes thor_worker_id."""
    
    def setUp(self):
        """Set up temporary test files."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.config_path = self.test_dir / "test_config.toml"
        
        config_data = {
            "main": {
                "target_profiles": [{"name": "testuser", "num_posts": 10}],
            },
            "data": {
                "output_dir": "outputs",
                "shot_dir": "shots",
                "posts_path": "posts.txt",
                "metadata_path": "metadata.jsonl",
                "skipped_path": "skipped.txt",
                "tmp_path": "tmp.jsonl",
                "cookie_file": "cookie.json",
                "media_path": "media",
                "schema_path": "schema.yaml",
                "models_path": "models.jsonl",
                "extracted_data_path": "extracted.jsonl",
                "graphql_keys_path": "keys.jsonl",
                "profile_page_data_key": ["key1"],
                "post_page_data_key": ["key2"],
                "post_entity_path": "post_entity.jsonl",
                "profile_path": "profile.jsonl"
            },
            "logging": {
                "level": "INFO",
                "log_dir": "logs",
                "log_format": "%(message)s",
                "date_format": "%Y-%m-%d"
            },
            "trace": {
                "thor_worker_id": "worker-log-999"
            }
        }
        
        with open(self.config_path, "w") as f:
            toml.dump(config_data, f)
    
    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    @patch('igscraper.pipeline.SeleniumBackend')
    @patch('igscraper.pipeline.GraphQLModelRegistry')
    @patch('igscraper.pipeline.logger')
    def test_timing_log_includes_thor_worker_id(self, mock_logger, mock_registry, mock_backend_class):
        """Test that timing logs include thor_worker_id."""
        from igscraper.pipeline import Pipeline

        mock_backend_instance = MagicMock()
        mock_backend_class.return_value = mock_backend_instance
        mock_registry.return_value = MagicMock()

        pipeline = Pipeline(str(self.config_path))
        
        # Call _emit_timing_log
        pipeline._emit_timing_log(
            event="pipeline_total_time",
            category="creator_profile",
            creator_handle="testuser",
            content_id=None,
            duration_ms=1000,
            status="success",
            error_type=None
        )
        
        # Verify logger.info was called
        mock_logger.info.assert_called()
        
        # Get the log entry (last call, first arg)
        log_call = mock_logger.info.call_args[0][0]
        log_data = json.loads(log_call)
        
        # Verify thor_worker_id is present
        self.assertIn("thor_worker_id", log_data)
        self.assertEqual(log_data["thor_worker_id"], "worker-log-999")


if __name__ == '__main__':
    unittest.main()

