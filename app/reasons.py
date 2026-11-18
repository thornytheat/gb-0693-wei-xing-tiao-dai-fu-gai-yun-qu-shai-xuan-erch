REASONS = {"COLUMNS":"列数不符", "HEADER":"字段缺失", "MISSING":"必填值为空", "NUMBER":"数值无效", "RANGE":"超出范围", "DUPLICATE":"相同行重复", "CONFLICT":"同键数值冲突", "VERSION":"版本冲突", "EMPTY":"输入为空", "STRUCTURE":"文件结构错误", "CURRENCY":"不支持的币种", "DATE":"报价日期无效", "FX_MISSING":"报价当日缺少汇率快照", "STALE_QUOTE":"旧报价不得倒退已确认采购单", "FX_FALLBACK":"汇率载入失败，沿用旧版候选"}
def isolate(ctx, row, code, detail):
    ctx['quarantine'].append({**row, '原因码': code, '原因': detail})
