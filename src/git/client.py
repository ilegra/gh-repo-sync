import os
import re
import subprocess
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class GitError(Exception):
    """Exception raised when a git command fails or encounters an operational error."""

    def __init__(self, message: str, result: Optional["GitResult"] = None):
        super().__init__(message)
        self.result = result


class GitResult:
    """Represents the execution result of a git CLI command invocation."""

    def __init__(self, exit_code: int, stdout: str, stderr: str, command: list[str]):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.command = command
        self.success = exit_code == 0

    def raise_for_status(self) -> "GitResult":
        """Raises a GitError if the exit code was non-zero."""
        if not self.success:
            cmd_str = " ".join(self.command)
            raise GitError(
                f"Git command failed ({self.exit_code}): {cmd_str}\n"
                f"Stderr: {self.stderr}\nStdout: {self.stdout}",
                result=self,
            )
        return self

    def __repr__(self) -> str:
        return f"<GitResult exit_code={self.exit_code} success={self.success}>"


class Git:
    """Wrapper around Git CLI commands for repository manipulations."""

    def __init__(self, cwd: str, mask_patterns: list[str] | None = None):
        self.cwd = cwd
        self.mask_patterns = mask_patterns or []

    def mask_text(self, text: str) -> str:
        """Masks sensitive credentials and tokens in command strings."""
        masked = text
        for pat in self.mask_patterns:
            if pat:
                masked = masked.replace(pat, "***")
        # Mask basic credentials embedded in URLs: https://user:pass@
        masked = re.sub(r"://([^:@\s]+):([^@\s]+)@", r"://\1:***@", masked)
        return masked

    def run(self, *args: str, check: bool = False) -> GitResult:
        """Executes an arbitrary git command within the configured working directory."""
        cmd = ["git"] + list(args)
        cmd_str = self.mask_text(" ".join(cmd))
        logger.debug("Executing git command", cmd=cmd_str, cwd=self.cwd)

        try:
            process = subprocess.run(
                cmd,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            stdout = process.stdout.strip()
            stderr = process.stderr.strip()
            result = GitResult(process.returncode, stdout, stderr, cmd)
            if check:
                result.raise_for_status()
            return result
        except FileNotFoundError as e:
            if not os.path.exists(self.cwd):
                raise GitError(f"Working directory does not exist: {self.cwd}")
            raise GitError(f"git executable not found in PATH: {e}")
        except GitError:
            raise
        except Exception as e:
            logger.exception("Unexpected error executing git", error=str(e))
            raise GitError(f"Unexpected git error: {e}")

    def clone(self, url: str, target_dir: str) -> GitResult:
        """Clones a remote repository to the designated target directory."""
        # Run clone using parent directory of target_dir or self.cwd if valid
        clone_cwd = (
            self.cwd if os.path.exists(self.cwd) else os.path.dirname(target_dir)
        )
        cmd = ["git", "clone", url, target_dir]
        try:
            process = subprocess.run(
                cmd, cwd=clone_cwd, capture_output=True, text=True, check=False
            )
            result = GitResult(
                process.returncode, process.stdout.strip(), process.stderr.strip(), cmd
            )
            result.raise_for_status()
            return result
        except FileNotFoundError as e:
            if not os.path.exists(clone_cwd):
                raise GitError(f"Clone directory does not exist: {clone_cwd}")
            raise GitError(f"git executable not found in PATH: {e}")

    def remote_add(self, name: str, url: str) -> GitResult:
        """Adds a named remote repository URL."""
        return self.run("remote", "add", name, url, check=True)

    def config(self, key: str, value: str) -> GitResult:
        """Sets a git configuration value."""
        return self.run("config", key, value, check=True)

    def fetch(self, remote: str, prune: bool = True) -> GitResult:
        """Fetches references from a remote with optional pruning."""
        args = ["fetch", remote]
        if prune:
            args.append("--prune")
        return self.run(*args)

    def rev_parse(self, ref: str, verify: bool = True) -> GitResult:
        """Resolves a git reference using rev-parse."""
        args = ["rev-parse", "--quiet"]
        if verify:
            args.append("--verify")
        args.append(ref)
        return self.run(*args)

    def ref_exists(self, ref: str) -> bool:
        """Checks if a git reference exists in the repository."""
        if not ref:
            return False
        res = self.rev_parse(ref, verify=True)
        return res.success

    def check_ref_format(self, branch: str) -> bool:
        """Validates if a given branch name adheres to git ref naming formats."""
        res = self.run("check-ref-format", "--branch", branch)
        return res.success

    def log_one(self, ref: str, format_str: str) -> str:
        """Fetches a single commit formatted according to format_str."""
        res = self.run("log", "-1", f"--format={format_str}", ref)
        if res.success:
            return res.stdout
        return ""

    def for_each_ref(
        self, ref_prefix: str, format_str: str = "%(refname)"
    ) -> list[str]:
        """Lists repository references matching a prefix using for-each-ref."""
        res = self.run("for-each-ref", f"--format={format_str}", ref_prefix, check=True)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def checkout(
        self,
        branch: str,
        base_ref: str | None = None,
        create: bool = False,
        theirs: bool = False,
        paths: list[str] | None = None,
    ) -> GitResult:
        """Checks out branch, ref, or specific paths with optional branch creation."""
        args = ["checkout"]
        if theirs:
            args.append("--theirs")
        if create:
            args.extend(["-B", branch])
            if base_ref:
                args.append(base_ref)
        elif not paths:
            args.append(branch)

        if paths:
            if base_ref and not create:
                args.append(base_ref)
            args.append("--")
            args.extend(paths)
        return self.run(*args)

    def rm(self, paths: list[str], cached: bool = False, rf: bool = False) -> GitResult:
        """Removes paths from working tree and/or index."""
        if not paths:
            return GitResult(0, "", "", ["git", "rm"])
        args = ["rm"]
        if rf:
            args.append("-rf")
        if cached:
            args.append("--cached")
        args.append("--")
        args.extend(paths)
        return self.run(*args)

    def add(self, paths: list[str] | None = None, all_files: bool = False) -> GitResult:
        """Stages file changes in index."""
        args = ["add"]
        if all_files:
            args.append("-A")
        elif paths:
            args.append("--")
            args.extend(paths)
        else:
            args.append(".")
        return self.run(*args)

    def commit(
        self, message: str, author: str | None = None, allow_empty: bool = False
    ) -> GitResult:
        """Records changes to the repository with commit message and optional author."""
        args = ["commit", "-m", message]
        if author:
            args.append(f"--author={author}")
        if allow_empty:
            args.append("--allow-empty")
        return self.run(*args)

    def push(
        self,
        remote: str,
        ref: str | None = None,
        delete: bool = False,
        tags: bool = False,
    ) -> GitResult:
        """Pushes references or tags to a remote destination."""
        args = ["push", remote]
        if delete and ref:
            args.extend(["--delete", ref])
        elif tags:
            args.append("--tags")
        elif ref:
            args.append(ref)
        return self.run(*args)

    def diff(
        self,
        ref1: str | None = None,
        ref2: str | None = None,
        name_only: bool = True,
        diff_filter: str | None = None,
    ) -> list[str]:
        """Shows changes between commits, commit and working tree, etc."""
        args = ["diff"]
        if name_only:
            args.append("--name-only")
        if diff_filter:
            args.append(f"--diff-filter={diff_filter}")
        if ref1:
            args.append(ref1)
        if ref2:
            args.append(ref2)
        res = self.run(*args)
        if not res.success:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def merge_base_is_ancestor(self, ref1: str, ref2: str) -> bool:
        """Checks if ref1 is an ancestor of ref2."""
        res = self.run("merge-base", "--is-ancestor", ref1, ref2)
        return res.success

    def merge(
        self,
        ref: str,
        strategy_option: str = "theirs",
        no_commit: bool = True,
        allow_unrelated_histories: bool = True,
    ) -> GitResult:
        """Merges changes from ref into current branch using strategy options."""
        args = ["merge"]
        if strategy_option:
            args.extend(["-X", strategy_option])
        if no_commit:
            args.append("--no-commit")
        if allow_unrelated_histories:
            args.append("--allow-unrelated-histories")
        args.append(ref)
        return self.run(*args)

    def status_porcelain(self) -> list[str]:
        """Returns porcelain status of working directory."""
        res = self.run("status", "--porcelain", check=True)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def symbolic_ref(self, ref: str, short: bool = True) -> GitResult:
        """Reads, sets, or deletes symbolic refs."""
        args = ["symbolic-ref"]
        if short:
            args.append("--short")
        args.append(ref)
        return self.run(*args)

    def ls_files(self, path: str | None = None, unmerged: bool = False) -> list[str]:
        """Lists files in the index or unmerged paths."""
        args = ["ls-files"]
        if unmerged:
            args.append("-u")
        if path:
            args.append(path)
        res = self.run(*args)
        if not res.success:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
