import os
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SyncConfig(BaseSettings):
    origin_url: str = Field(..., validation_alias="ORIGIN_URL")
    origin_token: str = Field(..., validation_alias="ORIGIN_TOKEN")
    destination_url: str = Field(..., validation_alias="DESTINATION_URL")
    destination_token: str = Field(..., validation_alias="DESTINATION_TOKEN")

    origin_exclusive_paths_raw: str = Field("", validation_alias="ORIGIN_EXCLUSIVE_PATHS")
    destination_exclusive_paths_raw: str = Field("", validation_alias="DESTINATION_EXCLUSIVE_PATHS")
    branch_mapping_raw: str = Field("", validation_alias="BRANCH_MAPPING")

    bot_name: str = Field("gh-organization-cerc-com[bot]", validation_alias="BOT_NAME")
    bot_email: str = Field("gh-organization-cerc-com[bot]@users.noreply.github.com", validation_alias="BOT_EMAIL")
    sync_json_file: str = Field("sync.json", validation_alias="SYNC_JSON_FILE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_aliases(cls, data: dict):
        # Support fallback environment variables matching the original script
        aliases = {
            "origin_url": ["ORIGIN_URL", "ADO_URL", "ADO_REPO_URL"],
            "origin_token": ["ORIGIN_TOKEN", "ADO_PAT", "ORIGIN_PAT"],
            "destination_url": ["DESTINATION_URL", "GH_URL", "GH_REPO_URL"],
            "destination_token": ["DESTINATION_TOKEN", "GH_TOKEN"],
            "origin_exclusive_paths_raw": ["ORIGIN_EXCLUSIVE_PATHS", "ADO_EXCLUSIVE_PATHS", "ADO_EXCLUSIVE_PATHS_RAW"],
            "destination_exclusive_paths_raw": ["DESTINATION_EXCLUSIVE_PATHS", "GH_EXCLUSIVE_PATHS", "GH_EXCLUSIVE_PATHS_RAW"],
            "branch_mapping_raw": ["BRANCH_MAPPING", "BRANCH_MAPPINGS"],
            "bot_name": ["BOT_NAME", "DEFAULT_BOT_NAME"],
            "bot_email": ["BOT_EMAIL", "DEFAULT_BOT_EMAIL"],
            "sync_json_file": ["SYNC_JSON_FILE"],
        }
        res = dict(data) if isinstance(data, dict) else {}
        for field, alt_keys in aliases.items():
            if field not in res or not res[field]:
                for key in alt_keys:
                    val = res.get(key) or os.getenv(key)
                    if val is not None:
                        res[field] = val
                        break
        return res

    @property
    def origin_exclusive_paths(self) -> List[str]:
        defaults = [".pipeline", ".pipelines", "azure-pipelines*.yml", "azure-pipelines*.yaml"]
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
    def destination_exclusive_paths(self) -> List[str]:
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
    def branch_mapping(self) -> Dict[str, str]:
        """
        Parses BRANCH_MAPPING string (format: 'origin_branch:dest_branch,master:main')
        into a dict: {'master': 'main'}
        """
        mapping: Dict[str, str] = {}
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
    def reverse_branch_mapping(self) -> Dict[str, str]:
        """
        Reverses branch_mapping: {destination_branch: origin_branch}
        """
        return {v: k for k, v in self.branch_mapping.items()}


class SyncResult(BaseModel):
    repo_name: str
    origin_repo: str
    destination_repo: str
    synced_branches: List[str] = Field(default_factory=list)
    removed_branches: List[str] = Field(default_factory=list)
    already_disabled: bool = False
    errors: List[str] = Field(default_factory=list)

    def write_to_file(self, filename: str):
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))
