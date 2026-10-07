import os
import shutil
import tempfile
from collections.abc import Generator

import pytest

from src.config import SyncConfig
from src.core.sync import SyncManager
from src.git.client import Git
from src.providers.base import DestinationProvider, OriginProvider


class LocalTestProvider(OriginProvider, DestinationProvider):
    def __init__(self, repo_url: str, name: str, git_client: Git | None = None) -> None:
        self.repo_url = repo_url
        self.name = name
        self.git = git_client

    def get_authenticated_url(self) -> str:
        return self.repo_url

    def is_repo_disabled(self) -> bool:
        return False

    def get_repo_name(self) -> str:
        return self.name

    def commit(
        self,
        subject: str,
        author: str,
        body: str | None = None,
        allow_empty: bool = False,
    ) -> None:
        if not self.git:
            raise RuntimeError("Git client not set")

        msg = f"{subject}\n\n{body}" if body else subject

        if self.git.status_porcelain():
            self.git.commit(msg, author=author)
        elif allow_empty:
            self.git.commit(msg, author=author, allow_empty=True)


def create_bare_repo(path: str) -> Git:
    os.makedirs(path, exist_ok=True)
    git = Git(path)
    git.run("init", "--bare", "-b", "main", check=True)
    return git


def create_seed_repo(bare_url: str, work_dir: str) -> Git:
    os.makedirs(work_dir, exist_ok=True)
    git = Git(work_dir)
    git.run("init", "-b", "main", check=True)
    git.config("user.name", "Tester")
    git.config("user.email", "tester@example.com")
    git.remote_add("origin", bare_url)
    return git


@pytest.fixture
def git_test_env() -> Generator[dict[str, str], None, None]:
    temp_dir = tempfile.mkdtemp(prefix="sync_integration_")
    origin_bare = os.path.join(temp_dir, "origin.git")
    dest_bare = os.path.join(temp_dir, "destination.git")

    create_bare_repo(origin_bare)
    create_bare_repo(dest_bare)

    yield {
        "root": temp_dir,
        "origin_url": f"file://{origin_bare}",
        "dest_url": f"file://{dest_bare}",
        "origin_bare": origin_bare,
        "dest_bare": dest_bare,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_integration_new_branch_and_exclusive_paths(
    git_test_env: dict[str, str],
) -> None:
    """
    Scenario 1 & 4:
    Origin has a new branch with application code and origin-exclusive
    paths (.pipeline). Destination has .github/workflow.yml.
    Verify Destination receives branch, retains .github, and purges .pipeline.
    """
    root = git_test_env["root"]
    dest_url = git_test_env["dest_url"]
    origin_url = git_test_env["origin_url"]

    # 1. Setup Destination with initial main branch containing .github/workflow.yml
    dest_work = os.path.join(root, "dest_work")
    dest_git = create_seed_repo(dest_url, dest_work)
    os.makedirs(os.path.join(dest_work, ".github"), exist_ok=True)
    with open(os.path.join(dest_work, ".github", "workflow.yml"), "w") as f:
        f.write("name: CI\n")
    with open(os.path.join(dest_work, "README.md"), "w") as f:
        f.write("# Destination Readme\n")
    dest_git.add(all_files=True)
    dest_git.commit("initial destination commit")
    dest_git.push("origin", "main")

    # 2. Setup Origin with a feature branch containing app code
    # and origin-exclusive .pipeline
    origin_work = os.path.join(root, "origin_work")
    origin_git = create_seed_repo(origin_url, origin_work)
    with open(os.path.join(origin_work, "app.py"), "w") as f:
        f.write("print('Hello World')\n")
    os.makedirs(os.path.join(origin_work, ".pipeline"), exist_ok=True)
    with open(os.path.join(origin_work, ".pipeline", "azure-pipelines.yml"), "w") as f:
        f.write("pipeline: build\n")
    origin_git.add(all_files=True)
    origin_git.commit(
        "feat: add app and pipeline", author="Developer One <dev1@company.com>"
    )
    origin_git.push("origin", "main")

    # Create feature branch in origin
    origin_git.checkout("feature/login", create=True)
    with open(os.path.join(origin_work, "login.py"), "w") as f:
        f.write("def login(): pass\n")
    origin_git.add(all_files=True)
    origin_git.commit("feat: login module", author="Developer Two <dev2@company.com>")
    origin_git.push("origin", "feature/login")

    # 3. Setup temporary working directory for SyncManager
    sync_work = os.path.join(root, "sync_work")
    os.makedirs(sync_work, exist_ok=True)
    sync_git = Git(sync_work)

    # 4. Run SyncManager
    config = SyncConfig(
        ORIGIN_URL=origin_url,
        ORIGIN_TOKEN="mock-origin-token",
        DESTINATION_URL=dest_url,
        DESTINATION_TOKEN="mock-dest-token",
        ORIGIN_EXCLUSIVE_PATHS=".pipeline",
        DESTINATION_EXCLUSIVE_PATHS=".github",
    )
    origin_prov = LocalTestProvider(origin_url, "origin-repo", sync_git)
    dest_prov = LocalTestProvider(dest_url, "dest-repo", sync_git)

    manager = SyncManager(config, origin_prov, dest_prov, sync_git)
    result = manager.execute()

    assert not result.errors
    assert "main" in result.synced_branches
    assert "feature/login" in result.synced_branches

    # 5. Verify Destination State
    verify_dir = os.path.join(root, "verify_work")
    helper_git = Git(root)
    helper_git.clone(dest_url, verify_dir)
    verify_git = Git(verify_dir)

    # Check main branch
    verify_git.checkout("main")
    assert os.path.exists(os.path.join(verify_dir, ".github", "workflow.yml"))
    assert os.path.exists(os.path.join(verify_dir, "app.py"))
    assert not os.path.exists(os.path.join(verify_dir, ".pipeline"))

    # Check feature/login branch
    verify_git.checkout("feature/login")
    assert os.path.exists(os.path.join(verify_dir, "login.py"))
    assert os.path.exists(os.path.join(verify_dir, ".github", "workflow.yml"))
    assert not os.path.exists(os.path.join(verify_dir, ".pipeline"))


def test_integration_fast_forward_and_conflict_resolution(
    git_test_env: dict[str, str],
) -> None:
    """
    Scenario 2 & 3:
    - Linear Fast-Forward test.
    - 3-Way Merge conflict resolution (favoring Origin / theirs).
    """
    root = git_test_env["root"]
    dest_url = git_test_env["dest_url"]
    origin_url = git_test_env["origin_url"]

    # 1. Initialize both repos with common base
    base_work = os.path.join(root, "base_work")
    base_git = create_seed_repo(origin_url, base_work)
    with open(os.path.join(base_work, "code.py"), "w") as f:
        f.write("version = 1\n")
    base_git.add(all_files=True)
    base_git.commit("initial commit", author="Original <orig@example.com>")
    base_git.push("origin", "main")

    # Push identical base to destination
    base_git.remote_add("dest", dest_url)
    base_git.push("dest", "main")

    # 2. Add linear commit in origin -> Fast Forward
    with open(os.path.join(base_work, "code.py"), "w") as f:
        f.write("version = 2\n")
    base_git.add(all_files=True)
    base_git.commit("update to version 2", author="Developer <dev@example.com>")
    base_git.push("origin", "main")

    config = SyncConfig(
        ORIGIN_URL=origin_url,
        ORIGIN_TOKEN="mock",
        DESTINATION_URL=dest_url,
        DESTINATION_TOKEN="mock",
    )

    sync_work1 = os.path.join(root, "sync_work1")
    os.makedirs(sync_work1, exist_ok=True)
    sync_git1 = Git(sync_work1)

    manager = SyncManager(
        config,
        LocalTestProvider(origin_url, "o", sync_git1),
        LocalTestProvider(dest_url, "d", sync_git1),
        sync_git1,
    )
    res = manager.execute()
    assert "main" in res.synced_branches

    # Verify linear update in destination
    verify_dir = os.path.join(root, "verify_ff")
    helper_git = Git(root)
    helper_git.clone(dest_url, verify_dir)
    verify_git = Git(verify_dir)
    verify_git.checkout("main")
    with open(os.path.join(verify_dir, "code.py")) as f:
        assert f.read().strip() == "version = 2"

    # 3. Create conflict: Destination modifies code.py to 'dest_conflict',
    # Origin modifies to 'origin_conflict'
    with open(os.path.join(verify_dir, "code.py"), "w") as f:
        f.write("dest_conflict\n")
    verify_git.add(all_files=True)
    verify_git.commit("dest side change")
    verify_git.push("origin", "main")

    with open(os.path.join(base_work, "code.py"), "w") as f:
        f.write("origin_conflict\n")
    base_git.add(all_files=True)
    base_git.commit("origin side change", author="Lead <lead@example.com>")
    base_git.push("origin", "main")

    # Run sync again -> 3-way merge should resolve using theirs (Origin's version)
    sync_work2 = os.path.join(root, "sync_work2")
    os.makedirs(sync_work2, exist_ok=True)
    sync_git2 = Git(sync_work2)

    manager2 = SyncManager(
        config,
        LocalTestProvider(origin_url, "o", sync_git2),
        LocalTestProvider(dest_url, "d", sync_git2),
        sync_git2,
    )
    res2 = manager2.execute()
    assert not res2.errors

    # Verify destination now contains origin's change
    verify_git.run("fetch", "origin", check=True)
    verify_git.run("reset", "--hard", "origin/main", check=True)
    with open(os.path.join(verify_dir, "code.py")) as f:
        assert f.read().strip() == "origin_conflict"


def test_integration_branch_pruning_and_mapping(git_test_env: dict[str, str]) -> None:
    """
    Scenario 5 & 6:
    - Branch Name Mapping (Origin 'master' -> Destination 'main').
    - Branch Pruning (Origin deletes 'feature/temp' -> pruned on Destination).
    - Default branch protection (never pruned).
    """
    root = git_test_env["root"]
    dest_url = git_test_env["dest_url"]
    origin_url = git_test_env["origin_url"]

    # 1. Setup Destination with 'main'
    dest_work = os.path.join(root, "dest_work")
    dest_git = create_seed_repo(dest_url, dest_work)
    with open(os.path.join(dest_work, "file.txt"), "w") as f:
        f.write("dest base\n")
    dest_git.add(all_files=True)
    dest_git.commit("init dest")
    dest_git.push("origin", "main")

    # Also add an old branch in destination that does NOT exist in origin
    dest_git.checkout("old-deprecated", create=True)
    with open(os.path.join(dest_work, "temp.txt"), "w") as f:
        f.write("deprecated\n")
    dest_git.add(all_files=True)
    dest_git.commit("deprecated branch")
    dest_git.push("origin", "old-deprecated")

    # 2. Setup Origin with 'master' (to test mapping master -> main)
    origin_work = os.path.join(root, "origin_work")
    origin_git = create_seed_repo(origin_url, origin_work)
    origin_git.checkout("master", create=True)
    with open(os.path.join(origin_work, "master_file.txt"), "w") as f:
        f.write("content from master\n")
    origin_git.add(all_files=True)
    origin_git.commit("master commit", author="Master Dev <m@example.com>")
    origin_git.push("origin", "master")

    config = SyncConfig(
        ORIGIN_URL=origin_url,
        ORIGIN_TOKEN="mock",
        DESTINATION_URL=dest_url,
        DESTINATION_TOKEN="mock",
        BRANCH_MAPPING="master:main",
    )

    sync_work3 = os.path.join(root, "sync_work3")
    os.makedirs(sync_work3, exist_ok=True)
    sync_git3 = Git(sync_work3)

    manager = SyncManager(
        config,
        LocalTestProvider(origin_url, "o", sync_git3),
        LocalTestProvider(dest_url, "d", sync_git3),
        sync_git3,
    )
    res = manager.execute()

    assert not res.errors
    assert "main" in res.synced_branches
    assert "old-deprecated" in res.removed_branches

    # Verify destination branches
    verify_dir = os.path.join(root, "verify_map")
    helper_git = Git(root)
    helper_git.clone(dest_url, verify_dir)
    verify_git = Git(verify_dir)

    # Master file should be on destination's main
    verify_git.checkout("main")
    assert os.path.exists(os.path.join(verify_dir, "master_file.txt"))

    # 'master' branch should NOT exist on destination
    assert not verify_git.ref_exists("origin/master")

    # 'old-deprecated' branch should be deleted
    assert not verify_git.ref_exists("origin/old-deprecated")

    # 'main' must still exist (default branch protection)
    assert verify_git.ref_exists("origin/main")
