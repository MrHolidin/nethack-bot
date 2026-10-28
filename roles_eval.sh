#!/bin/bash
# usage: roles_eval.sh TAG N START [KW_JSON] [ROLES...]
TAG=$1; N=$2; START=$3; KW=${4:-"{}"}; shift 4
ROLES=${@:-arc bar cav hea kni mon pri ran rog sam tou val wiz}
for r in $ROLES; do
  python3 eval.py -n $N --start $START --char $r --kw "$KW" --out roles/${TAG}_$r.jsonl > roles/${TAG}_$r.txt 2>/dev/null
  echo "$r $(sed -n 2p roles/${TAG}_$r.txt)"
done
echo DONE
