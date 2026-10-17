# E33 Wardrobe app: UI <-> backend contract

The window is pywebview (Edge WebView2 on Windows). `app/ui/` is plain HTML/CSS/JS, no framework.
JS calls Python through one function:

```js
// app.js
async function call(method, ...args)   // pywebview: window.pywebview.api[method](...args)
                                       // dev/test: POST /api/<method> with JSON body [args...]
```

Every method returns JSON (dicts, lists, strings, numbers, booleans, null). Methods never raise
to JS: on failure they return `{ "ok": false, "error": "plain sentence" }`. Long work (adding,
reinstalling, removing mods) runs in a background thread; JS polls `poll()` about every 500 ms.

Paths in results are Windows paths as strings. Sizes are bytes. Times are local `"HH:MM:SS"`.
Images (swatches) are `data:image/png;base64,...` strings, small (<= 96 px). `texture_preview`
returns bigger ones (up to 2048 px). Game paths of files are package paths (`/Game/...`).

## Methods

| Method | Returns |
|---|---|
| `get_state()` | `State` |
| `set_game_folder(path)` | `{ok, error?, state: State}`. Accepts the game folder or anything inside it (Sandfall, Content, Paks, the .exe's folder); normalised to the game folder. |
| `pick_game_folder()` | Opens a folder dialog, then as `set_game_folder`. `{ok:false, error:"cancelled"}` if cancelled. |
| `detect_game()` | Searches again (Steam, Game Pass). `{ok, error?, state}` |
| `pick_files()` | File dialog (zip, 7z, rar; several). Adds them like `add_paths`. `{ok, jobs:[id]}` |
| `pick_folder()` | Folder dialog; adds that folder. `{ok, jobs:[id]}` |
| `add_paths(paths)` | Queues archives/folders. Archives of one Nexus mod dropped together become one mod. `{ok, jobs:[id]}` |
| `poll()` | `Poll` |
| `clear_jobs()` | Drops finished jobs from `Poll.jobs`. `{ok, cleared: n}` |
| `list_mods()` | `[ModSummary]` |
| `mod_details(mod_id)` | `ModDetails` or `{ok:false, error}` |
| `reinstall_mod(mod_id)` | `{ok, jobs:[id]}` |
| `remove_mod(mod_id, delete_files)` | `{ok, jobs:[id]}`. `delete_files`: also delete the mod's folder in the library. |
| `reinstall_mods(mod_ids)` | `reinstall_mod` for each (one job per mod). `{ok, jobs:[id], errors:[{id, error}]}`; `ok` false only when none was queued. |
| `remove_mods(mod_ids, delete_files)` | `remove_mod` for each. Same answer as `reinstall_mods`. |
| `texture_preview(mod_id, ref, max_px)` | A bigger picture of one texture, for the image viewer. `ref`: an `Image.ref` from `ModDetails`. `max_px` 64..2048 (default 1024): the largest mip that fits is decoded. `Preview`. Reads the option's prepared pak with retoc and decodes in Python: under a second for small textures, several seconds for 2048 px BC7, up to a minute when a 4K texture has no smaller mips. Cached in `%APPDATA%\E33Wardrobe\previews`. When the texture can't be read, the saved swatch with `source:"swatch"` and a `note` saying why, or `{ok:false, error}` without one. |
| `install_menu()` | Installs/updates the in-game menu (UE4SS mod). `{ok, error?, state}` |
| `open_path(what)` | Opens Explorer. `what`: `"game"`, `"library"`, `"mods"` (Paks\~mods\_E33Wardrobe), `"menu"` (ue4ss\Mods\E33Wardrobe), `"report"` (report.txt), `"crashes"`, or a mod id (its library folder). `{ok, error?}` |
| `open_url(name)` | `name`: `"ue4ss"` (Nexus mod 630), `"nexus"` (mod 938), `"github"`, `"guide"`. `{ok}` |
| `monitor()` | `Monitor` |
| `set_disabled(mod_id, on)` | Disable (`on` true) or enable a prepared mod: its prepared folder moves between `Paks\~mods\_E33Wardrobe` and `Content\E33Wardrobe_Disabled`, the menu leaves it out, picks are kept (`e33fixes.set_disabled`). Refused while the game runs or a task of that mod is waiting. `{ok, error?}` |
| `rows_editor(mod_id)` | The Edit rows dialog's data: `{ok, mod, rows: [EditRow], defaults: [{id, label, character, options: [{id, label}]}]}` (`defaults`: the rows without edits, for Reset all). |
| `save_rows(mod_id, model)` | `model: {rows: [{id, label, new, character, options: [{id, label, hidden}]}]}` in display order (new rows: id `<mod>/+<n>`). Stores the differences in fixes.json and rewrites variants.lua. `{ok}` |
| `texture_choices(mod_id, variant_id, material, param)` | For "Choose texture": `{ok, variant, material (as cased in the mod), param ("*" = every empty link), current: rule value or null, choices: [Image]}` (the option's textures). |
| `set_texture_rule(mod_id, variant_id, material, param, texture)` | `texture`: a texture package of that option, `"game"` (the game's own), or null (remove the rule). `{ok}` |
| `material_choices(mod_id, variant_id, mesh, slot)` | For "Choose material": `{ok, variant, mesh, slot, current, choices: [{value: "body" \| "hide" \| material path, label, sub}]}`. |
| `set_material_rule(mod_id, variant_id, mesh, slot, choice)` | `choice`: `"body"`, `"hide"`, a material package of that option, or null. `{ok}` |
| `bundle_plan(mod_id, variant_id)` | What Bundle would copy for an option's missing files: `{ok, variant, sources: [{mod, option, label, package, files: [{path, what, size}], into: ["Row · Option"]}]}`, or `{ok:false}` when no library mod has them. |
| `bundle(mod_id, from_mod, from_option, packages)` | Queues a `bundle` job: `e33fixes.make_bundle`, then a full reinstall of the mod. `{ok, jobs:[id]}` |
| `undo_fix(mod_id, ref)` / `undo_all_fixes(mod_id)` | Undo one fix (`ref` from `ModDetails.fixes`) or all but "disabled". Removing a bundle queues a job (the mod is prepared again). `{ok, jobs:[id]}` |
| `check_mods()` | `{ok, mods, options, problems: [RepairProblem]}`: prepared files of every enabled mod, the shared pak, variants.lua (lists every enabled mod, not older than the registry). |
| `repair(problem_ids)` | Repairs those problems: missing option files: a `repair` job (only those options); shared pak: a reinstall; the menu's list: written again at once. `{ok, jobs:[id], menu: bool}` |
| `reconcile()` | At app start: prepared folders on the wrong side of Disable (an enabled mod's files in the disabled folder, a disabled mod's files still in ~mods) are moved where they belong. Skipped while the game runs. `{ok, moved: [mods], errors: [sentences]}` |
| `repair_option(mod_id, variant_id)` | The Game log's Repair button: a `repair` job for one option. `{ok, jobs:[id]}` |
| `compare_mods(a, b)` | For "Two versions of one mod?": `{ok, mods: [{id, files (the downloads), version, uploaded, added, options, rows, size, state}] (2), shared: [paths]}`. Downloads are recorded from 1.3.0 on. |
| `culprit(action, value)` | Find the problem mod. `action`: `"status"`, `"start"`, `"answer"` (`value` true: it still happens), `"finish"` (`value` true: keep the found mod off), `"forget"` (turn back on what it can, then end it anyway). `Culprit`; finish / forget also give `{errors, dropped, left}`. While it runs, Remove, Disable and Enable are refused for the mods it manages. |
| `monitor_file(which, known)` | The logs of a game that has ended, read once through the same rules: `"last"` (live_log.txt + UE4SS.log), `"previous"` (live_log_previous.txt), `"ue4ss"` (UE4SS.log alone). `Monitor` plus `{which, exists, version, files:[paths], lines, menu_version, ue4ss_version}`; `tail` holds up to 5000 lines (for `"ue4ss"`, UE4SS.log's). `known`: the `version` the page has; when the files haven't changed the answer is only `{ok, unchanged: true, version, which}`. |
| `problems_text()` | Plain text of the current problems, for pasting in a bug report. |
| `get_settings()` / `save_settings(dict)` | `{library, watch_game: bool}` |
| `pick_library_folder()` | Folder dialog, then `save_settings({library})`. `{ok, error?}` |

## Shapes

```jsonc
// State
{
  "version": "1.2.0",                          // app version
  "first_run": true,                           // no settings file yet
  "game": {
    "found": true,
    "root": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Expedition 33",
    "paks": "C:\\...\\Expedition 33\\Sandfall\\Content\\Paks",
    "store": "Steam" | "Game Pass" | null,
    "source": "detected" | "saved" | "picked"
  },
  "ue4ss": {
    "installed": true,
    "version": "3.0.1-1125-g527a483b" | null,    // from UE4SS.log when available
    "ok": true,                                  // false: missing, or the log says it's too old
    "problem": null | "UE4SS is too old for the in-game menu. Get 'UE4SS - Experimental (Newer)'."
  },
  "menu": { "installed": true, "version": "1.1.0" | null, "bundled": "1.2.0", "update": false },
  "library": "C:\\...\\Sandfall\\Content\\Paks_ModLibrary",
  "game_running": false,
  "tools": { "retoc": true, "formats": ["zip", "7z", "rar"] }
}

// ModSummary
{
  "id": "Lune Outfit Options",                 // = folder name in the library = name in the wardrobe
  "name": "Lune Outfit Options",
  "state": "ready" | "not_installed" | "working" | "failed" | "disabled",
  "characters": ["Lune"],
  "replaces": ["Expedition", "Civilian Skirt", "Swim A", "Clea", "Sirene"],   // outfit names
  "options": 26, "rows": 5,
  "size": 64802523,
  "swatches": ["data:image/png;base64,..."],   // up to 4
  "notes": 1,                                  // count of notes in ModDetails
  "note_level": "warn" | "info" | null,        // the most serious of them
  "skin": true                                 // brings its own body textures
}

// ModDetails
{
  "id": "...", "name": "...", "characters": [...], "replaces": [...], "options": 26, "size": 64802523,
  "folder": "C:\\...\\Paks_ModLibrary\\Lune Outfit Options",
  "state": "ready",
  "rows": [                                    // one per menu row (slot)
    { "id": "Lune Outfit Options/843 Clea", "label": "Clea", "character": "Lune",
      "options": [
        { "label": "Shorter Skirt",
          "changes": "Outfit mesh, 2 materials",      // short summary
          "textures": "Body 4K, outfit 2K" | "Outfit (size ?)" | "",   // by kind, largest size
          "tags": ["physics", "own shaders"],
          "swatch": "data:..." | null,
          "ok": true, "error": null | "why it was skipped",
          "notes": ["plain sentence", ...],          // unresolved links name the missing files when they can be read
          "id": "Lune Outfit Options/843 Clea/843_Clea - Shorter Skirt",   // variant id
          "files": [ { "path": "/Game/.../SK_Lune_Clea_Skin", "type": "Outfit mesh", "game": true } ],
                                                     // type: Outfit mesh, Body mesh, Mesh, Material, Body texture,
                                                     // Texture, Blueprint, Physics, Skeleton, Asset label,
                                                     // else the class name or "File"; game: it replaces a game file
          "images": [Image],                         // every texture; the ones with a swatch first
          "missing": [ { "in": "/Game/.../BP_X", "name": "BP_X", "links": 1, "texture": false,
                         "names": ["/Game/.../MI_Gone"],
                         "found_in": [ { "mod": "Other Mod", "option": "Other Mod/Row/Opt", "label": "Opt",
                                         "package": "/Game/.../MI_Gone" } ] } ],
                                                     // links to files that are in neither the game nor the mod;
                                                     // names: [] when they couldn't be read (see library.missing_names);
                                                     // found_in: another library mod has it (Bundle)
          "rules": [ { "kind": "texture" | "material", "key": "<material>|<param>" | "<mesh>|<slot>",
                       "value": "<path>" | "game" | "body" | "hide" } ] } ] } ],
  "skin": { "has": true, "text": "Brings its own body textures (4K) for Lune. They show only with this mod's outfits.",
            "swatches": ["data:..."], "images": [Image] },
  "overlaps": [ { "mod": "Other Mod", "text": "Both change Lune's body textures: T_Lune_Body_D. In game, the one picked last shows.",
                  "files": ["/Game/.../T_Lune_Body_D"] } ],      // the game files both replace
  "notes": [ { "level": "warn" | "info", "text": "plain sentence naming the options or files",
               "items": ["Clea · Shorter Skirt (MI_X: 1 link)", ...],    // optional: the full list
               "what": "options" | "files",
               "compare": "Other Mod" } ],               // optional: "Two versions of one mod?" (Compare...)
  "disabled": false,
  "fixes": [ { "kind": "Texture rule" | "Material rule" | "Bundled" | "Menu rows", "text": "...", "sub": "...",
               "ref": { "kind": "texture" | "material" | "bundle" | "rows", ... } } ]   // for undo_fix
}
// Rows are shown as the in-game menu shows them after Edit rows: renamed items carry "was" (the
// label before), moved options "moved_from", hidden options "hidden": true, new rows "new": true.
// Shared new files of two mods leave out PrimaryAssetLabels (cook metadata) and bundled files.

// EditRow (rows_editor)
{ "id": "<slot id>" | "<mod>/+<n>", "label": "Herald coat", "default": "Potato bag" | null, "character": "Lune" | null,
  "new": false, "options": [ { "id": "<variant id>", "label": "...", "default": "...", "hidden": false,
                                "home": "<the row id it is in without edits>" } ] }

// RepairProblem (check_mods)
{ "id": "out|<variant id>" | "shared|<mod>" | "menu|<mod>" | "menu|stale" | "menu|missing",
  "level": "error" | "warn", "mod": "..." | null, "variant": "..." | null, "where": "Mod · option",
  "problem": "Prepared file missing", "detail": "plain sentence", "repair": "Prepare this option again",
  "action": { "kind": "options", "mod", "rels": [...] } | { "kind": "mod", "mod" } | { "kind": "menu" }
            | { "kind": "move_back" | "move_out", "mod" } | null }
// "parked|<mod>": an enabled mod's prepared folder is in the disabled folder (move_back);
// "loaded|<mod>": a disabled mod's folder is still in ~mods (move_out). repair() also returns {moved, errors}.

// Culprit (culprit)
{ "ok": true, "active": true, "round": 2, "rounds_about": 3, "on": [...], "off": [...], "cleared": [...],
  "before": [...],                                     // already disabled when it started: left alone
  "found": null | "Mod", "started": "YYYY-MM-DD HH:MM",
  "history": [ { "round": 1, "on": [...], "off": [...], "answer": "still" | "gone" } ] }
// Kept in %APPDATA%\E33Wardrobe\culprit.json until it is finished. Cleared mods stay on.

// Image (a texture of an option)
{ "ref": "<variant id>|/Game/.../T_Clea_D",         // for texture_preview; "<variant id>|#0" for a swatch
                                                    // whose texture isn't recorded
  "name": "T_Clea_D", "path": "/Game/.../T_Clea_D", "kind": "Body" | "Outfit" | "Texture" | "",
  "width": 2048, "height": 2048, "format": "BC7",   // 0 / "" when the relocator didn't record them
  "swatch": "data:..." | null }

// Preview (texture_preview)
{ "ok": true, "url": "data:image/png;base64,...", "width": 1024, "height": 1024,   // the picture
  "tex_width": 2048, "tex_height": 2048, "format": "BC7", "name": "T_Clea_D", "path": "/Game/...",
  "source": "texture" | "swatch", "max_px": 1024,
  "note": "" | "Shown at 1024 x 1024, a smaller copy (mip) of the 2048 x 2048 texture." }

// Poll
{
  "busy": true,
  "changed": 17,                               // increases whenever mods/state change: refresh lists then
  "jobs": [
    { "id": 3, "name": "Lune's Outfit Options-337-2-1-1750919736.7z", "size": 64802523,
      "kind": "add" | "reinstall" | "remove",
      "status": "waiting" | "working" | "done" | "failed",
      "steps": [
        { "key": "unpack",  "label": "Unpacked",                        "state": "done" | "run" | "todo" | "fail", "detail": "26 options found" },
        { "key": "sort",    "label": "Sorted by outfit",                "state": "done", "detail": "5 rows in the menu", "tags": ["Expedition · 7", "Clea · 6"] },
        { "key": "install", "label": "Preparing for the in-game menu",  "state": "run",  "detail": "Option 17 of 26: Clea · Shorter Skirt", "progress": 0.64 }
      ],
      "error": null | "plain sentence",
      "notes": ["plain sentence", ...],        // e.g. options that were skipped
      "mod_id": "Lune Outfit Options" | null } ]
  // remove jobs have the steps "remove" (Removed from the game) and, with delete_files, "delete".
}

// Monitor (live: reads the game's logs while it runs; at app start it reads the last 4 MB of each
// log, so after the game closed it shows the last session)
{
  "watching": true,
  "game_running": true, "since": "21:03:10" | null,
  "menu_active": true,                         // the in-game menu started this session
  "last_activity": "21:10:44" | null,          // newest live_log.txt line
  "ended": "21:10:44" | null,                  // newest line of either log
  "date": "2026-10-11" | null,                 // the date of that line
  "problems": [
    { "key": "watchdog", "level": "error" | "warn" | "info", "title": "The game stopped responding for 9 s",
      "detail": "The menu was idle, so the pause came from the game itself.", "hint": "...",
      "first": "21:05:01", "last": "21:06:10", "count": 3,
      "lines": ["21:05:01 WATCHDOG: ...", "21:06:10 WATCHDOG: ..."],
      "fix": null | { "kind": "texture", "mod", "variant", "material", "param", "guess" }
                  | { "kind": "material", "mod", "variant", "mesh", "slot", "slot_name", "current" }
                  | { "kind": "repair", "mod", "variant" } } ],
                                               // texture / material: from the menu's {fix:...} tag on the
                                               // line (never shown); repair: a prepared file that didn't load
                                               // the log lines that raised it (newest 25), as in tail but
                                               // with user names hidden and cut at 500 characters;
                                               // UE4SS.log lines read "HH:MM:SS [UE4SS] text"
  "on_screen": [ { "slot": "Lune · Clea", "variant": "Shorter Skirt", "shown": 1, "total": 1, "worn": true } ],
  "tail": ["21:10:44 pass (...): 3 change(s)", "..."]   // last 500 lines of the session log (each cut at 1000 characters)
}
// The Game log tab shows a problem's `lines` when it is clicked, and for an on-screen row the
// tail lines that contain its slot.
```

## Files the app writes

- `%APPDATA%\E33Wardrobe\app.json`: settings (game folder, library folder, watch_game).
- `%APPDATA%\E33Wardrobe\relocator.json`: the relocator's saved paths (`E33_CONFIG`).
- `%APPDATA%\E33Wardrobe\sources.json`: which downloads each mod came from (for Compare).
- `%APPDATA%\E33Wardrobe\culprit.json`: Find the problem mod, while it runs.
- `ue4ss\Mods\E33Wardrobe\fixes.json`: disabled mods, row edits, texture / material rules, bundles
  (`tools/e33fixes.py`; kept on Reinstall). Bundled files are under `ue4ss\Mods\E33Wardrobe\bundles\`.
- `Sandfall\Content\E33Wardrobe_Disabled\`: prepared files of disabled mods.
- The library (`<game>\Sandfall\Content\Paks_ModLibrary\<mod>`), `Paks\~mods\_E33Wardrobe\`, and
  `ue4ss\Mods\E33Wardrobe\`: the same places the command-line tools use.
