import base64
import re
import urllib.parse

import requests
import structlog
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.providers.base import OriginProvider

logger = structlog.get_logger(__name__)


class AzureDevOpsProvider(OriginProvider):
    def __init__(self, repo_url: str, pat: str):
        self.repo_url = repo_url
        self.pat = pat
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._session = session
        return self._session

    def get_authenticated_url(self) -> str:
        clean_url = self.repo_url
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        return f"https://anything:{self.pat}@{clean_url}"

    def get_repo_name(self) -> str:
        clean = self.repo_url.rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]

    def _parse_ado_url(self) -> tuple[str, str, str] | None:
        """
        Parses Azure DevOps URL into (org, project, repo).
        Supports:
        - https://dev.azure.com/{org}/{project}/_git/{repo}
        - https://{org}.visualstudio.com/{project}/_git/{repo}
        """
        dev_azure_regex = r"^https://dev\.azure\.com/([^/]+)/([^/]+)/_git/(.+)$"
        vs_regex = r"^https://([^/]+)\.visualstudio\.com/([^/]+)/_git/(.+)$"

        m = re.match(dev_azure_regex, self.repo_url)
        if m:
            return m.group(1), m.group(2), m.group(3)

        m = re.match(vs_regex, self.repo_url)
        if m:
            return m.group(1), m.group(2), m.group(3)

        return None

    def is_repo_disabled(self) -> bool:
        parsed = self._parse_ado_url()
        if not parsed:
            logger.debug(
                "Could not parse ADO org/project/repo from URL for API check",
                url=self.repo_url,
            )
            return False

        org, project, repo = parsed
        project_url = urllib.parse.quote(project)
        repo_url = urllib.parse.quote(repo)
        api_url = f"https://dev.azure.com/{org}/{project_url}/_apis/git/repositories/{repo_url}?api-version=7.1"

        b64_pat = base64.b64encode(f":{self.pat}".encode()).decode("utf-8")
        headers = {
            "Authorization": f"Basic {b64_pat}",
            "Content-Type": "application/json",
        }

        try:
            session = self._get_session()
            response = session.get(api_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                is_disabled = bool(data.get("isDisabled", False))
                logger.info(
                    "Checked ADO repository status via API",
                    repo=repo,
                    is_disabled=is_disabled,
                )
                return is_disabled
            else:
                logger.warning(
                    "Azure DevOps API returned non-200 status code",
                    status_code=response.status_code,
                    body=response.text[:200],
                )
        except Exception as e:
            logger.warning(
                "Failed to check if Azure DevOps repo is disabled via API", error=str(e)
            )

        return False
