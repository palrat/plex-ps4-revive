# Technical notes

## Why the app fails

Plex 2.03 for PS4 (`CUSA01850`) contains no Plex code. `eboot.bin` is Sony's
**WebMAF** runtime, a browser shell. It reads its start page from
`/app0/webmaf_settings.dat`. In 2.03 that page is
`https://app.plex.tv/tv-ps4-281`, which now returns 404. The message *"there
appears to be a problem connecting"* is WebMAF's own error page (it is stored in
the eboot in eight languages), not a Plex error. The current PS4 client is served
at `https://app.plex.tv/tv-ps4-316/`.

Of the settings paths compiled into the runtime, only `/app0/webmaf_settings.dat`
is read by this app. A plain `webmaf_settings.ini` in the package is ignored, so the
`.dat` has to be rewritten.

## The settings file

```
[0:4]    u32 BE = 8          IV length
[4:12]   IV (8 bytes)
[12:]    body, XOR with a 32-byte repeating keystream

body plaintext:  u32 BE file size | INI text | 0x00 | HMAC-SHA1 (20 bytes)
HMAC key:        56 bytes in eboot.bin at vaddr 0x10FC80
HMAC input:      the whole plaintext with the 20 MAC bytes set to 0xFF
```

The keystream is recovered from the original file with a few known plaintext bytes
(`"\n; General Settings\nServiceStartUri=https\://app.plex.tv/"` at body offset
23). The key is read from the user's own `eboot.bin` and accepted only if it
verifies the original file. No key material is stored in this repository.

`revive.py` decodes the original INI, changes three values and keeps everything
else:

| Key | 2.03 | new |
|---|---|---|
| `ServiceStartUri` | `https\://app.plex.tv/tv-ps4-281` | `https\://app.plex.tv/tv-ps4-316/` |
| `UIAutoScaling` | `720` | `1080` (allowed: `none`, `720`, `1080`) |
| `EnablePSN` | `true` | `false` |

The new file keeps the original size (1228 bytes). Comment lines are removed from
the top to make room and the rest is padded with `;`. For the Homebrew Store
package, the result is byte-identical to the file that was tested on hardware.

## The package

- `sce_sys/nptitle.dat` is **not** repacked. It is stored encrypted in the original
  package; written back as plaintext the console refuses to start the app
  (`CE-33194-0` / `0x80A4000C`, klog: `invalid nptitle_dat`).
- `APP_VER` **and** `VERSION` in `param.sfo` are set to `03.05`. The console's patch
  checker reads `VERSION`. If it stays below Sony's last retail patch (3.00), the
  console adds that patch to the install task and the install fails
  (`0x80F00640` / `0x80F00633`).
- `pkg_extract` does not return the files of `sce_sys/` (`param.sfo`, icons, …);
  they are separate PKG entries and are extracted one by one.
- `eboot.bin` inside the package is already a fake SELF and is used as it is.
  Files copied off a running console are unwrapped ELFs and would need re-wrapping,
  which is why the tool only accepts the package.

## Checks

1. Input SHA-256. The tested input is
   `b5bef3b9eb18e1ae75e739c77d2ee04fc3171b9874449ef59b1f2e51d26968b7`
   (`PS4_CUSA01850_v2.03.pkg`, 68,681,728 bytes). Other inputs are allowed but
   must pass every following check.
2. For the known input: a fingerprint of all 577 unpacked files (path + SHA-256)
   must match. This catches a broken unpacker (see below).
3. `TITLE_ID` is `CUSA01850`, `eboot.bin` is a fake SELF, the original settings
   file verifies with the key from the eboot.
4. The new settings file verifies before it is written.
5. The built package is unpacked again: no `NPTITLE_DAT` entry, `param.sfo` has the
   new versions, and **every file** matches the tree that was packed.

## The LibOrbisPkg bug on .NET 6 and newer

`PkgTool.Core` (LibOrbisPkg v0.2.231, also shipped in the OpenOrbis toolchain)
targets .NET Core 3.0 and is usually run with `DOTNET_ROLL_FORWARD` on a current
runtime. On .NET 6+ it **silently corrupts files while unpacking**.

Cause: `PFSCReader.ReadSector` decompresses each 64 KiB block with a single
`DeflateStream.Read(output, 0, BlockSz)`. Up to .NET 5 that call filled the buffer;
since .NET 6 it may return fewer bytes
([breaking change](https://learn.microsoft.com/dotnet/core/compatibility/core-libraries/6.0/partial-byte-reads-in-streams)).
The rest of the reused buffer keeps data from the previous block. No error is
raised.

Seen on the Plex package with .NET 8 and .NET 10: 14 of 577 files damaged (fonts,
`icudt53l.dat`, sounds, the splash image, WebKit inspector files); same size, same
header, wrong bytes after the first partial read, up to the next 64 KiB boundary.
The executables (`eboot.bin`, `*.prx`) happened to be unaffected. The font from a .NET 10 extraction is
not parseable, the one from the console sandbox and from the .NET Framework build
(`PkgTool.exe`) is.

Fix: read until the requested count is reached.
[`third_party/LibOrbisPkg/readfully.patch`](third_party/LibOrbisPkg/readfully.patch)
applies this to every `Stream.Read` whose result was ignored. Verified: the fixed
build on .NET 10 unpacks all 577 files byte-identical to `PkgTool.exe`, and a
package built with it unpacks byte-identical to its input.

If you use PkgTool.Core from the OpenOrbis toolchain on Linux or macOS with a
current .NET, your extracted files may be damaged too.
