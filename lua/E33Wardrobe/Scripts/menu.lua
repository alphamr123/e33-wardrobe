--[[
E33Wardrobe in-game menu.

The panel is plain UMG assembled from Lua: one UserWidget whose WidgetTree is filled in here
(canvas > border > size box > vertical box of rows). No widget blueprint or other game asset is
used, so nothing can be missing after a game update.

  Delete                   open / close (config.lua: keys.menu)
  mouse                    click the buttons (the cursor is shown while the menu is open)
  Ctrl+Up / Ctrl+Down      highlight the previous / next row
  Ctrl+Left / Ctrl+Right   highlight the previous / next button in that row
  Ctrl+Enter               press the highlighted button
  Ctrl+PageUp / PageDown   previous / next page

How it behaves:
  * key callbacks run on UE4SS's key thread, so main.lua's binds only post them; its game-thread
    loop runs them and calls M.tick while the menu is open (or a slideshow runs)
  * the panel is built once per level and then only shown and hidden
  * it never takes keyboard focus and leaves the game's input mode alone (unless the "UI input
    mode" setting is on), so the game's own focus handling is untouched
  * text, colours and visibility are only sent to UMG when they change, so an idle tick is free
]]

local M = { open = false }

local W, S, log, valid                   -- set by M.init (API from main.lua)
local panel                              -- built widgets, kept while the map lives
local inp = {}                           -- what we changed on the player controller
local queue, suspended = {}, false
local suspendedAt = 0
local LOCKS = {}
local ticks = 0

local st = { view = "outfits", filter = nil, page = 1, pick = nil, pickPage = 1,
             row = 2, col = 1, msg = "", rows = {}, A = nil, B = nil, showing = nil, slide = nil,
             kbd = false, flash = nil, peekUntil = nil, favChar = nil, favPage = 1 }

local NROWS, NBTN = 14, 6
local WIDTH, ROW_H = 660, 30
-- ESlateVisibility
local VISIBLE, COLLAPSED, HIT_INVISIBLE, SELF_INVISIBLE = 0, 1, 3, 4

-- The palette is written as ordinary 0-255 sRGB values; UMG brushes and text take linear colour,
-- so each channel goes through the sRGB transfer curve once (table built at load).
local TO_LINEAR = {}
for v = 0, 255 do
    local c = v / 255
    TO_LINEAR[v] = (c > 0.04045) and ((c + 0.055) / 1.055) ^ 2.4 or c / 12.92
end
local function lin(r, g, b, a) return { R = TO_LINEAR[r], G = TO_LINEAR[g], B = TO_LINEAR[b], A = a or 1 } end

local C = {
    panel = lin(14, 18, 28, 0.94), row = lin(26, 31, 44, 0.85), rowFocus = lin(44, 54, 78, 0.95),
    text = lin(234, 239, 247), muted = lin(140, 154, 178), accent = lin(255, 196, 96),
    good = lin(150, 222, 160), btn = lin(70, 84, 112), hl = lin(70, 130, 200), off = lin(36, 40, 50),
    focus = lin(255, 196, 96), dark = lin(14, 16, 22), warn = lin(255, 140, 90), flash = lin(78, 70, 40, 0.95),
}

-- --------------------------------------------------------------------------- helpers

local function cut(s, n)
    s = tostring(s or "")
    local len = utf8.len(s)
    if not len then return #s > n and (s:sub(1, n - 2) .. "..") or s end
    if len <= n then return s end
    return s:sub(1, utf8.offset(s, n - 1) - 1) .. ".."
end

local function onoff(b) return b and "ON" or "OFF" end

local function say(fmt, ...)
    local ok, m = pcall(string.format, fmt, ...)
    st.msg = ok and m or tostring(fmt)
    st.lastSlot = nil
    if W and W.live then W.live("menu shows: %s", st.msg) end
end

local PRETTY = { UP_ARROW = "Up", DOWN_ARROW = "Down", LEFT_ARROW = "Left", RIGHT_ARROW = "Right",
                 RETURN = "Enter", PAGE_UP = "PgUp", PAGE_DOWN = "PgDn", HOME = "Home", END = "End",
                 INS = "Ins", DEL = "Del", CONTROL = "Ctrl", SHIFT = "Shift", ALT = "Alt" }

local function keyName(spec)
    if not spec then return "(off)" end
    local parts = {}
    for _, m in ipairs(spec[2] or {}) do parts[#parts + 1] = PRETTY[m] or m end
    parts[#parts + 1] = PRETTY[spec[1]] or spec[1]
    return table.concat(parts, "+")
end

local function keysHelp()
    local K = W.keys
    return string.format("%s close  |  %s/%s row  %s/%s button  %s press  %s/%s page  |  or click",
        keyName(K.menu), keyName(K.menuUp), keyName(K.menuDown), keyName(K.menuLeft),
        keyName(K.menuRight), keyName(K.menuOk), keyName(K.menuPageUp), keyName(K.menuPageDown))
end

local function loadLocks()
    LOCKS = {}
    for id in (S.locks or ""):gmatch("[^|]+") do LOCKS[id] = true end
end

local function saveLocks()
    local t = {}
    for id in pairs(LOCKS) do t[#t + 1] = id end
    table.sort(t)
    S.locks = table.concat(t, "|")
    W.saveSettings()
end

local function visible(slot) return S.show_technical or not (W.isTechnical and W.isTechnical(slot)) end

-- The characters a slot changes: its own, else those its meshes belong to (a costume for Lune,
-- Maelle and Sciel). An empty set: it isn't tied to anyone (applies to everybody).
local function slotChars(s)
    if s.character then return { [s.character] = true } end
    return (W.slotChars and W.slotChars(s)) or {}
end

local function characters()
    local seen, out = {}, {}
    for _, s in ipairs(W.slots()) do
        if visible(s) then
            for c in pairs(slotChars(s)) do
                if not seen[c] then seen[c] = true out[#out + 1] = c end
            end
        end
    end
    table.sort(out)
    return out
end

-- Slots shown under the character filter: the ones that change that character, plus the ones
-- tied to nobody (they apply to everybody).
local function shownSlots()
    local out = {}
    for i, s in ipairs(W.slots()) do
        local cs = slotChars(s)
        if visible(s) and (not st.filter or not next(cs) or cs[st.filter]) then out[#out + 1] = i end
    end
    return out
end

-- The character a slot's messages are about: its own, else the open tab's, else the first
-- character it changes.
local function charOf(slot)
    if slot.character then return slot.character end
    local cs = slotChars(slot)
    if st.filter and (cs[st.filter] or not next(cs)) then return st.filter end
    return (next(cs))
end

-- Labels from the relocator carry their context ("Some Outfit V2: Lune color",
-- "Non-Lace dress: Lune chic fire"); rows show the part that tells them apart.
local function slotName(slot)
    local l = slot.label or "?"
    if slot.mod and l:sub(1, #slot.mod + 2) == slot.mod .. ": " then l = l:sub(#slot.mod + 3) end
    if (l == "Main" or l == "Variants") and slot.mod then return slot.mod end   -- a one-option mod
    l = l:gsub("^_+", ""):gsub("_[Pp]$", ""):gsub("_", " ")          -- "_only Lune mod_fix_P"
    return l
end

local function isCharWord(w)
    for _, c in ipairs({ "lune", "sciel", "maelle", "gustave", "verso", "monoco", "noah", "frey" }) do
        if w:lower() == c then return true end
    end
    return false
end

-- "Some Outfit V2" -> "Some Outfit"; "Lune - Infernal Herald" -> "Infernal Herald";
-- "SomeModSciel" -> "Some Mod": the words of a mod name that tell it apart (character names dropped).
local function modShort(mod)
    local words = {}
    for w in (mod or ""):gsub("(%l)(%u)", "%1 %2"):gmatch("[%w']+") do
        if not isCharWord(w) and not w:match("^[Vv]%d") and not w:match("^%d") then words[#words + 1] = w end
    end
    if #words == 0 then return mod or "?" end
    if #words > 2 and (mod or ""):find("Chic") then return words[1] end
    return words[1] .. (words[2] and (" " .. words[2]) or "")
end

local function capital(w) return (w:gsub("^%l", string.upper)) end

-- Row name of a slot: "Outfit · Some Mod", "Color · Some Mod", "Another Mod" (one-option mod).
-- The character's own name is dropped on that character's tab (the "All" tab prefixes it);
-- withChar = true always prefixes it (messages), false never does.
local function slotDisplay(slot, withChar)
    local base = slotName(slot)
    local single = base == slot.mod                              -- a one-option mod: "Main" / "Variants"
    local words = {}
    for w in base:gmatch("%S+") do if not isCharWord(w) then words[#words + 1] = w end end
    local name = capital(table.concat(words, " "))
    local ms = modShort(slot.mod)
    if single or name == "" or name:lower() == (slot.mod or ""):lower() then name = ms
    elseif slot.mod then name = name .. " · " .. ms end
    if slot.character and (withChar or (withChar == nil and not st.filter)) then name = slot.character .. " · " .. name end
    return name
end

local function groupOf(label) return label and label:match("^(.-):%s") or nil end

-- Variant names without the words every variant of its group shares (or of the slot, if it has
-- no groups): "Lace dress: Lune Lace-chic black" -> "black", "Non-Lace dress: chic
-- lune-sleeves-boots" -> "sleeves · boots". The character's name is dropped too.
local DISTINCT = setmetatable({}, { __mode = "k" })
local function variantShort(slot, vi)
    if vi == 0 then return "off" end
    local d = DISTINCT[slot]
    if not d then
        d = {}
        local toks, count, size = {}, {}, {}
        for i, v in ipairs(slot.variants) do
            local g = groupOf(v.label) or ""
            local body = (v.label or ""):gsub("^.-:%s+", "")
            local list, seen = {}, {}
            for w in body:gmatch("[^%s%-_]+") do
                if w:find("%w") and not seen[w:lower()] then seen[w:lower()] = true list[#list + 1] = w end
            end
            toks[i] = list
            size[g] = (size[g] or 0) + 1
            count[g] = count[g] or {}
            for low in pairs(seen) do count[g][low] = (count[g][low] or 0) + 1 end
        end
        for i, list in ipairs(toks) do
            local g = groupOf(slot.variants[i].label) or ""
            local keep = {}
            for _, w in ipairs(list) do
                if not isCharWord(w) and (size[g] < 2 or count[g][w:lower()] < size[g]) then keep[#keep + 1] = w end
            end
            local name = table.concat(keep, " · ")
            if name == "" then name = ((slot.variants[i].label or "?"):gsub("^.-:%s+", "")) end
            d[i] = name
        end
        DISTINCT[slot] = d
    end
    return d[vi] or "?"
end

-- A group's name without the words all of the slot's groups share: "Non-Lace dress" -> "Non-Lace".
local function groupShort(slot, g)
    local groups, n = {}, 0
    for _, v in ipairs(slot.variants) do
        local x = groupOf(v.label)
        if x and not groups[x] then groups[x] = true n = n + 1 end
    end
    if n < 2 then return g end
    local count = {}
    for x in pairs(groups) do
        for w in x:gmatch("%S+") do count[w:lower()] = (count[w:lower()] or 0) + 1 end
    end
    local keep = {}
    for w in g:gmatch("%S+") do if count[w:lower()] < n then keep[#keep + 1] = w end end
    return #keep > 0 and table.concat(keep, " ") or g
end

-- With the group in front, for rows and messages: "Lace: black".
local function variantLong(slot, vi)
    local g = vi > 0 and slot.variants[vi] and groupOf(slot.variants[vi].label)
    return (g and (groupShort(slot, g) .. ": ") or "") .. variantShort(slot, vi)
end

-- What a character wears, in words ("Chic", "Potato bag", "base body"), or nil if not loaded here.
local function wornName(char)
    local w = char and W.wornBy and W.wornBy(char)
    if not w then return nil end
    return W.outfitName(w.path), w.under and W.outfitName(w.under) or nil
end

-- Why a selected variant shows nothing, in words.
local function whyUnused(slot)
    local char = charOf(slot) or (W.loadedChars and W.loadedChars()[1])
    local worn, under = wornName(char)
    if not char then return "no character is loaded here" end
    if not worn then return char .. " isn't loaded here" end
    local target = W.targetOutfit(slot, char)
    if target then
        local made = W.outfitName(target)
        if made == (under or worn) then
            return string.format("made for %s, which %s wears, but it did not apply: try Fix look; if it stays, "
                .. "report it with report.txt",
                made, char)
        end
        return string.format("made for %s; %s wears %s", made, char, under or worn)
    end
    return string.format("%s's current outfit (%s) doesn't use what it changes", char, worn)
end

-- Why a selected variant may not show, for the row and the status line.
local lastState = {}                     -- slot index -> last state that wasn't "pending"
local function stateOf(si)
    local state = W.slotState(si)
    if state == "pending" then return lastState[si] end
    lastState[si] = state
    return state
end

local function slotNote(si)
    local state = stateOf(si)
    if state == "unused" then return "not visible", C.warn end
    for _, o in ipairs(W.overlaps(si)) do
        if not o.wins then return "hidden", C.muted end
    end
    return nil
end

local function slotNoteHelp(si)
    local slot = W.slots()[si]
    local state = stateOf(si)
    if state == "unused" then
        return "Not visible: " .. whyUnused(slot) .. "."
            .. (W.canWear(slot) and " Wear puts it on instead of the current outfit." or "")
    end
    for _, o in ipairs(W.overlaps(si)) do
        if not o.wins then
            local other = W.slots()[o.idx]
            return string.format("Hidden by %s (it changes the same %d piece(s) and was picked later). "
                .. "Pick this one again to bring it to the front.", slotDisplay(other), o.count)
        end
    end
    return nil
end

local function go(view)
    st.view, st.row, st.col = view, 2, 1
    if view == "presets" then st.presets = W.loadPresets() end
end

-- --------------------------------------------------------------------------- actions

local function setSlot(si, vi, quiet)
    local slots = W.slots()
    local slot = slots[si]
    if not slot then return end
    local before = W.selection()
    W.setVariant(si, vi)
    local after, matched = W.selection(), {}
    for k, other in ipairs(slots) do
        if k ~= si and before[other.id] ~= after[other.id] and visible(other) then
            matched[#matched + 1] = slotDisplay(other) .. " -> " .. variantLong(other, W.variantIndex(other))
        end
    end
    if not quiet then
        say("%s: %s%s", cut(slotDisplay(slot, true), 36),
            variantLong(slot, W.variantIndex(slot)),
            #matched > 0 and ("  (to match, also " .. table.concat(matched, "; ") .. ")") or "")
    end
    st.lastSlot, st.flash = si, { si = si, n = 20 }   -- after say(), which clears lastSlot
end

local function cycle(si, d)
    local slot = W.slots()[si]
    if not slot then return end
    setSlot(si, (W.variantIndex(slot) + d) % (#slot.variants + 1))
end

local function randomOne(si)
    local slot = W.slots()[si]
    local n, cur = #slot.variants, W.variantIndex(slot)
    local lo = S.random_off and 0 or 1
    local choices = {}
    for vi = lo, n do if vi ~= cur then choices[#choices + 1] = vi end end
    if #choices == 0 then say("nothing else to pick for %s", slotDisplay(slot)) return end
    setSlot(si, choices[math.random(1, #choices)])
end

local function randomize()
    local sel, n, slots = W.selection(), 0, W.slots()
    for _, si in ipairs(shownSlots()) do
        local slot = slots[si]
        if not LOCKS[slot.id] and #slot.variants > 0 then
            local vi = math.random(S.random_off and 0 or 1, #slot.variants)
            sel[slot.id] = vi > 0 and slot.variants[vi].id or nil
            n = n + 1
        end
    end
    W.setSelection(sel, false, true)            -- true: keep each mod's groups (Lace / Non-Lace) matched
    say("randomized %d slot(s)%s", n, st.filter and (" for " .. st.filter) or "")
end

local function vanilla()
    local sel, n, slots = W.selection(), 0, W.slots()
    for _, si in ipairs(shownSlots()) do
        local slot = slots[si]
        if not LOCKS[slot.id] and sel[slot.id] then
            sel[slot.id] = nil
            n = n + 1
        end
    end
    W.setSelection(sel)
    say("%d slot(s) off (the game's own)%s", n, st.filter and (" for " .. st.filter) or "")
end

local function undo()
    local before = W.selection()
    if not W.undo() then say("nothing to undo") return end
    local after, what = W.selection(), {}
    for _, slot in ipairs(W.slots()) do
        if before[slot.id] ~= after[slot.id] and visible(slot) then
            what[#what + 1] = slotDisplay(slot) .. " back to " .. variantLong(slot, W.variantIndex(slot))
        end
    end
    say("undid: %s", #what > 0 and table.concat(what, "; ") or "a change of a hidden slot")
end

local function storeAB(which)
    st[which] = W.selection()
    st.showing = which
    say("current look stored as %s", which)
end

local function swapAB()
    local to = st.showing == "A" and "B" or "A"
    if not st[to] then say("store %s first", to) return end
    W.setSelection(st[to])
    st.showing = to
    say("showing look %s", to)
end

local function toggleLock(slot)
    LOCKS[slot.id] = not LOCKS[slot.id] or nil
    saveLocks()
    say("%s %s", slotDisplay(slot), LOCKS[slot.id] and "locked (Randomize / All off keep it)" or "unlocked")
end

local function presetSummary(p)
    if not p then return "empty" end
    local by, order, n = {}, {}, 0
    for _, slot in ipairs(W.slots()) do
        local vid = p[slot.id]
        if vid and visible(slot) then
            for vi, v in ipairs(slot.variants) do
                if v.id == vid then
                    n = n + 1
                    local c = slot.character or "all"
                    if not by[c] then by[c] = {} order[#order + 1] = c end
                    by[c][#by[c] + 1] = #slot.variants == 1 and modShort(slot.mod) or variantShort(slot, vi)
                end
            end
        end
    end
    if n == 0 then return "all off" end
    local parts = {}
    for _, c in ipairs(order) do parts[#parts + 1] = c .. ": " .. table.concat(by[c], ", ") end
    return table.concat(parts, " | ")
end

local function presetSave(i)
    local all = W.loadPresets()
    all[i] = W.selection()
    W.savePresets(all)
    st.presets = W.loadPresets()
    say("saved preset %d", i)
end

local function presetLoad(i)
    local p = (st.presets or {})[i]
    if not p then say("preset %d is empty", i) return end
    W.setSelection(p)
    say("loaded preset %d", i)
end

local function presetClear(i)
    local all = W.loadPresets()
    all[i] = nil
    W.savePresets(all)
    st.presets = W.loadPresets()
    say("cleared preset %d", i)
end

local function slideStep()
    local sl = st.slide
    if not sl then return end
    local slot = W.slots()[sl.si]
    if not slot or #slot.variants == 0 then st.slide = nil return end
    if os.time() < sl.at then return end
    sl.at = os.time() + math.max(1, S.slideshow_s or 4)
    local vi = W.variantIndex(slot) % #slot.variants + 1
    W.setVariant(sl.si, vi, true)               -- no undo entry per step
    say("slideshow %s: %d/%d %s", slotDisplay(slot), vi, #slot.variants, variantLong(slot, vi))
end

local function slideToggle(si)
    if st.slide and st.slide.si == si then
        st.slide = nil
        say("slideshow stopped")
    else
        st.slide = { si = si, at = os.time() + math.max(1, S.slideshow_s or 4) }
        say("slideshow every %d s (runs while the menu is closed too; Stop it here)", S.slideshow_s or 4)
    end
end

-- Favorites: W.favorites() is the list of saved looks { char, name, picks = { slot id = variant id } }
-- in the player's order. A look covers the slots tied to that character.
local function charSlots(char)
    local out = {}
    for si, slot in ipairs(W.slots()) do if slot.character == char then out[#out + 1] = si end end
    return out
end

local function currentLook(char)
    local picks, names = {}, {}
    for _, si in ipairs(charSlots(char)) do
        local slot = W.slots()[si]
        local vi = W.variantIndex(slot)
        if vi > 0 then
            picks[slot.id] = slot.variants[vi].id
            if visible(slot) then
                names[#names + 1] = #slot.variants > 1 and (slotDisplay(slot, false) .. " " .. variantShort(slot, vi))
                    or slotDisplay(slot, false)
            end
        end
    end
    return picks, #names > 0 and table.concat(names, " + ") or "Game's own outfit"
end

local function sameLook(a, b)
    for id, vid in pairs(a) do if b[id] ~= vid then return false end end
    for id, vid in pairs(b) do if a[id] ~= vid then return false end end
    return true
end

local function lookIndex(char, picks)
    local n = 0
    for k, e in ipairs(W.favorites()) do
        if e.char == char then
            n = n + 1
            if sameLook(e.picks, picks) then return k, n end
        end
    end
end

local function saveLook(char)
    local picks, name = currentLook(char)
    local _, n = lookIndex(char, picks)
    if n then say("this look is already favorite %d", n) return end
    local list = W.favorites()
    list[#list + 1] = { char = char, name = name, picks = picks }
    W.saveFavorites()
    say("saved to %s's favorites: %s", char, cut(name, 50))
end

local function useLook(e)
    for pass = 1, 2 do                          -- twice: matched groups may move a sibling on the first
        for _, si in ipairs(charSlots(e.char)) do
            local slot = W.slots()[si]
            local want = 0
            for vi, v in ipairs(slot.variants) do if v.id == e.picks[slot.id] then want = vi end end
            if W.variantIndex(slot) ~= want then setSlot(si, want, true) end
        end
    end
    say("%s: %s", e.char, cut(e.name, 60))
end

-- d = -1 / 1: swap with the previous / next look of the same character.
local function favMove(char, k, d)
    local list, mine = W.favorites(), {}
    for i, e in ipairs(list) do if e.char == char then mine[#mine + 1] = i end end
    for j, i in ipairs(mine) do
        local o = mine[j + d]
        if i == k and o then
            list[i], list[o] = list[o], list[i]
            W.saveFavorites()
            say("moved %s", d < 0 and "up" or "down")
            return
        end
    end
end

-- --------------------------------------------------------------------------- input on the player controller

local function playerController()
    local ok, pcs = pcall(FindAllOf, "PlayerController")
    if not ok or not pcs then return nil end
    for _, pc in ipairs(pcs) do
        if valid(pc) then
            local okp, player = pcall(function() return pc.Player end)
            if okp and valid(player) then return pc end
        end
    end
    return nil
end

local function blueprintLib()
    local lib = StaticFindObject("/Script/UMG.Default__WidgetBlueprintLibrary")
    return valid(lib) and lib or nil
end

local function grabInput(pc)
    inp.pc = pc
    if S.cursor and not inp.cursor then
        local okb, before = pcall(function() return pc.bShowMouseCursor end)
        inp.cursorBefore = okb and before or false
        pcall(function() pc.bShowMouseCursor = true end)
        inp.cursor = true
    end
    if S.block_look and not inp.look then
        inp.look = pcall(function() pc:SetIgnoreLookInput(true) end)
    end
    if S.ui_input and not inp.ui and panel then
        local lib = blueprintLib()
        inp.ui = lib and pcall(function() lib:SetInputMode_GameAndUIEx(pc, panel.host, 0, false) end) or false
    end
end

local function releaseInput()
    local pc = inp.pc
    local ok = pc and valid(pc)
    if inp.ui and ok then
        local lib = blueprintLib()
        if lib then pcall(function() lib:SetInputMode_GameOnly(pc, false) end) end
    end
    if inp.look and ok then pcall(function() pc:SetIgnoreLookInput(false) end) end
    if inp.cursor and ok then pcall(function() pc.bShowMouseCursor = inp.cursorBefore end) end
    inp = {}
end

local function reapplyInput()
    if not M.open then return end
    local pc = inp.pc
    releaseInput()
    if pc and valid(pc) then grabInput(pc) end
end

-- --------------------------------------------------------------------------- widgets

local SERIAL = 0
local function construct(cls, outer, prefix)
    local obj
    if prefix then
        SERIAL = SERIAL + 1
        local ok, o = pcall(StaticConstructObject, cls, outer,
            FName(string.format("%s_%d_%d", prefix, os.time() % 1000000, SERIAL)))
        if ok then obj = o end
    end
    if not (obj and valid(obj)) then obj = StaticConstructObject(cls, outer) end
    assert(obj and valid(obj), "could not construct a widget")
    return obj
end

-- Remove menus left on screen by an earlier Lua state (e.g. after a UE4SS mod reload).
local function sweep()
    local ok, all = pcall(FindAllOf, "UserWidget")
    if not ok or not all then return end
    for _, w in ipairs(all) do
        if valid(w) then
            local n = ""
            pcall(function() n = w:GetFName():ToString() end)
            if n:find("^E33WardrobeMenu") then pcall(function() w:RemoveFromParent() end) end
        end
    end
end

-- cached setters: only call into UMG when something changed
local function setText(c, s)
    if c.text ~= s then c.text = s; c.w:SetText(FText(s)) end
end
local function setColor(c, col)
    if c.color ~= col then
        c.color = col
        pcall(function() c.w:SetColorAndOpacity({ SpecifiedColor = col, ColorUseRule = 0 }) end)
    end
end
local function setVis(c, v)
    if c.vis ~= v then c.vis = v; c.w:SetVisibility(v) end
end
-- v: a fill weight, or "auto" (as wide as the caption needs)
local function setFill(c, v)
    if c.slot and c.fill ~= v then
        c.fill = v
        if v == "auto" then
            pcall(function() c.slot:SetSize({ SizeRule = 0, Value = 1 }) end)
        else
            pcall(function() c.slot:SetSize({ SizeRule = 1, Value = v }) end)
        end
    end
end
local function setBrush(c, col)
    if c.color ~= col then c.color = col; c.w:SetBrushColor(col) end
end
local function setBg(c, col)
    if c.bg ~= col then c.bg = col; c.w:SetBackgroundColor(col) end
end
local function setEnabled(c, e)
    if c.en ~= e then c.en = e; c.w:SetIsEnabled(e) end
end

local Z_ORDER = 9000                      -- above the game's HUD and menu widgets
local PAD = { frame = { 14, 10 }, rowLeft = 6, cellRight = 6, button = 2, caption = 8 }

local function build(pc)
    local function class(n)
        local c = StaticFindObject("/Script/UMG." .. n)
        assert(valid(c), "UMG class missing: " .. n)
        return c
    end
    -- The host is given the player controller as its outer, so it lives in the player's world.
    -- It isn't made from a widget blueprint, so there's no designer tree: we attach our own.
    local host = construct(class("UserWidget"), pc, "E33WardrobeMenu")
    local tree = construct(class("WidgetTree"), host)
    host.WidgetTree = tree
    if not pcall(function() host:SetOwningPlayer(pc) end) then
        pcall(function() host.Player = pc.Player end)
    end

    -- child(parent, kind, attach): a new widget of `kind`, attached with the parent's add function
    local function child(parent, kind, attach)
        local w = construct(class(kind), tree)
        local slot = parent and parent[attach or "AddChild"](parent, w) or nil
        return w, slot
    end
    local function text(parent, attach, size, wrap)
        local t, slot = child(parent, "TextBlock", attach)
        pcall(function() t.Font.Size = size end)          -- has to happen before Slate builds it
        pcall(function() t:SetAutoWrapText(wrap == true) end)
        pcall(function() t:SetClipping(1) end)            -- long names are cut at the cell edge
        return { w = t, slot = slot }
    end
    local function gapBelow(slot, px)
        pcall(function() slot:SetPadding({ Left = 0, Top = 0, Right = 0, Bottom = px }) end)
    end

    local root = child(nil, "CanvasPanel")
    tree.RootWidget = root
    pcall(function() root:SetVisibility(SELF_INVISIBLE) end)
    local frame, fslot = child(root, "Border", "AddChildToCanvas")
    frame:SetBrushColor(C.panel)
    frame:SetPadding({ Left = PAD.frame[1], Top = PAD.frame[2], Right = PAD.frame[1], Bottom = PAD.frame[2] })
    pcall(function() fslot:SetAutoSize(true) end)
    local width = child(frame, "SizeBox")
    width:SetWidthOverride(WIDTH)
    local column = child(width, "VerticalBox")

    local P = { host = host, frame = frame, fslot = fslot, rows = {}, pc = pc }
    P.title = text(column, "AddChildToVerticalBox", 20)
    gapBelow(P.title.slot, 2)
    P.status = text(column, "AddChildToVerticalBox", 14, true)
    gapBelow(P.status.slot, 6)
    for r = 1, NROWS do
        local box, bslot = child(column, "SizeBox", "AddChildToVerticalBox")
        box:SetHeightOverride(ROW_H)
        gapBelow(bslot, 2)
        local bg = child(box, "Border")
        bg:SetPadding({ Left = PAD.rowLeft, Top = 1, Right = 2, Bottom = 1 })
        local line = child(bg, "HorizontalBox")
        local R = { box = { w = box }, bg = { w = bg }, btns = {} }
        for _, key in ipairs({ "label", "value" }) do
            local c = text(line, "AddChildToHorizontalBox", 14)
            pcall(function() c.slot:SetVerticalAlignment(2) end)    -- each call on its own: one
            pcall(function() c.slot:SetPadding({ Left = 0, Top = 0, Right = PAD.cellRight, Bottom = 0 }) end)
            R[key] = c
        end
        for k = 1, NBTN do
            local b, slot = child(line, "Button", "AddChildToHorizontalBox")
            pcall(function() slot:SetPadding({ Left = PAD.button, Top = 1, Right = PAD.button, Bottom = 1 }) end)
            local cap = text(b, "AddChild", 13)
            pcall(function() cap.w:SetJustification(1) end)  -- that fails mustn't skip the others
            pcall(function() cap.slot:SetPadding({ Left = PAD.caption, Top = 0, Right = PAD.caption, Bottom = 0 }) end)
            pcall(function() cap.slot:SetHorizontalAlignment(2) end)
            pcall(function() cap.slot:SetVerticalAlignment(2) end)
            R.btns[k] = { w = b, cap = cap, slot = slot }
        end
        P.rows[r] = R
    end
    P.help = text(column, "AddChildToVerticalBox", 12, true)
    setText(P.title, "E33 Wardrobe")
    setColor(P.title, C.accent)
    setColor(P.status, C.text)
    setColor(P.help, C.muted)
    for _, c in ipairs({ P.title, P.status, P.help }) do setVis(c, HIT_INVISIBLE) end
    pcall(function() host.bIsFocusable = false end)
    host:AddToViewport(Z_ORDER)
    return P
end

local function dropPanel()
    if panel and valid(panel.host) then
        pcall(function() panel.host:SetVisibility(COLLAPSED) end)
        pcall(function() panel.host:RemoveFromParent() end)
    end
    panel = nil
end

-- Side, scale, and shrink-to-fit (viewport size in DPI-scaled units).
local function place(force)
    if not panel then return end
    local right = S.side ~= "left"
    if force or panel.side ~= S.side then
        panel.side = S.side
        pcall(function()
            local x = right and 1 or 0
            panel.fslot:SetAnchors({ Minimum = { X = x, Y = 0 }, Maximum = { X = x, Y = 0 } })
            panel.fslot:SetAlignment({ X = x, Y = 0 })
            panel.fslot:SetPosition({ X = right and -24 or 24, Y = 70 })
            panel.frame:SetRenderTransformPivot({ X = x, Y = 0 })
        end)
    end
    -- The chosen scale, made smaller when the panel wouldn't fit the screen. The viewport size is
    -- in pixels; dividing by the DPI scale gives the units the panel is laid out in.
    local scale = (S.scale or 100) / 100
    local panelW = WIDTH + 2 * PAD.frame[1]
    local panelH = 110 + #st.rows * (ROW_H + 2)
    local SPARE_X, SPARE_Y = 48, 90                     -- screen edges left free (incl. the panel's offset)
    pcall(function()
        local layout = StaticFindObject("/Script/UMG.Default__WidgetLayoutLibrary")
        if not valid(layout) then return end
        local px, dpi = layout:GetViewportSize(panel.pc), layout:GetViewportScale(panel.pc)
        if not (dpi and dpi > 0 and px.X > 0 and px.Y > 0) then return end
        local fitW = (px.X / dpi - SPARE_X) / panelW
        local fitH = (px.Y / dpi - SPARE_Y) / panelH
        scale = math.min(scale, fitW, fitH)
    end)
    scale = math.floor(math.max(0.35, scale) * 100 + 0.5) / 100
    if force or panel.scale ~= scale then
        panel.scale = scale
        pcall(function() panel.frame:SetRenderScale({ X = scale, Y = scale }) end)
    end
end

-- --------------------------------------------------------------------------- views
-- A view is a list of rows: { label, value, lc, vc (colours), lw, vw, bw (fill weights),
-- help, b = { {t = caption, fn = action, on = enabled, hl = highlighted}, ... } }

-- why: shown when a disabled button is clicked.
local function btn(t, fn, on, hl, w, why) return { t = t, fn = fn, on = on ~= false, hl = hl, w = w, why = why } end

local function peek()
    local secs = math.max(1, S.peek_s or 3)
    st.peekLeft = secs * 20                     -- M.tick runs every 50 ms
    releaseInput()
    if panel and valid(panel.host) then pcall(function() panel.host:SetVisibility(COLLAPSED) end) end
    W.live("menu peek: hidden for %d s", secs)
end

local function tabsRow()
    local v = (st.view == "pick" or st.view == "fav") and "outfits" or st.view
    return { help = "Peek hides the menu for a few seconds (camera free) so you can look at the character.",
        b = { btn("Outfits", function() go("outfits") end, true, v == "outfits"),
              btn("Presets", function() go("presets") end, true, v == "presets"),
              btn("Settings", function() go("settings") end, true, v == "settings"),
              btn("Peek", peek, true, false, 0.9),
              btn("Close", function() M.close() end, true, false, 0.9) } }
end

local function setWear(si, slot, on)
    W.setWear(slot.id, on)
    local worn, under = wornName(charOf(slot))
    if on then
        say("%s worn in place of %s", slotDisplay(slot, true), worn or "the current outfit")
    else
        say("%s taken off; back to %s", slotDisplay(slot, true), under or worn or "the game's outfit")
    end
    st.lastSlot = si
end

-- Wear: only where it can do something (a mesh to put on, and the pick doesn't show on what the
-- character wears now), and "Unwear" while it is on. No greyed button that invites clicks.
local function wearBtn(si, slot, w)
    if W.isWear(slot.id) then
        if W.variantIndex(slot) == 0 then return nil end
        return btn("Unwear", function() setWear(si, slot, false) end, true, true, w)
    end
    if not W.canWear(slot) or W.variantIndex(slot) == 0 or stateOf(si) ~= "unused" then return nil end
    local worn = wornName(charOf(slot))
    if not worn then return nil end
    return btn("Wear", function() setWear(si, slot, true) end, true, false, w)   -- the row says in place of what
end

-- Which tab opens first: the last one used, else the first character on screen.
local function initTab()
    if st.tabDone then return end
    st.tabDone = true
    local chars, want = characters(), S.tab
    if want == "All" then st.filter = nil return end
    for _, c in ipairs(chars) do if c == want then st.filter = c return end end
    local loaded = W.loadedChars and W.loadedChars() or {}
    for _, c in ipairs(chars) do
        for _, l in ipairs(loaded) do if c == l then st.filter = c return end end
    end
    st.filter = chars[1]
end

local function loadedSet()
    local t = {}
    for _, c in ipairs(W.loadedChars and W.loadedChars() or {}) do t[c] = true end
    return t
end

local function charTabs(rows, chars)
    local here, b = loadedSet(), {}
    local fit = NBTN - 1                        -- one button is "All"
    local list, first = chars, 1
    if #chars > fit then                        -- more characters than buttons: a window plus "More"
        fit = NBTN - 2
        if st.filter ~= st.tabShown then        -- a newly selected character starts in view
            st.tabShown = st.filter
            for k, c in ipairs(chars) do
                if c == st.filter and (k < (st.tabFirst or 1) or k >= (st.tabFirst or 1) + fit) then st.tabFirst = k end
            end
        end
        first = math.max(1, math.min(st.tabFirst or 1, #chars - fit + 1))
    end
    for k = first, math.min(#list, first + fit - 1) do
        local c = list[k]
        b[#b + 1] = btn(here[c] and c or (c .. " -"), function()
            st.filter, st.page, S.tab = c, 1, c
            W.saveSettings()
        end, true, st.filter == c)
    end
    if #chars > NBTN - 1 then
        b[#b + 1] = btn("More", function()      -- the next characters; after the last ones, back to the first
            st.tabFirst = (first + fit > #chars) and 1 or first + fit
        end, true, false, 0.7)
    end
    b[#b + 1] = btn("All", function()
        st.filter, st.page, S.tab = nil, 1, "All"
        W.saveSettings()
    end, true, st.filter == nil, 0.8)
    rows[#rows + 1] = { help = "One tab per character (\"-\" = not loaded in this area). All lists every character's slots.", b = b }
end

local function wearsRow(rows, char)
    local worn, under = wornName(char)
    local value, col = "not in this area", C.muted
    if worn and under then
        local by
        for _, slot in ipairs(W.slots()) do
            if slotChars(slot)[char] and W.isWear(slot.id) and W.variantIndex(slot) > 0 then by = slotDisplay(slot) end
        end
        value, col = string.format("%s (in place of %s)", by or worn, under), C.text
    elseif worn then
        value, col = worn, C.text
    end
    rows[#rows + 1] = { label = char .. " wears", value = cut(value, 34), lc = C.muted, vc = col, lw = 2, vw = 5,
        help = "The outfit " .. char .. " has on right now. Favorites: " .. char .. "'s saved looks.",
        b = { btn("Favorites", function() st.favChar, st.favPage = char, 1 go("fav") end) } }
end

local OUTFIT_HELP = "< > step through the variants, Choose shows them all by name, Off = the game's own. "
    .. "Randomize / All off act on this tab and keep locked slots."

local function slotRow(rows, si)
    local slot = W.slots()[si]
    local vi, n = W.variantIndex(slot), #slot.variants
    local note, ncol = slotNote(si)
    local value
    if vi == 0 then value = "off"
    elseif n == 1 then value = "on"
    else value = variantLong(slot, vi) end
    if note == "not visible" then
        local t = W.targetOutfit(slot)
        value = value .. (t and (" · made for " .. W.outfitName(t)) or " · not visible")
    elseif note == "hidden" then value = value .. " · hidden"
    elseif W.isWear(slot.id) and vi > 0 then value = value .. " · worn" end
    local b
    local wb = wearBtn(si, slot, 1.5)
    if n == 1 then
        b = { btn("On", function() setSlot(si, 1) end, vi == 0, vi ~= 0, 0.7, "already on"),
              btn("Off", function() setSlot(si, 0) end, vi ~= 0, false, 0.7, "already off (the game's own)") }
    else
        b = { btn("<", function() cycle(si, -1) end, true, false, 0.5),
              btn(">", function() cycle(si, 1) end, true, false, 0.5),
              btn("Choose", function()
                  st.pick, st.pickJump = si, true
                  go("pick")
              end, true, false, 1),
              btn("Off", function() setSlot(si, 0) end, vi ~= 0, false, 0.7, "already off (the game's own)") }
    end
    if wb then b[#b + 1] = wb end
    local flash = st.flash and st.flash.si == si
    rows[#rows + 1] = {
        label = cut(slotDisplay(slot), LOCKS[slot.id] and 18 or 24) .. (LOCKS[slot.id] and " [lock]" or ""),
        value = cut(value, wb and 27 or 36),
        vc = ncol or (vi == 0 and C.muted or C.accent), lw = 3, vw = wb and 3.4 or 4.2, bg = flash and C.flash or nil,
        help = slotNoteHelp(si) or OUTFIT_HELP, b = b }
end

-- One extra row under the slot just picked, when its pick doesn't show: says why, offers the fix.
local function explainRow(rows, si)
    local slot = W.slots()[si]
    local note = slotNote(si)
    local ok = btn("OK", function() st.lastSlot = nil end, true, false, 0.6)
    if note == "not visible" then
        local b = {}
        local wb = wearBtn(si, slot, 1.6)
        if wb then b[#b + 1] = wb end
        b[#b + 1] = ok
        local why = whyUnused(slot)
        if not W.canWear(slot) and slot.character then
            why = why .. " (colours / textures follow the outfit they were made for)"
        end
        rows[#rows + 1] = { label = "  ! " .. cut(why, 70), lc = C.warn, lw = 6, help = slotNoteHelp(si), b = b }
    elseif note == "hidden" then
        rows[#rows + 1] = { label = "  ! " .. cut(slotNoteHelp(si) or "hidden by a later pick", 70), lc = C.muted, lw = 6,
            help = slotNoteHelp(si),
            b = { btn("Bring to front", function() setSlot(si, W.variantIndex(slot)) end, true, false, 1.6), ok } }
    end
end

-- Clean and Fix look work without any relocated mod, so they are offered either way.
local function cleanBtn()
    return btn(S.clean and "Clean: on" or "Clean", function()
        local on = not S.clean
        local r = W.setClean and W.setClean(on)
        if not on then
            say("blood and dirt back as the game shows them (%d mask(s) restored)", r or 0)
        elseif r and r.noTex then
            say("Clean could not make its blank texture - nothing changed (see live_log.txt)")
        elseif r and r.set > 0 then
            say("clean: %d blood / dirt mask(s) blanked on %d character part(s); stays on for new characters",
                r.set, r.actors)
        else
            say("Clean is on; no blood / dirt masks on the characters loaded now (it stays on for new ones)")
        end
    end, true, S.clean, 0.8)
end

local function fixBtn()
    return btn("Fix look", function()
        W.fixLook()
        local r = W.lastFix and W.lastFix() or { n = 0 }
        if r.n > 0 then
            say("the game re-dressed %d character(s); your picks are applied again", r.n)
        else
            say("your picks are applied again (the game's own re-dress didn't respond)")
        end
    end)
end

local function outfitRows(rows)
    local slots = W.slots()
    if #slots == 0 then
        rows[#rows + 1] = { label = "No outfit mods relocated yet.", lw = 1 }
        rows[#rows + 1] = { label = "Run the relocator for a mod (see the docs), then press Reload files.", lw = 1 }
        rows[#rows + 1] = { help = "Clean: blood and dirt off every character (again: back on). Fix look: the game "
                .. "re-dresses everyone. Both work without relocated mods.",
            b = { btn("Reload files", function() W.reload(); say("reloaded variants.lua") end), cleanBtn(), fixBtn() } }
        return
    end
    initTab()
    local chars = characters()
    if #chars > 0 then charTabs(rows, chars) end
    if st.filter then wearsRow(rows, st.filter) end
    local list = shownSlots()
    local per = NROWS - #rows - 3                   -- explanation, page and bottom rows
    local pages = math.max(1, math.ceil(#list / per))
    st.page = math.max(1, math.min(st.page, pages))
    for k = (st.page - 1) * per + 1, math.min(#list, st.page * per) do
        slotRow(rows, list[k])
        if list[k] == st.lastSlot then explainRow(rows, list[k]) end
    end
    if #list == 0 then
        rows[#rows + 1] = { label = "Nothing to change for " .. (st.filter or "anyone") .. ".", lc = C.muted, lw = 1 }
    end
    if pages > 1 then
        rows[#rows + 1] = { value = string.format("Page %d/%d", st.page, pages), vc = C.muted, vw = 2,
            b = { btn("< Page", function() st.page = st.page - 1 end, st.page > 1, false, nil, "first page"),
                  btn("Page >", function() st.page = st.page + 1 end, st.page < pages, false, nil, "last page") } }
    end
    local who = st.filter or "everyone"
    rows[#rows + 1] = { help = "Undo goes back one change. All off / Randomize act on " .. who
            .. " (locked slots stay). Clean: blood and dirt off every character, also ones that come later (again: back on). "
            .. "Fix look: applies your picks again (and asks the game to re-dress everyone).",
        b = { btn("Undo", undo, W.canUndo(), false, nil, "nothing to undo"),
              btn("All off", vanilla),
              btn("Randomize", randomize),
              cleanBtn(), fixBtn() } }
end

-- The chooser: every variant is a button named by what tells it apart, under its group's name.
local function pickRows(rows)
    local slot = W.slots()[st.pick or 0]
    if not slot then
        st.view = "outfits"
        return outfitRows(rows)
    end
    local si, n, cur = st.pick, #slot.variants, W.variantIndex(slot)
    local sliding = st.slide and st.slide.si == si
    local note, ncol = slotNote(si)
    local head = { btn("Back", function() go("outfits") end, true, false, 0.8),
                   btn(LOCKS[slot.id] and "Unlock" or "Lock", function() toggleLock(slot) end, true, LOCKS[slot.id], 0.9),
                   btn(sliding and "Stop" or "Slides", function() slideToggle(si) end, n > 1 or sliding, sliding, 0.9,
                       "only one variant") }
    local wb = wearBtn(si, slot, 1.6)
    if wb then head[#head + 1] = wb end
    rows[#rows + 1] = { label = cut(slotDisplay(slot, true), 30),
        value = note or "", vc = ncol or C.accent, lw = 3.2, vw = 1.2,
        help = slotNoteHelp(si) or ((slot.mod or "") .. ". Lock keeps this slot when using Randomize / All off. "
            .. "Slides steps through the variants on a timer."),
        b = head }
    -- lines: group names and rows of 3 named buttons
    local lines, last, chips = {}, false, nil
    for vi = 1, n do
        local g = groupOf(slot.variants[vi].label) or ""
        if g ~= last then
            if g ~= "" then lines[#lines + 1] = { label = g, lc = C.muted, lw = 1 } end
            last, chips = g, nil
        end
        if not chips or #chips.b >= 3 then
            chips = { b = {}, full = {}, bw = 1 }
            lines[#lines + 1] = chips
        end
        chips.b[#chips.b + 1] = btn(cut(variantShort(slot, vi), 24), function() setSlot(si, vi) end, true, vi == cur)
        chips.full[#chips.full + 1] = slot.variants[vi].label
        chips.vis = chips.vis or {}
        chips.vis[#chips.vis + 1] = vi
    end
    for _, l in ipairs(lines) do
        if l.full then
            l.help = "Click a name to use it (the blue one is in use): " .. table.concat(l.full, "  |  ")
            l.full = nil
        end
    end
    local per = NROWS - #rows - 1
    local pages = math.max(1, math.ceil(#lines / per))
    if st.pickJump then                         -- open on the page with the current variant
        st.pickJump, st.pickPage = nil, 1
        for k, l in ipairs(lines) do
            for _, vi in ipairs(l.vis or {}) do if vi == cur then st.pickPage = math.ceil(k / per) end end
        end
    end
    st.pickPage = math.max(1, math.min(st.pickPage, pages))
    for k = (st.pickPage - 1) * per + 1, math.min(#lines, st.pickPage * per) do
        lines[k].vis = nil
        rows[#rows + 1] = lines[k]
    end
    local foot = { btn("Off (game's own)", function() setSlot(si, 0) end, cur ~= 0, cur == 0, 1.6, "already off"),
                   btn("Random", function() randomOne(si) end, n > 0) }
    if pages > 1 then
        foot[#foot + 1] = btn("< Page", function() st.pickPage = st.pickPage - 1 end, st.pickPage > 1, false, nil, "first page")
        foot[#foot + 1] = btn("Page >", function() st.pickPage = st.pickPage + 1 end, st.pickPage < pages, false, nil, "last page")
    end
    rows[#rows + 1] = { value = pages > 1 and string.format("%d/%d", st.pickPage, pages) or nil, vc = C.muted, vw = 0.6,
        help = "Off puts the game's own outfit back for this slot. Random picks another variant.", b = foot }
end

-- One character's favorites (saved looks), in the player's order.
local function favRows(rows)
    local char = st.favChar or st.filter
    if not char then go("outfits") return outfitRows(rows) end
    local items = {}
    for k, e in ipairs(W.favorites()) do if e.char == char then items[#items + 1] = { k = k, e = e } end end
    local cur = currentLook(char)
    rows[#rows + 1] = { label = char .. " favorites", lc = C.accent, lw = 4,
        help = "Save look stores everything " .. char .. " has on from your mods. Use puts it back; "
            .. "Up / Down set the order. Kept in favorites.txt.",
        b = { btn("Save look", function() saveLook(char) end),
              btn("Back", function() go("outfits") end) } }
    if #items == 0 then
        rows[#rows + 1] = { label = "No favorites yet. Pick an outfit, then press Save look.", lc = C.muted, lw = 1 }
        return
    end
    local per = NROWS - #rows - 1
    local pages = math.max(1, math.ceil(#items / per))
    st.favPage = math.max(1, math.min(st.favPage, pages))
    for n = (st.favPage - 1) * per + 1, math.min(#items, st.favPage * per) do
        local it = items[n]
        local inUse = sameLook(it.e.picks, cur)
        rows[#rows + 1] = { label = n .. ".  " .. cut(it.e.name, 40), lc = inUse and C.accent or C.text, lw = 1,
            help = it.e.name .. (inUse and " (on now)" or ""),
            b = { btn("Use", function() useLook(it.e) end, true, inUse),
                  btn("Up", function() favMove(char, it.k, -1) end, n > 1, false, nil, "already first"),
                  btn("Down", function() favMove(char, it.k, 1) end, n < #items, false, nil, "already last"),
                  btn("Remove", function()
                      table.remove(W.favorites(), it.k)
                      W.saveFavorites()
                      say("removed from %s's favorites: %s", char, cut(it.e.name, 50))
                  end) } }
    end
    if pages > 1 then
        rows[#rows + 1] = { value = string.format("Page %d/%d", st.favPage, pages), vc = C.muted, vw = 2,
            b = { btn("< Page", function() st.favPage = st.favPage - 1 end, st.favPage > 1, false, nil, "first page"),
                  btn("Page >", function() st.favPage = st.favPage + 1 end, st.favPage < pages, false, nil, "last page") } }
    end
end

local function presetRows(rows)
    st.presets = st.presets or W.loadPresets()
    for i = 1, 8 do
        local p = st.presets[i]
        rows[#rows + 1] = { label = "Preset " .. i, value = cut(presetSummary(p), 40), vc = p and C.accent or C.muted,
            lw = 1.4, vw = 5,
            help = "Save stores every slot's current choice (presets.txt); Load applies it; Clear empties it. "
                .. (p and presetSummary(p) or ""),
            b = { btn("Load", function() presetLoad(i) end, p ~= nil, false, nil, "this preset is empty"),
                  btn("Save", function() presetSave(i) end),
                  btn("Clear", function() presetClear(i) end, p ~= nil, false, nil, "already empty") } }
    end
    local function abText(x) return st[x] and presetSummary(st[x]) or "empty" end
    rows[#rows + 1] = { label = "A/B", value = cut("A " .. abText("A") .. " | B " .. abText("B"), 44), vc = C.muted,
        lw = 1, vw = 5, help = "Store two looks and flip between them to compare.",
        b = { btn("Store A", function() storeAB("A") end, true, st.showing == "A"),
              btn("Store B", function() storeAB("B") end, true, st.showing == "B"),
              btn("Swap", swapAB, st.A ~= nil and st.B ~= nil, false, nil, "store both A and B first") } }
    rows[#rows + 1] = { help = "These act on every character (locked slots are kept).",
        b = { btn("Undo", undo, W.canUndo(), false, nil, "nothing to undo"),
              btn("Randomize all", function() local f = st.filter; st.filter = nil; randomize(); st.filter = f end),
              btn("All off, everyone", function() local f = st.filter; st.filter = nil; vanilla(); st.filter = f end) } }
end

local function settingRows(rows)
    local function toggle(key, label, after)
        return function()
            S[key] = not S[key]
            W.saveSettings()
            if after then after() end
            say("%s: %s", label, onoff(S[key]))
        end
    end
    local function stepper(key, label, d, lo, hi, unit, after)
        return function()
            S[key] = math.max(lo, math.min(hi, (S[key] or lo) + d))
            W.saveSettings()
            if after then after() end
            say("%s: %s%s", label, tostring(S[key]), unit)
        end
    end
    local function row(key, label, help, after)
        rows[#rows + 1] = { label = label, value = onoff(S[key]), vc = S[key] and C.good or C.muted, lw = 4, vw = 1.2,
            bw = 1.3, help = help, b = { btn("Switch", toggle(key, label, after)) } }
    end
    local function num(key, label, d, lo, hi, unit, help, after)
        rows[#rows + 1] = { label = label, value = tostring(S[key]) .. unit, lw = 4, vw = 1.2, bw = 0.65, help = help,
            b = { btn("-", stepper(key, label, -d, lo, hi, unit, after), (S[key] or lo) > lo),
                  btn("+", stepper(key, label, d, lo, hi, unit, after), (S[key] or hi) < hi) } }
    end
    local function reapply() W.rebuildActive(); W.applyAll() end
    row("scoping", "Character scoping",
        "ON: a slot tied to a character (e.g. 'Sciel outfit') only changes that character. OFF: every slot applies to everyone.", reapply)
    row("auto_apply", "Apply to new skins automatically",
        "Swap as soon as the game spawns a skin (battle, cutscene, menu). OFF: only menu changes, Fix look and Ctrl+F7 swap.")
    row("random_off", "Randomize may pick vanilla", "Let Randomize / Random choose 'vanilla' for a slot too.")
    row("match_groups", "Keep a mod's groups matched",
        "Picking a 'Lace dress' outfit switches that character's color to a 'Lace dress' color too (and back), "
        .. "as the mod needs matching pieces. Vanilla slots are left alone.")
    row("auto_wear", "Auto Wear",
        "ON: an outfit mod made for an outfit the character isn't wearing (Infernal Herald: Potato bag) is worn "
        .. "in place of the current outfit as soon as you pick it. OFF: it waits for that outfit; Wear on the row "
        .. "does it by hand.")
    row("show_technical", "Show technical slots (fix paks)",
        "Slots that change nothing you can see (e.g. a mod's Blueprint 'fix' pak) are hidden from Outfits, "
        .. "Randomize, All off and presets. They stay installed and selected as they are.",
        function() st.page = 1 end)
    rows[#rows + 1] = { label = "Slideshow / Peek seconds",
        value = string.format("%d s / %d s", S.slideshow_s or 4, S.peek_s or 3), lw = 3, vw = 1.3,
        help = "Seconds between the steps of a Slideshow (Outfits > Choose > Slides), and how long Peek hides the menu.",
        b = { btn("Slides -", stepper("slideshow_s", "Slideshow interval", -1, 1, 60, " s"), (S.slideshow_s or 4) > 1),
              btn("Slides +", stepper("slideshow_s", "Slideshow interval", 1, 1, 60, " s"), (S.slideshow_s or 4) < 60),
              btn("Peek -", stepper("peek_s", "Peek time", -1, 1, 15, " s"), (S.peek_s or 3) > 1),
              btn("Peek +", stepper("peek_s", "Peek time", 1, 1, 15, " s"), (S.peek_s or 3) < 15) } }
    rows[#rows + 1] = { label = "Menu side / scale", value = S.side .. " " .. tostring(S.scale) .. "%", lw = 4, vw = 1.6,
        help = "Put the menu on the left or right edge of the screen, and size it (it also shrinks to fit small screens).",
        b = { btn("Side", function()
                  S.side = S.side == "left" and "right" or "left"
                  W.saveSettings()
                  place(true)
                  say("menu side: %s", S.side)
              end, true, false, 0.9),
              btn("-", stepper("scale", "Menu scale", -10, 50, 200, "%", function() place(true) end), (S.scale or 100) > 50,
                  false, 0.6),
              btn("+", stepper("scale", "Menu scale", 10, 50, 200, "%", function() place(true) end), (S.scale or 100) < 200,
                  false, 0.6) } }
    rows[#rows + 1] = { label = "Mouse cursor / freeze camera", value = onoff(S.cursor) .. " / " .. onoff(S.block_look),
        lw = 4, vw = 1.6,
        help = "While the menu is open: show the cursor so the buttons can be clicked; stop mouse movement "
            .. "from turning the camera.",
        b = { btn("Cursor", toggle("cursor", "Show mouse cursor", reapplyInput), true, S.cursor),
              btn("Camera", toggle("block_look", "Freeze camera while open", reapplyInput), true, S.block_look) } }
    row("ui_input", "UI input mode (try if clicks fail)",
        "Switch the game to game+UI input while open; can help clicking. Other mods saw trouble with input modes in cutscenes.",
        reapplyInput)
    rows[#rows + 1] = { label = "Record session / auto report", value = onoff(W.recording()) .. " / " .. onoff(S.auto_report),
        vc = W.recording() and C.good or C.muted, lw = 4, vw = 1.6,
        help = "Record: live_log.txt records every click, key and what each one changed (attach report.txt, next to "
            .. "the mod, to show a session). Auto report: rewrite dump.txt + report.txt 4 s after each change "
            .. "(off by default; while recording, a report is also written at every game start; Report or Ctrl+F9 "
            .. "write one any time).",
        b = { btn("Record", function()
                  W.setRecord(not W.recording())
                  say("recording %s", W.recording() and "on (live_log.txt)" or "off")
              end, true, W.recording()),
              btn("Auto report", toggle("auto_report", "Auto report after changes"), true, S.auto_report) } }
    local sc = W.lastApplied()
    rows[#rows + 1] = { label = "Characters found last pass: " .. (sc and tostring(sc) or "?"), lw = 3,
        help = "Reload re-reads variants.lua and selection.txt. Dump writes dump.txt. Report writes report.txt "
            .. "next to the mod (ue4ss\\Mods\\E33Wardrobe): attach it when reporting a problem. Defaults resets these settings "
            .. "(locks and Wear stay).",
        b = { btn("Reload", function() W.reload(); say("reloaded variants.lua + selection.txt") end),
              btn("Dump", function() W.dump(); say("writing dump.txt next to the mod") end),
              btn("Report", function() W.report(); say("report.txt written next to the mod (Mods\\E33Wardrobe): attach it when reporting a problem") end),
              btn("Defaults", function()
                  local wasClean = S.clean
                  for k, v in pairs(W.defaults) do if k ~= "locks" and k ~= "wear" then S[k] = v end end
                  if wasClean and W.setClean then W.setClean(false) end    -- the masks back, not just the flag
                  W.setRecord(S.record)
                  W.saveSettings()
                  reapplyInput()
                  place(true)
                  reapply()
                  say("settings reset to defaults")
              end) } }
end

-- After a pick: how much of it is on screen once the pass ran, or why nothing changed.
local function pickResult(si)
    local slot = W.slots()[si]
    if not slot or W.variantIndex(slot) == 0 then return nil end
    if W.applyPending and W.applyPending() then return "applying...", C.muted end
    local state = stateOf(si)
    if state == "unused" then return "nothing on screen changed: " .. whyUnused(slot), C.warn end
    if state == "on" then
        if W.autoWorn and W.autoWorn(slot.id) and W.isWear(slot.id) then
            local char = charOf(slot)
            local _, under = wornName(char)
            return string.format("made for %s, so it is worn in place of %s (Auto Wear)",
                W.outfitName(W.targetOutfit(slot, char)) or "another outfit", under or "the current outfit"), C.good
        end
        local sh = W.slotShown and W.slotShown(slot.id)
        if sh and sh.total > 0 then return string.format("%d/%d pieces on screen", sh.shown, sh.total), C.good end
        return "on screen", C.good
    end
    local note = slotNote(si)
    if note == "hidden" then return "hidden by a later pick (see below)", C.muted end
    return nil
end

local function statusLine()
    local msg = st.msg
    if msg ~= "" and st.lastSlot then
        local r, col = pickResult(st.lastSlot)
        if r then return msg .. "  -  " .. r, col end
    end
    if msg ~= "" then return msg, C.text end
    if st.view == "outfits" and st.filter then
        local worn = wornName(st.filter)
        if not worn then return st.filter .. " is not loaded in this area: picks are saved and show when "
            .. st.filter .. " appears.", C.muted end
    end
    local n = 0
    for id in pairs(W.selection()) do
        for _, slot in ipairs(W.slots()) do if slot.id == id and visible(slot) then n = n + 1 end end
    end
    local applied = W.lastApplied()
    return string.format("%d mod slot(s) switched on%s", n,
        (applied or 0) > 0 and string.format(", applied to %d character(s)", applied)
            or " - no character loaded yet"), C.text
end

-- --------------------------------------------------------------------------- render

local function hasButtons(r) return r ~= nil and r.b ~= nil and #r.b > 0 end

local function fixFocus(rows)
    if not hasButtons(rows[st.row]) then
        local best
        for d = 1, #rows do
            if hasButtons(rows[st.row + d]) then best = st.row + d break end
            if hasButtons(rows[st.row - d]) then best = st.row - d break end
        end
        st.row = best or 1
    end
    if hasButtons(rows[st.row]) then st.col = math.max(1, math.min(st.col, #rows[st.row].b)) end
end

local function cellText(c, s, col, fill)
    if s == nil then setVis(c, COLLAPSED) return end
    setVis(c, HIT_INVISIBLE)
    setText(c, s)
    setColor(c, col)
    setFill(c, fill)
end

local function paint(rows)
    local status, scol = statusLine()
    setText(panel.status, cut(status, 220))     -- wraps to 2 lines
    setColor(panel.status, scol or C.text)
    local focusRow = rows[st.row]
    local help = focusRow and focusRow.help or ""
    if st.kbd or st.view == "settings" then help = help .. (help ~= "" and "\n" or "") .. keysHelp() end
    setText(panel.help, help)
    for r = 1, NROWS do
        local R, spec = panel.rows[r], rows[r]
        if not spec then
            setVis(R.box, COLLAPSED)
        else
            setVis(R.box, SELF_INVISIBLE)
            setBrush(R.bg, spec.bg or (st.kbd and r == st.row and C.rowFocus) or C.row)
            cellText(R.label, spec.label, spec.lc or C.text, spec.lw or 3)
            cellText(R.value, spec.value, spec.vc or C.accent, spec.vw or 3)
            for j = 1, NBTN do
                local B, b = R.btns[j], spec.b and spec.b[j]
                if not b then
                    setVis(B, COLLAPSED)
                else
                    setVis(B, VISIBLE)
                    setText(B.cap, b.t)
                    setEnabled(B, b.on)
                    local focused = st.kbd and r == st.row and j == st.col   -- the focus ring is for keyboard use
                    setBg(B, focused and C.focus or (b.hl and C.hl) or (b.on and C.btn) or C.off)
                    setColor(B.cap, focused and C.dark or ((b.on or b.hl) and C.text) or C.muted)
                    -- next to a label or value a button is as wide as its caption, so the
                    -- caption is never cut; rows of buttons only share the width
                    setFill(B, (spec.label or spec.value) and "auto" or (b.w or spec.bw or 1.25))
                end
            end
        end
    end
end

local function render(force)
    local rows = { tabsRow() }
    if st.view == "pick" then pickRows(rows)
    elseif st.view == "fav" then favRows(rows)
    elseif st.view == "presets" then presetRows(rows)
    elseif st.view == "settings" then settingRows(rows)
    else outfitRows(rows) end
    while #rows > NROWS do table.remove(rows) end
    st.rows = rows
    fixFocus(rows)
    paint(rows)
    if force then place(true) end
end

-- A drawing error closes the menu and is logged once, instead of repeating 20 times a second.
local function draw(force)
    local ok, err = pcall(render, force)
    if ok then return true end
    M.open, st.peekLeft = false, nil
    go("outfits")                               -- a broken view must not break every later open
    releaseInput()
    dropPanel()
    log("menu closed after an error while drawing it: %s", tostring(err))
    return false
end

-- --------------------------------------------------------------------------- open / close / events

function M.openMenu()
    local pc = playerController()
    if not valid(pc) then
        log("menu: no player controller yet - load a save first")
        return
    end
    if panel and not (valid(panel.host) and valid(panel.pc) and panel.pc:GetAddress() == pc:GetAddress()) then
        dropPanel()                             -- new map or new controller without a LoadMap hook
    end
    if not panel then
        sweep()
        local ok, res = pcall(build, pc)
        if not ok then
            log("menu could not be built: %s", tostring(res))
            return
        end
        panel = res
    end
    panel.host:SetVisibility(SELF_INVISIBLE)
    M.open = true
    st.presets = nil
    grabInput(pc)
    if draw(true) then log("menu open") end
end

function M.close()
    if not M.open then return end
    M.open, st.peekLeft = false, nil
    releaseInput()
    if panel and valid(panel.host) then pcall(function() panel.host:SetVisibility(COLLAPSED) end) end
    log("menu closed")
end

local function press(spec, how)
    if not spec then return end
    local row = st.rows[st.row] or {}
    W.live("menu %s: [%s] %s%s -> '%s'%s", how or "press", st.view, row.label or "", row.value and (" (" .. row.value .. ")") or "",
        spec.t, spec.on and "" or " (disabled)")
    if not spec.on then say("%s: %s", spec.t, spec.why or "not available right now") return end
    local ok, err = pcall(spec.fn)
    if not ok then
        say("error: %s", tostring(err))
        log("menu action '%s' failed: %s", spec.t, tostring(err))
    end
end

local function click()
    for r, spec in ipairs(st.rows) do
        local R = panel.rows[r]
        for j, b in ipairs(spec.b or {}) do
            local B = R and R.btns[j]
            if B then
                local ok, hovered = pcall(function() return B.w:IsHovered() end)
                if ok and hovered then
                    st.row, st.col = r, j
                    press(b, "click")
                    return
                end
            end
        end
    end
    local where = "outside the menu"
    for r in ipairs(st.rows) do
        local R = panel.rows[r]
        local ok, h = pcall(function() return R.bg.w:IsHovered() end)
        if ok and h then where = "on row " .. r .. " (" .. (st.rows[r].label or "") .. ") but not on a button" break end
    end
    if where == "outside the menu" then
        local ok, h = pcall(function() return panel.frame:IsHovered() end)
        if ok and h then where = "on the menu, not on a row" end
    end
    W.live("menu click: %s", where)
end

local function moveRow(d)
    local rows, n = st.rows, #st.rows
    local r = st.row
    for _ = 1, n do
        r = (r - 1 + d) % n + 1
        if hasButtons(rows[r]) then st.row = r return end
    end
end

local function handle(ev)
    if ev == "toggle" then
        if M.open then M.close() else M.openMenu() end
        return
    end
    if not (M.open and panel) then return end
    if st.peekLeft then                         -- any key / click ends a peek (the click itself is dropped)
        st.peekLeft = 0
        if ev == "click" then return end
    end
    if ev == "click" then st.kbd = false
    elseif not st.kbd then                      -- the first key only shows where the focus is
        st.kbd = true
        draw()
        return
    end
    local row = st.rows[st.row]
    if ev == "up" then moveRow(-1)
    elseif ev == "down" then moveRow(1)
    elseif ev == "left" or ev == "right" then
        if hasButtons(row) then st.col = (st.col - 1 + (ev == "right" and 1 or -1)) % #row.b + 1 end
    elseif ev == "ok" then press(hasButtons(row) and row.b[st.col] or nil, "key")
    elseif ev == "pgup" or ev == "pgdn" then
        local d = ev == "pgdn" and 1 or -1
        if st.view == "pick" then st.pickPage = st.pickPage + d
        elseif st.view == "fav" then st.favPage = st.favPage + d
        else st.page = st.page + d end
    elseif ev == "click" then click()
    end
    if W.flushPending then W.flushPending() end   -- apply what this event asked for, then draw
    if M.open then draw() end
end

local function tick()
    if M.open and not (panel and valid(panel.host) and valid(panel.pc)) then
        M.open = false
        releaseInput()                          -- gives cursor / camera back if the controller survived
        dropPanel()
        log("menu closed (level changed)")
    end
    local evs = queue
    queue = {}
    for _, ev in ipairs(evs) do handle(ev) end
    slideStep()
    if W.flushPending then W.flushPending() end   -- run the apply the clicks asked for, then draw
    if st.flash then
        st.flash.n = st.flash.n - 1
        if st.flash.n <= 0 then st.flash = nil end
    end
    if st.peekLeft then
        st.peekLeft = st.peekLeft - 1
        if st.peekLeft > 0 then return end
        st.peekLeft = nil
        if M.open and panel and valid(panel.host) then
            panel.host:SetVisibility(SELF_INVISIBLE)
            if valid(panel.pc) then grabInput(panel.pc) end
        end
    end
    if M.open then
        ticks = ticks + 1
        if draw(false) and ticks % 25 == 0 then place(false) end
    end
end

-- Events arrive on the game thread (main.lua's loop runs key callbacks there), so this is plain
-- bookkeeping; the menu is then drawn by main.lua's game-thread loop calling M.tick.
local function push(ev)
    if suspended and os.time() - suspendedAt > 60 then suspended = false end   -- missed post-load hook
    if suspended then return end
    if ev ~= "toggle" and not M.open then return end
    if #queue < 16 then queue[#queue + 1] = ev end
end

-- main.lua's game-thread loop: tick while open, while events wait, or while a slideshow runs.
function M.wantsTick() return (M.open or #queue > 0 or st.slide ~= nil) and not suspended end
function M.tick() tick() end

-- Registered from the game thread by main.lua. Widgets belong to the old world: drop them on a
-- map change, and drop queued work too. (Without these hooks the tick notices the dead widget.)
function M.registerHooks()
    if pcall(RegisterLoadMapPostHook, function() suspended = false end) then
        pcall(RegisterLoadMapPreHook, function()
            suspended, suspendedAt = true, os.time()
            queue, st.slide = {}, nil
            if M.open then
                M.open = false
                releaseInput()
            end
            dropPanel()
        end)
    end
end

function M.init(api)
    W, S, log, valid = api, api.settings, api.log, api.valid
    math.randomseed(os.time())
    loadLocks()
    local K = api.keys
    api.bind(K.menu, function() push("toggle") end)
    api.bind(K.menuUp, function() push("up") end)
    api.bind(K.menuDown, function() push("down") end)
    api.bind(K.menuLeft, function() push("left") end)
    api.bind(K.menuRight, function() push("right") end)
    api.bind(K.menuOk, function() push("ok") end)
    api.bind(K.menuPageUp, function() push("pgup") end)
    api.bind(K.menuPageDown, function() push("pgdn") end)
    -- Nothing binds UButton::OnClicked from Lua, so a click is matched against the hovered button.
    -- Dropped at once while the menu is closed.
    api.bind({ "LEFT_MOUSE_BUTTON", {} }, function() push("click") end, true)
    api.menu = M
    api.toggleMenu = function() push("toggle") end
end

return M
