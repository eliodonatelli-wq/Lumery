"""Native-resolution luminance mask for stellar attenuation."""
import numpy as np
from scipy.ndimage import median_filter


def build_mask(starless, contrast, check_cancel):
    luminance = np.empty(starless.shape[:2], dtype=np.float32)
    for row in range(0, luminance.shape[0], 128):
        check_cancel()
        band = starless[row:row + 128]
        target = luminance[row:row + 128]
        if band.ndim == 2:
            target[:] = band
        else:
            target[:] = .2126 * band[..., 0] + .7152 * band[..., 1] + .0722 * band[..., 2]
    # A small median rejects isolated spikes without broadening bright edges.
    smooth = median_filter(luminance, size=3)
    del luminance
    check_cancel()
    stride = max(1, int(np.ceil(np.sqrt(smooth.size / 131072))))
    low, high = np.percentile(smooth[::stride, ::stride], [15, 98])
    if high - low > 1e-7:
        smooth -= low
        smooth /= high - low
        np.clip(smooth, 0, 1, out=smooth)
        # Symmetric contrast around the midpoint preserves both endpoints.
        for row in range(0, smooth.shape[0], 128):
            check_cancel()
            band = smooth[row:row + 128]
            bright = band ** contrast
            band[:] = bright / (bright + (1 - band) ** contrast)
            band[:] = band * band * (3 - 2 * band)
    else:
        smooth.fill(0)
    smooth.setflags(write=False)
    return smooth
