"""Weapon damage dice (small, large) and to-hit bonus, from NetHack 3.6.6 src/objects.c."""
WEAPON_DICE = {'dart': (3, 2, 0), 'shuriken': (8, 6, 2), 'boomerang': (9, 9, 0), 'spear': (6, 8, 0), 'elven spear': (7, 8, 0), 'orcish spear': (5, 8, 0), 'dwarvish spear': (8, 8, 0), 'silver spear': (6, 8, 0), 'javelin': (6, 6, 0), 'trident': (6, 4, 0), 'dagger': (4, 3, 2), 'elven dagger': (5, 3, 2), 'orcish dagger': (3, 3, 2), 'silver dagger': (4, 3, 2), 'athame': (4, 3, 2), 'scalpel': (3, 3, 2), 'knife': (3, 2, 0), 'stiletto': (3, 2, 0), 'worm tooth': (2, 2, 0), 'crysknife': (10, 10, 3), 'axe': (6, 4, 0), 'battle-axe': (8, 6, 0), 'short sword': (6, 8, 0), 'elven short sword': (8, 8, 0), 'orcish short sword': (5, 8, 0), 'dwarvish short sword': (7, 8, 0), 'scimitar': (8, 8, 0), 'silver saber': (8, 8, 0), 'broadsword': (4, 6, 0), 'elven broadsword': (6, 6, 0), 'long sword': (8, 12, 0), 'two-handed sword': (12, 6, 0), 'katana': (10, 12, 1), 'tsurugi': (16, 8, 2), 'runesword': (4, 6, 0), 'partisan': (6, 6, 0), 'ranseur': (4, 4, 0), 'spetum': (6, 6, 0), 'glaive': (6, 10, 0), 'lance': (6, 8, 0), 'halberd': (10, 6, 0), 'bardiche': (4, 4, 0), 'voulge': (4, 4, 0), 'dwarvish mattock': (12, 8, -1), 'fauchard': (6, 8, 0), 'guisarme': (4, 8, 0), 'bill-guisarme': (4, 10, 0), 'lucern hammer': (4, 6, 0), 'bec de corbin': (8, 6, 0), 'mace': (6, 6, 0), 'morning star': (4, 6, 0), 'war hammer': (4, 4, 0), 'club': (6, 3, 0), 'rubber hose': (4, 3, 0), 'quarterstaff': (6, 6, 0), 'aklys': (6, 3, 0), 'flail': (6, 4, 0), 'bullwhip': (2, 1, 0)}

# the skill each weapon (and weapon-tool) trains and uses, objects.c's sub field (abs: launcher ammo and missiles
# carry -P_BOW, -P_DART, ...; weapon.c weapon_type), by the name the #enhance menu gives that skill (weapon.c P_NAME)
WEAPON_SKILL = {
    'arrow': 'bow', 'elven arrow': 'bow', 'orcish arrow': 'bow', 'silver arrow': 'bow', 'ya': 'bow',
    'crossbow bolt': 'crossbow', 'dart': 'dart', 'shuriken': 'shuriken', 'boomerang': 'boomerang',
    'spear': 'spear', 'elven spear': 'spear', 'orcish spear': 'spear', 'dwarvish spear': 'spear',
    'silver spear': 'spear', 'javelin': 'spear', 'trident': 'trident', 'dagger': 'dagger', 'elven dagger': 'dagger',
    'orcish dagger': 'dagger', 'silver dagger': 'dagger', 'athame': 'dagger', 'scalpel': 'knife', 'knife': 'knife',
    'stiletto': 'knife', 'worm tooth': 'knife', 'crysknife': 'knife', 'axe': 'axe', 'battle-axe': 'axe',
    'short sword': 'short sword', 'elven short sword': 'short sword', 'orcish short sword': 'short sword',
    'dwarvish short sword': 'short sword', 'scimitar': 'scimitar', 'silver saber': 'saber',
    'broadsword': 'broadsword', 'elven broadsword': 'broadsword', 'long sword': 'long sword',
    'two-handed sword': 'two-handed sword', 'katana': 'long sword', 'tsurugi': 'two-handed sword',
    'runesword': 'broadsword', 'partisan': 'polearms', 'ranseur': 'polearms', 'spetum': 'polearms',
    'glaive': 'polearms', 'lance': 'lance', 'halberd': 'polearms', 'bardiche': 'polearms', 'voulge': 'polearms',
    'dwarvish mattock': 'pick-axe', 'fauchard': 'polearms', 'guisarme': 'polearms', 'bill-guisarme': 'polearms',
    'lucern hammer': 'polearms', 'bec de corbin': 'polearms', 'mace': 'mace', 'morning star': 'morning star',
    'war hammer': 'hammer', 'club': 'club', 'rubber hose': 'whip', 'quarterstaff': 'quarterstaff', 'aklys': 'club',
    'flail': 'flail', 'bullwhip': 'whip', 'bow': 'bow', 'elven bow': 'bow', 'orcish bow': 'bow', 'yumi': 'bow',
    'sling': 'sling', 'crossbow': 'crossbow', 'pick-axe': 'pick-axe', 'grappling hook': 'flail',
    'unicorn horn': 'unicorn horn'}

# skills.h P_ISRESTRICTED .. P_GRAND_MASTER, by the #enhance menu's level names (weapon.c skill_level_name)
SKILL_LEVEL = {"Restricted": 0, "Unskilled": 1, "Basic": 2, "Skilled": 3, "Expert": 4, "Master": 5,
               "Grand Master": 6}


def skill_hit_bonus(level, bare=False, martial=False):
    """weapon.c:1399-1465 weapon_hit_bonus: a weapon skill Restricted / Unskilled -4, Basic 0, Skilled +2, Expert +3;
    bare-handed ((max(level, Unskilled) - 1 + 2) * (2 if martial arts else 1)) / 2."""
    if bare:
        return ((max(level, 1) - 1 + 2) * (2 if martial else 1)) // 2
    return {0: -4, 1: -4, 2: 0, 3: 2}.get(level, 3)


def skill_dmg_bonus(level, bare=False, martial=False):
    """weapon.c:1494-1558 weapon_dam_bonus: a weapon skill Restricted / Unskilled -2, Basic 0, Skilled +1, Expert +2;
    bare-handed ((max(level, Unskilled) - 1 + 1) * (3 if martial arts else 1)) / 2."""
    if bare:
        return ((max(level, 1) - 1 + 1) * (3 if martial else 1)) // 2
    return {0: -2, 1: -2, 2: 0, 3: 1}.get(level, 2)
