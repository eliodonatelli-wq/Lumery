from dataclasses import dataclass, asdict
import math

SCALES = (4, 8, 16, 32, 64, 128, 256, 512)

@dataclass(frozen=True)
class Settings:
    gains: tuple = (0.0,) * 8
    mix: float = 100.0
    protect_range: bool = True
    master_db: float = 0.0

    def __post_init__(self):
        if len(self.gains) != 8 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not -12 <= x <= 12 for x in self.gains):
            raise ValueError('Eight finite band gains between -12 and +12 dB are required.')
        if isinstance(self.mix, bool) or not isinstance(self.mix, (int, float)) or not math.isfinite(self.mix) or not 0 <= self.mix <= 100:
            raise ValueError('Mix must be between 0 and 100%.')
        if not isinstance(self.protect_range, bool):
            raise ValueError('Protect range must be a boolean.')
        if isinstance(self.master_db, bool) or not isinstance(self.master_db, (int, float)) or not math.isfinite(self.master_db) or not -12 <= self.master_db <= 12:
            raise ValueError('Master Volume must be between -12 and +12 dB.')

    def preset(self):
        return {'plugin': 'astro_spatial_equalizer', 'schema': 2, 'settings': asdict(self)}

def from_preset(data):
    if not isinstance(data, dict) or data.get('plugin') != 'astro_spatial_equalizer' or type(data.get('schema')) is not int or data.get('schema') not in (1,2):
        raise ValueError('Unsupported equalizer preset.')
    values = data.get('settings')
    keys = {'gains', 'mix', 'protect_range'} | ({'master_db'} if data['schema'] == 2 else set())
    if not isinstance(values, dict) or set(values) != keys:
        raise ValueError('Invalid preset settings.')
    if not isinstance(values['gains'], (list, tuple)):
        raise ValueError('Invalid band gains.')
    return Settings(tuple(values['gains']), values['mix'], values['protect_range'],values.get('master_db',0.0))
