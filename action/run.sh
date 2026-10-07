#!/usr/bin/env bash
# Run `pbi-validate diff` in the action's image, then publish the summary and
# outputs. Inputs come in as IN_* environment variables (never interpolated
# into the script), credentials as PBI_* variables from the calling step.
set -euo pipefail

work_dir="$RUNNER_TEMP/pbi-validate"
mkdir -p "$work_dir"
json="${IN_JSON:-$work_dir/result.json}"
markdown="${IN_MARKDOWN:-$work_dir/summary.md}"

# Add "--option value" when the value is not empty.
add() {
  if [[ -n "$2" ]]; then args+=("$1" "$2"); fi
}

args=(diff "$IN_OLD" "$IN_NEW" --json "$json" --markdown "$markdown")
add --html "$IN_HTML"
if [[ "$IN_FAIL_ON" != "none" ]]; then add --fail-on "$IN_FAIL_ON"; fi
if [[ "$IN_DATA" == "true" ]]; then
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
