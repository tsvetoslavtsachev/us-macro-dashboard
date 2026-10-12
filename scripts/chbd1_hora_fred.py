"""ЧБД1 5.4 (хората): FRED серии за производителност, дял на труда, заетост в софтуер
и BEA инвестиции в софтуер срещу компютри/периферия.

Ползва само https://api.stlouisfed.org/fred/... с FRED_API_KEY от средата.
Печата кратък извод; с --search <текст> търси ID-та.
Изход (по избор): --csv <път> записва редовете (серия, дата, стойност, г/г).
"""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://api.stlouisfed.org/fred/"
KEY = os.environ.get("FRED_API_KEY", "")


def get(endpoint, **params):
    params.update(api_key=KEY, file_type="json")
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def meta(sid):
    s = get("series", series_id=sid)["seriess"][0]
    return s


def obs(sid, start="2022-01-01"):
    o = get("series/observations", series_id=sid, observation_start=start)["observations"]
    return [(x["date"], float(x["value"])) for x in o if x["value"] not in (".", "")]


def yoy(rows, lag):
    out = []
    for i, (d, v) in enumerate(rows):
        g = (v / rows[i - lag][1] - 1) * 100 if i >= lag and rows[i - lag][1] else None
        out.append((d, v, g))
    return out


SERIES = [
    # sid, lag за г/г (4 тримесечия / 12 месеца), бележка
    ("OPHNFB", 4, "производителност, нефинансов бизнес"),
    ("PRS85006173", 4, "дял на труда, нефинансов бизнес"),
    ("CES5051200001", 12, "заетост CES 5051200001 (оказа се филми и звукозапис, не софтуер)"),
    # национална CES серия за софтуерни издатели не се намери във FRED (12.10.2026)
    ("CES6054150001", 12, "заетост, компютърен системен дизайн"),
    ("USINFO", 12, "заетост, информация"),
    # Ramp AI Index (дял на Ramp фирмите с плащане за AI в месеца), във FRED
    ("RAMPAIALL", 12, "Ramp AI, общо"),
    ("RAMPAIOPENAI", 12, "Ramp AI, OpenAI"),
    ("RAMPAIANTHROPIC", 12, "Ramp AI, Anthropic"),
    ("RAMPAIENTERPRISE", 12, "Ramp AI, големи"),
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--search" in sys.argv:
        q = sys.argv[sys.argv.index("--search") + 1]
        res = get("series/search", search_text=q, limit=15, order_by="popularity")
        for s in res["seriess"]:
            print(s["id"], "|", s["title"][:90], "|", s["frequency_short"], s["units_short"][:25], "|", s["observation_end"])
        return
    extra = []
    if "--bea" in sys.argv:
        ids = sys.argv[sys.argv.index("--bea") + 1].split(",")
        extra = [(i, 4, "BEA") for i in ids]
    rows_out = []
    for sid, lag, note in SERIES + extra:
        try:
            m = meta(sid)
            r = yoy(obs(sid), lag)
        except Exception as e:  # noqa
            print(sid, "ГРЕШКА", e)
            continue
        print(f"== {sid} | {m['title'][:80]} | {m['frequency_short']} | {m['units_short'][:30]} | обновена {m['last_updated'][:10]}")
        n = 8 if lag == 4 else 4
        for d, v, g in r[-n:]:
            print(f"   {d}  {v:,.3f}  г/г {'' if g is None else f'{g:+.2f}%'}")
            rows_out.append((sid, m["title"], d, v, g, m["last_updated"][:10]))
    if "--csv" in sys.argv:
        p = sys.argv[sys.argv.index("--csv") + 1]
        with open(p, "w", encoding="utf-8") as f:
            f.write("series,title,date,value,yoy_pct,fred_last_updated\n")
            for sid, t, d, v, g, lu in rows_out:
                f.write(f"{sid},\"{t}\",{d},{v},{'' if g is None else round(g, 2)},{lu}\n")


if __name__ == "__main__":
    main()
