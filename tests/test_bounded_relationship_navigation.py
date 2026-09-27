import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('navigation',ROOT/'scripts/build_bounded_relationship_navigation.py');nav=importlib.util.module_from_spec(spec);spec.loader.exec_module(nav)
class BoundedNavigationTests(unittest.TestCase):
 def test_inactive_plane_cannot_force_or_hide_active_limits(self):
  row={'planes':[{'name':'active','chunks':['a'],'assertions':100001},{'name':'historical','chunks':['b'],'assertions':9}]}
  counts,over=nav.route_limit(row,{'active'},{'a':{'bytes':3}})
  self.assertTrue(over);self.assertEqual(counts,{'chunks':1,'assertions':100001,'compressed_bytes':3})
 def test_exact_limit_and_one_extra_chunk(self):
  chunks={str(i):{'bytes':1} for i in range(65)}
  for size,want in [(64,False),(65,True)]:
   row={'planes':[{'name':'active','chunks':list(chunks)[:size],'assertions':100000}]}
   self.assertEqual(nav.route_limit(row,{'active'},chunks)[1],want)
 def test_hash_tampering_and_external_paths_are_rejected(self):
  with tempfile.TemporaryDirectory() as temporary:
   path=Path(temporary);raw=b'[]';(path/'a.json').write_bytes(raw)
   with patch.object(nav,'BUNDLE',path):
    self.assertEqual(nav.load_bound({'path':'a.json','sha256':nav.digest(raw),'bytes':2}),[])
    with self.assertRaisesRegex(ValueError,'binding'):nav.load_bound({'path':'a.json','sha256':'0'*64})
    with self.assertRaisesRegex(ValueError,'External'):nav.load_bound({'path':'../outside','sha256':'0'*64})
 def test_navigation_preserves_local_and_pinned_source(self):
  import subprocess
  module = 'data:text/javascript,' + __import__('urllib.parse',fromlist=['quote']).quote(nav.NAVIGATION_JS)
  code = '''
const {explorerLink}=await import(MODULE);
const assert=(await import('node:assert/strict')).default;
const sha='a'.repeat(40);
for(const page of [
 'http://127.0.0.1:4178/okf-uk-legislation/docs/bounded-relationship-navigation.html',
 'https://raw.githubusercontent.com/owner/repo/'+sha+'/bundle/docs/bounded-relationship-navigation.html',
 'https://chris-page-gov.github.io/okf-uk-legislation/docs/bounded-relationship-navigation.html']) {
 const result=new URL(explorerLink(page,'dataset/ukpga/1992/4'));
 assert.equal(result.searchParams.get('bundle'),new URL('../okf-explorer.json',page).href);
 assert.equal(result.hash,'#dataset/ukpga/1992/4');
}
assert.throws(()=>explorerLink('file:///tmp/docs/test.html','dataset/x'));
assert.throws(()=>explorerLink('http://untrusted.test/docs/test.html','dataset/x'));
assert.throws(()=>explorerLink('https://example.test/docs/test.html','dataset/../escape'));
'''.replace('MODULE',json.dumps(module))
  subprocess.run(['node','--input-type=module','-e',code],check=True,capture_output=True)
