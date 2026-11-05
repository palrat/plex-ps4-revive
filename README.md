# Plex PS4 Revive

**Make the Plex app from the PS4 Homebrew Store work again.**

On a jailbroken PS4, the Plex app from the Homebrew Store (version 2.03, the
"No PSN" version) opens and then only shows:

> Sorry, there appears to be a problem connecting. Please try again later.

The app is fine. It only opens an old web address that Plex has switched off. This
tool changes that one address to the current one and builds a new package for you.
After that, Plex works again: sign in, choose your server, play.

You run **one file**. It works on Windows, macOS and Linux.

---

## What you need

- A jailbroken PS4 with **GoldHEN**
- A computer with **Python 3.8 or newer**
  ([python.org/downloads](https://www.python.org/downloads/))
- A **USB stick** (FAT32 or exFAT)
- The Plex package from the Homebrew Store (see step 2)
- About 500 MB of free disk space and an internet connection

You do **not** need any other tools, and you do not need a PSN account.

---

## Step 1 — Download this tool

On this page, click the green **Code** button, then **Download ZIP**. Unzip the
file. You now have a folder called `plex-ps4-revive-main`.

## Step 2 — Download the Plex package

Get **Plex**, version **2.03**, from the **Homebrew Store** (PKG-Zone), title ID
`CUSA01850`. Download it on your computer, not on the PS4. The file is called
`PS4_CUSA01850_v2.03.pkg` and is about 66 MB.

Put this file into the `plex-ps4-revive-main` folder.

## Step 3 — Run the tool

**Windows:** double-click `revive-windows.bat`.
If Windows warns you about the file, click *More info* → *Run anyway*.

**macOS / Linux:** open a terminal in the folder and type:

```
python3 revive.py
```

The tool now works for about a minute. The first time, it also downloads one
helper program. At the end it says:

```
Done! Your new package:
    .../plex-ps4-revive-main/output/Plex-revived-v03.05.pkg
```

If it says **STOPPED** instead, read the message — it tells you what to do. The tool
checks every step and stops rather than build a broken package.

## Step 4 — Install it on the PS4

1. **Delete the old Plex app** if it is installed: on the home screen, select Plex,
   press **OPTIONS**, choose **Delete**.
2. Copy `Plex-revived-v03.05.pkg` from the `output` folder to your USB stick.
   Put it directly on the stick, **not in a folder**.
3. Plug the stick into the PS4. Make sure GoldHEN is running.
4. Go to **Settings → Debug Settings → Game → Package Installer**, select the
   package and install it.

## Step 5 — Start Plex

Start Plex and sign in. It shows a code; enter it on
[plex.tv/link](https://plex.tv/link) on your phone or computer. Choose your server
and play.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| Still "problem connecting" | The old app is still installed. Delete Plex completely, then install the new package again. |
| Black screen after the start | Run the tool again with the untouched Plex 2.03 package from step 2. |
| "The data is corrupted" (`CE-33194-0`) | You installed a package that was not made by this tool. Use the one from the `output` folder. |
| The PS4 downloads a Plex update | Delete the update: *Notifications → Downloads*. With this package the PS4 should not offer it again. |
| Plex plays only in low quality, the server shows the PS4 as "indirect" | The PS4 cannot reach your server directly. This happens when your PS4 uses a DNS server that blocks Sony's update servers and does not know your server's address. Add a normal DNS server (for example `1.1.1.1`) as the **secondary DNS** in the PS4's network settings. |
| Windows: "Python is not installed" | Install Python from [python.org](https://www.python.org/downloads/), then start `revive-windows.bat` again. |
| macOS: download fails with a certificate error | Open *Applications → Python 3.x* and run **Install Certificates.command**, then try again. |
| "No Plex package found" | The `.pkg` file from step 2 must be in the same folder as `revive.py`. |

When you ask for help, please include the full text the tool printed.

---

## Questions

**Is a finished package available for download?**
No. This project does not share app files. You download Plex yourself, and the tool
changes your copy.

**What exactly does the tool change?**
Three settings inside the app: the start address (now
`https://app.plex.tv/tv-ps4-316/`, the current Plex client for PS4), the screen
resolution of the app (1080 instead of 720, so text is sharp) and PSN (switched
off, because a jailbroken console should not use it). It also raises the version
number to 03.05 so the PS4 does not try to install Sony's old Plex update (3.00)
over it. Nothing else is changed — every other file is checked to be identical.

**Which firmware?** Tested on firmware 12.02 with GoldHEN. The Homebrew Store lists
Plex 2.03 for firmware 7.50 and newer.

**Which computers were tested?** Linux. The Windows part was tested with the same
Windows program under Wine. macOS is not tested yet — please report if it works.

**What if it breaks again?** Then Plex has probably moved its PS4 client to a new
address. Run the tool with the new address, for example:

```
python3 revive.py --url https://app.plex.tv/tv-ps4-317/
```

**Is my Plex login safe?** Yes. The app loads the official Plex client from
`app.plex.tv` over HTTPS, the same as before. The tool changes only which address
it opens.

**Optional: block Sony's update servers on the console itself.**
[nanoDNS](https://github.com/drakmor/nanoDNS) runs on the PS4 as a GoldHEN payload
and blocks Sony's update servers, while all other addresses — including your Plex
server — work normally.

---

## For the curious

How the app and the settings file work, what the tool checks, and a bug in the
common PKG tool that this project works around: see [TECHNICAL.md](TECHNICAL.md).

## Credits and license

- [LibOrbisPkg](https://github.com/maxton/LibOrbisPkg) by maxton — unpacks and
  builds the package (LGPL-3.0; a fixed build is included, see
  [third_party/LibOrbisPkg](third_party/LibOrbisPkg/))
- HK31 — the "No PSN" Plex package in the Homebrew Store

This project's own code is MIT licensed (see `LICENSE`). Not affiliated with Plex,
Sony or PKG-Zone.
