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

from .utils import assert_connected_graph, remove_refs
from .sort import order_graph_by_dependencies
from collections import OrderedDict
from cwl_utils.parser import load_document_by_yaml, save
from cwl_utils.parser import Process
from cwltool.load_tool import default_loader
from cwltool.update import update
from gzip import GzipFile
from io import BytesIO, StringIO, TextIOWrapper
from loguru import logger
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from typing import (
    Any,
    List,
    Mapping,
    Optional,
    TextIO,
    Tuple
)
from urllib.parse import (
    urlparse,
    urldefrag
)
import copy
import requests
import os

__DEFAULT_BASE_URI__ = "io://"
__TARGET_CWL_VERSION__ = "v1.2"
__DEFAULT_ENCODING__ = "utf-8"
__CWL_VERSION__ = "cwlVersion"

_yaml = YAML()
_global_loader = default_loader()

# Module-level caches storing context from the most recent load.
# Cleared at the start of each top-level load (depth == 0) to prevent leaking
# state between successive loads.
_custom_requirements_cache: dict = {}
_original_namespaces: dict = {}
_load_depth: int = 0


def _extract_custom_reqs_from_item(
    item: dict,
    item_id: str,
    req_cache: dict
) -> None:
    """
    Remove custom namespaced requirements from ``item['requirements']`` (and
    ``item['hints']`` as fallback) in-place, storing them in *req_cache* keyed
    by *item_id*.

    Custom requirements found in ``hints`` are also extracted so that they can
    be re-injected into ``requirements`` by ``_inject_custom_reqs_into_item``
    (Calrissian's ``make_job_runner`` uses ``get_requirement()`` which searches
    hints, but ``KubernetesDaskPodBuilder`` only reads ``requirements``).

    Handles both dict-form and list-form requirements/hints.
    """
    collected: list = []

    # --- process requirements ---
    reqs = item.get('requirements')
    if isinstance(reqs, dict):
        custom_reqs: dict = {}
        standard_reqs: dict = {}
        for req_name, req_value in reqs.items():
            if ':' in str(req_name):
                logger.debug(f"Storing custom requirement for {item_id}: {req_name}")
                custom_reqs[req_name] = req_value
            else:
                standard_reqs[req_name] = req_value
        if custom_reqs:
            collected.append(('dict', custom_reqs))
        item['requirements'] = standard_reqs
    elif isinstance(reqs, list):
        custom_reqs_list: list = []
        standard_reqs_list: list = []
        for req in reqs:
            if isinstance(req, dict):
                req_class = req.get('class', '')
                if ':' in str(req_class):
                    logger.debug(f"Storing custom requirement for {item_id}: {req_class}")
                    custom_reqs_list.append(req)
                else:
                    standard_reqs_list.append(req)
            else:
                standard_reqs_list.append(req)
        if custom_reqs_list:
            collected.append(('list', custom_reqs_list))
        item['requirements'] = standard_reqs_list

    # --- process hints (fallback: custom reqs may have landed here) ---
    hints = item.get('hints')
    if isinstance(hints, list):
        custom_hints: list = []
        standard_hints: list = []
        for hint in hints:
            if isinstance(hint, dict):
                hint_class = hint.get('class', '')
                if ':' in str(hint_class):
                    logger.debug(f"Storing custom hint as requirement for {item_id}: {hint_class}")
                    custom_hints.append(hint)
                else:
                    standard_hints.append(hint)
            else:
                standard_hints.append(hint)
        if custom_hints:
            collected.append(('list', custom_hints))
        item['hints'] = standard_hints

    # Merge all collected custom reqs into a single list for this item
    if collected:
        merged: list = []
        for form, data in collected:
            if form == 'list':
                merged.extend(data)
            else:  # dict form → convert to list form for uniform injection
                for req_name, req_value in data.items():
                    entry: dict = {'class': req_name}
                    if isinstance(req_value, dict):
                        entry.update(req_value)
                    merged.append(entry)
        req_cache[item_id] = merged


def _clean_custom_namespaces(
    raw_process: Mapping[str, Any]
) -> Tuple[Mapping[str, Any], dict, dict]:
    """
    Extract custom namespaced requirements and record ``$namespaces`` for later
    restoration.

    Custom requirements - those whose dict key (dict-form) or ``class`` value
    (list-form) contains a colon - are removed so that the standard CWL parser
    does not reject them.  Both ``$graph`` documents and single top-level process
    documents are handled.

    The function never mutates *raw_process* or any of its nested objects.

    Args:
        raw_process: The raw CWL document as a plain dict or CommentedMap.

    Returns:
        A 3-tuple ``(cleaned_doc, req_cache, ns_store)`` where:

        * ``cleaned_doc`` – a (deep-)copy of *raw_process* with custom namespaced
          requirements removed from every process item.
        * ``req_cache`` – ``{item_id: custom_reqs}`` mapping; *custom_reqs* is a
          dict (dict-form source) or list (list-form source).
        * ``ns_store`` – ``{'__root__': {…}}`` if ``$namespaces`` was present,
          empty dict otherwise.
    """
    # Shallow-copy the top level so we do not mutate the caller's mapping.
    cleaned: Any = raw_process.copy() if isinstance(raw_process, dict) else CommentedMap(raw_process)
    req_cache: dict = {}
    ns_store: dict = {}

    if '$namespaces' in cleaned:
        ns_store['__root__'] = dict(cleaned['$namespaces'])
        logger.debug(f"Saved original $namespaces: {ns_store['__root__']}")

    if '$graph' in cleaned and isinstance(cleaned['$graph'], list):
        # Rebuild the $graph list using deep copies of each item so that we can
        # mutate requirements without touching the caller's original objects.
        new_graph = []
        for item in cleaned['$graph']:
            if isinstance(item, dict):
                item = copy.deepcopy(item)
                item_id = item.get('id', 'unknown')
                _extract_custom_reqs_from_item(item, item_id, req_cache)
            new_graph.append(item)
        cleaned['$graph'] = new_graph
    elif 'requirements' in cleaned:
        # Single top-level process (CommandLineTool / Workflow / …).
        # Deep-copy the entire cleaned document before mutating it.
        cleaned = copy.deepcopy(cleaned)
        item_id = cleaned.get('id', '__top__')
        _extract_custom_reqs_from_item(cleaned, item_id, req_cache)

    return cleaned, req_cache, ns_store


def _lookup_in_cache(item_id: Optional[str], cache: Mapping[str, Any]) -> Optional[Any]:
    """
    Find *item_id* in *cache*, trying the full string first then progressively
    shorter forms (fragment after ``#``, last path segment after ``/``).

    Returns the cached value or ``None`` if not found.
    """
    if item_id is None:
        return None
    if item_id in cache:
        return cache[item_id]
    for sep in ('#', '/'):
        if sep in str(item_id):
            short = str(item_id).split(sep)[-1]
            if short in cache:
                return cache[short]
    return None


def get_custom_requirements(item_id: str) -> List[Any] | Mapping[str, Any]:
    """
    Retrieve custom requirements for a given item ID from the global cache.

    Args:
        item_id: The ID of the CWL item (CommandLineTool, Workflow, etc.)

    Returns:
        Custom requirements (list or dict) or empty list if none found
    """
    return _custom_requirements_cache.get(item_id, [])


def _is_url(path_or_url: str) -> bool:
    try:
        result = urlparse(path_or_url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def _dereference_steps(process: Process | List[Process], uri: str) -> List[Process]:
    def _on_process(p: Process, accumulator: List[Process]):
        for step in getattr(p, "steps", []):
            logger.debug(f"Checking if {step.run} must be externally imported...")

            run_url, fragment = urldefrag(step.run)

            logger.debug(f"run_url: {run_url} - uri: {uri}")

            if run_url and not uri == run_url:
                referenced = load_cwl_from_location(run_url)

                if isinstance(referenced, list):
                    accumulator += referenced

                    if fragment:
                        step.run = f"#{fragment}"
                    elif 1 == len(referenced):
                        step.run = f"#{referenced[0].id}"
                    else:
                        raise ValueError(
                            f"No entry point provided for $graph referenced by {step.run}"
                        )
                else:
                    accumulator.append(referenced)
                    step.run = f"#{referenced.id}"

    result: List[Process] = process if isinstance(process, list) else [process]

    if isinstance(process, list):
        for p in process:
            _on_process(p, result)
    else:
        _on_process(process, result)

    return result


def load_cwl_from_yaml(
    raw_process: Mapping[str, Any] | CommentedMap,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
) -> Process | List[Process]:
    """
    Loads a CWL document from a raw dictionary.

    Args:
        `raw_process` (`dict`): The dictionary representing the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`
        `sort` (`Optional[bool]`): Sort processes by dependencies. Default to `True`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    """
    global _load_depth

    # At the top-level load (not a recursive call from _dereference_steps) clear
    # the caches so that state from a previous load does not bleed into the
    # current one.
    if _load_depth == 0:
        _custom_requirements_cache.clear()
        _original_namespaces.clear()

    _load_depth += 1
    try:
        # Clean custom namespaces and requirements before processing.
        # _clean_custom_namespaces never mutates raw_process and returns local dicts.
        cleaned_process, local_req_cache, local_ns = _clean_custom_namespaces(raw_process)

        # Merge per-document caches into the module globals so they are accessible
        # via get_custom_requirements / extract_dask_config without an explicit arg.
        _custom_requirements_cache.update(local_req_cache)
        _original_namespaces.update(local_ns)

        updated_process = cleaned_process

        if cwl_version != cleaned_process[__CWL_VERSION__]:
            logger.debug(f"Updating the model from version '{cleaned_process[__CWL_VERSION__]}' to version '{cwl_version}'...")

            updated_process = update(
                doc=cleaned_process if isinstance(cleaned_process, CommentedMap) else CommentedMap(OrderedDict(cleaned_process)),
                loader=_global_loader,
                baseuri=uri,
                enable_dev=False,
                metadata=CommentedMap(OrderedDict({'cwlVersion': cwl_version})),
                update_to=cwl_version
            )

            logger.debug(f"Raw CWL document successfully updated to {cwl_version}!")
        else:
            logger.debug(f"No needs to update the Raw CWL document since it targets already the {cwl_version}")

        logger.debug('Parsing the raw CWL document to the CWL Utils DOM...')

        clean_uri, fragment = urldefrag(uri)

        if fragment:
            logger.debug(f"Ignoring fragment #{fragment} from URI {clean_uri}")

        process = load_document_by_yaml(
            yaml=updated_process,
            uri=clean_uri,
            load_all=True
        )

        logger.debug('Raw CWL document successfully parsed to the CWL Utils DOM!')

        logger.debug('Dereferencing the steps[].run...')

        dereferenced_process = _dereference_steps(
            process=process,
            uri=uri
        )

        logger.debug('steps[].run successfully dereferenced! Dereferencing the FQNs...')

        remove_refs(dereferenced_process)

        logger.debug('CWL document successfully dereferenced! Now verifying steps[].run integrity...')

        assert_connected_graph(dereferenced_process)

        logger.debug('All steps[].run link are resolvable! ')

        if sort:
            logger.debug('Sorting Process instances by dependencies....')
            dereferenced_process = order_graph_by_dependencies(dereferenced_process)
            logger.debug('Sorting process is over.')

        return dereferenced_process if len(dereferenced_process) > 1 else dereferenced_process[0]
    finally:
        _load_depth -= 1

def load_cwl_from_stream(
    content: TextIO,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
) -> Process | List[Process]:
    """
    Loads a CWL document from a stream of data.

    Args:
        `content` (`TextIO`): The stream where reading the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    """
    cwl_content = _yaml.load(content)

    logger.debug(
        f"CWL data of type {type(cwl_content)} successfully loaded from stream"
    )

    return load_cwl_from_yaml(
        raw_process=cwl_content, uri=uri, cwl_version=cwl_version, sort=sort
    )


def load_cwl_from_location(
    path: str, cwl_version: str = __TARGET_CWL_VERSION__, sort: bool = True
) -> Process | List[Process]:
    """
    Loads a CWL document from a URL or a file on the local File System, automatically detected.

    Args:
        `path` (`str`): The URL or a file on the local File System where reading the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    """
    logger.debug(f"Loading CWL document from {path}...")

    def _load_cwl_from_stream(stream):
        logger.debug(f"Reading stream from {path}...")

        loaded = load_cwl_from_stream(
            content=stream, uri=path, cwl_version=cwl_version, sort=sort
        )

        logger.debug(f"Stream from {path} successfully load!")

        return loaded

    if _is_url(path):
        response = requests.get(path, stream=True)
        response.raise_for_status()

        # Read first 2 bytes to check for gzip
        magic = response.raw.read(2)
        remaining = response.raw.read()  # Read rest of the stream
        combined = BytesIO(magic + remaining)

        if b"\x1f\x8b" == magic:
            buffer = GzipFile(fileobj=combined)
        else:
            buffer = combined

        return _load_cwl_from_stream(
            TextIOWrapper(buffer, encoding=__DEFAULT_ENCODING__)
        )
    elif os.path.exists(path):
        with open(path, "r", encoding=__DEFAULT_ENCODING__) as f:
            return _load_cwl_from_stream(f)
    else:
        raise ValueError(f"Invalid source {path}: not a URL or existing file path")


def load_cwl_from_string_content(
    content: str,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True,
) -> Process | List[Process]:
    """
    Loads a CWL document from its textual representation.

    Args:
        `content` (`str`): The string text representing the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`)
    """
    return load_cwl_from_stream(
        content=StringIO(content), uri=uri, cwl_version=cwl_version, sort=sort
    )


def dump_cwl(process: Process | List[Process], stream: TextIO):
    """
    Serializes a CWL document to its YAML representation.

    Args:
        `process` (`Processes`): The CWL Process or Processes (if the CWL document is a `$graph`)
        `stream` (`Stream`): The stream where serializing the CWL document

    Returns:
        `None`: none.
    """
    data = save(
        val=process,  # type: ignore
        relative_uris=False,
    )

    _yaml.dump(data=data, stream=stream)

def _inject_custom_reqs_into_item(item: dict, custom_reqs: Any) -> None:
    """
    Reinject *custom_reqs* (list or dict form) into ``item['requirements']``.

    All custom requirements (including calrissian:DaskGatewayRequirement) are
    injected into ``requirements`` so that Calrissian can find them - it reads
    DaskGatewayRequirement from ``requirements``, not ``hints``.
    """
    if 'requirements' not in item or not isinstance(item['requirements'], list):
        item['requirements'] = []

    if isinstance(custom_reqs, list):
        for custom_req in custom_reqs:
            item['requirements'].append(custom_req)
    elif isinstance(custom_reqs, dict):
        for req_name, req_value in custom_reqs.items():
            custom_req_entry: dict = {'class': req_name}
            if isinstance(req_value, dict):
                custom_req_entry.update(req_value)
            elif req_value is not None:
                logger.warning(
                    f"Custom requirement '{req_name}' has a non-mapping value "
                    f"{req_value!r}; only the 'class' key will be emitted in the "
                    "serialised output."
                )
            item['requirements'].append(custom_req_entry)


def dump_cwl_with_custom_requirements(
    process: Process | List[Process],
    stream: TextIO,
    custom_requirements_cache: Optional[Mapping[str, Any]] = None,
    original_namespaces: Optional[Mapping[str, Any]] = None
):
    """
    Serializes a CWL document with custom requirements properly reinjected into the requirements section.

    This function ensures that custom namespaced requirements (like calrissian:DaskGatewayRequirement)
    are placed in the correct location within the 'requirements' section.

    Args:
        `process` (`Processes`): The CWL Process or Processes (if the CWL document is a `$graph`)
        `stream` (`Stream`): The stream where serializing the CWL document
        `custom_requirements_cache` (`Mapping[str, Any]`, optional): Cache of custom requirements.
                                    If None, uses the module-level cache.
        `original_namespaces` (`Mapping[str, Any]`, optional): Saved $namespaces mapping.
                                    If None, uses the module-level cache.

    Returns:
        `None`: none.
    """
    if custom_requirements_cache is None:
        custom_requirements_cache = _custom_requirements_cache
    if original_namespaces is None:
        original_namespaces = _original_namespaces

    data = save(
        val=process, # type: ignore
        relative_uris=False
    )

    if '__root__' in original_namespaces:
        data['$namespaces'] = original_namespaces['__root__']
        logger.debug(f"Restored original $namespaces: {data['$namespaces']}")

    if '$graph' in data and isinstance(data['$graph'], list):
        for item in data['$graph']:
            if isinstance(item, dict):
                item_id = item.get('id')

                if 'cwlVersion' in item:
                    del item['cwlVersion']
                if '$namespaces' in item:
                    del item['$namespaces']

                custom_reqs = _lookup_in_cache(item_id, custom_requirements_cache)
                if custom_reqs is not None:
                    _inject_custom_reqs_into_item(item, custom_reqs)
    else:
        # Single top-level process (no $graph wrapper).
        item_id = data.get('id') if isinstance(data, dict) else None
        custom_reqs = _lookup_in_cache(item_id, custom_requirements_cache)
        if custom_reqs is None:
            # Fallback: top-level processes without an id were cached under '__top__'.
            custom_reqs = custom_requirements_cache.get('__top__')
        if custom_reqs is not None and isinstance(data, dict):
            _inject_custom_reqs_into_item(data, custom_reqs)

    _yaml.dump(data=data, stream=stream)

def extract_dask_config(
    custom_requirements_cache: Optional[Mapping[str, Any]] = None
) -> Mapping[str, Any]:
    """
    Extracts Dask Gateway configuration from custom requirements cache.

    This utility function searches for DaskGatewayRequirement in the custom requirements
    and returns a dictionary with the Dask configuration parameters.

    Args:
        `custom_requirements_cache` (`Mapping[str, Any]`, optional): Cache of custom requirements.
                                     If None, uses the module-level cache.

    Returns:
        `Mapping[str, Any]`: Dictionary containing all fields found in the
                            DaskGatewayRequirement (except the `class` key when
                            the requirement is represented as a list item).
                            Returns empty dict if no DaskGatewayRequirement found.
    """
    if custom_requirements_cache is None:
        custom_requirements_cache = _custom_requirements_cache

    for item_id, reqs in custom_requirements_cache.items():
        if isinstance(reqs, dict):
            for req_name, req_value in reqs.items():
                if 'DaskGatewayRequirement' in req_name:
                    logger.debug(f"Found DaskGatewayRequirement in {item_id}")
                    return dict(req_value) if isinstance(req_value, dict) else {}
        elif isinstance(reqs, list):
            for req in reqs:
                if isinstance(req, dict):
                    req_class = req.get('class', '')
                    if 'DaskGatewayRequirement' in req_class:
                        logger.debug(f"Found DaskGatewayRequirement in {item_id}")
                        return {k: v for k, v in req.items() if k != 'class'}

    logger.debug("No DaskGatewayRequirement found in custom requirements cache")
    return {}
