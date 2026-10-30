from pathlib import Path
import hashlib,zipfile,json,shutil
r=Path(__file__).resolve().parent;baseline=r.parent/'palette_gas_curves_dev'
reports=r/'reports';reports.mkdir(exist_ok=True)
log=Path('/tmp/lumerys_native_verified.log').read_text()
assert log.rstrip().endswith('OK') and 'FAILED' not in log, 'Tests must finish successfully before packaging'
shutil.copy2('/tmp/lumerys_native_verified.log',reports/'final_tests.log')
shutil.copy2('/tmp/lumerys_native_dedicated.log',reports/'dedicated_tests.log')
changes=[]
for p in (baseline/'astrochain').rglob('*.py'):
 q=r/p.relative_to(baseline)
 if p.read_bytes()!=q.read_bytes():changes.append(str(p.relative_to(baseline)))
assert all('/vendor/' not in '/'+p for p in changes)
installed=Path.home()/'Library/Application Support/SASpro/scripts/astrochain_prototype'
with zipfile.ZipFile(installed/'_astrochain_lib.zip') as z:
 assert all(z.read(n)==(baseline/n).read_bytes() for n in z.namelist() if n.endswith('.py'))
assert (installed/'AstroChain_Prototype.py').read_bytes()==(baseline/'AstroChain_Prototype.py').read_bytes()
(reports/'integrity.json').write_text(json.dumps(dict(changed_common_files=changes,vendor_unchanged=True,main_installation_matches_original=True,legacy_development_unchanged=True),indent=2))
lib=r/'_astrochain_lib.zip'
with zipfile.ZipFile(lib,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted((r/'astrochain').rglob('*.py')):z.write(p,p.relative_to(r))
archive=r/'Lumerys_Palette_Native_DEV_0.10.0.dev1.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for p in (r/'AstroChain_Prototype.py',lib,r/'README.md'):z.write(p,Path('Lumerys_Palette_Native_DEV')/p.name)
 for p in sorted((r/'astrochain').rglob('*.py')):z.write(p,Path('Lumerys_Palette_Native_DEV/src')/p.relative_to(r))
 for p in sorted((r/'tests').glob('test_palette_native*.py')):z.write(p,Path('Lumerys_Palette_Native_DEV/tests')/p.name)
 for p in reports.iterdir():
  if p.name!='curves_0.9.4.png' and p.is_file():z.write(p,Path('Lumerys_Palette_Native_DEV/reports')/p.name)
dest=installed.parent/'lumerys_palette_native_dev'
assert not dest.exists(),'Do not overwrite an existing DEV installation'
dest.mkdir()
for p in (r/'AstroChain_Prototype.py',lib,r/'README.md'):shutil.copy2(p,dest/p.name)
manifest=dict(destination=str(dest),main_installation_untouched=True,version='0.10.0.dev1',live_host_tested=False,sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (r/'AstroChain_Prototype.py',lib,archive)})
(reports/'installation.json').write_text(json.dumps(manifest,indent=2))
(r/'SHA256SUMS.txt').write_text(''.join(f'{v}  {k}\n' for k,v in manifest['sha256'].items()))
print(json.dumps(manifest,indent=2))
