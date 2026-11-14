consolidate these python scripts as single cli tool.
target python=3.14
env=termux
- result code must be typer based cli app,
  no need to copy same flags again, be creative & th8nk about what that two script acvoplushed, impkement a bdter & optimized one that do the same jobs
- result code must use rich library to print to console
- log any errors with loguru
- in repo creation, no need to add all backends, choose best one for this use-case ( or go hybrid)
- add any other features & flags that you recommend.

deliverable: <<consolidated code>> full refactored & type-annotated code, in one markdown block -> (no docstrings & comments needed)


# File: gitools.py

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Optional, Sequence


@dataclass(slots=True)
class CommitInfo:
    sha: str
    subject: str
    timestamp: int
    parents: list[str] = field(default_factory=list)

    @property
    def short(self) -> str:
        return self.sha[:8]

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"[ERR] {msg}", file=sys.stderr)


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _parse_commit_ts(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class GitBackend:
    name = "subprocess"

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()

    def _run(self, *args: str, check: bool = True, input: Optional[str] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            input=input,
            check=check,
        )

    def _git(self, *args: str) -> str:
        return self._run(*args).stdout.strip()

    def is_repo(self) -> bool:
        r = self._run("rev-parse", "--is-inside-work-tree", check=False)
        return r.returncode == 0 and r.stdout.strip() == "true"

    def rev_parse(self, *args: str) -> str:
        return self._git("rev-parse", *args)

    def head_sha(self) -> str:
        return self.rev_parse("HEAD")

    def current_branch(self) -> Optional[str]:
        r = self._run("symbolic-ref", "--short", "-q", "HEAD", check=False)
        return r.stdout.strip() or None

    def is_dirty(self, untracked: bool = True) -> bool:
        args = ["status", "--porcelain"]
        if not untracked:
            args.append("--untracked-files=no")
        return bool(self._run(*args, check=False).stdout.strip())

    def status_porcelain(self) -> list[str]:
        return self._run("status", "--porcelain", check=False).stdout.splitlines()

    def log(self, *, ref: str = "HEAD", n: Optional[int] = None, reverse: bool = False) -> list[CommitInfo]:
        args = ["log", "--format=%H%x00%s%x00%ct%x00%P"]
        if n:
            args.append(f"-n{n}")
        if reverse:
            args.append("--reverse")
        args.append(ref)
        out = self._run(*args, check=False).stdout
        commits: list[CommitInfo] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\x00")
            if len(parts) < 4:
                continue
            sha, subj, ts, parents = parts[0], parts[1], parts[2], parts[3]
            commits.append(
                CommitInfo(
                    sha=sha,
                    subject=subj,
                    timestamp=int(ts),
                    parents=parents.split() if parents else [],
                )
            )
        return commits

    def checkout(self, ref: str) -> None:
        self._git("checkout", ref)

    def reset(self, ref: str, mode: str = "hard") -> None:
        self._git("reset", f"--{mode}", ref)

    def cherry_pick(self, sha: str, allow_empty: bool = True) -> None:
        args = ["cherry-pick"]
        if allow_empty:
            args.append("--allow-empty")
        args.append(sha)
        self._git(*args)

    def create_branch(self, name: str, start: Optional[str] = None) -> None:
        args = ["branch", name]
        if start:
            args.append(start)
        self._git(*args)

    def delete_branch(self, name: str, force: bool = True) -> None:
        self._git("branch", "-D" if force else "-d", name)

    def add(self, *files: str) -> None:
        self._git("add", "--", *files)

    def commit(self, message: str) -> str:
        return self._git("commit", "-m", message)

    def amend_last_commit(self) -> str:
        return self._git("commit", "--amend", "--no-edit")

    def push(self, remote: str, refspec: str, force: bool = False) -> None:
        args = ["push"]
        if force:
            args.append("--force")
        args.extend([remote, refspec])
        self._git(*args)

    def deleted_files_in_history(self) -> dict[str, str]:
        out = self._run(
            "log",
            "--diff-filter=D",
            "--pretty=format:%H",
            "--name-only",
            check=False,
        ).stdout
        deletions: dict[str, str] = {}
        current_sha: Optional[str] = None
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(line) == 40 and " " not in line:
                current_sha = line
            elif current_sha and line not in deletions:
                deletions[line] = current_sha
        return deletions

    def files_added_in_last(self, n: int) -> list[Path]:
        out = self._run(
            "log",
            "-n",
            str(n),
            "--pretty=format:",
            "--name-status",
            "--diff-filter=A",
            check=False,
        ).stdout
        added: list[Path] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                p = self.repo / parts[1]
                if p.is_symlink():
                    continue
                added.append(p)
        return added


class GitPythonBackend(GitBackend):
    name = "gitpython"

    def __init__(self, repo: Path) -> None:
        super().__init__(repo)
        try:
            from git import Repo

            self._r = Repo(str(self.repo))
        except Exception:
            self._r = None

    def is_repo(self) -> bool:
        if self._r is not None:
            return True
        return super().is_repo()

    def head_sha(self) -> str:
        if self._r is not None:
            return self._r.head.commit.hexsha
        return super().head_sha()

    def current_branch(self) -> Optional[str]:
        if self._r is not None and not self._r.head.is_detached:
            return self._r.active_branch.name
        return super().current_branch()

    def is_dirty(self, untracked: bool = True) -> bool:
        if self._r is not None:
            return self._r.is_dirty(untracked_files=untracked)
        return super().is_dirty(untracked)

    def log(self, *, ref: str = "HEAD", n: Optional[int] = None, reverse: bool = False) -> list[CommitInfo]:
        if self._r is None:
            return super().log(ref=ref, n=n, reverse=reverse)
        try:
            commits = list(self._r.iter_commits(ref, max_count=n, reverse=reverse))
        except Exception:
            return super().log(ref=ref, n=n, reverse=reverse)
        return [
            CommitInfo(
                sha=c.hexsha,
                subject=c.summary,
                timestamp=c.committed_date,
                parents=[p.hexsha for p in c.parents],
            )
            for c in commits
        ]

    def reset(self, ref: str, mode: str = "hard") -> None:
        if self._r is None:
            return super().reset(ref, mode)
        self._r.git.reset(f"--{mode}", ref)
        return None

    def checkout(self, ref: str) -> None:
        if self._r is None:
            return super().checkout(ref)
        self._r.git.checkout(ref)
        return None

    def cherry_pick(self, sha: str, allow_empty: bool = True) -> None:
        if self._r is None:
            return super().cherry_pick(sha, allow_empty)
        args = ["--allow-empty"] if allow_empty else []
        self._r.git.cherry_pick(sha, *args)
        return None

    def create_branch(self, name: str, start: Optional[str] = None) -> None:
        if self._r is None:
            return super().create_branch(name, start)
        self._r.create_head(name, start) if start else self._r.create_head(name)
        return None

    def add(self, *files: str) -> None:
        if self._r is None:
            return super().add(*files)
        self._r.index.add(list(files))
        return None

    def commit(self, message: str) -> str:
        if self._r is None:
            return super().commit(message)
        return self._r.index.commit(message).hexsha

    def amend_last_commit(self) -> str:
        if self._r is None:
            return super().amend_last_commit()
        self._r.git.commit("--amend", "--no-edit")
        return self._r.head.commit.hexsha

    def push(self, remote: str, refspec: str, force: bool = False) -> None:
        if self._r is None:
            return super().push(remote, refspec, force)
        args = ["--force"] if force else []
        self._r.git.push(remote, refspec, *args)
        return None


class Pygit2Backend(GitBackend):
    name = "libgit2"

    def __init__(self, repo: Path) -> None:
        super().__init__(repo)
        try:
            import pygit2

            self._repo = pygit2.Repository(str(self.repo))
        except Exception:
            self._repo = None

    def is_repo(self) -> bool:
        if self._repo is not None:
            return True
        return super().is_repo()

    def head_sha(self) -> str:
        if self._repo is not None:
            try:
                return str(self._repo.head.target)
            except Exception:
                pass
        return super().head_sha()

    def rev_parse(self, *args: str) -> str:
        if self._repo is None or len(args) != 1:
            return super().rev_parse(*args)
        try:
            obj = self._repo.revparse_single(args[0])
            return str(obj.id)
        except Exception:
            return super().rev_parse(*args)


class DulwichBackend(GitBackend):
    name = "dulwich"

    def __init__(self, repo: Path) -> None:
        super().__init__(repo)
        try:
            from dulwich.repo import Repo as DRepo

            self._d = DRepo(str(self.repo))
        except Exception:
            self._d = None

    def is_repo(self) -> bool:
        if self._d is not None:
            return True
        return super().is_repo()

    def head_sha(self) -> str:
        if self._d is None:
            return super().head_sha()
        try:
            return self._d.head().decode()
        except Exception:
            return super().head_sha()


class PyGithubBackend(GitBackend):
    name = "pygithub"

    def __init__(self, repo: Path) -> None:
        super().__init__(repo)
        self._gh = None
        try:
            import github

            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if token:
                self._gh = github.Github(token)
        except Exception:
            self._gh = None


class GhBackend(GitBackend):
    name = "gh"


def make_backend(name: str, repo: Path) -> GitBackend:
    if name == "subprocess":
        return GitBackend(repo)
    if name == "gitpython":
        return GitPythonBackend(repo)
    if name == "libgit2":
        return Pygit2Backend(repo)
    if name == "dulwich":
        return DulwichBackend(repo)
    if name == "pygithub":
        return PyGithubBackend(repo)
    if name == "gh":
        return GhBackend(repo)
    if name == "typer":
        return GitBackend(repo)
    msg = f"Unknown backend: {name!r}"
    raise ValueError(msg)


BACKEND_CHOICES: tuple[str, ...] = (
    "subprocess",
    "gitpython",
    "libgit2",
    "dulwich",
    "pygithub",
    "gh",
    "typer",
)


def cmd_checkout_previous(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    if not root.is_dir():
        err(f"Not a directory: {root}")
        return 1
    candidates = [root] + [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    found = False
    for candidate in candidates:
        be = make_backend(args.backend, candidate)
        if not be.is_repo():
            continue
        found = True
        try:
            head_list = be.log(ref="HEAD", n=1)
        except Exception as e:
            err(f"{candidate.name}: {e}")
            continue
        if not head_list:
            continue
        head = head_list[0]
        if not head.subject.startswith(args.prefix):
            print(f"[skip] {candidate.name}: latest commit does not start with {args.prefix!r}")
            continue
        if not head.parents:
            print(f"[skip] {candidate.name}: no parent commit")
            continue
        target = head.parents[0]
        print(f"\n[match] Repository: {candidate.name}")
        print(f"        Path: {candidate}")
        print(f"        Current commit: {head.short}")
        print(f"        Latest message: {head.subject}")
        print(f"        Target commit: {target[:8]}")
        if not args.yes:
            ans = input(f"Checkout {target[:8]} in {candidate.name}? [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print(f"[skip] {candidate.name}: cancelled")
                continue
        be.checkout(target)
        print(f"[done] {candidate.name}: now at {target[:8]}")
    if not found:
        print("No git repositories found.")
    return 0


def cmd_rm_commits(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    branch = be.current_branch()
    if branch is None:
        err("HEAD is detached — checkout a branch first")
        return 1
    print(f"Current branch: {branch}")
    cutoff = _cutoff(args.days)
    print(f"Cutoff: {cutoff:%Y-%m-%d %H:%M:%S UTC}")
    if be.is_dirty(untracked=True):
        err("Working directory is not clean — commit or stash first")
        return 1
    commits = be.log(ref=branch)
    if not commits:
        print("No commits found.")
        return 0
    keep = [c for c in commits if _parse_commit_ts(c.timestamp) > cutoff]
    old = [c for c in commits if _parse_commit_ts(c.timestamp) <= cutoff]
    if not old:
        print(f"No commits older than {args.days} days.")
        return 0
    if not keep:
        err("All commits would be deleted — aborting")
        return 1
    print(f"\nFound {len(old)} commit(s) to delete (older than {args.days} days)")
    print(f"Keeping {len(keep)} commit(s)")
    print("\nOldest commits to delete:")
    for c in old[-5:]:
        print(f"  {c.short} - {c.date:%Y-%m-%d %H:%M} - {c.subject}")
    new_head = keep[0]
    print(f"\nNew HEAD will be: {new_head.short} - {new_head.subject}")
    if not args.yes:
        ans = input("This will PERMANENTLY DELETE those commits. Continue? (yes/no): ").strip().lower()
        if ans != "yes":
            print("Cancelled.")
            return 0
    backup = f"backup-{branch}-{datetime.now():%Y%m%d%H%M%S}"
    print(f"\nCreating backup branch: {backup}")
    be.create_branch(backup)
    be.reset(new_head.sha, "hard")
    print(f"\n✓ Deleted {len(old)} commit(s)")
    print(f"Backup branch: {backup}")
    print(f"To restore: git reset --hard {backup}")
    return 0


def cmd_cut(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    cutoff = _cutoff(args.days)
    print(f"Cutoff date: {cutoff:%Y-%m-%d %H:%M:%S UTC}")
    commits = be.log(ref="HEAD")
    if not commits:
        print("No commits found.")
        return 0
    keep = [c for c in commits if _parse_commit_ts(c.timestamp) > cutoff]
    old = [c for c in commits if _parse_commit_ts(c.timestamp) <= cutoff]
    print(f"Commits to keep:   {len(keep)}")
    print(f"Commits to remove: {len(old)}")
    if not keep:
        err("No commits to keep — aborting")
        return 1
    if not old:
        print("No old commits to remove.")
        return 0
    oldest_kept = keep[-1]
    print(f"\nOldest kept: {oldest_kept.short} - {oldest_kept.subject}")
    print(f"Date:        {oldest_kept.date}")
    if not args.yes:
        ans = input("\nRewrite history? (yes/no): ").strip().lower()
        if ans != "yes":
            print("Cancelled.")
            return 0
    branch = be.current_branch()
    if args.method == "squash":
        be.reset(oldest_kept.sha, "hard")
        print(f"\n✓ Old commits removed (reset --hard to {oldest_kept.short}).")
        if branch:
            print(f"Force push needed: git push --force origin {branch}")
        return 0
    if branch is None:
        err("Cannot use orphan method on a detached HEAD")
        return 1
    new_branch = f"cleaned_{branch}"
    print(f"\nCreating orphan branch {new_branch}...")
    subprocess.run(["git", "checkout", "--orphan", new_branch], cwd=str(repo), check=True)
    for c in reversed(keep):
        try:
            be.cherry_pick(c.sha, allow_empty=True)
        except subprocess.CalledProcessError as e:
            warn(f"cherry-pick {c.short} failed: {e.stderr or e}")
    print(f"\n✓ New branch {new_branch} with {len(keep)} commit(s) created.")
    print(f"\nTo replace the original:")
    print(f"  git checkout {branch}")
    print(f"  git reset --hard {new_branch}")
    print(f"  git branch -D {new_branch}")
    return 0


def cmd_del_remote_commits(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    branch = args.branch
    try:
        refs = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        ).stdout
        if branch == "master" and "origin/main" in refs and "origin/master" not in refs:
            branch = "main"
    except Exception:
        pass
    cutoff = _cutoff(args.days)
    commits = be.log(ref=branch)
    if not commits:
        err(f"No commits on {branch}")
        return 1
    keep = [c for c in commits if _parse_commit_ts(c.timestamp) >= cutoff]
    if not keep:
        err(f"No commits within {args.days} days — nothing to keep, aborting")
        return 1
    new_head = keep[0]
    print(f"Branch: {branch}")
    print(f"Cutoff: {cutoff:%Y-%m-%d %H:%M:%S UTC}")
    print(f"Resetting to: {new_head.short} - {new_head.subject}")
    print(f"              ({new_head.date:%Y-%m-%d %H:%M UTC})")
    if not args.yes:
        ans = input("Proceed with local reset and force-push? (yes/no): ").strip().lower()
        if ans != "yes":
            print("Cancelled.")
            return 0
    if be.current_branch() != branch:
        be.checkout(branch)
    be.reset(new_head.sha, "hard")
    print(f"✓ Local branch {branch} reset to {new_head.short}")
    if args.no_push:
        print("Skipping push (--no-push).")
    else:
        try:
            be.push("origin", f"{branch}:{branch}", force=True)
            print(f"✓ Force-pushed {branch} to origin")
        except Exception as e:
            err(f"push failed: {e}")
            return 1
    return 0


def cmd_list_added(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    added = be.files_added_in_last(args.n)
    if not added:
        print(f"No files created in the last {args.n} commit(s).")
        return 0
    for path in added:
        try:
            print(path.relative_to(repo))
        except ValueError:
            print(path)
    return 0


def cmd_restore_deleted(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    print("🔍 Analyzing repository history for file deletions...")
    deletions = be.deleted_files_in_history()
    if not deletions:
        print("🎉 No deleted files found in this repository's history.")
        return 0
    missing = [(p, sha) for p, sha in deletions.items() if not (repo / p).exists()]
    if not missing:
        print("ℹ️  All historically deleted files are already present.")
        return 0
    print(f"⚠️  Found {len(missing)} missing file(s).\n")
    restored = 0
    for p, sha in missing:
        print(f"🔄 Restoring: {p} (from commit prior to {sha[:8]})")
        try:
            subprocess.run(
                ["git", "checkout", f"{sha}^", "--", p],
                cwd=str(repo),
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "add", "--", p], cwd=str(repo), check=True, capture_output=True)
            restored += 1
        except subprocess.CalledProcessError:
            try:
                subprocess.run(
                    ["git", "checkout", sha, "--", p],
                    cwd=str(repo),
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "add", "--", p],
                    cwd=str(repo),
                    check=True,
                    capture_output=True,
                )
                restored += 1
            except subprocess.CalledProcessError as e2:
                err(f"   could not restore {p}: {e2}")
    if restored:
        print(f"\n💾 Committing {restored} restored file(s)...")
        try:
            be.commit(args.message)
            print("✓ Commit created.")
        except Exception as e:
            err(f"commit failed: {e}")
            return 1
    else:
        print("❌ No files were successfully restored.")
    return 0


def _pending_deletions_matching_history(be: GitBackend) -> list[str]:
    historical = set(be.deleted_files_in_history().keys())
    if not historical:
        return []
    pending: list[str] = []
    for line in be.status_porcelain():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip()
        if "D" in code and path in historical:
            pending.append(path)
    return pending


def cmd_stage_deleted(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    pending = _pending_deletions_matching_history(be)
    if not pending:
        print("🎉 No pending historical file deletions need staging.")
        return 0
    print(f"⚠️  Found {len(pending)} deleted file(s) to stage:")
    for p in pending:
        print(f"  {p}")
    print("\n🛠️  Staging...")
    for p in pending:
        be.add(p)
    print(f'💾 Committing: "{args.message}"')
    try:
        be.commit(args.message)
        print("✓ Commit created.")
    except Exception as e:
        err(f"commit failed: {e}")
        return 1
    return 0


def cmd_squash_deletions(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    be = make_backend(args.backend, repo)
    if not be.is_repo():
        err(f"{repo} is not a git repository")
        return 1
    pending = _pending_deletions_matching_history(be)
    if not pending:
        print("🎉 No pending historical file deletions to squash.")
        return 0
    print(f"⚠️  Found {len(pending)} deleted file(s) to squash:")
    for p in pending:
        print(f"  {p}")
    print("\n🛠️  Staging...")
    for p in pending:
        be.add(p)
    print("💾 Amending last commit (--amend --no-edit)...")
    try:
        be.amend_last_commit()
        print("✓ Last commit amended.")
    except Exception as e:
        err(f"amend failed: {e}")
        return 1
    return 0


def cmd_age_filter(args: argparse.Namespace) -> int:
    age_bin = args.age_bin
    if not age_bin:
        default = Path.home() / ".." / "usr" / "bin" / "age"
        age_bin = str(default) if default.exists() else "age"
    if args.mode == "clean":
        pub_path = Path(args.public_key).expanduser()
        if not pub_path.exists():
            err(f"missing public key file: {pub_path}")
            return 1
        recipient = pub_path.read_text(encoding="utf-8").strip()
        if not recipient:
            err("public key file is empty")
            return 1
        data = sys.stdin.buffer.read()
        r = subprocess.run([age_bin, "-r", recipient, "-a"], input=data, capture_output=True)
        if r.returncode != 0:
            err(f"age encrypt failed: {r.stderr.decode(errors='replace')}")
            return 1
        sys.stdout.buffer.write(r.stdout)
        return 0
    data = sys.stdin.buffer.read()
    if not data.lstrip().startswith(b"-----BEGIN AGE ENCRYPTED FILE-----"):
        sys.stdout.buffer.write(data)
        return 0
    priv = Path(args.private_key).expanduser()
    if not priv.exists():
        warn("no private key; leaving ciphertext")
        sys.stdout.buffer.write(data)
        return 0
    r = subprocess.run([age_bin, "-d", "-i", str(priv)], input=data, capture_output=True)
    if r.returncode != 0:
        err(f"age decrypt failed: {r.stderr.decode(errors='replace')}")
        return 1
    sys.stdout.buffer.write(r.stdout)
    return 0


def _add_backend_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-b",
        "--backend",
        choices=BACKEND_CHOICES,
        default="subprocess",
        help="Git backend (default: subprocess; other backends fall back to subprocess for unsupported operations)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git_kit.py",
        description="Unified git maintenance CLI with pluggable backends.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Original-script mapping:\n"
            "  checkout_previous.py                ->  checkout-previous\n"
            "  cut30.py                            ->  cut\n"
            "  delcomit.py                         ->  del-remote-commits\n"
            "  git-age-filter.py                   ->  age-filter\n"
            "  lastncommits.py                     ->  list-added\n"
            "  restore_all_historical_deletions.py ->  restore-deleted\n"
            "  rmcommits.py                        ->  rm-commits\n"
            "  squash_deletions.py                 ->  squash-deletions\n"
            "  stage_deleted_files.py              ->  stage-deleted\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "checkout-previous",
        help="Checkout HEAD^ in repos whose HEAD subject matches a prefix",
    )
    p.add_argument(
        "-C",
        "--repo",
        default=".",
        help="Directory containing repositories (default: .)",
    )
    p.add_argument(
        "--prefix",
        default="2026-08-29",
        help="Latest commit subject must start with this prefix (default: 2026-08-29)",
    )
    p.add_argument("-y", "--yes", action="store_true", help="Skip the interactive confirmation")
    _add_backend_arg(p)
    p.set_defaults(func=cmd_checkout_previous)
    p = sub.add_parser(
        "rm-commits",
        help="Reset branch to drop commits older than N days (creates a backup branch)",
    )
    p.add_argument("-C", "--repo", default=".")
    p.add_argument(
        "--days",
        type=int,
        default=30,
        help="Delete commits older than N days (default: 30)",
    )
    p.add_argument("-y", "--yes", action="store_true")
    _add_backend_arg(p)
    p.set_defaults(func=cmd_rm_commits)
    p = sub.add_parser("cut", help="Rewrite branch dropping commits older than N days")
    p.add_argument("-C", "--repo", default=".")
    p.add_argument(
        "--days",
        type=int,
        default=30,
        help="Delete commits older than N days (default: 30)",
    )
    p.add_argument(
        "--method",
        choices=("squash", "orphan"),
        default="squash",
        help="Rewrite method (default: squash)",
    )
    p.add_argument("-y", "--yes", action="store_true")
    _add_backend_arg(p)
    p.set_defaults(func=cmd_cut)
    p = sub.add_parser(
        "del-remote-commits",
        help="Reset branch and force-push (deletes commits on remote)",
    )
    p.add_argument("-C", "--repo", default=".")
    p.add_argument(
        "--branch",
        default="master",
        help="Branch to clean (default: master; falls back to main)",
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Delete commits older than N days (default: 7)",
    )
    p.add_argument("--no-push", action="store_true", help="Do not force-push; only reset locally")
    p.add_argument("-y", "--yes", action="store_true")
    _add_backend_arg(p)
    p.set_defaults(func=cmd_del_remote_commits)
    p = sub.add_parser("list-added", help="List files added in the last N commits")
    p.add_argument("-C", "--repo", default=".")
    p.add_argument("-n", type=int, default=10, help="Number of commits to look back (default: 10)")
    _add_backend_arg(p)
    p.set_defaults(func=cmd_list_added)
    p = sub.add_parser("restore-deleted", help="Restore every file ever deleted in history")
    p.add_argument("-C", "--repo", default=".")
    p.add_argument(
        "-m",
        "--message",
        default="removed files",
        help='Commit message for the restore commit (default: "removed files")',
    )
    _add_backend_arg(p)
    p.set_defaults(func=cmd_restore_deleted)
    p = sub.add_parser("stage-deleted", help="Stage pending deletions that match history, then commit")
    p.add_argument("-C", "--repo", default=".")
    p.add_argument(
        "-m",
        "--message",
        default="removed files",
        help='Commit message (default: "removed files")',
    )
    _add_backend_arg(p)
    p.set_defaults(func=cmd_stage_deleted)
    p = sub.add_parser("squash-deletions", help="Amend last commit with pending historical deletions")
    p.add_argument("-C", "--repo", default=".")
    _add_backend_arg(p)
    p.set_defaults(func=cmd_squash_deletions)
    p = sub.add_parser(
        "age-filter",
        help="age-based git clean/smudge filter (reads/writes stdin/stdout)",
    )
    p.add_argument("mode", choices=("clean", "smudge"), help='"clean" encrypts; "smudge" decrypts')
    p.add_argument("--age-bin", default=None, help="Path to the age binary (default: auto-detect)")
    p.add_argument(
        "--public-key",
        default=str(Path.home() / ".config" / "age" / "public.key"),
        help="Public key file (default: ~/.config/age/public.key)",
    )
    p.add_argument(
        "--private-key",
        default=str(Path.home() / ".config" / "age" / "keys.txt"),
        help="Private key file (default: ~/.config/age/keys.txt)",
    )
    p.set_defaults(func=cmd_age_filter)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)
# File: gittools.py

import argparse
import concurrent.futures
import json
import os
import pathlib
import shutil
import subprocess
from typing import Any, Optional
import urllib.error
import urllib.request

from dh import MAX_WORKERS

_SOURCE_CITATION: str = "[cite: 1]"


def run_git(
    args: list[str], cwd: Optional[pathlib.Path] = None, check: bool = True, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=check, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        msg = f"git command timed out: {' '.join(args)}"
        raise RuntimeError(msg) from e
    except FileNotFoundError as e:
        msg = "git executable not found"
        raise RuntimeError(msg) from e


def get_current_branch(repo_path: pathlib.Path) -> str:
    res = run_git(["branch", "--show-current"], cwd=repo_path, check=False)
    branch = res.stdout.strip()
    if branch:
        return branch
    res2 = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=True)
    branch2 = res2.stdout.strip()
    if branch2 == "HEAD":
        msg = "detached HEAD"
        raise RuntimeError(msg)
    return branch2


def get_github_token(env_file: Optional[pathlib.Path] = None) -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    path = (env_file or pathlib.Path.home() / ".env").expanduser()
    if not path.exists():
        msg = f"GITHUB_TOKEN not found and {path} does not exist"
        raise RuntimeError(msg)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if line.startswith("GITHUB_TOKEN="):
            val = line.split("=", 1)[1].strip().strip("\"'")
            if val:
                return val
    msg = f"GITHUB_TOKEN not found in {path}"
    raise RuntimeError(msg)


def github_api_request(token: str, method: str, url: str, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "git-helper-tool/1.0")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"message": err_body}
        msg = f"GitHub API error {e.code}: {err_json.get('message', err_body)}"
        raise RuntimeError(msg) from e


def create_github_repo(
    token: str, name: str, private: bool, description: Optional[str], auto_init: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "private": private, "auto_init": auto_init}
    if description:
        payload["description"] = description
    try:
        return github_api_request(token, "POST", "https://api.github.com/user/repos", payload)
    except RuntimeError as e:
        if "422" in str(e):
            user_info = github_api_request(token, "GET", "https://api.github.com/user")
            login = user_info.get("login", "")
            return {
                "clone_url": f"https://github.com/{login}/{name}.git",
                "ssh_url": f"git@github.com:{login}/{name}.git",
                "html_url": f"https://github.com/{login}/{name}",
            }
        raise


def find_git_repos(root_path: pathlib.Path) -> list[pathlib.Path]:
    repos: list[pathlib.Path] = []
    for root, dirs, _ in os.walk(root_path):
        current = pathlib.Path(root)
        if (current / ".git").is_dir():
            repos.append(current)
            dirs[:] = []
    return repos


def cmd_scan_changes(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.path).resolve()
    repos = find_git_repos(root)
    if not repos:
        print("No git repositories found.")
        return 0

    def check_repo(repo: pathlib.Path) -> tuple[pathlib.Path, bool, str]:
        try:
            res = run_git(["status", "--porcelain"], cwd=repo, check=False, timeout=10)
            if res.returncode != 0:
                return (repo, False, f"Git error: {res.stderr.strip()}")
            lines = [line for line in res.stdout.splitlines() if line.strip()]
            if not lines:
                return (repo, False, "Clean")
            detail = ", ".join(lines[:5])
            if len(lines) > 5:
                detail += f" (+{len(lines) - 5} more)"
            return (repo, True, detail)
        except Exception as e:
            return (repo, False, f"Error: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(check_repo, repos))
    dirty_repos = [r for r in results if r[1]]
    for repo, dirty, detail in results:
        if dirty:
            print(f"✗ {repo.name}: CHANGES DETECTED\n  └─ {detail}")
        else:
            print(f"✓ {repo.name}: No changes\n  └─ {detail}")
    if dirty_repos:
        print(f"Found {len(dirty_repos)} repository(ies) with changes")
    else:
        print("All repositories are clean")
    return 0


def cmd_pull_all(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.path).resolve()
    repos = find_git_repos(root)
    if not repos:
        print("No git repositories found.")
        return 0

    def pull_repo(repo: pathlib.Path) -> tuple[pathlib.Path, bool, str]:
        try:
            branch = get_current_branch(repo)
            res = run_git(["remote"], cwd=repo, check=False)
            if res.returncode != 0 or not res.stdout.strip():
                return (repo, False, "No remote configured")
            remote = res.stdout.splitlines()[0]
            run_git(["pull", remote, branch], cwd=repo, check=True, timeout=120)
            return (repo, True, "Pulled successfully")
        except Exception as e:
            return (repo, False, str(e))

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(pull_repo, repos))
    for repo, success, msg in results:
        if success:
            print(f"✅ {repo.relative_to(root)}: {msg}")
        else:
            print(f"❌ {repo.relative_to(root)}: {msg}")
    return 0


def cmd_new_repo(args: argparse.Namespace) -> int:
    token = get_github_token(pathlib.Path(args.env_file) if args.env_file else None)
    cwd = pathlib.Path.cwd().resolve()
    name = args.name or cwd.name
    user_info = github_api_request(token, "GET", "https://api.github.com/user")
    login = user_info.get("login", "")
    repo_info = create_github_repo(token, name, args.private, args.description, False)
    clone_url = repo_info.get("clone_url") or repo_info.get("ssh_url")
    if not clone_url:
        msg = "Could not determine remote URL"
        raise RuntimeError(msg)
    if not (cwd / ".git").is_dir():
        run_git(["init", "-b", args.branch], cwd=cwd, check=True)
    gitignore_dest = cwd / ".gitignore"
    gitignore_global = pathlib.Path.home() / ".gitignore"
    if not gitignore_dest.exists() and gitignore_global.exists():
        shutil.copy2(gitignore_global, gitignore_dest)
    run_git(["add", "-A"], cwd=cwd, check=True)
    status_res = run_git(["status", "--porcelain"], cwd=cwd, check=True)
    if status_res.stdout.strip():
        run_git(["commit", "-m", args.message], cwd=cwd, check=True)
    run_git(["branch", "-M", args.branch], cwd=cwd, check=True)
    remote_res = run_git(["remote", "get-url", "origin"], cwd=cwd, check=False)
    if remote_res.returncode == 0:
        if remote_res.stdout.strip() != clone_url:
            run_git(["remote", "set-url", "origin", clone_url], cwd=cwd, check=True)
    else:
        run_git(["remote", "add", "origin", clone_url], cwd=cwd, check=True)
    run_git(["push", "-u", "origin", args.branch], cwd=cwd, check=True)
    print(f"https://github.com/{login}/{name}")
    return 0


def cmd_gitignore_add(args: argparse.Namespace) -> int:
    line = args.line.strip()
    if not line:
        msg = "line cannot be empty"
        raise RuntimeError(msg)
    paths = [pathlib.Path(p).resolve() for p in (args.paths or ["."])]
    gi_files: list[pathlib.Path] = []
    for p in paths:
        if p.is_file() and p.name == ".gitignore":
            gi_files.append(p)
        elif p.is_dir():
            gi_files.extend([f for f in p.rglob(".gitignore") if f.is_file()])
    modified = 0
    for gi in gi_files:
        try:
            content = gi.read_text(encoding="utf-8", errors="ignore")
            if line in content.splitlines():
                continue
            if content and not content.endswith("\n"):
                content += "\n"
            content += line + "\n"
            gi.write_text(content, encoding="utf-8")
            modified += 1
            print(f"Updated {gi}")
        except Exception as e:
            print(f"Failed {gi}: {e}", file=sys.stderr)
    print(f"Modified {modified} file(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="git-helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    p_scan = subparsers.add_parser("scan-changes")
    p_scan.add_argument("path", nargs="?", default=".")
    p_scan.set_defaults(func=cmd_scan_changes)
    p_pull = subparsers.add_parser("pull-all")
    p_pull.add_argument("path", nargs="?", default=".")
    p_pull.set_defaults(func=cmd_pull_all)
    p_new = subparsers.add_parser("newrepo")
    p_new.add_argument("--name", default=None)
    p_new.add_argument("--private", action="store_true")
    p_new.add_argument("--description", default=None)
    p_new.add_argument("--message", default="Initial commit")
    p_new.add_argument("--branch", default="main")
    p_new.add_argument("--env-file", default=None)
    p_new.set_defaults(func=cmd_new_repo)
    p_gi = subparsers.add_parser("gitignore-add")
    p_gi.add_argument("line")
    p_gi.add_argument("paths", nargs="*")
    p_gi.set_defaults(func=cmd_gitignore_add)
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

# File: gittools2.py

import argparse
import contextlib
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any, Callable, Iterator

from loguru import logger

LOG = logger
EXIT_OK: int = 0
EXIT_NO_COMMITS: int = 1
EXIT_USAGE: int = 2
EXIT_REPO: int = 3
BACKEND_CAPS: dict[str, dict[str, bool]] = {
    "dulwich": {"rename": False, "stats": False},
    "pygit2": {"rename": True, "stats": True},
    "gitpython": {"rename": True, "stats": True},
    "gitcli": {"rename": True, "stats": True},
}
CSV_FIELDS: list[str] = [
    "sha",
    "short",
    "author_name",
    "author_email",
    "committer_name",
    "committer_email",
    "authored_at",
    "committed_at",
    "message",
    "parents",
    "added",
    "modified",
    "deleted",
    "renamed",
    "files",
    "insertions",
    "deletions",
]


@dataclass(slots=True)
class Options:
    repo_path: str = "."
    branch: str = "HEAD"
    since: str | None = None
    until: str | None = None
    author: str | None = None
    max_count: int | None = None
    first_parent: bool = False
    path: str | None = None
    exclude: str | None = None
    mode: str = "changed"
    rename: bool = False


@dataclass(slots=True)
class CommitRecord:
    sha: str
    short: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    authored_at: str
    committed_at: str
    message: str
    parents: list[str]
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _passes_filters(rec: CommitRecord, opts: Options) -> bool:
    if opts.author:
        needle = opts.author.lower()
        hay = (rec.author_email + " " + rec.author_name).lower()
        if needle not in hay:
            return False
    if opts.since and _parse_dt(rec.authored_at) < _parse_dt(opts.since):
        return False
    return not (opts.until and _parse_dt(rec.authored_at) > _parse_dt(opts.until))


def _path_ok(path: str, opts: Options) -> bool:
    if opts.path and not fnmatch.fnmatch(path, opts.path):
        return False
    return not (opts.exclude and fnmatch.fnmatch(path, opts.exclude))


def _apply_mode(rec: CommitRecord, mode: str) -> CommitRecord:
    if mode == "added":
        rec.modified = []
        rec.deleted = []
        rec.renamed = []
    elif mode == "modified":
        rec.added = []
        rec.deleted = []
        rec.renamed = []
    elif mode == "deleted":
        rec.added = []
        rec.modified = []
        rec.renamed = []
    elif mode == "changed":
        rec.renamed = []
    return rec


def _sig_iso(t: int, offset_min: int) -> str:
    tz = timezone(timedelta(minutes=offset_min))
    return datetime.fromtimestamp(t, tz=timezone.utc).astimezone(tz).isoformat()


def _parse_actor(raw: bytes | str) -> tuple[str, str]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if "<" in raw and ">" in raw:
        name, rest = raw.rsplit("<", 1)
        return name.strip(), rest.rstrip(">").strip()
    return raw.strip(), ""


def _iter_dulwich(opts: Options) -> Iterator[CommitRecord]:
    from dulwich.repo import Repo

    repo = Repo(opts.repo_path)
    try:
        ref = opts.branch
        try:
            head_sha = repo.refs[ref.encode()]
        except KeyError:
            try:
                head_sha = repo.refs[f"refs/heads/{ref}".encode()]
            except KeyError:
                head_sha = ref.encode()
        blob_cache: dict[bytes, dict[str, bytes]] = {}

        def tree_blobs(tree_sha: bytes) -> dict[str, bytes]:
            if tree_sha in blob_cache:
                return blob_cache[tree_sha]
            result: dict[str, bytes] = {}
            stack = [("", repo[tree_sha])]
            while stack:
                prefix, t = stack.pop()
                for item in t.iteritems():
                    name = item.path.decode() if isinstance(item.path, bytes) else item.path
                    full = prefix + name
                    if item.mode & 0o170000 == 0o040000:
                        stack.append((full + "/", repo[item.sha]))
                    else:
                        result[full] = item.sha
            blob_cache[tree_sha] = result
            return result

        emitted = 0

        def _build(commit: Any) -> CommitRecord:
            sha = commit.id.decode()
            an, ae = _parse_actor(commit.author)
            cn, ce = _parse_actor(commit.committer)
            parents = [p.decode() for p in commit.parents]
            parents_used = parents[:1] if (opts.first_parent and parents) else parents
            current = tree_blobs(commit.tree)
            parent_map: dict[str, bytes] = {}
            for p in parents_used:
                pc = repo[p.encode()]
                parent_map.update(tree_blobs(pc.tree))
            added, modified, deleted = [], [], []
            for path, sh in current.items():
                if not _path_ok(path, opts):
                    continue
                if path not in parent_map:
                    added.append(path)
                elif parent_map[path] != sh:
                    modified.append(path)
            for path in parent_map:
                if not _path_ok(path, opts):
                    continue
                if path not in current:
                    deleted.append(path)
            return CommitRecord(
                sha=sha,
                short=sha[:8],
                author_name=an,
                author_email=ae,
                committer_name=cn,
                committer_email=ce,
                authored_at=_sig_iso(commit.author_time, commit.author_timezone),
                committed_at=_sig_iso(commit.commit_time, commit.commit_timezone),
                message=commit.message.decode("utf-8", errors="replace").strip(),
                parents=parents,
                added=sorted(added),
                modified=sorted(modified),
                deleted=sorted(deleted),
                renamed=[],
                stats={"files": len(added) + len(modified) + len(deleted)},
            )

        if opts.first_parent:
            cur = head_sha.decode() if isinstance(head_sha, bytes) else head_sha
            seen: set[str] = set()
            while cur and cur not in seen:
                seen.add(cur)
                commit = repo[cur.encode()]
                rec = _build(commit)
                if _passes_filters(rec, opts):
                    yield _apply_mode(rec, opts.mode)
                    emitted += 1
                    if opts.max_count is not None and emitted >= opts.max_count:
                        break
                cur = commit.parents[0].decode() if commit.parents else None
        else:
            walker = repo.get_walker(include=[head_sha])
            for entry in walker:
                rec = _build(entry.commit)
                if _passes_filters(rec, opts):
                    yield _apply_mode(rec, opts.mode)
                    emitted += 1
                    if opts.max_count is not None and emitted >= opts.max_count:
                        break
    finally:
        repo.close()


def _iter_pygit2(opts: Options) -> Iterator[CommitRecord]:
    import pygit2

    repo = pygit2.Repository(opts.repo_path)
    try:
        ref = repo.revparse_single(opts.branch)
    except (KeyError, ValueError):
        ref = repo.revparse_single("HEAD")
    head_id = (
        ref.id if hasattr(ref, "id") and isinstance(ref.id, pygit2.Oid) else getattr(ref, "target", None) or ref.id
    )

    def _build(commit: Any) -> CommitRecord:
        parents = list(commit.parents)
        parents_used = parents[:1] if (opts.first_parent and parents) else parents
        if parents_used:
            diff = repo.diff(parents_used[0], commit, context_lines=0)
        else:
            diff = commit.tree.diff_to_tree(context_lines=0)
        if opts.rename:
            with contextlib.suppress(Exception):
                diff.find_similar()
        added, modified, deleted, renamed = [], [], [], []
        for patch in diff:
            d = patch.delta
            old_path = d.old_file.path
            new_path = d.new_file.path
            st = d.status
            if st == pygit2.GIT_DELTA_ADDED:
                if _path_ok(new_path, opts):
                    added.append(new_path)
            elif st == pygit2.GIT_DELTA_DELETED:
                if _path_ok(old_path, opts):
                    deleted.append(old_path)
            elif st == pygit2.GIT_DELTA_RENAMED:
                if _path_ok(new_path, opts):
                    renamed.append({"from": old_path, "to": new_path})
            elif st in (pygit2.GIT_DELTA_MODIFIED, pygit2.GIT_DELTA_COPIED) and _path_ok(new_path, opts):
                modified.append(new_path)
        try:
            s = diff.stats
            stats = {
                "files": s.files_changed,
                "insertions": s.insertions,
                "deletions": s.deletions,
            }
        except Exception:
            stats = {}
        return CommitRecord(
            sha=str(commit.id),
            short=str(commit.id)[:8],
            author_name=commit.author.name,
            author_email=commit.author.email,
            committer_name=commit.committer.name,
            committer_email=commit.committer.email,
            authored_at=_sig_iso(commit.author.time, commit.author.offset),
            committed_at=_sig_iso(commit.committer.time, commit.committer.offset),
            message=commit.message.strip(),
            parents=[str(p.id) for p in parents],
            added=sorted(added),
            modified=sorted(modified),
            deleted=sorted(deleted),
            renamed=renamed,
            stats=stats,
        )

    emitted = 0
    if opts.first_parent:
        cur = head_id
        seen: set[str] = set()
        while cur is not None:
            sid = str(cur)
            if sid in seen:
                break
            seen.add(sid)
            commit = repo[cur]
            rec = _build(commit)
            if _passes_filters(rec, opts):
                yield _apply_mode(rec, opts.mode)
                emitted += 1
                if opts.max_count is not None and emitted >= opts.max_count:
                    break
            cur = commit.parents[0].id if commit.parents else None
    else:
        for commit in repo.walk(head_id, pygit2.GIT_SORT_TIME):
            rec = _build(commit)
            if _passes_filters(rec, opts):
                yield _apply_mode(rec, opts.mode)
                emitted += 1
                if opts.max_count is not None and emitted >= opts.max_count:
                    break


def _iter_gitpython(opts: Options) -> Iterator[CommitRecord]:
    from git import Repo as GitRepo
    from git.objects.tree import NULL_TREE

    repo = GitRepo(opts.repo_path)
    kwargs: dict[str, Any] = {}
    if opts.first_parent:
        kwargs["first_parent"] = True
    try:
        commits = repo.iter_commits(opts.branch, **kwargs)
    except Exception:
        commits = iter(())
    emitted = 0
    for commit in commits:
        parents = list(commit.parents)
        parents_used = parents[:1] if (opts.first_parent and parents) else parents
        if parents_used:
            diffs = commit.diff(parents_used[0], create_patch=False, R=opts.rename)
        else:
            diffs = commit.diff(NULL_TREE, create_patch=False, R=opts.rename)
        added, modified, deleted, renamed = [], [], [], []
        for d in diffs:
            ct = d.change_type
            a = d.a_path
            b = d.b_path
            if ct == "A":
                if _path_ok(b, opts):
                    added.append(b)
            elif ct == "D":
                if _path_ok(a, opts):
                    deleted.append(a)
            elif ct == "R":
                if _path_ok(b, opts):
                    renamed.append({"from": a, "to": b})
            elif ct in ("M", "C", "T") and _path_ok(b, opts):
                modified.append(b)
        try:
            total = commit.stats.total
            stats = {
                "files": int(total.get("files", 0)),
                "insertions": int(total.get("insertions", 0)),
                "deletions": int(total.get("deletions", 0)),
            }
        except Exception:
            stats = {}
        rec = CommitRecord(
            sha=commit.hexsha,
            short=commit.hexsha[:8],
            author_name=commit.author.name,
            author_email=commit.author.email,
            committer_name=commit.committer.name,
            committer_email=commit.committer.email,
            authored_at=commit.authored_datetime.isoformat(),
            committed_at=commit.committed_datetime.isoformat(),
            message=commit.message.strip(),
            parents=[p.hexsha for p in parents],
            added=sorted(added),
            modified=sorted(modified),
            deleted=sorted(deleted),
            renamed=renamed,
            stats=stats,
        )
        if _passes_filters(rec, opts):
            yield _apply_mode(rec, opts.mode)
            emitted += 1
            if opts.max_count is not None and emitted >= opts.max_count:
                break


def _iter_gitcli(opts: Options) -> Iterator[CommitRecord]:
    args = [
        "git",
        "-C",
        opts.repo_path,
        "log",
        "--format=%x1e%H%x1f%h%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%aI%x1f%cI%x1f%s%x1f%P",
        "--name-status",
        "-z",
    ]
    args.append("-M" if opts.rename else "--no-renames")
    if opts.first_parent:
        args.append("--first-parent")
    if opts.since:
        args.append(f"--since={opts.since}")
    if opts.until:
        args.append(f"--until={opts.until}")
    if opts.author:
        args.append(f"--author={opts.author}")
    args.append(opts.branch)
    try:
        out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return
    emitted = 0
    for chunk in out.split("\x1e")[1:]:
        nl = chunk.find("\n")
        if nl < 0:
            continue
        header = chunk[:nl].split("\x1f")
        if len(header) < 10:
            continue
        sha, short, an, ae, cn, ce, ai, ci, msg, parents_str = header[:10]
        parents = parents_str.split() if parents_str.strip() else []
        tokens = chunk[nl + 1 :].split("\0")
        added, modified, deleted, renamed = [], [], [], []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if not tok:
                i += 1
                continue
            code = tok[0]
            if code in ("R", "C"):
                if i + 2 >= len(tokens):
                    break
                old = tokens[i + 1]
                new = tokens[i + 2]
                i += 3
                if code == "R":
                    if _path_ok(new, opts):
                        renamed.append({"from": old, "to": new})
                elif _path_ok(new, opts):
                    added.append(new)
            else:
                if i + 1 >= len(tokens):
                    break
                path = tokens[i + 1]
                i += 2
                if code == "A":
                    if _path_ok(path, opts):
                        added.append(path)
                elif code == "D":
                    if _path_ok(path, opts):
                        deleted.append(path)
                elif code in ("M", "T") and _path_ok(path, opts):
                    modified.append(path)
        rec = CommitRecord(
            sha=sha,
            short=short,
            author_name=an,
            author_email=ae,
            committer_name=cn,
            committer_email=ce,
            authored_at=ai,
            committed_at=ci,
            message=msg.strip(),
            parents=parents,
            added=sorted(added),
            modified=sorted(modified),
            deleted=sorted(deleted),
            renamed=renamed,
            stats={},
        )
        if _passes_filters(rec, opts):
            yield _apply_mode(rec, opts.mode)
            emitted += 1
            if opts.max_count is not None and emitted >= opts.max_count:
                break


BACKENDS: dict[str, Callable[[Options], Iterator[CommitRecord]]] = {
    "dulwich": _iter_dulwich,
    "pygit2": _iter_pygit2,
    "gitpython": _iter_gitpython,
    "gitcli": _iter_gitcli,
}


def iter_commits(repo_path: str = ".", backend: str = "dulwich", **kwargs: Any) -> Iterator[CommitRecord]:
    opts = Options(repo_path=repo_path, **kwargs)
    if backend not in BACKENDS:
        msg = f"unknown backend: {backend}"
        raise ValueError(msg)
    return BACKENDS[backend](opts)


def get_added_files_per_commit(repo_path: str = ".", backend: str = "dulwich", **kwargs: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for rec in iter_commits(repo_path=repo_path, backend=backend, **kwargs):
        result[rec.short] = sorted({p.split("/")[-1] for p in rec.added})
    return result


def _record_to_row(rec: CommitRecord) -> dict[str, Any]:
    return {
        "sha": rec.sha,
        "short": rec.short,
        "author_name": rec.author_name,
        "author_email": rec.author_email,
        "committer_name": rec.committer_name,
        "committer_email": rec.committer_email,
        "authored_at": rec.authored_at,
        "committed_at": rec.committed_at,
        "message": rec.message,
        "parents": ";".join(rec.parents),
        "added": ";".join(rec.added),
        "modified": ";".join(rec.modified),
        "deleted": ";".join(rec.deleted),
        "renamed": ";".join(f"{r['from']}->{r['to']}" for r in rec.renamed),
        "files": rec.stats.get("files", 0),
        "insertions": rec.stats.get("insertions", 0),
        "deletions": rec.stats.get("deletions", 0),
    }


def _write_json(records: Iterator[CommitRecord], out: Any) -> int:
    data = [asdict(r) for r in records]
    json.dump(data, out, indent=2, default=str)
    out.write("\n")
    return len(data)


def _write_jsonl(records: Iterator[CommitRecord], out: Any) -> int:
    n = 0
    for r in records:
        out.write(json.dumps(asdict(r), default=str) + "\n")
        n += 1
    return n


def _write_csv(records: Iterator[CommitRecord], out: Any) -> int:
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS)
    writer.writeheader()
    n = 0
    for r in records:
        writer.writerow(_record_to_row(r))
        n += 1
    return n


def _write_yaml(records: Iterator[CommitRecord], out: Any) -> int:
    try:
        import yaml
    except ImportError as e:
        msg = f"yaml output requires pyyaml: {e}"
        raise SystemExit(msg)
    data = [asdict(r) for r in records]
    yaml.safe_dump(data, out, sort_keys=False, default_flow_style=False)
    return len(data)


def _write_markdown(records: Iterator[CommitRecord], out: Any) -> int:
    cols = [
        "short",
        "author_name",
        "authored_at",
        "added",
        "modified",
        "deleted",
        "renamed",
    ]
    out.write("| " + " | ".join(cols) + " |\n")
    out.write("| " + " | ".join("---" for _ in cols) + " |\n")
    n = 0
    for r in records:
        row = _record_to_row(r)
        cells = [str(row[c]).replace("|", "\\|") for c in cols]
        out.write("| " + " | ".join(cells) + " |\n")
        n += 1
    return n


def _write_table(records: Iterator[CommitRecord], out: Any) -> int:
    rows = [_record_to_row(r) for r in records]
    if not rows:
        return 0
    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(show_header=True, header_style="bold")
        for c in CSV_FIELDS:
            table.add_column(c)
        for row in rows:
            table.add_row(*[str(row[c]) for c in CSV_FIELDS])
        Console(file=out, force_terminal=False).print(table)
    except ImportError:
        widths = {c: max(len(c), max((len(str(r[c])) for r in rows), default=0)) for c in CSV_FIELDS}
        out.write(" | ".join(c.ljust(widths[c]) for c in CSV_FIELDS) + "\n")
        out.write("-+-".join("-" * widths[c] for c in CSV_FIELDS) + "\n")
        for r in rows:
            out.write(" | ".join(str(r[c]).ljust(widths[c]) for c in CSV_FIELDS) + "\n")
    return len(rows)


WRITERS: dict[str, Callable[[Iterator[CommitRecord], Any], int]] = {
    "json": _write_json,
    "jsonl": _write_jsonl,
    "csv": _write_csv,
    "yaml": _write_yaml,
    "md": _write_markdown,
    "markdown": _write_markdown,
    "table": _write_table,
}


def _load_config_file(path: Path | None) -> dict[str, Any]:
    candidates: list[Path] = []
    if path:
        candidates.append(path)
    else:
        candidates.append(Path(".gitaddedfiles.toml"))
        candidates.append(Path("pyproject.toml"))
    for p in candidates:
        if not p.is_file():
            continue
        try:
            with p.open("rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            LOG.warning("could not read config {}: {}", p, e)
            continue
        if p.name == "pyproject.toml":
            return data.get("tool", {}).get("gitaddedfiles", {})
        return data
    return {}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="git-added-files",
        description="List added/modified/deleted files per commit across multiple Git backends.",
    )
    p.add_argument(
        "repo_path",
        nargs="?",
        default=None,
        help="Path to the git repository (default: .)",
    )
    p.add_argument("output_path", nargs="?", default=None, help="Output file (- for stdout)")
    p.add_argument("-b", "--backend", choices=list(BACKENDS), help="Git backend to use")
    p.add_argument("-f", "--format", dest="fmt", choices=list(WRITERS), help="Output format")
    p.add_argument("--branch", help="Ref/branch to walk (default: HEAD)")
    p.add_argument("--since", help="Only commits after this date (ISO 8601 or git-style)")
    p.add_argument("--until", help="Only commits before this date")
    p.add_argument("--author", help="Filter by author name or email (substring)")
    p.add_argument("--max-count", type=int, help="Limit number of commits emitted")
    p.add_argument(
        "--first-parent",
        action="store_true",
        default=None,
        help="Follow only first parents",
    )
    p.add_argument("--path", help="Only include paths matching this glob (fnmatch)")
    p.add_argument("--exclude", help="Exclude paths matching this glob (fnmatch)")
    p.add_argument(
        "--mode",
        choices=["added", "modified", "deleted", "changed", "all"],
        help="Which change types to include",
    )
    p.add_argument(
        "--rename",
        action="store_true",
        default=None,
        help="Enable rename detection (backend-dependent)",
    )
    p.add_argument(
        "--config",
        help="Explicit config TOML path (default: .gitaddedfiles.toml or pyproject.toml)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count but do not write output",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    p.add_argument("-q", "--quiet", action="store_true", help="Quiet logging (errors only)")
    return p


def _resolve(cli_val: Any, key: str, env_key: str, config: dict[str, Any], default: Any) -> Any:
    if cli_val is not None:
        return cli_val
    if key in config:
        return config[key]
    if env_key in os.environ:
        return os.environ[env_key]
    return default


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = "ERROR" if args.quiet else ("DEBUG" if args.verbose else "INFO")
    config = _load_config_file(Path(args.config) if args.config else None)
    repo_path = _resolve(args.repo_path, "repo_path", "GAF_REPO_PATH", config, ".")
    output_path = _resolve(args.output_path, "output_path", "GAF_OUTPUT_PATH", config, None)
    backend = _resolve(args.backend, "backend", "GAF_BACKEND", config, "dulwich")
    fmt = _resolve(args.fmt, "format", "GAF_FORMAT", config, "json")
    branch = _resolve(args.branch, "branch", "GAF_BRANCH", config, "HEAD")
    since = _resolve(args.since, "since", "GAF_SINCE", config, None)
    until = _resolve(args.until, "until", "GAF_UNTIL", config, None)
    author = _resolve(args.author, "author", "GAF_AUTHOR", config, None)
    max_count = _resolve(args.max_count, "max_count", "GAF_MAX_COUNT", config, None)
    first_parent = _resolve(args.first_parent, "first_parent", "GAF_FIRST_PARENT", config, False)
    path_glob = _resolve(args.path, "path", "GAF_PATH", config, None)
    exclude = _resolve(args.exclude, "exclude", "GAF_EXCLUDE", config, None)
    mode = _resolve(args.mode, "mode", "GAF_MODE", config, "changed")
    rename = _resolve(args.rename, "rename", "GAF_RENAME", config, False)
    if max_count is not None:
        try:
            max_count = int(max_count)
        except (TypeError, ValueError):
            LOG.error("invalid max_count: {}", max_count)
            return EXIT_USAGE
    if backend not in BACKENDS:
        LOG.error("unknown backend: {} (choose from {})", backend, ", ".join(BACKENDS))
        return EXIT_USAGE
    if fmt not in WRITERS:
        LOG.error("unknown format: {} (choose from {})", fmt, ", ".join(WRITERS))
        return EXIT_USAGE
    if rename and not BACKEND_CAPS[backend]["rename"]:
        LOG.warning("backend {} does not support rename detection; ignoring --rename", backend)
        rename = False
    opts = Options(
        repo_path=str(repo_path),
        branch=branch,
        since=since,
        until=until,
        author=author,
        max_count=max_count,
        first_parent=bool(first_parent),
        path=path_glob,
        exclude=exclude,
        mode=mode,
        rename=bool(rename),
    )
    try:
        records = BACKENDS[backend](opts)
    except ImportError as e:
        LOG.error("missing dependency for backend {}: {}", backend, e)
        return EXIT_REPO
    except Exception as e:
        LOG.error("failed to open repository: {}", e)
        if args.verbose:
            LOG.exception("traceback")
        return EXIT_REPO
    if args.dry_run:
        n = sum(1 for _ in records)
        LOG.info("dry run: would write {} commits (backend={}, format={})", n, backend, fmt)
        return EXIT_OK if n else EXIT_NO_COMMITS
    try:
        if output_path in (None, "-"):
            n = WRITERS[fmt](records, sys.stdout)
        else:
            with open(output_path, "w", newline="") as f:
                n = WRITERS[fmt](records, f)
    except Exception as e:
        LOG.error("output error: {}", e)
        if args.verbose:
            LOG.exception("traceback")
        return EXIT_REPO
    LOG.info("wrote {} commits (backend={}, format={})", n, backend, fmt)
    return EXIT_OK if n else EXIT_NO_COMMITS


if __name__ == "__main__":
    sys.exit(main())
