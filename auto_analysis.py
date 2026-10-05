"""Schema inference and descriptive graphs. No external calls or invented values."""
from collections import Counter
import re
from healing import run_pipeline, date_value

def number(value):
    value=str(value).strip()
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',value):return None
    n=float(value)
    return n if abs(n)<1e18 else None

def infer(cols,rows):
    numeric=[];dates=[];columns=[];warnings=[]
    for k in cols:
        norm=re.sub('[^a-z0-9]+','_',k.lower()).strip('_')
        vals=[r[k].strip() for r in rows if r[k].strip()]
        identifier=bool(re.search(r'(^|_)(id|code|phone|mobile|zip|postal|pin|account|sku)($|_)',norm))
        count=sum(number(v) is not None for v in vals)
        numeric_hint=bool(re.search(r'(^|_)(revenue|sales|amount|cost|expense|expenses|cogs|price|quantity|qty|salary|age|score|rating|stock|weight|temperature)($|_)',norm))
        date_hint=bool(re.search(r'(^|_)(date|timestamp|datetime)($|_)',norm))
        kind='identifier' if identifier else 'text';reason='Identifier-like column name; excluded from numeric inference.' if identifier else 'Insufficient evidence for numeric or date interpretation.'
        if not identifier and (date_hint or (vals and sum(date_value(v,'iso') is not None for v in vals)/len(vals)>=.9)):
            kind='date';mode='iso';reason='Date-like name or at least 90% ISO-compatible nonblank values.'
            slash=[v for v in vals if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}',v)]
            if slash:
                dmy=any(int(v.split('/')[0])>12 and int(v.split('/')[1])<=12 for v in slash)
                mdy=any(int(v.split('/')[1])>12 and int(v.split('/')[0])<=12 for v in slash)
                # Only normalize a single consistent, evidenced format. Mixed ISO/slash stays manual.
                nonslash_dates=any(date_value(v,'iso') is not None for v in vals)
                if dmy!=mdy and not nonslash_dates:mode='dmy' if dmy else 'mdy'
                else:mode='review';warnings.append(f'{k}: ambiguous or mixed date format; choose its format in manual settings. No dates automatically changed.')
            dates.append({'column':k,'format':mode})
        elif not identifier and (numeric_hint or (vals and count/len(vals)>=.8)):
            kind='numeric';numeric.append(k);reason='Numeric column-name hint.' if numeric_hint else 'At least 80% of nonblank values use plain decimal notation.'
        elif vals and len(set(vals))<=min(30,max(2,len(vals)//2)):kind='category';reason='Repeated labels with limited distinct values.'
        columns.append({'column':k,'type':kind,'reason':reason,'nonempty':len(vals),'missing':len(rows)-len(vals),'numeric_values':count,'completeness':round(100*len(vals)/len(rows),2)})
    if len(dates)>1:warnings.append('Multiple date columns detected. Automatic repair validates/normalizes only the first unambiguous date column; other fields remain profiled for review.')
    return {'numeric':numeric,'dates':dates,'columns':columns,'warnings':warnings}

def describe(cols,rows,schema=None):
    schema=schema or infer(cols,rows);histograms=[];categories=[];trends=[]
    for col in schema['columns']:
        k=col['column'];vals=[r[k].strip() for r in rows if r[k].strip()]
        if col['type']=='numeric' and len(histograms)<6:
            nums=[n for v in vals if (n:=number(v)) is not None]
            if nums:
                lo,hi=min(nums),max(nums);counts=[0]*8 if hi>lo else [len(nums)]
                edges=[lo+(hi-lo)*i/8 for i in range(9)] if hi>lo else [lo,hi]
                if hi>lo:
                    for n in nums:counts[min(7,int((n-lo)/(hi-lo)*8))]+=1
                histograms.append({'column':k,'valid':len(nums),'invalid':len(vals)-len(nums),'min':lo,'max':hi,'mean':sum(nums)/len(nums),'edges':edges,'counts':counts})
        if col['type']=='category' and len(categories)<3:
            counts=Counter(vals);top=counts.most_common(12)
            categories.append({'column':k,'values':top,'other':sum(counts.values())-sum(n for _,n in top),'nonempty':len(vals)})
    for spec in schema['dates'][:3]:
        if spec['format']=='review':continue
        counts=Counter();invalid=0
        for r in rows:
            v=r[spec['column']].strip()
            if not v:continue
            parsed=date_value(v,spec['format'])
            if parsed:counts[parsed[:7]]+=1
            else:invalid+=1
        if counts:trends.append({'column':spec['column'],'values':sorted(counts.items())[-36:],'omitted_months':max(0,len(counts)-36),'invalid':invalid})
    return {'columns':schema['columns'],'histograms':histograms,'categories':categories,'trends':trends,'warnings':schema['warnings'],
            'limits':'All rows profiled. Charts show up to 6 numeric fields, 3 categorical fields (top 12 labels) and 3 date fields (latest 36 months). Counts describe uploaded records, not market demand.'}

def automatic(cols,rows):
    schema=infer(cols,rows)
    date=next((d for d in schema['dates'] if d['format']!='review'),None)
    policy={'numeric':schema['numeric'],'date':date['column'] if date else '', 'date_format':date['format'] if date else 'iso','trim':True}
    result,clean=run_pipeline(cols,rows,policy)
    result['mode']='automatic';result['inference']=schema
    result['charts']=describe(cols,clean)
    # Do not claim successful validation when inference left date semantics unresolved.
    if schema['warnings']:
        result['status']='needs_review'
        result['stages'][3].update(status='needs_review',detail='Review schema inference warnings as well as unresolved quality checks.')
    result['stages'].insert(0,{'agent':'Schema detector','status':'completed','detail':f"Inferred {len(schema['numeric'])} numeric and {len(schema['dates'])} date fields. Inference is provisional."})
    result['stages'].insert(-1,{'agent':'Graph analyst','status':'completed','detail':'Computed completeness, distributions, category counts and available date trends from uploaded records.'})
    result['findings']=[f"Analyzed {len(rows)} rows and {len(cols)} columns automatically.",f"Applied {sum(result['actions'].values())} formatting repairs; all rows retained.",f"{result['after']['missing_cells']} missing cells and {result['after']['duplicate_candidates']} exact duplicate candidates remain."]+schema['warnings']
    result['explanation']='Automatic local rule-based agents computed these graphs. Gemini is optional for a separate AI-written explanation. Financial interpretation still requires confirmed revenue/cost mappings.'
    return result,clean
