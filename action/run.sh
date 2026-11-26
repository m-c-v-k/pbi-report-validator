#!/usr/bin/env bash
# Run `pbi-validate diff` (old and new given) or `pbi-validate changed` (every
# report changed since a git ref) in the action's image, then publish the
# summary and outputs. Inputs come in as IN_* environment variables (never
# interpolated into the script), credentials and AI settings as PBI_* and
# ANTHROPIC_API_KEY variables from the calling step.
set -euo pipefail

EXIT_USAGE=2  # same meaning as the CLI's exit code 2

fail_usage() {
  echo "::error::$1"
  exit "$EXIT_USAGE"
}

# Inside a job container (`container:`) the runner paths are not the Docker
# host's paths, so the volumes below would mount empty folders.
if [[ "$GITHUB_WORKSPACE" == /__w/* ]]; then
  fail_usage "The action cannot run inside a job container; run the job directly on a Linux runner."
fi

# Only the workspace and the runner's temp folder are mounted; a path
# elsewhere would be read or written inside the container and lost. A ".."
# segment could lead a relative path out of the workspace, and the outputs
# are removed on the runner below.
check_path() {
  local path="$2"
  if [[ "$path" =~ (^|/)\.\.(/|$) ]]; then
    fail_usage "Input $1 must not contain a '..' path segment: $path"
  fi
  [[ -z "$path" || "$path" != /* ]] && return 0
  case "$path" in
    "$GITHUB_WORKSPACE"/* | "$RUNNER_TEMP"/*) return 0 ;;
  esac
  fail_usage "Input $1 must be inside the workspace or \$RUNNER_TEMP: $path"
}
check_path old "$IN_OLD"
check_path new "$IN_NEW"
check_path path "$IN_PATH"
check_path html "$IN_HTML"
check_path json "$IN_JSON"
check_path markdown "$IN_MARKDOWN"

# Set variable $1 to true or false from boolean input $2 (any case; empty
# is false).
boolean() {
  case "${3,,}" in
    true) printf -v "$1" true ;;
    false | "") printf -v "$1" false ;;
    *) fail_usage "Input $2 must be true or false, not '$3'" ;;
  esac
}
boolean data data "$IN_DATA"
boolean fail_on_data_error fail-on-data-error "$IN_FAIL_ON_DATA_ERROR"
boolean comment comment "$IN_COMMENT"
boolean show_data_values show-data-values "$IN_SHOW_DATA_VALUES"
if [[ "$show_data_values" == true && "$data" != true ]]; then
  fail_usage "Input show-data-values needs data: true"
fi
case "${IN_AI,,}" in
  off | "") ai=off ;;
  api) ai=api ;;
  *) fail_usage "Input ai must be off or api, not '$IN_AI'" ;;
esac
boolean allow_data_to_llm allow-data-to-llm "$IN_ALLOW_DATA_TO_LLM"
if [[ "$allow_data_to_llm" == true && "$ai" != api ]]; then
  fail_usage "Input allow-data-to-llm needs ai: api"
fi
boolean ai_match ai-match "$IN_AI_MATCH"
boolean ai_explain ai-explain "$IN_AI_EXPLAIN"
case "${IN_AI_EXPLAIN_FROM,,}" in
  "") ai_explain_from="" ;;
  info | warning | critical) ai_explain_from="${IN_AI_EXPLAIN_FROM,,}" ;;
  *) fail_usage "Input ai-explain-from must be info, warning or critical, not '$IN_AI_EXPLAIN_FROM'" ;;
esac
if [[ ("$ai_match" == true || "$ai_explain" == true || -n "$ai_explain_from") && "$ai" != api ]]; then
  fail_usage "Inputs ai-match, ai-explain and ai-explain-from need ai: api"
fi
if [[ -n "$ai_explain_from" && "$ai_explain" != true ]]; then
  fail_usage "Input ai-explain-from needs ai-explain: true"
fi

# old and new compare exactly two versions (diff). Without them, every report
# changed since base is compared (changed); on a pull request, base defaults
# to the pull request's base commit.
if [[ -n "$IN_OLD" || -n "$IN_NEW" ]]; then
  [[ -n "$IN_OLD" && -n "$IN_NEW" ]] \
    || fail_usage "Inputs old and new go together: set both, or neither to compare changes since base"
  [[ -z "$IN_BASE" ]] || fail_usage "Input base cannot be combined with old and new"
  mode=diff
else
  mode=changed
  base="${IN_BASE:-${PR_BASE_SHA:-}}"
  [[ -n "$base" ]] \
    || fail_usage "Set old and new, or base (it defaults to the pull request base only on pull_request events)"
  [[ "$base" != -* ]] || fail_usage "Input base must be a git ref, not '$base'"
  if [[ "$data" == true || "$fail_on_data_error" == true || "$ai" != off ]]; then
    fail_usage "Inputs data, fail-on-data-error and ai need old and new; runs over changed reports do not support them yet"
  fi
fi

# The CLI never fetches. A shallow checkout (the actions/checkout default)
# lacks the base commit, so the action fetches that one commit, or the
# branch behind an origin/<branch> ref; anything else is left to the CLI,
# which explains how to make the ref available.
ensure_base() {
  local ref="$1" spec="$1"
  git -C "$GITHUB_WORKSPACE" rev-parse --verify --quiet "$ref^{commit}" >/dev/null && return 0
  if [[ "$ref" == origin/* ]]; then spec="+refs/heads/${ref#origin/}:refs/remotes/$ref"; fi
  echo "Fetching $ref, which the checkout does not contain"
  git -C "$GITHUB_WORKSPACE" fetch --quiet --no-tags --depth=1 origin "$spec" \
    || echo "::warning::Could not fetch $ref."
}

# A folder per step, so a second run in the same job never reads the first
# run's results.
work_dir="$(mktemp -d "$RUNNER_TEMP/pbi-validate.XXXXXX")"
json="${IN_JSON:-$work_dir/result.json}"
markdown="${IN_MARKDOWN:-$work_dir/summary.md}"
rm -f "$json" "$markdown" ${IN_HTML:+"$IN_HTML"}

# Add "--option value" when the value is not empty.
add() {
  if [[ -n "$2" ]]; then args+=("$1" "$2"); fi
}

if [[ "$mode" == diff ]]; then
  args=(diff "$IN_OLD" "$IN_NEW")
else
  ensure_base "$base"
  args=(changed --base "$base" "${IN_PATH:-.}")
fi
args+=(--json "$json" --markdown "$markdown")
add --html "$IN_HTML"
if [[ "$IN_FAIL_ON" != "none" ]]; then add --fail-on "$IN_FAIL_ON"; fi
if [[ "$fail_on_data_error" == true ]]; then args+=(--fail-on-data-error); fi
if [[ "$data" == true ]]; then
  args+=(--data)
  add --old-dataset "$IN_OLD_DATASET"
  add --new-dataset "$IN_NEW_DATASET"
  add --abs-tol "$IN_ABS_TOL"
  add --rel-tol "$IN_REL_TOL"
  if [[ "$show_data_values" == true ]]; then
    args+=(--show-data-values)
    echo "::warning::show-data-values is on: the job summary, outputs and any pull request comment contain unmasked row-level data."
  fi
fi
# Always explicit with diff, so the input wins over a PBI_VALIDATE_AI
# default; the disabled kill switch still blocks api in the CLI.
if [[ "$mode" == diff ]]; then args+=(--ai "$ai"); fi
if [[ "$allow_data_to_llm" == true ]]; then
  args+=(--allow-data-to-llm)
  echo "::warning::allow-data-to-llm is on: row-level values may be sent to the Anthropic API."
fi
if [[ "$ai_match" == true ]]; then args+=(--ai-match); fi
if [[ "$ai_explain" == true ]]; then args+=(--ai-explain); fi
add --ai-explain-from "$ai_explain_from"

# Same paths inside the container as on the runner, and the runner's user,
# so relative paths work and written files are owned by the workflow.
set +e
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$GITHUB_WORKSPACE:$GITHUB_WORKSPACE" \
  --volume "$RUNNER_TEMP:$RUNNER_TEMP" \
  --workdir "$GITHUB_WORKSPACE" \
  --env PBI_TENANT_ID --env PBI_CLIENT_ID --env PBI_CLIENT_SECRET \
  --env ANTHROPIC_API_KEY --env PBI_VALIDATE_AI --env PBI_VALIDATE_AI_MODEL \
  "$IMAGE" "${args[@]}"
status=$?
set -e

if [[ -f "$markdown" ]]; then
  cat "$markdown" >> "$GITHUB_STEP_SUMMARY"
fi
{
  echo "json=$json"
  echo "markdown=$markdown"
  echo "html=$IN_HTML"
  if [[ -f "$json" ]]; then
    # A changed run has one result per project under .projects.
    jq -r '"findings=\(if has("projects")
        then [.projects[].result.findings // [] | length] | add // 0
        else .findings | length end)",
      (["critical", "warning", "info"][] as $s
        | "\($s)=\(.severity_counts[$s] // 0)")' "$json"
  fi
} >> "$GITHUB_OUTPUT"

if [[ "$comment" == true && -f "$markdown" ]]; then
  # One comment per comparison: the old/new pair, or the changed folder.
  if [[ "$mode" == diff ]]; then key=("$IN_OLD" "$IN_NEW"); else key=(changed "${IN_PATH:-.}"); fi
  bash "$GITHUB_ACTION_PATH/action/comment.sh" "$markdown" "${key[@]}" \
    || echo "::warning::Pull request comment failed; the diff result is unaffected."
fi

exit "$status"
