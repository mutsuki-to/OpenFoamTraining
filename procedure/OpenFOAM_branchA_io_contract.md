# ブランチA 入出力契約（[9a] Zth抽出 / [9b] PyRth構造関数）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[9a][9b]・§6 を展開する設計文書。
> **スクリプトを書く前に入出力契約（何を入力に取り何を返すか、両者をつなぐ制約）を固定する**ためのもの。
> この契約に基づいて、後続で 9a（`zth_calc`）と 9b（`PyRth`ラッパー）の手順書を書く。
> **9bは自作実装をやめ、PyRth（NID + Foster→Cauer + 構造関数, JESD51-14準拠, MIT, PyPI）を採用する。**

---

## 0. このドキュメントの位置づけ

ブランチA = ParaView単体ではできない定量出力（Zth(t)・構造関数）を**ソルバlogから**計算する系統。2段（9a→9b）に分かれ、間にデータ受け渡しがある。9bは PyRth に委譲するため、9aは「PyRthへ渡すクリーンな過渡データを作る前処理」になる。**契約を先に決める理由**は、PyRthが要求する早期の対数時間密度を9a側で確保しておく必要があるため（後決めだと9aをやり直す）。

```
[6]log ──► [9a]zth_calc ──► zth_data.csv ──► [9b]PyRth(standard_module) ──► 構造関数CSV/図
                              (time,Tj,Zth)        struc_method="lanczos"          (累積+微分)
                                                                                       │
                                       [7]検証2 ◄── 定常Zth          [7]検証4 ◄────────┘
                                                              standard_module×2 を重ね描き（同一Evaluation）
```

---

## 1. データフロー全体

| 段 | スクリプト/ツール | 入力 | 出力 | 下流 |
|---|---|---|---|---|
| 9a | `zth_calc`（自作） | `log.chtMultiRegionFoam`, P, T_ref, 接合領域名 | `zth_data.csv` (time_s,Tj_K,Zth_KW) | 9b / 検証2 |
| 9b | `PyRth`（ラッパー） | 9a出力(`data`), power_step, struc_method 等 | 構造関数CSV/図（累積+微分）, 時定数スペクトル | 検証4 / 報告 |

**注意**: ParaViewブランチ[8]とは独立。Zth抽出は `reconstructPar` 不要（logだけで完結）。9aは自作のまま、9bがPyRthに替わる。

---

## 2. [9a] zth_calc 入出力契約（PyRthの前処理）

### 2.1 入力

| 名前 | 型/単位 | 説明 | 作業例 |
|---|---|---|---|
| `logfile` | path | ソルバlog（teeで保存したもの、231MB級） | `log.chtMultiRegionFoam` |
| `P` | float [W] | 総発熱量（fvOptionsの値） | 20.0 |
| `T_ref` | float [K] | 基準温度（コールドプレート） | 300.0 |
| `junction_region` | str | 接合温度を取る領域名（発熱層） | `chip` |
| `samples_per_decade` | int | 対数等間隔サンプリング密度（§2.4） | 30〜50 |
| `t_min` | float [s] | 採取開始時刻（早期ノイズを避ける） | 1e-6〜1e-5 |

### 2.2 出力スキーマ（`zth_data.csv`）

```
列: time_s, Tj_K, Zth_KW
  time_s : 時刻 [s]（対数等間隔, §2.4）
  Tj_K   : 接合温度 = junction_region の Max T [K]
  Zth_KW : (Tj_K − T_ref) / P  [K/W]
```

> PyRthへは (time_s, Tj_K)（温度入力）または (time_s, Zth_KW)（インピーダンス入力）のどちらでも渡せる。input_mode に合わせて列を選ぶ（§3.1）。両方持っておくと切替が楽。

### 2.3 領域同定戦略（堅牢化）★

**接合温度をindex番号でなく領域名で取る。** logは各領域の解を順に出すため、最も確実なのは「直前の `Solving for ... region <name>` 行で現在領域を特定し、その `Min/max T` を読む」方式。

```
方式A（推奨, name-anchored）:
  "Solving for solid region <name>" を検出して current_region を更新
  続く "Min/max T:<min> <max>" を current_region の温度として記録
  junction_region == current_region のとき Tj = max を採用

方式B（既存, index-based, フォールバック）:
  "Time =" ごとに Min/max T の出現回数を数え、target_region_index 番目を接合とする
  → 領域の出力順が変わると壊れる。logの実際の並びを確認して使う
```

- 接合領域の同定は「**そのregionだけ温度が立ち上がる**」ことで検算できる（他領域は初期300K近傍から遅れて上昇）。

### 2.4 サンプリング密度契約（最重要）★

**対数等間隔（または生の高密度）で渡す。線形1ms丸め間引きは禁止。**

```
理由: PyRthは内部で log_time_size 点に対数再サンプルするが、
      早期decade（µs〜ms）にデータが無ければ再サンプルもできない。
      chip+はんだの応答はµs〜ms帯にあり、ここが空だと早期層が分解できない。
      logは毎タイムステップ Min/max T を出す（Δt≈6e-7s → 生データは超高密度）。
      これを対数等間隔（例 30〜50点/decade）に間引くか、生密のまま渡す。

実装イメージ:
  log_times = logspace(log10(t_min), log10(t_end), n_per_decade × decades)
  各 target 時刻に最も近い実時刻の (t, Tj) を1点採用
```

| 渡し方 | 早期(µs-ms)密度 | PyRthでの可否 |
|---|---|---|
| 線形1ms丸め（旧script） | ほぼ無し（1ms未満が1点） | ✗ 早期層が出ない |
| 対数等間隔30〜50/decade or 生密 | 十分 | ✓ PyRthが log_time_size に整える |

### 2.5 9aの検算

- [ ] `zth_data.csv` の最終行 Zth ≈ 検証2の定常Zth（手計算予測と整合）
- [ ] 早期（< 1ms）に十分な点数がある（対数等間隔できている）
- [ ] Tj が単調増加で定常へ漸近（非単調なら領域同定ミス or log破損）

---

## 3. [9b] PyRth による構造関数算出 入出力契約

> 自作の `struct_func.py`（NID + 連分数Foster→Cauer + ステージ数スキャン堅牢化）を **PyRth に置換**。
> 自作で苦労したFoster→Cauerの不安定性は、PyRthの安定手法（`struc_method "lanczos"` 等）で解消。

### 3.1 入力（PyRthのparams辞書）

| パラメータ | 説明 | このルーティンでの値 |
|---|---|---|
| `data` | 過渡データ。**(N,2) NumPy配列 [time, 値]**（列必須2・100点以上・time>0） | zth_data.csv由来 |
| `input_mode` | dataの解釈。有効値 `["t3ster","temp","volt","impedance"]`、既定 `"impedance"` | **`"impedance"`**（列1=Zth直接） |
| `power_step` | 電力ステップ [W]。**impedanceモードでは変換に未使用**（tempモードで必要） | 20.0（temp時） |
| `is_heating` | 加熱過渡か | True |
| `deconv_mode` | "bayesian"（堅牢, `bay_steps`要）/ "fft" / "lasso" | "bayesian" |
| `struc_method` | 構造関数法 `["sobhy"(既定),"lanczos","boor_golub","khatwani","polylong"]` | "lanczos"（安定Foster→Cauer） |
| `log_time_size` | インピーダンス曲線の再サンプル点数（既定250） | 250〜 |
| `lower_fit_limit`/`upper_fit_limit` | t=0外挿/フィット窓（**tempモードの外挿時のみ必須**） | impedance時は不要 |
| `output_dir`/`label` | 出力先/ラベル | — |

> **確認済み（実機検証）**: CFDはZth(t)を持つので `input_mode="impedance"` で列1にZthを渡すのが最適（校正`calib`不要、power_step不要）。温度を渡したい場合は `"temp"` + `power_step`。`"volt"` のみ `calib` 必須。

### 3.2 呼び出し（standard_module）

```python
import numpy as np, PyRth
# 9aの出力 (time_s, Zth_KW) を (N,2) 配列に
data = np.column_stack([time_s, Zth_KW])   # 列0=time(>0), 列1=Zth
params = {
    "data": data,
    "input_mode": "impedance",         # 列1=Zth直接（校正・power_step不要）
    "deconv_mode": "bayesian",
    "bay_steps": 1000,
    "struc_method": "lanczos",         # 安定なFoster→Cauer
    "log_time_size": 250,
    "output_dir": "out",
    "label": "phase5_4_cfd",
}
ev = PyRth.Evaluation()
ev.standard_module(params)
ev.save_as_csv()                       # → out/phase5_4_cfd/csv/*.csv
ev.save_figures()
```

> 実機検証済み（PyRth 1.2.0）: 上記で `standard_module` が完走し、構造関数CSVが出力される。`pip` 既定では1.2.0が入る（README最新は1.3.0、必要なら `pip install PyRth==1.3.0` で固定）。

### 3.3 自作版から委譲される処理（何がPyRth内部に移るか）

| 自作で書く予定だった処理 | PyRthでの扱い |
|---|---|
| 対数時間化・再サンプル | `log_time_size` で内部処理 |
| NIDデコンボリューション+正則化 | `deconv_mode "bayesian"` |
| Foster離散化 | 内部 |
| Foster→Cauer（不安定→ステージスキャン回避策） | `struc_method "lanczos"` 等の**安定手法** |
| 累積構造関数 | `standard_module` が出力（累積**+微分**） |

> 自作の「ステージ数スキャンで最小誤差を選ぶ」堅牢化は不要。PyRthの安定手法が置き換える。

### 3.4 出力（PyRthのCSV/図）— 実機確認済み

`save_as_csv` で **`<output_dir>/<label>/csv/`** 配下に生成（2列・空白区切り・ヘッダ無し）:

| ファイル | 列 | 内容 |
|---|---|---|
| `cumul_struc.csv` ★ | `Rcum[K/W], Ccum[J/K]` | **累積構造関数**（主成果。Cは対数で見る） |
| `diff_struc.csv` ★ | `Rcum[K/W], dCcum/dRcum` | **微分構造関数**（層境界がピーク。検証4で有用） |
| `local_resist_struc.csv` | `Ccum, Rcum` | 局所抵抗構造関数 |
| `impedance.csv` | `time[s], Zth[K/W]` | 再サンプル済みZth(t) |
| `impedance_smooth.csv` | `time, Zth` | 平滑化Zth(t) |
| `back_impedance.csv` | `time, Zth` | 同定網からの逆算Zth（入力と比較=検算用） |
| `time_spec.csv` / `sum_time_spec.csv` | `tau[s], R` | 時定数スペクトル / 累積 |
| `derivative.csv` / `back_derivative.csv` | `time, dZth/dz` | 対数時間微分 / 逆算 |

> `save_figures` で同名の図も出る。`back_impedance` と入力Zthの一致が、同定の良し悪しの内部検算になる。

### 3.5 9bの検算

- [ ] 累積構造関数の Rcum 最大 ≈ Zth_∞（自己整合, §4）
- [ ] ブレークポイント/微分ピークが既知の層境界数に対応
- [ ] deconv_mode / struc_method を変えても主要ブレークポイントが頑健（過正則化・不足の確認）

---

## 4. 9a ⇔ 9b(PyRth) インターフェース制約（契約の要）

| 制約 | 内容 | 破ると |
|---|---|---|
| **密度** | 9a出力は対数密 or 生密（線形1ms間引き禁止）。PyRthは `log_time_size` で内部再サンプルするが、早期decadeが空だと再サンプル不可 | 早期層が分解できない |
| **スキーマ/単位** | 9a → PyRth `data`。温度入力なら (time_s,Tj_K)、インピーダンス入力なら (time_s,Zth_KW)。`input_mode` と整合させる | 解釈ミスでZthスケール誤り |
| **Zth_∞** | 自己整合の基準。**9a最終Zth／検証2のCFD定常Zth／PyRthのRcum最大**、この3つが一致して初めて信頼 | ずれは設定/抽出ミスの兆候 |

---

## 5. 検証4（[7]）との接続 — 同一パイプラインの利点

PyRth採用の最大利点: **CFDと T3Ster実測を同じPyRthパイプラインに通せる**。デコンボリューション・Foster→Cauer・規約が同一になり、手法差が差異に混入しない。

```
CFD Zth(t)     ─► PyRth standard_module (label="cfd")     ─┐ 同一Evaluation
                                                           ├─► save_figures で両方を保持
T3Ster Zth(t)  ─► PyRth standard_module (label="t3ster")  ─┘   + 両 cumul_struc.csv を外部で重ね描き
  → 重なる区間=同等構造、分岐点(divergence)=そこから先の差
  → 分岐点の ΔRcum を界面/取付けの熱抵抗差として読む（JESD51-14・T3Ster流）
  → 帯域（chip+はんだ / ceramic 5-100ms / baseplate横拡散）に差を帰属（手法差は排除済み）
```

- **2実データの重ね合わせは「同一Evaluationインスタンスで `standard_module` を2回」**（CFD/実測を別ラベル）。`comparison_module` は**理論R,C網との比較用**で2実データ用途ではない（実機確認済み）。
- T3Ster側もPyRthで処理することで、業務（T3Ster測定）とCFDが1つの解析系に統一される。
- 実証: 末端Rのみ変えた2データで Rcum_max が 0.45 vs 0.53 に分岐 → ΔR≈0.08 が界面差として現れる。

---

## 6. 他形状への転用（差分ポイント）

| 変わる前提 | ブランチAで変わる箇所 |
|---|---|
| 定常解析（室内気流等） | Zth/構造関数は無し。ブランチAは**目的関数CSV**（例: 居住域温度の標準偏差 vs パラメータ）に置換、PyRthは使わない |
| 接合が複数（マルチチップ） | 9aで接合ごとにZth出力、PyRthを接合ごとに実行（`evaluation_set_module` でバッチ） |
| パルス発熱 | 9aは応答波形。PyRthはステップ応答前提なので適用可否を要検討 |
| 実測なし | 重ね描き不要。`standard_module` の自己整合（Rcum≈Zth_∞・層対応）まで |

**不変なもの**: 9a→9bの2段分割、対数密度契約、PyRthによる安定Foster→Cauer、Zth_∞による3点自己整合（9a最終値／検証2／Rcum最大）。

---

## 7. PyRth採用の宿題 — 解決結果（実機検証済み, PyRth 1.2.0）

| # | 宿題 | 結果 |
|---|---|---|
| 1 | CFDのZthを渡す `input_mode` | **解決**: 有効値 `["t3ster","temp","volt","impedance"]`、既定 `"impedance"`。CFDは `"impedance"` で列1=Zthを直接（校正不要）。温度なら `"temp"`+`power_step` |
| 2 | `data` の配列形状 | **解決**: `(N,2)` の `[time, 値]`。列数must=2（違えば transpose 警告）、推奨100点以上、time>0（内部対数時間） |
| 3 | 出力CSVの列名 | **解決**: `<output_dir>/<label>/csv/` に生成。`cumul_struc.csv`=`[Rcum,Ccum]`、`diff_struc.csv`=`[Rcum,dC/dR]` 他（§3.4） |
| 4 | 導入 | **解決**: `pip install PyRth` 成功（→1.2.0、依存 numpy/numba 自動）。最新固定は `==1.3.0`。Python3.11+ |

**追加で確認できた自己整合（§4の実証）**:
```
合成Foster網（R=[0.1,0.05,0.1,0.2], Zth_inf=0.45）を input_mode="impedance" で投入
  → impedance.csv 最終Zth = 0.4500（入力を完全復元）
  → cumul_struc.csv の Rcum最大 = 0.4493 ≈ Zth_inf（誤差0.2%）  ★自己整合成立
  → struc_method="lanczos" / deconv_mode="bayesian" で完走
```
契約§4の「Rcum最大 ≈ Zth_∞」がPyRthで実際に成り立つことを確認。実装の前提がすべて固まった。

> 残る調整事項（宿題ではなくチューニング）: 接合近傍（小R域）の分解能は早期時間のZth密度（9a契約2.4）と `log_time_size`・deconv設定に依存。本番CFDデータで `log_time_size` とデコンボリューション強度を詰める。

---

## 次のステップ

この契約に基づき:
- **[9a]手順書**: `zth_calc` の実装（log解析・name-anchored領域同定・対数/生密サンプリング・PyRth用CSV/配列出力）
- **[9b]手順書**: **PyRthワークフロー**（install → 9a出力を `data` に → `standard_module`(lanczos/bayesian) → 出力確認 → standard_module×2の重ね描きでT3Ster照合）

を順に書く。契約の各項目（特に2.3 領域同定 / 2.4 密度 / 3.1〜3.4 PyRth API）が実装の骨子になる。宿題（§7）は全て解決済みで、実装に入れる状態。
