# First steps with CWL Loader

In this tutorial we will load a small CWL document with the Python API and write
the normalized document back to disk.

## Install the package

```bash
pip install cwl-loader
```

## Create a CWL document

Create a file named `hello.cwl`:

```yaml
cwlVersion: v1.0
class: CommandLineTool
id: hello
baseCommand: echo
inputs:
  message:
    type: string
    inputBinding:
      position: 1
outputs: []
```

This is intentionally small. It gives the loader a real CWL object to parse
without requiring any external files.

## Load and write it

Create `normalize.py` next to `hello.cwl`:

```python
from pathlib import Path

from cwl_loader import dump_cwl, load_cwl_from_location

process = load_cwl_from_location("hello.cwl")

Path("build").mkdir(exist_ok=True)

with Path("build/hello.normalized.cwl").open("w", encoding="utf-8") as stream:
    dump_cwl(process, stream)

print(f"Loaded process: {process.id}")
```

Run it:

```bash
python normalize.py
```

You should now have a `build/hello.normalized.cwl` file. Notice that the loader
accepted a `v1.0` input document and wrote a normalized document using the
target CWL model.

## Load from text

The same pattern works when the CWL document is already in memory:

```python
from cwl_loader import load_cwl_from_string_content

process = load_cwl_from_string_content("""
cwlVersion: v1.2
class: CommandLineTool
id: inline-hello
baseCommand: echo
inputs: []
outputs: []
""")

print(process.id)
```

You have now used the two most common pieces of the library: loading CWL into a
`cwl-utils` object model and serializing it back to YAML.
