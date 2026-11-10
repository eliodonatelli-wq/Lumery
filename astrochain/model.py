"""Prototype data path. Original engine sources are vendored unchanged."""
from dataclasses import asdict, replace
import hashlib
import json
import threading
import os
from collections import OrderedDict
from time import perf_counter
import numpy as np
from scipy.ndimage import gaussian_filter, zoom
from .vendor.ghs import core as ghs
from .ghs_auto import suggest as suggest_ghs
from .vendor.spatial import processing as spatial
from .vendor.spatial.parameters import Settings as EqualizerSettings
from .vendor.dynamics import core as dynamics
from .vendor.dynamics import analysis as dynamics_analysis
from .vendor.filament.passes import PassPipeline
from .filament_settings import FilamentSettings
from .filament_runtime import CachedFilamentPipeline
from .nebula_settings import PaletteSettings,ColorSettings
from .color_runtime import process as process_colors
from .foraxx import is_foraxx,VERSION as FORAXX_VERSION
from . import nebula_processing
from .sky_background import active as sky_active, VERSION as SKY_VERSION
from .vendor.nebula import mixer as color_engine
from .vendor.parametric import processing as parametric
from .vendor.parametric.parameters import Settings as ParametricSettings, Band as ParametricBand
from .curves import input_histograms,CurveSettings,process as process_curves,VERSION as CURVES_VERSION
from .freeze import FreezeSettings,VERSION as FREEZE_VERSION,frame_view,signature as freeze_signature
from .palette_native import NativePaletteSettings, render as native_palette_render, VERSION as NATIVE_PALETTE_VERSION, COMPATIBLE_VERSIONS as NATIVE_PALETTE_COMPATIBLE_VERSIONS
from .palette_native_inputs import signature as native_input_signature, load as native_load_inputs
from . import spectral_extraction as spectral
from . import response_profiles as response_profiles
from .profile_separation import qualify as qualify_response_profile
from .clahe import ClaheSettings, process as process_clahe, VERSION as CLAHE_VERSION
from .statistical_stretch import StatisticalSettings, process as process_statistical, VERSION as STATISTICAL_VERSION
MODULE_NAMES={"statistical":"Statistical Stretch","clahe":"CLAHE","palette_native":"Palette Studio","freeze":"Freeze","curves":"Curves","ghs":"Adaptive GHS","eq":"Spatial Equalizer","compressor":"Multiband Compressor","parametric":"Astro Parametric Equalizer","filament":"Nebula Filament Enhancer","palette":"Nebula Palette","colors":"Nebula Colors & Tone"}

class Cancelled(Exception):
    pass

class Pipeline:
    def __init__(self, image, metadata=None):
        self.source = ghs.prepare(image)
        if self.source.ndim == 3 and self.source.shape[-1] == 1:
            self.source = self.source[..., 0]
        spatial.validate(self.source)  # Explicit common contract: finite mono/RGB.
        self.source.setflags(write=False)
        self.metadata = metadata or {}
        self.analysis = ghs.analyze(self.source)
        self.initial = suggest_ghs(self.source,self.analysis)
        self.display_settings=self.initial
        self._display_curve=None
        self.cache = {}
        self.compressor_references={}
        self.native_palette_cache=OrderedDict()
        self.clahe_cache=OrderedDict()
        self.statistical_cache=OrderedDict()
        self.ghs_cache=OrderedDict()
        self.freeze_frames={}
        self.channel_frames={}
        self.freeze_proxies={}
        self.filament_cache=OrderedDict()
        try:physical=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
        except (ValueError,OSError,AttributeError):physical=4*1024**3
        self.cache_budget=max(256*1024**2,min(1024**3,physical//16))
        digest = hashlib.sha256()
        for row in range(0, self.source.shape[0], 192):
            digest.update(self.source[row:row+192].tobytes())
        self.fingerprint = digest.hexdigest()

    def visualize(self,image,state,enabled=True):
        """Fixed source-derived GHS for display only; never used by rendering."""
        if not enabled or state!='linear':return image,False
        if self._display_curve is None:self._display_curve=ghs.build_curve(self.display_settings,self.analysis)
        return ghs.process(image,self._display_curve,self.display_settings),True

    def inferred_state(self):
        chain = self.metadata.get('astrochain', {})
        if isinstance(chain, dict) and chain.get('application') == 'AstroChain Prototype':
            state=chain.get('result_state','unknown')
            return state if state in ('linear','nonlinear') else 'unknown'
        record = self.metadata.get('adaptive_ghs_stretch', {})
        if isinstance(record, dict) and record.get('linear') is False:
            return 'nonlinear'
        return 'unknown'

    def compute(self, state, settings, equalizer, bypass=False, divisor=4,
                cancel=None, progress=None):
        cancel = cancel or threading.Event()
        progress = progress or (lambda message: None)
        def check():
            if cancel.is_set():
                raise Cancelled('Operation cancelled')
        check()
        if state not in ('linear', 'nonlinear'):
            raise ValueError('Confirm in INPUT whether the image is linear or already non-linear.')
        if divisor not in (1, 2, 4, 8):
            raise ValueError('Invalid resolution')
        if state == 'linear' and settings.strength == 0 and settings.black == 0 and settings.color == 1 and settings.output_points == ((0.,0.),(1.,1.)) and not bypass:
            raise ValueError('Identity GHS: data remains linear. Apply a stretch or bypass the equalizer.')
        key = (state, settings if state == 'linear' else None, divisor)
        if self.cache.get('key') != key:
            progress('INPUT · GHS' if state == 'linear' else 'INPUT · GHS skipped')
            # Fixed full-source analysis; actual dimensions define spatial scale.
            sample = reduce_image(self.source,divisor)
            check()
            result = ghs.process(sample, ghs.build_curve(settings, self.analysis), settings) if state == 'linear' else sample
            result.setflags(write=False)
            self.cache = dict(key=key, input=result, engine={})
        check()
        base = self.cache['input']
        progress('Spatial Equalizer' if not bypass else 'Spatial Equalizer · bypass')
        scale = (self.source.shape[0]/base.shape[0], self.source.shape[1]/base.shape[1])
        output, limited = (base, 0.) if bypass else spatial.process(base, equalizer, scale, self.cache['engine'])
        check()
        return base, output, limited

    def project(self, state_index, ghs_settings, eq, bypass, divisor, output):
        return dict(schema=1, application='AstroChain Prototype', source=dict(sha256=self.fingerprint, shape=list(self.source.shape), dtype=self.source.dtype.str), input=dict(state_index=state_index, ghs=asdict(ghs_settings)), module=dict(engine='spatial_equalizer', version='0.1.2', settings=asdict(eq), bypass=bypass), preview_divisor=divisor, output=output, versions=dict(ghs='0.4.1', spatial='0.1.2'))

    def validate_project(self, data):
        if data.get('schema') != 1 or data.get('application') != 'AstroChain Prototype':
            raise ValueError('Unsupported project')
        if data['source']['sha256'] != self.fingerprint:
            raise ValueError('This project belongs to a different image. Open and select the correct source.')
        if data['versions'] != dict(ghs='0.4.1', spatial='0.1.2'):
            raise ValueError('Incompatible engine versions')
        p = dict(data['input']['ghs'])
        p['output_points'] = tuple(tuple(v) for v in p['output_points'])
        gs = ghs.Settings(**p)
        ghs.check(gs)
        p = dict(data['module']['settings']); p['gains'] = tuple(p['gains'])
        eq = EqualizerSettings(**p)
        if data['input']['state_index'] not in (0, 1, 2) or data['preview_divisor'] not in (1, 2, 4, 8):
            raise ValueError('Invalid state or resolution')
        if type(data['module']['bypass']) is not bool:
            raise ValueError('Invalid bypass')
        if data['module']['engine'] != 'spatial_equalizer' or data['module']['version'] != '0.1.2':
            raise ValueError('Unsupported module')
        if data['output'].get('format') not in ('Documento AstroSuite', 'FITS float32', 'FITS float64'):
            raise ValueError('Unsupported format')
        return gs, eq

    def compute_serial(self, state, input_settings, integrated_ghs, modules, divisor=4, cancel=None, progress=None, allow_partial=False):
        cancel = cancel or threading.Event()
        progress = progress or (lambda text: None)
        if state not in ('linear','nonlinear'):
            raise ValueError('Open INPUT and confirm Linear or Already non-linear.')
        if divisor not in (1,2,4,8):raise ValueError('Invalid resolution')
        if cancel.is_set(): raise Cancelled()
        # Interactive previews run at the requested proxy resolution.
        # Native calibration parity needs shared references, not a full-chain
        # native render on each control change.
        use_input = integrated_ghs and state == 'linear'
        checkpoint=next((i for i in range(len(modules)-1,-1,-1) if modules[i]['kind']=='freeze' and not modules[i]['bypass'] and modules[i]['settings'].token),None)
        notes=[];diagnostics={}
        if checkpoint is None:
            base, _, _ = self.compute('linear' if use_input else 'nonlinear', input_settings, EqualizerSettings(), True, divisor, cancel, progress)
            current=base
            current_state='nonlinear' if use_input and not identity_ghs(input_settings) else state
            stages={'input':base};states={'input':current_state}
            previous_key=(self.fingerprint,divisor,state,integrated_ghs,input_settings if use_input else None)
            start=0;new=[]
        else:
            frozen=modules[checkpoint];settings=frozen['settings']
            current=frame_view(self,settings,divisor);current_state=settings.state
            # INPUT previews are requested with an empty module list. No upstream
            # image processing runs here; base denotes this checkpoint's ingress.
            base=current;stages={frozen['id']:current};states={frozen['id']:current_state}
            previous_key=('freeze',settings.token,divisor);start=checkpoint+1;new=[None]*start
            stale=settings.signature!=freeze_signature(self,state,input_settings,integrated_ghs,modules[:checkpoint])
            diagnostics[frozen['id']]=dict(frozen=True,stale=stale,shape=list(self.freeze_frames[settings.token].shape),bytes=self.freeze_frames[settings.token].nbytes)
            notes.append('Freeze: native pixels pinned; upstream skipped'+(' · upstream changed: update manually' if stale else ''))
        old=getattr(self,'serial_cache',[]);used=0
        for index,module in enumerate(modules[start:],start):
            if cancel.is_set(): raise Cancelled()
            external_signature=native_input_signature(module['settings'],self.channel_frames) if module['kind']=='palette_native' and not module['bypass'] else ()
            key=(previous_key,module['id'],module['kind'],module['settings'],module['bypass'],module.get('force',False),module.get('auto_reference',True),external_signature)
            record=old[index] if index<len(old) and old[index] is not None and old[index]['key']==key else None
            result_cached=record is not None
            progress(f'{index+1}/{len(modules)} · '+MODULE_NAMES.get(module['kind'],module['kind'])+(' · cached result' if result_cached else ''))
            ingress=current
            if record is None:
                prior=old[index] if index<len(old) and old[index] is not None and old[index]['key'][0]==previous_key and old[index]['key'][2]==module['kind'] else None
                engine=prior.get('engine',{}) if prior else {}; output=current; next_state=current_state; note='';diagnostic={}
                if not module['bypass']:
                    if module['kind']=='freeze':
                        note='Freeze live · capture to pin a native image'
                    elif module['kind']=='ghs':
                        if current_state=='nonlinear' and not module.get('force',False):
                            note='GHS automatically skipped: data is already non-linear'
                        else:
                            prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings'],self.channel_frames) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                            native_key=(self.fingerprint,state,input_settings if integrated_ghs else None,integrated_ghs,prefix,module['settings'])
                            prepared=self.ghs_cache.pop(module['id'],None)
                            if prepared is None or prepared[0]!=native_key:
                                progress('GHS · preparing native ingress')
                                native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                                analysis=ghs.analyze(native)
                                rgb=ghs.process(native,ghs.build_curve(module['settings'],analysis),module['settings'])
                                rgb.setflags(write=False)
                            else:rgb=prepared[1]
                            self.ghs_cache[module['id']]=(native_key,rgb)
                            while self.ghs_cache and buffer_bytes(self.ghs_cache)>self.cache_budget:self.ghs_cache.popitem(last=False)
                            output=reduce_image(rgb,divisor)
                            if not identity_ghs(module['settings']): next_state='nonlinear'
                    elif module['kind']=='statistical':
                        if current_state=='nonlinear' and not module.get('force',False):
                            note='Statistical Stretch automatically skipped: data is already non-linear'
                            diagnostic=dict(skipped=True)
                        else:
                            prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings'],self.channel_frames) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                            native_key=(self.fingerprint,state,input_settings if integrated_ghs else None,integrated_ghs,prefix,module['settings'])
                            prepared=self.statistical_cache.pop(module['id'],None)
                            if prepared is None or prepared[0]!=native_key:
                                progress('Statistical Stretch · preparing native ingress')
                                native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                                rgb,diagnostic=process_statistical(native,module['settings'],cancel)
                                rgb.setflags(write=False)
                            else:_,rgb,diagnostic=prepared
                            self.statistical_cache[module['id']]=(native_key,rgb,diagnostic)
                            while self.statistical_cache and buffer_bytes(self.statistical_cache)>self.cache_budget:
                                self.statistical_cache.popitem(last=False)
                            output=reduce_image(rgb,divisor);next_state='nonlinear'
                            note='Statistical Stretch · native calculation; output in [0, 1]'
                            diagnostic=dict(diagnostic,native_shape=list(rgb.shape))
                    elif module['kind']=='clahe':
                        settings=module['settings']
                        if not settings.identity():
                            if current_state!='nonlinear':
                                raise ValueError('CLAHE requires non-linear data. Add an active stretch before CLAHE.')
                            prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings'],self.channel_frames) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                            native_key=(self.fingerprint,state,input_settings if integrated_ghs else None,integrated_ghs,prefix,settings)
                            prepared=self.clahe_cache.pop(module['id'],None)
                            if prepared is None or prepared[0]!=native_key:
                                progress('CLAHE · preparing native ingress')
                                native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                                rgb=process_clahe(native,settings,cancel)
                                rgb.setflags(write=False)
                            else:rgb=prepared[1]
                            self.clahe_cache[module['id']]=(native_key,rgb)
                            while self.clahe_cache and buffer_bytes(self.clahe_cache)>self.cache_budget:
                                self.clahe_cache.popitem(last=False)
                            output=reduce_image(rgb,divisor)
                            note='CLAHE · native calculation; RGB ratios preserved; exact black unchanged'
                    elif module['kind']=='curves':
                        output=process_curves(current,module['settings'],cancel)
                        if not module['settings'].identity():next_state='nonlinear'
                    elif module['kind']=='eq':
                        # The unmodified DCT engine accepts finite float linear and non-linear data.
                        scale=(self.source.shape[0]/current.shape[0],self.source.shape[1]/current.shape[1])
                        output,_=spatial.process(current,module['settings'],scale,engine)
                    elif module['kind']=='palette_native':
                        if module['settings'].extraction_method==response_profiles.METHOD and current_state!='linear' and qualify_response_profile(module['settings'].response_profile)['hbeta_separated']:
                            raise ValueError('Hβ separation requires linear RGB ingress. Remove upstream stretching or use a two-component filter/current matrix.')
                        module['settings'].require_foraxx_state(current_state)
                        prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings'],self.channel_frames) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                        native_key=(state,input_settings if integrated_ghs else None,integrated_ghs,prefix,module['settings'],external_signature)
                        prepared=self.native_palette_cache.get(module['id'])
                        if prepared is None or prepared[0]!=native_key:
                            progress('Palette Studio · preparing native ingress')
                            native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                            channels=native_load_inputs(module['settings'],external_signature,self.channel_frames)
                            rgb,diagnostic=native_palette_render(native,module['settings'],channels,cancel)
                            rgb.setflags(write=False)
                            self.native_palette_cache[module['id']]=(native_key,rgb,diagnostic)
                            while len(self.native_palette_cache)>1 and buffer_bytes(self.native_palette_cache)>self.cache_budget:
                                self.native_palette_cache.popitem(last=False)
                        else:_,rgb,diagnostic=prepared
                        output=reduce_image(rgb,divisor)
                        if module['settings'].source=='fits_channels':next_state='nonlinear' if module['settings'].fits_nonlinear else 'linear'
                        if module['settings'].nonlinear():next_state='nonlinear'
                        diagnostic=dict(diagnostic,native_shape=list(rgb.shape),external_inputs=external_signature)
                        note='Palette Studio · native render; reduced RGB preview. '+('Artificial SII.' if module['settings'].synthetic else 'RGB gas estimates.' if module['settings'].source=='rgb_estimate' else 'Registered FITS channels; alignment confirmed by user.')
                    elif module['kind']=='palette':
                        if is_foraxx(module['settings'].values()['view_a']) and current_state!='nonlinear':
                            raise ValueError('Foraxx requires non-linear data: insert an active GHS node before Nebula Palette, or select a classic palette.')
                        if module['settings'].values()['extraction_method'] in (spectral.METHOD,response_profiles.METHOD):
                            prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings'],self.channel_frames) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                            native_key=('spectral-legacy',state,input_settings if integrated_ghs else None,integrated_ghs,prefix,module['settings'])
                            prepared=self.native_palette_cache.get(module['id'])
                            if prepared is None or prepared[0]!=native_key:
                                native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                                rgb,diagnostic=nebula_processing.process(native,module['settings'],engine,current_state)
                                rgb.setflags(write=False)
                                self.native_palette_cache[module['id']]=(native_key,rgb,diagnostic)
                                while len(self.native_palette_cache)>1 and buffer_bytes(self.native_palette_cache)>self.cache_budget:self.native_palette_cache.popitem(last=False)
                            else:_,rgb,diagnostic=prepared
                            output=reduce_image(rgb,divisor)
                        else:output,diagnostic=nebula_processing.process(current,module['settings'],engine,current_state)
                        note='Nebula Palette: data mapped to RGB 0–1 with a shared offset/divisor; no stretch. Synthetic SII.'
                    elif module['kind']=='colors':
                        values=module['settings'].values()
                        output=process_colors(current,values,engine)
                        if any(values['tone'].get(k,0)!=0 for k in ('highlights','shadows','whites','blacks')):next_state='nonlinear'
                    elif module['kind']=='filament':
                        settings=module['settings']
                        if min(current.shape[:2])<32 and settings.passes and settings.global_amount and any((settings.fine,settings.extended,settings.diffuse,settings.local_contrast)):
                            raise ValueError('Nebula Filament requires at least 32 pixels per side: choose a higher preview resolution.')
                        analysis_key=(module['id'],previous_key,settings.protect_stars)
                        pipeline=self.filament_cache.pop(analysis_key,None)
                        if pipeline is None:
                            candidate=engine.get('pipeline')
                            pipeline=candidate if engine.get('analysis_key')==analysis_key else CachedFilamentPipeline(current,settings.protect_stars)
                        engine['pipeline']=pipeline;engine['analysis_key']=analysis_key
                        reused=pipeline.first is not None
                        if reused:progress('Nebula Filament · cached structural analysis')
                        def tell(message):
                            if cancel.is_set():raise Cancelled()
                            progress('Nebula Filament · '+('proxy: ' if divisor!=1 else '')+message)
                        started=perf_counter()
                        output=pipeline.render(*settings.parameters(),progress=tell)
                        elapsed=perf_counter()-started
                        if cancel.is_set():raise Cancelled()
                        self.filament_cache[analysis_key]=pipeline
                        while sum(buffer_bytes(v) for v in self.filament_cache.values())>self.cache_budget:
                            self.filament_cache.popitem(last=False)
                        diagnostic=dict(cache_bytes=pipeline.cache_bytes,seconds=pipeline.seconds,divisor=divisor,elapsed=elapsed,analysis_reused=reused)
                        note='Nebula Filament: approximate proxy; detection and scales vary with resolution. Check Full.' if divisor!=1 else ''
                    elif module['kind']=='parametric':
                        scale=(self.source.shape[0]/current.shape[0],self.source.shape[1]/current.shape[1])
                        output,guarded=parametric.process(current,module['settings'],scale,engine)
                        diagnostic=dict(guarded_percent=guarded)
                    elif module['kind']=='compressor':
                        settings=module['settings'];reference=settings.reference
                        if module.get('auto_reference',True):
                            prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings'],self.channel_frames) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                            reference_key=(state,input_settings if integrated_ghs else None,integrated_ghs,prefix)
                            prepared=self.compressor_references.get(module['id'])
                            if prepared is None or prepared[0]!=reference_key:
                                progress('Preparing native reference · compressor')
                                native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                                reference=dynamics.reference_level(native)
                                self.compressor_references[module['id']]=(reference_key,reference)
                            else:reference=prepared[1]
                        factor=float(np.sqrt((self.source.shape[0]/current.shape[0])*(self.source.shape[1]/current.shape[1])))
                        effective=replace(settings,reference=reference,crossovers=tuple(max(2.+i*.01,x/factor) for i,x in enumerate(settings.crossovers)),spatial_response=settings.spatial_response/factor)
                        output,diagnostic=dynamics.process(current,effective,engine)
                        diagnostic=dict(diagnostic,reference=reference)
                    else: raise ValueError('Unknown engine')
                if module['kind']=='curves':
                    if engine.get('hist_source') is not current:
                        engine['histograms']=input_histograms(current);engine['hist_source']=current
                    diagnostic=dict(input_histograms=engine['histograms'],output_histograms=engine['histograms'] if output is current else input_histograms(output))
                output.setflags(write=False)
                record=dict(key=key,output=output,state=next_state,note=note,engine=engine,diagnostic=diagnostic)
            current=record['output'];current_state=record['state'];stages[module['id']]=current;states[module['id']]=current_state
            if record['note']:notes.append(record['note'])
            if module['kind'] in ('statistical','parametric','filament','palette','palette_native','curves'):
                diagnostics[module['id']]=dict(record.get('diagnostic',{}),result_cached=result_cached)
                if result_cached:diagnostics[module['id']]['elapsed']=0.
            if module['kind']=='compressor':
                diag=dict(record.get('diagnostic',{}))
                if module.get('spectrum',False) and not module['bypass']:
                    a,factor=dynamics_analysis.downsample(ingress,1024);b,_=dynamics_analysis.downsample(current,1024)
                    native_scale=float(np.sqrt((self.source.shape[0]/ingress.shape[0])*(self.source.shape[1]/ingress.shape[1])))
                    frequency,original=dynamics_analysis.spectrum(a,native_scale*factor);_,processed=dynamics_analysis.spectrum(b,native_scale*factor)
                    diag['spectrum']=(frequency,original,processed)
                diagnostics[module['id']]=diag
            # Bounded retained results; displayed stage references live in the UI until replaced.
            new.append(record)
            previous_key=key
        # Keep compact stage outputs before expensive disposable analyses.
        while self.filament_cache and buffer_bytes((new,self.filament_cache))>self.cache_budget:
            self.filament_cache.popitem(last=False)
        for i in sorted((i for i in range(len(new)) if new[i] is not None),key=lambda i:buffer_bytes(new[i].get('engine',{})),reverse=True):
            if buffer_bytes((new,self.filament_cache))<=self.cache_budget:break
            new[i]=dict(new[i],engine={})
        # Preserve positions when a stage cannot fit: later cached stages still remain usable.
        candidates=sorted((i for i in range(len(new)) if new[i] is not None),key=lambda i:(new[i]['key'][2]=='filament',-new[i]['output'].nbytes))
        for i in candidates:
            if buffer_bytes((new,self.filament_cache))<=self.cache_budget:break
            new[i]=None
        while new and new[-1] is None:new.pop()
        self.serial_cache=new
        if cancel.is_set():raise Cancelled()
        sky_display=any(m['kind']=='palette' and not m['bypass'] and (sky_active(m['settings']) or any(any(x!=y for x,y in c['points']) for c in m['settings'].values()['gas_curves']['channels'].values())) for m in modules[(checkpoint+1) if checkpoint is not None else 0:])
        if checkpoint is not None:sky_display=sky_display or modules[checkpoint]['settings'].direct_display
        return dict(freeze_index=checkpoint,base=base,output=current,stages=stages,states=states,output_state=current_state,notes=notes,diagnostics=diagnostics,sky_direct_display=sky_display,
                    sky_proxy_preview=bool(sky_display and divisor!=1))

    def serial_project(self, snapshot):
        snapshot=dict(snapshot,modules=snapshot.get("graph_modules",snapshot["modules"]))
        data=dict(schema=2,application='AstroChain Prototype',source=dict(sha256=self.fingerprint),versions=dict(ghs='0.4.1',spatial='0.1.2'),input=dict(state_index=snapshot['state_index'],ghs=asdict(snapshot['ghs']),integrated=snapshot['integrated']),modules=[dict(id=m['id'],kind=m['kind'],settings=asdict(m['settings']),bypass=m['bypass'],force=m.get('force',False),position=m.get('position')) for m in snapshot['modules']],preview_divisor=snapshot['divisor'],output=dict(format=snapshot['format'],path=snapshot['path']))
        if any(m['kind']=='palette_native' for m in snapshot['modules']):data['versions']['palette_native']=NATIVE_PALETTE_VERSION
        if any((m['settings'].extraction_method if m['kind']=='palette_native' else m['settings'].values()['extraction_method'] if m['kind']=='palette' else 'matrix')==spectral.METHOD for m in snapshot['modules']):data['versions']['spectral_extraction']=spectral.VERSION
        if any((m['settings'].extraction_method if m['kind']=='palette_native' else m['settings'].values()['extraction_method'] if m['kind']=='palette' else 'matrix')==response_profiles.METHOD for m in snapshot['modules']):data['versions']['response_profiles']=response_profiles.VERSION
        if any(m['kind']=='freeze' for m in snapshot['modules']):data['versions']['freeze']=FREEZE_VERSION
        data['output']['exports']=dict(snapshot.get('exports',dict(components=False,rgb=False,palette_source=None)))
        if any(m['kind']=='palette' for m in snapshot['modules']):data['versions']['palette']='9.7-nebula-0.6.8'
        if any(m['kind']=='palette' and sky_active(m['settings']) for m in snapshot['modules']):data['versions']['sky']=SKY_VERSION
        if any(m['kind']=='palette' and is_foraxx(m['settings'].values()['view_a']) for m in snapshot['modules']):data['versions']['foraxx']=FORAXX_VERSION
        if any(m['kind']=='statistical' or (m['kind']=='palette_native' and 'statistical' in m['settings'].gas_stretch_methods) for m in snapshot['modules']):data['versions']['statistical']=STATISTICAL_VERSION
        if any(m['kind']=='clahe' for m in snapshot['modules']):data['versions']['clahe']=CLAHE_VERSION
        if any(m['kind']=='curves' for m in snapshot['modules']):data['versions']['curves']=CURVES_VERSION
        if any(m['kind']=='colors' for m in snapshot['modules']):data['versions']['colors']='12.4'
        if any(m['kind']=='filament' for m in snapshot['modules']):data['versions']['filament']='0.6.0-trial-b6'
        if any(m['kind']=='parametric' for m in snapshot['modules']):data['versions']['parametric']='0.2.2'
        if any(m['kind']=='compressor' for m in snapshot['modules']):data['versions']['compressor']='0.2.2'
        for source,target in zip(snapshot['modules'],data['modules']):
            if source['kind']=='compressor':target.update(auto_reference=source.get('auto_reference',True),spectrum=source.get('spectrum',False))
        native_inputs={m['id']:native_input_signature(m['settings'],self.channel_frames) for m in snapshot['modules'] if m['kind']=='palette_native' and m['settings'].source=='fits_channels'}
        if native_inputs:data['native_palette_inputs']=native_inputs
        data['wiring_version']=2
        data['connections']=snapshot.get('connections',[])
        data['endpoints']=snapshot.get('endpoints',{})
        data['display']=dict(enabled=snapshot.get('display_auto',True),settings=asdict(self.display_settings),engine='ghs',version='0.4.1')
        return data

    def load_serial_project(self, data):
        if data.get('schema')==1:
            gs,eq=self.validate_project(data)
            import uuid
            return dict(state_index=data['input']['state_index'],ghs=gs,integrated=True,modules=[dict(id=str(uuid.uuid4()),kind='eq',settings=eq,bypass=data['module']['bypass'],force=False)],divisor=data['preview_divisor'],format=data['output']['format'],path=data['output']['path'])
        if data.get('schema')!=2 or data.get('application')!='AstroChain Prototype':raise ValueError('Unsupported project')
        if data['source']['sha256']!=self.fingerprint:raise ValueError('Select the same original image as the project.')
        supported=dict(statistical=STATISTICAL_VERSION,clahe=CLAHE_VERSION,palette_native=NATIVE_PALETTE_VERSION,freeze=FREEZE_VERSION,curves=CURVES_VERSION,ghs='0.4.1',spatial='0.1.2',compressor='0.2.2',parametric='0.2.2',filament='0.6.0-trial-b6',palette='9.7-nebula-0.6.8',colors='12.4',foraxx=FORAXX_VERSION,sky=SKY_VERSION)
        def version_supported(kind,version):
            if kind=='response_profiles':return version==response_profiles.VERSION
            if kind=='spectral_extraction':return version==spectral.VERSION
            if kind=='curves':return version in ('0.1.0',CURVES_VERSION)
            if kind=='palette_native':return version in NATIVE_PALETTE_COMPATIBLE_VERSIONS
            return supported.get(kind)==version
        if not isinstance(data['versions'],dict) or any(not version_supported(k,v) for k,v in data['versions'].items()) or any(data['versions'].get(k)!=supported[k] for k in ('ghs','spatial')):raise ValueError('Incompatible engine versions')
        def parse(kind,values):
            p=dict(values)
            if kind=='ghs':
                p['output_points']=tuple(tuple(x) for x in p['output_points']);settings=ghs.Settings(**p);ghs.check(settings);return settings
            if kind=='palette_native':return NativePaletteSettings(**p)
            if kind=='freeze':return FreezeSettings(**p)
            if kind=='statistical':return StatisticalSettings(**p)
            if kind=='clahe':return ClaheSettings(**p)
            if kind=='curves':return CurveSettings(**p)
            if kind=='eq':p['gains']=tuple(p['gains']);return EqualizerSettings(**p)
            if kind=='palette':return PaletteSettings(**p)
            if kind=='colors':return ColorSettings(**p)
            if kind=='filament':return FilamentSettings(**p)
            if kind=='parametric':
                p['bands']=tuple(ParametricBand(**b) for b in p['bands']);return ParametricSettings(**p)
            if kind=='compressor':
                p['local']=dynamics.Band(**p['local']);p['bands']=tuple(dynamics.Band(**b) for b in p['bands']);p['crossovers']=tuple(p['crossovers'])
                settings=dynamics.Settings(**p);settings.validate()
                if settings.spatial_response>256 or any(not -24<=b.threshold<=4 for b in (*settings.bands,settings.local)) or settings.crossovers[-1]>1e6 or np.min(np.diff(settings.crossovers))<.1:raise ValueError('Compressor parameters outside the control ranges')
                return settings
            raise ValueError('Unknown module')
        state=data['input']['state_index'];divisor=data['preview_divisor'];integrated=data['input']['integrated']
        if type(state) is not int or state not in (0,1,2) or divisor not in (1,2,4,8) or type(integrated) is not bool:raise ValueError('Invalid INPUT')
        modules=[];ids=set()
        for m in data['modules']:
            if not isinstance(m['id'],str) or not m['id'] or m['id'] in ids:raise ValueError('Invalid instance identifier')
            if type(m['bypass']) is not bool or type(m.get('force',False)) is not bool:raise ValueError('Invalid module state')
            if m['kind']=='compressor' and (data['versions'].get('compressor')!='0.2.2' or type(m.get('auto_reference',True)) is not bool or type(m.get('spectrum',False)) is not bool):raise ValueError('Invalid compressor or missing version')
            if m['kind']=='palette_native' and data['versions'].get('palette_native') not in NATIVE_PALETTE_COMPATIBLE_VERSIONS:raise ValueError('Incompatible Palette Studio version')
            if m['kind']=='statistical' and data['versions'].get('statistical')!=STATISTICAL_VERSION:raise ValueError('Incompatible Statistical Stretch version')
            if m['kind']=='clahe' and data['versions'].get('clahe')!=CLAHE_VERSION:raise ValueError('Incompatible CLAHE version')
            if m['kind']=='freeze' and data['versions'].get('freeze')!=FREEZE_VERSION:raise ValueError('Incompatible Freeze version')
            if m['kind']=='curves' and data['versions'].get('curves') not in ('0.1.0',CURVES_VERSION):raise ValueError('Incompatible Curves version')
            if m['kind']=='parametric' and data['versions'].get('parametric')!='0.2.2':raise ValueError('Incompatible Parametric Equalizer version')
            if m['kind']=='filament' and data['versions'].get('filament')!='0.6.0-trial-b6':raise ValueError('Incompatible Nebula Filament version')
            if m['kind'] in ('palette','colors') and data['versions'].get(m['kind'])!=supported[m['kind']]:raise ValueError('Incompatible Nebula version')
            ids.add(m['id']);node=dict(m);node['settings']=parse(m['kind'],m['settings'])
            if m['kind']=='palette_native' and 'statistical' in node['settings'].gas_stretch_methods and data['versions'].get('statistical')!=STATISTICAL_VERSION:raise ValueError('Incompatible gas Statistical Stretch version')
            if ((node['settings'].extraction_method if m['kind']=='palette_native' else node['settings'].values()['extraction_method'] if m['kind']=='palette' else 'matrix')==spectral.METHOD and data['versions'].get('spectral_extraction')!=spectral.VERSION):raise ValueError('Incompatible experimental extraction version')
            if ((node['settings'].extraction_method if m['kind']=='palette_native' else node['settings'].values()['extraction_method'] if m['kind']=='palette' else 'matrix')==response_profiles.METHOD and data['versions'].get('response_profiles')!=response_profiles.VERSION):raise ValueError('Incompatible response profile engine version')
            if m['kind']=='palette' and sky_active(node['settings']) and data['versions'].get('sky')!=SKY_VERSION:raise ValueError('Incompatible sky neutralization version')
            if m['kind']=='palette' and is_foraxx(node['settings'].values()['view_a']) and data['versions'].get('foraxx')!=FORAXX_VERSION:raise ValueError('Incompatible Foraxx version')
            if m['kind']=='palette_native' and node['settings'].source=='fits_channels':
                expected=data.get('native_palette_inputs',{}).get(m['id'])
                if expected is None or tuple(map(tuple,expected))!=native_input_signature(node['settings'],self.channel_frames):raise ValueError('Palette Studio channel inputs changed or are missing; restore the files or reassign the channels')
            pos=m.get('position')
            if pos is not None and (not isinstance(pos,list) or len(pos)!=2 or not all(isinstance(x,(int,float)) and np.isfinite(x) for x in pos)):raise ValueError('Invalid position')
            modules.append(node)
        if data['output']['format'] not in ('Documento AstroSuite','FITS float32','FITS float64') or not isinstance(data['output']['path'],str):raise ValueError('Invalid OUTPUT')
        exports=data['output'].get('exports',dict(components=False,rgb=False,palette_source=None))
        if not isinstance(exports,dict) or set(exports)!={'components','rgb','palette_source'} or type(exports['components']) is not bool or type(exports['rgb']) is not bool or (exports['palette_source'] is not None and not isinstance(exports['palette_source'],str)):raise ValueError('Invalid OUTPUT exports')
        if exports['components'] and not any(m['id']==exports['palette_source'] and m['kind'] in ('palette','palette_native') and not m['bypass'] for m in modules):raise ValueError('Palette node unavailable for channel export')
        chain=['input']+[m['id'] for m in modules]+['output'];expected=list(zip(chain,chain[1:]))
        if data.get('wiring_version',1) not in (1,2):raise ValueError('Unsupported wiring version')
        connections=data.get('connections',expected) if data.get('wiring_version',1)==2 else data.get('connections') or expected
        from .wiring import ordered_ids
        ordered_ids([m['id'] for m in modules],connections,require_output=False)
        endpoints=data.get('endpoints',{})
        if not isinstance(endpoints,dict) or any(key not in ('input','output') or not isinstance(pos,list) or len(pos)!=2 or not all(isinstance(v,(int,float)) and np.isfinite(v) for v in pos) for key,pos in endpoints.items()):raise ValueError('Invalid INPUT/OUTPUT positions')
        display=data.get('display',{})
        if display and (type(display.get('enabled')) is not bool or display.get('engine')!='ghs' or display.get('version')!='0.4.1'):raise ValueError('Unsupported display configuration')
        return dict(exports=dict(exports),display_auto=display.get('enabled',True),display_settings=parse('ghs',display['settings']) if display else self.initial,endpoints=endpoints,connections=connections,state_index=state,ghs=parse('ghs',data['input']['ghs']),integrated=integrated,modules=modules,divisor=divisor,format=data['output']['format'],path=data['output']['path'])

def identity_ghs(settings):
    return settings.strength==0 and settings.black==0 and settings.color==1 and settings.output_points==((0.,0.),(1.,1.))


def buffer_bytes(value,seen=None):
    seen=set() if seen is None else seen
    if id(value) in seen:return 0
    seen.add(id(value))
    if isinstance(value,np.ndarray):return value.nbytes
    if isinstance(value,PassPipeline):return value.cache_bytes+value.source.nbytes
    if isinstance(value,dict):return sum(buffer_bytes(v,seen) for v in value.values())
    if isinstance(value,(tuple,list)):return sum(buffer_bytes(v,seen) for v in value)
    return 0


def reduce_image(image,divisor):
    if divisor==1:return image
    h,w=image.shape[:2];target=(max(2,round(h/divisor)),max(2,round(w/divisor)))
    factors=(target[0]/h,target[1]/w)
    filtered=gaussian_filter(image,tuple(max(0,(1/f-1)/2) for f in factors)+((0,) if image.ndim==3 else ()),mode='reflect')
    return zoom(filtered,factors+((1,) if image.ndim==3 else ()),order=1,prefilter=False)
