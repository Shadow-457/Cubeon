# Windows smoke test

CI proves the Windows **installer builds**. It has never run the real Windows
app: the `Startup tests (Windows)` job fails in the test harness itself (those
tests ban every socket and read the event loop's internals, which a Windows
`ProactorEventLoop` does not have), so a green run there would not mean much
anyway. That makes this 5-minute pass on a real Windows machine the only thing
standing between "it builds" and "it works for other people".

Do it once, on a clean-ish machine or VM, the way a new person would.

---

## 0. Get the file the way a member will

1. On the Windows box open **https://www.ylet.online/download** - the site,
   not a GitHub link. (The repo is private, so release pages are an auth wall
   for anyone but us.)
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
5. Launch Cubeon. Expect a normal window with the Cubeon UI. ☐
   - **Watch closely here.** The window does a hidden start and is revealed
     later (see `agents/docs/module-map.md`); if it flashes and disappears, or
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
10. **Settings**: change something obvious, close Cubeon completely, reopen it,
    and confirm the setting stuck. ☐

## 3. Automatic launcher updates

11. Install an older version, then reopen it while a **newer release exists
    in its selected update channel**. Expect the Skip / Update prompt. Skip
    should download nothing. Settings → System → **Check for updates** can
    retry after an offline startup or a skip. ☐
12. Close Minecraft and stop installs or hosted servers, then click **Update**
    once. Expect download progress and checksum verification, followed by an
    automatic close, installation and reopen. No browser or second Restart
    click should be needed. Verify the new version in Windows Apps & features
    and confirm settings/worlds remain. Repeat in a custom installation folder
    and with a Windows username containing non-ASCII characters. ☐
    - Cancel must leave the current installation usable. If a game starts
      during download, the verified update should wait for it to finish.
    - On a failed install, reopen Cubeon and expect a failure message. Keep
      `updates/download-*/install.log` under the launcher data folder.

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
