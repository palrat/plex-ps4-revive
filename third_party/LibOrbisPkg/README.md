# LibOrbisPkg — fixed PkgTool.Core build

`bin/` contains `PkgTool.Core.dll` and `LibOrbisPkg.Core.dll`, built from
[maxton/LibOrbisPkg](https://github.com/maxton/LibOrbisPkg) tag `v0.2` (the
source of release 0.2.231) with one change: [`readfully.patch`](readfully.patch).

**Why:** the released build silently corrupts unpacked files when it runs on .NET 6
or newer, because it expects `Stream.Read` to always fill the buffer. The patch adds
a `ReadFully` helper and uses it wherever the return value of `Stream.Read` was
ignored. Details: [TECHNICAL.md](../../TECHNICAL.md#the-liborbispkg-bug-on-net-6-and-newer).

`revive.py` uses this build on macOS and Linux only. On Windows it downloads the
original `PkgTool.exe` (.NET Framework), which does not have the problem.

`PkgTool.Core.runtimeconfig.json` adds `"rollForward": "LatestMajor"` so the tool
runs on any current .NET runtime.

## Rebuild it yourself

```
git clone https://github.com/maxton/LibOrbisPkg
cd LibOrbisPkg
git checkout v0.2
git apply /path/to/readfully.patch
dotnet build -c Release PkgTool.Core/PkgTool.Core.csproj -o out \
    -p:Deterministic=true -p:ContinuousIntegrationBuild=true -p:DebugType=none \
    "-p:PathMap=$(pwd)=/src"
```

The build is reproducible: with .NET SDK 8.0.427 it gives exactly the files in
`bin/`:

```
2061489481647c59176db5a57d5f3a40b3ce611fc1cf8a3ab4a4c5efa4b06f58  PkgTool.Core.dll
5a01e44d5ecc10e723387d5c1a014643879e3c027ce62428df73d6d882a00009  LibOrbisPkg.Core.dll
```

## License

LibOrbisPkg is licensed under the GNU LGPL v3.0 (`LICENSE.txt`, which builds on
the GNU GPL v3.0 in `COPYING.GPL-3.0.txt`). The modified
source is the upstream tag `v0.2` plus `readfully.patch`.
