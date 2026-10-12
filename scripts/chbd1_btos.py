"""ЧБД1 5.4: Census BTOS, националните AI въпроси (последните N цикъла).

Употреба: python -I chbd1_btos.py <National.xlsx> [N=12] [--csv out.csv]
Файлът се сваля от https://www.census.gov/hfp/btos/downloads/National.xlsx
Печата текста на AI въпросите, отговора "Yes" и последните N двуседмични стойности
с референтните периоди.
"""
import sys

import openpyxl


def supplement(fn, qids=(1, 4, 6, 7, 8, 9, 13)):
    """AI добавката (AI_Supplement_Table_2026.xlsx, полева Nov 17, 2025 - Feb 8, 2026):
    националните отговори на избраните въпроси. Обхватът (scope) е в първата колона."""
    wb = openpyxl.load_workbook(fn, read_only=True)
    for r in list(wb["National Response Estimates"].iter_rows(values_only=True))[1:]:
        if r[1] in qids:
            print(f"scope {r[0]} Q{r[1]} {r[3]} {str(r[4])[:90]} | {r[5]}")
    # по размер: A = 1-4 заети, G = 250+; Q1 "Yes" и Q7 "без промени"
    for r in list(wb["Employment Response Estimates"].iter_rows(values_only=True))[1:]:
        if r[0] in ("A", "G") and (r[2], r[4]) in ((1, 1), (7, 9)):
            print(f"размер {r[0]} Q{r[2]} {str(r[5])[:60]} | {r[6]}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if "--supp" in sys.argv:
        supplement(sys.argv[sys.argv.index("--supp") + 1])
        return
    fn = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 12
    wb = openpyxl.load_workbook(fn, read_only=True)
    est = list(wb["Response Estimates"].iter_rows(values_only=True))
    hdr = est[0]
    cols = [i for i, h in enumerate(hdr) if h and str(h).isdigit()][:n]
    dates = {}
    for r in list(wb["Collection and Reference Dates"].iter_rows(values_only=True))[1:]:
        if r[3]:
            dates[str(r[3])] = (str(r[6])[:10], str(r[7])[:10])
    out = []
    for r in est[1:]:
        q = str(r[1] or "")
        if "AI" not in q and "rtificial" not in q:
            continue
        print(f"Q{r[0]} | {q[:400]}")
        print(f"   отговор {r[2]}: {r[3]}")
        for i in reversed(cols):
            smp = str(hdr[i])
            ref = dates.get(smp, ("?", "?"))
            print(f"   {smp}  реф. {ref[0]}..{ref[1]}  {r[i]}")
            out.append((r[0], r[3], smp, ref[0], ref[1], r[i]))
    if "--csv" in sys.argv:
        p = sys.argv[sys.argv.index("--csv") + 1]
        with open(p, "w", encoding="utf-8") as f:
            f.write("question_id,answer,smpdt,ref_start,ref_end,estimate\n")
            for row in out:
                f.write(",".join(str(x) for x in row) + "\n")


if __name__ == "__main__":
    main()
