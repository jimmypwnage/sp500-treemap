/* Shared treemap engine. A page sets window.CHART (metric key) and optional
   window.NAV=true before loading this + data.js. Tuple layout:
   [0 tkr,1 sec,2 price,3 wt,4 dod,5 wow,6 sh3,7 sh6,8 so3,9 so6,10 a3,11 a6,12 b3,13 b6,14 v3,15 v6] */
(function(){
const D=window.SP500;
const map=document.getElementById('map');
if(!D||!D.stocks){if(map)map.innerHTML='<div id="err">data.js not found — run fetch_data.py.</div>';return;}
const STOCKS=D.stocks, SERIES=D.series||{}, SECTOR_SERIES=D.sectorSeries||{}, SPX_SERIES=D.spxSeries||[];
const SECTOR_ORDER=["Information Technology","Communication Services","Consumer Discretionary","Financials",
  "Health Care","Consumer Staples","Industrials","Energy","Utilities","Materials","Real Estate"];

const sgn=v=>v>=0?'+':'';
const num2=v=>sgn(v)+v.toFixed(2), pct1=v=>sgn(v)+v.toFixed(1)+'%', pct2=v=>sgn(v)+v.toFixed(2)+'%';
const MET={
  dod:{i:4,label:'Daily change',fmt:pct2},
  sharpe3m:{i:6,label:'3-month Sharpe',fmt:num2},
  sharpe6m:{i:7,label:'6-month Sharpe',fmt:num2},
  sortino3m:{i:8,label:'3-month Sortino',fmt:num2},
  sortino6m:{i:9,label:'6-month Sortino',fmt:num2},
  alpha3m:{i:10,label:'3-month Alpha (ann.)',fmt:pct1},
  alpha6m:{i:11,label:'6-month Alpha (ann.)',fmt:pct1},
};
const PAGES=[["dod","Daily","index.html"],["sharpe3m","Sharpe 3m","sharpe-3m.html"],
  ["sharpe6m","Sharpe 6m","sharpe-6m.html"],["sortino3m","Sortino 3m","sortino-3m.html"],
  ["sortino6m","Sortino 6m","sortino-6m.html"],["alpha3m","Alpha 3m","alpha-3m.html"],
  ["alpha6m","Alpha 6m","alpha-6m.html"]];

const KEY=MET[window.CHART]?window.CHART:'dod';
const M=MET[KEY], IDX=M.i;
const val=r=>r[IDX];      // metric value for a stock row (may be null)

// ---- adaptive diverging clamp: 92nd percentile of |value| ----
let CLAMP=1;
function clampFor(){
  const v=STOCKS.map(val).filter(x=>x!=null&&isFinite(x)).map(Math.abs).sort((a,b)=>a-b);
  if(!v.length)return 1;
  const p=v[Math.floor(v.length*0.92)]||v[v.length-1];
  return Math.max(0.2,p);
}
const lerp=(a,b,t)=>a+(b-a)*t;
function colorFor(v){
  if(v==null||!isFinite(v))return 'rgb(45,50,60)';       // no data → neutral
  const c=Math.max(-CLAMP,Math.min(CLAMP,v))/CLAMP, g=[61,68,80];let r,gr,b;
  if(c<0){const t=-c;r=lerp(g[0],140,t);gr=lerp(g[1],28,t);b=lerp(g[2],28,t);}
  else{const t=c;r=lerp(g[0],18,t);gr=lerp(g[1],150,t);b=lerp(g[2],70,t);}
  return `rgb(${r|0},${gr|0},${b|0})`;
}

// ---- sparkline (unchanged: 1-month ticker vs sector vs S&P) ----
function sparkline(ticker,sector){
  const a=SERIES[ticker],b=SECTOR_SERIES[sector],c=SPX_SERIES;
  if(!a||!a.length)return'';
  const N=a.length, all=[].concat(a,b||[],c||[]);
  let mn=Math.min(...all),mx=Math.max(...all);if(mx-mn<1e-6){mx+=.01;mn-=.01;}
  const W=200,H=54,pad=3,X=i=>pad+i*(W-2*pad)/(N-1),Y=v=>pad+(1-(v-mn)/(mx-mn))*(H-2*pad);
  const path=s=>s.map((v,i)=>`${i?'L':'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
  const zeroY=Y(0).toFixed(1),last=v=>(v>=0?'+':'')+(v*100).toFixed(1)+'%';
  const sec=b?`<path d="${path(b)}" fill="none" stroke="#d29922" stroke-width="1.2" opacity=".9"/>`:'';
  const spx=c&&c.length?`<path d="${path(c)}" fill="none" stroke="#8b949e" stroke-width="1" stroke-dasharray="3 2" opacity=".8"/>`:'';
  return `<svg width="${W}" height="${H}" style="display:block;margin-top:6px">
    <line x1="${pad}" y1="${zeroY}" x2="${W-pad}" y2="${zeroY}" stroke="#30363d" stroke-dasharray="2 2"/>
    ${spx}${sec}<path d="${path(a)}" fill="none" stroke="#58a6ff" stroke-width="1.8"/></svg>
   <div style="display:flex;gap:10px;font-size:10px;margin-top:2px">
    <span style="color:#58a6ff">— ${ticker} ${last(a[N-1])}</span>
    ${b?'<span style="color:#d29922">— Sector</span>':''}
    ${c&&c.length?`<span style="color:#8b949e">-- S&amp;P ${last(c[c.length-1])}</span>`:''}</div>`;
}

// ---- squarified treemap ----
function squarify(items,x,y,w,h){
  const total=items.reduce((s,i)=>s+i.value,0)||1,scale=(w*h)/total;
  const norm=items.map(i=>({...i,area:i.value*scale})),out=[];
  let rx=x,ry=y,rw=w,rh=h,row=[],i=0;
  const worst=(row,len)=>{const s=row.reduce((a,b)=>a+b.area,0),mx=Math.max(...row.map(r=>r.area)),mn=Math.min(...row.map(r=>r.area));
    return Math.max((len*len*mx)/(s*s),(s*s)/(len*len*mn));};
  function lay(row,len,horiz){const s=row.reduce((a,b)=>a+b.area,0),thick=s/len;let off=0;
    for(const r of row){const cell=r.area/thick;
      if(horiz){out.push({...r,rect:[rx,ry+off,thick,cell]});off+=cell;}else{out.push({...r,rect:[rx+off,ry,cell,thick]});off+=cell;}}
    if(horiz){rx+=thick;rw-=thick;}else{ry+=thick;rh-=thick;}}
  while(i<norm.length){const horiz=rw>=rh,len=horiz?rh:rw,cur=norm[i];
    if(!row.length){row.push(cur);i++;continue;}
    if(worst(row,len)>=worst([...row,cur],len)){row.push(cur);i++;}else{lay(row,len,horiz);row=[];}}
  if(row.length){const horiz=rw>=rh;lay(row,horiz?rh:rw,horiz);}
  return out;
}

// ---- Telegram SDK (no-op outside Telegram) ----
const TG=window.Telegram&&window.Telegram.WebApp;
function haptic(k){try{TG&&TG.HapticFeedback&&TG.HapticFeedback.impactOccurred(k||'light');}catch(e){}}
if(TG){try{TG.ready();TG.expand();TG.setBackgroundColor&&TG.setBackgroundColor('#0d1117');
  TG.setHeaderColor&&TG.setHeaderColor('#161b22');TG.disableVerticalSwipes&&TG.disableVerticalSwipes();}catch(e){}}

let zoomedSector=null,pinned=null;
const BY_SECTOR={};
for(const r of STOCKS){(BY_SECTOR[r[1]]=BY_SECTOR[r[1]]||[]).push(r);}
function sectorMetric(sec){   // weight-weighted mean of the current metric
  let w=0,wd=0;for(const r of BY_SECTOR[sec]){const v=val(r);if(v==null)continue;const x=r[3]||0;w+=x;wd+=x*v;}
  return w?wd/w:null;
}

function makeTile(r,tx,ty,tw,th){
  const d=document.createElement('div');d.className='tile';
  const v=val(r);
  d.style.cssText=`left:${tx}px;top:${ty}px;width:${tw}px;height:${th}px;background:${colorFor(v)};`;
  const area=tw*th;let html='';
  if(area>260)html+=`<div class="tk">${r[0]}</div>`;
  if(area>1800)html+=`<div class="mv">${v==null?'–':M.fmt(v)}</div>`;
  if(area>8000)html+=`<div class="pr">$${r[2]}</div>`;
  d.innerHTML=html;
  d.style.fontSize=Math.max(7,Math.min(20,Math.sqrt(area)/7))+'px';
  d.addEventListener('click',e=>tileTap(e,r));
  d.addEventListener('mouseenter',e=>{if(!pinned)showTip(e,r);});
  d.addEventListener('mousemove',e=>{if(!pinned)showTip(e,r);});
  d.addEventListener('mouseleave',()=>{if(!pinned)hideTip();});
  return d;
}

function build(){
  hideTip();pinned=null;map.innerHTML='';
  CLAMP=clampFor();
  const W=map.clientWidth,H=map.clientHeight;
  if(zoomedSector){renderZoom(W,H);return;}
  const sectors=SECTOR_ORDER.filter(s=>BY_SECTOR[s]).map(s=>({
    name:s,value:BY_SECTOR[s].reduce((a,b)=>a+(b[3]||0.01),0),items:BY_SECTOR[s]}));
  for(const sr of squarify(sectors,0,0,W,H)){
    const [sx,sy,sw,sh]=sr.rect;
    const sd=document.createElement('div');sd.className='sector';
    sd.style.cssText=`left:${sx}px;top:${sy}px;width:${sw}px;height:${sh}px;`;
    const lbl=document.createElement('div');lbl.className='sector-label';lbl.textContent=sr.name;
    lbl.addEventListener('click',e=>{e.stopPropagation();haptic();zoomedSector=sr.name;build();});
    sd.appendChild(lbl);
    const items=sr.items.slice().sort((a,b)=>(b[3]||0)-(a[3]||0)).map(r=>({r,value:r[3]||0.005}));
    for(const t of squarify(items,1,19,Math.max(1,sw-2),Math.max(1,sh-20))){
      const [tx,ty,tw,th]=t.rect;sd.appendChild(makeTile(t.r,tx,ty,tw,th));
    }
    map.appendChild(sd);
  }
}
function renderZoom(W,H){
  const sec=zoomedSector,sm=sectorMetric(sec);
  const bar=document.createElement('div');bar.className='backbar';
  const sv=sm==null?'':` <span class="sd" style="color:${sm>=0?'#3fb950':'#f85149'}">${M.fmt(sm)}</span>`;
  bar.innerHTML=`<span class="chev">‹</span>All sectors &nbsp;·&nbsp; ${sec}${sv}`;
  bar.addEventListener('click',e=>{e.stopPropagation();haptic();zoomedSector=null;build();});
  map.appendChild(bar);
  const items=BY_SECTOR[sec].slice().sort((a,b)=>(b[3]||0)-(a[3]||0)).map(r=>({r,value:r[3]||0.005}));
  for(const t of squarify(items,0,32,W,Math.max(1,H-32))){
    const [tx,ty,tw,th]=t.rect;map.appendChild(makeTile(t.r,tx,ty,tw,th));
  }
}

// ---- tooltip: tap to pin (mobile) + hover preview (desktop) ----
const tt=document.getElementById('tt');
function tileTap(e,r){e.stopPropagation();haptic();
  if(pinned===r[0]){hideTip();pinned=null;return;}pinned=r[0];showTip(e,r);}
function row(k,lo,hi,fmt,hi_){const f=v=>v==null?'–':fmt(v);
  return `<tr class="${hi_?'hi':''}"><td class="k">${k}</td><td>${f(lo)}</td><td>${f(hi)}</td></tr>`;}
function showTip(e,r){
  tt.style.display='block';
  const wt=r[3]!=null?r[3].toFixed(3)+'%':'–';
  tt.innerHTML=`<b>${r[0]}</b> <span class="hd">${r[1]}</span>
    <div class="hd">$${r[2]} · DoD ${sgn(r[4])}${r[4].toFixed(2)}% · WoW ${sgn(r[5])}${r[5].toFixed(2)}% · wt ${wt}</div>
    <table><tr><th></th><th>3m</th><th>6m</th></tr>
    ${row('Sharpe',r[6],r[7],num2,KEY.startsWith('sharpe'))}
    ${row('Sortino',r[8],r[9],num2,KEY.startsWith('sortino'))}
    ${row('Alpha',r[10],r[11],pct1,KEY.startsWith('alpha'))}
    ${row('Beta',r[12],r[13],v=>v.toFixed(2))}
    ${row('Vol',r[14],r[15],v=>v.toFixed(1)+'%')}
    </table>${sparkline(r[0],r[1])}`;
  const w=228,h=250,pad=14;
  const px=e&&e.clientX!=null?e.clientX:innerWidth/2,py=e&&e.clientY!=null?e.clientY:innerHeight/2;
  let x=px+pad,y=py+pad;if(x+w>innerWidth)x=px-w-pad;if(y+h>innerHeight)y=py-h-pad;
  tt.style.left=Math.max(4,x)+'px';tt.style.top=Math.max(4,y)+'px';
}
function hideTip(){tt.style.display='none';}
document.addEventListener('click',()=>{hideTip();pinned=null;});

// ---- header + nav ----
const asof=document.getElementById('asof');
if(asof)asof.textContent=`as of ${D.asOf} · ${STOCKS.length} names · daily close · generated ${D.generated||''}`;
const mn=document.getElementById('metric');
if(mn&&window.NAV)mn.textContent=M.label+(KEY!=='dod'&&D.rfAnnualPct!=null&&KEY.match(/sharpe|sortino/)?`  ·  rf ${D.rfAnnualPct}%`:'');
const navEl=document.getElementById('nav');
if(navEl&&window.NAV){
  navEl.innerHTML=PAGES.map(([k,l,h])=>`<a href="${h}" class="${k===KEY?'active':''}">${l}</a>`).join('');
}
addEventListener('resize',build);
build();
})();