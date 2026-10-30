"""Attack types of every monster, by permonst index (generated from NetHack 3.6.6 src/monst.c)."""
ATTACK_TYPES = [
    ('BITE',),  # 0 giant ant
    ('STNG',),  # 1 killer bee
    ('BITE', 'STNG'),  # 2 soldier ant
    ('BITE',),  # 3 fire ant
    ('BITE',),  # 4 giant beetle
    ('STNG',),  # 5 queen bee
    ('NONE',),  # 6 acid blob
    ('TUCH',),  # 7 quivering blob
    ('NONE', 'TUCH'),  # 8 gelatinous cube
    ('BITE', 'NONE', 'TUCH'),  # 9 chickatrice
    ('BITE', 'NONE', 'TUCH'),  # 10 cockatrice
    ('GAZE',),  # 11 pyrolisk
    ('BITE',),  # 12 jackal
    ('BITE',),  # 13 fox
    ('BITE',),  # 14 coyote
    ('BITE',),  # 15 werejackal
    ('BITE',),  # 16 little dog
    ('BITE',),  # 17 dingo
    ('BITE',),  # 18 dog
    ('BITE',),  # 19 large dog
    ('BITE',),  # 20 wolf
    ('BITE',),  # 21 werewolf
    ('BITE', 'BREA'),  # 22 winter wolf cub
    ('BITE',),  # 23 warg
    ('BITE', 'BREA'),  # 24 winter wolf
    ('BITE', 'BREA'),  # 25 hell hound pup
    ('BITE', 'BREA'),  # 26 hell hound
    ('BOOM',),  # 27 gas spore
    ('NONE',),  # 28 floating eye
    ('EXPL',),  # 29 freezing sphere
    ('EXPL',),  # 30 flaming sphere
    ('EXPL',),  # 31 shocking sphere
    ('BITE',),  # 32 kitten
    ('BITE',),  # 33 housecat
    ('BITE', 'CLAW'),  # 34 jaguar
    ('BITE', 'CLAW'),  # 35 lynx
    ('BITE', 'CLAW'),  # 36 panther
    ('BITE',),  # 37 large cat
    ('BITE', 'CLAW'),  # 38 tiger
    ('BITE', 'CLAW'),  # 39 gremlin
    ('BITE', 'CLAW'),  # 40 gargoyle
    ('BITE', 'CLAW'),  # 41 winged gargoyle
    ('WEAP',),  # 42 hobbit
    ('WEAP',),  # 43 dwarf
    ('WEAP',),  # 44 bugbear
    ('WEAP',),  # 45 dwarf lord
    ('WEAP',),  # 46 dwarf king
    ('TENT', 'WEAP'),  # 47 mind flayer
    ('TENT', 'WEAP'),  # 48 master mind flayer
    ('BITE', 'CLAW'),  # 49 manes
    ('BITE',),  # 50 homunculus
    ('CLAW',),  # 51 imp
    ('CLAW',),  # 52 lemure
    ('BITE', 'CLAW'),  # 53 quasit
    ('BITE',),  # 54 tengu
    ('NONE',),  # 55 blue jelly
    ('NONE',),  # 56 spotted jelly
    ('ENGL', 'NONE'),  # 57 ochre jelly
    ('WEAP',),  # 58 kobold
    ('WEAP',),  # 59 large kobold
    ('WEAP',),  # 60 kobold lord
    ('MAGC',),  # 61 kobold shaman
    ('CLAW',),  # 62 leprechaun
    ('CLAW',),  # 63 small mimic
    ('CLAW',),  # 64 large mimic
    ('CLAW',),  # 65 giant mimic
    ('CLAW',),  # 66 wood nymph
    ('CLAW',),  # 67 water nymph
    ('CLAW',),  # 68 mountain nymph
    ('WEAP',),  # 69 goblin
    ('WEAP',),  # 70 hobgoblin
    ('WEAP',),  # 71 orc
    ('WEAP',),  # 72 hill orc
    ('WEAP',),  # 73 Mordor orc
    ('WEAP',),  # 74 Uruk-hai
    ('MAGC',),  # 75 orc shaman
    ('WEAP',),  # 76 orc-captain
    ('BITE',),  # 77 rock piercer
    ('BITE',),  # 78 iron piercer
    ('BITE',),  # 79 glass piercer
    ('BITE', 'CLAW'),  # 80 rothe
    ('BITE', 'BUTT'),  # 81 mumak
    ('BITE', 'CLAW'),  # 82 leocrotta
    ('BITE',),  # 83 wumpus
    ('CLAW',),  # 84 titanothere
    ('CLAW',),  # 85 baluchitherium
    ('BUTT',),  # 86 mastodon
    ('BITE',),  # 87 sewer rat
    ('BITE',),  # 88 giant rat
    ('BITE',),  # 89 rabid rat
    ('BITE',),  # 90 wererat
    ('BITE',),  # 91 rock mole
    ('BITE',),  # 92 woodchuck
    ('BITE',),  # 93 cave spider
    ('BITE',),  # 94 centipede
    ('BITE',),  # 95 giant spider
    ('CLAW', 'STNG'),  # 96 scorpion
    ('ENGL',),  # 97 lurker above
    ('ENGL',),  # 98 trapper
    ('BITE', 'KICK'),  # 99 pony
    ('BUTT', 'KICK'),  # 100 white unicorn
    ('BUTT', 'KICK'),  # 101 gray unicorn
    ('BUTT', 'KICK'),  # 102 black unicorn
    ('BITE', 'KICK'),  # 103 horse
    ('BITE', 'KICK'),  # 104 warhorse
    ('ENGL',),  # 105 fog cloud
    ('ENGL',),  # 106 dust vortex
    ('ENGL',),  # 107 ice vortex
    ('ENGL', 'NONE'),  # 108 energy vortex
    ('ENGL',),  # 109 steam vortex
    ('ENGL', 'NONE'),  # 110 fire vortex
    ('BITE',),  # 111 baby long worm
    ('BITE',),  # 112 baby purple worm
    ('BITE',),  # 113 long worm
    ('BITE', 'ENGL'),  # 114 purple worm
    ('BITE',),  # 115 grid bug
    ('STNG',),  # 116 xan
    ('EXPL',),  # 117 yellow light
    ('EXPL',),  # 118 black light
    ('BITE', 'CLAW'),  # 119 zruty
    ('BITE', 'HUGS'),  # 120 couatl
    ('KICK', 'WEAP'),  # 121 Aleax
    ('CLAW', 'MAGC', 'WEAP'),  # 122 Angel
    ('BUTT', 'KICK', 'MAGC'),  # 123 ki-rin
    ('CLAW', 'GAZE', 'MAGC', 'WEAP'),  # 124 Archon
    ('BITE',),  # 125 bat
    ('BITE',),  # 126 giant bat
    ('BITE', 'CLAW'),  # 127 raven
    ('BITE',),  # 128 vampire bat
    ('KICK', 'WEAP'),  # 129 plains centaur
    ('KICK', 'WEAP'),  # 130 forest centaur
    ('KICK', 'WEAP'),  # 131 mountain centaur
    ('BITE',),  # 132 baby gray dragon
    ('BITE',),  # 133 baby silver dragon
    ('BITE',),  # 134 baby red dragon
    ('BITE',),  # 135 baby white dragon
    ('BITE',),  # 136 baby orange dragon
    ('BITE',),  # 137 baby black dragon
    ('BITE',),  # 138 baby blue dragon
    ('BITE',),  # 139 baby green dragon
    ('BITE',),  # 140 baby yellow dragon
    ('BITE', 'BREA', 'CLAW'),  # 141 gray dragon
    ('BITE', 'BREA', 'CLAW'),  # 142 silver dragon
    ('BITE', 'BREA', 'CLAW'),  # 143 red dragon
    ('BITE', 'BREA', 'CLAW'),  # 144 white dragon
    ('BITE', 'BREA', 'CLAW'),  # 145 orange dragon
    ('BITE', 'BREA', 'CLAW'),  # 146 black dragon
    ('BITE', 'BREA', 'CLAW'),  # 147 blue dragon
    ('BITE', 'BREA', 'CLAW'),  # 148 green dragon
    ('BITE', 'BREA', 'CLAW'),  # 149 yellow dragon
    ('CLAW',),  # 150 stalker
    ('ENGL',),  # 151 air elemental
    ('CLAW', 'NONE'),  # 152 fire elemental
    ('CLAW',),  # 153 earth elemental
    ('CLAW',),  # 154 water elemental
    ('TUCH',),  # 155 lichen
    ('NONE',),  # 156 brown mold
    ('NONE',),  # 157 yellow mold
    ('NONE',),  # 158 green mold
    ('NONE',),  # 159 red mold
    ('SSEX',),  # 160 shrieker
    ('TUCH',),  # 161 violet fungus
    ('WEAP',),  # 162 gnome
    ('WEAP',),  # 163 gnome lord
    ('MAGC',),  # 164 gnomish wizard
    ('WEAP',),  # 165 gnome king
    ('WEAP',),  # 166 giant
    ('WEAP',),  # 167 stone giant
    ('WEAP',),  # 168 hill giant
    ('WEAP',),  # 169 fire giant
    ('WEAP',),  # 170 frost giant
    ('WEAP',),  # 171 ettin
    ('WEAP',),  # 172 storm giant
    ('MAGC', 'WEAP'),  # 173 titan
    ('BUTT', 'CLAW'),  # 174 minotaur
    ('BITE', 'CLAW'),  # 175 jabberwock
    ('WEAP',),  # 176 Keystone Kop
    ('WEAP',),  # 177 Kop Sergeant
    ('WEAP',),  # 178 Kop Lieutenant
    ('WEAP',),  # 179 Kop Kaptain
    ('MAGC', 'TUCH'),  # 180 lich
    ('MAGC', 'TUCH'),  # 181 demilich
    ('MAGC', 'TUCH'),  # 182 master lich
    ('MAGC', 'TUCH'),  # 183 arch-lich
    ('CLAW',),  # 184 kobold mummy
    ('CLAW',),  # 185 gnome mummy
    ('CLAW',),  # 186 orc mummy
    ('CLAW',),  # 187 dwarf mummy
    ('CLAW',),  # 188 elf mummy
    ('CLAW',),  # 189 human mummy
    ('CLAW',),  # 190 ettin mummy
    ('CLAW',),  # 191 giant mummy
    ('BITE',),  # 192 red naga hatchling
    ('BITE',),  # 193 black naga hatchling
    ('BITE',),  # 194 golden naga hatchling
    ('BITE',),  # 195 guardian naga hatchling
    ('BITE', 'BREA'),  # 196 red naga
    ('BITE', 'SPIT'),  # 197 black naga
    ('BITE', 'MAGC'),  # 198 golden naga
    ('BITE', 'HUGS', 'SPIT'),  # 199 guardian naga
    ('WEAP',),  # 200 ogre
    ('WEAP',),  # 201 ogre lord
    ('WEAP',),  # 202 ogre king
    ('BITE',),  # 203 gray ooze
    ('BITE',),  # 204 brown pudding
    ('NONE', 'TUCH'),  # 205 green slime
    ('BITE', 'NONE'),  # 206 black pudding
    ('CLAW',),  # 207 quantum mechanic
    ('NONE', 'TUCH'),  # 208 rust monster
    ('CLAW', 'NONE'),  # 209 disenchanter
    ('BITE',),  # 210 garter snake
    ('BITE',),  # 211 snake
    ('BITE',),  # 212 water moccasin
    ('BITE', 'HUGS', 'TUCH'),  # 213 python
    ('BITE',),  # 214 pit viper
    ('BITE', 'SPIT'),  # 215 cobra
    ('BITE', 'CLAW', 'WEAP'),  # 216 troll
    ('BITE', 'CLAW', 'WEAP'),  # 217 ice troll
    ('BITE', 'CLAW', 'WEAP'),  # 218 rock troll
    ('BITE', 'CLAW', 'WEAP'),  # 219 water troll
    ('BITE', 'CLAW', 'WEAP'),  # 220 Olog-hai
    ('BITE', 'CLAW', 'GAZE'),  # 221 umber hulk
    ('BITE', 'CLAW'),  # 222 vampire
    ('BITE', 'CLAW'),  # 223 vampire lord
    ('BITE', 'WEAP'),  # 224 Vlad the Impaler
    ('CLAW', 'MAGC', 'WEAP'),  # 225 barrow wight
    ('TUCH',),  # 226 wraith
    ('BREA', 'WEAP'),  # 227 Nazgul
    ('BITE', 'CLAW'),  # 228 xorn
    ('BITE', 'CLAW'),  # 229 monkey
    ('BITE', 'CLAW'),  # 230 ape
    ('CLAW', 'HUGS'),  # 231 owlbear
    ('BITE', 'CLAW'),  # 232 yeti
    ('CLAW', 'HUGS'),  # 233 carnivorous ape
    ('CLAW', 'KICK'),  # 234 sasquatch
    ('CLAW',),  # 235 kobold zombie
    ('CLAW',),  # 236 gnome zombie
    ('CLAW',),  # 237 orc zombie
    ('CLAW',),  # 238 dwarf zombie
    ('CLAW',),  # 239 elf zombie
    ('CLAW',),  # 240 human zombie
    ('CLAW',),  # 241 ettin zombie
    ('CLAW',),  # 242 ghoul
    ('CLAW',),  # 243 giant zombie
    ('TUCH', 'WEAP'),  # 244 skeleton
    ('CLAW',),  # 245 straw golem
    ('CLAW',),  # 246 paper golem
    ('CLAW', 'HUGS'),  # 247 rope golem
    ('CLAW',),  # 248 gold golem
    ('CLAW',),  # 249 leather golem
    ('CLAW',),  # 250 wood golem
    ('CLAW',),  # 251 flesh golem
    ('CLAW',),  # 252 clay golem
    ('CLAW',),  # 253 stone golem
    ('CLAW',),  # 254 glass golem
    ('BREA', 'WEAP'),  # 255 iron golem
    ('WEAP',),  # 256 human
    ('WEAP',),  # 257 wererat
    ('WEAP',),  # 258 werejackal
    ('WEAP',),  # 259 werewolf
    ('WEAP',),  # 260 elf
    ('WEAP',),  # 261 Woodland-elf
    ('WEAP',),  # 262 Green-elf
    ('WEAP',),  # 263 Grey-elf
    ('WEAP',),  # 264 elf-lord
    ('WEAP',),  # 265 Elvenking
    ('WEAP',),  # 266 doppelganger
    ('WEAP',),  # 267 shopkeeper
    ('WEAP',),  # 268 guard
    ('WEAP',),  # 269 prisoner
    ('NONE',),  # 270 Oracle
    ('KICK', 'MAGC', 'WEAP'),  # 271 aligned priest
    ('KICK', 'MAGC', 'WEAP'),  # 272 high priest
    ('WEAP',),  # 273 soldier
    ('WEAP',),  # 274 sergeant
    ('CLAW',),  # 275 nurse
    ('WEAP',),  # 276 lieutenant
    ('WEAP',),  # 277 captain
    ('WEAP',),  # 278 watchman
    ('WEAP',),  # 279 watch captain
    ('BITE', 'CLAW', 'GAZE', 'WEAP'),  # 280 Medusa
    ('CLAW', 'MAGC'),  # 281 Wizard of Yendor
    ('WEAP',),  # 282 Croesus
    ('TUCH',),  # 283 ghost
    ('TUCH',),  # 284 shade
    ('BITE', 'CLAW', 'WEAP'),  # 285 water demon
    ('SSEX',),  # 286 succubus
    ('BITE', 'CLAW', 'STNG', 'WEAP'),  # 287 horned devil
    ('SSEX',),  # 288 incubus
    ('WEAP',),  # 289 erinys
    ('CLAW', 'STNG'),  # 290 barbed devil
    ('CLAW', 'WEAP'),  # 291 marilith
    ('BITE', 'CLAW'),  # 292 vrock
    ('BITE', 'CLAW'),  # 293 hezrou
    ('STNG', 'WEAP'),  # 294 bone devil
    ('BITE', 'CLAW', 'STNG'),  # 295 ice devil
    ('BITE', 'CLAW', 'MAGC'),  # 296 nalfeshnee
    ('HUGS', 'WEAP'),  # 297 pit fiend
    ('WEAP',),  # 298 sandestin
    ('WEAP',),  # 299 balrog
    ('ENGL', 'SPIT'),  # 300 Juiblex
    ('CLAW', 'MAGC', 'WEAP'),  # 301 Yeenoghu
    ('CLAW', 'MAGC', 'STNG', 'WEAP'),  # 302 Orcus
    ('CLAW', 'STNG'),  # 303 Geryon
    ('MAGC', 'WEAP'),  # 304 Dispater
    ('BITE', 'GAZE'),  # 305 Baalzebub
    ('CLAW', 'MAGC'),  # 306 Asmodeus
    ('CLAW', 'MAGC', 'STNG'),  # 307 Demogorgon
    ('TUCH',),  # 308 Death
    ('TUCH',),  # 309 Pestilence
    ('TUCH',),  # 310 Famine
    ('WEAP',),  # 311 djinni
    ('STNG',),  # 312 jellyfish
    ('BITE',),  # 313 piranha
    ('BITE',),  # 314 shark
    ('BITE', 'TUCH'),  # 315 giant eel
    ('BITE', 'TUCH'),  # 316 electric eel
    ('BITE', 'CLAW', 'HUGS'),  # 317 kraken
    ('BITE',),  # 318 newt
    ('BITE',),  # 319 gecko
    ('BITE',),  # 320 iguana
    ('BITE',),  # 321 baby crocodile
    ('BITE',),  # 322 lizard
    ('BITE',),  # 323 chameleon
    ('BITE', 'CLAW'),  # 324 crocodile
    ('HUGS', 'TUCH', 'WEAP'),  # 325 salamander
    ('SSEX',),  # 326 long worm tail
    ('WEAP',),  # 327 archeologist
    ('WEAP',),  # 328 barbarian
    ('WEAP',),  # 329 caveman
    ('WEAP',),  # 330 cavewoman
    ('WEAP',),  # 331 healer
    ('WEAP',),  # 332 knight
    ('CLAW', 'KICK'),  # 333 monk
    ('WEAP',),  # 334 priest
    ('WEAP',),  # 335 priestess
    ('WEAP',),  # 336 ranger
    ('WEAP',),  # 337 rogue
    ('WEAP',),  # 338 samurai
    ('WEAP',),  # 339 tourist
    ('WEAP',),  # 340 valkyrie
    ('WEAP',),  # 341 wizard
    ('WEAP',),  # 342 Lord Carnarvon
    ('WEAP',),  # 343 Pelias
    ('WEAP',),  # 344 Shaman Karnov
    ('WEAP',),  # 345 Hippocrates
    ('WEAP',),  # 346 King Arthur
    ('CLAW', 'KICK', 'MAGC'),  # 347 Grand Master
    ('KICK', 'MAGC', 'WEAP'),  # 348 Arch Priest
    ('WEAP',),  # 349 Orion
    ('CLAW', 'WEAP'),  # 350 Master of Thieves
    ('WEAP',),  # 351 Lord Sato
    ('WEAP',),  # 352 Twoflower
    ('WEAP',),  # 353 Norn
    ('MAGC', 'WEAP'),  # 354 Neferet the Green
    ('CLAW', 'MAGC', 'WEAP'),  # 355 Minion of Huhetotl
    ('CLAW', 'MAGC', 'WEAP'),  # 356 Thoth Amon
    ('BITE', 'BREA', 'CLAW', 'MAGC', 'STNG'),  # 357 Chromatic Dragon
    ('CLAW', 'WEAP'),  # 358 Cyclops
    ('BITE', 'BREA', 'CLAW', 'MAGC'),  # 359 Ixoth
    ('CLAW', 'MAGC'),  # 360 Master Kaen
    ('CLAW', 'MAGC', 'WEAP'),  # 361 Nalzok
    ('CLAW', 'STNG'),  # 362 Scorpius
    ('CLAW', 'WEAP'),  # 363 Master Assassin
    ('CLAW', 'WEAP'),  # 364 Ashikaga Takauji
    ('CLAW', 'WEAP'),  # 365 Lord Surtur
    ('CLAW', 'MAGC', 'WEAP'),  # 366 Dark One
    ('WEAP',),  # 367 student
    ('WEAP',),  # 368 chieftain
    ('WEAP',),  # 369 neanderthal
    ('WEAP',),  # 370 attendant
    ('WEAP',),  # 371 page
    ('CLAW', 'KICK', 'MAGC'),  # 372 abbot
    ('MAGC', 'WEAP'),  # 373 acolyte
    ('WEAP',),  # 374 hunter
    ('WEAP',),  # 375 thug
    ('WEAP',),  # 376 ninja
    ('WEAP',),  # 377 roshi
    ('MAGC', 'WEAP'),  # 378 guide
    ('WEAP',),  # 379 warrior
    ('MAGC', 'WEAP'),  # 380 apprentice
]
