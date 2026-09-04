"""
Analyzer #5 — Git

Collects repository metadata using read-only Git CLI commands.
Does NOT execute: git checkout, git pull, git reset, git clean, git commit.

If Git is unavailable or the directory is not a repo — returns gracefully.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ..evidence import EvidenceBuilder
from ..models import AnalyzerResult, AnalyzerWarning, EvidenceSource

logger = logging.getLogger(__name__)

# Maximum number of entries to show in "top changed files"
TOP_CHANGED_FILES_LIMIT = 20
# Git log format for commit activity
COMMIT_COUNT_LIMIT = 10000


def run(project_root: Path, evidence: EvidenceBuilder) -> AnalyzerResult:
    result = AnalyzerResult(name="git")

    try:
        data = _analyze_git(project_root, evidence)
        result.data = data
    except Exception as exc:
        logger.exception("Git analyzer failed")
        result.success = False
        result.warnings.append(
            AnalyzerWarning(analyzer="git", error=str(exc), recoverable=True)
        )
        result.data = {"available": False, "error": str(exc)}

    return result


def _analyze_git(project_root: Path, evidence: EvidenceBuilder) -> dict:
    """Run read-only git commands to collect repo metadata."""

    # First check: is this a git repo?
    if not (project_root / ".git").exists():
        # Try running git status to confirm
        ret = _git(project_root, ["rev-parse", "--git-dir"])
        if ret is None:
            return {"available": False, "reason": ".git directory not found"}

    ret = _git(project_root, ["rev-parse", "--git-dir"])
    if ret is None:
        return {"available": False, "reason": "git command failed or not installed"}

    data: dict = {"available": True}

    # Current branch
    branch = _git(project_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch:
        data["current_branch"] = branch.strip()
        evidence.add(
            type="git",
            subject="current_branch",
            value=data["current_branch"],
            source=EvidenceSource(method="git rev-parse --abbrev-ref HEAD"),
        )

    # HEAD commit hash + message
    head_log = _git(project_root, ["log", "-1", "--format=%H|||%ai|||%s"])
    if head_log:
        parts = head_log.strip().split("|||")
        if len(parts) >= 3:
            data["head_commit"] = {
                "hash": parts[0],
                "date": parts[1],
                "message": parts[2],
            }
            evidence.add(
                type="git",
                subject="head_commit",
                value=data["head_commit"],
                source=EvidenceSource(method="git log -1"),
            )

    # Total commit count
    commit_count_str = _git(project_root, ["rev-list", "--count", "HEAD"])
    if commit_count_str:
        try:
            data["total_commits"] = int(commit_count_str.strip())
            evidence.add_metric("git_commits", data["total_commits"])
        except ValueError:
            pass

    # Branch count
    branches_str = _git(project_root, ["branch", "-a"])
    if branches_str:
        branches = [b.strip().lstrip("* ") for b in branches_str.splitlines() if b.strip()]
        # Deduplicate remote/local
        branch_names = set(b.replace("remotes/origin/", "") for b in branches)
        data["branches_count"] = len(branch_names)
        data["branches"] = sorted(branch_names)[:30]  # cap at 30
        evidence.add_metric("git_branches", data["branches_count"])

    # First commit date
    first_commit = _git(project_root, ["log", "--reverse", "--format=%ai", "--max-count=1"])
    if first_commit:
        data["first_commit_date"] = first_commit.strip()
        evidence.add(
            type="git",
            subject="first_commit_date",
            value=data["first_commit_date"],
            source=EvidenceSource(method="git log --reverse"),
        )

    # Latest commit date
    latest_commit = _git(project_root, ["log", "-1", "--format=%ai"])
    if latest_commit:
        data["latest_commit_date"] = latest_commit.strip()

    # Contributors
    contributors_str = _git(
        project_root,
        ["log", "--format=%aN", f"--max-count={COMMIT_COUNT_LIMIT}"],
    )
    if contributors_str:
        names = [n.strip() for n in contributors_str.splitlines() if n.strip()]
        unique_contributors = set(names)
        data["contributors_count"] = len(unique_contributors)
        data["contributors"] = sorted(unique_contributors)
        evidence.add_metric("git_contributors", data["contributors_count"])

    # Modified / deleted files (uncommitted changes)
    status_str = _git(project_root, ["status", "--porcelain"])
    if status_str is not None:
        modified = []
        deleted = []
        untracked = []
        for line in status_str.splitlines():
            if len(line) < 3:
                continue
            xy = line[:2]
            fname = line[3:].strip()
            if "D" in xy:
                deleted.append(fname)
            elif "?" in xy:
                untracked.append(fname)
            else:
                modified.append(fname)
        data["uncommitted_changes"] = {
            "modified_files": modified[:50],
            "deleted_files": deleted[:50],
            "untracked_files": len(untracked),
            "total_modified": len(modified),
            "total_deleted": len(deleted),
        }

    # Top changed files (churn metric)
    churn_str = _git(
        project_root,
        ["log", "--name-only", "--pretty=format:", f"--max-count={COMMIT_COUNT_LIMIT}"],
    )
    if churn_str:
        file_changes: dict[str, int] = {}
        for line in churn_str.splitlines():
            line = line.strip()
            if line:
                file_changes[line] = file_changes.get(line, 0) + 1
        top_changed = sorted(file_changes.items(), key=lambda x: -x[1])
        data["top_changed_files"] = [
            {"file": f, "change_count": c}
            for f, c in top_changed[:TOP_CHANGED_FILES_LIMIT]
        ]
        data["unique_files_changed_total"] = len(file_changes)

    # Commit activity by month (last 12 months)
    activity_str = _git(
        project_root,
        ["log", "--format=%ai", "--since=12 months ago"],
    )
    if activity_str:
        monthly: dict[str, int] = {}
        for line in activity_str.splitlines():
            line = line.strip()
            if line and len(line) >= 7:
                month = line[:7]  # "YYYY-MM"
                monthly[month] = monthly.get(month, 0) + 1
        data["commit_activity_last_12_months"] = {
            "months": dict(sorted(monthly.items())),
            "total_commits": sum(monthly.values()),
        }

    return data


def _git(project_root: Path, args: list[str]) -> str | None:
    """
    Run a read-only git command and return stdout as string.
    Returns None on failure.
    """
    cmd = ["git"] + args
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout
        else:
            logger.debug(f"git command {args} failed: {proc.stderr.strip()}")
            return None
    except FileNotFoundError:
        logger.warning("git not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"git command {args} timed out")
        return None
    except Exception as e:
        logger.warning(f"git command {args} error: {e}")
        return None
