#!/bin/sh
# PreToolUse guard: this clone is a GitHub fork of ideoforms/AbletonOSC.
# `gh pr create` without an explicit --repo resolves to the PARENT. Refuse any
# PR creation that does not name the fork, and anything that names ideoforms.
cmd=$(jq -r '.tool_input.command // ""')
case "$cmd" in
  *"gh pr create"*|*"gh pr new"*) ;;
  *) exit 0 ;;
esac
deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}
case "$cmd" in
  *ideoforms/AbletonOSC*) deny "Blocked: PRs must never target ideoforms/AbletonOSC. Use --repo jpatricknola/AbletonOSC." ;;
esac
case "$cmd" in
  *"--repo jpatricknola/AbletonOSC"*|*"--repo=jpatricknola/AbletonOSC"*|*"-R jpatricknola/AbletonOSC"*) exit 0 ;;
  *) deny "Blocked: gh pr create must pass --repo jpatricknola/AbletonOSC (this clone is a fork; the default base is the ideoforms parent)." ;;
esac
