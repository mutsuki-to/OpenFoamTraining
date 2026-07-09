# 手順書 [9b] PyRth による構造関数算出（ブランチA後段）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[9b]、および `OpenFOAM_branchA_io_contract.md` の §3 を実装に落とした手順書。
> 自作 `struct_func.py` を廃し、**PyRth**（NID + 安定Foster→Cauer + 構造関数, JESD51-14準拠, MIT）をラップする。
> 本書のコード・出力・数値は **PyRth 1.2.0 で実機検証済み**。

---

## 0. このステップの位置づけ

**9b = 9aのZth(t)を PyRth に通し、構造関数（累積・微分）を得る。** 自作で苦労したNIDデコンボリューションとFoster→Cauerの数値不安定は PyRth の安定手法に委譲する。

```
[9a]zth_data.csv ──► [9b]PyRth standard_module ──► cumul_struc.csv / diff_struc.csv / 図
   (time,Tj,Zth)         input_mode="impedance"            │
                         struc_method="lanczos"            ├─► [7]検証4（T3Ster照合, §7）
                         deconv_mode="bayesian"            └─► 報告
```

---

## 1. 導入と前提

### 1.1 インストール（WSL2）

```bash
pip install PyRth                 # 既定で 1.2.0 が入る（numpy/numba 依存も自動）
# 再現性のため固定するなら:
pip install PyRth==1.3.0          # README最新。Python 3.11+
```

> numpy 1.x へ落ちる場合がある（PyRthは numpy<2 想定）。他パッケージとの競合が嫌なら専用 venv を推奨。

### 1.2 入力契約（9aから）

| 項目 | 要件（契約 §2/§3） |
|---|---|
| ファイル | `zth_data.csv`（列 `time_s, Tj_K, Zth_KW`） |
| 時間 | `time > 0`（内部で対数時間）。早期(µs-ms)が**対数等間隔 or 生密**であること |
| 点数 | 100点以上推奨 |

---

## 2. 入力整形（9a出力 → PyRthのdata）

PyRthの `data` は **`(N,2)` 配列 `[time, 値]`**。CFDはZthを持つので `input_mode="impedance"` で**列1=Zth**を渡す（校正`calib`・`power_step`不要）。

```python
import numpy as np
z = np.loadtxt("zth_data.csv", delimiter=",", skiprows=1)   # time_s, Tj_K, Zth_KW
data = np.column_stack([z[:,0], z[:,2]])                     # [time, Zth]  ← impedanceモード
# （温度で渡す場合は [time, Tj] + input_mode="temp" + power_step=P）
assert data.shape[1] == 2 and (data[:,0] > 0).all()
```

---

## 3. PyRth 実行（standard_module）

```python
import PyRth

params = {
    "data":          data,                 # (N,2) [time, Zth]
    "input_mode":    "impedance",          # 列1=Zth直接（校正・power_step不要）
    "deconv_mode":   "bayesian",           # 堅牢。bay_stepsで反復数
    "bay_steps":     1000,
    "struc_method":  "lanczos",            # 安定なFoster→Cauer（2024論文）
    "log_time_size": 250,                  # インピーダンス再サンプル点数
    "filter_name":   "hann",               # デコンボリューション窓（既定）
    "output_dir":    "out",
    "label":         "phase5_4_cfd",
}

ev = PyRth.Evaluation()
ev.standard_module(params)
ev.save_as_csv()        # → out/phase5_4_cfd/csv/*.csv
ev.save_figures()       # → out/phase5_4_cfd/png/*.png
```

> 委譲される処理: 対数時間化・再サンプル＝`log_time_size`／NIDデコンボリューション＝`deconv_mode`／Foster→Cauer＝`struc_method`。自作の「ステージ数スキャン堅牢化」は不要。

---

## 4. 出力の読み方

`out/<label>/csv/` に2列・空白区切り・ヘッダ無しで生成（実機確認済み）。

| ファイル | 列 | 用途 |
|---|---|---|
| `cumul_struc.csv` ★ | `Rcum[K/W], Ccum[J/K]` | **累積構造関数**（主成果。Ccumは対数軸） |
| `diff_struc.csv` ★ | `Rcum[K/W], dCcum/dRcum` | **微分構造関数**（層境界がピーク） |
| `impedance.csv` | `time[s], Zth[K/W]` | 再サンプル済みZth(t) |
| `back_impedance.csv` | `time, Zth` | 同定網からの逆算Zth（入力と比較=検算） |
| `time_spec.csv` | `tau[s], R` | 時定数スペクトル |
| `local_resist_struc.csv` | `Ccum, Rcum` | 局所抵抗構造関数 |

読み方:
- **累積構造関数**: 平坦部（Rcumが伸びCcum微増）=高抵抗・低熱容量の層/界面。急立ち上がり（Ccum急増、Rcumほぼ一定）=大熱容量領域。傾き変化が材料境界。
- **微分構造関数**: ピーク=大熱容量領域（各層の本体）、谷=界面/くびれ。**層境界がピークで鋭く出る**ので帯域同定に有利。

---

## 5. 検算（自己整合）★

契約 §4 の自己整合を必ず確認する。

```python
import numpy as np
c = np.loadtxt("out/phase5_4_cfd/csv/cumul_struc.csv")
imp = np.loadtxt("out/phase5_4_cfd/csv/impedance.csv")
print("Rcum_max =", c[:,0].max(), " / Zth(t)最終 =", imp[:,1].max())
```

- [ ] **Rcum最大 ≈ Zth_∞**（= 9aの最終Zth = 検証2のCFD定常Zth）。3点一致でブランチA自己整合
  - 実証例: 合成Zth_∞=0.45 → Rcum_max=0.4493（誤差0.2%）
- [ ] `back_impedance.csv` が入力 `impedance.csv` と一致（同定の良否）
- [ ] 累積の傾き変化／微分のピーク数が**既知の層境界数に対応**（chip / はんだ / dbc各層 / TIM / baseplate）

---

## 6. パラメータチューニング

主要パラメータと効果（既定で動くが、本番CFDで詰める）。

| パラメータ | 既定 | 効果・調整指針 |
|---|---|---|
| `struc_method` | "sobhy" | **"lanczos" 推奨**（安定）。他に boor_golub / khatwani / polylong。結果の頑健性を別法で相互確認 |
| `deconv_mode` | "bayesian" | "bayesian"（堅牢, `bay_steps`大で収束）/ "fft"（速いが平滑化で滲む）/ "lasso"（スパース同定） |
| `bay_steps` | 1000 | 大→収束良・低速。早期層が割れないとき増やす |
| `log_time_size` | 250 | 大→細かいが雑音増。**接合近傍(小R)の分解能は早期Zth密度(9a契約2.4)とこの値に依存** |
| `filter_name` | "hann" | デコンボリューション窓。過平滑なら見直し |

**チューニングの指標**:
- Rcum_max が Zth_∞ から外れる → log_time_size/早期密度/deconv強度を見直す
- 接合近傍が潰れて層が割れない → 9aで早期(µs-ms)を密に + log_time_size↑
- 微分にスパイク状の偽ピーク → 平滑強める（filter / bay_steps）

---

## 7. T3Ster実測との照合（検証4）★

**最大の利点: CFDとT3Sterを同じPyRthパイプラインに通す**ので、手法差が差異に混入しない。

### 方法: 同一Evaluationで2回 standard_module → 重ね描き

```python
ev = PyRth.Evaluation()
base = dict(input_mode="impedance", deconv_mode="bayesian", bay_steps=1000,
            struc_method="lanczos", log_time_size=250, output_dir="out")

ev.standard_module({**base, "data": data_cfd,    "label": "cfd"})    # CFDのZth(t)
ev.standard_module({**base, "data": data_t3ster, "label": "t3ster"}) # 実測のZth(t)
ev.save_as_csv()        # out/cfd/csv/ と out/t3ster/csv/ に各々出力
ev.save_figures()
```

> `comparison_module` は「与えたR,Cの**理論**インピーダンスとの比較」用で、2実データの重ね合わせ用途ではない。2実データは上記のように同一インスタンスで処理する。

### 分岐点（divergence point）の読み

両者の `cumul_struc.csv` を重ねる:

```python
import numpy as np, matplotlib.pyplot as plt
for lbl,st in [("cfd","-"),("t3ster","--")]:
    c = np.loadtxt(f"out/{lbl}/csv/cumul_struc.csv")
    plt.semilogy(c[:,0], c[:,1], st, label=lbl)
plt.xlabel("Rcum [K/W]"); plt.ylabel("Ccum [J/K]"); plt.legend(); plt.grid(True)
```

- 両曲線が**重なる区間**=同等の構造（chip〜DBC）。**分岐する点（divergence point）**=そこから先の差（界面抵抗・取付け・形状差）
- 分岐点での ΔRcum = 界面/取付けの熱抵抗差として読む（JESD51-14・T3Ster流）
  - 実証例: 末端Rのみ変えた2データで Rcum_max が 0.45 vs 0.53 に分岐 → ΔR≈0.08 が界面差として現れる
- 帯域対応（検証4）: chip+はんだ（〜数ms）/ ceramic（5–100ms, 材料感度帯）/ baseplate横拡散（0.1s〜）

---

## 8. 完了ゲート（→ 検証4クローズ / 報告）

```
[9b] 完了チェック
  □ PyRth導入（pip, バージョン記録）
  □ 9a出力を (N,2)[time,Zth] に整形、input_mode="impedance"
  □ standard_module(lanczos/bayesian) 完走、save_as_csv/figures
  □ 自己整合: Rcum最大 ≈ Zth_∞（9a最終／検証2と3点一致）★
  □ back_impedance が入力と一致
  □ 層境界数 ≈ 微分ピーク数／累積の傾き変化
  □ （実測あり）2データ重ね描き → 分岐点ΔRを界面差として読む（検証4）
```

---

## 9. 他形状への転用（差分ポイント）

| 変わる前提 | 9bで変わる箇所 |
|---|---|
| 定常解析（室内気流等） | 構造関数なし。9b（PyRth）は使わない。目的関数評価に置換 |
| 接合が複数 | 接合ごとにZth→ラベル分けて standard_module を複数回（同一Evaluationで一括図化） |
| 温度を直接渡す | `input_mode="temp"` + `power_step=P`（+ 外挿時 lower/upper_fit_limit） |
| 実測なし | §7省略。§5の自己整合（Rcum≈Zth_∞・層対応）まで |
| 感度study（材料/メッシュ） | 各ケースのZthを別ラベルで一括処理し、構造関数を重ねて差を読む |

**不変なもの**: input_mode="impedance"でZth直接投入、struc_method="lanczos"の安定変換、Rcum_max≈Zth_∞の自己整合、同一Evaluationでの重ね描きによる分岐点読み。

---

## 付録: 最小実行スクリプト（検証済みテンプレート）

```python
import numpy as np, PyRth

def zth_to_structure(zth_csv, label, out="out",
                     struc_method="lanczos", deconv_mode="bayesian",
                     bay_steps=1000, log_time_size=250):
    z = np.loadtxt(zth_csv, delimiter=",", skiprows=1)      # time_s,Tj_K,Zth_KW
    data = np.column_stack([z[:,0], z[:,2]])                # [time, Zth]
    assert data.shape[1] == 2 and (data[:,0] > 0).all()
    ev = PyRth.Evaluation()
    ev.standard_module({
        "data": data, "input_mode": "impedance",
        "deconv_mode": deconv_mode, "bay_steps": bay_steps,
        "struc_method": struc_method, "log_time_size": log_time_size,
        "output_dir": out, "label": label,
    })
    ev.save_as_csv(); ev.save_figures()
    c = np.loadtxt(f"{out}/{label}/csv/cumul_struc.csv")
    print(f"[{label}] Rcum_max={c[:,0].max():.4f}  (Zth_∞と照合)")
    return ev

# 単体:
zth_to_structure("zth_data.csv", "phase5_4_cfd")
```
