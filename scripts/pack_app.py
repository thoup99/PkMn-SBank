#!/usr/bin/env python3
"""Build a desktop bundle, including PKHeX and the required radio firmware."""
import argparse
import os
import importlib.util
import platform
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pokeldn import __version__
from gui.flet_client import CLIENT, MARKER, platform_key

FIRMWARE = ROOT / "gui" / "firmware" / "pokeldn-radio.bin"
FIRMWARE_S3 = ROOT / "gui" / "firmware" / "pokeldn-radio-s3.bin"
FIRMWARE_C3 = ROOT / "gui" / "firmware" / "pokeldn-radio-c3.bin"
FIRMWARE_C6 = ROOT / "gui" / "firmware" / "pokeldn-radio-c6.bin"
FIRMWARE_PAD = ROOT / "gui" / "firmware" / "pokeldn-pad-s3.bin"
FIRMWARE_PAD_ESP32 = ROOT / "gui" / "firmware" / "pokeldn-pad.bin"
FIRMWARE_BLE = ROOT / "gui" / "firmware" / "pokeldn-radio-ble.bin"
FIRMWARE_BLE_C6 = ROOT / "gui" / "firmware" / "pokeldn-radio-ble-c6.bin"
APP_ID = "io.github.decryptu.pokeldn"
UNICORN = ROOT / "gui" / "unicorn"
MARKER_UNICORN = "pokeldn-unicorn"
def runtime_id() -> str:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return f"win-{arch}" if sys.platform == "win32" else f"linux-{arch}"


def runtime_files() -> list[str]:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    folders = ("bin/", "pokeldn/", "vendor/LDN/ldn/", "docs/", "gui/assets/")
    return [name for name in tracked if (name.startswith(folders) or name in
            ("config/host.toml", "gui/guide.md", "LICENSE", "vendor/LDN/LICENSE")) and (ROOT / name).is_file()]


def platform_excludes():
    excluded = ["pytest", "_pytest", "PyInstaller", "flet_cli", "pip", "setuptools",
                "pycparser.lextab", "pycparser.yacctab",
                # Flet's web server, auth and raw-image extras; the desktop view uses none of them.
                "flet_web", "fastapi", "starlette", "uvicorn", "uvloop", "httptools", "watchfiles",
                "pydantic", "pydantic_core", "httpx", "httpcore", "oauthlib", "yaml", "PIL",
                # rich's syntax highlighting, Markdown and tracebacks (Pygments, markdown-it, pydoc): esptool
                # prints through rich and rich-click and reaches none of them. No code starts processes.
                "pygments", "rich.syntax", "rich.markdown", "rich.traceback", "rich.__main__",
                "multiprocessing", "_pydecimal"]
    if sys.platform != "win32":
        excluded += ["serial.tools.list_ports_windows", "serial.serialwin32", "serial.win32",
                     "flet_desktop.win_taskbar", "click._winconsole"]
    excluded.append("serial.tools.list_ports_osx")
    if not sys.platform.startswith("linux"):
        excluded.append("serial.tools.list_ports_linux")
    return excluded


# Standard-library modules pokeldn never imports, bundled so a plugin can (docs/plugins.md, What a plugin
# can import). Developer tools, multiprocessing and the platform-only modules stay out.
PLUGIN_STDLIB = ("cmath", "cmd", "code", "codeop", "dbm", "filecmp", "fileinput", "graphlib", "imaplib",
                 "mailbox", "optparse", "pickletools", "poplib", "sched", "shelve", "smtplib", "socketserver",
                 "sqlite3", "symtable", "syslog", "timeit", "wave", "wsgiref", "xmlrpc", "zipapp", "zoneinfo")


# docs/plugins.md, What a plugin can import: shipped whole, not only what pokeldn imports. flet, bleak
# and unicorn are collected below on their own terms.
PLUGIN_PACKAGES = ("trio", "Crypto", "zstandard", "serial", "websockets", "certifi")


def plugin_stdlib() -> list[str]:
    return [name for name in PLUGIN_STDLIB if importlib.util.find_spec(name) is not None]


def clear_cfg(exe: Path) -> None:
    """PyInstaller's Windows bootloader enables Control Flow Guard; Unicorn faults in a CFG process
    (unicorn-engine/unicorn#2281), python.exe has it off. Clear GUARD_CF in DllCharacteristics.
    Trap: a stale header CheckSum reads as a tampered file to antivirus heuristics; recompute it."""
    data = bytearray(exe.read_bytes())
    pe = int.from_bytes(data[0x3C:0x40], "little")
    assert data[pe:pe + 4] == b"PE\0\0", exe
    field = pe + 24 + 70
    flags = int.from_bytes(data[field:field + 2], "little")
    data[field:field + 2] = (flags & ~0x4000).to_bytes(2, "little")
    checksum = pe + 24 + 64
    data[checksum:checksum + 4] = pe_checksum(data, checksum).to_bytes(4, "little")
    exe.write_bytes(data)


def pe_checksum(data: bytes, field: int) -> int:
    """The PE optional header CheckSum (imagehlp CheckSumMappedFile), skipping its own four bytes."""
    padded = bytes(data[:field]) + b"\0\0\0\0" + bytes(data[field + 4:]) + b"\0" * (len(data) % 2)
    total = sum(memoryview(padded).cast("H"))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return total + len(data)


def main() -> int:
    if sys.platform not in ("linux", "win32"):
        raise SystemExit("Desktop builds support Linux and Windows only; use the website on other platforms.")
    argparse.ArgumentParser(description=__doc__).parse_args()
    firmware = (FIRMWARE, FIRMWARE_S3, FIRMWARE_C3, FIRMWARE_C6, FIRMWARE_PAD, FIRMWARE_PAD_ESP32, FIRMWARE_BLE,
                FIRMWARE_BLE_C6)
    missing = [str(path) for path in firmware if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing firmware: {', '.join(missing)}. Build all eight images "
                         "as described in docs/gui.md before packing.")
    client = CLIENT / platform_key()
    if not (client / MARKER).is_file():
        raise SystemExit("Missing the Flet client that takes file drops. Build it with "
                         "python scripts/build_client.py (needs Flutter) before packing.")
    if not (UNICORN / MARKER_UNICORN).is_file():
        raise SystemExit("Missing the ARM-only Unicorn. Build it with python scripts/build_unicorn.py "
                         "(needs CMake) before packing.")
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit("Install desktop build dependencies: python -m pip install -r gui/requirements.txt")
    service = ROOT / "services" / "pkhex"
    subprocess.run(["dotnet", "publish", str(service), "-c", "Release", "-r", runtime_id(),
                    "-o", str(service / "dist"), "-warnaserror"], check=True)
    executable = service / "dist" / ("pokeldn-pkhex.exe" if sys.platform == "win32" else "pokeldn-pkhex")
    with tempfile.TemporaryDirectory(prefix="pokeldn-pack-") as folder:
        stage = Path(folder)
        icon = ROOT / "gui/assets" / ("icon.ico" if sys.platform == "win32" else "icon.png")
        for name in runtime_files():
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dest)
        dependencies = stage / "dependencies"
        data = [(stage / name, name) for name in
                ("bin", "pokeldn", "vendor/LDN/ldn", "docs", "config", "gui/assets")]
        data += [(stage / "gui/guide.md", "gui"), (executable, "services/pkhex/dist")]
        data += [(stage / "LICENSE", "."), (stage / "vendor/LDN/LICENSE", "vendor/LDN")]
        data += [(path, "gui/firmware") for path in firmware]
        # scripts/build_unicorn.py's ARM-only library, not the wheel's; unicorn looks in its own lib/.
        data += [(path, "unicorn/lib") for path in (UNICORN / "lib").iterdir()]
        args = [sys.executable, "-m", "flet_cli.cli", "pack", str(ROOT / "gui" / "main.py"),
                "--name", "pokeldn", "-y",
                "--distpath", str(ROOT / "dist"), "--product-name", "pokeldn",
                "--product-version", __version__, "--file-version", f"{__version__}.0",
                "--bundle-id", APP_ID, "--add-data",
                *[f"{src}{os.pathsep}{dest}" for src, dest in data]]
        if sys.platform == "win32":
            args += ["--icon", str(icon)]
        scripts = sorted(p.stem for p in (stage / "bin").glob("*.py"))
        console = ["--console", "--hide-console=hide-early"] if sys.platform == "win32" else []
        # Keep the existing one-folder layout for Windows/Linux updates.
        onedir = ["--onedir"]
        for option in (f"--paths={dependencies}", f"--paths={ROOT}", f"--paths={ROOT / 'bin'}", f"--paths={ROOT / 'vendor' / 'LDN'}",
                       *console, *onedir,
                       *[f"--hidden-import={s}" for s in scripts],
                       *[f"--collect-submodules={m}" for m in plugin_stdlib()],
                       *[f"--collect-all={m}" for m in PLUGIN_PACKAGES],
                       *[f"--exclude-module={m}" for m in platform_excludes()], "--collect-all=esptool", "--collect-submodules=unicorn",
                       "--collect-all=esp_pylib", "--collect-submodules=pokeldn", "--collect-submodules=bleak",
                       "--collect-submodules=ldn"):
            args.append(f"--pyinstaller-build-args={option}")
        env = dict(os.environ, FLET_VIEW_PATH=str(client))
        result = subprocess.run(args, cwd=stage, env=env).returncode
        expected = ROOT / "dist" / "pokeldn"
        if result == 0 and not expected.exists():
            raise SystemExit("The packer produced no desktop application.")
        if result == 0 and sys.platform == "win32":
            clear_cfg(expected / "pokeldn.exe")
        if result == 0 and sys.platform.startswith("linux"):
            (ROOT / "dist" / f"{APP_ID}.desktop").unlink(missing_ok=True)
        return result


if __name__ == "__main__":
    sys.exit(main())
