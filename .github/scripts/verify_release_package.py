"""校验发布归档是否自带 pyproject 声明所需的构建包与入口点。

单独成脚本、而不是写进 pytest：打包依赖 tar / zip，本地 Windows 环境不一定具备，
放在 CI 的独立 job 中执行更合适。

用法：python .github/scripts/verify_release_package.py <归档文件> [项目根目录]
"""

from __future__ import annotations

import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

REQUIRED_DIRS = ("desktop", "extension", "scripts", "skills")
REQUIRED_FILES = ("SKILL.md", "README.md", "LICENSE", "pyproject.toml", "uv.lock")


def archive_entries(archive: Path) -> set[str]:
    """返回归档内的相对路径；tar 包需先剥掉统一的前缀目录。"""
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as handle:
            return set(handle.namelist())
    with tarfile.open(archive) as handle:
        names = handle.getnames()
    prefix = names[0].split("/", 1)[0]
    return {name.removeprefix(f"{prefix}/") for name in names}


def load_pyproject(root: Path) -> dict:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def declared_packages(project: dict) -> list[str]:
    hatch = project.get("tool", {}).get("hatch", {})
    wheel = hatch.get("build", {}).get("targets", {}).get("wheel", {})
    return list(wheel.get("packages", []))


def entry_point_modules(project: dict) -> list[str]:
    scripts = project.get("project", {}).get("scripts", {})
    return [target.split(":", 1)[0] for target in scripts.values()]


def missing_entries(entries: set[str], project: dict) -> list[str]:
    missing = [
        f"{name}/"
        for name in REQUIRED_DIRS
        if not any(entry.startswith(f"{name}/") for entry in entries)
    ]
    missing += [name for name in REQUIRED_FILES if name not in entries]
    for package in declared_packages(project):
        if not any(entry.startswith(f"{package}/") for entry in entries):
            missing.append(f"{package}/（pyproject 的构建包声明）")
    for module in entry_point_modules(project):
        path = module.replace(".", "/")
        if not any(entry == f"{path}.py" or entry.startswith(f"{path}/") for entry in entries):
            missing.append(f"{path}.py（[project.scripts] 入口点目标）")
    return missing


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: verify_release_package.py <归档文件> [项目根目录]")
        return 2
    archive = Path(argv[1])
    root = Path(argv[2]) if len(argv) > 2 else Path.cwd()
    missing = missing_entries(archive_entries(archive), load_pyproject(root))
    if missing:
        for name in missing:
            print(f"::error::{archive.name} 缺少 {name}")
        return 1
    print(f"{archive.name} 校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
