#!/usr/bin/env python3
"""zth_calc: chtMultiRegionFoam の log から接合温度を抽出し Zth(t) を出力する。
   - name-anchored 領域同定（'Solving for ... region <name>' を追って Min/max T を読む）
   - 対数等間隔サンプリング（9b/PyRth の早期密度要件を満たす）
"""
import re, argparse, numpy as np

def extract_zth(logfile, P, T_ref=300.0, junction_region="chip",
                samples_per_decade=30, t_min=1e-6,
                region_pat=r"Solving for (?:solid|fluid) region (\S+)",
                time_pat=r"^Time = ([\d.eE+-]+)",
                temp_pat=r"Min/max T[:\s]+([\d.eE+-]+)\s+([\d.eE+-]+)"):
    REG, TIM, TMP = re.compile(region_pat), re.compile(time_pat), re.compile(temp_pat)
    t, cur, rt, rTj = None, None, [], []
    with open(logfile) as f:
        for line in f:                      # 大容量logを行ストリームで処理
            m = TIM.match(line)
            if m: t = float(m.group(1)); continue
            m = REG.search(line)
            if m: cur = m.group(1); continue
            m = TMP.search(line)
            if m and cur == junction_region and t is not None:
                rt.append(t); rTj.append(float(m.group(2)))
    rt, rTj = np.asarray(rt), np.asarray(rTj)
    if rt.size == 0:
        raise SystemExit("接合領域の Min/max T が取れない。region/temp パターンを確認")
    # sanity: 接合は昇温するはず
    if rTj.max() <= T_ref + 1e-6:
        print(f"[warn] 接合 {junction_region} が昇温していない（領域同定ミスの疑い）")
    # 対数等間隔サンプリング（raw から最近傍を採用）
    rt_max = rt.max()
    decades = max(np.log10(rt_max) - np.log10(t_min), 1.0)
    n = max(int(samples_per_decade * decades), 100)
    targets = np.logspace(np.log10(t_min), np.log10(rt_max), n)
    pos = np.clip(np.searchsorted(rt, targets), 1, rt.size - 1)
    pick = np.where(targets - rt[pos-1] < rt[pos] - targets, pos-1, pos)
    sel = np.unique(pick)
    out_t, out_Tj = rt[sel], rTj[sel]
    Zth = (out_Tj - T_ref) / P
    return np.column_stack([out_t, out_Tj, Zth])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile"); ap.add_argument("-P", type=float, required=True)
    ap.add_argument("--tref", type=float, default=300.0)
    ap.add_argument("--region", default="chip")
    ap.add_argument("--spd", type=int, default=30)
    ap.add_argument("--tmin", type=float, default=1e-6)
    ap.add_argument("-o", default="zth_data.csv")
    a = ap.parse_args()
    arr = extract_zth(a.logfile, a.P, a.tref, a.region, a.spd, a.tmin)
    np.savetxt(a.o, arr, delimiter=",", header="time_s,Tj_K,Zth_KW",
               comments="", fmt=["%.6e","%.4f","%.6f"])
    print(f"{a.o}: {arr.shape[0]} 点, 最終Zth={arr[-1,2]:.4f} K/W")
