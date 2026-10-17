-- Counting UE4SS mock: every index on an engine proxy (UObject, struct, TArray, FName) is one
-- Lua->C++ crossing in real UE4SS. TRACE keeps them in order, interleaved with live_log lines.
TRACING, TRACE, COUNT, KCOUNT = false, {}, 0, {}
SITES = nil   -- set to {} to count call sites (main.lua lines, the two innermost)
local function site()
  local where = {}
  for lvl = 3, 40 do
    local info = debug.getinfo(lvl, "Sl")
    if not info or #where == 3 then break end
    if (info.source or ""):find("main.lua", 1, true) then where[#where + 1] = info.currentline end
  end
  return table.concat(where, "<")
end
local function rec(kind, what)
  if not TRACING then return end
  if SITES then local k = site(); SITES[k] = (SITES[k] or 0) + 1 end
  if FUNCS then                                -- inclusive count per main.lua function (by its first line)
    local seen = {}
    for lvl = 3, 60 do
      local info = debug.getinfo(lvl, "S")
      if not info then break end
      if (info.source or ""):find("main.lua", 1, true) then
        local k = info.linedefined
        if not seen[k] then seen[k] = true FUNCS[k] = (FUNCS[k] or 0) + 1 end
      end
    end
  end
  COUNT = COUNT + 1
  KCOUNT[kind] = (KCOUNT[kind] or 0) + 1
  TRACE[#TRACE + 1] = kind .. " " .. what
end
function resetTrace() TRACE, COUNT, KCOUNT, TICKMAX = {}, 0, {}, 0 end

-- live_log.txt and other files: in memory; live lines go into the trace
local realOpen = io.open
FILESTORE = {}
io.open = function(path, mode)
  mode = mode or "r"
  if mode:find("[wa]") then
    local buf = {}
    return { write = function(self, ...) for _, s in ipairs({ ... }) do s = tostring(s); buf[#buf + 1] = s
               if path:find("live_log") and TRACING then TRACE[#TRACE + 1] = "LIVE " .. s:gsub("\n$", "") end end return self end,
             flush = function() end, close = function() FILESTORE[path] = table.concat(buf) end,
             lines = function() return function() return nil end end, seek = function() return 0 end }
  end
  if FILESTORE[path] then
    local s = FILESTORE[path]
    return { lines = function() return s:gmatch("[^\n]+") end, read = function() return s end, close = function() end,
             seek = function() return #s end }
  end
  return realOpen(path, mode)
end
os.remove = function() end
os.rename = function() end

local LOG = {}
function print(s) LOG[#LOG + 1] = s end
function getlog() return table.concat(LOG) end

-- FName / FString
function FName(s) rec("FNameCtor", s)
  return setmetatable({ _s = s }, { __index = function(t, k) rec("fname", k) if k == "ToString" then return function() return s end end end })
end
EFindName = { FNAME_Add = 1 }

-- structs
function struct(name, fields)
  return setmetatable({ _raw = fields }, { __index = function(_, k)
    local v = fields[k]
    rec(v == nil and "MISS.struct" or "struct", name .. "." .. k)
    return v end })
end
-- TArray property (userdata with ForEach / GetArrayNum / [i])
function TArray(name, items)
  return setmetatable({ _items = items }, { __index = function(t, k)
    if k == "ForEach" then rec("array", name .. ":ForEach(" .. #items .. ")")
      return function(_, fn) for i, v in ipairs(items) do
        fn(i, setmetatable({}, { __index = function(_, kk) rec("elem", name .. "[i]:get") if kk == "get" then return function() return v end end end }))
      end end
    elseif k == "GetArrayNum" then rec("array", name .. ":GetArrayNum") return function() return #items end
    elseif type(k) == "number" then rec("array", name .. "[i]") return items[k] end
    end, __newindex = function(t, k, v) rec("array", name .. "[i]=") items[k] = v end })
end
-- UFunction TArray return value: plain table of RemoteUnrealParam
function PARAMS(name, items)
  local t = {}
  for i, v in ipairs(items) do t[i] = setmetatable({}, { __index = function(_, k) rec("param", name .. ":get") if k == "get" then return function() return v end end end }) end
  return t
end

local ADDR = 0x1000
-- game time: advances 50 ms per loop tick (deterministic counts; the 8 ms budgets never split work)
MOCK_TICKS = 0
os.clock = function() return MOCK_TICKS * 0.05 end
Obj = {}
local function short(o) return (rawget(o, "_path") or "?"):match("[%.:]([^%.:]+)$") or rawget(o, "_path") end
local METHODS = {}
METHODS.IsValid = function(o) return not rawget(o, "_dead") end
METHODS.GetFullName = function(o) return o._cls .. " " .. o._path end
METHODS.GetFName = function(o) local n = short(o); return FNameQuiet(n) end
METHODS.GetAddress = function(o) return o._addr end
METHODS.GetClass = function(o) return o._class end
METHODS.GetSuperStruct = function(o) return o._super end
-- UE4SS has these (the old mock read them as missing properties)
METHODS.HasAnyFlags = function(o) return false end
METHODS.HasAnyInternalFlags = function(o) return false end
-- classes list their properties (UE4SS can; propOf then skips names a class doesn't have)
METHODS.ForEachProperty = function(o, fn) for _, pr in ipairs(rawget(o, "_plist") or {}) do fn(pr) end end
METHODS.IsA = function(o, c)
  local k = o._kind
  while k do if c and rawget(c, "_name") == k then return true end; k = KINDS[k] end
  return false
end
function FNameQuiet(s)
  return setmetatable({}, { __index = function(_, k) rec("fname", k) if k == "ToString" then return function() return s end end end })
end
KINDS = { SkeletalMeshComponent = "MeshComponent", StaticMeshComponent = "MeshComponent", MeshComponent = "Component",
          MaterialInstanceDynamic = "MaterialInstance", MaterialInstanceConstant = "MaterialInstance",
          MaterialInstance = "MaterialInterface", Material = "MaterialInterface",
          Texture2D = "Texture", TextureRenderTarget2D = "Texture" }
Obj.__index = function(t, k)
  local m = METHODS[k]
  if m then rec("call", short(t) .. ":" .. k) return m end
  local fns = rawget(t, "_f"); if fns and fns[k] then rec("ufunc", short(t) .. ":" .. k) return fns[k] end
  local props = rawget(t, "_p"); if props and props[k] ~= nil then rec("prop", short(t) .. "." .. k) return props[k] end
  rec("MISS", short(t) .. "." .. k)
  return nil
end
Obj.__newindex = function(t, k, v)
  if type(k) == "string" and k:sub(1, 1) == "_" then rawset(t, k, v) return end
  rec("propset", short(t) .. "." .. k) rawget(t, "_p")[k] = v end

function new(kind, cls, path, props, fns)
  ADDR = ADDR + 0x100
  return setmetatable({ _kind = kind, _cls = cls or kind, _path = path, _p = props or {}, _f = fns or {}, _addr = ADDR }, Obj)
end
CLASSES = {}
for _, n in ipairs({ "MeshComponent", "SkeletalMeshComponent", "StaticMeshComponent", "MaterialInstanceDynamic",
                     "MaterialInterface", "Texture", "TextureRenderTarget2D" }) do
  local c = new("Class", "Class", "/Script/Engine." .. n)
  c._name = n
  CLASSES["/Script/Engine." .. n] = c
end
REG, LOADABLE = {}, {}
local INVALID = setmetatable({ _path = "INVALID" }, { __index = function(_, k) rec("call", "invalid:" .. k) if k == "IsValid" then return function() return false end end end })
function StaticFindObject(p) rec("StaticFindObject", p) return CLASSES[p] or REG[p] or INVALID end
function realLoad(p) if REG[p] == nil and LOADABLE[p] then REG[p] = LOADABLE[p]() end end
local ARHobj = new("AssetRegistryHelpers", "Class", "/Script/AssetRegistry.Default__AssetRegistryHelpers", {}, {
  GetAsset = function(self, ad)
    local full = ad.PackageName._s .. "." .. ad.AssetName._s
    if TRACING then TRACE[#TRACE + 1] = "SYNCLOAD " .. full end
    realLoad(full); return REG[full] end })
CLASSES["/Script/AssetRegistry.Default__AssetRegistryHelpers"] = ARHobj
function LoadAsset(p) rec("LoadAsset", p) end
function asset(kind, full, props, fns) LOADABLE[full] = function() return new(kind, kind, full, props, fns) end end
function get(full) realLoad(full); return REG[full] end

ACTORS = {}
function FindAllOf(name)
  rec("FindAllOf", name)
  local out = {}
  for _, a in ipairs(ACTORS) do if a._find and a._find[name] then out[#out + 1] = a end end
  if name == "SkeletalMeshComponent" then for _, c in ipairs(ALLSKMC or {}) do out[#out + 1] = c end end
  return #out > 0 and out or nil
end
function FindFirstOf() return nil end
IN_GT = false
function ExecuteInGameThread(f) local o = IN_GT; IN_GT = true; f(); IN_GT = o end
function IsInGameThread() return IN_GT end
GTLOOPS = {}
function LoopInGameThreadWithDelay(ms, f) GTLOOPS[#GTLOOPS + 1] = f return #GTLOOPS end
TICKMAX = 0                                   -- most crossings in one loop tick (one frame)
function tickGT(n) for _ = 1, n or 1 do MOCK_TICKS = MOCK_TICKS + 1 local c0 = COUNT
  for _, f in ipairs(GTLOOPS) do local o = IN_GT; IN_GT = true; f(); IN_GT = o end
  if COUNT - c0 > TICKMAX then TICKMAX = COUNT - c0 end end end
function LoopAsync() end
function ExecuteWithDelay() end
Key = setmetatable({}, { __index = function(_, k) return k end })
ModifierKey = { CONTROL = "C", SHIFT = "S", ALT = "A" }
function RegisterKeyBind() end
function RegisterConsoleCommandHandler(n, fn) CMD = fn end
function RegisterBeginPlayPostHook(fn) BEGINPLAY = fn end
HOOKS = {}
function RegisterHook(name, pre, post) HOOKS[name] = post return 1, 2 end
function RegisterLoadMapPreHook(fn) MAP_PRE = fn end
function RegisterLoadMapPostHook(fn) MAP_POST = fn end
