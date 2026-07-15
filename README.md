# cwl-loader

[![PyPI - Version](https://img.shields.io/pypi/v/cwl-loader.svg)](https://pypi.org/project/cwl-loader)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/cwl-loader.svg)](https://pypi.org/project/cwl-loader)

`cwl-loader` provides utilities to load CWL documents (local files, URLs, streams, or strings) into [cwl-utils](https://github.com/common-workflow-language/cwl-utils) object models, normalize references, and sort dependency graphs.

> [!IMPORTANT]
> The `cwl-loader bundle` CLI has moved to
> [Transpiler Mate](https://terradue.github.io/transpiler-mate/). This package
> continues to provide the Python API for loading and serializing CWL documents.

## Installation

```bash
pip install cwl-loader
```

## Quick Start

Load a CWL document from a URL or local path:

```python
from cwl_loader import load_cwl_from_location

process = load_cwl_from_location("workflow.cwl")
```

Load from in-memory text:

```python
from cwl_loader import load_cwl_from_string_content

content = """
cwlVersion: v1.2
class: CommandLineTool
id: example-tool
baseCommand: echo
inputs: []
outputs: []
"""

process = load_cwl_from_string_content(content)
```

Dump back to YAML:

```python
from cwl_loader import dump_cwl

with open("normalized.cwl", "w", encoding="utf-8") as out:
    dump_cwl(process, out)
```

## Development

Run tests:

```bash
task test
```

Or directly with Hatch:

```bash
hatch run test:test
```

Run code quality checks:

```bash
task check
task lint
```

## Documentation

Project documentation is published at:
https://Terradue.github.io/cwl-loader/

## Contributing

Issues and pull requests are welcome:
https://github.com/eoap/cwl-loader/issues

## License

Licensed under the Apache License 2.0.
