import json
import os
from typing import Any, Final

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_FALLBACK_BOT_NAME: Final[str] = "github-actions[bot]"
DEFAULT_FALLBACK_BOT_EMAIL: Final[str] = "github-actions[bot]@users.noreply.github.com"


class SyncConfig(BaseSettings):
    """Configuration settings for repository synchronization engine."""

    origin_url: str = Field(..., validation_alias="ORIGIN_URL")
    origin_token: str = Field(..., validation_alias="ORIGIN_TOKEN")
    origin_username: str | None = Field(None, validation_alias="ORIGIN_USERNAME")
    origin_provider: str | None = Field(None, validation_alias="ORIGIN_PROVIDER")
    destination_url: str = Field(..., validation_alias="DESTINATION_URL")
    destination_token: str = Field(..., validation_alias="DESTINATION_TOKEN")

    origin_exclusive_paths_raw: str = Field(
        "", validation_alias="ORIGIN_EXCLUSIVE_PATHS"
    )
    destination_exclusive_paths_raw: str = Field(
        "", validation_alias="DESTINATION_EXCLUSIVE_PATHS"
    )
    branch_mapping_raw: str = Field("", validation_alias="BRANCH_MAPPING")

    bot_name: str = Field(DEFAULT_FALLBACK_BOT_NAME, validation_alias="BOT_NAME")
    bot_email: str = Field(
        DEFAULT_FALLBACK_BOT_EMAIL,
        validation_alias="BOT_EMAIL",
    )
    sync_json_file: str = Field("sync.json", validation_alias="SYNC_JSON_FILE")
    sync_pull_requests: bool = Field(False, validation_alias="SYNC_PULL_REQUESTS")
    pr_user_mapping_raw: str = Field("", validation_alias="PR_USER_MAPPING")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("bot_name", mode="before")
    @classmethod
    def _validate_bot_name(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return DEFAULT_FALLBACK_BOT_NAME
        return str(v).strip()

    @field_validator("bot_email", mode="before")
    @classmethod
    def _validate_bot_email(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return DEFAULT_FALLBACK_BOT_EMAIL
        return str(v).strip()

    @field_validator("pr_user_mapping_raw", mode="before")
    @classmethod
    def _validate_pr_user_mapping_raw(cls, v: Any) -> str:
        if v is None:
            return ""
        raw = str(v).strip()
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in PR_USER_MAPPING: {exc}") from exc
            if not isinstance(parsed, dict) or not all(
                isinstance(k, str) and isinstance(val, str) for k, val in parsed.items()
            ):
                raise ValueError(
                    "PR_USER_MAPPING JSON must be an object mapping strings to strings"
                )
        return str(v)

    @model_validator(mode="before")
    @classmethod
    def _populate_legacy_aliases(cls, data: dict[str, Any]) -> dict[str, Any]:
        # Support fallback environment variables matching the original script
        aliases = {
            "origin_url": ["ORIGIN_URL", "ADO_URL", "ADO_REPO_URL"],
            "origin_token": [
                "ORIGIN_TOKEN",
                "ADO_PAT",
                "ORIGIN_PAT",
                "BITBUCKET_TOKEN",
            ],
            "origin_username": ["ORIGIN_USERNAME", "BITBUCKET_USERNAME"],
            "origin_provider": ["ORIGIN_PROVIDER", "ORIGIN_TYPE"],
            "destination_url": ["DESTINATION_URL", "GH_URL", "GH_REPO_URL"],
            "destination_token": ["DESTINATION_TOKEN", "GH_TOKEN"],
            "origin_exclusive_paths_raw": [
                "ORIGIN_EXCLUSIVE_PATHS",
                "ADO_EXCLUSIVE_PATHS",
                "ADO_EXCLUSIVE_PATHS_RAW",
            ],
            "destination_exclusive_paths_raw": [
                "DESTINATION_EXCLUSIVE_PATHS",
                "GH_EXCLUSIVE_PATHS",
                "GH_EXCLUSIVE_PATHS_RAW",
            ],
            "branch_mapping_raw": ["BRANCH_MAPPING", "BRANCH_MAPPINGS"],
            "bot_name": [
                "COMMITTER_NAME",
                "BOT_NAME",
                "GIT_COMMITTER_NAME",
                "DEFAULT_BOT_NAME",
            ],
            "bot_email": [
                "COMMITTER_EMAIL",
                "BOT_EMAIL",
                "GIT_COMMITTER_EMAIL",
                "DEFAULT_BOT_EMAIL",
            ],
            "sync_json_file": ["SYNC_JSON_FILE"],
            "sync_pull_requests": ["SYNC_PULL_REQUESTS"],
            "pr_user_mapping_raw": ["PR_USER_MAPPING"],
        }
        res = dict(data) if isinstance(data, dict) else {}
        for field, alt_keys in aliases.items():
            current_val = res.get(field)
            if current_val is None or (
                isinstance(current_val, str) and not current_val.strip()
            ):
                for key in alt_keys:
                    val = res.get(key)
                    if val is None:
                        val = os.getenv(key)
                    if val is not None and isinstance(val, str) and val.strip():
                        res[field] = val.strip()
                        break
                    elif val is not None and not isinstance(val, str):
                        res[field] = val
                        break
        return res

    @property
    def committer_name(self) -> str:
        """Git committer name fallback."""
        return self.bot_name

    @property
    def committer_email(self) -> str:
        """Git committer email fallback."""
        return self.bot_email

    @property
    def origin_exclusive_paths(self) -> list[str]:
        """List of origin paths that should be purged or excluded on the destination."""
        defaults = [
            ".pipeline",
            ".pipelines",
            "azure-pipelines*.yml",
            "azure-pipelines*.yaml",
            "bitbucket-pipelines.yml",
        ]
        custom = []
        if self.origin_exclusive_paths_raw:
            for item in self.origin_exclusive_paths_raw.split(","):
                cleaned = item.strip().lstrip("/")
                if cleaned:
                    custom.append(cleaned)
        # Deduplicate while preserving order
        combined = []
        for p in defaults + custom:
            if p not in combined:
                combined.append(p)
        return combined

    @property
    def destination_exclusive_paths(self) -> list[str]:
        """List of destination paths preserved from the destination seed."""
        defaults = [".github"]
        custom = []
        if self.destination_exclusive_paths_raw:
            for item in self.destination_exclusive_paths_raw.split(","):
                cleaned = item.strip().lstrip("/")
                if cleaned:
                    custom.append(cleaned)
        combined = []
        for p in defaults + custom:
            if p not in combined:
                combined.append(p)
        return combined

    @property
    def branch_mapping(self) -> dict[str, str]:
        """
        Parses BRANCH_MAPPING string (format: 'origin_branch:dest_branch,master:main')
        into a dict: {'master': 'main'}
        """
        mapping: dict[str, str] = {}
        if not self.branch_mapping_raw:
            return mapping
        for pair in self.branch_mapping_raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" in pair:
                src, dst = pair.split(":", 1)
                src = src.strip()
                dst = dst.strip()
                if src and dst:
                    mapping[src] = dst
        return mapping

    @property
    def reverse_branch_mapping(self) -> dict[str, str]:
        """
        Reverses branch_mapping: {destination_branch: origin_branch}
        """
        return {v: k for k, v in self.branch_mapping.items()}

    @property
    def pr_user_mapping(self) -> dict[str, str]:
        """
        Parses PR_USER_MAPPING into a dict mapping origin display names to GitHub
        logins (without leading '@').

        Supports both JSON object syntax (e.g. '{"Doe, Jane": "jdoe"}') and
        comma-separated 'Display Name:github-login' pairs.
        """
        raw = self.pr_user_mapping_raw.strip()
        if not raw:
            return {}

        mapping: dict[str, str] = {}
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for origin_name, gh_login in parsed.items():
                    key = str(origin_name).strip()
                    val = str(gh_login).strip().lstrip("@")
                    if key and val:
                        mapping[key] = val
            return mapping

        for pair in raw.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            origin_name, gh_login = pair.split(":", 1)
            key = origin_name.strip()
            val = gh_login.strip().lstrip("@")
            if key and val:
                mapping[key] = val
        return mapping


class SyncResult(BaseModel):
    """Result data transfer object for repository synchronization runs."""

    repo_name: str
    origin_repo: str
    destination_repo: str
    evaluated_branches: list[str] = Field(default_factory=list)
    updated_branches: list[str] = Field(default_factory=list)
    removed_branches: list[str] = Field(default_factory=list)
    synced_tags: list[str] = Field(default_factory=list)
    created_prs: list[int] = Field(default_factory=list)
    updated_prs: list[int] = Field(default_factory=list)
    closed_prs: list[int] = Field(default_factory=list)
    synced_pr_comments: int = 0
    already_disabled: bool = False
    errors: list[str] = Field(default_factory=list)

    def write_to_file(self, filename: str) -> None:
        """Serializes sync execution results to a JSON file."""
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))
