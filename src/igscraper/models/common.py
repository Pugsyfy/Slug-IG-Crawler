from __future__ import annotations
from typing import Optional, List, Dict, Any, Type, Union, Pattern
from pydantic import BaseModel, TypeAdapter
import json
import re
from igscraper.logger import get_logger

logger = get_logger(__name__)


class BaseFlexibleSafeModel(BaseModel):
    """
    Flexible + safe Pydantic base model for v2:
      • Allows unknown fields
      • Tracks invalid fields in .extra_invalid (only if non-empty)
      • Tracks unknown fields in .extras (only if non-empty)
      • Logs type mismatches instead of raising
      • Recursively validates nested models and lists
      • Compatible with old parse_obj() and model_dump()
    """

    extras: Dict[str, Any] = {}
    extra_invalid: Dict[str, Dict[str, Any]] = {}

    # --- Old BaseFlexibleModel compatibility ---
    @classmethod
    def parse_obj(cls, obj: Any):
        if not isinstance(obj, dict):
            return TypeAdapter(cls).validate_python(obj)
        return cls.model_validate(obj)

    def model_dump(self):
        """
        Return the model dict without empty 'extras' or 'extra_invalid'.
        """
        data = self.__dict__.copy()
        if not data.get("extras"):
            data.pop("extras", None)
        if not data.get("extra_invalid"):
            data.pop("extra_invalid", None)
        return data

    # --- Validation logic ---
    @classmethod
    def model_validate(cls, data: Any, **kwargs):
        if not isinstance(data, dict):
            return super().model_validate(data, **kwargs)

        valid_fields: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        extra_invalid: Dict[str, Dict[str, Any]] = {}

        for key, value in data.items():
            if key not in cls.model_fields:
                extras[key] = value
                continue

            field_info = cls.model_fields[key]
            expected_type = str(field_info.annotation)

            try:
                # Validate field value using TypeAdapter in Pydantic v2
                adapter = TypeAdapter(field_info.annotation)
                validated_value = adapter.validate_python(value)

                # Recursively re-validate nested models/lists
                if isinstance(validated_value, BaseModel):
                    validated_value = validated_value.__class__.model_validate(
                        validated_value.model_dump()
                    )
                elif isinstance(validated_value, list):
                    new_list = []
                    for item in validated_value:
                        if isinstance(item, BaseModel):
                            new_list.append(
                                item.__class__.model_validate(item.model_dump())
                            )
                        else:
                            new_list.append(item)
                    validated_value = new_list

                valid_fields[key] = validated_value

            except Exception as e:
                actual_type = type(value).__name__
                logger.warning(
                    f"[{cls.__name__}] Field '{key}' invalid "
                    f"(expected {expected_type}, got {actual_type}): {e}"
                )
                extra_invalid[key] = {
                    "value": value,
                    "actual_type": actual_type,
                    "expected_type": expected_type,
                    "error": str(e),
                }

        instance = super().model_validate(valid_fields, **kwargs)

        # Only set extras if non-empty
        if extras:
            instance.extras = extras
        elif hasattr(instance, "extras"):
            instance.__dict__.pop("extras", None)

        # Only set extra_invalid if non-empty
        if extra_invalid:
            instance.extra_invalid = extra_invalid
        elif hasattr(instance, "extra_invalid"):
            instance.__dict__.pop("extra_invalid", None)

        return instance

    class Config:
        extra = "allow"



from dataclasses import dataclass

@dataclass
class RegistryEntry:
    model: Type[BaseFlexibleSafeModel]
    patterns: List[Pattern]
    match_all: bool = False   # require all patterns to match
    scope: str = "subtree"    # "subtree" or "whole"
    priority: int = 0         # higher runs first
    consume: bool = False     # remove matched keys after parse

MODEL_REGISTRY: Dict[Pattern[str], Type[BaseFlexibleSafeModel]] = {}

ENTRIES: List[RegistryEntry] = []

def register_model(
    patterns: Union[str, List[str]],
    *,
    match_all: bool = False,
    scope: str = "subtree",
    priority: int = 0,
    consume: bool = False,
):
    if isinstance(patterns, str):
        patterns = [patterns]
    compiled = [re.compile(p) for p in patterns]

    def wrapper(cls: Type[BaseFlexibleSafeModel]):
        logger.debug(f"Registering model {cls.__name__} with patterns {patterns}")
        ENTRIES.append(
            RegistryEntry(
                model=cls,
                patterns=compiled,
                match_all=match_all,
                scope=scope,
                priority=priority,
                consume=consume,
            )
        )
        ENTRIES.sort(key=lambda e: -e.priority)  # high priority first
        return cls

    return wrapper



# --- Caption ---
class Caption(BaseFlexibleSafeModel):
    text: Optional[str] = None
    created_at: Optional[int] = None
    pk: Optional[str] = None
    has_translation: Optional[bool]= None

# --- Image + Video ---
class ImageCandidate(BaseFlexibleSafeModel):
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ImageVersions2(BaseFlexibleSafeModel):
    candidates: Optional[List[ImageCandidate]] = []


class VideoVersion(BaseFlexibleSafeModel):
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    type: Optional[int] = None


# --- Owner & Friendship ---
class FriendshipStatus(BaseFlexibleSafeModel):
    following: Optional[bool] = None
    is_private: Optional[bool] = None
    is_verified: Optional[bool] = None


class Owner(BaseFlexibleSafeModel):
    id: Optional[str] = None
    pk: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    profile_pic_url: Optional[str] = None
    is_private: Optional[bool] = None
    is_verified: Optional[bool] = None
    friendship_status: Optional[FriendshipStatus] = []


# --- User (shortcode specific) ---
# class UserFriendshipStatus(BaseFlexibleSafeModel):
#     following: Optional[bool] = None
#     followed_by: Optional[bool] = None
#     is_private: Optional[bool] = None
#     is_restricted: Optional[bool] = None
#     blocking: Optional[bool] = None
#     muting: Optional[bool] = None


class User(BaseFlexibleSafeModel):
    id: Optional[Union[int,str]] = None
    pk: Optional[Union[int,str]] = None
    username: Optional[str] = None
    profile_pic_url: Optional[str] = None
    is_private: Optional[bool] = None 
    is_verified: Optional[bool] = None
    follower_count: Optional[Union[int,str]] = None
    following_count: Optional[Union[int,str]] = None
    media_count: Optional[Union[int,str]] = None
    full_name: Optional[str] = None
    # friendship_status: Optional[UserFriendshipStatus]= None

# =====================
# === EXTENSIONS ===
# =====================

# --- DASH Segments ---
class VideoSegment(BaseFlexibleSafeModel):
    start: Optional[int] = None
    end: Optional[int] = None


class VideoRepresentation(BaseFlexibleSafeModel):
    representation_id: Optional[Union[str,int]] = None
    base_url: Optional[str] = None
    bandwidth: Optional[Union[str,int]] = None
    width: Optional[Union[str,int]] = None
    height: Optional[Union[str,int]] = None
    # codecs: Optional[str] = None
    mime_type: Optional[str] = None

    # playback_resolution_csvqm: Optional[str] = None
    # playback_resolution_mos: Optional[str] = None

    segments: Optional[List[VideoSegment]] = []


# --- All Video DASH Prefetch Representations ---
class AllVideoDashPrefetchRepresentations(BaseFlexibleSafeModel):
    video_id: Optional[Union[str,int]] = None
    representations: Optional[List[VideoRepresentation]] = None


class ServerMetadata(BaseFlexibleSafeModel):
    request_start_time_ms: Optional[int] = None
    time_at_flush_ms: Optional[int] = None



# --- Registry-based parsing ---

# Registry of known data-keys → model classes
# MODEL_REGISTRY: Dict[str, Type["BaseFlexibleSafeModel"]] = {}
# def register_model(key: str):
#     """Decorator to register models for specific GraphQL data keys."""
#     def wrapper(cls: Type["BaseFlexibleSafeModel"]):
#         MODEL_REGISTRY[key] = cls
#         return cls
#     return wrapper

# --- Viewer ---
class ViewerUser(BaseFlexibleSafeModel):
    id: Optional[str] = None

# # @register_model(r"xdt_viewer", scope="subtree", priority=10)
class XdtViewer(BaseFlexibleSafeModel):
    user: Optional[ViewerUser]= None

class Status(BaseFlexibleSafeModel):
    status: Optional[str] = None


class Extensions(BaseFlexibleSafeModel):
    all_video_dash_prefetch_representations: Optional[List[AllVideoDashPrefetchRepresentations]] = None
    is_final: Optional[bool] = None
    server_metadata: Optional[ServerMetadata] = None


class GiphyImageVariant(BaseFlexibleSafeModel):
    """Model for individual Giphy image variants (fixed_height, fixed_width, etc.)"""
    url: str
    width: Optional[str] = None
    height: Optional[str] = None
    size: Optional[str] = None
    mp4: Optional[str] = None
    mp4_size: Optional[str] = None
    webp: Optional[str] = None
    webp_size: Optional[str] = None

class FirstPartyCDNProxiedImages(BaseFlexibleSafeModel):
    """Model for first-party CDN proxied images"""
    fixed_height: Optional[GiphyImageVariant] = None
    fixed_height_still: Optional[GiphyImageVariant] = None
    fixed_height_downsampled: Optional[GiphyImageVariant] = None
    fixed_width: Optional[GiphyImageVariant] = None
    fixed_width_still: Optional[GiphyImageVariant] = None
    fixed_width_downsampled: Optional[GiphyImageVariant] = None
    fixed_height_small: Optional[GiphyImageVariant] = None
    fixed_width_small: Optional[GiphyImageVariant] = None
    downsized: Optional[GiphyImageVariant] = None
    downsized_still: Optional[GiphyImageVariant] = None
    downsized_large: Optional[GiphyImageVariant] = None
    downsized_medium: Optional[GiphyImageVariant] = None
    downsized_small: Optional[GiphyImageVariant] = None
    original: Optional[GiphyImageVariant] = None
    original_still: Optional[GiphyImageVariant] = None
    looping: Optional[GiphyImageVariant] = None
    preview: Optional[GiphyImageVariant] = None
    preview_gif: Optional[GiphyImageVariant] = None

class GiphyMediaInfo(BaseFlexibleSafeModel):
    """Main model for Giphy media information in Instagram comments"""
    id: str
    first_party_cdn_proxied_images: Optional[FirstPartyCDNProxiedImages] = None
    images: Optional[Dict[str, Any]] = None  # Could be more complex, but null in example
    # Additional fields that might be present
    type: Optional[str] = None
    url: Optional[str] = None
    slug: Optional[str] = None
    bitly_gif_url: Optional[str] = None
    bitly_url: Optional[str] = None
    embed_url: Optional[str] = None
    username: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    rating: Optional[str] = None
    content_url: Optional[str] = None
    source_tld: Optional[str] = None
    source_post_url: Optional[str] = None
    is_sticker: Optional[int] = None
    import_datetime: Optional[str] = None
    trending_datetime: Optional[str] = None
    user: Optional[Dict[str, Any]] = None

# Simplified version if you only need the basic structure:
class SimpleGiphyMediaInfo(BaseFlexibleSafeModel):
    """Simplified model for Giphy media info"""
    id: str
    first_party_cdn_proxied_images: Optional[Dict[str, Dict[str, str]]] = None
    images: Optional[Any] = None

# Even more minimal version focusing only on what's in your example:
class MinimalGiphyMediaInfo(BaseFlexibleSafeModel):
    """Minimal model based on the provided example"""
    id: str
    first_party_cdn_proxied_images: Dict[str, Dict[str, str]]
    images: Optional[Any] = None