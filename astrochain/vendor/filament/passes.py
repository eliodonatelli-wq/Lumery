"""Sequential 0–3 passes: frozen relative correction or optional reanalysis.

Same settings on each previous result. Cache lives only in RAM; no image exports
or analysis arrays are written to disk. At most one extra analysis is retained.
"""
import numpy as np
from .engine_local import analyze
from .engine_v2 import luminance


class PassPipeline:
    def __init__(self, source, protect_stars):
        self.source = source
        self.protect_stars = protect_stars
        self.first = None
        self.tail = None
        self.key = None
        self.results = []
        self.gain = None
        self.offset = None
        self.seconds = 0.

    @property
    def cache_bytes(self):
        analyses = sum(a.cache_bytes for a in (self.first, self.tail) if a is not None)
        maps = sum(a.nbytes for a in (self.gain, self.offset) if a is not None)
        return analyses + maps + sum(image.nbytes for image in self.results)

    def render(self, fine, extended, diffuse, global_amount, local_contrast,
               passes=1, reanalyze=False, *, progress=None):
        if passes not in (0, 1, 2, 3):
            raise ValueError('Il numero di passate deve essere 0, 1, 2 o 3.')
        settings = (fine, extended, diffuse, global_amount, local_contrast)
        if passes == 0 or global_amount == 0 or not any((fine, extended, diffuse, local_contrast)):
            return self.source.copy()
        tell = progress if progress is not None else lambda message: None
        if self.first is None:
            tell(f'Analisi passata 1/{passes} alla risoluzione originale…')
            self.first = analyze(self.source, protect_stars=self.protect_stars)
        key = settings + (bool(reanalyze),)
        if self.key != key:
            self.key = key
            self.results.clear()
            self.tail = self.gain = self.offset = None
            self.seconds = self.first.seconds
        while len(self.results) < passes:
            number = len(self.results) + 1
            if number == 1:
                tell(f'Elaborazione passata 1/{passes}…')
                image = self.first.render(*settings)
            elif reanalyze:
                self.tail = None
                tell(f'Rianalisi passata {number}/{passes} sul risultato precedente…')
                self.tail = analyze(self.results[-1], protect_stars=self.protect_stars)
                self.seconds += self.tail.seconds
                image = self.tail.render(*settings)
            else:
                tell(f'Passata {number}/{passes}: riutilizzo della correzione iniziale…')
                if self.gain is None:
                    light = self.first.light
                    valid = np.abs(light) > max(self.first.noise*.1, 1e-30)
                    first_light = luminance(self.results[0])
                    self.gain = np.divide(first_light, light, out=np.ones_like(light), where=valid)
                    # Mono values near zero cannot define a stable relative gain.
                    # Reuse their original additive correction instead.
                    if self.source.ndim == 2:
                        self.offset = np.where(valid, 0., self.results[0]-self.source).astype(self.source.dtype)
                if self.source.ndim == 2:
                    image = self.results[-1]*self.gain + self.offset
                else:
                    # A common RGB factor keeps channel ratios; the underlying
                    # engine leaves near-zero luminance RGB pixels unchanged.
                    image = self.results[-1]*self.gain[..., None]
            image = image.astype(self.source.dtype, copy=False)
            if not np.isfinite(image).all():
                raise ValueError('Valori non finiti nelle passate: ridurre intensità o numero di passate.')
            image.setflags(write=False)
            self.results.append(image)
        return self.results[passes - 1].copy()
