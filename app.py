"""ReFlow local multi-business prototype. Python 3.10+, standard library only."""
import argparse, csv, hashlib, hmac, io, json, os, re, secrets, sqlite3, time
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse
from datetime import datetime
from healing import run_pipeline, gemini_summary
from auto_analysis import automatic, describe
from report_builder import build_report, generate_report, DEFAULT_REQUIREMENTS
from business_features import migrate, handle as business_handle

ROOT=Path(__file__).parent
DATA=Path(os.environ.get('REFLOW_DATA',str(ROOT/'data')))
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'reflow.sqlite3'
def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def init():
 with db() as c:c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','customer')),business TEXT NOT NULL,sector TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),csrf TEXT,expires REAL);
 CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER,until REAL);
 CREATE TABLE IF NOT EXISTS datasets(id INTEGER PRIMARY KEY,owner INTEGER REFERENCES users(id),name TEXT,created TEXT,content TEXT);
 CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY,dataset INTEGER REFERENCES datasets(id),created TEXT,analysis TEXT,published INTEGER DEFAULT 0,note TEXT DEFAULT '');
 CREATE TABLE IF NOT EXISTS healing_runs(id INTEGER PRIMARY KEY,dataset INTEGER REFERENCES datasets(id),derived INTEGER REFERENCES datasets(id),created TEXT,result TEXT);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor INTEGER,action TEXT,target INTEGER,created TEXT);
 ''')
 with db() as c:migrate(c)
def now():return datetime.now().astimezone().isoformat(timespec='seconds')
def pw(password,salt=None):
 salt=salt or secrets.token_hex(16)
 return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
def valid_pw(stored,entered):return hmac.compare_digest(stored,pw(entered,stored.split(':')[0]))
def audit(c,u,action,target):c.execute('INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)',(u,action,target,now()))
def parse_file(text,name):
 if name.lower().endswith('.json'):
  rows=json.loads(text)
  if not isinstance(rows,list) or not rows or not all(isinstance(r,dict) for r in rows):raise ValueError('JSON must be a nonempty array of flat objects.')
  cols=list(dict.fromkeys(k for r in rows for k in r))
  if any(isinstance(v,(list,dict)) for r in rows for v in r.values()):raise ValueError('Nested JSON is not supported. Flatten the records first.')
  rows=[{k:'' if r.get(k) is None else str(r.get(k,'')) for k in cols} for r in rows]
 elif name.lower().endswith('.csv'):
  reader=csv.reader(io.StringIO(text.lstrip('\ufeff')));cols=next(reader,[])
  cols=[x.strip() for x in cols]
  if not cols or any(not x for x in cols) or len(set(cols))!=len(cols):raise ValueError('Use unique, nonempty column headers.')
  rows=[]
  for i,r in enumerate(reader,2):
   if not r or all(not x for x in r):continue
   if len(r)!=len(cols):raise ValueError(f'Row {i} has a different column count.')
   rows.append(dict(zip(cols,r)))
 else:raise ValueError('Use CSV or a flat JSON array.')
 if not rows or len(rows)>100000 or len(cols)>150:raise ValueError('Use 1–100,000 rows and at most 150 columns.')
 return cols,rows
def number(v):
 # Deliberately strict: locale/currency meaning is supplied by administrator.
 t=str(v).strip()
 if not re.fullmatch(r'-?\d+(?:\.\d+)?',t):return None
 n=float(t)
 return n if abs(n)<1e18 else None
ALIASES={'revenue':['revenue','sales_amount','total_sales','net_sales','sales'], 'cost':['total_cost','cost','expense','expenses','cogs'], 'category':['category','department','product_category','service'], 'date':['date','order_date','transaction_date','invoice_date']}
def profile(cols,rows):
 out=[]
 for k in cols:
  vals=[r[k] for r in rows]; non=[v for v in vals if str(v).strip()]
  out.append({'column':k,'missing':len(vals)-len(non),'numeric':sum(number(v) is not None for v in non),'nonempty':len(non)})
 norm={re.sub(r'[^a-z0-9]+','_',k.lower()).strip('_'):k for k in cols}
 mapping={role:next((norm[a] for a in aa if a in norm),'') for role,aa in ALIASES.items()}
 duplicates=len(rows)-len({tuple(r[k] for k in cols) for r in rows})
 return {'rows':len(rows),'columns':cols,'profile':out,'duplicate_candidates':duplicates,'suggested_mapping':mapping,'sample':rows[:8]}
def analyse(cols,rows,m,currency):
 if not isinstance(m,dict) or any(k not in ALIASES for k in m):raise ValueError('Invalid mapping.')
 if any(v and v not in cols for v in m.values()):raise ValueError('Mapped column does not exist.')
 if m.get('revenue') and m.get('revenue')==m.get('cost'):raise ValueError('Revenue and cost must be different columns.')
 def value(r,key):return number(r[m[key]]) if m.get(key) else None
 rev=[value(r,'revenue') for r in rows];cost=[value(r,'cost') for r in rows]
 pairs=[(a,b) for a,b in zip(rev,cost) if a is not None and b is not None]
 rv=[v for v in rev if v is not None];cv=[v for v in cost if v is not None]
 paired_revenue=sum(a for a,b in pairs);profit=sum(a-b for a,b in pairs) if pairs else None
 groups={};months={};date_bad=0
 for r,a in zip(rows,rev):
  if a is None:continue
  if m.get('category'):
   key=r[m['category']].strip() or '(missing category)';groups[key]=groups.get(key,0)+a
  if m.get('date'):
   try:key=datetime.fromisoformat(r[m['date']].strip().replace('Z','+00:00')).strftime('%Y-%m');months[key]=months.get(key,0)+a
   except ValueError:date_bad+=1
 p=profile(cols,rows);notes=[]
 if not rv:notes.append('Revenue unavailable. Map a row-level revenue column; product prices alone do not measure sales.')
 if not pairs:notes.append('Profit unavailable. Supply comparable revenue and total cost per record.')
 elif len(pairs)<len(rows):notes.append(f'Profit covers only {len(pairs)} of {len(rows)} records. Review missing or invalid revenue and cost values.')
 if pairs and profit<0:notes.append('Recorded costs exceed revenue on comparable rows. Review cost allocation, loss-making items, and pricing before making changes.')
 if p['duplicate_candidates']:notes.append('Inspect exact duplicate candidates before interpreting totals; legitimate repeated transactions must not be removed automatically.')
 if any(x['missing'] for x in p['profile']):notes.append('Review incomplete fields with the data owner. Missing values have not been guessed or filled.')
 if groups:notes.append('Use the category revenue chart to prioritize investigation. Revenue alone does not show category profitability or customer demand.')
 notes.append('Recommendations are rule-based observations from uploaded records, not live market forecasts or guaranteed profit improvements.')
 return {'profile':p,'mapping':m,'currency':currency,'revenue':sum(rv) if rv else None,'cost':sum(cv) if cv else None,'profit':profit,'margin':profit/paired_revenue*100 if pairs and paired_revenue>0 else None,'revenue_rows':len(rv),'cost_rows':len(cv),'paired_rows':len(pairs),'invalid_dates':date_bad,'categories':sorted(groups.items(),key=lambda x:x[1],reverse=True)[:15],'months':sorted(months.items()),'recommendations':notes}

def save_automatic(c,actor,dataset,owner,name,cols,rows):
 result,clean=automatic(cols,rows)
 derived=c.execute('INSERT INTO datasets(owner,name,created,content) VALUES(?,?,?,?)',(owner,'healed_'+name,now(),json.dumps({'cols':cols,'rows':clean}))).lastrowid
 rid=c.execute('INSERT INTO healing_runs(dataset,derived,created,result) VALUES(?,?,?,?)',(dataset,derived,now(),json.dumps(result))).lastrowid
 audit(c,actor,'automatic_analysis',rid)
 report=build_report(result,cols,clean);report['source_run']=rid
 c.execute('INSERT INTO reports(dataset,created,analysis) VALUES(?,?,?)',(dataset,now(),json.dumps(report)))
 return rid

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def send(self,obj,status=200):
  raw=json.dumps(obj,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
 def user(self,c):
  cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));t=cookie.get('reflow_session');token=t.value if t else ''
  return c.execute('SELECT u.*,s.csrf,s.token FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
 def do_GET(self):self.run('GET')
 def do_POST(self):self.run('POST')
 def run(self,method):
  try:self.dispatch(method)
  except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:self.send({'error':str(e)},400)
  except Exception:self.send({'error':'Server error. Please retry or inspect the local database setup.'},500)
 def dispatch(self,method):
  path=urlparse(self.path).path
  if method=='GET' and path in ['/','/app.js','/business.js','/style.css','/admin-banner.svg','/shop-banner.svg']:
   f=ROOT/'static'/({'/':'index.html'}.get(path,path[1:]));raw=f.read_bytes();self.send_response(200);self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css','svg':'image/svg+xml'}[f.suffix[1:]]);self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'");self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw);return
  with db() as c:
   u=self.user(c);body={}
   if method=='POST':
    origin=self.headers.get('Origin');host=self.headers.get('Host')
    if origin and urlparse(origin).netloc!=host:return self.send({'error':'Cross-origin request rejected.'},403)
    length=int(self.headers.get('Content-Length','0'))
    if length>12*1024*1024:return self.send({'error':'Upload limit: 12 MB request.'},413)
    body=json.loads(self.rfile.read(length) or b'{}')
    if not isinstance(body,dict):raise ValueError('Expected an object.')
    if path not in ['/api/login','/api/register']:
     if not u:return self.send({'error':'Please log in.'},401)
     if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),u['csrf']):return self.send({'error':'Session verification failed. Refresh the page.'},403)
   if path=='/api/register' and method=='POST':
    email=str(body.get('email','')).strip().lower();password=str(body.get('password',''));business=str(body.get('business','')).strip();sector=str(body.get('sector','General'))[:80]
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>200 or len(password)<12 or len(password)>200 or not 1<=len(business)<=120:raise ValueError('Enter a valid email, business name, and a password of 12–200 characters.')
    try:c.execute('INSERT INTO users(email,password,role,business,sector) VALUES(?,?,?,?,?)',(email,pw(password),'customer',business,sector))
    except sqlite3.IntegrityError:return self.send({'error':'An account already exists for this email. Log in instead.'},409)
    self.send({'ok':True});return
   if path=='/api/login' and method=='POST':
    key=self.client_address[0]+':'+str(body.get('email','')).lower();attempt=c.execute('SELECT * FROM attempts WHERE key=?',(key,)).fetchone()
    if attempt and attempt['count']>=8 and attempt['until']>time.time():return self.send({'error':'Too many attempts. Try again in 15 minutes.'},429)
    account=c.execute('SELECT * FROM users WHERE email=?',(str(body.get('email','')).strip().lower(),)).fetchone()
    if not account or not account['active'] or not valid_pw(account['password'],str(body.get('password',''))):
     count=attempt['count']+1 if attempt and attempt['until']>time.time() else 1;c.execute('INSERT OR REPLACE INTO attempts VALUES(?,?,?)',(key,count,time.time()+900));self.send({'error':'Invalid email or password.'},401);return
    c.execute('DELETE FROM attempts WHERE key=?',(key,));token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
    if u:c.execute('DELETE FROM sessions WHERE token=?',(u['token'],))
    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account['id'],csrf,time.time()+28800));audit(c,account['id'],'login',account['id'])
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Set-Cookie',f'reflow_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'+('; Secure' if os.environ.get('REFLOW_HTTPS')=='1' else ''));self.end_headers();self.wfile.write(b'{"ok":true}');return
   if not u:return self.send({'error':'Please log in.'},401)
   admin=u['role']=='admin'
   if business_handle(self,c,u,admin,path,method,body,(now,audit,pw,valid_pw)):return
   if path=='/api/me':return self.send({'id':u['id'],'role':u['role'],'email':u['email'],'business':u['business'],'csrf':u['csrf']})
   if path=='/api/logout' and method=='POST':c.execute('DELETE FROM sessions WHERE token=?',(u['token'],));return self.send({'ok':True})
   if path=='/api/businesses':
    rows=c.execute("SELECT id,business,sector,email,active FROM users WHERE role='customer'"+('' if admin else ' AND id=?'),() if admin else (u['id'],)).fetchall();return self.send([dict(r) for r in rows])
   if path=='/api/datasets' and method=='POST':
    owner=int(body.get('owner',u['id'])) if admin else u['id']
    if not c.execute("SELECT id FROM users WHERE id=? AND role='customer'",(owner,)).fetchone():raise ValueError('Select a customer business.')
    name=str(body['name'])[:200];text=str(body['content']);cols,rows=parse_file(text,name)
    cur=c.execute('INSERT INTO datasets(owner,name,created,content) VALUES(?,?,?,?)',(owner,name,now(),json.dumps({'cols':cols,'rows':rows})));did=cur.lastrowid;audit(c,u['id'],'upload',did)
    rid=save_automatic(c,u['id'],did,owner,name,cols,rows)
    return self.send({'id':did,'automatic_analysis':'completed',**({'run_id':rid,'report_id':c.execute('SELECT id FROM reports WHERE dataset=? ORDER BY id DESC',(did,)).fetchone()['id']} if admin else {})})
   if path=='/api/datasets':
    rows=c.execute('SELECT d.id,d.name,d.owner,d.created,u.business FROM datasets d JOIN users u ON u.id=d.owner'+('' if admin else ' WHERE d.owner=?')+' ORDER BY d.id DESC',() if admin else (u['id'],)).fetchall();return self.send([dict(r) for r in rows])
   if path.startswith('/api/healing'):
    if not admin:return self.send({'error':'Administrator access required.'},403)
    if path=='/api/healing/config' and method=='GET':return self.send({'configured':bool(os.environ.get('GEMINI_API_KEY') and os.environ.get('GEMINI_MODEL')),'model':os.environ.get('GEMINI_MODEL','')})
    if path=='/api/healing' and method=='GET':
     rs=c.execute('SELECT h.*,d.name,u.business FROM healing_runs h JOIN datasets d ON d.id=h.dataset JOIN users u ON u.id=d.owner ORDER BY h.id DESC').fetchall()
     return self.send([{**dict(r),'result':json.loads(r['result'])} for r in rs])
    if path=='/api/healing/auto' and method=='POST':
     ds=c.execute('SELECT * FROM datasets WHERE id=?',(int(body['dataset']),)).fetchone()
     if not ds:return self.send({'error':'Dataset not found.'},404)
     prior=c.execute('SELECT id,result FROM healing_runs WHERE dataset=? ORDER BY id DESC',(ds['id'],)).fetchall()
     for r in prior:
      if json.loads(r['result']).get('mode')=='automatic':return self.send({'id':r['id'],'reused':True})
     data=json.loads(ds['content']);rid=save_automatic(c,u['id'],ds['id'],ds['owner'],ds['name'],data['cols'],data['rows'])
     return self.send({'id':rid,'reused':False})
    if path=='/api/healing/run' and method=='POST':
     ds=c.execute('SELECT * FROM datasets WHERE id=?',(int(body['dataset']),)).fetchone()
     if not ds:return self.send({'error':'Dataset not found.'},404)
     data=json.loads(ds['content']);result,clean=run_pipeline(data['cols'],data['rows'],body.get('policy',{}));result['charts']=describe(data['cols'],clean);result['mode']='manual'
     derived=c.execute('INSERT INTO datasets(owner,name,created,content) VALUES(?,?,?,?)',(ds['owner'],'healed_'+ds['name'],now(),json.dumps({'cols':data['cols'],'rows':clean}))).lastrowid
     rid=c.execute('INSERT INTO healing_runs(dataset,derived,created,result) VALUES(?,?,?,?)',(ds['id'],derived,now(),json.dumps(result))).lastrowid
     audit(c,u['id'],'self_healing',rid)
     return self.send({'id':rid,'derived':derived,'result':result})
    hm=re.fullmatch(r'/api/healing/(\d+)/(ai|download)',path)
    if hm:
     run=c.execute('SELECT * FROM healing_runs WHERE id=?',(int(hm[1]),)).fetchone()
     if not run:return self.send({'error':'Run not found.'},404)
     if hm[2]=='download' and method=='GET':
      ds=c.execute('SELECT content FROM datasets WHERE id=?',(run['derived'],)).fetchone()
      return self.send(json.loads(ds['content']))
     if hm[2]=='ai' and method=='POST':
      if body.get('consent') is not True:raise ValueError('Confirm sending aggregate quality counts to Gemini.')
      result=json.loads(run['result']);result['ai']=gemini_summary(result)
      c.execute('UPDATE healing_runs SET result=? WHERE id=?',(json.dumps(result),run['id']));audit(c,u['id'],'ai_analysis',run['id'])
      return self.send(result['ai'])
    return self.send({'error':'Not found.'},404)
   match=re.fullmatch(r'/api/datasets/(\d+)(/analyse)?',path)
   if match:
    ds=c.execute('SELECT * FROM datasets WHERE id=?',(int(match[1]),)).fetchone()
    if not ds or (not admin and ds['owner']!=u['id']):return self.send({'error':'Dataset not found.'},404)
    data=json.loads(ds['content'])
    if match[2]:
     if method!='POST' or not admin:return self.send({'error':'Administrator access required.'},403)
     if not body.get('confirmed'):raise ValueError('Confirm row-level amounts, period, currency, and cost meaning.')
     currency=str(body.get('currency','')).strip().upper()
     if not re.fullmatch('[A-Z]{3}',currency):raise ValueError('Enter a three-letter currency code, for example INR.')
     result=analyse(data['cols'],data['rows'],body.get('mapping',{}),currency)
     cur=c.execute('INSERT INTO reports(dataset,created,analysis) VALUES(?,?,?)',(ds['id'],now(),json.dumps(result)));audit(c,u['id'],'analyse',ds['id']);return self.send({'id':cur.lastrowid,'analysis':result})
    return self.send(profile(data['cols'],data['rows']))
   if path=='/api/reports/auto' and method=='POST':
    if not admin:return self.send({'error':'Administrator access required.'},403)
    ds=c.execute('SELECT * FROM datasets WHERE id=?',(int(body['dataset']),)).fetchone()
    if not ds:return self.send({'error':'Dataset not found.'},404)
    for r in c.execute('SELECT id,analysis FROM reports WHERE dataset=? ORDER BY id DESC',(ds['id'],)).fetchall():
     if json.loads(r['analysis']).get('kind')=='automatic_graph_report':return self.send({'id':r['id']})
    runs=c.execute('SELECT * FROM healing_runs WHERE dataset=? ORDER BY id DESC',(ds['id'],)).fetchall()
    if runs:
     run=runs[0];derived=c.execute('SELECT content FROM datasets WHERE id=?',(run['derived'],)).fetchone();data=json.loads(derived['content'])
     result=json.loads(run['result']);report=build_report(result,data['cols'],data['rows']);report['source_run']=run['id']
     rid=c.execute('INSERT INTO reports(dataset,created,analysis) VALUES(?,?,?)',(ds['id'],now(),json.dumps(report))).lastrowid
    else:
     data=json.loads(ds['content']);save_automatic(c,u['id'],ds['id'],ds['owner'],ds['name'],data['cols'],data['rows'])
     rid=c.execute('SELECT id FROM reports WHERE dataset=? ORDER BY id DESC',(ds['id'],)).fetchone()['id']
    audit(c,u['id'],'automatic_report',rid);return self.send({'id':rid})
   match=re.fullmatch(r'/api/reports/(\d+)/generate',path)
   if match and method=='POST':
    if not admin:return self.send({'error':'Administrator access required.'},403)
    source=c.execute('SELECT * FROM reports WHERE id=?',(int(match[1]),)).fetchone()
    if not source:return self.send({'error':'Report not found.'},404)
    analysis=json.loads(source['analysis'])
    if analysis.get('kind')!='automatic_graph_report':raise ValueError('Select an automatic graph report or generate one from the dataset.')
    requirements=body.get('requirements',DEFAULT_REQUIREMENTS)
    if not isinstance(requirements,str) or not 1<=len(requirements.strip())<=2000:raise ValueError('Enter requirements using 1–2,000 characters.')
    use_ai=body.get('use_ai') is True
    if use_ai and body.get('consent') is not True:raise ValueError('Confirm sending report requirements and aggregate chart data to Gemini.')
    result=generate_report(analysis,requirements.strip(),use_ai,body.get('chart_ids'))
    rid=c.execute('INSERT INTO reports(dataset,created,analysis,note) VALUES(?,?,?,?)',(source['dataset'],now(),json.dumps(result),source['note'])).lastrowid
    audit(c,u['id'],'generate_report',rid);return self.send({'id':rid,'ai_status':(result.get('ai') or {}).get('status','local')})
   if path=='/api/reports':
    rows=c.execute('SELECT r.id,r.dataset,r.created,r.analysis,r.published,r.note,d.name,u.business FROM reports r JOIN datasets d ON d.id=r.dataset JOIN users u ON u.id=d.owner'+('' if admin else ' WHERE d.owner=? AND r.published=1')+' ORDER BY r.id DESC',() if admin else (u['id'],)).fetchall();return self.send([{**dict(r),'analysis':json.loads(r['analysis'])} for r in rows])
   match=re.fullmatch(r'/api/reports/(\d+)/publish',path)
   if match and method=='POST':
    if not admin:return self.send({'error':'Administrator access required.'},403)
    if not c.execute('SELECT id FROM reports WHERE id=?',(int(match[1]),)).fetchone():return self.send({'error':'Report not found.'},404)
    c.execute('UPDATE reports SET published=?,note=? WHERE id=?',(1 if body.get('published') else 0,str(body.get('note',''))[:5000],int(match[1])));audit(c,u['id'],'publish' if body.get('published') else 'unpublish',int(match[1]));return self.send({'ok':True})
   return self.send({'error':'Not found.'},404)

if __name__=='__main__':
 init();parser=argparse.ArgumentParser();parser.add_argument('--create-admin',action='store_true');parser.add_argument('--port',type=int,default=8502);args=parser.parse_args()
 if args.create_admin:
  import getpass
  email=input('Admin email: ').strip().lower();password=getpass.getpass('Password (12+ characters): ')
  if len(password)<12 or '@' not in email:raise SystemExit('Valid email and 12+ character password required.')
  with db() as c:c.execute('INSERT INTO users(email,password,role,business,sector) VALUES(?,?,?,?,?)',(email,pw(password),'admin','Administration','All sectors'))
  print('Admin created. Run python app.py to start.')
 else:
  server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
  print(f'ReFlow: http://127.0.0.1:{args.port}')
  try:server.serve_forever()
  except KeyboardInterrupt:print('ReFlow stopped.')
  finally:server.server_close()
