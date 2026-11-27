"""Color the identified gas contributions, never select final RGB hue ranges.

Hue is an HSV angle offset; saturation is a multiplier with HSV saturation
bounded to one. Value is retained. A shared negative pedestal is retained for
signed custom-matrix contributions; there is no [0,1] RGB data clipping.
Only changed contributions are replaced. Foraxx weights are computed from the
original post-curve, balanced signals and remain fixed during color adjustment.
"""
import numpy as np


def adjust_color(rgb, hue, saturation):
    if hue == 0 and saturation == 1:
        return rgb
    pedestal = np.minimum(rgb.min(axis=-1), 0.)
    color = rgb - pedestal[..., None]
    value = color.max(axis=-1)
    minimum = color.min(axis=-1)
    chroma = value - minimum
    # Achromatic values have no hue. Saturation changes must not invent chroma.
    chromatic = chroma > 0
    safe = np.where(chromatic, chroma, 1.)
    r, g, b = np.moveaxis(color, -1, 0)
    h = np.where(value == r, (g-b)/safe,
                 np.where(value == g, 2.+(b-r)/safe, 4.+(r-g)/safe))
    h = np.mod(h + hue/60., 6.)
    sat = np.divide(chroma, value, out=np.zeros_like(chroma), where=value > 0)
    sat = np.minimum(1., sat*saturation)
    c = value*sat
    x = c*(1.-np.abs(np.mod(h, 2.)-1.))
    zero = np.zeros_like(c)
    sector = np.floor(h).astype(np.int8)
    red = np.select((sector==0,sector==1,sector==2,sector==3,sector==4), (c,x,zero,zero,x), default=c)
    green = np.select((sector==0,sector==1,sector==2,sector==3,sector==4), (x,c,c,x,zero), default=zero)
    blue = np.select((sector==0,sector==1,sector==2,sector==3,sector==4), (zero,zero,x,c,c), default=x)
    output = np.stack((red,green,blue),axis=-1)+(value-c+pedestal)[...,None]
    # Preserve exact gray endpoints, also for finite signed data.
    return np.where(chromatic[...,None],output,rgb)


def apply_gas_colors(rgb, signals, hues, saturations, *, matrix=None, pip=None,
                     sulfur_weight=None, cancel=None):
    active = [i for i in range(signals.shape[-1]) if hues[i] != 0 or saturations[i] != 1]
    if not active:
        return rgb  # Exact legacy arithmetic, including Foraxx and extended range.
    output = rgb.copy()
    rows = max(1, 131072 // max(1, rgb.shape[1]))
    for top in range(0,rgb.shape[0],rows):
        if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
        span = slice(top,top+rows)
        gas = signals[span]
        for index in active:
            if matrix is not None:
                component = gas[...,index,None]*matrix[:,index]
            else:
                component = np.zeros_like(output[span])
                if index == 0:
                    component[...,0] = gas[...,0] if sulfur_weight is None else (1.-sulfur_weight[span])*gas[...,0]
                    component[...,1] = pip[span]*gas[...,0]
                elif index == 1:
                    component[...,1] = (1.-pip[span])*gas[...,1]
                    component[...,2] = gas[...,1]
                else:
                    component[...,0] = sulfur_weight[span]*gas[...,2]
            output[span] += adjust_color(component,hues[index],saturations[index])-component
    if not np.isfinite(output).all():raise ValueError('Gas color adjustment exceeds finite numeric range')
    return output
