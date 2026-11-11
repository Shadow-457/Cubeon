# Windows smoke test

The Windows build runs installer transaction fixtures before publishing: custom
paths, upgrades, file locks, rollback, recovery and uninstall. These fixtures use
small program payloads and do not run the complete frozen launcher or certify
hardware rendering. Complete this pass on a real Windows machine or VM before
claiming the full desktop experience works.

Do it once, on a clean-ish machine or VM, the way a new person would.

---

## 0. Get the file the way a member will

1. On the Windows box open **https://www.ylet.online/download** and verify
   that the public GitHub release assets are accessible without signing in.
2. Click **Download for Windows**. Expect `Cubeon-Windows-x64-Setup.exe` at the
   size the page shows. ☐
3. Run it. Windows will show **"Windows protected your PC"** - that is expected
   and already documented on the site (download step 1). Choose **More info ->
   Run anyway**. ☐
   - If the wording or the steps differ from that, note it: this is the first
     thing every member will hit, and the site text is what they will follow.

## 1. Install + first launch (the fragile part)

4. The installer should finish without asking for administrator rights and
   without a reboot. ☐
   - Repeat over an existing install after closing Cubeon, including a custom
     folder on another writable drive. Temporary file locks should retry.
     If setup fails, its message must name the failed step/path and Windows
     error; keep `Cubeon-Setup.log` in the installation folder. Rollback must
     restore the old program, or retain its files in the named recovery folder.
     A generic warning does not prove a disk-space problem. ☐
5. Launch Cubeon. Expect a normal window with the Cubeon UI. ☐
   - **Watch closely here.** The window does a hidden start and is revealed
     later (see the [startup architecture](../architecture/overview.md)); if it flashes and disappears, or
     stays invisible, or shows a black rectangle, that is the bug to report.
6. The first-run dialog asks for your in-game name. Type one, confirm. The
   window must stay alive and usable. ☐
7. Version check: right-click the installed `Cubeon.exe` -> **Properties ->
   Details**. "File version" should match the version on the site. Windows'
   **Apps & features** should also list Cubeon with that version. ☐

## 2. The paths people actually use

8. **Play tab**: install a Minecraft version, let it finish, press
   **Start playing**, and get into a world. ☐
   - First run downloads Java and the game files - let it do that (it is the
     slow part, and the thing most likely to fail on someone else's machine).
9. **Mods tab**: browse Modrinth, install one mod, toggle it off and on again,
   and confirm the game still launches. ☐
   - Confirm Mods, Modpacks, Resource Packs and Shaders share one content area.
     Switch each selector without changing the selected instance; check compact
     tiles, artwork, Installed badges and usable controls at 980 and 1280 px widths.
10. **Settings**: change something obvious, close Cubeon completely, reopen it,
    and confirm the setting stuck. ☐

## 3. Launcher upgrades

11. Open an installed older build online. Confirm a newer stable GitHub release
    downloads and verifies before closing; the silent setup starts only after
    Cubeon exits. Reopen Cubeon and verify the new version and retained settings/worlds.
    Repeat offline and while Minecraft/server/content work is active: the app
    stays usable and installation is deferred. ☐
12. Run a manual newer Windows setup for the existing installation. Verify the
    version in Windows Apps & features and confirm settings/worlds remain.
    Repeat in a custom installation folder and with a Windows username
    containing non-ASCII characters. ☐
    - Cancelled or failed setup must leave the current installation usable.
      Keep `Cubeon-Setup.log` beside the installed executable on failure.

## 4. Optional - the custom window frame (default ON)

13. Settings -> turn on **Custom window frame**, restart Cubeon. Expect ONE
    header instead of two: your own top bar, custom minimise/maximise/close,
    dragging by the top bar, double-click to maximise, edges to resize. ☐
    - This defaults on; a saved choice to switch it off is preserved. If it
      fails on real Windows, switch it off and record what happened.
    - Try maximise -> restore -> minimise -> close, and confirm the window
      really closes rather than leaving a process behind.

## 5. If anything goes wrong

The app writes a rotating log here:

```
%USERPROFILE%\.cubeon_launcher\cubeon.log
```

Send me: **what you did, what you expected, what actually happened**, plus the
last ~50 lines of that log. If it is a visual thing, a screenshot of the window
is worth more than a description.

Even if every box ticks, tell me which steps you skipped - "all good" on step 9
when you did not reach step 9 is worse than telling me you stopped at 8.
