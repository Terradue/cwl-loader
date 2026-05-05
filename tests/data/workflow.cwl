cwlVersion: v1.2

$graph:
- class: Workflow
  id: main
  requirements: 
    InlineJavascriptRequirement: {}
    NetworkAccess:
      networkAccess: true
    ScatterFeatureRequirement: {}
    MultipleInputFeatureRequirement: {}
  inputs:
    stac-item: 
      type: string
    epsg_code:
      type: string
      default: "native"
    bands:
      type: string[]
  outputs:
    rgb-tif:
      outputSource: step_color/rgb
      type: File
    stack:
      outputSource: 
      - step_stack/stacked
      - step_warp_stack/stacked
      pickValue: the_only_non_null
      type: File
  steps:
    step_curl:
      in: 
        stac_item: stac-item
        common_band_name: bands
      out: 
      - hrefs
      run:
        stac.cwl
      scatter: common_band_name
      scatterMethod: dotproduct
    step_stack:
      in:
        tiffs: 
          source: step_curl/hrefs
        epsg_code: epsg_code
      out:
      - stacked
      run:
        rio-stack.cwl
      when: $( inputs.epsg_code == "native")

    step_warp_stack:
      in:
        tiffs: 
          source: step_curl/hrefs
        epsg_code: epsg_code
      out:
      - stacked
      run:
        rio-warp-stack.cwl
      when: $( inputs.epsg_code != "native")

    step_color:
      in:
        stacked:
          source:
          - step_stack/stacked
          - step_warp_stack/stacked
          pickValue: the_only_non_null
      out:
      - rgb
      run:
        rio-color.cwl
