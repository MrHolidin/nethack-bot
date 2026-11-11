#!/usr/bin/env python3
"""nhdash: a one-page dashboard of the game farm (http://127.0.0.1:8081, reach it by ssh port forwarding).

Queue now, finished runs with the paired comparison against each run's base (`nhq submit --base TAG`), and the
documents of the `auto` branch (auto/STATUS.md ...). Standard library only; the numbers come from nhq.py next to it.
Run:  python nhdash.py [port]      (tmux session nhdash; NHQ_ROOT as for nhq)
"""
import html, json, os, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nhq

DOCS = ["STATUS", "JOURNAL", "PLAN", "BACKLOG"]
PAIRS = {}                                   # (a, b, mtime a, mtime b) -> {name: (mean, lo, hi)}, 80 % CI
DOC_CACHE = {}                               # name -> (time, text)
NEW_PAIRS_PER_PAGE = 12                      # the bootstraps are slow: a page computes a few, the refresh the rest

CSS = """body{font:13px/1.4 system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}
h2{margin:20px 0 6px}table{border-collapse:collapse}td,th{padding:2px 8px;text-align:right;border-bottom:1px solid #ddd}
td.l,th.l{text-align:left}.bar{background:#ddd;width:200px;height:12px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:12px;background:#4a8}.win{background:#cfc}.loss{background:#fcc}.dim{color:#888}
pre{background:#fff;border:1px solid #ddd;padding:8px;white-space:pre-wrap;max-width:110ch}summary{cursor:pointer;font-weight:600}"""


def pair(a, b):
    """J, score and depth of b - a over the shared seeds, with the 80 % CI; cached per pair of files."""
    key = (a, b, os.path.getmtime(os.path.join(nhq.RES, a + ".jsonl")), os.path.getmtime(os.path.join(nhq.RES, b + ".jsonl")))
    if key not in PAIRS:
        A, B = nhq.load(a), nhq.load(b)
        seeds = sorted(set(A) & set(B))
        out = {}
        for name in ("score", "depth", "J"):
            d = [nhq.VALUES[name](B[s]) - nhq.VALUES[name](A[s]) for s in seeds]
            out[name] = (sum(d) / len(d), *nhq.boot(d)) if d else None
        PAIRS[key] = out
    return PAIRS[key]


def cell(v, fmt):
    if v is None:
        return "<td class=dim>-</td>"
    mean, lo, hi = v
    cls = "win" if lo > 0 else "loss" if hi < 0 else ""
    return "<td class='%s' title='80%% CI [%s, %s]'>%s <span class=dim>[%s, %s]</span></td>" % (
        cls, fmt % lo, fmt % hi, fmt % mean, fmt % lo, fmt % hi)


def queue_html():
    try:
        st = json.load(open(os.path.join(nhq.ROOT, "status.json")))
    except (OSError, ValueError):
        return "<p>нет status.json: демон не запущен?</p>"
    age = time.time() - st["t"]
    load = os.getloadavg()[0]
    rows = []
    for j in st["jobs"]:
        pct = 100.0 * j["done"] / j["n"]
        rows.append("<tr><td class=l>%s</td><td>%d</td><td><span class=bar><i style='width:%.0f%%'></i></span></td>"
                    "<td>%d/%d</td><td>%d</td><td>%d</td><td>%ds</td><td class=l>%s %s</td></tr>" % (
                        html.escape(j["tag"]), j["prio"], pct, j["done"], j["n"], j["running"], j["left"], j["age"],
                        j["sha"], html.escape(json.dumps(j["kw"]) if j["kw"] else "")))
    return ("<p>воркеры: <b>%d / %d</b>, load %.0f%s</p><table><tr><th class=l>задача</th><th>prio</th><th></th>"
            "<th>готово</th><th>идут</th><th>в очереди</th><th>возраст</th><th class=l>sha kw</th></tr>%s</table>"
            % (st["busy"], st["workers"], load,
               "  <b style='color:#c00'>статус устарел на %.0f с: демон стоит?</b>" % age if age > 30 else "", "".join(rows)))


def runs_html():
    metas = [m for m in nhq.finished() if m["n"]]
    new, rows = 0, []
    for m in metas[:150]:
        base, cmps = m.get("base"), ["<td class=dim></td>"] * 3
        if base and base != m["tag"] and os.path.exists(os.path.join(nhq.RES, base + ".jsonl")):
            fresh = not any(k[:2] == (base, m["tag"]) for k in PAIRS)
            if fresh and new >= NEW_PAIRS_PER_PAGE:
                cmps = ["<td class=dim>…</td>"] * 3
            else:
                new += fresh
                p = pair(base, m["tag"])
                cmps = [cell(p["score"], "%+.0f"), cell(p["depth"], "%+.2f"), cell(p["J"], "%+.3f")]
        rows.append("<tr><td class=l>%s</td><td>%d</td><td>%.0f</td><td>%.0f</td><td>%.2f</td><td>%d</td><td>%d</td>"
                    "<td>%.0f</td><td>%.0f</td><td class=l>%s</td><td class=l>%s</td><td class=l>%s</td>%s</tr>" % (
                        html.escape(m["tag"]), m["n"], m["score"], m["median"], m["depth"], m["crashes"], m["truncated"],
                        m["steps"], m["secs"], m["sha"], html.escape(json.dumps(m["kw"]) if m["kw"] else ""),
                        html.escape(base or ""), "".join(cmps)))
    return ("<table><tr><th class=l>тег</th><th>n</th><th>score</th><th>медиана</th><th>глубина</th><th>краши</th>"
            "<th>обрезано</th><th>ключей</th><th>сек</th><th class=l>sha</th><th class=l>kw</th><th class=l>база</th>"
            "<th>Δ score</th><th>Δ depth</th><th>Δ J</th></tr>%s</table>" % "".join(rows))


def doc(name):
    t, text = DOC_CACHE.get(name, (0, None))
    if time.time() - t > 30:
        r = subprocess.run(["git", "--git-dir", nhq.GIT, "show", "auto:auto/%s.md" % name], capture_output=True, text=True)
        text = r.stdout if r.returncode == 0 else None
        DOC_CACHE[name] = (time.time(), text)
    return text


def docs_html():
    out = []
    for i, name in enumerate(DOCS):
        text = doc(name)
        if text is not None:
            out.append("<details%s><summary>%s.md</summary><pre>%s</pre></details>" % (" open" if i == 0 else "", name,
                                                                                    html.escape(text)))
    return "".join(out) or "<p class=dim>в ветке auto нет документов</p>"


def page():
    return ("<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=15><title>nh farm</title><style>%s</style>"
            "<h2>Очередь</h2>%s<h2>Завершённые запуски</h2>%s<h2>Документы (ветка auto)</h2>%s"
            "<p class=dim>обновлено %s</p>" % (CSS, queue_html(), runs_html(), docs_html(), time.strftime("%H:%M:%S")))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, code = page().encode(), 200
        except Exception as e:
            body, code = ("<pre>ошибка: %s</pre>" % html.escape(repr(e))).encode(), 500
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
