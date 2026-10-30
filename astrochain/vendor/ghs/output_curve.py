"""Monotone cubic output tone curve; NumPy only, no clipping of image samples."""
import numpy as np

IDENTITY = ((0., 0.), (1., 1.))


def validate_points(points):
    a = np.asarray(points, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != 2 or not 2 <= len(a) <= 128:
        raise ValueError('Output curve needs 2–128 points.')
    if not np.isfinite(a).all() or np.any(a < 0) or np.any(a > 1):
        raise ValueError('Output curve points must be finite in [0,1].')
    if not np.array_equal(a[[0, -1]], np.array(IDENTITY)):
        raise ValueError('Output curve endpoints must stay at (0,0) and (1,1).')
    if np.any(np.diff(a[:, 0]) < 1e-6) or np.any(np.diff(a[:, 1]) < 0):
        raise ValueError('Output curve points must be ordered and monotone.')
    return a


def coefficients(points):
    a = validate_points(points)
    x, y = a.T
    h = np.diff(x)
    d = np.diff(y) / h
    m = np.zeros(len(x), dtype=np.float64)
    if len(a) == 2:
        m[:] = d[0]
    else:
        # PCHIP harmonic slopes prevent overshoot between monotone knots.
        for i in range(1, len(x)-1):
            if d[i-1] > 0 and d[i] > 0:
                w1, w2 = 2*h[i]+h[i-1], h[i]+2*h[i-1]
                m[i] = (w1+w2)/(w1/d[i-1]+w2/d[i])
        for idx, first, second, h0, h1 in ((0,d[0],d[1],h[0],h[1]),(-1,d[-1],d[-2],h[-1],h[-2])):
            slope = ((2*h0+h1)*first-h0*second)/(h0+h1)
            m[idx] = min(max(0.,slope),3*first)
    return x, y, m


def evaluate(values, points):
    values = np.asarray(values,dtype=np.float64)
    if tuple(map(tuple, points)) == IDENTITY:
        return values.copy()
    x,y,m = coefficients(points)
    # Bound the interpolation argument, then extend endpoint tangents outside.
    z = np.clip(values,0.,1.)
    k = np.clip(np.searchsorted(x,z,side='right')-1,0,len(x)-2)
    h = x[k+1]-x[k]
    t = (z-x[k])/h
    result = ((2*t**3-3*t**2+1)*y[k] + (t**3-2*t**2+t)*h*m[k]
              + (-2*t**3+3*t**2)*y[k+1] + (t**3-t**2)*h*m[k+1])
    result = np.where(values<0, values*m[0], result)
    return np.where(values>1, 1+(values-1)*m[-1], result)


def apply(image, points):
    """Common peak gain after either stretch mode; retains resulting RGB ratios."""
    if tuple(map(tuple, points)) == IDENTITY:
        return image
    a = np.asarray(image,dtype=np.float64)
    valid = np.isfinite(a).all(axis=-1) if a.ndim==3 else np.isfinite(a)
    safe = np.where(valid[...,None],a,0.) if a.ndim==3 else np.where(valid,a,0.)
    peak = np.max(safe,axis=-1) if a.ndim==3 else safe
    mapped = evaluate(peak,points)
    if a.ndim==3:
        slope0 = coefficients(points)[2][0]
        gain = np.divide(mapped,peak,out=np.full_like(peak,slope0),where=peak!=0)
        result = safe*gain[...,None]
        return np.where(valid[...,None],result,a)
    return np.where(valid,mapped,a)
