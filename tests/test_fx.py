import json
import pytest

from app.fx import parse_price, quote_day, load_snapshot, rate_for, convert, FXError
from app.errors import DomainError
from decimal import Decimal


def test_parse_price_defaults_cny():
    amount, currency = parse_price('100')
    assert amount == Decimal('100') and currency == 'CNY'


def test_parse_price_with_currency_suffix():
    for text in ('100 USD', '100USD', ' 100 usd '):
        amount, currency = parse_price(text)
        assert amount == Decimal('100') and currency == 'USD'


def test_parse_price_fullwidth_and_commas():
    assert parse_price('１，２３４．５ USD') == (Decimal('1234.5'), 'USD')


def test_parse_price_rejects_unknown_currency():
    with pytest.raises(DomainError) as exc:
        parse_price('19 EUR')
    assert exc.value.code == 'CURRENCY'


def test_parse_price_rejects_negative():
    with pytest.raises(DomainError) as exc:
        parse_price('-1 USD')
    assert exc.value.code == 'RANGE'


def test_quote_day_utc_calendar_date():
    assert quote_day('2026-11-17T08:00:00+08:00') == '2026-11-17'
    assert quote_day('2026-11-17T00:00:00Z') == '2026-11-17'


def test_quote_day_invalid():
    with pytest.raises(DomainError) as exc:
        quote_day('not-a-date')
    assert exc.value.code == 'DATE'


def test_bundled_snapshot_loads():
    snapshot = load_snapshot()
    assert snapshot['rates']['USD']['2026-11-17'] == Decimal('7.1200')


def test_rate_for_missing_day_raises(tmp_path):
    snapshot = load_snapshot()
    with pytest.raises(FXError):
        rate_for(snapshot, 'USD', '2026-11-19')


def test_load_snapshot_missing_file(tmp_path):
    with pytest.raises(FXError):
        load_snapshot(str(tmp_path / 'nope.json'))


def test_load_snapshot_broken_json(tmp_path):
    path = tmp_path / 'fx.json'
    path.write_text('{broken', encoding='utf-8')
    with pytest.raises(FXError):
        load_snapshot(str(path))


def test_load_snapshot_rejects_negative_rate(tmp_path):
    path = tmp_path / 'fx.json'
    path.write_text(json.dumps({'rates': {'USD': {'2026-11-17': '-1'}}}), encoding='utf-8')
    with pytest.raises(FXError):
        load_snapshot(str(path))


def test_convert_quantized():
    assert convert('45', '7.12') == Decimal('320.40')
