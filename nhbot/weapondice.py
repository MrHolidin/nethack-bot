"""Weapon damage dice (small, large) and to-hit bonus, from NetHack 3.6.6 src/objects.c; the attribute bonuses
(weapon.c abon / dbon)."""
WEAPON_DICE = {'dart': (3, 2, 0), 'shuriken': (8, 6, 2), 'boomerang': (9, 9, 0), 'spear': (6, 8, 0), 'elven spear': (7, 8, 0), 'orcish spear': (5, 8, 0), 'dwarvish spear': (8, 8, 0), 'silver spear': (6, 8, 0), 'javelin': (6, 6, 0), 'trident': (6, 4, 0), 'dagger': (4, 3, 2), 'elven dagger': (5, 3, 2), 'orcish dagger': (3, 3, 2), 'silver dagger': (4, 3, 2), 'athame': (4, 3, 2), 'scalpel': (3, 3, 2), 'knife': (3, 2, 0), 'stiletto': (3, 2, 0), 'worm tooth': (2, 2, 0), 'crysknife': (10, 10, 3), 'axe': (6, 4, 0), 'battle-axe': (8, 6, 0), 'short sword': (6, 8, 0), 'elven short sword': (8, 8, 0), 'orcish short sword': (5, 8, 0), 'dwarvish short sword': (7, 8, 0), 'scimitar': (8, 8, 0), 'silver saber': (8, 8, 0), 'broadsword': (4, 6, 0), 'elven broadsword': (6, 6, 0), 'long sword': (8, 12, 0), 'two-handed sword': (12, 6, 0), 'katana': (10, 12, 1), 'tsurugi': (16, 8, 2), 'runesword': (4, 6, 0), 'partisan': (6, 6, 0), 'ranseur': (4, 4, 0), 'spetum': (6, 6, 0), 'glaive': (6, 10, 0), 'lance': (6, 8, 0), 'halberd': (10, 6, 0), 'bardiche': (4, 4, 0), 'voulge': (4, 4, 0), 'dwarvish mattock': (12, 8, -1), 'fauchard': (6, 8, 0), 'guisarme': (4, 8, 0), 'bill-guisarme': (4, 10, 0), 'lucern hammer': (4, 6, 0), 'bec de corbin': (8, 6, 0), 'mace': (6, 6, 0), 'morning star': (4, 6, 0), 'war hammer': (4, 4, 0), 'club': (6, 3, 0), 'rubber hose': (4, 3, 0), 'quarterstaff': (6, 6, 0), 'aklys': (6, 3, 0), 'flail': (6, 4, 0), 'bullwhip': (2, 1, 0)}


def str_dbon(s):
    """weapon.c dbon: the damage bonus of Strength s (NLE_BL_STR125: 18/xx as 18 + xx)."""
    if s < 6: return -1
    if s < 16: return 0
    if s < 18: return 1
    if s == 18: return 2
    if s <= 18 + 75: return 3
    if s <= 18 + 90: return 4
    if s < 18 + 100: return 5
    return 6


def to_hit_abon(s, dex, xl):
    """weapon.c abon: the to-hit bonus of Strength s (18/xx as 18 + xx) and Dexterity; +1 below XL 3."""
    sb = -2 if s < 6 else -1 if s < 8 else 0 if s < 17 else 1 if s <= 18 + 50 else 2 if s < 18 + 100 else 3
    if xl < 3:
        sb += 1
    db = -3 if dex < 4 else -2 if dex < 6 else -1 if dex < 8 else 0 if dex < 14 else dex - 14
    return sb + db
