import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _list_plugin_hiddenimports(plugins_dir: Path) -> list[str]:
    hiddenimports: list[str] = []
    if not plugins_dir.exists():
        return hiddenimports
    for item in sorted(plugins_dir.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue
        if item.name.startswith(".") or item.name.startswith("__"):
            continue
        init_py = item / "__init__.py"
        if init_py.exists():
            hiddenimports.append(f"plugins.{item.name}")
    return hiddenimports


def _add_data_args(root: Path) -> list[str]:
    sep = ";"
    data_specs: list[tuple[str, str]] = []

    plugins_dir = root / "plugins"
    if plugins_dir.exists():
        data_specs.append((str(plugins_dir), "plugins"))

    for rel in ["head-img", "img", "voice", os.path.join("channel", "web")]:
        p = root / rel
        if p.exists():
            data_specs.append((str(p), rel))

    wx849_dir = root / "lib" / "wx849" / "849"
    if wx849_dir.exists():
        data_specs.append((str(wx849_dir), str(Path("lib") / "wx849" / "849")))

    wx849_device_info = root / "channel" / "wx849_device_info.json"
    if wx849_device_info.exists():
        data_specs.append((str(wx849_device_info), str(Path("channel"))))

    args: list[str] = []
    for src, dst in data_specs:
        args.extend(["--add-data", f"{src}{sep}{dst}"])
    return args


def _ensure_release_runtime_dirs(release_app_dir: Path) -> None:
    for rel in ["tmp", "logs"]:
        (release_app_dir / rel).mkdir(parents=True, exist_ok=True)


def _write_ecosystem_config(release_app_dir: Path, app_name: str) -> None:
    ecosystem_path = release_app_dir / "ecosystem.config.js"
    script_name = f"{app_name}.exe"
    content = "\n".join(
        [
            "module.exports = {",
            "  apps: [",
            "    {",
            f"      name: '{app_name}',",
            f"      script: '{script_name}',",
            "      cwd: __dirname,",
            "      exec_interpreter: 'none',",
            "      exec_mode: 'fork',",
            "      autorestart: true,",
            "      max_restarts: 10,",
            "      out_file: './logs/out.log',",
            "      error_file: './logs/err.log',",
            "      merge_logs: true,",
            "      env: {",
            "        PYTHONUTF8: '1'",
            "      }",
            "    }",
            "  ]",
            "};",
            "",
        ]
    )
    ecosystem_path.write_text(content, encoding="utf-8")


def _write_release_readme(release_app_dir: Path, app_name: str) -> None:
    readme_path = release_app_dir / "README-PM2.md"
    content = "\n".join(
        [
            "# Release Usage",
            "",
            f"应用目录: `{release_app_dir}`",
            "",
            "## 目录说明",
            f"- `{app_name}.exe`: 主程序",
            "- `_internal/`: 运行时依赖",
            "- `config.json`: 运行配置（优先使用）",
            "- `config-template.json`: 配置模板",
            "- `ecosystem.config.js`: PM2 启动配置",
            "- `logs/`: PM2 输出日志目录",
            "- `tmp/`: 运行时缓存目录",
            "",
            "## PM2 命令",
            "```powershell",
            "cd .",
            "pm2 start ecosystem.config.js",
            "pm2 status",
            "pm2 logs cow-wework-akun",
            "pm2 restart cow-wework-akun",
            "pm2 stop cow-wework-akun",
            "```",
            "",
            "## 重新打包",
            "```powershell",
            "cd <repo-root>",
            ".\\packaging\\build_release.ps1",
            "```",
            "",
            "说明: 如需指定 Python，可设置环境变量 `WEWORK_PYTHON`。",
            "",
        ]
    )
    readme_path.write_text(content, encoding="utf-8")


def _copy_config_files(root: Path, release_app_dir: Path) -> None:
    src_config = root / "config.json"
    src_template = root / "config-template.json"
    src_template_wework = root / "config-template.wework.json"

    if src_template.exists():
        shutil.copy2(src_template, release_app_dir / "config-template.json")
    if src_template_wework.exists():
        shutil.copy2(src_template_wework, release_app_dir / "config-template.wework.json")

    if src_config.exists():
        shutil.copy2(src_config, release_app_dir / "config.json")
        return

    if src_template.exists():
        shutil.copy2(src_template, release_app_dir / "config.json")
        return

    (release_app_dir / "config.json").write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_conda_runtime_dlls(python_exe: Path, release_app_dir: Path) -> None:
    env_root = python_exe.parent
    src_bin = env_root / "Library" / "bin"
    dst_internal = release_app_dir / "_internal"
    if not dst_internal.exists():
        for child in release_app_dir.iterdir():
            if child.is_dir() and child.name.lower().endswith("internal"):
                dst_internal = child
                break
    if not src_bin.exists():
        return
    dst_internal.mkdir(parents=True, exist_ok=True)

    patterns = ["ffi*.dll", "libcrypto*.dll", "libssl*.dll"]
    for pattern in patterns:
        for dll_path in sorted(src_bin.glob(pattern), key=lambda p: p.name.lower()):
            shutil.copy2(dll_path, dst_internal / dll_path.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=os.environ.get("WEWORK_PYTHON", r"D:\conda_envs\wework\python.exe"))
    parser.add_argument("--app-name", default="cow-wework-akun")
    parser.add_argument("--entry", default="app.py")
    parser.add_argument("--release-dir", default=str(_repo_root() / "release"))
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    root = _repo_root()
    release_root = Path(args.release_dir).resolve()
    release_root.mkdir(parents=True, exist_ok=True)

    py = Path(args.python)
    if not py.exists():
        raise FileNotFoundError(f"python not found: {py}")

    entry = (root / args.entry).resolve()
    if not entry.exists():
        raise FileNotFoundError(f"entry not found: {entry}")

    app_name = args.app_name
    distpath = str(release_root)
    workpath = str(root / "build" / "pyinstaller")
    specpath = str(root / "build" / "pyinstaller")

    if args.clean:
        shutil.rmtree(release_root / app_name, ignore_errors=True)
        shutil.rmtree(Path(workpath), ignore_errors=True)

    hiddenimports = _list_plugin_hiddenimports(root / "plugins")
    hiddenimports.extend(["backports", "backports.tarfile"])

    cmd: list[str] = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        app_name,
        "--distpath",
        distpath,
        "--workpath",
        workpath,
        "--specpath",
        specpath,
    ]
    cmd.extend(_add_data_args(root))
    for hi in hiddenimports:
        cmd.extend(["--hidden-import", hi])
    cmd.append(str(entry))

    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=str(root))

    release_app_dir = release_root / app_name
    _ensure_release_runtime_dirs(release_app_dir)
    _copy_config_files(root, release_app_dir)
    _copy_conda_runtime_dlls(py, release_app_dir)
    _write_ecosystem_config(release_app_dir, app_name)
    _write_release_readme(release_app_dir, app_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
