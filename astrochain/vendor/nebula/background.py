"""Background-only color correction, after palette stretch and global color.

The mask is a smooth function of brightness, with an additional color-excess
protection relative to the sampled sky. Reference statistics are shared between
sampled preview and full-resolution export; no independent output rescaling.
"""
import numpy as np


def _falloff(value, low, high):
    t = np.clip((value-low)/max(high-low,1e-12),0,1)
    return 1-t*t*(3-2*t)


def sky_model(reference, sky):
    sample=np.asarray(reference)[sky]
    sample=sample[np.isfinite(sample).all(axis=-1)&(sample.max(axis=-1)>0)]
    if len(sample)<16:return None
    background=np.median(sample,axis=0).astype(np.float64)
    peak=sample.max(axis=-1).astype(np.float64)
    center=float(np.median(peak))
    scatter=1.4826*float(np.median(np.abs(peak-center)))
    low=max(float(np.percentile(peak,90)),center+scatter)
    high=max(low+3*scatter,low*1.5,low+1e-9)
    color=background/max(float(background.max()),1e-12)
    chroma=np.max(np.abs(sample/np.maximum(peak[:,None],1e-12)-color),axis=-1)
    color_low=max(.02,float(np.percentile(chroma,95)))
    color_high=max(.08,color_low*2)
    return background,low,high,color,color_low,color_high


def background_weight(rgb, model):
    if model is None:return np.zeros(rgb.shape[:2],dtype=np.float32)
    background,low,high,color,color_low,color_high=model
    color=np.asarray(color,dtype=rgb.dtype)
    peak=rgb.max(axis=-1)
    weight=_falloff(peak,low,high)
    # Protect line-emission/color excess that differs from the sky, even when
    # it is faint. Signals indistinguishable from sky noise cannot be classified.
    difference=np.max(np.abs(rgb/np.maximum(peak[...,None],1e-12)-color),axis=-1)
    weight*=_falloff(difference,color_low,color_high)
    weight[peak<=0]=0
    return weight.astype(np.float32)


def neutralize(rgb, reference, sky, amount=1):
    """Neutralize only dark sky-like pixels; highlights stay bitwise identical.

    Blend toward a neutral local-luminance value, with attenuation chosen from
    the sampled sky. This handles a missing/zero synthetic background channel
    without hard subtraction, forcing black, or amplifying pixel brightness.
    """
    if amount<=0:return rgb
    model=sky_model(reference,sky)
    if model is None:return rgb
    background=model[0]
    if np.ptp(background)<=max(float(background.max())*1e-5,1e-12):return rgb
    weights=np.array([.2126,.7152,.0722])
    sky_luminance=float(background@weights)
    positive=background[background>1e-12]
    if not len(positive) or sky_luminance<=1e-12:return rgb
    attenuation=min(1.,float(positive.min())/sky_luminance)
    mask=background_weight(rgb,model)*float(np.clip(amount,0,1))
    active=mask>0
    out=rgb.copy()
    if np.any(active):
        pixels=rgb[active].astype(np.float64)
        gray=(pixels@weights)*attenuation
        alpha=mask[active,None]
        out[active]=pixels+(gray[:,None]-pixels)*alpha
    return out


def selected_sky(rgb, reference, roi, amount):
    if roi is None or amount<=0:return rgb,None,None
    h,w=reference.shape[:2];x0,y0,x1,y1=roi
    sky=np.zeros((h,w),dtype=bool)
    sky[int(y0*h):int(np.ceil(y1*h)),int(x0*w):int(np.ceil(x1*w))]=True
    if np.count_nonzero(sky)<16:
        raise ValueError('Select a larger sky region: at least 16 sampled pixels are required.')
    result=neutralize(rgb,reference,sky,amount)
    corrected_reference=neutralize(reference,reference,sky,amount)
    return result,np.median(reference[sky],axis=0),np.median(corrected_reference[sky],axis=0)


def finish_background(engine,rgb,reference,params,ha,oiii):
    """One ordering and one reference for preview and full-resolution export."""
    out=rgb;ref=reference
    if params.get('bg_neutralize',False):
        sky=engine._reference_sky(ha,oiii,params.get('bg_roi'))
        out=neutralize(out,ref,sky)
        ref=neutralize(ref,ref,sky)
    return selected_sky(out,ref,params.get('sky_roi'),params.get('sky_amount',0))


def install(engine):
    if not hasattr(engine,'_nebula_background_originals'):
        engine._nebula_background_originals=(engine.render_palette,engine.StudioDialog)
    original_render,OriginalDialog=engine._nebula_background_originals

    def render(name,ha,oiii,params):
        # Defer background correction: estimating the stretch from a corrected
        # linear image would alter the highlights as well as the background.
        return original_render(name,ha,oiii,dict(params,bg_neutralize=False))

    class BackgroundPalette(OriginalDialog):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.chk_bg_neutralize.setText('Neutralize dark background only')
            self.chk_bg_neutralize.setToolTip('After stretching: neutralize only dark sky-like pixels through a soft mask. Protect bright structures and color excess. Does not remove spatial gradients.')
            self.roi_button.setText('1 · Select sky reference')
            self.roi_button.setToolTip('Draw a rectangle over empty sky, then apply it. The correction affects dark sky-like pixels across the image, not bright objects.')
            self.sky_disable.setText('Disable selected-sky correction')
            self.sky_amount.spin.setToolTip('Selected-sky strength: 0 is off, 1 fully corrects the masked background. Highlights and detected color excess stay protected.')
            from PyQt6.QtWidgets import QLabel
            for label in self.findChildren(QLabel):
                if label.text()=='Experimental background strength · 0 = off, 1 = full':
                    label.setText('Selected-sky strength · shadows only · 0 = off, 1 = full')

        def _finish_sky(self,out,reference,report=False):
            if not hasattr(self,'Ha_prev'):return out
            params=self._params()
            result,before,after=finish_background(engine,out,reference,params,self.Ha_prev,self.OIII_prev)
            if report and getattr(self,'_sky_ready',False):
                if before is None:
                    self.sky_readout.setText('Dark-background protection active' if params.get('bg_neutralize') else 'Background correction disabled')
                else:
                    fmt=lambda value:' / '.join(f'{v:.4f}' for v in value)
                    self.sky_readout.setText(f'Selected sky · shadows only · strength {params["sky_amount"]:.0%}\nR / G / B medians before: {fmt(before)}\nAfter: {fmt(after)}')
            return result

        def _process_single(self,img,params,metadata=None,title='OSC'):
            # The legacy exporter already renders all requested products and
            # applies identical stretch statistics. Intercept only stretched RGB
            # documents; extracted channels and unstretched exports are untouched.
            if not self.chk_stretch.isChecked() or (not params.get('bg_neutralize') and (params.get('sky_roi') is None or params.get('sky_amount',0)<=0)):
                return super()._process_single(img,params,metadata,title)
            if img is self.img and params['sensor']==self.sensor_combo.currentText():
                ha,o=self.Ha_full,self.OIII_full
                hp,op=self.Ha_prev,self.OIII_prev
            else:
                ha,o=engine.extract_channels_v5(img,params['sensor'])
                hp=engine.downsample_mono(ha,engine.PREVIEW_MAX_SIDE)
                op=engine.downsample_mono(o,engine.PREVIEW_MAX_SIDE)
            reference=engine.render_palette(self.view_a.currentText(),hp,op,dict(params,refs=(ha,o)))
            if self.chk_stretch.isChecked():
                lo,hi=self._stretch_limits(reference)
                reference=self._apply_stretch(reference,lo,hi,reference=reference)
                reference=engine.apply_global_color(reference,params.get('global_hue',0),params.get('global_saturation',0))
            context=self.ctx
            class Route:
                def __getattr__(router,name):return getattr(context,name)
                def open_new_document(router,image,metadata=None,name='Nebula'):
                    if image.ndim==3 and name.endswith('_stretched'):
                        image=finish_background(engine,image,reference,params,hp,op)[0]
                    context.open_new_document(image,metadata=metadata,name=name)
            self.ctx=Route()
            try:
                return super()._process_single(img,dict(params,sky_roi=None,sky_amount=0),metadata,title)
            finally:
                self.ctx=context

    engine.render_palette=render
    engine.StudioDialog=BackgroundPalette
    engine._neutralize_composite=lambda rgb,reference,sky:neutralize(rgb,reference,sky)
    engine.neutralize_selected_sky=selected_sky
