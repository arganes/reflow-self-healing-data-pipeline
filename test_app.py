import os,tempfile,unittest,threading,json,urllib.request,urllib.error,http.cookiejar
from pathlib import Path
tmp=tempfile.TemporaryDirectory();os.environ['REFLOW_DATA']=tmp.name
import app

class Client:
 def __init__(self):self.op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));self.csrf=''
 def call(self,path,data=None,csrf=True):
  req=urllib.request.Request(BASE+'/api'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-CSRF-Token':self.csrf if csrf else ''})
  try:
   with self.op.open(req) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def login(self,email):
  assert self.call('/login',{'email':email,'password':'Testing-Password-123'})[0]==200
  self.csrf=self.call('/me')[1]['csrf']

app.init()
with app.db() as c:c.execute('INSERT INTO users(email,password,role,business,sector) VALUES(?,?,?,?,?)',('admin@test.com',app.pw('Testing-Password-123'),'admin','Admin','All'))
server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);BASE='http://127.0.0.1:'+str(server.server_address[1]);threading.Thread(target=server.serve_forever,daemon=True).start()

class Tests(unittest.TestCase):
 def test_end_to_end_isolation(self):
  a,b,admin=Client(),Client(),Client()
  for client,email,business in [(a,'a@test.com','Shop A'),(b,'b@test.com','Shop B')]:
   status,_=client.call('/register',{'email':email,'business':business,'password':'Testing-Password-123','role':'admin'});self.assertEqual(status,200);client.login(email);self.assertEqual(client.call('/me')[1]['role'],'customer')
  self.assertEqual(a.call('/register',{'email':'a@test.com','business':'Another','password':'Testing-Password-123'})[0],409)
  admin.login('admin@test.com')
  payload={'name':'sales.csv','content':(app.ROOT/'samples/retail.csv').read_text(),'owner':9999}
  self.assertEqual(a.call('/datasets',payload,csrf=False)[0],403)
  status,result=a.call('/datasets',payload);self.assertEqual(status,200);did=result['id']
  self.assertEqual(b.call('/datasets/'+str(did))[0],404)
  self.assertEqual(b.call('/datasets')[1],[])
  self.assertEqual(len(admin.call('/businesses')[1]),2)
  self.assertEqual(a.call('/datasets/'+str(did)+'/analyse',{})[0],403)
  conf={'mapping':{'revenue':'revenue','cost':'total_cost','category':'category','date':'date'},'currency':'INR','confirmed':True}
  status,result=admin.call('/datasets/'+str(did)+'/analyse',conf);self.assertEqual(status,200);rid=result['id'];self.assertEqual(result['analysis']['profit'],11600)
  self.assertEqual(result['analysis']['revenue'],38500)
  self.assertEqual(a.call('/reports')[1],[])
  self.assertEqual(a.call('/reports/'+str(rid)+'/publish',{'published':True})[0],403)
  self.assertEqual(admin.call('/reports/'+str(rid)+'/publish',{'published':True,'note':'Review cost coverage.'})[0],200)
  self.assertEqual(len(a.call('/reports')[1]),1);self.assertEqual(b.call('/reports')[1],[])
  self.assertEqual(admin.call('/reports/'+str(rid)+'/publish',{'published':False})[0],200);self.assertEqual(a.call('/reports')[1],[])
  self.assertEqual(a.call('/logout',{})[0],200);self.assertEqual(a.call('/datasets')[0],401)
 def test_healing_and_permissions(self):
  from unittest.mock import patch
  customer,admin=Client(),Client()
  customer.call('/register',{'email':'healing@test.com','business':'Quality shop','password':'Testing-Password-123'})
  customer.login('healing@test.com');admin.login('admin@test.com')
  original=(app.ROOT/'samples/quality_issues.csv').read_text()
  did=customer.call('/datasets',{'name':'quality.csv','content':original})[1]['id']
  body={'dataset':did,'policy':{'numeric':['revenue','total_cost'],'date':'date','date_format':'dmy','trim':True}}
  self.assertEqual(customer.call('/healing/run',body)[0],403)
  self.assertEqual(customer.call('/healing')[0],403)
  self.assertEqual(admin.call('/healing/run',body,csrf=False)[0],403)
  status,run=admin.call('/healing/run',body);self.assertEqual(status,200)
  r=run['result'];self.assertEqual(r['before']['whitespace_cells'],3);self.assertEqual(r['after']['whitespace_cells'],0)
  self.assertEqual(r['after']['invalid_numeric'],1);self.assertEqual(r['after']['missing_cells'],1)
  self.assertEqual(r['after']['invalid_dates'],1);self.assertEqual(r['after']['duplicate_candidates'],1)
  self.assertEqual(r['status'],'needs_review');self.assertEqual(r['after']['rows'],5)
  rid=run['id'];derived=admin.call(f'/healing/{rid}/download')[1]
  self.assertEqual(derived['rows'][0]['order_id'],'001');self.assertEqual(derived['rows'][0]['date'],'2026-01-15')
  self.assertEqual(customer.call(f'/healing/{rid}/download')[0],403)
  self.assertEqual(customer.call(f'/healing/{rid}/ai',{'consent':True})[0],403)
  self.assertEqual(admin.call(f'/healing/{rid}/ai',{})[0],400)
  with patch.dict(os.environ,{'GEMINI_API_KEY':'','GEMINI_MODEL':''}):
   self.assertEqual(admin.call(f'/healing/{rid}/ai',{'consent':True})[1]['status'],'unavailable')
  with app.db() as c:
   source=json.loads(c.execute('SELECT content FROM datasets WHERE id=?',(did,)).fetchone()[0])
   self.assertEqual(source['rows'][0]['date'],'15/01/2026')
   self.assertEqual(source['rows'][0]['category'],' Retail ')
  # Invalid policy must not leave a partial derived dataset or run.
  count=len(admin.call('/datasets')[1]);body['policy']['numeric']=['nonexistent']
  self.assertEqual(admin.call('/healing/run',body)[0],400);self.assertEqual(len(admin.call('/datasets')[1]),count)
 def test_gemini_recovery(self):
  from unittest.mock import patch,MagicMock
  import healing
  evidence={'before':{},'after':{},'status':'validated','actions':{}}
  response=MagicMock();response.__enter__.return_value.read.return_value=b'{"candidates":[{"content":{"parts":[{"text":"Verified summary"}]}}]}'
  failure=urllib.error.HTTPError('https://example.test',503,'unavailable',{},None)
  with patch.dict(os.environ,{'GEMINI_API_KEY':'test-key','GEMINI_MODEL':'test-model'}),patch('healing.time.sleep'),patch('healing.urllib.request.urlopen',side_effect=[failure,response]) as request:
   result=healing.gemini_summary(evidence);self.assertEqual(result['status'],'generated');self.assertEqual(result['attempts'],2)
   payload=json.loads(request.call_args.args[0].data);self.assertNotIn('test-key',str(payload))
  with patch.dict(os.environ,{'GEMINI_API_KEY':'test-key','GEMINI_MODEL':'test-model'}),patch('healing.time.sleep'),patch('healing.urllib.request.urlopen',side_effect=failure):
   result=healing.gemini_summary(evidence);self.assertEqual(result['status'],'unavailable');self.assertEqual(result['attempts'],3)
 def test_zz_report_generation_and_publication(self):
  from unittest.mock import patch
  import report_builder
  admin,owner,other=Client(),Client(),Client();admin.login('admin@test.com')
  for client,email in [(owner,'report_owner@test.com'),(other,'report_other@test.com')]:
   client.call('/register',{'email':email,'business':email,'password':'Testing-Password-123'});client.login(email)
  did=owner.call('/datasets',{'name':'retail.csv','content':(app.ROOT/'samples/retail.csv').read_text()})[1]['id']
  rid=admin.call('/reports/auto',{'dataset':did})[1]['id']
  report=next(r for r in admin.call('/reports')[1] if r['id']==rid);a=report['analysis']
  self.assertEqual(a['kind'],'automatic_graph_report');self.assertFalse(report['published'])
  self.assertTrue(any('Sum of revenue' in c['title'] for c in a['catalog']))
  self.assertEqual(owner.call('/reports/auto',{'dataset':did})[0],403)
  self.assertEqual(owner.call(f'/reports/{rid}/generate',{'requirements':'monthly sales'})[0],403)
  self.assertEqual(admin.call(f'/reports/{rid}/generate',{'requirements':'monthly sales','use_ai':True})[0],400)
  self.assertEqual(admin.call(f'/reports/{rid}/generate',{'requirements':'monthly sales','chart_ids':['unknown']})[0],400)
  self.assertEqual(admin.call(f'/reports/{rid}/generate',{'requirements':'monthly sales'},csrf=False)[0],403)
  admin.call(f'/reports/{rid}/publish',{'published':True,'note':'Original report'})
  before=next(r for r in owner.call('/reports')[1] if r['id']==rid)
  status,new=admin.call(f'/reports/{rid}/generate',{'requirements':'Show monthly sales and category comparisons'})
  self.assertEqual(status,200);self.assertNotEqual(new['id'],rid)
  self.assertEqual(next(r for r in owner.call('/reports')[1] if r['id']==rid),before)
  self.assertFalse(any(r['id']==new['id'] for r in owner.call('/reports')[1]))
  chosen=next(c for c in a['catalog'] if 'Sum of revenue by month' in c['title'])
  self.assertEqual(sum(v for _,v in chosen['values']),38500)
  with patch('report_builder.gemini_prompt',return_value={'status':'generated','text':json.dumps({'chart_ids':[chosen['id']],'summary':'Review recorded monthly revenue.','limitations':'Units need confirmation.'}),'attempts':1,'model':'mock'}):
   status,result=admin.call(f'/reports/{rid}/generate',{'requirements':'Monthly sales','use_ai':True,'consent':True})
   self.assertEqual(status,200);generated=next(r for r in admin.call('/reports')[1] if r['id']==result['id'])
   self.assertEqual(generated['analysis']['selected'],[chosen['id']]);self.assertEqual(generated['analysis']['catalog'],a['catalog'])
   admin.call(f"/reports/{result['id']}/publish",{'published':True})
   self.assertTrue(any(r['id']==result['id'] for r in owner.call('/reports')[1]));self.assertFalse(any(r['id']==result['id'] for r in other.call('/reports')[1]))
  with patch('report_builder.gemini_prompt',return_value={'status':'generated','text':json.dumps({'chart_ids':['invented'],'summary':'bad','limitations':''}),'attempts':1}):
   fallback=report_builder.generate_report(a,'Monthly sales',True)
   self.assertEqual(fallback['ai']['status'],'unavailable');self.assertEqual(fallback['catalog'],a['catalog']);self.assertNotIn('invented',fallback['selected'])
  with patch('report_builder.gemini_prompt',return_value={'status':'unavailable','text':'Quota reached.','attempts':3}):
   fallback=report_builder.generate_report(a,'profit forecast',True)
   self.assertTrue(fallback['warnings']);self.assertEqual(fallback['ai']['status'],'unavailable');self.assertTrue(fallback['selected'])
 def test_z_automatic_upload_graphs(self):
  customer,admin=Client(),Client()
  customer.call('/register',{'email':'auto@test.com','business':'Auto shop','password':'Testing-Password-123'})
  customer.login('auto@test.com');admin.login('admin@test.com')
  status,upload=customer.call('/datasets',{'name':'issues.csv','content':(app.ROOT/'samples/quality_issues.csv').read_text()})
  self.assertEqual(status,200);self.assertEqual(upload['automatic_analysis'],'completed');self.assertNotIn('run_id',upload)
  runs=admin.call('/healing')[1];r=next(x for x in runs if x['dataset']==upload['id']);data=r['result']
  self.assertEqual(data['mode'],'automatic');self.assertEqual(data['after']['rows'],5)
  self.assertEqual(data['after']['whitespace_cells'],0);self.assertEqual(data['policy']['date_format'],'dmy')
  self.assertNotIn('order_id',data['policy']['numeric'])
  charts=data['charts'];hist=next(h for h in charts['histograms'] if h['column']=='revenue')
  self.assertEqual(sum(hist['counts']),3);self.assertEqual(hist['invalid'],1)
  self.assertEqual(charts['trends'][0]['values'],[['2026-01',4]])
  self.assertEqual(customer.call('/healing/auto',{'dataset':upload['id']})[0],403)
  status,reused=admin.call('/healing/auto',{'dataset':upload['id']});self.assertEqual(status,200);self.assertTrue(reused['reused']);self.assertEqual(reused['id'],r['id'])
  self.assertEqual(admin.call('/healing/auto',{'dataset':upload['id']},csrf=False)[0],403)
  self.assertEqual(admin.call('/healing/auto',{'dataset':999999})[0],404)
  from auto_analysis import automatic
  cols,rows=app.parse_file('code,date,temperature\n001,01/02/2026,10\n002,02/03/2026,20','ambiguous.csv')
  result,clean=automatic(cols,rows);self.assertEqual(result['status'],'needs_review');self.assertEqual(clean,rows)
  self.assertEqual(result['policy']['date'],'');self.assertTrue(result['inference']['warnings'])
  self.assertEqual(sum(result['charts']['histograms'][0]['counts']),2)
 def test_unknown_schema_and_quality(self):
  cols,rows=app.parse_file('employee,department\nA,IT\nB,HR','hr.csv')
  result=app.analyse(cols,rows,{},'INR');self.assertIsNone(result['profit']);self.assertIsNone(result['revenue'])
  with self.assertRaises(ValueError):app.parse_file('a,a\n1,2','bad.csv')
  with self.assertRaises(ValueError):app.parse_file('a,b\n1,2,3','bad.csv')
  with self.assertRaises(ValueError):app.analyse(cols,rows,{'revenue':'missing'},'INR')
  with self.assertRaises(ValueError):app.analyse(cols,rows,{'revenue':'employee','cost':'employee'},'INR')
  cols,rows=app.parse_file('revenue,cost,date\n100,70,2026-01-01\n200,,bad-date','x.csv');r=app.analyse(cols,rows,{'revenue':'revenue','cost':'cost','date':'date'},'INR');self.assertEqual(r['profit'],30);self.assertEqual(r['paired_rows'],1);self.assertEqual(r['invalid_dates'],1)
  self.assertIsNone(app.number('₹1,000'));self.assertIsNone(app.number('1e999'))

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:server.shutdown();tmp.cleanup()
