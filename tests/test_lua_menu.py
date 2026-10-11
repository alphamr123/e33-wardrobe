"""In-game menu (Scripts/menu.lua) against a mock UE4SS + UMG (needs lupa).

The mock widgets record their parent, text, visibility, colours and calls, so the test can
read the menu the way a player sees it (visible buttons with their row label / value) and
press keys or click buttons.
"""
import os
import shutil
import sys
import tempfile

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_lua_mock as base  # noqa: E402

SCRIPTS = os.path.join(HERE, '..', 'lua', 'E33Wardrobe', 'Scripts')

UMG_MOCK = r'''
CLOCK = 1000
os.time = function() return CLOCK end
function FText(s) return { _s = s } end

UMGW, CALLS, BUILT = {}, { paint = 0 }, 0
THREAD, OFFTHREAD = "load", {}
local function eng(name) if THREAD ~= "game" and THREAD ~= "load" then table.insert(OFFTHREAD, THREAD .. ":" .. name) end end
function ExecuteInGameThread(f) local o, og = THREAD, IN_GT; THREAD = "game"; IN_GT = true; f(); THREAD = o; IN_GT = og end
local PAINT = { SetText = true, SetVisibility = true, SetColorAndOpacity = true, SetBackgroundColor = true,
                SetIsEnabled = true, SetBrushColor = true, SetSize = true }
local WADDR = 500000
local WMT = {}
local function slot(parent, child)
  local s = { _parent = parent, _child = child, _calls = {} }
  return setmetatable(s, { __index = function(t, k)
    return function(self, ...) table.insert(self._calls, { k, ... }); return nil end end })
end
local function adopt(self, child) child._parent = self; table.insert(self._children, child); local s = slot(self, child); child._slot = s; return s end
local methods = {
  IsValid = function(self) return not self._dead end,
  GetAddress = function(self) return self._addr end,
  GetFName = function(self) local n = self._name; return { ToString = function() return n end } end,
  GetFullName = function(self) return self._kind .. " " .. self._name end,
  SetText = function(self, ft) if BREAK_TEXT then error("text broke") end; self._text = ft._s end,
  SetVisibility = function(self, v) self._vis = v end,
  SetIsEnabled = function(self, e) self._en = e end,
  IsHovered = function(self) CALLS.hover = (CALLS.hover or 0) + 1; return self._hover == true end,
  AddChild = adopt, AddChildToCanvas = adopt, AddChildToVerticalBox = adopt, AddChildToHorizontalBox = adopt,
  AddToViewport = function(self, z) self._inViewport = true; self._z = z end,
  RemoveFromParent = function(self) self._inViewport = false end,
  IsInViewport = function(self) return self._inViewport == true end,
  SetBackgroundColor = function(self, c) self._bg = c end,
  SetBrushColor = function(self, c) self._brush = c end,
  SetColorAndOpacity = function(self, c) self._color = c end,
}
WMT.__index = function(t, k)
  if type(k) ~= "string" or k:sub(1, 1) == "_" then return nil end
  local m = methods[k]
  if m then
    if k == "IsValid" or k == "GetAddress" then return m end
    return function(...) eng(k); if PAINT[k] then CALLS.paint = CALLS.paint + 1 end; return m(...) end
  end
  return function(self, ...) eng(k); table.insert(self._calls, { k, ... }); return nil end
end
local function widget(kind, outer, name)
  WADDR = WADDR + 1
  local w = setmetatable({ _kind = kind, _outer = outer, _children = {}, _calls = {}, _addr = WADDR,
                           _name = name and name:ToString() or (kind .. "_" .. WADDR) }, WMT)
  if kind == "TextBlock" then w.Font = { Size = 24 } end
  if kind == "UserWidget" then BUILT = BUILT + 1 end
  table.insert(UMGW, w)
  return w
end
local UMGC = {}
BROKEN = {}
for _, n in ipairs({ "UserWidget", "WidgetTree", "CanvasPanel", "Border", "VerticalBox", "HorizontalBox",
                     "SizeBox", "TextBlock", "Button" }) do
  UMGC["/Script/UMG." .. n] = { _name = n, IsValid = function() return not BROKEN[n] end }
end
VP = { X = 2560, Y = 1440, dpi = 1.0 }
UMGC["/Script/UMG.Default__WidgetLayoutLibrary"] = { IsValid = function() return true end,
  GetViewportSize = function() return { X = VP.X, Y = VP.Y } end, GetViewportScale = function() return VP.dpi end }
INPUTMODE = "game"
UMGC["/Script/UMG.Default__WidgetBlueprintLibrary"] = { IsValid = function() return true end,
  SetInputMode_GameAndUIEx = function() INPUTMODE = "gameui" end, SetInputMode_GameOnly = function() INPUTMODE = "game" end }
local baseSFO = StaticFindObject
function StaticFindObject(p) return UMGC[p] or baseSFO(p) end
function StaticConstructObject(cls, outer, name) eng("StaticConstructObject"); return widget(cls._name, outer, name) end

LOOKIGN = 0
PC = new("BP_jRPG_PlayerController_C", "/Game/Map.PersistentLevel.PC_1",
  { Player = new("LocalPlayer", "/Engine/Transient.LocalPlayer_1"), bShowMouseCursor = false },
  { SetIgnoreLookInput = function(self, b) eng("SetIgnoreLookInput"); LOOKIGN = LOOKIGN + (b and 1 or -1) end })
local baseFAO = FindAllOf
function FindAllOf(n)
  if n == "PlayerController" then return { PC } end
  if n == "UserWidget" then local o = {}; for _, w in ipairs(UMGW) do if w._kind == "UserWidget" then o[#o + 1] = w end end; return o end
  return baseFAO(n)
end

LOOPS = {}
WATCHDOGS = {}
function LoopAsync(ms, fn)
  local w = function() local o = THREAD; THREAD = "async"; local r = fn(); THREAD = o; return r end
  if ms >= 1000 then table.insert(WATCHDOGS, w) else table.insert(LOOPS, w) end   -- the 1 s heartbeat runs all game
end
-- one "step" = 6 ticks of main.lua's game-thread loop (~300 ms: debounced passes run too)
function runLoops(n) tickGT((n or 1) * 6) end
function RegisterKeyBind(k, mods, fn)
  if type(mods) == "function" then fn, mods = mods, {} end
  local id = k; for _, m in ipairs(mods) do id = m .. "+" .. id end
  KEYS[id] = function() local o = THREAD; THREAD = "key"; fn(); THREAD = o end
end
-- LoadMap hooks run on the game thread
function RegisterLoadMapPreHook(fn) LOADMAP_PRE = function() local o = THREAD; THREAD = "game"; fn(); THREAD = o end end
function RegisterLoadMapPostHook(fn) LOADMAP_POST = function() local o = THREAD; THREAD = "game"; fn(); THREAD = o end end

-- ---- reading the screen
function host() for i = #UMGW, 1, -1 do local w = UMGW[i]; if w._kind == "UserWidget" and w._inViewport and not w._dead then return w end end end
function menuShown() local h = host(); return h ~= nil and h._vis ~= 1 end
local function shownIn(w, h)
  local x = w
  while x._parent do if x._vis == 1 or x._vis == 2 then return false end; x = x._parent end
  if x._vis == 1 then return false end
  return h ~= nil and h.WidgetTree ~= nil and h.WidgetTree.RootWidget == x
end
function screen()
  local h = host(); local out = {}
  if not h or h._vis == 1 then return out end
  for _, w in ipairs(UMGW) do
    if w._kind == "Button" and shownIn(w, h) then
      local hb = w._parent; local lab, val = hb._children[1], hb._children[2]
      out[#out + 1] = { w = w, cap = w._children[1]._text, enabled = w._en ~= false, bg = w._bg,
                        label = (lab._vis ~= 1) and lab._text or nil, value = (val._vis ~= 1) and val._text or nil }
    end
  end
  return out
end
function textsShown()
  local h = host(); local out = {}
  for _, w in ipairs(UMGW) do if w._kind == "TextBlock" and w._text and shownIn(w, h) then out[#out + 1] = w._text end end
  return table.concat(out, "\n")
end
function findBtn(cap, label)
  for _, b in ipairs(screen()) do
    if b.cap == cap and (label == nil or (b.label and b.label:find(label, 1, true))) then return b end
  end
end
function click(cap, label)
  local b = findBtn(cap, label)
  if not b then return false end
  b.w._hover = true; KEYS["LEFT_MOUSE_BUTTON"](); runLoops(); b.w._hover = false
  return true
end
function key(id) KEYS[id](); runLoops() end
function rowValue(label) for _, b in ipairs(screen()) do if b.label and b.label:find(label, 1, true) then return b.value end end end
function focused()  -- the button painted with the focus colour (the one colour used once)
  local count, byBg = {}, {}
  for _, b in ipairs(screen()) do count[b.bg] = (count[b.bg] or 0) + 1; byBg[b.bg] = b end
  for bg, n in pairs(count) do if n == 1 and bg.R > 0.9 then return byBg[bg] end end
end
function sameBg(a, b) return a.bg == b.bg end
function autoSized(cap, label)
  local b = findBtn(cap, label); local c = b and lastCall(b.w._slot, 'SetSize')
  return c ~= nil and c[2].SizeRule == 0
end
function sameRow(a, b) return rowBrush(a) == rowBrush(b) end
function rowBrush(label) for _, b in ipairs(screen()) do if b.label and b.label:find(label, 1, true) then return b.w._parent._parent._brush end end end
function lastCall(w, name) for i = #w._calls, 1, -1 do if w._calls[i][1] == name then return w._calls[i] end end end
'''


def variants():
    slots = []
    base_slots = '''
    { id = "CC/Lune outfit", label = "Lune outfit", character = "Lune", variants = {
      { id = "CC/A", label = "Sleeves + boots", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" },
        ["/Game/Characters/Lune/Chic/MI_Chic"] = { "/Game/Characters/ZWOUTFITA/Chic/MI_Chic", "MI_Chic", "MaterialInstanceConstant" } } },
      { id = "CC/B", label = "Sleeveless", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" } } } } },
    { id = "CC/Sciel outfit", label = "Sciel outfit", character = "Sciel", variants = {
      { id = "CC/S", label = "Sciel sleeveless", map = {
        ["/Game/Characters/Lune/Chic/SK_Lune_Chic"] = { "/Game/Characters/ZWOUTFITB/Chic/SK_Lune_Chic", "SK_Lune_Chic", "SkeletalMesh" } } },
      { id = "CC/S2", label = "Sciel lace", map = {} } } },
    { id = "CC/Shared color", label = "Shared color", variants = {
      { id = "CC/red", label = "red", map = {} }, { id = "CC/blue", label = "blue", map = {} } } },
    { id = "CC/Long", label = "CC: Prefixed slot", variants = {
      { id = "CC/long1", label = "Non-Lace dress: Lune chic fire", map = {} } } },
    { id = "CC/Herald", label = "CC: Lune herald", character = "Lune", variants = {
      { id = "CC/H", label = "Herald", map = {
        ["/Game/Characters/Lune/Potato/SK_Lune_Potato_Skin"] = { "/Game/Characters/ZWHERALD/SK_Lune_Potato_Skin", "SK_Lune_Potato_Skin", "SkeletalMesh" } } } } },
    { id = "CC/Fix", label = "CC: _only Lune mod_fix_P", character = "Lune", variants = {
      { id = "CC/F", label = "fix", map = {
        ["/Game/BP/BP_Fix"] = { "/Game/ZWFIX/BP_Fix", "BP_Fix", "BlueprintGeneratedClass" } } } } },'''
    for i in range(1, 9):
        ch = 'Sciel' if i % 2 else 'Lune'
        vs = ', '.join(f'{{ id = "X{i}/v{k}", label = "Extra {i} v{k}", map = {{}} }}' for k in range(1, 4))
        slots.append(f'{{ id = "X/slot{i}", label = "{ch} extra {i}", character = "{ch}", variants = {{ {vs} }} }}')
    # one slot with 40 variants for paging inside the chooser (3 per row)
    vs = ', '.join(f'{{ id = "Many/v{k}", label = "Many v{k}", map = {{}} }}' for k in range(1, 41))
    slots.append(f'{{ id = "Many", label = "Many variants", variants = {{ {vs} }} }}')
    more = '''
  { mod = "Maelle - Claudia Set", slots = {
    { id = "Maelle - Claudia Set/Main", label = "Maelle - Claudia Set: Main", variants = {
      { id = "Maelle - Claudia Set/", label = "", map = {
        ["/Game/Characters/Heros/Maelle/SK_Maelle_Placeholder"] = { "/Game/ZWMAELLE01/Heros/Maelle/SK_Maelle_Placeholder", "SK_Maelle_Placeholder", "SkeletalMesh", true } } } } } } },
  { mod = "ScielBodyLight", slots = {
    { id = "ScielBodyLight/Main", label = "ScielBodyLight: Main", variants = {
      { id = "ScielBodyLight/", label = "", map = {} } } } } },'''
    return 'return { { mod = "CC", slots = {' + base_slots + ',\n'.join(slots) + '} },' + more + ' }\n'


def main():
    tmp = tempfile.mkdtemp(prefix='e33menu_')
    mod = os.path.join(tmp, 'E33Wardrobe')
    scripts = os.path.join(mod, 'Scripts')
    os.makedirs(scripts)
    for f in ('main.lua', 'menu.lua'):
        shutil.copy(os.path.join(SCRIPTS, f), scripts)
    shutil.copy(os.path.join(SCRIPTS, 'config.example.lua'), os.path.join(scripts, 'config.lua'))   # the example works as is
    open(os.path.join(scripts, 'variants.lua'), 'w').write(variants())
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(UMG_MOCK)
    body, _actor = L.execute(base.SCENARIO)
    L.execute('asset("SkeletalMesh", "/Game/Characters/ZWHERALD/SK_Lune_Potato_Skin", "SK_Lune_Potato_Skin", '
              '{ Materials = TArray({ { MaterialInterface = get("/Game/Characters/Lune/Chic/MI_Chic.MI_Chic") } }) })')
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    G = L.globals()
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    def sel():
        p = os.path.join(mod, 'selection.txt')
        out = {}
        if os.path.isfile(p):
            for line in open(p):
                k, _, v = line.rstrip('\n').partition('\t')
                if v:
                    out[k] = v
        return out

    def settings():
        p = os.path.join(mod, 'settings.txt')
        return open(p, encoding='utf-8').read() if os.path.isfile(p) else ''

    def favs():
        p = os.path.join(mod, 'favorites.txt')
        if not os.path.isfile(p):
            return []
        return [tuple(x.split('\t')) for x in open(p, encoding='utf-8').read().splitlines()]

    def fav_rows():
        return [(b.label, b.value) for b in G.screen().values() if b.cap == 'Use']

    def use_btns():
        return [b for b in G.screen().values() if b.cap == 'Use']

    def mesh():
        return L.eval('function(b) return b._mesh._path end')(body)

    def screen_text():
        return G.textsShown()

    def labels():
        return [b.label for b in G.screen().values() if b.label]

    key, click = G.key, G.click
    log = G.getlog

    check('menu.lua loaded with the mod', 'menu not available' not in log() and 'press DEL for the menu' in log(), log()[-400:])
    check('keys registered (Home, Ctrl+arrows, Ctrl+Enter, click)',
          all(k in G.KEYS for k in ('DEL', 'C+UP_ARROW', 'C+DOWN_ARROW', 'C+LEFT_ARROW', 'C+RIGHT_ARROW',
                                    'C+RETURN', 'C+PAGE_UP', 'C+PAGE_DOWN', 'LEFT_MOUSE_BUTTON')))
    check('nothing is built before the menu is opened', G.BUILT == 0)
    G.KEYS['LEFT_MOUSE_BUTTON']()
    p0 = G.CALLS.paint
    G.runLoops(3)
    check('a click while the menu is closed does nothing', G.CALLS.paint == p0 and not G.menuShown())

    # ---- open
    key('DEL')
    check('Delete opens the menu', G.menuShown() and 'menu open' in log(), log()[-300:])
    check('  cursor shown and camera look blocked', G.PC.bShowMouseCursor is True and G.LOOKIGN == 1,
          (G.PC.bShowMouseCursor, G.LOOKIGN))
    check('  widget is on the viewport at a high Z order', G.host()._z == 9000)
    tf = [w for w in G.UMGW.values() if w._kind == 'TextBlock']
    check('  text sizes set before the widget is shown', all(w.Font.Size < 24 for w in tf[1:]) and tf[0].Font.Size == 20)
    caps = [b.cap for b in G.screen().values()]
    check('tabs shown, with Peek', all(c in caps for c in ('Outfits', 'Presets', 'Settings', 'Peek', 'Close')), caps)
    check('one tab per character; the loaded one plain, the others marked "-"',
          all(c in caps for c in ('Lune', 'Maelle -', 'Sciel -', 'All')), caps)
    check('it opens on the first character on screen (Lune) and says what Lune wears',
          G.sameBg(G.findBtn('Lune'), G.findBtn('Outfits')) and 'Lune wears\nChic' in screen_text(), screen_text()[:300])
    check('slot rows: short name without the character, value "off"', G.rowValue('Outfit · CC') == 'off',
          (labels(), G.rowValue('Outfit · CC')))
    check('relocator labels shortened: mod prefix dropped from the slot name', 'Prefixed slot · CC' in labels()
          and not any(x.startswith('CC: ') for x in labels()), labels())
    check('the technical fix slot is hidden', not any('mod fix' in x for x in labels()), labels())
    check('Lune tab: 9 slots -> 8 rows and page 1/2', 'Page 1/2' in screen_text() and len(
        [b for b in G.screen().values() if b.cap == 'Choose']) == 6, screen_text())
    check('mouse users see no key help and no focus ring', 'Ctrl+Up' not in screen_text() and G.focused() is None,
          screen_text()[-300:])

    # ---- idle tick does not touch UMG
    before = G.CALLS.paint
    G.runLoops()
    check('an idle tick sends nothing to UMG (cached text/colour/visibility)', G.CALLS.paint == before,
          G.CALLS.paint - before)

    # ---- keyboard
    key('C+DOWN_ARROW')
    f = G.focused()
    check('the first key only shows the focus (on the Lune tab) and the key help',
          f is not None and f.cap == 'Lune' and 'Ctrl+Up/Ctrl+Down row' in screen_text(), f and (f.cap, f.label))
    key('C+DOWN_ARROW')      # the "Lune wears" row (its Favorites button)
    f = G.focused()
    check('  the next row down is "Lune wears" with its Favorites button', f is not None and f.cap == 'Favorites',
          f and (f.cap, f.label))
    key('C+DOWN_ARROW')      # the Outfit row
    key('C+RIGHT_ARROW')     # '>' button
    f = G.focused()
    check('keyboard focus is painted on the Outfit ">" button', f is not None and f.cap == '>' and 'Outfit · CC' in (f.label or ''),
          f and (f.cap, f.label))
    key('C+RETURN')
    check('Ctrl+Enter presses it: Lune outfit = variant 1', sel().get('CC/Lune outfit') == 'CC/A', sel())
    check('  the swap reached the character', mesh().startswith('/Game/Characters/ZWOUTFITA/'), mesh())
    check('  row value: the distinct words of the variant', G.rowValue('Outfit · CC') == 'Sleeves · boots', G.rowValue('Outfit · CC'))
    check('  status names the character and what is on screen', 'Lune · Outfit · CC: Sleeves · boots' in screen_text()
          and '2/2 pieces on screen' in screen_text(), screen_text()[:200])
    key('C+LEFT_ARROW')      # '<'
    key('C+RETURN')
    check('Ctrl+Left then Enter steps back to off', 'CC/Lune outfit' not in sel(), sel())
    click('On', 'Prefixed slot')
    check('  a pick that shows nothing: the value says so', G.rowValue('Prefixed slot') == 'on · not visible',
          G.rowValue('Prefixed slot'))
    ex = G.findBtn('OK')
    check('  an explanation row appears under it, in words', ex is not None and "Lune's current outfit (Chic) doesn't use"
          in (ex.label or '') and 'nothing on screen changed' in screen_text(), (ex and ex.label, screen_text()[:300]))
    click('OK')
    check('  OK dismisses it', G.findBtn('OK') is None)
    click('Off', 'Prefixed slot')
    click('Off', 'Prefixed slot')
    check('a disabled button says why when clicked', "Off: already off (the game's own)" in screen_text(), screen_text()[:200])

    # ---- a replacer for an outfit Lune doesn't wear: Auto Wear, then Wear by hand
    click('On', 'Herald')
    G.runLoops()                                     # the pass, then Auto Wear's own pass (~0.4 s in game)
    check('Auto Wear: Herald (made for Potato bag) is worn in place of Chic by itself',
          mesh().startswith('/Game/Characters/ZWHERALD/') and 'wear = CC/Herald' in settings()
          and 'worn in place of Chic (Auto Wear)' in screen_text(), (mesh(), screen_text()[:300]))
    check('  one-option mod: On / Off instead of < > Choose', G.findBtn('<', 'Herald') is None
          and G.rowValue('Herald') == 'on · worn', G.rowValue('Herald'))
    check('  "Lune wears" says the mod replaces Chic (no layering); the row offers Unwear',
          'Herald · CC (in place of Chic)' in screen_text() and G.findBtn('Unwear', 'Herald') is not None,
          screen_text()[:400])
    click('Unwear', 'Herald')
    check('Unwear: back to Chic, and Auto Wear leaves it so', mesh().startswith('/Game/Characters/Lune/')
          and 'wear = \n' in settings() + '\n' and G.rowValue('Herald') == 'on · made for Potato bag',
          (mesh(), settings(), G.rowValue('Herald')))
    w = G.findBtn('Wear', 'Herald')
    check('  Wear is offered on the row', w is not None, [b.cap for b in G.screen().values()])
    check('  and no Wear button where it would do nothing (Outfit, shown already; no-mesh slots)',
          G.findBtn('Wear', 'Outfit · CC') is None and G.findBtn('Wear', 'Prefixed slot') is None)
    click('Wear', 'Herald')
    check('Wear by hand puts Herald on in place of Chic', mesh().startswith('/Game/Characters/ZWHERALD/')
          and 'wear = CC/Herald' in settings(), (mesh(), settings()))
    click('Unwear', 'Herald')
    click('Off', 'Herald')
    check('buttons next to text are as wide as their captions (never cut)', G.autoSized('Choose', 'Outfit · CC')
          and not G.autoSized('Outfits'))

    # ---- chooser
    click('Choose', 'Outfit · CC')
    check('Choose lists the variants as named buttons', G.findBtn('Sleeves · boots') is not None
          and G.findBtn('Sleeveless') is not None and 'Lune · Outfit · CC' in screen_text(), screen_text()[:300])
    click('Sleeveless')
    check('  clicking a name uses it', sel().get('CC/Lune outfit') == 'CC/B'
          and not G.sameBg(G.findBtn('Sleeveless'), G.findBtn('Sleeves · boots')),
          sel())
    check("  Off (game's own) is there", G.findBtn("Off (game's own)").enabled)
    check('  no Wear for a pick that already shows on what Lune wears',
          not any(b.cap.startswith('Wear') for b in G.screen().values()), [b.cap for b in G.screen().values()])
    click('Back')
    check('Undo goes back one step and says what it undid', click('Undo') and 'CC/Lune outfit' not in sel()
          and 'undid: Outfit · CC back to off' in screen_text(), (sel(), screen_text()[:200]))
    click('Page >')
    click('Choose', 'Many variants')
    check('40 variants: grouped by 3, paged', G.findBtn('v1') is not None and G.findBtn('v3') is not None
          and G.findBtn('Page >') is not None and G.findBtn('v40') is None, [b.cap for b in G.screen().values()])
    click('Page >')
    check('  page 2 shows the rest', G.findBtn('v40') is not None)
    click('v38')
    check('  a name on page 2', sel().get('Many') == 'Many/v38', sel())
    click('Random')
    check('Random picks a different variant', sel().get('Many') not in (None, 'Many/v38'), sel())

    # ---- slideshow (runs on with the menu closed)
    click('Slides')
    s0 = sel().get('Many')
    G.CLOCK += 5
    G.runLoops()
    s1 = sel().get('Many')
    check('slideshow steps to the next variant after the interval', s1 != s0 and s1 is not None, (s0, s1))
    key('DEL')
    check('menu closes', not G.menuShown())
    G.CLOCK += 5
    G.runLoops()
    check('  and keeps stepping while closed', sel().get('Many') != s1, (s1, sel().get('Many')))
    key('DEL')
    check('reopening reuses the same widgets', G.BUILT == 1 and G.menuShown(), G.BUILT)
    click('Stop')
    key('DEL')
    G.runLoops(2)
    s_stop = sel().get('Many')
    G.CLOCK += 10
    G.runLoops(3)
    check('stopping the slideshow: nothing changes any more', sel().get('Many') == s_stop, (s_stop, sel().get('Many')))
    key('DEL')
    click('Back')

    # ---- character tabs, lock, randomize, all off
    click('Maelle -')
    check('Maelle tab (a mod named after Maelle): not in this area', 'Maelle wears\nnot in this area' in screen_text()
          and 'tab = Maelle' in settings(), screen_text()[:300])
    shown = labels()
    check('  the one-option mod under its own name, not "Main"', 'Claudia Set' in shown
          and 'Main' not in shown and not any('Outfit' in x for x in shown), shown)
    click('On', 'Claudia Set')
    check('  On: saved; the value says what it is made for', sel().get('Maelle - Claudia Set/Main') == 'Maelle - Claudia Set/'
          and G.rowValue('Claudia Set') == 'on · made for base body', G.rowValue('Claudia Set'))
    check("  and the explanation: Maelle isn't loaded here", "Maelle isn't loaded here" in (G.findBtn('OK').label or ''))
    click('Off', 'Claudia Set')
    click('Sciel -')
    shown = ' '.join(labels())
    check('Sciel tab: Sciel + shared slots only', 'Outfit · CC' in shown and 'Shared color' in shown
          and 'Herald' not in shown, shown)
    click('Page >')
    check('  a CamelCase mod name (ScielBodyLight) is sorted to Sciel', 'Body Light' in labels(), labels())
    click('< Page')
    click('Choose', 'Shared color')
    check('no Wear button for a slot tied to no character', not any(b.cap.startswith('Wear') for b in G.screen().values()))
    click('Lock')
    check('Lock marks the slot', G.findBtn('Unlock') is not None and 'CC/Shared color' in settings(), settings())
    click('Back')
    check('  locked slot shows [lock]', any('[lock]' in x for x in labels()), labels())
    before = sel()
    click('Randomize')
    after = sel()
    check('Randomize (Sciel): Sciel slots get a variant, Lune slots and the locked slot unchanged',
          after.get('CC/Sciel outfit') in ('CC/S', 'CC/S2') and after.get('CC/Lune outfit') == before.get('CC/Lune outfit')
          and after.get('CC/Shared color') == before.get('CC/Shared color'), (before, after))
    click('All off')
    after2 = sel()
    check('All off (Sciel): Sciel slots cleared, Lune kept', 'CC/Sciel outfit' not in after2
          and after2.get('CC/Lune outfit') == before.get('CC/Lune outfit'), after2)
    click('All')
    check('All tab: every slot, the character in front', 'Lune · Outfit · CC' in labels() and 'tab = All' in settings(),
          labels())
    click('Lune')
    click('>', 'Outfit · CC')
    check('  the picked row flashes, then settles', not G.sameRow('Outfit · CC', 'Prefixed slot'))
    G.runLoops(4)
    check('  ', G.sameRow('Outfit · CC', 'Prefixed slot'))
    click('Off', 'Outfit · CC')

    # ---- clean
    click('Clean')
    check('Clean is a switch: on (nothing to blank in this mock, and it says so), saved',
          'Clean is on; no blood / dirt masks' in screen_text() and G.findBtn('Clean: on') is not None
          and 'clean = true' in settings(), screen_text()[:200])
    click('Clean: on')
    check('  and off again', 'blood and dirt back as the game shows them' in screen_text() and G.findBtn('Clean') is not None
          and 'clean = false' in settings(), screen_text()[:200])

    # ---- peek
    click('Peek')
    check('Peek hides the menu and gives the camera back', not G.menuShown() and G.LOOKIGN == 0
          and G.PC.bShowMouseCursor is False, (G.menuShown(), G.LOOKIGN))
    G.runLoops(11)                                   # 3 s
    check('  and it comes back by itself', G.menuShown() and G.LOOKIGN == 1 and G.PC.bShowMouseCursor is True,
          (G.menuShown(), G.LOOKIGN))

    # ---- presets
    click('Presets')
    check('presets view lists 8 presets', len({x for x in labels() if x.startswith('Preset ')}) == 8, labels())
    click('Store A')
    a_sel = sel()
    click('Outfits')
    click('>', 'Outfit · CC')
    b_sel = sel()
    click('Presets')
    click('Store B')
    click('Swap')
    check('A/B: Swap shows look A', sel() == a_sel, (sel(), a_sel))
    click('Swap')
    check('  and look B again', sel() == b_sel, (sel(), b_sel))
    click('Save', 'Preset 3')
    saved = sel()
    check('Save writes presets.txt and a summary by character', os.path.isfile(os.path.join(mod, 'presets.txt'))
          and (G.rowValue('Preset 3') or '').startswith('Lune: '), G.rowValue('Preset 3'))
    click('All off, everyone')
    check('All off, everyone: clears every unlocked slot', set(sel()) <= {'CC/Shared color'}, sel())
    click('Load', 'Preset 3')
    check('Load restores the preset', sel() == saved, (sel(), saved))
    check('empty preset: Load disabled', not G.findBtn('Load', 'Preset 5').enabled)
    click('Clear', 'Preset 3')
    check('Clear empties it', G.rowValue('Preset 3') == 'empty')
    check('a disabled Load says why', click('Load', 'Preset 5') and 'Load: this preset is empty' in screen_text())

    # ---- favorites: saved looks per character
    click('Outfits')
    click('Lune')
    check('the "Lune wears" row has Favorites; the bottom row keeps 5 buttons',
          G.findBtn('Favorites', 'Lune wears') is not None and G.findBtn('Fix look') is not None
          and len([b for b in G.screen().values() if b.cap in ('Undo', 'All off', 'Randomize', 'Clean: on', 'Clean', 'Fix look', 'Favorites')
                   and b.label is None]) == 5)
    click('Favorites', 'Lune wears')
    check('  it opens Lune\'s favorites, empty at first, with Save look',
          'Lune favorites' in screen_text() and 'No favorites yet' in screen_text() and G.findBtn('Save look') is not None,
          screen_text()[:300])
    click('Back')
    click('Choose', 'Outfit · CC')
    click('Sleeveless')
    click('Back')
    click('On', 'Herald')
    click('Favorites', 'Lune wears')
    click('Save look')
    f1 = favs()
    check('Save look stores every pick of Lune\'s slots, one-option mods included (favorites.txt)',
          len(f1) == 1 and f1[0][0] == 'Lune' and f1[0][2:] == ('CC/Herald', 'CC/H', 'CC/Lune outfit', 'CC/B'), f1)
    check('  the list shows it, named by what is on, and marks it as on now',
          len(use_btns()) == 1 and use_btns()[0].label.startswith('1.') and 'Herald' in use_btns()[0].label
          and 'Sleeveless' in use_btns()[0].label, [b.label for b in use_btns()])
    click('Save look')
    check('  saving the same look again says so instead of adding it', len(favs()) == 1
          and 'already favorite 1' in screen_text(), screen_text()[:200])
    click('Back')
    click('Off', 'Herald')
    click('Choose', 'Outfit · CC')
    click('Sleeves · boots')
    click('Back')
    click('Favorites', 'Lune wears')
    click('Save look')
    u = use_btns()
    check('a second look: two rows, only the second highlighted as on', len(u) == 2 and not G.sameBg(u[0], u[1])
          and u[1].label.startswith('2.'), [b.label for b in u])
    click('Use', '1.')
    check('Use puts the whole look back (Herald on again, Sleeveless)',
          sel().get('CC/Herald') == 'CC/H' and sel().get('CC/Lune outfit') == 'CC/B', sel())
    click('Up', '2.')
    check('Up moves a look up, on screen and in favorites.txt', favs()[0][2:4] == ('CC/Lune outfit', 'CC/A')
          and use_btns()[0].label.startswith('1.') and 'Sleeves' in use_btns()[0].label, (favs(), [b.label for b in use_btns()]))
    check('  the first cannot go up, the last cannot go down',
          not G.findBtn('Up', '1.').enabled and not G.findBtn('Down', '2.').enabled)
    click('Remove', '1.')
    check('Remove takes it off the list and out of favorites.txt', len(favs()) == 1 and len(use_btns()) == 1, favs())
    click('Back')
    click('Sciel -')
    click('Favorites', 'Sciel wears')
    check("another character's list is its own", 'No favorites yet' in screen_text() and not use_btns(), screen_text()[:300])
    click('Back')
    click('All')
    check('  no Favorites on the All tab', G.findBtn('Favorites') is None)
    click('Lune')
    with open(os.path.join(mod, 'favorites.txt'), 'a', encoding='utf-8') as f:
        f.write('Lune\tGone look\tGone/slot\tGone/v\n')
        for k in range(1, 13):
            f.write(f'Sciel\tLook {k}\tX/slot{2 * (k % 4) + 1}\tX{2 * (k % 4) + 1}/v{1 + k % 3}\n')
    click('Settings')
    click('Reload')
    check('favorites.txt survives a reload; a look of mods no longer installed is dropped',
          len(favs()) == 13 and not any(f[1] == 'Gone look' for f in favs()), favs())
    click('Outfits')
    click('Sciel -')
    click('Favorites', 'Sciel wears')
    check('a long list is paged', len(use_btns()) == 11 and 'Page 1/2' in screen_text(), screen_text()[:300])
    click('Page >')
    check('  page 2 shows the rest', len(use_btns()) == 1, [b.label for b in use_btns()])
    click('Back')
    click('Lune')
    click('Off', 'Herald')                       # leave Lune as the later checks expect
    click('Off', 'Outfit · CC')

    # ---- settings
    click('Settings')
    check('legacy Ctrl+F5/F6 cycling is off by default and not even bound (other mods keep those keys)',
          'C+F6' not in G.KEYS and 'C+F5' not in G.KEYS, list(G.KEYS.keys()))
    check('the default menu key is Delete (UE4SS\'s BPModLoaderMod also uses Insert)',
          'DEL' in G.KEYS and 'INS' not in G.KEYS, list(G.KEYS.keys()))
    check('auto report is off by default', 'auto_report = false' in settings(), settings())
    click('Auto report', 'Record session')
    check('  and can be switched on from Settings', 'auto_report = true' in settings(), settings())
    click('Auto report', 'Record session')

    # character scoping: a Sciel-only variant reaches the Lune actor only with scoping off
    L.globals().CMDS['wardrobe'](None, L.table_from(['1', 'off']))
    L.globals().CMDS['wardrobe'](None, L.table_from(['2', '1']))
    check('scoping ON: Sciel-only slot leaves Lune vanilla', mesh() == '/Game/Characters/Lune/Chic/SK_Lune_Chic.SK_Lune_Chic', mesh())
    click('Switch', "Keep a mod's groups matched")
    check('group matching can be switched off from Settings', 'match_groups = false' in settings(), settings())
    click('Switch', "Keep a mod's groups matched")
    click('Switch', 'Character scoping')
    check('scoping OFF: saved and re-applied - the Sciel slot now changes Lune too',
          'scoping = false' in settings() and mesh().startswith('/Game/Characters/ZWOUTFITB/'), (settings(), mesh()))
    click('Switch', 'Character scoping')

    frame = [w for w in G.UMGW.values() if w._kind == 'Border'][0]
    click('+', 'Menu side / scale')
    sc = G.lastCall(frame, 'SetRenderScale')
    check('scale + saves 110 and scales the menu', 'scale = 110' in settings() and sc and abs(sc[2].X - 1.1) < 1e-6,
          (settings(), sc and sc[2].X))
    G.VP.X, G.VP.Y = 1024, 576
    click('+', 'Menu side / scale')
    sc = G.lastCall(frame, 'SetRenderScale')
    check('  shrinks to fit a small screen', sc and sc[2].X < 1.0, sc and sc[2].X)
    G.VP.dpi = 2.0
    G.VP.X, G.VP.Y = 2048, 1152                  # 4K-ish pixels at 200% = 1024x576 units
    for _ in range(25):
        G.runLoops()
    sc = G.lastCall(frame, 'SetRenderScale')
    check('  DPI scale is taken into account (re-checked every ~2 s)', sc and sc[2].X < 1.0, sc and sc[2].X)
    G.VP.dpi = 1.0
    G.VP.X, G.VP.Y = 2560, 1440
    G.VP.X, G.VP.Y = 2560, 1440
    click('Side', 'Menu side / scale')
    anchors = G.lastCall(frame._slot, 'SetAnchors')
    check('menu side: left anchors the panel left', 'side = left' in settings() and anchors and anchors[2].Minimum.X == 0,
          anchors and anchors[2].Minimum.X)
    click('Cursor', 'Mouse cursor')
    check('cursor OFF restores the game cursor at once', G.PC.bShowMouseCursor is False)
    click('Cursor', 'Mouse cursor')
    check('cursor ON shows it again', G.PC.bShowMouseCursor is True)
    click('Switch', 'UI input mode')
    check('experimental UI input mode applies while open', G.INPUTMODE == 'gameui')
    check('the diagnostics row shows how many characters the last pass found',
          any(x.startswith('Characters found last pass: ') for x in labels()), labels())
    check('Settings shows the key help', 'Ctrl+Up/Ctrl+Down row' in screen_text())
    click('Switch', 'Show technical slots')
    click('Outfits')
    check('technical slots can be shown from Settings', any('mod fix' in x for x in labels()), labels())
    click('Settings')
    click('Switch', 'Show technical slots')
    click('Dump')
    check('Dump writes dump.txt', os.path.isfile(os.path.join(mod, 'dump.txt')))
    click('Peek +', 'Slideshow / Peek')
    check('peek time steps by 1 s', 'peek_s = 4' in settings(), settings())
    click('Defaults')
    st_ = settings()
    check('Defaults resets settings but keeps locks', 'scale = 100' in st_ and 'side = right' in st_
          and 'ui_input = false' in st_ and 'CC/Shared color' in st_, st_)
    check('  and takes back the UI input mode', G.INPUTMODE == 'game')
    for _ in range(10):
        click('Slides -', 'Slideshow / Peek')
    b = G.findBtn('Slides -', 'Slideshow / Peek')
    check('a stepper stops at its minimum and its "-" button is disabled', 'slideshow_s = 1' in settings() and not b.enabled,
          settings())

    # ---- close
    click('Close')
    check('Close hides the menu and restores cursor / look', not G.menuShown() and G.PC.bShowMouseCursor is False
          and G.LOOKIGN == 0, (G.menuShown(), G.PC.bShowMouseCursor, G.LOOKIGN))
    G.runLoops(2)
    p0 = G.CALLS.paint
    G.runLoops(3)
    check('  a closed menu sends nothing to UMG', G.CALLS.paint == p0)

    # ---- map change: hooks drop the widgets, next open builds fresh
    key('DEL')
    G.LOADMAP_PRE()
    check('LoadMap pre-hook closes, restores input and removes the widget', not G.menuShown() and G.LOOKIGN == 0
          and G.PC.bShowMouseCursor is False)
    key('DEL')
    check('  keys are ignored while the map loads', not G.menuShown())
    G.LOADMAP_POST()
    key('DEL')
    check('  after the load Home builds a new menu', G.menuShown() and G.BUILT == 2, G.BUILT)
    # without hooks: the widget dies under us
    G.host()._dead = True
    G.runLoops()
    check('dead widget noticed: menu closed, cursor and camera given back', 'menu closed (level changed)' in log()
          and G.PC.bShowMouseCursor is False and G.LOOKIGN == 0, (G.PC.bShowMouseCursor, G.LOOKIGN))
    key('DEL')
    check('  and rebuilt on the next Home', G.menuShown() and G.BUILT == 3, G.BUILT)
    key('DEL')

    # ---- console
    G.CMDS['wardrobe'](None, L.table_from(['menu']))
    G.runLoops()
    check('console "wardrobe menu" toggles it', G.menuShown())
    G.CMDS['wardrobe'](None, L.table_from(['menu']))
    G.runLoops()

    # ---- build failure is contained
    G.LOADMAP_PRE()
    G.LOADMAP_POST()
    G.BROKEN.Button = True
    key('DEL')
    check('a failed build is logged, nothing else changes', 'menu could not be built' in log() and not G.menuShown()
          and G.PC.bShowMouseCursor is False and G.LOOKIGN == 0, log()[-300:])
    G.BROKEN.Button = False
    key('DEL')
    check('  and works once UMG is available', G.menuShown())
    key('DEL')

    off = list(G.OFFTHREAD.values())
    check('every widget / controller call ran on the game thread', not off, off[:10])
    lv = open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read()
    check('live log records menu clicks with their row and button', "menu click: [outfits] Outfit · CC" in lv
          and "-> 'Choose'" in lv and "menu click: [settings] Character scoping (ON) -> 'Switch'" in lv,
          [l for l in lv.splitlines() if 'menu click' in l][:5])
    check('  keyboard presses and the keys themselves', "menu key: [outfits]" in lv and 'key CONTROL+DOWN_ARROW' in lv
          and 'key DEL' in lv)
    check('  what the menu then showed', 'menu shows: Lune · Outfit · CC: Sleeves · boots' in lv)
    key('DEL')
    G.KEYS['LEFT_MOUSE_BUTTON']()                      # nothing hovered
    G.runLoops()
    check('  a click beside the buttons is recorded, with where it landed', 'menu click: outside the menu' in
          open(os.path.join(mod, 'live_log.txt'), encoding='utf-8').read())
    click('Settings')
    check('Settings has Record session (on) and a Report button', G.rowValue('Record session') == 'ON / OFF'
          and G.findBtn('Report') is not None, G.rowValue('Record session'))
    click('Report')
    check('  Report writes report.txt', os.path.isfile(os.path.join(mod, 'report.txt')))
    click('Close')
    errors = [l for l in log().split('\n') if ('failed' in l or 'menu error' in l) and 'could not be built' not in l]
    check('no action errors logged', not errors, errors)

    # ---- an error while drawing closes the menu once instead of every tick
    key('DEL')
    G.BREAK_TEXT = True
    click('Presets')
    G.runLoops(5)
    n = log().count('menu closed after an error while drawing it')
    check('a drawing error closes the menu, gives input back and is logged once',
          n == 1 and not G.menuShown() and G.LOOKIGN == 0 and G.PC.bShowMouseCursor is False, (n, log()[-300:]))
    G.BREAK_TEXT = False
    key('DEL')
    check('  the next Delete builds it again', G.menuShown(), log()[-200:])
    check('  on the Outfits tab: a view that failed to draw is not opened again', G.findBtn('Fix look') is not None)
    key('DEL')

    # every place that draws contains its own error: closed once, nothing uncaught, input back
    L.execute('REAL_LEN = utf8.len')

    def brk(on):
        L.execute('utf8.len = ' + ('function() error("cut broke") end' if on else 'REAL_LEN'))

    def site(name, provoke):
        u0, c0 = log().count('] error: '), log().count('menu closed after an error while drawing it')
        provoke()
        G.runLoops(3)
        brk(False)
        res = (log().count('menu closed after an error while drawing it') - c0, log().count('] error: ') - u0,
               G.menuShown(), G.LOOKIGN)
        check(f'  a drawing error when {name}: closed once, nothing uncaught, input back', res == (1, 0, False, 0), res)
        key('DEL')
        check(f'    and the menu opens again', G.menuShown(), log()[-200:])

    def p_open():
        brk(True)
        key('DEL')

    def p_click():
        brk(True)
        click('Settings')

    def p_key():
        click('Outfits')
        brk(True)
        key('C+DOWN_ARROW')

    site('opening', p_open)
    site('clicking', p_click)
    site('pressing the first key', p_key)
    site('ticking', lambda: brk(True))
    key('DEL')

    # ---- favorites of a slot that is now split per character ("<id>@<character>") are carried over
    costume = '''
  { mod = "Costume", slots = {
    { id = "K/main", label = "Costume: Main", variants = {
      { id = "K/a", label = "Main", map = {
        ["/Game/Characters/Maelle/Body/SK_Maelle_Placeholder"] = { "/Game/Characters/ZWMAEL/Body/SK_Maelle_Placeholder", "SK_Maelle_Placeholder", "SkeletalMesh" },
        ["/Game/Characters/Lune/Body/SK_Lune_Placeholder"] = { "/Game/Characters/ZWLIGHT/Body/SK_Lune_Placeholder", "SK_Lune_Placeholder", "SkeletalMesh" } } } } } } },'''
    v = variants()
    open(os.path.join(scripts, 'variants.lua'), 'w').write(v[:v.rstrip().rfind('}')] + costume + ' }\n')
    open(os.path.join(mod, 'favorites.txt'), 'w').write('Lune\tCostume\tK/main\tK/a\nSciel\tCostume\tK/main\tK/a\n')
    key('C+F8')
    check('a look saved before a slot was split per character moves to that character\'s slot (others dropped)',
          favs() == [('Lune', 'Costume', 'K/main@Lune', 'K/a@Lune')], favs())
    shutil.rmtree(tmp, ignore_errors=True)   # Windows: the Lua state still holds live_log.txt open
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
