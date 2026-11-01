"""Attack types of every monster, by permonst index (generated from NetHack 3.6.6 src/monst.c)."""
# ATTACKS[i] = ((attack type, damage type, n, d), ...): damage is n d d
ATTACKS = [
    (('BITE', 'PHYS', 1, 4),),  # 0 giant ant
    (('STNG', 'DRST', 1, 3),),  # 1 killer bee
    (('BITE', 'PHYS', 2, 4), ('STNG', 'DRST', 3, 4)),  # 2 soldier ant
    (('BITE', 'PHYS', 2, 4), ('BITE', 'FIRE', 2, 4)),  # 3 fire ant
    (('BITE', 'PHYS', 3, 6),),  # 4 giant beetle
    (('STNG', 'DRST', 1, 8),),  # 5 queen bee
    (('NONE', 'ACID', 1, 8),),  # 6 acid blob
    (('TUCH', 'PHYS', 1, 8),),  # 7 quivering blob
    (('TUCH', 'PLYS', 2, 4), ('NONE', 'PLYS', 1, 4)),  # 8 gelatinous cube
    (('BITE', 'PHYS', 1, 2), ('TUCH', 'STON', 0, 0), ('NONE', 'STON', 0, 0)),  # 9 chickatrice
    (('BITE', 'PHYS', 1, 3), ('TUCH', 'STON', 0, 0), ('NONE', 'STON', 0, 0)),  # 10 cockatrice
    (('GAZE', 'FIRE', 2, 6),),  # 11 pyrolisk
    (('BITE', 'PHYS', 1, 2),),  # 12 jackal
    (('BITE', 'PHYS', 1, 3),),  # 13 fox
    (('BITE', 'PHYS', 1, 4),),  # 14 coyote
    (('BITE', 'WERE', 1, 4),),  # 15 werejackal
    (('BITE', 'PHYS', 1, 6),),  # 16 little dog
    (('BITE', 'PHYS', 1, 6),),  # 17 dingo
    (('BITE', 'PHYS', 1, 6),),  # 18 dog
    (('BITE', 'PHYS', 2, 4),),  # 19 large dog
    (('BITE', 'PHYS', 2, 4),),  # 20 wolf
    (('BITE', 'WERE', 2, 6),),  # 21 werewolf
    (('BITE', 'PHYS', 1, 8), ('BREA', 'COLD', 1, 6)),  # 22 winter wolf cub
    (('BITE', 'PHYS', 2, 6),),  # 23 warg
    (('BITE', 'PHYS', 2, 6), ('BREA', 'COLD', 2, 6)),  # 24 winter wolf
    (('BITE', 'PHYS', 2, 6), ('BREA', 'FIRE', 2, 6)),  # 25 hell hound pup
    (('BITE', 'PHYS', 3, 6), ('BREA', 'FIRE', 3, 6)),  # 26 hell hound
    (('BOOM', 'PHYS', 4, 6),),  # 27 gas spore
    (('NONE', 'PLYS', 0, 70),),  # 28 floating eye
    (('EXPL', 'COLD', 4, 6),),  # 29 freezing sphere
    (('EXPL', 'FIRE', 4, 6),),  # 30 flaming sphere
    (('EXPL', 'ELEC', 4, 6),),  # 31 shocking sphere
    (('BITE', 'PHYS', 1, 6),),  # 32 kitten
    (('BITE', 'PHYS', 1, 6),),  # 33 housecat
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('BITE', 'PHYS', 1, 8)),  # 34 jaguar
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('BITE', 'PHYS', 1, 10)),  # 35 lynx
    (('CLAW', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 6), ('BITE', 'PHYS', 1, 10)),  # 36 panther
    (('BITE', 'PHYS', 2, 4),),  # 37 large cat
    (('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4), ('BITE', 'PHYS', 1, 10)),  # 38 tiger
    (('CLAW', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 6), ('BITE', 'PHYS', 1, 4), ('CLAW', 'CURS', 0, 0)),  # 39 gremlin
    (('CLAW', 'PHYS', 2, 6), ('CLAW', 'PHYS', 2, 6), ('BITE', 'PHYS', 2, 4)),  # 40 gargoyle
    (('CLAW', 'PHYS', 3, 6), ('CLAW', 'PHYS', 3, 6), ('BITE', 'PHYS', 3, 4)),  # 41 winged gargoyle
    (('WEAP', 'PHYS', 1, 6),),  # 42 hobbit
    (('WEAP', 'PHYS', 1, 8),),  # 43 dwarf
    (('WEAP', 'PHYS', 2, 4),),  # 44 bugbear
    (('WEAP', 'PHYS', 2, 4), ('WEAP', 'PHYS', 2, 4)),  # 45 dwarf lord
    (('WEAP', 'PHYS', 2, 6), ('WEAP', 'PHYS', 2, 6)),  # 46 dwarf king
    (('WEAP', 'PHYS', 1, 4), ('TENT', 'DRIN', 2, 1), ('TENT', 'DRIN', 2, 1), ('TENT', 'DRIN', 2, 1)),  # 47 mind flayer
    (('WEAP', 'PHYS', 1, 8), ('TENT', 'DRIN', 2, 1), ('TENT', 'DRIN', 2, 1), ('TENT', 'DRIN', 2, 1), ('TENT', 'DRIN', 2, 1), ('TENT', 'DRIN', 2, 1)),  # 48 master mind flayer
    (('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3), ('BITE', 'PHYS', 1, 4)),  # 49 manes
    (('BITE', 'SLEE', 1, 3),),  # 50 homunculus
    (('CLAW', 'PHYS', 1, 4),),  # 51 imp
    (('CLAW', 'PHYS', 1, 3),),  # 52 lemure
    (('CLAW', 'DRDX', 1, 2), ('CLAW', 'DRDX', 1, 2), ('BITE', 'PHYS', 1, 4)),  # 53 quasit
    (('BITE', 'PHYS', 1, 7),),  # 54 tengu
    (('NONE', 'COLD', 0, 6),),  # 55 blue jelly
    (('NONE', 'ACID', 0, 6),),  # 56 spotted jelly
    (('ENGL', 'ACID', 3, 6), ('NONE', 'ACID', 3, 6)),  # 57 ochre jelly
    (('WEAP', 'PHYS', 1, 4),),  # 58 kobold
    (('WEAP', 'PHYS', 1, 6),),  # 59 large kobold
    (('WEAP', 'PHYS', 2, 4),),  # 60 kobold lord
    (('MAGC', 'SPEL', 0, 0),),  # 61 kobold shaman
    (('CLAW', 'SGLD', 1, 2),),  # 62 leprechaun
    (('CLAW', 'PHYS', 3, 4),),  # 63 small mimic
    (('CLAW', 'STCK', 3, 4),),  # 64 large mimic
    (('CLAW', 'STCK', 3, 6), ('CLAW', 'STCK', 3, 6)),  # 65 giant mimic
    (('CLAW', 'SITM', 0, 0), ('CLAW', 'SEDU', 0, 0)),  # 66 wood nymph
    (('CLAW', 'SITM', 0, 0), ('CLAW', 'SEDU', 0, 0)),  # 67 water nymph
    (('CLAW', 'SITM', 0, 0), ('CLAW', 'SEDU', 0, 0)),  # 68 mountain nymph
    (('WEAP', 'PHYS', 1, 4),),  # 69 goblin
    (('WEAP', 'PHYS', 1, 6),),  # 70 hobgoblin
    (('WEAP', 'PHYS', 1, 8),),  # 71 orc
    (('WEAP', 'PHYS', 1, 6),),  # 72 hill orc
    (('WEAP', 'PHYS', 1, 6),),  # 73 Mordor orc
    (('WEAP', 'PHYS', 1, 8),),  # 74 Uruk-hai
    (('MAGC', 'SPEL', 0, 0),),  # 75 orc shaman
    (('WEAP', 'PHYS', 2, 4), ('WEAP', 'PHYS', 2, 4)),  # 76 orc-captain
    (('BITE', 'PHYS', 2, 6),),  # 77 rock piercer
    (('BITE', 'PHYS', 3, 6),),  # 78 iron piercer
    (('BITE', 'PHYS', 4, 6),),  # 79 glass piercer
    (('CLAW', 'PHYS', 1, 3), ('BITE', 'PHYS', 1, 3), ('BITE', 'PHYS', 1, 8)),  # 80 rothe
    (('BUTT', 'PHYS', 4, 12), ('BITE', 'PHYS', 2, 6)),  # 81 mumak
    (('CLAW', 'PHYS', 2, 6), ('BITE', 'PHYS', 2, 6), ('CLAW', 'PHYS', 2, 6)),  # 82 leocrotta
    (('BITE', 'PHYS', 3, 6),),  # 83 wumpus
    (('CLAW', 'PHYS', 2, 8),),  # 84 titanothere
    (('CLAW', 'PHYS', 5, 4), ('CLAW', 'PHYS', 5, 4)),  # 85 baluchitherium
    (('BUTT', 'PHYS', 4, 8), ('BUTT', 'PHYS', 4, 8)),  # 86 mastodon
    (('BITE', 'PHYS', 1, 3),),  # 87 sewer rat
    (('BITE', 'PHYS', 1, 3),),  # 88 giant rat
    (('BITE', 'DRCO', 2, 4),),  # 89 rabid rat
    (('BITE', 'WERE', 1, 4),),  # 90 wererat
    (('BITE', 'PHYS', 1, 6),),  # 91 rock mole
    (('BITE', 'PHYS', 1, 6),),  # 92 woodchuck
    (('BITE', 'PHYS', 1, 2),),  # 93 cave spider
    (('BITE', 'DRST', 1, 3),),  # 94 centipede
    (('BITE', 'DRST', 2, 4),),  # 95 giant spider
    (('CLAW', 'PHYS', 1, 2), ('CLAW', 'PHYS', 1, 2), ('STNG', 'DRST', 1, 4)),  # 96 scorpion
    (('ENGL', 'DGST', 1, 8),),  # 97 lurker above
    (('ENGL', 'DGST', 1, 10),),  # 98 trapper
    (('KICK', 'PHYS', 1, 6), ('BITE', 'PHYS', 1, 2)),  # 99 pony
    (('BUTT', 'PHYS', 1, 12), ('KICK', 'PHYS', 1, 6)),  # 100 white unicorn
    (('BUTT', 'PHYS', 1, 12), ('KICK', 'PHYS', 1, 6)),  # 101 gray unicorn
    (('BUTT', 'PHYS', 1, 12), ('KICK', 'PHYS', 1, 6)),  # 102 black unicorn
    (('KICK', 'PHYS', 1, 8), ('BITE', 'PHYS', 1, 3)),  # 103 horse
    (('KICK', 'PHYS', 1, 10), ('BITE', 'PHYS', 1, 4)),  # 104 warhorse
    (('ENGL', 'PHYS', 1, 6),),  # 105 fog cloud
    (('ENGL', 'BLND', 2, 8),),  # 106 dust vortex
    (('ENGL', 'COLD', 1, 6),),  # 107 ice vortex
    (('ENGL', 'ELEC', 1, 6), ('ENGL', 'DREN', 2, 6), ('NONE', 'ELEC', 0, 4)),  # 108 energy vortex
    (('ENGL', 'FIRE', 1, 8),),  # 109 steam vortex
    (('ENGL', 'FIRE', 1, 10), ('NONE', 'FIRE', 0, 4)),  # 110 fire vortex
    (('BITE', 'PHYS', 1, 4),),  # 111 baby long worm
    (('BITE', 'PHYS', 1, 6),),  # 112 baby purple worm
    (('BITE', 'PHYS', 2, 4),),  # 113 long worm
    (('BITE', 'PHYS', 2, 8), ('ENGL', 'DGST', 1, 10)),  # 114 purple worm
    (('BITE', 'ELEC', 1, 1),),  # 115 grid bug
    (('STNG', 'LEGS', 1, 4),),  # 116 xan
    (('EXPL', 'BLND', 10, 20),),  # 117 yellow light
    (('EXPL', 'HALU', 10, 12),),  # 118 black light
    (('CLAW', 'PHYS', 3, 4), ('CLAW', 'PHYS', 3, 4), ('BITE', 'PHYS', 3, 6)),  # 119 zruty
    (('BITE', 'DRST', 2, 4), ('BITE', 'PHYS', 1, 3), ('HUGS', 'WRAP', 2, 4)),  # 120 couatl
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6), ('KICK', 'PHYS', 1, 4)),  # 121 Aleax
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 4), ('MAGC', 'MAGM', 2, 6)),  # 122 Angel
    (('KICK', 'PHYS', 2, 4), ('KICK', 'PHYS', 2, 4), ('BUTT', 'PHYS', 3, 6), ('MAGC', 'SPEL', 2, 6)),  # 123 ki-rin
    (('WEAP', 'PHYS', 2, 4), ('WEAP', 'PHYS', 2, 4), ('GAZE', 'BLND', 2, 6), ('CLAW', 'PHYS', 1, 8), ('MAGC', 'SPEL', 4, 6)),  # 124 Archon
    (('BITE', 'PHYS', 1, 4),),  # 125 bat
    (('BITE', 'PHYS', 1, 6),),  # 126 giant bat
    (('BITE', 'PHYS', 1, 6), ('CLAW', 'BLND', 1, 6)),  # 127 raven
    (('BITE', 'PHYS', 1, 6), ('BITE', 'DRST', 0, 0)),  # 128 vampire bat
    (('WEAP', 'PHYS', 1, 6), ('KICK', 'PHYS', 1, 6)),  # 129 plains centaur
    (('WEAP', 'PHYS', 1, 8), ('KICK', 'PHYS', 1, 6)),  # 130 forest centaur
    (('WEAP', 'PHYS', 1, 10), ('KICK', 'PHYS', 1, 6), ('KICK', 'PHYS', 1, 6)),  # 131 mountain centaur
    (('BITE', 'PHYS', 2, 6),),  # 132 baby gray dragon
    (('BITE', 'PHYS', 2, 6),),  # 133 baby silver dragon
    (('BITE', 'PHYS', 2, 6),),  # 134 baby red dragon
    (('BITE', 'PHYS', 2, 6),),  # 135 baby white dragon
    (('BITE', 'PHYS', 2, 6),),  # 136 baby orange dragon
    (('BITE', 'PHYS', 2, 6),),  # 137 baby black dragon
    (('BITE', 'PHYS', 2, 6),),  # 138 baby blue dragon
    (('BITE', 'PHYS', 2, 6),),  # 139 baby green dragon
    (('BITE', 'PHYS', 2, 6),),  # 140 baby yellow dragon
    (('BREA', 'MAGM', 4, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 141 gray dragon
    (('BREA', 'COLD', 4, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 142 silver dragon
    (('BREA', 'FIRE', 6, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 143 red dragon
    (('BREA', 'COLD', 4, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 144 white dragon
    (('BREA', 'SLEE', 4, 25), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 145 orange dragon
    (('BREA', 'DISN', 1, 255), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 146 black dragon
    (('BREA', 'ELEC', 4, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 147 blue dragon
    (('BREA', 'DRST', 4, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 148 green dragon
    (('BREA', 'ACID', 4, 6), ('BITE', 'PHYS', 3, 8), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4)),  # 149 yellow dragon
    (('CLAW', 'PHYS', 4, 4),),  # 150 stalker
    (('ENGL', 'PHYS', 1, 10),),  # 151 air elemental
    (('CLAW', 'FIRE', 3, 6), ('NONE', 'FIRE', 0, 4)),  # 152 fire elemental
    (('CLAW', 'PHYS', 4, 6),),  # 153 earth elemental
    (('CLAW', 'PHYS', 5, 6),),  # 154 water elemental
    (('TUCH', 'STCK', 0, 0),),  # 155 lichen
    (('NONE', 'COLD', 0, 6),),  # 156 brown mold
    (('NONE', 'STUN', 0, 4),),  # 157 yellow mold
    (('NONE', 'ACID', 0, 4),),  # 158 green mold
    (('NONE', 'FIRE', 0, 4),),  # 159 red mold
    (),  # 160 shrieker
    (('TUCH', 'PHYS', 1, 4), ('TUCH', 'STCK', 0, 0)),  # 161 violet fungus
    (('WEAP', 'PHYS', 1, 6),),  # 162 gnome
    (('WEAP', 'PHYS', 1, 8),),  # 163 gnome lord
    (('MAGC', 'SPEL', 0, 0),),  # 164 gnomish wizard
    (('WEAP', 'PHYS', 2, 6),),  # 165 gnome king
    (('WEAP', 'PHYS', 2, 10),),  # 166 giant
    (('WEAP', 'PHYS', 2, 10),),  # 167 stone giant
    (('WEAP', 'PHYS', 2, 8),),  # 168 hill giant
    (('WEAP', 'PHYS', 2, 10),),  # 169 fire giant
    (('WEAP', 'PHYS', 2, 12),),  # 170 frost giant
    (('WEAP', 'PHYS', 2, 8), ('WEAP', 'PHYS', 3, 6)),  # 171 ettin
    (('WEAP', 'PHYS', 2, 12),),  # 172 storm giant
    (('WEAP', 'PHYS', 2, 8), ('MAGC', 'SPEL', 0, 0)),  # 173 titan
    (('CLAW', 'PHYS', 3, 10), ('CLAW', 'PHYS', 3, 10), ('BUTT', 'PHYS', 2, 8)),  # 174 minotaur
    (('BITE', 'PHYS', 2, 10), ('BITE', 'PHYS', 2, 10), ('CLAW', 'PHYS', 2, 10), ('CLAW', 'PHYS', 2, 10)),  # 175 jabberwock
    (('WEAP', 'PHYS', 1, 4),),  # 176 Keystone Kop
    (('WEAP', 'PHYS', 1, 6),),  # 177 Kop Sergeant
    (('WEAP', 'PHYS', 1, 8),),  # 178 Kop Lieutenant
    (('WEAP', 'PHYS', 2, 6),),  # 179 Kop Kaptain
    (('TUCH', 'COLD', 1, 10), ('MAGC', 'SPEL', 0, 0)),  # 180 lich
    (('TUCH', 'COLD', 3, 4), ('MAGC', 'SPEL', 0, 0)),  # 181 demilich
    (('TUCH', 'COLD', 3, 6), ('MAGC', 'SPEL', 0, 0)),  # 182 master lich
    (('TUCH', 'COLD', 5, 6), ('MAGC', 'SPEL', 0, 0)),  # 183 arch-lich
    (('CLAW', 'PHYS', 1, 4),),  # 184 kobold mummy
    (('CLAW', 'PHYS', 1, 6),),  # 185 gnome mummy
    (('CLAW', 'PHYS', 1, 6),),  # 186 orc mummy
    (('CLAW', 'PHYS', 1, 6),),  # 187 dwarf mummy
    (('CLAW', 'PHYS', 2, 4),),  # 188 elf mummy
    (('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4)),  # 189 human mummy
    (('CLAW', 'PHYS', 2, 6), ('CLAW', 'PHYS', 2, 6)),  # 190 ettin mummy
    (('CLAW', 'PHYS', 3, 4), ('CLAW', 'PHYS', 3, 4)),  # 191 giant mummy
    (('BITE', 'PHYS', 1, 4),),  # 192 red naga hatchling
    (('BITE', 'PHYS', 1, 4),),  # 193 black naga hatchling
    (('BITE', 'PHYS', 1, 4),),  # 194 golden naga hatchling
    (('BITE', 'PHYS', 1, 4),),  # 195 guardian naga hatchling
    (('BITE', 'PHYS', 2, 4), ('BREA', 'FIRE', 2, 6)),  # 196 red naga
    (('BITE', 'PHYS', 2, 6), ('SPIT', 'ACID', 0, 0)),  # 197 black naga
    (('BITE', 'PHYS', 2, 6), ('MAGC', 'SPEL', 4, 6)),  # 198 golden naga
    (('BITE', 'PLYS', 1, 6), ('SPIT', 'DRST', 1, 6), ('HUGS', 'PHYS', 2, 4)),  # 199 guardian naga
    (('WEAP', 'PHYS', 2, 5),),  # 200 ogre
    (('WEAP', 'PHYS', 2, 6),),  # 201 ogre lord
    (('WEAP', 'PHYS', 3, 5),),  # 202 ogre king
    (('BITE', 'RUST', 2, 8),),  # 203 gray ooze
    (('BITE', 'DCAY', 0, 0),),  # 204 brown pudding
    (('TUCH', 'SLIM', 1, 4), ('NONE', 'SLIM', 0, 0)),  # 205 green slime
    (('BITE', 'CORR', 3, 8), ('NONE', 'CORR', 0, 0)),  # 206 black pudding
    (('CLAW', 'TLPT', 1, 4),),  # 207 quantum mechanic
    (('TUCH', 'RUST', 0, 0), ('TUCH', 'RUST', 0, 0), ('NONE', 'RUST', 0, 0)),  # 208 rust monster
    (('CLAW', 'ENCH', 4, 4), ('NONE', 'ENCH', 0, 0)),  # 209 disenchanter
    (('BITE', 'PHYS', 1, 2),),  # 210 garter snake
    (('BITE', 'DRST', 1, 6),),  # 211 snake
    (('BITE', 'DRST', 1, 6),),  # 212 water moccasin
    (('BITE', 'PHYS', 1, 4), ('TUCH', 'PHYS', 0, 0), ('HUGS', 'WRAP', 1, 4), ('HUGS', 'PHYS', 2, 4)),  # 213 python
    (('BITE', 'DRST', 1, 4), ('BITE', 'DRST', 1, 4)),  # 214 pit viper
    (('BITE', 'DRST', 2, 4), ('SPIT', 'BLND', 0, 0)),  # 215 cobra
    (('WEAP', 'PHYS', 4, 2), ('CLAW', 'PHYS', 4, 2), ('BITE', 'PHYS', 2, 6)),  # 216 troll
    (('WEAP', 'PHYS', 2, 6), ('CLAW', 'COLD', 2, 6), ('BITE', 'PHYS', 2, 6)),  # 217 ice troll
    (('WEAP', 'PHYS', 3, 6), ('CLAW', 'PHYS', 2, 8), ('BITE', 'PHYS', 2, 6)),  # 218 rock troll
    (('WEAP', 'PHYS', 2, 8), ('CLAW', 'PHYS', 2, 8), ('BITE', 'PHYS', 2, 6)),  # 219 water troll
    (('WEAP', 'PHYS', 3, 6), ('CLAW', 'PHYS', 2, 8), ('BITE', 'PHYS', 2, 6)),  # 220 Olog-hai
    (('CLAW', 'PHYS', 3, 4), ('CLAW', 'PHYS', 3, 4), ('BITE', 'PHYS', 2, 5), ('GAZE', 'CONF', 0, 0)),  # 221 umber hulk
    (('CLAW', 'PHYS', 1, 6), ('BITE', 'DRLI', 1, 6)),  # 222 vampire
    (('CLAW', 'PHYS', 1, 8), ('BITE', 'DRLI', 1, 8)),  # 223 vampire lord
    (('WEAP', 'PHYS', 2, 10), ('BITE', 'DRLI', 1, 12)),  # 224 Vlad the Impaler
    (('WEAP', 'DRLI', 0, 0), ('MAGC', 'SPEL', 0, 0), ('CLAW', 'PHYS', 1, 4)),  # 225 barrow wight
    (('TUCH', 'DRLI', 1, 6),),  # 226 wraith
    (('WEAP', 'DRLI', 1, 4), ('BREA', 'SLEE', 2, 25)),  # 227 Nazgul
    (('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3), ('BITE', 'PHYS', 4, 6)),  # 228 xorn
    (('CLAW', 'SITM', 0, 0), ('BITE', 'PHYS', 1, 3)),  # 229 monkey
    (('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3), ('BITE', 'PHYS', 1, 6)),  # 230 ape
    (('CLAW', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 6), ('HUGS', 'PHYS', 2, 8)),  # 231 owlbear
    (('CLAW', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 6), ('BITE', 'PHYS', 1, 4)),  # 232 yeti
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('HUGS', 'PHYS', 1, 8)),  # 233 carnivorous ape
    (('CLAW', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 6), ('KICK', 'PHYS', 1, 8)),  # 234 sasquatch
    (('CLAW', 'PHYS', 1, 4),),  # 235 kobold zombie
    (('CLAW', 'PHYS', 1, 5),),  # 236 gnome zombie
    (('CLAW', 'PHYS', 1, 6),),  # 237 orc zombie
    (('CLAW', 'PHYS', 1, 6),),  # 238 dwarf zombie
    (('CLAW', 'PHYS', 1, 7),),  # 239 elf zombie
    (('CLAW', 'PHYS', 1, 8),),  # 240 human zombie
    (('CLAW', 'PHYS', 1, 10), ('CLAW', 'PHYS', 1, 10)),  # 241 ettin zombie
    (('CLAW', 'PLYS', 1, 2), ('CLAW', 'PHYS', 1, 3)),  # 242 ghoul
    (('CLAW', 'PHYS', 2, 8), ('CLAW', 'PHYS', 2, 8)),  # 243 giant zombie
    (('WEAP', 'PHYS', 2, 6), ('TUCH', 'SLOW', 1, 6)),  # 244 skeleton
    (('CLAW', 'PHYS', 1, 2), ('CLAW', 'PHYS', 1, 2)),  # 245 straw golem
    (('CLAW', 'PHYS', 1, 3),),  # 246 paper golem
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('HUGS', 'PHYS', 6, 1)),  # 247 rope golem
    (('CLAW', 'PHYS', 2, 3), ('CLAW', 'PHYS', 2, 3)),  # 248 gold golem
    (('CLAW', 'PHYS', 1, 6), ('CLAW', 'PHYS', 1, 6)),  # 249 leather golem
    (('CLAW', 'PHYS', 3, 4),),  # 250 wood golem
    (('CLAW', 'PHYS', 2, 8), ('CLAW', 'PHYS', 2, 8)),  # 251 flesh golem
    (('CLAW', 'PHYS', 3, 10),),  # 252 clay golem
    (('CLAW', 'PHYS', 3, 8),),  # 253 stone golem
    (('CLAW', 'PHYS', 2, 8), ('CLAW', 'PHYS', 2, 8)),  # 254 glass golem
    (('WEAP', 'PHYS', 4, 10), ('BREA', 'DRST', 4, 6)),  # 255 iron golem
    (('WEAP', 'PHYS', 1, 6),),  # 256 human
    (('WEAP', 'PHYS', 2, 4),),  # 257 wererat
    (('WEAP', 'PHYS', 2, 4),),  # 258 werejackal
    (('WEAP', 'PHYS', 2, 4),),  # 259 werewolf
    (('WEAP', 'PHYS', 1, 8),),  # 260 elf
    (('WEAP', 'PHYS', 2, 4),),  # 261 Woodland-elf
    (('WEAP', 'PHYS', 2, 4),),  # 262 Green-elf
    (('WEAP', 'PHYS', 2, 4),),  # 263 Grey-elf
    (('WEAP', 'PHYS', 2, 4), ('WEAP', 'PHYS', 2, 4)),  # 264 elf-lord
    (('WEAP', 'PHYS', 2, 4), ('WEAP', 'PHYS', 2, 4)),  # 265 Elvenking
    (('WEAP', 'PHYS', 1, 12),),  # 266 doppelganger
    (('WEAP', 'PHYS', 4, 4), ('WEAP', 'PHYS', 4, 4)),  # 267 shopkeeper
    (('WEAP', 'PHYS', 4, 10),),  # 268 guard
    (('WEAP', 'PHYS', 1, 6),),  # 269 prisoner
    (('NONE', 'MAGM', 0, 4),),  # 270 Oracle
    (('WEAP', 'PHYS', 4, 10), ('KICK', 'PHYS', 1, 4), ('MAGC', 'CLRC', 0, 0)),  # 271 aligned priest
    (('WEAP', 'PHYS', 4, 10), ('KICK', 'PHYS', 2, 8), ('MAGC', 'CLRC', 2, 8), ('MAGC', 'CLRC', 2, 8)),  # 272 high priest
    (('WEAP', 'PHYS', 1, 8),),  # 273 soldier
    (('WEAP', 'PHYS', 2, 6),),  # 274 sergeant
    (('CLAW', 'HEAL', 2, 6),),  # 275 nurse
    (('WEAP', 'PHYS', 3, 4), ('WEAP', 'PHYS', 3, 4)),  # 276 lieutenant
    (('WEAP', 'PHYS', 4, 4), ('WEAP', 'PHYS', 4, 4)),  # 277 captain
    (('WEAP', 'PHYS', 1, 8),),  # 278 watchman
    (('WEAP', 'PHYS', 3, 4), ('WEAP', 'PHYS', 3, 4)),  # 279 watch captain
    (('WEAP', 'PHYS', 2, 4), ('CLAW', 'PHYS', 1, 8), ('GAZE', 'STON', 0, 0), ('BITE', 'DRST', 1, 6)),  # 280 Medusa
    (('CLAW', 'SAMU', 2, 12), ('MAGC', 'SPEL', 0, 0)),  # 281 Wizard of Yendor
    (('WEAP', 'PHYS', 4, 10),),  # 282 Croesus
    (('TUCH', 'PHYS', 1, 1),),  # 283 ghost
    (('TUCH', 'PLYS', 2, 6), ('TUCH', 'SLOW', 1, 6)),  # 284 shade
    (('WEAP', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3), ('BITE', 'PHYS', 1, 3)),  # 285 water demon
    (('BITE', 'SSEX', 0, 0), ('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3)),  # 286 succubus
    (('WEAP', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('BITE', 'PHYS', 2, 3), ('STNG', 'PHYS', 1, 3)),  # 287 horned devil
    (('BITE', 'SSEX', 0, 0), ('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3)),  # 288 incubus
    (('WEAP', 'DRST', 2, 4),),  # 289 erinys
    (('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4), ('STNG', 'PHYS', 3, 4)),  # 290 barbed devil
    (('WEAP', 'PHYS', 2, 4), ('WEAP', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4)),  # 291 marilith
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 8), ('CLAW', 'PHYS', 1, 8), ('BITE', 'PHYS', 1, 6)),  # 292 vrock
    (('CLAW', 'PHYS', 1, 3), ('CLAW', 'PHYS', 1, 3), ('BITE', 'PHYS', 4, 4)),  # 293 hezrou
    (('WEAP', 'PHYS', 3, 4), ('STNG', 'DRST', 2, 4)),  # 294 bone devil
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('BITE', 'PHYS', 2, 4), ('STNG', 'COLD', 3, 4)),  # 295 ice devil
    (('CLAW', 'PHYS', 1, 4), ('CLAW', 'PHYS', 1, 4), ('BITE', 'PHYS', 2, 4), ('MAGC', 'SPEL', 0, 0)),  # 296 nalfeshnee
    (('WEAP', 'PHYS', 4, 2), ('WEAP', 'PHYS', 4, 2), ('HUGS', 'PHYS', 2, 4)),  # 297 pit fiend
    (('WEAP', 'PHYS', 2, 6), ('WEAP', 'PHYS', 2, 6)),  # 298 sandestin
    (('WEAP', 'PHYS', 8, 4), ('WEAP', 'PHYS', 4, 6)),  # 299 balrog
    (('ENGL', 'DISE', 4, 10), ('SPIT', 'ACID', 3, 6)),  # 300 Juiblex
    (('WEAP', 'PHYS', 3, 6), ('WEAP', 'CONF', 2, 8), ('CLAW', 'PLYS', 1, 6), ('MAGC', 'MAGM', 2, 6)),  # 301 Yeenoghu
    (('WEAP', 'PHYS', 3, 6), ('CLAW', 'PHYS', 3, 4), ('CLAW', 'PHYS', 3, 4), ('MAGC', 'SPEL', 8, 6), ('STNG', 'DRST', 2, 4)),  # 302 Orcus
    (('CLAW', 'PHYS', 3, 6), ('CLAW', 'PHYS', 3, 6), ('STNG', 'DRST', 2, 4)),  # 303 Geryon
    (('WEAP', 'PHYS', 4, 6), ('MAGC', 'SPEL', 6, 6)),  # 304 Dispater
    (('BITE', 'DRST', 2, 6), ('GAZE', 'STUN', 2, 6)),  # 305 Baalzebub
    (('CLAW', 'PHYS', 4, 4), ('MAGC', 'COLD', 6, 6)),  # 306 Asmodeus
    (('MAGC', 'SPEL', 8, 6), ('STNG', 'DRLI', 1, 4), ('CLAW', 'DISE', 1, 6), ('CLAW', 'DISE', 1, 6)),  # 307 Demogorgon
    (('TUCH', 'DETH', 8, 8), ('TUCH', 'DETH', 8, 8)),  # 308 Death
    (('TUCH', 'PEST', 8, 8), ('TUCH', 'PEST', 8, 8)),  # 309 Pestilence
    (('TUCH', 'FAMN', 8, 8), ('TUCH', 'FAMN', 8, 8)),  # 310 Famine
    (('WEAP', 'PHYS', 2, 8),),  # 311 djinni
    (('STNG', 'DRST', 3, 3),),  # 312 jellyfish
    (('BITE', 'PHYS', 2, 6),),  # 313 piranha
    (('BITE', 'PHYS', 5, 6),),  # 314 shark
    (('BITE', 'PHYS', 3, 6), ('TUCH', 'WRAP', 0, 0)),  # 315 giant eel
    (('BITE', 'ELEC', 4, 6), ('TUCH', 'WRAP', 0, 0)),  # 316 electric eel
    (('CLAW', 'PHYS', 2, 4), ('CLAW', 'PHYS', 2, 4), ('HUGS', 'WRAP', 2, 6), ('BITE', 'PHYS', 5, 4)),  # 317 kraken
    (('BITE', 'PHYS', 1, 2),),  # 318 newt
    (('BITE', 'PHYS', 1, 3),),  # 319 gecko
    (('BITE', 'PHYS', 1, 4),),  # 320 iguana
    (('BITE', 'PHYS', 1, 4),),  # 321 baby crocodile
    (('BITE', 'PHYS', 1, 6),),  # 322 lizard
    (('BITE', 'PHYS', 4, 2),),  # 323 chameleon
    (('BITE', 'PHYS', 4, 2), ('CLAW', 'PHYS', 1, 12)),  # 324 crocodile
    (('WEAP', 'PHYS', 2, 8), ('TUCH', 'FIRE', 1, 6), ('HUGS', 'PHYS', 2, 6), ('HUGS', 'FIRE', 3, 6)),  # 325 salamander
    (),  # 326 long worm tail
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 327 archeologist
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 328 barbarian
    (('WEAP', 'PHYS', 2, 4),),  # 329 caveman
    (('WEAP', 'PHYS', 2, 4),),  # 330 cavewoman
    (('WEAP', 'PHYS', 1, 6),),  # 331 healer
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 332 knight
    (('CLAW', 'PHYS', 1, 8), ('KICK', 'PHYS', 1, 8)),  # 333 monk
    (('WEAP', 'PHYS', 1, 6),),  # 334 priest
    (('WEAP', 'PHYS', 1, 6),),  # 335 priestess
    (('WEAP', 'PHYS', 1, 4),),  # 336 ranger
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 337 rogue
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 8)),  # 338 samurai
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 339 tourist
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 8)),  # 340 valkyrie
    (('WEAP', 'PHYS', 1, 6),),  # 341 wizard
    (('WEAP', 'PHYS', 1, 6),),  # 342 Lord Carnarvon
    (('WEAP', 'PHYS', 1, 6),),  # 343 Pelias
    (('WEAP', 'PHYS', 2, 4),),  # 344 Shaman Karnov
    (('WEAP', 'PHYS', 1, 6),),  # 345 Hippocrates
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 346 King Arthur
    (('CLAW', 'PHYS', 4, 10), ('KICK', 'PHYS', 2, 8), ('MAGC', 'CLRC', 2, 8), ('MAGC', 'CLRC', 2, 8)),  # 347 Grand Master
    (('WEAP', 'PHYS', 4, 10), ('KICK', 'PHYS', 2, 8), ('MAGC', 'CLRC', 2, 8), ('MAGC', 'CLRC', 2, 8)),  # 348 Arch Priest
    (('WEAP', 'PHYS', 1, 6),),  # 349 Orion
    (('WEAP', 'PHYS', 2, 6), ('WEAP', 'PHYS', 2, 6), ('CLAW', 'SAMU', 2, 4)),  # 350 Master of Thieves
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 6)),  # 351 Lord Sato
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 352 Twoflower
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 6)),  # 353 Norn
    (('WEAP', 'PHYS', 1, 6), ('MAGC', 'SPEL', 2, 8)),  # 354 Neferet the Green
    (('WEAP', 'PHYS', 8, 4), ('WEAP', 'PHYS', 4, 6), ('MAGC', 'SPEL', 0, 0), ('CLAW', 'SAMU', 2, 6)),  # 355 Minion of Huhetotl
    (('WEAP', 'PHYS', 1, 6), ('MAGC', 'SPEL', 0, 0), ('MAGC', 'SPEL', 0, 0), ('CLAW', 'SAMU', 1, 4)),  # 356 Thoth Amon
    (('BREA', 'RBRE', 6, 6), ('MAGC', 'SPEL', 0, 0), ('CLAW', 'SAMU', 2, 8), ('BITE', 'PHYS', 4, 8), ('BITE', 'PHYS', 4, 8), ('STNG', 'PHYS', 1, 6)),  # 357 Chromatic Dragon
    (('WEAP', 'PHYS', 4, 8), ('WEAP', 'PHYS', 4, 8), ('CLAW', 'SAMU', 2, 6)),  # 358 Cyclops
    (('BREA', 'FIRE', 8, 6), ('BITE', 'PHYS', 4, 8), ('MAGC', 'SPEL', 0, 0), ('CLAW', 'PHYS', 2, 4), ('CLAW', 'SAMU', 2, 4)),  # 359 Ixoth
    (('CLAW', 'PHYS', 16, 2), ('CLAW', 'PHYS', 16, 2), ('MAGC', 'CLRC', 0, 0), ('CLAW', 'SAMU', 1, 4)),  # 360 Master Kaen
    (('WEAP', 'PHYS', 8, 4), ('WEAP', 'PHYS', 4, 6), ('MAGC', 'SPEL', 0, 0), ('CLAW', 'SAMU', 2, 6)),  # 361 Nalzok
    (('CLAW', 'PHYS', 2, 6), ('CLAW', 'SAMU', 2, 6), ('STNG', 'DISE', 1, 4)),  # 362 Scorpius
    (('WEAP', 'DRST', 2, 6), ('WEAP', 'PHYS', 2, 8), ('CLAW', 'SAMU', 2, 6)),  # 363 Master Assassin
    (('WEAP', 'PHYS', 2, 6), ('WEAP', 'PHYS', 2, 6), ('CLAW', 'SAMU', 2, 6)),  # 364 Ashikaga Takauji
    (('WEAP', 'PHYS', 2, 10), ('WEAP', 'PHYS', 2, 10), ('CLAW', 'SAMU', 2, 6)),  # 365 Lord Surtur
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6), ('CLAW', 'SAMU', 1, 4), ('MAGC', 'SPEL', 0, 0)),  # 366 Dark One
    (('WEAP', 'PHYS', 1, 6),),  # 367 student
    (('WEAP', 'PHYS', 1, 6),),  # 368 chieftain
    (('WEAP', 'PHYS', 2, 4),),  # 369 neanderthal
    (('WEAP', 'PHYS', 1, 6),),  # 370 attendant
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 371 page
    (('CLAW', 'PHYS', 8, 2), ('KICK', 'STUN', 3, 2), ('MAGC', 'CLRC', 0, 0)),  # 372 abbot
    (('WEAP', 'PHYS', 1, 6), ('MAGC', 'CLRC', 0, 0)),  # 373 acolyte
    (('WEAP', 'PHYS', 1, 4),),  # 374 hunter
    (('WEAP', 'PHYS', 1, 6), ('WEAP', 'PHYS', 1, 6)),  # 375 thug
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 8)),  # 376 ninja
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 8)),  # 377 roshi
    (('WEAP', 'PHYS', 1, 6), ('MAGC', 'SPEL', 0, 0)),  # 378 guide
    (('WEAP', 'PHYS', 1, 8), ('WEAP', 'PHYS', 1, 8)),  # 379 warrior
    (('WEAP', 'PHYS', 1, 6), ('MAGC', 'SPEL', 0, 0)),  # 380 apprentice
]
ATTACK_TYPES = [tuple(sorted({a[0] for a in row})) for row in ATTACKS]
