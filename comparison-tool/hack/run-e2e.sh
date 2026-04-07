#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

BEFORE_REPO="https://github.com/jwmatthews/quipucords-ui.git"
BEFORE_REF="3b3ce52"
ATTEMPT_REPO="https://github.com/shawn-hurley/quipucords-ui.git"
ATTEMPT_NAME="shawn"
TARGET="${TARGET:-patternfly}"
LAYERS="${LAYERS:-source,build}"

# Reuse existing workdir if WORKDIR is set, otherwise create a new one
if [[ -z "${WORKDIR:-}" ]]; then
    WORKDIR="$(mktemp -d)"
    echo "Created working directory: $WORKDIR"
else
    echo "Reusing working directory: $WORKDIR"
fi

cleanup() {
    echo ""
    echo "Temp dir preserved at: $WORKDIR"
    echo "To clean up: rm -rf $WORKDIR"
}
trap cleanup EXIT

# Clone repos if not already present
if [[ ! -d "$WORKDIR/before" ]]; then
    echo "Cloning before repo (jwmatthews/quipucords-ui @ $BEFORE_REF)..."
    git clone --quiet "$BEFORE_REPO" "$WORKDIR/before"
    (cd "$WORKDIR/before" && git checkout --quiet "$BEFORE_REF")
else
    echo "Before repo already cloned."
fi

if [[ ! -d "$WORKDIR/$ATTEMPT_NAME" ]]; then
    echo "Cloning attempt repo (shawn-hurley/quipucords-ui)..."
    git clone --quiet "$ATTEMPT_REPO" "$WORKDIR/$ATTEMPT_NAME"
else
    echo "Attempt repo already cloned."
fi

LAYERS_SLUG="${LAYERS//,/-}"
OUTPUT_DIR="$WORKDIR/output/$LAYERS_SLUG"

# Determine target flags
if [[ -d "$TARGET" ]]; then
    TARGET_FLAG="--target-dir $TARGET"
    TARGET_DISPLAY="$TARGET (external dir)"
else
    TARGET_FLAG="--target $TARGET"
    TARGET_DISPLAY="$TARGET (bundled)"
fi

echo ""
echo "Running migeval evaluate..."
echo "  --before $WORKDIR/before"
echo "  --attempt $ATTEMPT_NAME=$WORKDIR/$ATTEMPT_NAME"
echo "  --target $TARGET_DISPLAY"
echo "  --layers $LAYERS"
echo "  --output-dir $OUTPUT_DIR"
echo ""

cd "$V2_DIR"
uv run migeval evaluate \
    --before "$WORKDIR/before" \
    --attempt "$ATTEMPT_NAME=$WORKDIR/$ATTEMPT_NAME" \
    $TARGET_FLAG \
    --layers "$LAYERS" \
    --output-dir "$OUTPUT_DIR"

echo ""
echo "Results:"
echo "  JSON:     $OUTPUT_DIR/evaluation.json"
echo "  Markdown: $OUTPUT_DIR/report.md"
