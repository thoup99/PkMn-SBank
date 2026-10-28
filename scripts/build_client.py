#!/usr/bin/env python3
"""Build Flet's desktop client with gui/flet_drop, so files dragged from the desktop reach the app.

Flet's own client takes no file drops. This checks out Flet's source at the installed version, adds
the extension, and builds the client into gui/client/<platform>; gui/main.py runs it and
scripts/pack_app.py bundles it. Needs Flutter on PATH, the version `flet --version --json` names.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gui.flet_client import CLIENT, MARKER, platform_key  # noqa: E402

SOURCE = CLIENT / "flet"
EXTENSION = ROOT / "gui" / "flet_drop"


def flet_versions() -> tuple[str, str]:
    out = subprocess.check_output([sys.executable, "-m", "flet_cli.cli", "--version", "--json"], text=True)
    found = json.loads(out)
    return found["flet"], found["flutter"]


def drop_extensions(pubspec: Path, main: Path) -> None:
    """Removes every optional Flet extension (video, maps, camera...): the app draws core controls only,
    and the extensions' native libraries were most of the client's size."""
    text, count = re.subn(r"^  flet_\w+:\n    path: \.\./sdk/python/packages/.*\n", "", pubspec.read_text(),
                          flags=re.M)
    assert count, "Flet's client pubspec changed shape"
    pubspec.write_text(text)
    text = re.sub(r"^import ['\"]package:flet_\w+/[^;]*;\n", "", main.read_text(), flags=re.M)
    text, count = re.subn(r"^\s*flet_\w+\.Extension\(\),\n", "", text, flags=re.M)
    assert count and "flet_" not in text.replace("package:flet/", ""), "Flet's client main.dart changed shape"
    main.write_text(text)


def patch(client: Path) -> None:
    subprocess.run(["git", "checkout", "--", "pubspec.yaml", "lib/main.dart"], cwd=client, check=True)
    pubspec, main = client / "pubspec.yaml", client / "lib" / "main.dart"
    drop_extensions(pubspec, main)
    text = pubspec.read_text()
    anchor = "dependencies:\n  flutter:\n    sdk: flutter\n"
    assert anchor in text, "Flet's client pubspec changed shape"
    pubspec.write_text(text.replace(anchor, anchor + f"  flet_drop:\n    path: {EXTENSION.as_posix()}\n", 1))
    text = main.read_text()
    anchor = "List<FletExtension> extensions = [\n"
    assert anchor in text, "Flet's client main.dart changed shape"
    text = text.replace(anchor, anchor + "    flet_drop.Extension(),\n", 1)
    main.write_text("import 'package:flet_drop/flet_drop.dart' as flet_drop;\n" + text)


def main() -> int:
    if sys.platform not in ("linux", "win32"):
        raise SystemExit("Desktop builds support Linux and Windows only; use the website on other platforms.")
    if not shutil.which("flutter"):
        raise SystemExit("Install Flutter first: https://docs.flutter.dev/get-started/install")
    flet, flutter = flet_versions()
    out = subprocess.check_output(["flutter", "--version", "--machine"], text=True, shell=os.name == "nt")
    # A first run on a CI runner prints a banner before the JSON.
    have = json.loads(out[out.index("{"):out.rindex("}") + 1])["frameworkVersion"]
    if have != flutter:
        print(f"Warning: Flet {flet} is built with Flutter {flutter}, this is {have}.", file=sys.stderr)
    tag = f"v{flet}"
    if not (SOURCE / ".git").is_dir():
        CLIENT.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", tag,
                        "https://github.com/flet-dev/flet.git", str(SOURCE)], check=True)
    else:
        found = subprocess.check_output(["git", "describe", "--tags", "--exact-match"], cwd=SOURCE, text=True)
        if found.strip() != tag:
            subprocess.run(["git", "fetch", "--depth", "1", "origin", "tag", tag], cwd=SOURCE, check=True)
            subprocess.run(["git", "checkout", "-f", tag], cwd=SOURCE, check=True)
    client = SOURCE / "client"
    key = platform_key()
    patch(client)
    # The Dart symbols go to a file beside the build, not into the client (2.6 MB on macOS).
    flutter_cmd = ["flutter", "build", key, "--release", f"--build-name={flet}",
                   f"--split-debug-info={client / 'build' / 'dart-symbols'}"]
    subprocess.run(flutter_cmd, cwd=client, check=True, shell=os.name == "nt")
    out = CLIENT / key
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if key == "windows":
        built = client / "build/windows/x64/runner/Release"
        shutil.copytree(built, out / "flet")
        system = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
        for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            shutil.copy2(system / dll, out / "flet")
    else:
        arch = "arm64" if os.uname().machine in ("aarch64", "arm64") else "x64"
        shutil.copytree(client / f"build/linux/{arch}/release/bundle", out / "flet", symlinks=True)
    (out / MARKER).write_text(f"flet {flet}\n")
    print(f"Built {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
