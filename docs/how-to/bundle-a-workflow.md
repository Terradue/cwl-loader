# Bundle a workflow from the command line

Use `cwl-loader bundle` when you want to resolve a CWL workflow and write the
result to a file from the shell.

## Bundle a local workflow

```bash
cwl-loader bundle workflow.cwl --output build/workflow.bundle.cwl
```

The command creates the output directory when it does not exist. The input file
is not modified.

## Bundle a remote workflow

```bash
cwl-loader bundle \
  https://example.com/workflows/workflow.cwl \
  --output build/workflow.bundle.cwl
```

The CLI mounts adapters for `file://`, `s3://`, and `oci://` sources, and keeps
the standard Requests adapters for `http://` and `https://`.

## Bundle a workflow with OCI imports

Set OCI credentials with environment variables:

```bash
OCI_HOSTNAME=ghcr.io \
OCI_USERNAME=my-user \
OCI_PASSWORD=my-password \
cwl-loader bundle workflow_oci.cwl --output build/workflow_oci.bundle.cwl
```

Or provide them as options:

```bash
cwl-loader bundle workflow_oci.cwl \
  --output build/workflow_oci.bundle.cwl \
  --oci-hostname ghcr.io \
  --oci-username my-user \
  --oci-password my-password
```

When a `steps[].run` value references a process inside an external `$graph`, add
the process fragment:

```yaml
run: oci://ghcr.io/terradue/cwl-loader/stac:latest#stac
```

If the external `$graph` contains more than one process and no fragment is
provided, the loader cannot choose the workflow entry point.
