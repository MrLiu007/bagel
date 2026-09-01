"""External CLI runner — subprocess counterpart to httpx + feedparser.

In-process app CLI stays on Typer+Rich (`bagel …`).
Third-party binaries (Feishu/lark-cli, gh, …) go through this runner.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class CliResult:
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0

    @property
    def output(self) -> str:
        return (self.stdout or self.stderr or "").strip()


@dataclass
class CliBinary:
    name: str
    path: str | None = None
    found: bool = False
    version: str = ""
    hints: list[str] = field(default_factory=list)


def resolve_binary(bin_name: str, *, extra_paths: Sequence[str] | None = None) -> CliBinary:
    name = (bin_name or "").strip()
    if not name:
        return CliBinary(name="", found=False, hints=["未配置 CLI 可执行文件名"])

    candidates: list[str] = [name]
    if extra_paths:
        candidates.extend(extra_paths)

    resolved: str | None = None
    for cand in candidates:
        p = Path(cand)
        if p.is_file():
            resolved = str(p)
            break
        which = shutil.which(cand)
        if which:
            resolved = which
            break

    if not resolved:
        return CliBinary(
            name=name,
            found=False,
            hints=[
                f"未找到可执行文件 `{name}`",
                "可在系统设置 → CLI 中填写绝对路径，或加入 PATH",
            ],
        )

    ver = run_command([resolved, "--version"], timeout=8)
    version = ""
    if ver.ok:
        version = (ver.stdout or ver.stderr).strip().splitlines()[0][:120]
    elif ver.returncode != 0:
        # some CLIs use `version` subcommand
        ver2 = run_command([resolved, "version"], timeout=8)
        if ver2.ok:
            version = (ver2.stdout or ver2.stderr).strip().splitlines()[0][:120]

    return CliBinary(name=name, path=resolved, found=True, version=version)


def run_command(
    argv: Sequence[str],
    *,
    timeout: float = 60.0,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> CliResult:
    args = [str(a) for a in argv if a is not None]
    if not args:
        return CliResult(argv=[], returncode=1, error="empty command")
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
            input=input_text,
            check=False,
        )
        return CliResult(
            argv=args,
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except FileNotFoundError as exc:
        return CliResult(argv=args, returncode=127, error=f"not found: {exc}")
    except subprocess.TimeoutExpired:
        return CliResult(argv=args, returncode=124, error=f"timeout after {timeout}s")
    except OSError as exc:
        return CliResult(argv=args, returncode=1, error=str(exc)[:300])
