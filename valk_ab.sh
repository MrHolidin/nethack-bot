#!/bin/bash
python3 eval.py -n 160 --start 9000 --char val --kw '{"role_opts": {"excal": false}}' --out roles/vx_off.jsonl >/dev/null 2>&1
python3 eval.py -n 160 --start 9000 --char val --out roles/vx_on.jsonl >/dev/null 2>&1
echo DONE
