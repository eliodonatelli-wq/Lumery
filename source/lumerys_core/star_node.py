"""Session-local native frame pairs for the Separate Stars node."""
from dataclasses import dataclass
from uuid import uuid4

from .freeze import signature

VERSION = '1.0.0'


@dataclass(frozen=True)
class StarSettings:
    crop: tuple | None = None
    token: str = ''
    crop_only: bool = False

    def __post_init__(self):
        if type(self.crop_only) is not bool:
            raise ValueError('Invalid crop mode.')
        if self.crop is not None:
            crop = tuple(self.crop)
            if (len(crop) != 4 or any(type(v) is not int or v < 0 for v in crop)
                    or crop[0] >= crop[2] or crop[1] >= crop[3]):
                raise ValueError('Invalid Separate Stars crop.')
            object.__setattr__(self, 'crop', crop)


@dataclass(frozen=True)
class StarPair:
    signature: tuple
    token: str
    images: tuple
    offset: tuple
    state: str

    @classmethod
    def capture(cls, stamp, images, offset, state="linear"):
        for image in images:
            image.setflags(write=False)
        return cls(stamp, uuid4().hex, images, offset, state)


def input_stamp(pipeline, state, ghs, integrated, upstream, crop):
    return signature(pipeline, state, ghs, integrated, upstream), crop


def valid_pair(pipeline, state, ghs, integrated, upstream, module):
    settings = module['settings']
    if settings.crop_only:
        return None
    pair = pipeline.star_pairs.get(module['id'])
    if pair is not None and settings.token == pair.token:
        if pair.signature == input_stamp(pipeline, state, ghs, integrated, upstream, settings.crop):
            return pair
    return None
