"""Reproduce preliminary descriptive results from saved semantic agent annotations.

No API calls, no keyword-based semantic labels, no human-validation claim.
"""
from pathlib import Path
import sys, json, csv, re, hashlib, collections, math, argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.deps'))
import numpy as np
import pandas as pd

REQUIRED='id r why t l s g m b a f role ph rd cl d db ex q an di obj flags ev'.split()
ARRAYS={'t':{'spo','he','admission','work','access','policy','quality','status','experience','other'},
        'l':{'auth','rat','moral','narr'},'m':{'cool','warm','route','info'},
        'b':{'score','cost','rules','geography','quality','other'},
        'a':{'spo','he','program','org','funding','timing'},
        'role':{'parent','applicant','student','graduate','educator','other'},
        'db':{'work','income','skills','inflation','quality','cost','status','other'},
        'ex':{'self','others','hypothetical'},'obj':{'procedure','access','quality','status','other'},
        'flags':{'consolation','recognition','reversibility','access_promise','job_guarantee','quoted_actor','genre_ad','ambiguous'}}
ENUM={'g':{'lower','same','raise','mixed','unknown','na'},'ph':{'yes','no','unknown'},
      'rd':{'dominant','negotiated','oppositional','unlinked'},'q':{'barrier','procedure','mixed','unknown','na'}}
DEFAULT={'t':[],'l':[],'s':['n','n'],'g':'na','m':[],'b':[],'a':[],'f':0,'role':[],
         'ph':'unknown','rd':'unlinked','cl':'','d':0,'db':[],'ex':[],'q':'na','an':0,'di':0,'obj':[],'flags':[],'ev':''}
PUBLIC_DEFAULT={k:v for k,v in DEFAULT.items() if k not in {'cl','ev'}}
GROUPS=['telegram_post','pikabu_post','pikabu_comment','tabiturient_question','tabiturient_answer']
GLABEL={'telegram_post':'Telegram\nпосты','pikabu_post':'Пикабу\nпосты','pikabu_comment':'Пикабу\nкомментарии',
        'tabiturient_question':'Табитуриент\nвопросы','tabiturient_answer':'Табитуриент\nответы'}
LLABEL={'auth':'Авторитет и нормы','rat':'Практическая польза','moral':'Моральная ценность','narr':'Истории успеха и неудачи'}
MLABEL={'cool':'Строгое охлаждение','warm':'Поддержка ожиданий','route':'Смена пути при сохранении цели','info':'Информирование'}
DBLABEL={'work':'Трудоустройство','income':'Доход','skills':'Навыки и знания','inflation':'Инфляция дипломов','quality':'Качество обучения','cost':'Затраты','status':'Статус','other':'Другое'}
PLABEL={'P1':'До 11.03.2020','P2':'11.03.2020–23.02.2022','P3':'24.02.2022–2023','P4':'2024–06.10.2026'}

def dump(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda v: bool(v) if isinstance(v,np.bool_) else int(v) if isinstance(v,np.integer) else float(v) if isinstance(v,np.floating) else None),encoding='utf-8')

def read_jsonl(files,add_file=True):
    rows=[]
    for p in sorted(files):
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                r=json.loads(line)
                if add_file:r['_file']=p.name
                rows.append(r)
    return rows

def norm(s): return re.sub(r'\s+',' ',s).strip().lower().replace('ё','е')

def validate(rows,meta,public_mode=False):
    errors=[];warnings=[]; ids=[r.get('id') for r in rows]
    required=([k for k in REQUIRED if k not in {'why','cl','ev'}] if public_mode else REQUIRED)
    for k,n in collections.Counter(ids).items():
        if n>1: errors.append(f'duplicate id {k} x{n}')
    lookup={x['id']:x for x in meta}
    for r in rows:
        sid=r.get('id')
        if sid not in lookup: errors.append(f'unknown id {sid}');continue
        if r.get('r') not in [0,1,None]:errors.append(f'{sid}: r domain')
        if r.get('r')!=1:continue
        for k in required:
            if k not in r:errors.append(f'{sid}: missing {k}')
        for k,domain in ARRAYS.items():
            if not isinstance(r.get(k),list) or any(v not in domain for v in r.get(k,[])):errors.append(f'{sid}: {k} domain {r.get(k)}')
        for k,domain in ENUM.items():
            if r.get(k) not in domain:errors.append(f'{sid}: {k} domain {r.get(k)}')
        if not isinstance(r.get('s'),list) or len(r['s'])!=2 or any(v not in {'+','-','m','0','n','?'} for v in r['s']):errors.append(f'{sid}: s domain')
        for k in ['f','an']:
            if r.get(k) not in [0,1]:errors.append(f'{sid}: {k} domain')
        if r.get('d') not in [0,1,None]:errors.append(f'{sid}: d domain')
        if r.get('di') not in [0,1,2,None]:errors.append(f'{sid}: di domain')
        if r.get('d')!=1 and r.get('db'):errors.append(f'{sid}: db without d')
        if not public_mode and r.get('rd','unlinked')!='unlinked' and not r.get('cl'):errors.append(f'{sid}: reading without claim')
        if lookup[sid]['row_type']!='question' and r.get('q')!='na':errors.append(f'{sid}: q on non-question')
        if 'cool' in r.get('m',[]) and (r.get('g') not in ['lower','mixed'] or not r.get('b')):warnings.append({'id':sid,'issue':'cool missing lowering/barrier'})
        if not public_mode and r.get('ev'):
            fragments=[norm(v).strip(' «»\"\'.,;:') for v in re.split(r'…|\.\.\.',r['ev']) if norm(v).strip(' «»\"\'.,;:')]
            context=' '.join(norm(m['text']) for m in meta if m['package']==lookup[sid]['package'] and m['source']==lookup[sid]['source'])
            if not fragments or any(v not in context for v in fragments):warnings.append({'id':sid,'issue':'evidence excerpt needs review against saved context'})
        if not public_mode and not r.get('ev'):warnings.append({'id':sid,'issue':'empty evidence'})
    if public_mode:warnings.append({'issue':'evidence verification unavailable; public text withheld'})
    return errors,warnings

def frame(rows,meta,public_mode=False):
    indexed={r['id']:r for r in rows}; data=[]
    for m in meta:
        if m['id'] not in indexed:continue
        if public_mode:m={k:v for k,v in m.items() if k not in {'text','content_hash'}}
        defaults=PUBLIC_DEFAULT if public_mode else DEFAULT
        a={**defaults,**indexed[m['id']]};x={**m,**a}
        x['group']=f"{m['source']}_{m['row_type']}"
        x['role_known']=int(bool(a['role']));x['family']=a['f'];x['deval']=a['d']
        x['stance_spo'],x['stance_he']=a['s']
        x['reading_known']=int(a['rd']!='unlinked')
        x['goal_known']=int(a['g'] in ['lower','same','raise','mixed'])
        x['alternative']=int(bool(a['a']))
        for key,domain in ARRAYS.items():
            for val in domain:x[f'{key}_{val}']=int(val in a[key])
        data.append(x)
    return pd.DataFrame(data)

def rate_table(df,groups,fields):
    out=[]
    for keys,g in df.groupby(groups,dropna=False,sort=False):
        keys=keys if isinstance(keys,tuple) else (keys,)
        for field in fields:
            valid=g[field].notna();n=int((g.loc[valid,field]==1).sum());N=int(valid.sum())
            out.append({**dict(zip(groups,keys)),'code':field,'n':n,'N':N,'unknown':int((~valid).sum()),'pct':100*n/N if N else np.nan})
    return pd.DataFrame(out)

def save_table(name,df): df.to_csv(ROOT/'tables'/f'{name}.csv',index=False,encoding='utf-8-sig')

def alpha(a,b,ordinal=False):
    pairs=[(x,y) for x,y in zip(a,b) if x is not None and y is not None and not (isinstance(x,float) and math.isnan(x)) and not (isinstance(y,float) and math.isnan(y))]
    n=len(pairs)
    if n==0:return None,0,None
    counts=collections.Counter(v for p in pairs for v in p);N=2*n
    if len(counts)<2:return None,n,1.0
    if ordinal:
        mid={};cum=0
        for k in sorted(counts):mid[k]=cum+counts[k]/2;cum+=counts[k]
        dist=lambda x,y:(mid[x]-mid[y])**2
    else:dist=lambda x,y:int(x!=y)
    Do=sum(dist(x,y) for x,y in pairs)/n
    De=sum(cx*cy*dist(x,y) for x,cx in counts.items() for y,cy in counts.items())/(N*(N-1))
    return 1-Do/De if De else None,n,sum(x==y for x,y in pairs)/n

def main(partial=False):
    corpus_path=ROOT/'data/corpus.json'
    public_mode=not corpus_path.exists()
    metadata_path=ROOT/'data/corpus_metadata.json' if public_mode else corpus_path
    meta=json.loads(metadata_path.read_text(encoding='utf-8'))
    files=[p for p in (ROOT/'annotations').glob('*.jsonl') if re.fullmatch(r'(telegram|pikabu|tabiturient)_\d{3}\.jsonl',p.name)]
    raw=read_jsonl(files,add_file=not public_mode);errors,warnings=validate(raw,meta,public_mode)
    missing=sorted(set(m['id'] for m in meta)-set(r['id'] for r in raw))
    status={'expected':len(meta),'annotated':len(raw),'files':len(files),'missing_ids':missing,'errors':errors,'warnings':warnings,
            'human_validation':'not_performed','status':'in_progress' if missing else 'complete_raw_annotation'}
    if public_mode:status['evidence_verification']='unavailable_public_text_withheld'
    dump(ROOT/'audit/structural_validation.json',status)
    print(json.dumps({'annotated':len(raw),'expected':len(meta),'errors':errors[:20],'warnings':len(warnings)},ensure_ascii=False))
    if partial:return
    if missing or errors:raise RuntimeError('Annotation incomplete or invalid; see structural_validation.json')
    (ROOT/'data/annotations_primary.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in raw)+'\n',encoding='utf-8')
    # Model editorial adjudication is stored separately, never overwritten into primary annotations.
    corrected={r['id']:dict(r) for r in raw}
    patchfile=ROOT/'audit/model_adjudications.json'
    if patchfile.exists():
        for p in json.loads(patchfile.read_text(encoding='utf-8')):corrected[p['id']].update(p['changes'])
    final=list(corrected.values()); errors2,_=validate(final,meta,public_mode)
    if errors2:raise RuntimeError(errors2)
    df=frame(final,meta,public_mode); baseline=frame(raw,meta,public_mode)
    if public_mode:
        # Public metadata already carries the deduplication decisions. Do not
        # attempt to reconstruct text-derived groups without the withheld text.
        df['is_exact_duplicate']=df['is_exact_duplicate'].astype(bool)
    else:
        df['duplicate_group']=df['content_hash'].where(df['content_hash']!='',df['id'])
        df['is_exact_duplicate']=df.duplicated(['source','row_type','duplicate_group'])
    # Near-copy groups for sensitivity only; never change content codes.
    if public_mode:
        # Preserve metadata flags and leave the locally generated pair table intact.
        df['is_near_duplicate']=df['is_near_duplicate'].astype(bool)
    else:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        parent=list(range(len(df)))
        def find(i):
            while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
            return i
        def union(i,j):
            a,b=find(i),find(j)
            if a!=b:parent[max(a,b)]=min(a,b)
        near=[]
        for _,idx in df.groupby(['source','row_type']).groups.items():
            indices=list(idx)
            if len(indices)<2:continue
            texts=df.loc[indices,'text'].fillna('').map(norm)
            if not any(texts.str.len()>100):continue
            X=TfidfVectorizer(analyzer='char_wb',ngram_range=(4,5),min_df=2,max_features=75000).fit_transform(texts)
            sim=cosine_similarity(X)
            for a,b in zip(*np.where(np.triu(sim,1)>=.92)):
                i,j=indices[a],indices[b]
                if min(len(texts.iloc[a]),len(texts.iloc[b]))<100:continue
                union(i,j);near.append({'id1':df.loc[i,'id'],'id2':df.loc[j,'id'],'cosine':float(sim[a,b])})
        df['near_duplicate_group']=[df.loc[find(i),'id'] for i in range(len(df))]
        df['is_near_duplicate']=df.duplicated(['source','row_type','near_duplicate_group'])
        save_table('near_duplicate_pairs',pd.DataFrame(near,columns=['id1','id2','cosine']))
    dump(ROOT/'data/annotations_final.json',final)
    df.drop(columns=['text'],errors='ignore').to_csv(ROOT/'data/annotated_metadata.csv',index=False,encoding='utf-8-sig')
    screen=[]
    for group in GROUPS:
        g=df[df.group==group]
        screen.append({'group':group,'total':len(g),'included':int((g.r==1).sum()),'excluded':int((g.r==0).sum()),'undetermined':int(g.r.isna().sum()),'missing_main_text':int((~g.has_text).sum())})
    screen=pd.DataFrame(screen);save_table('screening',screen)
    rel=df[df.r==1].copy()
    periods=df.groupby(['group','period'],observed=True).size().rename('input_n').reset_index().merge(rel.groupby(['group','period'],observed=True).size().rename('included_n').reset_index(),how='left').fillna({'included_n':0})
    save_table('coverage_periods',periods)
    allcodes=['l_'+x for x in LLABEL]+['m_'+x for x in MLABEL]+['family','role_known','reading_known','goal_known','deval','alternative']
    profiles=rate_table(rel,['group'],allcodes);save_table('profiles',profiles)
    tg=rel[rel.source=='telegram']
    save_table('vi1_official_all',rate_table(tg,['channel'],['l_'+x for x in LLABEL]+['t_spo','t_he']))
    tg_common=tg[tg.sample_windows.str.contains(r'202[2-6]-07-31',regex=True,na=False)]
    v1=rate_table(tg_common,['channel'],['l_'+x for x in LLABEL]+['t_spo','t_he']);save_table('vi1_official_common_windows',v1)
    # Common calendar interval and educational subject, keeping all document genres separate.
    cross_common=rel[(rel.period.isin(['P3','P4']))&((rel.t_spo==1)|(rel.t_he==1))]
    cross_profiles=rate_table(cross_common,['group'],['l_'+x for x in LLABEL]);save_table('vi5_common_topic_period',cross_profiles)
    # Periods are merged by preregistered availability rule, before looking at code shares.
    parent_units=rel[rel.row_type.isin(['post','question'])]
    combine={}
    for source,g in parent_units.groupby('source'):
        cnt=g.period.value_counts();combine[source]=cnt.get('P3',0)<30 or cnt.get('P4',0)<30
    rel['comparison_period']=[('P34' if p in ['P3','P4'] and combine[s] else p) for s,p in zip(rel.source,rel.period)]
    dump(ROOT/'audit/period_merging.json',{'rule':'Merge P3/P4 within corpus if either has fewer than30 eligible parent units, before code comparison','merge':combine})
    save_table('profiles_by_period',rate_table(rel,['group','comparison_period'],['l_'+x for x in LLABEL]+['deval']))
    questions=rel[rel.row_type=='question'];answers=rel[rel.row_type=='answer'].copy()
    qmap=dict(zip(questions.package,questions.q));answers['question_type']=answers.package.map(qmap).fillna('unknown')
    v2=rate_table(answers,['question_type'],['alternative']+['m_'+x for x in MLABEL]);save_table('vi2_question_answer',v2)
    save_table('vi2_goal_relation',answers.groupby('g').size().rename('n').reset_index())
    save_table('vi3_family_profiles',rate_table(rel,['group'],['family','role_known','reading_known']))
    selfdesc=rel[rel.role_known==1]
    save_table('vi3_role_stance',selfdesc.explode('role').groupby(['group','role','ph','stance_spo','stance_he','rd']).size().rename('n').reset_index())
    deval=rel[rel.deval==1]
    save_table('vi4_devaluation_bases',rate_table(deval,['group'],['db_'+x for x in DBLABEL]))
    # Selection sensitivity retains denominator and abstentions for every group/code.
    variants={'base':rel,'unique_exact':rel[~rel.is_exact_duplicate],'unique_near':rel[~rel.is_near_duplicate],
              'without_purposive_tabiturient':rel[(rel.source!='tabiturient')|(~rel.selection_method.str.contains('purposive',case=False,na=False))],
              'telegram_july_only':rel[(rel.source!='telegram')|(~rel.sample_windows.str.contains('10-06|oct|окт',case=False,na=False))],
              'without_ambiguous':rel[rel.flags_ambiguous==0]}
    sense=[]
    for name,v in variants.items():
        tab=rate_table(v,['group'],allcodes);tab['variant']=name;sense.append(tab)
    sensitivity=pd.concat(sense,ignore_index=True);save_table('sensitivity',sensitivity)
    before=rate_table(baseline[baseline.r==1],['group'],allcodes);before['variant']='primary_unadjudicated'
    save_table('adjudication_sensitivity',pd.concat([before,sensitivity[sensitivity.variant=='base']],ignore_index=True))
    # Secondary blind labels are compared to original labels before adjudication.
    second=read_jsonl((ROOT/'audit').glob('second_*.jsonl'),add_file=not public_mode)
    e2,w2=validate(second,meta,public_mode);dump(ROOT/'audit/secondary_validation.json',{'records':len(second),'errors':e2,'warnings':w2,
        **({'evidence_verification':'unavailable_public_text_withheld'} if public_mode else {})})
    if e2:raise RuntimeError(e2)
    sdf=frame(second,meta,public_mode);primary=baseline.set_index('id');secondary=sdf.set_index('id')
    agreement=[];disagreements=[]
    for group in GROUPS:
        ids=[i for i in secondary.index if primary.loc[i,'group']==group]
        for code in ['r']+allcodes+['ph','rd','g','q','di']:
            use=ids if code=='r' else [i for i in ids if primary.loc[i,'r']==1 and secondary.loc[i,'r']==1]
            aa=[primary.loc[i,code] for i in use];bb=[secondary.loc[i,code] for i in use]
            al,n,agree=alpha(aa,bb,ordinal=code=='di')
            agreement.append({'group':group,'code':code,'selected_records':len(ids),'eligible_records':len(use),'n_pairs':n,'missing_pairs':len(use)-n,'agreement':agree,'alpha':al,'kind':'AI_AI_not_human'})
            for i,a,b in zip(use,aa,bb):
                if str(a)!=str(b):disagreements.append({'id':i,'group':group,'code':code,'primary':a,'secondary':b})
    agreement=pd.DataFrame(agreement);save_table('ai_agreement',agreement)
    save_table('ai_disagreements',pd.DataFrame(disagreements))
    control=json.loads((ROOT/'audit/control_selection.json').read_text(encoding='utf-8'))
    expected_second=set(x for s in control.values() for x in s['record_ids'])
    audit_missing=sorted(expected_second-set(secondary.index))
    if audit_missing:raise RuntimeError(f'Blind second coding incomplete: {audit_missing}')
    facts={'screening':screen.to_dict('records'),'included_total':len(rel),'human_validation':False,
           'primary_records':len(raw),'secondary_records':len(second),'secondary_missing':audit_missing,
           'exact_duplicate_extra':int(df.is_exact_duplicate.sum()),'near_duplicate_extra':int(df.is_near_duplicate.sum()),
           'codes':profiles.to_dict('records'),'official':v1.to_dict('records'),'cross_common':cross_profiles.to_dict('records'),
           'v2':v2.to_dict('records'),'goal_relation':answers.g.value_counts().to_dict(),
           'parent_education':rel.ph.value_counts().to_dict(),
           'devaluation_n':len(deval),'devaluation_bases':{k:int(deval['db_'+k].sum()) for k in DBLABEL},
           'cool_ids':rel.loc[rel.m_cool==1,'id'].tolist(),'route_ids':rel.loc[rel.m_route==1,'id'].tolist(),
           'warm_ids':rel.loc[rel.m_warm==1,'id'].tolist(),'family_ids':rel.loc[rel.family==1,'id'].tolist(),
           'deval_ids':deval.id.tolist(),'institutional_ids':df.loc[df.author_type=='university_label','id'].tolist()}
    dump(ROOT/'tables/key_results.json',facts)
    make_figures(df,rel,screen,profiles,v1,v2,agreement,deval,cross_profiles)
    print(json.dumps({'included':len(rel),'secondary':len(second),'secondary_missing':audit_missing,'strict_cooling':facts['cool_ids'],'devaluation_n':len(deval)},ensure_ascii=False))

def make_family_observability_figure(profiles):
    """Explain three separate textual indicators; do not imply agreement or accuracy."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    fields=['family','role_known','reading_known']
    titles=['А. Семейный опыт\nиспользован как аргумент',
            'Б. Автор прямо сообщает\nо своей роли',
            'В. Модель определила тип\nреакции на утверждение']
    descriptions=['Опыт семьи помогает\nобосновать оценку или выбор.',
                  'Например: родитель,\nабитуриент или выпускник.',
                  'Принятие, принятие с оговорками\nили оспаривание утверждения.']
    colors=['#285A78','#BD7A3B','#517A72']
    style={'font.family':'DejaVu Sans','font.size':12,'axes.spines.top':False,
           'axes.spines.right':False,'axes.spines.left':False,'svg.fonttype':'none',
           'figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white'}
    with plt.rc_context(style):
        fig,axes=plt.subplots(1,3,figsize=(14,8.2),sharey=True)
        fig.subplots_adjust(left=.19,right=.99,top=.70,bottom=.32,wspace=.18)
        fig.text(.025,.965,'Какие сведения модель выделила в сообщениях',
                 fontsize=20,fontweight='bold',va='top',color='#17212a')
        fig.text(.025,.91,'Три отдельных признака. Длина полосы показывает долю сообщений с данным признаком.',
                 fontsize=12,color='#4b5563')
        y=np.arange(len(GROUPS))
        for j,(ax,field) in enumerate(zip(axes,fields)):
            sub=profiles[profiles.code==field].set_index('group').loc[GROUPS]
            ax.barh(y,np.full(len(y),100),height=.45,color='#EDF0F3',zorder=1)
            ax.barh(y,sub.pct.to_numpy(),height=.45,color=colors[j],zorder=2)
            for i,r in enumerate(sub.itertuples()):
                ax.text(104,i,f'{int(r.n)}/{int(r.N)}',va='center',ha='left',
                        fontsize=11,fontweight='bold',color='#17212a')
            ax.text(0,1.29,titles[j],transform=ax.transAxes,fontsize=13.2,
                    fontweight='bold',va='top',linespacing=1.3,color='#17212a')
            ax.text(0,1.11,descriptions[j],transform=ax.transAxes,fontsize=10.5,
                    va='top',linespacing=1.35,color='#4b5563')
            ax.set_xlim(0,139);ax.set_xticks([0,50,100])
            ax.xaxis.set_major_formatter(PercentFormatter())
            ax.tick_params(axis='x',labelsize=10,length=3,color='#9CA3AF')
            ax.tick_params(axis='y',length=0,pad=12)
            ax.spines['bottom'].set_color('#CBD2D9')
            ax.set_ylim(len(y)-.45,-.55)
        axes[0].set_yticks(y,[GLABEL[g].replace('\n',' — ') for g in GROUPS])
        fig.text(.19,.26,'Числа справа: сообщения с признаком / все включённые сообщения данного типа.',
                 fontsize=11,color='#4b5563')
        fig.text(.025,.205,
                 'Как читать 78/100 в панели В: в 78 из 100 комментариев Пикабу модель назначила тип реакции.\n'
                 'Число 78 объединяет все три типа реакции; доля сообщений с согласием на этом графике не показана.',
                 fontsize=12,linespacing=1.5,va='top',color='#17212a',
                 bbox={'boxstyle':'round,pad=.7','facecolor':'#F0F5F4','edgecolor':'none'})
        fig.text(.025,.083,
                 'Серый остаток: признак не отмечен моделью; это не характеристика человека.\n'
                 'Разметка предварительная. Согласованность классификации реакций низкая; проверка исследователем не проведена.',
                 fontsize=10.2,linespacing=1.5,va='top',color='#4b5563')
        for extension in ['png','svg']:
            fig.savefig(ROOT/'figures'/f'04_family_observability.{extension}',
                        dpi=220,bbox_inches='tight')
        plt.close(fig)

def make_figures(df,rel,screen,profiles,v1,v2,agreement,deval,cross_profiles):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import seaborn as sns
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.titlesize':16,'axes.labelsize':11,
                         'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','svg.fonttype':'none',
                         'figure.facecolor':'white','axes.facecolor':'white','savefig.facecolor':'white'})
    colors=['#285A78','#D98B47','#5C8D76','#8B78A5','#A25B5B']
    def save(fig,name,caption):
        fig.text(.03,.018,caption+'\nПредварительная модельная разметка; проверка человеком не проведена.',fontsize=9,color='#4b5563',va='bottom')
        fig.tight_layout(rect=[0,.11,1,.97])
        fig.savefig(ROOT/'figures'/f'{name}.png',dpi=220,bbox_inches='tight')
        fig.savefig(ROOT/'figures'/f'{name}.svg',bbox_inches='tight');plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,5.5));y=np.arange(len(GROUPS));left=np.zeros(len(GROUPS))
    for key,label,color in [('included','Включено','#285A78'),('excluded','Исключено','#DCE2E6'),('undetermined','Недостаточно данных','#D98B47')]:
        vals=screen.set_index('group').loc[GROUPS,key].to_numpy();ax.barh(y,vals,left=left,label=label,color=color,height=.65)
        for i,n in enumerate(vals):
            if n:ax.text(left[i]+n/2,i,str(n),ha='center',va='center',color='white' if key=='included' else '#1f2937',fontsize=10)
        left+=vals
    ax.set_yticks(y,[GLABEL[g].replace('\n',' — ') for g in GROUPS]);ax.invert_yaxis();ax.set_xlabel('Число сообщений');ax.set_title('Какая часть собранного корпуса пригодна для анализа',loc='left');ax.legend(loc='lower right')
    save(fig,'01_screening','Все 1094 записи прошли модельный скрининг. Числа относятся к сообщениям разных типов.')
    fig,ax=plt.subplots(figsize=(10,5.5));channels=list(v1.channel.unique());codes=list(LLABEL);y=np.arange(len(codes))
    for j,ch in enumerate(channels):
        sub=v1[(v1.channel==ch)&v1.code.str.startswith('l_')].set_index('code');vals=[sub.loc['l_'+c,'pct'] for c in codes];offset=(j-(len(channels)-1)/2)*.3
        ax.barh(y+offset,vals,height=.26,color=colors[j],label={'minprosrf':'Минпросвещения','minobrnaukiofficial':'Минобрнауки'}.get(ch,ch))
        for i,c in enumerate(codes):
            r=sub.loc['l_'+c];ax.text(vals[i]+1,y[i]+offset,f"{r['pct']:.1f}% ({int(r['n'])}/{int(r['N'])})",va='center',fontsize=9)
    ax.set_yticks(y,[LLABEL[c] for c in codes]);ax.invert_yaxis();ax.set_xlim(0,115);ax.xaxis.set_major_formatter(PercentFormatter());ax.set_title('Как ведомства обосновывают образовательный путь',loc='left');ax.legend(loc='lower right')
    save(fig,'02_official_arguments','Общие июльские окна 2022–2026 годов. Доли среди включённых постов каждого ведомства; коды совместимы.')
    fig,axs=plt.subplots(1,2,figsize=(12,5.6),gridspec_kw={'width_ratios':[1.2,1]})
    a=rel[rel.row_type=='answer'];counts=[int(a['m_'+k].sum()) for k in MLABEL]
    axs[0].barh(list(MLABEL.values()),counts,color=colors[0]);axs[0].invert_yaxis();axs[0].set_xlabel('Ответы с признаком');axs[0].set_title('Предложения в ответах',loc='left')
    for i,n in enumerate(counts):axs[0].text(n+.5,i,f'{n}/{len(a)}',va='center')
    cats=['lower','same','raise','mixed','unknown','na'];labels=['Снижение','Сохранение','Повышение','Смешанное','Цель не определена','Нет сравнения целей']
    vals=[int((a.g==c).sum()) for c in cats]
    axs[1].barh(labels,vals,color=[colors[1]]*4+['#9CA3AF','#DCE2E6']);axs[1].invert_yaxis();axs[1].set_xlabel('Число ответов');axs[1].set_title('Отношение к исходной цели',loc='left')
    for i,n in enumerate(vals):axs[1].text(n+.5,i,str(n),va='center')
    fig.suptitle('Консультирование и границы определения охлаждения',x=.02,ha='left',fontweight='bold',fontsize=16)
    save(fig,'03_advice_mechanisms',f'Табитуриент: {len(a)} включённых ответов. Несколько ответов могут относиться к одному вопросу.')
    make_family_observability_figure(profiles)
    fig,ax=plt.subplots(figsize=(10,5.5));counts={DBLABEL[k]:int(deval['db_'+k].sum()) for k in DBLABEL};counts=dict(sorted(counts.items(),key=lambda x:x[1],reverse=True))
    ax.barh(list(counts),list(counts.values()),color=colors[1]);ax.invert_yaxis();ax.set_xlabel('Число сообщений с основанием');ax.set_title('Чем обосновывается снижение ценности диплома',loc='left')
    for i,n in enumerate(counts.values()):ax.text(n+.2,i,f'{n}/{len(deval)}',va='center')
    ax.set_xlim(0,max(counts.values(),default=0)*1.25+2)
    save(fig,'05_devaluation_bases',f'Основания среди {len(deval)} сообщений с модельным кодом девальвации ВО. В одном сообщении возможны несколько оснований.')
    mat=np.zeros((4,5));annot=np.empty((4,5),dtype=object)
    for i,c in enumerate(LLABEL):
        for j,g in enumerate(GROUPS):
            r=cross_profiles[(cross_profiles.group==g)&(cross_profiles.code=='l_'+c)]
            if len(r):
                r=r.iloc[0];mat[i,j]=r['pct'];annot[i,j]=f"{r['pct']:.1f}%\n{int(r['n'])}/{int(r['N'])}"
            else:mat[i,j]=np.nan;annot[i,j]='н/д'
    fig,ax=plt.subplots(figsize=(11,5.6));sns.heatmap(mat,annot=annot,fmt='',cmap='Blues',vmin=0,vmax=100,xticklabels=[GLABEL[g] for g in GROUPS],yticklabels=list(LLABEL.values()),cbar_kws={'label':'Доля, %'},ax=ax,linewidths=1,linecolor='white')
    ax.set_yticklabels(ax.get_yticklabels(),rotation=0);ax.set_title('Профили аргументации в разных коммуникативных ситуациях',loc='left',pad=18)
    save(fig,'06_cross_corpus','Общая тема СПО/ВО, 24.02.2022–06.10.2026. Каждый тип имеет свой знаменатель; жанр и отбор остаются различными.')
    # Coverage is shown as discrete counts, avoiding false continuous population trends.
    cov=df[df.row_type.isin(['post','question'])].groupby(['source','period']).size().unstack(fill_value=0).reindex(columns=['P1','P2','P3','P4'],fill_value=0)
    fig,ax=plt.subplots(figsize=(10,4.8));sns.heatmap(cov,annot=True,fmt='d',cmap='Greys',cbar=False,xticklabels=[PLABEL[p] for p in cov.columns],yticklabels=['Пикабу' if s=='pikabu' else 'Табитуриент' if s=='tabiturient' else 'Telegram' for s in cov.index],ax=ax,linewidths=2,linecolor='white')
    ax.set_xlabel('');ax.set_ylabel('');ax.set_yticklabels(ax.get_yticklabels(),rotation=0);ax.set_title('Неравномерное календарное покрытие исходного корпуса',loc='left',pad=15)
    save(fig,'07_calendar_coverage','Число родительских единиц до скрининга: постов либо вопросов. Нули означают отсутствие сохранённых данных.')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--partial',action='store_true')
    p.add_argument('--family-figure-only',action='store_true')
    args=p.parse_args()
    if args.family_figure_only:
        make_family_observability_figure(pd.read_csv(ROOT/'tables/vi3_family_profiles.csv'))
    else:
        main(args.partial)
