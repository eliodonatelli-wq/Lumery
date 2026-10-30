import os,sys,json,ast,importlib.util,unittest,threading,tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from astrochain.model import Pipeline,PaletteSettings,ColorSettings,ghs,nebula_processing,color_engine
from astrochain.nebula_settings import canonical
from astrochain.vendor.nebula import palette
from astrochain.ui import ChainDialog,Events,Job
from PyQt6.QtWidgets import QApplication
ORIGINAL=Path.home()/'Library/Application Support/SASpro/scripts/nebula_unified'
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,ORIGINAL/filename);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
legacy=load('reference_nebula','legacy_studio.py');load('reference_palette_tone','palette_tone.py').install(legacy.PALETTE);load('reference_background','background.py').install(legacy.PALETTE)
def source(dtype='float32'):
    y,x=np.mgrid[:41,:53];a=(.002+.3*np.exp(-((x-25)**2+(y-20)**2)/40)).astype(dtype);return np.stack((a,a*.7+.003,a*.4+.001),-1)
def node(kind,settings,key=None,**kw):return dict(id=key or kind,kind=kind,settings=settings,bypass=False,force=False,**kw)
class NebulaTests(unittest.TestCase):
    def test_original_sources_identical(self):
        tree=ast.parse((ORIGINAL/'legacy_studio.py').read_text())
        for n in tree.body:
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('PALETTE','MIXER'):
                self.assertEqual(ast.literal_eval(n.value.args[1]),(ROOT/'astrochain/vendor/nebula'/(n.targets[0].id.lower()+'.py')).read_text())
        for name in ('palette_tone.py','background.py'):self.assertEqual((ORIGINAL/name).read_bytes(),(ROOT/'astrochain/vendor/nebula'/name).read_bytes())
    def test_every_palette_matches_original_without_stretch_or_sky(self):
        for dtype in ('float32','float64'):
            a=source(dtype);adapted,divisor,offset=nebula_processing.palette_input(a)
            for name in legacy.PALETTE.PALETTES:
                values=PaletteSettings().values();values.update(view_a=name,sii_gain=1.2,sii_softness=.2,blend=.4)
                s=PaletteSettings(canonical(values));v=s.values();ha,o=legacy.PALETTE.extract_channels_v5(adapted,v['sensor']);expected=legacy.PALETTE.render_palette(name,ha,o,dict(v,refs=(ha,o)))
                with patch.object(palette,'apply_stretch_asinh',side_effect=AssertionError('hidden stretch')),patch.object(palette,'apply_stretch_stat',side_effect=AssertionError('hidden stretch')):
                    got,_=nebula_processing.process(a,s)
                np.testing.assert_array_equal(got,expected)
    def test_signed_hdr_adaptation_and_excluded_controls(self):
        a=source('float64')*20-.1;adapted,divisor,offset=nebula_processing.palette_input(a)
        np.testing.assert_array_equal(adapted,((a+offset)/divisor).astype('float32'));self.assertGreater(divisor,1);self.assertGreater(offset,0)
        values=PaletteSettings().values();values.update(bg_neutralize=True,sky_amount=1,sky_roi=[0,0,.5,.5],global_hue=90)
        values=PaletteSettings(canonical(values)).values();self.assertFalse(values['bg_neutralize']);self.assertEqual(values['sky_amount'],0);self.assertIsNone(values['sky_roi']);self.assertEqual(values['global_hue'],0)
    def test_colors_and_order_match_original(self):
        a=source();p=Pipeline(a);v=ColorSettings().values();v['color']['red'].update(hue=12,sat=20,lum=-15);v['primary']['blue_gain']=15;v['tone'].update(exposure=.2,highlights=-10)
        color=ColorSettings(canonical(v));stretch=replace(p.initial,strength=2)
        modules=[node('palette',PaletteSettings()),node('ghs',stretch),node('colors',color)]
        composition,_=nebula_processing.process(p.source,modules[0]['settings']);stretched=ghs.process(composition,ghs.build_curve(stretch,ghs.analyze(composition)),stretch)
        normalized=legacy.MIXER._as_float01(stretched);expected=legacy.MIXER._apply_all(normalized,legacy.MIXER._compute_masks(normalized),v['tone'],v['color'],v['primary'])
        got=p.compute_serial('linear',p.initial,False,modules,1);np.testing.assert_array_equal(got['output'],expected);self.assertEqual(got['output_state'],'nonlinear')
    def test_bypass_and_domain_validation(self):
        a=source();p=Pipeline(a);n=node('palette',PaletteSettings());n['bypass']=True;np.testing.assert_array_equal(p.compute_serial('linear',p.initial,False,[n],1)['output'],a)
        with self.assertRaisesRegex(ValueError,'OSC RGB'):nebula_processing.process(a[...,0],PaletteSettings())
        color_values=ColorSettings().values();color_values['tone']['exposure']=-.6
        wide=a*10;color_output=Pipeline(wide).compute_serial('linear',p.initial,False,[node('colors',ColorSettings(canonical(color_values)))],1)['output']
        self.assertTrue(np.isfinite(color_output).all());self.assertFalse(np.array_equal(color_output,wide))
        q=Pipeline(a);self.assertEqual(q.compute_serial('linear',q.initial,False,[node('palette',PaletteSettings())],1)['output_state'],'linear')
class NebulaUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.d=ChainDialog(source());self.d.state.setCurrentIndex(1);self.d.resolution.setCurrentIndex(0);self.d.timer.stop()
    def tearDown(self):self.d.timer.stop();self.d.close()
    def add(self):
        p=self.d.canvas.add_module('palette');c=self.d.canvas.add_module('colors');self.d.timer.stop();return p,c
    def render(self):
        self.d.timer.stop();events=Events();results=[];events.done.connect(results.append);Job(self.d.pipeline,self.d.snapshot(),events,threading.Event(),True).run();return results[-1]
    def test_controls_and_no_stretch_sky_or_export_in_module(self):
        p,c=self.add();pe=self.d.editors[p.key];ce=self.d.editors[c.key]
        self.assertFalse(pe.panel._studio_tabs.isTabVisible(1));self.assertFalse(pe.panel._studio_tabs.isTabVisible(2));self.assertTrue(pe.panel.chk_bg_neutralize.isHidden());self.assertTrue(pe.panel.roi_button.isHidden())
        self.assertEqual([ce.tabs.tabText(i) for i in range(ce.tabs.count())],['Colors','Tone','Global','RGB primaries'])
        pe.panel.view_a.setCurrentText('SHO');pe.panel.sii_gain.spin.setValue(1.3);self.assertEqual(pe.settings().values()['view_a'],'SHO');self.assertEqual(pe.settings().values()['sii_gain'],1.3)
        ce.primary_rows['red_gain'].spin.setValue(10);self.assertEqual(ce.settings().values()['primary']['red_gain'],10)
        other=self.d.canvas.add_module('palette');self.assertEqual(self.d.editors[other.key].settings().values()['view_a'],'HOO');self.d.timer.stop()
    def test_projects_and_output_flags_roundtrip(self):
        p,c=self.add();self.d.export_components.setChecked(True);self.d.export_rgb.setChecked(True)
        document=json.loads(json.dumps(self.d.pipeline.serial_project(self.d.snapshot())));loaded=self.d.pipeline.load_serial_project(document);self.d.apply_project(loaded);self.d.timer.stop()
        self.assertTrue(self.d.export_rgb.isChecked());self.assertTrue(self.d.export_components.isChecked());self.assertEqual(self.d.palette_source.currentData(),p.key)
        document['versions']['palette']='old';self.assertRaises(ValueError,self.d.pipeline.load_serial_project,document)
    def test_full_exports_components_and_exact_rgb_recombination(self):
        p,c=self.add();self.d.export_components.setChecked(True);self.d.export_rgb.setChecked(True);r=self.render();self.assertNotIn('error',r)
        aux=r['auxiliary'];self.assertEqual(set(aux),{'Ha','OIII','SII_Synthetic','R','G','B'});np.testing.assert_array_equal(np.stack([aux[n] for n in ('R','G','B')],-1),r['output'])
        adapted,*_=nebula_processing.palette_input(self.d.pipeline.source);v=self.d.editors[p.key].settings().values();ha,o=legacy.PALETTE.extract_channels_v5(adapted,v['sensor']);np.testing.assert_array_equal(aux['Ha'],ha);np.testing.assert_array_equal(aux['OIII'],o)
        expected=legacy.PALETTE.generate_synthetic_SII(ha,o*legacy.PALETTE._balance_gain(ha,o),v['oiii_subtract'],ha,v['sii_softness'],v['sii_gain']);np.testing.assert_array_equal(aux['SII_Synthetic'],expected)
    def test_fits_bundle_preflight_no_overwrite_and_recombination(self):
        from astropy.io import fits
        p,c=self.add();self.d.export_components.setChecked(True);self.d.export_rgb.setChecked(True);self.d.format.setCurrentText('FITS float64')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'result.fits';self.d.path.setText(str(path));existing=Path(folder)/'result_OIII.fits';existing.write_bytes(b'original')
            r=self.render();self.assertIn('error',r);self.assertFalse(path.exists());self.assertEqual(existing.read_bytes(),b'original');existing.unlink()
            r=self.render();self.assertNotIn('error',r);self.assertEqual(len(r['saved_files']),7)
            rgb=np.stack([fits.getdata(Path(folder)/('result_'+n+'.fits')) for n in ('R','G','B')],-1);np.testing.assert_array_equal(rgb,np.moveaxis(fits.getdata(path),0,-1))
            self.assertTrue(fits.getheader(Path(folder)/'result_SII_Synthetic.fits')['SYNTHSII']);self.assertFalse(any(Path(folder).glob('.astrochain-*')))
    def test_host_documents_receive_channels_and_correct_metadata(self):
        from types import SimpleNamespace
        records=[];self.d.ctx=SimpleNamespace(open_new_document=lambda image,metadata,name:records.append((image.copy(),metadata,name)))
        self.add();self.d.export_components.setChecked(True);self.d.export_rgb.setChecked(True);r=self.render();self.assertNotIn('error',r);self.d.completed(r)
        self.assertEqual(len(records),7);self.assertEqual(records[3][1]['CHANNEL'],'SII_Synthetic');self.assertTrue(records[3][1]['SYNTHSII'])
        np.testing.assert_array_equal(np.stack([row[0] for row in records[-3:]],-1),records[0][0])
    def test_component_source_is_explicit_with_multiple_palettes(self):
        p,c=self.add();other=self.d.canvas.add_module('palette');self.d.palette_source.setCurrentIndex(self.d.palette_source.findData(other.key));self.d.export_components.setChecked(True)
        self.d.editors[other.key].panel.sensor_combo.setCurrentText('Generic OSC (default)');r=self.render();self.assertNotIn('error',r)
        expected=nebula_processing.channels(r['stages'][c.key],self.d.editors[other.key].settings());np.testing.assert_array_equal(r['auxiliary']['Ha'],expected['Ha']);self.d.timer.stop()
    def test_bundle_rolls_back_on_publication_failure(self):
        import astrochain.outputs as outputs
        self.add();self.d.export_rgb.setChecked(True);self.d.format.setCurrentText('FITS float32')
        with tempfile.TemporaryDirectory() as folder:
            self.d.path.setText(str(Path(folder)/'result.fits'));real=outputs.os.link;counter=[0]
            def fail_second(a,b):
                counter[0]+=1
                if counter[0]==2:raise OSError('simulated publication failure')
                return real(a,b)
            with patch.object(outputs.os,'link',fail_second):r=self.render()
            self.assertIn('error',r);self.assertEqual(list(Path(folder).iterdir()),[])
if __name__=='__main__':unittest.main()
