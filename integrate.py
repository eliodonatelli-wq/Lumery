from pathlib import Path
r=Path(__file__).resolve().parent/'astrochain'
def edit(name,old,new):
 p=r/name;s=p.read_text();assert old in s,(name,old);p.write_text(s.replace(old,new))
edit('model.py','MODULE_NAMES={','from .palette_native import NativePaletteSettings, render as native_palette_render, VERSION as NATIVE_PALETTE_VERSION\nfrom .palette_native_inputs import signature as native_input_signature, load as native_load_inputs\nMODULE_NAMES={"palette_native":"Palette Studio",')
edit('model.py','self.freeze_frames={}','self.native_palette_cache=OrderedDict()\n        self.freeze_frames={}')
edit('model.py',"            key=(previous_key,module['id']", "            external_signature=native_input_signature(module['settings']) if module['kind']=='palette_native' and not module['bypass'] else ()\n            key=(previous_key,module['id']")
edit('model.py',"module.get('auto_reference',True))\n            record=", "module.get('auto_reference',True),external_signature)\n            record=")
old="                    elif module['kind']=='palette':"
new="""                    elif module['kind']=='palette_native':
                        prefix=tuple((m['id'],m['kind'],m['settings'],m['bypass'],m.get('force',False),m.get('auto_reference',True),native_input_signature(m['settings']) if m['kind']=='palette_native' and not m['bypass'] else ()) for m in modules[:index])
                        native_key=(state,input_settings if integrated_ghs else None,integrated_ghs,prefix,module['settings'],external_signature)
                        prepared=self.native_palette_cache.get(module['id'])
                        if prepared is None or prepared[0]!=native_key:
                            progress('Palette Studio · preparing native ingress')
                            native=current if divisor==1 else self.compute_serial(state,input_settings,integrated_ghs,modules[:index],1,cancel,progress)['output']
                            channels=native_load_inputs(module['settings'],external_signature)
                            rgb,diagnostic=native_palette_render(native,module['settings'],channels,cancel)
                            rgb.setflags(write=False)
                            self.native_palette_cache[module['id']]=(native_key,rgb,diagnostic)
                            while len(self.native_palette_cache)>1 and buffer_bytes(self.native_palette_cache)>self.cache_budget:
                                self.native_palette_cache.popitem(last=False)
                        else:_,rgb,diagnostic=prepared
                        output=reduce_image(rgb,divisor)
                        if module['settings'].nonlinear():next_state='nonlinear'
                        diagnostic=dict(diagnostic,native_shape=list(rgb.shape),external_inputs=external_signature)
                        # Mask is a diagnostic view through the existing preview service.
                        if module['settings'].mask_view:
                            output=np.repeat(reduce_image(diagnostic['mask'],divisor)[...,None],3,-1);next_state='nonlinear'
                        note='Palette Studio · native render; reduced RGB preview. '+('Artificial SII.' if module['settings'].synthetic else 'RGB gas estimates.' if module['settings'].source=='rgb_estimate' else 'Registered FITS channels; alignment confirmed by user.')
                    elif module['kind']=='palette':"""
edit('model.py',old,new)
edit('model.py',"('parametric','filament','palette','curves')", "('parametric','filament','palette','palette_native','curves')")
edit('model.py',"        if any(m['kind']=='freeze' for m in snapshot['modules']):", "        if any(m['kind']=='palette_native' for m in snapshot['modules']):data['versions']['palette_native']=NATIVE_PALETTE_VERSION\n        if any(m['kind']=='freeze' for m in snapshot['modules']):")
edit('model.py','supported=dict(freeze=', 'supported=dict(palette_native=NATIVE_PALETTE_VERSION,freeze=')
edit('model.py',"            if kind=='freeze':return", "            if kind=='palette_native':return NativePaletteSettings(**p)\n            if kind=='freeze':return")
edit('model.py',"            if m['kind']=='freeze' and", "            if m['kind']=='palette_native' and data['versions'].get('palette_native')!=NATIVE_PALETTE_VERSION:raise ValueError('Incompatible Palette Studio version')\n            if m['kind']=='freeze' and")
edit('node_canvas.py',"MODULE_CATALOG=", "MODULE_CATALOG=")
edit('node_canvas.py',"(('ghs','Adaptive", "(('palette_native','Palette Studio'),('ghs','Adaptive")
edit('node_canvas.py',"'colors','curves','freeze')", "'colors','curves','freeze','palette_native')")
edit('ui.py',"from .model import Pipeline,", "from .palette_native import NativePaletteSettings\nfrom .model import Pipeline,")
edit('ui.py',"settings=FreezeSettings() if node.kind", "settings=NativePaletteSettings() if node.kind=='palette_native' else FreezeSettings() if node.kind")
edit('ui.py',"        elif node.kind=='palette':\n            from .nebula_editor", "        elif node.kind=='palette_native':\n            from .palette_native_editor import NativePaletteEditor\n            self.editors[node.key]=NativePaletteEditor(self,settings,'Palette Studio · '+str(node.serial))\n        elif node.kind=='palette':\n            from .nebula_editor")
edit('ui.py',"('compressor','parametric','filament','palette','curves','freeze')", "('compressor','parametric','filament','palette','palette_native','curves','freeze')")
edit('ui.py',"            if node.kind=='curves' and status", "            if node.kind=='palette_native' and status=='ok' and editor.settings().nonlinear():state='nonlinear'\n            if node.kind=='curves' and status")
