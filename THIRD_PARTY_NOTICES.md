# Third-party notices

E33 Wardrobe is licensed under the MIT License (see [LICENSE](LICENSE)), except where noted
below. It includes no game files and no files from other mods.

## Code adapted into this project

### CUE4Parse (Apache License 2.0)

<https://github.com/FabianFG/CUE4Parse>, copyright CUE4Parse contributors (FabianFG and
contributors).

Portions of `tools/e33tex.py` (`parse_texture`, `parse_vt`, `_tile_offset`, `decode_vt`) were
translated from C# to Python and modified, based on CUE4Parse's `FTexturePlatformData`,
`FTexture2DMipMap`, `FVirtualTextureBuiltData`, `FVirtualTextureDataChunk` and `TextureDecoder`.
These portions are licensed under the Apache License, Version 2.0; a copy is in
[LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt).

> Licensed under the Apache License, Version 2.0 (the "License"); you may not use these files
> except in compliance with the License. Unless required by applicable law or agreed to in
> writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
> WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

### bcdec (MIT or Unlicense, used under the Unlicense)

<https://github.com/iOrange/bcdec>, copyright (c) 2022 Sergii Kudlai.

The BC7 partition and anchor tables in `tools/e33tex.py` were derived from bcdec's tables (they
are the BC7/BPTC specification tables). The BC1-BC7 decoders themselves are an independent
implementation.

## Included in the app (`E33 Wardrobe.exe`)

The app's download bundles these, unmodified. Their source is at the linked pages.

| Project | Used for | License |
|---|---|---|
| [Python](https://www.python.org/) | Runtime | PSF License |
| [PyInstaller](https://pyinstaller.org/) bootloader | Starts the app | GPL-2.0 with the bootloader exception |
| [pywebview](https://github.com/r0x0r/pywebview) (+ bottle, proxy_tools, typing_extensions) | The window | BSD-3-Clause (bottle, proxy_tools: MIT; typing_extensions: PSF) |
| [pythonnet](https://github.com/pythonnet/pythonnet) | pywebview on Windows (Edge WebView2) | MIT |
| [py7zr](https://github.com/miurahr/py7zr) with pyppmd, pybcj, inflate64, multivolumefile | Unpacking 7z archives | LGPL-2.1-or-later |
| pycryptodomex, brotli, texttable, psutil | Used by py7zr | BSD / Public Domain, MIT, MIT, BSD-3-Clause |
| [retoc](https://github.com/trumank/retoc) 0.1.5 (`bin\retoc.exe`) | Converting IoStore containers | MIT, copyright (c) 2025 Truman Kilen and Archengius |
| [7-Zip](https://www.7-zip.org/) (`bin\7z.exe`, `bin\7z.dll`) | Unpacking rar archives | GNU LGPL, with the unRAR license restriction; full text in `bin\7-Zip-License.txt` |

The LGPL components can be replaced: they are separate files in the app folder (Python packages
and `7z.dll`).

## Tools and runtimes used (not included)

| Project | Used for | License |
|---|---|---|
| [RE-UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) | Runs the E33Wardrobe Lua mod (install it separately) | MIT |
| [retoc](https://github.com/trumank/retoc) | Called by `e33_relocate.py` and the swatch builder to convert IoStore containers (the command-line tools: download it separately; the app includes it) | MIT, copyright (c) 2025 Truman Kilen and Archengius |
| Oodle (`oo2core_9_win64.dll`) | Downloaded by retoc on first use | Proprietary (Epic Games / RAD). Never included here. |
| [lupa](https://github.com/scoder/lupa) | Test suite only | MIT |
| [zstandard](https://github.com/indygreg/python-zstandard) | Optional, `research/usmap.py` (compressed `.usmap` files) | BSD-3-Clause |
| [Pillow](https://github.com/python-pillow/Pillow) | Used during development to cross-check the BC decoders; not a dependency | MIT-CMU |

## Acknowledgements (research and techniques; no code copied)

- **Loud and Clear** by DatGuySnowfox (<https://github.com/DatGuySnowfox/swgr-loud-and-clear>):
  the technique of building a native UMG panel from UE4SS Lua (a bare `UserWidget` with a
  hand-made `WidgetTree`, built once and then shown and hidden, scaled to fit the viewport),
  used by `Scripts/menu.lua`.
- **RE-UE4SS's BPModLoaderMod**: loading mod assets through `AssetRegistryHelpers.GetAsset`.
- **retoc** and **UAssetAPI** (<https://github.com/atenfyr/UAssetAPI>, MIT): references for the
  UE5 IoStore and legacy package formats read by `e33utoc.py` and `e33legacy.py`.
- **E33 Randomizer** by IhorChornyi314 (<https://github.com/IhorChornyi314/E33-Randomizer>, MIT):
  its published `Mappings.usmap` and data table were used to research the game's outfit classes
  ([docs/RESEARCH.md](docs/RESEARCH.md)). Not redistributed.
- **FModel** (<https://github.com/4sval/FModel>): used as an asset viewer during research.
- **CNS and CNS Repacker** (Stellar Blade): the idea of side-by-side relocated outfit variants.
- **E33 Versus Mod** by Sebastian0211-vs (MIT): a reference for UE4SS UMG usage in this game.
- The authors of the Nexus mods **Clean Characters and Bloody Effects Remover**, **Dirt And
  Blood Remover** and **Dirt and Blood Reducer**: Clean follows how these mods work. None of their
  files are included or needed.
- **Cheekier Chic** (Nexus Mods, Clair Obscur: Expedition 33 mod 685):
  `tools/rules/cheekier_chic_v331.json` describes that mod's folder layout and install rules so
  the Mixer can offer them as choices. The mod itself must be downloaded from its page; this
  project is not affiliated with it.

Clair Obscur: Expedition 33 and all of its content belong to Sandfall Interactive and Kepler
Interactive. This project ships no game files; asset paths and class names in the code and tests
are references used to find the game's own content at runtime. Not affiliated with Sandfall
Interactive, Kepler Interactive, or the authors of the mods named here.
