#!/usr/bin/env python3
"""plex-ps4-revive - make the Plex 2.03 "No PSN" package for jailbroken PS4s work again.

Put the Plex package (PS4_CUSA01850_v2.03.pkg) next to this file and run it:

    Windows:        double-click  revive-windows.bat
    macOS / Linux:  python3 revive.py

It downloads the one helper tool it needs (PkgTool from LibOrbisPkg), unpacks the
package, rewrites the app's start-page setting and builds a new package in the
"output" folder. Nothing else has to be installed except Python 3.8 or newer.

Advanced options: python3 revive.py --help
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE / "tools"
WORK = HERE / "work"
OUTPUT = HERE / "output"

TITLE_ID = "CUSA01850"
CONTENT_ID = "UP4544-CUSA01850_00-PLEX000000000000"
NEW_VERSION = "03.05"          # must be higher than Sony's last retail patch (03.00)
DEFAULT_URL = "https://app.plex.tv/tv-ps4-316/"
OUT_NAME = "Plex-revived-v{ver}.pkg"
PASSCODE = "0" * 32

# The one input file this was built and tested with. Other copies are accepted,
# but they have to pass every check below.
KNOWN_INPUTS = {
    "b5bef3b9eb18e1ae75e739c77d2ee04fc3171b9874449ef59b1f2e51d26968b7":
        "Plex 2.03 from the Homebrew Store (PS4_CUSA01850_v2.03.pkg)",
}

# Fingerprint of the unpacked app files of that package (path + SHA-256 of every
# file). If unpacking does not reproduce it exactly, the tool is broken - stop.
KNOWN_PAYLOAD = {
    "b5bef3b9eb18e1ae75e739c77d2ee04fc3171b9874449ef59b1f2e51d26968b7":
        "d1a53664917faa75e4c0f4bc574daf587449a815511ccdfa8cc92d77598f8615",
}

# PkgTool from LibOrbisPkg v0.2.231 (the same build the OpenOrbis toolchain ships).
# Windows: the original .NET Framework build, downloaded once (.NET Framework is part
#   of Windows 10/11).
# macOS/Linux: the .NET Core build cannot be used as released - on .NET 6 and newer
#   it silently corrupts files while unpacking (it expects Stream.Read to always fill
#   the buffer). A fixed build ships in third_party/LibOrbisPkg; it is run by an
#   installed `dotnet` or by an official .NET runtime downloaded into ./tools.
_LOP = "https://github.com/maxton/LibOrbisPkg/releases/download/v0.2/"
PKGTOOL_WIN = ("PkgTool-0.2.231.zip",
               "c639e591e35c2431f68410d1771541d95f7308863638f9e3a6eedf1818530097", "PkgTool.exe")
PKGTOOL_CORE = HERE / "third_party" / "LibOrbisPkg" / "bin" / "PkgTool.Core.dll"
DOTNET_VERSION = "10.0.14"
DOTNET_URL = ("https://builds.dotnet.microsoft.com/dotnet/Runtime/{v}/"
              "dotnet-runtime-{v}-{rid}.tar.gz")
DOTNET_SHA512 = {
    "linux-x64": "634326028645f38731c8c4e71a68356e4ca0d6b6607139a234ab760687f742063edaf33a1f20dda615742d2dc8300ca2ff857619d51fbb38090383b71334af89",
    "linux-arm64": "99e1d6eb5d3de935853404fd378c77cbf813bd3ae094837b5a589000a492c289bf0d01d8a6bff99b4470572d9f85dc0b41239b5b7801e031197b83d527cdfeb2",
    "osx-x64": "b13d453e60f3d718743ada5710d0174524cbf16dead74aa62af6cc258bc5f7310e8ec991fa9365f84bf78bb198417ddceb1381acf557ed52ab0300a21b671596",
    "osx-arm64": "19c5781dc2f87600865886b8774a4c5851caf1f5cf3f591185b922b0e51dea6b8c0ed0bf80ae4d3be2e083db662124258743e779fab6885322d641eff52b0382",
}

# PKG entries that hold the files of sce_sys/. pkg_extract does not return them,
# they are separate entries in the package. NPTITLE_DAT is left out on purpose:
# it is encrypted in Sony's package and breaks the install when repacked
# (CE-33194-0 / 0x80A4000C "the data is corrupted").
SCE_SYS_ENTRIES = {
    "PARAM_SFO": "sce_sys/param.sfo",
    "PRONUNCIATION_XML": "sce_sys/pronunciation.xml",
    "PRONUNCIATION_SIG": "sce_sys/pronunciation.sig",
    "ICON0_PNG": "sce_sys/icon0.png",
    "PIC0_PNG": "sce_sys/pic0.png",
    "PIC1_PNG": "sce_sys/pic1.png",
    "ICON0_DDS": "sce_sys/icon0.dds",
    "PIC0_DDS": "sce_sys/pic0.dds",
    "PIC1_DDS": "sce_sys/pic1.dds",
    "SHAREPARAM_JSON": "sce_sys/shareparam.json",
}


class Stop(Exception):
    """A problem the user can fix. Printed without a traceback."""


def say(msg: str = "") -> None:
    print(msg, flush=True)


def tree_digest(root: Path, skip: tuple = ()) -> dict[str, str]:
    """relative path -> SHA-256 for every file below root."""
    return {p.relative_to(root).as_posix(): sha256_file(p)
            for p in sorted(root.rglob("*")) if p.is_file()
            and p.relative_to(root).as_posix() not in skip}


def manifest(files: dict[str, str]) -> str:
    return hashlib.sha256("".join(f"{k}\t{v}\n" for k, v in files.items()).encode()).hexdigest()


def sha256_file(path: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ===================================================================== PkgTool
class PkgTool:
    def __init__(self, cmd: list[str]):
        self.cmd = cmd

    def run(self, *args: str, quiet: bool = True) -> str:
        env = dict(os.environ)
        env["DOTNET_SYSTEM_GLOBALIZATION_INVARIANT"] = "1"
        env["DOTNET_ROLL_FORWARD"] = "LatestMajor"   # PkgTool.Core targets .NET Core 3.0
        proc = subprocess.run(self.cmd + list(args), env=env, capture_output=True,
                              text=True, errors="replace")
        if proc.returncode != 0:
            raise Stop(
                f"PkgTool failed ({args[0]}, exit code {proc.returncode}).\n"
                f"{(proc.stdout + proc.stderr).strip()[-1500:]}"
            )
        if not quiet:
            say(proc.stdout)
        return proc.stdout

    def entries(self, pkg: Path) -> dict[str, int]:
        """PKG entry name -> entry index."""
        out = {}
        for line in self.run("pkg_listentries", str(pkg)).splitlines():
            m = re.match(r"\s*0x[0-9A-Fa-f]+\s+0x[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+(\d+)\s+(?:\d+\s+)?(\S+)\s*$",
                         line)
            if m:
                out[m.group(2)] = int(m.group(1))
        if not out:
            raise Stop(f"Could not read the entry list of {pkg.name}. Is it really a PS4 package?")
        return out


def download(url: str, dest: Path, digest: str, algo: str = "sha256") -> None:
    """Download once into ./tools and check the hash."""
    if dest.is_file() and sha256_file(dest, algo) == digest:
        return
    say(f"      downloading {dest.name} (one time only) ...")
    TOOLS.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "plex-ps4-revive"})
        with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as exc:   # noqa: BLE001 - any network problem
        if tmp.exists():
            tmp.unlink()
        raise Stop(
            f"Download failed: {exc}\n\n"
            f"Download this file in your browser:\n    {url}\n"
            f"put it into this folder:\n    {TOOLS}\n"
            "and run this again. (macOS: if the error mentions certificates, open your\n"
            "Python folder in Applications and run 'Install Certificates.command'.)"
        ) from None
    tmp.replace(dest)
    if sha256_file(dest, algo) != digest:
        dest.unlink()
        raise Stop(f"{dest.name} is damaged or not the expected file. Run this again.")


def unzip_tool(zip_name: str, digest: str, exe_name: str) -> Path:
    folder = TOOLS / zip_name[:-4]
    exe = folder / exe_name
    if not exe.is_file():
        archive = TOOLS / zip_name
        download(_LOP + zip_name, archive, digest)
        with zipfile.ZipFile(archive) as z:
            z.extractall(folder)
        if not exe.is_file():
            raise Stop(f"{exe_name} not found inside {zip_name}")
    return exe


def system_dotnet() -> str | None:
    exe = shutil.which("dotnet")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--list-runtimes"], capture_output=True, text=True,
                             timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if "Microsoft.NETCore.App" in out else None


def bundled_dotnet() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    os_name = "osx" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else None
    rid = f"{os_name}-{arch}"
    if rid not in DOTNET_SHA512:
        raise Stop(
            f"No ready-made .NET runtime for this computer ({sys.platform}, {machine}).\n"
            "Install the .NET runtime (8 or newer) from https://dotnet.microsoft.com/download\n"
            "and run this again."
        )
    folder = TOOLS / f"dotnet-{DOTNET_VERSION}-{rid}"
    exe = folder / "dotnet"
    if not exe.is_file():
        archive = TOOLS / f"dotnet-runtime-{DOTNET_VERSION}-{rid}.tar.gz"
        download(DOTNET_URL.format(v=DOTNET_VERSION, rid=rid), archive, DOTNET_SHA512[rid], "sha512")
        say("      unpacking the .NET runtime ...")
        tmp = folder.with_name(folder.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(tmp, filter="data")
            else:
                t.extractall(tmp)
        tmp.rename(folder)
        archive.unlink()               # 30 MB we no longer need
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(exe)


def get_pkgtool(override: str | None) -> PkgTool:
    if override:
        p = Path(override)
        if not p.is_file():
            raise Stop(f"--pkgtool: {p} does not exist")
        if p.suffix.lower() == ".dll":
            return PkgTool([system_dotnet() or bundled_dotnet(), str(p)])
        return PkgTool([str(p)])
    if sys.platform.startswith("win"):
        return PkgTool([str(unzip_tool(*PKGTOOL_WIN))])
    if not PKGTOOL_CORE.is_file():
        raise Stop(f"{PKGTOOL_CORE} is missing. Download the complete folder again.")
    return PkgTool([system_dotnet() or bundled_dotnet(), str(PKGTOOL_CORE)])


# ====================================================================== SFO
def sfo_read(data: bytes) -> dict[str, str]:
    magic, _v, key_off, data_off, count = struct.unpack_from("<4sIIII", data, 0)
    if magic != b"\0PSF":
        raise Stop("param.sfo is damaged")
    out = {}
    for i in range(count):
        koff, fmt, length, _maxlen, doff = struct.unpack_from("<HHIII", data, 20 + i * 16)
        name = data[key_off + koff:data.find(b"\0", key_off + koff)].decode("ascii", "replace")
        raw = data[data_off + doff:data_off + doff + length]
        out[name] = (raw.rstrip(b"\0").decode("utf-8", "replace") if fmt != 0x0404
                     else str(struct.unpack("<I", raw[:4])[0]))
    return out


def sfo_patch(path: Path, values: dict[str, str]) -> None:
    d = bytearray(path.read_bytes())
    _m, _v, key_off, data_off, count = struct.unpack_from("<4sIIII", d, 0)
    for i in range(count):
        koff, _fmt, _length, maxlen, doff = struct.unpack_from("<HHIII", d, 20 + i * 16)
        name = d[key_off + koff:d.find(b"\0", key_off + koff)].decode("ascii", "replace")
        if name in values:
            raw = values[name].encode("ascii") + b"\0"
            if len(raw) > maxlen:
                raise Stop(f"param.sfo: {name}={values[name]!r} is too long")
            d[data_off + doff:data_off + doff + maxlen] = raw.ljust(maxlen, b"\0")
            struct.pack_into("<I", d, 20 + i * 16 + 4, len(raw))
    path.write_bytes(d)


# =========================================================== webmaf_settings
# The file the app reads its start page from (/app0/webmaf_settings.dat):
#   [0:4] u32 BE = 8 | [4:12] IV | body XOR-ed with a 32-byte repeating keystream
#   body plaintext = u32 BE file size | INI text | 0x00 | HMAC-SHA1 (20 bytes)
#   HMAC key = 56 bytes inside eboot.bin (vaddr 0x10FC80); MAC computed with the
#   20 MAC bytes set to 0xFF. The keystream is recovered from the original file
#   (known plaintext), the key is read from the user's own eboot.bin.
PERIOD = 32
KEY_VADDR = 0x10FC80
KEY_LEN = 0x38
CRIB = b"\n; General Settings\nServiceStartUri=https\\://app.plex.tv/"
CRIB_OFF = 23


def ks_from_original(orig: bytes) -> bytes:
    body = orig[4:]
    ks: list[int | None] = [None] * PERIOD
    for i in range(8):
        ks[i] = body[i]
    for t, ch in enumerate(CRIB):
        if CRIB_OFF + t < len(body):
            ks[(CRIB_OFF + t) % PERIOD] = body[CRIB_OFF + t] ^ ch
    if None in ks or len(orig) < 200:
        raise Stop("webmaf_settings.dat is not the expected Plex file")
    return bytes(ks)  # type: ignore[arg-type]


def dat_decode(data: bytes, ks: bytes) -> bytes:
    body = data[4:]
    pt = bytes(body[i] ^ ks[i % PERIOD] for i in range(len(body)))
    return data[:12] + pt[8:]


def dat_mac(key: bytes, plain: bytes) -> bytes:
    return hmac.new(key, plain[:-20] + b"\xff" * 20, "sha1").digest()


def dat_ok(key: bytes, data: bytes, ks: bytes) -> bool:
    plain = dat_decode(data, ks)
    return hmac.compare_digest(dat_mac(key, plain), plain[-20:])


def dat_ini(data: bytes, ks: bytes) -> str:
    return dat_decode(data, ks)[16:-21].decode("latin1")


def find_hmac_key(eboot: bytes, orig: bytes, ks: bytes) -> bytes:
    offsets = []
    if eboot[:4] == b"\x4f\x15\x3d\x1d":            # fake SELF, as found in the package
        n, = struct.unpack_from("<H", eboot, 0x18)
        for i in range(n):
            _p, off, filesz, _m = struct.unpack_from("<4Q", eboot, 0x20 + i * 0x20)
            if off and filesz > KEY_VADDR:
                offsets.append(off + KEY_VADDR)
    elif eboot[:4] == b"\x7fELF":
        phoff, = struct.unpack_from("<Q", eboot, 0x20)
        phsize, phnum = struct.unpack_from("<HH", eboot, 0x36)
        for i in range(phnum):
            b = phoff + i * phsize
            if struct.unpack_from("<I", eboot, b)[0] == 1:
                p_off, p_vaddr, _pa, p_filesz = struct.unpack_from("<QQQQ", eboot, b + 8)
                if p_vaddr <= KEY_VADDR < p_vaddr + p_filesz:
                    offsets.append(p_off + KEY_VADDR - p_vaddr)
    for off in offsets:
        key = eboot[off:off + KEY_LEN]
        if len(key) == KEY_LEN and any(key):
            plain = dat_decode(orig, ks)
            if hmac.compare_digest(dat_mac(key, plain), plain[-20:]):
                return key
    raise Stop("Could not find the settings key in eboot.bin - this is not Plex 2.03.")


def ini_escape(value: str) -> str:
    return value.replace(":", "\\:")


def new_ini(orig_ini: str, url: str, ui_scale: str) -> str:
    """Change three values and keep everything else exactly as Plex shipped it."""
    changes = {
        "ServiceStartUri": ini_escape(url),
        "UIAutoScaling": ui_scale,
        "EnablePSN": "false",
    }
    lines = orig_ini.split("\n")
    for name, value in changes.items():
        hits = [i for i, l in enumerate(lines) if l.startswith(name + "=")]
        if len(hits) != 1:
            raise Stop(f"Unexpected settings file: '{name}' found {len(hits)} times")
        lines[hits[0]] = f"{name}={value}"
    return "\n".join(lines)


def dat_build(orig: bytes, key: bytes, ks: bytes, ini: str) -> bytes:
    """Encode `ini` into a file of exactly the original size.

    The new values are a few bytes longer than the old ones, so comment-only
    lines are removed from the top until the text fits; the rest is padded.
    """
    lines = ini.split("\n")
    while True:
        text = "\n".join(lines).encode("latin1")
        total = 4 + 8 + 4 + len(text) + 1 + 20
        if total <= len(orig):
            break
        idx = next((i for i, l in enumerate(lines) if l.startswith(";")), None)
        if idx is None:
            raise Stop("The new settings do not fit into the file. Use a shorter URL.")
        del lines[idx]
    need = len(orig) - total
    if need >= 1:
        text += b"\n" + b";" * (need - 1)
    total = 4 + 8 + 4 + len(text) + 1 + 20
    plain = b"\x00\x00\x00\x08" + orig[4:12] + struct.pack(">I", total) + text + b"\x00" * 21
    plain = plain[:-20] + dat_mac(key, plain)
    body = plain[12:]
    out = plain[:12] + bytes(body[i] ^ ks[(i + 8) % PERIOD] for i in range(len(body)))
    if len(out) != len(orig) or not dat_ok(key, out, ks):
        raise Stop("internal error: the new settings file does not verify")
    return out


# ====================================================================== GP4
def write_gp4(root: Path) -> Path:
    files, dirs = [], []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file():
            files.append(f'    <file targ_path="{rel}" orig_path="{rel}"/>')

    def tree(rel: str = "") -> None:
        for e in sorted((root / rel).iterdir(), key=lambda p: p.name):
            if e.is_dir():
                dirs.append(f'\t\t<dir targ_name="{e.name}">')
                tree(f"{rel}/{e.name}" if rel else e.name)
                dirs.append("\t\t</dir>")
    tree()
    gp4 = root / "Project.gp4"
    gp4.write_text(
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
        '<psproject fmt="gp4" version="1000">\n'
        "\t<volume>\n"
        "\t\t<volume_type>pkg_ps4_app</volume_type>\n"
        "\t\t<volume_id>PS4VOLUME</volume_id>\n"
        "\t\t<volume_ts>2026-01-01 00:00:00</volume_ts>\n"
        f'\t\t<package content_id="{CONTENT_ID}" passcode="{PASSCODE}" '
        'c_date="2026-01-01" storage_type="digital50" app_type="full"/>\n'
        '\t\t<chunk_info chunk_count="1" scenario_count="1">\n'
        "\t\t\t<chunks>\n"
        '\t\t\t\t<chunk id="0" layer_no="0" label="Chunk #0"/>\n'
        "\t\t\t</chunks>\n"
        '\t\t\t<scenarios default_id="0">\n'
        '\t\t\t\t<scenario id="0" type="sp" initial_chunk_count="1" label="Scenario #0">0</scenario>\n'
        "\t\t\t</scenarios>\n"
        "\t\t</chunk_info>\n"
        "\t</volume>\n"
        '\t<files img_no="0">\n' + "\n".join(files) + "\n\t</files>\n"
        "\t<rootdir>\n" + "\n".join(dirs) + "\n\t</rootdir>\n"
        "</psproject>\n",
        encoding="utf-8",
    )
    return gp4


# ===================================================================== steps
def find_input(arg: str | None) -> Path:
    if arg:
        p = Path(arg).expanduser().resolve()
        if not p.is_file():
            raise Stop(f"File not found: {p}")
        return p
    candidates = sorted(
        p for d in (HERE, HERE / "input") if d.is_dir() for p in d.glob("*.pkg")
        if not p.name.startswith("Plex-revived")
    )
    if not candidates:
        raise Stop(
            "No Plex package found.\n"
            f"Put PS4_CUSA01850_v2.03.pkg into this folder:\n    {HERE}\n"
            "and run this again."
        )
    if len(candidates) == 1:
        return candidates[0]
    known = [p for p in candidates if sha256_file(p) in KNOWN_INPUTS]
    if len(known) == 1:
        return known[0]
    raise Stop("More than one .pkg file in this folder. Leave only the Plex package here:\n    "
               + "\n    ".join(p.name for p in candidates))


def revive(args: argparse.Namespace) -> Path:
    say("Plex PS4 revive\n")

    # ---- 1. input
    src = find_input(args.pkg)
    say(f"[1/5] Checking {src.name} ...")
    with src.open("rb") as f:
        if f.read(4) != b"\x7fCNT":
            raise Stop(f"{src.name} is not a PS4 package (.pkg).")
    digest = sha256_file(src)
    if digest in KNOWN_INPUTS:
        say(f"      OK: {KNOWN_INPUTS[digest]}")
    else:
        say("      This is not the exact file this tool was tested with.\n"
            "      Continuing - the checks below stop if it does not fit.")

    tool = get_pkgtool(args.pkgtool)

    # ---- 2. unpack
    say("[2/5] Unpacking ...")
    if WORK.exists():
        shutil.rmtree(WORK)
    tree, scratch = WORK / "app", WORK / "extract"
    scratch.mkdir(parents=True)
    tool.run("pkg_extract", "--passcode", PASSCODE, str(src), str(scratch))
    payload = scratch / "uroot" if (scratch / "uroot").is_dir() else scratch
    payload.rename(tree)
    if digest in KNOWN_PAYLOAD and manifest(tree_digest(tree)) != KNOWN_PAYLOAD[digest]:
        raise Stop("Unpacking produced damaged files. Your PkgTool or .NET runtime is not "
                   "working correctly.\nDelete the 'tools' folder and run this again.")
    entries = tool.entries(src)
    for name, rel in SCE_SYS_ENTRIES.items():
        if name in entries:
            dest = tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            tool.run("pkg_extractentry", "--passcode", PASSCODE, str(src),
                     str(entries[name]), str(dest))
    sfo_path = tree / "sce_sys" / "param.sfo"
    if not sfo_path.is_file():
        raise Stop("The package has no param.sfo - it is not a normal app package.")
    sfo = sfo_read(sfo_path.read_bytes())
    if sfo.get("TITLE_ID") != TITLE_ID:
        raise Stop(f"This package is '{sfo.get('TITLE', '?')}' ({sfo.get('TITLE_ID')}), "
                   f"not Plex ({TITLE_ID}).")
    eboot_path, dat_path = tree / "eboot.bin", tree / "webmaf_settings.dat"
    if not eboot_path.is_file() or not dat_path.is_file():
        raise Stop("eboot.bin or webmaf_settings.dat missing - this is not Plex 2.03.")
    eboot = eboot_path.read_bytes()
    if eboot[:4] != b"\x4f\x15\x3d\x1d":
        raise Stop("eboot.bin is not in the format a jailbroken PS4 can start. "
                   "Use the package from the Homebrew Store, not files copied off a console.")
    nfiles = sum(1 for p in tree.rglob("*") if p.is_file())
    say(f"      Plex {sfo.get('APP_VER', '?')}, {nfiles} files")

    # ---- 3. settings
    say("[3/5] Writing the new start page ...")
    orig = dat_path.read_bytes()
    try:
        ks = ks_from_original(orig)
        key = find_hmac_key(eboot, orig, ks)
    except Stop:
        raise Stop("The settings file in this package is not the original one.\n"
                   "Was this package already revived? Use the untouched Plex 2.03 package.") from None
    new = dat_build(orig, key, ks, new_ini(dat_ini(orig, ks), args.url, args.ui_scale))
    dat_path.write_bytes(new)
    say(f"      start page: {args.url}  (checked: OK)")

    # ---- 4. build
    say("[4/5] Building the new package (takes a minute) ...")
    sfo_patch(sfo_path, {"TITLE": "Plex", "TITLE_ID": TITLE_ID, "CONTENT_ID": CONTENT_ID,
                         "APP_VER": args.app_ver, "VERSION": args.app_ver})
    source = tree_digest(tree)          # what must come back out of the new package
    gp4 = write_gp4(tree)
    built_dir = WORK / "built"
    built_dir.mkdir()
    tool.run("pkg_build", str(gp4), str(built_dir))
    built = sorted(built_dir.glob("*.pkg"))
    if not built or built[0].stat().st_size < 10_000_000:
        raise Stop("PkgTool did not produce a package.")

    # ---- 5. verify the result, not the intention
    say("[5/5] Checking the new package ...")
    pkg = built[0]
    out_entries = tool.entries(pkg)
    if "NPTITLE_DAT" in out_entries or "PARAM_SFO" not in out_entries:
        raise Stop("The new package has the wrong entries.")
    check_sfo = WORK / "check.sfo"
    tool.run("pkg_extractentry", "--passcode", PASSCODE, str(pkg),
             str(out_entries["PARAM_SFO"]), str(check_sfo))
    s = sfo_read(check_sfo.read_bytes())
    if (s.get("TITLE_ID"), s.get("APP_VER"), s.get("VERSION")) != (TITLE_ID, args.app_ver, args.app_ver):
        raise Stop("The new package has wrong version data.")
    check_dir = WORK / "check"
    check_dir.mkdir()
    tool.run("pkg_extract", "--passcode", PASSCODE, str(pkg), str(check_dir))
    packed_root = check_dir / "uroot" if (check_dir / "uroot").is_dir() else check_dir
    packed = tree_digest(packed_root)
    wanted = {k: v for k, v in source.items() if k in packed or not k.startswith("sce_sys/")}
    if packed.get("webmaf_settings.dat") != hashlib.sha256(new).hexdigest():
        raise Stop("The settings file inside the new package is not the new one.")
    if packed != wanted:
        bad = sorted(set(packed) ^ set(wanted) | {k for k in packed if packed[k] != wanted.get(k)})
        raise Stop("The new package does not contain exactly the unpacked files: "
                   + ", ".join(bad[:5]))

    OUTPUT.mkdir(exist_ok=True)
    final = OUTPUT / OUT_NAME.format(ver=args.app_ver)
    if final.exists():
        final.unlink()
    shutil.move(str(pkg), str(final))
    if not args.keep_work:
        shutil.rmtree(WORK, ignore_errors=True)
    say(f"      OK: version {args.app_ver}, new start page inside, {final.stat().st_size:,} bytes")
    return final


def print_settings(args: argparse.Namespace) -> None:
    """Show the settings of a package (secrets masked)."""
    src = find_input(args.pkg)
    tool = get_pkgtool(args.pkgtool)
    with tempfile.TemporaryDirectory() as tmp:
        tool.run("pkg_extract", "--passcode", PASSCODE, str(src), tmp)
        dat = next(Path(tmp).rglob("webmaf_settings.dat"), None)
        if dat is None:
            raise Stop("no webmaf_settings.dat in this package")
        data = dat.read_bytes()
        try:
            text = dat_ini(data, ks_from_original(data))
        except Stop:
            raise Stop("This package was already modified; show the original package instead.") from None
    say(re.sub(r"^(NPTitleSecret|SettingPassphrase)=.*$", r"\1=<hidden>", text.rstrip(";\n"),
               flags=re.M))


def main() -> int:
    ap = argparse.ArgumentParser(description="Make the Plex 2.03 PS4 package work again.")
    ap.add_argument("pkg", nargs="?", help="the Plex 2.03 .pkg (default: the .pkg in this folder)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"start page (default: {DEFAULT_URL})")
    ap.add_argument("--ui-scale", default="1080", choices=["1080", "720", "none"],
                    help="resolution of the app's surface (default: 1080)")
    ap.add_argument("--app-ver", default=NEW_VERSION,
                    help=f"version written into the package, NN.NN, above 03.00 (default: {NEW_VERSION})")
    ap.add_argument("--pkgtool", help="use this PkgTool (.exe, binary or .dll) instead of downloading one")
    ap.add_argument("--keep-work", action="store_true", help="keep the unpacked files in ./work")
    ap.add_argument("--print-settings", action="store_true",
                    help="only show the settings inside the given package")
    args = ap.parse_args()
    if not re.fullmatch(r"\d\d\.\d\d", args.app_ver) or args.app_ver <= "03.00":
        ap.error("--app-ver must look like 03.05 and be higher than 03.00")
    if not args.url.startswith(("https://", "http://")):
        ap.error("--url must start with https://")

    try:
        if args.print_settings:
            print_settings(args)
            return 0
        final = revive(args)
    except Stop as exc:
        say(f"\nSTOPPED: {exc}")
        return 1
    except KeyboardInterrupt:
        say("\ncancelled")
        return 1

    say("\nDone! Your new package:")
    say(f"    {final}")
    say("\nNext: copy it to a USB stick and install it - see README, step 4.")
    return 0


if __name__ == "__main__":
    rc = main()
    # A double-clicked window on Windows would close before anyone can read it.
    if sys.platform.startswith("win") and not os.environ.get("PROMPT") \
            and not os.environ.get("PLEX_REVIVE_NO_PAUSE"):
        input("\nPress Enter to close this window.")
    sys.exit(rc)
