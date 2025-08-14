"""
The CWL Loader Python library is a helper library to simplify the parse and serialize operations of CWL documents to and from [cwl-utils](https://github.com/common-workflow-language/cwl-utils) object models.

CWL Loader (c) 2025

CWL Loader is licensed under
Creative Commons Attribution-ShareAlike 4.0 International.

You should have received a copy of the license along with this work.
If not, see <https://creativecommons.org/licenses/by-sa/4.0/>.
"""

import sys
from cwl_utils.parser import (
    load_document_by_yaml,
    save
)
from cwl_utils.parser import Process
from cwltool.load_tool import default_loader
from cwltool.update import (
    update,
    ORIGINAL_CWLVERSION
)
from gzip import GzipFile
from io import (
    BytesIO,
    IOBase,
    StringIO,
    TextIOWrapper
)
from loguru import logger
from ruamel.yaml import YAML
from pathlib import Path
from typing import (
    Any,
    Optional,
    TypeVar,
    Union
)
from urllib.parse import urlparse
import requests
import os

Stream = TypeVar('Stream', bound=IOBase)
'''A generic type to accept `io.IOBase` specializations only.'''

Processes = TypeVar('Processes', bound=Union[Process, list[Process]])
'''A single CWL Process or a list of Processes union type.'''

__DEFAULT_BASE_URI__ = 'io://'
__TARGET_CWL_VERSION__ = 'v1.2'
__DEFAULT_ENCODING__ = 'utf-8'

_yaml = YAML()

def _clean_part(
    value: str,
    separator: str = '/'
) -> str:
    return value.split(separator)[-1]

def _clean_process(process: Process):
    process.id = _clean_part(process.id, '#')

    logger.info(f"  Cleaning {process.class_} {process.id}...")

    for parameters in [ process.inputs, process.outputs ]:
        for parameter in parameters:
            parameter.id = _clean_part(parameter.id)

            if hasattr(parameter, 'outputSource'):
                for i, output_source in enumerate(parameter.outputSource):
                    parameter.outputSource[i] = _clean_part(output_source, f"{process.id}/")

    for step in getattr(process, 'steps', []):
        step.id = _clean_part(step.id)

        for step_in in getattr(step, 'in_', []):
            step_in.id = _clean_part(step_in.id)
            step_in.source = _clean_part(step_in.source, f"{process.id}/")

        if step.out:
            if isinstance(step.out, list):
                step.out = [_clean_part(step_out) for step_out in step.out]
            else:
               step.out = _clean_part(step)

        if step.run:
            step.run = step.run[step.run.rfind('#'):]

        if step.scatter:
            if isinstance(step.scatter, list):
                step.scatter = [_clean_part(scatter, f"{process.id}/") for scatter in step.scatter]
            else:
                step.scatter = _clean_part(step.scatter, f"{process.id}/")
    
    if process.extension_fields:
        process.extension_fields.pop(ORIGINAL_CWLVERSION)

def _is_url(path_or_url: str) -> bool:
    try:
        result = urlparse(path_or_url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except Exception:
        return False

def load_cwl_from_yaml(
    raw_process: dict,
    uri: Optional[str] = __DEFAULT_BASE_URI__,
    cwl_version: Optional[str] = __TARGET_CWL_VERSION__
) -> Processes:
    '''
    Loads a CWL document from a raw dictionary.

    Args:
        `raw_process` (`dict`): The dictionary representing the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    '''
    logger.info(f"Updating the model to {cwl_version}...")

    updated_process = update(
        doc=raw_process,
        loader=default_loader(),
        baseuri=uri,
        enable_dev=False,
        metadata={'cwlVersion': cwl_version},
        update_to=cwl_version
    )

    logger.info(f"Raw CWL document successfully updated to {cwl_version}! Now converting to the CWL model...")

    process = load_document_by_yaml(
        yaml=updated_process,
        uri=uri,
        load_all=True
    )

    logger.info(f"Raw CWL document successfully updated to {cwl_version}! Now dereferencing the FQNs...")

    if isinstance(process, list):
        for p in process:
            _clean_process(p)
    else:
        _clean_process(process)

    logger.info('CWL document successfully dereferenced!')

    return process

def load_cwl_from_stream(
    content: Stream,
    uri: Optional[str] = __DEFAULT_BASE_URI__,
    cwl_version: Optional[str] = __TARGET_CWL_VERSION__
) -> Processes:
    '''
    Loads a CWL document from a stream of data.

    Args:
        `content` (`Stream`): The stream where reading the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    '''
    cwl_content = _yaml.load(content)
    return load_cwl_from_yaml(
        raw_process=cwl_content,
        uri=uri,
        cwl_version=cwl_version
    )

def load_cwl_from_location(
    path: str,
    cwl_version: Optional[str] = __TARGET_CWL_VERSION__
) -> Processes:
    '''
    Loads a CWL document from a URL or a file on the local File System, automatically detected.

    Args:
        `path` (`str`): The URL or a file on the local File System where reading the CWL document
        `uri` (`Optional[str]`): The CWL document URI. Default to `io://`
        `cwl_version` (`Optional[str]`): The CWL document version. Default to `v1.2`

    Returns:
        `Processes`: The parsed CWL Process or Processes (if the CWL document is a `$graph`).
    '''
    logger.info(f"Loading CWL document from {path}...")

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

        return load_cwl_from_stream(
            content=TextIOWrapper(buffer, encoding=__DEFAULT_ENCODING__),
            uri=path,
            cwl_version=cwl_version
        )
    elif os.path.exists(path):
        with open(path, 'r', encoding=__DEFAULT_ENCODING__) as f:
            return load_cwl_from_stream(
                content=f,
                uri=path,
                cwl_version=cwl_version
            )
    else:
        raise ValueError(f"Invalid source {path}: not a URL or existing file path")

def load_cwl_from_string_content(
    content: str,
    uri: Optional[str] = __DEFAULT_BASE_URI__,
    cwl_version: Optional[str] = __TARGET_CWL_VERSION__
) -> Processes:
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
        cwl_version=cwl_version
    )

def dump_cwl(
    process: Processes,
    stream: Stream
):
    '''
    Serializes a CWL document to its YAML representation.

    Args:
        `process` (`Processes`): The CWL Process or Processes (if the CWL document is a `$graph`)
        `stream` (`Stream`): The stream where serializing the CWL document

    Returns:
        `None`: none.
    '''
    data = save(
        val=process,
        relative_uris=False
    )
    _yaml.dump(data=data, stream=stream)
