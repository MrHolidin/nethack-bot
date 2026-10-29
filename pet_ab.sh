#!/bin/bash
for r in arc hea tou; do
  python3 eval.py -n 60 --start 6000 --char $r --kw '{"role_opts": {"pet_recent": false}}' --out roles/pet_off_$r.jsonl >/dev/null 2>&1
  python3 eval.py -n 60 --start 6000 --char $r --out roles/pet_on_$r.jsonl >/dev/null 2>&1
  echo "== $r"; python3 compare.py roles/pet_off_$r.jsonl roles/pet_on_$r.jsonl 2>/dev/null | head -2
  python3 -c "
import json; a=[json.loads(l) for l in open('roles/pet_off_$r.jsonl')]; b=[json.loads(l) for l in open('roles/pet_on_$r.jsonl')]
print('   pet>T1000', sum(1 for x in a if x['pet_last_seen']>1000), '->', sum(1 for x in b if x['pet_last_seen']>1000))"
done
echo DONE
