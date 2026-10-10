--[[
E33Wardrobe - switch outfit-mod variants in game, for Clair Obscur: Expedition 33.
Documentation: README.md and docs/ in the project (link on the mod page). MIT licence.

Variant paks made by e33_relocate.py live at unique asset paths, so they are all installed
at once without replacing anything. This script does at runtime what installing one variant as a
replacer would do: every mesh, material and texture a character uses is looked up by its ORIGINAL
path in the table of picked variants (Scripts\variants.lua) and swapped for the relocated copy.

Keys (to change them, copy Scripts\config.example.lua to config.lua and edit it; updates never touch config.lua):
  Delete                    open / close the in-game menu (Scripts\menu.lua)
  Ctrl+Up/Down, Ctrl+Left/Right, Ctrl+Enter, Ctrl+PageUp/PageDown   drive the menu from the keyboard
  Ctrl+F7                   apply the picks to everyone again
  Ctrl+F8                   reload selection.txt + variants.lua
  Ctrl+F9                   write dump.txt + report.txt
Console (UE4SS or game console): wardrobe | wardrobe menu | wardrobe <slot#> <variant#|off> | wardrobe apply
  | wardrobe reload | wardrobe dump | wardrobe report | wardrobe fix | wardrobe clean [off]

Threading: all work runs in one game-thread loop (LoopInGameThreadWithDelay), started by a single
ExecuteInGameThread at load. Key binds only post to an inbox; hooks already run on the game thread.
Nothing is queued to the game thread from another thread (see "threading" below).
]]

local MOD = "E33Wardrobe"
local VERSION = "1.0.0"                         -- the same as tools/e33common.py VERSION
local KEYS = {
    menu = { "DEL", {} },
    menuUp = { "UP_ARROW", { "CONTROL" } }, menuDown = { "DOWN_ARROW", { "CONTROL" } },
    menuLeft = { "LEFT_ARROW", { "CONTROL" } }, menuRight = { "RIGHT_ARROW", { "CONTROL" } },
    menuOk = { "RETURN", { "CONTROL" } }, menuPageUp = { "PAGE_UP", { "CONTROL" } },
    menuPageDown = { "PAGE_DOWN", { "CONTROL" } },
    nextSlot = { "F5", { "CONTROL" } }, prevSlot = { "F5", { "CONTROL", "SHIFT" } },
    nextVariant = { "F6", { "CONTROL" } }, prevVariant = { "F6", { "CONTROL", "SHIFT" } },
    apply = { "F7", { "CONTROL" } }, reload = { "F8", { "CONTROL" } }, dump = { "F9", { "CONTROL" } },
}

local liveSink                                  -- set once the session log is open

local function log(fmt, ...)
    local ok, msg = pcall(string.format, fmt, ...)
    msg = ok and msg or tostring(fmt)
    print("[" .. MOD .. "] " .. msg .. "\n")
    if liveSink then liveSink(msg) end
end

local scriptDir = (debug.getinfo(1, "S").source:match("^@(.*[\\/])")) or ""
local CONFIG_OUTFIT_NAMES = nil
do
    local ok, cfg = pcall(dofile, scriptDir .. "config.lua")
    if not ok and io.open(scriptDir .. "config.lua", "r") then
        print("[E33Wardrobe] config.lua has an error, so the default keys are used: " .. tostring(cfg) .. "\n")
    end
    if ok and type(cfg) == "table" and type(cfg.keys) == "table" then
        for k, v in pairs(cfg.keys) do KEYS[k] = v end
    end
    if ok and type(cfg) == "table" and type(cfg.outfit_names) == "table" then CONFIG_OUTFIT_NAMES = cfg.outfit_names end
end
local modDir = (scriptDir:gsub("([\\/])[Ss]cripts[\\/]$", "%1"))
local FILES = { SEL = modDir .. "selection.txt", DUMP = modDir .. "dump.txt", SETTINGS = modDir .. "settings.txt",
                PRESETS = modDir .. "presets.txt", LIVE = modDir .. "live_log.txt",
                LIVE_PREV = modDir .. "live_log_previous.txt", REPORT = modDir .. "report.txt" }

-- Runtime settings, changed from the menu and kept in settings.txt.
local SETTINGS = { scoping = true, auto_apply = true, recheck_ms = 700, side = "right", scale = 100,
                   block_look = true, cursor = true, ui_input = false, legacy_keys = false,
                   random_off = false, slideshow_s = 4, locks = "", wear = "", match_groups = true,
                   record = true, auto_report = false, show_technical = false, tab = "", peek_s = 3,
                   auto_wear = true, clean = false }
local DEFAULT_SETTINGS = {}
for k, v in pairs(SETTINGS) do DEFAULT_SETTINGS[k] = v end

local function loadSettings()
    local f = io.open(FILES.SETTINGS, "r")
    if not f then return end
    for line in f:lines() do
        local k, v = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
        if k and SETTINGS[k] ~= nil then
            if type(SETTINGS[k]) == "boolean" then SETTINGS[k] = (v == "true")
            elseif type(SETTINGS[k]) == "number" then
                local n = tonumber(v)
                SETTINGS[k] = n and math.tointeger(math.floor(n)) or SETTINGS[k]
            else SETTINGS[k] = v end
        end
    end
    f:close()
end

local savedSettings = {}

local function saveSettings()
    for k, v in pairs(SETTINGS) do
        if savedSettings[k] ~= nil and savedSettings[k] ~= v and liveSink then
            liveSink(string.format("setting %s = %s", k, tostring(v)))
        end
        savedSettings[k] = v
    end
    local f = io.open(FILES.SETTINGS, "w")
    if not f then return end
    local keys = {}
    for k in pairs(SETTINGS) do keys[#keys + 1] = k end
    table.sort(keys)
    for _, k in ipairs(keys) do f:write(k, " = ", tostring(SETTINGS[k]), "\n") end
    f:close()
end
loadSettings()

-- --------------------------------------------------------------------------- session recorder
-- live_log.txt records every interaction (menu clicks and keys, console, settings) and every
-- response (what each pass changed, skin spawns, map loads, errors) with a timestamp, so a test
-- session can be read back without having pressed anything at the right moment. The previous
-- session is kept as live_log_previous.txt. dump.txt and report.txt (everything in one file)
-- refresh a few seconds after the last change. Settings > "Record session" switches it off.
local REC = { max = 20 * 1024 * 1024, bytes = 0, seq = 0, opened = false }   -- recorder counters
local liveF = nil

local function live(fmt, ...)
    if not liveF then return end
    local ok, msg = pcall(string.format, fmt, ...)
    msg = ok and msg or tostring(fmt)
    REC.seq = REC.seq + 1
    local line = string.format("%s #%d %s\n", os.date("%H:%M:%S"), REC.seq, msg)
    REC.bytes = REC.bytes + #line
    if REC.bytes > REC.max then
        liveF:write("(live log reached 20 MB; later events only go to UE4SS.log)\n")
        liveF:close()
        liveF = nil
        return
    end
    liveF:write(line)
    liveF:flush()
end

local function openLive()
    if liveF or not SETTINGS.record then return end
    if REC.opened then                          -- switched on again: append, keep the previous session
        liveF = io.open(FILES.LIVE, "a")
        live("recording switched on")
        return
    end
    REC.opened = true
    os.remove(FILES.LIVE_PREV)
    os.rename(FILES.LIVE, FILES.LIVE_PREV)
    liveF = io.open(FILES.LIVE, "w")
    REC.bytes, REC.seq = 0, 0
    live("session start %s", os.date("%Y-%m-%d %H:%M:%S"))
end

local function closeLive()
    if liveF then
        live("recording switched off")
        liveF:close()
        liveF = nil
    end
end

openLive()
liveSink = function(msg) live("log: %s", msg) end
for k, v in pairs(SETTINGS) do savedSettings[k] = v end

local liveCtx, passChanges = "", 0             -- which actor/component a pass is working on
local function change(fmt, ...)
    passChanges = passChanges + 1
    if liveF then
        local ok, msg = pcall(string.format, fmt, ...)
        live("  change %s: %s", liveCtx, ok and msg or tostring(fmt))
    end
end

-- --------------------------------------------------------------------------- threading
--[[
Threading rules, from an audit of this UE4SS build's source (RE-UE4SS 527a483b):
  * The game thread runs every hook and queued action of this mod on ONE shared Lua stack, and
    Lua's lock is released during every engine call. Calling ExecuteInGameThread / LoopAsync /
    ExecuteWithDelay from another thread (key binds, async loops) races with it: that is the
    "Ref was not function" in UE4SS.log (UE4SS issues #1180 / #1445). From inside a game-thread
    callback, queuing is safe in this build.
  * So after start-up nothing is queued from another thread:
      - key binds only append to INBOX (plain Lua, no UE4SS call);
      - one game-thread loop (LoopInGameThreadWithDelay, every TICK_MS) drains INBOX, runs the
        mod's own timers (later()), the menu and the debounced apply pass, and sets the
        heartbeat the watchdog reads;
      - hooks are registered from the game thread (the last statement of this file).
  * The watchdog's async loop only reads a number and writes the log file.
Builds without LoopInGameThreadWithDelay have no safe way to do this: the mod stays off there and says so.
]]
local TICK_MS = 50
local HAS_GT_LOOP = type(LoopInGameThreadWithDelay) == "function"
local gtDepth = 0
local GT_STATE, GT_STATE_SINCE, GT_BEAT = "idle", os.time(), os.time()   -- read by the watchdog
local INBOX = {}                -- events or functions posted from other threads
local SCHED = {}                -- the mod's game-thread timers: { due = loop tick, f = function }
local loopTicks = 0
local atCallbackEnd = {}

local function onGameThread()
    if type(IsInGameThread) == "function" then
        local ok, r = pcall(IsInGameThread)
        if ok and type(r) == "boolean" then return r end
    end
    return gtDepth > 0
end

local function post(ev)                         -- any thread: plain Lua only
    if #INBOX < 64 then INBOX[#INBOX + 1] = ev end
end

local function runCallbackEnd()                  -- e.g. the apply pass requested by a click
    local guard = 0
    while #atCallbackEnd > 0 and guard < 8 do
        guard = guard + 1
        local todo = atCallbackEnd
        atCallbackEnd = {}
        for _, g in ipairs(todo) do
            local ok2, err2 = pcall(g)
            if not ok2 then log("error: %s", tostring(err2)) end
        end
    end
end

local function onGT(f, ...)
    gtDepth = gtDepth + 1
    if gtDepth == 1 then GT_STATE, GT_STATE_SINCE = "mod work", os.time() end
    local ok, err = pcall(f, ...)
    if gtDepth == 1 then
        runCallbackEnd()
        GT_STATE, GT_STATE_SINCE = "idle", os.time()
    end
    gtDepth = gtDepth - 1
    if not ok then log("error: %s", tostring(err)) end
end

-- Run f on the game thread: now if already there, else via the loop's inbox.
local function inGame(f)
    if onGameThread() then onGT(f) else post(f) end
end

-- Run f on the game thread after ms. Call from the game thread (hooks, the loop, the menu).
local function later(ms, f)                     -- run f in the game-thread loop about ms from now
    SCHED[#SCHED + 1] = { due = loopTicks + math.max(1, math.ceil(ms / TICK_MS)), f = f }
end
local delayGT = later

-- --------------------------------------------------------------------------- data

local SLOTS, TO_ORIGINAL = {}, {}
local MOD_ONLY = {}           -- original paths (lower) that exist only in mods, never in the game
local selection = {}          -- slot id -> variant id
local PICK, pickCounter = {}, 0   -- slot id -> when it was picked: where variants overlap, the later pick wins
local MAPPED_MESH = {}        -- lower-case original and relocated paths of skeletal meshes variants replace
local APPLIED = {}            -- lower-case original -> { variant id = true }: whose version was applied (last full pass)
local function markApplied(okey, vid)
    local t = APPLIED[okey]
    if not t then t = {} APPLIED[okey] = t end
    t[vid or "?"] = true
end
local function appliedBy(okey, vid)
    local t = APPLIED[okey]
    return t ~= nil and t[vid] == true
end
local PASS = { full = 0, last = nil, queued = false, why = {}, debounce = 4, due = nil, autoGen = 0 }
-- full: full passes so far; last: actors the last pass handled; queued: a pass is queued (fallback
-- path); why: reasons merged into the next pass; debounce: ~200 ms in loop ticks; due: tick of the
-- next pass; autoGen: auto-report generation
local currentSlot = 1
local ACTIVE_CACHE = {}       -- character (or "*") -> { [orig:lower()] = {pkg, obj, class} }

local CHAR_ALIASES = { frey = "Gustave", noah = "Gustave", gustave = "Gustave", lune = "Lune", sciel = "Sciel",
                       maelle = "Maelle", verso = "Verso", monoco = "Monoco" }

local function loadVariants()
    SLOTS, TO_ORIGINAL, MOD_ONLY, MAPPED_MESH = {}, {}, {}, {}
    -- variants.lua is data: it runs without access to io, os or anything else
    local ok, data = false, "missing"
    local vf = io.open(scriptDir .. "variants.lua", "r")
    if vf then
        local src = vf:read("a")
        vf:close()
        local chunk, err = load(src, "=variants.lua", "t", {})
        if chunk then ok, data = pcall(chunk) else data = err end
    end
    if not ok or type(data) ~= "table" then
        log("variants.lua missing or invalid (%s). Run e33_relocate.py first.", tostring(data))
        return
    end
    for _, mod in ipairs(data) do
        for _, slot in ipairs(type(mod) == "table" and mod.slots or {}) do
            slot.mod = slot.mod or mod.mod
            slot.variants = slot.variants or {}
            table.insert(SLOTS, slot)
            for _, v in ipairs(slot.variants or {}) do
                v.map = v.map or {}
                if (v.label or "") == "" then v.label = "on" end
                for orig, e in pairs(v.map or {}) do
                    TO_ORIGINAL[e[1]:lower()] = orig
                    if e[4] == false then MOD_ONLY[orig:lower()] = true end
                    if e[3] == "SkeletalMesh" then
                        MAPPED_MESH[orig:lower()] = true
                        MAPPED_MESH[e[1]:lower()] = true
                    end
                end
            end
        end
    end
    log("loaded %d slot(s)", #SLOTS)
end

local function loadSelection()
    selection, PICK, pickCounter = {}, {}, 0
    local f = io.open(FILES.SEL, "r")
    if not f then return end
    for line in f:lines() do                    -- lines are in pick order
        local k, v = line:match("^(.-)\t(.*)$")
        if k and v and v ~= "" then
            selection[k] = v
            pickCounter = pickCounter + 1
            PICK[k] = pickCounter
        end
    end
    f:close()
end

local AUTOWEAR_PENDING = {}     -- slot id -> true: picked; after the pass, wear it if its mesh doesn't show
local AUTO_WORN = {}            -- slot id -> true: Wear was switched on by Auto Wear (for the menu)

local function picked(id)
    pickCounter = pickCounter + 1
    PICK[id] = pickCounter
    AUTOWEAR_PENDING[id] = true
end

local function saveSelection()
    local f = io.open(FILES.SEL, "w")
    if not f then log("cannot write %s", FILES.SEL) return end
    local ids = {}
    for k in pairs(selection) do ids[#ids + 1] = k end
    table.sort(ids, function(a, b) return (PICK[a] or 0) < (PICK[b] or 0) end)
    for _, k in ipairs(ids) do f:write(k, "\t", selection[k], "\n") end
    f:close()
end

local FORCE_CACHE = {}        -- character -> mesh worn over any outfit (or false)

local function rebuildActive() ACTIVE_CACHE = {} FORCE_CACHE = {} end

-- "Wear over any outfit": slots whose variant mesh replaces the outfit the character wears now,
-- instead of only the outfit the mod was made for (Infernal Herald = Potato bag outfit, etc.).
local function wearSet()
    local t = {}
    for id in (SETTINGS.wear or ""):gmatch("[^|]+") do t[id] = true end
    return t
end

local function anyActive()
    for _ in pairs(selection) do return true end
    return false
end

-- Variant table for one character: slots for other characters are skipped, so a "Lune outfit"
-- variant never changes Sciel even though vanilla Lune and Sciel share the Chic mesh. If the
-- character can't be told, only slots that aren't tied to a character apply.
local function activeFor(char)
    local key = char or "*"
    local a = ACTIVE_CACHE[key]
    if a then return a end
    a = {}
    local order = {}
    for i, slot in ipairs(SLOTS) do order[#order + 1] = { slot = slot, i = i } end
    table.sort(order, function(x, y)            -- the later pick wins where variants overlap
        local px, py = PICK[x.slot.id] or 0, PICK[y.slot.id] or 0
        if px ~= py then return px < py end
        return x.i < y.i
    end)
    for _, o in ipairs(order) do
        local slot = o.slot
        if slot.character == nil or slot.character == char or not SETTINGS.scoping then
            local vid = selection[slot.id]
            for _, v in ipairs(slot.variants) do
                if v.id == vid then
                    -- an outfit mod (it brings a skeletal mesh) applies to a body as a whole:
                    -- its textures and materials only where its mesh is shown (see forOutfit)
                    local meshes
                    for orig, e in pairs(v.map) do
                        if e[3] == "SkeletalMesh" then meshes = meshes or {} meshes[orig:lower()] = true end
                    end
                    for orig, e in pairs(v.map) do
                        local k = orig:lower()
                        -- under: the earlier pick's entry for the same asset, used where this one
                        -- doesn't apply (forOutfit)
                        a[k] = { pkg = e[1], obj = e[2], class = e[3], meshes = meshes, vid = v.id, under = a[k] }
                    end
                end
            end
        end
    end
    ACTIVE_CACHE[key] = a
    return a
end

-- The variant table for one body component showing `mesh`: entries of outfit mods whose mesh
-- isn't this one are left out. A body mod's textures then stay off Chic's skin material
-- (they belong with its own body mesh), and come back off when Lune changes outfit.
local BY_MESH = setmetatable({}, { __mode = "k" })
local function forOutfit(active, meshPath)
    local mo = meshPath and (TO_ORIGINAL[meshPath:lower()] or meshPath):lower() or ""
    local per = BY_MESH[active]
    if not per then per = {} BY_MESH[active] = per end
    local f = per[mo]
    if f then return f end
    f = {}
    for k, e in pairs(active) do
        while e and e.meshes and not e.meshes[mo] do e = e.under end
        f[k] = e
    end
    per[mo] = f
    return f
end

-- Mesh to put on a character's body over whatever outfit it wears: the selected variant's
-- skeletal mesh in a "wear" slot tied to that character (the later pick wins).
local function forcedFor(char)
    if not char then return nil end
    local f = FORCE_CACHE[char]
    if f ~= nil then return f or nil end
    local wear, best, bestPick = wearSet(), false, -1
    for _, slot in ipairs(SLOTS) do
        if wear[slot.id] and slot.character == char and (PICK[slot.id] or 0) > bestPick then
            local vid = selection[slot.id]
            for _, v in ipairs(slot.variants) do
                if v.id == vid then
                    local pick
                    for orig, e in pairs(v.map) do
                        if e[3] == "SkeletalMesh" then
                            local o = orig:lower()
                            local score = (o:find("/customization/skin/", 1, true) or o:find("_placeholder", 1, true)) and 2 or 1
                            if not pick or score > pick.score then pick = { pkg = e[1], obj = e[2], score = score, vid = v.id } end
                        end
                    end
                    if pick then best, bestPick = pick, PICK[slot.id] or 0 end
                end
            end
        end
    end
    FORCE_CACHE[char] = best
    return best or nil
end

-- --------------------------------------------------------------------------- UE helpers

local function valid(o)
    if o == nil or type(o) ~= "userdata" and type(o) ~= "table" then return false end
    local ok, r = pcall(function() return o:IsValid() end)
    return ok and r == true
end

-- "/Game/A/B" for a top-level asset ("Class /Game/A/B.B"). Subobjects such as the game's
-- dynamic material instances ("... /Game/Map.Map:PersistentLevel.Actor.Comp.MID_0") and
-- transient objects return nil.
local function pkgPath(obj)
    if not valid(obj) then return nil end
    local ok, full = pcall(function() return obj:GetFullName() end)
    if not ok or not full then return nil end
    local path, rest = full:match("^%S+%s+([^%.:]+)%.(.*)$")
    if not path or path:sub(1, 1) ~= "/" or rest:find("[%.:]") then return nil end
    if path:find("^/Engine/Transient") or path:find("^/Temp/") then return nil end
    return path
end

local function fullPath(obj)
    local ok, full = pcall(function() return obj:GetFullName() end)
    return ok and full and full:match("^%S+%s+(.+)$") or nil
end

local function fname(s)
    if EFindName ~= nil then
        local ok, n = pcall(FName, s, EFindName.FNAME_Add)
        if ok and n then return n end
    end
    return FName(s)
end

local function leafName(obj)
    local ok, n = pcall(function() return obj:GetFName():ToString() end)
    return ok and n or nil
end

-- Both kinds of arrays: TArray properties (userdata with ForEach) and UFunction return
-- values (plain Lua tables of RemoteUnrealParam that need :get()).
local function arrayItems(arr)
    local out = {}
    if arr == nil then return out end
    if type(arr) == "table" and arr.ForEach == nil then
        for _, e in ipairs(arr) do
            local ok, v = pcall(function() return e:get() end)
            out[#out + 1] = (ok and v ~= nil) and v or e
        end
        return out
    end
    pcall(function() arr:ForEach(function(_, e) if e ~= nil then out[#out + 1] = e:get() end end) end)
    return out
end

-- Relocated assets are not in the game's AssetRegistry.bin, which UE4SS's LoadAsset relies on.
-- AssetRegistryHelpers.GetAsset loads straight from the package path (the method UE4SS's own
-- BPModLoaderMod uses for mod assets), so it is tried first.
local ARH, FAILED = nil, {}
local function loadObj(pkg, obj)
    local full = pkg .. "." .. obj
    local o = StaticFindObject(full)
    if valid(o) then return o end
    if FAILED[full] then return nil end
    if liveF then live("    loading %s", full) end
    local t0 = os.clock()
    if not valid(ARH) then ARH = StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers") end
    if valid(ARH) then
        local ok, r = pcall(function() return ARH:GetAsset({ PackageName = fname(pkg), AssetName = fname(obj) }) end)
        if ok and valid(r) then
            if liveF then live("    loaded (%d ms)", math.floor((os.clock() - t0) * 1000 + 0.5)) end
            return r
        end
    end
    pcall(LoadAsset, full)
    o = StaticFindObject(full)
    if valid(o) then return o end
    FAILED[full] = true
    log("could not load %s", full)
    return nil
end

local CLS = {}
local function cls(path)
    if not valid(CLS[path]) then CLS[path] = StaticFindObject(path) end
    return CLS[path]
end

local function isA(o, path)
    local c = cls(path)
    if not valid(c) then return false end
    local ok, r = pcall(function() return o:IsA(c) end)
    return ok and r
end

-- --------------------------------------------------------------------------- character

local function normChar(s)
    if not s then return nil end
    s = tostring(s):lower()
    for k, v in pairs(CHAR_ALIASES) do
        if s == k or s:find("^" .. k .. "[^%a]") or s:find("[^%a]" .. k .. "$") or s:find("[^%a]" .. k .. "[^%a]") then
            return v
        end
    end
    return nil
end

-- Characters named in a mod name, label or asset path ("Lune - Infernal Herald", "ScielBodyLight",
-- "/Game/Characters/Heros/Sciel/SK_Sciel_Placeholder"). Returns a set and its size.
local function charsIn(text)
    local found, n = {}, 0
    local t = tostring(text or ""):gsub("(%l)(%u)", "%1 %2"):lower()
    for k, v in pairs(CHAR_ALIASES) do
        if t == k or t:find("^" .. k .. "[^%a]") or t:find("[^%a]" .. k .. "$") or t:find("[^%a]" .. k .. "[^%a]") then
            if not found[v] then found[v] = true n = n + 1 end
        end
    end
    return found, n
end

local function onlyChar(text)
    local found, n = charsIn(text)
    if n == 1 then return (next(found)) end
    return nil
end

-- Slots without a character get one from their own name, then the mod's name, then (when one
-- character clearly dominates) the paths of the assets they replace. Characters share assets
-- (Lune wears Maelle's hair), so names come first.
local function inferCharacters()
    for _, slot in ipairs(SLOTS) do
        if not slot.character then
            local short = slot.label or ""
            if slot.mod and short:sub(1, #slot.mod + 2) == slot.mod .. ": " then short = short:sub(#slot.mod + 3) end
            local c = onlyChar(short) or onlyChar(slot.mod)
            if not c then
                local votes, total = {}, 0
                for _, v in ipairs(slot.variants or {}) do
                    for orig in pairs(v.map or {}) do
                        local ch = onlyChar(orig)
                        if ch then
                            votes[ch] = (votes[ch] or 0) + 1
                            total = total + 1
                        end
                    end
                end
                for ch, k in pairs(votes) do if total > 0 and k * 3 >= total * 2 then c = ch end end
            end
            if c then
                slot.character = c
                slot.inferred = true
            end
        end
    end
end

local CHAR_OF = {}            -- actor address -> {name = full name, char = character} (from assign hooks)

local function propString(o, name)
    local ok, v = pcall(function() return o[name] end)
    if not ok or v == nil then return nil end
    if type(v) == "string" then return v end
    local ok2, s = pcall(function() return v:ToString() end)
    if ok2 and type(s) == "string" then return s end
    return nil
end

local function ownerOf(actor)
    local ok, o = pcall(function() return actor:GetOwner() end)
    if ok and valid(o) then return o end
    ok, o = pcall(function() return actor:GetAttachParentActor() end)
    if ok and valid(o) then return o end
    return nil
end

local function characterOf(actor)
    local known = CHAR_OF[actor:GetAddress()]
    if known then
        local ok, n = pcall(function() return actor:GetFullName() end)
        if ok and n == known.name then return known.char end
        CHAR_OF[actor:GetAddress()] = nil            -- address reused by a new object
    end
    local c
    -- cinematic pawns name their character on their skin component
    for _, comp in ipairs({ "BP_CinematicCharacterSkinComponent", "CinematicCharacterSkinComponent" }) do
        local ok, sc = pcall(function() return actor[comp] end)
        if ok and valid(sc) then
            c = normChar(propString(sc, "CharacterHardcodedName"))
            if c then return c end
        end
    end
    local owner = ownerOf(actor)
    for _, o in ipairs({ owner, actor }) do
        if valid(o) then
            for _, prop in ipairs({ "CharacterHardcodedName", "HardcodedNameID", "CharacterName" }) do
                c = normChar(propString(o, prop))
                if c then return c end
            end
            local okd, data = pcall(function() return o.CharacterData end)
            if okd and valid(data) then
                c = normChar(propString(data, "HardcodedNameID"))
                if c then return c end
            end
        end
    end
    -- last resort: exactly one character name in the skin class path (e.g. ".../Lune/BP_..._C")
    local okc, clsObj = pcall(function() return actor:GetClass() end)
    if okc and valid(clsObj) then
        local p = (fullPath(clsObj) or ""):lower()
        local only
        for k, v in pairs(CHAR_ALIASES) do
            if p:find("[^%a]" .. k .. "[^%a]") then
                if only and only ~= v then return nil end
                only = v
            end
        end
        return only
    end
    return nil
end

-- --------------------------------------------------------------------------- remapping

-- Desired asset for something that currently uses `path`. Returns pkg, obj, mode:
--   mode "map"     -> a selected variant's relocated copy
--   mode "orig"    -> no variant selected: back to the game's own asset at the original path
--   mode "default" -> it belongs to a variant that isn't selected and has no game counterpart
--                     (mod-only asset): the caller falls back to the vanilla setup
--   nil            -> keep what is there
-- Paths are compared case-insensitively, like Unreal does.
local function wanted(active, path, objName)
    local key = path:lower()
    local orig = TO_ORIGINAL[key]
    local okey = orig and orig:lower() or key
    local a = active[okey]
    if a then
        markApplied(okey, a.vid)
        if a.pkg:lower() ~= key then return a.pkg, a.obj, "map" end
        return nil
    end
    if MOD_ONLY[okey] then return nil, nil, "default" end
    if orig then return orig, objName, "orig" end
    return nil
end


-- Asset that belongs to some variant (a relocated copy, or a mod-only original from the shared pak).
local function variantOwned(obj)
    local p = pkgPath(obj)
    if not p then return false end
    local k = p:lower()
    return TO_ORIGINAL[k] ~= nil or MOD_ONLY[k] == true
end

local function isMID(m) return valid(m) and isA(m, "/Script/Engine.MaterialInstanceDynamic") end

local GLOBAL_PARAMETER = 2                     -- EMaterialParameterAssociation::GlobalParameter

local function textureParams(mat)              -- key -> {info, tex}, child values win
    local out, guard = {}, 0
    local m = mat
    while valid(m) and guard < 8 do
        guard = guard + 1
        local ok, arr = pcall(function() return m.TextureParameterValues end)
        if ok and arr then
            for _, tp in ipairs(arrayItems(arr)) do
                local okn, info = pcall(function()
                    local pi = tp.ParameterInfo
                    local okA, assoc = pcall(function() return pi.Association end)
                    local okI, index = pcall(function() return pi.Index end)
                    return { name = pi.Name, assoc = okA and assoc or nil, index = okI and index or nil }
                end)
                if okn and info and info.name then
                    local key = info.name:ToString() .. "|" .. tostring(info.assoc) .. "|" .. tostring(info.index)
                    if out[key] == nil then out[key] = { info = info, tex = tp.ParameterValue } end
                end
            end
        end
        local okp, parent = pcall(function() return m.Parent end)
        if not okp then break end
        m = parent
    end
    return out
end

local function scalarParams(mat)               -- name -> value, child values win
    local out, guard, m = {}, 0, mat
    while valid(m) and guard < 8 do
        guard = guard + 1
        local ok, arr = pcall(function() return m.ScalarParameterValues end)
        if ok and arr then
            for _, p in ipairs(arrayItems(arr)) do
                local okn, name, v = pcall(function() return p.ParameterInfo.Name:ToString(), p.ParameterValue end)
                if okn and name and out[name] == nil then out[name] = v end
            end
        end
        local okp, parent = pcall(function() return m.Parent end)
        if not okp then break end
        m = parent
    end
    return out
end

local function setTexture(mid, info, tex)
    if info.assoc ~= nil and info.assoc ~= GLOBAL_PARAMETER then
        local ok = pcall(function()
            mid:SetTextureParameterValueByInfo({ Name = info.name, Association = info.assoc, Index = info.index }, tex)
        end)
        if ok then return end
    end
    pcall(function() mid:SetTextureParameterValue(info.name, tex) end)
end

-- Copy the game's scalar/vector settings (wetness, opacity, dirt...) onto a replacement
-- instance. Textures are NOT copied: the variant's material brings its own (CNS lesson).
local function copyParams(fromMid, toMid)
    pcall(function()
        for _, p in ipairs(arrayItems(fromMid.ScalarParameterValues)) do
            toMid:SetScalarParameterValue(p.ParameterInfo.Name, p.ParameterValue)
        end
    end)
    pcall(function()
        for _, p in ipairs(arrayItems(fromMid.VectorParameterValues)) do
            local c = p.ParameterValue
            toMid:SetVectorParameterValue(p.ParameterInfo.Name, { R = c.R, G = c.G, B = c.B, A = c.A })
        end
    end)
end

-- The game keeps its own list of the skin's dynamic instances and drives effects through it;
-- point those lists at our replacement so the effects keep working on swapped slots.
local function replaceTracked(actor, oldMid, newMid)
    if not valid(oldMid) then return end
    local oldAddr = oldMid:GetAddress()
    local holders = {}
    local owner = ownerOf(actor)
    for _, o in ipairs({ owner, actor }) do
        if valid(o) then
            for _, compName in ipairs({ "BP_CharacterSkinComponent", "BP_CinematicCharacterSkinComponent" }) do
                local ok, c = pcall(function() return o[compName] end)
                if ok and valid(c) then table.insert(holders, { c, "CurrentCharacterSkinMaterialInstances" }) end
            end
            table.insert(holders, { o, "AllMeshMaterials" })
        end
    end
    for _, h in ipairs(holders) do
        pcall(function()
            local arr = h[1][h[2]]
            local n = arr:GetArrayNum()
            for i = 1, n do
                local e = arr[i]
                if valid(e) and e:GetAddress() == oldAddr then arr[i] = newMid end
            end
        end)
    end
end

local function makeMID(actor, comp, slot, parent, copyFrom)
    local ok, mid = pcall(function() return comp:CreateDynamicMaterialInstance(slot, parent, FName("None")) end)
    if not ok or not valid(mid) then return nil end
    if copyFrom then
        copyParams(copyFrom, mid)
        replaceTracked(actor, copyFrom, mid)
    end
    return mid
end

-- Material that should end up on slot i. `meshDefault`/`oldDefault` are the new/previous mesh's
-- own materials for the slot; `meshChanged` says the mesh was swapped in this pass.
local function chooseMaterial(active, base, meshDefault, oldDefault, meshChanged)
    local bpath = pkgPath(base)
    if not bpath then return nil end
    local p, o, mode = wanted(active, bpath, leafName(base))
    if meshChanged and meshDefault then
        -- The slot showed the old mesh's own material (the game builds its instances from the
        -- mesh), or a material left over from another variant: follow the new mesh, as a
        -- respawn with the replacer installed would. Blueprint-set materials stay.
        -- Checked before the variant's own remap: on a fresh skin the slot shows the game's
        -- instance of the OLD mesh's material (vanilla Bottom), and the new mesh may want another
        -- one there (a barefoot variant: Hide_Material on the boots' slot). Remapping the old
        -- material instead left boot parts visible (PC). fixSlot remaps the mesh's choice.
        if (oldDefault and pkgPath(oldDefault) == bpath) or variantOwned(base) then
            if pkgPath(meshDefault) ~= bpath then return meshDefault end
            if mode ~= "map" then return nil end      -- same material: only a variant's remap
        end
    end
    if mode == "map" then return loadObj(p, o) end
    if mode == "orig" then return loadObj(p, o) or meshDefault end
    if mode == "default" then return meshDefault end    -- mod-only material of an unselected variant
    return nil
end

local function fixSlot(actor, active, comp, i, meshDefault, oldDefault, meshChanged)
    local ok, mat = pcall(function() return comp:GetMaterial(i) end)
    if not ok or not valid(mat) then return end
    local mid = isMID(mat) and mat or nil
    local base = mid and mat.Parent or mat
    local target = chooseMaterial(active, base, meshDefault, oldDefault, meshChanged)
    if target and pkgPath(target) and pkgPath(target) == pkgPath(base) then target = nil end   -- already right
    if target and valid(target) then
        -- the mesh default itself may be remapped by a selected variant (e.g. a color variant)
        local tp = pkgPath(target)
        if tp then
            local p, o, mode = wanted(active, tp, leafName(target))
            if mode == "map" then target = loadObj(p, o) or target end
        end
        change("mat%d %s -> %s", i, pkgPath(base) or "?", pkgPath(target) or "?")
        if mid then
            local nm = makeMID(actor, comp, i, target, mid)
            if nm then mat = nm end
        else
            comp:SetMaterial(i, target)
            mat = target
        end
    end
    -- textures referenced through material parameters
    local changes, stale = {}, false
    for key, tp in pairs(textureParams(mat)) do
        local tpath = pkgPath(tp.tex)
        if tpath then
            local p, o, mode = wanted(active, tpath, leafName(tp.tex))
            if mode == "map" or mode == "orig" then
                local t = loadObj(p, o)
                if t then
                    table.insert(changes, { tp.info, t })
                    change("mat%d texture %s: %s -> %s", i, tostring(key):match("^[^|]*"), tpath, p)
                end
            elseif mode == "default" then
                stale = true                    -- a texture we set for a variant that is now off
            end
        end
    end
    if stale and isMID(mat) and valid(mat.Parent) then
        change("mat%d textures back to %s's own (variant off)", i, pkgPath(mat.Parent) or "?")
        local fresh = makeMID(actor, comp, i, mat.Parent, mat)   -- back to the parent's own textures
        if fresh then mat = fresh end
    end
    if #changes > 0 then
        local m2 = isMID(mat) and mat or makeMID(actor, comp, i, mat, nil)
        if m2 then
            for _, c in ipairs(changes) do setTexture(m2, c[1], c[2]) end
        end
    end
end

local function meshDefaults(mesh)               -- slot -> material from the mesh asset itself
    local out = {}
    pcall(function()
        for i, sm in ipairs(arrayItems(mesh.Materials)) do out[i - 1] = sm.MaterialInterface end
    end)
    pcall(function()
        if next(out) == nil then
            for i, sm in ipairs(arrayItems(mesh.StaticMaterials)) do out[i - 1] = sm.MaterialInterface end
        end
    end)
    return out
end

-- --------------------------------------------------------------------------- components

local NAMED = { "Body", "Face", "Hair", "Eyebrows", "Eyelashes", "Beard", "Mustache",
                "Haircut_SkeletalMesh", "Haircut_StaticMesh" }

local function meshComponents(actor)
    local list, seen = {}, {}
    local function add(name, c)
        if valid(c) then
            local a = c:GetAddress()
            if not seen[a] then seen[a] = true table.insert(list, { name = name, comp = c }) end
        end
    end
    for _, n in ipairs(NAMED) do
        local ok, c = pcall(function() return actor[n] end)
        if ok then add(n, c) end
    end
    local meshCls = cls("/Script/Engine.MeshComponent")
    if valid(meshCls) then
        local ok, arr = pcall(function() return actor:K2_GetComponentsByClass(meshCls) end)
        if ok then for _, c in ipairs(arrayItems(arr)) do add(leafName(c) or "?", c) end end
    end
    return list
end

local function getMesh(comp)
    if isA(comp, "/Script/Engine.SkeletalMeshComponent") then
        local ok, m = pcall(function() return comp:GetSkeletalMeshAsset() end)
        if ok and valid(m) then return m, "skel" end
        ok, m = pcall(function() return comp.SkinnedAsset end)
        if ok and valid(m) then return m, "skel" end
        return nil, "skel"
    elseif isA(comp, "/Script/Engine.StaticMeshComponent") then
        local ok, m = pcall(function() return comp.StaticMesh end)
        if ok and valid(m) then return m, "static" end
        return nil, "static"
    end
    return nil, nil
end

local function skeletonOf(mesh)
    local ok, sk = pcall(function() return mesh.Skeleton end)
    return (ok and valid(sk)) and pkgPath(sk) or nil
end

-- Same skeleton: keep the running animation pose (SetSkinnedAssetAndUpdate(mesh, false)) instead
-- of re-initialising the anim instance, physics and cloth from scratch on every swap.
local function setMesh(comp, kind, mesh, oldMesh)
    if kind == "skel" then
        local sameSkeleton = oldMesh ~= nil and skeletonOf(oldMesh) ~= nil and skeletonOf(oldMesh) == skeletonOf(mesh)
        if sameSkeleton and pcall(function() comp:SetSkinnedAssetAndUpdate(mesh, false) end) then return end
        if not pcall(function() comp:SetSkeletalMeshAsset(mesh) end) then
            pcall(function() comp:SetSkinnedAssetAndUpdate(mesh, true) end)
        end
    elseif kind == "static" then
        pcall(function() comp:SetStaticMesh(mesh) end)
    end
end

-- Component templates of a (relocated) Blueprint class. Reading UClass properties from Lua
-- doesn't work in UE4SS (it looks names up in the instance layout), but cooked templates are
-- named subobjects "<Class path>:<Var>_GEN_VARIABLE".
local function classTemplates(bpClass, names)
    local out = {}
    local cpath = fullPath(bpClass)
    if not cpath then return out end
    for _, n in ipairs(names) do
        local t = StaticFindObject(cpath .. ":" .. n .. "_GEN_VARIABLE")
        if valid(t) then out[n] = t end
    end
    return out
end

local function remapAnimClass(active, comp)
    local ok, ac = pcall(function() return comp.AnimClass end)
    if not ok or not valid(ac) then return end
    local p = pkgPath(ac)
    if not p then return end
    local np, no, mode = wanted(active, p, leafName(ac))
    if np and (mode == "map" or mode == "orig") then
        local c = loadObj(np, no)
        if c then
            change("anim %s -> %s", p, np)
            if not pcall(function() comp:SetAnimInstanceClass(c) end) then
                pcall(function() comp:SetAnimClass(c) end)
            end
        end
    end
end

-- Character of an actor that isn't a skin actor, from the meshes it shows (Body first).
local function charFromComps(comps)
    local found = {}
    for pass = 1, 2 do
        for _, e in ipairs(comps) do
            if (pass == 1) == (e.name == "Body") then
                local m = getMesh(e.comp)
                local p = valid(m) and pkgPath(m)
                if p then
                    local c = onlyChar(TO_ORIGINAL[p:lower()] or p)
                    if c and pass == 1 then return c end
                    if c then found[c] = true end
                end
            end
        end
    end
    local only
    for c in pairs(found) do
        if only then return nil end
        only = c
    end
    return only
end

local isSkinActor                               -- defined below with the skin class list
local WEAR_COMPS = { Body = true, CharacterMesh0 = true }
local FORCED_FROM = {}        -- component address -> mesh it showed before a "wear" mesh replaced it
local WORN = {}               -- character -> { path = original path of the body mesh shown, under = worn-over path, skin = bool }

-- doneComps (optional): components already handled in this pass. The game's swap policy shares
-- one component between a skin actor and its pawn, so a pass must not handle it twice.
local Clean = {}                -- filled in below (blood / dirt); applyToActor re-cleans after swaps

local function applyToActor(actor, doneComps)
    if not valid(actor) then return end
    local comps = meshComponents(actor)
    if doneComps then
        local left = {}
        for _, e in ipairs(comps) do
            local a = e.comp:GetAddress()
            if not doneComps[a] then
                doneComps[a] = true
                left[#left + 1] = e
            end
        end
        comps = left
    end
    local char = characterOf(actor) or charFromComps(comps)
    local active = activeFor(char)
    local force = forcedFor(char)
    local actorCtx = (leafName(actor) or "?") .. " [" .. tostring(char or "no character") .. "]"
    local skinActor = isSkinActor(actor)
    -- 1) whole skin Blueprint overridden by a variant: copy its component setup
    local templates
    local clsObj = actor:GetClass()
    local cpath = pkgPath(clsObj)
    if cpath then
        local p, o, mode = wanted(active, cpath, leafName(clsObj))
        if mode == "map" then
            local bp = loadObj(p, o)
            if bp then
                local names = {}
                for _, e in ipairs(comps) do table.insert(names, e.name) end
                templates = classTemplates(bp, names)
            end
        end
    end
    local ownTemplates                          -- the live class's own (vanilla) component setup
    local function vanillaMesh(name)
        if ownTemplates == nil then
            local names = {}
            for _, e in ipairs(comps) do table.insert(names, e.name) end
            ownTemplates = classTemplates(clsObj, names)
        end
        local t = ownTemplates[name]
        return t and getMesh(t) or nil
    end
    for _, e in ipairs(comps) do
        local comp = e.comp
        liveCtx = actorCtx .. "." .. e.name
        local mesh, kind = getMesh(comp)
        local newMesh, why
        local tmpl = templates and templates[e.name]
        if tmpl then
            local tm = getMesh(tmpl)
            if valid(tm) and pkgPath(tm) ~= pkgPath(mesh) then newMesh, why = tm, "the variant's skin Blueprint" end
        end
        local wearReset, wearRestore
        if not newMesh and WEAR_COMPS[e.name] and kind == "skel" and mesh then
            local ca, mp = comp:GetAddress(), pkgPath(mesh)
            local prev = FORCED_FROM[ca]
            -- is the component still showing the worn mesh we put there? (else the game re-dressed it)
            local ours = prev ~= nil and mp ~= nil and prev.set ~= nil and mp:lower() == prev.set:lower()
            local nm = 0
            if force or prev then
                local okn, n = pcall(function() return comp:GetNumMaterials() end)
                nm = okn and n or 0
            end
            if force then
                local fo = TO_ORIGINAL[force.pkg:lower()]
                if fo then markApplied(fo:lower(), force.vid) end
                if mp and mp:lower() ~= force.pkg:lower() then
                    if ours then
                        -- another worn mesh (e.g. Body Clean -> PH): keep the outfit remembered before
                        why = "Wear: another worn mesh"
                    else
                        -- remember what the game put there, materials included (hidden slots etc.)
                        local mats = {}
                        for i = 0, nm - 1 do
                            local okm, m = pcall(function() return comp:GetMaterial(i) end)
                            if okm and valid(m) then mats[i] = m end
                        end
                        FORCED_FROM[ca] = { path = mp, obj = leafName(mesh), mats = mats }
                        why = "Wear: over the outfit worn now"
                    end
                    FORCED_FROM[ca].set = force.pkg
                    newMesh = loadObj(force.pkg, force.obj)
                    wearReset = nm
                elseif prev then
                    prev.set = force.pkg
                end
            elseif prev then                                                -- wear switched off
                FORCED_FROM[ca] = nil
                if ours then
                    local p, o, mode = wanted(active, prev.path, prev.obj)
                    newMesh = (mode == "map" and loadObj(p, o)) or loadObj(prev.path, prev.obj)
                    why = "Wear off: back to the outfit"
                    wearRestore = prev
                end                                     -- else the game re-dressed it: map as usual
            end
        end
        if not newMesh and mesh and kind == "skel" and WEAR_COMPS[e.name] and not force and not templates
           and skinActor then
            -- A skin actor's body shows its own outfit or a variant of it. A worn mesh left on it
            -- (Wear switched off while the bookkeeping was lost) goes back to the outfit first.
            local mp = pkgPath(mesh)
            local orig = mp and TO_ORIGINAL[mp:lower()]
            local vm = orig and vanillaMesh(e.name)
            local vp = valid(vm) and pkgPath(vm)
            if vp and orig:lower() ~= vp:lower() then
                local p2, o2, m2 = wanted(active, vp, leafName(vm))
                newMesh = (m2 == "map" and loadObj(p2, o2)) or vm
                why = "back to this outfit's own mesh (a worn mesh was left on it)"
            end
        end
        if not newMesh and mesh then
            local mp = pkgPath(mesh)
            local p, o, mode
            if mp then p, o, mode = wanted(active, mp, leafName(mesh)) end
            if mode == "map" or mode == "orig" then
                newMesh = loadObj(p, o)
                why = mode == "map" and "selected variant" or "variant off: the game's own"
            elseif mode == "default" then
                local vm = vanillaMesh(e.name)  -- mod-only mesh of an unselected variant
                if valid(vm) and pkgPath(vm) ~= mp then newMesh, why = vm, "variant off: the class's own" end
            end
        end
        local meshChanged = false
        local oldDefaults = {}
        if newMesh and kind then
            change("mesh %s -> %s (%s)", mesh and pkgPath(mesh) or "none", pkgPath(newMesh) or "?", why or "?")
            oldDefaults = mesh and meshDefaults(mesh) or {}
            local t0 = os.clock()
            setMesh(comp, kind, newMesh, mesh) mesh = newMesh meshChanged = true
            if liveF then live("    mesh set (%d ms)", math.floor((os.clock() - t0) * 1000 + 0.5)) end
            if wearReset then
                -- the old outfit's material setup doesn't belong on another outfit's mesh
                local okn, nm = pcall(function() return comp:GetNumMaterials() end)
                for i = 0, math.max(wearReset, okn and nm or 0) - 1 do
                    pcall(function() comp:SetMaterial(i, nil) end)
                end
            elseif wearRestore then
                for i, m in pairs(wearRestore.mats or {}) do
                    -- the game may have rebuilt its instances; an old pointer could now be any object
                    if not (valid(m) and isA(m, "/Script/Engine.MaterialInterface")) then m = nil end
                    if valid(m) then pcall(function() comp:SetMaterial(i, m) end) end
                end
            end
        end
        local defaults = mesh and meshDefaults(mesh) or {}
        if tmpl then
            pcall(function()
                for i, m in ipairs(arrayItems(tmpl.OverrideMaterials)) do
                    if valid(m) then change("mat%d %s (from the variant's skin Blueprint)", i - 1, pkgPath(m) or "?") end
                    if valid(m) then comp:SetMaterial(i - 1, m) end
                end
            end)
        end
        local compActive = active
        if WEAR_COMPS[e.name] and kind == "skel" then compActive = forOutfit(active, mesh and pkgPath(mesh)) end
        if kind == "skel" then remapAnimClass(compActive, comp) end
        local ok, n = pcall(function() return comp:GetNumMaterials() end)
        if ok and n then
            for i = 0, n - 1 do
                local okf, err = pcall(fixSlot, actor, compActive, comp, i, defaults[i], oldDefaults[i], meshChanged)
                if not okf then log("slot %d of %s: %s", i, e.name, tostring(err)) end
            end
        end
        if SETTINGS.clean and Clean.comp then pcall(Clean.comp, comp, actor) end
        -- what this character wears now (for the menu): the body mesh after this pass
        if char and kind == "skel" and WEAR_COMPS[e.name] and mesh then
            local mp = pkgPath(mesh)
            local prev = WORN[char]
            if mp and (not prev or not prev.skin or skinActor) then
                local f = FORCED_FROM[comp:GetAddress()]
                WORN[char] = { path = TO_ORIGINAL[mp:lower()] or mp, under = f and f.path or nil, skin = skinActor }
            end
        end
    end
end

local SKIN_CLASSES = { "BP_CharacterSkinBase_C", "BP_CharacterFaceBase_C", "BP_CineCharacter_Main_C" }
local SKIN_OF_CLASS = {}      -- class address|name -> bool

isSkinActor = function(a)
    local okc, c = pcall(function() return a:GetClass() end)
    if not okc or not valid(c) then return false end
    local addr = c:GetAddress() .. "|" .. tostring(leafName(c))   -- an unloaded class's address can be reused
    if SKIN_OF_CLASS[addr] ~= nil then return SKIN_OF_CLASS[addr] end
    local result, s = false, c
    for _ = 1, 16 do
        if not valid(s) then break end
        local n = leafName(s)
        for _, cn in ipairs(SKIN_CLASSES) do if n == cn then result = true end end
        if result then break end
        local okp, sup = pcall(function() return s:GetSuperStruct() end)
        if not okp then break end
        s = sup
    end
    SKIN_OF_CLASS[addr] = result
    return result
end

local EXTRA_CLASS = {}         -- class address|name -> true: non-skin actors seen showing a replaced mesh

local function isWardrobeActor(a)
    if isSkinActor(a) then return true end
    local ok, c = pcall(function() return a:GetClass() end)
    return ok and valid(c) and EXTRA_CLASS[c:GetAddress() .. "|" .. tostring(leafName(c))] == true
end

-- Actors (not only skin actors) that show a mesh some variant replaces, e.g. the base body
-- "SK_<Character>_Placeholder" on world / menu pawns. One pass over all skeletal mesh components.
local function wearActive()
    for id in pairs(wearSet()) do if selection[id] then return true end end
    return false
end

local function forEachMappedMeshOwner(fn)
    local heroes = wearActive()                -- "wear" can put a mesh on any outfit a hero wears
    if next(MAPPED_MESH) == nil and not heroes then return end
    local ok, all = pcall(FindAllOf, "SkeletalMeshComponent")
    if not ok or not all then return end
    local seen = {}
    for _, c in ipairs(all) do
        if valid(c) then
            local m = getMesh(c)
            local p = valid(m) and pkgPath(m)
            if p and (MAPPED_MESH[p:lower()] or (heroes and p:lower():find("/characters/heros/", 1, true))) then
                local oko, owner = pcall(function() return c:GetOwner() end)
                if oko and valid(owner) and not seen[owner:GetAddress()] then
                    seen[owner:GetAddress()] = true
                    fn(owner)
                end
            end
        end
    end
end

local function forEachSkin(fn)                  -- full object scan: only for explicit user actions
    for _, cn in ipairs(SKIN_CLASSES) do
        local all = FindAllOf(cn)
        if all then for _, a in ipairs(all) do if valid(a) then fn(a) end end end
    end
end

-- --------------------------------------------------------------------------- clean (blood / dirt)
-- Studied from the Nexus mods #143 "Dirt And Blood Remover", #115 "Clean Characters and Bloody
-- Effects Remover" and #151 "Dirt and Blood Reducer": all three only replace the textures under
-- /Game/MetaHumans/BTLS_Textures/ (per character Body/Face masks, their normals, Mask_2..4,
-- T_BTLS_Mask_Tiling, T_Mask_RGBA_BTLS). #143 / #115 make every mask all zero (RGB 0, alpha 0);
-- #151 caps the values. The characters' materials take the masks as texture parameters
-- (BTLS_Map / BTLS_Map_Tiling, plus BTLS_Normal* for the normals).
-- Clean does what #143 does, at runtime and switchable: every texture parameter currently showing
-- a BTLS mask (not a normal map) gets an all-zero 4x4 render target made in memory; the game's mask
-- is remembered and put back when Clean is switched off. Cutscene pawns' BloodLevel / DirtLevel /
-- DustingLevel go to 0 as well (re-set every second while Clean is on: sequences animate them).
do
    local CINE_LEVELS = { "BloodLevel", "DirtLevel", "DustingLevel" }
    -- Objects are remembered by address AND name: the engine frees objects nothing references (the
    -- render target once Clean is off, everything at a level change), and a freed address can be
    -- reused by another object that `valid()` would accept.
    local CLEANED = {}          -- MID address -> { mid = obj, name = its name, params = { key = { info, orig } } }
    local CLEAN_CINE = {}       -- address -> { actor = obj, name = its name }
    local ZERO, ZERO_NAME = nil, nil   -- the all-zero texture and its name
    local LAST_CLEAN = nil

    local function isMask(tex)
        local p = valid(tex) and pkgPath(tex)
        if not p or not p:find("/BTLS_Textures/", 1, true) then return false end
        return not (p:match("[^/]+$") or ""):lower():find("normal", 1, true)
    end

    local function zeroTexture(ctx)
        if ZERO and valid(ZERO) and leafName(ZERO) == ZERO_NAME
           and isA(ZERO, "/Script/Engine.TextureRenderTarget2D") then
            return ZERO
        end
        ZERO, ZERO_NAME = nil, nil
        local lib = StaticFindObject("/Script/Engine.Default__KismetRenderingLibrary")
        if not valid(lib) then return nil end
        local owner = ctx
        pcall(function()                        -- outlive the actor: the game instance holds it
            local gi = FindFirstOf("GameInstance")
            if valid(gi) then owner = gi end
        end)
        local black = { R = 0.0, G = 0.0, B = 0.0, A = 0.0 }
        local ok, rt = pcall(function() return lib:CreateRenderTarget2D(owner, 4, 4, 2, black, false, false) end)   -- 2 = RTF_RGBA8
        if ok and valid(rt) then
            pcall(function() lib:ClearRenderTarget2D(owner, rt, black) end)
            ZERO, ZERO_NAME = rt, leafName(rt)
            live("clean: made the all-zero mask texture (%s)", tostring(pkgPath(rt) or leafName(rt) or "render target"))
        else
            live("clean: could not make the all-zero texture: %s", tostring(rt))
        end
        return ZERO
    end

    local function cleanCine(actor, stats)
        local any = false
        for _, prop in ipairs(CINE_LEVELS) do
            local ok, v = pcall(function() return actor[prop] end)
            if ok and type(v) == "number" then
                any = true
                if v > 0 and pcall(function() actor[prop] = 0.0 end) then stats.cine = stats.cine + 1 end
            end
        end
        if any then CLEAN_CINE[actor:GetAddress()] = { actor = actor, name = leafName(actor) } end
    end

    local function cleanComp(comp, stats, ctx)
        local okn, n = pcall(function() return comp:GetNumMaterials() end)
        for i = 0, (okn and n or 0) - 1 do
            local okm, m = pcall(function() return comp:GetMaterial(i) end)
            if okm and valid(m) then
                local mid = isMID(m)
                for key, tp in pairs(textureParams(m)) do
                    if isMask(tp.tex) then
                        stats.names[key:match("^[^|]+")] = true
                        if not mid and ctx then                  -- a plain material: give the slot an instance
                            local nm = makeMID(ctx, comp, i, m, nil)
                            if nm then m, mid = nm, true end
                        end
                        if not mid then
                            stats.noMid = stats.noMid + 1
                        else
                            local z = zeroTexture(ctx)
                            if not z then stats.noTex = true return end
                            local a = m:GetAddress()
                            local e = CLEANED[a]
                            if not e or e.name ~= leafName(m) then e = { mid = m, name = leafName(m), params = {} } end
                            if not e.params[key] then e.params[key] = { info = tp.info, orig = tp.tex } end
                            CLEANED[a] = e
                            setTexture(m, tp.info, z)
                            stats.set = stats.set + 1
                        end
                    end
                end
            end
        end
    end

    local function newStats() return { set = 0, cine = 0, noMid = 0, actors = 0, names = {} } end

    local function cleanActor(actor, stats, seen)
        if not valid(actor) then return end
        local a = actor:GetAddress()
        if seen then
            if seen[a] then return end
            seen[a] = true
        end
        stats.actors = stats.actors + 1
        cleanCine(actor, stats)
        for _, e in ipairs(meshComponents(actor)) do cleanComp(e.comp, stats, actor) end
    end

    -- One pass over the characters (skin / face / cutscene actors and pawns).
    local function cleanAll(why)
        local stats, seen = newStats(), {}
        GT_STATE = "clean"
        forEachSkin(function(a) cleanActor(a, stats, seen) end)
        local ok, pawns = pcall(FindAllOf, "Pawn")
        for _, a in ipairs(ok and pawns or {}) do cleanActor(a, stats, seen) end
        local names = {}
        for k in pairs(stats.names) do names[#names + 1] = k end
        table.sort(names)
        live("clean (%s): %d mask(s) blanked on %d actor(s), %d cutscene level(s) to 0; mask parameters: %s%s%s",
            why or "button", stats.set, stats.actors, stats.cine, #names > 0 and table.concat(names, ", ") or "none found",
            stats.noMid > 0 and string.format(" (%d on materials without a dynamic instance, left)", stats.noMid) or "",
            stats.noTex and "; NO all-zero texture (see above), nothing blanked" or "")
        for a, e in pairs(CLEANED) do                -- forget instances that are gone
            if not (valid(e.mid) and leafName(e.mid) == e.name) then CLEANED[a] = nil end
        end
        LAST_CLEAN = { set = stats.set, cine = stats.cine, names = names, actors = stats.actors, noTex = stats.noTex }
        return LAST_CLEAN
    end

    -- Clean off: the game's own masks back on every material that is still there.
    local function restoreAll()
        local n = 0
        for _, e in pairs(CLEANED) do
            if valid(e.mid) and leafName(e.mid) == e.name then
                for _, p in pairs(e.params) do
                    if valid(p.orig) and isA(p.orig, "/Script/Engine.Texture") then
                        setTexture(e.mid, p.info, p.orig)
                        n = n + 1
                    end
                end
            end
        end
        CLEANED, CLEAN_CINE = {}, {}
        live("clean off: %d mask(s) back to the game's own", n)
        return n
    end

    -- While Clean is on, every second: cutscene levels to 0 (cheap, no object scan).
    local function keepClean()
        for a, e in pairs(CLEAN_CINE) do
            if valid(e.actor) and leafName(e.actor) == e.name then
                for _, prop in ipairs(CINE_LEVELS) do pcall(function() e.actor[prop] = 0.0 end) end
            else
                CLEAN_CINE[a] = nil
            end
        end
    end

    Clean.all, Clean.keep, Clean.actor, Clean.newStats, Clean.restore = cleanAll, keepClean, cleanActor, newStats, restoreAll
    Clean.comp = function(comp, ctx) cleanComp(comp, newStats(), ctx) end   -- after our own swaps (new MIDs)
    Clean.last = function() return LAST_CLEAN end
    Clean.owner = function(owner)               -- the skin / face actors a character's skin component spawned
        if not valid(owner) then return end
        for _, cn in ipairs({ "BP_CharacterSkinComponent", "BP_CinematicCharacterSkinComponent" }) do
            local ok, sc = pcall(function() return owner[cn] end)
            if ok and valid(sc) then
                for _, prop in ipairs({ "SpawnedCharacterSkin", "SpawnedCharacterFace" }) do
                    local ok2, skin = pcall(function() return sc[prop] end)
                    if ok2 and valid(skin) then cleanActor(skin, newStats()) end
                end
            end
        end
    end
    -- level change: the old world's instances and the texture go with it; the new world is cleaned
    -- after it loads
    Clean.forget = function() ZERO, ZERO_NAME, CLEANED, CLEAN_CINE = nil, nil, {}, {} end
end


local afterPass                                -- set further down: state lines + auto dump/report


local function runApply()
        PASS.queued = false
        local reasons = table.concat(PASS.why, " + ")
        PASS.why = {}
        GT_STATE = "apply pass (" .. reasons .. ")"
        APPLIED = {}
        WORN = {}
        passChanges = 0
        local n, extra, done, doneComps = 0, 0, {}, {}
        local function one(a)
            done[a:GetAddress()] = true
            local ok, err = pcall(applyToActor, a, doneComps)
            if not ok then log("apply failed on %s: %s", tostring(leafName(a)), tostring(err)) end
            n = n + 1
        end
        forEachSkin(one)
        forEachMappedMeshOwner(function(a)
            if done[a:GetAddress()] then return end
            local okc, c = pcall(function() return a:GetClass() end)
            if okc and valid(c) then EXTRA_CLASS[c:GetAddress() .. "|" .. tostring(leafName(c))] = true end
            extra = extra + 1
            one(a)
        end)
        PASS.last = n
        PASS.full = PASS.full + 1
        if extra > 0 then
            log("applied to %d actor(s): %d skin actor(s), %d other(s) showing a replaced mesh", n, n - extra, extra)
        else
            log("applied to %d skin actor(s)", n)
        end
        live("pass (%s): %d change(s)%s", reasons, passChanges,
            passChanges == 0 and " - nothing loaded needed changing" or "")
        if afterPass then afterPass() end
end

-- Ask for a pass. Plain Lua bookkeeping only, so it may be called from any thread: the
-- game-thread loop runs one pass ~200 ms after the first request (fast clicks, a pick that also
-- switches matched slots and a Wear toggle are merged).
local function applyAll(why)
    local w = type(why) == "string" and why or "Ctrl+F7 / apply"
    local known = false
    for _, x in ipairs(PASS.why) do if x == w then known = true end end
    if not known then PASS.why[#PASS.why + 1] = w end
    if HAS_GT_LOOP then
        if not PASS.due then PASS.due = loopTicks + PASS.debounce end
        return
    end
    if PASS.queued then return end              -- older UE4SS without a game-thread loop
    PASS.queued = true
    if onGameThread() then atCallbackEnd[#atCallbackEnd + 1] = runApply else post(runApply) end
end

local function applyIfDue()                     -- the game-thread loop
    if PASS.due and loopTicks >= PASS.due then
        PASS.due = nil
        runApply()
    end
end

-- --------------------------------------------------------------------------- diagnostics

local function dump(quiet)
    inGame(function()
        GT_STATE = "dump"
        live("dump: start")
        local f = io.open(FILES.DUMP, "w")
        if not f then log("cannot write %s", FILES.DUMP) return end
        local ok, err = pcall(function()
            local listedFns = false
            local present = {}                      -- lower-case original path -> where it is shown
            local function note(obj, where)
                local p = valid(obj) and pkgPath(obj)
                if p then
                    local o = (TO_ORIGINAL[p:lower()] or p):lower()
                    present[o] = present[o] or where
                end
            end
            local visit, seenA = {}, {}
            forEachSkin(function(a) seenA[a:GetAddress()] = true visit[#visit + 1] = a end)
            forEachMappedMeshOwner(function(a)
                if not seenA[a:GetAddress()] then seenA[a:GetAddress()] = true visit[#visit + 1] = a end
            end)
            local function dumpActor(a)
                f:write("ACTOR ", a:GetFullName(), "\n  class: ", a:GetClass():GetFullName(), "\n")
                local owner = ownerOf(a)
                f:write("  owner: ", valid(owner) and owner:GetFullName() or "nil", "\n")
                local comps = meshComponents(a)
                local ch = characterOf(a)
                f:write("  character: ", tostring(ch or charFromComps(comps)), ch and "" or " (from its meshes)", "\n")
                if not isSkinActor(a) then f:write("  (not a skin actor: visited because it shows a replaced mesh)\n") end
                for _, o in ipairs({ owner, a }) do
                    if valid(o) then
                        local ok, sc = pcall(function() return o.BP_CharacterSkinComponent end)
                        if ok and valid(sc) then
                            local okp, pol = pcall(function() return sc.SkinAssignPolicy end)
                            f:write("  skin component: ", sc:GetFullName(), "\n  policy: ",
                                (okp and valid(pol)) and pol:GetClass():GetFullName() or "nil", "\n")
                            local okm, arr = pcall(function() return sc.CurrentCharacterSkinMaterialInstances end)
                            f:write("  CurrentCharacterSkinMaterialInstances: ", okm and #arrayItems(arr) or "?", "\n")
                            if not listedFns then
                                listedFns = true
                                pcall(function()
                                    sc:GetClass():ForEachFunction(function(fn)
                                        f:write("    fn ", fn:GetFName():ToString(), "\n")
                                    end)
                                end)
                            end
                        end
                    end
                end
                local short = leafName(a) or "?"
                for _, e in ipairs(comps) do
                    local mesh = getMesh(e.comp)
                    note(mesh, short .. "." .. e.name)
                    f:write("  [", e.name, "] mesh=", valid(mesh) and mesh:GetFullName() or "nil", "\n")
                    if valid(mesh) then
                        pcall(function() f:write("     skeleton=", mesh.Skeleton:GetFullName(), "\n") end)
                        pcall(function() f:write("     physics=", mesh.PhysicsAsset:GetFullName(), "\n") end)
                    end
                    pcall(function() f:write("     anim=", e.comp.AnimClass:GetFullName(), "\n") end)
                    pcall(function() f:write("     leader=", e.comp.LeaderPoseComponent:GetFullName(), "\n") end)
                    local ok, n = pcall(function() return e.comp:GetNumMaterials() end)
                    for i = 0, (ok and n or 0) - 1 do
                        local m = e.comp:GetMaterial(i)
                        note(m, short .. "." .. e.name)
                        if isMID(m) then note(m.Parent, short .. "." .. e.name) end
                        f:write("     mat", i, " ", valid(m) and m:GetFullName() or "nil")
                        if isMID(m) and valid(m.Parent) then f:write("  parent=", m.Parent:GetFullName()) end
                        f:write("\n")
                        for key, tp in pairs(textureParams(m)) do
                            note(tp.tex, short .. "." .. e.name)
                            f:write("        tex ", key, " = ", valid(tp.tex) and tp.tex:GetFullName() or "nil", "\n")
                        end
                        local sc, names = scalarParams(m), {}
                        for k in pairs(sc) do names[#names + 1] = k end
                        table.sort(names)
                        for _, k in ipairs(names) do f:write("        scalar ", k, " = ", tostring(sc[k]), "\n") end
                    end
                end
            end
            for _, a in ipairs(visit) do            -- a character that dies mid-listing doesn't cut the file short
                local ok, err = pcall(dumpActor, a)
                if not ok then f:write("  (listing stopped: ", tostring(err), ")\n") end
            end
            -- What each selected variant replaces, and whether anything loaded shows it right now.
            f:write("\nWARDROBE CHECK (selected variants)\n")
            for _, slot in ipairs(SLOTS) do
                local vid = selection[slot.id]
                for _, v in ipairs(slot.variants) do
                    if v.id == vid then
                        f:write("SLOT ", slot.label, " [", tostring(slot.character or "everyone"),
                            slot.inferred and ", guessed from names/assets" or "", "] = ", v.label,
                            wearSet()[slot.id] and "  (worn over any outfit)" or "", "\n")
                        local keys = {}
                        for orig in pairs(v.map) do keys[#keys + 1] = orig end
                        table.sort(keys)
                        for _, orig in ipairs(keys) do
                            local e = v.map[orig]
                            local w = present[orig:lower()]
                            f:write("   ", w and "SHOWN  " or "absent ", orig, " (", tostring(e[3]), ")",
                                w and ("  on " .. w) or "", "\n")
                        end
                    end
                end
            end
        end)
        f:close()
        if not ok then log("dump.txt stopped early: %s", tostring(err)) end
        if quiet then live("wrote %s", FILES.DUMP) else log("wrote %s", FILES.DUMP) end
    end)
end

-- --------------------------------------------------------------------------- selection UI

local function variantIndex(slot)
    local vid = selection[slot.id]
    for i, v in ipairs(slot.variants) do if v.id == vid then return i end end
    return 0
end

local function describe(i)
    local slot = SLOTS[i]
    if not slot then return "(no slots - run e33_relocate.py)" end
    local vi = variantIndex(slot)
    return string.format("slot %d/%d %s%s = %s", i, #SLOTS, slot.label,
        slot.character and (" [" .. slot.character .. " only]") or "",
        vi == 0 and "off (vanilla)" or slot.variants[vi].label)
end

local function selectedVariant(slot)
    local vid = selection[slot.id]
    if not vid then return nil end
    for _, v in ipairs(slot.variants) do if v.id == vid then return v end end
    return nil
end

-- Asset classes that show on a character (a PrimaryAssetLabel such as a mod's "chic_MyMod" in
-- every pak, a PhysicsAsset or a Skeleton never does): only these count for states and overlaps.
local SHOWABLE = { SkeletalMesh = true, StaticMesh = true, MaterialInstanceConstant = true, Material = true,
                   Texture2D = true, BlueprintGeneratedClass = true }

local function variantKeys(v)                  -- lower-case originals that can show, cached on the variant
    if not v._keys then
        v._keys = {}
        for orig, e in pairs(v.map or {}) do
            if SHOWABLE[e[3]] then v._keys[orig:lower()] = true end
        end
    end
    return v._keys
end

-- "on"      the selected variant reached at least one loaded actor in the last full pass
-- "unused"  nothing loaded uses any asset it replaces (e.g. the outfit it changes isn't worn)
-- "pending" no full pass yet; nil when the slot is off
local function slotState(slotIdx)
    local slot = SLOTS[slotIdx]
    local v = slot and selectedVariant(slot)
    if not v then return nil end
    if PASS.full == 0 or PASS.due ~= nil or PASS.queued then return "pending" end
    for k in pairs(variantKeys(v)) do if appliedBy(k, v.id) then return "on" end end
    return "unused"
end

-- Other selected slots that replace some of the same assets for the same character.
-- wins = true when this slot was picked later (its version is the one shown).
local function overlaps(slotIdx)
    local out = {}
    local slot = SLOTS[slotIdx]
    local v = slot and selectedVariant(slot)
    if not v then return out end
    local mine = variantKeys(v)
    for j, other in ipairs(SLOTS) do
        local ov = j ~= slotIdx and selectedVariant(other)
        if ov and (not SETTINGS.scoping or not slot.character or not other.character
                   or slot.character == other.character) then
            local n, mineShown, otherShown = 0, false, false
            for k in pairs(variantKeys(ov)) do
                if mine[k] then
                    n = n + 1
                    if appliedBy(k, v.id) then mineShown = true end
                    if appliedBy(k, ov.id) then otherShown = true end
                end
            end
            if n > 0 then
                -- whose version the last pass showed (an outfit mod whose mesh isn't worn gives way
                -- to an earlier pick); the pick order where neither or both showed
                local wins = mineShown
                if mineShown == otherShown then wins = (PICK[slot.id] or 0) > (PICK[other.id] or 0) end
                out[#out + 1] = { idx = j, count = n, wins = wins }
            end
        end
    end
    return out
end

local function groupOf(label) return label and label:match("^(.-):%s") or nil end

local function wordsOf(label)
    local t = {}
    for w in ((label or ""):gsub("^.-:%s*", "")):lower():gmatch("%a+") do t[w] = true end
    return t
end

-- A mod's pieces only fit within one group (for example a "Lace dress" outfit needs a "Lace dress"
-- color; the lace colors carry the lace normal maps). When a slot's variant is in group G, its
-- sibling slots (same mod, same character) that show another group switch to their closest
-- variant in G. Vanilla siblings are left alone. Returns "slot -> variant" strings.
local LOOK = { SkeletalMesh = true, StaticMesh = true, MaterialInstanceConstant = true, Material = true,
               Texture2D = true }

local function changesLooks(slot)              -- has variants with meshes / materials / textures
    for _, v in ipairs(slot.variants or {}) do
        for _, e in pairs(v.map or {}) do if LOOK[e[3]] then return true end end
    end
    return false
end

local function hasMesh(slot)
    for _, v in ipairs(slot.variants or {}) do
        for _, e in pairs(v.map or {}) do if e[3] == "SkeletalMesh" then return true end end
    end
    return false
end

-- "SK_Lune_Potato_Skin" -> "Potato bag"; "SK_Sciel_Placeholder" -> "base body". config.lua can add
-- names: outfit_names = { Potato = "Potato bag" }.
local OUTFIT_NAMES = { Potato = "Potato bag", Placeholder = "base body" }
for k, v in pairs(CONFIG_OUTFIT_NAMES or {}) do OUTFIT_NAMES[k] = v end
local function outfitName(path)
    if not path then return nil end
    local leaf = path:match("[^/%.]+$") or path
    local parts = {}
    for tok in leaf:gmatch("[^_]+") do
        local low = tok:lower()
        if low ~= "sk" and low ~= "skin" and not CHAR_ALIASES[low] then parts[#parts + 1] = tok end
    end
    local name = table.concat(parts, " ")
    if name == "" then name = leaf end
    return OUTFIT_NAMES[name] or name
end

-- The outfit a slot's selected (or first) variant replaces: its skeletal mesh's original path.
local function targetOutfit(slot)
    local v = selectedVariant(slot) or (slot.variants or {})[1]
    if not v then return nil end
    for orig, e in pairs(v.map or {}) do
        if e[3] == "SkeletalMesh" then return orig end
    end
    return nil
end

-- A slot that replaces assets, none of them anything anyone sees (e.g. a Blueprint-only "fix"
-- pak): hidden in the menu. A slot with nothing mapped at all is not called technical.
local function isTechnical(slot)
    for _, v in ipairs(slot.variants or {}) do
        if next(v.map or {}) then return not changesLooks(slot) end
    end
    return false
end

local function matchGroups(slotIdx)
    local changed = {}
    if not SETTINGS.match_groups then return changed end
    local slot = SLOTS[slotIdx]
    local v = slot and selectedVariant(slot)
    local g = v and groupOf(v.label)
    if not g or not changesLooks(slot) then return changed end   -- e.g. a Blueprint-only fix pak
    for j, other in ipairs(SLOTS) do
        if j ~= slotIdx and other.mod == slot.mod and other.character == slot.character and changesLooks(other) then
            local ov = selectedVariant(other)
            local og = ov and groupOf(ov.label)
            if og and og ~= g then
                local cur, best, bestScore = wordsOf(ov.label), nil, -1
                for _, cand in ipairs(other.variants) do
                    if groupOf(cand.label) == g then
                        local sc = 0
                        for w in pairs(wordsOf(cand.label)) do if cur[w] then sc = sc + 1 end end
                        if sc > bestScore then best, bestScore = cand, sc end
                    end
                end
                if best then
                    selection[other.id] = best.id
                    picked(other.id)
                    changed[#changed + 1] = other.label .. " -> " .. best.label
                end
            end
        end
    end
    return changed
end

-- After every pass: one line per selected variant saying how much of it is on screen, then
-- dump.txt + report.txt rewritten 4 s after the last change (debounced).
local report                                   -- defined with reload(), below


local SHOWN = {}                -- slot id -> { shown = n, total = n } after the last pass

local function setWearFlag(id, on, why)
    local t = wearSet()
    t[id] = on or nil
    if not on then AUTO_WORN[id] = nil end
    local ids = {}
    for k in pairs(t) do ids[#ids + 1] = k end
    table.sort(ids)
    SETTINGS.wear = table.concat(ids, "|")
    saveSettings()
    rebuildActive()
    local label = id
    for _, sl in ipairs(SLOTS) do if sl.id == id then label = sl.label end end
    applyAll((why or "Wear") .. " " .. (on and "on" or "off") .. ": " .. label)
end

-- Auto Wear: a picked outfit mod whose mesh shows nowhere on its character (it was made for an
-- outfit the character isn't wearing) is put on over the outfit worn now. Waits until the
-- character is loaded.
local function autoWear()
    if not SETTINGS.auto_wear then AUTOWEAR_PENDING = {} return end
    local wear = wearSet()
    for i, slot in ipairs(SLOTS) do
        if AUTOWEAR_PENDING[slot.id] then
            local v = selectedVariant(slot)
            if not v or wear[slot.id] or not slot.character or not hasMesh(slot) then
                AUTOWEAR_PENDING[slot.id] = nil
            elseif WORN[slot.character] then
                AUTOWEAR_PENDING[slot.id] = nil
                local shown = false
                for orig, e in pairs(v.map or {}) do
                    if e[3] == "SkeletalMesh" and appliedBy(orig:lower(), v.id) then shown = true end
                end
                if not shown then
                    AUTO_WORN[slot.id] = true
                    live("Auto Wear: %s doesn't fit what %s wears; worn in place of it", slot.label, slot.character)
                    setWearFlag(slot.id, true, "Auto Wear")
                end
            end
        end
    end
end

afterPass = function(fromSpawn)
    for i, slot in ipairs(SLOTS) do
        local v = selectedVariant(slot)
        if v then
            local total, shown, missing = 0, 0, {}
            for orig, e in pairs(v.map or {}) do
                if SHOWABLE[e[3]] then
                    total = total + 1
                    if appliedBy(orig:lower(), v.id) then shown = shown + 1
                    elseif #missing < 6 then missing[#missing + 1] = orig:match("[^/]+$") end
                end
            end
            SHOWN[slot.id] = { shown = shown, total = total }
            local ov = {}
            for _, o in ipairs(overlaps(i)) do
                ov[#ov + 1] = SLOTS[o.idx].label .. (o.wins and " (this one shows)" or " (that one shows)")
            end
            if liveF then live("  on screen: %s = %s: %d/%d asset(s)%s%s%s", slot.label, v.label, shown, total,
                #missing > 0 and ("; not shown: " .. table.concat(missing, ", ")) or "",
                wearSet()[slot.id] and "; worn (Wear)" or "",
                #ov > 0 and ("; overlaps " .. table.concat(ov, ", ")) or "") end
        else
            SHOWN[slot.id] = nil
        end
    end
    autoWear()
    if fromSpawn or not SETTINGS.auto_report or not liveF then return end   -- opt-in; never after spawns
    PASS.autoGen = PASS.autoGen + 1
    local gen = PASS.autoGen
    delayGT(4000, function()
        if gen ~= PASS.autoGen or not liveF then return end
        dump(true)
        report(true)
        live("dump.txt and report.txt refreshed")
    end)
end

local HISTORY = {}              -- previous selections, for Undo

local function copySel(t)
    local c = {}
    for k, v in pairs(t or {}) do c[k] = v end
    return c
end

local function pushHistory()
    table.insert(HISTORY, copySel(selection))
    if #HISTORY > 30 then table.remove(HISTORY, 1) end
end

-- Replace the whole selection (presets, randomize, A/B, undo) and apply once.
local function setSelection(newSel, noHistory, match)
    if not noHistory then pushHistory() end
    local old = selection
    selection = {}
    for _, slot in ipairs(SLOTS) do
        local vid = newSel[slot.id]
        for _, v in ipairs(slot.variants) do
            if v.id == vid then
                selection[slot.id] = vid
                if old[slot.id] ~= vid then picked(slot.id) end
            end
        end
    end
    if match then                               -- e.g. Randomize: keep each mod's groups consistent
        for i in ipairs(SLOTS) do matchGroups(i) end
    end
    for _, slot in ipairs(SLOTS) do
        if old[slot.id] ~= selection[slot.id] then
            live("selection: %s = %s", slot.label, tostring(selection[slot.id] or "off"))
        end
    end
    saveSelection()
    rebuildActive()
    applyAll("several slots at once (preset / randomize / undo / A-B)")
end

local function setVariant(slotIdx, vi, noHistory)
    local slot = SLOTS[slotIdx]
    if not slot then return end
    if not noHistory then pushHistory() end
    vi = vi % (#slot.variants + 1)
    selection[slot.id] = vi > 0 and slot.variants[vi].id or nil
    local changed = {}
    if vi > 0 then
        changed = matchGroups(slotIdx)
        picked(slot.id)                         -- after the siblings: the user's pick stays on top
    end
    saveSelection()
    rebuildActive()
    log(describe(slotIdx))
    for _, c in ipairs(changed) do log("  matched: %s", c) end
    applyAll(slot.label .. " = " .. (vi > 0 and slot.variants[vi].label or "off"))
    return changed
end

local function undo()
    local last = table.remove(HISTORY)
    if not last then return false end
    setSelection(last, true)
    return true
end

-- Presets: up to 8, stored as "index<TAB>slot id<TAB>variant id" lines (empty variant = vanilla).
local function loadPresets()
    local out = {}
    local f = io.open(FILES.PRESETS, "r")
    if not f then return out end
    for line in f:lines() do
        local i, k, v = line:match("^(%d+)\t(.-)\t(.*)$")
        i = tonumber(i)
        if i then
            out[i] = out[i] or {}
            if k ~= "" and v ~= "" then out[i][k] = v end
        end
    end
    f:close()
    return out
end

local function savePresets(p)
    local f = io.open(FILES.PRESETS, "w")
    if not f then return end
    for i = 1, 8 do
        if p[i] then
            f:write(i, "\t\t\n")                     -- marks the preset as saved even if all vanilla
            for k, v in pairs(p[i]) do f:write(i, "\t", k, "\t", v, "\n") end
        end
    end
    f:close()
end

local function listAll()
    for i in ipairs(SLOTS) do
        log(describe(i))
        for vi, v in ipairs(SLOTS[i].variants) do log("      %d: %s", vi, v.label) end
    end
end

local function reload()
    FAILED = {}
    loadVariants()
    inferCharacters()
    -- Wear on a slot that can't wear (no mesh) does nothing: drop such stale flags
    do
        local keep, dropped, byId = {}, false, {}
        for _, slot in ipairs(SLOTS) do byId[slot.id] = slot end
        for id in (SETTINGS.wear or ""):gmatch("[^|]+") do
            local slot = byId[id]
            if slot and not (slot.character and hasMesh(slot)) then dropped = true else keep[#keep + 1] = id end
        end
        if dropped then
            SETTINGS.wear = table.concat(keep, "|")
            saveSettings()
            log("dropped Wear from slots that have no mesh to wear")
        end
    end
    loadSelection()
    if #SLOTS > 0 then                          -- picks of slots / variants no longer in the wardrobe
        local known, dropped = {}, 0
        for _, slot in ipairs(SLOTS) do
            known[slot.id] = {}
            for _, v in ipairs(slot.variants) do known[slot.id][v.id] = true end
        end
        for id, vid in pairs(selection) do
            if not (known[id] and known[id][vid]) then selection[id] = nil dropped = dropped + 1 end
        end
        if dropped > 0 then
            saveSelection()
            log("dropped %d pick(s) of mods no longer in the wardrobe", dropped)
        end
    end
    rebuildActive()
    currentSlot = math.max(1, math.min(currentSlot, #SLOTS))
    if liveF then
        live("wardrobe: %d slot(s)", #SLOTS)
        for i, slot in ipairs(SLOTS) do
            live("  slot %d %s [%s%s] %d variant(s), selected: %s", i, slot.label, tostring(slot.character or "everyone"),
                slot.inferred and ", guessed" or "", #slot.variants, tostring(selection[slot.id] or "off"))
        end
    end
    applyAll("reload: variants.lua + selection.txt")
end

-- "Fix look": ask the game to re-dress every character (as re-equipping the outfit does); the
-- spawn / assign hooks then re-apply the current picks. Recovers from any state we left behind.
-- ApplyCurrentCharacterSkin takes one parameter. Its name and type are read from the function
-- itself once. PC: "NameProperty Character Name": each component gets the name the game gave its
-- owner when it assigned the skin (the policy hook records it), or a cutscene component's
-- CharacterHardcodedName. A single bool is passed as true unless its name says skip/keep/no;
-- anything else: the call is not made. A failure logs the error and the component's functions.
local Fix = {}
do
    local LAST_FIX = { n = 0, tried = 0 }
    local GAME_NAME = {}        -- owner address -> the game's character name ("Lune", "Default", ...)
    Fix.noteName = function(owner, name)
        if valid(owner) and name and name ~= "" and name ~= "None" then GAME_NAME[owner:GetAddress()] = name end
    end
    local function nameFor(c)
        local okO, owner = pcall(function() return c:GetOwner() end)
        if okO and valid(owner) and GAME_NAME[owner:GetAddress()] then return GAME_NAME[owner:GetAddress()] end
        local okH, n = pcall(function() return c.CharacterHardcodedName:ToString() end)
        if okH and n and n ~= "" and n ~= "None" then return n end
        return nil
    end
    local fixProbed = false
    local FIX_ARGS = nil            -- learned arguments, or false: the call can't be made safely

    local function findFunction(obj, name)
        local fn
        pcall(function()
            local cls, depth = obj:GetClass(), 0
            while not fn and cls and valid(cls) and depth < 6 do
                depth = depth + 1
                cls:ForEachFunction(function(f)
                    if not fn and f:GetFName():ToString() == name then fn = f end
                end)
                cls = cls:GetSuperStruct()
            end
        end)
        return fn
    end

    local function learnFixArgs(c)
        if FIX_ARGS ~= nil then return FIX_ARGS end
        FIX_ARGS = {}
        local fn = findFunction(c, "ApplyCurrentCharacterSkin")
        if not fn then return FIX_ARGS end          -- can't look: call it without arguments
        local params = {}
        pcall(function()
            fn:ForEachProperty(function(p)
                params[#params + 1] = { name = p:GetFName():ToString(), cls = p:GetClass():GetFName():ToString() }
            end)
        end)
        local shown = {}
        for _, p in ipairs(params) do shown[#shown + 1] = p.cls .. " " .. p.name end
        if #params == 1 and params[1].cls == "NameProperty" then
            FIX_ARGS = "name"
            live("Fix look: ApplyCurrentCharacterSkin(%s) - calling it with each character's name", table.concat(shown, ", "))
        elseif #params == 1 and params[1].cls == "BoolProperty" then
            local low = params[1].name:lower()
            local v = not (low:find("skip") or low:find("keep") or low:find("^b?no") or low:find("dont")
                           or low:find("prevent") or low:find("disable")) and true or false
            FIX_ARGS = { v }
            live("Fix look: ApplyCurrentCharacterSkin(%s) - calling it with %s", table.concat(shown, ", "), tostring(v))
        elseif #params > 0 then
            FIX_ARGS = false
            live("Fix look: ApplyCurrentCharacterSkin(%s) - not called (unknown parameters)", table.concat(shown, ", "))
        end
        return FIX_ARGS
    end

    local function probeSkinComponent(c, err)
        if fixProbed then return end
        fixProbed = true
        live("Fix look: ApplyCurrentCharacterSkin failed on %s: %s", leafName(c) or "?", tostring(err))
        local names, seen = {}, {}
        pcall(function()
            local cls, depth = c:GetClass(), 0
            while cls and valid(cls) and depth < 6 do
                depth = depth + 1
                cls:ForEachFunction(function(fn)
                    local n = fn:GetFName():ToString()
                    if not seen[n] and (n:find("Skin") or n:find("Custom") or n:find("Apply") or n:find("Refresh")
                                        or n:find("Update") or n:find("Spawn")) then
                        seen[n] = true
                        names[#names + 1] = n
                    end
                end)
                cls = cls:GetSuperStruct()
            end
        end)
        table.sort(names)
        live("Fix look: skin component functions: %s", #names > 0 and table.concat(names, ", ") or "(could not list)")
    end

    Fix.look = function()
        inGame(function()
            local n, tried, noName, used = 0, 0, 0, {}
            for _, cn in ipairs({ "BP_CharacterSkinComponent_C", "BP_CinematicCharacterSkinComponent_C" }) do
                local ok, comps = pcall(FindAllOf, cn)
                for _, c in ipairs(ok and comps or {}) do
                    if valid(c) then
                        tried = tried + 1
                        local args = learnFixArgs(c)
                        if args == "name" then
                            local name = nameFor(c)
                            if not name then
                                noName = noName + 1
                            else
                                local okc, err = pcall(function() c:ApplyCurrentCharacterSkin(FName(name)) end)
                                if okc then n = n + 1 used[name] = true else probeSkinComponent(c, err) end
                            end
                        elseif args then
                            local okc, err = pcall(function() c:ApplyCurrentCharacterSkin(table.unpack(args)) end)
                            if okc then n = n + 1 else probeSkinComponent(c, err) end
                        end
                    end
                end
            end
            if n > 0 then
                for k in pairs(FORCED_FROM) do FORCED_FROM[k] = nil end   -- the game put its own outfits back
            end
            LAST_FIX = { n = n, tried = tried }
            local names = {}
            for k in pairs(used) do names[#names + 1] = k end
            table.sort(names)
            log("Fix look: the game re-dressed %d of %d character(s)%s%s", n, tried,
                #names > 0 and (" (" .. table.concat(names, ", ") .. ")") or "",
                noName > 0 and string.format("; %d without a known character name", noName) or "")
            delayGT(800, function() applyAll("after Fix look") end)
        end)
    end

    Fix.last = function() return LAST_FIX end
end

-- One file with everything needed to look at a session from outside: settings, selection, the
-- live log, the latest dump, the relevant UE4SS.log lines and the relocator's console output.
local function readAll(path, maxBytes)        -- the last maxBytes of a file (logs can be large)
    local f = io.open(path, "rb")
    if not f then return nil end
    local size = f:seek("end") or 0
    maxBytes = maxBytes or (2 * 1024 * 1024)
    f:seek("set", size > maxBytes and size - maxBytes or 0)
    local t = f:read("a") or ""
    f:close()
    if size > maxBytes then t = "(first " .. (size - maxBytes) .. " bytes left out)\n" .. t end
    return t
end

report = function(quiet)
    GT_STATE = "report"
    live("report: start")
    local f = io.open(FILES.REPORT, "w")
    if not f then log("cannot write %s", FILES.REPORT) return end
    -- report.txt is meant to be posted: Windows user names become <user>. First the name Windows
    -- reports, where it is a whole folder name; then whatever follows Users\ (also Users\\ in
    -- text written by Python).
    local user = os.getenv("USERNAME")
    local AS_FOLDER = { game = true, content = true, script = true, engine = true, mods = true,
                        paks = true, sandfall = true, binaries = true, win64 = true, ue4ss = true }
    local function redact(text)
        if user and #user >= 2 and not AS_FOLDER[user:lower()] then
            local u = user:gsub("%p", "%%%0")
            text = text:gsub("([\\/])" .. u .. "([\\/])", "%1<user>%2")
        end
        text = text:gsub("([Uu][Ss][Ee][Rr][Ss][\\/]+)[^\\/\r\n\"']+", "%1<user>")
        return text
    end
    local function section(title, text)
        f:write("\n==================== ", title, "\n", redact(text or "(missing)\n"))
    end
    local ok, err = pcall(function()
        f:write("E33Wardrobe ", VERSION, " report ", os.date("%Y-%m-%d %H:%M:%S"), "\n")
        section("settings.txt", readAll(FILES.SETTINGS))
        section("selection.txt (pick order: the last line wins where variants overlap)", readAll(FILES.SEL) or "(nothing selected)\n")
        section("live_log.txt (this session)", readAll(FILES.LIVE))
        section("live_log_previous.txt (the session before: after a freeze, this is the one)", readAll(FILES.LIVE_PREV))
        section("dump.txt (latest)", readAll(FILES.DUMP))
        local ue = readAll(modDir .. "../../UE4SS.log", 1024 * 1024)
        if ue then
            local keep, all = {}, {}
            for line in ue:gmatch("[^\r\n]+") do
                all[#all + 1] = line
                if line:find("E33Wardrobe", 1, true) or line:find("Error", 1, true) or line:find("error", 1, true) then
                    keep[#keep + 1] = line
                end
            end
            local tail = {}
            for i = math.max(1, #all - 80), #all do tail[#tail + 1] = all[i] end
            section("UE4SS.log: wardrobe lines and errors", table.concat(keep, "\n") .. "\n")
            section("UE4SS.log: last 80 lines", table.concat(tail, "\n") .. "\n")
        else
            section("UE4SS.log", "(could not read " .. modDir .. "../../UE4SS.log)\n")
        end
        local rc = readAll(modDir .. "../../../../../Content/Paks/~mods/_E33Wardrobe/relocate_console.txt", 200000)
        section("relocate_console.txt (relocator output, newest runs last)", rc)
    end)
    f:close()
    if not ok then log("report.txt stopped early: %s", tostring(err)) end
    if not quiet then log("wrote %s", FILES.REPORT) end
end

-- --------------------------------------------------------------------------- wiring

local MENU = {}                 -- from menu.lua: toggle, tick, wantsTick, registerHooks

-- Key binds are registered here, at the top level (UE4SS needs that). They run on UE4SS's
-- event-loop thread, so the callback only posts: the work runs in the game-thread loop.
local function bind(spec, fn, quiet)
    if not spec then return end                 -- config.lua can switch a key off with false
    if type(spec) ~= "table" or type(spec[1]) ~= "string" or Key[spec[1]] == nil then
        log("config.lua: %s is not a key name (see the list at the top of config.example.lua); not bound",
            tostring(type(spec) == "table" and spec[1] or spec))
        return
    end
    local mods, names = {}, type(spec[2]) == "table" and spec[2] or {}
    for _, m in ipairs(names) do
        if ModifierKey[m] == nil then
            log("config.lua: %s is not a modifier (use CONTROL, SHIFT or ALT); %s not bound", tostring(m), spec[1])
            return
        end
        table.insert(mods, ModifierKey[m])
    end
    local name = table.concat(names, "+") .. (#names > 0 and "+" or "") .. spec[1]
    local ok, err = pcall(RegisterKeyBind, Key[spec[1]], mods, function()
        post(function()
            if not quiet then live("key %s", name) end
            fn()
        end)
    end)
    if not ok then log("could not bind %s: %s", spec[1], tostring(err)) end
end

if SETTINGS.legacy_keys then                   -- legacy slot / variant cycling (settings.txt)
bind(KEYS.nextSlot, function()
    if not SETTINGS.legacy_keys or #SLOTS == 0 then return end
    currentSlot = currentSlot % #SLOTS + 1
    log(describe(currentSlot))
end)
bind(KEYS.prevSlot, function()
    if not SETTINGS.legacy_keys or #SLOTS == 0 then return end
    currentSlot = (currentSlot - 2) % #SLOTS + 1
    log(describe(currentSlot))
end)
bind(KEYS.nextVariant, function()
    if SETTINGS.legacy_keys and SLOTS[currentSlot] then setVariant(currentSlot, variantIndex(SLOTS[currentSlot]) + 1) end
end)
bind(KEYS.prevVariant, function()
    if SETTINGS.legacy_keys and SLOTS[currentSlot] then setVariant(currentSlot, variantIndex(SLOTS[currentSlot]) - 1) end
end)
end
bind(KEYS.reload, reload)
bind(KEYS.apply, function() applyAll() end)
bind(KEYS.dump, function() dump() report() end)   -- dump.txt + report.txt

local function onConsole(_, params)
    local a, b = params[1], params[2]
    onGT(function()
        live("console: wardrobe %s %s", tostring(a or ""), tostring(b or ""))
        if a == nil then listAll()
        elseif a == "menu" then
            if MENU.toggle then MENU.toggle() else log("menu not available (see the log above)") end
        elseif a == "dump" then dump()
        elseif a == "report" then dump() report()
        elseif a == "fix" then Fix.look()
        elseif a == "clean" then
            SETTINGS.clean = b ~= "off"
            saveSettings()
            if SETTINGS.clean then Clean.all("console") else Clean.restore() end
        elseif a == "reload" then reload()
        elseif a == "apply" then applyAll()
        else
            local si = tonumber(a)
            if SLOTS[si] then
                currentSlot = si
                setVariant(si, (b == nil or b == "off") and 0 or (tonumber(b) or 0))
            else log("no slot %s", tostring(a)) end
        end
    end)
    return true
end

-- New skin actors (outfit change, battle, cutscene, menu preview) are swapped on the next loop
-- tick (not inside BeginPlay, where the game may be loading or streaming), then checked again
-- ~0.7 s later for anything the game set up afterwards. Actors are kept by reference and
-- re-validated; no full object scans on this path.
local spawned, recheck, recheckQueued = {}, {}, false

local function recheckPending()
    local todo = recheck
    recheck = {}
    recheckQueued = false
    local before = passChanges
    for _, a in pairs(todo) do
        if valid(a) and isWardrobeActor(a) then
            local ok, err = pcall(applyToActor, a)
            if not ok then log("apply failed: %s", tostring(err)) end
        end
    end
    if passChanges > before then
        live("re-check after spawn: %d change(s)", passChanges - before)
        if afterPass then afterPass(true) end
    end
end

local function onSkinActor(a, delayOnly)
    live("game %s %s", delayOnly and "re-assigned" or "spawned", tostring(leafName(a)))
    if not delayOnly then spawned[a:GetAddress()] = a end
    recheck[a:GetAddress()] = a
    if not recheckQueued then
        recheckQueued = true
        later(math.max(50, SETTINGS.recheck_ms or 700), recheckPending)
    end
end

local function applySpawned()                   -- the game-thread loop
    if next(spawned) == nil then return end
    local todo = spawned
    spawned = {}
    for _, a in pairs(todo) do
        if valid(a) and isWardrobeActor(a) then
            GT_STATE = "skin spawn " .. tostring(leafName(a))
            local ok, err = pcall(applyToActor, a)
            if not ok then log("apply failed: %s", tostring(err)) end
        end
    end
end

local function paramGet(p)
    local ok, v = pcall(function() return p:get() end)
    if ok and v ~= nil then return v end
    return p
end

-- Skins may be pooled and re-shown without a new BeginPlay; the native assign policy is called
-- for every skin change, and tells us which character the skin belongs to.
local function onAssigned(owner, charName)
    if not valid(owner) then return end
    for _, compName in ipairs({ "BP_CharacterSkinComponent", "BP_CinematicCharacterSkinComponent" }) do
        local ok, sc = pcall(function() return owner[compName] end)
        if ok and valid(sc) then
            for _, prop in ipairs({ "SpawnedCharacterSkin", "SpawnedCharacterFace" }) do
                local ok2, skin = pcall(function() return sc[prop] end)
                if ok2 and valid(skin) then
                    local c = normChar(charName)
                    if c then CHAR_OF[skin:GetAddress()] = { name = skin:GetFullName(), char = c } end
                    live("game assigned %s to %s", tostring(leafName(skin)), tostring(charName))
                    onSkinActor(skin, true)
                end
            end
        end
    end
end

local POLICY_FUNCS = { "AssignBodySkin", "AssignBodySkinAsync", "AssignFaceSkin", "AssignFaceSkinAsync",
                       "AssignBodyAndFaceSkin", "AssignBodyAndFaceSkinAsync" }
local policyHooks, hooked = 0, false

-- Called once on the game thread: every hook of this mod is registered from there.
local function registerHooks()
    hooked = pcall(function()
        RegisterBeginPlayPostHook(function(actor)
            if SETTINGS.clean then
                local ka = paramGet(actor)
                if valid(ka) and isWardrobeActor(ka) then
                    later(1000, function() Clean.actor(ka, Clean.newStats()) end)
                end
            end
            if not SETTINGS.auto_apply or not anyActive() then return end
            local a = paramGet(actor)
            if valid(a) and isWardrobeActor(a) then onGT(onSkinActor, a, false) end
        end)
    end)
    for _, fn in ipairs(POLICY_FUNCS) do
        local ok = pcall(RegisterHook, "/Script/SandFall.CharacterSkinAssignPolicy:" .. fn, function() end,
            function(_, owner, charName)
                if not onGameThread() then return end
                local o = owner and paramGet(owner)
                local c
                if charName then
                    local okc, s = pcall(function() return paramGet(charName):ToString() end)
                    if okc then c = s end
                end
                Fix.noteName(o, c)                  -- the name Fix look passes back to the game
                -- a pooled skin re-shown without a BeginPlay: clean it too, picks or not
                if SETTINGS.clean and Clean.owner then later(1000, function() Clean.owner(o) end) end
                if not SETTINGS.auto_apply or not anyActive() then return end
                later(50, function() onAssigned(o, c) end)
            end)
        if ok then policyHooks = policyHooks + 1 end
    end
    -- After a level loads, one full pass also reaches actors that aren't skin actors (world / menu
    -- pawns showing a replaced base body), and learns their classes for the BeginPlay hook.
    pcall(RegisterLoadMapPreHook, function() if Clean.forget then Clean.forget() end end)
    pcall(RegisterLoadMapPostHook, function(_, world)
        local okw, wname = pcall(function() return leafName(paramGet(world)) end)
        live("map loaded: %s", okw and tostring(wname) or "?")
        if SETTINGS.auto_apply and anyActive() then later(3000, function() applyAll("after map load") end) end
        if SETTINGS.clean then later(3500, function() Clean.all("map loaded") end) end
    end)
    pcall(RegisterConsoleCommandHandler, "wardrobe", onConsole)
    if MENU.registerHooks then pcall(MENU.registerHooks) end
end

-- The game-thread loop: inbox (keys, clicks), the mod's timers, new skins, the menu, the
-- debounced apply pass. Its timestamp is the heartbeat the watchdog reads.
local function loopBody()
    GT_BEAT = os.time()
    loopTicks = loopTicks + 1
    if #INBOX > 0 then
        local evs = INBOX
        INBOX = {}
        for _, ev in ipairs(evs) do
            if type(ev) == "function" then onGT(ev) end
        end
    end
    if #SCHED > 0 then
        local due, keep = {}, {}
        for _, t in ipairs(SCHED) do
            if t.due <= loopTicks then due[#due + 1] = t else keep[#keep + 1] = t end
        end
        SCHED = keep
        for _, t in ipairs(due) do onGT(t.f) end
    end
    if next(spawned) ~= nil then onGT(applySpawned) end
    if MENU.wantsTick and MENU.wantsTick() then onGT(MENU.tick) end
    if PASS.due and loopTicks >= PASS.due then onGT(applyIfDue) end
    if SETTINGS.clean and loopTicks % 20 == 0 then onGT(Clean.keep) end
end

-- --------------------------------------------------------------------------- watchdog
-- The game-thread loop stamps GT_BEAT every tick. If that stops for 6 s, this async loop writes
-- one line with what the mod was doing (it only reads numbers and writes the log file; it never
-- calls into UE4SS). Reading it:
--   * "mod state: idle"  -> the game thread is stuck outside the mod (game, engine, UE4SS);
--   * "mod state: apply pass / skin spawn / menu / dump" -> stuck inside an engine call the mod
--     made (the "change"/"loading" lines just before it name the call);
--   * no WATCHDOG line at all -> something holds the Lua lock (UE4SS itself) or the process died.
-- A WATCHDOG line during a long loading screen is normal. Only a process dump (Task Manager >
-- right-click the game > Create dump file) shows the exact stack.
local wdLast = 0
if HAS_GT_LOOP then pcall(LoopAsync, 1000, function()
    pcall(function()
        if not liveF or loopTicks == 0 then return end      -- not before the loop has started
        local now = os.time()
        if now - GT_BEAT >= 6 and now - wdLast >= 15 then
            wdLast = now
            live("WATCHDOG: the game thread has not run for %d s; mod state: %s (since %s)", now - GT_BEAT, GT_STATE,
                os.date("%H:%M:%S", GT_STATE_SINCE))
        end
    end)
    return false
end) end

-- A report right away: after a freeze, starting the game once leaves report.txt with the frozen
-- session (live_log_previous.txt) in it. Files only; nothing in the world is touched.
if liveF then pcall(report, true) end          -- with the previous session: after a freeze, starting is enough
GT_STATE = "idle"

-- --------------------------------------------------------------------------- in-game menu

local skinCount = nil
local API = {
    log = log, settings = SETTINGS, defaults = DEFAULT_SETTINGS, saveSettings = saveSettings,
    keys = KEYS, bind = bind, lastApplied = function() return PASS.last end,
    slots = function() return SLOTS end,
    variantIndex = variantIndex,
    selection = function() return copySel(selection) end,
    setVariant = setVariant, setSelection = setSelection, undo = undo,
    canUndo = function() return #HISTORY > 0 end,
    applyAll = applyAll, reload = reload, dump = dump,
    loadPresets = loadPresets, savePresets = savePresets,
    rebuildActive = rebuildActive,
    countSkins = function()                         -- full object scan: only on a button press
        local n = 0
        forEachSkin(function() n = n + 1 end)
        skinCount = n
        return n
    end,
    skinCount = function() return skinCount end,
    slotState = slotState, overlaps = overlaps,
    gt = onGT,                                  -- run on the game thread (marks it for inGame)
    post = post, later = later,                 -- post: any thread -> game-thread loop
    flushPending = function() if gtDepth > 0 then runCallbackEnd() end end,   -- menu: apply, then draw
    isWear = function(id) return wearSet()[id] == true end,
    canWear = function(slot) return slot.character ~= nil and hasMesh(slot) end,
    isTechnical = isTechnical, outfitName = outfitName,
    targetOutfit = function(slot) return targetOutfit(slot) end,
    wornBy = function(char) return WORN[char] end,
    loadedChars = function()
        local out = {}
        for c in pairs(WORN) do out[#out + 1] = c end
        table.sort(out)
        return out
    end,
    slotShown = function(id) return SHOWN[id] end,
    applyPending = function() return PASS.due ~= nil or PASS.queued end,
    setWear = function(id, on)
        AUTOWEAR_PENDING[id] = nil                  -- the player decided
        setWearFlag(id, on)
    end,
    autoWorn = function(id) return AUTO_WORN[id] == true end,
    live = live, report = function() inGame(function() dump() report() end) end,
    onGameThread = onGameThread,
    fixLook = Fix.look, lastFix = Fix.last,
    -- Clean on / off (saved): on blanks the blood / dirt masks now and on every character that comes
    -- later; off puts the game's masks back
    setClean = function(on)
        SETTINGS.clean = on and true or false
        saveSettings()
        local r
        inGame(function() if on then r = Clean.all("switched on") else r = Clean.restore() end end)
        return r
    end,
    lastClean = function() return Clean.last() end,
    recording = function() return liveF ~= nil end,
    setRecord = function(on)
        SETTINGS.record = on and true or false
        saveSettings()
        if on then openLive() else closeLive() end
    end,
    inGame = inGame, valid = valid,
}
do
    local menuOk, menuErr = pcall(function()
        local m = dofile(scriptDir .. "menu.lua")
        m.init(API)                                 -- registers its key binds here (top level)
        MENU.toggle, MENU.tick, MENU.wantsTick, MENU.registerHooks = API.toggleMenu, m.tick, m.wantsTick, m.registerHooks
    end)
    if not menuOk then log("menu not available: %s", tostring(menuErr)) end
end

-- --------------------------------------------------------------------------- start
-- One hop to the game thread (nothing else is queued or hooked yet, so this is the one safe
-- cross-thread call); hooks, the first load and the loop all start from there.
local function startOnGameThread()
    registerHooks()
    if not hooked then log("RegisterBeginPlayPostHook unavailable: new skins are only handled by passes") end
    reload()
    local ok, err = pcall(LoopInGameThreadWithDelay, TICK_MS, function() onGT(loopBody) end)
    if not ok then
        log("LoopInGameThreadWithDelay failed (%s): the mod stays off. Update UE4SS.", tostring(err))
        return
    end
    live("game-thread work runs in one game-thread loop every %d ms (LoopInGameThreadWithDelay)", TICK_MS)
    log("%s ready (%d policy hook(s)) - press %s for the menu. %s", VERSION, policyHooks,
        (KEYS.menu and KEYS.menu[1]) or "?", describe(currentSlot))
end
if not HAS_GT_LOOP then
    -- Without it every timer and key would have to be queued to the game thread from another
    -- thread, which races and can crash these builds (UE4SS issues #1180, #1445).
    log("This UE4SS build is too old for E33Wardrobe: it has no LoopInGameThreadWithDelay. "
        .. "Use a UE4SS experimental build from December 2025 or newer (tested: 3.0.1-1125-g527a483b). "
        .. "The mod stays off.")
else
    local ok, err = pcall(ExecuteInGameThread, function() onGT(startOnGameThread) end)
    if not ok then log("could not reach the game thread (%s); the mod stays off", tostring(err)) end
end
