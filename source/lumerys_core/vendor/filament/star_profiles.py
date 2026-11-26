"""Compact-source footprint fitted for protection only; no star removal."""
import numpy as np
from scipy.ndimage import gaussian_filter as gf,maximum_filter,map_coordinates,label
from scipy.optimize import least_squares
from .engine_v2 import ramp

def footprint(light,noise,legacy):
    weight=1-ramp(legacy,.2,.65)
    base=gf(light,.7);excess=gf(light,1.2)-gf(light,12)
    candidates=(gf(light,1.2)==maximum_filter(gf(light,1.2),9))&(legacy>.35)&(excess>50*noise)
    lab,n=label(candidates);ys,xs=np.nonzero(candidates)
    if not len(ys):return weight,dict(fitted=0,failed=0)
    _,idx=np.unique(lab[ys,xs],return_index=True);ys,xs=ys[idx],xs[idx]
    xx=gf(light,1.2,order=(0,2));yy=gf(light,1.2,order=(2,0));xy=gf(light,1.2,order=(1,1))
    disc=np.hypot(xx-yy,2*xy);major=-(xx+yy-disc)/2;minor=-(xx+yy+disc)/2
    theta=.5*np.arctan2(2*xy,xx-yy)[ys,xs];q=np.clip((major[ys,xs]/np.maximum(minor[ys,xs],1e-30))**.25,1,1.7)
    phi=np.arange(24)*2*np.pi/24;ux=np.cos(phi)[None,:]*q[:,None];uy=np.sin(phi)[None,:]/q[:,None]
    cx=ux*np.cos(theta)[:,None]-uy*np.sin(theta)[:,None];cy=ux*np.sin(theta)[:,None]+uy*np.cos(theta)[:,None]
    radii=np.array([0.,1.,2.,3.,4.,6.,8.,12.,16.,24.])
    profiles=np.array([np.median(map_coordinates(base,(ys[:,None]+r*cy,xs[:,None]+r*cx),order=1,mode='reflect'),axis=1) for r in radii]).T
    h,w=light.shape;failed=0;fits=0
    for k,(y,x,t,elongation) in enumerate(zip(ys,xs,theta,q)):
        observations=profiles[k];background=float(np.median(observations[-2:]));amplitude=max(float(observations[0]-background),noise)
        values=(observations-background)/amplitude
        def model(p):return p[0]*(1+(radii/p[1])**2)**(-p[2])+p[3]+p[4]*(radii/16)**2
        try:
            fit=least_squares(lambda p:model(p)-values,[1.,3.,3.,0.,0.],bounds=([.2,.5,1.5,-.6,-.5],[3.,30.,12.,.6,.5]),max_nfev=80,loss='soft_l1',f_scale=.03)
            amp,alpha,beta,_,_=fit.x
            error=float(np.sqrt(np.mean((model(fit.x)-values)**2)))
            if not fit.success or error>.12:raise ValueError('Unreliable profile')
            radius=alpha*np.sqrt(max((amp*amplitude/max(noise*.5,1e-30))**(1/beta)-1,0))
            radius=float(np.clip(radius,4,96));fits+=1
        except (ValueError,FloatingPointError):
            # Conservative compact fallback, based on measured local curvature.
            width=np.sqrt(np.clip(2*excess[y,x]/max(-(xx+yy)[y,x],1e-30),1,144))
            radius=min(96,max(8,4*width));failed+=1
        extent=int(np.ceil((radius+4)*elongation));y0=max(0,y-extent);y1=min(h,y+extent+1);x0=max(0,x-extent);x1=min(w,x+extent+1)
        dy,dx=np.mgrid[y0:y1,x0:x1];dx=dx-x;dy=dy-y
        distance=np.hypot((dx*np.cos(t)+dy*np.sin(t))/elongation,(-dx*np.sin(t)+dy*np.cos(t))*elongation)
        weight[y0:y1,x0:x1]=np.minimum(weight[y0:y1,x0:x1],ramp(distance,radius,radius+4))
    return weight,dict(fitted=fits,failed=failed)
