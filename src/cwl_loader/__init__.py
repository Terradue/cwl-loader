# Copyright 2025 Terradue
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load, normalize, and serialize CWL documents while preserving metadata."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from collections.abc import MutableMapping as MutableMappingABC
from gzip import GzipFile
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urldefrag, urlparse
from urllib.request import url2pathname

import requests
from cwl_utils.parser import Process, load_document_by_yaml, save
from loguru import logger
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from ._cwlupgrader import _upgrade_document
from ._dereference import _dereference_steps, remove_refs
from .sort import order_graph_by_dependencies
from .utils import assert_connected_graph

__DEFAULT_BASE_URI__ = "io://"
__TARGET_CWL_VERSION__ = "v1.2"
__DEFAULT_ENCODING__ = "utf-8"
__CWL_VERSION__ = "cwlVersion"
__CWL_GRAPH__ = "$graph"
__CWL_DOCUMENT_METADATA_ATTR__ = "_cwl_loader_document_metadata"
__CWL_DOCUMENT_HAS_GRAPH_ATTR__ = "_cwl_loader_document_has_graph"
__CWL_DOCUMENT_CONTROL_FIELDS__ = ("$namespaces", "$schemas", "$base")

_yaml = YAML()
_global_session = requests.Session()

# Module-level cache storing custom (namespaced) requirements extracted from
# the most recent load, keyed by item id. Unlike document-level metadata
# (namespaces, schemas, arbitrary top-level annotations, ...) - which
# `_extract_document_metadata`/`_preserve_document_metadata` below already
# capture and restore generically - custom requirements live *inside*
# individual `$graph` items' `requirements`/`hints` and must be stripped
# before parsing (the standard CWL parser rejects namespaced requirement
# classes it doesn't recognize) and re-injected explicitly at dump time.
# Cleared at the start of each top-level load (depth == 0) to prevent
# leaking state between successive loads.
_custom_requirements_cache: dict[str, Any] = {}
_load_depth: int = 0


def _as_process_list(process: Process | list[Process]) -> list[Process]:
    return process if isinstance(process, list) else [process]


def _extract_document_metadata(
    raw_process: Mapping[str, Any] | CommentedMap,
    process: Process | list[Process] | None = None,
) -> CommentedMap:
    metadata = CommentedMap()

    process_fields: set[str] = set()
    if __CWL_GRAPH__ not in raw_process and process is not None:
        for p in _as_process_list(process):
            process_fields.update(getattr(p, "attrs", ()))

    for key, value in raw_process.items():
        if key not in (__CWL_VERSION__, __CWL_GRAPH__) and key not in process_fields:
            metadata[key] = value

    return metadata


def _preserve_document_metadata(
    process: Process | list[Process],
    document_metadata: CommentedMap,
    document_has_graph: bool,
) -> None:
    """Attach document metadata to each parsed process for serialization."""
    if not document_metadata:
        return

    for p in _as_process_list(process):
        metadata = CommentedMap(document_metadata)
        setattr(p, __CWL_DOCUMENT_METADATA_ATTR__, metadata)
        setattr(p, __CWL_DOCUMENT_HAS_GRAPH_ATTR__, document_has_graph)

        loading_options = getattr(p, "loadingOptions", None)
        if loading_options is not None:
            loading_options.addl_metadata.update(metadata)


def _preserved_document_metadata(
    process: Process | list[Process],
) -> Mapping[str, Any] | None:
    """Find preserved document metadata, falling back to parser metadata."""
    for p in _as_process_list(process):
        metadata = getattr(p, __CWL_DOCUMENT_METADATA_ATTR__, None)
        if isinstance(metadata, Mapping) and metadata:
            return metadata

        loading_options = getattr(p, "loadingOptions", None)
        metadata = getattr(loading_options, "addl_metadata", None)
        if isinstance(metadata, Mapping) and metadata:
            return metadata

    return None


def _has_preserved_graph_document(process: Process | list[Process]) -> bool:
    return any(
        bool(getattr(p, __CWL_DOCUMENT_HAS_GRAPH_ATTR__, False)) for p in _as_process_list(process)
    )


def _strip_nested_document_controls(
    data: MutableMappingABC[str, Any], document_metadata: Mapping[str, Any]
) -> None:
    """Remove document-level controls from nested graph entries in place."""
    graph = data.get(__CWL_GRAPH__)

    if not isinstance(graph, list):
        return

    for item in graph:
        if not isinstance(item, MutableMappingABC):
            continue

        for field in __CWL_DOCUMENT_CONTROL_FIELDS__:
            if field in document_metadata:
                item.pop(field, None)


def _serialized_extension_metadata_keys(
    process: Process | list[Process], document_metadata: Mapping[str, Any]
) -> set[str]:
    """Return serialized extension keys that duplicate preserved source keys."""
    serialized_keys: set[str] = set()

    for p in _as_process_list(process):
        extension_fields = getattr(p, "extension_fields", {})
        loading_options = getattr(p, "loadingOptions", None)
        namespaces = getattr(loading_options, "namespaces", {})

        for key in document_metadata:
            if key.startswith("$"):
                continue

            expanded_key = key
            if ":" in key and not key.startswith(("http://", "https://")):
                prefix, local_name = key.split(":", 1)
                if prefix in namespaces:
                    expanded_key = f"{namespaces[prefix]}{local_name}"

            if expanded_key in extension_fields:
                serialized_keys.add(expanded_key)

    return serialized_keys


def _strip_serialized_extension_metadata(
    data: MutableMappingABC[str, Any],
    process: Process | list[Process],
    document_metadata: Mapping[str, Any],
) -> None:
    """Remove serialized extension fields duplicated by document metadata."""
    keys = _serialized_extension_metadata_keys(process, document_metadata)
    if not keys:
        return

    graph = data.get(__CWL_GRAPH__)
    targets = graph if isinstance(graph, list) else [data]
    for target in targets:
        if isinstance(target, MutableMappingABC):
            for key in keys:
                target.pop(key, None)


def _restore_graph_document(data: MutableMappingABC[str, Any]) -> CommentedMap:
    restored = CommentedMap()
    graph_item = CommentedMap((key, value) for key, value in data.items() if key != __CWL_VERSION__)
    if __CWL_VERSION__ in data:
        restored[__CWL_VERSION__] = data[__CWL_VERSION__]
    restored[__CWL_GRAPH__] = [graph_item]
    return restored


def _merge_document_metadata(
    restored: MutableMappingABC[str, Any], document_metadata: Mapping[str, Any]
) -> CommentedMap:
    result = CommentedMap()
    if __CWL_VERSION__ in restored:
        result[__CWL_VERSION__] = restored[__CWL_VERSION__]

    for key, value in document_metadata.items():
        if key not in (__CWL_VERSION__, __CWL_GRAPH__) and key not in result:
            result[key] = value

    for key, value in restored.items():
        if key not in result:
            result[key] = value

    return result


def _restore_document_metadata(data: Any, process: Process | list[Process]) -> Any:
    document_metadata = _preserved_document_metadata(process)

    if not document_metadata or not isinstance(data, MutableMappingABC):
        return data

    if _has_preserved_graph_document(process) and __CWL_GRAPH__ not in data:
        restored = _restore_graph_document(data)
    else:
        restored = CommentedMap(data)

    _strip_nested_document_controls(restored, document_metadata)
    if not _has_preserved_graph_document(process):
        _strip_serialized_extension_metadata(restored, process, document_metadata)
    return _merge_document_metadata(restored, document_metadata)


def _split_dict_form_requirements(
    reqs: dict[str, Any], item_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split dict-form requirements into (standard, custom) by namespaced key."""
    custom_reqs: dict[str, Any] = {}
    standard_reqs: dict[str, Any] = {}
    for req_name, req_value in reqs.items():
        if ":" in str(req_name):
            logger.debug(f"Storing custom requirement for {item_id}: {req_name}")
            custom_reqs[req_name] = req_value
        else:
            standard_reqs[req_name] = req_value
    return standard_reqs, custom_reqs


def _split_list_form_requirements(
    reqs: list[Any], item_id: str, label: str
) -> tuple[list[Any], list[Any]]:
    """Split list-form requirements/hints into (standard, custom) by namespaced class."""
    custom: list[Any] = []
    standard: list[Any] = []
    for req in reqs:
        req_class = req.get("class", "") if isinstance(req, dict) else ""
        if isinstance(req, dict) and ":" in str(req_class):
            logger.debug(f"Storing custom {label} for {item_id}: {req_class}")
            custom.append(req)
        else:
            standard.append(req)
    return standard, custom


def _merge_collected_custom_reqs(collected: list[tuple[str, Any]]) -> list[Any]:
    """Flatten dict-form/list-form custom requirements collected for one item into a list."""
    merged: list[Any] = []
    for form, data in collected:
        if form == "list":
            merged.extend(data)
        else:  # dict form -> convert to list form for uniform injection
            for req_name, req_value in data.items():
                entry: dict[str, Any] = {"class": req_name}
                if isinstance(req_value, dict):
                    entry.update(req_value)
                merged.append(entry)
    return merged


def _extract_requirements_field(item: dict[str, Any], item_id: str) -> tuple[str, Any] | None:
    """Split ``item['requirements']`` into standard/custom, in-place; return the custom entry."""
    reqs = item.get("requirements")
    if isinstance(reqs, dict):
        standard_reqs, custom_reqs = _split_dict_form_requirements(reqs, item_id)
        item["requirements"] = standard_reqs
        return ("dict", custom_reqs) if custom_reqs else None
    if isinstance(reqs, list):
        standard_reqs_list, custom_reqs_list = _split_list_form_requirements(
            reqs, item_id, "requirement"
        )
        item["requirements"] = standard_reqs_list
        return ("list", custom_reqs_list) if custom_reqs_list else None
    return None


def _extract_hints_field(item: dict[str, Any], item_id: str) -> tuple[str, Any] | None:
    """Split ``item['hints']`` into standard/custom, in-place; return the custom entry.

    Hints are a fallback: custom reqs may have landed there instead of in
    ``requirements`` (Calrissian's ``make_job_runner`` uses
    ``get_requirement()`` which searches hints, but ``KubernetesDaskPodBuilder``
    only reads ``requirements``, so these get re-injected into ``requirements``
    by ``_inject_custom_reqs_into_item``).
    """
    hints = item.get("hints")
    if not isinstance(hints, list):
        return None
    standard_hints, custom_hints = _split_list_form_requirements(
        hints, item_id, "hint as requirement"
    )
    item["hints"] = standard_hints
    return ("list", custom_hints) if custom_hints else None


def _extract_custom_reqs_from_item(
    item: dict[str, Any], item_id: str, req_cache: dict[str, Any]
) -> None:
    """
    Remove custom namespaced requirements from ``item['requirements']`` (and
    ``item['hints']`` as fallback) in-place, storing them in *req_cache* keyed
    by *item_id*. Handles both dict-form and list-form requirements/hints.
    """
    collected = [
        entry
        for entry in (
            _extract_requirements_field(item, item_id),
            _extract_hints_field(item, item_id),
        )
        if entry is not None
    ]
    if collected:
        req_cache[item_id] = _merge_collected_custom_reqs(collected)


def _clean_custom_namespaces(
    raw_process: Mapping[str, Any],
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """
    Extract custom namespaced requirements so the standard CWL parser does
    not reject them.

    Custom requirements - those whose dict key (dict-form) or ``class``
    value (list-form) contains a colon - are removed from every process
    item. Both ``$graph`` documents and single top-level process documents
    are handled.

    Document-level fields (``$namespaces``, ``$schemas``, arbitrary
    extension annotations, ...) are left untouched here: they're preserved
    generically by `_extract_document_metadata`/`_restore_document_metadata`
    instead, which operate on the original `raw_process` regardless of this
    cleaning.

    The function never mutates *raw_process* or any of its nested objects.

    Args:
        raw_process: The raw CWL document as a plain dict or CommentedMap.

    Returns:
        A 2-tuple ``(cleaned_doc, req_cache)`` where:

        * ``cleaned_doc`` - a (deep-)copy of *raw_process* with custom namespaced
          requirements removed from every process item.
        * ``req_cache`` - ``{item_id: custom_reqs}`` mapping; *custom_reqs* is a
          dict (dict-form source) or list (list-form source).
    """
    # Shallow-copy the top level so we do not mutate the caller's mapping.
    cleaned: Any = (
        raw_process.copy() if isinstance(raw_process, dict) else CommentedMap(raw_process)
    )
    req_cache: dict[str, Any] = {}

    if __CWL_GRAPH__ in cleaned and isinstance(cleaned[__CWL_GRAPH__], list):
        # Rebuild the $graph list using deep copies of each item so that we can
        # mutate requirements without touching the caller's original objects.
        new_graph = []
        for item in cleaned[__CWL_GRAPH__]:
            if not isinstance(item, dict):
                new_graph.append(item)
                continue
            cleaned_item = copy.deepcopy(item)
            item_id = cleaned_item.get("id", "unknown")
            _extract_custom_reqs_from_item(cleaned_item, item_id, req_cache)
            new_graph.append(cleaned_item)
        cleaned[__CWL_GRAPH__] = new_graph
    elif "requirements" in cleaned:
        # Single top-level process (CommandLineTool / Workflow / …).
        # Deep-copy the entire cleaned document before mutating it.
        cleaned = copy.deepcopy(cleaned)
        item_id = cleaned.get("id", "__top__")
        _extract_custom_reqs_from_item(cleaned, item_id, req_cache)

    return cleaned, req_cache


def _lookup_in_cache(item_id: str | None, cache: Mapping[str, Any]) -> Any | None:
    """
    Find *item_id* in *cache*, trying the full string first then progressively
    shorter forms (fragment after ``#``, last path segment after ``/``).

    Returns the cached value or ``None`` if not found.
    """
    if item_id is None:
        return None
    if item_id in cache:
        return cache[item_id]
    for sep in ("#", "/"):
        if sep in str(item_id):
            short = str(item_id).split(sep)[-1]
            if short in cache:
                return cache[short]
    return None


def get_custom_requirements(item_id: str) -> list[Any] | Mapping[str, Any]:
    """
    Retrieve custom requirements for a given item ID from the global cache.

    Args:
        item_id: The ID of the CWL item (CommandLineTool, Workflow, etc.)

    Returns:
        Custom requirements (list or dict) or empty list if none found
    """
    result: list[Any] | Mapping[str, Any] = _custom_requirements_cache.get(item_id, [])
    return result


def _is_url(path_or_url: str, session: requests.Session) -> bool:
    try:
        result = urlparse(path_or_url)
        return all([f"{result.scheme}://" in session.adapters, result.netloc])
    except Exception:
        return False


def load_cwl_from_yaml(
    raw_process: Mapping[str, Any] | CommentedMap,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
    session: requests.Session = _global_session,
) -> Process | list[Process]:
    """Load a CWL document from a raw dictionary.

    Custom namespaced requirements (e.g. ``calrissian:DaskGatewayRequirement``)
    are stripped before parsing - the standard parser rejects requirement
    classes it doesn't recognize when they appear directly in
    ``requirements`` - and cached so they can be reinjected by
    `dump_cwl_with_custom_requirements`. Other document-level fields
    (``$namespaces``, ``$schemas``, ...) are preserved generically and
    restored by `dump_cwl`/`dump_cwl_with_custom_requirements` regardless.

    Args:
        raw_process: Mapping representing the CWL document.
        uri: Base URI used to resolve relative references. Defaults to ``io://``.
        cwl_version: Target CWL version. Defaults to ``v1.2``.
        sort: Whether to order processes by their dependencies.
        session: HTTP session used to retrieve remote documents.

    Returns:
        The parsed process, or a list of processes for a multi-process document.
    """
    # Tracks recursion depth across load_cwl_from_yaml/_dereference_steps calls;
    # threading it as a parameter would leak into this function's public
    # signature, which callers rely on staying stable.
    global _load_depth  # noqa: PLW0603

    # At the top-level load (not a recursive call from _dereference_steps)
    # clear the cache so that state from a previous load does not bleed
    # into the current one.
    if _load_depth == 0:
        _custom_requirements_cache.clear()

    _load_depth += 1
    try:
        document_has_graph = __CWL_GRAPH__ in raw_process

        # Clean custom namespaces and requirements before processing.
        # _clean_custom_namespaces never mutates raw_process and returns a
        # local cache merged into the module global below, so
        # get_custom_requirements/extract_dask_config work without an
        # explicit arg.
        cleaned_process, local_req_cache = _clean_custom_namespaces(raw_process)
        _custom_requirements_cache.update(local_req_cache)

        updated_process = cleaned_process

        if cwl_version != cleaned_process[__CWL_VERSION__]:
            logger.debug(
                f"Updating the model from version '{cleaned_process[__CWL_VERSION__]}' to version '{cwl_version}'..."
            )

            updated_process = _upgrade_document(
                raw_process=cleaned_process,
                cwl_version=cwl_version,
                uri=uri,
            )

            logger.debug(f"Raw CWL document successfully updated to {cwl_version}!")
        else:
            logger.debug(
                f"No needs to update the Raw CWL document since it targets already the {cwl_version}"
            )

        logger.debug("Parsing the raw CWL document to the CWL Utils DOM...")

        clean_uri, fragment = urldefrag(uri)

        if fragment:
            logger.debug(f"Ignoring fragment #{fragment} from URI {clean_uri}")

        process = load_document_by_yaml(yaml=updated_process, uri=clean_uri, load_all=True)

        logger.debug("Raw CWL document successfully parsed to the CWL Utils DOM!")

        logger.debug("Dereferencing the steps[].run...")

        dereferenced_process = _dereference_steps(
            process=process,
            uri=uri,
            session=session,
            loader=load_cwl_from_location,
        )

        logger.debug("steps[].run successfully dereferenced! Dereferencing the FQNs...")

        remove_refs(dereferenced_process)

        logger.debug(
            "CWL document successfully dereferenced! Now verifying steps[].run integrity..."
        )

        assert_connected_graph(dereferenced_process)

        logger.debug("All steps[].run link are resolvable! ")

        if sort:
            logger.debug("Sorting Process instances by dependencies....")
            dereferenced_process = order_graph_by_dependencies(dereferenced_process)
            logger.debug("Sorting process is over.")

        document_metadata = _extract_document_metadata(raw_process, process=dereferenced_process)
        _preserve_document_metadata(
            process=dereferenced_process,
            document_metadata=document_metadata,
            document_has_graph=document_has_graph,
        )

        return dereferenced_process if len(dereferenced_process) > 1 else dereferenced_process[0]
    finally:
        _load_depth -= 1


def load_cwl_from_stream(
    content: TextIO,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
    session: requests.Session = _global_session,
) -> Process | list[Process]:
    """Load a CWL document from a stream of data.

    Args:
        content: Text stream containing the CWL document.
        uri: Base URI used to resolve relative references. Defaults to ``io://``.
        cwl_version: Target CWL version. Defaults to ``v1.2``.
        sort: Whether to order processes by their dependencies.
        session: HTTP session used to retrieve remote documents.

    Returns:
        The parsed process, or a list of processes for a multi-process document.
    """
    cwl_content = _yaml.load(content)

    logger.debug(f"CWL data of type {type(cwl_content)} successfully loaded from stream")

    return load_cwl_from_yaml(
        raw_process=cwl_content,
        uri=uri,
        cwl_version=cwl_version,
        sort=sort,
        session=session,
    )


def _local_source_path(path: str, session: requests.Session) -> Path | None:
    """Resolve local paths and file URIs, returning None for remote URLs.

    Raises:
        ValueError: If a file URI has a remote authority, query, or relative path.
    """
    parsed = urlparse(path)
    source_path = None
    if parsed.scheme == "file":
        if parsed.netloc.lower() not in ("", "localhost"):
            raise ValueError(f"Non-local file URI authority is not supported: {parsed.netloc}")
        if parsed.query:
            raise ValueError(f"File URI queries are not supported: {path}")
        source_path = Path(url2pathname(parsed.path))
        if not source_path.is_absolute():
            raise ValueError(f"File URI must contain an absolute path: {path}")
    elif not _is_url(path, session):
        source_path = Path(path)

    return source_path


def load_cwl_from_location(
    path: str,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
    session: requests.Session = _global_session,
) -> Process | list[Process]:
    """Load a CWL document from an HTTP(S) URL, local path, or local file URI.

    Local file URIs may use an empty authority or localhost. Percent-encoded
    paths are decoded before opening; relative references use the file URI.
    As for other sources, URI fragments do not select a process: the complete
    document is loaded.

    Args:
        path: HTTP(S) URL, local file path, or local file URI.
        cwl_version: Target CWL version. Defaults to ``v1.2``.
        sort: Whether to order processes by their dependencies.
        session: HTTP session used to retrieve remote documents.

    Returns:
        The parsed process, or a list of processes for a multi-process document.
    """
    logger.debug(f"Loading CWL document from {path}...")

    document_uri = path
    source_path = _local_source_path(path, session)

    if source_path is not None:
        document_uri = source_path.resolve().as_uri()

    def _load_cwl_from_stream(stream: TextIO) -> Process | list[Process]:
        """Load a stream using the resolved source URI and requested options."""
        logger.debug(f"Reading stream from {path}...")

        loaded = load_cwl_from_stream(
            content=stream,
            uri=document_uri,
            cwl_version=cwl_version,
            sort=sort,
            session=session,
        )

        logger.debug(f"Stream from {path} successfully load!")

        return loaded

    if source_path is None:
        response = session.get(path, stream=True)
        response.raise_for_status()

        # Read first 2 bytes to check for gzip
        magic = response.raw.read(2)
        remaining = response.raw.read()  # Read rest of the stream
        combined = BytesIO(magic + remaining)

        buffer = GzipFile(fileobj=combined) if magic == b"\x1f\x8b" else combined

        return _load_cwl_from_stream(TextIOWrapper(buffer, encoding=__DEFAULT_ENCODING__))
    if source_path.is_file():
        with source_path.open(encoding=__DEFAULT_ENCODING__) as f:
            return _load_cwl_from_stream(f)
    else:
        raise ValueError(f"Invalid source {path}: not a URL or existing file path")


def load_cwl_from_string_content(
    content: str,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
) -> Process | list[Process]:
    """Load a CWL document from its textual representation.

    Args:
        content: YAML text representing the CWL document.
        uri: Base URI used to resolve relative references. Defaults to ``io://``.
        cwl_version: Target CWL version. Defaults to ``v1.2``.
        sort: Whether to order processes by their dependencies.

    Returns:
        The parsed process, or a list of processes for a multi-process document.
    """
    return load_cwl_from_stream(
        content=StringIO(content), uri=uri, cwl_version=cwl_version, sort=sort
    )


def _schema_def_urls(req: Mapping[str, Any]) -> frozenset[str]:
    """
    Returns the set of external schema URLs a `SchemaDefRequirement`
    covers, whether its `types` entries are still lazy `$import` dicts or
    already resolved (fully inlined) type records.
    """
    urls: set[str] = set()
    for type_ in req.get("types", []) or []:
        if not isinstance(type_, dict):
            continue
        if "$import" in type_:
            urls.add(type_["$import"])
        elif isinstance(type_.get("name"), str):
            urls.add(type_["name"].split("#", 1)[0])
    return frozenset(urls)


def _is_resolved_schema_def(req: Mapping[str, Any]) -> bool:
    """True if every type in *req* is fully inlined (no lazy `$import`)."""
    types = req.get("types", []) or []
    return bool(types) and all(
        isinstance(type_, dict) and "$import" not in type_ for type_ in types
    )


_MIN_DUPLICATE_OCCURRENCES = 2


def _collect_schema_def_occurrences(
    items: list[Any],
) -> tuple[
    dict[frozenset[str], list[tuple[list[Any], int]]],
    dict[frozenset[str], list[dict[str, Any]]],
]:
    """Index every `SchemaDefRequirement` in *items* by the schema URLs it covers.

    Returns:
        A pair of mappings keyed by the requirement's schema URLs: where each
        occurrence lives (`(requirements list, index)`, to allow rewriting it
        in place) and the requirement dicts themselves (to pick a canonical
        one from).
    """
    occurrences: dict[frozenset[str], list[tuple[list[Any], int]]] = {}
    all_reqs: dict[frozenset[str], list[dict[str, Any]]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        requirements = item.get("requirements")
        if not isinstance(requirements, list):
            continue
        for idx, req in enumerate(requirements):
            if not isinstance(req, dict) or req.get("class") != "SchemaDefRequirement":
                continue
            urls = _schema_def_urls(req)
            if not urls:
                continue
            occurrences.setdefault(urls, []).append((requirements, idx))
            all_reqs.setdefault(urls, []).append(req)

    return occurrences, all_reqs


def _deduplicate_schema_def_requirements(data: dict[str, Any]) -> None:
    """
    `cwl_utils.parser.save()` serializes each Process's `requirements`
    independently, so when several processes of the same `$graph` import
    the same external schema (e.g. `eoap_cwlwrap` building its own
    `SchemaDefRequirement` for a type already resolved elsewhere from
    loading the source CWL), the dumped YAML ends up with the schema's
    type definitions duplicated once per process. cwltool's schema-salad
    loader registers external type names once per document; re-registering
    the same names a second time makes its type-equivalence checker
    recurse pathologically on non-trivial schemas (observed: RecursionError
    / multi-minute hang), even though the duplicate declarations are
    otherwise valid CWL.

    This normalizes every `SchemaDefRequirement` in *data*'s `$graph` (or
    the single top-level process) so that requirements covering the same
    set of schema URLs share the *same* dict object - preferring an
    already-resolved copy over a lazy `$import` one. `ruamel.yaml` then
    naturally emits a YAML anchor/alias for the shared object instead of
    duplicating its text, and cwltool loads the result once, cleanly.
    """
    graph = data.get(__CWL_GRAPH__)
    items: list[Any] = graph if isinstance(graph, list) else [data]
    occurrences, all_reqs = _collect_schema_def_occurrences(items)

    for urls, reqs in all_reqs.items():
        if len(reqs) < _MIN_DUPLICATE_OCCURRENCES:
            continue
        # Prefer a fully resolved copy as the shared object: cwltool needs
        # the concrete types, not just a reference to re-resolve.
        canonical = next((r for r in reqs if _is_resolved_schema_def(r)), reqs[0])
        for requirements, idx in occurrences[urls]:
            requirements[idx] = canonical


def _deduplicate_blank_named_nodes(data: dict[str, Any]) -> None:
    """
    `cwl_utils.parser.save()` gives anonymous/synthesized nodes (e.g. an
    inline `array`/`record` type used as an input's `type`) a content-derived
    blank-node `name` such as `_:<uuid>`. When the *same* anonymous type is
    independently serialized from more than one process of the same
    `$graph` (e.g. an orchestrator input and the wrapped process' matching
    input), each occurrence gets its own dict with an *equal* `name` but no
    shared identity - the same duplicate-registration issue
    `_deduplicate_schema_def_requirements` fixes for `SchemaDefRequirement`,
    just for these blank-named subtrees instead. Left alone, cwltool
    re-registers the name for every occurrence, which - like the
    `SchemaDefRequirement` case - makes its type-equivalence checker recurse
    pathologically (observed: thousands of "previously defined" warnings
    before hitting the same `RecursionError`).

    Walks *data* recursively and rewrites every later occurrence of a
    blank-named dict (its `name`'s last `/`-segment starts with `_:`) to
    point at the *first* equal one, so `ruamel.yaml` emits a shared anchor/
    alias instead of duplicating the text.
    """
    _dedupe_blank_named_node(data, seen={})


def _is_blank_named(name: str) -> bool:
    # The blank-node marker isn't always the whole name: cwl_utils also
    # mints ids like "io:/#water-bodies/stac_items/_:<uuid>", where
    # "_:<uuid>" is only the last '/'-separated segment.
    return name.rsplit("/", 1)[-1].startswith("_:")


def _dedupe_blank_named_node(node: Any, seen: dict[str, dict[str, Any]]) -> Any:
    """Recursively rewrite duplicate blank-named dicts in *node* to a shared instance."""
    if isinstance(node, dict):
        for key, value in node.items():
            node[key] = _dedupe_blank_named_node(value, seen)
        name = node.get("name")
        if isinstance(name, str) and _is_blank_named(name):
            existing = seen.get(name)
            if existing is not None and existing == node:
                return existing
            seen.setdefault(name, node)
        return node
    if isinstance(node, list):
        for idx, value in enumerate(node):
            node[idx] = _dedupe_blank_named_node(value, seen)
        return node
    return node


def _ensure_default_base_namespace_declared(data: dict[str, Any]) -> None:
    """
    Processes loaded via `load_cwl_from_yaml`/`load_cwl_from_location`/etc.
    without an explicit `uri=` default to `__DEFAULT_BASE_URI__` ("io://")
    as their base. Any anonymous/synthesized id schema-salad mints while
    parsing that document inherits it - observed as either "io://#..." or,
    for ids built by joining a relative path onto the empty-authority base
    (e.g. a nested step/port path), the single-slash "io:/#water-bodies/
    stac_items/_:<uuid>" form. Either way, nothing in the dumped output
    ever *declares* what the `io` prefix means, so cwltool warns "URI
    prefix 'io' ... not recognized, are you missing a $namespaces
    section?" on every such id when later loading the dumped document.

    Declares it once in *data*'s `$namespaces`, matching whichever exact
    form was found, unless something already assigns `io` to a different
    value (a document's own, unrelated `io` namespace is left untouched
    rather than risk clobbering it).
    """
    text = json.dumps(data)
    for candidate in (__DEFAULT_BASE_URI__, "io:/"):
        if candidate in text:
            namespaces = data.setdefault("$namespaces", {})
            namespaces.setdefault("io", candidate)
            return


def dump_cwl(process: Process | list[Process], stream: TextIO) -> None:
    """Write a CWL process or graph to a text stream as YAML.

    Args:
        process: Process or graph to serialize with preserved document metadata.
        stream: Destination for the serialized document.
    """
    data = save(
        val=process,  # type: ignore
        relative_uris=False,
    )

    _deduplicate_schema_def_requirements(data)
    _deduplicate_blank_named_nodes(data)

    data = _restore_document_metadata(data=data, process=process)

    # Runs after restoration: that call can replace data["$namespaces"]
    # wholesale, which would otherwise wipe out an "io" entry added here.
    _ensure_default_base_namespace_declared(data)

    _yaml.dump(data=data, stream=stream)


def _build_custom_req_entry(req_name: str, req_value: Any) -> dict[str, Any]:
    """Build a `requirements` entry for a dict-form custom requirement."""
    custom_req_entry: dict[str, Any] = {"class": req_name}
    if isinstance(req_value, dict):
        custom_req_entry.update(req_value)
    elif req_value is not None:
        logger.warning(
            f"Custom requirement '{req_name}' has a non-mapping value "
            f"{req_value!r}; only the 'class' key will be emitted in the "
            "serialised output."
        )
    return custom_req_entry


def _inject_custom_reqs_into_item(item: dict[str, Any], custom_reqs: Any) -> None:
    """
    Reinject *custom_reqs* (list or dict form) into ``item['requirements']``.

    All custom requirements (including calrissian:DaskGatewayRequirement) are
    injected into ``requirements`` so that Calrissian can find them - it reads
    DaskGatewayRequirement from ``requirements``, not ``hints``.
    """
    if "requirements" not in item or not isinstance(item["requirements"], list):
        item["requirements"] = []

    if isinstance(custom_reqs, list):
        item["requirements"].extend(custom_reqs)
    elif isinstance(custom_reqs, dict):
        item["requirements"].extend(
            _build_custom_req_entry(req_name, req_value)
            for req_name, req_value in custom_reqs.items()
        )


def _inject_custom_reqs_into_graph_items(
    graph_items: list[Any], custom_requirements_cache: Mapping[str, Any]
) -> None:
    for item in graph_items:
        if not isinstance(item, dict):
            continue
        # Defensive: save() should not emit a per-item cwlVersion, but strip
        # it if present rather than risk schema-salad re-validating a
        # $graph item as if it were a standalone document when this gets
        # reloaded. $namespaces/$schemas/$base are already stripped from
        # graph items (when duplicating preserved metadata) by
        # _restore_document_metadata.
        item.pop(__CWL_VERSION__, None)

        custom_reqs = _lookup_in_cache(item.get("id"), custom_requirements_cache)
        if custom_reqs is not None:
            _inject_custom_reqs_into_item(item, custom_reqs)


def _inject_custom_reqs_into_top_level(
    data: dict[str, Any], custom_requirements_cache: Mapping[str, Any]
) -> None:
    custom_reqs = _lookup_in_cache(data.get("id"), custom_requirements_cache)
    if custom_reqs is None:
        # Fallback: top-level processes without an id were cached under '__top__'.
        custom_reqs = custom_requirements_cache.get("__top__")
    if custom_reqs is not None:
        _inject_custom_reqs_into_item(data, custom_reqs)


def dump_cwl_with_custom_requirements(
    process: Process | list[Process],
    stream: TextIO,
    custom_requirements_cache: Mapping[str, Any] | None = None,
) -> None:
    """Write a CWL process or graph to a text stream, with custom requirements reinjected.

    This ensures that custom namespaced requirements (like
    ``calrissian:DaskGatewayRequirement``) are placed in the correct location
    within the ``requirements`` section. Document-level fields
    (``$namespaces``, ``$schemas``, ...) are restored the same way `dump_cwl`
    does it, generically, via the metadata preserved at load time - no
    separate namespaces cache is needed here.

    Args:
        process: Process or graph to serialize with preserved document metadata.
        stream: Destination for the serialized document.
        custom_requirements_cache: Cache of custom requirements, keyed by
            process id. Uses the module-level cache when omitted.
    """
    if custom_requirements_cache is None:
        custom_requirements_cache = _custom_requirements_cache

    data = save(
        val=process,  # type: ignore
        relative_uris=False,
    )

    _deduplicate_schema_def_requirements(data)
    _deduplicate_blank_named_nodes(data)

    data = _restore_document_metadata(data=data, process=process)

    # Runs after restoration: that call can replace data["$namespaces"]
    # wholesale, which would otherwise wipe out an "io" entry added here.
    _ensure_default_base_namespace_declared(data)

    if __CWL_GRAPH__ in data and isinstance(data[__CWL_GRAPH__], list):
        _inject_custom_reqs_into_graph_items(data[__CWL_GRAPH__], custom_requirements_cache)
    elif isinstance(data, dict):
        _inject_custom_reqs_into_top_level(data, custom_requirements_cache)

    _yaml.dump(data=data, stream=stream)


def _find_dask_config_in_dict_reqs(reqs: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for req_name, req_value in reqs.items():
        if "DaskGatewayRequirement" in req_name:
            return dict(req_value) if isinstance(req_value, dict) else {}
    return None


def _find_dask_config_in_list_reqs(reqs: list[Any]) -> Mapping[str, Any] | None:
    for req in reqs:
        if not isinstance(req, dict):
            continue
        if "DaskGatewayRequirement" in req.get("class", ""):
            return {k: v for k, v in req.items() if k != "class"}
    return None


def extract_dask_config(
    custom_requirements_cache: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Extract Dask Gateway configuration from the custom requirements cache.

    Searches for a ``DaskGatewayRequirement`` in the custom requirements and
    returns its fields as a plain mapping.

    Args:
        custom_requirements_cache: Cache of custom requirements, keyed by
            process id. Uses the module-level cache when omitted.

    Returns:
        All fields found in the ``DaskGatewayRequirement`` (except the
        ``class`` key when the requirement is represented as a list item),
        or an empty mapping if none was found.
    """
    if custom_requirements_cache is None:
        custom_requirements_cache = _custom_requirements_cache

    for item_id, reqs in custom_requirements_cache.items():
        if isinstance(reqs, dict):
            found = _find_dask_config_in_dict_reqs(reqs)
        elif isinstance(reqs, list):
            found = _find_dask_config_in_list_reqs(reqs)
        else:
            found = None
        if found is not None:
            logger.debug(f"Found DaskGatewayRequirement in {item_id}")
            return found

    logger.debug("No DaskGatewayRequirement found in custom requirements cache")
    return {}
