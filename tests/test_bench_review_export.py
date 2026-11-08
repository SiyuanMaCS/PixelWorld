import gzip

import numpy as np

from tools.build_bench_review import export_pixels


def test_changed_candidate_retains_old_url_and_exports_new_rgb(tmp_path):
    source, target = tmp_path/'candidate', tmp_path/'public'
    source.mkdir()
    spec = {'width':2, 'height':2, 'frames':2, 'fps':4}
    pixels = np.full((2,2,2), 0x102030, dtype=np.uint32)
    np.savez_compressed(source/'pixels.npz', pixels=pixels)
    initial = export_pixels(source,target,spec)
    first = target/initial['pixels_file']
    before = first.read_bytes()
    assert export_pixels(source,target,spec) == initial
    pixels[...,1] = 0x405060
    np.savez_compressed(source/'pixels.npz', pixels=pixels)
    changed = export_pixels(source,target,spec)
    assert changed['pixels_file'] != initial['pixels_file']
    assert first.read_bytes() == before
    decoded = np.frombuffer(gzip.decompress((target/changed['pixels_file']).read_bytes()), dtype=np.uint8).reshape(2,2,2,3)
    np.testing.assert_array_equal(decoded[:,:,0], np.broadcast_to([16,32,48],(2,2,3)))
    np.testing.assert_array_equal(decoded[:,:,1], np.broadcast_to([64,80,96],(2,2,3)))
