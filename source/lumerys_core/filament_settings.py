from dataclasses import dataclass
@dataclass(frozen=True)
class FilamentSettings:
    fine:int=40
    extended:int=40
    diffuse:int=40
    global_amount:int=100
    local_contrast:int=0
    passes:int=1
    reanalyze:bool=False
    protect_stars:bool=True
    def __post_init__(self):
        if any(type(v) is not int or not 0<=v<=100 for v in (self.fine,self.extended,self.diffuse,self.global_amount,self.local_contrast)):
            raise ValueError('Strength values must be integers from 0 to 100.')
        if type(self.passes) is not int or not 0<=self.passes<=3:raise ValueError('Pass count: 0 to 3.')
        if type(self.reanalyze) is not bool or type(self.protect_stars) is not bool:raise ValueError('Invalid Filament switch.')
    def parameters(self):return (self.fine,self.extended,self.diffuse,self.global_amount,self.local_contrast,self.passes,self.reanalyze)
