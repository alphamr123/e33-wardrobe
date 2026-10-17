# Contributing

How to report a bug, add rules for a mod, or send a code change.

Thanks for helping. Bug reports, rules files for more mods, and code are all welcome.

## Reporting a bug

Open an issue (or post in the Bugs tab on Nexus Mods) with:

- what you did and what you expected;
- your UE4SS version, and whether you play on Steam or Game Pass;
- the mods you relocated;
- `ue4ss\Mods\E33Wardrobe\report.txt`. It is written at every game start while Settings > Record session
  is on (the default), and on demand with Settings > Report, Ctrl+F9 or the console command `wardrobe report`.
  User names in paths are replaced by `<user>`, but it still lists your mods and folders: look
  through it before posting.

If the game froze, follow [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#if-the-game-freezes)
before closing it.

## Asking for support of a mod's layout

Send the mod's folder tree (names only, not its files) and the install rules from its readme or
mod page.

## Adding a rules file

See [docs/MIXER.md](docs/MIXER.md#writing-your-own-rules-file). One JSON file per mod in
`tools/rules/`. Credit the mod and link its page in the file's `source` field.

## Code changes

- Read [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) first: how to run the tests, and the rules the
  code follows (one game-thread loop in the Lua mod, Lua's 200-locals limit in `main.lua`,
  stdlib-only Python tools).
- Run the tests that apply to your change, and add one for the behaviour you change.
- Keep user-facing messages plain and specific: say what happened and what to do.

## Please don't commit

Game files, other mods' files, `retoc.exe`, `oo2core_*.dll`, logs or reports, or test fixtures
that can't be published. The `.gitignore` covers the usual ones.
