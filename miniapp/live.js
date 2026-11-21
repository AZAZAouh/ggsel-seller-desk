let state=null,period='month',filter='all',currency='RUB',orderChip='all',month=new Date();month.setDate(1);
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const money=(n,c=currency)=>n==null?'Нет данных':Number(n).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+' '+c;
function moneyParts(n,c=currency){
  if(n==null||!Number.isFinite(Number(n)))return 'Нет данных';
  const formatted=Number(n).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2});
  const idx=formatted.lastIndexOf(',');
  if(idx<0)return `${esc(formatted)}<span class="frac"> ${esc(c)}</span>`;
  return `${esc(formatted.slice(0,idx))}<span class="frac">${esc(formatted.slice(idx))} ${esc(c)}</span>`;
}
const dateKey=d=>Reporting.warsawTime(d)?.day||new Date().toISOString().slice(0,10);

function orderProductName(o){
  const raw=String(o?.name??'').trim();
  if(raw&&!UUID_RE.test(raw))return raw;
  const prod=(state?.data?.products||[]).find(p=>Number(p.id_goods)===Number(o?.item_id));
  return prod?.name_goods?.trim()||raw||'Название не получено';
}

function windowOrders(currFilter=currency,prodFilter=filter){
  const bounds=Reporting.periodBounds(period,new Date());
  return (state?.data?.orders||[]).filter(o=>{
    if(currFilter&&o.currency_type!==currFilter)return false;
    if(prodFilter!=='all'&&String(o.item_id)!==prodFilter)return false;
    const wt=Reporting.warsawTime(o.date_pay||o.purchase_date);
    if(!wt)return false;
    return wt.day>=bounds.start&&wt.day<=bounds.end;
  });
}
const rows=()=>windowOrders(currency,filter);

function notify(t){const el=$('#toast');el.textContent=t;el.classList.add('visible');clearTimeout(notify._t);notify._t=setTimeout(()=>el.classList.remove('visible'),3600)}

async function load(){
  try{
    const r=await fetch('/api/state',{cache:'no-store'});
    if(!r.ok)throw Error();
    state=await r.json();
    render();
  }catch{
    $('#connection').textContent='Сервер недоступен';
    $('#sync-dot')?.classList.add('error');
  }
}

async function post(path,data){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(data)});
  const result=await r.json();
  if(!r.ok)throw Error(result.error||'Ошибка сохранения');
  await load();
  return result;
}

const pageMeta={
  overview:['Обзор магазина','Реальные зачисления, динамика заказов и контроль холда GGsel'],
  products:['Товары и закупки','Настройка себестоимости и переключателей карточек CapCut'],
  orders:['Журнал заказов','Статусы оплат, отзывы, возвраты и учёт себестоимости'],
  finance:['Финансы и реклама','Структура выручки, себестоимости и рекламных расходов']
};

function nav(page){
  document.querySelectorAll('.page').forEach(x=>x.hidden=x.id!==page);
  document.querySelectorAll('[data-page]').forEach(x=>x.classList.toggle('active',x.dataset.page===page));
  const [title,sub]=pageMeta[page]||pageMeta.overview;
  $('#page-title').textContent=title;
  $('#page-subtitle').textContent=sub;
  $('#crumb').textContent=title;
  window.scrollTo(0,0);
  if(page==='overview')requestAnimationFrame(()=>{drawSalesChart();drawActivityHeatmap()});
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>nav(b.dataset.page));
$('.brand').onclick=e=>{e.preventDefault();nav('overview')};

function setCurrency(nextCurr){
  currency=nextCurr;
  $('#currency-filter').value=currency;
  document.querySelectorAll('#currency-pills [data-currency]').forEach(b=>b.classList.toggle('selected',b.dataset.currency===currency));
  render();
}
document.querySelectorAll('#currency-pills [data-currency]').forEach(b=>b.onclick=()=>setCurrency(b.dataset.currency));

function setProductFilter(nextProd){
  filter=nextProd;
  if($('#product-filter'))$('#product-filter').value=filter;
  render();
}

function ringSvg(pct,stroke){
  const p=Math.max(0,Math.min(100,Number(pct)||0));
  return `<svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="14" fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="3.4"/><circle cx="18" cy="18" r="14" fill="none" stroke="${stroke}" stroke-width="3.4" stroke-linecap="round" pathLength="100" stroke-dasharray="${p} 100"/></svg>`;
}

function render(){
  const d=state?.data;
  const syncing=Boolean(state?.status?.syncing);
  const hasErr=Boolean(state?.status?.error);
  $('#refresh')?.classList.toggle('syncing',syncing);
  const dot=$('#sync-dot');
  if(dot){dot.classList.toggle('syncing',syncing);dot.classList.toggle('error',hasErr&&!syncing)}
  $('#connection').textContent=syncing?'Обновляем API…':state?.status?.error||(d?'Обновлено '+new Date(d.updated_at*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})+' · '+new Date(d.updated_at*1000).toLocaleDateString('ru-RU'):'Нет снимка');

  if(!d){$('#real-metrics').innerHTML='<article class="panel panel-body">Нажмите «Обновить из API» для загрузки снимка магазина.</article>';return}

  const navOrders=$('#nav-orders-count'),navProds=$('#nav-products-count');
  if(navOrders){navOrders.hidden=false;navOrders.textContent=d.orders.length}
  if(navProds){navProds.hidden=false;navProds.textContent=d.products.length}

  const options=d.products.map(p=>`<option value="${esc(p.id_goods)}">${esc(p.name_goods)}</option>`).join('');
  $('#product-filter').innerHTML='<option value="all">Все товары ('+d.products.length+')</option>'+options;
  if([...$('#product-filter').options].some(o=>o.value===filter))$('#product-filter').value=filter;else filter='all';
  $('#currency-filter').value=currency;
  document.querySelectorAll('#currency-pills [data-currency]').forEach(b=>b.classList.toggle('selected',b.dataset.currency===currency));
  const oldAdProd=$('#ad-product').value;
  $('#ad-product').innerHTML=options;
  if(oldAdProd)$('#ad-product').value=oldAdProd;

  $('#coverage').textContent=d.coverage;
  $('#reset-product-filter').hidden=filter==='all';
  $('#reset-product-filter').onclick=()=>setProductFilter('all');

  const bounds=Reporting.periodBounds(period,new Date());
  const list=rows();
  const health=Reporting.orderHealth(list,state.settings.order_costs,currency);
  const credit=health.paidAmount,known=health.knownCost,missing=health.missingCount;
  const ads=state.settings.ads.filter(a=>a.currency===currency&&a.date>=bounds.start&&a.date<=bounds.end&&(filter==='all'||a.product_id===filter)).reduce((s,a)=>s+Number(a.amount),0);

  // Helpful hint if 0 paid orders in active currency while other currencies have orders in window
  const hintEl=$('#currency-hint');
  if(health.paidCount===0){
    const alts=['RUB','USD','EUR'].filter(c=>c!==currency).map(c=>{
      const cnt=windowOrders(c,filter).filter(o=>[3,4].includes(Number(o.invoice_state))).length;
      return cnt>0?`<button class="ghost-chip" data-switch-curr="${c}">Есть оплаты в ${c} (${cnt}) →</button>`:'';
    }).filter(Boolean).join('');
    hintEl.innerHTML=alts;
    hintEl.querySelectorAll('[data-switch-curr]').forEach(b=>b.onclick=()=>setCurrency(b.dataset.switchCurr));
  }else hintEl.innerHTML='';

  const now=new Date();
  const bucketed=Reporting.bucketedSeries(list,period,now);
  if(bucketed.missing)$('#coverage').textContent+=` Пропущено без суммы/даты: ${bucketed.missing}.`;

  const historyTruncated=Number(d.received_sales)>=Number(d.requested_limit||1000);
  const pop=Reporting.comparePeriod(d.orders,period,currency,filter,now,historyTruncated);
  let popBadge=`<span class="pill pill--lavender">${esc(currency)}</span>`;
  if(pop&&!pop.truncated){
    if(pop.pct!==null){
      const up=pop.pct>=0;
      const cls=pop.pct>0.2?'pill--emerald':pop.pct<-0.2?'pill--rose':'pill--neutral';
      popBadge=`<span class="pill ${cls} num" title="Сравнение ${esc(pop.label)}">${up?'+':''}${pop.pct.toFixed(1).replace('.',',')}%</span>`;
    }else if(pop.curAmount>0&&pop.prevAmount===0){
      popBadge=`<span class="pill pill--neutral">Пред.: 0</span>`;
    }
  }

  const elapsedDays=Math.max(1,bucketed.granularity==='day'?bucketed.points.length:Math.round((Date.parse(bounds.end+'T00:00:00Z')-Date.parse((period==='all'&&bucketed.points[0]?bucketed.points[0].date.slice(0,10):bounds.start)+'T00:00:00Z'))/86400000)+1);
  const avgCaption=period==='day'?`Ср. чек: <strong>${health.paidCount?money(credit/health.paidCount):'—'}</strong>`:`Ср./день: <strong>${money(credit/elapsedDays)}</strong>`;

  const costBadgeCls=health.paidCount===0?'pill--neutral':missing===0?'pill--emerald':'pill--amber';
  const netResultVal=credit-known-ads;
  const marginPct=credit>0?((netResultVal/credit)*100).toFixed(1).replace('.',','):'0,0';

  const card1=`<article class="metric metric--hero"><header class="metric-head"><span class="metric-label">Зачислено после комиссии</span>${popBadge}</header><div class="metric-value num">${moneyParts(credit)}</div><div class="metric-viz">${kpiSparklineSvg(bucketed.points,'#c8b3dc','spark-rev')}</div><footer class="metric-foot"><span>${avgCaption}</span><span>${pop&&!pop.truncated?esc(pop.label):esc(currency)}</span></footer></article>`;

  const card2=`<article class="metric"><header class="metric-head"><span class="metric-label">Учтено закупок</span><span class="pill ${costBadgeCls} num">${health.costedCount}/${health.paidCount}</span></header><div class="metric-value num">${moneyParts(known)}</div><div class="metric-viz">${kpiCoverageBarSvg(health.costedCount,health.otherCurrCostCount,health.noCostCount)}</div><footer class="metric-foot"><span>Учтено: <strong>${health.costedCount} из ${health.paidCount}</strong></span>${health.otherCurrCostCount?`<span>В др. вал.: ${health.otherCurrCostCount}</span>`:`<span>Без цены: ${health.noCostCount}</span>`}</footer></article>`;

  const card3=missing?`<article class="metric metric--warn"><header class="metric-head"><span class="metric-label">Результат</span><span class="pill pill--amber num">−${missing} зак.</span></header><div class="metric-status-title"><span>Не все закупки учтены</span><button class="inline-action" id="go-fill-costs">Внести →</button></div><div class="metric-viz">${kpiSparklineSvg([],'#dfc07c','spark-warn')}</div><footer class="metric-foot"><span>Реклама: <strong>${money(ads)}</strong></span><span>Ждут цены: ${missing}</span></footer></article>`:`<article class="metric"><header class="metric-head"><span class="metric-label">Результат после расходов</span>${health.paidCount?`<span class="pill ${netResultVal>=0?'pill--emerald':'pill--rose'} num">${marginPct}% маржа</span>`:`<span class="pill pill--neutral">—</span>`}</header><div class="metric-value num">${moneyParts(netResultVal)}</div><div class="metric-viz">${kpiSparklineSvg(bucketed.points,netResultVal>=0?'#6ec498':'#e0828d','spark-net')}</div><footer class="metric-foot"><span>Реклама: <strong>${money(ads)}</strong></span><span>Закупки учтены полностью</span></footer></article>`;

  const card4=`<article class="metric"><header class="metric-head"><span class="metric-label">Оплаченных заказов</span><span class="pill pill--lavender num">★ ${health.reviewPct}% отз.</span></header><div class="metric-value num">${health.paidCount}<span class="frac"> зак.</span></div><div class="metric-viz">${kpiHistogramSvg(bucketed.points)}</div><footer class="metric-foot"><span>Ср. чек: <strong>${health.paidCount?money(credit/health.paidCount):'—'}</strong></span><span>${health.refundCount?`Возвратов: ${health.refundCount}`:`В холде: ${health.holdCount}`}</span></footer></article>`;

  $('#real-metrics').innerHTML=card1+card2+card3+card4;
  if($('#go-fill-costs'))$('#go-fill-costs').onclick=()=>nav('products');

  drawSalesChart(bucketed);
  renderBalanceAndHealth(d,health);
  renderTopProducts(d);
  drawActivityHeatmap(Reporting.activityMatrix(list));
  renderProducts();
  renderOrders(list,health);
  renderHold();
  renderFinance(credit,known,ads,missing,health);
}

const mappings={'104005409':'variant_01M60E6PGWFM88HSH1ZS1X1H1Q','104005436':'variant_01M60E6PGWFM88HSH1ZS1X1H1Q','103376334':'variant_01KSKHJGS2Q8T7VQ7T2K59VGZG'};

function renderBalanceAndHealth(d,health){
  const controls=state.controls||{mode:'dry_run',live_purchases_active:false};
  const badge=$('#mode-badge');
  if(badge){
    badge.textContent=controls.live_purchases_active?'LIVE':controls.mode||'dry_run';
    badge.className='pill '+(controls.live_purchases_active?'pill--emerald':'pill--amber');
  }
  const bal=d.supplier_balance||{};
  const usdVal=bal.usd!=null?Number(bal.usd):null;
  const vndVal=bal.vnd!=null?Number(bal.vnd):null;

  const variants=d.supplier?.variants||[];
  const v7=variants.find(v=>v.id==='variant_01M60E6PGWFM88HSH1ZS1X1H1Q');
  const v30=variants.find(v=>v.id==='variant_01KSKHJGS2Q8T7VQ7T2K59VGZG');
  const slotLine=(label,v)=>{
    if(!v)return '';
    const price=Number(v.prices?.usd||0);
    const qty=Number(v.available_quantity||0);
    const canBuy=price>0&&usdVal!=null?Math.floor(usdVal/price):0;
    return `<div class="slot-row"><div><strong>${label}</strong><small>${money(price,'USD')} · баланс на ~${canBuy} зак.</small></div><div class="slot-right"><span class="pill ${qty>0?'pill--emerald':'pill--amber'}">${qty>0?`В наличии: ${qty} шт.`:'Остаток: 0 шт.'}</span></div></div>`;
  };

  $('#real-balance').innerHTML=`
    <div class="wallet-balances">
      <div class="wallet-primary">${usdVal!=null?moneyParts(usdVal,'USD'):'Баланс недоступен'}</div>
      ${vndVal!=null?`<div class="wallet-secondary">${money(vndVal,'VND')}</div>`:''}
    </div>
    <div class="supplier-slots">
      ${slotLine('CapCut Pro · 7 дней',v7)}
      ${slotLine('CapCut Personal · 30 дней',v30)}
    </div>
    <div class="health-rings">
      <div class="ring-card">${ringSvg(health.reviewPct,'#6ec498')}<div class="ring-meta"><strong>${health.reviewPct}%</strong><span>Отзывы (${health.reviewCount}/${health.paidCount})</span></div></div>
      <div class="ring-card">${ringSvg(health.costPct,'#c8b3dc')}<div class="ring-meta"><strong>${health.costPct}%</strong><span>Закупки (${health.costedCount}/${health.paidCount})</span></div></div>
    </div>
  `;
}

function renderTopProducts(d){
  const allInCurrWindow=windowOrders(currency,'all');
  const ranked=Reporting.topProducts(allInCurrWindow,d.products,orderProductName,5);
  const box=$('#top-products');
  if(!ranked.items.length){
    box.innerHTML=`<div class="chart-empty">Нет продаж в ${esc(currency)} за выбранный период</div>`;
    return;
  }
  let html=ranked.items.map((item,idx)=>`
    <button class="top-prod-row ${filter===item.id?'active':''}" data-pick-prod="${esc(item.id)}" title="Нажмите для фильтрации по товару">
      <div class="top-prod-head">
        <span class="rank-badge">${idx+1}</span>
        <span class="top-prod-title">${esc(item.name)}</span>
        <span class="top-prod-amount">${money(item.credit)}</span>
      </div>
      <div class="top-prod-bar"><i style="width:${Math.max(3,item.barPct).toFixed(1)}%"></i></div>
      <div class="top-prod-meta">
        <span>${item.sharePct.toFixed(1).replace('.',',')}% доли</span>
        <span>· ${item.paidCount} зак.</span>
        <span>· ★ ${item.reviewPct}% отз.</span>
        ${item.refundCount?`<span class="pill pill--rose">↩ ${item.refundCount} возвр.</span>`:''}
        ${!item.visible?`<span class="pill pill--neutral">скрыт</span>`:''}
      </div>
    </button>
  `).join('');
  if(ranked.tail){
    html+=`<div class="top-prod-meta" style="padding:4px 6px 0;justify-content:space-between"><span>Остальные товары (${ranked.tail.count} шт. · ${ranked.tail.paidCount} зак.)</span><strong>${money(ranked.tail.credit)} (${ranked.tail.sharePct.toFixed(1).replace('.',',')}%)</strong></div>`;
  }
  box.innerHTML=html;
  box.querySelectorAll('[data-pick-prod]').forEach(btn=>{
    btn.onclick=()=>setProductFilter(filter===btn.dataset.pickProd?'all':btn.dataset.pickProd);
  });
}

function fulfillmentHint(name){
  const lower=String(name||'').toLowerCase();
  if(lower.includes('canva'))return 'Автовыдача настроена отдельно на стороне площадки — карточка участвует в учёте';
  if(lower.includes('duolingo'))return 'Ручная выдача владельцем — карточка участвует в учёте';
  return 'Карточка для финансового учёта — автовыдача не требуется';
}

function renderProducts(){
  if(!state?.data)return;
  const search=($('#product-search')?.value||'').toLowerCase().trim();
  const controls=state.controls||{mode:'dry_run',live_purchases_active:false,cards:{}};
  $('#product-details').innerHTML=state.data.products.filter(p=>(p.name_goods+' '+p.id_goods).toLowerCase().includes(search)).map(p=>{
    const id=String(p.id_goods),cost=state.settings.costs[id],variant=state.data.supplier?.variants?.find(v=>v.id===mappings[id]),cardCtrl=controls.cards?.[id];
    const capcutBlock=variant&&cardCtrl?`<div class="capcut-controls"><div class="capcut-head"><span>RoboticVN: <strong>${money(variant.prices.usd,'USD')}</strong> · Остаток: <strong>${variant.available_quantity} шт.</strong></span><span class="pill ${controls.live_purchases_active?'pill--emerald':'pill--amber'}">${controls.live_purchases_active?'Боевой режим':'Режим: '+esc(controls.mode)+' — реальные закупки выключены'}</span></div><label class="switch-row"><span>Синхронизация поставщика (${esc(cardCtrl.label)})</span><input type="checkbox" data-card-sync="${id}" ${cardCtrl.sync_enabled?'checked':''}></label><label class="switch-row"><span>Выключатель выдачи этой карточки</span><input type="checkbox" data-card-delivery="${id}" ${cardCtrl.delivery_enabled?'checked':''}></label></div>`:`<p class="fulfillment-note">${esc(fulfillmentHint(p.name_goods))}</p>`;

    return `<article class="panel product-detail"><div class="prod-card-top"><span class="pill ${p.visible?'pill--emerald':'pill--neutral'}">${p.visible?'● В продаже':'● Скрыт'}</span><span class="prod-id">ID ${esc(id)}</span></div><h2>${esc(p.name_goods)}</h2><div class="prod-stats-strip"><div><span>Цена GGsel</span><strong>${money(p.price_usd,'USD')}</strong></div><div><span>Продаж (каталог)</span><strong>${p.cnt_sell??'—'}</strong></div><div><span>Закупка / ед.</span><strong>${cost?money(cost.amount,cost.currency):'Не задана'}</strong></div></div>${capcutBlock}<form class="cost-form" data-product="${id}"><div class="cost-inline"><input name="amount" type="number" min="0" max="10000000" step="0.01" placeholder="Закупка за 1 ед." aria-label="Закупка за единицу" required value="${esc(cost?.amount??'')}"><div class="select-wrap full"><select name="currency" aria-label="Валюта закупки">${['USD','RUB','EUR','VND'].map(c=>`<option ${cost?.currency===c?'selected':''}>${c}</option>`).join('')}</select></div><button class="primary-button">Сохранить</button></div><label class="check-label"><input type="checkbox" name="apply_missing">Применить к загруженным заказам без себестоимости</label></form></article>`;
  }).join('');

  document.querySelectorAll('[data-card-sync]').forEach(cb=>cb.onchange=async()=>{try{await post('/api/card-control',{product_id:cb.dataset.cardSync,sync_enabled:cb.checked});notify('Настройка синхронизации карточки сохранена')}catch(e){notify(e.message)}});
  document.querySelectorAll('[data-card-delivery]').forEach(cb=>cb.onchange=async()=>{try{await post('/api/card-control',{product_id:cb.dataset.cardDelivery,delivery_enabled:cb.checked});notify('Выключатель выдачи карточки сохранён')}catch(e){notify(e.message)}});
  document.querySelectorAll('.cost-form').forEach(f=>f.onsubmit=async e=>{e.preventDefault();const data=new FormData(f);try{await post('/api/cost',{product_id:f.dataset.product,amount:data.get('amount'),currency:data.get('currency'),apply_missing:data.has('apply_missing')});notify('Закупочная стоимость сохранена')}catch(e){notify(e.message)}});
}

function renderOrders(baseList=rows(),health=Reporting.orderHealth(baseList,state?.settings?.order_costs,currency)){
  const chips=[
    ['all',`Все (${baseList.length})`],
    ['paid',`Оплачены (${health.paidCount})`],
    ['refund',`Возвраты (${health.refundCount})`],
    ['reviewed',`С отзывом (${health.reviewCount})`],
    ['nocost',`Без закупки (${health.missingCount})`]
  ];
  const chipBox=$('#order-state-chips');
  if(chipBox){
    chipBox.innerHTML=chips.map(([id,lbl])=>`<button class="filter-chip ${orderChip===id?'active':''}" data-ochip="${id}">${lbl}</button>`).join('');
    chipBox.querySelectorAll('[data-ochip]').forEach(b=>b.onclick=()=>{orderChip=b.dataset.ochip;renderOrders(baseList,health)});
  }
  const q=($('#order-search')?.value||'').toLowerCase().trim();
  const filtered=baseList.filter(o=>{
    const st=Number(o.invoice_state);
    if(orderChip==='paid'&&![3,4].includes(st))return false;
    if(orderChip==='refund'&&st!==5)return false;
    if(orderChip==='reviewed'&&!o.review_present)return false;
    if(orderChip==='nocost'&&(!([3,4].includes(st))||state.settings.order_costs[o.id]?.currency===currency))return false;
    if(q&&!(String(o.id)+' '+orderProductName(o)).toLowerCase().includes(q))return false;
    return true;
  });

  const states={1:['Создан','pill--neutral'],2:['Отменён','pill--neutral'],3:['Оплачен','pill--emerald'],4:['Завершён','pill--emerald'],5:['Возвращён','pill--rose']};
  if(!filtered.length){
    $('#all-orders').innerHTML='<p class="panel-body notice">Нет загруженных заказов по выбранным фильтрам.</p>';
    return;
  }
  const header=`<div class="orders-head"><span>Товар и заказ</span><span>Дата (Warsaw)</span><span>Статус</span><span>Доступно</span><span>Закупка</span><span style="text-align:right">Зачисление</span></div>`;
  const body=filtered.map(o=>{
    const [stName,stCls]=states[o.invoice_state]||['Неизвестен','pill--neutral'];
    const wt=Reporting.warsawTime(o.date_pay||o.purchase_date);
    const dateTxt=wt?`${wt.day.split('-').reverse().join('.')} ${wt.hhmm}`:'Дата неизвестна';
    const cost=state.settings.order_costs[o.id];
    const availTxt=o.available_at?Reporting.formatAvailable(o.available_at):'не получена';
    return `<div class="order-row"><div class="order-main"><strong>${esc(orderProductName(o))}</strong><small>№ ${esc(o.id)}</small></div><div class="order-cell-muted">${esc(dateTxt)}</div><div><span class="pill ${stCls}">${stName}</span> ${o.review_present?'<span class="pill pill--lavender" title="Оставлен отзыв">★</span>':''}</div><div class="order-cell-muted">Доступно: ${esc(availTxt)}</div><div class="order-cell-muted">${cost?esc(money(cost.amount,cost.currency)):'<span style="color:var(--amber)">не внесена</span>'}</div><div class="order-amount-col">${esc(money(o.amount,o.currency_type))}</div></div>`;
  }).join('');
  $('#all-orders').innerHTML=header+body;
}

function renderHold(){
  const y=month.getFullYear(),m=month.getMonth(),prefix=`${y}-${String(m+1).padStart(2,'0')}`,count=new Date(y,m+1,0).getDate(),offset=(new Date(y,m,1).getDay()+6)%7;
  const calendar=Reporting.calendar(state?.data?.orders||[],prefix,currency,filter);
  $('#hold-month').textContent=month.toLocaleDateString('ru-RU',{month:'long',year:'numeric'});
  $('#hold-note').textContent='Только оплаченные заказы (invoice_state = 3). Завершённые и возвраты исключены.';
  $('#hold-selection').textContent=calendar.unknown?`У ${calendar.unknown} оплаченных заказов дата «Доступно» ещё не получена. Они не распределены по календарю.`:'Выберите день для просмотра заказов.';

  const dayEntries=Object.values(calendar.days);
  const maxDaySum=Math.max(1,...dayEntries.map(e=>Object.values(e.totals).reduce((a,b)=>a+b,0)));

  let html='<span></span>'.repeat(offset);
  for(let d=1;d<=count;d++){
    const key=prefix+'-'+String(d).padStart(2,'0'),entry=calendar.days[key];
    let heat=0;
    if(entry){
      const sum=Object.values(entry.totals).reduce((a,b)=>a+b,0);
      const ratio=sum/maxDaySum;
      heat=ratio>0.75?4:ratio>0.4?3:ratio>0.15?2:1;
    }
    html+=`<button class="calendar-day ${entry?'has-money':''}" ${heat?`data-heat="${heat}"`:''} data-available-day="${key}" aria-label="${key}${entry?', есть поступления':''}"><span>${d}</span>${entry?Object.entries(entry.totals).map(([c,n])=>`<strong>${money(n,c)}</strong>`).join(''):''}</button>`;
  }
  $('#hold-calendar').innerHTML=html;
  document.querySelectorAll('[data-available-day]').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('[data-available-day]').forEach(x=>x.classList.toggle('chosen',x===b));
    const entry=calendar.days[b.dataset.availableDay];
    $('#hold-selection').innerHTML=entry?entry.orders.map(o=>`<div class="hold-order"><strong>${esc(orderProductName(o))}</strong><br>Заказ № ${esc(o.id)}<br>${money(o.amount,o.currency_type)}<br>Доступно: ${esc(Reporting.formatAvailable(o.available_at))}<br><small>${o.availability_source==='user_confirmed_ggsel_column'?'Подтверждено вами из колонки «Доступно»':'Данные GGsel'}</small></div>`).join(''):'На эту дату нет заказов с подтверждённым временем анхолда.';
  });
}

function renderFinance(credit,known,ads,missing,health){
  const denom=Math.max(0.01,credit,known+ads);
  const wCost=Math.min(100,(known/denom)*100);
  const wAds=Math.min(100-wCost,(ads/denom)*100);
  const wRest=Math.max(0,100-wCost-wAds);

  const allocBar=credit>0?`<div class="alloc-bar-wrap"><svg viewBox="0 0 300 12" width="100%" height="12" aria-label="Распределение зачислений"><defs><pattern id="unverified-hatch" width="6" height="6" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse"><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(223,192,124,0.38)" stroke-width="2.5"/></pattern></defs><rect x="0" y="0" width="300" height="12" rx="6" fill="rgba(255,255,255,0.05)"/>${wCost>0?`<rect x="0" y="0" width="${(wCost*3).toFixed(1)}" height="12" fill="#9a82b8"/>`:''}${wAds>0?`<rect x="${(wCost*3).toFixed(1)}" y="0" width="${(wAds*3).toFixed(1)}" height="12" fill="#dfc07c"/>`:''}${wRest>0?`<rect x="${((wCost+wAds)*3).toFixed(1)}" y="0" width="${(wRest*3).toFixed(1)}" height="12" fill="${missing?'url(#unverified-hatch)':'#6ec498'}"/>`:''}</svg><div class="alloc-legend"><span><i class="alloc-dot" style="background:#9a82b8"></i>Закупки</span><span><i class="alloc-dot" style="background:#dfc07c"></i>Реклама</span><span><i class="alloc-dot" style="background:${missing?'#dfc07c66':'#6ec498'}"></i>${missing?'Ожидает себестоимости':'Чистый результат'}</span></div></div>`:'';

  $('#finance-summary').innerHTML=`
    ${allocBar}
    <div class="ledger-row"><span>Зачислено после комиссии (${health.paidCount} зак.)</span><strong>${money(credit)}</strong></div>
    <div class="ledger-row"><span>Подтверждённые закупки (${health.costedCount} зак.)</span><strong>${money(known)}</strong></div>
    <div class="ledger-row"><span>Расходы на рекламу за период</span><strong>${money(ads)}</strong></div>
    <div class="ledger-row"><span>Итоговый результат (${esc(currency)})</span><strong>${missing?`Не все закупки учтены (${missing} зак.)`:money(credit-known-ads)}</strong></div>
    <p class="notice" style="margin-top:12px">Разные валюты не смешиваются. Каталожная цена RoboticVN не подставляется задним числом в старые заказы.</p>
  `;

  const d=state.data;
  $('#ad-list').innerHTML=state.settings.ads.length?state.settings.ads.slice().reverse().map(a=>`<div class="ad-table-row"><span class="num" style="color:var(--text-muted)">${esc(a.date)}</span><span>${esc(d.products.find(p=>String(p.id_goods)===a.product_id)?.name_goods||a.product_id)}</span><strong class="num">${money(a.amount,a.currency)}</strong></div>`).join(''):'<p class="notice">Рекламные расходы ещё не внесены.</p>';
}

$('#month-prev').onclick=()=>{month.setMonth(month.getMonth()-1);renderHold()};
$('#month-next').onclick=()=>{month.setMonth(month.getMonth()+1);renderHold()};
$('#product-search').oninput=renderProducts;
if($('#order-search'))$('#order-search').oninput=()=>renderOrders();

document.querySelectorAll('[data-period]').forEach(b=>b.onclick=()=>{
  period=b.dataset.period;
  document.querySelectorAll('[data-period]').forEach(x=>x.classList.toggle('selected',x===b));
  render();
});
$('#product-filter').onchange=e=>setProductFilter(e.target.value);
$('#currency-filter').onchange=e=>setCurrency(e.target.value);

$('#refresh').onclick=async()=>{try{await post('/api/refresh',{});notify('Обновление из API запущено')}catch(e){notify(e.message)}};
$('#ad-form [name=date]').value=dateKey(new Date());
$('#ad-form').onsubmit=async e=>{
  e.preventDefault();
  const f=new FormData(e.target);
  try{
    await post('/api/ad',Object.fromEntries(f));
    e.target.elements.amount.value='';
    notify('Рекламный расход сохранён');
  }catch(e){notify(e.message)}
};
$('#notifications').onclick=()=>notify('Уведомления о выдаче отправляются владельцу в Telegram-бот @AZAZAggselbot.');

load();
setInterval(()=>{if(state?.status?.syncing)load()},4000);

async function downloadOfficeHolds() {
  if (location.origin !== 'https://seller.ggsel.com') return alert('Откройте кабинет продавца GGsel.');
  try {
    const dates = {}, seen = new Set();
    for (let page = 1; ; page++) {
      const query = new URLSearchParams({'filter[status]':'paid', page, limit:50});
      const response = await fetch('/api/v1/orders?' + query, {headers:{Accept:'application/json'}});
      if (!response.ok) throw Error('GGsel: ' + response.status);
      const {data} = await response.json();
      if (!Array.isArray(data)) throw Error('Не удалось прочитать список заказов');
      if (!data.length) break;
      for (const order of data) {
        if (!order.number || seen.has(order.number)) throw Error('Не удалось проверить полноту списка');
        seen.add(order.number);
        if (order.status === 'paid' && order.seller_reward_complete_at) {
          dates[order.number] = order.seller_reward_complete_at;
        }
      }
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify({dates})], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = 'ggsel-holds.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (error) { alert(error.message); }
}
$('#export-holds').href = 'javascript:(' + downloadOfficeHolds.toString() + ')();void 0';
$('#import-holds').onchange = async event => {
  try {
    const payload = JSON.parse(await event.target.files[0].text());
    await post('/api/holds',payload);
    notify('Календарь обновлён');
  } catch { notify('Не удалось загрузить даты. Проверьте файл из кабинета GGsel.'); }
  event.target.value = '';
};
