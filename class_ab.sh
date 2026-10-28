#!/bin/bash
OFF='{"role_opts": {"wands": false, "hea_xh": false, "camera": false, "bolt_conserve": false, "arc_pet": false}}'
for r in hea tou wiz arc; do
  python3 eval.py -n 60 --start 6000 --char $r --kw "$OFF" --out roles/cls_off_$r.jsonl >/dev/null 2>&1
  python3 eval.py -n 60 --start 6000 --char $r --out roles/cls_on_$r.jsonl >/dev/null 2>&1
  echo "== $r"; python3 compare.py roles/cls_off_$r.jsonl roles/cls_on_$r.jsonl 2>/dev/null | head -2
done
echo DONE
