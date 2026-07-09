# 手順書 [5] メッシュ生成 + checkMesh採取（4bへの引き継ぎ）

> 上位ルーティン `OpenFOAM_calc_routine.md` の §2[5]・§3 を展開した詳細手順書。
> 手順書[4a]の出口を受け、メッシュを生成して**実測値を採取し4bへ渡す**までを扱う。
> 作業例はパワーデバイス模擬（6領域、phase5-4構成）。

---

## 0. このステップの位置づけ

**5 = メッシュを作るだけでなく、「4bが書けるようにするための実測値を採取する」ステップ。** 採取項目（実スナップ底面Z座標・実パッチ名・残骸パッチ）が無いと4bは正しく書けない。ここがフィードバックの“折り返し点”。

```
[4a]設定 ──► [5]生成+checkMesh採取 ──► [4b]依存設定 ──► [6]
                   │                       ▲
                   └── 実Z座標 / 実パッチ名 ─┘
```

**このステップは原則シリアル実行**（メッシュ生成→分割まで）。並列化（decomposePar）は4b〜6で行う。

---

## 1. 実行シーケンス全体像

```
blockMesh                              # 背景メッシュ
  └► checkMesh                         # 背景bbox確認（採取①）
snappyHexMesh -overwrite               # STLフィット + cellZone作成
  └► checkMesh                         # cellZone数 / 品質 / 全体bbox（採取②③）
        │
   〔cellZone決定〕 cellZone数 = 層数 か？
        ├─ YES → topoSet スキップ
        └─ NO  → topoSet（boxToCellで作り直し, 手順書[4a]§7）
        │
splitMeshRegions -cellZones -overwrite # 領域別polyMeshに分割
  └► foamListRegions                   # 領域名リスト確認
  └► checkMesh -region <底面領域>       # 実スナップ底面Z（採取④）★
  └► cat constant/<region>/polyMesh/boundary  # 実パッチ名 / 残骸（採取⑤⑥）★
```

---

## 2. blockMesh 実行 + 背景checkMesh

```bash
blockMesh
checkMesh | grep "Overall domain bounding box"
```

**採取①: 背景bounding box が全層を内包するか。**

```
Overall domain bounding box (-0.035 -0.035 -0.0055) (0.035 0.035 0.0011)
                             └── 全層(最大±30mm, Z -4.94〜0.60mm)を含む ✓
```

- [ ] bboxが全層 + 余白を含む。含まないなら blockMeshDict の頂点座標を見直す（4aへ戻る）
- [ ] `Mesh OK.` で終わる

---

## 3. snappyHexMesh 実行

```bash
snappyHexMesh -overwrite
```

`-overwrite` で時刻ディレクトリを作らず `constant/polyMesh/` に直接書く。

ログ末尾の品質チェックで全項目0が理想だが、接触積層では非直交・スキューが残る（§4で判断）。

---

## 4. checkMesh の読み方（snappy後・分割前）

```bash
checkMesh > log.checkMesh.snappy 2>&1
```

ログを保存して3項目を見る。

### 採取②: cellZone数（最重要の分岐材料）

```bash
grep -A 20 "Number of cellZones" log.checkMesh.snappy
# または
grep -iE "cellZone|cell zones" log.checkMesh.snappy
```

期待される見え方:
```
Number of cellZones: 6
   <cellZone名>  ...  <cell数>
   chip          ...  約 5,000
   dbc_cu_top    ...  約 40,000
   ...
   heatsink      ...  約 130,000
```

- [ ] cellZone数 = 層数（作業例なら6）
- [ ] **各cellZoneのcell数が0でない**（空のzoneがあると分割後にその領域が消える）
- [ ] cellZone数 ≠ 層数、または空zoneあり → §5でtopoSetフォールバックへ

### 採取③: 全体品質（非直交・スキューネス）

```bash
grep -E "non-orthogonality|skewness" log.checkMesh.snappy
```

接触する直方体積層での典型値と判定:

| 項目 | 典型値（作業例） | 判定 |
|---|---|---|
| Max non-orthogonality | 〜82度 | 警告は出るが固体伝導では可。`nNonOrthogonalCorrectors 2` で対応 |
| Max skewness | 〜4.0 | 上限を僅かに超えても固体伝導では実用上可 |

```
***Number of severely non-orthogonal (> 70 degrees) faces: ...
 <<Writing ... faces ...
Max skewness = 4.02  ***Max skewness ... too high
```

> `***` や `Failed` が出ても、**固体熱伝導に限れば**これらは即NGではない。流体（対流）を含むケースでは非直交82度は流れ場に悪影響なので、その場合は refinementSurfaces のlevel差を縮める / nCellsBetweenLevels を増やす（4aへ戻る）。

### 全体bbox（参考）

```bash
grep "Overall domain bounding box" log.checkMesh.snappy
```
snappy後はSTL外周（±30mm）の footprint になり、背景の±35mm外周セルは除去されている（locationsInMeshで残す指定をしていないため）。

---

## 5. cellZone決定の実行

手順書[4a]§6の決定木をここで確定する。

```
checkMesh の cellZone数 = 層数 かつ 各zone非空？
   ├─ YES → topoSet 不要。そのまま §6（splitMeshRegions）へ
   └─ NO  → topoSetDict(boxToCell, 手順書[4a]§7) を実行してcellZone作り直し
            topoSet
            再度 checkMesh で cellZone数を再確認
```

> phase5-3/5-4 は `locationsInMesh` でcellZone作成に成功し topoSet不要だった例。phase5-1 は失敗してtopoSetへ切り替えた例。**checkMeshで確認してから決める**。

topoSetが必要な場合:
```bash
topoSet
checkMesh | grep -iE "cellZone|cell zones"   # 6 zones / 全zone非空を再確認
```

---

## 6. splitMeshRegions 実行

cellZoneごとに独立した polyMesh に分割する。

```bash
splitMeshRegions -cellZones -overwrite
```

完了後、領域名リストを確認:

```bash
foamListRegions          # 全領域
foamListRegions solid    # 固体のみ（fluidがあれば分離）
```

期待:
```
chip
dbc_cu_top
dbc_ceramic
dbc_cu_bot
baseplate
heatsink
```

この時点で `constant/<region>/polyMesh/` が領域ごとに生成される。**界面パッチ `<A>_to_<B>` はsplitMeshRegionsが自動生成する**（命名は領域名から決まる）。

---

## 7. 領域別checkMeshで実スナップ底面Z座標を採取 ★

**採取④: 4bの底面パッチ作成（boxToFace）に必須。**

底面fixedValueを与える領域（作業例ではheatsink）に対して:

```bash
checkMesh -region heatsink | grep "Overall domain bounding box"
```

```
Overall domain bounding box (-0.0301 -0.0301 -0.004948) (0.0301 0.0301 -0.003948)
                                            └─ 実底面Z         └─ 実上面Z
```

**ここが核心**: 設計値 −4.94mm（−0.00494）に対し、snapで実値は **−4.948mm（−0.004948）** 程度にずれる（phase5-3でbaseplate底が −3.940→−3.948mm にずれた事例と同種、ズレは数µm〜10µm）。

4bの `boxToFace` のZ範囲は、この**実値 ±0.011mm** で設定する:
```
実底面 −0.004948 → box Z範囲 = −0.004959 〜 −0.004937
```

- [ ] 実底面Zを設計値で代用しない（`Read 0 faces from faceSet` の典型原因）
- [ ] 採取した実値を採取表（§9）に記録

> 上面側に界面熱抵抗パッチを別途切り出す必要がある場合も、同様に実Z座標を採取する。

---

## 8. cat boundary で実パッチ名・残骸パッチを採取 ★

**採取⑤⑥: 4bの changeDictionaryDict に必須。**

各領域の boundary ファイルを読む:

```bash
cat constant/heatsink/polyMesh/boundary
```

典型的な構造:
```
6
(
    heatsink                 { type wall;       nFaces 12000; ... }  // 外表面(側面+底面が混在)
    heatsink_to_baseplate    { type mappedWall; nFaces 3600;  ... }  // 界面(カップリング)
    ...
)
```

ポイント:
- 外表面パッチ `<region>`（側面・露出上下面が**混在**）— 底面を切り出す前はここに底面が含まれる
- 界面パッチ `<region>_to_<neighbor>`（type `mappedWall`）— カップリング条件を書く対象
- **採取⑤**: これら実パッチ名をそのまま changeDict に列挙（`.*` ワイルドカード併用禁止。手順書[4b]で詳述）

### 採取⑥: 残骸パッチの検出

topoSetのbox重複や分割の都合で、**ある領域に隣接層の名前のパッチが残留**することがある。

検出のしかた:
```bash
for r in $(foamListRegions); do
  echo "=== $r ==="
  grep -E "^\s+[a-z]" constant/$r/polyMesh/boundary | awk '{print $1}'
done
```

異常例（phase5-3の事例）:
```
=== dbc_cu_bot ===
dbc_cu_bot
dbc_cu_bot_to_dbc_ceramic
dbc_cu_bot_to_baseplate
dbc_ceramic              ← ★残骸（dbc_cu_bot領域に別層名のパッチ, nFaces=16）
```

- 残骸パッチは4bの changeDict で **zeroGradient（断熱）** にして無害化する
- [ ] 各領域のパッチ一覧を採取表に記録し、残骸の有無を明示

---

## 9. 採取表（4bへの引き継ぎ — このステップの“出口”）

5の成果を1枚にまとめて4bへ渡す。下記を埋めた状態が完了形。

```
─────────────────────────────────────────────────────────
■ cellZone（採取②）
  cellZone数 = 6 / 層数 = 6  → 一致 ✓ / topoSet: 不要 or 実行済み

■ 品質（採取③）
  Max non-orthogonality = 82度（固体伝導で可）
  Max skewness = 4.02（可）
  → fvSolution: nNonOrthogonalCorrectors 2

■ 実スナップ底面Z（採取④）★→ 4b boxToFace
  heatsink 実底面Z = −0.004948 m（設計 −0.00494）
  → boxToFace Z範囲 = −0.004959 〜 −0.004937

■ 実パッチ名（採取⑤）★→ 4b changeDict
  領域ごとの実パッチ名一覧:
   chip       : chip, chip_to_dbc_cu_top
   dbc_cu_top : dbc_cu_top, dbc_cu_top_to_chip, dbc_cu_top_to_dbc_ceramic
   ...
   heatsink   : heatsink, heatsink_to_baseplate
              （※底面は4bで heatsink_bottom を切り出す）

■ 残骸パッチ（採取⑥）★→ 4b changeDictでzeroGradient化
   dbc_cu_bot に dbc_ceramic（nFaces=16）残留 → 断熱化
   （無ければ「なし」と明記）
─────────────────────────────────────────────────────────
```

---

## 10. 完了ゲート（4bへ）

```
[5] 完了チェック
  □ blockMesh完走 / 背景bboxが全層内包（採取①）
  □ snappyHexMesh完走
  □ checkMesh: cellZone数 = 層数 / 全zone非空（採取②）
  □ checkMesh: 非直交・スキューを記録し許容判断（採取③）
  □ cellZone決定実行（snappy native or topoSet）
  □ splitMeshRegions完走 / foamListRegionsで領域確認
  □ checkMesh -region で実底面Z採取（採取④）★
  □ cat boundary で実パッチ名採取（採取⑤）★
  □ 残骸パッチの有無を確認・記録（採取⑥）★
  □ 採取表（§9）を埋めた
```

採取表が埋まっていれば4bの入力が揃う。

---

## 11. 他形状への転用（差分ポイント）

| 変わる前提 | 5で変わる箇所 |
|---|---|
| 流体領域が入る | 流体のcellZone/領域が増える。流体の品質（非直交・スキュー）は固体より厳しく判定（対流に効く）。foamListRegions fluid で確認 |
| 底面が複数領域に分散 | 採取④を各底面領域で実施 |
| 界面熱抵抗が複数界面 | 採取⑤で全界面パッチ名を漏れなく採取（両側ペア） |
| メッシュ品質がNG | 4aへ戻る（level差縮小 / nCellsBetweenLevels増 / refinementRegions追加） |
| パラメトリックスイープ | 5は1回だけ。メッシュ固定後は採取表も固定で再利用 |

**不変なもの**: 「生成→checkMeshで実測値採取→4bへ渡す」という折り返し構造、採取④⑤⑥の3点、cellZone決定の確認手順。
