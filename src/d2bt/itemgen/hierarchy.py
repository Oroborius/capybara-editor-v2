"""Stat hierarchy of vanilla LoD 1.14d: source layers, table columns, properties, stats, edge cases.

Static knowledge lives in LAYERS, TABLES, EDGE_CASES and DERIVED (each entry cites D2MOO file:line or
the data column); everything keyed by game data (property codes, stat rows, table headers, which
stats a table can reach) is computed from the stock tables, so the export cannot silently miss a row.
"""

import fnmatch
import re

from . import statvocab as sv

MODS = 'D2Common/src/Items/ItemMods.cpp'
ITEMS = 'D2Common/src/Items/Items.cpp'
GITEMS = 'D2Game/src/ITEMS/'
TBLS = 'D2Common/include/DataTbls/ItemsTbls.h'
SCHEMA = 1

LAYERS = [
    {'order': 1, 'id': 'base', 'tables': ['weapons', 'armor', 'misc', 'itemtypes'],
     'writes': ['mindamage/maxdamage', 'secondary_mindamage/maxdamage', 'item_throw_mindamage/maxdamage',
                'armorclass', 'maxdurability/durability', 'quantity', 'sockets (item header)'],
     'how': 'Base damage, defense and durability are rolled into the item own stat list when the item is '
            'created; ITEMS_SetDefenseOrDamage raises max to the base row max when a percent stat is added. '
            'Requirements are not stats: reqstr/reqdex come from the row, required level from '
            'ITEMS_GetRequiredLevel. The automagic prefix is the base `auto prefix` group.',
     'source': [f'{ITEMS}:6246 ITEMS_SetDefenseOrDamage', f'{ITEMS}:1286 ITEMS_GetRequiredLevel',
                f'{ITEMS}:3036 ITEMS_GetMaxSockets', 'weapons/armor/misc: mindam maxdam minac maxac durability']},
    {'order': 2, 'id': 'quality', 'tables': ['qualityitems', 'lowqualityitems', 'magicprefix', 'magicsuffix',
                                              'automagic', 'rareprefix', 'raresuffix', 'uniqueitems', 'setitems',
                                              'runes'],
     'writes': ['own stat list (mode AFFIX / GRADE / UNIQUE / SET / RUNEWORD)'],
     'how': 'Quality picks which table rows contribute: low quality scales base values only (no stats); '
            'superior adds the qualityitems row (<=2 props, PROPMODE_GRADE); magic = <=1 prefix + <=1 '
            'suffix + automagic (3 props each, PROPMODE_AFFIX); rare/crafted = up to 3+3 magic affixes (names '
            'from rareprefix/raresuffix carry no stats); unique = 12 props of its row; set = 9 always-on '
            'props of its row; runeword = 7 T1 props of the runes row, a separate list.',
     'source': [f'{MODS}:2360 ITEMMODS_AssignProperty (nProperties 3/2, 12 unique, 9+10 set)',
                f'{MODS}:2592 ITEMMODS_UpdateRuneword', 'D2Game/src/ITEMS/ItemsMagic.cpp:969,1033']},
    {'order': 3, 'id': 'save_lists', 'tables': [],
     'writes': ['own list', 'set lists (one per mask bit)', 'runeword list', 'socketed children lists'],
     'how': 'v96 save: the item own stat list; for set items a 5-bit mask then one stat list per set bit '
            '(the partial-bonus pairs aprop1a/b..5a/b, one list per bonus tier); for runewords a second '
            'list; then each socketed child item with its own lists (gems/runes carry their already '
            'resolved weapon/helm/shield mods).',
     'source': [f'{ITEMS}:5744 mask read (5 bits)', f'{ITEMS}:5769 per-bit set list', f'{ITEMS}:7421 mask write',
                f'{MODS}:2592 runeword list']},
    {'order': 4, 'id': 'summed', 'tables': ['sets'],
     'writes': ['character stat list'],
     'how': 'Equipped: the own list, always-on set props and the runeword list are summed. Socketed children '
            'contribute their own lists when the parent is equipped (ITEMS_GetBonusStatFromSockets reads '
            'them back for requirement checks). Set partial lists are STATLIST_MAGIC|STATLIST_SET lists tied to '
            'STATE_ITEMSET1..5: `add func` 0 always on, 1 = tier toggled by the worn-item mask, 2 = tier '
            'count from gnSetMaskToBonusMappingTable. Full-set bonuses (sets.txt FCode) and the 2..5 item '
            'bonuses (PCode) go onto the character (the unit), not the item, via states; a set stat list '
            'without its state is skipped (D2StatList.cpp STATLIST_SET checks).',
     'source': [f'{ITEMS}:4604 ITEMS_GetSetItemsMask (equipped items of the same set)',
                f'{ITEMS}:7615 sub_6FDA4380 (toggle tiers)', f'{ITEMS}:7686 sub_6FDA4490 (set state lists)',
                f'{ITEMS}:7763 ITEMS_UpdateSets', f'{MODS}:2623 ITEMMODS_UpdateFullSetBoni',
                'D2Common/src/D2StatList.cpp:726,767,821,1118 STATLIST_SET handling']},
]

# column role specs: (glob over lower-cased header, role, ignored?)
_AFFIX = [
    ('name', 'string key of the affix text (no stats)', False),
    ('version', 'format gate; expansion format needs >= 100 (ItemsMagic.cpp:134)', False),
    ('spawnable', 'ordinary-roll eligibility gate; automagic ignores it', False),
    ('rare', 'rare/crafted eligibility gate', False),
    ('level', 'affix level: lower bound against effective ilvl', False),
    ('maxlevel', 'inclusive upper level bound when nonzero', False),
    ('levelreq', 'required-level contribution (ITEMS_GetRequiredLevel, max over affixes)', False),
    ('classlevelreq', 'required level used instead of levelreq for the owner class', False),
    ('classspecific', 'class restriction checked against ItemTypes.Class', False),
    ('class', 'class used with classlevelreq / classspecific', False),
    ('frequency', 'selection weight (x level for magic-lvl bases)', False),
    ('group', 'exclusion group: no two affixes of one group on one item', False),
    ('mod?code', 'properties.txt code: which stats the slot writes', False),
    ('mod?param', 'property par (layer / skill / class / monster / state)', False),
    ('mod?min', 'property min (value, chance, charges... per func)', False),
    ('mod?max', 'property max (value, skill level... per func)', False),
    ('itype?', 'allowed item types (Equiv closure)', False),
    ('etype?', 'vetoed item types (Equiv closure)', False),
    ('transformcolor', 'palette change only', True),
    ('transform', 'palette change only', True),
    ('divide', 'price formula only (ITEMS_CalculateTransactionCost)', True),
    ('multiply', 'price formula only', True),
    ('add', 'price formula only', True),
]
TABLES = {
    'weapons': {'cite': f'{TBLS} D2ItemsTxt', 'feeds': 'base layer', 'roles': [
        ('mindam', 'one-hand base minimum -> stat mindamage (21)', False),
        ('maxdam', 'one-hand base maximum -> stat maxdamage (22)', False),
        ('2handmindam', 'two-hand minimum -> secondary_mindamage (23)', False),
        ('2handmaxdam', 'two-hand maximum -> secondary_maxdamage (24)', False),
        ('minmisdam', 'throw minimum -> item_throw_mindamage (159)', False),
        ('maxmisdam', 'throw maximum -> item_throw_maxdamage (160)', False),
        ('durability', 'base durability -> maxdurability / durability (halved roll at creation)', False),
        ('nodurability', 'no durability stats', False),
        ('reqstr', 'strength requirement (not a stat)', False), ('reqdex', 'dexterity requirement (not a stat)', False),
        ('level', 'qlvl: ambient filter and quality delta', False), ('levelreq', 'base required level', False),
        ('gemsockets', 'physical socket cap', False), ('gemapplytype', 'rune/gem column set: 0 weapon, 1 armor, 2 shield', False),
        ('auto prefix', 'automagic group forced on the item', False), ('magic lvl', 'magic level bonus for affix selection', False),
        ('stackable', 'quantity stat', False), ('minstack', 'quantity roll', False), ('maxstack', 'quantity roll', False),
        ('spawnstack', 'quantity roll', False), ('type', 'primary item type', False), ('type2', 'secondary item type', False),
        ('code', 'base code', False), ('rarity', 'drop rarity', False), ('spawnable', 'drop eligibility', False),
        ('normcode', 'normal/exceptional/elite family (cube upgrade)', False), ('ubercode', 'exceptional code', False),
        ('ultracode', 'elite code', False), ('quest', 'quest base', False), ('version', 'format gate', False),
        ('rangeadder', 'attack range (not a stat)', True), ('speed', 'base speed (not a saved stat)', True),
        ('strbonus', 'damage bonus scaling (not saved)', True), ('dexbonus', 'damage bonus scaling (not saved)', True),
        ('*magiclvl', 'vendor magic-level tuning (not stats)', True), ('*min', 'vendor stock tuning', True),
        ('*max', 'vendor stock tuning', True), ('*magicmin', 'vendor tuning', True), ('*magicmax', 'vendor tuning', True),
        ('*eol', 'terminator', True),
    ]},
    'armor': {'cite': f'{TBLS} D2ItemsTxt', 'feeds': 'base layer', 'roles': [
        ('minac', 'base defense minimum -> armorclass (31) roll', False),
        ('maxac', 'base defense maximum -> armorclass roll; also the +1 cap in ITEMS_SetDefenseOrDamage', False),
        ('durability', 'base durability', False), ('nodurability', 'no durability stats', False),
        ('reqstr', 'strength requirement (not a stat)', False), ('level', 'qlvl', False), ('levelreq', 'base required level', False),
        ('gemsockets', 'physical socket cap', False), ('gemapplytype', 'rune/gem column set: 0 weapon, 1 armor, 2 shield', False),
        ('auto prefix', 'automagic group', False), ('magic lvl', 'magic level bonus', False),
        ('block', 'shield block (not a stat on the item)', True), ('mindam', 'bash damage (not a saved stat)', True),
        ('maxdam', 'bash damage (not a saved stat)', True),
        ('type', 'primary item type', False), ('type2', 'secondary item type', False), ('code', 'base code', False),
        ('rarity', 'drop rarity', False), ('spawnable', 'drop eligibility', False), ('normcode', 'upgrade family', False),
        ('ubercode', 'upgrade family', False), ('ultracode', 'upgrade family', False), ('version', 'format gate', False),
        ('speed', 'movement/hit speed penalty (not a saved stat)', True), ('absorbs', 'unused', True),
        ('*magiclvl', 'vendor magic-level tuning (not stats)', True), ('*min', 'vendor stock tuning', True),
        ('*max', 'vendor stock tuning', True), ('*magicmin', 'vendor tuning', True), ('*magicmax', 'vendor tuning', True),
        ('*eol', 'terminator', True),
    ]},
    'misc': {'cite': f'{TBLS} D2ItemsTxt', 'feeds': 'base layer', 'roles': [
        ('level', 'qlvl', False), ('levelreq', 'base required level', False), ('gemsockets', 'physical socket cap', False),
        ('gemapplytype', 'rune/gem column set', False), ('auto prefix', 'automagic group', False),
        ('stackable', 'quantity stat', False), ('minstack', 'quantity roll', False), ('maxstack', 'quantity roll', False),
        ('spawnstack', 'quantity roll', False), ('type', 'primary item type', False), ('code', 'base code', False),
        ('rarity', 'drop rarity', False), ('nodurability', 'no durability stats', False), ('version', 'format gate', False),
        ('stat?', 'consumable effect stats (use effect, not the saved list)', True), ('calc?', 'consumable effect formula', True),
        ('*magiclvl', 'vendor magic-level tuning (not stats)', True), ('*min', 'vendor stock tuning', True),
        ('*max', 'vendor stock tuning', True), ('*magicmin', 'vendor tuning', True), ('*magicmax', 'vendor tuning', True),
        ('*eol', 'terminator', True),
    ]},
    'itemtypes': {'cite': f'{TBLS}:403 D2ItemTypesTxt', 'feeds': 'eligibility for all layers', 'roles': [
        ('itemtype', 'display name (not a stat)', True), ('code', 'type code used by itype/etype', False),
        ('equiv?', 'parent types: Equiv closure used by affix, runeword, cube and set matching (ItemMods.cpp:2698)', False),
        ('normal', 'normal-only quality gate', False), ('magic', 'magic minimum / magic-only quality', False),
        ('rare', 'allows ordinary rare', False), ('maxsock?', 'socket cap by ilvl band 1-25 / 26-40 / 41+ (Items.cpp:3036)', False),
        ('staffmods', 'class whose skills a staff can roll (Items.cpp:2771 in D2Game)', False),
        ('class', 'class of the type; checked against affix classspecific', False),
        ('throwable', 'throw damage stats apply', False), ('quiver', 'quantity cap with stack stat', False),
        ('autostack', 'quantity merging', False), ('body', 'equippable', False), ('bodyloc?', 'equip slot', False),
        ('charm', 'charm flag', False), ('beltable', 'belt use', False),
        ('rarity', 'type drop weight', False), ('treasureclass', 'treasure class link', False),
        ('repair', 'repair rules', True), ('shoots', 'ammo type', True), ('reload', 'unused', True), ('reequip', 'unused', True),
        ('gem', 'gem/rune type flag for sockets', False), ('costformula', 'price only', True),
        ('*eol', 'terminator', True), ('varinvgfx', 'graphics', True), ('invgfx?', 'graphics', True), ('storepage', 'vendor page', True),
    ]},
    'magicprefix': {'cite': f'{TBLS}:545 D2MagicAffixTxt', 'feeds': 'quality layer: magic, rare, crafted', 'roles': _AFFIX},
    'magicsuffix': {'cite': f'{TBLS}:545 D2MagicAffixTxt', 'feeds': 'quality layer: magic, rare, crafted', 'roles': _AFFIX},
    'automagic': {'cite': f'{TBLS}:545 D2MagicAffixTxt', 'feeds': 'quality layer: magic items with a base auto prefix; '
                  'group = base auto prefix; rolled by ItemMode.cpp:6357', 'roles': _AFFIX},
    'rareprefix': {'cite': f'{TBLS}:51 D2RareAffixTxt', 'feeds': 'rare/crafted names only; no properties', 'roles': [
        ('name', 'name string key', False), ('version', 'format gate', False), ('itype?', 'allowed types', False),
        ('etype?', 'vetoed types', False)]},
    'raresuffix': {'cite': f'{TBLS}:51 D2RareAffixTxt', 'feeds': 'rare/crafted names only; no properties', 'roles': [
        ('name', 'name string key', False), ('version', 'format gate', False), ('itype?', 'allowed types', False),
        ('etype?', 'vetoed types', False)]},
    'uniqueitems': {'cite': f'{TBLS}:121 D2UniqueItemsTxt', 'feeds': 'quality layer: unique (12 props)', 'roles': [
        ('index', 'identity name key', False), ('version', 'format gate', False), ('enabled', 'drop gate', False),
        ('ladder', 'ladder-only gate', False), ('rarity', 'selection weight max(1, rarity)', False),
        ('nolimit', 'flag word: may drop repeatedly', False), ('lvl', 'drop ilvl threshold', False),
        ('lvl req', 'required level (ITEMS_GetRequiredLevel, max with base levelreq)', False),
        ('code', 'base item code (exact native base)', False), ('*type', 'comment', True), ('*uber', 'comment', True),
        ('carry1', 'carry limit flag', True), ('cost mult', 'price only', True), ('cost add', 'price only', True),
        ('chrtransform', 'palette', True), ('invtransform', 'palette', True), ('flippyfile', 'art', True),
        ('invfile', 'art', True), ('dropsound', 'sound', True), ('dropsfxframe', 'sound', True), ('usesound', 'sound', True),
        ('prop?', 'properties.txt code', False), ('par?', 'property par', False),
        ('min?', 'property min', False), ('max?', 'property max', False), ('*eol', 'terminator', True)]},
    'setitems': {'cite': f'{TBLS}:62 D2SetItemsTxt', 'feeds': 'quality layer: set (9 always-on + 10 partial props)', 'roles': [
        ('index', 'identity name key', False), ('set', 'set row link (nSetId)', False), ('item', 'base item code', False),
        ('*item', 'comment', True), ('rarity', 'selection weight', False), ('lvl', 'drop ilvl threshold', False),
        ('lvl req', 'required level', False), ('add func', 'partial-bonus mode: 0 always on, 1 per worn-item mask, 2 by count', False),
        ('prop?', 'always-on property code (9 slots)', False), ('par?', 'property par', False),
        ('min?', 'property min', False), ('max?', 'property max', False),
        ('aprop?[ab]', 'partial bonus property code; tier n pair a/b is toggled by state ITEMSETn', False),
        ('apar?[ab]', 'partial bonus par', False), ('amin?[ab]', 'partial bonus min', False), ('amax?[ab]', 'partial bonus max', False),
        ('cost mult', 'price only', True), ('cost add', 'price only', True), ('chrtransform', 'palette', True),
        ('invtransform', 'palette', True), ('invfile', 'art', True), ('flippyfile', 'art', True), ('dropsound', 'sound', True),
        ('dropsfxframe', 'sound', True), ('usesound', 'sound', True), ('*eol', 'terminator', True)]},
    'sets': {'cite': f'{TBLS}:89 D2SetsTxt', 'feeds': 'summed layer: character-level set bonuses', 'roles': [
        ('index', 'identity key', False), ('name', 'set name string key', False), ('version', 'format gate', False),
        ('level', 'not compiled into D2SetsTxt', True),
        ('pcode?[ab]', 'partial bonus for n worn items (pBoni2..5), applied as a state list on the character', False),
        ('pparam?[ab]', 'par', False), ('pmin?[ab]', 'min', False), ('pmax?[ab]', 'max', False),
        ('fcode?', 'full-set bonus (pFBoni, 8 slots), on the character when all items worn', False),
        ('fparam?', 'par', False), ('fmin?', 'min', False), ('fmax?', 'max', False), ('*eol', 'terminator', True)]},
    'runes': {'cite': f'{TBLS}:16 D2RunesTxt', 'feeds': 'quality layer: runeword list (7 T1 props)', 'roles': [
        ('name', 'internal key / runeword string key', False), ('rune name', 'display name string key', False),
        ('complete', 'recipe enabled', False), ('server', 'server-only flag', True),
        ('itype?', 'allowed base types', False), ('etype?', 'excluded base types', False),
        ('*runes', 'comment', True), ('rune?', 'ordered rune item codes of the recipe (checked in order)', False),
        ('t1code?', 'runeword property code', False), ('t1param?', 'property par', False),
        ('t1min?', 'property min', False), ('t1max?', 'property max', False), ('eol', 'terminator', True)]},
    'gems': {'cite': f'{TBLS}:470 D2GemsTxt', 'feeds': 'socketed child lists: rune/gem mods by base type', 'roles': [
        ('name', 'item name key', False), ('letter', 'rune letter (display)', True), ('code', 'gem/rune item code', False),
        ('transform', 'palette', True), ('nummods', 'compiled but properties stop at nProperty < 0', True),
        ('weaponmod?*', 'mods when socketed in a weapon (gemapplytype 0)', False),
        ('helmmod?*', 'mods when socketed in a helm/armor (gemapplytype 1)', False),
        ('shieldmod?*', 'mods when socketed in a shield (gemapplytype 2)', False)]},
    'qualityitems': {'cite': f'{TBLS}:30 D2QualityItemsTxt', 'feeds': 'quality layer: superior (<=2 props)', 'roles': [
        ('nummods', 'compiled; at most two property slots are read', False),
        ('mod?code', 'property code', False), ('mod?param', 'property par', False), ('mod?min', 'property min', False),
        ('mod?max', 'property max', False), ('armor', 'row applies to armor types', False), ('weapon', 'applies to weapons', False),
        ('shield', 'applies to shields', False), ('thrown', 'applies to throwing weapons', False),
        ('scepter', 'applies to scepters', False), ('wand', 'applies to wands', False), ('staff', 'applies to staves', False),
        ('bow', 'applies to bows', False), ('boots', 'applies to boots', False), ('gloves', 'applies to gloves', False),
        ('belt', 'applies to belts', False), ('effect?', 'effect strings, not compiled into stats', True),
        ('tohitmin', 'not in D2QualityItemsTxt', True), ('tohitmax', 'not in D2QualityItemsTxt', True),
        ('dam%min', 'not in D2QualityItemsTxt', True), ('dam%max', 'not in D2QualityItemsTxt', True),
        ('ac%min', 'not in D2QualityItemsTxt', True), ('ac%max', 'not in D2QualityItemsTxt', True),
        ('dur%min', 'not in D2QualityItemsTxt', True), ('dur%max', 'not in D2QualityItemsTxt', True),
        ('level', 'not in D2QualityItemsTxt', True), ('multiply', 'not in D2QualityItemsTxt', True),
        ('add', 'not in D2QualityItemsTxt', True)]},
    'lowqualityitems': {'cite': f'{TBLS}:491 D2LowQualityItemsTxt', 'feeds': 'quality layer: inferior name only', 'roles': [
        ('name', 'row index = file index; name only (Cracked/Crude/Damaged/Low Quality). Effect is the fixed '
                 '75% base and 1/3 durability rule in code, not a column', False)]},
    'cubemain': {'cite': 'D2Common/include/DataTbls/HoradricCube.h:93 D2CubeMainTxt', 'feeds': 'crafts, upgrades, rerolls, socket/copy ops', 'roles': [
        ('description', 'comment', True), ('enabled', 'recipe gate', False), ('ladder', 'ladder gate', False),
        ('min diff', 'difficulty gate', False), ('version', 'format gate', False), ('op', 'conditional op', False),
        ('param', 'op param', False), ('value', 'op value', False), ('class', 'class gate', False),
        ('numinputs', 'input count', False), ('input ?', 'input item/type with quality, socket, ethereal modifiers', False),
        ('*output*', 'output item code/flags (usetype, copy mods, socket, ethereal, repair...)', False),
        ('*lvl', 'fixed output level (PlrTrade.cpp:579)', False), ('*plvl', 'output level from player level %', False),
        ('*ilvl', 'output level from input ilvl %', False),
        ('*mod ? chance', 'percent chance the mod slot applies', False),
        ('*mod ?', 'property code written as a crafted/forced property (ITEMMODS_AddCraftPropertyList, ItemMods.cpp:2844)', False),
        ('*mod ? param', 'property par', False), ('*mod ? min', 'property min', False), ('*mod ? max', 'property max', False),
        ('*eol', 'terminator', True)]},
    'itemstatcost': {'cite': f'{TBLS}:235 D2ItemStatCostTxt', 'feeds': 'save format, op derivation and display for every stat', 'roles': [
        ('stat', 'stat name used by properties.txt', False), ('id', 'stat id: save group key', False),
        ('send other', 'flag word', False), ('signed', 'signedness of the value', False),
        ('send bits', 'network width', False), ('send param bits', 'network param width', False),
        ('updateanimrate', 'flag', False), ('saved', 'flag word: stat is saved with the item', False),
        ('csvsigned', 'character save', False), ('csvbits', 'character save width (not used for items)', False),
        ('csvparam', 'character save param', False), ('fcallback', 'flag', False), ('fmin', 'flag', False),
        ('minaccr', 'minimum accrual', False), ('encode', 'save param encoding (e.g. skill pairs)', False),
        ('add', 'cost accounting', True), ('multiply', 'cost accounting', True), ('divide', 'cost accounting', True),
        ('valshift', 'engine value = (saved - Save Add) << ValShift (Items.cpp:6325)', False),
        ('1.09-save bits', 'v<=1.09 item format only', False), ('1.09-save add', 'v<=1.09 item format only', False),
        ('save bits', 'item save value width', False), ('save add', 'item save value bias', False),
        ('save param bits', 'item save param width', False), ('keepzero', 'keep stat at zero', False),
        ('op', 'derivation family (D2StatList.cpp:208)', False), ('op param', 'op shift/param', False),
        ('op base', 'stat read as op base', False), ('op stat?', 'stats the op writes into', False),
        ('direct', 'flag', False), ('maxstat', 'stat capping this one', False), ('itemspecific', 'flag', False),
        ('damagerelated', 'flag: damage-list inheritance (D2StatList.cpp:767)', False),
        ('itemevent?', 'event trigger', False), ('itemeventfunc?', 'event function', False),
        ('descpriority', 'tooltip sort', False), ('descfunc', 'tooltip format function', False),
        ('descval', 'value placement 0/1/2', False), ('descstrpos', 'positive string key', False),
        ('descstrneg', 'negative string key', False), ('descstr2', 'suffix string key', False),
        ('dgrp', 'display group id', False), ('dgrpfunc', 'group format function', False), ('dgrpval', 'group value placement', False),
        ('dgrpstrpos', 'group positive string', False), ('dgrpstrneg', 'group negative string', False),
        ('dgrpstr2', 'group suffix string', False), ('stuff', 'reserved word', True), ('*eol', 'terminator', True)]},
    'properties': {'cite': f'{TBLS}:437 D2PropertiesTxt', 'feeds': 'every property slot of every table above', 'roles': [
        ('code', 'property code used in all prop/mod columns', False),
        ('*done', 'comment flag', True), ('set?', 'value written to the stat (func 1/2/3...: fixed set value)', False),
        ('val?', 'value argument per slot (func 21 layer, func 36 bonus)', False),
        ('func?', 'ITEMMODS_PropertyFuncNN selector (statvocab FUNCS)', False),
        ('stat?', 'itemstatcost stat written by the slot', False), ('*desc', 'comment', True),
        ('*param', 'comment', True), ('*min', 'comment', True), ('*max', 'comment', True),
        ('*notes', 'comment', True), ('*eol', 'terminator', True)]},
}

# Property-bearing columns per table: (code glob, par glob, min glob, max glob, and slot regex)
_CODE_COLS = {
    'magicprefix': r'mod\dcode', 'magicsuffix': r'mod\dcode', 'automagic': r'mod\dcode',
    'uniqueitems': r'prop\d+', 'setitems': r'a?prop\d+[ab]?', 'sets': r'(pcode\d[ab]|fcode\d)',
    'runes': r't1code\d', 'gems': r'(weapon|helm|shield)mod\dcode', 'qualityitems': r'mod\dcode',
    'cubemain': r'(output|mod \d|output [bc]|mod \d b|mod \d c)',
}

EDGE_CASES = [
    {'id': 'ethereal', 'rule': 'Ethereal multiplies base damage (all three damage families) or defense by 3/2 '
     '(integer) and sets IFLAG_ETHEREAL; max durability is halved plus one at creation. The `ethereal` property '
     '(func 23) sets the same flag with no stat.',
     'source': [f'{MODS}:2568 ITEMMODS_ApplyEthereality', f'{MODS}:4370 PropertyFunc23']},
    {'id': 'indestructible', 'rule': 'Property `indestruct` (func 20) sets item_indestructible; the base keeps its '
     'durability stats unless the row has `nodurability`. Ethereal and indestructible coexist; neither '
     'cancels the other.', 'source': [f'{MODS}:4135 PropertyFunc20', 'weapons/armor/misc: nodurability']},
    {'id': 'superior_defense_durability', 'rule': 'Superior adds the qualityitems row props (typically '
     'item_armor_percent/ enhanced damage/ +tohit, and +durability via func 13); armor percent first lifts armorclass to '
     'maxac+1 (ITEMS_SetDefenseOrDamage) then scales; durability percent raises both max and current durability. '
     'Throwables and no-durability bases only consider the first four rows. Inferior scales base damage/defense to '
     '75% and max durability to 1/3 in code; lowqualityitems has no value columns.',
     'source': [f'{ITEMS}:6246', f'{MODS}:4306 PropertyFunc13', 'D2Game/src/ITEMS/ItemsMagic.cpp:969,1033',
                f'{TBLS}:30 D2QualityItemsTxt']},
    {'id': 'sockets_and_filled', 'rule': 'Socket count is an item-header field written by property `sock` (func 14, '
     'clamped to the type MaxSock band), drops, Larzuk or cube; item_numsockets is never a saved stat. A filled socket '
     'is a child item: its gems/runes row picks weaponMod/helmMod/shieldMod by the parent base gemapplytype and the '
     'resolved stats ride on the child list, summed only while the parent is equipped. Runewords only fill '
     'the sockets with runes in order and add the runeword list.',
     'source': [f'{MODS}:3766 PropertyFunc14', f'{ITEMS}:3036 ITEMS_GetMaxSockets', f'{ITEMS}:3360 ITEMS_GetGemApplyType',
                f'{GITEMS}ItemMode.cpp:511,532 ITEMMODS_AssignProperty(gem/rune)', f'{ITEMS}:1070']},
    {'id': 'staffmods', 'rule': 'ItemTypes.StaffMods names the class whose skill tiers a staff may roll; up to '
     'three item_singleskill/class skill props with +1 to +3, tiers raised by ilvl bands. Not in any affix table.',
     'source': [f'{GITEMS}Items.cpp:2771-2895', f'{ITEMS}:2997 ITEMS_GetStaffMods']},
    {'id': 'random_skills', 'rule': '`skill-rand` (func 12) rolls a skill id in [min,max] as the layer with par as the '
     'bonus; `randclassskill` (func 36) rolls a class in [min,max] with properties val1 as the bonus. The rolled layer '
     'is saved, so the table row alone cannot give the final stat.',
     'source': [f'{MODS}:4261 PropertyFunc12', f'{MODS}:4200 PropertyFunc36']},
    {'id': 'larzuk', 'rule': 'Larzuk adds sockets after creation: full base cap for normal/superior/low, 1-2 for magic, 1 '
     'for higher qualities; only the socket header changes.', 'source': [f'{GITEMS.replace("ITEMS/", "UNIT/")}SUnitNpc.cpp:2188-2204']},
    {'id': 'cube_rerolls', 'rule': 'Cube outputs may copy mods (COPYMODS), change quality, add sockets/ethereal, or '
     'regenerate affixes; crafted mod columns apply the authored chance (0 or >=100 always) as extra properties on '
     'top of rolled magic affixes. A rerolled item has a fresh affix set, not the old lists.',
     'source': ['D2Game/src/PLAYER/PlrTrade.cpp:392,547-900', f'{MODS}:2844 ITEMMODS_AddCraftPropertyList']},
    {'id': 'upgraded_uniques', 'rule': 'Cube upgrade keeps the unique identity (file index) so the same uniqueitems row '
     'props are written, but the new base supplies base stats; required level gains 5 (exceptional) or 7 (elite).',
     'source': ['D2Game/src/PLAYER/PlrTrade.cpp:405-440']},
    {'id': 'set_partials', 'rule': 'Partial and full bonuses depend on the worn mask: ITEMS_GetSetItemsMask ORs '
     '1 << setItem.nSetItems for each equipped set item (unequippable flagged items skipped). Reconstruction caveat: '
     'ITEMMODS_UpdateFullSetBoni clamps the item count to nSetItems - 1 before testing the full-set condition.',
     'source': [f'{ITEMS}:4604', f'{MODS}:2623']},
]

DERIVED = {   # stat name -> (kind, note)
    'strength': ('all-stats', 'func 1,3,3,3 of property all-stats adds the same roll to strength, dexterity, vitality, energy'),
    'fireresist': ('res-all', 'property res-all writes the same roll to the four resists; display folds equal values into "All Resistances"'),
    'mindamage': ('damage pair', 'min/max damage props use funcs 5/6: one roll on the one-hand, two-hand and throw stats (21/23/159, 22/24/160)'),
    'maxdamage': ('damage pair', 'see mindamage'),
    'secondary_mindamage': ('secondary copy', 'copy of mindamage on two-handed weapons; weapons.2handmindam seeds it'),
    'secondary_maxdamage': ('secondary copy', 'copy of maxdamage on two-handed weapons'),
    'item_throw_mindamage': ('throw copy', 'copy of mindamage for throwing weapons; weapons.minmisdam seeds it'),
    'item_throw_maxdamage': ('throw copy', 'copy of maxdamage for throwing weapons'),
}


def _match_spec(h, spec):
    pattern = spec.lower().replace('?', '#')
    pattern = re.escape(pattern).replace(r'\#', r'\d+').replace(r'\*', '.*').replace(r'\[ab\]', '[ab]')
    return re.fullmatch(pattern, h.strip().lower()) is not None


def column_roles(table, headers):
    """headers -> [{column, role, ignored}]; columns no spec matches are listed as ignored."""
    roles = TABLES[table]['roles']
    out = []
    for h in headers:
        hit = next(((r, ign) for g, r, ign in roles if _match_spec(h, g)), None)
        if hit is None:
            hit = ('not read by item stat derivation (sources, art, vendor or comment column)', True)
        out.append({'column': str(h), 'role': hit[0], 'ignored': hit[1]})
    return out


def _prop_codes(v, table):
    """Property codes referenced by every property slot of a table (computed)."""
    tb = v.gd.table(table)
    pat = _CODE_COLS.get(table)
    if not pat:
        return set()
    cols = [i for i, h in enumerate(tb.hdr) if re.fullmatch(pat, str(h).strip().lower())]
    # cubemain mod columns are named 'mod 1' / 'mod 1 b' (code) beside 'mod 1 chance'
    codes = set()
    for r in range(len(tb)):
        for i in cols:
            c = str(tb.get(r, tb.hdr[i])).strip().lower()
            if c:
                codes.add(c)
    return codes


def tables_section(v, props):
    by_code = {p['code'].lower(): p for p in props}
    out = {}
    for t, spec in TABLES.items():
        tb = v.gd.table(t)
        headers = list(tb.hdr)
        roles = column_roles(t, headers)
        codes = sorted(_prop_codes(v, t) & set(by_code))
        stat_names = sorted({s['stat'] for c in codes for s in by_code[c]['stats'] if s['stat']})
        out[t] = {
            'cite': spec['cite'], 'feeds': spec['feeds'], 'rows': len(tb),
            'columns': {r['column']: r['role'] for r in roles},
            'ignored': [r['column'] for r in roles if r['ignored']],
            'used_by_stats': stat_names, 'property_codes_used': codes,
        }
    return out


PAR = {'par': 'property par = pProperty->nLayer', 'min': 'authored minimum', 'max': 'authored maximum'}


def properties_hier(v, props):
    out = {}
    for p in props:
        slots = []
        for s in p['stats']:
            uses = set(s['uses'])
            slots.append({
                'slot': s['slot'], 'func': s['func'], 'func_name': s['func_name'], 'stat': s['stat'],
                'stat_id': s['stat_id'], 'set': s['set'], 'val': s['val'],
                'par_role': ('par' in uses) and p['param_kind'] or None,
                'min_role': 'min' in uses and 'value / chance / charges per func' or None,
                'max_role': 'max' in uses and 'value / skill level per func' or None,
                'val_role': 'val' in uses and 'properties.txt valN (layer or bonus)' or None,
                'source': s['source'],
            })
        out[p['code']] = {'func': p['funcs'][0] if p['funcs'] else None, 'funcs': p['funcs'], 'stats': slots,
                          'reads': p['uses'], 'domains': p['domains'], 'param_kind': p['param_kind']}
    return out


def stats_hier(v, props, stats):
    prop_of = {}
    for p in props:
        for s in p['stats']:
            if s['stat_id'] is not None:
                prop_of.setdefault(s['stat_id'], []).append({'code': p['code'], 'slot': s['slot'], 'func': s['func']})
    base = {'armorclass': 'armor.minac/maxac roll', 'mindamage': 'weapons.mindam', 'maxdamage': 'weapons.maxdam',
            'secondary_mindamage': 'weapons.2handmindam', 'secondary_maxdamage': 'weapons.2handmaxdam',
            'item_throw_mindamage': 'weapons.minmisdam', 'item_throw_maxdamage': 'weapons.maxmisdam',
            'maxdurability': 'weapons/armor.durability', 'durability': 'weapons/armor.durability'}
    out = {}
    for sid in sorted(v.it.row_of):
        e = next(x for x in stats if x['id'] == sid)
        name = e['name']
        derived = [{'source': 'property', **x} for x in prop_of.get(sid, [])]
        if name in base:
            derived.insert(0, {'source': 'base', 'column': base[name]})
        if e['op']:
            derived.append({'source': 'op', 'op': e['op'], 'op_stats': e['op_stats'], 'doc': e.get('op_doc', '')})
        out[str(sid)] = {
            'name': name, 'saved': e['saved'], 'param_kind': e['param_kind'], 'value_kind': e['value_kind'],
            'display': {'descfunc': e['descfunc'], 'descval': e['descval'], 'descpriority': e['descpriority'],
                        'pos': e['descstrpos']['text'], 'neg': e['descstrneg']['text'], 'str2': e['descstr2']['text'],
                        'dgrp': e['dgrp'], 'see': 'docs/research/item_generation_114d.md (Stat and parameter vocabulary)'},
            'derived_from': derived,
            'derived_note': DERIVED[name][1] if name in DERIVED else None,
        }
    return out


def build(game_dir=None, tables=None):
    v = sv.load(game_dir, tables)
    stats = sv.stats_section(v)
    props = sv.properties_section(v)
    return {
        'version': '1.14d', 'schema': SCHEMA,
        'layers': LAYERS,
        'tables': tables_section(v, props),
        'properties': properties_hier(v, props),
        'stats': stats_hier(v, props, stats),
        'edge_cases': EDGE_CASES,
    }
