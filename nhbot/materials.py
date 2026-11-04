"""What water does to an object (fountain dips): objects.c materials.

trap.c water_damage -> erode_obj(ERODE_RUST): only iron rusts (is_rustprone), unless erodeproof ("rustproof")
or already thoroughly rusty. IRON lists the iron weapons, armor and tools of objects.c by name and by their
unshuffled appearance (an unidentified pair of gloves or boots may still be iron under another look).
"""
import re

from nhbot.items import base_name

IRON = frozenset((
    'Uruk-hai shield', 'aklys', 'angled poleaxe', 'arrow', 'athame', 'axe', 'banded mail', 'bardiche',
    'battle-axe', 'beaked polearm', 'beartrap', 'bec de corbin', 'bill-guisarme', 'broad pick',
    'broad short sword', 'broadsword', 'buckled boots', 'can of grease', 'chain mail', 'crested helmet',
    'crossbow bolt', 'crude arrow', 'crude chain mail', 'crude dagger', 'crude ring mail', 'crude short sword',
    'crude spear', 'curved sword', 'dagger', 'dart', 'dented pot', 'double-headed axe', 'dwarvish iron helm',
    'dwarvish mattock', 'dwarvish roundshield', 'dwarvish short sword', 'dwarvish spear', 'etched helmet',
    'fauchard', 'flail', 'forked polearm', 'gauntlets of power', 'glaive', 'grappling hook', 'guisarme', 'halberd',
    'hard hat', 'hard shoes', 'helm of brilliance', 'helm of opposite alignment', 'helm of telepathy', 'helmet',
    'hilted polearm', 'hooked polearm', 'iron hook', 'iron shoes', 'iron skull cap', 'javelin', 'katana', 'key',
    'kicking boots', 'knife', 'lance', 'land mine', 'large round shield', 'large shield', 'lock pick',
    'long poleaxe', 'long sword', 'lucern hammer', 'mace', 'morning star', 'orcish arrow', 'orcish chain mail',
    'orcish dagger', 'orcish helm', 'orcish ring mail', 'orcish shield', 'orcish short sword', 'orcish spear',
    'partisan', 'pick-axe', 'plate mail', 'plumed helmet', 'pole cleaver', 'pole sickle', 'pronged polearm',
    'pruning hook', 'ranseur', 'red-eyed shield', 'riding gloves', 'ring mail', 'runed broadsword', 'runesword',
    'samurai sword', 'scale mail', 'scimitar', 'short sword', 'shuriken', 'single-edged polearm', 'skeleton key',
    'spear', 'spetum', 'splint mail', 'stethoscope', 'stiletto', 'stout spear', 'thonged club', 'throwing spear',
    'throwing star', 'tin opener', 'tinning kit', 'trident', 'two-handed sword', 'visored helmet', 'voulge',
    'vulgar polearm', 'war hammer', 'white-handed shield',
))


def rusts(text):
    """Would water rust this item (inventory text)?"""
    if "rustproof" in text or "thoroughly rusty" in text:
        return False
    name = re.sub(r"^(?:pairs? of|sets? of) ", "", base_name(text)[2])
    return name in IRON or re.sub(r"s$", "", name) in IRON
