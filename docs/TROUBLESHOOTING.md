# Troubleshooting

- [Quick answers](#quick-answers)
- [report.txt](#reporttxt)
- [Session recording](#session-recording)
- [The watchdog line](#the-watchdog-line)
- [If the game freezes](#if-the-game-freezes)
- [Reporting a problem](#reporting-a-problem)

## Quick answers

| Symptom | What to do |
|---|---|
| Delete does nothing | Load a save first (the menu needs a player). Check that `UE4SS.log` says `Mod 'E33Wardrobe' has enabled.txt, starting mod.` and that the folder isn't nested one level too deep ([INSTALL.md](INSTALL.md#1-the-in-game-menu)). If you changed the key in `config.lua`, use that key. |
| `UE4SS.log` says "This UE4SS build is too old for E33Wardrobe" | Install a newer UE4SS: the experimental build from December 2025 or later ([INSTALL.md](INSTALL.md#1-the-in-game-menu)). Older builds have no safe way to run the mod's work on the game thread, so the mod stays off. |
| The menu key also reloads Blueprint mods | You set the menu to Insert, which UE4SS's BPModLoaderMod also uses. Pick another key ([USAGE.md](USAGE.md#changing-keys-and-outfit-names)). |
| The menu says "No outfit mods relocated yet." | Run the relocator for a mod ([RELOCATOR.md](RELOCATOR.md)), then press **Reload files** in the menu. |
| I picked something and nothing changed | Read the status line under the title; it says why, for example "made for Potato bag; Lune wears Chic". Use **Wear** or **Bring to front** on that row or the line under it, or **Fix look** in the bottom row ([USAGE.md](USAGE.md#outfits-tab)). |
| Something still looks wrong after switching a slot off | Press **Fix look**, or re-equip the outfit in the game's menu. |
| Clicks don't reach the menu | Use the keyboard (Ctrl+arrows, Ctrl+Enter), or open the game's own menu first and then press Delete. As a last resort, switch on Settings > UI input mode. |
| A character falls through the floor, or cloth and hair behave oddly, with one variant | Relocate that mod again with `--physics game` ([RELOCATOR.md](RELOCATOR.md#skeletons-and-physics)). |
| The relocator skipped a variant | Its console output says why ([RELOCATOR.md](RELOCATOR.md#when-a-variant-is-refused)). |

## report.txt

`ue4ss\Mods\E33Wardrobe\report.txt` is one file with what is needed to look into a problem:

- the settings and the picks (in pick order);
- this session's and the previous session's log (see below);
- the latest dump: every character's meshes, materials, texture and scalar parameters, skeleton,
  physics and animation, then a check of each picked variant's assets: shown (and where) or absent;
- the E33Wardrobe and error lines of `UE4SS.log`, and its last 80 lines;
- the relocator's console output.

It is written at every game start while Settings > **Record session** is on (the default), so after
a freeze, start the game once. You can also write it with Settings > **Report**, **Ctrl+F9** or the
console command `wardrobe report`. With Settings > Auto report on (and recording on), it is also
rewritten 4 s after each change.

**Privacy**: user names in folder paths (`C:\Users\<user>\...`) are replaced by `<user>` in
report.txt, and so is your Windows user name elsewhere (spelled as Windows spells it, if it has 3 or
more letters). It still lists your mods and folder names; look through it
before posting it publicly.

## Session recording

While Settings > **Record session** is on, the mod writes `live_log.txt` next to itself. Each line
has a time. It records:

- every menu click and key, with the row and button it hit, and what the menu then showed;
- console commands and setting changes;
- for each pass: why it ran, and every change it made (mesh, material slot, texture parameter,
  animation class, Wear), per character and component; a pass that changed nothing says so;
- after each pass, one line per picked variant: how much of it is on screen, what isn't, and which
  other slot it overlaps;
- characters the game spawns or re-dresses, level loads, and errors.

The previous session is kept as `live_log_previous.txt`. The log stops at 20 MB.

## The watchdog line

While recording is on, a watchdog writes
`WATCHDOG: the game thread has not run for N s; mod state: …` when the mod's game-thread loop
(every 50 ms) hasn't run for 6 seconds (at most one line per 15 s):

- State `idle`: the mod wasn't doing anything when the game stopped. The stall is in the game or
  engine. During a long loading screen this is normal.
- Another state (`mod work`, `dump`, …): the game stopped while the mod was working. The log lines
  just before (`loading …`, `mesh set …`) name the call.
- **No** watchdog line during a freeze: UE4SS's background thread was stuck too, or the process
  died. Only a process dump can tell more.

## If the game freezes

Before you close the game:

1. Note the time, and whether the picture, the sound and the mouse still move.
2. Press Delete twice and wait 5 s. The mod's game-thread loop writes key presses to
   `live_log.txt`: `key DEL` lines appear only if that loop still runs. If they don't, the game
   thread is stuck.
3. Task Manager > Details > right-click `SandFall-Win64-Shipping.exe` (Game Pass:
   `SandFall-WinGDK-Shipping.exe`) > **Create dump file**. Keep
   the `.DMP` file it names: it shows where every thread is stuck.
4. Copy `ue4ss\UE4SS.log` and `Mods\E33Wardrobe\live_log.txt` **before starting the game again**:
   UE4SS overwrites its log at every start.

To make freezes less likely, use the recommended UE4SS settings in
[INSTALL.md](INSTALL.md#1-the-in-game-menu) (hot reload off, GUI closed).

## Reporting a problem

Open an issue on GitHub, or post in the Bugs tab of the Nexus Mods page, with:

- what you did and what you expected;
- your E33 Wardrobe and UE4SS versions, and Steam or Game Pass;
- the mods you relocated;
- `report.txt` (checked for personal paths first). For a freeze, also the copied `UE4SS.log`; the
  `.DMP` file only when asked (it is large and contains memory of your PC's process).
