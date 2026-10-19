#!/usr/bin/env bash
# Post the Markdown summary as a pull request comment, or update the comment
# an earlier run of the same comparison posted. A comment that cannot be
# posted (no pull request, no permission on a fork) is a warning, never a
# failure of the step.
# Usage: comment.sh <markdown file> <old> <new>; the token comes in as GH_TOKEN.
set -euo pipefail

GITHUB_COMMENT_LIMIT=65536

markdown_file="$1"
# One comment per comparison; a hash keeps quotes and "-->" in paths out.
comparison="$(printf '%s\n%s' "$2" "$3" | sha256sum | cut -c1-12)"
marker="<!-- pbi-report-validator:$comparison -->"

warn() {
  echo "::warning::Pull request comment skipped: $1"
  exit 0
}

pr_number="$(jq -r '.pull_request.number // empty' "$GITHUB_EVENT_PATH")"
[[ -n "$pr_number" ]] || warn "the workflow was not triggered by a pull request."

run_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
footer=$'\n'"<sub>Full report: the job summary and artifacts of [this run]($run_url).</sub>"$'\n'
summary="$(cat "$markdown_file")"
# The CLI keeps the summary below the limit; this cut is only a safeguard.
room=$((GITHUB_COMMENT_LIMIT - ${#marker} - ${#footer} - 2))
summary="${summary:0:room}"
body="$marker"$'\n'"$summary"$'\n'"$footer"

# Only update a comment this token wrote, since anyone can post the marker.
# The default GITHUB_TOKEN cannot read /user; its comments are by the bot.
author="$(gh api user --jq .login 2>/dev/null)" || author="github-actions[bot]"

comments="repos/$GITHUB_REPOSITORY/issues/$pr_number/comments"
listing="$(gh api --paginate "$comments" --jq '.[] | {id, body, login: .user.login}')" \
  || warn "could not read the comments of #$pr_number."
existing="$(jq -rn --arg marker "$marker" --arg author "$author" \
  'first(inputs | select(.login == $author and (.body | startswith($marker))) | .id)
    // empty' <<<"$listing")"

payload="$(jq -n --arg body "$body" '{body: $body}')"
if [[ -n "$existing" ]]; then
  gh api --method PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$existing" \
    --input - <<<"$payload" >/dev/null \
    || warn "no permission to update comment $existing (a fork, or missing pull-requests: write)."
  echo "Updated the comment on #$pr_number"
else
  gh api --method POST "$comments" --input - <<<"$payload" >/dev/null \
    || warn "no permission to comment on #$pr_number (a fork, or missing pull-requests: write)."
  echo "Commented on #$pr_number"
fi
