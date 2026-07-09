# 手順書 [9a] zth_calc — log から Zth(t) 抽出（ブランチA前段）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[9a]、`OpenFOAM_branchA_io_contract.md` の §2 を実装に落とした手順書。
> ソルバlogの接合温度から Zth(t) を作り、**9b（PyRth）が要求する形（対数密・time>0・(N,2)化可能）**で出力する。
> 同梱スクリプト `zth_calc.py` は合成logでパーサ動作と 9a→9b 連鎖を検証済み。

---

## 0. このステップの位置づけ

**9a = ソルバlog → Zth(t) の抽出。ブランチA前段で、9b（PyRth）の前処理。** ParaView不要・`reconstructPar`不要（logだけで完結）。

```
[6]log.chtMultiRegionFoam ──► [9a]zth_calc ──► zth_data.csv ──► [9b]PyRth
   毎step "Min/max T"           name-anchored      (time,Tj,Zth)    impedanceモード
                                対数サンプリング      対数密・time>0
```

設計の2本柱（契約 §2.3 / §2.4）:
1. **name-anchored 領域同定**: index番号でなく領域名で接合温度を取る（順序変化に強い）
2. **対数等間隔サンプリング**: 線形1ms間引きを禁止し、早期(µs-ms)を密に保つ（9bの分解能要件）

---

## 1. 入力と出力契約

### 入力

| 名前 | 既定 | 説明 |
|---|---|---|
| `logfile` | — | `log.chtMultiRegionFoam`（tee保存, 231MB級） |
| `-P` | — | 総発熱量 [W]（fvOptionsの値, 例 20） |
| `--tref` | 300.0 | 基準温度 [K]（コールドプレート） |
| `--region` | chip | 接合温度を取る領域名（発熱層） |
| `--spd` | 30 | samples_per_decade（対数密度） |
| `--tmin` | 1e-6 | 採取開始時刻 [s]（早期ノイズ回避, time>0保証） |

### 出力（`zth_data.csv`）

```
列: time_s, Tj_K, Zth_KW    （対数等間隔, time>0）
  Zth_KW = (Tj_K − T_ref) / P
→ 9bへは np.column_stack([time_s, Zth_KW]) を input_mode="impedance" で渡す
```

---

## 2. 領域同定（name-anchored）★

logは各領域の解を順に出す。**直前の `Solving for ... region <name>` 行で現在領域を確定し、その `Min/max T` を読む**のが堅牢（領域の出力順が変わっても壊れない）。

```
current_region = None
各行:
  "Time = X"                          → t を更新
  "Solving for solid region <name>"   → current_region = name
  "Min/max T:<min> <max>"             → current_region==接合 のとき Tj=max を記録
```

> 旧方式（Min/max T の出現回数を数えて N番目）は領域順に依存して壊れる。name-anchoredが推奨。

### ★実logでの正規表現の確認（必須）

スクリプトの正規表現が**自分のlogの実際の行**に合うか、最初に確認する（版・設定で文言が違うことがある）:

```bash
grep -m3 "^Time ="            log.chtMultiRegionFoam
grep -m3 "Solving for .*region" log.chtMultiRegionFoam
grep -m3 "Min/max T"          log.chtMultiRegionFoam
```

文言が違えば `zth_calc.py` の `region_pat` / `time_pat` / `temp_pat` を合わせる。
同定の検算: **接合領域だけ昇温**する（他は遅れて上昇）。スクリプトは接合が昇温しない場合に警告を出す。

---

## 3. 対数等間隔サンプリング ★

**線形1ms間引きは禁止**（chip+はんだの応答µs-ms帯が消え、9bで早期層が分解できない）。logは毎step `Min/max T` を出す超高密度データなので、これを **samples_per_decade（30〜50）** の対数等間隔に間引く。

```
rt_max = 生データの最大時刻
n = samples_per_decade × (log10(rt_max) − log10(t_min))   （下限100点）
targets = logspace(log10(t_min), log10(rt_max), n)
各 target に最も近い生 (t, Tj) を採用 → unique
```

### 密度の検算

```bash
python3 - << 'EOF'
import numpy as np; d=np.loadtxt('zth_data.csv',delimiter=',',skiprows=1)
for lo in [1e-6,1e-5,1e-4,1e-3,1e-2]:
    print(f'{lo:.0e}-{lo*10:.0e}: {((d[:,0]>=lo)&(d[:,0]<lo*10)).sum()}点')
EOF
```
各decadeに十分点があること（検証例では17〜30点/decade）。早期が薄ければ 6 の writeに依らずlogは毎step出るので、`--tmin` と生データ密度（adjustTimeStep）を確認。

---

## 4. スクリプト `zth_calc.py`（検証済み）

```python
#!/usr/bin/env python3
"""zth_calc: chtMultiRegionFoam の log から接合温度を抽出し Zth(t) を出力。
   name-anchored 領域同定 + 対数等間隔サンプリング。"""
import re, argparse, numpy as np

def extract_zth(logfile, P, T_ref=300.0, junction_region="chip",
                samples_per_decade=30, t_min=1e-6,
                region_pat=r"Solving for (?:solid|fluid) region (\S+)",
                time_pat=r"^Time = ([\d.eE+-]+)",
                temp_pat=r"Min/max T[:\s]+([\d.eE+-]+)\s+([\d.eE+-]+)"):
    REG, TIM, TMP = re.compile(region_pat), re.compile(time_pat), re.compile(temp_pat)
    t, cur, rt, rTj = None, None, [], []
    with open(logfile) as f:                 # 大容量logを行ストリーム処理
        for line in f:
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
    if rTj.max() <= T_ref + 1e-6:
        print(f"[warn] 接合 {junction_region} が昇温していない（領域同定ミスの疑い）")
    rt_max = rt.max()
    decades = max(np.log10(rt_max) - np.log10(t_min), 1.0)
    n = max(int(samples_per_decade * decades), 100)
    targets = np.logspace(np.log10(t_min), np.log10(rt_max), n)
    pos = np.clip(np.searchsorted(rt, targets), 1, rt.size - 1)
    pick = np.where(targets - rt[pos-1] < rt[pos] - targets, pos-1, pos)
    sel = np.unique(pick)
    out_t, out_Tj = rt[sel], rTj[sel]
    return np.column_stack([out_t, out_Tj, (out_Tj - T_ref) / P])

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
```

---

## 5. 実行と検算

```bash
python3 zth_calc.py log.chtMultiRegionFoam -P 20 --region chip --spd 30 --tmin 1e-6 -o zth_data.csv
```

検算:
- [ ] 正規表現が実logに合致（§2 の grep）
- [ ] 接合が昇温（警告が出ない）
- [ ] 各decadeに十分な点（§3 の密度チェック）
- [ ] **最終 Zth ≈ 検証2の定常Zth**（手計算予測と整合）

---

## 6. 9a→9b 連鎖の確認（検証済み）

9aの出力をそのままPyRthへ渡す:

```python
import numpy as np, PyRth
z = np.loadtxt("zth_data.csv", delimiter=",", skiprows=1)
data = np.column_stack([z[:,0], z[:,2]])      # [time, Zth]
ev = PyRth.Evaluation()
ev.standard_module({"data":data,"input_mode":"impedance","deconv_mode":"bayesian",
                    "bay_steps":1000,"struc_method":"lanczos","log_time_size":250,
                    "output_dir":"out","label":"cfd"})
ev.save_as_csv()
```

### 自己整合（Rcum_max ≈ Zth_∞）は**チューニング診断**

連鎖の検証で分かった性質:

| 条件 | Rcum_max vs Zth_∞ |
|---|---|
| 時間範囲が非定常で打ち切り（t=0.05s） | +9.5% |
| **定常まで延長（t=0.5s）+ 対数40/decade** | +5.4%（設定にほぼ不感） |

- 残差は「離散RC（時定数スペクトルがデルタ）」という合成データ特有の上振れ。**実CFD/実測は連続スペクトル（分布RC）なのでより良く一致**する。
- 自己整合がずれるとき: ① Zthを**定常まで回したか**（最重要）② 早期密度（`--spd`↑）③ 9b側 `log_time_size`/`bay_steps`/`struc_method` を見直す。

---

## 7. 詰まりやすい点

| 症状 | 原因 | 対処 |
|---|---|---|
| `Min/max T が取れない` | 正規表現が実logと不一致 | §2 grepで実文言を確認し `*_pat` を調整 |
| 接合が昇温しない警告 | `--region` 名違い / name-anchored不発 | 領域名確認、`Solving for...region` 行の有無確認 |
| 早期decadeが薄い | 生データが早期で疎（Δt大）/ `--tmin` 過大 | adjustTimeStep設定・maxDi確認、`--tmin` 下げ |
| 最終Zthが予測と乖離 | 領域取り違え / 非定常打ち切り / 設定ミス | 検証2と突合、endTime延長（[6]/[7]へ） |
| Rcum_maxが大きくずれる | 9a密度不足 or 非定常 | `--spd`↑・定常まで延長・9b設定（[9b]§6） |

---

## 8. 完了ゲート（→ [9b]）

```
[9a] 完了チェック
  □ 正規表現が実logに合致（grep確認）★
  □ name-anchoredで接合(chip)を同定、昇温を確認
  □ 対数等間隔出力（各decadeに十分点, 線形間引きでない）★
  □ 最終Zth ≈ 検証2の定常Zth
  □ zth_data.csv (time_s,Tj_K,Zth_KW) 生成 → 9bへ
```

---

## 9. 他形状への転用（差分ポイント）

| 変わる前提 | 9aで変わる箇所 |
|---|---|
| 流体領域が入る | `region_pat` は solid|fluid 両対応済み。接合が固体内ならそのまま |
| 接合が複数（マルチチップ） | `--region` を変えて複数回実行、接合ごとに `zth_data_<name>.csv` |
| 定常解析（室内気流） | Zth抽出は無し。logから目的関数（残差収束値・代表点温度）を抽出するスクリプトに置換 |
| 出力形式が違う版 | `*_pat` を実logに合わせる（パーサはパターン差し替えで対応） |

**不変なもの**: name-anchored同定、対数等間隔サンプリング、time>0・最終Zth≈定常Zthの検算、行ストリーム処理（大容量log対応）。
