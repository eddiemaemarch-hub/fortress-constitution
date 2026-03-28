#!/bin/bash
# sync_memory.sh
# Syncs fortress-constitution memory to all 4 Claude memory locations.
# Source of truth: ~/fortress-constitution/memory/
#
# Usage:
#   chmod +x sync_memory.sh
#   ./sync_memory.sh
#   ./sync_memory.sh --dry-run

DRY_RUN=false
[[ "$1" == "--dry-run" ]] && DRY_RUN=true

SOURCE="$HOME/fortress-constitution/memory"

# ── Locate desktop app memory path ────────────────────────────────────────────
DESKTOP_BASE="$HOME/Library/Application Support/Claude"
DESKTOP_MEMORY=$(find "$DESKTOP_BASE" -type d -name "memory" 2>/dev/null | head -1)

# ── Locate agent-zero worktree memory path ────────────────────────────────────
AGENT_ZERO_MEMORY=$(find "$HOME/agent-zero" -type d -name "memory" 2>/dev/null | head -1)

# ── All 4 targets ─────────────────────────────────────────────────────────────
declare -a TARGETS=(
    "$HOME/.claude/projects/-Users-eddiemae/memory"
    "$HOME/fortress-constitution/memory"
    "$DESKTOP_MEMORY"
    "$AGENT_ZERO_MEMORY"
)

declare -a LABELS=(
    "CLI          (~/.claude/projects/-Users-eddiemae/memory/)"
    "GitHub repo  (~/fortress-constitution/memory/)"
    "Desktop app  (~/Library/Application Support/Claude/.../memory/)"
    "Agent-zero   (~/agent-zero/.claude/worktrees/.../memory/)"
)

echo "═══════════════════════════════════════════════════════"
echo "  MEMORY SYNC — fortress-constitution → all 4 locations"
echo "  Source: $SOURCE"
[[ "$DRY_RUN" == true ]] && echo "  MODE: DRY RUN — no files will be written"
echo "═══════════════════════════════════════════════════════"
echo ""

FILES=$(ls "$SOURCE"/*.md 2>/dev/null)
FILE_COUNT=$(echo "$FILES" | wc -l | tr -d ' ')
echo "  Files to sync: $FILE_COUNT"
echo ""

TOTAL_SYNCED=0
TOTAL_SKIPPED=0
TOTAL_ERRORS=0

for i in "${!TARGETS[@]}"; do
    TARGET="${TARGETS[$i]}"
    LABEL="${LABELS[$i]}"
    echo "  ── ${LABEL}"

    # Skip if this is the source itself
    if [[ "$TARGET" == "$SOURCE" ]]; then
        echo "     ↳ Source — skipping self"
        echo ""
        continue
    fi

    # Skip if path is empty (not found)
    if [[ -z "$TARGET" ]]; then
        echo "     ↳ ✗ NOT FOUND — skipping"
        echo ""
        ((TOTAL_ERRORS++))
        continue
    fi

    # Skip if path doesn't exist
    if [[ ! -d "$TARGET" ]]; then
        if [[ "$DRY_RUN" == false ]]; then
            mkdir -p "$TARGET"
            echo "     ↳ Created directory: $TARGET"
        else
            echo "     ↳ [DRY RUN] Would create: $TARGET"
        fi
    fi

    synced=0
    skipped=0

    for filepath in $SOURCE/*.md; do
        filename=$(basename "$filepath")
        dest="$TARGET/$filename"

        # Check if file needs updating
        if [[ -f "$dest" ]] && cmp -s "$filepath" "$dest"; then
            ((skipped++))
        else
            if [[ "$DRY_RUN" == false ]]; then
                cp "$filepath" "$dest"
                echo "     ↳ ✓ $filename"
            else
                echo "     ↳ [DRY RUN] Would copy: $filename"
            fi
            ((synced++))
        fi
    done

    echo "     ↳ Synced: $synced  |  Already current: $skipped"
    ((TOTAL_SYNCED += synced))
    ((TOTAL_SKIPPED += skipped))
    echo ""
done

echo "═══════════════════════════════════════════════════════"
echo "  COMPLETE"
echo "  Files updated:       $TOTAL_SYNCED"
echo "  Already current:     $TOTAL_SKIPPED"
echo "  Locations not found: $TOTAL_ERRORS"
[[ "$DRY_RUN" == true ]] && echo "  (Dry run — no changes made)"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Git commit + push if anything changed ─────────────────────────────────────
if [[ "$DRY_RUN" == false ]] && [[ $TOTAL_SYNCED -gt 0 ]]; then
    echo "  Checking git status..."
    cd "$HOME/fortress-constitution" || exit 1
    if [[ -n $(git status --porcelain memory/) ]]; then
        git add memory/
        git commit -m "Sync memory — $TOTAL_SYNCED file(s) updated $(date '+%Y-%m-%d %H:%M')"
        git push origin "$(git branch --show-current)"
        echo "  ✓ Committed + pushed to GitHub"
    else
        echo "  ✓ GitHub repo already current — no commit needed"
    fi
fi
