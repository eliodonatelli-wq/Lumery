"""Blend Stretch passes using the AstroSuite Layers mode definitions."""
import numpy as np

MODES = (
    'Normal', 'Multiply', 'Screen', 'Overlay', 'Soft Light', 'Hard Light',
    'Color Dodge', 'Color Burn', 'Pin Light', 'Add', 'Relativistic Addition',
    'Subtract', 'Divide', 'Lighten', 'Darken', 'Lighter Color', 'Darker Color',
    'Difference', 'Difference (Squared)', 'Exclusion', 'Negation', 'Grain Extract',
    'Grain Merge', 'Average', 'Geometric Mean', 'Sigmoid', 'Luminosity', 'Color',
)

EPS = 1e-6


def luma(image):
    if image.ndim == 2:
        return image
    return (image[..., 0] * .2126 + image[..., 1] * .7152
            + image[..., 2] * .0722)[..., None]


def blend(base, source, mode):
    if mode == 'Normal':
        return source

    # Extended-range data stays intact in Normal and at zero opacity.
    # Layer modes evaluate on bounded operands, like the Layers compositor.
    a = np.clip(base, 0, 1)
    b = np.clip(source, 0, 1)
    if mode == 'Multiply':
        return a * b
    if mode == 'Screen':
        return 1 - (1 - a) * (1 - b)
    if mode in ('Overlay', 'Hard Light'):
        pivot = a if mode == 'Overlay' else b
        return np.where(pivot <= .5, 2 * a * b, 1 - 2 * (1 - a) * (1 - b))
    if mode == 'Soft Light':
        return (1 - 2 * b) * a**2 + 2 * b * a
    if mode == 'Color Dodge':
        return np.clip(a / np.maximum(1 - b, EPS), 0, 1)
    if mode == 'Color Burn':
        return np.clip(1 - (1 - a) / np.maximum(b, EPS), 0, 1)
    if mode == 'Pin Light':
        return np.where(b > .5, np.maximum(a, 2 * b - 1), np.minimum(a, 2 * b))
    if mode == 'Add':
        return np.minimum(a + b, 1)
    if mode == 'Relativistic Addition':
        return np.clip((a + b) / (1 + a * b), 0, 1)
    if mode == 'Subtract':
        return np.maximum(a - b, 0)
    if mode == 'Divide':
        return np.clip(a / np.maximum(b, EPS), 0, 1)
    if mode == 'Lighten':
        return np.maximum(a, b)
    if mode == 'Darken':
        return np.minimum(a, b)
    if mode in ('Lighter Color', 'Darker Color'):
        a_luma, b_luma = luma(a), luma(b)
        take_source = b_luma >= a_luma if mode == 'Lighter Color' else b_luma <= a_luma
        return np.where(take_source, b, a)
    if mode == 'Difference':
        return np.abs(a - b)
    if mode == 'Difference (Squared)':
        return (a - b)**2
    if mode == 'Exclusion':
        return a + b - 2 * a * b
    if mode == 'Negation':
        return 1 - np.abs(1 - a - b)
    if mode == 'Grain Extract':
        return np.clip(a - b + .5, 0, 1)
    if mode == 'Grain Merge':
        return np.clip(a + b - .5, 0, 1)
    if mode == 'Average':
        return .5 * (a + b)
    if mode == 'Geometric Mean':
        return np.sqrt(a * b)
    if mode == 'Sigmoid':
        weight = 1 / (1 + np.exp(-10 * (luma(a) - .5)))
        return a * (1 - weight) + b * weight
    if mode == 'Luminosity':
        if a.ndim == 2:
            return b
        lifted = (a + .05) / 1.05
        ratio = ((luma(b) + .05) / 1.05) / (luma(lifted) + EPS)
        return np.clip(lifted * ratio * 1.05 - .05, 0, 1)
    if mode == 'Color':
        if a.ndim == 2:
            return a
        return np.clip(b * (luma(a) / np.maximum(luma(b), EPS)), 0, 1)
    raise ValueError(f'Unknown blend mode: {mode}')
