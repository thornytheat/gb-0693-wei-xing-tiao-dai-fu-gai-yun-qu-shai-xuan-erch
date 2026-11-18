# 深度登记 卫星条带覆盖与云区筛选

- 规模：中型
- 使用者与工作流：遥感影像采购数据员，读取轨道条带清单，筛选能覆盖目标纬带的可用影像。
- 核心规则：目标经度区间支持跨180度拆分；覆盖只算并集，云掩膜从有效条带扣除，重复条带不增加面积。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 条带接收 | 运行条带接收并复核证据 | `POST /api/m1`；`/work/1` | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py` |
| M2 坐标契约 | 运行坐标契约并复核证据 | `POST /api/m2`；`/work/2` | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py` |
| M3 云区剔除 | 运行云区剔除并复核证据 | `POST /api/m3`；`/work/3` | `app/modules/m3_cloud/rules.py` | `tests/test_m3.py` |
| M4 覆盖并集 | 运行覆盖并集并复核证据 | `POST /api/m4`；`/work/4` | `app/modules/m4_union/rules.py` | `tests/test_m4.py` |
| M5 缺口定位 | 运行缺口定位并复核证据 | `POST /api/m5`；`/work/5` | `app/modules/m5_gaps/rules.py` | `tests/test_m5.py` |
| M6 采购候选 | 运行采购候选并复核证据（多币种按报价日期快照折算，确认单锁定） | `POST /api/m6`；`/work/6`；`GET /api/fx` | `app/modules/m6_purchase/rules.py`、`app/fx.py`、`app/store.py` | `tests/test_m6.py`、`tests/test_m6_currency.py`、`tests/test_purchase_orders.py` |
| M7 交付核验 | 运行交付核验并复核证据 | `POST /api/m7`；`/work/7` | `app/modules/m7_delivery/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | BOM | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py::test_bom_strip` |
| TRAP-06 | 全角坐标 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_number_fullwidth` |
| TRAP-07 | 缺失坐标 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_missing_coordinate` |
| TRAP-14 | 重复场景 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_duplicate_does_not_cover_twice` |
| TRAP-19 | 质量优先 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_cloud/rules.py` | `tests/test_m3.py::test_quality_priority` |
| TRAP-22 | 别名等价类 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_alias_equivalence` |
| TRAP-23 | 跨日界线 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_dateline_split` |
| TRAP-25 | 版本有效性 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_coordinates/rules.py` | `tests/test_m2.py::test_newest_version_rules` |
| TRAP-26 | 多币种混用 | 按最新汇率重算改掉已确认成本，或只留原币无法比较 | 按报价日期取汇率快照折算；已确认单锁定原币与下单汇率，重估差额只读 | `app/fx.py`、`app/modules/m6_purchase/rules.py` | `tests/test_m6_currency.py`、`tests/test_purchase_orders.py` |
| TRAP-27 | 汇率源失败 | 失败即中断或用空值污染候选 | 同原文有旧批次则整体回退旧版候选，否则隔离外币报价 | `app/modules/m6_purchase/service.py` | `tests/test_purchase_orders.py::test_failure_keeps_previous_candidates` |
| TRAP-28 | 迟到旧报价 | 新到的便宜报价倒退已确认采购单 | 已确认场景的后续报价以STALE_QUOTE隔离，台账不可变 | `app/modules/m6_purchase/rules.py`、`app/store.py` | `tests/test_purchase_orders.py::test_late_quote_cannot_reverse_confirmed_order` |
| TRAP-29 | 批次重试 | 重试产生重复采购单 | run_id幂等键加采购单主键(run_id,canonical)去重 | `app/store.py` | `tests/test_purchase_orders.py::test_retry_same_batch_creates_no_extra_purchase_orders` |

## 对账规则

输入记录 = 采信记录 + 隔离记录 + 相同行重复。重复表头与空行单独记数。业务合计按阶段中的守恒或差值列复核。运行清单有原文SHA256、规则版本与耗时；相同规则版本下同文重复提交复用批次。

## 已知不覆盖

部署为本地单用户工具，不连接外部上游系统。CSV单文件5MB及一万条业务记录上限；不推断未提供的未知数据。
