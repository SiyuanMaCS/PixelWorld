import html
import json
from pathlib import Path
from tools.prepare_pages_site import build,rewrite

REV='1'*40


def test_pages_uses_exact_raw_media_without_changing_code_or_personal_home(tmp_path):
    root=tmp_path/'repo';case=root/'pixelworld/run/case';case.mkdir(parents=True)
    (root/'index.html').write_text('<img src="avatar.png">Personal homepage')
    (root/'avatar.png').write_bytes(b'personal-avatar')
    for name in ['poster.png','pixels.rgb.gz','source.mp4']:(case/name).write_bytes(b'media')
    config=html.escape(json.dumps({'pixels':'pixels.rgb.gz','poster':'poster.png','width':256}),quote=True)
    original=f'<div data-video=\x27{config}\x27></div><video src="source.mp4"></video><img src=poster.png><pre>open("source.mp4")</pre><a href="../index.html">Home</a>'
    (case/'index.html').write_text(original)
    result=build(root,tmp_path/'site','SiyuanMaCS/example',REV)
    text=(tmp_path/'site/pixelworld/run/case/index.html').read_text()
    assert (tmp_path/'site/index.html').read_text()==(root/'index.html').read_text()
    assert (tmp_path/'site/avatar.png').read_bytes()==b'personal-avatar'
    assert not (tmp_path/'site/pixelworld/run/case/pixels.rgb.gz').exists()
    assert (case/'pixels.rgb.gz').read_bytes()==b'media'
    prefix=f'https://raw.githubusercontent.com/SiyuanMaCS/example/{REV}/pixelworld/run/case/'
    assert prefix+'source.mp4' in text and prefix+'pixels.rgb.gz' in text
    assert '<pre>open("source.mp4")</pre>' in text
    assert 'href="../index.html"' in text
    assert result['excluded_media_files']==3 and not result['source_media_deleted']


def test_sparse_checkout_rewrites_media_known_to_git_even_if_not_downloaded():
    known={'pixelworld/a/index.html','pixelworld/a/p.png','pixelworld/pixels.rgb.gz'}
    original='<img src="p.png"><script>const p="../pixels.rgb.gz";</script><img src="https://other.example/x.png">'
    text=rewrite(original,'pixelworld/a/index.html',known,'o/r',REV)
    assert f'/{REV}/pixelworld/a/p.png' in text
    assert f'/{REV}/pixelworld/pixels.rgb.gz' in text
    assert 'https://other.example/x.png' in text
