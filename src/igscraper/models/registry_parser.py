import re
import json
import copy
import yaml
from pathlib import Path
from typing import Dict, Any, List, Pattern, Type, Optional, Union,Tuple
from pydantic import BaseModel, TypeAdapter
from igscraper.logger import get_logger
from igscraper.models import ENTRIES, BaseFlexibleSafeModel 
from igscraper.decorator import try_except
import pdb
from igscraper.utils import capture_instagram_requests, unique_keys_by_depth
from collections import OrderedDict
import pprint
from typing import Tuple
from pathlib import Path
from typing import Any, Dict, List
from igscraper.models import BaseFlexibleSafeModel
logger = get_logger(__name__)


class GraphQLModelRegistry:
    def __init__(self, registry: Dict[Pattern[str], Type[BaseFlexibleSafeModel]], schema_path: str):
        # copy provided registry into internal map (you can also use global MODEL_REGISTRY)
        self._registry = registry
        self.flatten_schema = self.load_nested_schema(schema_path)
#         self.COMMENT_MODEL_KEYS = {
#     "xdt_api__v1__media__media_id__comments__connection",
#     # "xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection",
# }

        logger.debug("Initialized GraphQLModelRegistry")

    # ----------------------------
    # Model lookup helpers
    # ----------------------------
    def find_model(self, key: str) -> Optional[Type[BaseFlexibleSafeModel]]:
        """Find model class for a data-key. Try fullmatch first, then search as fallback."""
        logger.debug(f"Finding model for key: {key}")
        # fullmatch (strict)
        for pattern, model_cls in self._registry.items():
            try:
                if pattern.fullmatch(key):
                    logger.info(f"Found model {model_cls.__name__} for key (fullmatch): {key}")
                    return model_cls
            except re.error:
                # ignore bad patterns
                continue
        # fallback: search (looser)
        for pattern, model_cls in self._registry.items():
            try:
                if pattern.search(key):
                    logger.info(f"Found model {model_cls.__name__} for key (search): {key}")
                    return model_cls
            except re.error:
                continue

        logger.warning(f"No model found for key: {key}")
        return None

    # ----------------------------
    # Schema loading & normalization
    # ----------------------------

    def load_nested_schema(self, path: str) -> Dict[str, Any]:
        # Preserve order in YAML loading
        def ordered_load(stream):
            class OrderedLoader(yaml.SafeLoader):
                pass
            def construct_mapping(loader, node):
                loader.flatten_mapping(node)
                return OrderedDict(loader.construct_pairs(node))
            OrderedLoader.add_constructor(
                yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                construct_mapping)
            return yaml.load(stream, OrderedLoader)
        
        raw = ordered_load(Path(path).read_text())["rules"]
        logger.debug("Loaded schema:\n%s", pprint.pformat(raw, width=120))
        return raw

    def expand_dot_keys(self, d: dict) -> dict:
        """Expand keys with dot notation into nested dicts."""
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                v = self.expand_dot_keys(v)  # recurse
            if "." in k and k != "fields":
                parts = k.split(".")
                current = out
                for p in parts[:-1]:
                    current = current.setdefault(p, {})
                current[parts[-1]] = v
            else:
                out[k] = v
        return out

    def _deep_merge_dicts(self, a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        """Return deep-merged dict where b overrides a on conflicts."""
        out = dict(a)
        for k, v in b.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = self._deep_merge_dicts(out[k], v)
            else:
                out[k] = v
        return out

    def extract_graphql_data_keys(self, captured_results):
        patterns = ["graphql/query"]
        extracted = []
        for item in captured_results:
            url = item.get("url", "")
            response = item.get("response", None)
            if any(p in url for p in patterns) and response:
                try:
                    data = json.loads(response).get("data", {})
                    if isinstance(data, dict):
                        extracted.append({
                            "requestId": item.get("requestId"),
                            "url": url,
                            "data_keys": list(data.keys()),
                            "response": response
                        })
                except Exception:
                    continue
        return extracted
    
    def parse_responses_bk2(self, extracted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        logger.info(f"Parsing {len(extracted)} responses")
        parsed_results = []
        # logger.info(f"Schema to use - {self.flatten_schema}")

        for item in extracted:
            url = item.get("url")
            request_id = item.get("requestId")
            raw_response = item.get("response")
            # logger.debug("Top-level data keys for %s: %s", request_id, list(data.keys()))


            if not raw_response:
                logger.warning(f"No raw_response for requestId={request_id}, url={url}")
                continue

            try:
                response_json = json.loads(raw_response)
                data = response_json.get("data", {}) or {}
            except Exception as e:
                logger.error(f"Failed to load JSON for requestId={request_id}: {e}")
                continue

            models = []
            available_keys = set(data.keys())
            flattened_all: List[Dict[str, Any]] = []
            logger.debug("Top-level data keys for %s: %s", request_id, list(data.keys()))
            # logger.debug("Loaded schema keys under 'data': %s", self._schema_data_keys())

            # iterate registry entries in priority order
            for entry in ENTRIES:
                if not available_keys:
                    break

                matched_keys = []
                for pat in entry.patterns:
                    hits = [k for k in available_keys if pat.fullmatch(k) or pat.search(k)]
                    if hits:
                        matched_keys.extend(hits)
                    elif entry.match_all:
                        matched_keys = []
                        break

                if not matched_keys:
                    continue

                # determine payload
                if entry.scope == "whole":
                    payload = response_json
                else:
                    payload = {k: data[k] for k in matched_keys}

                try:
                    # 1. parse into model
                    instance = entry.model.parse_obj(payload)

                    # 2. flatten the parsed model with schema
                    flat_rows, diag = self.apply_nested_schema(response_json, self.flatten_schema, debug=True)
                    # pdb.set_trace()

                    models.append({
                        "entry": entry.model.__name__,
                        "matched_keys": matched_keys,
                        "model": instance,
                        "flattened": flat_rows,
                        "diagnostics": diag,
                    })

                    # accumulate all flattenings
                    flattened_all.extend(flat_rows)

                    if entry.consume and entry.scope != "whole":
                        available_keys -= set(matched_keys)

                    logger.info(f"Parsed {entry.model.__name__} for keys={matched_keys} requestId={request_id}")

                except Exception as e:
                    models.append({
                        "entry": entry.model.__name__,
                        "matched_keys": matched_keys,
                        "error": str(e),
                    })
                    logger.error(f"Error parsing {entry.model.__name__}: {e}")

            # any leftovers
            unparsed = {k: data[k] for k in available_keys}

            parsed_results.append({
                "requestId": request_id,
                "url": url,
                "parsed_models": models,
                "flattened": flattened_all,
                "unparsed": unparsed,
            })

        logger.info("Finished parsing responses")
        return parsed_results

    def parse_responses(self, extracted: List[Dict[str, Any]], selected_data_keys: List[str] = [], driver: Any = None) -> List[Dict[str, Any]]:
        """
        Parse a list of GraphQL network responses into structured models and separate
        flattened outputs for 'data' and 'extensions'.
        """
        logger.info(f"Starting parse_responses for {len(extracted)} extracted items")
        parsed_results = []

        for idx, item in enumerate(extracted):
            url = item.get("url")
            request_id = item.get("requestId")
            raw_response = item.get("response")

            logger.debug(f"[{idx+1}/{len(extracted)}] Processing requestId={request_id}, url={url}")

            if not raw_response:
                logger.warning(f"No raw_response for requestId={request_id}, url={url}")
                continue

            try:
                response_json = json.loads(raw_response)
                data = response_json.get("data", {}) or {}
                extensions = response_json.get("extensions", {}) or {}
            except Exception as e:
                logger.error(f"Failed to decode JSON for requestId={request_id}: {e}")
                continue

            available_keys = set(data.keys())
            logger.debug(f"Initial available_keys: {sorted(list(available_keys))}")
            # --- If user specified selected_data_keys, skip responses that don't contain any of them ---
            if selected_data_keys:
                overlap = set(selected_data_keys) & available_keys
                if not overlap:
                    logger.debug(f"No selected_data_keys ({selected_data_keys}) found in available_keys, skipping response.")
                    continue

            models = []
            flattened_data_all: List[Dict[str, Any]] = []
            flattened_ext_all: List[Dict[str, Any]] = []

            for entry in ENTRIES:
                logger.debug(f"Checking entry: {entry.model.__name__} (scope={entry.scope}, consume={entry.consume})")

                if not available_keys and entry.scope != "whole":
                    logger.debug("No available_keys left, breaking out of loop")
                    break

                matched_keys = []
                for pat in entry.patterns:
                    hits = [k for k in available_keys if pat.fullmatch(k) or pat.search(k)]
                    if hits:
                        matched_keys.extend(hits)
                    elif entry.match_all:
                        matched_keys = []
                        break

                if not matched_keys and entry.scope != "whole":
                    continue

                payload = response_json if entry.scope == "whole" else {k: data[k] for k in matched_keys}
                logger.debug(
                    f"Matched entry={entry.model.__name__} with keys={matched_keys or ['<whole>']} "
                    f"(payload_size={len(str(payload))} chars)"
                )

                try:
                    instance = entry.model.parse_obj(payload)
                    logger.debug(f"Successfully parsed model {entry.model.__name__}")

                    # --- Flatten separately ---
                    flat_data, diag_data, flat_ext, diag_ext = self.flatten_selected_top_level(
                        data=data,
                        extensions=extensions,
                        data_keys=selected_data_keys,
                        sep="$$",
                        debug=True,
                        allow_regex=False
                    )
                    # flat_data, diag_data = self.apply_nested_schema({"data": data}, self.flatten_schema, debug=True)
                    # flat_ext, diag_ext = self.apply_nested_schema({"extensions": extensions}, self.flatten_schema, debug=True)

                    # # --- Deduplicate by PK (only data) ---
                    # unique_by_pk = {}
                    # for row in flat_data:
                    #     pk = row.get("pk")
                    #     if pk:
                    #         unique_by_pk[pk] = row
                    # flat_data = list(unique_by_pk.values())

                    logger.debug(
                        f"Flattened {len(flat_data)} rows for data and {len(flat_ext)} rows for extensions "
                        f"for requestId={request_id}"
                    )

                    models.append({
                        "entry": entry.model.__name__,
                        "matched_keys": matched_keys,
                        "model": instance,
                        "diagnostics": {"data": diag_data, "extensions": diag_ext},
                    })

                    flattened_data_all.extend(flat_data)
                    flattened_ext_all.extend(flat_ext)

                    # Consume keys if applicable
                    if entry.consume:
                        if entry.scope == "whole":
                            available_keys.clear()
                        else:
                            available_keys -= set(matched_keys)

                except Exception as e:
                    logger.error(f"Error parsing {entry.model.__name__}: {e}")
                    models.append({
                        "entry": entry.model.__name__,
                        "matched_keys": matched_keys,
                        "error": str(e),
                    })

            unparsed = {k: data[k] for k in available_keys}

            parsed_results.append({
                "requestId": request_id,
                "url": url,
                "parsed_models": models,
                "flattened_data": flattened_data_all,
                "flattened_extensions": flattened_ext_all,
                "unparsed": unparsed,
                "current_url": driver.current_url
            })

            logger.debug(
                f"Finished requestId={request_id} "
                f"({len(flattened_data_all)} data rows, {len(flattened_ext_all)} extension rows)"
            )

        logger.debug("Completed parse_responses for all inputs")
        return parsed_results

    # Schema walker / flattener
    # apply_nested_schema_with_separate_flag_v2
    def apply_nested_schema(
        self,
        obj: Any,
        schema: Dict[str, Any],
        sep: str = "__",
        debug: bool = False
    ) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
        """
        Final apply_nested_schema:
        - Use __separate__: True to force children into separate output rows (no merging).
        - Child-level __strict__ overrides parent for regex vs exact matching.
        - Regexes precompiled and cached; invalid regex falls back to exact match.
        - 'unwrap' explodes lists; absence of 'unwrap' keeps lists intact but processes each item
        (so carousel_media remains a list of processed dicts).
        - sep controls the separator used in flattened column names (default '__').
        """
        if isinstance(obj, BaseFlexibleSafeModel):
            obj = obj.model_dump()

        matched_rules = set()
        unmatched_rules = set()
        regex_cache: Dict[str, Union[re.Pattern, None]] = {}

        def join_path(path: str, child: str) -> str:
            return f"{path}{sep}{child}" if path else child

        def _nested_children_keys(scfg: Dict[str, Any]) -> List[str]:
            return [k for k in scfg.keys() if k not in ("fields", "__strict__", "unwrap", "__separate__")]

        def _compile_or_none(pattern: str):
            if pattern in regex_cache:
                return regex_cache[pattern]
            try:
                compiled = re.compile(pattern)
                regex_cache[pattern] = compiled
                return compiled
            except re.error:
                regex_cache[pattern] = None
                return None

        def process_item_with_schema(item: Dict[str, Any], scfg: Dict[str, Any]):
            """
            Process a single list-item dict according to scfg:
            - include scfg['fields'] for the item
            - process nested children per-item (keeps lists unless nested child says 'unwrap')
            """
            result = {}
            if not isinstance(item, dict):
                return item
            # attach fields at this level
            if "fields" in scfg:
                for f in scfg["fields"]:
                    if f in item:
                        result[f] = item[f]
            # handle nested children
            for child_key, child_cfg in scfg.items():
                if child_key in ("fields", "__strict__", "unwrap", "__separate__"):
                    continue
                if child_key not in item:
                    continue
                val = item[child_key]
                # list
                if isinstance(val, list):
                    if isinstance(child_cfg, dict) and "unwrap" in child_cfg:
                        unwrap_key = child_cfg["unwrap"]
                        processed_list = []
                        for it in val:
                            if isinstance(it, dict) and unwrap_key in it:
                                payload = it[unwrap_key]
                            else:
                                payload = it
                            if isinstance(payload, dict):
                                processed_list.append(process_item_with_schema(payload, child_cfg))
                            else:
                                processed_list.append(payload)
                        result[child_key] = processed_list
                    else:
                        processed_list = []
                        for it in val:
                            if isinstance(it, dict):
                                processed_list.append(process_item_with_schema(it, child_cfg))
                            else:
                                processed_list.append(it)
                        result[child_key] = processed_list
                # dict
                elif isinstance(val, dict):
                    result[child_key] = process_item_with_schema(val, child_cfg)
                # scalar
                else:
                    # only include scalar if declared in child_cfg['fields']
                    if "fields" in child_cfg and child_key in child_cfg["fields"]:
                        result[child_key] = val
            return result

        def walk(o: Any, schema_node: Dict[str, Any], path: str) -> List[Dict[str, Any]]:
            """
            Pure recursion: returns list[dict] where each dict is a flattened row.
            """
            if isinstance(o, BaseFlexibleSafeModel):
                o = o.model_dump()

            # unwrap-from-dict shortcut
            if isinstance(o, dict) and "unwrap" in schema_node:
                unwrap_key = schema_node["unwrap"]
                if unwrap_key in o and isinstance(o[unwrap_key], list):
                    return walk(o[unwrap_key], schema_node, join_path(path, unwrap_key))

            # If node explicitly asks for separation, process children independently
            child_keys = [k for k in schema_node.keys() if k not in ("fields", "__strict__", "unwrap", "__separate__")]
            if schema_node.get("__separate__", False) and child_keys:
                result_rows: List[Dict[str, Any]] = []
                if isinstance(o, dict):
                    parent_strict = schema_node.get("__strict__", True)
                    for sk in child_keys:
                        scfg = schema_node[sk]
                        child_strict = (scfg.get("__strict__", parent_strict) if isinstance(scfg, dict) else parent_strict)

                        matches: List[Tuple[str, str]] = []
                        if child_strict:
                            if sk in o:
                                matches.append((sk, sk))
                        else:
                            compiled = _compile_or_none(sk)
                            if compiled is None:
                                if sk in o:
                                    matches.append((sk, sk))
                            else:
                                for actual_key in o.keys():
                                    if compiled.fullmatch(actual_key):
                                        matches.append((sk, actual_key))

                        if not matches:
                            unmatched_rules.add(join_path(path, sk))
                            continue

                        for _, actual_key in matches:
                            current_path = join_path(path, actual_key)
                            matched_rules.add(current_path)
                            value = o[actual_key]
                            child_rows = walk(value, scfg if isinstance(scfg, dict) else {}, current_path)
                            if child_rows:
                                result_rows.extend(child_rows)
                    return result_rows
                else:
                    return []

            # Single-pattern processing (fields at this level, children merged)
            if isinstance(o, dict):
                base_rows: List[Dict[str, Any]] = [{}]

                # attach fields at this level
                if "fields" in schema_node:
                    for f in schema_node["fields"]:
                        if f in o:
                            for br in base_rows:
                                br[join_path(path, f)] = o[f]
                            matched_rules.add(join_path(path, f))
                        else:
                            unmatched_rules.add(join_path(path, f))

                for sk, scfg in schema_node.items():
                    if sk in ("fields", "__strict__", "unwrap", "__separate__"):
                        continue

                    parent_strict = schema_node.get("__strict__", True)
                    child_strict = (scfg.get("__strict__", parent_strict) if isinstance(scfg, dict) else parent_strict)

                    matches: List[Tuple[str, str]] = []
                    if child_strict:
                        if sk in o:
                            matches.append((sk, sk))
                    else:
                        compiled = _compile_or_none(sk)
                        if compiled is None:
                            if sk in o:
                                matches.append((sk, sk))
                        else:
                            for actual_key in o.keys():
                                if compiled.fullmatch(actual_key):
                                    matches.append((sk, actual_key))

                    if not matches:
                        unmatched_rules.add(join_path(path, sk))
                        continue

                    new_base_rows: List[Dict[str, Any]] = []
                    for _, actual_key in matches:
                        current_path = join_path(path, actual_key)
                        matched_rules.add(current_path)
                        v = o[actual_key]

                        # LIST
                        if isinstance(v, list):
                            if isinstance(scfg, dict) and "unwrap" in scfg:
                                unwrap_key = scfg["unwrap"]
                                for br in base_rows:
                                    for item in v:
                                        if isinstance(item, dict) and unwrap_key in item:
                                            item_payload = item[unwrap_key]
                                        else:
                                            item_payload = item

                                        if isinstance(item_payload, dict):
                                            parent_for_child = {}
                                            fields = scfg.get("fields")
                                            if fields:
                                                for f in fields:
                                                    if f in item_payload:
                                                        parent_for_child[join_path(current_path, f)] = item_payload[f]
                                            child_rows = walk(item_payload, scfg, current_path)
                                            if child_rows:
                                                for cr in child_rows:
                                                    new_base_rows.append({**br, **parent_for_child, **cr})
                                            else:
                                                new_base_rows.append({**br, **parent_for_child})
                                        else:
                                            new_base_rows.append({**br, current_path: item_payload})
                            else:
                                # keep list intact; but if scfg has fields or nested children,
                                # process each list-item and store processed list
                                fields = scfg.get("fields") if isinstance(scfg, dict) else None
                                nested_children = _nested_children_keys(scfg if isinstance(scfg, dict) else {})
                                if (fields or nested_children) and all(isinstance(it, dict) for it in v):
                                    processed_list = [process_item_with_schema(it, scfg) for it in v]
                                    for br in base_rows:
                                        new = dict(br)
                                        new[current_path] = processed_list
                                        new_base_rows.append(new)
                                else:
                                    for br in base_rows:
                                        new = dict(br)
                                        new[current_path] = v
                                        new_base_rows.append(new)

                        # DICT
                        elif isinstance(v, dict):
                            fields = scfg.get("fields") if isinstance(scfg, dict) else None
                            nested_children = _nested_children_keys(scfg if isinstance(scfg, dict) else {})
                            if fields:
                                for br in base_rows:
                                    new = dict(br)
                                    for f in fields:
                                        if f in v:
                                            new[join_path(current_path, f)] = v[f]
                                    if nested_children:
                                        child_rows = walk(v, scfg if isinstance(scfg, dict) else {}, current_path)
                                        if child_rows:
                                            for cr in child_rows:
                                                new_base_rows.append({**new, **cr})
                                        else:
                                            new_base_rows.append(new)
                                    else:
                                        new_base_rows.append(new)
                            else:
                                child_rows = walk(v, scfg if isinstance(scfg, dict) else {}, current_path)
                                if child_rows:
                                    for br in base_rows:
                                        for cr in child_rows:
                                            new_base_rows.append({**br, **cr})
                                else:
                                    for br in base_rows:
                                        new_base_rows.append(dict(br))

                        # SCALAR
                        else:
                            if "fields" in schema_node and actual_key in schema_node["fields"]:
                                for br in base_rows:
                                    new_row = dict(br)
                                    new_row[current_path] = v
                                    new_base_rows.append(new_row)
                            else:
                                for br in base_rows:
                                    new_base_rows.append(dict(br))

                    base_rows = new_base_rows if new_base_rows else base_rows

                return base_rows

            # LIST at node level (not exploded)
            elif isinstance(o, list):
                if "unwrap" in schema_node:
                    unwrap_key = schema_node["unwrap"]
                    result_rows: List[Dict[str, Any]] = []
                    for item in o:
                        if isinstance(item, dict) and unwrap_key in item:
                            item_payload = item[unwrap_key]
                        else:
                            item_payload = item

                        if isinstance(item_payload, dict):
                            parent_for_child = {}
                            fields = schema_node.get("fields")
                            if fields:
                                for f in fields:
                                    if f in item_payload:
                                        parent_for_child[join_path(path, f)] = item_payload[f]
                            child_rows = walk(item_payload, schema_node, path)
                            if child_rows:
                                for cr in child_rows:
                                    result_rows.append({**parent_for_child, **cr})
                            else:
                                result_rows.append(parent_for_child)
                        else:
                            result_rows.append({path or "value": item_payload})
                    return result_rows
                else:
                    # keep list intact, but process per-item if schema_node defines fields/nested children
                    fields = schema_node.get("fields")
                    nested_children = _nested_children_keys(schema_node)
                    if (fields or nested_children) and all(isinstance(it, dict) for it in o):
                        processed_list = [process_item_with_schema(it, schema_node) for it in o]
                        return [{path or "value": processed_list}]
                    else:
                        return [{path or "value": o}]

            # fallback
            return []

        rows = walk(obj, schema, "")

        if not rows and (obj or debug):
            rows = [{}]

        if debug:
            diag = {
                "matched_rules": sorted(matched_rules),
                "unmatched_schema_paths": sorted(unmatched_rules),
                "rows_count": len(rows),
                "rows_sample": rows[:5],
            }
            return rows, diag

        return rows, {}

    def collect_schema_paths(self, schema_node: Dict[str, Any], path: str = "") -> set:
        """Collect all schema keys (ignore 'fields' and '__strict__')."""
        paths = set()
        for k, v in schema_node.items():
            if k in ("fields", "__strict__", "unwrap"):
                continue
            new_path = f"{path}.{k}" if path else k
            paths.add(new_path)
            if isinstance(v, dict):
                paths |= self.collect_schema_paths(v, new_path)
        return paths

    def _schema_data_keys(self) -> List[str]:
        """Helper: return the schema keys under 'data' (as stored - regex or literal)."""
        schema_data = self.flatten_schema.get("data", {}) or {}
        return list(schema_data.keys())

    def _diagnose_flattening(self, response_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Diagnose why apply_nested_schema produced no rows.
        Logs schema vs JSON keys side-by-side.
        """
        import pprint
        from igscraper.utils import unique_keys_by_depth

        diag: Dict[str, Any] = {}
        data = response_json.get("data", {})
        data_keys = list(data.keys())
        diag["data_keys"] = data_keys

        schema_data_keys = self._schema_data_keys()
        diag["schema_data_keys"] = schema_data_keys

        logger.debug("=== Flattening DIAG ===")
        logger.debug("Top-level data keys: %s", data_keys)
        logger.debug("Schema (data) keys: %s", schema_data_keys)

        # check regex fullmatch for each schema key vs data keys
        matches = []
        for sk in schema_data_keys:
            for dk in data_keys:
                try:
                    ok = bool(re.fullmatch(sk, dk))
                except re.error:
                    ok = (sk == dk)
                if ok:
                    matches.append((sk, dk))
                logger.debug("Schema key %r vs data key %r -> %s", sk, dk, ok)
        diag["matches"] = matches

        # inspect payload
        if data_keys:
            tk = data_keys[0]
            payload = data.get(tk)
            diag["sample_key"] = tk
            diag["payload_type"] = str(type(payload))
            if isinstance(payload, dict):
                diag["payload_keys"] = list(payload.keys())
            elif isinstance(payload, list):
                diag["payload_len"] = len(payload)
                diag["payload_sample"] = payload[:2]
            else:
                diag["payload_repr"] = repr(payload)[:200]

            # edges/node inspection
            if isinstance(payload, dict) and "edges" in payload:
                e = payload["edges"]
                diag["edges_present"] = True
                if isinstance(e, list) and e:
                    diag["edges_len"] = len(e)
                    diag["edge0_keys"] = list(e[0].keys())
                    node0 = e[0].get("node")
                    diag["edge0_has_node"] = isinstance(node0, dict)
                    if isinstance(node0, dict):
                        diag["node0_keys"] = list(node0.keys())

        try:
            diag["keys_by_depth"] = unique_keys_by_depth(response_json)
        except Exception as e:
            logger.exception("unique_keys_by_depth failed: %s", e)

        # include normalized schema paths for direct comparison
        diag["normalized_schema_paths"] = self.debug_schema_paths()

        logger.debug("=== DIAG SUMMARY ===\n%s", pprint.pformat(diag, width=120))
        return diag

    def _to_serializable(self, obj: Any) -> Any:
        """Convert Pydantic models, sets, and nested structures into plain JSON-safe types."""
        if isinstance(obj, BaseFlexibleSafeModel):
            return obj.model_dump()
        if isinstance(obj, dict):
            return {k: self._to_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._to_serializable(v) for v in obj]
        if isinstance(obj, set):
            return [self._to_serializable(v) for v in obj]  # convert set → list
        return obj

    def save_parsed_results_bk(self, parsed_results: Dict[Any, Any], file_path: str, mode = 'a'):
        """
        Save parsed results to JSON file, ensuring all objects are serializable.
        """
        def make_serializable(obj):
            """Recursively convert objects to JSON-serializable types."""
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return obj
            elif isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            elif hasattr(obj, 'model_dump'):
                # Pydantic v2
                return make_serializable(obj.model_dump())
            elif hasattr(obj, 'dict'):
                # Pydantic v1
                return make_serializable(obj.dict())
            elif hasattr(obj, '__dict__'):
                # Regular objects
                return make_serializable(obj.__dict__)
            else:
                # Fallback to string representation
                return str(obj)
        path = Path(file_path)
        parent = path.parent

        if not parent.exists():
            logger.warning(f"Creating missing directory: {parent}")
            parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, mode, encoding='utf-8') as f:
            for entry in parsed_results:
                safe_entry = make_serializable(entry)
                f.write(json.dumps(safe_entry, ensure_ascii=False) + "\n")
        logger.debug(f"✅ Saved {len(parsed_results)} parsed responses to {file_path}")

    def save_parsed_results(self, parsed_results: List[Dict]| Dict, file_path: str, mode='a'):
        """
        Save parsed results (list[dict] or dict) to a JSONL file,
        ensuring all objects are JSON-serializable.
        """

        def make_serializable(obj):
            """Recursively convert objects to JSON-serializable types."""
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return obj
            elif isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_serializable(item) for item in obj]
            elif hasattr(obj, 'model_dump'):
                # Pydantic v2
                return make_serializable(obj.model_dump())
            elif hasattr(obj, 'dict'):
                # Pydantic v1
                return make_serializable(obj.dict())
            elif hasattr(obj, '__dict__'):
                # Regular class/object
                return make_serializable(vars(obj))
            else:
                # Fallback to string
                return str(obj)

        path = Path(file_path)
        parent = path.parent
        if not parent.exists():
            logger.warning(f"Creating missing directory: {parent}")
            parent.mkdir(parents=True, exist_ok=True)

        # Normalize to list
        if isinstance(parsed_results, dict):
            parsed_results = [parsed_results]
        elif not isinstance(parsed_results, list):
            logger.warning(f"Unexpected type for parsed_results: {type(parsed_results)}; converting to list")
            parsed_results = [parsed_results]

        # Write safely to file
        try:
            with open(path, mode, encoding='utf-8') as f:
                for entry in parsed_results:
                    safe_entry = make_serializable(entry)
                    f.write(json.dumps(safe_entry, ensure_ascii=False) + "\n")
            logger.debug(f"✅ Saved {len(parsed_results)} parsed response(s) to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save parsed results to {file_path}: {e}")
            return False


    @try_except(log_error=True)
    def get_posts_data(self, config, keys_to_match: List[str], data_type: str = "post"):
        relevant_requests_data = capture_instagram_requests(config._driver, 500)
        graphql_keys = self.extract_graphql_data_keys(relevant_requests_data)
        self.save_keys(graphql_keys, config.data.graphql_keys_path)
        save_path = ""
        if data_type == "post":
            save_path = config.data.post_entity_path
        elif data_type == "profile":
            save_path = config.data.profile_path
        else:
            logger.error(f"Unknown data_type: {data_type}. Must be 'post' or 'profile'.")
            raise ValueError(f"Unknown data_type: {data_type}")
        if graphql_keys:
            logger.debug(f"Extracted {len(graphql_keys)} unique GraphQL keys from network requests.")
            # self.registry.debug_schema_paths()
            graphql_data = self.parse_responses(graphql_keys,selected_data_keys=keys_to_match, driver=config._driver)

            ## for testing purpose. TODO: remove later
            filtered_result = self.filter_parsed_models_by_keys(graphql_data, keys_to_match)
            if not filtered_result:
                logger.debug("No matched keys found in this response; skipping save.")
                return False

            # parsed_ids = self._extract_ids_from_parsed_data(
            #     filtered_result,
            #     allowed_model_keys=self.COMMENT_MODEL_KEYS,
            # )

            # logger.debug(
            #     f"Extracted {len(parsed_ids)} COMMENT ids "
            #     f"from {len(filtered_result)} GraphQL models"
            # )

            # extracted_data = graphql_data['flattened'].pop()
            # self.save_parsed_results(extracted_data, self.config.data.extracted_data_path)

            is_saved = self.save_parsed_results(filtered_result, save_path)
            logger.debug(f"Parsed GraphQL data contains {len(filtered_result)} entries.")
            return is_saved
        return False


    def filter_parsed_models_by_keys(self, data: dict | list[dict], required_keys: list[str]) -> dict | list[dict]:
        """
        Filters parsed_models, keeping only those whose matched_keys contain any of required_keys.
        Works for both dicts and list of dicts. Logs what gets removed.

        Args:
            data: The Instagram GraphQL-like response dict or list of dicts.
            required_keys: The keys to match against 'matched_keys'.

        Returns:
            Filtered dict or list[dict] with only matching parsed_models.
        """
        # --- Case 1: list of dicts ---
        if isinstance(data, list):
            logger.debug(f"Filtering list of {len(data)} items for keys: {required_keys}")
            return [self.filter_parsed_models_by_keys(d, required_keys) for d in data]

        # --- Case 2: single dict ---
        if not isinstance(data, dict):
            logger.warning(f"Expected dict or list of dicts, got {type(data).__name__}")
            return data

        parsed_models = data.get("parsed_models", [])
        if not parsed_models:
            logger.debug(f"No parsed_models found for requestId={data.get('requestId')}")
            return {}

        # Separate matches and rejections
        filtered_models = []
        removed_models = []

        for model in parsed_models:
            matched = model.get("matched_keys", [])
            entry = model.get("entry", "unknown")

            if any(key in matched for key in required_keys):
                filtered_models.append(model)
            else:
                removed_models.append({"entry": entry, "matched_keys": matched})

        # --- Logging summary ---
        req_id = data.get("requestId", "N/A")
        if removed_models:
            removed_entries = [f"{m['entry']}({m['matched_keys']})" for m in removed_models]
            logger.info(
                f"[filter_parsed_models_by_keys] requestId={req_id} "
                f"removed {len(removed_models)} model(s): {', '.join(removed_entries)}"
            )
        else:
            logger.debug(f"[filter_parsed_models_by_keys] requestId={req_id} all models matched {required_keys}")

        # --- Return new data copy with filtered models ---
        result = data.copy()
        result["parsed_models"] = filtered_models
        return result

    def save_keys(self, keys: List[Dict], file_path: str):
        path = Path(file_path)
        parent = path.parent
        if not parent.exists():
            logger.warning(f"Creating missing directory: {parent}")
            parent.mkdir(parents=True, exist_ok=True)
        _ = [self.save_parsed_results(key, file_path) for key in keys if key]


    def flatten_response(self, response_json: Dict[str, Any], debug: bool = False):
        """
        Normalizes and flattens any GraphQL response into table-like rows.
        Automatically starts from the 'data' node if present.
        """
        if isinstance(response_json, dict) and "data" in response_json:
            target = response_json["data"]
        else:
            target = response_json

        return self.apply_nested_schema(target, self.flatten_schema, debug=debug)


    def flatten_selected_top_level(
        self,
        data: Dict[str, Any],
        extensions: Dict[str, Any],
        data_keys: List[str],
        sep: str = "__",
        debug: bool = False,
        allow_regex: bool = False
    ) -> Tuple[List[Dict[str, Any]], Dict, List[Dict[str, Any]], Dict]:
        """
        Minimal helper:
        - Run apply_nested_schema only for selected first-level keys under 'data'
        - Always run the full 'extensions' subtree
        Returns: (flat_data_rows, diag_data, flat_ext_rows, diag_ext)
        """
        # --- build pruned data schema for selected first-level keys ---
        source_data = self.flatten_schema.get("data", {}) if isinstance(self.flatten_schema, dict) else self.flatten_schema
        pruned_children: Dict[str, Any] = {}

        if allow_regex:
            compiled = []
            for p in data_keys:
                try:
                    compiled.append(re.compile(p))
                except re.error:
                    compiled.append(None)
            for child_name, cfg in source_data.items():
                for patt in compiled:
                    if patt is None:
                        continue
                    if patt.fullmatch(child_name):
                        pruned_children[child_name] = copy.deepcopy(cfg)
                        break
        else:
            for key in data_keys:
                if key in source_data:
                    pruned_children[key] = copy.deepcopy(source_data[key])

        # fallback: if nothing selected, run entire data subtree (safe default)
        if not pruned_children:
            pruned_data_schema = {"data": copy.deepcopy(source_data)} if isinstance(self.flatten_schema, dict) and "data" in self.flatten_schema else copy.deepcopy(source_data)
        else:
            pruned_data_schema = {"data": pruned_children}

        # --- build pruned extensions schema (always run full extensions subtree) ---
        if isinstance(self.flatten_schema, dict) and "extensions" in self.flatten_schema:
            pruned_ext_schema = {"extensions": copy.deepcopy(self.flatten_schema["extensions"])}
        else:
            # if there's no explicit "extensions" key in flatten_schema, fall back to whole schema
            pruned_ext_schema = copy.deepcopy(self.flatten_schema)

        # --- prepare payload wrappers ---
        payload_data = {"data": data}
        payload_ext = {"extensions": extensions}

        # --- call apply_nested_schema on pruned schemas ---
        res_data = self.apply_nested_schema(payload_data, pruned_data_schema, sep=sep, debug=debug)
        res_ext = self.apply_nested_schema(payload_ext, pruned_ext_schema, sep=sep, debug=debug)

        # normalize outputs into (rows, diag)
        if debug:
            rows_data, diag_data = res_data if isinstance(res_data, tuple) and len(res_data) == 2 else (res_data, {})
            rows_ext, diag_ext = res_ext if isinstance(res_ext, tuple) and len(res_ext) == 2 else (res_ext, {})
        else:
            rows_data = res_data[0] if isinstance(res_data, tuple) else res_data
            diag_data = {}
            rows_ext = res_ext[0] if isinstance(res_ext, tuple) else res_ext
            diag_ext = {}

        return rows_data, diag_data, rows_ext, diag_ext

    # def extract_comment_id(self, row: dict) -> str | None:
    #     """
    #     Attempts to extract a stable comment identifier from a flattened row
    #     without hard-coding schema paths.
    #     """
    #     for key, value in row.items():
    #         if not value:
    #             continue

    #         key_lower = key.lower()

    #         # strongest signals first
    #         if key_lower.endswith("$$pk") or key_lower.endswith(".pk") or key_lower.endswith("_pk"):
    #             return str(value)

    #         if key_lower.endswith("$$id") or key_lower.endswith(".id"):
    #             # avoid media_id / user_id
    #             if "comment" in key_lower or "node" in key_lower:
    #                 return str(value)

    #     return None

    # def _extract_ids_from_parsed_data(
    #     self,
    #     parsed_models: list[dict],
    #     allowed_model_keys: set[str],
    # ) -> set[str]:
    #     """
    #     Extract COMMENT ids only from allowed GraphQL models.
    #     """
    #     ids = set()

    #     if not parsed_models:
    #         return ids

    #     for model in parsed_models:
    #         if not isinstance(model, dict):
    #             continue

    #         parsed_models_meta = model.get("parsed_models", [])
    #         if not parsed_models_meta:
    #             continue

    #         matched_keys = set(parsed_models_meta[0].get("matched_keys", []))

    #         # 🚨 HARD GATE — ignore feed / timeline / profile models
    #         if not matched_keys & allowed_model_keys:
    #             continue

    #         for row in model.get("flattened_data", []):
    #             cid = self.extract_comment_id(row)
    #             if cid:
    #                 ids.add(cid)

    #     return ids
