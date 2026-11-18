"""Phase 1: standalone universal compositing, without pipeline integration."""
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lumerys_masks.manual_mask import Geometry
from lumerys_masks import universal_mask
from lumerys_masks.universal_mask import blend


class UniversalMaskTests(unittest.TestCase):
    def inputs(self, dtype=np.float32, rgb=False):
        a = np.linspace(-.3, 1.7, 35, dtype=dtype).reshape(5, 7)
        b = np.flip(a, 1).copy() + dtype(.25)
        if rgb:
            a = np.stack((a, a * .7, a * 1.2), -1)
            b = np.stack((b, b * .8, b * 1.1), -1)
        m = np.linspace(0, 1, 35, dtype=dtype).reshape(5, 7)
        return a, b, m

    def mix(self, a, b, m, **options):
        geometry = Geometry(tuple(b.shape[:2]), (12, 29), 'source-fingerprint')
        kwargs = dict(ingress_geometry=geometry, processed_geometry=geometry,
                      mask_geometry=geometry)
        kwargs.update(options)
        return blend(a, b, m, **kwargs)

    def test_black_mask_is_exact_ingress(self):
        for dtype in (np.float32, np.float64):
            for rgb in (False, True):
                a, b, m = self.inputs(dtype, rgb)
                r = self.mix(a, b, np.zeros_like(m))
                self.assertEqual(r.tobytes(), a.tobytes())
                self.assertIsNot(r, a)

    def test_white_mask_is_exact_processed(self):
        for dtype in (np.float32, np.float64):
            for rgb in (False, True):
                a, b, m = self.inputs(dtype, rgb)
                r = self.mix(a, b, np.ones_like(m))
                self.assertEqual(r.tobytes(), b.tobytes())
                self.assertIsNot(r, b)

    def test_zero_intensity_preserves_ingress_for_any_mask(self):
        for dtype in (np.float32, np.float64):
            a, b, m = self.inputs(dtype, True)
            r = self.mix(a, b, m, intensity=0)
            self.assertEqual(r.tobytes(), a.tobytes())

    def test_midtones_and_intensity_match_formula(self):
        for dtype in (np.float32, np.float64):
            for rgb in (False, True):
                a, b, m = self.inputs(dtype, rgb)
                for alpha in (.01, .25, .5, .9, 1):
                    with self.subTest(dtype=dtype, rgb=rgb, alpha=alpha):
                        w = m.astype(np.float64) * alpha
                        if rgb:
                            w = w[..., None]
                        expected = (a.astype(np.float64)*(1-w) + b.astype(np.float64)*w).astype(dtype)
                        np.testing.assert_array_equal(self.mix(a, b, m, intensity=alpha), expected)

    def test_intermediate_response_is_continuous(self):
        a = np.zeros((1, 1001), np.float64)
        b = np.ones_like(a)
        m = np.linspace(0, 1, 1001).reshape(a.shape)
        for alpha in (.25, 1):
            result = self.mix(a, b, m, intensity=alpha)
            np.testing.assert_array_equal(result, m*alpha)
            self.assertTrue(np.all(np.diff(result[0]) > 0))

    def test_signed_zero_at_individual_endpoints(self):
        for dtype in (np.float32, np.float64):
            a = np.array([[-0., 2., -0., 4.]], dtype)
            b = np.array([[1., -0., +0., -0.]], dtype)
            m = np.array([[0., 1., 1., 1.]], dtype)
            result = self.mix(a, b, m)
            self.assertEqual(result.tobytes(), np.array([[-0., -0., +0., -0.]], dtype).tobytes())

    def test_photographic_extended_range_is_not_clipped(self):
        a = np.array([[-10., 5., 100.]], np.float64)
        b = np.array([[-20., 10., 200.]], np.float64)
        m = np.full(a.shape, .5)
        np.testing.assert_array_equal(self.mix(a, b, m), [[-15., 7.5, 150.]])

    def test_output_precision_depends_on_images(self):
        for adtype in (np.float32, np.float64):
            for bdtype in (np.float32, np.float64):
                for mdtype in (np.float32, np.float64):
                    a, b, m = self.inputs()
                    result = self.mix(a.astype(adtype), b.astype(bdtype), m.astype(mdtype))
                    self.assertEqual(result.dtype, np.result_type(adtype, bdtype))

    def test_high_precision_mask_is_not_rounded_to_image_precision(self):
        a = np.array([[1e10]], np.float32)
        b = np.array([[0.]], np.float32)
        m = np.array([[1 - 1e-10]], np.float64)
        result = self.mix(a, b, m)
        self.assertGreater(float(result[0, 0]), .9)
        self.assertLess(float(result[0, 0]), 1.1)
        self.assertEqual(result.dtype, np.dtype('float32'))

    def test_float64_against_decimal_reference(self):
        a = np.array([[-.125, 1.75, 123.456, -12.]], np.float64)
        b = np.array([[.875, -.25, -98.765, 14.]], np.float64)
        m = np.array([[.125, .7, .3333333333333333, .99]], np.float64)
        alpha = .7
        with localcontext() as ctx:
            ctx.prec = 80
            expected = []
            for x, y, z in zip(a.flat, b.flat, m.flat):
                w = Decimal.from_float(float(z))*Decimal.from_float(alpha)
                expected.append(float(Decimal.from_float(float(x))*(1-w) + Decimal.from_float(float(y))*w))
        np.testing.assert_allclose(self.mix(a, b, m, intensity=alpha), np.array([expected]), rtol=4*np.finfo(float).eps, atol=1e-14)

    def test_extreme_finite_endpoints_and_opposite_signs(self):
        for dtype in (np.float32, np.float64):
            limit = np.finfo(dtype).max
            a = np.array([[limit, limit, -limit]], dtype)
            b = np.array([[limit, -limit, limit]], dtype)
            result = self.mix(a, b, np.full((1, 3), .5, dtype))
            np.testing.assert_array_equal(result, [[limit, 0, 0]])
            self.assertTrue(np.isfinite(result).all())

    def test_no_input_mutation_or_storage_alias(self):
        for readonly in (False, True):
            for alpha in (0, .5, 1):
                a, b, m = self.inputs(np.float64, True)
                if readonly:
                    for arr in (a, b, m):
                        arr.setflags(write=False)
                copies = [arr.copy() for arr in (a, b, m)]
                flags = [(arr.flags.writeable, arr.strides, arr.dtype) for arr in (a, b, m)]
                result = self.mix(a, b, m, intensity=alpha)
                for arr, saved, state in zip((a, b, m), copies, flags):
                    self.assertEqual(arr.tobytes(), saved.tobytes())
                    self.assertEqual((arr.flags.writeable, arr.strides, arr.dtype), state)
                    self.assertFalse(np.shares_memory(result, arr))
                self.assertTrue(result.flags.writeable)
                result.fill(7)
                for arr, saved in zip((a, b, m), copies):
                    np.testing.assert_array_equal(arr, saved)

    def test_noncontiguous_views_and_shared_storage(self):
        a, b, m = self.inputs(np.float64, True)
        a, b, m = a[::-1, ::2], b[::-1, ::2], m[::-1, ::2]
        expected = a*(1-m[..., None]) + b*m[..., None]
        np.testing.assert_array_equal(self.mix(a, b, m), expected)
        same = self.mix(a, a, m)
        self.assertEqual(same.tobytes(), a.copy().tobytes())
        self.assertFalse(np.shares_memory(same, a))

    def test_row_blocks_match_single_block(self):
        a, b, m = self.inputs(np.float64, True)
        expected = self.mix(a, b, m, intensity=.75)
        with patch.object(universal_mask, '_BLOCK_BYTES', 1):
            np.testing.assert_array_equal(self.mix(a, b, m, intensity=.75), expected)

    def test_wrong_shapes_and_channels_are_rejected(self):
        a, b, m = self.inputs()
        for other in (b[:-1], b.T, b[..., None], np.repeat(b[..., None], 3, -1)):
            with self.subTest(shape=other.shape), self.assertRaises(ValueError):
                self.mix(a, other, m)
        for wrong in (m[:-1], m.T, m[..., None], np.repeat(m[..., None], 3, -1)):
            with self.subTest(mask=wrong.shape), self.assertRaises(ValueError):
                self.mix(a, b, wrong)

    def test_crop_source_and_declared_dimensions_are_rejected(self):
        a, b, m = self.inputs()
        geometry = Geometry(m.shape, (12, 29), 'source-fingerprint')
        for field in ('ingress_geometry', 'processed_geometry', 'mask_geometry'):
            for wrong in (replace(geometry, offset=(13, 29)), replace(geometry, source_id='other'), replace(geometry, shape=(7, 5))):
                with self.subTest(field=field, wrong=wrong), self.assertRaises(ValueError):
                    self.mix(a, b, m, **{field: wrong})
        with self.assertRaises(ValueError):
            self.mix(a, b, m, mask_geometry=replace(geometry, source_id=''))
        with self.assertRaises(TypeError):
            self.mix(a, b, m, mask_geometry=None)

    def test_mixed_image_precision_and_endian_inputs(self):
        for adtype, bdtype in (('<f4', '>f8'), ('>f8', '>f4'), ('>f4', '<f4')):
            a, b, m = self.inputs(np.float64, True)
            a, b = a.astype(adtype), b.astype(bdtype)
            weight = m[..., None] * .75
            expected = (a.astype(np.float64)*(1-weight) + b.astype(np.float64)*weight).astype(np.result_type(a.dtype, b.dtype))
            np.testing.assert_array_equal(self.mix(a, b, m, intensity=.75), expected)
            np.testing.assert_array_equal(self.mix(a, b, np.zeros_like(m)), a)
            np.testing.assert_array_equal(self.mix(a, b, np.ones_like(m)), b)

    def test_missing_geometry_is_not_inferred(self):
        a, b, m = self.inputs()
        with self.assertRaises(TypeError):
            blend(a, b, m)

    def test_invalid_intensity_is_rejected(self):
        a, b, m = self.inputs()
        for alpha in (-.01, 1.01, np.nan, np.inf, -np.inf):
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                self.mix(a, b, m, intensity=alpha)
        for alpha in (True, np.bool_(False), '0.5', None, 1j, np.array(.5)):
            with self.subTest(alpha=alpha), self.assertRaises(TypeError):
                self.mix(a, b, m, intensity=alpha)

    def test_nonfinite_or_out_of_range_pixels_are_rejected_even_at_zero(self):
        for alpha in (0, 1):
            for field in range(3):
                for value in (np.nan, np.inf, -np.inf):
                    arrays = list(self.inputs())
                    arrays[field].flat[0] = value
                    with self.subTest(field=field, value=value, alpha=alpha), self.assertRaises(ValueError):
                        self.mix(*arrays, intensity=alpha)
        for value in (-np.finfo(float).eps, 1+np.finfo(float).eps):
            a, b, m = self.inputs(np.float64)
            m.flat[0] = value
            with self.assertRaises(ValueError):
                self.mix(a, b, m)

    def test_unsupported_types_and_empty_images_are_rejected(self):
        a, b, m = self.inputs()
        for index in range(3):
            for dtype in (np.int16, np.uint8, np.float16, np.complex64, bool, object):
                arrays = [a, b, m]
                arrays[index] = arrays[index].astype(dtype)
                with self.subTest(index=index, dtype=dtype), self.assertRaises(TypeError):
                    self.mix(*arrays)
        with self.assertRaises(TypeError):
            self.mix(a.tolist(), b, m)
        with self.assertRaises(TypeError):
            self.mix(np.ma.array(a), b, m)
        with self.assertRaises(ValueError):
            self.mix(a[:0], b[:0], m[:0])



class CentralIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from astrochain.model import Pipeline
        from astrochain.curves import CurveSettings
        from astrochain.tone_curve import IDENTITY
        cls.Pipeline = Pipeline
        cls.curve = CurveSettings(( ((0.,0.),(.5,.75),(1.,1.)), )+(IDENTITY,)*8)
        cls.following = CurveSettings(( ((0.,0.),(.5,.3),(1.,1.)), )+(IDENTITY,)*8)

    def pipeline(self):
        a=np.linspace(.01,.8,32*40,dtype=np.float32).reshape(32,40)
        return self.Pipeline(np.stack((a,a*.7,a*.4),-1))

    def node(self,kind,settings,key=None,**extra):
        return dict(id=key or kind,kind=kind,settings=settings,bypass=False,**extra)

    def mask(self,key='mask',**options):
        from lumerys_masks.chain_state import MaskNodeSettings
        from lumerys_masks.automatic_mask import mask_settings
        automatic=options.pop('automatic',mask_settings(True,feather=100))
        return self.node('masks',MaskNodeSettings(automatic=automatic,apply_next=True,**options),key)

    def run_chain(self,p,modules,divisor=1,state='linear',**options):
        return p.compute_serial(state,p.initial,False,modules,divisor,**options)

    def expected(self,p,mask,photo=None):
        from astrochain.curves import process
        from lumerys_masks.automatic_mask import build_mask
        settings=mask['settings'];original=p.source
        processed=process(original,photo or self.curve)
        plane=build_mask(original,settings.automatic)
        geometry=Geometry(original.shape[:2],(0,0),p.fingerprint)
        return blend(original,processed,plane,ingress_geometry=geometry,
                     processed_geometry=geometry,mask_geometry=geometry,intensity=settings.intensity)

    def test_single_recipient_and_following_module_runs_normally(self):
        from astrochain.curves import process
        p=self.pipeline();m=self.mask();modules=[m,self.node('curves',self.curve,'target'),self.node('curves',self.following,'following'),self.node('curves',self.curve,'last')]
        result=self.run_chain(p,modules)
        expected=self.expected(p,m)
        np.testing.assert_array_equal(result['stages']['target'],expected)
        np.testing.assert_array_equal(result['stages']['following'],process(expected,self.following))
        np.testing.assert_array_equal(result['output'],process(process(expected,self.following),self.curve))
        self.assertNotIn('universal_mask',result['diagnostics']['last'])
        self.assertIs(result['stages']['mask'],result['base'])
        self.assertNotIn('universal_mask',result['diagnostics']['following'])

    def test_native_proxy_is_reduced_after_blend_exactly_once(self):
        from astrochain.model import reduce_image
        import astrochain.model as model
        p=self.pipeline();m=self.mask();modules=[m,self.node('curves',self.curve)]
        expected=self.expected(p,m)
        for divisor in (1,2,4,8):
            with self.subTest(divisor=divisor), patch.object(model,'blend_universal',wraps=model.blend_universal) as mix:
                result=self.run_chain(p,modules,divisor)
                np.testing.assert_array_equal(result['output'],reduce_image(expected,divisor))
                self.assertLessEqual(mix.call_count,1)
                if mix.call_args:
                    self.assertEqual(mix.call_args.args[0].shape,p.source.shape)

    def test_bypass_target_and_automatic_skip_consume_association(self):
        from astrochain.curves import process
        from astrochain.vendor.ghs.core import Settings
        p=self.pipeline()
        for target,state in ((dict(self.node('curves',self.curve,'target'),bypass=True),'linear'),
                             (self.node('ghs',Settings(),'target'),'nonlinear')):
            result=self.run_chain(p,[self.mask(),target,self.node('curves',self.following,'after')],state=state)
            np.testing.assert_array_equal(result['output'],process(p.source,self.following))
            self.assertNotIn('universal_mask',result['diagnostics']['after'])

    def test_disabled_mask_bypass_and_generation_only_are_normal(self):
        from astrochain.curves import process
        from lumerys_masks.automatic_mask import mask_settings
        p=self.pipeline();m=self.mask()
        variants=[dict(m,bypass=True),dict(m,settings=replace(m['settings'],automatic=mask_settings(False))),dict(m,settings=replace(m['settings'],apply_next=False))]
        for variant in variants:
            result=self.run_chain(p,[variant,self.node('curves',self.curve)])
            np.testing.assert_array_equal(result['output'],process(p.source,self.curve))
            self.assertNotIn('universal_mask',result['diagnostics']['curves'])

    def test_consecutive_masks_last_wins_including_disabled(self):
        from astrochain.curves import process
        from lumerys_masks.automatic_mask import mask_settings
        p=self.pipeline();a=self.mask('a',automatic=mask_settings(True,threshold=100))
        b=self.mask('b',automatic=mask_settings(True,threshold=0,feather=0))
        for last in (b,dict(b,bypass=True),dict(b,settings=replace(b['settings'],automatic=mask_settings(False)))):
            result=self.run_chain(p,[a,last,self.node('curves',self.curve)])
            np.testing.assert_array_equal(result['output'],process(p.source,self.curve))
            if not last['bypass'] and last['settings'].automatic.enabled:
                self.assertEqual(result['diagnostics']['curves']['universal_mask']['source'],'b')

    def test_black_white_zero_intensity_and_state(self):
        from astrochain.curves import process
        from lumerys_masks.automatic_mask import mask_settings
        p=self.pipeline()
        for m,expected,state in ((self.mask(automatic=mask_settings(True,threshold=100)),p.source,'linear'),
                                 (self.mask(intensity=0),p.source,'linear'),
                                 (self.mask(automatic=mask_settings(True,feather=0)),process(p.source,self.curve),'nonlinear')):
            result=self.run_chain(p,[m,self.node('curves',self.curve)])
            np.testing.assert_array_equal(result['output'],expected)
            self.assertEqual(result['output_state'],state)

    def test_raw_and_mixed_caches_are_separate(self):
        import astrochain.model as model
        p=self.pipeline();m=self.mask();target=self.node('curves',self.curve)
        with patch.object(model,'process_curves',wraps=model.process_curves) as raw, patch.object(model,'blend_universal',wraps=model.blend_universal) as mix:
            self.run_chain(p,[m,target],4);self.assertEqual(raw.call_count,1);self.assertEqual(mix.call_count,1)
            m['settings']=replace(m['settings'],intensity=.5)
            result=self.run_chain(p,[m,target],4)
            self.assertEqual(raw.call_count,1);self.assertEqual(mix.call_count,2)
            self.run_chain(p,[m,target],4)
            self.assertEqual(raw.call_count,1);self.assertEqual(mix.call_count,2)
        self.assertTrue(result['diagnostics']['curves']['universal_mask']['raw_cached'])
        self.assertTrue(p.universal_raw_cache);self.assertTrue(p.universal_blend_cache)

    def test_manual_edit_preserves_upstream_and_raw_target_cache(self):
        import astrochain.model as model
        from lumerys_masks.chain_state import geometry_key,encode_tiles
        p=self.pipeline();m=self.mask();up=self.node('curves',self.following,'up');target=self.node('curves',self.curve,'target');down=self.node('curves',self.following,'down')
        with patch.object(model,'process_curves',wraps=model.process_curves) as raw:
            result=self.run_chain(p,[up,m,target,down],4)
            counts=[call.args[1] for call in raw.call_args_list]
            doc=result['diagnostics']['mask']['mask_document']
            doc.begin_stroke('exclude',10,0);doc.stroke_to(12,12);doc.end_stroke()
            m['settings']=replace(m['settings'],geometry=geometry_key(doc.geometry),corrections=encode_tiles(doc))
            raw.reset_mock();self.run_chain(p,[up,m,target,down],4)
            changed=[call.args[1] for call in raw.call_args_list]
            self.assertNotIn(self.curve,changed)
            # Same settings for upstream and downstream; only downstream reruns.
            self.assertEqual(changed.count(self.following),1)

    def test_geometry_failure_blocks_render_and_marks_partial_preview(self):
        from lumerys_masks.chain_state import geometry_key,encode_tiles
        p=self.pipeline();m=self.mask();doc=self.run_chain(p,[m])['diagnostics']['mask']['mask_document']
        doc.begin_stroke('exclude',10,0);doc.stroke_to(10,10);doc.end_stroke()
        geometry=list(geometry_key(doc.geometry));geometry[2]=1
        m['settings']=replace(m['settings'],geometry=tuple(geometry),corrections=encode_tiles(doc))
        modules=[m,self.node('curves',self.curve)]
        with self.assertRaisesRegex(ValueError,'geometry'):
            self.run_chain(p,modules)
        result=self.run_chain(p,modules,allow_partial=True)
        self.assertIn('processing_error',result)
        np.testing.assert_array_equal(result['output'],p.source)

    def test_channel_changes_are_not_silently_broadcast(self):
        import astrochain.model as model
        p=self.pipeline();m=self.mask()
        with patch.object(model,'process_curves',side_effect=lambda a,s,cancel=None: a[...,0]):
            with self.assertRaisesRegex(ValueError,'layouts'):
                self.run_chain(p,[m,self.node('curves',self.curve)])

    def test_photographic_parameters_invalidate_raw_cache(self):
        import astrochain.model as model
        p=self.pipeline();m=self.mask();target=self.node('curves',self.curve)
        with patch.object(model,'process_curves',wraps=model.process_curves) as raw:
            self.run_chain(p,[m,target]);target['settings']=self.following;self.run_chain(p,[m,target])
            self.assertEqual(raw.call_count,2)

    def test_original_images_unchanged(self):
        p=self.pipeline();before=p.source.tobytes();result=self.run_chain(p,[self.mask(),self.node('curves',self.curve)])
        self.assertEqual(p.source.tobytes(),before)
        self.assertFalse(np.shares_memory(result['output'],p.source))

    def test_real_wire_order_not_creation_order_and_parked_nodes(self):
        from astrochain.wiring import ordered_ids
        p=self.pipeline();a=self.node('curves',self.following,'earlier');m=self.mask();b=self.node('curves',self.curve,'target');park=self.mask('parked')
        creation=[b,park,m,a];edges=[('input','earlier'),('earlier','mask'),('mask','target'),('target','output')]
        ids,_=ordered_ids([n['id'] for n in creation],edges);nodes={n['id']:n for n in creation}
        result=self.run_chain(p,[nodes[key] for key in ids])
        self.assertEqual(result['diagnostics']['target']['universal_mask']['source'],'mask')
        self.assertNotIn('universal_mask',result['diagnostics']['earlier'])
        self.assertNotIn('parked',result['stages'])

    def test_direct_freeze_and_stellar_recipients_are_rejected(self):
        from astrochain.freeze import FreezeSettings
        from astrochain.star_node import StarSettings
        from astrochain.star_recombine import RecombineSettings
        from lumerys_masks.universal_mask import UnsupportedUniversalMask
        p=self.pipeline()
        for kind,settings in (('freeze',FreezeSettings()),('separate_stars',StarSettings()),
                              ('recombine_stars',RecombineSettings())):
            special=self.node(kind,settings)
            with self.subTest(kind=kind), self.assertRaisesRegex(UnsupportedUniversalMask,'phase 2'):
                self.run_chain(p,[self.mask(),special])
            bypassed=dict(special,bypass=True)
            result=self.run_chain(p,[self.mask(),bypassed,self.node('curves',self.curve)])
            self.assertNotIn('universal_mask',result['diagnostics']['curves'])

    def test_later_freeze_captures_masked_pixels_and_tracks_changes(self):
        from dataclasses import replace
        from astrochain.freeze import FreezeSettings,capture
        from lumerys_masks.chain_state import photographic_modules
        p=self.pipeline();mask=self.mask(intensity=.5)
        prefix=[mask,self.node('curves',self.curve)]
        freeze=self.node('freeze',FreezeSettings())
        freeze['settings']=capture(p,'linear',p.initial,False,photographic_modules(prefix+[freeze]),'freeze')
        result=self.run_chain(p,prefix+[freeze])
        np.testing.assert_array_equal(result['output'],self.expected(p,mask))
        self.assertFalse(result['diagnostics']['freeze']['stale'])
        mask['settings']=replace(mask['settings'],intensity=.2)
        changed=self.run_chain(p,prefix+[freeze])
        self.assertTrue(changed['diagnostics']['freeze']['stale'])
        np.testing.assert_array_equal(changed['output'],result['output'])

    def test_stretch22_wrapped_without_double_application(self):
        from astrochain.stretch import StretchSettings,StretchPass
        from astrochain.model import reduce_image
        from lumerys_masks.automatic_mask import build_mask
        p=self.pipeline();m=self.mask()
        settings=StretchSettings((StretchPass('statistical',enabled=True),StretchPass(),StretchPass()))
        target=self.node('stretch',settings)
        raw=self.run_chain(self.pipeline(),[target])['output']
        geometry=Geometry(p.source.shape[:2],(0,0),p.fingerprint)
        expected=blend(p.source,raw,build_mask(p.source,m['settings'].automatic),ingress_geometry=geometry,processed_geometry=geometry,mask_geometry=geometry)
        for divisor in (1,4):
            result=self.run_chain(p,[m,target],divisor)
            np.testing.assert_array_equal(result['output'],reduce_image(expected,divisor))

    def test_two_independent_recipients_recompute_masks_on_their_own_ingress(self):
        from astrochain.curves import process
        from astrochain.model import reduce_image
        from lumerys_masks.automatic_mask import build_mask
        p=self.pipeline();a=self.mask('a');b=self.mask('b',intensity=.5)
        geometry=Geometry(p.source.shape[:2],(0,0),p.fingerprint)
        first=self.expected(p,a)
        second=blend(first,process(first,self.following),build_mask(first,b['settings'].automatic),
                     ingress_geometry=geometry,processed_geometry=geometry,mask_geometry=geometry,intensity=.5)
        modules=[a,self.node('curves',self.curve,'first'),b,self.node('curves',self.following,'second')]
        for divisor in (1,4):
            result=self.run_chain(p,modules,divisor)
            np.testing.assert_array_equal(result['output'],reduce_image(second,divisor))

    def test_cache_eviction_preserves_results(self):
        p=self.pipeline();p.cache_budget=1;m=self.mask();modules=[m,self.node('curves',self.curve)]
        expected=self.expected(p,m)
        for _ in range(2):
            result=self.run_chain(p,modules)
            np.testing.assert_array_equal(result['output'],expected)
        self.assertFalse(p.universal_raw_cache)
        self.assertFalse(p.universal_blend_cache)

    def test_equalizer_then_filaments_receives_the_mixed_image(self):
        from astrochain.model import EqualizerSettings
        from astrochain.filament_settings import FilamentSettings
        from lumerys_masks.automatic_mask import build_mask
        p=self.pipeline();m=self.mask();eq=self.node('eq',EqualizerSettings(gains=(2.,0.,0.,0.,0.,0.,0.,0.)))
        filament=self.node('filament',FilamentSettings(protect_stars=False))
        raw=self.run_chain(self.pipeline(),[eq])['output']
        geometry=Geometry(p.source.shape[:2],(0,0),p.fingerprint)
        mixed=blend(p.source,raw,build_mask(p.source,m['settings'].automatic),ingress_geometry=geometry,processed_geometry=geometry,mask_geometry=geometry)
        expected=self.run_chain(self.Pipeline(mixed),[filament])['output']
        actual=self.run_chain(p,[m,eq,filament])
        np.testing.assert_array_equal(actual['stages']['eq'],mixed)
        np.testing.assert_array_equal(actual['output'],expected)
        self.assertNotIn('universal_mask',actual['diagnostics']['filament'])

    def test_filament_recipient_uses_native_geometry_at_proxy_resolution(self):
        from astrochain.filament_settings import FilamentSettings
        from astrochain.model import reduce_image
        from lumerys_masks.automatic_mask import build_mask
        p=self.pipeline();m=self.mask();target=self.node('filament',FilamentSettings(protect_stars=False))
        raw=self.run_chain(self.pipeline(),[target])['output']
        geometry=Geometry(p.source.shape[:2],(0,0),p.fingerprint)
        expected=blend(p.source,raw,build_mask(p.source,m['settings'].automatic),ingress_geometry=geometry,processed_geometry=geometry,mask_geometry=geometry)
        actual=self.run_chain(p,[m,target],4)
        np.testing.assert_array_equal(actual['output'],reduce_image(expected,4))

    def test_minimal_project_compatibility_and_application_parameters(self):
        from lumerys_masks.chain_state import MaskNodeSettings
        p=self.pipeline();m=self.mask(intensity=.35)
        record=m['settings'].to_project();restored=MaskNodeSettings.from_project(record)
        self.assertTrue(restored.apply_next);self.assertEqual(restored.intensity,.35)
        record['version']=1;record.pop('apply_next');record.pop('intensity')
        self.assertFalse(MaskNodeSettings.from_project(record).apply_next)
        from astrochain.wiring import ordered_ids
        snap=dict(modules=[m],ghs=p.initial,state_index=1,integrated=False,divisor=4,format='FITS float32',path='')
        saved=p.serial_project(snap);saved['versions']['masks']=1;saved['modules'][0]['settings']=record
        self.assertFalse(p.load_serial_project(saved)['modules'][0]['settings'].apply_next)



class CentralInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def dialog(self,with_freeze=False):
        from astrochain.ui import ChainDialog
        from astrochain.curves import CurveSettings
        from astrochain.tone_curve import IDENTITY
        d=ChainDialog(np.linspace(.01,.7,32*40,dtype=np.float32).reshape(32,40),{},None)
        d.state.setCurrentIndex(1);d.timer.stop();d.loading=True
        mask=d.canvas.add_module('masks');photo=d.canvas.add_module('curves')
        settings=CurveSettings(( ((0.,0.),(.5,.8),(1.,1.)), )+(IDENTITY,)*8)
        d.editors[photo.key].restore(settings)
        if with_freeze:d.canvas.add_module('freeze',edge=(mask.key,photo.key))
        d.loading=False;d.graph_changed();d.timer.stop()
        self.addCleanup(lambda:self.cleanup(d))
        return d,d.editors[mask.key],photo.key

    def cleanup(self,d):
        d.timer.stop();d.cancel_token.set();d.pool.waitForDone(15000);self.app.processEvents()
        for editor in d.editors.values():editor.close()
        d.close();d.deleteLater();self.app.processEvents()

    def settle(self,d):
        import time
        end=time.monotonic()+15
        while time.monotonic()<end:
            self.app.processEvents();time.sleep(.003)
            if not d.busy and not d.pending and not d.timer.isActive():return
        self.fail('Preview did not settle')

    def test_new_node_applies_and_manual_settings_keep_application(self):
        d,e,target=self.dialog()
        self.assertTrue(e.settings().apply_next)
        d.start(False);self.settle(d)
        self.assertIn('universal_mask',d.displayed['diagnostics'][target])
        e.controls.mode.setCurrentIndex(1);e.controls.begin(15,15);e.controls.end()
        self.assertTrue(e.settings().apply_next)
        d.timer.stop();d.start(False);self.settle(d)
        self.assertIn('universal_mask',d.displayed['diagnostics'][target])
        record=d.pipeline.serial_project(d.snapshot(require_output=False,mask_pixels=True))
        restored=d.pipeline.load_serial_project(record)
        settings=next(m['settings'] for m in restored['modules'] if m['kind']=='masks')
        self.assertTrue(settings.apply_next);self.assertTrue(settings.corrections)

    def test_stretch_masks_curves_clahe_separate_stars(self):
        from dataclasses import replace
        from astrochain.clahe import process as clahe
        from astrochain.model import reduce_image
        from astrochain.star_node import StarPair, StarSettings, input_stamp
        from astrochain.stretch import StretchPass, StretchSettings

        d,_,target=self.dialog()
        d.loading=True
        mask=next(n.key for n in d.canvas.modules if n.kind=='masks')
        stretch=d.canvas.add_module('stretch',edge=('input',mask))
        d.editors[stretch.key].restore(StretchSettings((StretchPass('statistical',enabled=True),StretchPass(),StretchPass())))
        contrast=d.canvas.add_module('clahe')
        stars=d.canvas.add_module('separate_stars')
        editor=d.editors[stars.key]
        p=d.pipeline
        state,ghs,integrated,upstream,stellar=editor.current_input()
        self.assertEqual([m['kind'] for m in upstream],['stretch','masks','curves','clahe'])
        native=p.compute_serial(state,ghs,integrated,upstream,1)
        self.assertEqual(native['diagnostics'][target]['universal_mask']['source'],mask)
        np.testing.assert_array_equal(native['output'],clahe(native['stages'][target],upstream[-1]['settings']))
        starless=native['output']*.7
        pair=StarPair.capture(input_stamp(p,state,ghs,integrated,upstream,None),
                              (starless,native['output']-starless),native['offset'],native['output_state'])
        p.star_pairs[stars.key]=pair
        editor.restore(StarSettings(token=pair.token))
        self.assertIs(editor.pair(),pair)
        modules=d.snapshot(require_output=False)['modules']
        for divisor in (1,4):
            for _ in range(2):
                result=p.compute_serial(state,ghs,integrated,modules,divisor)
                np.testing.assert_array_equal(result['output'],reduce_image(starless,divisor))
                self.assertIn('universal_mask',result['diagnostics'][target])
                for key in (contrast.key,stars.key):
                    self.assertNotIn('universal_mask',result['diagnostics'].get(key,{}))
        modules[1]['settings']=replace(modules[1]['settings'],intensity=.25)
        stale=p.compute_serial(state,ghs,integrated,modules,1,allow_partial=True)
        self.assertEqual(stale['last_valid'],contrast.key)
        self.assertIn('run separation for the current input',stale['processing_error'])

    def test_snapshot_rejects_unsupported_path_before_auxiliary_operations(self):
        from lumerys_masks.universal_mask import UnsupportedUniversalMask
        d,e,target=self.dialog(with_freeze=True)
        with self.assertRaises(UnsupportedUniversalMask):d.snapshot(require_output=False)
        sentinel=object();d.pipeline.star_pairs['existing-pair']=sentinel
        revision=d.revision;d.schedule()
        self.assertIs(d.pipeline.star_pairs['existing-pair'],sentinel)
        self.assertGreater(d.revision,revision)
        self.assertFalse(d.pending)
        self.assertIn('phase 2',d.error_notice.text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
