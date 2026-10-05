"""Integration tests for deletion, profiles, salary records and growth. No live Gemini calls."""
import unittest,json,base64
from unittest.mock import patch
import test_app as env
from test_app import Client
import app
from business_features import growth

class BusinessTests(unittest.TestCase):
 def setUp(self):
  with app.db() as c:
   for table in ('deletion_previews','growth_plans','salary_records','staff','business_profiles','dashboard_settings','reports','healing_runs','datasets','sessions','attempts'):
    c.execute('DELETE FROM '+table)
   c.execute("DELETE FROM users WHERE role='customer'")
   c.execute("UPDATE users SET active=1")
  self.admin=Client();self.admin.login('admin@test.com')
  self.owner=Client();self.other=Client()
  for client,email,name in [(self.owner,'owner@test.com','Owner shop'),(self.other,'other@test.com','Other shop')]:
   self.assertEqual(client.call('/register',{'email':email,'business':name,'password':'Testing-Password-123'})[0],200);client.login(email)
  self.oid=self.owner.call('/me')[1]['id'];self.bid=self.other.call('/me')[1]['id'];self.base=f'/workspaces/{self.oid}'
 def upload(self,client=None,content=None):
  text=content or 'date,revenue,cost\n'+''.join(f'2025-{i:02d}-01,{i*100},50\n' for i in range(1,10))
  status,r=(client or self.owner).call('/datasets',{'name':'sales.csv','content':text});self.assertEqual(status,200);return r['id']
 def profile_body(self):return {'business':'New shop','sector':'Retail','email':'owner@test.com','owner_name':'Owner','currency':'INR','monthly_target':2000,'goal':'Improve repeat orders.'}
 def test_profiles_images_staff_salary_and_isolation(self):
  b=self.profile_body();b['shop_image']='https://example.com/shop.jpg'
  self.assertEqual(self.owner.call(self.base+'/profile',b)[0],200)
  self.assertEqual(self.other.call(self.base+'/profile')[0],404)
  self.assertEqual(self.other.call(self.base+'/profile',b)[0],404)
  self.assertEqual(self.owner.call(self.base+'/profile',b,csrf=False)[0],403)
  self.assertEqual(self.admin.call(self.base+'/profile')[1]['profile']['goal'],b['goal'])
  self.assertEqual(self.owner.call('/settings',{'image':'javascript:alert(1)'})[0],400)
  self.assertEqual(self.owner.call('/settings',{'image':'data:image/svg+xml;base64,AAAA'})[0],400)
  self.assertEqual(self.owner.call('/settings',{'image':'https://example.com/a.jpg'})[0],200)
  self.assertEqual(self.other.call('/settings')[1]['image'],'')
  staff={'name':'Worker','job':'Sales','salary':12500,'start_date':'2024-01-01','active':True}
  status,r=self.owner.call(self.base+'/staff',staff);self.assertEqual(status,200);sid=r['id']
  self.assertEqual(self.other.call(self.base+'/staff/'+str(sid),staff)[0],404)
  staff['salary']=13000;self.assertEqual(self.admin.call(self.base+'/staff/'+str(sid),staff)[0],200)
  b['currency']='USD';self.assertEqual(self.owner.call(self.base+'/profile',b)[0],400)
  self.assertEqual(self.owner.call(self.base+'/salary',{'staff':sid,'month':'2025-06','amount':13000,'status':'pending'})[0],200)
  self.assertEqual(self.owner.call(self.base+'/salary',{'staff':sid,'month':'2025-06','amount':13000,'status':'paid'})[0],200)
  ledger=self.admin.call(self.base+'/salary')[1];self.assertEqual(len(ledger),1);self.assertEqual(ledger[0]['status'],'paid')
  self.assertEqual(self.other.call(f'/workspaces/{self.bid}/salary',{'staff':sid,'month':'2025-06','amount':0,'status':'paid'})[0],404)
  self.assertEqual(self.owner.call(self.base+'/staff/'+str(sid)+'/delete',{'confirm':'DELETE'})[0],200)
  self.assertEqual(self.owner.call(self.base+'/salary')[1],[])
 def test_growth_and_cascade_deletion(self):
  did=self.upload();other_did=self.upload(self.other)
  body={'dataset':did,'mapping':{'date':'date','revenue':'revenue','date_format':'iso'},'currency':'INR','confirmed':True}
  status,plan=self.owner.call(self.base+'/growth',body);self.assertEqual(status,200);self.assertEqual(plan['result']['status'],'estimated')
  self.assertEqual(len(plan['result']['forecast']),3);self.assertAlmostEqual(plan['result']['forecast'][0]['estimate'],1000)
  self.assertEqual(self.other.call(f'/workspaces/{self.bid}/growth',body)[0],404)
  self.assertEqual(self.other.call(self.base+'/growth')[0],404)
  self.assertEqual(self.owner.call(self.base+'/growth',{**body,'use_ai':True})[0],400)
  with patch('business_features.gemini_prompt',return_value={'status':'generated','text':'Try measuring repeat orders.'}) as gemini:
   status,_=self.owner.call(self.base+'/growth',{**body,'use_ai':True,'consent':True});self.assertEqual(status,200)
   prompt=gemini.call_args.args[0];self.assertNotIn('owner@test.com',prompt);self.assertNotIn('Owner shop',prompt)
  run=next(r for r in self.admin.call('/healing')[1] if r['dataset']==did)
  # A further derived copy ensures deletion follows the whole descendant tree.
  self.assertEqual(self.admin.call('/healing/auto',{'dataset':run['derived']})[0],200)
  report=next(r for r in self.admin.call('/reports')[1] if r['dataset']==did)
  self.admin.call(f"/reports/{report['id']}/publish",{'published':True})
  self.assertEqual(self.owner.call('/datasets/'+str(did)+'/download')[0],200)
  self.assertEqual(self.other.call('/datasets/'+str(did)+'/download')[0],404)
  self.assertEqual(self.other.call('/datasets/'+str(did)+'/delete-preview')[0],404)
  preview=self.owner.call('/datasets/'+str(did)+'/delete-preview')[1]
  self.assertEqual(preview['datasets'],3);self.assertEqual(preview['growth_plans'],2)
  self.assertEqual(self.owner.call('/datasets/'+str(did)+'/delete',{'confirm':'DELETE','token':'old'})[0],409)
  self.assertEqual(self.owner.call('/datasets/'+str(did)+'/delete',{'confirm':'DELETE','token':preview['token']},csrf=False)[0],403)
  self.assertEqual(self.owner.call('/datasets/'+str(did)+'/delete',{'confirm':'DELETE','token':preview['token']})[0],200)
  self.assertEqual(self.owner.call('/datasets')[1],[]);self.assertEqual(self.owner.call('/reports')[1],[]);self.assertEqual(self.owner.call(self.base+'/growth')[1],[])
  self.assertEqual(self.other.call('/datasets/'+str(other_did))[0],200)
  replacement=self.upload()
  self.assertEqual(self.owner.call('/datasets/'+str(replacement)+'/delete',{'confirm':'DELETE','token':preview['token']})[0],409)
  with app.db() as c:self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
 def test_admin_deletes_customer_dataset_and_preview_is_actor_bound(self):
  did=self.upload();other_did=self.upload(self.other)
  path='/datasets/'+str(did)
  preview=self.admin.call(path+'/delete-preview')[1]
  self.assertEqual(self.owner.call(path+'/delete',{'confirm':'DELETE','token':preview['token']})[0],409)
  self.assertEqual(self.other.call(path+'/delete',{'confirm':'DELETE','token':preview['token']})[0],404)
  self.assertEqual(self.admin.call(path+'/delete',{'confirm':'DELETE','token':preview['token']})[0],200)
  self.assertEqual(self.owner.call(path)[0],404)
  self.assertEqual(self.owner.call('/datasets')[1],[])
  self.assertEqual(self.other.call('/datasets/'+str(other_did))[0],200)
  self.assertFalse(any(r['dataset']==did for r in self.admin.call('/healing')[1]))
  with app.db() as c:self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
 def test_account_controls(self):
  self.assertEqual(self.owner.call(self.base+'/account',{'action':'disable'})[0],403)
  self.assertEqual(self.admin.call(self.base+'/account',{'action':'disable','admin_password':'wrong'})[0],403)
  self.assertEqual(self.admin.call(self.base+'/account',{'action':'disable','admin_password':'Testing-Password-123'})[0],200)
  self.assertEqual(self.owner.call('/me')[0],401)
  self.assertEqual(self.owner.call('/login',{'email':'owner@test.com','password':'Testing-Password-123'})[0],401)
  self.assertEqual(self.admin.call(self.base+'/account',{'action':'enable','admin_password':'Testing-Password-123'})[0],200)
  self.owner.login('owner@test.com')
  self.assertEqual(self.admin.call(self.base+'/account',{'action':'reset_password','password':'Replacement-Test-123','admin_password':'Testing-Password-123'})[0],200)
  self.assertEqual(self.owner.call('/me')[0],401)
  self.assertEqual(self.owner.call('/login',{'email':'owner@test.com','password':'Replacement-Test-123'})[0],200)
  self.owner.csrf=self.owner.call('/me')[1]['csrf']
  self.assertEqual(self.owner.call('/password',{'current':'wrong','password':'New-Password-456'})[0],403)
  self.assertEqual(self.owner.call('/password',{'current':'Replacement-Test-123','password':'New-Password-456'})[0],200)
  self.assertEqual(self.owner.call('/me')[0],401)
 def test_migration_preserves_existing_users(self):
  import tempfile,sqlite3
  from pathlib import Path
  with tempfile.TemporaryDirectory() as directory:
   old=Path(directory)/'old.sqlite3'
   with sqlite3.connect(old) as c:
    c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,business TEXT NOT NULL,sector TEXT NOT NULL)')
    c.execute("INSERT INTO users VALUES(1,'legacy@test.com','existing-hash','customer','Legacy shop','Retail')")
   with patch.object(app,'DB',old):
    app.init();app.init()
    with app.db() as c:
     row=c.execute('SELECT * FROM users WHERE id=1').fetchone();self.assertEqual(row['business'],'Legacy shop');self.assertEqual(row['password'],'existing-hash');self.assertEqual(row['active'],1)
     self.assertEqual(c.execute('SELECT COUNT(*) FROM growth_plans').fetchone()[0],0)
 def test_forecast_missing_gaps_and_no_leakage(self):
  cols=['date','revenue'];rows=[{'date':f'2025-{i:02d}-01','revenue':str(i*100)} for i in range(1,10)]
  args=({'revenue':'revenue','date':'date'},'INR',0,'Retail','', '2026-01')
  self.assertEqual(growth(cols,rows[:3],*args)['status'],'insufficient_data')
  self.assertEqual(growth(cols,rows[:3]+rows[4:],*args)['status'],'insufficient_data')
  self.assertEqual(growth(cols,rows+[{'date':'bad','revenue':'0'}],*args)['invalid_rows'],1)
  a=growth(cols,rows,*args);self.assertEqual(a['backtest']['held_out_months'],3);self.assertEqual(a['backtest']['mae'],0)
  # Perturbing the last observation must appear as held-out error, not disappear into training.
  changed=rows[:-1]+[{'date':'2025-09-01','revenue':'9000'}];self.assertGreater(growth(cols,changed,*args)['backtest']['mae'],0)
  future=rows+[{'date':'2026-01-01','revenue':'999999'}];self.assertEqual(growth(cols,future,*args)['history'],a['history'])

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.server.shutdown();env.tmp.cleanup()
