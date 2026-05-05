cwlVersion: v1.2
class: CommandLineTool
id: stac
requirements:
  DockerRequirement:
    dockerPull: docker.io/curlimages/curl:latest
baseCommand: curl
stdout: message
arguments:
- $( inputs.stac_item )
inputs:
  stac_item:
    type: string
  common_band_name:
    type: string
outputs:
  hrefs:
    type: string
    outputBinding:
      glob: message
      loadContents: true
      outputEval: |
        ${
          const assets = JSON.parse(self[0].contents).assets;
          const bandKey = Object.keys(assets).find(key =>
            assets[key]['eo:bands'] &&
            assets[key]['eo:bands'].length === 1 &&
            assets[key]['eo:bands'].some(band => band.common_name === inputs.common_band_name)
          );
          if (!bandKey) {
            throw new Error(`No valid asset found for band: ${inputs.common_band_name}`);
          }
          return assets[bandKey].href;
        }
