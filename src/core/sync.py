import fnmatch
import os
import re
import shutil

import structlog

from src.config import SyncConfig, SyncResult
from src.git.client import Git, GitError
from src.providers.base import (
    Branch,
    DestinationProvider,
    OriginProvider,
)
from src.providers.base import (
    validate_branch_name as validate_branch_name,
)

logger = structlog.get_logger(__name__)


def is_exclusive_path(target_path: str, exclusive_paths: list[str]) -> bool:
    """Checks if target_path matches any exclusive path or pattern."""
    target_clean = target_path.strip()
    if target_clean.startswith("./"):
        target_clean = target_clean[2:]
    target_clean = target_clean.lstrip("/")

    for exp in exclusive_paths:
        clean_exp = exp.strip().strip("/")
        if not clean_exp:
            continue
        if "*" in clean_exp:
            regex_exp = clean_exp.replace(".", r"\.").replace("*", ".*")
            pattern = rf"(^|/){regex_exp}(/|$)"
            if re.search(pattern, target_clean):
                return True
        else:
            pattern = rf"(^|/){re.escape(clean_exp)}(/|$)"
            if re.search(pattern, target_clean):
                return True
    return False


def parse_author(
    log_output: str, default_name: str, default_email: str
) -> tuple[str, str]:
    """Parses author name and email from git log tab-separated format."""
    if not log_output or "\t" not in log_output:
        return default_name, default_email

    parts = log_output.split("\t", 1)
    name = parts[0].strip()
    email = parts[1].strip() if len(parts) > 1 else ""

    if not name or not email or "@" not in email:
        return default_name, default_email
    return name, email


class SyncManager:
    """Manages repository sync between origin and destination."""

    def __init__(
        self,
        config: SyncConfig,
        origin_provider: OriginProvider,
        destination_provider: DestinationProvider,
        git_client: Git,
    ):
        self.config = config
        self.origin_provider = origin_provider
        self.destination_provider = destination_provider

        self.git: Git = git_client
        self.default_branch: str = "main"
        self.origin_branches: list[Branch] = []
        self.destination_branches: list[Branch] = []

        self.synced_branches: list[str] = []
        self.removed_branches: list[str] = []
        self.sync_errors: list[str] = []

        self.origin_remote = getattr(origin_provider, "remote_name", "origin_remote")
        self.destination_remote = getattr(
            destination_provider, "remote_name", "destination_remote"
        )

    @property
    def git_client(self) -> Git:
        """Returns the underlying Git client instance."""
        return self.git

    def _resolve_origin_author(self, ref: str) -> tuple[str, str]:
        if not self.git or not self.git.ref_exists(ref):
            return self.config.bot_name, self.config.bot_email
        output = self.git.log_one(ref, "%an%x09%ae")
        return parse_author(output, self.config.bot_name, self.config.bot_email)

    def _protect_destination_exclusive_assets(self, base_ref: str = "HEAD") -> None:
        if not self.git:
            return
        repo_root = self.git.cwd
        for path in self.config.destination_exclusive_paths:
            clean_path = path.strip().strip("/")
            if not clean_path:
                continue

            ref_check = f"{base_ref}:{clean_path}"
            full_path = os.path.join(repo_root, clean_path)

            if self.git.ref_exists(ref_check):
                logger.info(
                    "Restoring destination exclusive asset",
                    path=clean_path,
                    base_ref=base_ref,
                )
                if os.path.exists(full_path):
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path, ignore_errors=True)
                    else:
                        os.remove(full_path)
                self.git.checkout("", base_ref=base_ref, paths=[clean_path])
                self.git.add([clean_path])
            else:
                if os.path.exists(full_path):
                    logger.info(
                        "Removing destination asset not in base ref", path=clean_path
                    )
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path, ignore_errors=True)
                    else:
                        os.remove(full_path)
                    self.git.rm([clean_path], cached=True, rf=True)

    def _purge_origin_exclusive_assets(self) -> None:
        if not self.git:
            return
        repo_root = self.git.cwd
        for item in self.config.origin_exclusive_paths:
            clean_item = item.strip().strip("/")
            if not clean_item:
                continue

            if "*" in clean_item:
                # Glob pattern matching across the repository workspace
                for root, dirs, files in os.walk(repo_root):
                    # Check files
                    for filename in files:
                        if fnmatch.fnmatch(filename, clean_item):
                            rel_path = os.path.relpath(
                                os.path.join(root, filename), repo_root
                            )
                            logger.info(
                                "Purging origin exclusive asset (glob file)",
                                path=rel_path,
                            )
                            self.git.rm([rel_path], cached=True, rf=True)
                            os.remove(os.path.join(root, filename))
                    # Check directories
                    for dirname in dirs:
                        if fnmatch.fnmatch(dirname, clean_item):
                            rel_path = os.path.relpath(
                                os.path.join(root, dirname), repo_root
                            )
                            logger.info(
                                "Purging origin exclusive asset (glob dir)",
                                path=rel_path,
                            )
                            self.git.rm([rel_path], cached=True, rf=True)
                            shutil.rmtree(
                                os.path.join(root, dirname), ignore_errors=True
                            )
            else:
                # Exact path or directory
                tracked_files = self.git.ls_files(clean_item)
                if tracked_files:
                    logger.info(
                        "Purging origin exclusive tracked files", path=clean_item
                    )
                    self.git.rm(tracked_files, cached=True, rf=True)

                full_path = os.path.join(repo_root, clean_item)
                if os.path.exists(full_path):
                    logger.info(
                        "Purging origin exclusive workspace file/dir", path=clean_item
                    )
                    self.git.rm([clean_item], cached=True, rf=True)
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path, ignore_errors=True)
                    else:
                        os.remove(full_path)

    def _has_exclusive_path_changes(self, dest_ref: str, origin_ref: str) -> bool:
        if not self.git:
            return False
        changed_files = self.git.diff(dest_ref, origin_ref, name_only=True)
        all_exclusive = (
            self.config.destination_exclusive_paths + self.config.origin_exclusive_paths
        )
        for file in changed_files:
            if is_exclusive_path(file, all_exclusive):
                return True
        return False

    def _resolve_non_exclusive_conflicts(self) -> None:
        if not self.git:
            return
        unmerged = self.git.diff(name_only=True, diff_filter="U")
        all_exclusive = (
            self.config.destination_exclusive_paths + self.config.origin_exclusive_paths
        )
        for file in unmerged:
            if not is_exclusive_path(file, all_exclusive):
                self.git.checkout(file, theirs=True, paths=[file])
                self.git.add([file])

    def _validate_post_merge_state(self, branch: str) -> None:
        if not self.git:
            return
        unresolved = self.git.ls_files(unmerged=True)
        if unresolved:
            raise GitError(
                f"Unresolved merge conflicts remain on branch '{branch}':\n"
                + "\n".join(unresolved)
            )

    def _resolve_seed_reference(self, target_branch: str) -> str:
        if not self.git:
            return "HEAD"
        dest_branch_ref = self.destination_provider.get_remote_ref(target_branch)
        dest_default_ref = self.destination_provider.get_remote_ref(self.default_branch)
        if self.git.ref_exists(dest_branch_ref):
            return dest_branch_ref
        if self.git.ref_exists(dest_default_ref):
            return dest_default_ref
        return "HEAD"

    def _determine_default_branch(self) -> str:
        for branch in self.destination_branches:
            if branch.is_default:
                return branch.name
        for branch in self.origin_branches:
            if branch.is_default:
                return branch.name
        return "main"

    def _setup_environment(self) -> bool:
        logger.info("Step 1: Setting up environment and remotes")

        if self.origin_provider.is_repo_disabled():
            logger.warning("Origin repository is marked as disabled or archived.")
            return False

        repo_dir = self.git.cwd
        mask_patterns = [self.config.origin_token, self.config.destination_token]
        parent_git = Git(os.path.dirname(repo_dir), mask_patterns=mask_patterns)

        dest_url = self.destination_provider.get_authenticated_url()

        # Clone destination repository
        logger.info("Cloning destination repository...")
        parent_git.clone(dest_url, repo_dir)

        self.git.config("user.name", self.config.bot_name)
        self.git.config("user.email", self.config.bot_email)

        # Providers handle remotes, fetching, and branch discovery
        logger.info("Discovering branches via providers...")
        self.origin_branches = self.origin_provider.get_branches()
        if not self.origin_branches and self.origin_provider.is_repo_disabled():
            logger.warning("Origin repository is disabled.")
            return False

        self.destination_branches = self.destination_provider.get_branches()
        self.default_branch = self._determine_default_branch()

        logger.info(
            "Detected destination default branch", default_branch=self.default_branch
        )
        logger.info(
            "Discovered branches",
            origin_count=len(self.origin_branches),
            origin_branches=[b.name for b in self.origin_branches],
            dest_count=len(self.destination_branches),
            dest_branches=[b.name for b in self.destination_branches],
        )
        return True

    def _sync_new_branch(self, dest_branch: str, origin_ref: str) -> None:
        assert self.git is not None
        logger.info("Creating new branch on destination", branch=dest_branch)
        self.git.checkout(dest_branch, base_ref=origin_ref, create=True)

        seed_ref = self._resolve_seed_reference(dest_branch)
        if self.git.ref_exists(seed_ref):
            logger.info(
                "Applying exclusive asset seed", seed_ref=seed_ref, branch=dest_branch
            )
            self._protect_destination_exclusive_assets(seed_ref)

        self._purge_origin_exclusive_assets()

        author_name, author_email = self._resolve_origin_author(origin_ref)
        self.git.add(all_files=True)

        if self.git.status_porcelain():
            msg = (
                f"sync({dest_branch}): align exclusive paths with destination "
                f"{self.default_branch}"
            )
            self.destination_provider.commit(
                subject=msg, author=f"{author_name} <{author_email}>"
            )
        else:
            msg = f"sync({dest_branch}): initialize branch from origin"
            self.destination_provider.commit(
                subject=msg,
                author=f"{author_name} <{author_email}>",
                allow_empty=True,
            )

        push_res = self.git.push(self.destination_remote, ref=dest_branch)
        if push_res.success:
            self.synced_branches.append(dest_branch)
            logger.info(
                "New branch successfully synced to destination", branch=dest_branch
            )
        else:
            self.sync_errors.append(f"Push failed for branch `{dest_branch}`")
            logger.error(
                "Failed to push new branch", branch=dest_branch, stderr=push_res.stderr
            )

    def _perform_fast_forward_sync(
        self, dest_branch: str, origin_ref: str, dest_ref: str
    ) -> None:
        assert self.git is not None
        logger.info("Performing fast-forward sync", branch=dest_branch)
        self.git.checkout(dest_branch, base_ref=origin_ref, create=True)

        self._protect_destination_exclusive_assets(dest_ref)
        self._purge_origin_exclusive_assets()

        author_name, author_email = self._resolve_origin_author(origin_ref)
        origin_subject = (
            self.git.log_one(origin_ref, "%s") or "sync changes from origin"
        )

        self.git.add(all_files=True)
        msg = f"sync({dest_branch}): {origin_subject}"

        if self.git.status_porcelain():
            self.destination_provider.commit(
                subject=msg, author=f"{author_name} <{author_email}>"
            )
        else:
            self.destination_provider.commit(
                subject=msg,
                author=f"{author_name} <{author_email}>",
                allow_empty=True,
            )

        push_res = self.git.push(self.destination_remote, ref=dest_branch)
        if push_res.success:
            self.synced_branches.append(dest_branch)
            logger.info("Fast-forward push succeeded", branch=dest_branch)
        else:
            self.sync_errors.append(f"Push failed for branch `{dest_branch}`")
            logger.error(
                "Fast-forward push failed", branch=dest_branch, stderr=push_res.stderr
            )

    def _perform_three_way_merge_sync(
        self, dest_branch: str, origin_ref: str, dest_ref: str
    ) -> None:
        assert self.git is not None
        logger.info("Performing 3-way merge sync", branch=dest_branch)
        self.git.checkout(dest_branch, base_ref=dest_ref, create=True)

        author_name, author_email = self._resolve_origin_author(origin_ref)
        origin_subject = (
            self.git.log_one(origin_ref, "%s") or "sync changes from origin"
        )
        origin_short_sha = self.git.log_one(origin_ref, "%h") or "unknown"

        subject_msg = f"sync({dest_branch}): {origin_subject}"
        body_msg = f"Origin commit {origin_short_sha} by {author_name} <{author_email}>"

        self.git.merge(
            origin_ref,
            strategy_option="theirs",
            no_commit=True,
            allow_unrelated_histories=True,
        )
        self._resolve_non_exclusive_conflicts()

        seed_ref = self._resolve_seed_reference(dest_branch)
        self._protect_destination_exclusive_assets(seed_ref)
        self._purge_origin_exclusive_assets()

        self._validate_post_merge_state(dest_branch)
        self.git.add(all_files=True)

        if self.git.status_porcelain():
            self.destination_provider.commit(
                subject=subject_msg,
                author=f"{author_name} <{author_email}>",
                body=body_msg,
            )
        else:
            self.destination_provider.commit(
                subject=subject_msg,
                author=f"{author_name} <{author_email}>",
                body=body_msg,
                allow_empty=True,
            )

        push_res = self.git.push(self.destination_remote, ref=dest_branch)
        if push_res.success:
            self.synced_branches.append(dest_branch)
            logger.info("3-way merge push succeeded", branch=dest_branch)
        else:
            self.sync_errors.append(f"Push failed for branch `{dest_branch}`")
            logger.error(
                "3-way merge push failed", branch=dest_branch, stderr=push_res.stderr
            )

    def _process_branch_sync(self, origin_branch: Branch) -> None:
        assert self.git is not None
        if not validate_branch_name(origin_branch.name, self.git):
            return

        # Apply branch name mapping: origin_branch.name -> dest_branch
        dest_branch = self.config.branch_mapping.get(
            origin_branch.name, origin_branch.name
        )
        if not validate_branch_name(dest_branch, self.git):
            logger.warning(
                "Mapped destination branch name is invalid", dest_branch=dest_branch
            )
            return

        origin_ref = origin_branch.remote_ref
        if not self.git.ref_exists(origin_ref):
            logger.warning("Origin remote reference not found", origin_ref=origin_ref)
            return

        dest_ref = self.destination_provider.get_remote_ref(dest_branch)

        # Case 1: Branch does not exist on destination
        if not self.git.ref_exists(dest_ref):
            self._sync_new_branch(dest_branch, origin_ref)
            return

        # Case 2: Destination already has all commits from origin
        if self.git.merge_base_is_ancestor(origin_ref, dest_ref):
            logger.info(
                "Branch already fully synced",
                origin=origin_branch.name,
                destination=dest_branch,
            )
            self.synced_branches.append(dest_branch)
            return

        # Case 3: Safe fast-forward (no changes in exclusive paths and
        # destination is ancestor of origin)
        if not self._has_exclusive_path_changes(
            dest_ref, origin_ref
        ) and self.git.merge_base_is_ancestor(dest_ref, origin_ref):
            self._perform_fast_forward_sync(dest_branch, origin_ref, dest_ref)
        else:
            # Case 4: 3-way merge
            self._perform_three_way_merge_sync(dest_branch, origin_ref, dest_ref)

    def _sync_branches(self) -> None:
        logger.info("Step 2: Syncing branches from Origin to Destination")
        for branch in self.origin_branches:
            self._process_branch_sync(branch)

    def _prune_deleted_origin_branches(self) -> None:
        assert self.git is not None
        logger.info(
            "Step 3: Checking for deleted branches on Origin to prune on Destination"
        )
        rev_mapping = self.config.reverse_branch_mapping

        for dest_branch in self.destination_branches:
            dest_branch_name = dest_branch.name
            if not validate_branch_name(dest_branch_name, self.git):
                continue

            # NEVER prune the destination default branch
            if dest_branch.is_default or dest_branch_name == self.default_branch:
                continue

            # Determine corresponding origin branch name
            origin_branch_name = rev_mapping.get(dest_branch_name, dest_branch_name)
            origin_ref = self.origin_provider.get_remote_ref(origin_branch_name)

            if not self.git.ref_exists(origin_ref):
                logger.info(
                    "Branch deleted on Origin, pruning on Destination",
                    branch=dest_branch_name,
                )
                del_res = self.git.push(
                    self.destination_remote, ref=dest_branch_name, delete=True
                )
                if del_res.success:
                    self.removed_branches.append(dest_branch_name)
                else:
                    self.sync_errors.append(
                        f"Failed to delete branch `{dest_branch_name}` on destination"
                    )
                    logger.warning(
                        "Failed to delete branch on destination",
                        branch=dest_branch_name,
                    )

    def _sync_tags(self) -> None:
        assert self.git is not None
        logger.info("Step 4: Syncing tags")
        push_tags = self.git.push(self.destination_remote, tags=True)
        if not push_tags.success:
            self.sync_errors.append("Push failed for tags")
            logger.error("Failed to push tags", stderr=push_tags.stderr)

    def execute(self) -> SyncResult:
        """Executes repository synchronization and returns the final SyncResult."""
        active = self._setup_environment()
        if not active:
            res = SyncResult(
                repo_name=self.destination_provider.get_repo_name(),
                origin_repo=self.config.origin_url,
                destination_repo=self.config.destination_url,
                already_disabled=True,
            )
            res.write_to_file(self.config.sync_json_file)
            return res

        self._sync_branches()
        self._prune_deleted_origin_branches()
        self._sync_tags()

        res = SyncResult(
            repo_name=self.destination_provider.get_repo_name(),
            origin_repo=self.config.origin_url,
            destination_repo=self.config.destination_url,
            synced_branches=self.synced_branches,
            removed_branches=self.removed_branches,
            errors=self.sync_errors,
        )
        res.write_to_file(self.config.sync_json_file)
        return res
