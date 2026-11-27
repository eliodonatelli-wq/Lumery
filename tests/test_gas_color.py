"""Gas identity, legacy parity, Foraxx weights and persistence regressions."""
from dataclasses import asdict,replace,fields
from pathlib import Path
import importlib.util,json,sys,threading
import numpy as np
import pytest
from lumerys_core.palette_native import NativePaletteSettings,render,PALETTES,acquire
from lumerys_core.gas_color import adjust_color

@pytest.fixture(scope='module')
def baseline():
    root=Path(__file__).parents[1];origin=json.loads((root/'PROVENANCE.json').read_text())['source']
    name='lumerys_core._pre_gas_color_baseline'
    spec=importlib.util.spec_from_file_location(name,Path(origin)/'source/lumerys_core/palette_native.py')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('palette',PALETTES)
def test_neutral_exact_legacy_parity(palette,baseline):
    rng=np.random.default_rng(102);image=rng.random((31,47,3))
    s=NativePaletteSettings(palette=palette,synthetic=True,gains=(1.4,.8,1.1))
    old=baseline.NativePaletteSettings(**{k:v for k,v in asdict(s).items() if k in {f.name for f in fields(baseline.NativePaletteSettings)}})
    expected,diagnostic=baseline.render(image,old)
    actual,current=render(image,s)
    np.testing.assert_array_equal(actual,expected)
    if palette.startswith('Foraxx'):
        assert current['foraxx_common_scale']==diagnostic['foraxx_common_scale']
        assert current['foraxx_input_ranges']==diagnostic['foraxx_input_ranges']

@pytest.mark.parametrize('custom',[False,True])
def test_signed_extended_range_legacy_parity(custom,baseline):
    image=np.random.default_rng(8).normal(size=(23,27,3))*4
    s=NativePaletteSettings(extraction=((1,0,0),(0,.5,.5),(0,0,1)),custom_matrix=custom,matrix=((1,-.2,.5),(.3,1,0),(-.4,0,1)))
    old=baseline.NativePaletteSettings(**{k:v for k,v in asdict(s).items() if k in {f.name for f in fields(baseline.NativePaletteSettings)}})
    np.testing.assert_array_equal(render(image,s)[0],baseline.render(image,old)[0])


def external(h,o,s=0):
    return np.zeros((3,4,3)),dict(Ha=np.full((3,4),h,dtype=float),OIII=np.full((3,4),o,dtype=float),SII=np.full((3,4),s,dtype=float))

@pytest.mark.parametrize('palette',['HOO','Foraxx HOO'])
def test_red_halpha_rotates_to_green_not_all_red_pixels(palette):
    image,channels=external(1,0)
    settings=NativePaletteSettings(palette=palette,source='fits_channels',alignment_confirmed=True,fits_nonlinear=True,gas_hue=(120,0,0))
    result,_=render(image,settings,channels)
    np.testing.assert_allclose(result,np.broadcast_to([0,1,0],result.shape),atol=1e-15)


def test_foraxx_sulfur_color_changes_only_its_dynamic_contribution():
    image,channels=external(0,1,1)
    s=NativePaletteSettings(palette='Foraxx SHO · synthetic SII',source='fits_channels',alignment_confirmed=True,fits_nonlinear=True)
    neutral,old_diagnostic=render(image,s,channels)
    np.testing.assert_array_equal(neutral,np.ones_like(neutral))
    changed,diagnostic=render(image,replace(s,gas_hue=(0,0,120)),channels)
    np.testing.assert_allclose(changed,np.broadcast_to([0,2,1],changed.shape),atol=1e-15)
    assert diagnostic['foraxx_input_ranges']==old_diagnostic['foraxx_input_ranges']
    assert diagnostic['foraxx_common_scale']==old_diagnostic['foraxx_common_scale']
    np.testing.assert_array_equal(acquire(image,s,channels),acquire(image,replace(s,gas_hue=(0,0,120)),channels))


def test_saturation_zero_gray_and_signed_pixels_remain_finite():
    colors=np.array([[[1.,0,0],[2.,1,1],[-2.,-1,-1],[.2,.2,.2],[0,0,0]]])
    gray=adjust_color(colors,0,0)
    np.testing.assert_array_equal(gray,np.repeat(colors.max(-1)[...,None],3,-1))
    assert np.isfinite(adjust_color(colors,170,2)).all()
    np.testing.assert_array_equal(adjust_color(colors,0,1),colors)


def test_non_selected_gas_contribution_is_retained():
    image,channels=external(.4,.2)
    s=NativePaletteSettings(source='fits_channels',alignment_confirmed=True)
    result,_=render(image,replace(s,gas_hue=(120,0,0)),channels)
    np.testing.assert_allclose(result,np.broadcast_to([0,.6,.2],result.shape),atol=1e-15)


def test_project_roundtrip_old_defaults_and_freeze_stamp(baseline):
    from lumerys_core.model import Pipeline
    from lumerys_core.freeze import signature
    image=np.random.default_rng(3).random((16,20,3)).astype(np.float32);p=Pipeline(image)
    s=NativePaletteSettings(gas_hue=(20,-35,45),gas_saturation=(.3,1.2,.8))
    module=dict(id='palette',kind='palette_native',settings=s,bypass=False,force=False)
    snapshot=dict(state_index=1,state='linear',ghs=p.initial,integrated=False,modules=[module],divisor=4,format='FITS float32',path='')
    project=p.serial_project(snapshot);restored=p.load_serial_project(json.loads(json.dumps(project)))
    assert restored['modules'][0]['settings']==s
    project['versions']['palette_native']='1.6.0'
    for key in ('gas_hue','gas_saturation'):project['modules'][0]['settings'].pop(key)
    loaded=p.load_serial_project(project)['modules'][0]['settings']
    assert loaded.gas_hue==(0,0,0) and loaded.gas_saturation==(1,1,1)
    old_s=baseline.NativePaletteSettings();old_node=dict(module,settings=old_s)
    assert signature(p,'linear',p.initial,False,[dict(module,settings=NativePaletteSettings())])==signature(p,'linear',p.initial,False,[old_node])
    assert signature(p,'linear',p.initial,False,[module])!=signature(p,'linear',p.initial,False,[old_node])

@pytest.mark.parametrize('kwargs',[{'gas_hue':(0,0,float('nan'))},{'gas_saturation':(-1,1,1)},{'gas_hue':(True,0,0)},{'gas_saturation':(1,1,3)}])
def test_invalid_gas_colors_rejected(kwargs):
    with pytest.raises(ValueError):NativePaletteSettings(**kwargs)


def test_controls_only_on_gases_and_independent_restore():
    from PyQt6.QtWidgets import QApplication
    from lumerys_core.ui import ChainDialog
    app=QApplication.instance() or QApplication([])
    d=ChainDialog(np.ones((12,16,3),dtype=np.float32)*.1);d.state.setCurrentIndex(1);d.timer.stop()
    node=d.canvas.add_module('palette_native');editor=d.editors[node.key];d.timer.stop()
    editor.curve_select.setCurrentIndex(0);editor.gas_hue_control.setValue(120);editor.gas_sat_control.setValue(60)
    assert editor.settings().gas_hue[0]==120 and editor.settings().gas_saturation[0]==.6
    editor.curve_select.setCurrentIndex(1);assert editor.gas_hue_control.value()==0 and editor.gas_sat_control.value()==100
    editor.gas_hue_control.setValue(-60);assert editor.settings().gas_hue[:2]==(120,-60)
    editor.curve_select.setCurrentIndex(3);assert editor.gas_color_group.isHidden()
    saved=editor.settings();editor.restore(saved);assert editor.settings()==saved
    editor.curve_select.setCurrentIndex(0);assert not editor.gas_color_group.isHidden()
    assert editor.gas_hue_control.value()==120
    editor.reset();assert editor.settings().gas_hue==(0,0,0) and editor.settings().gas_saturation==(1,1,1)
    d.timer.stop();d.close();app.processEvents()
