#!/usr/bin/env bash
# Run `pbi-validate diff` in the action's image, then publish the summary and
# outputs. Inputs come in as IN_* environment variables (never interpolated
# into the script), credentials as PBI_* variables from the calling step.
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
# elsewhere would be read or written inside the container and lost.
check_path() {
  local path="$2"
  [[ -z "$path" || "$path" != /* ]] && return 0
  case "$path" in
    "$GITHUB_WORKSPACE"/* | "$RUNNER_TEMP"/*) return 0 ;;
  esac
  fail_usage "Input $1 must be inside the workspace or \$RUNNER_TEMP: $path"
}
check_path old "$IN_OLD"
check_path new "$IN_NEW"
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

args=(diff "$IN_OLD" "$IN_NEW" --json "$json" --markdown "$markdown")
add --html "$IN_HTML"
if [[ "$IN_FAIL_ON" != "none" ]]; then add --fail-on "$IN_FAIL_ON"; fi
if [[ "$fail_on_data_error" == true ]]; then args+=(--fail-on-data-error); fi
if [[ "$data" == true ]]; then
  args+=(--data)
  add --old-dataset "$IN_OLD_DATASET"
  add --new-dataset "$IN_NEW_DATASET"
  add --abs-tol "$IN_ABS_TOL"
  add --rel-tol "$IN_REL_TOL"
fi

# Same paths inside the container as on the runner, and the runner's user,
# so relative paths work and written files are owned by the workflow.
set +e
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$GITHUB_WORKSPACE:$GITHUB_WORKSPACE" \
  --volume "$RUNNER_TEMP:$RUNNER_TEMP" \
  --workdir "$GITHUB_WORKSPACE" \
  --env PBI_TENANT_ID --env PBI_CLIENT_ID --env PBI_CLIENT_SECRET \
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
    jq -r '"findings=\(.findings | length)",
      (["critical", "warning", "info"][] as $s
        | "\($s)=\(.severity_counts[$s] // 0)")' "$json"
  fi
} >> "$GITHUB_OUTPUT"

exit "$status"
