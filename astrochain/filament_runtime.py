"""Equivalent B6 execution: prepare local contrast only when requested.

Original engine files and pass arithmetic stay untouched. The initial structural
analysis is identical; zero local contrast never needs the expensive local field.
"""
from time import perf_counter
from .vendor.filament.passes import PassPipeline
from .vendor.filament.engine_balanced import analyze as analyze_structures
from .vendor.filament.engine_local import Analysis as LocalAnalysis,local_component

class LazyLocalAnalysis:
    def __init__(self,source,protect_stars):
        self.structural=analyze_structures(source,protect_stars=protect_stars)
        self.local=None;self.seconds=self.structural.seconds
    def __getattr__(self,name):return getattr(self.structural,name)
    @property
    def cache_bytes(self):return self.structural.cache_bytes+(self.local.nbytes if self.local is not None else 0)
    def render(self,fine=0,extended=0,diffuse=0,global_amount=100,local_contrast=0):
        if local_contrast==0:return self.structural.render(fine,extended,diffuse,global_amount)
        if self.local is None:
            start=perf_counter();self.local=local_component(self.light,self.stars,self.noise);self.seconds+=perf_counter()-start
        return LocalAnalysis(self.structural,self.local,self.seconds).render(fine,extended,diffuse,global_amount,local_contrast)

class CachedFilamentPipeline(PassPipeline):
    def render(self,fine,extended,diffuse,global_amount,local_contrast,passes=1,reanalyze=False,*,progress=None):
        active=passes and global_amount and any((fine,extended,diffuse,local_contrast))
        if self.first is None and active:
            if progress:progress(f'Structural analysis pass 1/{passes}…')
            self.first=LazyLocalAnalysis(self.source,self.protect_stars)
        result=super().render(fine,extended,diffuse,global_amount,local_contrast,passes,reanalyze,progress=progress)
        # The local field may have been prepared during the first render.
        if self.first is not None:self.seconds=max(self.seconds,self.first.seconds)
        return result
