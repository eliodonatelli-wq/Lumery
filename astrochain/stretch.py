"""Sequential stretch settings and native-resolution pass evaluation."""
from dataclasses import dataclass, field
from .stretch_blend import MODES, blend

from .statistical_stretch import StatisticalSettings, process as statistical
from .vendor.ghs import core as ghs

VERSION = '1.1.0'
COMPATIBLE_VERSIONS = ('1.0.0', VERSION)


@dataclass(frozen=True)
class StretchPass:
    algorithm: str = 'ghs'
    enabled: bool = False
    opacity: int = 100
    locked: bool = False
    ghs_settings: ghs.Settings = field(default_factory=ghs.Settings)
    statistical_settings: StatisticalSettings = field(default_factory=StatisticalSettings)

    blend_mode: str = "Normal"

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
            passes.append(StretchPass(**record))
        return cls(tuple(passes))


def active_pass(step):
    return step.enabled and step.opacity > 0


def changes_state(step):
    from .model import identity_ghs
    return active_pass(step) and (
        step.blend_mode != 'Normal' or step.algorithm == 'statistical' or not identity_ghs(step.ghs_settings))


def evaluate(image, state, settings, key, cache, budget, cancel, progress):
    from .model import buffer_bytes, Cancelled
    for index, step in enumerate(settings.passes, 1):
        if cancel.is_set():
            raise Cancelled()
        if not active_pass(step):
            continue
        params = step.ghs_settings if step.algorithm == 'ghs' else step.statistical_settings
        engine_key = (key, index, step.algorithm, params)
        result = cache.pop(engine_key, None)
        if result is None:
            progress(f'Stretch · pass {index} · ' + ('GHS' if step.algorithm == 'ghs' else 'Statistical'))
            try:
                if step.algorithm == 'ghs':
                    result = ghs.process(image, ghs.build_curve(params, ghs.analyze(image)), params)
                else:
                    result, _ = statistical(image, params, cancel)
            except ValueError as exc:
                raise ValueError(f'Stretch pass {index}: {exc}') from exc
            result.setflags(write=False)
        if cancel.is_set():
            raise Cancelled()
        cache[engine_key] = result
        key = (engine_key, step.blend_mode, step.opacity)
        if step.opacity == 100 and step.blend_mode == 'Normal':
            image = result
        else:
            mixed = cache.pop(key, None)
            if mixed is None:
                weight = step.opacity / 100
                blended = blend(image, result, step.blend_mode)
                mixed = blended if step.opacity == 100 else (1 - weight) * image + weight * blended
                mixed.setflags(write=False)
            image = cache[key] = mixed
        while cache and buffer_bytes(cache) > budget:
            cache.popitem(last=False)
        if changes_state(step):
            state = 'nonlinear'
    return image, state
