# GitHub Repository Sync (gh-repo-sync)

A modular application to synchronize Git repositories from an Origin (Azure DevOps, etc.) to a Destination (GitHub). The engine maintains commit authors, handles exclusive path filtering, and supports branch mapping, ensuring seamless cross-platform syncing without unintended side effects.

## Features

- **Author Preservation:** Retains original author names and emails during synchronization.
- **Exclusive Paths:** Protects specific destination paths (e.g., `.github`) while purging origin-specific artifacts (e.g., `.pipeline`).
- **Branch Mapping:** Translates origin branch names to different destination names (e.g., `master:main`).
- **Destination Action Suppression:** When pushing commits to GitHub, the engine automatically injects the `[skip actions]` marker. This is handled transparently by the `GitHubProvider` to ensure that GitHub Actions workflows are not recursively or redundantly triggered by automated syncs.
- **Smart Merge Resolution:** Automatically resolves non-exclusive file conflicts by favoring the origin repository state (theirs).

## Action Avoidance (`[skip actions]`)

Because synchronizing large histories across platforms can inadvertently trigger massive, redundant CI/CD runs on the destination repository, `gh-repo-sync` explicitly prevents this on GitHub destinations. 

The `GitHubProvider` natively formats all synchronization commits to include `[skip actions]` in the commit message. If an upstream commit already includes standard skip tags (like `[skip ci]`, `[no ci]`, etc.), the provider deduplicates these to avoid redundant markers.

## GitHub Actions Usage

You can use this action directly in your workflow (runs on Linux runners such as `ubuntu-latest` via Docker):

```yaml
name: Sync Repositories
on:
  schedule:
    - cron: '0 * * * *' # Run hourly
  workflow_dispatch:     # Allow manual trigger

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write # Required if destination uses GITHUB_TOKEN
    steps:
      - name: Sync from Azure DevOps
        id: sync-step
        uses: ilegra/gh-repo-sync@v0
        with:
          origin-url: 'https://dev.azure.com/org/project/_git/repo'
          origin-token: ${{ secrets.ADO_PAT }}
          destination-url: 'https://github.com/org/repo.git'
          destination-token: ${{ secrets.GH_TOKEN }}
          branch-mapping: 'master:main'
          committer-name: 'github-actions[bot]'
          committer-email: 'github-actions[bot]@users.noreply.github.com'
```

### Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `origin-url` | **Yes** | — | Repository URL of the Origin (Azure DevOps). |
| `origin-token` | **Yes** | — | Personal Access Token (PAT) for the Origin. |
| `destination-url` | **Yes** | — | Repository URL of the Destination (GitHub). |
| `destination-token` | **Yes** | — | GitHub Token or App installation token with push permissions. |
| `origin-exclusive-paths` | No | `""` | Comma-separated paths on Origin to purge from sync (e.g. `.pipeline`, `azure-pipelines*.yml`). |
| `destination-exclusive-paths` | No | `""` | Comma-separated paths on Destination to keep protected (e.g. `.github`). |
| `branch-mapping` | No | `""` | Comma-separated branch mappings `origin:dest` (e.g. `master:main`). |
| `committer-name` | No | `github-actions[bot]` | Committer name fallback when origin author cannot be resolved. |
| `committer-email` | No | `github-actions[bot]@users.noreply.github.com` | Committer email fallback when origin author cannot be resolved. |
| `bot-name` | No | `""` | Legacy alias for `committer-name`. |
| `bot-email` | No | `""` | Legacy alias for `committer-email`. |

### Action Outputs

The action emits execution reports directly to GitHub Actions output variables for downstream workflow steps to consume.

#### `sync-result`
A single-line JSON string containing the complete synchronization report.

##### Schema Definition

| Field | Type | Description |
|---|---|---|
| `repo_name` | `string` | Base repository name of the destination. |
| `origin_repo` | `string` | Origin repository URL. |
| `destination_repo` | `string` | Destination repository URL. |
| `synced_branches` | `array[string]` | List of branch names that were synchronized or updated. |
| `removed_branches` | `array[string]` | List of pruned branches that no longer exist in origin. |
| `synced_tags` | `array[string]` | List of tag names synchronized to the destination. |
| `already_disabled` | `boolean` | Flag indicating whether origin repo is disabled (sync bypassed). |
| `errors` | `array[string]` | List of non-fatal and fatal errors collected during execution. |

##### Example JSON Payload

```json
{
  "repo_name": "destination-repo",
  "origin_repo": "https://dev.azure.com/org/project/_git/origin-repo",
  "destination_repo": "https://github.com/org/destination-repo.git",
  "synced_branches": [
    "main",
    "feature/user-auth"
  ],
  "removed_branches": [
    "feature/deprecated-flow"
  ],
  "synced_tags": [
    "v1.2.0"
  ],
  "already_disabled": false,
  "errors": []
}
```

##### Consuming `sync-result` in Downstream Steps

###### 1. Conditional Step Execution via `fromJSON()`
Trigger downstream actions only when branches were synchronized:
```yaml
      - name: Trigger Build on Changes
        if: ${{ fromJSON(steps.sync-step.outputs.sync-result).synced_branches[0] != null }}
        run: echo "New branches or updates detected! Triggering downstream build..."
```

###### 2. Parsing Output Fields with `jq` in Bash
Extract specific fields in shell steps for processing:
```yaml
      - name: Parse Synchronized Branches
        run: |
          SYNC_RESULT='${{ steps.sync-step.outputs.sync-result }}'
          SYNCED_BRANCHES=$(echo "$SYNC_RESULT" | jq -r '.synced_branches | join(", ")')
          REMOVED_BRANCHES=$(echo "$SYNC_RESULT" | jq -r '.removed_branches | join(", ")')
          echo "Synced branches: $SYNCED_BRANCHES"
          echo "Removed branches: $REMOVED_BRANCHES"
```

###### 3. Slack / PR Comment Notification Summary
Generate a formatted markdown or notification summary from the returned report:
```yaml
      - name: Notify Slack or PR Summary
        if: always()
        run: |
          SYNC_RESULT='${{ steps.sync-step.outputs.sync-result }}'
          REPO=$(echo "$SYNC_RESULT" | jq -r '.repo_name')
          ERRORS=$(echo "$SYNC_RESULT" | jq -r '.errors | length')
          SYNCED_COUNT=$(echo "$SYNC_RESULT" | jq -r '.synced_branches | length')

          SUMMARY="Sync completed for *${REPO}*: ${SYNCED_COUNT} branches updated, ${ERRORS} errors."
          echo "SUMMARY=$SUMMARY" >> $GITHUB_ENV
```

## CLI / Environment Variable Configuration

For standalone or local container execution, the following environment variables are supported:

| Environment Variable | Description |
|---------------------|-------------|
| `ORIGIN_URL` | The repository URL of the Origin. |
| `ORIGIN_TOKEN` | Access Token / PAT for the Origin. |
| `DESTINATION_URL` | The repository URL of the Destination (GitHub). |
| `DESTINATION_TOKEN` | GitHub Token or App installation token. |
| `ORIGIN_EXCLUSIVE_PATHS` | Comma-separated paths on Origin to purge from sync (default: `.pipeline`, `azure-pipelines*.yml`). |
| `DESTINATION_EXCLUSIVE_PATHS` | Comma-separated paths on Destination that must remain protected (default: `.github`). |
| `BRANCH_MAPPING` | Branch mapping `origin:dest` (e.g., `master:main`). |
| `COMMITTER_NAME` | Git bot author/committer name fallback (default: `github-actions[bot]`). |
| `COMMITTER_EMAIL` | Git bot author/committer email fallback (default: `github-actions[bot]@users.noreply.github.com`). |

## Development and Testing

This project uses Poetry for dependency management and requires Python 3.10+.

```bash
# Install dependencies
poetry install

# Run linters and type checking
poetry run ruff check src tests
poetry run ruff format --check src tests
poetry run mypy src tests

# Run unit tests
poetry run pytest tests/unit -v

# Run integration tests
poetry run pytest tests/integration -v
```

## Versioning and Release Process

### Canonical Version Definition
The canonical version of the application is defined in [`pyproject.toml`](pyproject.toml) under `[tool.poetry] version`.

- **Check Current Version:**
  ```bash
  poetry version --short
  # or via the Python API
  poetry run python -m src.version
  ```
- **Bump Version (SemVer):**
  ```bash
  # Increment patch, minor, or major version
  poetry version patch
  poetry version minor
  poetry version major
  ```

### Automated Release Pipeline
When code is integrated via GitHub Actions:
1. **Pull Requests:** `lint`, `unit-tests`, and `integration-tests` run concurrently in parallel to validate proposed changes.
2. **Main Branch:** Upon merging into `main`, the identical checks run in parallel again to verify the integrated state.
3. **Automated Release & Tagging:** If all verification jobs pass:
   - The pipeline resolves the canonical application version from `pyproject.toml`.
   - If the tag `v<version>` does not yet exist, it analyzes the commit history since the previous tag using Conventional Commits.
   - It generates structured release notes categorized into Features, Bug Fixes, Improvements, and Pull Requests.
   - It creates the Git tag and publishes a new GitHub Release.

