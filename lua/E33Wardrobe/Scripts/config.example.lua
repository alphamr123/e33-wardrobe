-- E33Wardrobe keys and outfit names: an example.
-- To change them, copy this file to config.lua in the same folder and edit the copy. Updates
-- replace this example but never config.lua. Without config.lua the defaults below are used.
-- Key names come from UE4SS's Key table (F1..F12, A..Z, HOME, END, INS, DEL, PAGE_UP, UP_ARROW, RETURN, ...);
-- modifiers: CONTROL, SHIFT, ALT. Avoid F10: UE4SS's console uses it. Avoid INS unless UE4SS's
-- BPModLoaderMod is switched off in ue4ss\Mods\mods.txt: it reloads Blueprint mods on Insert.
-- Set a key to false to switch it off. Everything else (scoping, cursor, menu side/scale, ...)
-- is changed in the in-game menu and kept in settings.txt.
return {
    keys = {
        menu         = { "DEL", {} },                 -- open / close the in-game menu
        menuUp       = { "UP_ARROW", { "CONTROL" } },  -- menu: previous row
        menuDown     = { "DOWN_ARROW", { "CONTROL" } },
        menuLeft     = { "LEFT_ARROW", { "CONTROL" } }, -- menu: previous button in the row
        menuRight    = { "RIGHT_ARROW", { "CONTROL" } },
        menuOk       = { "RETURN", { "CONTROL" } },    -- menu: press the highlighted button
        menuPageUp   = { "PAGE_UP", { "CONTROL" } },
        menuPageDown = { "PAGE_DOWN", { "CONTROL" } },
        apply        = { "F7", { "CONTROL" } },        -- apply the picks to everyone again
        reload       = { "F8", { "CONTROL" } },        -- reload variants.lua and selection.txt
        dump         = { "F9", { "CONTROL" } },        -- write dump.txt and report.txt
        -- slot / variant cycling without the menu; only bound when legacy_keys = true in settings.txt
        nextSlot     = { "F5", { "CONTROL" } },
        prevSlot     = { "F5", { "CONTROL", "SHIFT" } },
        nextVariant  = { "F6", { "CONTROL" } },
        prevVariant  = { "F6", { "CONTROL", "SHIFT" } },
    },
    -- Names for outfits in messages such as "made for Potato bag" (the mesh name without SK_,
    -- the character and _Skin). Add your own, for example:  Civil = "Civilian clothes",
    outfit_names = {
        Potato = "Potato bag",
        Placeholder = "base body",
    },
}
