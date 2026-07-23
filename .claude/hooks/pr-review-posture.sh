#!/bin/bash
# SessionStart hook (remote / Claude Code on the web only): inject the PR-review
# posture rule as session context.
#
# Why a hook and not CLAUDE.md: only remote/web sessions ever subscribe to a
# PR's activity stream, so only they can receive an @claude review-request
# mention and mistake it for a task. Gating on CLAUDE_CODE_REMOTE keeps this
# context out of every local session (which never subscribes and doesn't need
# it), whereas CLAUDE.md would load it everywhere.
#
# Emits SessionStart `additionalContext` (a single-line JSON string) on stdout.
set -euo pipefail

# Local sessions don't subscribe to PRs -- skip entirely, add no context.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"PR review posture (this repo): On a pull request this session is subscribed to via subscribe_pr_activity, a comment whose substance is an @claude / @claude-bot mention requesting a review (e.g. '@claude full review', '@claude go/no-go') is a trigger for the SEPARATE Claude reviewer GitHub Action, NOT a task for this session. Do NOT start your own review, post a review, or render a go/no-go verdict in response to such a mention. Wait for the reviewer workflow to post its review, then act on that review's findings (plus CI results and direct human comments) the normal way. This exemption is only for review-request mentions -- ordinary human comments, review findings, CI failures, and merge-conflict notices are still handled as usual."}}
JSON
exit 0
