#!/bin/bash
python3 eval.py -n 160 --start 9200 --char val-hum-law-fem --kw '{"role_opts": {"excal": false}}' --out roles/vxl_off.jsonl >/dev/null 2>&1
python3 eval.py -n 160 --start 9200 --char val-hum-law-fem --out roles/vxl_on.jsonl >/dev/null 2>&1
echo DONE
