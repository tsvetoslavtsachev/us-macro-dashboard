"""ЧБД1г Р6 (потребителят): жилището срещу енергията в CPI, PCE, достъпността и анкетите.

Източници (всички четени в сесията на 13.10.2026):
  BLS API v1 (без ключ) за индексите на CPI-U (NSA за г/г и с начало на годината, SA за м/м);
  BLS таблици на тежестите (relative importance), прочетени с WebFetch (curl получава 403),
    затова стойностите са константи по-долу с URL;
  FRED API (FRED_API_KEY): DHUTRC1Q027SBEA, DGOERC1Q027SBEA, PCEC, FIXHAI, MORTGAGE30US;
  BEA плосък файл NipaDataM.txt (apps.bea.gov/national/Release/TXT/) за месечните PCE категории;
  UMich Surveys of Consumers (sca.isr.umich.edu, data.sca.isr.umich.edu, публични таблици);
  NY Fed SCE (frbny-sce-data.xlsx);
  NAR HAI месечен PDF (текстът е изваден с pdftotext -layout в DL/nar_hai.txt).

Употреба:
  python chbd1g_consumer.py <папка_със_свалените> <изходен_csv>
Свалените файлове (NipaDataM.txt, umich_*.xls, umich_home.html, tbm*.csv, sce.xlsx) трябва да са
в <папка_със_свалените>; BLS и FRED се теглят наново (BLS се кешира като bls_*.json там).
Печата кратък извод и записва CSV с колони r, metric, value, unit, as_of, source, url, status, note.
"""
import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
DL = sys.argv[1]
OUT = sys.argv[2]
FRED_KEY = os.environ.get("FRED_API_KEY", "")
R = "Р6"
ROWS = []


def add(metric, value, unit, as_of, source, url, status, note=""):
    ROWS.append(dict(r=R, metric=metric, value=value, unit=unit, as_of=as_of,
                     source=source, url=url, status=status, note=note))


# ---------------------------------------------------------------- BLS
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
# код: (име, тежест дек.2024 [2023 тегла], дек.2025 [2024 тегла], юли 2026 [от табл.1 на CPI за авг.2026])
ITEMS = {
    "SA0":    ("Всички стоки и услуги", 100.0, 100.0, 100.0),
    "SAF1":   ("Храна", 13.691, 13.698, 13.540),
    "SA0E":   ("Енергия", 6.216, 6.383, 7.347),
    "SA0L1E": ("Без храна и енергия (базисен)", 80.094, 79.919, 79.114),
    "SAH1":   ("Подслон", 35.483, 35.625, 35.343),
    "SEHA":   ("Наем на основно жилище", 7.499, 7.840, 7.735),
    "SEHC":   ("Наем, приравнен за собственици (OER)", 26.282, 26.204, 25.918),
    "SEHB":   ("Нощувки извън дома", 1.292, 1.289, None),
    "SAH":    ("Жилище (широко: подслон, комунални, обзавеждане)", 44.201, 44.469, None),
    "SAH21":  ("Енергия за дома (горива + ток и газ)", 3.233, 3.402, None),
    "SACE":   ("Енергийни стоки", 3.122, 3.120, 4.044),
    "SETB":   ("Моторно гориво", 2.983, 2.981, 3.882),
    "SETB01": ("Бензин (всички видове)", 2.902, 2.895, 3.770),
    "SETB02": ("Други моторни горива (вкл. дизел)", 0.081, 0.086, None),
    "SEHE":   ("Горива за дома (мазут и др.)", 0.139, 0.140, None),
    "SEHE01": ("Мазут за отопление", 0.074, 0.083, 0.107),
    "SEHF":   ("Енергийни услуги", 3.094, 3.262, 3.303),
    "SEHF01": ("Електричество", 2.343, 2.489, 2.551),
    "SEHF02": ("Газ по мрежата", 0.750, 0.773, 0.752),
}
# публикувани в табл.1 на CPI за авг.2026: (г/г NSA %, м/м SA %)
PUBLISHED = {
    "SA0": (3.4, 0.4), "SAF1": (2.7, 0.1), "SA0E": (16.3, 2.1), "SACE": (28.0, 4.2),
    "SEHE01": (52.0, 10.1), "SETB": (27.9, 4.1), "SETB01": (27.4, 3.9), "SEHF": (4.0, -0.4),
    "SEHF01": (3.8, -0.2), "SEHF02": (4.4, -1.1), "SA0L1E": (2.4, 0.3), "SAH1": (3.0, 0.3),
    "SEHA": (2.7, 0.2), "SEHC": (3.1, 0.2),
}
URL_RI24 = "https://www.bls.gov/cpi/tables/relative-importance/2024.htm"
URL_RI25 = "https://www.bls.gov/cpi/tables/relative-importance/2025.htm"
URL_T01 = "https://www.bls.gov/news.release/cpi.t01.htm"


def bls(series, tag):
    cache = os.path.join(DL, f"bls_{tag}.json")
    if os.path.exists(cache):
        d = json.load(open(cache, encoding="utf-8"))
    else:
        body = json.dumps({"seriesid": series, "startyear": "2024", "endyear": "2026"}).encode()
        req = urllib.request.Request(BLS_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("status") != "REQUEST_SUCCEEDED":
            raise SystemExit(f"BLS: {d.get('status')} {d.get('message')}")
        json.dump(d, open(cache, "w", encoding="utf-8"))
    out = {}
    for s in d["Results"]["series"]:
        out[s["seriesID"]] = {f"{x['year']}-{x['period'][1:]}": float(x["value"])
                              for x in s["data"] if x["period"].startswith("M") and x["period"] != "M13"
                              and x["value"] not in ("-", "")}
    return out


nsa = bls(["CUUR0000" + k for k in ITEMS], "nsa")
SA_CODES = ["SA0", "SAF1", "SA0E", "SA0L1E", "SAH1", "SEHA", "SEHC", "SACE", "SETB", "SETB01",
            "SEHF", "SEHF01", "SEHF02", "SEHE01", "SETB02"]
sa = bls(["CUSR0000" + k for k in SA_CODES], "sa")

A = nsa["CUUR0000SA0"]
last = max(A)  # най-новият месец
y, m = map(int, last.split("-"))
prev12 = f"{y-1}-{m:02d}"
dec_prev = f"{y-1}-12"
dec_prev2 = f"{y-2}-12"
prevm = f"{y}-{m-1:02d}" if m > 1 else f"{y-1}-12"
print(f"CPI последен месец: {last}; база 12м: {prev12}")
assert last == "2026-08", "очаквах август 2026 като последен (септември излиза на 14.10.2026)"
g1_all = A[dec_prev] / A[prev12] - 1
g2_all = A[last] / A[dec_prev] - 1

cpi = {}
for k, (name, ri24, ri25, ri26) in ITEMS.items():
    s = nsa.get("CUUR0000" + k, {})
    if last not in s:
        print("липсва", k)
        continue
    yoy = (s[last] / s[prev12] - 1) * 100
    ytd = (s[last] / s[dec_prev] - 1) * 100
    # тежест в базовия месец (авг.2025) по тегла 2023: RI_dec24 * (I_t/I_dec24) / (A_t/A_dec24)
    ri_base = ri24 * (s[prev12] / s[dec_prev2]) / (A[prev12] / A[dec_prev2])
    c1 = ri_base / 100 * (s[dec_prev] / s[prev12] - 1)          # авг.25 -> дек.25, тегла 2023
    c2 = ri25 / 100 * (s[last] / s[dec_prev] - 1)               # дек.25 -> авг.26, тегла 2024
    # поправка (проверката на ЧБД1г, 13.10.2026): в индексни точки A_авг26 - A_авг25 =
    # A_авг25 * c1 + A_дек25 * c2, затова приносът е c1 + c2 * A_дек25/A_авг25 = c1 + c2 * (1 + g1);
    # старото c1 * (1 + g2) + c2 също дава верния сбор, но слага кръстосания член на грешния период
    contrib = (c1 + c2 * (1 + g1_all)) * 100                     # п.п. към 12-месечния ръст
    contrib_ytd = c2 * 100 * 1.0                                 # п.п. към ръста от дек.2025
    simple = (ri26 if ri26 else ri25) * yoy / 100
    # проверка на тежестта за юли 2026: RI_dec25 * (I_jul/I_dec25)/(A_jul/A_dec25)
    ri_jul_calc = ri25 * (s[prevm] / s[dec_prev]) / (A[prevm] / A[dec_prev])
    mm = None
    ss = sa.get("CUSR0000" + k)
    if ss and last in ss and prevm in ss:
        mm = (ss[last] / ss[prevm] - 1) * 100
    cpi[k] = dict(name=name, ri24=ri24, ri25=ri25, ri26=ri26, ri_base=ri_base, idx=s[last],
                  idx_prev12=s[prev12], idx_dec=s[dec_prev], yoy=yoy, ytd=ytd, contrib=contrib,
                  contrib_ytd=contrib_ytd, simple=simple, mm=mm, ri_jul_calc=ri_jul_calc)

print("\nкод | тежест юли26 (дек25) | г/г % | м/м SA % | принос г/г п.п. (верижен) | принос от дек.25 п.п. | грубо RI*г/г | RI юли изч.")
for k, c in cpi.items():
    pub = PUBLISHED.get(k)
    flag = ""
    if pub:
        if round(c["yoy"], 1) != pub[0]:
            flag += f" !г/г публ.{pub[0]}"
        if c["mm"] is not None and round(c["mm"], 1) != pub[1]:
            flag += f" !м/м публ.{pub[1]}"
    print(f"{k:7s}| {c['ri26'] if c['ri26'] else '-'} ({c['ri25']}) | {c['yoy']:.2f} | "
          f"{'-' if c['mm'] is None else round(c['mm'], 2)} | {c['contrib']:.3f} | {c['contrib_ytd']:.3f} | "
          f"{c['simple']:.3f} | {c['ri_jul_calc']:.3f}{flag}")
parts = sum(cpi[k]["contrib"] for k in ("SAF1", "SA0E", "SA0L1E"))
print(f"сбор храна+енергия+базисен = {parts:.3f} п.п. срещу общ г/г {cpi['SA0']['yoy']:.3f}")
parts_ytd = sum(cpi[k]["contrib_ytd"] for k in ("SAF1", "SA0E", "SA0L1E"))
print(f"сбор от дек.25 = {parts_ytd:.3f} п.п. срещу общ {cpi['SA0']['ytd']:.3f}")

# месечна траектория на 12-месечните приноси на подслона и енергията през 2026 (верижно)
traj = []
for mon in range(1, m + 1):
    t = f"{y}-{mon:02d}"
    b = f"{y-1}-{mon:02d}"
    g1a = A[dec_prev] / A[b] - 1  # поправка ЧБД1г: вторият период се мащабира с A_дек/A_база
    row = [t]
    for k in ("SAH1", "SA0E", "SETB"):
        s = nsa["CUUR0000" + k]
        ri24 = ITEMS[k][1]
        ri25 = ITEMS[k][2]
        rib = ri24 * (s[b] / s[dec_prev2]) / (A[b] / A[dec_prev2])
        c = (rib / 100 * (s[dec_prev] / s[b] - 1) + ri25 / 100 * (s[t] / s[dec_prev] - 1) * (1 + g1a)) * 100
        row.append(round(c, 3))
        row.append(round((s[t] / s[b] - 1) * 100, 2))
    row.append(round((A[t] / A[b] - 1) * 100, 2))
    traj.append(row)
print("\nмесец | подслон принос, г/г | енергия принос, г/г | моторно гориво принос, г/г | общ г/г")
for r_ in traj:
    print(" | ".join(str(x) for x in r_))

BLS_API_NOTE = "BLS API v1, серия CUUR0000{k} (NSA)"
for k, c in cpi.items():
    nm = c["name"]
    add(f"CPI тежест дек.2025 (тегла 2024): {nm}", round(c["ri25"], 3), "% от CPI", "12.2025",
        "BLS relative importance 2025, табл.1 (2024 Weights)", URL_RI25, "В")
    add(f"CPI тежест дек.2024 (тегла 2023): {nm}", round(c["ri24"], 3), "% от CPI", "12.2024",
        "BLS relative importance 2024, табл.1 (2023 Weights)", URL_RI24, "В", "база за верижния принос")
    if c["ri26"]:
        add(f"CPI тежест юли 2026: {nm}", c["ri26"], "% от CPI", "07.2026",
            "BLS CPI release авг.2026, табл.1", URL_T01, "В",
            f"проверка: RI дек.25 x (I юли/I дек.25)/(A юли/A дек.25) = {c['ri_jul_calc']:.3f}")
    add(f"CPI индекс NSA авг.2026: {nm}", c["idx"], "1982-84=100", "08.2026",
        BLS_API_NOTE.format(k=k), BLS_URL + "CUUR0000" + k, "В")
    add(f"CPI индекс NSA авг.2025: {nm}", c["idx_prev12"], "1982-84=100", "08.2025",
        BLS_API_NOTE.format(k=k), BLS_URL + "CUUR0000" + k, "В")
    add(f"CPI индекс NSA дек.2025: {nm}", c["idx_dec"], "1982-84=100", "12.2025",
        BLS_API_NOTE.format(k=k), BLS_URL + "CUUR0000" + k, "В")
    pub = PUBLISHED.get(k)
    add(f"CPI г/г авг.2026: {nm}", round(c["yoy"], 2), "%", "08.2026",
        "изчислено от индексите NSA (BLS API)", BLS_URL + "CUUR0000" + k, "Х",
        "I авг.26 / I авг.25 - 1" + (f"; BLS табл.1 публикува {pub[0]} (В)" if pub else ""))
    if c["mm"] is not None:
        ss_k = sa["CUSR0000" + k]
        ytd_sa = (ss_k[last] / ss_k[dec_prev] - 1) * 100
        print(f"  {k}: ръст от дек.25 SA {ytd_sa:.2f}% (NSA {c['ytd']:.2f}%), принос SA ~ {c['ri25'] * ytd_sa / 100:.3f} п.п.")
        add(f"CPI ръст от дек.2025 до авг.2026, SA: {nm}", round(ytd_sa, 2), "%", "08.2026",
            "изчислено от индексите SA (BLS API CUSR0000" + k + ")", BLS_URL + "CUSR0000" + k, "Х", "I_SA авг.26 / I_SA дек.25 - 1")
        add(f"CPI принос към ръста от дек.2025, SA (приближение): {nm}", round(c["ri25"] * ytd_sa / 100, 3), "п.п.",
            "08.2026", "изчислено (RI дек.2025 x ръст SA)", URL_RI25, "Х", "без сезонния ефект на NSA; приближение")
        ri_m = c["ri26"] if c["ri26"] else c["ri_jul_calc"]
        add(f"CPI принос към м/м SA авг.2026 (приближение): {nm}", round(ri_m * c["mm"] / 100, 3), "п.п.", "08.2026",
            "изчислено (тежест юли 2026 x м/м SA)", URL_T01, "Х",
            "RI_юли26 x м/м/100; приближение (SA индексите не се сумират точно)")
        add(f"CPI м/м SA авг.2026: {nm}", round(c["mm"], 2), "%", "08.2026",
            "изчислено от индексите SA (BLS API CUSR0000" + k + ")", BLS_URL + "CUSR0000" + k, "Х",
            "I авг.26 / I юли 26 - 1" + (f"; BLS табл.1 публикува {pub[1]} (В)" if pub else ""))
    add(f"CPI принос към г/г авг.2026: {nm}", round(c["contrib"], 3), "п.п.", "08.2026",
        "изчислено (верижно, тежести BLS)", URL_RI25, "Х",
        "c1=RI_авг25*(I_дек25/I_авг25-1), RI_авг25=RI_дек24*(I_авг25/I_дек24)/(A_авг25/A_дек24); "
        "c2=RI_дек25*(I_авг26/I_дек25-1); принос=(c1+c2*A_дек25/A_авг25)*100 (поправено от проверката)")
    add(f"CPI принос към ръста от дек.2025 до авг.2026: {nm}", round(c["contrib_ytd"], 3), "п.п.", "08.2026",
        "изчислено (RI дек.2025 x ръст от дек.2025)", URL_RI25, "Х", "RI_дек25*(I_авг26/I_дек25-1)")
    add(f"CPI ръст от дек.2025 до авг.2026: {nm}", round(c["ytd"], 2), "%", "08.2026",
        "изчислено от индексите NSA (BLS API)", BLS_URL + "CUUR0000" + k, "Х", "I авг.26 / I дек.25 - 1")
for r_ in traj:
    add(f"CPI принос към г/г, подслон, {r_[0]}", r_[1], "п.п.", r_[0], "изчислено (верижно)", URL_RI25, "Х",
        f"г/г подслон {r_[2]}%")
    add(f"CPI принос към г/г, енергия, {r_[0]}", r_[3], "п.п.", r_[0], "изчислено (верижно)", URL_RI25, "Х",
        f"г/г енергия {r_[4]}%")
    add(f"CPI принос към г/г, моторно гориво, {r_[0]}", r_[5], "п.п.", r_[0], "изчислено (верижно)", URL_RI25,
        "Х", f"г/г моторно гориво {r_[6]}%; общ CPI г/г {r_[7]}%")
add("CPI за септември 2026: дата на излизане", "14.10.2026", "дата", "13.10.2026",
    "BLS календар, октомври 2026", "https://www.bls.gov/schedule/2026/10_sched.htm", "В",
    "към 13.10.2026 последният публикуван месец е август 2026")


# ---------------------------------------------------------------- FRED
def fred(sid, start):
    q = urllib.parse.urlencode(dict(series_id=sid, observation_start=start, api_key=FRED_KEY, file_type="json"))
    with urllib.request.urlopen("https://api.stlouisfed.org/fred/series/observations?" + q, timeout=60) as r:
        o = json.loads(r.read().decode("utf-8"))["observations"]
    return [(x["date"], float(x["value"])) for x in o if x["value"] not in (".", "")]


FRED_U = "https://fred.stlouisfed.org/series/"
q_hu = dict(fred("DHUTRC1Q027SBEA", "2019-01-01"))
q_ge = dict(fred("DGOERC1Q027SBEA", "2019-01-01"))
q_pce = dict(fred("PCEC", "2019-01-01"))
lq = max(q_pce)
print(f"\nPCE последно тримесечие: {lq}")
for lab, qs in (("последно", [lq]), ("2021 средно", [d for d in q_pce if d.startswith("2021")]),
                ("2019 средно", [d for d in q_pce if d.startswith("2019")])):
    hu = sum(q_hu[d] for d in qs) / len(qs)
    ge = sum(q_ge[d] for d in qs) / len(qs)
    pc = sum(q_pce[d] for d in qs) / len(qs)
    print(f"  {lab}: жилище+комунални {hu:.1f} ({hu/pc*100:.2f}%), бензин и енергийни стоки {ge:.1f} "
          f"({ge/pc*100:.2f}%), PCE {pc:.1f}")
    tag = lq if lab == "последно" else lab
    add(f"PCE жилище и комунални, {tag}", round(hu, 1), "$ млрд SAAR", tag, "BEA през FRED DHUTRC1Q027SBEA",
        FRED_U + "DHUTRC1Q027SBEA", "В" if lab == "последно" else "Х",
        "" if lab == "последно" else "средно от 4-те тримесечия")
    add(f"PCE бензин и други енергийни стоки, {tag}", round(ge, 1), "$ млрд SAAR", tag,
        "BEA през FRED DGOERC1Q027SBEA", FRED_U + "DGOERC1Q027SBEA", "В" if lab == "последно" else "Х",
        "" if lab == "последно" else "средно от 4-те тримесечия")
    add(f"PCE общо, {tag}", round(pc, 1), "$ млрд SAAR", tag, "BEA през FRED PCEC", FRED_U + "PCEC",
        "В" if lab == "последно" else "Х", "" if lab == "последно" else "средно от 4-те тримесечия")
    add(f"Дял на жилище и комунални в PCE, {tag}", round(hu / pc * 100, 2), "%", tag, "изчислено", FRED_U + "PCEC",
        "Х", "DHUTRC1Q027SBEA / PCEC")
    add(f"Дял на бензин и енергийни стоки в PCE, {tag}", round(ge / pc * 100, 2), "%", tag, "изчислено",
        FRED_U + "PCEC", "Х", "DGOERC1Q027SBEA / PCEC")

# BEA месечни (плосък файл)
BEA_U = "https://apps.bea.gov/national/Release/TXT/NipaDataM.txt"
CODES = {"DPCERC": "PCE общо", "DHUTRC": "Жилище и комунални", "DHSGRC": "Жилище (без комунални)",
         "DUTLRC": "Комунални за дома", "DELGRC": "Електричество и газ", "DGOERC": "Бензин и други енергийни стоки",
         "DMFLRC": "Моторни горива, смазки", "DFULRC": "Мазут и други горива"}
bea = {c: {} for c in CODES}
with open(os.path.join(DL, "NipaDataM.txt"), encoding="utf-8", errors="replace") as f:
    for line in f:
        p = line.split(",", 2)
        if p[0] in bea:
            bea[p[0]][p[1]] = float(p[2].strip().strip('"').replace(",", ""))
lm = max(bea["DPCERC"])
ly, lmo = lm.split("M")
pm = f"{int(ly)-1}M{lmo}"
print(f"\nBEA месечно последно: {lm}")
for per_lab, pers in ((lm, [lm]), (pm, [pm]), ("2021 средно", [f"2021M{i:02d}" for i in range(1, 13)]),
                      ("2019 средно", [f"2019M{i:02d}" for i in range(1, 13)])):
    tot = sum(bea["DPCERC"][p] for p in pers) / len(pers)
    line = [per_lab]
    for c, nm in CODES.items():
        v = sum(bea[c][p] for p in pers) / len(pers)
        sh = v / tot * 100
        line.append(f"{c} {v/1000:.1f} ({sh:.2f}%)")
        st = "В" if len(pers) == 1 else "Х"
        add(f"PCE месечно {nm}, {per_lab}", round(v / 1000, 1), "$ млрд SAAR", per_lab,
            f"BEA NIPA плосък файл, код {c} (табл. 2.4.5U)", BEA_U, st,
            "файлът е в $ млн; /1000" + ("" if len(pers) == 1 else "; средно от 12 месеца"))
        if c != "DPCERC":
            add(f"Дял в PCE: {nm}, {per_lab}", round(sh, 2), "%", per_lab, "изчислено", BEA_U, "Х", f"{c}/DPCERC")
    en = sum(bea["DGOERC"][p] + bea["DELGRC"][p] for p in pers) / len(pers)
    add(f"Дял в PCE: енергия общо (DGOERC+DELGRC), {per_lab}", round(en / tot * 100, 2), "%", per_lab,
        "изчислено", BEA_U, "Х", "(DGOERC + DELGRC)/DPCERC")
    line.append(f"енергия общо {en/1000:.1f} ({en/tot*100:.2f}%)")
    print("  " + " | ".join(line))
# долари отгоре за година
for c in ("DHSGRC", "DHUTRC", "DGOERC", "DELGRC", "DPCERC"):
    d = (bea[c][lm] - bea[c][pm]) / 1000
    gg = (bea[c][lm] / bea[c][pm] - 1) * 100
    print(f"  {c}: +{d:.1f} млрд SAAR г/г ({gg:.2f}%)")
    add(f"PCE промяна г/г {lm} срещу {pm}: {CODES[c]}", round(d, 1), "$ млрд SAAR", lm, "изчислено", BEA_U, "Х",
        f"{c} {lm} - {pm}; г/г {gg:.2f}%")
en_now = bea["DGOERC"][lm] + bea["DELGRC"][lm]
en_prev = bea["DGOERC"][pm] + bea["DELGRC"][pm]
print(f"  енергия общо: +{(en_now-en_prev)/1000:.1f} млрд г/г ({(en_now/en_prev-1)*100:.2f}%)")
add(f"PCE промяна г/г {lm} срещу {pm}: енергия общо (DGOERC+DELGRC)", round((en_now - en_prev) / 1000, 1),
    "$ млрд SAAR", lm, "изчислено", BEA_U, "Х", f"г/г {(en_now/en_prev-1)*100:.2f}%")

# достъпност
hai = fred("FIXHAI", "1981-01-01")
print("\nFIXHAI (FRED дава само последните 13 месеца):", hai[0], "...", hai[-3:])
for d_, v_ in hai:
    add("NAR HAI (fixed), версия FRED", v_, "индекс (100 = медианният доход точно стига)", d_, "NAR през FRED FIXHAI",
        FRED_U + "FIXHAI", "В", "FRED пази само последните 13 месеца; стойностите може да са преди ревизия")
mn = min(hai, key=lambda x: x[1])
add("NAR HAI (FRED): минимум в наличните месеци", mn[1], "индекс", mn[0], "NAR през FRED FIXHAI", FRED_U + "FIXHAI",
    "Х", f"мин. от {hai[0][0]} до {hai[-1][0]}")

# NAR PDF (месечен HAI, публ. 13.10.2026), текст от pdftotext -layout в DL/nar_hai.txt
NAR_U = "https://www.nar.realtor/sites/default/files/2026-10/hai-09-2026-housing-affordability-index-2026-10-13.pdf"
MON = dict(Jan="01", Feb="02", Mar="03", Apr="04", May="05", Jun="06", Jul="07", Aug="08", Sep="09", Oct="10",
           Nov="11", Dec="12")
nar_txt = re.sub(r"[ \t]+", " ",open(os.path.join(DL, "nar_hai.txt"), encoding="latin-1").read())
nar = {}
for line in nar_txt.splitlines():
    line = line.strip()
    mo = re.match(r"^(\d{4})(?: (\w{3}))?(?: ([pr]))? ([\d,]{7}) ([\d.]+)(?: ([\d,]{4,5}))? ([\d.]+) ([\d,]+) ([\d,]+) "
                  r"([\d.]+)$", line)
    if not mo:
        continue
    yr, mon, flag, price, rate, pmt, share, inc, qinc, idx = mo.groups()
    per = f"{yr}-{MON[mon]}" if mon else f"{yr} (година)"
    nar[per] = dict(price=float(price.replace(",", "")), rate=float(rate), share=float(share),
                    inc=float(inc.replace(",", "")), qinc=float(qinc.replace(",", "")), idx=float(idx), flag=flag or "")
print("NAR PDF редове:", len(nar), "; последен:", max(k for k in nar if "година" not in k))
for per, v in nar.items():
    fl = {"p": " (предварителен)", "r": " (ревизиран)"}.get(v["flag"], "")
    add(f"NAR HAI (fixed), PDF{fl}", v["idx"], "индекс", per, "NAR Housing Affordability Index, месечен PDF (13.10.2026)",
        NAR_U, "В")
    if per in ("2026-09", "2025-09", "2026-01", "2026-06"):
        add(f"NAR: медианна цена на съществуващо еднофамилно жилище{fl}", v["price"], "$", per, "NAR HAI PDF", NAR_U, "В")
        add(f"NAR: ефективна ипотечна лихва в HAI{fl}", v["rate"], "%", per, "NAR HAI PDF (FHFA/Freddie Mac)", NAR_U, "В")
        add(f"NAR: вноска (главница+лихва) като % от медианния семеен доход{fl}", v["share"], "%", per, "NAR HAI PDF",
            NAR_U, "В")
        add(f"NAR: медианен семеен доход{fl}", v["inc"], "$", per, "NAR HAI PDF (проекция на NAR)", NAR_U, "В")
        add(f"NAR: нужен доход за медианното жилище{fl}", v["qinc"], "$", per, "NAR HAI PDF", NAR_U, "В")
        add(f"Цена/доход: медианна цена / медианен семеен доход (NAR){fl}", round(v["price"] / v["inc"], 2), "пъти",
            per, "изчислено от NAR HAI PDF", NAR_U, "Х", "медианна цена / медианен семеен доход")
fred_d = dict(hai)
for per, v in nar.items():
    fv = fred_d.get(per + "-01")
    if fv is not None and abs(fv - v["idx"]) > 0.05:
        print(f"  разминаване {per}: FRED {fv} срещу NAR PDF {v['idx']}")

mort = fred("MORTGAGE30US", "1971-01-01")
md, mv = mort[-1]
print("\nMORTGAGE30US последни:", mort[-4:])
add("Ипотека 30г фиксирана (Freddie Mac PMMS)", mv, "%", md, "FRED MORTGAGE30US", FRED_U + "MORTGAGE30US", "В",
    "описът, ред 332: 7,40 (08.10)")
# текущата серия над прага и предишния път
i = len(mort) - 1
while i > 0 and mort[i - 1][1] >= mv:
    i -= 1
run_start = mort[i][0]
before = [x for x in mort[:i] if x[1] >= mv]
print("текуща серия >= текущото от", run_start, "; предишно >= :", before[-1] if before else None)
add("Ипотека 30г: начало на текущата поредица от седмици >= текущото ниво", run_start, "дата", md,
    "изчислено от FRED MORTGAGE30US", FRED_U + "MORTGAGE30US", "Х")
if before:
    add("Ипотека 30г: последната седмица преди тази поредица със стойност >= текущото", before[-1][1], "%",
        before[-1][0], "FRED MORTGAGE30US", FRED_U + "MORTGAGE30US", "Х",
        f"преди {run_start} последно >= {mv} на {before[-1][0]}")
y2026 = [x for x in mort if x[0].startswith("2026")]
mn26 = min(y2026, key=lambda x: x[1])
mx26 = max(y2026, key=lambda x: x[1])
print("2026 мин/макс:", mn26, mx26)
add("Ипотека 30г: минимум 2026", mn26[1], "%", mn26[0], "FRED MORTGAGE30US", FRED_U + "MORTGAGE30US", "Х")
add("Ипотека 30г: максимум 2026", mx26[1], "%", mx26[0], "FRED MORTGAGE30US", FRED_U + "MORTGAGE30US", "Х")
yago_m = [x for x in mort if x[0] <= f"{int(md[:4])-1}{md[4:]}"][-1]
add("Ипотека 30г: година по-рано", yago_m[1], "%", yago_m[0], "FRED MORTGAGE30US", FRED_U + "MORTGAGE30US", "В")
mx_all_after2000 = max([x for x in mort if x[0] >= "2001"], key=lambda x: x[1])
add("Ипотека 30г: максимум от 2001 насам", mx_all_after2000[1], "%", mx_all_after2000[0], "FRED MORTGAGE30US",
    FRED_U + "MORTGAGE30US", "Х")
print("макс от 2001:", mx_all_after2000, "година по-рано:", yago_m)

# ---------------------------------------------------------------- UMich
import xlrd  # noqa: E402

UM = "https://www.sca.isr.umich.edu/"
home = open(os.path.join(DL, "umich_home.html"), encoding="utf-8", errors="replace").read()
home_t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", home, flags=re.S)))
mprel = re.search(r"Preliminary Results for (\w+ \d{4})", home_t).group(1)
for lab, bg in (("Index of Consumer Sentiment", "UMich настроение (ICS)"),
                ("Current Economic Conditions", "UMich текущи условия (ICC)"),
                ("Index of Consumer Expectations", "UMich очаквания (ICE)")):
    mm_ = re.search(re.escape(lab) + r" ([\d.]+) ([\d.]+) ([\d.]+)", home_t)
    print(f"UMich {lab}: {mm_.groups()} ({mprel} предв., пред. месец, година по-рано)")
    add(f"{bg}, {mprel} предварителни", float(mm_.group(1)), "индекс", "10.2026 (публ. 09.10.2026)",
        "UMich Surveys of Consumers, начална страница", UM, "В", "W41 ред 123 пише 46,3 (П): съвпада")
    add(f"{bg}, септември 2026 окончателни", float(mm_.group(2)), "индекс", "09.2026",
        "UMich Surveys of Consumers, начална страница", UM, "В")
    add(f"{bg}, октомври 2025", float(mm_.group(3)), "индекс", "10.2025",
        "UMich Surveys of Consumers, начална страница", UM, "В")
for lab, bg in (("Year-ahead inflation expectations ticked up from ([\\d.]+)% last month to ([\\d.]+)%",
                 "UMich очаквана инфлация 1 г."),
                ("Long-run inflation expectations also stepped up from ([\\d.]+)% in September to ([\\d.]+)%",
                 "UMich очаквана инфлация 5-10 г.")):
    mm_ = re.search(lab, home_t)
    print(bg, mm_.groups())
    add(f"{bg}, {mprel} предварителни", float(mm_.group(2)), "%", "10.2026 (публ. 09.10.2026)",
        "UMich, начална страница (текст на директора)", UM, "В", "W41 ред 123: 4,7% (П), съвпада")
    add(f"{bg}, септември 2026", float(mm_.group(1)), "%", "09.2026", "UMich, начална страница", UM, "В")

TBL = "https://data.sca.isr.umich.edu/tables.php"


def umt(n):
    s = xlrd.open_workbook(os.path.join(DL, f"umich_t{n}.xls")).sheet_by_index(0)
    rows = [s.row_values(r) for r in range(s.nrows)]
    mon_r = next(i for i, r in enumerate(rows) if r[2] in ("Aug", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                                                             "Sep", "Oct", "Nov", "Dec"))
    cols = [f"{rows[mon_r+1][j]:.0f}-{rows[mon_r][j]}" for j in range(2, len(rows[mon_r]))]
    return rows, cols


def pct(v):
    return float(str(v).replace("%", ""))


for n, picks in (("39", [("INCREASE", "очакват поскъпване на бензина за 1 г.", "% от анкетираните"),
                         ("MEDIAN INCREASE (¢)", "медианно очаквано поскъпване на бензина за 1 г.", "цента/галон"),
                         ("MEAN INCREASE (¢)", "средно очаквано поскъпване на бензина за 1 г.", "цента/галон")]),
                 ("41", [("GOOD TIME TO BUY", "добро време за купуване на жилище", "% от анкетираните"),
                         ("BAD TIME TO BUY", "лошо време за купуване на жилище", "% от анкетираните"),
                         ("INDEX SCORE", "индекс на условията за купуване на жилище", "индекс")]),
                 ("42", [("Prices are high", "причина „лошо време“: цените са високи", "% от анкетираните"),
                         (" credit is tight", "причина „лошо време“: лихвите са високи, кредитът е труден",
                          "% от анкетираните"),
                         (" can't afford to buy", "причина „лошо време“: не можем да си позволим", "% от анкетираните")]),
                 ("46", [("INCREASE", "очакват поскъпване на жилищата за 1 г.", "% от анкетираните"),
                         ("DECREASE", "очакват поевтиняване на жилищата за 1 г.", "% от анкетираните")])):
    rows, cols = umt(n)
    for key, bg, unit in picks:
        r_ = next(r for r in rows if str(r[0]) == key)
        vals = [pct(v) for v in r_[2:2 + len(cols)]]
        print(f"UMich T{n} {key}: {cols[0]}={vals[0]} {cols[7]}={vals[7]} {cols[-1]}={vals[-1]}")
        for j in (0, 6, 7, len(cols) - 1):
            add(f"UMich табл.{n}: {bg}", vals[j], unit, cols[j], f"UMich Surveys of Consumers, табл.{n} (YB, публична)",
                TBL, "В", "последният публичен месец в детайлните таблици е август 2026")

gas_rep = "https://data.sca.isr.umich.edu/fetchdoc.php?docid=82236"
for v, lab in ((31, "ще харчат както обикновено"), (54, "ще намалят покупките"), (16, "ще спрат покупките")):
    add(f"UMich специален доклад „Gasoline Prices and Expected Consumer Spending“: за поскъпналите стоки {lab}",
        v, "% от анкетираните", "23.06-21.09.2026 (публ. 09.10.2026)", "UMich, Joanne Hsu, табл.1", gas_rep, "В",
        "3 492 интервюта")

# ---------------------------------------------------------------- NY Fed SCE
import openpyxl  # noqa: E402

SCE = "https://www.newyorkfed.org/microeconomics/sce"
wb = openpyxl.load_workbook(os.path.join(DL, "sce.xlsx"), read_only=True, data_only=True)


def sce_sheet(name):
    rows = list(wb[name].iter_rows(values_only=True))
    hdr = rows[3]
    data = {str(r[0]): r for r in rows if r[0] is not None and str(r[0]).isdigit()}
    return hdr, data


for name, cols in (("Inflation expectations", [(1, "очаквана инфлация 1 г. (медиана)"),
                                               (2, "очаквана инфлация 3 г. (медиана)")]),
                   ("Home price expectations", [(1, "очакван ръст на цените на жилищата за 1 г. (медиана)")]),
                   ("Commodity expectations", [(1, "очакван ръст на цената на бензина за 1 г. (медиана)"),
                                               (2, "очакван ръст на цената на храната за 1 г. (медиана)"),
                                               (3, "очакван ръст на медицинските разходи за 1 г. (медиана)"),
                                               (5, "очакван ръст на наемите за 1 г. (медиана)")])):
    hdr, data = sce_sheet(name)
    lastk = max(data)
    for j, bg in cols:
        for per in (lastk, "202608", "202602", "202509"):
            v = data[per][j]
            add(f"NY Fed SCE: {bg}", round(float(v), 2), "%", f"{per[4:]}.{per[:4]}",
                f"NY Fed SCE, frbny-sce-data.xlsx, лист „{name}“, колона „{hdr[j]}“", SCE, "В")
        print(f"SCE {bg}: {lastk}={data[lastk][j]:.2f} 202608={data['202608'][j]:.2f} "
              f"202602={data['202602'][j]:.2f} 202509={data['202509'][j]:.2f}")

# ---------------------------------------------------------------- от описа (без нова проверка)
INV = r"C:\Projects\media\videos\work\2026-10-chipove-bondove-dizel\DANNI-INVENTAR.md"
add("Дизел на дребно, САЩ (No 2, седмична)", 6.20, "$/галон", "05.10.2026", "EIA xls EMD_EPD2D_PTE_NUS_DPG (описът, ред 782)",
    INV, "В", "статус от описа; г/г +67,04%; година по-рано 3,71")
add("Бензин regular на дребно, САЩ (седмична)", 4.35, "$/галон", "05.10.2026",
    "EIA xls EMM_EPMR_PTE_NUS_DPG (описът, ред 783)", INV, "В", "статус от описа; г/г +39,37%; година по-рано 3,12")

# ---------------------------------------------------------------- съотношения за присъдата
sh, en, mf = cpi["SAH1"], cpi["SA0E"], cpi["SETB"]
for metric, val, note in (
        ("Съотношение тежест подслон / енергия (юли 2026)", sh["ri26"] / en["ri26"], "35,343 / 7,347"),
        ("Съотношение тежест подслон / енергия (дек.2025)", sh["ri25"] / en["ri25"], "35,625 / 6,383"),
        ("Съотношение г/г ръст енергия / подслон (авг.2026)", en["yoy"] / sh["yoy"], "г/г енергия / г/г подслон"),
        ("Съотношение принос към г/г подслон / енергия (авг.2026)", sh["contrib"] / en["contrib"], "верижни приноси"),
        ("Дял на подслона в 12-месечния CPI (авг.2026)", sh["contrib"] / cpi["SA0"]["yoy"] * 100, "% от 3,40"),
        ("Дял на енергията в 12-месечния CPI (авг.2026)", en["contrib"] / cpi["SA0"]["yoy"] * 100, "% от 3,40"),
        ("Дял на моторното гориво в 12-месечния CPI (авг.2026)", mf["contrib"] / cpi["SA0"]["yoy"] * 100, "% от 3,40")):
    print(f"{metric}: {val:.2f}")
    add(metric, round(val, 2), "пъти" if "Съотношение" in metric else "%", "08.2026", "изчислено", URL_RI25, "Х", note)
pce_ratio = bea["DHSGRC"][lm] / (bea["DGOERC"][lm] + bea["DELGRC"][lm])
print(f"PCE жилище / енергия общо {lm}: {pce_ratio:.2f}")
add(f"Съотношение в PCE: жилище (без комунални) / енергия общо, {lm}", round(pce_ratio, 2), "пъти", lm, "изчислено",
    BEA_U, "Х", "DHSGRC / (DGOERC + DELGRC)")

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["r", "metric", "value", "unit", "as_of", "source", "url", "status", "note"])
    w.writeheader()
    w.writerows(ROWS)
print(f"\nCSV: {OUT} ({len(ROWS)} реда)")
