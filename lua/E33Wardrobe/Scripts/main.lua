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
local VERSION = "1.3.1"                         -- the same as tools/e33common.py VERSION
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
                PRESETS = modDir .. "presets.txt", FAV = modDir .. "favorites.txt", LIVE = modDir .. "live_log.txt",
                LIVE_PREV = modDir .. "live_log_previous.txt", REPORT = modDir .. "report.txt",
                COMMANDS = modDir .. "commands.txt" }

-- Runtime settings, changed from the menu and kept in settings.txt.
local SETTINGS = { scoping = true, auto_apply = true, recheck_ms = 700, side = "right", scale = 100,
                   block_look = true, cursor = true, ui_input = false, legacy_keys = false,
                   random_off = false, slideshow_s = 4, locks = "", wear = "", match_groups = true,
                   record = true, auto_report = false, show_technical = false, tab = "", peek_s = 3,
                   auto_wear = true, clean = false, scene_copies = true, trace = true,
                   b_soft = "auto", b_swap = "off" }
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
-- Breadcrumbs for freezes: before each engine call that could hang, the game thread notes what it
-- is about to do (plain strings, no engine calls). When the game thread stalls, the watchdog writes
-- the last ones, so the log names the call that never returned (no memory dump needed).
-- Also the numbers behind stutter: time per actor and per pass, game-thread gaps (hitches).
-- settings.txt "trace = false" turns the breadcrumbs off.
local TRACE = { ring = {}, n = 0, size = 40, step = "-", at = 0, on = true, beat = nil,
                tickMs = 0, lastTick = nil, lastHitch = -10,
                st = { actors = 0, actorMs = 0, slowest = 0, slowName = "", sets = 0, passes = 0, passMs = 0,
                       hitches = 0, worst = 0, since = os.clock() } }
local function step(s)
    if not TRACE.on then return end
    local t = os.clock()
    local acc = TRACE.acc                          -- in a timed look: time per step, for "slow look"
    if acc then acc[TRACE.step] = (acc[TRACE.step] or 0) + (t - TRACE.at) end
    TRACE.step, TRACE.at = s, t
    local e = TRACE.ring[TRACE.n]
    if e and e.s == s then e.t, e.k = t, (e.k or 1) + 1 return end   -- a repeat: counted, not another line
    TRACE.n = TRACE.n % TRACE.size + 1
    TRACE.ring[TRACE.n] = { t = t, s = s }
end
TRACE.on = SETTINGS.trace ~= false
local B = {}                    -- the redesign-B probe (see "redesign B probe" below)
-- Engine reads kept for the rest of ONE top-level game-thread call (onGT; the loop runs each tick
-- as one), because every Lua -> UE4SS call costs time and the same materials, meshes and classes
-- are read again and again in a look or a pass. Safe within one call: the engine frees and reuses
-- objects only between frames (garbage collection), so an address names the same object until
-- the call ends. Created at the start of the call, dropped at its end; nil outside game-thread
-- calls (nothing is kept there). Started again after anything that runs the game's own code or
-- loads assets (TRACE.fresh), and setTexture forgets what it changes (TRACE.forget).
TRACE.memo = nil
TRACE.fresh = function()
    if TRACE.memo or gtDepth > 0 then TRACE.memo = { tp = {} } end
end
-- f(o, ...) once per game-thread call for the same object (o valid); its results are shared, so
-- callers must not change them
TRACE.once = function(kind, o, f, ...)
    local memo = TRACE.memo
    if not memo then return f(o, ...) end
    local okA, a = pcall(function() return o:GetAddress() end)
    if not okA or a == nil then return f(o, ...) end
    local m = memo[kind]
    if not m then m = {} memo[kind] = m end
    local r = m[a]
    if r == nil then r = table.pack(f(o, ...)) m[a] = r end
    return table.unpack(r, 1, r.n)
end
-- Scene actors (battle, cutscene, dialogue, level sequence) as they begin play, so the live log
-- shows which scene the game's character copies belong to. One name lookup per class, cached.
TRACE.sceneCls, TRACE.sceneAt = {}, {}
TRACE.scene = function(a)
    local function ok(o)                        -- valid() is defined further down
        local okv, r = pcall(function() return o:IsValid() end)
        return okv and r == true
    end
    if not ok(a) then return end
    local okc, c = pcall(function() return a:GetClass() end)
    if not okc or not ok(c) then return end
    local okA, addr = pcall(function() return c:GetAddress() end)
    if not okA then return end
    local name = TRACE.sceneCls[addr]
    if name == nil then
        local okn, n = pcall(function() return c:GetFName():ToString() end)
        n = okn and n or ""
        local low = n:lower()
        name = (low:find("battle") or low:find("cine") or low:find("dialog") or low:find("sequence")
                or low:find("encounter") or low:find("cutscene")) and n or false
        TRACE.sceneCls[addr] = name
    end
    if not name then return end
    local now = os.clock()
    if now - (TRACE.sceneAt[name] or -10) < 5 then return end
    TRACE.sceneAt[name] = now
    live("scene: %s began", name)
end
-- "Busy": a burst of new actors (a map, a cutscene or a battle being set up) or a long frame in
-- the last 0.5 s. New skins and passes wait for calm (at most 10 s): both freezes on PC were in
-- the mod's look at a just-spawned skin during such a burst.
TRACE.bp, TRACE.busyAt, TRACE.tick = 0, -1000, 0   -- loop ticks: of the last burst, now
TRACE.busy = function() return TRACE.tick - TRACE.busyAt < 10 end           -- 10 ticks = 0.5 s
TRACE.timed = function(name, f, ...)          -- f(...) with its time added to the statistics
    local outer = TRACE.acc
    TRACE.acc = TRACE.on and {} or nil
    step("look " .. name)
    local t0 = os.clock()
    local ok, err = pcall(f, ...)
    local t1 = os.clock()
    local ms = (t1 - t0) * 1000
    local acc = TRACE.acc
    TRACE.acc = outer
    local st = TRACE.st
    st.actors, st.actorMs = st.actors + 1, st.actorMs + ms
    if ms > st.slowest then st.slowest, st.slowName = ms, name end
    if ms >= 100 then
        -- where a slow look spent its time (PC: 150-310 ms looks, of which the logged loads and
        -- mesh sets explained only ~20 ms)
        local parts = {}
        if acc then
            acc[TRACE.step] = (acc[TRACE.step] or 0) + (t1 - TRACE.at)
            for k, v in pairs(acc) do parts[#parts + 1] = { k, v } end
            table.sort(parts, function(a, b) return a[2] > b[2] end)
            for i = 1, #parts do
                parts[i] = i <= 4 and string.format("%s %d ms", parts[i][1], math.floor(parts[i][2] * 1000 + 0.5)) or nil
            end
        end
        live("slow look: %s %d ms; most time in: %s", name, math.floor(ms + 0.5),
            #parts > 0 and table.concat(parts, ", ") or "(trace = false)")
    end
    return ok, err, ms
end
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
    if gtDepth == 1 then
        GT_STATE, GT_STATE_SINCE = "mod work", os.time()
        TRACE.fresh()
    end
    local ok, err = pcall(f, ...)
    if gtDepth == 1 then
        runCallbackEnd()
        TRACE.memo = nil
        GT_STATE, GT_STATE_SINCE = "idle", os.time()
        if TRACE.step ~= "idle" then step("idle") end
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

local function rebuildActive() ACTIVE_CACHE = {} FORCE_CACHE = {} if B.changed then pcall(B.changed) end end

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
                        a[k] = { pkg = e[1], obj = e[2], class = e[3], meshes = meshes, vid = v.id, under = a[k],
                                 orig = orig }
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

-- Slots tied to no character (one mod for several characters, e.g. a costume with a mesh for
-- Lune, Maelle and Sciel): which character a mesh belongs to comes from its game path. Filled
-- in below, once charsIn exists.
local Wear = {}

-- Mesh to put on a character's body over whatever outfit it wears: the selected variant's
-- skeletal mesh in a "wear" slot for that character (the later pick wins). In a slot tied to no
-- character, only that character's own mesh counts.
local function forcedFor(char)
    if not char then return nil end
    local f = FORCE_CACHE[char]
    if f ~= nil then return f or nil end
    local wear, best, bestPick = wearSet(), false, -1
    for _, slot in ipairs(SLOTS) do
        if wear[slot.id] and (slot.character == char or (not slot.character and Wear.slotChars(slot)[char]))
           and (PICK[slot.id] or 0) > bestPick then
            local vid = selection[slot.id]
            for _, v in ipairs(slot.variants) do
                if v.id == vid then
                    local pick = Wear.meshFor(v, char, slot.character)
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

-- Valid for UE4SS AND safe to read: not being destroyed, not garbage, fully loaded. UE4SS's
-- IsValid looks at none of this (PC: the mod wrote to actors already renamed "None"; both freezes
-- happened while reading actors the game had just spawned during loading). UE 5.4 values, as
-- numbers (UE4SS's own flag tables are from UE4): RF_NeedLoad 0x400, RF_NeedPostLoad 0x1000,
-- RF_NeedPostLoadSubobjects 0x2000, RF_BeginDestroyed 0x8000, RF_FinishDestroyed 0x10000;
-- internal Garbage 1<<21, Async 1<<26, AsyncLoading 1<<27. If UE4SS can't answer, it counts as
-- alive (as before). Skips are counted in the per-minute stats line. known: o was just found valid.
-- Which of alive()'s flags an object has (names), for the log; nil if none or UE4SS can't say.
TRACE.FLAGS = { { 0x400, "NeedLoad" }, { 0x1000, "NeedPostLoad" }, { 0x2000, "NeedPostLoadSubobjects" },
                { 0x8000, "BeginDestroyed" }, { 0x10000, "FinishDestroyed" } }
TRACE.IFLAGS = { { 0x200000, "Garbage" }, { 0x4000000, "Async" }, { 0x8000000, "AsyncLoading" } }
TRACE.aliveWhy = function(o)
    if not valid(o) then return "invalid" end
    local out = {}
    for _, f in ipairs(TRACE.FLAGS) do
        local ok, r = pcall(function() return o:HasAnyFlags(f[1]) end)
        if ok and r == true then out[#out + 1] = f[2] end
    end
    for _, f in ipairs(TRACE.IFLAGS) do
        local ok, r = pcall(function() return o:HasAnyInternalFlags(f[1]) end)
        if ok and r == true then out[#out + 1] = f[2] .. " (internal)" end
    end
    return #out > 0 and table.concat(out, ", ") or nil
end

local function alive(o, known)
    if not known and not valid(o) then return false end
    local okF, f = pcall(function() return o:HasAnyFlags(0x1B400) end)
    local okI, i = pcall(function() return o:HasAnyInternalFlags(0x0C200000) end)
    if (okF and f == true) or (okI and i == true) then
        TRACE.st.skipped = (TRACE.st.skipped or 0) + 1
        return false
    end
    return true
end

-- "/Game/A/B" for a top-level asset ("Class /Game/A/B.B"). Subobjects such as the game's
-- dynamic material instances ("... /Game/Map.Map:PersistentLevel.Actor.Comp.MID_0") and
-- transient objects return nil. The second value is the object's name ("B", the same as leafName),
-- so callers that need both make one call. known: obj was just found valid.
local function pkgPath(obj, known)
    if not known and not valid(obj) then return nil end
    local ok, full = pcall(function() return obj:GetFullName() end)
    if not ok or not full then return nil end
    local path, rest = full:match("^%S+%s+([^%.:]+)%.(.*)$")
    if not path or path:sub(1, 1) ~= "/" or rest:find("[%.:]") then return nil end
    if path:find("^/Engine/Transient") or path:find("^/Temp/") then return nil end
    return path, rest
end

-- Never call a method on an object UE4SS hands back as "invalid" (a missing link, a null array
-- entry): inside UE4SS that reads address 0 and is an access violation, which pcall can't catch.
-- PC: one froze the game (GetClass() on a missing attach parent; a frame limiter's exception
-- handler then hung instead of letting the game crash).
local function fullPath(obj)
    if not valid(obj) then return nil end
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

local function leafName(obj, known)
    if not known and not valid(obj) then return nil end
    local ok, n = pcall(function() return obj:GetFName():ToString() end)
    return ok and n or nil
end

-- "class address|class name" of a valid object, and its class (false: none). Once per call.
TRACE.classKey = function(o)
    return TRACE.once("class", o, function()
        local okc, c = pcall(function() return o:GetClass() end)
        if not okc or not valid(c) then return false end
        local okk, key = pcall(function() return c:GetAddress() .. "|" .. tostring(leafName(c, true)) end)
        return okk and key or tostring(c), c
    end)
end

-- Both kinds of arrays: TArray properties (userdata with ForEach) and UFunction return
-- values (plain Lua tables of RemoteUnrealParam that need :get()). A property the object doesn't
-- have (StaticMesh.Materials, Material.TextureParameterValues) reads as an invalid object: no
-- ForEach on that (see fullPath).
local function arrayItems(arr)
    local out = {}
    if arr == nil then return out end
    local okv, isv = pcall(function() return arr:IsValid() end)
    if okv and isv == false then return out end
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
-- GetAsset finds an asset already in memory or loads it: 0-1 ms on PC. Until fix14 StaticFindObject
-- came first, and every asset it didn't find cost 13 ms (small maps) to 27 ms (world map) - it
-- seems to search all objects - although GetAsset then had most of them at once (PC, 15 Oct: 179
-- such lookups made up most of the 150-360 ms looks). StaticFindObject is only the last resort.
-- "loading" is logged before the first use of an asset in a map (a hang there names it).
local ARH, FAILED = nil, {}
TRACE.used = {}                 -- assets asked for in this map (cleared on map load)
local function loadObj(pkg, obj)
    local full = pkg .. "." .. obj
    if not TO_ORIGINAL[pkg:lower()] then
        -- a game asset (not one of the mod's relocated copies, which the game never streams) may be
        -- streaming in right now: GetAsset would load it synchronously on the game thread. Found
        -- and still loading = not now, as before fix14. These are mostly in memory (cheap hits).
        step("StaticFindObject " .. full)
        local o = StaticFindObject(full)
        if valid(o) then return alive(o) and o or nil end
    end
    if FAILED[full] then return nil end
    if liveF and not TRACE.used[full] then live("    loading %s", full) end
    local first = not TRACE.used[full]
    TRACE.used[full] = true
    local t0 = os.clock()
    if not valid(ARH) then ARH = StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers") end
    if valid(ARH) then
        step("GetAsset " .. full)
        local ok, r = pcall(function() return ARH:GetAsset({ PackageName = fname(pkg), AssetName = fname(obj) }) end)
        -- a real load runs engine code: nothing read before is kept. An asset already in memory
        -- comes back in well under 1 ms (PC: 0 ms for most), so a call that took 1 ms or more loaded.
        local ms = (os.clock() - t0) * 1000
        if ms >= 1 or not (ok and valid(r)) then TRACE.fresh() end
        if ms >= 50 and liveF then live("    slow GetAsset: %s took %d ms", full, math.floor(ms + 0.5)) end
        if ok and valid(r) then
            if liveF and first then live("    loaded (%d ms)", math.floor(ms + 0.5)) end
            if not alive(r, true) then return nil end           -- still loading: the next look gets it
            return r
        end
    end
    step("load (LoadAsset) " .. full)
    pcall(LoadAsset, full)
    step("StaticFindObject " .. full)
    local o = StaticFindObject(full)
    if valid(o) then return alive(o, true) and o or nil end
    FAILED[full] = true
    log("could not load %s", full)
    return nil
end

local CLS = {}
local function cls(path)                       -- engine classes; checked once per game-thread call
    local memo = TRACE.memo
    if memo and memo.cls and memo.cls[path] then return CLS[path] end
    if not valid(CLS[path]) then
        CLS[path] = StaticFindObject(path)
        if not valid(CLS[path]) then return CLS[path] end
    end
    if memo then memo.cls = memo.cls or {} memo.cls[path] = true end
    return CLS[path]
end

-- A property read by name only when its type is known to be safe to read. PC dump: a character's
-- "Face" property was a weak/soft reference (bytes 43 00 00 00 04 00 00 00: object index 0x43,
-- serial 4), and this UE4SS build reads those as a plain object pointer and crashes inside the
-- game (UE4SS issue #1433), before any check can run. The types come from the class itself
-- (metadata, read once per class). Where UE4SS can't list them, the read goes ahead as before.
local PROP_TYPES = {}         -- class address|name -> { property name -> type name } (false: can't list)
local function propOf(obj, name, ...)
    if not valid(obj) then return nil end
    local key, c = TRACE.classKey(obj)
    if not key then return nil end
    -- A read by name walks the class's property list. PC 17 Oct crash (UE4SS AV in
    -- FField::GetFName under UStruct::FindProperty): a camp actor's "Face", 3 s after a fast
    -- travel into camp. Guess: its class was still loading or being destroyed. Such a class is
    -- not read; the object is looked at again later. Once per class per game-thread call.
    if not TRACE.once("classAlive", c, function(cl) return alive(cl, true) end) then
        TRACE.clsSkip = TRACE.clsSkip or {}
        if not TRACE.clsSkip[key] then
            TRACE.clsSkip[key] = true
            live("  skipped reading %s of %s: its class is %s", tostring(name), tostring(leafName(obj)),
                tostring(TRACE.aliveWhy(c) or "not ready"))
        end
        return nil
    end
    local t = PROP_TYPES[key]
    if t == nil then
        t = {}
        local listed, s, depth = false, c, 0
        while valid(s) and depth < 16 do
            local okF = pcall(function()
                s:ForEachProperty(function(pr)
                    local n = pr:GetFName():ToString()
                    if t[n] == nil then t[n] = pr:GetClass():GetFName():ToString() end
                end)
            end)
            listed = listed or okF
            local okS, sup = pcall(function() return s:GetSuperStruct() end)
            if not okS then break end
            s, depth = sup, depth + 1
        end
        if not listed then t = false end
        PROP_TYPES[key] = t
    end
    if t then
        local ty, ok = t[name], false
        for i = 1, select("#", ...) do if ty == select(i, ...) then ok = true end end
        if not ok then return nil end
    end
    local okv, v = pcall(function() return obj[name] end)
    if okv then return v end
    return nil
end

local function isA(o, path, known)            -- known: o was just found valid
    local c = cls(path)
    local memo = TRACE.memo
    if not (memo and memo.cls and memo.cls[path]) and not valid(c) then return false end
    if not known and not valid(o) then return false end
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

-- The variant's body mesh for `char`: in a slot tied to a character any of its skeletal meshes
-- (an outfit skin or a body base first), else only a mesh whose game path names that character.
Wear.meshFor = function(v, char, slotChar)
    local pick
    for orig, e in pairs(v.map or {}) do
        if e[3] == "SkeletalMesh" and (slotChar or charsIn(orig)[char]) then
            local o = orig:lower()
            local score = (o:find("/customization/skin/", 1, true) or o:find("_placeholder", 1, true)) and 2 or 1
            if not pick or score > pick.score then
                pick = { pkg = e[1], obj = e[2], score = score, vid = v.id, orig = orig }
            end
        end
    end
    return pick
end

-- Characters whose body meshes a variant brings (from the meshes' game paths).
Wear.variantChars = function(v)
    local out = {}
    for orig, e in pairs(v.map or {}) do
        if e[3] == "SkeletalMesh" then
            for c in pairs((charsIn(orig))) do out[c] = true end
        end
    end
    return out
end

-- The same over all of a slot's variants (kept on the slot; SLOTS is rebuilt on reload).
-- (Split slots below have a character, so this is only asked of slots tied to nobody.)
Wear.slotChars = function(slot)
    if not slot._chars then
        local out = {}
        for _, v in ipairs(slot.variants or {}) do
            for c in pairs(Wear.variantChars(v)) do out[c] = true end
        end
        slot._chars = out
    end
    return slot._chars
end

-- A slot tied to nobody whose meshes belong to several characters (one costume with a mesh for
-- Lune, Maelle and Sciel, or a mod with a Lune and a Sciel option) becomes one slot per character.
-- Each holds that character's assets plus the ones that name nobody, so each character is
-- switched on and off on its own. Ids get "@<character>"; Wear.split maps the old id to them.
Wear.split = {}
Wear.splitByCharacter = function()
    Wear.split = {}
    local out = {}
    for _, slot in ipairs(SLOTS) do
        local chars = {}
        if not slot.character then for c in pairs(Wear.slotChars(slot)) do chars[#chars + 1] = c end end
        if #chars < 2 then
            out[#out + 1] = slot
        else
            table.sort(chars)
            local per = {}
            for _, c in ipairs(chars) do
                local ns = {}
                for k, v in pairs(slot) do if k ~= "_chars" then ns[k] = v end end
                ns.id, ns.character, ns.splitFrom, ns.variants = slot.id .. "@" .. c, c, slot.id, {}
                for _, v in ipairs(slot.variants or {}) do
                    -- whose option it is: the character whose body mesh it brings (a Sciel option
                    -- may also carry textures kept in Lune's folder); without a mesh, any asset
                    local map, meshFor, anyFor, hasMesh = {}, false, false, false
                    for orig, e in pairs(v.map or {}) do
                        local who, n = charsIn(orig)
                        if n == 0 or who[c] then map[orig] = e end
                        if e[3] == "SkeletalMesh" then hasMesh = true if who[c] then meshFor = true end end
                        if who[c] then anyFor = true end
                    end
                    local mine = meshFor or (not hasMesh and anyFor)
                    if mine then
                        local nv = {}
                        for k, x in pairs(v) do nv[k] = x end
                        nv.id, nv.map, nv.base = v.id .. "@" .. c, map, v.base or v.id
                        ns.variants[#ns.variants + 1] = nv
                    end
                end
                if #ns.variants > 0 then out[#out + 1] = ns per[c] = ns end
            end
            Wear.split[slot.id] = per
        end
    end
    for k = #SLOTS, 1, -1 do SLOTS[k] = nil end
    for k, sl in ipairs(out) do SLOTS[k] = sl end
end

-- Picks and Wear flags saved under a slot that is now split: carried over to each character's slot.
Wear.migrate = function()
    local moved = false
    for old, per in pairs(Wear.split) do
        local vid = selection[old]
        if vid then
            selection[old] = nil
            moved = true
            for c, ns in pairs(per) do
                for _, v in ipairs(ns.variants) do
                    if v.id == vid .. "@" .. c then selection[ns.id] = v.id PICK[ns.id] = PICK[old] end
                end
            end
        end
    end
    local ids, wmoved = {}, false
    for id in (SETTINGS.wear or ""):gmatch("[^|]+") do
        if Wear.split[id] then
            wmoved = true
            for _, ns in pairs(Wear.split[id]) do ids[#ids + 1] = ns.id end
        else
            ids[#ids + 1] = id
        end
    end
    if wmoved then table.sort(ids) SETTINGS.wear = table.concat(ids, "|") saveSettings() end
    return moved
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
-- Actors the game dressed as "Default" (the copies it makes for dialogue and battle), and their
-- owners: address -> full name. settings.txt "scene_copies = false" leaves them alone (a test:
-- PC, dialogue stopped appearing while the mod kept re-dressing such copies).
local SCENE_COPY = {}
-- Skin actors seen, by address: { a = object, name = full name, owner = owner's full name }. When
-- the game re-assigns a skin to an owner, these are what get looked at again. Never read through
-- the owner's properties (owner.BP_CharacterSkinComponent.SpawnedCharacterSkin): at the start of
-- a battle such a reference can point to an object the game already freed, and UE4SS crashes
-- while wrapping it (PC dump: IsA inside auto_construct_object), before any check can run.
local KNOWN_SKINS = {}

local function propString(o, name)
    local v = propOf(o, name, "NameProperty", "StrProperty", "TextProperty")
    if v == nil then return nil end
    if type(v) == "string" then return v end
    local okv, isv = pcall(function() return v:IsValid() end)    -- no such property: an invalid object
    if okv and isv == false then return nil end
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

-- An actor's skin components (BP_CharacterSkinComponent_C and its cutscene child), from its own
-- component list, never through its properties: camp characters hold theirs in a Blueprint
-- property, and reading camp Blueprint properties by name crashed UE4SS twice (see meshComponents).
-- The component class is looked up each time (a Blueprint class: no address kept across frames).
TRACE.skinComps = function(o)
    return TRACE.once("skinComps", o, function()
        step("skin components: K2_GetComponentsByClass")
        local okc, c = pcall(StaticFindObject,
            "/Game/Gameplay/CharacterCustomization/Blueprints/BP_CharacterSkinComponent.BP_CharacterSkinComponent_C")
        if not (okc and valid(c)) then return {} end
        local ok, arr = pcall(function() return o:K2_GetComponentsByClass(c) end)
        local out = {}
        for _, sc in ipairs(ok and arrayItems(arr) or {}) do if valid(sc) then out[#out + 1] = sc end end
        return out
    end)
end

-- Once per game-thread call per actor (a re-check asks before and while it looks at a skin);
-- onAssigned forgets it when the game names the actor's character.
local function characterOf(actor)
    return TRACE.once("char", actor, function()
        local known = CHAR_OF[actor:GetAddress()]
        if known then
            local ok, n = pcall(function() return actor:GetFullName() end)
            if ok and n == known.name then return known.char end
            CHAR_OF[actor:GetAddress()] = nil            -- address reused by a new object
        end
        local c
        step("character: cutscene skin component")
        -- cinematic, menu and camp pawns name their character on their skin component
        for _, sc in ipairs(TRACE.skinComps(actor)) do
            c = normChar(propString(sc, "CharacterHardcodedName"))
            if c then return c end
        end
        step("character: owner")
        local owner = ownerOf(actor)
        step("character: name properties of owner/actor")
        for _, o in ipairs({ owner, actor }) do
            if valid(o) then
                for _, prop in ipairs({ "CharacterHardcodedName", "HardcodedNameID", "CharacterName" }) do
                    c = normChar(propString(o, prop))
                    if c then return c end
                end
                local data = propOf(o, "CharacterData", "ObjectProperty")
                if valid(data) then
                    c = normChar(propString(data, "HardcodedNameID"))
                    if c then return c end
                end
            end
        end
        -- last resort: exactly one character name in the skin class path (e.g. ".../Lune/BP_..._C")
        step("character: class path")
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
    end)
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
local function variantOwned(obj, path)          -- path: obj's pkgPath, if known
    local p = path or pkgPath(obj)
    if not p then return false end
    local k = p:lower()
    return TO_ORIGINAL[k] ~= nil or MOD_ONLY[k] == true
end

local function isMID(m) return valid(m) and isA(m, "/Script/Engine.MaterialInstanceDynamic", true) end

local GLOBAL_PARAMETER = 2                     -- EMaterialParameterAssociation::GlobalParameter

-- Within one game-thread call, each material's result is kept (TRACE.memo.tp, by address) with the
-- result of every parent on its chain, so parents shared by all slots and copies of a character
-- are read once. Kept only for a chain read to its end (none of it loading). A result is shared:
-- callers must not change it. setTexture forgets every result that includes the instance it sets.
local function textureParams(mat)              -- key -> {info, tex}, child values win
    step("texture parameters of a material")
    local memo = TRACE.memo and TRACE.memo.tp
    local levels, guard, m, top, whole = {}, 0, mat, nil, true
    while guard < 8 do
        if not valid(m) then break end
        local addr
        if memo then
            local okA, a = pcall(function() return m:GetAddress() end)
            addr = okA and a or nil
            local hit = addr and memo[addr]
            if hit and guard + hit.hops <= 8 then top = hit break end
        end
        if not alive(m, true) then whole = false break end      -- loading or being destroyed
        guard = guard + 1
        local own, seen = { addr = addr }, {}                    -- this level's parameters, in order
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
                    if not seen[key] then
                        seen[key] = true
                        own[#own + 1] = { key, { info = info, tex = tp.ParameterValue } }
                    end
                end
            end
        end
        levels[#levels + 1] = own
        local okp, parent = pcall(function() return m.Parent end)
        if not okp then break end
        m = parent
    end
    if guard >= 8 then whole = false end
    -- from the top parent down: a level's own values, then its parent's (same order as one walk)
    local below = top
    for j = #levels, 1, -1 do
        local own = levels[j]
        local out, list, chain = {}, {}, {}
        for _, it in ipairs(own) do out[it[1]] = it[2] list[#list + 1] = it end
        if below then
            for _, it in ipairs(below.list) do
                if out[it[1]] == nil then out[it[1]] = it[2] list[#list + 1] = it end
            end
            for a in pairs(below.chain) do chain[a] = true end
        end
        if own.addr then chain[own.addr] = true end
        below = { out = out, list = list, chain = chain, hops = (below and below.hops or 0) + 1 }
        if memo and whole and own.addr then memo[own.addr] = below end
    end
    return below and below.out or {}
end
-- A texture parameter's texture: valid? and its path and name (read once per call, kept on tp).
TRACE.tex = function(tp, wantPath)
    if tp.ok == nil then tp.ok = valid(tp.tex) end
    if wantPath and tp.ok and tp.path == nil then
        local p, o = pkgPath(tp.tex, true)
        tp.path, tp.obj = p or false, o
    end
    return tp.ok, tp.path or nil, tp.obj
end
-- mid's texture parameters are about to change: forget the kept results that include it
TRACE.forget = function(mid)
    local memo = TRACE.memo and TRACE.memo.tp
    if not memo then return end
    local okA, a = pcall(function() return mid:GetAddress() end)
    if not okA then TRACE.memo.tp = {} return end
    for k, e in pairs(memo) do if e.chain[a] then memo[k] = nil end end
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
    TRACE.forget(mid)
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
            for _, c in ipairs(TRACE.skinComps(o)) do         -- not through o's properties
                table.insert(holders, { c, "CurrentCharacterSkinMaterialInstances" })
            end
            table.insert(holders, { o, "AllMeshMaterials" })
        end
    end
    for _, h in ipairs(holders) do
        pcall(function()
            local arr = propOf(h[1], h[2], "ArrayProperty")
            if arr == nil then return end
            local okv, isv = pcall(function() return arr:IsValid() end)   -- no such property: invalid
            if okv and isv == false then return end
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
local function chooseMaterial(active, base, bpath, bname, meshDefault, oldDefault, meshChanged)
    if not bpath then return nil end
    local p, o, mode = wanted(active, bpath, bname)
    if meshChanged and meshDefault then
        -- The slot showed the old mesh's own material (the game builds its instances from the
        -- mesh), or a material left over from another variant: follow the new mesh, as a
        -- respawn with the replacer installed would. Blueprint-set materials stay.
        -- Checked before the variant's own remap: on a fresh skin the slot shows the game's
        -- instance of the OLD mesh's material (vanilla Bottom), and the new mesh may want another
        -- one there (a barefoot variant: Hide_Material on the boots' slot). Remapping the old
        -- material instead left boot parts visible (PC). fixSlot remaps the mesh's choice.
        if (oldDefault and pkgPath(oldDefault) == bpath) or variantOwned(base, bpath) then
            if pkgPath(meshDefault) ~= bpath then return meshDefault end
            if mode ~= "map" then return nil end      -- same material: only a variant's remap
        end
    end
    if mode == "map" then return loadObj(p, o) end
    if mode == "orig" then return loadObj(p, o) or meshDefault end
    if mode == "default" then return meshDefault end    -- mod-only material of an unselected variant
    return nil
end

-- Empty texture slots. Some mods' materials point at a texture that isn't where they look for it
-- (PC: an outfit mod's body material, Color_MAIN empty, so the body showed grey, while the mod ships
-- Lune_Body_Basecolor-<suffix> and nothing uses it). Before a body mesh is changed, the textures its
-- materials show are noted per character. Afterwards an empty texture parameter gets, in order:
-- an unused texture of the picked variants named like the one it had ("Lune_Body_Basecolor" ->
-- "Lune_Body_Basecolor-<suffix>"), else the texture it had under that name.
Wear.donor = {}                 -- character -> parameter name -> texture last seen on the body
Wear.noteTextures = function(comp, char)
    if not char then return end
    step("Wear: note the textures shown")
    local d = Wear.donor[char] or {}
    Wear.donor[char] = d
    local ok, n = pcall(function() return comp:GetNumMaterials() end)
    for i = 0, (ok and n or 0) - 1 do
        local okm, m = pcall(function() return comp:GetMaterial(i) end)
        if okm and valid(m) then
            for key, tp in pairs(textureParams(m)) do
                if TRACE.tex(tp) then d[key:match("^[^|]*")] = tp.tex end
            end
        end
    end
end
Wear.likeTex = function(active, name)          -- the mod's texture named like `name`, without loading it
    local stem = (name or ""):lower()
    if #stem < 4 then return nil end
    local best
    for orig, e in pairs(active or {}) do
        if e.class == "Texture2D" then
            local leaf = orig:match("[^/]+$") or ""     -- keys are lower-case original paths
            if leaf ~= stem and leaf:sub(1, #stem) == stem and (not best or #leaf < #best.leaf) then
                best = { leaf = leaf, pkg = e.pkg, obj = e.obj }
            end
        end
    end
    return best
end
local function namedLike(active, before, name)   -- name: before's name, if known
    local best = Wear.likeTex(active, name or leafName(before))
    return best and loadObj(best.pkg, best.obj) or nil
end
-- An unused texture of the picked variants that fits the parameter by name, for an empty link whose
-- old texture has no namesake in the mod. Words of the parameter must be in the texture name;
-- "body" counts in favour, words the parameter doesn't have (underwear, bikini) against. (Sciel's
-- grey outfit-mod body turned out to be empty material slots, not this: see Wear.fillSlots.)
local KIND_WORDS = { color = "color", colour = "color", albedo = "color", diffuse = "color", normal = "normal",
                     roughness = "roughness", orm = "roughness", cavity = "cavity", emissive = "emissive",
                     glow = "emissive", underwear = "underwear", btls = "btls" }
local function byKind(active, param)
    local want = {}
    local words = param:gsub("(%l)(%u)", "%1 %2"):lower():gsub("basecolou?r", "color")
    for w in words:gmatch("%a+") do if KIND_WORDS[w] then want[KIND_WORDS[w]] = true end end
    if not next(want) then return nil end
    local best, bestScore
    for orig, e in pairs(active or {}) do
        if e.class == "Texture2D" and not appliedBy(orig, e.vid) then
            local leaf = (orig:match("[^/]+$") or ""):gsub("basecolou?r", "color"):gsub("albedo", "color")
            local ok, score = true, 0
            for w in pairs(want) do if not leaf:find(w, 1, true) then ok = false end end
            if ok then
                if leaf:find("body", 1, true) then score = score + 2 end
                for _, w in ipairs({ "underwear", "bikini", "btls" }) do
                    if leaf:find(w, 1, true) and not want[w] then score = score - 3 end
                end
                if not bestScore or score > bestScore then best, bestScore = e, score end
            end
        end
    end
    return best and loadObj(best.pkg, best.obj) or nil
end
Wear.fillEmpty = function(actor, comp, char, n, active)
    local d = (char and Wear.donor[char]) or {}
    local rules = Wear.rules(active)
    for i = 0, (n or 0) - 1 do
        local okm, m = pcall(function() return comp:GetMaterial(i) end)
        if okm and valid(m) then
            local mid
            local mo, vid = Wear.origOf(isMID(m) and m.Parent or m, active)
            for key, tp in pairs(textureParams(m)) do
                local name = key:match("^[^|]*")
                if not TRACE.tex(tp) then                         -- an empty link reads as an invalid object
                    local rule = mo and (rules.tex[mo .. "|" .. name] or rules.tex[mo .. "|*"])
                    local tex, why
                    if rule == "game" then
                        tex, why = d[name], " (the game's own: your choice)"
                    elseif rule then
                        tex, why = Wear.resolve(active, rule, "/Script/Engine.Texture"), " (your choice)"
                    end
                    local isTex = function(t) return valid(t) and isA(t, "/Script/Engine.Texture") end
                    if not isTex(tex) then
                        -- the donor is an object seen earlier: it must still be a texture
                        local donor = isTex(d[name]) and d[name] or nil
                        local own = (donor and namedLike(active, donor)) or byKind(active, name)
                        tex = own or donor
                        why = own and " (the mod's own texture for it)" or " (what the body showed before)"
                    end
                    if not isTex(tex) then goto continue end
                    mid = mid or (isMID(m) and m or makeMID(actor, comp, i, m, nil))
                    if not mid then break end
                    setTexture(mid, tp.info, tex)
                    change("mat%d texture %s: empty (the mod's material points at a texture it doesn't have) -> %s%s {fix:tex|%s|%s|%s}",
                        i, name, pkgPath(tex) or "?", why, vid or "?", mo or "?", name)
                end
                ::continue::
            end
        end
    end
end

-- Empty material slots. Some mods' meshes leave a slot without a material and count on the game's
-- skin Blueprint to fill it (PC report 2026-10-11: an outfit mod's Sciel mesh, mat1 and mat2 nil, so the
-- body showed grey). Wear clears the old outfit's materials, so nothing fills them. An empty slot
-- gets the material the body showed before (the game's own, with the character's skin settings):
-- the one in the slot of the same name, else the skin material. On it, the mod's textures named
-- like the ones it shows ("body_high_BaseColor" -> "body_high_BaseColor-<suffix>") replace them.
Wear.slotNames = function(mesh)                 -- slot -> lower-case slot name of a mesh asset (shared: don't change)
    if not valid(mesh) then return {} end
    return TRACE.once("slotNames", mesh, function()
        step("Wear: slot names of " .. tostring(leafName(mesh, true)))
        local out = {}
        pcall(function()
            for i, sm in ipairs(arrayItems(mesh.Materials)) do
                local ok, s = pcall(function() return sm.MaterialSlotName:ToString() end)
                if ok and type(s) == "string" and s ~= "" and s ~= "None" then out[i - 1] = s:lower() end
            end
        end)
        return out
    end)
end
Wear.isSkin = function(m, name)
    if name and (name:find("body", 1, true) or name:find("skin", 1, true)) then return true end
    for key in pairs(textureParams(m)) do
        if key:match("^[^|]*") == "Color_MAIN" then return true end      -- the MetaHuman body material
    end
    local base = isMID(m) and m.Parent or m
    return ((pkgPath(base) or ""):lower():match("/mi_body[^/]*$")) ~= nil
end
Wear.before = function(comp, mesh, prev)         -- what the body shows before its mesh changes
    step("Wear: materials before the change")
    local b = { byName = {}, skin = nil }
    local function add(m, nm)
        if not (valid(m) and isA(m, "/Script/Engine.MaterialInterface", true)) then return end
        if nm and not b.byName[nm] then b.byName[nm] = m end
        if not b.skin and Wear.isSkin(m, nm) then b.skin = m end
    end
    if prev and prev.mats then                  -- under a worn mesh: the outfit the game put there
        for i, m in pairs(prev.mats) do add(m, prev.names and prev.names[i]) end
    end
    local names = mesh and Wear.slotNames(mesh) or {}
    local ok, n = pcall(function() return comp:GetNumMaterials() end)
    for i = 0, (ok and n or 0) - 1 do
        local okm, m = pcall(function() return comp:GetMaterial(i) end)
        if okm then add(m, names[i]) end
    end
    return b
end
-- Which material fills an empty slot: the body's material for a slot of that name, else its skin
-- material, else a skin material of the game's own version of the mod's mesh, whichever has the
-- most textures the variant brings a namesake for. PC 17 Oct: Sciel's Chic outfit is a Lune mesh,
-- so "the body's skin material" was MI_Body_Lune (Lune's skin tone, none of the mod's textures fit);
-- the game's SK_Sciel_Bikini_B_skin uses MI_Body_Sciel, whose textures the mod replaces.
Wear.likeCount = function(active, m)
    local n = 0
    for _, tp in pairs(textureParams(m)) do
        local okT, _, tname = TRACE.tex(tp, true)
        if okT and Wear.likeTex(active, tname) then n = n + 1 end
    end
    return n
end
Wear.pickDonor = function(active, mo, before, nm)
    local cands = {}
    local function add(m, how)
        if valid(m) then cands[#cands + 1] = { m = m, how = how } end
    end
    if nm then add(before.byName[nm], "the body's material for slot " .. nm) end
    add(before.skin, "the body's skin material")
    local op = mo and ((active and active[mo] and active[mo].orig) or mo)   -- as the game spells it
    local game = op and loadObj(op, op:match("[^/]+$"))
    if valid(game) then                         -- the original of the mod's mesh: a skeletal mesh
        local names = Wear.slotNames(game)
        local okM, mats = pcall(function() return arrayItems(game.Materials) end)
        for i, sm in ipairs(okM and mats or {}) do
            local okI, m = pcall(function() return sm.MaterialInterface end)
            if okI and valid(m) and Wear.isSkin(m, names[i - 1]) then
                add(m, "the skin material of the game's own " .. tostring(leafName(game, true)))
            end
        end
    end
    local best, bestN = cands[1], -1
    for _, c in ipairs(cands) do
        local n = Wear.likeCount(active, c.m)
        if n > bestN then best, bestN = c, n end
    end
    if not best then return nil, nil end
    return best.m, best.how
end
Wear.fillSlots = function(actor, comp, mesh, before, active)
    local names = Wear.slotNames(mesh)
    local mo, vid = Wear.origOf(mesh, active)
    local rules = Wear.rules(active)
    local ok, n = pcall(function() return comp:GetNumMaterials() end)
    for i = 0, (ok and n or 0) - 1 do
        local okm, m = pcall(function() return comp:GetMaterial(i) end)
        if okm and not valid(m) then
            local nm = names[i]
            local tag = string.format(" {fix:mat|%s|%s|%d|%s}", vid or "?", mo or "?", i, nm or "")
            local rule = mo and rules.mat[mo .. "|" .. i]
            local chosen = rule and rule ~= "body"
                and Wear.resolve(active, rule == "hide" and "/Game/Materials/Hide_Material" or rule,
                                 "/Script/Engine.MaterialInterface")
            if chosen and valid(chosen) then
                pcall(function() comp:SetMaterial(i, chosen) end)
                change("mat%d empty (the mod's mesh has no material for slot %s) -> %s (your choice)%s",
                    i, nm or "?", pkgPath(chosen) or "?", tag)
                goto nextslot
            end
            local donor, how = Wear.pickDonor(active, mo, before, nm)
            if donor and valid(donor) then
                local parent = isMID(donor) and donor.Parent or donor
                local mid = makeMID(actor, comp, i, parent, nil)
                if mid and isMID(donor) then pcall(copyParams, donor, mid) end
                if not mid then pcall(function() comp:SetMaterial(i, donor) end) end
                change("mat%d empty (the mod's mesh has no material for slot %s) -> %s (%s)%s",
                    i, nm or "?", pkgPath(parent) or "?", how, tag)
                if mid then
                    for key, tp in pairs(textureParams(mid)) do
                        local okT, tpath, tname = TRACE.tex(tp, true)
                        local t = okT and namedLike(active, tp.tex, tname)
                        if t then
                            setTexture(mid, tp.info, t)
                            change("mat%d texture %s: %s -> %s (the mod's own, named like it)",
                                i, key:match("^[^|]*"), tpath or "?", pkgPath(t) or "?")
                        end
                    end
                end
            else
                change("mat%d empty (the mod's mesh has no material for slot %s) and nothing to fill it with%s",
                    i, nm or "?", tag)
            end
        end
        ::nextslot::
    end
end

-- Rules the player chose in the app (fixes.json, written into variants.lua as v.fix): which
-- texture an empty texture link gets ("<material>|<param or *>"), which material an empty slot
-- gets ("<mesh>|<slot>": "body", "hide" or a material). Keys use lower-case original paths.
Wear.fixOf, Wear.baseOf = {}, {}
Wear.indexFixes = function()
    Wear.fixOf, Wear.baseOf, Wear.ruleCache = {}, {}, setmetatable({}, { __mode = "k" })
    for _, slot in ipairs(SLOTS) do
        for _, v in ipairs(slot.variants or {}) do
            Wear.baseOf[v.id] = v.base or v.id
            if type(v.fix) == "table" then Wear.fixOf[v.id] = v.fix end
        end
    end
end
Wear.rules = function(active)                   -- the rules of the variants picked in `active`
    Wear.ruleCache = Wear.ruleCache or setmetatable({}, { __mode = "k" })
    local r = active and Wear.ruleCache[active]
    if r then return r end
    r = { tex = {}, mat = {} }
    local seen = {}
    for _, e in pairs(active or {}) do
        while e do
            if e.vid and not seen[e.vid] then
                seen[e.vid] = true
                local fx = Wear.fixOf[e.vid]
                if fx then
                    for k, v in pairs(type(fx.tex) == "table" and fx.tex or {}) do r.tex[k] = r.tex[k] or v end
                    for k, v in pairs(type(fx.mat) == "table" and fx.mat or {}) do r.mat[k] = r.mat[k] or v end
                end
            end
            e = e.under
        end
    end
    if active then Wear.ruleCache[active] = r end
    return r
end
Wear.origOf = function(obj, active)             -- lower-case original path, and its variant's registry id
    local p = valid(obj) and pkgPath(obj)
    if not p then return nil, nil end
    local o = (TO_ORIGINAL[p:lower()] or p):lower()
    local e = active and active[o]
    return o, e and e.vid and (Wear.baseOf[e.vid] or e.vid) or nil
end
Wear.resolve = function(active, orig, class)    -- an asset named by its original path, as the game has it
    -- now; nil unless it is a `class` ("/Script/Engine.Texture", ".MaterialInterface")
    if type(orig) ~= "string" or not orig:match("^/[%w_]+/.*[^/]$") then return nil end
    local e = active and active[orig:lower()]
    local o
    if e then o = loadObj(e.pkg, e.obj) else o = loadObj(orig, orig:match("[^/]+$")) end
    if valid(o) and (not class or isA(o, class)) then return o end
    return nil
end

local function fixSlot(actor, active, comp, i, meshDefault, oldDefault, meshChanged)
    step("slot " .. i .. ": GetMaterial")
    local ok, mat = pcall(function() return comp:GetMaterial(i) end)
    if not ok or not alive(mat) then return end
    local mid = isMID(mat) and mat or nil
    local base = mid and mat.Parent or mat
    local bpath, bname = pkgPath(base)
    local target = chooseMaterial(active, base, bpath, bname, meshDefault, oldDefault, meshChanged)
    local tpath, tname
    if target then tpath, tname = pkgPath(target) end
    if tpath and tpath == bpath then target = nil end   -- already right
    if target and valid(target) then
        -- the mesh default itself may be remapped by a selected variant (e.g. a color variant)
        if tpath then
            local p, o, mode = wanted(active, tpath, tname)
            if mode == "map" then
                local t2 = loadObj(p, o)
                if t2 then target, tpath = t2, pkgPath(t2) end
            end
        end
        change("mat%d %s -> %s", i, bpath or "?", tpath or "?")
        step("slot " .. i .. ": set material")
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
        local _, tpath, tname = TRACE.tex(tp, true)
        if tpath then
            local p, o, mode = wanted(active, tpath, tname)
            if mode == "map" or mode == "orig" then
                local t = loadObj(p, o)
                if t then
                    table.insert(changes, { tp.info, t })
                    change("mat%d texture %s: %s -> %s", i, tostring(key):match("^[^|]*"), tpath, p)
                end
            elseif mode == "default" and not stale then
                -- a texture we set for a variant that is now off, unless the parent shows the same
                -- one: then it is the material's own (a mod-only original from the shared pak) and
                -- going back to the parent changes nothing. PC 17 Oct: a multi-outfit mod's swapped
                -- Blueprint's materials use such textures; every look rebuilt three of them.
                local own = isMID(mat) and valid(mat.Parent) and textureParams(mat.Parent)[key]
                local _, opath = nil, nil
                if own then _, opath = TRACE.tex(own, true) end
                if opath ~= tpath then stale = true end
            end
        end
    end
    if stale and isMID(mat) and valid(mat.Parent) then
        change("mat%d textures back to %s's own (variant off)", i, pkgPath(mat.Parent) or "?")
        local fresh = makeMID(actor, comp, i, mat.Parent, mat)   -- back to the parent's own textures
        if fresh then mat = fresh end
    end
    if #changes > 0 then
        step("slot " .. i .. ": dynamic material + textures")
        local m2 = isMID(mat) and mat or makeMID(actor, comp, i, mat, nil)
        if m2 then
            for _, c in ipairs(changes) do setTexture(m2, c[1], c[2]) end
        end
    end
end

local function meshDefaults(mesh)               -- slot -> material from the mesh asset itself (shared: don't change)
    if not valid(mesh) then return {} end
    return TRACE.once("meshDefaults", mesh, function()
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
    end)
end

-- --------------------------------------------------------------------------- components

local NAMED = { "Body", "Face", "Hair", "Eyebrows", "Eyelashes", "Beard", "Mustache",
                "Haircut_SkeletalMesh", "Haircut_StaticMesh" }

-- The actor's mesh components, named by their own object names (a Blueprint's components are named
-- like its variables: Body, Face, ...), in NAMED order first. Never through the actor's properties:
-- PC 17 Oct, two crashes at camp right after a fast travel, both inside UE4SS's property cache
-- (FindProperty -> FFieldClassVariant::GetFName) while reading "Face" of a camp character. UE4SS
-- 1176 caches a property per class address; camp Blueprints are unloaded and loaded again, a new
-- class can get the old address, and the cache hands back the freed property (a guess that fits
-- both dumps). K2_GetComponentsByClass is a call of a native function: no Blueprint property read.
-- Only outfit actors (the game's skin and face Blueprints) are also read by property: their Body,
-- Face, ... point at the pawn's components (the swap policy renders the outfit through the pawn),
-- which their own component list doesn't hold.
TRACE.outfitActor = function(a)
    local key, c = TRACE.classKey(a)
    if not key then return false end
    TRACE.outfitCls = TRACE.outfitCls or {}
    if TRACE.outfitCls[key] ~= nil then return TRACE.outfitCls[key] end
    local r, s = false, c
    for _ = 1, 16 do
        if not valid(s) then break end
        local n = leafName(s)
        if n == "BP_CharacterSkinBase_C" or n == "BP_CharacterFaceBase_C" then r = true break end
        local okp, sup = pcall(function() return s:GetSuperStruct() end)
        if not okp then break end
        s = sup
    end
    TRACE.outfitCls[key] = r
    return r
end
local function meshComponents(actor)
    local list, seen = {}, {}
    local function add(name, c)
        if valid(c) then
            local a = c:GetAddress()
            if not seen[a] then seen[a] = true table.insert(list, { name = name or leafName(c, true) or "?", comp = c }) end
        end
    end
    local meshCls = cls("/Script/Engine.MeshComponent")
    if valid(meshCls) then
        step("components: K2_GetComponentsByClass")
        local ok, arr = pcall(function() return actor:K2_GetComponentsByClass(meshCls) end)
        for _, c in ipairs(ok and arrayItems(arr) or {}) do add(nil, c) end
    end
    if valid(actor) and TRACE.outfitActor(actor) then
        -- a name the class lists with another type (or not at all) is skipped without a read
        local key = TRACE.classKey(actor)
        for _, n in ipairs(NAMED) do
            local types = PROP_TYPES[key]
            if not (type(types) == "table" and types[n] ~= "ObjectProperty") then
                step("components: property " .. n)
                local c = propOf(actor, n, "ObjectProperty")
                if c ~= nil then add(n, c) end
            end
        end
    end
    local rank = {}
    for i, n in ipairs(NAMED) do rank[n] = i end
    for i, e in ipairs(list) do e.i = i end
    table.sort(list, function(x, y)
        local rx, ry = rank[x.name] or 99, rank[y.name] or 99
        if rx ~= ry then return rx < ry end
        return x.i < y.i
    end)
    return list
end

local function getMesh(comp, skel)              -- skel: comp is known to be a valid SkeletalMeshComponent
    step("mesh of a component")
    if skel or isA(comp, "/Script/Engine.SkeletalMeshComponent") then
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
    step("set mesh " .. tostring(leafName(mesh)))
    TRACE.st.sets = TRACE.st.sets + 1
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
-- Components the game creates at run time ("GroomComponent_2147317866") have no template, and
-- every lookup that finds nothing costs 13-27 ms (see loadObj): they are skipped, and what a class
-- has (or hasn't) is kept for the map (TRACE.tmpl, cleared on map load).
TRACE.tmpl = {}
-- Once per session, 9 s after the first map that isn't the title screen: what a lookup costs in
-- game, to check the reason for fix14 (StaticFindObject finding nothing: 13-27 ms each, GetAsset
-- of an asset in memory: ~0 ms). If both come out near 0 ms, that reason was wrong.
TRACE.speedTest = function()
    if TRACE.speedDone then return end
    TRACE.speedDone = true
    local function each(f)
        local t0 = os.clock()
        for _ = 1, 5 do pcall(f) end
        return (os.clock() - t0) * 1000 / 5
    end
    local miss = each(function() return StaticFindObject("/Game/E33WardrobeSpeedTest/Missing.Missing") end)
    local hit = each(function() return StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers") end)
    local get = -1
    local arh = StaticFindObject("/Script/AssetRegistry.Default__AssetRegistryHelpers")
    if valid(arh) then
        get = each(function()
            return arh:GetAsset({ PackageName = fname("/Engine/EngineMaterials/WorldGridMaterial"),
                                  AssetName = fname("WorldGridMaterial") })
        end)
    end
    live("speed test: StaticFindObject, not found: %.1f ms; found: %.1f ms; GetAsset of an asset in memory: %.1f ms "
        .. "(each, mean of 5)", miss, hit, get)
end

local function classTemplates(bpClass, names)
    local out = {}
    local cpath = fullPath(bpClass)
    if not cpath then return out end
    local addr = bpClass:GetAddress()
    for _, n in ipairs(names) do
        if not n:find("_%d%d%d%d%d%d+$") then
            local key = cpath .. ":" .. n
            local c = TRACE.tmpl[key]
            -- a hit is checked by name too: an unloaded class's template address can be reused
            if not (c and c.addr == addr and (c.t == false or (valid(c.t) and fullPath(c.t) == c.name))) then
                step("StaticFindObject " .. key .. "_GEN_VARIABLE")
                local t = StaticFindObject(key .. "_GEN_VARIABLE")
                c = { addr = addr, t = valid(t) and t or false, name = valid(t) and fullPath(t) or nil }
                TRACE.tmpl[key] = c
            end
            if c.t then out[n] = c.t end
        end
    end
    return out
end

local function remapAnimClass(active, comp)
    step("anim class")
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
    step("actor: alive and name")
    if not alive(actor) then return end
    local aname = leafName(actor, true)
    if aname == "None" then return end                                  -- destroyed: its memory may be reused
    if not SETTINGS.scene_copies then
        for _, o in ipairs({ actor, ownerOf(actor) }) do
            local copy = valid(o) and SCENE_COPY[o:GetAddress()]
            if copy and copy == fullPath(o) then return end
        end
    end
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
    local actorCtx = (aname or "?") .. " [" .. tostring(char or "no character") .. "]"
    local skinActor = isSkinActor(actor)
    -- 1) whole skin Blueprint overridden by a variant: copy its component setup
    local templates
    step("class of the actor")
    local clsObj = actor:GetClass()
    local cpath, cname = pkgPath(clsObj)
    if cpath then
        local p, o, mode = wanted(active, cpath, cname)
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
        step("component " .. e.name)
        if not alive(comp) then goto nextComp end
        local mesh, kind = getMesh(comp)
        if mesh and not alive(mesh, true) then goto nextComp end     -- still loading: the next look gets it
        -- the shown mesh's path and name, read once (mp follows mesh when it is swapped below)
        local mp, mname
        if mesh then mp, mname = pkgPath(mesh, true) end
        -- an actor whose character can't be told (the walking character's run-time named body
        -- component): a component showing one of the mod's relocated meshes belongs to the
        -- character that mesh is made for, for everything on it (mesh, materials, textures). PC:
        -- with no character the Lune pick didn't count there, so the mesh went back to the game's
        -- own while Lune's skin put the worn one on again 2 s later, every pass. Only relocated
        -- meshes: the game's own can be shared (Lune's Chic mesh is Sciel's too).
        local cchar = char
        if not cchar and kind == "skel" and mp and TO_ORIGINAL[mp:lower()] then
            cchar = onlyChar(TO_ORIGINAL[mp:lower()])
        end
        local cActive = (cchar ~= char) and activeFor(cchar) or active
        local ca                                -- the component's address, once needed
        local newMesh, why
        local tmpl = templates and templates[e.name]
        if tmpl then
            local tm = getMesh(tmpl)
            if valid(tm) and pkgPath(tm) ~= mp then newMesh, why = tm, "the variant's skin Blueprint" end
        end
        local wearReset, wearRestore
        if not newMesh and WEAR_COMPS[e.name] and kind == "skel" and mesh then
            ca = comp:GetAddress()
            local prev = FORCED_FROM[ca]
            local cname = fullPath(comp)
            if prev and prev.comp ~= cname then prev = nil FORCED_FROM[ca] = nil end   -- address reused
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
                    -- the game put its own mesh back within seconds of ours: counted. Copies it keeps
                    -- for scenes get theirs back every time, and re-dressing them again only costs
                    -- frames (PC: 5-8 times per copy, stutter). After 3 in a row they're left alone
                    -- for 30 s; an outfit change later starts the count again.
                    local now = os.time()
                    local recent = prev ~= nil and prev.at ~= nil and now - prev.at <= 10
                    local resets = (prev and prev.set and not ours and recent) and (prev.resets or 0) + 1 or 0
                    if ours then
                        -- another worn mesh (e.g. Body Clean -> PH): keep the outfit remembered before
                        why = "Wear: another worn mesh"
                    elseif resets >= 3 or (prev and prev.gaveUp and now - (prev.at or 0) <= 30) then
                        if not prev.gaveUp then
                            prev.gaveUp = true
                            live("    %s: the game keeps putting its own mesh back; left alone", actorCtx)
                        end
                    else
                        -- remember what the game put there, materials included (hidden slots etc.)
                        step("Wear: materials the game put there")
                        local mats = {}
                        for i = 0, nm - 1 do
                            local okm, m = pcall(function() return comp:GetMaterial(i) end)
                            if okm and valid(m) then mats[i] = m end
                        end
                        FORCED_FROM[ca] = { path = mp, obj = mname, mats = mats, names = Wear.slotNames(mesh),
                                            comp = cname, resets = resets }
                        why = "Wear: over the outfit worn now"
                    end
                    if FORCED_FROM[ca] and not FORCED_FROM[ca].gaveUp then
                        FORCED_FROM[ca].set, FORCED_FROM[ca].at = force.pkg, now
                        newMesh = loadObj(force.pkg, force.obj)
                        wearReset = nm
                    end
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
            local orig = mp and TO_ORIGINAL[mp:lower()]
            local vm = orig and vanillaMesh(e.name)
            local vp, vname
            if valid(vm) then vp, vname = pkgPath(vm, true) end
            if vp and orig:lower() ~= vp:lower() then
                local p2, o2, m2 = wanted(active, vp, vname)
                newMesh = (m2 == "map" and loadObj(p2, o2)) or vm
                why = "back to this outfit's own mesh (a worn mesh was left on it)"
            end
        end
        if not newMesh and mesh then
            local p, o, mode
            if mp then p, o, mode = wanted(cActive, mp, mname) end
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
        if newMesh and kind and char and kind == "skel" and WEAR_COMPS[e.name] then
            pcall(Wear.noteTextures, comp, char)        -- what the body shows before its mesh changes
        end
        local before = newMesh and kind == "skel" and WEAR_COMPS[e.name]
            and select(2, pcall(Wear.before, comp, mesh, FORCED_FROM[ca or comp:GetAddress()])) or nil
        if newMesh and kind then
            local np = pkgPath(newMesh)
            change("mesh %s -> %s (%s)", mesh and mp or "none", np or "?", why or "?")
            oldDefaults = mesh and meshDefaults(mesh) or {}
            local t0 = os.clock()
            setMesh(comp, kind, newMesh, mesh) mesh = newMesh mp = np meshChanged = true
            if liveF then live("    mesh set (%d ms)", math.floor((os.clock() - t0) * 1000 + 0.5)) end
            if wearReset then
                step("Wear: clear the old outfit's materials")
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
        local compActive = cActive
        if WEAR_COMPS[e.name] and kind == "skel" then compActive = forOutfit(cActive, mesh and mp) end
        if kind == "skel" then remapAnimClass(compActive, comp) end
        if meshChanged and type(before) == "table" then step("Wear: fill material slots") pcall(Wear.fillSlots, actor, comp, mesh, before, compActive) end
        local ok, n = pcall(function() return comp:GetNumMaterials() end)
        if ok and n then
            for i = 0, n - 1 do
                local okf, err = pcall(fixSlot, actor, compActive, comp, i, defaults[i], oldDefaults[i], meshChanged)
                if not okf then log("slot %d of %s: %s", i, e.name, tostring(err)) end
            end
        end
        if ok and n and char and kind == "skel" and WEAR_COMPS[e.name] then
            step("Wear: fill empty textures")
            pcall(Wear.fillEmpty, actor, comp, char, n, compActive)
        end
        if SETTINGS.clean and Clean.comp then step("Clean") pcall(Clean.comp, comp, actor) end
        -- what this character wears now (for the menu): the body mesh after this pass
        if char and kind == "skel" and WEAR_COMPS[e.name] and mesh then
            local prev = WORN[char]
            if mp and (not prev or not prev.skin or skinActor) then
                local f = FORCED_FROM[ca or comp:GetAddress()]
                WORN[char] = { path = TO_ORIGINAL[mp:lower()] or mp, under = f and f.path or nil, skin = skinActor }
            end
        end
        ::nextComp::
    end
end

local SKIN_CLASSES = { "BP_CharacterSkinBase_C", "BP_CharacterFaceBase_C", "BP_CineCharacter_Main_C" }
local SKIN_OF_CLASS = {}      -- class address|name -> bool

isSkinActor = function(a)
    step("skin class check")
    if not valid(a) then return false end
    local addr, c = TRACE.classKey(a)          -- an unloaded class's address can be reused: with its name
    if not addr then return false end
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

-- Party characters that aren't skin actors are otherwise only known once a pass has seen one
-- showing a replaced mesh, and passes don't run when a battle starts (PC, 15 Oct: with an outfit mod worn
-- over Chic, no battle character was ever looked at). These are known by their class names.
TRACE.PAWN_NAMES = { "^BP_%u%l+_Battle%d*_C$", "^BP_Pawn_AICompanion_%u%l+_C$" }
local function isWardrobeActor(a)
    if isSkinActor(a) then return true end
    if not valid(a) then return false end
    local key, c = TRACE.classKey(a)
    if not key then return false end
    if EXTRA_CLASS[key] == true then return true end
    -- PC, 17 Oct: ~6000 BeginPlays a minute in battle, nearly all of other classes; the name check
    -- is done once per class (a pass can still add the class to EXTRA_CLASS later)
    TRACE.notPawn = TRACE.notPawn or {}
    if TRACE.notPawn[key] then return false end
    local n = valid(c) and leafName(c) or nil
    if n then
        for _, pat in ipairs(TRACE.PAWN_NAMES) do
            if n:find(pat) then
                EXTRA_CLASS[key] = true
                EXTRA_CLASS._names = EXTRA_CLASS._names or {}
                EXTRA_CLASS._names[n] = true
                return true
            end
        end
        TRACE.notPawn[key] = true
    end
    return false
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
            local m = getMesh(c, true)                 -- FindAllOf gave skeletal mesh components
            local p = m and pkgPath(m, true)
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

    local function isMask(tp)                   -- a texture parameter showing a BTLS mask
        local _, p = TRACE.tex(tp, true)
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
            local v = propOf(actor, prop, "FloatProperty", "DoubleProperty")
            if type(v) == "number" then
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
                    if isMask(tp) then
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
    Clean.owner = function(owner)               -- the skin / face actors of this owner seen so far
        local on = fullPath(owner)
        if not on then return end
        for _, k in pairs(KNOWN_SKINS) do         -- not through owner properties (see KNOWN_SKINS)
            if k.owner == on and alive(k.a) and fullPath(k.a) == k.name:match("^%S+%s+(.+)$") then
                cleanActor(k.a, newStats())
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
        local passT0 = os.clock()
        local function one(a)
            done[a:GetAddress()] = true
            if not alive(a) then return end
            local ok, err = TRACE.timed(leafName(a) or "?", applyToActor, a, doneComps)
            if not ok then log("apply failed on %s: %s", tostring(leafName(a)), tostring(err)) end
            n = n + 1
        end
        step("pass: find skin actors (FindAllOf)")
        forEachSkin(function(a)
            one(a)
            -- skins made while a map loads are left to this pass, so they are noted here too: a
            -- skin the game shows again later without a BeginPlay is found through its owner
            local addr = alive(a) and a:GetAddress()
            if addr and not KNOWN_SKINS[addr] then
                local okN, nm = pcall(function() return a:GetFullName() end)
                local own = ownerOf(a)
                if okN and nm then KNOWN_SKINS[addr] = { a = a, name = nm, owner = valid(own) and fullPath(own) or nil } end
            end
        end)
        step("pass: find other actors showing a replaced mesh (FindAllOf)")
        forEachMappedMeshOwner(function(a)
            if done[a:GetAddress()] then return end
            local okc, c = pcall(function() return a:GetClass() end)
            if okc and valid(c) then
                EXTRA_CLASS[c:GetAddress() .. "|" .. tostring(leafName(c))] = true
                EXTRA_CLASS._names = EXTRA_CLASS._names or {}
                if leafName(c) then EXTRA_CLASS._names[leafName(c)] = true end
            end
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
        local passMs = (os.clock() - passT0) * 1000
        TRACE.st.passes, TRACE.st.passMs = TRACE.st.passes + 1, TRACE.st.passMs + passMs
        live("pass (%s): %d change(s)%s; %d actor(s) in %d ms", reasons, passChanges,
            passChanges == 0 and " - nothing loaded needed changing" or "", n, math.floor(passMs + 0.5))
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
        if TRACE.busy() and loopTicks - (PASS.waitFrom or loopTicks) < 200 then
            PASS.waitFrom = PASS.waitFrom or loopTicks
            PASS.due = loopTicks + 5                -- a burst of new actors: wait for calm
            TRACE.st.waits = (TRACE.st.waits or 0) + 1
            return
        end
        PASS.waitFrom = nil
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
                local ac = a:GetClass()
                f:write("ACTOR ", a:GetFullName(), "\n  class: ", valid(ac) and ac:GetFullName() or "nil", "\n")
                local owner = ownerOf(a)
                f:write("  owner: ", valid(owner) and owner:GetFullName() or "nil", "\n")
                local comps = meshComponents(a)
                local ch = characterOf(a)
                f:write("  character: ", tostring(ch or charFromComps(comps)), ch and "" or " (from its meshes)", "\n")
                if not isSkinActor(a) then f:write("  (not a skin actor: visited because it shows a replaced mesh)\n") end
                for _, o in ipairs({ owner, a }) do
                    if valid(o) then
                        local sc = propOf(o, "BP_CharacterSkinComponent", "ObjectProperty")
                        if valid(sc) then
                            local pol = propOf(sc, "SkinAssignPolicy", "ObjectProperty")
                            local pc = valid(pol) and pol:GetClass()
                            f:write("  skin component: ", sc:GetFullName(), "\n  policy: ",
                                valid(pc) and pc:GetFullName() or "nil", "\n")
                            local arr = propOf(sc, "CurrentCharacterSkinMaterialInstances", "ArrayProperty")
                            f:write("  CurrentCharacterSkinMaterialInstances: ", arr ~= nil and #arrayItems(arr) or "?", "\n")
                            if not listedFns then
                                listedFns = true
                                pcall(function()
                                    local scc = sc:GetClass()
                                    if not valid(scc) then return end
                                    scc:ForEachFunction(function(fn)
                                        f:write("    fn ", fn:GetFName():ToString(), "\n")
                                    end)
                                end)
                            end
                        end
                    end
                end
                local short = leafName(a) or "?"
                for _, e in ipairs(comps) do
                    local mesh, mkind = getMesh(e.comp)
                    note(mesh, short .. "." .. e.name)
                    f:write("  [", e.name, "] mesh=", valid(mesh) and mesh:GetFullName() or "nil", "\n")
                    if valid(mesh) then
                        pcall(function() f:write("     skeleton=", fullPath(mesh.Skeleton) or "nil", "\n") end)
                        pcall(function() f:write("     physics=", fullPath(mesh.PhysicsAsset) or "nil", "\n") end)
                    end
                    pcall(function() f:write("     anim=", fullPath(e.comp.AnimClass) or "nil", "\n") end)
                    -- a weak pointer in UE 5.4 (UE4SS #1433): read only through propOf's type check
                    pcall(function() f:write("     leader=", fullPath(propOf(e.comp, "LeaderPoseComponent", "ObjectProperty")) or "nil", "\n") end)
                    if mkind == "skel" then
                        -- what animates it now: anim= is only the class it is set up with. PC 17 Oct:
                        -- the cutscene Sciel from the swapped Blueprint had none; every other
                        -- cutscene character had ABP_CinematicCharacter.
                        pcall(function()
                            local inst = propOf(e.comp, "AnimScriptInstance", "ObjectProperty")
                            local ic = valid(inst) and inst:GetClass() or nil
                            local mode = propOf(e.comp, "AnimationMode", "ByteProperty", "EnumProperty")
                            local modes = { [0] = "AnimationBlueprint", "AnimationSingleNode", "AnimationCustomMode" }
                            f:write("     instance=", valid(ic) and (fullPath(ic) or "?") or "nil",
                                "  mode=", tostring(modes[mode] or mode), "\n")
                        end)
                    end
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
local function targetOutfit(slot, char)
    local v = selectedVariant(slot) or (slot.variants or {})[1]
    if not v then return nil end
    if char and not slot.character and next(Wear.slotChars(slot)) then
        local pick = Wear.meshFor(v, char, nil)
        return pick and pick.orig or nil       -- this variant has no mesh for that character
    end
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
            -- the characters it is for: the slot's own, else whoever its meshes belong to
            local chars = v and (slot.character and { [slot.character] = true } or Wear.variantChars(v))
            if not v or wear[slot.id] or not hasMesh(slot) or not next(chars) then
                AUTOWEAR_PENDING[slot.id] = nil
            else
                local loaded, misfit = false, nil
                for c in pairs(chars) do
                    if WORN[c] then
                        loaded = true
                        local shown = false
                        for orig, e in pairs(v.map or {}) do
                            if e[3] == "SkeletalMesh" and (slot.character or charsIn(orig)[c])
                               and appliedBy(orig:lower(), v.id) then shown = true end
                        end
                        if not shown then misfit = c end
                    end
                end
                if loaded then
                    AUTOWEAR_PENDING[slot.id] = nil
                    if misfit then
                        AUTO_WORN[slot.id] = true
                        live("Auto Wear: %s doesn't fit what %s wears; worn in place of it", slot.label, misfit)
                        setWearFlag(slot.id, true, "Auto Wear")
                    end
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

-- Favorites: saved looks per character, in the player's order. A look is every pick of that
-- character's slots at the time it was saved (one-option mods included; a slot not in the look is
-- off). favorites.txt: one look per line, tab-separated: character, name, then slot id / variant id
-- pairs. The menu edits Fav.list and calls Fav.save.
local Fav = { list = {} }
Fav.save = function()
    local f = io.open(FILES.FAV, "w")
    if not f then log("cannot write %s", FILES.FAV) return end
    for _, e in ipairs(Fav.list) do
        local parts = { e.char, e.name }
        local ids = {}
        for id in pairs(e.picks) do ids[#ids + 1] = id end
        table.sort(ids)
        for _, id in ipairs(ids) do parts[#parts + 1] = id parts[#parts + 1] = e.picks[id] end
        f:write(table.concat(parts, "\t"), "\n")
    end
    f:close()
end
-- Picks of slots / variants no longer in the wardrobe are dropped (a look left with none of its
-- picks goes); picks saved before a slot was split per character ("<id>@<character>") carry over.
Fav.load = function()
    Fav.list = {}
    local f = io.open(FILES.FAV, "r")
    if not f then return end
    local raw = {}
    for line in f:lines() do
        local t = {}
        for x in (line:gsub("\r$", "") .. "\t"):gmatch("(.-)\t") do t[#t + 1] = x end
        if #t >= 2 and t[1] ~= "" then
            local e = { char = t[1], name = t[2], picks = {}, n = 0 }
            for k = 3, #t - 1, 2 do
                if t[k] ~= "" and t[k + 1] ~= "" then e.picks[t[k]] = t[k + 1] e.n = e.n + 1 end
            end
            raw[#raw + 1] = e
        end
    end
    f:close()
    if #SLOTS == 0 then Fav.list = raw return end
    local known, changed = {}, false
    for _, slot in ipairs(SLOTS) do
        known[slot.id] = {}
        for _, v in ipairs(slot.variants) do known[slot.id][v.id] = true end
    end
    for _, e in ipairs(raw) do
        local picks, kept = {}, 0
        for id, vid in pairs(e.picks) do
            if not (known[id] and known[id][vid]) then
                changed = true
                id, vid = id .. "@" .. e.char, vid .. "@" .. e.char
            end
            if known[id] and known[id][vid] then picks[id] = vid kept = kept + 1 end
        end
        if kept > 0 or e.n == 0 then
            Fav.list[#Fav.list + 1] = { char = e.char, name = e.name, picks = picks }
        else
            changed = true
        end
    end
    if changed then
        Fav.save()
        log("favorites.txt: updated for the current wardrobe (%d look(s) kept)", #Fav.list)
    end
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
    Wear.splitByCharacter()
    Wear.indexFixes()
    -- Wear on a slot that can't wear (no mesh) does nothing: drop such stale flags
    do
        local keep, dropped, byId = {}, false, {}
        for _, slot in ipairs(SLOTS) do byId[slot.id] = slot end
        for id in (SETTINGS.wear or ""):gmatch("[^|]+") do
            local slot = byId[id]
            local canWear = slot and hasMesh(slot) and (slot.character or next(Wear.slotChars(slot)))
            if slot and not canWear then dropped = true else keep[#keep + 1] = id end
        end
        if dropped then
            SETTINGS.wear = table.concat(keep, "|")
            saveSettings()
            log("dropped Wear from slots that have no mesh to wear")
        end
    end
    loadSelection()
    if Wear.migrate() then saveSelection() end
    Fav.load()
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
    Fix.forget = function() GAME_NAME = {} end
    Fix.noteName = function(owner, name)
        if valid(owner) and name and name ~= "" and name ~= "None" then GAME_NAME[owner:GetAddress()] = name end
    end
    local function nameFor(c)
        local okO, owner = pcall(function() return c:GetOwner() end)
        if okO and valid(owner) and GAME_NAME[owner:GetAddress()] then return GAME_NAME[owner:GetAddress()] end
        local n = propString(c, "CharacterHardcodedName")
        if n and n ~= "" and n ~= "None" then return n end
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
            local n, tried, noName, used, inScene = 0, 0, 0, {}, 0
            -- Cutscene pawns are left alone: re-dressing one mid-scene can leave the scene waiting
            -- (PC: dialogue no longer appeared after Fix look). The game dresses them per shot.
            local okC, cine = pcall(FindAllOf, "BP_CinematicCharacterSkinComponent_C")
            if okC and cine then inScene = #cine end
            for _, cn in ipairs({ "BP_CharacterSkinComponent_C" }) do
                local ok, comps = pcall(FindAllOf, cn)
                for _, c in ipairs(ok and comps or {}) do
                    local okK, k = false, nil
                    if valid(c) then okK, k = pcall(function() return leafName(c:GetClass()) end) end
                    if valid(c) and not (okK and k == "BP_CinematicCharacterSkinComponent_C") then
                        tried = tried + 1
                        local args = learnFixArgs(c)
                        if args == "name" then
                            local name = nameFor(c)
                            if not name then
                                noName = noName + 1
                            else
                                local okc, err = pcall(function() c:ApplyCurrentCharacterSkin(FName(name)) end)
                                TRACE.fresh()       -- the game's code ran: nothing read before is kept
                                if okc then n = n + 1 used[name] = true else probeSkinComponent(c, err) end
                            end
                        elseif args then
                            local okc, err = pcall(function() c:ApplyCurrentCharacterSkin(table.unpack(args)) end)
                            TRACE.fresh()
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
            log("Fix look: the game re-dressed %d of %d character(s)%s%s%s", n, tried,
                #names > 0 and (" (" .. table.concat(names, ", ") .. ")") or "",
                noName > 0 and string.format("; %d without a known character name", noName) or "",
                inScene > 0 and string.format("; %d cutscene character(s) left alone", inScene) or "")
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

-- commands.txt next to the mod: read about once a second, every line run on the game thread, then
-- the file is removed (for a script or a developer driving the mod while the game runs; each line
-- is logged as "command: ..."). A line is what the console's "wardrobe" command takes ("dump",
-- "report", "fix", "apply", "reload", "<slot> <variant>|off", "clean on|off"), or:
--   pick <slot id> | <variant id or off>     wear <slot id> | on|off     set <setting> <value>
-- (slot and variant ids hold spaces: " | " separates the arguments of pick and wear)
TRACE.commands = function()
    local f = io.open(FILES.COMMANDS, "r")
    if not f then return end
    local text = f:read("a") or ""
    f:close()
    local removed = os.remove(FILES.COMMANDS)
    if not removed then                         -- held open elsewhere (Windows): run it once only
        if text == TRACE.cmdLast then return end
    end
    TRACE.cmdLast = text
    for line in text:gmatch("[^\r\n]+") do
        local words = {}
        for w in line:gmatch("%S+") do words[#words + 1] = w end
        local a, b, c = words[1], words[2], table.concat(words, " ", 3)
        if a == "pick" or a == "wear" then
            local rest = line:match("^%s*%S+%s+(.-)%s*$") or ""
            b, c = rest:match("^(.-)%s*|%s*(.-)$")
        end
        if a and #line <= 300 and not a:find("^#") then
            live("command: %s", line)
            if a == "pick" and b then
                local done = false
                for si, slot in ipairs(SLOTS) do
                    if slot.id == b then
                        local vi = 0
                        for i, v in ipairs(slot.variants) do if v.id == c then vi = i end end
                        if c ~= "off" and vi == 0 then log("command: no variant %s in %s", c, b) else setVariant(si, vi) end
                        done = true
                    end
                end
                if not done then log("command: no slot %s", b) end
            elseif a == "wear" and b then
                AUTOWEAR_PENDING[b] = nil
                setWearFlag(b, c == "on")
                rebuildActive()
                applyAll("command")
            elseif a == "set" and b and SETTINGS[b] ~= nil then
                local cur = SETTINGS[b]
                if type(cur) == "boolean" then SETTINGS[b] = (c == "true" or c == "on")
                elseif type(cur) == "number" then SETTINGS[b] = tonumber(c) or cur
                else SETTINGS[b] = c end
                saveSettings()
            elseif a == "set" then
                log("command: no setting %s", tostring(b))
            else
                onConsole(nil, { a, b })
            end
        end
    end
end

-- New skin actors (outfit change, battle, cutscene, menu preview) are looked at about 1 s after
-- they appear, and again 2 s later for anything the game set up afterwards (battle skins are
-- assigned asynchronously). Never on the tick they appear: both freezes on PC happened in the
-- mod's first look at a skin the game had just spawned, during heavy loading (a map change, a
-- cutscene starting). For 3 s after a map loads new skins are left to the map-load pass.
-- Actors are kept by reference with their full name: a destroyed actor's address can be reused
-- by a new object, and that one must not be touched (PC: "change None [Maelle].Body" a second
-- after a battle ended). Skin actors of no party character (e.g. BP_Cine_Esquie) are left alone
-- unless a slot tied to no character is picked, since nothing else could apply to them.
local SPAWN = { again = {}, queued = {}, AFTER = { 1000, 2000 }, quietUntil = 0 }

SPAWN.same = function(e)
    step("new skin: still the same object?")
    if not alive(e.a) then return false end
    local ok, n = pcall(function() return e.a:GetFullName() end)
    return ok and n ~= nil and n == e.name and leafName(e.a) ~= "None"
end

SPAWN.worth = function(a)
    if not isWardrobeActor(a) then return false end
    if not isSkinActor(a) or characterOf(a) then return true end
    return next(activeFor(nil)) ~= nil
end

-- Why a new skin is not looked at (logged: PC, only 26 of 269 new skins were looked at, silently)
SPAWN.dropped = {}
SPAWN.drop = function(e, round)
    local why
    if not SPAWN.same(e) then
        -- which part of "same" failed (PC: battle skins, visible in battle, all failed it)
        local flags = TRACE.aliveWhy(e.a)
        if flags == "invalid" then
            why = "gone (invalid object) before the look"
        elseif flags then
            why = "skipped by its flags: " .. flags
        else
            local ok, n = pcall(function() return e.a:GetFullName() end)
            why = (ok and n and n ~= e.name) and ("renamed before the look: now " .. tostring(n:match("([^%.:]+)$")))
                or "gone or replaced before the look (named None)"
        end
    elseif not isWardrobeActor(e.a) then
        why = "not a skin actor, and its class never showed a replaced mesh"
    else
        why = "no party character found for it, and no picked slot is for every character"
    end
    local cls = (e.name:match("^(%S+)") or "?") .. " " .. ((e.name:match("([^%.:]+)$") or "?"):gsub("_%d+$", ""))
    local k = why .. "|" .. cls
    SPAWN.dropped[k] = (SPAWN.dropped[k] or 0) + 1
    if SPAWN.dropped[k] <= 2 then
        live("  new skin %s not looked at (round %d): %s", tostring(e.name:match("([^%.:]+)$")), round, why)
    end
end

SPAWN.entry = function(a)
    local ok, n = pcall(function() return a:GetFullName() end)
    if not ok or not n then return nil end
    return { a = a, name = n }
end

-- AI companions (the party members walking behind the leader) are re-created after battles,
-- mostly without a BeginPlay the mod gets to see (PC: 3 of 19 seen; they kept the game's outfit
-- until Fix look). Every 2 s the classes learned in passes are looked up, and a companion whose
-- body shows another mesh than when the mod last looked is looked at again (~8 calls each).
SPAWN.seen = {}
SPAWN.watch = function()
    if not anyActive() or TRACE.busy() or not EXTRA_CLASS._names then return end
    local t0 = os.clock()
    -- PC, 14-15 Oct: every class in one frame took up to 757 ms (FindAllOf scans all objects).
    -- Classes are taken in turn until the 8 ms are used up; the next watch goes on from there.
    local names = {}
    for cname in pairs(EXTRA_CLASS._names) do names[#names + 1] = cname end
    table.sort(names)
    local n = #names
    for i = 0, n - 1 do
        if i > 0 and (os.clock() - t0) * 1000 > 8 then return end
        local cur = ((SPAWN.next or 1) - 1) % n + 1
        SPAWN.next = cur % n + 1
        local cname = names[cur]
        step("watch: FindAllOf " .. cname)
        local ok, all = pcall(FindAllOf, cname)
        for _, a in ipairs(ok and all or {}) do
            if (os.clock() - t0) * 1000 > 8 then return end
            if alive(a) and leafName(a) ~= "None" then
                local key = fullPath(a)
                local function sig()          -- the body's mesh, by component name (see meshComponents)
                    for _, e in ipairs(meshComponents(a)) do
                        if (e.name == "CharacterMesh0" or e.name == "Body") and alive(e.comp) then
                            local m = getMesh(e.comp)
                            if m then return pkgPath(m) or "?" end
                        end
                    end
                    return "-"
                end
                if key and SPAWN.seen[key] ~= sig() then
                    GT_STATE = "companion " .. tostring(leafName(a))
                    local okA, err = TRACE.timed(leafName(a) or "?", applyToActor, a)
                    if not okA then log("apply failed: %s", tostring(err)) end
                    SPAWN.seen[key] = sig()
                end
            end
        end
    end
end

local function recheckPending(round, waitedSince)
    round = round or 1
    if TRACE.busy() and loopTicks - (waitedSince or loopTicks) < 200 then   -- at most ~10 s
        TRACE.st.waits = (TRACE.st.waits or 0) + 1
        local since = waitedSince or loopTicks
        later(250, function() recheckPending(round, since) end)
        return
    end
    local todo = SPAWN.again[round] or {}
    SPAWN.again[round] = {}
    SPAWN.queued[round] = false
    local before = passChanges
    local keep = {}
    -- about 8 ms of looks per frame; the rest in the next frames (PC: the four party-menu
    -- characters took 95-309 ms each, all in one frame after every map load)
    local t0, left = os.clock(), nil
    for addr, e in pairs(todo) do
        if left then
            left[addr] = e
        elseif (os.clock() - t0) * 1000 > 8 then
            left = { [addr] = e }
        elseif not (SPAWN.same(e) and SPAWN.worth(e.a)) then
            if round == 1 then SPAWN.drop(e, round) end
        else
            keep[addr] = e
            GT_STATE = "new skin " .. tostring(leafName(e.a))
            if round == 1 and isSkinActor(e.a) then
                step("new skin: owner")
                local own = ownerOf(e.a)
                KNOWN_SKINS[addr] = { a = e.a, name = e.name, owner = valid(own) and fullPath(own) or nil }
            end
            if round == 1 and TRACE.on then
                -- what this skin belongs to and whether it is shown (copies the game keeps hidden?)
                step("new skin: owner, parent, hidden")
                local o = ownerOf(e.a)
                local okO, oc = pcall(function() return valid(o) and leafName(o:GetClass()) or "none" end)
                local okA, par = pcall(function() return e.a:GetAttachParentActor() end)
                local okP, pc = pcall(function() return (okA and valid(par)) and leafName(par:GetClass()) or "none" end)
                local okH, hid = pcall(function() return propOf(e.a, "bHidden", "BoolProperty") end)
                local shows = "-"
                for _, cn in ipairs({ "Body", "CharacterMesh0" }) do
                    local okC, comp = pcall(propOf, e.a, cn, "ObjectProperty")
                    if okC and alive(comp) then
                        local m = getMesh(comp)
                        shows = cn .. " " .. tostring(m and leafName(m) or "no mesh")
                        break
                    end
                end
                live("  new skin %s: owner %s, attached to %s, %s, shows %s", tostring(leafName(e.a)),
                    okO and tostring(oc) or "-", okP and tostring(pc) or "-",
                    okH and (hid and "hidden" or "shown") or "hidden: ?", shows)
            end
            local ok, err, ms = TRACE.timed(leafName(e.a) or "?", applyToActor, e.a)
            if not ok then log("apply failed: %s", tostring(err)) end
            if ms > 20 then live("  slow: %s took %d ms", tostring(leafName(e.a)), math.floor(ms + 0.5)) end
        end
    end
    if passChanges > before then
        live("re-check after spawn: %d change(s)", passChanges - before)
        if afterPass then afterPass(true) end
    end
    if left then                                -- next frame, same round
        local cur = SPAWN.again[round] or {}
        for addr, e in pairs(left) do cur[addr] = e end
        SPAWN.again[round] = cur
        if not SPAWN.queued[round] then
            SPAWN.queued[round] = true
            later(50, function() recheckPending(round) end)
        end
    end
    if round < #SPAWN.AFTER and next(keep) ~= nil then
        local nxt = SPAWN.again[round + 1] or {}
        for addr, e in pairs(keep) do nxt[addr] = e end
        SPAWN.again[round + 1] = nxt
        if not SPAWN.queued[round + 1] then
            SPAWN.queued[round + 1] = true
            later(SPAWN.AFTER[round + 1], function() recheckPending(round + 1) end)
        end
    end
end

local function onSkinActor(a, delayOnly)
    if not delayOnly then TRACE.st.spawns = (TRACE.st.spawns or 0) + 1 end
    if B.onSpawn then pcall(B.onSpawn, a, delayOnly) end
    local own = ownerOf(a)
    local okO, ownerCls = pcall(function() return valid(own) and leafName(own:GetClass()) or nil end)
    live("game %s %s%s", delayOnly and "re-assigned" or "spawned", tostring(leafName(a)),
        okO and ownerCls and (" for " .. ownerCls) or "")
    if loopTicks < SPAWN.quietUntil then return end      -- the map-load pass will handle it
    local e = SPAWN.entry(a)
    if not e then return end
    SPAWN.again[1] = SPAWN.again[1] or {}
    SPAWN.again[1][a:GetAddress()] = e
    if not SPAWN.queued[1] then
        SPAWN.queued[1] = true
        later(math.max(SPAWN.AFTER[1], SETTINGS.recheck_ms or 0), function() recheckPending(1) end)
    end
end

local function paramGet(p)
    local ok, v = pcall(function() return p:get() end)
    if ok and v ~= nil then return v end
    return p
end

-- Skins may be pooled and re-shown without a new BeginPlay; the native assign policy is called
-- for every skin change, and tells us which character the skin belongs to.
local function onAssigned(ownerName, charName)
    if not ownerName then return end
    for addr, k in pairs(KNOWN_SKINS) do
        if k.owner == ownerName then
            if not SPAWN.same(k) then
                KNOWN_SKINS[addr] = nil
            else
                local skin, c = k.a, normChar(charName)
                SCENE_COPY[addr] = tostring(charName):lower() == "default" and fullPath(skin) or nil
                if c then CHAR_OF[addr] = { name = k.name, char = c } end
                if TRACE.memo and TRACE.memo.char then TRACE.memo.char[addr] = nil end
                live("game assigned %s to %s", tostring(leafName(skin)), tostring(charName))
                onSkinActor(skin, true)
            end
        end
    end
end


-- --------------------------------------------------------------------------- redesign B probe
-- Redesign B: give the game the picked variant's own skin Blueprint in its "dress this character"
-- call, so the game dresses everyone itself instead of the mod re-dressing after it. This part
-- only measures and tests; it changes nothing unless settings.txt / the menu set b_swap:
--   * every skin call: which outfit class the game asks for, for whom ("B: call" lines);
--   * whether every new skin follows such a call (the minute's "B:" summary);
--   * how many picked variants bring their own skin Blueprint ("B: variants" line at start);
--   * whether a soft reference can be made from a class, and read back ("B: built");
--   * b_swap = param: the call's outfit is replaced before it runs; b_swap = call: the mod calls
--     the game's AssignBodySkin with the variant's class after the game's own call. The spawn
--     that follows says whether it took ("B: swap took" / "did not take").
-- The calls the game uses pass the outfit as a soft reference, and UE4SS 3.0.1-1125 crashes on
-- those (UE4SS #1433): they are only read on a build where it is fixed (1176), or b_soft = on.
B.FIXED = { ["1ba38db4"] = true }       -- UE4SS 3.0.1-1176: #1433 fixed
B.SLOTS = { AssignBodySkin = { "body" }, AssignBodySkinAsync = { "body" }, AssignFaceSkin = { "face" },
            AssignFaceSkinAsync = { "face" }, AssignBodyAndFaceSkin = { "body", "face" },
            AssignBodyAndFaceSkinAsync = { "body", "face" } }
B.keys, B.pending, B.expect, B.built, B.checks, B.broken = {}, {}, {}, {}, {}, {}
B.newStats = function()
    return { calls = 0, spawns = 0, matched = 0, reshown = 0, without = {}, swaps = 0, took = 0, nottaken = 0 }
end
B.st = B.newStats()

-- b_swap = call (fix11/fix12: the mod called the policy's AssignBodySkin itself) left bodies
-- invisible and animations frozen until a restart (PC, 15 Oct): it is gone; such a setting is off.
B.mode = function()
    if SETTINGS.b_swap ~= "off" and SETTINGS.b_swap ~= "param" then
        live("B: b_swap = %s is no longer offered (it broke bodies and animation in game): off", tostring(SETTINGS.b_swap))
        SETTINGS.b_swap = "off"
    end
    return SETTINGS.b_swap
end

B.softOk = function()
    if B.ok ~= nil then return B.ok end
    local head = ""
    local f = io.open(modDir .. "../../UE4SS.log", "r")
    if f then head = f:read(4096) or "" f:close() end
    B.sha = head:match("Git SHA #(%x+)")
    local force = tostring(SETTINGS.b_soft or "auto")
    if force == "on" then B.ok = true
    elseif force == "off" then B.ok = false
    else B.ok = B.sha ~= nil and B.FIXED[B.sha:sub(1, 8):lower()] == true end
    live("B: UE4SS build %s (b_soft = %s): soft references %s", B.sha or "unknown", force,
        B.ok and "are read" or "are not read (this build may crash on them, UE4SS #1433)")
    return B.ok
end

B.ksl = function()
    if B.kslObj == nil then
        local o = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
        B.kslObj = valid(o) and o or false
    end
    return B.kslObj or nil
end

B.str = function(v)                     -- an FString / FName / Lua string as a Lua string
    if type(v) == "string" then return v end
    if v == nil then return nil end
    local ok, s = pcall(function() return v:ToString() end)
    return ok and type(s) == "string" and s or nil
end

-- The path in a soft reference, read two independent ways: UE4SS's own accessor and the engine's
-- KismetSystemLibrary. Returns the path and both readings (they should agree).
-- The engine's reading is a second UFunction call, so it is made only when asked (logged calls).
B.path = function(soft, check)
    if soft == nil then return nil end
    -- an invalid UE4SS object answers IsValid() with false; a soft reference has no IsValid (error)
    local okv, v = pcall(function() return soft:IsValid() end)
    if okv and v == false then return nil end
    local ok1, p1 = pcall(function() return B.str(soft:GetObjectID():GetAssetPathName()) end)
    p1 = ok1 and p1 or nil
    local p2
    local k = check and B.ksl()
    if k then
        local ok2, r = pcall(function() return B.str(k:Conv_SoftClassReferenceToString(soft)) end)
        p2 = ok2 and r or nil
    end
    -- "/Package/Path.Object_C" is wanted; a reading without the object part is the worse one
    local best = (p1 and p1:find("%.")) and p1 or ((p2 and p2:find("%.")) and p2) or p1 or p2
    return best, p1, p2
end

B.classPath = function(cls)             -- "/Game/X/BP_Y.BP_Y_C" of a loaded class
    if not valid(cls) then return nil end
    local pp, r = pkgPath(cls)
    return pp and (pp .. "." .. r) or nil
end

B.charOf = function(name, path)         -- the party character a call is for
    local c = normChar(name)
    if c then return c end
    local set, n = charsIn(path)
    if n == 1 then return next(set) end
    return nil
end

-- The picked variant's own copy of a skin class, if it has one (no side effects; see wanted())
B.target = function(char, path)
    local pkg, obj = tostring(path or ""):match("^([^%.]+)%.(.+)$")
    if not pkg then return nil end
    local key = pkg:lower()
    local orig = TO_ORIGINAL[key]
    local a = activeFor(char)[orig and orig:lower() or key]
    if a and a.pkg:lower() ~= key and a.class == "BlueprintGeneratedClass" then return a.pkg, a.obj end
    return nil
end

-- noLoad: inside the game's own call, only a class already in memory (no synchronous load there)
-- With Wear on: the picked variant's own Blueprint class for this character, whatever outfit the
-- game asks for (PC: the party wore their base skins, BP_CharacterSkinBase_*, and Wear put the
-- Chic outfit over them, so the Chic Blueprint never matched what the game asked for). Same
-- choice as Wear's mesh (forcedFor): the latest pick among this character's Wear slots.
B.wearTarget = function(char)
    if not char then return nil end
    local wear, best, bestPick = wearSet(), nil, -1
    for _, slot in ipairs(SLOTS) do
        if wear[slot.id] and (slot.character == char or (not slot.character and Wear.slotChars(slot)[char]))
           and (PICK[slot.id] or 0) > bestPick then
            local v = selectedVariant(slot)
            for orig, e in pairs(v and v.map or {}) do
                -- a Blueprint whose path names characters must name this one: a mod split per
                -- character keeps every Blueprint in each part (Altered Flower Suit: Sciel's
                -- BP_CharacterSkin_ScielOutfit_FlowerSuit in the Lune part too)
                local named, n = charsIn(orig)
                if e[3] == "BlueprintGeneratedClass" and ((n > 0 and named[char]) or (n == 0 and slot.character == char)) then
                    best, bestPick = { pkg = e[1], obj = e[2] }, PICK[slot.id] or 0
                end
            end
        end
    end
    if best then return best.pkg, best.obj end
    return nil
end

B.softFor = function(pkg, obj, noLoad)  -- a soft reference to a loaded class, made by the engine
    local key = (pkg .. "." .. obj):lower()
    if B.built[key] ~= nil then return B.built[key] or nil end
    local k = B.ksl()
    if not k then return nil end
    local cls
    if noLoad then
        local o = StaticFindObject(pkg .. "." .. obj)
        cls = (valid(o) and alive(o)) and o or nil
    else
        step("B: load " .. pkg)
        cls = loadObj(pkg, obj)
    end
    if not cls then return nil end      -- not loaded yet: try again next time
    step("B: Conv_ClassToSoftClassReference")
    local ok, s = pcall(function() return k:Conv_ClassToSoftClassReference(cls) end)
    B.built[key] = (ok and s ~= nil) and s or false
    if not B.built[key] then live("B: could not make a soft reference to %s.%s: %s", pkg, obj, tostring(s)) end
    return B.built[key] or nil
end

-- Before the game's skin call runs (UE4SS pre-hook): read what it asks for; with b_swap = param,
-- replace the outfit with the picked variant's own class.
B.pre = function(fn, ctx, owner, charName, p1, p2)
    if not onGameThread() then return end
    local soft = fn:find("Async$") ~= nil
    if soft and not B.softOk() then return end
    step("B: read the call " .. fn)
    local c = B.str(paramGet(charName)) or "?"
    local ow = paramGet(owner)
    local okw, ownerCls = pcall(function()
        if not valid(ow) then return "none" end
        local oc = ow:GetClass()
        return valid(oc) and leafName(oc) or "?"
    end)
    ownerCls = okw and ownerCls or "?"
    local parts, req = {}, {}
    local key0 = fn .. "|" .. c .. "|" .. ownerCls
    local logIt = (B.keys[key0] or 0) < 2      -- the first calls per function and name: cross-checked
    for i, what in ipairs(B.SLOTS[fn] or {}) do
        local p = (i == 1) and p1 or p2
        if p then
            local path, a, b
            if soft then
                path, a, b = B.path(paramGet(p), logIt)
            else
                path = B.classPath(paramGet(p))
            end
            if a and b and a ~= b then
                parts[#parts + 1] = string.format("%s %s (the engine reads %s)", what, a, b)
            else
                parts[#parts + 1] = what .. " " .. tostring(path)
            end
            req[#req + 1] = { what = what, path = path, p = p }
        end
    end
    B.st.calls = B.st.calls + 1
    B.keys[key0] = (B.keys[key0] or 0) + 1
    local key = key0 .. "|" .. table.concat(parts, "|")
    B.keys[key] = (B.keys[key] or 0) + 1
    if B.keys[key] <= 2 then
        live("B: call %s for %s (owner %s): %s%s", fn, c, ownerCls, table.concat(parts, ", "),
            "")
    end
    local char = nil
    for _, r in ipairs(req) do
        if r.path and r.path ~= "" and r.path ~= "None" then
            local k = r.path:lower()
            local e = B.pending[k] or { n = 0 }
            e.n, e.t, e.char = e.n + 1, os.clock(), c
            B.pending[k] = e
            char = char or B.charOf(c, r.path)
            local pkg, obj = B.target(char, r.path)
            local how = "replaces"
            if not pkg and r.what == "body" then
                pkg, obj = B.wearTarget(char)
                how = "Wear"
                -- already the variant's class (the game asks for what a swap gave it): nothing to do
                if pkg and (pkg .. "." .. obj):lower() == r.path:lower() then pkg = nil end
            end
            if pkg and B.broken[(pkg .. "." .. obj):lower()] then
                pkg = nil                       -- it broke a body before (B.checkBody): not again this session
            end
            if pkg and c ~= "?" then
                if SETTINGS.b_swap == "param" and soft then
                    local s = B.softFor(pkg, obj, true)
                    if s then
                        step("B: write the call's " .. r.what)
                        local okw, err = pcall(function() r.p:set(s) end)
                        local back = B.path(paramGet(r.p))
                        B.st.swaps = B.st.swaps + 1
                        e.swappedTo = pkg .. "." .. obj
                        local ek = (pkg .. "." .. obj):lower()
                        local x0 = B.expect[ek]       -- several swaps to one class: one "took" each
                        B.expect[ek] = { t = os.clock(), char = c, from = r.path,
                                         n = ((x0 and os.clock() - x0.t < 20) and x0.n or 0) + 1 }
                        local ow = paramGet(owner)
                        if valid(ow) and r.what == "body" then
                            B.checks[#B.checks + 1] = { ek = ek, owner = ow, name = fullPath(ow), char = c, t = os.clock() }
                        end
                        live("B: swap (param, %s) %s %s for %s: %s -> %s.%s: %s; the call now asks for %s", how, fn,
                            r.what, c, r.path, pkg, obj, okw and "written" or ("write failed: " .. tostring(err)),
                            tostring(back))
                    else
                        live("B: swap (param) for %s skipped: %s.%s is not ready yet (prepared after a pick)", c, pkg, obj)
                        later(100, function() pcall(B.softFor, pkg, obj) end)
                    end
                end
            end
        end
    end
end

-- A skin the game spawned (or showed again): did a call ask for its class? Did a swap take?
B.onSpawn = function(a, reshown)
    local okc, cls = pcall(function() return a:GetClass() end)
    local cp = okc and B.classPath(cls)
    if not cp then return end
    local k, now = cp:lower(), os.clock()
    local x = B.expect[k]
    if x and now - x.t < 20 then
        x.n = (x.n or 1) - 1
        if x.n <= 0 then B.expect[k] = nil end
        B.st.took = B.st.took + 1
        live("B: swap took: the game %s %s for %s (it had asked for %s)", reshown and "showed" or "spawned", cp,
            x.char, x.from)
        for i, ch in ipairs(B.checks) do       -- the character that call dressed: look at its body soon
            if ch.ek == k then
                table.remove(B.checks, i)
                later(2000, function() pcall(B.checkBody, ch, cp) end)
                break
            end
        end
    end
    local e = B.pending[k]
    if e and now - e.t < 15 then
        if e.swappedTo then
            B.st.nottaken = B.st.nottaken + 1
            live("B: swap did not take: the game %s its own %s for %s", reshown and "showed" or "spawned", cp, e.char)
        end
        e.n = e.n - 1
        if e.n <= 0 then B.pending[k] = nil end
        if reshown then B.st.reshown = B.st.reshown + 1 else B.st.matched = B.st.matched + 1 end
    elseif not reshown and not x then
        local n = leafName(cls) or cp
        B.st.without[n] = (B.st.without[n] or 0) + 1
    end
    if not reshown then B.st.spawns = B.st.spawns + 1 end
end

-- 2 s after a swap took: the body of the character the game dressed. PC, 16 Oct: with a multi-outfit
-- mod's relocated Sciel Blueprint the cutscene Sciel's Body had no mesh (lower body invisible),
-- in both swap tests (call and param). A broken body stops swaps to that class for the session.
B.checkBody = function(ch, cp)
    if not (alive(ch.owner) and fullPath(ch.owner) == ch.name) then
        live("B: after the swap to %s, %s is gone: body not checked", cp, tostring(ch.name))
        return
    end
    local function judge(comp, cn)
        local m = getMesh(comp)
        if m then
            live("B: after the swap %s (%s).%s shows %s", tostring(leafName(ch.owner)), ch.char, cn,
                tostring(pkgPath(m) or leafName(m)))
        else
            B.broken[ch.ek] = true
            live("B: swap broke the body: %s (%s).%s has no mesh after the game used %s; no more swaps to it "
                .. "this session (switch the test off; the next re-dress shows the game's outfit)",
                tostring(leafName(ch.owner)), ch.char, cn, cp)
        end
    end
    -- the body by its component's own name, never through a property (see meshComponents): Body on
    -- skin actors and world pawns, CharacterMesh0 on battle and companion pawns (their empty
    -- "SkeletalMesh" component is not the body)
    local list, shown = meshComponents(ch.owner), {}
    for _, cn in ipairs({ "Body", "CharacterMesh0" }) do
        for _, e in ipairs(list) do
            if e.name == cn and alive(e.comp) and isA(e.comp, "/Script/Engine.SkeletalMeshComponent") then
                return judge(e.comp, cn)
            end
        end
    end
    -- a pawn whose body component is named at run time: what its skeletal meshes show, without
    -- judging which is the body
    for _, e in ipairs(list) do
        local m, kind = getMesh(e.comp)
        if kind == "skel" and #shown < 4 then
            shown[#shown + 1] = tostring(e.name) .. " " .. tostring(m and (pkgPath(m) or leafName(m)) or "no mesh")
        end
    end
    live("B: after the swap %s (%s) has no Body or CharacterMesh0 to check; its skeletal meshes: %s",
        tostring(leafName(ch.owner)), ch.char, #shown > 0 and table.concat(shown, ", ") or "none")
end

B.minute = function()                   -- one summary line per minute (with "stats")
    local st, now = B.st, os.clock()
    local stale = 0
    for k, e in pairs(B.pending) do
        if now - e.t >= 15 then stale = stale + e.n B.pending[k] = nil end
    end
    for i = #B.checks, 1, -1 do                 -- swaps whose skin never appeared
        if now - B.checks[i].t >= 20 then table.remove(B.checks, i) end
    end
    for k, x in pairs(B.expect) do
        if now - x.t >= 20 then
            live("B: swap to %s for %s: no skin of that class appeared within 20 s", k, x.char)
            B.expect[k] = nil
        end
    end
    B.st = B.newStats()
    if st.calls + st.spawns + st.swaps + st.reshown + st.took == 0 then return end
    local w, nw = {}, 0
    for n, c in pairs(st.without) do nw = nw + c w[#w + 1] = n .. (c > 1 and (" x" .. c) or "") end
    table.sort(w)
    live("B: %d call(s); %d new skin(s): %d after a call for that class, %d without%s; %d shown again after a call; "
        .. "%d asked-for skin(s) (bodies and faces) with no new one within 15 s; swaps %d: took %d, did not take %d",
        st.calls, st.spawns, st.matched, nw, nw > 0 and (" (" .. table.concat(w, ", ") .. ")") or "", st.reshown,
        stale, st.swaps, st.took, st.nottaken)
    if not (SETTINGS.auto_apply and anyActive()) then
        live("B: (new skins are only watched while something is picked and \"Apply to new skins\" is on)")
    end
end

-- Picks changed: the call-mode stops start over, and the picked variants' classes are prepared
-- (loaded, soft reference made) outside the game's own calls.
B.changed = function()
    if SETTINGS.b_swap ~= "off" and B.ok then later(500, function() pcall(B.preload) end) end
end
B.preload = function()
    for _, c in ipairs({ "Lune", "Maelle", "Sciel", "Verso", "Monoco", "Gustave" }) do
        local pkg, obj = B.wearTarget(c)
        if pkg then B.softFor(pkg, obj) end
    end
    for _, slot in ipairs(SLOTS) do
        local v = selectedVariant(slot)
        for _, e in pairs(v and v.map or {}) do
            if e[3] == "BlueprintGeneratedClass" then B.softFor(e[1], e[2]) end
        end
    end
end

-- At start: how many picked-or-not variants bring their own skin Blueprint (those the game could
-- dress itself as they are); the others replace meshes or textures only.
B.inventory = function()
    local total, own, perMod, names = 0, 0, {}, {}
    for _, slot in ipairs(SLOTS) do
        for _, v in ipairs(slot.variants or {}) do
            total = total + 1
            local has = false
            for _, e in pairs(v.map or {}) do
                if e[3] == "BlueprintGeneratedClass" then
                    has = true
                    if #names < 6 then names[#names + 1] = e[2] end
                end
            end
            local m = slot.mod or "?"
            perMod[m] = perMod[m] or { 0, 0 }
            perMod[m][2] = perMod[m][2] + 1
            if has then own = own + 1 perMod[m][1] = perMod[m][1] + 1 end
        end
    end
    local parts = {}
    for m, c in pairs(perMod) do parts[#parts + 1] = string.format("%s %d/%d", m, c[1], c[2]) end
    table.sort(parts)
    live("B: variants: %d of %d bring their own Blueprint class (%s); per mod: %s", own, total,
        #names > 0 and table.concat(names, ", ") or "none", table.concat(parts, "; "))
end

-- Once per session, a few seconds after the first map: the functions a redesign could use (names
-- and types only), the build test, and what each character's skin component says it wears.
B.prepare = function()
    if B.prepared then return end
    local function sig(full)
        local okf, f = pcall(StaticFindObject, full)
        if not (okf and valid(f)) then live("B: function %s not found", full) return end
        local params = {}
        pcall(function()
            f:ForEachProperty(function(pr)
                params[#params + 1] = pr:GetClass():GetFName():ToString() .. " " .. pr:GetFName():ToString()
            end)
        end)
        live("B: function %s(%s)", full:match("[^%.:]+:[^:]+$") or full, table.concat(params, ", "))
    end
    -- after a map with characters (the first map is often the title screen, without any)
    step("B: skin components")
    local okc, comps = pcall(FindAllOf, "BP_CharacterSkinComponent_C")
    local first = okc and type(comps) == "table" and comps[1] or nil
    local okp, cpath = pcall(function()
        if not alive(first) then return nil end
        local cls = first:GetClass()
        return valid(cls) and B.classPath(cls) or nil
    end)
    if not (okp and cpath) then return end
    B.prepared = true
    for _, fn in ipairs({ "Conv_ClassToSoftClassReference", "Conv_SoftClassReferenceToString",
                          "Conv_SoftClassReferenceToClass" }) do
        sig("/Script/Engine.KismetSystemLibrary:" .. fn)
    end
    for _, fn in ipairs({ "OverrideCharacterSkin", "SetCharacterCustomization", "ApplyCurrentCharacterSkin",
                          "ApplyCurrentCustomization" }) do
        sig(cpath .. ":" .. fn)
    end
    -- only with the test on: it loads Blueprints on the game thread (a hitch for nothing otherwise)
    if not B.softOk() or B.mode() == "off" then return end
    -- the build test: a soft reference to each picked variant's own skin class, read back
    local done = 0
    for _, slot in ipairs(SLOTS) do
        local v = selectedVariant(slot)
        for _, e in pairs(v and v.map or {}) do
            if done < 6 and e[3] == "BlueprintGeneratedClass" then
                done = done + 1
                local s = B.softFor(e[1], e[2])
                local back = s and B.path(s, true)
                local want = e[1] .. "." .. e[2]
                live("B: built a soft reference to %s: %s", want, not s and "failed"
                    or (back == want and "reads back the same" or ("reads back " .. tostring(back))))
                -- what the game will copy from it: its Body template, next to the game's own class
                local function body(pkg, obj)
                    local c = loadObj(pkg, obj)
                    if not c then return "not loaded" end
                    local t = classTemplates(c, { "Body" }).Body
                    if not t then return "no Body template" end
                    local m = getMesh(t)
                    local okM, mats = pcall(function() return #arrayItems(propOf(t, "OverrideMaterials", "ArrayProperty")) end)
                    return string.format("mesh %s, %s material override(s)", tostring(m and pkgPath(m) or "none"),
                        okM and tostring(mats) or "?")
                end
                local orig = TO_ORIGINAL[e[1]:lower()]
                live("B: Blueprint %s: Body %s; the game's own %s: Body %s", e[2], body(e[1], e[2]),
                    tostring(orig), orig and body(orig, e[2]) or "-")
            end
        end
    end
    if done == 0 then live("B: no picked variant brings its own skin Blueprint: nothing to build") end
end

local POLICY_FUNCS = { "AssignBodySkin", "AssignBodySkinAsync", "AssignFaceSkin", "AssignFaceSkinAsync",
                       "AssignBodyAndFaceSkin", "AssignBodyAndFaceSkinAsync" }
local policyHooks, hooked = 0, false

-- Called once on the game thread: every hook of this mod is registered from there.
local function registerHooks()
    hooked = pcall(function()
        -- timed: the hook runs for every actor the game creates (PC: up to 25 000 times in one
        -- map-load stall), outside the loop the hitch lines measure
        local onBeginPlay
        RegisterBeginPlayPostHook(function(actor)
            local t0 = os.clock()
            local ok, err = pcall(onBeginPlay, actor)
            TRACE.bpMs, TRACE.bpN = (TRACE.bpMs or 0) + (os.clock() - t0) * 1000, (TRACE.bpN or 0) + 1
            if not ok then error(err, 0) end
        end)
        onBeginPlay = function(actor)
            TRACE.bp = TRACE.bp + 1                 -- spawn burst detection (plain Lua)
            if TRACE.on and liveF then TRACE.scene(paramGet(actor)) end
            if SETTINGS.clean then
                local ka = paramGet(actor)
                if valid(ka) and isWardrobeActor(ka) then
                    local kn = fullPath(ka)
                    later(1000, function() if alive(ka) and fullPath(ka) == kn then Clean.actor(ka, Clean.newStats()) end end)
                end
            end
            if not SETTINGS.auto_apply or not anyActive() then
                -- a swap test waits for its skin even then (B.onSpawn runs from onSkinActor otherwise)
                if next(B.expect or {}) ~= nil then
                    local x = paramGet(actor)
                    if valid(x) and isWardrobeActor(x) then pcall(B.onSpawn, x) end
                end
                return
            end
            local a = paramGet(actor)
            if valid(a) and isWardrobeActor(a) then onGT(onSkinActor, a, false) end
        end
    end)
    -- Probe for a possible redesign (giving the game the picked outfit before it dresses anyone):
    -- each function's parameter list, read from the function itself (names and types only, never
    -- a value), and how often each is called through ProcessEvent (only those calls can be
    -- changed before they run). Written to the live log; counted in the stats line.
    TRACE.policy = {}
    for _, fn in ipairs(POLICY_FUNCS) do
        pcall(function()
            local f = StaticFindObject("/Script/SandFall.CharacterSkinAssignPolicy:" .. fn)
            if not valid(f) then live("probe: %s not found", fn) return end
            local params = {}
            f:ForEachProperty(function(pr)
                params[#params + 1] = pr:GetClass():GetFName():ToString() .. " " .. pr:GetFName():ToString()
            end)
            live("probe: %s(%s)", fn, table.concat(params, ", "))
        end)
    end
    for _, fn in ipairs(POLICY_FUNCS) do
        local ok = pcall(RegisterHook, "/Script/SandFall.CharacterSkinAssignPolicy:" .. fn,
            function(ctx, owner, charName, p1, p2)
                TRACE.policy[fn] = (TRACE.policy[fn] or 0) + 1
                local okB, errB = pcall(B.pre, fn, ctx, owner, charName, p1, p2)
                if not okB then live("B: reading the call %s failed: %s", fn, tostring(errB)) end
            end,
            function(_, owner, charName)
                if not onGameThread() then return end
                local o = owner and paramGet(owner)
                local c
                if charName then
                    local okc, s = pcall(function() return paramGet(charName):ToString() end)
                    if okc then c = s end
                end
                Fix.noteName(o, c)                  -- the name Fix look passes back to the game
                if valid(o) then SCENE_COPY[o:GetAddress()] = tostring(c):lower() == "default" and fullPath(o) or nil end
                -- a pooled skin re-shown without a BeginPlay: clean it too, picks or not
                local oName = valid(o) and fullPath(o) or nil
                if SETTINGS.clean and Clean.owner then
                    later(1000, function() if alive(o) and fullPath(o) == oName then Clean.owner(o) end end)
                end
                if not SETTINGS.auto_apply or not anyActive() then return end
                later(50, function() onAssigned(oName, c) end)
            end)
        if ok then policyHooks = policyHooks + 1 end
    end
    -- After a level loads, one full pass also reaches actors that aren't skin actors (world / menu
    -- pawns showing a replaced base body), and learns their classes for the BeginPlay hook.
    pcall(RegisterLoadMapPreHook, function() if Clean.forget then Clean.forget() end end)
    -- A new map, from either hook (whichever fires first; the other is ignored for 5 s). With
    -- UE4SS-settings.ini HookLoadMap = 0 (PC: one crash came from inside the engine's LoadMap,
    -- called through UE4SS's LoadMap hook) InitGameState still tells the mod.
    local function mapLoaded(wname, via)
        if os.clock() - (SPAWN.mapAt or -100) < 5 then return end
        -- a map right after another (PC 17 Oct: world map, then camp 11 s later, crash 3 s after
        -- that in the map-load pass): give the game 6 s instead of 3 to finish loading
        local wait = (os.clock() - (SPAWN.mapAt or -100) < 30) and 6000 or 3000
        SPAWN.mapAt = os.clock()
        live("map loaded: %s%s", tostring(wname or "?"), via and (" (" .. via .. ")") or "")
        SPAWN.quietUntil = loopTicks + wait // 50   -- new skins are left to the map-load pass
        TRACE.clsSkip = {}
        for k in pairs(FORCED_FROM) do FORCED_FROM[k] = nil end   -- every component is new now
        -- objects of the previous map: their addresses can be reused by new ones
        Wear.donor = {}
        for k in pairs(CHAR_OF) do CHAR_OF[k] = nil end
        for k in pairs(SCENE_COPY) do SCENE_COPY[k] = nil end
        for k in pairs(KNOWN_SKINS) do KNOWN_SKINS[k] = nil end
        SPAWN.seen, SPAWN.dropped = {}, {}
        TRACE.tmpl = {}
        TRACE.used = {}
        if Fix.forget then Fix.forget() end
        B.built, B.pending, B.expect = {}, {}, {}
        if not B.prepared then later(8000, function() pcall(B.prepare) end) end
        -- a diagnostic (~70 ms once): only in test sessions (b_swap on), not for every player
        if not TRACE.speedDone and wname and wname ~= "Level_MainMenu" and B.mode() ~= "off" then
            later(9000, function() pcall(TRACE.speedTest) end)
        end
        if B.changed then later(9000, function() pcall(B.changed) end) end
        if SETTINGS.auto_apply and anyActive() then later(wait, function() applyAll("after map load") end) end
        if SETTINGS.clean then later(wait + 500, function() Clean.all("map loaded") end) end
    end
    pcall(RegisterLoadMapPostHook, function(_, world)
        local okw, wname = pcall(function() return leafName(paramGet(world)) end)
        mapLoaded(okw and wname or nil)
    end)
    pcall(RegisterInitGameStatePostHook, function(ctx)
        local okw, wname = pcall(function()
            local gm = paramGet(ctx)
            if not valid(gm) then return nil end
            local w = gm:GetWorld()
            return valid(w) and leafName(w) or nil
        end)
        mapLoaded(okw and wname or nil, "game state")
    end)
    pcall(RegisterConsoleCommandHandler, "wardrobe", onConsole)
    if MENU.registerHooks then pcall(MENU.registerHooks) end
end

-- The game-thread loop: inbox (keys, clicks), the mod's timers, new skins, the menu, the
-- debounced apply pass. Its timestamp is the heartbeat the watchdog reads.
local function loopBody()
    if TRACE.wdBeat then
        -- after a WATCHDOG line: the game went on (a long load), it wasn't a freeze
        live("WATCHDOG: the game thread ran again after %d s", os.time() - TRACE.wdBeat)
        TRACE.wdBeat = nil
    end
    GT_BEAT = os.time()
    loopTicks = loopTicks + 1
    TRACE.tick = loopTicks
    local tickT0 = os.clock()
    if TRACE.lastTick then
        -- the loop runs every 50 ms; a longer gap is a frame the game took that long for
        local gap = (tickT0 - TRACE.lastTick) * 1000
        local st = TRACE.st
        if gap >= 500 or TRACE.bp >= 5 then TRACE.busyAt = loopTicks end
        TRACE.bp = 0
        if gap >= 150 and gap < 6000 then
            st.hitches = st.hitches + 1
            if gap > st.worst then st.worst = gap end
            if tickT0 - TRACE.lastHitch >= 1 then  -- at most one line a second
                TRACE.lastHitch = tickT0
                live("hitch: a frame took %d ms (mod work in the tick before: %d ms; last mod step: %s; "
                    .. "BeginPlay hook meanwhile: %d ms in %d call(s))",
                    math.floor(gap + 0.5), math.floor(TRACE.tickMs + 0.5), TRACE.step,
                    math.floor((TRACE.bpMs or 0) + 0.5), TRACE.bpN or 0)
            end
        end
        if tickT0 - st.since >= 60 then
            live("stats (%d s): %d actor look(s) in %d ms (slowest %s %d ms), %d mesh set(s), %d pass(es) in %d ms, %d hitch(es) (worst %d ms), %d object(s) skipped (loading/destroyed), %d wait(s) for calm, BeginPlay hook %d ms in %d call(s)",
                math.floor(tickT0 - st.since + 0.5), st.actors, math.floor(st.actorMs + 0.5), st.slowName,
                math.floor(st.slowest + 0.5), st.sets, st.passes, math.floor(st.passMs + 0.5), st.hitches, math.floor(st.worst + 0.5),
                st.skipped or 0, st.waits or 0, math.floor((st.bpMs or 0) + 0.5), st.bpN or 0)
            if TRACE.policy and next(TRACE.policy) then
                local parts = {}
                for k, v in pairs(TRACE.policy) do parts[#parts + 1] = k .. " " .. v end
                table.sort(parts)
                live("probe: calls seen before they run: %s; new skins seen: %d", table.concat(parts, ", "), st.spawns or 0)
                TRACE.policy = {}
            end
            pcall(B.minute)
            TRACE.st = { actors = 0, actorMs = 0, slowest = 0, slowName = "", sets = 0, passes = 0, passMs = 0,
                         hitches = 0, worst = 0, since = tickT0 }
        end
    end
    TRACE.st.bpMs = (TRACE.st.bpMs or 0) + (TRACE.bpMs or 0)
    TRACE.st.bpN = (TRACE.st.bpN or 0) + (TRACE.bpN or 0)
    TRACE.bpMs, TRACE.bpN = 0, 0
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
    if MENU.wantsTick and MENU.wantsTick() then onGT(MENU.tick) end
    if PASS.due and loopTicks >= PASS.due then onGT(applyIfDue) end
    if SETTINGS.clean and loopTicks % 20 == 0 then onGT(Clean.keep) end
    if SETTINGS.auto_apply and loopTicks % 40 == 0 then onGT(SPAWN.watch) end
    if loopTicks % 20 == 7 then onGT(TRACE.commands) end
    TRACE.lastTick = os.clock()
    TRACE.tickMs = (TRACE.lastTick - tickT0) * 1000
    if TRACE.tickMs >= 150 then
        -- the gap above is measured between ticks, so a long frame made by the mod's own work
        -- shows here, not there
        local st = TRACE.st
        st.hitches = st.hitches + 1
        if TRACE.tickMs > st.worst then st.worst = TRACE.tickMs end
        live("hitch: the mod's own work took %d ms in one frame (last mod step: %s)",
            math.floor(TRACE.tickMs + 0.5), TRACE.step)
    end
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
            TRACE.wdBeat = GT_BEAT
            live("WATCHDOG: the game thread has not run for %d s; mod state: %s (since %s)", now - GT_BEAT, GT_STATE,
                os.date("%H:%M:%S", GT_STATE_SINCE))
            if TRACE.on and TRACE.beat ~= GT_BEAT then
                -- once per stall: the mod's last steps, oldest first; the last one is where it stopped
                -- if the mod state above isn't "idle"
                TRACE.beat = GT_BEAT
                local last = TRACE.ring[TRACE.n]
                local t1 = last and last.t or 0
                live("WATCHDOG: last mod step: %s", TRACE.step)
                for i = 1, TRACE.size do
                    local e = TRACE.ring[(TRACE.n + i - 1) % TRACE.size + 1]
                    if e then
                        live("  step %6d ms: %s%s", math.floor((e.t - t1) * 1000 - 0.5), e.s,
                            e.k and string.format(" (x%d)", e.k) or "")
                    end
                end
            end
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
    favorites = function() return Fav.list end, saveFavorites = Fav.save,
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
    canWear = function(slot) return hasMesh(slot) and (slot.character ~= nil or next(Wear.slotChars(slot)) ~= nil) end,
    slotChars = function(slot) return Wear.slotChars(slot) end,
    isTechnical = isTechnical, outfitName = outfitName,
    targetOutfit = function(slot, char) return targetOutfit(slot, char) end,
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
    pcall(B.inventory)
    pcall(B.mode)
    pcall(B.softOk)
    pcall(B.changed)                    -- prepares the picked variants' classes for the swap tests
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
