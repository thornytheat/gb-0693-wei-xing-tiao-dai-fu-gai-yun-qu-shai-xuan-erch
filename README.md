# 卫星条带覆盖与云区筛选

遥感影像采购数据员使用本工具完成：读取轨道条带清单，筛选能覆盖目标纬带的可用影像。

## 业务

目标经度区间支持跨180度拆分；覆盖只算并集，云掩膜从有效条带扣除，重复条带不增加面积。七个模块：条带接收、坐标契约、云区剔除、覆盖并集、缺口定位、采购候选、交付核验。模块独立API及页面入口见docs/API.md。样例中包含真实常见脏数据，原因码和原始行号在隔离面板及证据文件中可复核。

## 启动与验证

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
docker compose config --quiet
```

打开 http://localhost:18207 。点击“运行样例”，或展开输入区提交CSV。切换七个模块查看计算依据。复核区可通过或退回，同一版本仅允许一次复核。证据CSV包含所有阶段与隔离行，批次内容不因复核变更。

采购报价支持CNY与USD混用：按每条报价的报价日期从汇率快照取当日汇率折算CNY后排名；复核通过的采购单锁定下单时原币金额与汇率，后续重算只在“重估差额_CNY”列做只读对比，不修改已确认成本。汇率源载入失败时沿用同原文旧版候选；迟到报价不能倒退已确认单；重试同一批次不新增采购单。汇率快照为离线文件`sample_data/fx_rates.json`，可用环境变量`FX_SOURCE`覆盖，`GET /api/fx`可核对当前快照。

SQLite保存在命名卷records；容器重建保留历史。只在确认不再需要数据时执行 `docker compose down -v` 重建。端口可通过.env中的PORT调整。本地也可 `pip install -r requirements.txt` 后 `python -m app.main`。

## 定义与限制

详见docs/DATA-DICTIONARY.md、docs/DEPTH.md。单文件最大5MB/一万行，本工具按确定性文件离线复算，不查询外部业务系统。源码位于app，测试位于tests，样例位于sample_data。
