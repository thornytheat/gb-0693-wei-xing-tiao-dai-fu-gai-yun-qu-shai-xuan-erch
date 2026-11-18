import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.errors import DomainError
from app.numeric import number

CURRENCIES = ('CNY', 'USD')
FX_FILE = Path(__file__).resolve().parent.parent / 'sample_data' / 'fx_rates.json'


class FXError(DomainError):
    def __init__(self, message, status=502):
        super().__init__('FX_LOAD', message, status)


def load_snapshot(source=None):
    """载入汇率快照。来源为JSON文件路径；失败时由调用方决定回退，本函数不静默吞错。"""
    path = Path(source) if source else FX_FILE
    override = bool(source) or bool(os.environ.get('FX_SOURCE'))
    try:
        text = path.read_text(encoding='utf-8-sig')
        data = json.loads(text)
    except FileNotFoundError:
        raise FXError(('外部汇率源' if override else '内置汇率快照') + '不存在: ' + str(path))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FXError('汇率快照格式损坏: ' + str(path) + ' / ' + exc.__class__.__name__)
    if not isinstance(data, dict) or not isinstance(data.get('rates'), dict):
        raise FXError('汇率快照缺少rates表')
    rates = {}
    for currency, table in data['rates'].items():
        if currency not in CURRENCIES or not isinstance(table, dict):
            raise FXError('汇率快照含未知币种: ' + str(currency))
        parsed = {}
        for day, value in table.items():
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(day)):
                raise FXError('汇率日期格式无效: ' + str(day))
            rate = number(value)
            if rate <= 0:
                raise FXError('汇率必须为正数: ' + currency + ' ' + str(day))
            parsed[day] = rate
        rates[currency] = parsed
    return {
        'base': str(data.get('base', 'CNY')),
        'source': str(data.get('source', path.name)),
        'as_of': str(data.get('as_of', '')),
        'rates': rates,
        'path': str(path),
    }


def rate_for(snapshot, currency, day):
    """按报价日期取汇率快照值；无当日记录即失败，绝不推断或取最新值。"""
    if not snapshot:
        raise FXError('汇率快照不可用: ' + currency + ' ' + day)
    table = snapshot['rates'].get(currency)
    if table is None:
        raise FXError('汇率快照缺少币种: ' + currency)
    rate = table.get(day)
    if rate is None:
        raise FXError('汇率快照缺少 ' + currency + ' 在 ' + day + ' 的记录')
    return rate


def quote_day(captured):
    """从ISO 8601采集时间提取报价日期（UTC日历日），失败抛出DomainError。"""
    text = str(captured).strip()
    try:
        if text.endswith('Z'):
            parsed = datetime.fromisoformat(text[:-1]).replace(tzinfo=timezone.utc)
        else:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
    except ValueError:
        raise DomainError('DATE', '报价时间格式无效: ' + text)
    return parsed.date().isoformat()


_PRICE_RE = re.compile(r'^(.+?)\s*([A-Za-z]{3})$')


def parse_price(raw):
    """解析价格文本，允许裸数字（默认CNY）或数字加币种后缀，如 100 USD / 100USD。"""
    text = str(raw).strip()
    match = _PRICE_RE.match(text)
    if match:
        amount_text, currency = match.group(1).strip(), match.group(2).upper()
    else:
        amount_text, currency = text, 'CNY'
    amount = number(amount_text)
    if amount < 0:
        raise DomainError('RANGE', '价格不能为负')
    if currency not in CURRENCIES:
        raise DomainError('CURRENCY', '不支持的币种: ' + currency)
    return amount, currency


def convert(amount, rate):
    return (number(amount) * number(rate)).quantize(Decimal('0.01'))
