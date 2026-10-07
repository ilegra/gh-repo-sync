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

    @model_validator(mode="before")
    @classmethod
    def _populate_legacy_aliases(cls, data: dict[str, Any]) -> dict[str, Any]:
        # Support fallback environment variables matching the original script
        aliases = {
            "origin_url": ["ORIGIN_URL", "ADO_URL", "ADO_REPO_URL"],
            "origin_token": ["ORIGIN_TOKEN", "ADO_PAT", "ORIGIN_PAT"],
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


class SyncResult(BaseModel):
    """Result data transfer object for repository synchronization runs."""

    repo_name: str
    origin_repo: str
    destination_repo: str
    synced_branches: list[str] = Field(default_factory=list)
    removed_branches: list[str] = Field(default_factory=list)
    synced_tags: list[str] = Field(default_factory=list)
    already_disabled: bool = False
    errors: list[str] = Field(default_factory=list)

    def write_to_file(self, filename: str) -> None:
        """Serializes sync execution results to a JSON file."""
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))
