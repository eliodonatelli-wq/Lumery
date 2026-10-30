from pathlib import Path
import json,time
from dataclasses import replace
import numpy as np
from PyQt6.QtGui import QImage
from astrochain.model import Pipeline,reduce_image
from astrochain.palette_native import NativePaletteSettings,render
root=Path(__file__).resolve().parent;out=root/'reports';out.mkdir(exist_ok=True)
path=root.parent/'astrosuite_chain_prototype/reports/live_green_20261024_162046/palette_ingress.npy'
a=np.load(path);p=Pipeline(a);s=NativePaletteSettings();m=dict(id='native',kind='palette_native',settings=s,bypass=False)
t=time.perf_counter();full=p.compute_serial('nonlinear',p.initial,False,[m],1)['output'];elapsed=time.perf_counter()-t
errors={}
for d in (2,4,8):
 preview=p.compute_serial('nonlinear',p.initial,False,[m],d)['output'];expected=reduce_image(full,d);errors[str(d)]=float(np.max(np.abs(preview-expected)))
# Display-only common mapping, shared for the complete comparison.
crop=a[max(0,a.shape[0]//2-256):a.shape[0]//2+256,max(0,a.shape[1]//2-256):a.shape[1]//2+256]
hoo,_=render(crop,s);sho,_=render(crop,replace(s,palette='SHO',synthetic=True))
lo=float(np.min(crop));hi=float(np.max(crop));scale=max(hi-lo,1e-12)
canvas=np.concatenate([(x-lo)/scale for x in (crop,hoo,sho)],axis=1)
display=np.ascontiguousarray((np.clip(canvas,0,1)*255).astype('uint8'))
QImage(display.data,display.shape[1],display.shape[0],display.strides[0],QImage.Format.Format_RGB888).save(str(out/'real_comparison.png'))
report=dict(source=str(path),shape=list(a.shape),finite=bool(np.isfinite(full).all()),range=[float(full.min()),float(full.max())],native_seconds=elapsed,preview_max_absolute_error=errors,crop_comparison='Center crop: source | HOO | SHO artificial SII; identical display scale. PNG clips display only.',live_host_tested=False)
(out/'real_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
