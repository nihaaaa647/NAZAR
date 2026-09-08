import pandas as pd
import pytest

from pipeline.consolidate import parse_letter_no, fiscal_year_bounds, containing_fy_end


@pytest.mark.parametrize('text,expected', [
    ('LN/MP18129/2024-2025/3', [18129, 2024, 2025, 3]),
    ('LN/\t MP319/2024-2025/32', [319, 2024, 2025, 32]),
    (' LN/MP319/2024-2025/32\n', [319, 2024, 2025, 32]),
])
def test_real_letter_formats(text, expected):
    assert parse_letter_no(pd.Series([text], dtype='string')).iloc[0].tolist() == expected


@pytest.mark.parametrize('text', [None, '', 'bad', 'LN/MPx/2024-2025/3', 'LN/MP319/2024/32', 'prefixLN/MP319/2024-2025/32'])
def test_bad_letters_remain_missing(text):
    assert parse_letter_no(pd.Series([text], dtype='string')).iloc[0].isna().all()


def test_financial_year_boundaries_and_nulls():
    start, end = fiscal_year_bounds(pd.Series([2023, None]))
    assert start.iloc[0] == pd.Timestamp('2023-04-01')
    assert end.iloc[0] == pd.Timestamp('2024-03-31')
    assert pd.isna(start.iloc[1]) and pd.isna(end.iloc[1])
    actual = pd.to_datetime(pd.Series(['2024-03-31', '2024-04-01', None]))
    close = containing_fy_end(actual)
    assert close.iloc[:2].tolist() == [pd.Timestamp('2024-03-31'), pd.Timestamp('2025-03-31')]
    assert pd.isna(close.iloc[2])
