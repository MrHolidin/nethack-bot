#!/bin/bash
for r in ran rog; do
  python3 eval.py -n 60 --start 7000 --char $r --kw '{"use_roles": false}' --out roles/ab7_off_$r.jsonl >/dev/null 2>&1
  python3 eval.py -n 60 --start 7000 --char $r --out roles/ab7_on_$r.jsonl >/dev/null 2>&1
  echo "== $r"; python3 compare.py roles/ab7_off_$r.jsonl roles/ab7_on_$r.jsonl 2>/dev/null | head -2
done
echo DONE
