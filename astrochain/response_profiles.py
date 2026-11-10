"""Validated response records, explicit CSV units and self-contained session snapshots."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tempfile
import numpy as np

VERSION='1.0'
METHOD='spectral_profiles_v1'
LABEL='Camera / filter profiles (experimental)'
LINES={'Hb':486.133,'O4959':495.891,'O5007':500.684,'N6548':654.805,'Ha':656.281,'N6583':658.345}
CAMERA_LINES=('O4959','O5007','Ha')
FILTER_LINES=('Hb','O4959','O5007','N6548','Ha','N6583')
MAX_BYTES=2_000_000


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def number(value,label,low=0,high=None):
    if type(value) not in (int,float) or not np.isfinite(value) or value<low or (high is not None and value>high):raise ValueError('Invalid '+label)
    return float(value)


def record(kind,name,source,**values):
    """Factory for incomplete metadata as well as complete numeric records."""
    defaults=dict(id='',revision='1',kind=kind,name=name,source=source,date='',quality='user',scope='unknown',sensor='',common_scale=True,units='relative' if kind=='camera' else 'fraction',medium='air',sampling='lines',samples=[],uncertainty=None,uncertainty_scope='none',band_class='unknown',blocking='unknown',optical_context='unknown',f_min=None,f_max=None,fast=False,notes='')
    defaults.update(values)
    return validate_record(defaults)


def validate_record(value):
    if not isinstance(value,dict):raise ValueError('Invalid profile record')
    required={'id','revision','kind','name','source','date','quality','scope','sensor','common_scale','units','medium','sampling','samples','uncertainty','uncertainty_scope','band_class','blocking','optical_context','f_min','f_max','fast','notes'}
    if set(value)!=required:raise ValueError('Missing or unknown profile fields')
    v=dict(value)
    for k in ('id','revision','name','source','date','scope','sensor','blocking','optical_context','notes'):
        if not isinstance(v[k],str) or len(v[k])>10000:raise ValueError('Invalid profile '+k)
    if not all(v[k].strip() for k in ('id','revision','name','source')):raise ValueError('Profile name, source, ID and revision are required')
    if v['kind'] not in ('camera','filter') or v['quality'] not in ('graph','user','measured','incomplete'):raise ValueError('Invalid profile type or data quality')
    if v['sampling'] not in ('lines','curve') or v['medium']!='air':raise ValueError('Use air wavelengths with a declared sampling format')
    if v['units'] not in (('relative','fraction') if v['kind']=='camera' else ('fraction',)):raise ValueError('Invalid canonical response units')
    if type(v['common_scale']) is not bool or type(v['fast']) is not bool:raise ValueError('Invalid profile declaration')
    if v['uncertainty_scope'] not in ('none','digitization','measurement','user_estimate'):raise ValueError('Invalid uncertainty scope')
    if v['uncertainty'] is not None:v['uncertainty']=number(v['uncertainty'],'absolute response uncertainty')
    if v['band_class'] not in ('unknown','ha_oiii','ha_hb_oiii','sii_oiii','multi','broadband'):raise ValueError('Invalid filter band class')
    for k in ('f_min','f_max'):
        if v[k] is not None:v[k]=number(v[k],k,.1,100)
    if v['f_min'] is not None and v['f_max'] is not None and v['f_min']>v['f_max']:raise ValueError('Invalid focal-ratio interval')
    rows=v['samples'];width=4 if v['kind']=='camera' else 2
    if not isinstance(rows,(list,tuple)) or len(rows)>20000:raise ValueError('Profile sample limit exceeded')
    clean=[]
    for row in rows:
        if not isinstance(row,(list,tuple)) or len(row)!=width:raise ValueError('Invalid profile sample columns')
        wavelength=number(row[0],'wavelength',200,2500)
        values=[number(x,'response',0,1 if v['units']=='fraction' else None) for x in row[1:]]
        clean.append([wavelength,*values])
    clean.sort(key=lambda r:r[0])
    if any(a[0]==b[0] for a,b in zip(clean,clean[1:])):raise ValueError('Duplicate wavelength: resolve duplicate rows explicitly')
    v['samples']=clean
    return v


def at(profile,line):
    rows=profile['samples'];wavelength=LINES[line]
    if not rows:return None
    a=np.asarray(rows,dtype=float)
    if profile['sampling']=='lines':
        match=np.flatnonzero(np.abs(a[:,0]-wavelength)<1e-6)
        return a[match[0],1:] if match.size else None
    if wavelength<a[0,0] or wavelength>a[-1,0]:return None
    return np.array([np.interp(wavelength,a[:,0],a[:,i]) for i in range(1,a.shape[1])])


def import_csv(text,kind,units='relative',wavelength_unit='nm',medium='air',delimiter=','):
    """Parse numeric data only; metadata/provenance are entered by the user."""
    if not isinstance(text,str) or len(text.encode('utf-8'))>MAX_BYTES:raise ValueError('CSV is too large')
    if medium!='air':raise ValueError('Convert vacuum wavelengths to a documented air scale before import')
    if delimiter not in (',',';','\t'):raise ValueError('Choose comma, semicolon or tab explicitly')
    if wavelength_unit not in ('nm','angstrom','um'):raise ValueError('Unknown wavelength unit')
    if units not in (('relative','fraction','percent') if kind=='camera' else ('fraction','percent')):raise ValueError('Use photon response / QE units, not A/W or independently normalized channels')
    reader=csv.reader(io.StringIO(text.lstrip('\ufeff')),delimiter=delimiter)
    try:header=next(reader)
    except StopIteration:raise ValueError('CSV is empty')
    wanted=['wavelength_nm','R','G','B'] if kind=='camera' else ['wavelength_nm','transmission']
    if header!=wanted:raise ValueError('Required CSV header: '+delimiter.join(wanted)+' (axis unit selected separately)')
    rows=[];factor={'nm':1.,'angstrom':.1,'um':1000.}[wavelength_unit]
    for index,row in enumerate(reader,2):
        if not row or all(not cell.strip() for cell in row):continue
        if len(row)!=len(wanted):raise ValueError(f'CSV row {index}: wrong column count; use decimal points')
        try:r=[float(cell.strip()) for cell in row]
        except ValueError:raise ValueError(f'CSV row {index}: invalid number; use decimal points')
        r[0]*=factor
        if units=='percent':r[1:]=[x/100 for x in r[1:]]
        rows.append(r)
        if len(rows)>20000:raise ValueError('Profile sample limit exceeded')
    v=record(kind,'Imported data','User CSV',id='custom:import',sampling='curve',samples=rows,units='relative' if units=='relative' else 'fraction')
    if not rows:raise ValueError('CSV contains no samples')
    return v['samples'],v['units']


def snapshot(camera,filter_profile,context=None):
    context=dict(context or {})
    c=dict(f_ratio=None,rgb_gains=[1.,1.,1.],input_description='unknown',gains_known=False)
    c.update(context)
    return validate_snapshot(canonical(dict(schema=1,engine=VERSION,preprocessing='trial30.v1',normalization='Ha_R_OIII_G_Hb_B',camera=camera,filter=filter_profile,context=c)))


def validate_snapshot(text):
    if text=='':return ''
    if not isinstance(text,str) or len(text.encode('utf-8'))>MAX_BYTES:raise ValueError('Invalid profile snapshot size')
    try:v=json.loads(text)
    except (ValueError,TypeError):raise ValueError('Invalid profile snapshot JSON')
    if not isinstance(v,dict) or set(v)!={'schema','engine','preprocessing','normalization','camera','filter','context'} or type(v['schema']) is not int or v['schema']!=1 or v['engine']!=VERSION or v['preprocessing']!='trial30.v1' or v['normalization']!='Ha_R_OIII_G_Hb_B':raise ValueError('Incompatible profile snapshot version')
    v['camera']=validate_record(v['camera']);v['filter']=validate_record(v['filter'])
    if v['camera']['kind']!='camera' or v['filter']['kind']!='filter':raise ValueError('Wrong profile record kind')
    c=v['context']
    if not isinstance(c,dict) or set(c)!={'f_ratio','rgb_gains','input_description','gains_known'}:raise ValueError('Invalid optical/RGB context')
    if c['input_description'] not in ('linear','equalized','stretched','unknown') or type(c['gains_known']) is not bool:raise ValueError('Invalid RGB state declaration')
    if c['f_ratio'] is not None:c['f_ratio']=number(c['f_ratio'],'focal ratio',.1,100)
    if not isinstance(c['rgb_gains'],(tuple,list)) or len(c['rgb_gains'])!=3:raise ValueError('Three relative RGB gains required')
    c['rgb_gains']=[number(x,'RGB gain',1e-6,1e6) for x in c['rgb_gains']]
    if not c['gains_known'] and c['rgb_gains']!=[1.,1.,1.]:raise ValueError('Declare known gains before applying RGB corrections')
    return canonical(v)


def library_path():
    if platform.system()=='Darwin':base=Path.home()/'Library/Application Support'
    elif platform.system()=='Windows':base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))
    else:base=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))
    return base/'Lumerys/response_profiles.json'


def load_library(path=None):
    path=Path(path) if path is not None else library_path()
    if not path.exists():return []
    if path.stat().st_size>MAX_BYTES:raise ValueError('Custom profile library is too large')
    v=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(v,dict) or set(v)!={'schema','profiles'} or type(v['schema']) is not int or v['schema']!=1 or not isinstance(v['profiles'],list):raise ValueError('Incompatible custom profile library')
    profiles=[validate_record(p) for p in v['profiles']]
    ids=[p['id'] for p in profiles]
    if len(set(ids))!=len(ids) or any(not i.startswith('custom:') for i in ids):raise ValueError('Invalid custom profile identities')
    return profiles


def save_custom(profile,path=None):
    profile=validate_record(profile)
    if not profile['id'].startswith('custom:'):raise ValueError('Built-in profiles cannot be overwritten')
    path=Path(path) if path is not None else library_path()
    profiles=load_library(path)
    profiles=[p for p in profiles if p['id']!=profile['id']]+[profile]
    content=canonical(dict(schema=1,profiles=profiles))
    if len(content.encode())>MAX_BYTES:raise ValueError('Custom profile library is too large')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.profiles-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
