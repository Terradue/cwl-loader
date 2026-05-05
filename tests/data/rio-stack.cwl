cwlVersion: v1.2
class: CommandLineTool
id: rio_stack
requirements:
  DockerRequirement:
    dockerPull: ghcr.io/eoap/how-to/rio:1.0.0
  EnvVarRequirement:
    envDef:
      GDAL_TIFF_INTERNAL_MASK: "YES"
      GDAL_HTTP_MERGE_CONSECUTIVE_RANGES: "YES"
      CPL_VSIL_CURL_ALLOWED_EXTENSIONS: ".tif"
  InitialWorkDirRequirement:
    listing:
      - entryname: run.sh
        entry: |-
          #!/bin/bash
          rio stack $@
baseCommand: ["/bin/bash", "run.sh"]
arguments:
- valueFrom: |
    ${
      var arr = [];
      for(var i=0; i<inputs.tiffs.length; i++) {
          arr.push(inputs.tiffs[i]);
      }
      return arr;
    }
- stacked.tif
inputs:
  tiffs:
    type: string[]
outputs:
  stacked:
    type: File
    outputBinding:
      glob: stacked.tif
