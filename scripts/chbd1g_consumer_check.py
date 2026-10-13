"""ЧБД1г Р6, проверката (13.10.2026): допълнителни редове към consumer_2026-10_chbd1g.csv.

Пуска се СЛЕД chbd1g_consumer.py (който презаписва CSV-то). Добавя редове с бележка
"ЧБД1г-проверка" и при повторно пускане първо маха старите такива редове.

Входове в <папка_със_свалените> (теглени в сесията на 13.10.2026):
  NipaDataM.txt  BEA, https://apps.bea.gov/national/Release/TXT/NipaDataM.txt (DTENRC, DOWNRC, DPCERC)
  nar.txt        pdftotext -layout на NAR HAI 09.2026 (публ. 13.10.2026)
  nar2023.txt    pdftotext -layout на NAR HAI 07.2023 (публ. 08.09.2023; годишните 2020-2022)
  gas_w.xls      EIA EMM_EPMR_PTE_NUS_DPGw.xls (бензин regular на дребно, седмичен)
  bls.json       BLS API v1 (CUUR0000SA0, CUUR0000SETB02)

Употреба: python -I chbd1g_consumer_check.py <папка_със_свалените> <csv>
"""
import csv
import datetime
import json
import os
import re
import sys

import xlrd

sys.stdout.reconfigure(encoding="utf-8")
DL, OUT = sys.argv[1], sys.argv[2]
TAG = "ЧБД1г-проверка"
R = "Р6"
NEW = []


def add(metric, value, unit, as_of, source, url, status, note=""):
    NEW.append([R, metric, value, unit, as_of, source, url, status, (note + "; " if note else "") + TAG])


# 1. PCE: наемът, който наемателите плащат, срещу приравнения наем на собствениците
BEA = "https://apps.bea.gov/national/Release/TXT/NipaDataM.txt"
want = {"DPCERC", "DTENRC", "DOWNRC", "DGOERC", "DELGRC"}
d = {c: {} for c in want}
with open(os.path.join(DL, "NipaDataM.txt"), encoding="utf-8") as f:
    for row in csv.reader(f):
        if row and row[0] in want:
            d[row[0]][row[1]] = float(row[2].replace(",", "")) / 1000  # $ млрд, SAAR


def avg(c, y):
    v = [x for k, x in d[c].items() if k.startswith(y + "M")]
    return sum(v) / len(v)


names = {"DTENRC": "PCE: наем на жилища под наем (плаща се в брой)",
         "DOWNRC": "PCE: приравнен наем на собствениците (импутиран, не се плаща)"}
for c, nm in names.items():
    for per in ("2026M08", "2025M08"):
        add(f"{nm}, {per}", round(d[c][per], 1), "$ млрд SAAR", per, f"BEA NIPA табл. 2.4.5U, {c}", BEA, "В")
        add(f"Дял от PCE: {nm}, {per}", round(d[c][per] / d["DPCERC"][per] * 100, 2), "%", per,
            "изчислено", BEA, "Х", f"{c}/DPCERC*100")
    for y in ("2019", "2021"):
        add(f"Дял от PCE: {nm}, средно {y}", round(avg(c, y) / avg("DPCERC", y) * 100, 2), "%", y,
            "изчислено", BEA, "Х", f"средно {c} / средно DPCERC за {y}")
    ch = d[c]["2026M08"] - d[c]["2025M08"]
    add(f"Промяна г/г: {nm}, 08.2026", round(ch, 1), "$ млрд SAAR", "2026M08", "изчислено", BEA, "Х",
        f"{c} 2026M08 - 2025M08; г/г {round((d[c]['2026M08'] / d[c]['2025M08'] - 1) * 100, 2)}%")
print("PCE наем в брой 08.2026:", round(d["DTENRC"]["2026M08"], 1), "приравнен:", round(d["DOWNRC"]["2026M08"], 1))

# 2. NAR HAI: подробностите за 08.2026 и годишните 2023-2025 (PDF 09.2026), годишните 2020-2022 (PDF 07.2023)
NAR26 = "https://www.nar.realtor/sites/default/files/2026-10/hai-09-2026-housing-affordability-index-2026-10-13.pdf"
NAR23 = "https://www.nar.realtor/sites/default/files/documents/hai-07-2023-housing-affordability-index-2023-09-08.pdf"
t26 = open(os.path.join(DL, "nar.txt"), encoding="utf-8", errors="replace").read().splitlines()
num = r"([\d,]+(?:\.\d+)?)"
for line in t26:
    m = re.match(r"^(2023|2024|2025)\s+" + r"\s+".join([num] * 7) + r"\s*$", line.strip())
    m2 = re.match(r"^2026\s+Aug r\s+" + num + r"\s+" + num + r"\s+" + num + r"\s+" + num + r"\s+" + num + r"\s+" + num + r"\s*$", line.strip())
    if m:
        y, price, rate, pmt, share, inc, qinc, hai = m.groups()
        lab, asof = f"година {y}", y
    elif m2:
        price, rate, share, inc, qinc, hai = m2.groups()
        lab, asof = "08.2026 (ревизиран)", "2026-08"
    else:
        continue
    p, i = float(price.replace(",", "")), float(inc.replace(",", ""))
    add(f"NAR: медианна цена, {lab}", p, "$", asof, "NAR HAI месечен PDF 09.2026", NAR26, "В")
    add(f"NAR: ефективна лихва в HAI, {lab}", float(rate), "%", asof, "NAR HAI месечен PDF 09.2026", NAR26, "В")
    add(f"NAR: вноска като % от дохода, {lab}", float(share), "%", asof, "NAR HAI месечен PDF 09.2026", NAR26, "В")
    add(f"NAR: медианен семеен доход, {lab}", i, "$", asof, "NAR HAI месечен PDF 09.2026", NAR26, "В")
    add(f"NAR: нужен доход, {lab}", float(qinc.replace(",", "")), "$", asof, "NAR HAI месечен PDF 09.2026", NAR26, "В")
    add(f"Цена/доход (NAR), {lab}", round(p / i, 2), "пъти", asof, "изчислено", NAR26, "Х", "медианна цена / медианен доход")
    print("NAR", lab, hai, round(p / i, 2))
t23 = open(os.path.join(DL, "nar2023.txt"), encoding="utf-8", errors="replace").read().splitlines()
for line in t23:
    m = re.match(r"^(2020|2021|2022)(?!\s+[A-Z][a-z]{2}\b)\b.*\s(\d{2,3}\.\d)\s*$", line.strip())
    if m:
        add(f"NAR HAI (fixed), година {m.group(1)}", float(m.group(2)), "индекс", m.group(1),
            "NAR HAI месечен PDF 07.2023 (публ. 08.09.2023), колона Fixed", NAR23, "В",
            "по-късни ревизии на NAR са възможни; останалите колони на годишните редове са разбъркани при извличането")
        print("NAR годишен", m.group(1), m.group(2))

# 3. EIA: бензинът на дребно, средно за август и септември (за догадката за CPI септември)
EIA = "https://www.eia.gov/dnav/pet/hist_xls/EMM_EPMR_PTE_NUS_DPGw.xls"
b = xlrd.open_workbook(os.path.join(DL, "gas_w.xls"))
s = b.sheet_by_name("Data 1")
wk = []
for r in range(3, s.nrows):
    v = s.row_values(r)
    if v[0] != "" and v[1] != "":
        wk.append((datetime.datetime(*xlrd.xldate_as_tuple(v[0], b.datemode)), float(v[1])))
for y, mth in ((2025, 8), (2025, 9), (2026, 8), (2026, 9)):
    x = [p for dt, p in wk if dt.year == y and dt.month == mth]
    add(f"Бензин regular на дребно, средно за месеца {mth:02d}.{y}", round(sum(x) / len(x), 3), "$/галон",
        f"{y}-{mth:02d}", "EIA EMM_EPMR_PTE_NUS_DPG, седмичен", EIA, "Х",
        f"средно от {len(x)} седмични стойности (В)")
    print("EIA бензин", y, mth, round(sum(x) / len(x), 3), len(x))

# 4. Тежестта на „други моторни горива“ (вкл. дизел), пренесена до юли 2026 по цените
j = json.load(open(os.path.join(DL, "bls.json"), encoding="utf-8"))
S = {x["seriesID"]: {(o["year"], o["period"]): float(o["value"]) for o in x["data"] if o["value"] != "-"}
     for x in j["Results"]["series"]}
o, a = S["CUUR0000SETB02"], S["CUUR0000SA0"]
ri = 0.086 * (o[("2026", "M07")] / o[("2025", "M12")]) / (a[("2026", "M07")] / a[("2025", "M12")])
add("CPI тежест юли 2026 (оценка): Други моторни горива (вкл. дизел)", round(ri, 3), "% от CPI", "07.2026",
    "изчислено от BLS RI дек.2025 (0,086) и BLS API индексите", "https://www.bls.gov/cpi/tables/relative-importance/2025.htm",
    "Х", "0,086 x (I_юли26/I_дек25)/(A_юли26/A_дек25); BLS не я публикува в табл. 1")
print("RI други моторни горива юли 2026 (оценка):", round(ri, 3))

# запис: маха старите редове на проверката, добавя новите
with open(OUT, encoding="utf-8", newline="") as f:
    rows = [r for r in csv.reader(f)]
hdr, body = rows[0], [r for r in rows[1:] if not (r and TAG in r[-1])]
with open(OUT, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(hdr)
    w.writerows(body + NEW)
print(f"CSV: {OUT} ({len(body) + len(NEW)} реда, от тях {len(NEW)} от проверката)")
