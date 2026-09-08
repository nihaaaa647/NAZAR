import io

import pandas as pd
from PIL import Image

from scripts.profile_data import jpeg_streams, image_measurements, attachment_inventory, profile_table


def test_jpeg_probe_preserves_bytes_and_counts_multiple_streams():
    buffer = io.BytesIO()
    Image.new('RGB', (16, 12), 'white').save(buffer, format='JPEG')
    jpeg = buffer.getvalue()
    assert jpeg_streams(b'%PDF-1.5\n' + jpeg + b'\n' + jpeg) == [jpeg, jpeg]
    assert image_measurements(jpeg)['width'] == 16
    assert jpeg_streams(b'%PDF-corrupted\xff\xd8\xff') == []


def test_inventory_excludes_unreferenced_and_reports_missing(tmp_path):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    Image.new('RGB', (16, 12), 'white').save(corpus / 'real.jpg')
    (corpus / 'synthetic.pdf').write_bytes(b'not real evidence')
    frame = pd.DataFrame([{'_source_csv': 'works_with_images.csv', 'WORK_ID': '1',
                           'local_image_filenames': 'real.jpg;missing.jpg'}])
    result = attachment_inventory(corpus.resolve(), frame, tmp_path)
    assert result['decoded_images'] == 1
    assert result['unreferenced_paths'] == ['synthetic.pdf']
    assert result['missing_referenced_paths'] == ['missing.jpg']


def test_date_failures_distinguish_missing_from_invalid():
    result = profile_table(pd.DataFrame({'SANCTION_DATE': pd.Series(['01-Apr-2024', None, '31-Feb-2024'], dtype='string')}))
    date = result['dates']['SANCTION_DATE']
    assert date['missing'] == 1
    assert date['parse_failures'] == 1
    assert date['parse_failure_rate_non_null'] == .5


def test_tenure_dates_use_portal_timestamp_format():
    result = profile_table(pd.DataFrame({'TENURE_START_DATE': pd.Series(['Jun 4, 2024 12:00:00 AM'], dtype='string')}))
    assert result['dates']['TENURE_START_DATE']['parse_failures'] == 0
    assert result['dates']['TENURE_START_DATE']['min'] == '2024-06-04 00:00:00'
