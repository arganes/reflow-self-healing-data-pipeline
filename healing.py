"""Local deterministic repair agents plus optional, advisory Gemini analysis."""
import json, os, re, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

def load_env():
    p=Path(__file__).parent/'.env'
    if p.exists():
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1); k=k.strip()
                if k in ('GEMINI_API_KEY','GEMINI_MODEL'): os.environ.setdefault(k,v.strip().strip('"\''))
load_env()

def date_value(v,mode):
    if not v.strip(): return None
    try:
        if mode=='iso': return datetime.fromisoformat(v.strip().replace('Z','+00:00')).date().isoformat()
        return datetime.strptime(v.strip(),'%d/%m/%Y' if mode=='dmy' else '%m/%d/%Y').date().isoformat()
    except ValueError: return None

def number(value):
    value=str(value).strip()
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',value):return None
    n=float(value)
    return n if abs(n)<1e18 else None

def metrics(cols,rows,numeric,date,mode):
    missing=sum(not r[k].strip() for r in rows for k in cols)
    whitespace=sum(r[k]!=r[k].strip() for r in rows for k in cols)
    invalid_numeric=sum(bool(r[k].strip()) and number(r[k]) is None for r in rows for k in numeric)
    invalid_dates=sum(bool(r[date].strip()) and date_value(r[date],mode) is None for r in rows) if date else 0
    duplicates=len(rows)-len({tuple(r[k] for k in cols) for r in rows})
    checks=len(rows)*(len(cols)*2+len(numeric)+(1 if date else 0))+len(rows)
    issues=missing+whitespace+invalid_numeric+invalid_dates+duplicates
    return dict(rows=len(rows),missing_cells=missing,whitespace_cells=whitespace,invalid_numeric=invalid_numeric,invalid_dates=invalid_dates,duplicate_candidates=duplicates,score=round(100*(1-issues/checks),2))

def run_pipeline(cols,rows,policy):
    if not isinstance(policy,dict): raise ValueError('Invalid repair policy.')
    numeric=policy.get('numeric',[]);date=policy.get('date','');mode=policy.get('date_format','iso')
    if not isinstance(numeric,list) or len(set(numeric))!=len(numeric) or any(k not in cols for k in numeric):raise ValueError('Select valid numeric columns.')
    if date and (date not in cols or date in numeric):raise ValueError('Date column must be valid and separate from numeric fields.')
    if mode not in ('iso','dmy','mdy'):raise ValueError('Select a supported date format.')
    before=metrics(cols,rows,numeric,date,mode);clean=[];events=[];counts={}
    def event(row,column,action):
        counts[action]=counts.get(action,0)+1
        if len(events)<500:events.append(dict(row=row,column=column,action=action))
    for i,row in enumerate(rows,1):
        r=dict(row)
        if policy.get('trim',True):
            for k in cols:
                if r[k]!=r[k].strip(): r[k]=r[k].strip();event(i,k,'Trimmed outer whitespace')
        # Strict decimal notation only; preserve original precision and leading zero identifiers.
        if date and mode!='iso' and date_value(r[date],mode):
            r[date]=date_value(r[date],mode);event(i,date,'Normalized confirmed date format')
        clean.append(r)
    after=metrics(cols,clean,numeric,date,'iso' if date and mode!='iso' else mode)
    remaining=after['missing_cells']+after['invalid_numeric']+after['invalid_dates']+after['duplicate_candidates']+after['whitespace_cells']
    status='needs_review' if remaining else 'validated'
    return dict(before=before,after=after,status=status,policy=policy,actions=counts,incidents=events,incidents_truncated=sum(counts.values())>len(events),
        stages=[{'agent':'Monitor','status':'completed','detail':'Profiled every row against selected checks.'},
                {'agent':'Repair planner','status':'completed','detail':'Selected only administrator-authorized formatting repairs.'},
                {'agent':'Healing executor','status':'completed','detail':f'{sum(counts.values())} formatting repairs; no records dropped or values imputed.'},
                {'agent':'Validation','status':status,'detail':'Missing values, duplicate candidates and invalid values require human review.' if remaining else 'All selected checks passed.'},
                {'agent':'Version store','status':'completed','detail':'Saved a derived dataset; original upload retained.'}],
        explanation='Local rule-based analysis. Enable Gemini for an additional AI explanation. Repairs are deterministic; the LLM cannot execute code or modify data.'),clean

def gemini_summary(result):
    evidence={k:result[k] for k in ('before','after','status','actions')}
    prompt='You are ReFlow data quality analyst. Explain the supplied aggregate evidence in plain English under headings: Findings, Likely causes (hypotheses), Recovery performed, Unresolved issues, Next steps. Do not invent columns, financial values, market data or successful repairs. Scores measure selected checks only. No profit guarantees. Data: '+json.dumps(evidence)
    return gemini_prompt(prompt)

def gemini_prompt(prompt):
    key=os.environ.get('GEMINI_API_KEY','');model=os.environ.get('GEMINI_MODEL','')
    if not key or not model:return {'status':'unavailable','text':'Set GEMINI_API_KEY and GEMINI_MODEL in .env, then restart. Local reports remain available.','attempts':0}
    if not re.fullmatch(r'[A-Za-z0-9._-]+',model):return {'status':'unavailable','text':'Use a bare Gemini model ID in .env.','attempts':0}
    payload=json.dumps({'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'maxOutputTokens':4096}}).encode()
    req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',data=payload,headers={'Content-Type':'application/json','x-goog-api-key':key})
    for attempt in range(1,4):
        try:
            with urllib.request.urlopen(req,timeout=20) as response:data=json.load(response)
            text='\n'.join(p.get('text','') for c in data.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if not p.get('thought'))
            if not text: return {'status':'unavailable','text':'Gemini returned no explanation. Local results are preserved.','attempts':attempt}
            return {'status':'generated','text':text,'attempts':attempt,'model':model}
        except urllib.error.HTTPError as exc:
            transient=exc.code in (429,500,502,503,504)
            message={400:'Check the configured model and request support.',401:'Check your API key.',403:'Check API key permissions.',404:'Model unavailable. Choose a model ID available to your API key.',429:'Quota or rate limit reached.'}.get(exc.code,'Gemini service unavailable.')
        except (urllib.error.URLError,TimeoutError,OSError):transient=True;message='Network connection failed or timed out.'
        except (ValueError,TypeError,KeyError):transient=False;message='Unexpected Gemini response.'
        if not transient or attempt==3:return {'status':'unavailable','text':message+' Local results are preserved; retry AI explanation later.','attempts':attempt}
        time.sleep(attempt)
