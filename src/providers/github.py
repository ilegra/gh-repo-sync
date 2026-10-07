from src.providers.base import DestinationProvider


class GitHubProvider(DestinationProvider):
    def __init__(self, repo_url: str, token: str):
        self.repo_url = repo_url
        self.token = token

    def get_authenticated_url(self) -> str:
        clean_url = self.repo_url
        if clean_url.startswith("https://"):
            clean_url = clean_url[len("https://") :]
        elif clean_url.startswith("http://"):
            clean_url = clean_url[len("http://") :]
        return f"https://x-access-token:{self.token}@{clean_url}"

    def get_repo_name(self) -> str:
        clean = self.repo_url.rstrip("/").removesuffix(".git")
        return clean.split("/")[-1]
