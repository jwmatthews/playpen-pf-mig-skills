uv run migeval evaluate \
    --before /tmp/tmp.PniHL7EKnO/before \
    --attempt "shawn-fixed=/home/jonah/Projects/github.com/shawn-hurley/quipucords-ui-fixed" \
    --target-dir ./targets/patternfly-bootstrap \
    --layers source,build,runtime,llm \
    --output-dir /tmp/tmp.PniHL7EKnO/output/full-3way
