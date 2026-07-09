# 手順書 [6] ソルバ実行（実行前処理 + 6a起動時sanity + 6b計算中monitoring）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[6]・§4 を展開した詳細手順書。
> 手順書[4b]の changeDict/decomposePar を**適用**し、ソルバを回し、起動時(6a)と実行中(6b)で弾く。
> 作業例はパワーデバイス模擬（6領域、シリアル約9.5h/並列短縮、phase5-3/5-4構成）。

---

## 0. このステップの位置づけ

**6 = 回すだけでなく、「起動数秒(6a)」と「実行中(6b)」で破綻を弾く検査を含む。** 完走後にまとめて検証すると、設定ミスで長時間（例: 9.5h）を捨てる。**早期に弾くのが本質**。

```
[4b]設定 ──► [6]ここ ──► log + 時刻フィールド ──┬─► [9a]Zth(ブランチA)
                ├─[6a]起動時sanity              └─► [8]ParaView(ブランチB)
                └─[6b]計算中monitoring
```

---

## Part 0. 実行前提（メッシュ非依存の物理/ソルバ設定 = 4a相当）

> これらはメッシュに依存しないため**4aと並行して書ける**設定群だが、手順書[4a]では meshing に絞ったため、ここで実行前提として確認する。詳細テンプレートは `OpenFOAM_solid_CHT_procedure.md`（Step7〜9）に委譲し、本書は**6で効く決定事項**だけ示す。

### 必要ファイルと、出力が強制する設定（ルーティン§5）

| ファイル | 6で効く決定事項 |
|---|---|
| `constant/regionProperties` | `fluid ()` を**空でも必須**で置く（無いと `fluid not found` で起動失敗） |
| `constant/g` | `(0 0 -9.81)`（固体のみでも必須） |
| `constant/<region>/thermophysicalProperties` | 材料物性（Si k148/ρ2330/Cp712、Cu k400/ρ8960/Cp385、AlN k170/ρ3260/Cp740） |
| `system/<region>/fvSchemes` | **`ddtSchemes Euler`**（`steadyState`だとZth曲線が出ない）／`divSchemes none` |
| `system/<region>/fvSolution` | `T`(PCG/DIC) + `h` + **`hFinal`**（無いと起動失敗）／`nNonOrthogonalCorrectors 2` |
| `system/<発熱region>/fvOptions` | `scalarSemiImplicitSource`, `volumeMode absolute`, 20W（absoluteは総量W。cell数に依らず合計20W） |
| `system/controlDict`（本番） | 下記 |
| `0.orig/T`, `0.orig/p` | T=uniform300（`".*"` zeroGradient）／**p必須**（固体のみでもchtMultiRegionFoamが要求） |

### 本番 controlDict

```cpp
application     chtMultiRegionFoam;
startFrom       startTime;  startTime 0;
stopAt          endTime;    endTime 0.5;     // ★ ≥ τ_max×(3〜5)。下記参照
deltaT          1e-6;
adjustTimeStep  yes;
maxCo           0.5;        // 固体は流速0でCoは効かない（保険）
maxDi           20.0;       // ★ Cuの高α。Diを20まで許容しΔtを稼ぐ
writeControl    adjustableRunTime;
writeInterval   0.01;       // 時刻フィールド出力（ブランチB用）。Zthはlog由来で密
purgeWrite      0;
```

**endTimeの決め方（出力定義との整合）**:
```
τ ≈ L²/α。最大τ層が目安。定常近傍は τ×(3〜5)。
ただし本目的（Zth比較）では「数値的に変化が出力精度以下になる時刻」で十分。
材料感度study（5〜100ms帯に差）より、真の定常まで回す必要はないと確認済み。
作業例では endTime 0.5s で実用上のZthが得られる（baseplate横拡散τ≈7.5sの緩慢な裾は無視可）。
```

- [ ] `ddtSchemes Euler` / `hFinal`有 / `fluid ()`有 / `0.orig/p`有（4大起動失敗要因）
- [ ] fvOptions の発熱量と volumeMode（absolute=総W）

---

## Part 1. 実行前処理（4bの設定を適用）

```bash
cd ~/OpenFOAM/training/<ケース>
REGIONS="chip dbc_cu_top dbc_ceramic dbc_cu_bot baseplate heatsink"

# 1) 0.orig → 0/<region>/（固体のみなのでT,pの2ファイル）
for r in $REGIONS; do
    rm -rf 0/$r && mkdir -p 0/$r
    cp 0.orig/T 0/$r/ && cp 0.orig/p 0/$r/
done

# 2) 境界条件適用（4b Part BのchangeDictを反映）
for r in $REGIONS; do
    changeDictionary -region $r > log.changeDictionary.$r 2>&1
done

# 3) 並列分割（4b Part CのdecomposeParDictを使用）
for r in $REGIONS; do
    decomposePar -region $r > log.decomposePar.$r 2>&1
done
```

> 自動化済みなら `Allrun_calc`（計算のみ：changeDict→decomposePar→solver）を使用。シリアルはスクリプト内でコメントアウト保持。
> **クリーンは `foamCleanTutorials`**（`rm -rf 0 [0-9]*` は 0.orig を消す事故）。

### 前処理の即チェック（changeDictが効いたか）

```bash
# 0/<region>/T に実BCが反映されたか（zeroGradientのままなら未適用）
grep -A3 "_to_\|_bottom" 0/heatsink/T | head
```
- [ ] `heatsink_bottom` が fixedValue 300 になっている（`".*"`のzeroGradientのままなら changeDict未適用 or パッチ名不一致 → 4bへ戻る）

---

## Part 2. ソルバ起動

```bash
# 並列（i5-1335U 物理4コア）
mpirun -np 4 chtMultiRegionFoam -parallel | tee log.chtMultiRegionFoam
```

> `tee` 必須（Zth抽出は231MB級のlogをパースする。標準出力を残さないと再実行になる）。
> シリアルは `chtMultiRegionFoam | tee log.chtMultiRegionFoam`。

**起動直後は止めずに数秒ログを流し、6aを確認** → 異常なら即Ctrl-Cして4a/4bへ戻る（長時間を捨てない）。

---

## 6a. 起動時sanity（起動〜数秒で弾く）★

起動直後のログ（最初の数十行〜最初の `Time = ...`）で4点を確認。

```bash
# 起動部分だけ抜く
head -100 log.chtMultiRegionFoam
```

### チェック1: 全領域のメッシュ読み込み

```bash
grep -i "Create.*mesh\|region" log.chtMultiRegionFoam | head -20
```
- [ ] 6領域すべての mesh 作成行がある（欠落＝splitMeshRegions/regionProperties不整合）

### チェック2: 発熱cell数 ★最重要

```bash
grep -i "selected.*cell" log.chtMultiRegionFoam
```
```
fvOptions: selected 5123 cell(s) with volume ...   ← chip領域のcell数か？
```
- [ ] **N = 想定の発熱領域(chip)のcell数**（0なら発熱無し、別領域の数なら発熱場所間違い）
- [ ] N=0 や桁違い → fvOptionsのselectionMode/領域指定ミス → 即停止して修正

### チェック3: fvOptions読み込み

```bash
grep -i "fvOptions\|scalarSemiImplicit\|heatSource" log.chtMultiRegionFoam | head
```
- [ ] heatSource（scalarSemiImplicitSource）が認識されている

### チェック4: 起動時 Min/max T

```bash
grep "Min/max T" log.chtMultiRegionFoam | head -12
```
- [ ] 初期は全領域 ≈ 300K、最初の数ステップで**発熱層(chip)から上昇**し始める
- [ ] いきなり負値・数千Kは設定異常（境界・物性・発熱の桁ミス）

### チェック5: エネルギー収支の経路（設定レベル）
- [ ] 側面 zeroGradient（断熱）＋ 底面 fixedValue（吸熱）で、発熱20Wの出口が底面に一意化されている（定量検証は[7]）

---

## 6b. 計算中monitoring（実行中）

定期的にログ末尾を見る。

```bash
tail -40 log.chtMultiRegionFoam
```

### チェック1: h残差が下がっているか

```bash
grep -i "Solving for h" log.chtMultiRegionFoam | tail
```
- [ ] 各領域でhの残差が初期から数桁低下／単調 or 穏やかな振動減少
- [ ] 増加に転じる＝発散の兆候（→停止、メッシュ品質/スキーム/Δt見直し）

### チェック2: Min/max T が物理的に妥当

```bash
grep "Min/max T" log.chtMultiRegionFoam | tail -12
```
- [ ] 発熱層が単調に上昇し定常へ漸近（作業例: chip Tj は 0.1s 付近で頭打ち傾向）
- [ ] 非発熱層が底面温度(300K)〜chip温度の間に収まる

### チェック3: Δt（deltaT）が崩壊していないか ★

```bash
grep -E "^deltaT|^Time =" log.chtMultiRegionFoam | tail
grep -iE "Courant|Diffusion Number" log.chtMultiRegionFoam | tail
```

**固体のみの場合のΔtの性質**:
```
固体は流速0 → Co=0 → maxCoは効かない
Δtを縛るのは拡散数 Di = α·Δt/Δx² ≤ maxDi
  → Δt ≤ maxDi·Δx²/α
maxDi=20 は maxDi=5 比で約4倍のΔtを許容（高α材Cuの計算時間対策）
作業例の典型 Δt ≈ 6e-7 s（シリアル0.5sで約9.5h）
```
- [ ] 固体のみでは**Δtは比較的安定**（流体ケースのように流れ発達で1/35に縮む現象は起きにくい）
- [ ] Δtが突然桁落ち＝局所セル不良・不安定の兆候（checkMeshの最悪セル周辺を疑う）

> **Δt制約源の切り分け**（最適化したい場合）: `Courant` と `Diffusion Number` のどちらが上限に張り付いているかをgrepで確認する。固体では Diffusion Number が律速のはず。もし現象の分解能（早期の急峻な過渡を解像するため）でΔtを小さくしたいのか、安定性(Di)で小さくせざるを得ないのかで、対処（maxDi緩和 vs writeInterval/メッシュ）が変わる。

### チェック4: 進捗・完了見積もり

```bash
grep "ExecutionTime" log.chtMultiRegionFoam | tail -1
```
- ExecutionTime と現在Timeから残り時間を見積もる。Δtがほぼ一定なら線形外挿で概算可。

---

## 完了ゲート（→ [7]検証 / ブランチA[9a] / ブランチB[8]）

```bash
tail -10 log.chtMultiRegionFoam | grep -E "End|ExecutionTime"
ls -d [0-9]* 2>/dev/null | sort -n          # 時刻ディレクトリ生成確認
```

```
[6] 完了チェック
  Part0 前提
    □ ddtSchemes Euler / hFinal有 / fluid()有 / 0.orig p有
    □ controlDict: endTime / maxDi / writeInterval
  Part1 前処理
    □ 0/<region> に T,p / changeDictionary適用（heatsink_bottom=fixedValue確認）
    □ decomposePar 全領域
  Part2 起動
    □ tee付きで起動
  6a 起動時sanity（数秒）
    □ 全6領域mesh読込  □ 発熱cell数=chip ★  □ fvOptions認識  □ 起動Min/maxT妥当
  6b 計算中
    □ h残差低下  □ Min/maxT物理的  □ Δt非崩壊（Di律速確認）
  完走
    □ log末尾 End / 時刻ディレクトリ生成 / 並列なら reconstructPar
```

並列の結果統合（ブランチBで時刻フィールドを使う場合）:
```bash
reconstructPar -allRegions -latestTime    # または対象時刻
```

> **Zth抽出（ブランチA[9a]）は log から直接**取れるので、reconstructParを待たずに着手できる。ParaView（ブランチB[8]）は時刻フィールドが要るので reconstructPar が前提。

---

## 他形状への転用（差分ポイント）

| 変わる前提 | 6で変わる箇所 |
|---|---|
| 流体領域が入る | 0.origに U,p_rgh,k,ε等／固体からは流体場を削除／6bでΔtが**Co律速**に変わり流れ発達で縮む（phase5-2: 1/35）／turbulence収束も監視 |
| 定常解析（例: 室内気流） | `ddtSchemes steadyState`＋simple系＋residualControl／6bは残差プラトーで収束判定（Min/maxTでなく目的関数を監視） |
| パラメトリックsweep | Part0/メッシュ固定、Part1のchangeDict（角度=速度ベクトル変更等）だけ差替え→`Allrun_calc`連続実行 |
| 発熱がパルス/起動過渡 | fvOptionsを時間関数化／writeIntervalを過渡に合わせ密に |

**不変なもの**: 起動数秒で弾く(6a)→実行中監視(6b)の二段検査、4大起動失敗要因（Euler/hFinal/fluid()/p）、Zthはlog由来でreconstruct不要という分岐構造。
