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

## Configuration

| Environment Variable | Description |
|---------------------|-------------|
| `ORIGIN_URL` | The repository URL of the Origin. |
| `ORIGIN_TOKEN` | Access Token / PAT for the Origin. |
| `DESTINATION_URL` | The repository URL of the Destination (GitHub). |
| `DESTINATION_TOKEN` | GitHub Token or App installation token. |
| `ORIGIN_EXCLUSIVE_PATHS` | Comma-separated paths on Origin to purge from sync (default: `.pipeline`, `azure-pipelines*.yml`, etc.). |
| `DESTINATION_EXCLUSIVE_PATHS` | Comma-separated paths on Destination that must remain protected (default: `.github`). |
| `BRANCH_MAPPING` | Branch mapping `origin:dest` (e.g., `master:main`). |
| `BOT_NAME` | Git bot author/committer name fallback. |
| `BOT_EMAIL` | Git bot author/committer email fallback. |

## GitHub Actions Usage

You can use this synchronization engine directly in a GitHub Actions workflow:

```yaml
name: Sync Repositories
on:
  schedule:
    - cron: '0 * * * *' # Run hourly

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Sync from Azure DevOps
        uses: ilegra/gh-repo-sync@v1
        with:
          origin-url: 'https://dev.azure.com/org/project/_git/repo'
          origin-token: ${{ secrets.ADO_PAT }}
          destination-url: 'https://github.com/org/repo.git'
          destination-token: ${{ secrets.GH_TOKEN }}
          branch-mapping: 'master:main'
```

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

