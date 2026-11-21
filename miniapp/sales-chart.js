let salesChartMode='line',salesChartState={points:[],granularity:'day'};
let heatmapMode='count',heatmapData=null;

const DOW_LABELS=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const DOW_FULL=['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];

function kpiSparklineSvg(points,stroke='#c8b3dc',fillId='kpi-spark'){
  if(!points||!points.length)return `<svg viewBox="0 0 148 28" aria-hidden="true"><line x1="2" x2="146" y1="22" y2="22" stroke="rgba(255,255,255,0.08)" stroke-dasharray="3 3"/></svg>`;
  const vals=points.map(p=>p.value);
  const max=Math.max(0.01,...vals);
  if(points.length===1){
    const y=vals[0]>0?10:22;
    return `<svg viewBox="0 0 148 28" aria-hidden="true"><line x1="2" x2="146" y1="22" y2="22" stroke="rgba(255,255,255,0.07)" stroke-dasharray="2 3"/><circle cx="74" cy="${y}" r="5" fill="${stroke}" fill-opacity=".22"/><circle cx="74" cy="${y}" r="2.6" fill="#f2f0f5"/></svg>`;
  }
  const coords=vals.map((v,i)=>[2+i*(142/(vals.length-1)),24-(v/max)*19]);
  const d=coords.map((p,i)=>i?`C${((coords[i-1][0]+p[0])/2).toFixed(1)},${coords[i-1][1].toFixed(1)} ${((coords[i-1][0]+p[0])/2).toFixed(1)},${p[1].toFixed(1)} ${p[0].toFixed(1)},${p[1].toFixed(1)}`:`M${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
  const last=coords.at(-1);
  return `<svg viewBox="0 0 148 28" aria-hidden="true"><defs><linearGradient id="${fillId}" x1="0" y1="0" x2="0" y2="1"><stop stop-color="${stroke}" stop-opacity=".28"/><stop offset="1" stop-color="${stroke}" stop-opacity="0"/></linearGradient></defs><path d="${d} L${last[0].toFixed(1)},26 L2,26 Z" fill="url(#${fillId})"/><path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.8" stroke-linecap="round"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.6" fill="#f2f0f5" stroke="${stroke}" stroke-width="1.5"/></svg>`;
}

function kpiHistogramSvg(points){
  if(!points||!points.length)return `<svg viewBox="0 0 148 28" aria-hidden="true"><line x1="2" x2="146" y1="24" y2="24" stroke="rgba(255,255,255,0.08)"/></svg>`;
  const sample=points.length>24?points.slice(-24):points;
  const max=Math.max(1,...sample.map(p=>p.count));
  const step=144/Math.max(1,sample.length);
  const bw=Math.max(2,Math.min(7,step*0.66));
  const bars=sample.map((p,i)=>{
    const x=2+i*step+(step-bw)/2;
    if(!p.count)return `<rect x="${x.toFixed(1)}" y="24" width="${bw.toFixed(1)}" height="1.2" rx=".6" fill="rgba(255,255,255,0.1)"/>`;
    const h=Math.max(3,(p.count/max)*21);
    return `<rect x="${x.toFixed(1)}" y="${(25-h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="1.4" fill="${i===sample.length-1?'#dfd0ee':'rgba(200,179,220,0.52)'}"/>`;
  }).join('');
  return `<svg viewBox="0 0 148 28" aria-hidden="true">${bars}</svg>`;
}

function kpiCoverageBarSvg(costed,otherCurr,noCost){
  const total=costed+otherCurr+noCost;
  if(!total)return `<svg viewBox="0 0 148 28" aria-hidden="true"><rect x="0" y="11" width="148" height="6" rx="3" fill="rgba(255,255,255,0.06)"/></svg>`;
  const w1=(costed/total)*148,w2=(otherCurr/total)*148;
  return `<svg viewBox="0 0 148 28" aria-hidden="true"><rect x="0" y="11" width="148" height="6" rx="3" fill="rgba(255,255,255,0.06)"/>${w1>0?`<rect x="0" y="11" width="${Math.max(3,w1).toFixed(1)}" height="6" rx="3" fill="#6ec498"/>`:''}${w2>0?`<rect x="${w1.toFixed(1)}" y="11" width="${Math.max(3,w2).toFixed(1)}" height="6" rx="3" fill="#dfc07c"/>`:''}</svg>`;
}

function drawSalesChart(input=salesChartState){
  if(Array.isArray(input)){
    salesChartState={points:input.map(([date,value])=>({date,value,count:1})),granularity:period==='day'?'hour':period==='year'?'month':'day'};
  }else if(input&&Array.isArray(input.points)){
    salesChartState=input;
  }
  const {points:rawPoints,granularity}=salesChartState;
  const root=document.querySelector('#real-chart');
  if(!root)return;
  const heading=root.closest('.panel').querySelector('.panel-heading');
  heading.classList.add('sales-heading');
  const titles={hour:'Зачисления по часам',day:'Зачисления по дням',week:'Зачисления по неделям',month:'Зачисления по месяцам'};
  const lineIcon=typeof icon==='function'?icon('line'):'';
  const barIcon=typeof icon==='function'?icon('bars'):'';
  heading.innerHTML=`<div><h2>${titles[granularity]||'Зачисления по дням'}</h2><p>Чистые поступления продавцу в ${esc(currency)} (Europe/Warsaw)</p></div><div class="sales-modes" role="group" aria-label="Вид графика">${[['line','Линия',lineIcon],['bars','Столбцы',barIcon]].map(([m,lbl,ic])=>`<button data-mode="${m}" aria-pressed="${salesChartMode===m}">${ic}<span>${lbl}</span></button>`).join('')}</div>`;
  heading.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{salesChartMode=b.dataset.mode;drawSalesChart()});

  const totalOrders=rawPoints.reduce((s,p)=>s+(p.count||0),0);
  const totalValue=rawPoints.reduce((s,p)=>s+p.value,0);
  if(!rawPoints.length||totalOrders===0){
    root.innerHTML=`<div class="chart-empty">Нет оплаченных заказов в ${esc(currency)} за выбранный период</div>`;
    return;
  }

  const width=Math.max(300,root.clientWidth-36),height=252,left=52,right=14,top=18,bottom=210;
  const maxVal=Math.max(1,...rawPoints.map(p=>p.value))*1.14;
  const n=rawPoints.length;
  const spanW=width-left-right-24;
  const pts=rawPoints.map((p,i)=>({
    ...p,
    x:n>1?left+12+(i/(n-1))*spanW:(width+left)/2,
    y:bottom-(p.value/maxVal)*(bottom-top)
  }));

  const shortDate=d=>d.includes('T')?d.slice(11,16):granularity==='month'?d.slice(5,7)+'.'+d.slice(2,4):d.slice(8,10)+'.'+d.slice(5,7);
  const fullDate=d=>d.includes('T')?d.slice(0,10).split('-').reverse().join('.')+' · '+d.slice(11,16):granularity==='week'?'Неделя с '+d.split('-').reverse().join('.'):d.split('-').reverse().join('.');

  let svg=`<defs><linearGradient id="sales-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#c8b3dc" stop-opacity=".22"/><stop offset="75%" stop-color="#c8b3dc" stop-opacity=".03"/><stop offset="100%" stop-color="#c8b3dc" stop-opacity="0"/></linearGradient><linearGradient id="sales-bar" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#cbb5e0" stop-opacity=".62"/><stop offset="1" stop-color="#6b5680" stop-opacity=".28"/></linearGradient></defs>`;

  for(let i=0;i<5;i++){
    const y=top+(bottom-top)*i/4;
    const labelVal=maxVal*(4-i)/4;
    svg+=`<line x1="${left}" x2="${width-right}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,0.05)" ${i<4?'stroke-dasharray="3 3"':''}/>`;
    svg+=`<text x="${left-8}" y="${y+3.5}" text-anchor="end" fill="#827c8e" font-size="11" class="num">${new Intl.NumberFormat('ru-RU',{notation:'compact',maximumFractionDigits:1}).format(labelVal)}</text>`;
  }

  if(n>=2&&totalValue>0){
    const avg=totalValue/n;
    const avgY=bottom-(avg/maxVal)*(bottom-top);
    svg+=`<line x1="${left}" x2="${width-right}" y1="${avgY}" y2="${avgY}" stroke="rgba(200,179,220,0.28)" stroke-dasharray="4 4"/>`;
  }

  if(salesChartMode==='line'){
    if(n>1){
      const path=pts.map((p,i)=>i?`C${((pts[i-1].x+p.x)/2).toFixed(1)},${pts[i-1].y.toFixed(1)} ${((pts[i-1].x+p.x)/2).toFixed(1)},${p.y.toFixed(1)} ${p.x.toFixed(1)},${p.y.toFixed(1)}`:`M${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
      svg+=`<path d="${path} L${pts.at(-1).x.toFixed(1)},${bottom} L${pts[0].x.toFixed(1)},${bottom}Z" fill="url(#sales-fill)"/>`;
      svg+=`<path d="${path}" fill="none" stroke="#c8b3dc" stroke-width="2.1" stroke-linecap="round"/>`;
    }else{
      svg+=`<circle cx="${pts[0].x}" cy="${pts[0].y}" r="9" fill="rgba(200,179,220,0.18)"/><circle cx="${pts[0].x}" cy="${pts[0].y}" r="4" fill="#f2f0f5" stroke="#9b7fc0" stroke-width="2"/>`;
    }
  }

  const stepGap=n>1?spanW/(n-1):56;
  const barWidth=Math.max(3,Math.min(30,stepGap*0.62));
  let lastLabelX=-Infinity;

  pts.forEach((p,i)=>{
    if(salesChartMode==='bars'){
      if(p.value>0){
        const bh=Math.max(2,bottom-p.y);
        const bx=p.x-barWidth/2;
        svg+=`<rect x="${bx.toFixed(1)}" y="${p.y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${bh.toFixed(1)}" rx="${Math.min(4,barWidth/2.5).toFixed(1)}" fill="url(#sales-bar)"/>`;
        svg+=`<line x1="${(bx+1).toFixed(1)}" x2="${(bx+barWidth-1).toFixed(1)}" y1="${p.y.toFixed(1)}" y2="${p.y.toFixed(1)}" stroke="#e3d4f1" stroke-width="1.5" stroke-linecap="round"/>`;
      }else{
        svg+=`<line x1="${(p.x-barWidth/2).toFixed(1)}" x2="${(p.x+barWidth/2).toFixed(1)}" y1="${bottom}" y2="${bottom}" stroke="rgba(255,255,255,0.12)" stroke-width="1.2"/>`;
      }
    }
    const hitW=Math.max(12,stepGap);
    svg+=`<rect class="chart-hit" data-index="${i}" tabindex="0" role="button" aria-label="${p.date}: ${money(p.value)}" x="${(p.x-hitW/2).toFixed(1)}" y="${top}" width="${hitW.toFixed(1)}" height="${bottom-top}" fill="transparent"/>`;
    const isLast=i===n-1,minGap=width<500?48:42;
    const canFit=p.x-lastLabelX>=minGap&&(isLast||pts.at(-1).x-p.x>=minGap);
    if(i===0||(isLast&&p.x-lastLabelX>=34)||canFit){
      lastLabelX=p.x;
      svg+=`<text x="${p.x.toFixed(1)}" y="${bottom+24}" text-anchor="${n===1?'middle':i===0?'start':isLast?'end':'middle'}" fill="#827c8e" font-size="11" class="num">${shortDate(p.date)}</text>`;
    }
  });

  svg+=`<g id="sales-marker" visibility="hidden"><line id="sales-guide" y1="${top}" y2="${bottom}" stroke="rgba(200,179,220,0.45)" stroke-dasharray="3 3"/><circle id="sales-halo" r="9" fill="rgba(200,179,220,0.18)"/><circle id="sales-point" r="4" fill="#f2f0f5" stroke="#8a6cae" stroke-width="2"/></g>`;

  const peak=[...pts].sort((a,b)=>b.value-a.value)[0];
  root.innerHTML=`<div class="sales-summary"><div class="sales-summary-main"><span>После комиссии</span><strong>${money(totalValue)}</strong></div><div class="sales-summary-meta"><span class="pill pill--neutral">${totalOrders} оплач. зак.</span>${peak&&peak.value>0?`<span class="pill pill--lavender">Пик: ${shortDate(peak.date)} · ${money(peak.value)}</span>`:''}</div></div><div class="sales-canvas"><svg viewBox="0 0 ${width} ${height}" aria-label="Зачисления ${currency}, ${salesChartMode==='line'?'линия':'столбцы'}">${svg}</svg><div class="sales-tooltip" hidden></div></div><div class="sales-caption"><span>${shortDate(pts[0].date)} — ${shortDate(pts.at(-1).date)}</span><span>Пунктир — среднее за интервал</span></div>`;

  const tooltip=root.querySelector('.sales-tooltip');
  function show(i){
    const p=pts[i];
    const share=totalValue>0?((p.value/totalValue)*100).toFixed(1):'0.0';
    tooltip.hidden=false;
    tooltip.innerHTML=`<span>${esc(fullDate(p.date))}</span><strong>${money(p.value)}</strong><em>${p.count} зак. · ${share}% периода</em>`;
    tooltip.style.left=Math.max(0,Math.min(p.x-76,width-164))+'px';
    root.querySelector('#sales-marker').setAttribute('visibility','visible');
    const line=root.querySelector('#sales-guide');line.setAttribute('x1',p.x);line.setAttribute('x2',p.x);
    const halo=root.querySelector('#sales-halo');halo.setAttribute('cx',p.x);halo.setAttribute('cy',p.y);
    const dot=root.querySelector('#sales-point');dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y);
  }
  root.querySelectorAll('.chart-hit').forEach(hit=>{
    hit.onpointerenter=hit.onfocus=hit.onclick=()=>show(Number(hit.dataset.index));
    hit.onkeydown=e=>{if(e.key==='Escape'){tooltip.hidden=true;root.querySelector('#sales-marker').setAttribute('visibility','hidden')}};
  });
  root.querySelector('svg').onpointerleave=()=>{tooltip.hidden=true;root.querySelector('#sales-marker').setAttribute('visibility','hidden')};
}

function drawActivityHeatmap(matrix=heatmapData){
  heatmapData=matrix;
  const root=document.querySelector('#activity-heatmap');
  if(!root)return;
  document.querySelectorAll('#heatmap-modes [data-hmode]').forEach(b=>{
    b.setAttribute('aria-pressed',String(b.dataset.hmode===heatmapMode));
    b.onclick=()=>{heatmapMode=b.dataset.hmode;drawActivityHeatmap()};
  });
  if(!matrix||matrix.totalCount===0){
    root.innerHTML=`<div class="chart-empty">Нет оплаченных заказов для тепловой матрицы за выбранный период</div>`;
    return;
  }

  const vbW=360,vbH=168,left=28,top=18,cellW=11.6,cellH=17.5,gapX=2.1,gapY=3.2;
  const maxVal=heatmapMode==='count'?matrix.maxCount:matrix.maxAmount;
  const palette=['rgba(255,255,255,0.035)','#2c2238','#533c6b','#8663ab','#d2bae9'];
  const colorFor=val=>{
    if(!val||!maxVal)return palette[0];
    const t=Math.sqrt(val/maxVal);
    if(t<=0.30)return palette[1];
    if(t<=0.58)return palette[2];
    if(t<=0.82)return palette[3];
    return palette[4];
  };

  let svg='';
  for(let h=0;h<24;h+=3){
    const x=left+h*(cellW+gapX)+cellW/2;
    svg+=`<text x="${x.toFixed(1)}" y="11" text-anchor="middle" fill="#827c8e" font-size="9.5" class="num">${String(h).padStart(2,'0')}</text>`;
  }
  matrix.grid.forEach((row,dow)=>{
    const y=top+dow*(cellH+gapY);
    svg+=`<text x="0" y="${(y+12.2).toFixed(1)}" fill="#827c8e" font-size="10">${DOW_LABELS[dow]}</text>`;
    row.forEach((cell,h)=>{
      const val=heatmapMode==='count'?cell.count:cell.amount;
      const x=left+h*(cellW+gapX);
      const stroke=val>0&&Math.sqrt(val/maxVal)>0.82?'rgba(242,240,245,0.45)':'rgba(255,255,255,0.04)';
      svg+=`<rect class="heat-cell" data-dow="${dow}" data-hour="${h}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${cellW}" height="${cellH}" rx="2.8" fill="${colorFor(val)}" stroke="${stroke}" stroke-width="0.8"/>`;
    });
  });

  const peakDayTxt=matrix.peakDay?`Пик дня: <strong>${DOW_FULL[matrix.peakDay.dow]} (${matrix.peakDay.count} зак.)</strong>`:'';
  const peakWinTxt=matrix.peakWindow?`Окно: <strong>${String(matrix.peakWindow.startHour).padStart(2,'0')}:00–${String(matrix.peakWindow.endHour).padStart(2,'0')}:00 (${matrix.peakWindow.sharePct}%)</strong>`:'';

  root.innerHTML=`<svg viewBox="0 0 ${vbW} ${vbH}" aria-label="Матрица активности покупок Пн-Вс по часам">${svg}</svg><div class="heatmap-tooltip" hidden></div><div class="heatmap-footer"><div class="heatmap-insights">${peakDayTxt?`<span>${peakDayTxt}</span>`:''}${peakWinTxt?`<span>${peakWinTxt}</span>`:''}</div><div class="heat-scale"><span>0</span>${palette.map(c=>`<i style="background:${c}"></i>`).join('')}<span>Пик</span></div></div>`;

  const tip=root.querySelector('.heatmap-tooltip');
  root.querySelectorAll('.heat-cell').forEach(rect=>{
    rect.onpointerenter=rect.onclick=()=>{
      const dow=Number(rect.dataset.dow),h=Number(rect.dataset.hour);
      const c=matrix.grid[dow][h];
      tip.hidden=false;
      tip.innerHTML=`<span>${DOW_FULL[dow]} · ${String(h).padStart(2,'0')}:00–${String(h).padStart(2,'0')}:59</span><strong>${c.count} зак.</strong><em>${money(c.amount)}</em>`;
      const containerW=root.clientWidth||320;
      const relX=(left+h*(cellW+gapX))/vbW*containerW;
      tip.style.left=Math.max(8,Math.min(relX-65,containerW-162))+'px';
    };
  });
  root.querySelector('svg').onpointerleave=()=>{tip.hidden=true};
}

let chartResizeTimer;
window.addEventListener('resize',()=>{
  clearTimeout(chartResizeTimer);
  chartResizeTimer=setTimeout(()=>{
    if(salesChartState.points.length)drawSalesChart();
  },120);
});
