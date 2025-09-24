"""
The CWL Loader Python library is a helper library to simplify the parse and serialize operations of CWL documents to and from [cwl-utils](https://github.com/common-workflow-language/cwl-utils) object models.

CWL Loader (c) 2025

CWL Loader is licensed under
Creative Commons Attribution-ShareAlike 4.0 International.

You should have received a copy of the license along with this work.
If not, see <https://creativecommons.org/licenses/by-sa/4.0/>.
"""

from .utils import (
    assert_connected_graph,
    remove_refs
)
from .sort import order_graph_by_dependencies
from collections import OrderedDict
from cwl_utils.parser import (
    load_document_by_yaml,
    save
)
from cwl_utils.parser import Process
from cwltool.load_tool import default_loader
from cwltool.update import update
from gzip import GzipFile
from io import (
    BytesIO,
    StringIO,
    TextIOWrapper
)
from loguru import logger
from ruamel.yaml import YAML
from ruamel.yaml.comments import (
    CommentedMap,
    CommentedSeq,
    CommentedSet,
    TaggedScalar
)
from ruamel.yaml.scalarstring import ScalarString
from ruamel.yaml.scalarfloat import ScalarFloat
from ruamel.yaml.scalarint import ScalarInt
from pathlib import Path
from typing import (
    Any,
    List,
    Mapping,
    TextIO
)
from urllib.parse import (
    urlparse,
    urldefrag
)
import requests
import os

__DEFAULT_BASE_URI__ = 'io://'
__TARGET_CWL_VERSION__ = 'v1.2'
__DEFAULT_ENCODING__ = 'utf-8'
__CWL_VERSION__ = 'cwlVersion'

_yaml = YAML()
_global_loader = default_loader()

def _is_url(path_or_url: str) -> bool:
    try:
        result = urlparse(path_or_url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except Exception:
        return False

def _dereference_steps(
    process: Process | List[Process],
    uri: str
) -> List[Process]:
    def _on_process(
        p: Process,
        accumulator: List[Process]
    ):
        for step in getattr(p, 'steps', []):
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
                        raise ValueError(f"No entry point provided for $graph referenced by {step.run}")
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
    sort: bool = True
) -> Process | List[Process]:
    '''
    Loads a CWL document from a raw dictionary.

    Args:
        `raw_process` (`dict`): The dictionary representing the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    '''
    updated_process = raw_process

    if cwl_version != raw_process[__CWL_VERSION__]:
        logger.debug(f"Updating the model from version '{raw_process[__CWL_VERSION__]}' to version '{cwl_version}'...")

        updated_process = update(
            doc=raw_process if isinstance(raw_process, CommentedMap) else CommentedMap(OrderedDict(raw_process)),
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

def load_cwl_from_stream(
    content: TextIO,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True
) -> Process | List[Process]:
    '''
    Loads a CWL document from a stream of data.

    Args:
        `content` (`TextIO`): The stream where reading the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    '''
    cwl_content = _yaml.load(content)

    logger.debug(f"CWL data of type {type(cwl_content)} successfully loaded from stream")

    return load_cwl_from_yaml(
        raw_process=cwl_content,
        uri=uri,
        cwl_version=cwl_version,
        sort=sort
    )

def load_cwl_from_location(
    path: str,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True
) -> Process | List[Process]:
    '''
    Loads a CWL document from a URL or a file on the local File System, automatically detected.

    Args:
        `path` (`str`): The URL or a file on the local File System where reading the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    '''
    logger.debug(f"Loading CWL document from {path}...")

    def _load_cwl_from_stream(stream):
        logger.debug(f"Reading stream from {path}...")

        loaded = load_cwl_from_stream(
            content=stream,
            uri=path,
            cwl_version=cwl_version,
            sort=sort
        )

        logger.debug(f"Stream from {path} successfully load!")

        return loaded

    if _is_url(path):
        response = requests.get(path, stream=True)
        response.raise_for_status()

        # Read first 2 bytes to check for gzip
        magic = response.raw.read(2)
        remaining = response.raw.read() # Read rest of the stream
        combined = BytesIO(magic + remaining)

        if b'\x1f\x8b' == magic:
            buffer = GzipFile(fileobj=combined)
        else:
            buffer = combined

        return _load_cwl_from_stream(TextIOWrapper(buffer, encoding=__DEFAULT_ENCODING__))
    elif os.path.exists(path):
        with open(path, 'r', encoding=__DEFAULT_ENCODING__) as f:
            return _load_cwl_from_stream(f)
    else:
        raise ValueError(f"Invalid source {path}: not a URL or existing file path")

def load_cwl_from_string_content(
    content: str,
    uri: str = __DEFAULT_BASE_URI__,
    cwl_version: str = __TARGET_CWL_VERSION__,
    sort: bool = True
) -> Process | List[Process]:
    '''
    Loads a CWL document from its textual representation.

    Args:
        `content` (`str`): The string text representing the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`)
    '''
    return load_cwl_from_stream(
        content=StringIO(content),
        uri=uri,
        cwl_version=cwl_version,
        sort=sort
    )

def dump_cwl(
    process: Process | List[Process],
    stream: TextIO
) -> Mapping[str, Any] | None:
    '''
    Serializes a CWL document to its YAML representation.

    Args:
        `process` (`Processes`): The CWL Process or Processes (if the CWL document is a `$graph`)
        `stream` (`Stream`): The stream where serializing the CWL document

    Returns:
        `None`: none.
    '''
    data = save(
        val=process, # type: ignore
        relative_uris=False
    )

    _yaml.dump(data=data, stream=stream)
