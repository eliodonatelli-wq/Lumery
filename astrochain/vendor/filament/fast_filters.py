"""Separable FFT implementation of the SAME truncated Gaussian kernels.
Half-sample symmetric padding matches scipy.ndimage mode='reflect'.
No image reduction, no scale changes, no new dependencies.
"""
import numpy as np
from scipy.ndimage import gaussian_filter as standard
from scipy.signal import fftconvolve

def gaussian_filter(a,sigma,order=0,mode='reflect',truncate=4.):
    if mode!='reflect':return standard(a,sigma,order=order,mode=mode,truncate=truncate)
    sigmas=(sigma,)*a.ndim if np.isscalar(sigma) else sigma
    orders=(order,)*a.ndim if np.isscalar(order) else order
    out=a
    for axis,(s,n) in enumerate(zip(sigmas,orders)):
        if s<5:
            ss=[0.]*a.ndim;ss[axis]=s;oo=[0]*a.ndim;oo[axis]=n
            out=standard(out,ss,order=oo,mode=mode,truncate=truncate);continue
        if n not in (0,1,2):raise ValueError('Unsupported derivative')
        r=int(truncate*s+.5);x=np.arange(-r,r+1,dtype=np.float64)
        k=np.exp(-.5*(x/s)**2);k/=k.sum()
        if n==1:k*= -x/s**2
        if n==2:k*=x*x/s**4-1/s**2
        shape=[1]*a.ndim;shape[axis]=len(k);k=k.astype(a.dtype).reshape(shape)
        pads=[(0,0)]*a.ndim;pads[axis]=(r,r)
        out=fftconvolve(np.pad(out,pads,mode='symmetric'),k,mode='valid',axes=(axis,)).astype(a.dtype,copy=False)
    return out

def hessian(a,s):
    radius=int(4*s+.5);x=np.arange(-radius,radius+1,dtype=np.float64)
    phi=np.exp(-.5*(x/s)**2);phi/=phi.sum();dc=float(np.sum((x*x/s**4-1/s**2)*phi))
    base=gaussian_filter(a,s)
    return (s*s*(gaussian_filter(a,s,(0,2))-dc*base),s*s*(gaussian_filter(a,s,(2,0))-dc*base),s*s*gaussian_filter(a,s,(1,1)))
