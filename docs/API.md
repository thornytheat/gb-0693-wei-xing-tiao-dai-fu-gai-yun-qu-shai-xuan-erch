# 接口

`POST /api/run`：JSON中的csv文本，省略使用样例；或multipart字段file。最大5MB。

`POST /api/m1`至`POST /api/m7`：独立运行到指定模块，JSON结构同运行接口。

`GET /api/history`：历史批次。`POST /api/review`接收id、revision和decision（通过或退回），通过时采购单转为已确认并锁定原币金额与下单汇率。`GET /api/evidence.csv`提供单一证据导出，采购候选阶段含原币金额、币种、下单汇率、折算金额_CNY、重估差额_CNY与采购状态。

`GET /api/fx`：返回当前汇率快照（币种→报价日期→对CNY汇率）。快照源损坏或缺失返回502 FX_LOAD；采购管线在载入失败时回退旧版候选而不是中断。

结构错误422，版本变化409，文件过大413，汇率源失败502；错误返回code与message。所有页面可从左侧七个模块入口访问。

`GET /api/runs/<id>`读取指定批次；页面与证据CSV通过run_id查询参数绑定批次，模块导航保留该参数。

JSON请求体必须是对象，数组、标量、null、损坏JSON及错误上传字段返回400，且不运行默认样例。
