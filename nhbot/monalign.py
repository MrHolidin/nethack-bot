"""Alignment (maligntyp) of every monster, by permonst index (generated from NetHack 3.6.6 src/monst.c;
NLE does not expose it). A_NONE = -128 (Moloch's: hostile to everyone)."""
ALIGN = [
    0,  # 0 giant ant
    0,  # 1 killer bee
    0,  # 2 soldier ant
    0,  # 3 fire ant
    0,  # 4 giant beetle
    0,  # 5 queen bee
    0,  # 6 acid blob
    0,  # 7 quivering blob
    0,  # 8 gelatinous cube
    0,  # 9 chickatrice
    0,  # 10 cockatrice
    0,  # 11 pyrolisk
    0,  # 12 jackal
    0,  # 13 fox
    0,  # 14 coyote
    -7,  # 15 werejackal
    0,  # 16 little dog
    0,  # 17 dingo
    0,  # 18 dog
    0,  # 19 large dog
    0,  # 20 wolf
    -7,  # 21 werewolf
    -5,  # 22 winter wolf cub
    -5,  # 23 warg
    0,  # 24 winter wolf
    -5,  # 25 hell hound pup
    0,  # 26 hell hound
    0,  # 27 gas spore
    0,  # 28 floating eye
    0,  # 29 freezing sphere
    0,  # 30 flaming sphere
    0,  # 31 shocking sphere
    0,  # 32 kitten
    0,  # 33 housecat
    0,  # 34 jaguar
    0,  # 35 lynx
    0,  # 36 panther
    0,  # 37 large cat
    0,  # 38 tiger
    -9,  # 39 gremlin
    -9,  # 40 gargoyle
    -12,  # 41 winged gargoyle
    6,  # 42 hobbit
    4,  # 43 dwarf
    -6,  # 44 bugbear
    5,  # 45 dwarf lord
    6,  # 46 dwarf king
    -8,  # 47 mind flayer
    -8,  # 48 master mind flayer
    -7,  # 49 manes
    -7,  # 50 homunculus
    -7,  # 51 imp
    -7,  # 52 lemure
    -7,  # 53 quasit
    7,  # 54 tengu
    0,  # 55 blue jelly
    0,  # 56 spotted jelly
    0,  # 57 ochre jelly
    -2,  # 58 kobold
    -3,  # 59 large kobold
    -4,  # 60 kobold lord
    -4,  # 61 kobold shaman
    0,  # 62 leprechaun
    0,  # 63 small mimic
    0,  # 64 large mimic
    0,  # 65 giant mimic
    0,  # 66 wood nymph
    0,  # 67 water nymph
    0,  # 68 mountain nymph
    -3,  # 69 goblin
    -4,  # 70 hobgoblin
    -3,  # 71 orc
    -4,  # 72 hill orc
    -5,  # 73 Mordor orc
    -4,  # 74 Uruk-hai
    -5,  # 75 orc shaman
    -5,  # 76 orc-captain
    0,  # 77 rock piercer
    0,  # 78 iron piercer
    0,  # 79 glass piercer
    0,  # 80 rothe
    -2,  # 81 mumak
    0,  # 82 leocrotta
    0,  # 83 wumpus
    0,  # 84 titanothere
    0,  # 85 baluchitherium
    0,  # 86 mastodon
    0,  # 87 sewer rat
    0,  # 88 giant rat
    0,  # 89 rabid rat
    -7,  # 90 wererat
    0,  # 91 rock mole
    0,  # 92 woodchuck
    0,  # 93 cave spider
    0,  # 94 centipede
    0,  # 95 giant spider
    0,  # 96 scorpion
    0,  # 97 lurker above
    0,  # 98 trapper
    0,  # 99 pony
    7,  # 100 white unicorn
    0,  # 101 gray unicorn
    -7,  # 102 black unicorn
    0,  # 103 horse
    0,  # 104 warhorse
    0,  # 105 fog cloud
    0,  # 106 dust vortex
    0,  # 107 ice vortex
    0,  # 108 energy vortex
    0,  # 109 steam vortex
    0,  # 110 fire vortex
    0,  # 111 baby long worm
    0,  # 112 baby purple worm
    0,  # 113 long worm
    0,  # 114 purple worm
    0,  # 115 grid bug
    0,  # 116 xan
    0,  # 117 yellow light
    0,  # 118 black light
    0,  # 119 zruty
    7,  # 120 couatl
    7,  # 121 Aleax
    12,  # 122 Angel
    15,  # 123 ki-rin
    15,  # 124 Archon
    0,  # 125 bat
    0,  # 126 giant bat
    0,  # 127 raven
    0,  # 128 vampire bat
    0,  # 129 plains centaur
    -1,  # 130 forest centaur
    -3,  # 131 mountain centaur
    0,  # 132 baby gray dragon
    0,  # 133 baby silver dragon
    0,  # 134 baby red dragon
    0,  # 135 baby white dragon
    0,  # 136 baby orange dragon
    0,  # 137 baby black dragon
    0,  # 138 baby blue dragon
    0,  # 139 baby green dragon
    0,  # 140 baby yellow dragon
    4,  # 141 gray dragon
    4,  # 142 silver dragon
    -4,  # 143 red dragon
    -5,  # 144 white dragon
    5,  # 145 orange dragon
    -6,  # 146 black dragon
    -7,  # 147 blue dragon
    6,  # 148 green dragon
    7,  # 149 yellow dragon
    0,  # 150 stalker
    0,  # 151 air elemental
    0,  # 152 fire elemental
    0,  # 153 earth elemental
    0,  # 154 water elemental
    0,  # 155 lichen
    0,  # 156 brown mold
    0,  # 157 yellow mold
    0,  # 158 green mold
    0,  # 159 red mold
    0,  # 160 shrieker
    0,  # 161 violet fungus
    0,  # 162 gnome
    0,  # 163 gnome lord
    0,  # 164 gnomish wizard
    0,  # 165 gnome king
    2,  # 166 giant
    2,  # 167 stone giant
    -2,  # 168 hill giant
    2,  # 169 fire giant
    -3,  # 170 frost giant
    0,  # 171 ettin
    -3,  # 172 storm giant
    9,  # 173 titan
    0,  # 174 minotaur
    0,  # 175 jabberwock
    9,  # 176 Keystone Kop
    10,  # 177 Kop Sergeant
    11,  # 178 Kop Lieutenant
    12,  # 179 Kop Kaptain
    -9,  # 180 lich
    -12,  # 181 demilich
    -15,  # 182 master lich
    -15,  # 183 arch-lich
    -2,  # 184 kobold mummy
    -3,  # 185 gnome mummy
    -4,  # 186 orc mummy
    -4,  # 187 dwarf mummy
    -5,  # 188 elf mummy
    -5,  # 189 human mummy
    -6,  # 190 ettin mummy
    -7,  # 191 giant mummy
    0,  # 192 red naga hatchling
    0,  # 193 black naga hatchling
    0,  # 194 golden naga hatchling
    0,  # 195 guardian naga hatchling
    -4,  # 196 red naga
    4,  # 197 black naga
    5,  # 198 golden naga
    7,  # 199 guardian naga
    -3,  # 200 ogre
    -5,  # 201 ogre lord
    -7,  # 202 ogre king
    0,  # 203 gray ooze
    0,  # 204 brown pudding
    0,  # 205 green slime
    0,  # 206 black pudding
    0,  # 207 quantum mechanic
    0,  # 208 rust monster
    -3,  # 209 disenchanter
    0,  # 210 garter snake
    0,  # 211 snake
    0,  # 212 water moccasin
    0,  # 213 python
    0,  # 214 pit viper
    0,  # 215 cobra
    -3,  # 216 troll
    -3,  # 217 ice troll
    -3,  # 218 rock troll
    -3,  # 219 water troll
    -7,  # 220 Olog-hai
    0,  # 221 umber hulk
    -8,  # 222 vampire
    -9,  # 223 vampire lord
    -10,  # 224 Vlad the Impaler
    -3,  # 225 barrow wight
    -6,  # 226 wraith
    -17,  # 227 Nazgul
    0,  # 228 xorn
    0,  # 229 monkey
    0,  # 230 ape
    0,  # 231 owlbear
    0,  # 232 yeti
    0,  # 233 carnivorous ape
    2,  # 234 sasquatch
    -2,  # 235 kobold zombie
    -2,  # 236 gnome zombie
    -3,  # 237 orc zombie
    -3,  # 238 dwarf zombie
    -3,  # 239 elf zombie
    -3,  # 240 human zombie
    -4,  # 241 ettin zombie
    -2,  # 242 ghoul
    -4,  # 243 giant zombie
    0,  # 244 skeleton
    0,  # 245 straw golem
    0,  # 246 paper golem
    0,  # 247 rope golem
    0,  # 248 gold golem
    0,  # 249 leather golem
    0,  # 250 wood golem
    0,  # 251 flesh golem
    0,  # 252 clay golem
    0,  # 253 stone golem
    0,  # 254 glass golem
    0,  # 255 iron golem
    0,  # 256 human
    -7,  # 257 wererat
    -7,  # 258 werejackal
    -7,  # 259 werewolf
    -3,  # 260 elf
    -5,  # 261 Woodland-elf
    -6,  # 262 Green-elf
    -7,  # 263 Grey-elf
    -9,  # 264 elf-lord
    -10,  # 265 Elvenking
    0,  # 266 doppelganger
    0,  # 267 shopkeeper
    10,  # 268 guard
    0,  # 269 prisoner
    0,  # 270 Oracle
    0,  # 271 aligned priest
    0,  # 272 high priest
    -2,  # 273 soldier
    -3,  # 274 sergeant
    0,  # 275 nurse
    -4,  # 276 lieutenant
    -5,  # 277 captain
    -2,  # 278 watchman
    -4,  # 279 watch captain
    -15,  # 280 Medusa
    -128,  # 281 Wizard of Yendor
    15,  # 282 Croesus
    -5,  # 283 ghost
    0,  # 284 shade
    -7,  # 285 water demon
    -9,  # 286 succubus
    11,  # 287 horned devil
    -9,  # 288 incubus
    10,  # 289 erinys
    8,  # 290 barbed devil
    -12,  # 291 marilith
    -9,  # 292 vrock
    -10,  # 293 hezrou
    -9,  # 294 bone devil
    -12,  # 295 ice devil
    -11,  # 296 nalfeshnee
    -13,  # 297 pit fiend
    -5,  # 298 sandestin
    -14,  # 299 balrog
    -15,  # 300 Juiblex
    -15,  # 301 Yeenoghu
    -20,  # 302 Orcus
    15,  # 303 Geryon
    15,  # 304 Dispater
    20,  # 305 Baalzebub
    20,  # 306 Asmodeus
    -20,  # 307 Demogorgon
    0,  # 308 Death
    0,  # 309 Pestilence
    0,  # 310 Famine
    0,  # 311 djinni
    0,  # 312 jellyfish
    0,  # 313 piranha
    0,  # 314 shark
    0,  # 315 giant eel
    0,  # 316 electric eel
    -3,  # 317 kraken
    0,  # 318 newt
    0,  # 319 gecko
    0,  # 320 iguana
    0,  # 321 baby crocodile
    0,  # 322 lizard
    0,  # 323 chameleon
    0,  # 324 crocodile
    -9,  # 325 salamander
    0,  # 326 long worm tail
    3,  # 327 archeologist
    0,  # 328 barbarian
    1,  # 329 caveman
    1,  # 330 cavewoman
    0,  # 331 healer
    3,  # 332 knight
    0,  # 333 monk
    0,  # 334 priest
    0,  # 335 priestess
    -3,  # 336 ranger
    -3,  # 337 rogue
    3,  # 338 samurai
    0,  # 339 tourist
    -1,  # 340 valkyrie
    0,  # 341 wizard
    20,  # 342 Lord Carnarvon
    0,  # 343 Pelias
    20,  # 344 Shaman Karnov
    0,  # 345 Hippocrates
    20,  # 346 King Arthur
    0,  # 347 Grand Master
    0,  # 348 Arch Priest
    0,  # 349 Orion
    -20,  # 350 Master of Thieves
    20,  # 351 Lord Sato
    0,  # 352 Twoflower
    0,  # 353 Norn
    0,  # 354 Neferet the Green
    -14,  # 355 Minion of Huhetotl
    -14,  # 356 Thoth Amon
    -14,  # 357 Chromatic Dragon
    -15,  # 358 Cyclops
    -14,  # 359 Ixoth
    -20,  # 360 Master Kaen
    -127,  # 361 Nalzok
    -15,  # 362 Scorpius
    18,  # 363 Master Assassin
    -13,  # 364 Ashikaga Takauji
    12,  # 365 Lord Surtur
    -10,  # 366 Dark One
    3,  # 367 student
    0,  # 368 chieftain
    1,  # 369 neanderthal
    3,  # 370 attendant
    3,  # 371 page
    0,  # 372 abbot
    0,  # 373 acolyte
    -7,  # 374 hunter
    -3,  # 375 thug
    3,  # 376 ninja
    3,  # 377 roshi
    0,  # 378 guide
    -1,  # 379 warrior
    0,  # 380 apprentice
]
