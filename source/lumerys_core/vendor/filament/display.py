"""Fixed source-derived display only. No upper white cut, no processing changes."""
import numpy as np

def reference(source):
    # Fixed for the lifetime of the dialog; linked RGB channels, full-frame min.
    black = float(np.min(source))
    sample = source[::max(1, source.shape[0]//512), ::max(1, source.shape[1]//512)]
    median = float(np.median(sample))
    span = float(np.max(source)) - black
    scale = max(median-black, span*1e-4, abs(black)*1e-12, 1e-30)
    return black - scale*.02, scale

def map_image(image, ref):
    black, scale = ref
    t = np.arcsinh(np.maximum((image.astype(np.float64)-black)/scale, 0))
    return (t/(1+t)).astype(np.float32)
