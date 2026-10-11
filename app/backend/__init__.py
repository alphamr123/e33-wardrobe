"""Backend of the E33 Wardrobe desktop app: the `Api` object the window calls (see app/API.md).

  paths.py     app data folder, bundled resources, the game folder, UE4SS and the in-game menu
  archives.py  unpacking dropped archives and folders into the mod library
  library.py   sorting options by outfit, and what each mod contains (list and details)
  jobs.py      the background queue (add / reinstall / remove) and the in-process relocator
  api.py       class Api: every method of API.md
"""
