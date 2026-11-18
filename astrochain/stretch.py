"""Sequential stretch settings and native-resolution pass evaluation."""
from dataclasses import asdict, dataclass, field
from .selective_hdr import HDRSettings
from .stretch_mask import MaskSettings, build_mask, decode_reference, luminance_reference, mask_settings
from .stretch_blend import MODES, blend

from .statistical_stretch import StatisticalSettings, process as statistical
from .vendor.ghs import core as ghs

VERSION = '1.4.1'
COMPATIBLE_VERSIONS = ('1.0.0', '1.1.0', '1.2.0', '1.3.0', '1.3.1', '1.3.2', '1.3.3', '1.3.4', '1.4.0', VERSION)


@dataclass(frozen=True)
class StretchPass:
    algorithm: str = 'ghs'
    enabled: bool = False
    opacity: int = 100
    locked: bool = False
    ghs_settings: ghs.Settings = field(default_factory=ghs.Settings)
    statistical_settings: StatisticalSettings = field(default_factory=StatisticalSettings)

    blend_mode: str = "Normal"
    mask: MaskSettings = field(default_factory=MaskSettings)
    selective_hdr: HDRSettings = field(default_factory=lambda: HDRSettings(relative=True))

    def __post_init__(self):
        if self.blend_mode not in MODES:
            raise ValueError("Unknown stretch blend mode")
        if self.algorithm not in ('ghs', 'statistical'):
            raise ValueError('Unknown stretch algorithm')
        if type(self.enabled) is not bool or type(self.locked) is not bool:
            raise ValueError('Invalid stretch pass switches')
        if type(self.opacity) is not int or not 0 <= self.opacity <= 100:
            raise ValueError('Stretch opacity must be between 0 and 100')
        ghs.check(self.ghs_settings)


@dataclass(frozen=True)
class StretchSettings:
    passes: tuple[StretchPass, ...]

    def __post_init__(self):
        if (not isinstance(self.passes, tuple) or not 3 <= len(self.passes) <= 4
                or any(not isinstance(step, StretchPass) for step in self.passes)):
            raise ValueError('Stretch requires three or four passes')

    @classmethod
    def from_project(cls, values, parse):
        passes = []
        for record in values['passes']:
            record = dict(record)
            record['ghs_settings'] = parse('ghs', record['ghs_settings'])
            record['statistical_settings'] = parse('statistical', record['statistical_settings'])
            record['mask'] = mask_settings(**record.get('mask', {}))
            record['selective_hdr'] = HDRSettings(**record.get('selective_hdr', {}))
            passes.append(StretchPass(**record))
        return cls(tuple(passes))


def settings_record(settings, *, include_mask_pixels=True):
    record = asdict(settings)
    for step in record['passes']:
        mask = step['mask']
        reference = mask.get('reference')
        if reference and not include_mask_pixels:
            mask['reference'] = (*reference[:5], '')
    return record


def active_pass(step):
    return step.enabled and step.opacity > 0


def changes_state(step):
    from .model import identity_ghs
    return active_pass(step) and (
        step.selective_hdr.active or step.blend_mode != 'Normal' or step.algorithm == 'statistical' or not identity_ghs(step.ghs_settings))


def evaluate(image, state, settings, key, cache, budget, cancel, progress, *, mask_preview=None, diagnostics=None, mask_offset=(0, 0)):
    from .model import buffer_bytes, Cancelled
    for index, step in enumerate(settings.passes, 1):
        if cancel.is_set():
            raise Cancelled()
        showing_mask = mask_preview == index - 1 and step.mask.enabled
        if not active_pass(step) and not showing_mask:
            continue
        params = step.ghs_settings if step.algorithm == 'ghs' else step.statistical_settings
        hdr = step.selective_hdr if step.selective_hdr.active else None
        engine_key = (key, index, step.algorithm, params, hdr)
        prepared = cache.pop(engine_key, None)
        if prepared is None:
            coverage = {} if hdr is not None else None
            hdr_options = {'selective_hdr': hdr, 'hdr_diagnostics': coverage} if hdr is not None else {}
            progress(f'Stretch · pass {index} · ' + ('GHS' if step.algorithm == 'ghs' else 'Statistical'))
            try:
                if step.algorithm == 'ghs':
                    result = ghs.process(image, ghs.build_curve(params, ghs.analyze(image)), params, **hdr_options)
                else:
                    result, _ = statistical(image, params, cancel, **hdr_options)
            except ValueError as exc:
                raise ValueError(f'Stretch pass {index}: {exc}') from exc
            result.setflags(write=False)
            prepared = (result, coverage)
        result, coverage = prepared
        if coverage is not None and diagnostics is not None:
            diagnostics.setdefault('hdr_coverage', {})[index - 1] = coverage
        if cancel.is_set():
            raise Cancelled()
        cache[engine_key] = prepared
        mask = None
        if step.mask.enabled:
            mask_key = (engine_key, step.mask, mask_offset) if step.mask.reference else (engine_key, step.mask)
            mask = cache.pop(mask_key, None)
            levels = None
            if showing_mask:
                levels = (decode_reference(step.mask.reference, result.shape[:2], mask_offset)
                          if step.mask.reference else luminance_reference(result))
            if mask is None:
                mask = build_mask(result, step.mask, levels=levels, offset=mask_offset)
            cache[mask_key] = mask
            if showing_mask:
                diagnostics['mask'] = mask
                diagnostics['mask_luminance'] = (levels, mask_offset, index - 1)

        if cancel.is_set():
            raise Cancelled()
        if not active_pass(step) or (mask is not None and not mask.any()):
            while cache and buffer_bytes(cache) > budget:
                cache.popitem(last=False)
            continue

        key = (engine_key, step.blend_mode, step.opacity, step.mask if mask is not None else None)
        if mask is None and step.opacity == 100 and step.blend_mode == 'Normal':
            image = result
        else:
            mixed = cache.pop(key, None)
            if mixed is None:
                weight = step.opacity / 100
                blended = blend(image, result, step.blend_mode)
                if mask is not None:
                    weight = weight * (mask[..., None] if image.ndim == 3 else mask)
                    mixed = (1 - weight) * image + weight * blended
                else:
                    mixed = blended if step.opacity == 100 else (1 - weight) * image + weight * blended
                mixed.setflags(write=False)
            image = cache[key] = mixed
        while cache and buffer_bytes(cache) > budget:
            cache.popitem(last=False)
        if changes_state(step):
            state = 'nonlinear'
    return image, state
