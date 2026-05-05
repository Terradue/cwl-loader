cwlVersion: v1.2
class: CommandLineTool
id: rio_color
requirements:
  DockerRequirement:
    dockerPull: ghcr.io/eoap/how-to/rio:1.0.0
  InitialWorkDirRequirement:
    listing:
      - entryname: run.sh
        entry: |-
          #!/bin/bash
          rio color -j -1 --out-dtype uint8 $1 rgb.tif "gamma 3 0.95, sigmoidal rgb 35 0.13"
baseCommand: ["/bin/bash", "run.sh"]
arguments:
- $( inputs.stacked.path )
inputs:
  stacked:
    type: File
outputs:
  rgb:
    type: File
    outputBinding:
      glob: rgb.tif
