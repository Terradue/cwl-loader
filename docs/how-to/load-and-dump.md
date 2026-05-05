# Load and serialize CWL

Use these patterns when an application needs to read CWL, work with the parsed
`cwl-utils` objects, and write CWL back to YAML.

## Load from a local path or URL

```python
from cwl_loader import load_cwl_from_location

process = load_cwl_from_location("workflow.cwl")
```

`load_cwl_from_location()` accepts an existing local file path or a URL supported
by the request session. With the default session, HTTP and HTTPS URLs are
available.

```python
process = load_cwl_from_location(
    "https://example.com/workflows/workflow.cwl"
)
```

## Load from a string

```python
from cwl_loader import load_cwl_from_string_content

process = load_cwl_from_string_content("""
cwlVersion: v1.2
class: CommandLineTool
id: echo
baseCommand: echo
inputs: []
outputs: []
""")
```

## Load from an existing Python mapping

```python
from cwl_loader import load_cwl_from_yaml

process = load_cwl_from_yaml(
    {
        "cwlVersion": "v1.2",
        "class": "CommandLineTool",
        "id": "echo",
        "baseCommand": "echo",
        "inputs": [],
        "outputs": [],
    }
)
```

## Write CWL to YAML

```python
from cwl_loader import dump_cwl, load_cwl_from_location

process = load_cwl_from_location("workflow.cwl")

with open("build/workflow.normalized.cwl", "w", encoding="utf-8") as stream:
    dump_cwl(process, stream)
```

Create the output directory before opening the file if it does not exist:

```python
from pathlib import Path

Path("build").mkdir(parents=True, exist_ok=True)
```

## Preserve input order

By default, the loader sorts process definitions by dependency order. Disable
sorting when the caller needs to preserve the parsed order:

```python
process = load_cwl_from_location("workflow.cwl", sort=False)
```
