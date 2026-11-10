"""Host-source identity, ownership, persistence, and shared rendering contracts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import patch
import numpy as np
from astrochain import channel_snapshots as cs
from astrochain.palette_native import NativePaletteSettings as Settings
from astrochain.palette_native_inputs import signature,load
from astrochain.model import Pipeline,reduce_image
from astrochain.freeze_project import save_project,load_project
from astrochain.outputs import auxiliary_images
from astrochain.freeze import FreezeSettings,capture as freeze_capture,signature as freeze_signature

class Host:
 def __init__(self):
  self.docs={uid:SimpleNamespace(uid=uid,image=np.full((17,23),value,dtype='float32'),metadata={'source':uid}) for uid,value in [('uid-h',.2),('uid-o',.4),('uid-s',.6)]}
 def list_image_views(self):return [('Same title',doc) for doc in self.docs.values()]
 def get_document(self,uid):return self.docs.get(uid)

class ChannelTests(unittest.TestCase):
 def setUp(self):
  self.host=Host();self.p=Pipeline(np.full((17,23,3),.1,dtype='float32'))
 def settings(self,include_sii=False):
  selected={'Ha':'uid-h','OIII':'uid-o'}
  if include_sii:selected['SII']='uid-s'
  frames=cs.capture(self.host,selected,(17,23));self.p.channel_frames.update(frames)
  return Settings(source='fits_channels',alignment_confirmed=True,channel_snapshots=cs.references(frames))
 def node(self,s):return dict(id='p',kind='palette_native',settings=s,bypass=False,force=False)
 def snapshot(self,s,modules=None):
  modules=modules or [self.node(s)];ids=['input']+[m['id'] for m in modules]+['output']
  return dict(state_index=1,state='linear',ghs=self.p.initial,integrated=False,modules=modules,connections=list(zip(ids,ids[1:])),divisor=4,format='FITS float32',path='',exports=dict(components=True,rgb=True,palette_source='p'))
 def run_chain(self,s,divisor=1):return self.p.compute_serial('linear',self.p.initial,False,[self.node(s)],divisor)
 def test_duplicate_titles_resolve_by_uid(self):
  s=self.settings();gas=load(s,signature(s,self.p.channel_frames),self.p.channel_frames)
  np.testing.assert_array_equal(gas['Ha'],self.host.docs['uid-h'].image)
  np.testing.assert_array_equal(gas['OIII'],self.host.docs['uid-o'].image)
 def test_snapshot_survives_edits_close_and_cannot_be_mutated(self):
  s=self.settings();before=self.run_chain(s)['output'].copy();sig=signature(s,self.p.channel_frames)
  self.host.docs['uid-h'].image[:]=.9;self.host.docs.clear()
  np.testing.assert_array_equal(before,self.run_chain(s)['output']);self.assertEqual(sig,signature(s,self.p.channel_frames))
  image=next(iter(self.p.channel_frames.values()))['image']
  with self.assertRaises(ValueError):image.setflags(write=True)
 def test_reacquire_changes_cache_and_preview_export_share_snapshot(self):
  s=self.settings(True);full=self.run_chain(s)['output'];old_sig=signature(s,self.p.channel_frames)
  for divisor in (2,4,8):np.testing.assert_array_equal(self.run_chain(s,divisor)['output'],reduce_image(full,divisor))
  gas=auxiliary_images(self.p,self.snapshot(s),self.run_chain(s));self.assertIn('SII',gas)
  np.testing.assert_array_equal(gas['Ha'],self.host.docs['uid-h'].image)
  self.host.docs['uid-h'].image[:]=.8;new=self.settings(True)
  self.assertNotEqual(old_sig,signature(new,self.p.channel_frames));self.assertFalse(np.array_equal(full,self.run_chain(new)['output']))
  np.testing.assert_array_equal(gas['Ha'],auxiliary_images(self.p,self.snapshot(s),self.run_chain(s))['Ha'])
 def test_invalid_channels(self):
  for image in (np.zeros((17,23,3)),np.zeros((5,6)),np.full((17,23),np.nan),np.ones((17,23),complex),np.ones((17,23),bool)):
   self.host.docs['uid-h'].image=image
   with self.assertRaises(ValueError):cs.capture(self.host,{'Ha':'uid-h'},(17,23))
 def test_singleton_and_signed_hdr_preserved(self):
  image=np.linspace(-2,4,391,dtype='float64').reshape(17,23,1);self.host.docs['uid-h'].image=image
  frames=cs.capture(self.host,{'Ha':'uid-h'},(17,23));a=next(iter(frames.values()))['image'];np.testing.assert_array_equal(a,image[...,0]);self.assertEqual(a.dtype,image.dtype)
 def test_closed_uid_never_binds_another_same_title(self):
  del self.host.docs['uid-h']
  with self.assertRaisesRegex(ValueError,'closed'):cs.capture(self.host,{'Ha':'uid-h'},(17,23))
 def test_mutation_during_batch_rejects_whole_batch(self):
  original=cs.digest;calls=[0]
  def changed(image):
   result=original(image);calls[0]+=1
   if calls[0]==3:self.host.docs['uid-h'].image[:]=.7
   return result
  with patch.object(cs,'digest',side_effect=changed):
   with self.assertRaisesRegex(ValueError,'changed'):self.settings()
  self.assertFalse(self.p.channel_frames)
 def test_mixed_file_and_memory(self):
  from astropy.io import fits
  frames=cs.capture(self.host,{'Ha':'uid-h'},(17,23));self.p.channel_frames.update(frames)
  with tempfile.TemporaryDirectory() as folder:
   file=Path(folder)/'oiii.fits';fits.writeto(file,self.host.docs['uid-o'].image)
   s=Settings(source='fits_channels',alignment_confirmed=True,channel_snapshots=cs.references(frames),oiii_path=str(file))
   out=self.run_chain(s)['output'];np.testing.assert_allclose(out[0,0],[.2,.4,.4])
   before=signature(s,self.p.channel_frames);fits.writeto(file,np.full((17,23),.7),overwrite=True)
   self.assertNotEqual(before,signature(s,self.p.channel_frames));np.testing.assert_allclose(self.run_chain(s)['output'][0,0],[.2,.7,.7])
 def test_session_without_host_and_lossless_dtype(self):
  s=self.settings(True);expected=self.run_chain(s)['output']
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'session.json';save_project(self.p,self.snapshot(s),path);self.host.docs.clear();other=Pipeline(self.p.source)
   restored=load_project(other,path);got=other.compute_serial('linear',other.initial,False,restored['modules'],1)['output'];np.testing.assert_array_equal(expected,got)
   self.assertEqual(next(iter(other.channel_frames.values()))['image'].dtype,np.dtype('float32'))
 def test_corrupt_or_missing_archive_rejected_without_state_mutation(self):
  s=self.settings()
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'session.json';save_project(self.p,self.snapshot(s),path);data=json.loads(path.read_text());file=path.parent/data['channel_archive']['file']
   with np.load(file) as archive:arrays={key:archive[key].copy() for key in archive.files}
   arrays[next(iter(arrays))][:]=.99;np.savez(file,**arrays);other=Pipeline(self.p.source)
   with self.assertRaisesRegex(ValueError,'corrupt'):load_project(other,path)
   self.assertFalse(other.channel_frames);file.unlink()
   with self.assertRaisesRegex(ValueError,'missing'):load_project(other,path)
 def test_freeze_signature_updates_only_on_reacquire(self):
  s=self.settings();modules=[self.node(s),dict(id='f',kind='freeze',settings=FreezeSettings(),bypass=False,force=False)]
  frozen=freeze_capture(self.p,'linear',self.p.initial,False,modules,'f');sig=frozen.signature
  self.host.docs['uid-h'].image[:]=.9
  self.assertEqual(sig,freeze_signature(self.p,'linear',self.p.initial,False,modules[:1]))
  modules[0]['settings']=self.settings();self.assertNotEqual(sig,freeze_signature(self.p,'linear',self.p.initial,False,modules[:1]))
 def test_old_session_without_snapshot_field(self):
  s=Settings();data=self.p.serial_project(self.snapshot(s));data['modules'][0]['settings'].pop('channel_snapshots')
  self.assertEqual(self.p.load_serial_project(data)['modules'][0]['settings'],s)

class ChannelUITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from PyQt6.QtWidgets import QApplication
  cls.app=QApplication.instance() or QApplication([])
 def test_selector_duplicate_titles_invalid_entries_and_uid(self):
  from PyQt6.QtCore import Qt
  from astrochain.channel_selector import ChannelSelector
  host=Host();host.docs['uid-s'].image=np.zeros((17,23,3));d=ChannelSelector(None,host,(17,23))
  self.assertEqual(d.items.count(),3);d.items.setCurrentRow(1);d.accept_selection();self.assertEqual(d.uid,'uid-o')
  self.assertFalse(d.items.item(2).flags() & Qt.ItemFlag.ItemIsEnabled);d.close()
 def test_editor_acquire_edit_close_reacquire_and_browse(self):
  from astrochain.ui import ChainDialog
  from PyQt6.QtCore import QObject,pyqtSignal
  class Doc(QObject):
   changed=pyqtSignal()
  host=Host();original=host.docs['uid-h'];doc=Doc();doc.uid=original.uid;doc.image=original.image;doc.metadata={};host.docs['uid-h']=doc
  d=ChainDialog(np.ones((17,23,3),dtype='float32')*.1,ctx=host);d.timer.stop()
  try:
   n=d.canvas.add_module('palette_native');e=d.editors[n.key]
   e.acquire_selected({'Ha':'uid-h','OIII':'uid-o'});d.timer.stop();before=e.settings();tokens=set(d.pipeline.channel_frames)
   doc.image[:]=.8;doc.changed.emit();self.assertIn('modificata',e.channel_status.text());self.assertEqual(e.settings(),before)
   e.reacquire();d.timer.stop();self.assertNotEqual(e.settings().channel_snapshots,before.channel_snapshots)
   host.docs.clear();e.refresh_channel_status();self.assertIn('chiusa',e.channel_status.text())
   e.controls['ha_path'].setText('/example/file.fits');e.use_file('ha_path');d.timer.stop();self.assertFalse(any(ref[0]=='Ha' for ref in e.settings().channel_snapshots));self.assertFalse(e.controls['ha_path'].isReadOnly())
  finally:d.close()
 def test_saved_session_applies_to_editor_without_open_documents(self):
  from astrochain.ui import ChainDialog
  host=Host();image=np.full((17,23,3),.1,dtype='float32')
  d=ChainDialog(image,ctx=host);d.timer.stop();other=None
  try:
   n=d.canvas.add_module('palette_native');e=d.editors[n.key];e.acquire_selected({'Ha':'uid-h','OIII':'uid-o'});e.controls['alignment_confirmed'].setChecked(True)
   d.canvas.edges=[('input',n.key),(n.key,'output')];d.state.setCurrentIndex(1);d.timer.stop()
   expected=d.pipeline.compute_serial('linear',d.pipeline.initial,False,d.snapshot()['modules'],1)['output']
   with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'session.json';save_project(d.pipeline,d.snapshot(),path);host.docs.clear()
    other=ChainDialog(image,ctx=host);other.timer.stop();loaded=load_project(other.pipeline,path);other.apply_project(loaded);other.timer.stop()
    actual=other.pipeline.compute_serial('linear',other.pipeline.initial,False,other.snapshot()['modules'],1)['output'];np.testing.assert_array_equal(expected,actual)
    editor=next(iter(other.editors.values()));self.assertIn('chiusa',editor.channel_status.text());self.assertTrue(other.pipeline.channel_frames)
  finally:
   d.close()
   if other is not None:other.close()
