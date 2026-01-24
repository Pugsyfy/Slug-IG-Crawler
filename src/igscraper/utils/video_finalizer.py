"""
Video finalization utility for converting screenshots to MP4 videos.

This module provides a pure function for generating videos from screenshot sequences,
designed to be unit-testable and non-blocking.
"""
import re
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from igscraper.logger import get_logger

try:
    import imageio
    import imageio_ffmpeg
except ImportError:
    imageio = None
    imageio_ffmpeg = None

logger = get_logger(__name__)


def generate_video_from_screenshots(
    screenshot_dir: Path,
    output_path: Path,
    fps: float = 2.5,
    target_height: int = 640,
) -> bool:
    """
    Generate an MP4 video from WebP screenshots in a directory.

    Args:
        screenshot_dir: Directory containing .webp screenshot files
        output_path: Path where the output MP4 video will be written
        fps: Frames per second for the output video (default: 2.5)
        target_height: Target height in pixels (width auto-scaled, default: 640)

    Returns:
        True if video was successfully generated, False otherwise

    This is a pure function that:
    - Reads all .webp files from screenshot_dir
    - Sorts them lexicographically (timestamped filenames)
    - Resizes frames to target_height (preserving aspect ratio)
    - Writes MP4 (H.264) video to output_path
    - Returns False if < 2 screenshots found
    """
    if imageio is None:
        logger.error("[video_finalizer] imageio not available, cannot generate video")
        return False

    # Find all .webp files
    webp_files = sorted(screenshot_dir.glob("*.webp"))
    
    if len(webp_files) < 2:
        logger.warning(
            f"[video_finalizer] Found {len(webp_files)} screenshots, need at least 2. Skipping video generation."
        )
        return False

    logger.info(f"[video_finalizer] Found {len(webp_files)} screenshots, generating video...")

    try:
        # Read and resize frames
        import numpy as np
        from PIL import Image
        
        frames = []
        for webp_path in webp_files:
            try:
                # Read image using PIL (handles WebP better)
                pil_img = Image.open(str(webp_path))
                
                # Convert to RGB if necessary (WebP might be RGBA)
                if pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")
                
                # Calculate new width preserving aspect ratio
                width, height = pil_img.size
                aspect_ratio = width / height
                new_width = int(target_height * aspect_ratio)
                
                # Resize
                resized = pil_img.resize((new_width, target_height), Image.Resampling.LANCZOS)
                
                # Convert to numpy array for imageio
                frame_array = np.array(resized)
                frames.append(frame_array)
            except Exception as e:
                logger.warning(f"[video_finalizer] Failed to process {webp_path}: {e}")
                continue

        if len(frames) < 2:
            logger.warning(
                f"[video_finalizer] Only {len(frames)} valid frames after processing, need at least 2. Skipping video generation."
            )
            return False

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write video
        logger.info(f"[video_finalizer] Writing video to {output_path} ({len(frames)} frames, {fps} FPS)...")
        imageio.mimwrite(
            str(output_path),
            frames,
            fps=fps,
            codec="libx264",
            quality=8,  # Good quality, reasonable file size
            pixelformat="yuv420p",  # Ensures compatibility
        )
        
        logger.info(f"[video_finalizer] Video generated successfully: {output_path}")
        return True

    except Exception as e:
        logger.error(f"[video_finalizer] Failed to generate video: {e}", exc_info=True)
        return False


def _validate_and_sanitize_bucket_name(bucket_name: str) -> Optional[str]:
    """
    Validate and sanitize a GCS bucket name.
    
    GCS bucket names must:
    - Start and end with a letter or number
    - Contain only lowercase letters, numbers, hyphens, and underscores
    - Be 3-63 characters long
    
    Handles cases where the bucket name might be:
    - A path (e.g., "/app/pugsy_ai_crawled_data" -> "pugsy_ai_crawled_data")
    - Have leading/trailing slashes or whitespace
    - Have invalid characters
    
    Args:
        bucket_name: Raw bucket name from config (may be a path, have whitespace, etc.)
        
    Returns:
        Sanitized bucket name if valid, None if invalid
    """
    if not bucket_name:
        return None
    
    # Strip whitespace
    sanitized = bucket_name.strip()
    
    # Remove gs:// prefix if present
    sanitized = re.sub(r'^gs://', '', sanitized)
    
    # If it looks like a path (contains slashes), extract just the basename
    # This handles cases like "/app/pugsy_ai_crawled_data" -> "pugsy_ai_crawled_data"
    if '/' in sanitized or '\\' in sanitized:
        # Use Path to extract the last component (works for both / and \)
        sanitized = Path(sanitized).name
        # Fallback: if Path.name didn't work, split manually
        if '/' in sanitized:
            sanitized = sanitized.split('/')[-1]
        if '\\' in sanitized:
            sanitized = sanitized.split('\\')[-1]
    
    # Remove any leading/trailing path separators or invalid characters
    sanitized = sanitized.strip('/').strip('\\').strip()
    
    # Convert to lowercase
    sanitized = sanitized.lower()
    
    # Remove any remaining invalid characters (keep only alphanumeric, hyphens, underscores)
    sanitized = re.sub(r'[^a-z0-9_-]', '', sanitized)
    
    # Remove leading/trailing hyphens/underscores (must start/end with letter/number)
    sanitized = sanitized.strip('-_')
    
    # Validate format: must start and end with letter or number
    if not re.match(r'^[a-z0-9][a-z0-9_-]*[a-z0-9]$', sanitized):
        logger.error(f"[video_finalizer] Invalid bucket name format: {bucket_name!r} (sanitized: {sanitized!r})")
        return None
    
    # Validate length (3-63 characters)
    if len(sanitized) < 3 or len(sanitized) > 63:
        logger.error(f"[video_finalizer] Bucket name length invalid: {len(sanitized)} (must be 3-63 characters)")
        return None
    
    return sanitized


def upload_video_to_gcs(
    local_video_path: Path,
    bucket_name: str,
    gcs_object_name: str,
    storage_client=None,
) -> Optional[str]:
    """
    Upload a video file to Google Cloud Storage.

    Args:
        local_video_path: Path to the local video file
        bucket_name: GCS bucket name (will be validated and sanitized)
        gcs_object_name: Object name/path in GCS (e.g., "vid_log/video.mp4")
        storage_client: Optional pre-initialized storage.Client() instance

    Returns:
        GCS URI string (e.g., "gs://bucket/vid_log/video.mp4") on success, None on failure
    """
    try:
        from google.cloud import storage
        
        # Validate and sanitize bucket name
        sanitized_bucket = _validate_and_sanitize_bucket_name(bucket_name)
        if not sanitized_bucket:
            logger.error(f"[video_finalizer] Cannot upload: invalid bucket name: {bucket_name!r}")
            return None
        
        if sanitized_bucket != bucket_name.strip():
            logger.info(f"[video_finalizer] Sanitized bucket name: {bucket_name!r} -> {sanitized_bucket!r}")
        
        if storage_client is None:
            storage_client = storage.Client()

        bucket = storage_client.bucket(sanitized_bucket)
        blob = bucket.blob(gcs_object_name)
        blob.upload_from_filename(str(local_video_path))
        
        gcs_uri = f"gs://{sanitized_bucket}/{gcs_object_name}"
        logger.info(f"[video_finalizer] Uploaded video to GCS: {gcs_uri}")
        return gcs_uri

    except Exception as e:
        logger.error(f"[video_finalizer] Failed to upload video to GCS: {e}", exc_info=True)
        return None


def cleanup_local_files(
    screenshot_dir: Path,
    video_path: Optional[Path] = None,
) -> None:
    """
    Delete local screenshot and video files (best-effort, non-blocking).

    Args:
        screenshot_dir: Directory containing .webp files to delete
        video_path: Optional path to video file to delete
    """
    deleted_screenshots = 0
    deleted_video = False

    try:
        # Delete all .webp files
        for webp_file in screenshot_dir.glob("*.webp"):
            try:
                webp_file.unlink()
                deleted_screenshots += 1
            except Exception as e:
                logger.warning(f"[video_finalizer] Failed to delete {webp_file}: {e}")

        if deleted_screenshots > 0:
            logger.info(f"[video_finalizer] Deleted {deleted_screenshots} screenshot files")

        # Delete video file if provided
        if video_path and video_path.exists():
            try:
                video_path.unlink()
                deleted_video = True
                logger.info(f"[video_finalizer] Deleted local video file: {video_path}")
            except Exception as e:
                logger.warning(f"[video_finalizer] Failed to delete video {video_path}: {e}")

    except Exception as e:
        logger.error(f"[video_finalizer] Error during cleanup: {e}", exc_info=True)


def _sanitize_filename_component(value: str) -> str:
    """
    Sanitize a string to be safe for use in filenames.
    
    Removes path separators and other invalid characters, replacing them with underscores.
    
    Args:
        value: String to sanitize (may contain paths or special characters)
        
    Returns:
        Sanitized string safe for use in filenames
    """
    # Remove leading/trailing path separators and whitespace
    sanitized = value.strip().strip("/").strip("\\")
    # Extract just the basename if it looks like a path
    if '/' in value or '\\' in value:
        sanitized = Path(value).name
    # Replace path separators and invalid filename characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*\s]+', '_', sanitized)
    # Remove multiple consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')
    return sanitized or "unknown"


def generate_video_name(
    mode: int,
    consumer_id: Optional[str],
    profile_name: Optional[str] = None,
    run_name: Optional[str] = None,
) -> Optional[str]:
    """
    Generate a deterministic video filename based on config values.

    Args:
        mode: Scraping mode (1 = PROFILE, 2 = POST)
        consumer_id: Consumer ID from config (may contain paths, will be sanitized)
        profile_name: Profile name (for mode 1, may contain paths, will be sanitized)
        run_name: Run name for URL file (for mode 2, may contain paths, will be sanitized)

    Returns:
        Video filename string (e.g., "profile_consumer1_handle_20250106_120000.mp4") or None if required fields missing
    """
    if not consumer_id:
        logger.error("[video_finalizer] consumer_id is required for video naming")
        return None

    # Sanitize all inputs to remove path separators and invalid characters
    consumer_id_safe = _sanitize_filename_component(consumer_id)

    # Generate UTC timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if mode == 1:
        # PROFILE mode
        if not profile_name:
            logger.error("[video_finalizer] profile_name is required for PROFILE mode")
            return None
        profile_name_safe = _sanitize_filename_component(profile_name)
        return f"profile_{consumer_id_safe}_{profile_name_safe}_{timestamp}.mp4"
    
    elif mode == 2:
        # POST mode
        if not run_name:
            logger.error("[video_finalizer] run_name_for_url_file is required for POST mode")
            return None
        run_name_safe = _sanitize_filename_component(run_name)
        return f"post_{consumer_id_safe}_{run_name_safe}_{timestamp}.mp4"
    
    else:
        logger.error(f"[video_finalizer] Unknown mode: {mode}")
        return None

