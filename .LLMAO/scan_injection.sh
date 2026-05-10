#!/usr/bin/env bash
# scan_injection.sh — scan .apm/ artifacts for known prompt injection patterns
# Added as check #8 in the validation protocol (AGENTS.md)

set -euo pipefail

TARGET_DIR="${1:-.apm}"

# Patterns that indicate prompt injection attempts in markdown artifacts
# These patterns target text that tries to override agent instructions
PATTERNS=(
    "ignore previous instructions"
    "ignore all previous"
    "ignore the above"
    "disregard previous"
    "disregard all previous"
    "disregard the above"
    "forget previous instructions"
    "forget all previous"
    "you are now"
    "you are a"
    "new instructions:"
    "system prompt:"
    "override instructions"
    "act as if"
    "pretend you are"
    "from now on you"
    "ignore your instructions"
    "do not follow"
    "bypass"
    "jailbreak"
)

if [ ! -d "$TARGET_DIR" ]; then
    echo "SKIP: $TARGET_DIR does not exist"
    exit 0
fi

# Build grep pattern from array
GREP_PATTERN=""
for p in "${PATTERNS[@]}"; do
    if [ -z "$GREP_PATTERN" ]; then
        GREP_PATTERN="$p"
    else
        GREP_PATTERN="$GREP_PATTERN|$p"
    fi
done

# Search markdown files in the target directory
MATCHES=$(grep -riEn "$GREP_PATTERN" "$TARGET_DIR" --include="*.md" --include="*.yaml" --include="*.json" 2>/dev/null || true)

if [ -n "$MATCHES" ]; then
    echo "WARN: Potential prompt injection patterns found in $TARGET_DIR:"
    echo ""
    echo "$MATCHES"
    echo ""
    echo "Review these matches manually. False positives are possible"
    echo "(e.g., documentation about injection patterns)."
    exit 1
else
    echo "OK: No injection patterns found in $TARGET_DIR"
    exit 0
fi
