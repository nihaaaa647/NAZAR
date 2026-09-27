"""The scanner-app watermark ("Scanned with OKEN Scanner", CamScanner logo) must
never itself become duplicate evidence, in either photo tier."""
import importlib

pipeline = importlib.import_module('scripts.pipeline')


def img(work_id, md5, width, height, phash='00' * 8):
    return {'work_id': work_id, 'md5': md5, 'width': width, 'height': height,
            'phash': phash, 'source_filename': f'{work_id}.pdf'}


def test_is_photo_evidence_rejects_scanner_strip():
    assert pipeline.is_photo_evidence(img('1', 'a', 656, 83)) is False   # OKEN footer
    assert pipeline.is_photo_evidence(img('1', 'a', 74, 106)) is False   # CamScanner logo
    assert pipeline.is_photo_evidence(img('1', 'a', 1275, 1754)) is True  # real scan page


def test_identical_watermark_strip_is_not_a_tier1_pair():
    # Same watermark bytes attached to three unrelated works.
    strip = [img('178450', 'wm', 656, 83), img('178656', 'wm', 656, 83), img('179001', 'wm', 656, 83)]
    # A genuinely reused full-size completion photo across two works.
    photo = [img('200', 'reuse', 1600, 1200), img('201', 'reuse', 1600, 1200)]
    pairs, image_matches, stats = pipeline.photo_duplicates(strip + photo)

    tier1 = [p for p in pairs if p['tier'] == 'photo_identical']
    assert {tuple(sorted(p['work_ids'])) for p in tier1} == {('200', '201')}
    assert stats['tier1_watermark_strips_suppressed'] == 1
    assert sorted(stats['tier1_watermark_groups'][0]) == ['178450', '178656', '179001']
