const Reporting=(()=>{
  const validAmount=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
  const day=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}/.test(value)?value.slice(0,10):null;
  const warsawFmt=new Intl.DateTimeFormat('en-CA',{
    timeZone:'Europe/Warsaw',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'
  });
  const warsawDowFmt=new Intl.DateTimeFormat('en-US',{
    timeZone:'Europe/Warsaw',weekday:'short'
  });
  const DOW_MAP={Mon:0,Tue:1,Wed:2,Thu:3,Fri:4,Sat:5,Sun:6};

  function warsawTime(value){
    if(typeof value!=='string'&&!(value instanceof Date))return null;
    if(value instanceof Date){
      const ms=value.getTime();
      if(!Number.isFinite(ms))return null;
      const parts=Object.fromEntries(warsawFmt.formatToParts(value).map(p=>[p.type,p.value]));
      const dow=DOW_MAP[warsawDowFmt.format(value)]??0;
      const d=`${parts.year}-${parts.month}-${parts.day}`;
      const h=Number(parts.hour),m=Number(parts.minute);
      return {ms,day:d,month:`${parts.year}-${parts.month}`,year:parts.year,hour:h,minute:m,dow,hhmm:`${parts.hour}:${parts.minute}`};
    }
    const s=value.trim();
    if(!s)return null;
    if(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(s)){
      const ms=Date.parse(s);
      if(!Number.isFinite(ms))return null;
      return warsawTime(new Date(ms));
    }
    const m=s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
    if(!m)return null;
    const d=`${m[1]}-${m[2]}-${m[3]}`,h=Number(m[4]||0),min=Number(m[5]||0);
    const utcDate=new Date(Date.UTC(Number(m[1]),Number(m[2])-1,Number(m[3]),12,0,0));
    const dow=(utcDate.getUTCDay()+6)%7;
    return {ms:utcDate.getTime(),day:d,month:`${m[1]}-${m[2]}`,year:m[1],hour:h,minute:min,dow,hhmm:`${String(h).padStart(2,'0')}:${String(min).padStart(2,'0')}`};
  }

  function localAvailable(value){
    if(typeof value!=='string'||!value.trim())return null;
    const s=value.trim();
    if(/^\d{4}-\d{2}-\d{2}$/.test(s))return {day:s,time:null,sortKey:s+'T00:00',display:s};
    if(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(s)){
      const w=warsawTime(s);
      if(!w)return null;
      return {day:w.day,time:w.hhmm,sortKey:`${w.day}T${w.hhmm}`,display:`${w.day} ${w.hhmm}`};
    }
    const m=s.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
    if(m)return {day:m[1],time:m[2],sortKey:`${m[1]}T${m[2]}`,display:`${m[1]} ${m[2]}`};
    return null;
  }

  const formatAvailable=value=>localAvailable(value)?.display||'';

  function holdOrders(orders){
    return orders.filter(o=>Number(o.invoice_state)===3);
  }

  function calendar(orders,month,currency,product='all'){
    const paid=holdOrders(orders).filter(o=>product==='all'||String(o.item_id)===product);
    const days={};let unknown=0;
    for(const order of paid){
      const loc=localAvailable(order.available_at);
      if(!order.available_at||!order.availability_source||!loc){unknown++;continue}
      if(!loc.day.startsWith(month))continue;
      const key=loc.day;
      if(!days[key])days[key]={orders:[],totals:{},missingAmount:0};
      days[key].orders.push({...order,_sortKey:loc.sortKey});
      const c=order.currency_type;
      if(validAmount(order.amount)&&c)days[key].totals[c]=(days[key].totals[c]||0)+Number(order.amount);
      else days[key].missingAmount++;
    }
    for(const d of Object.values(days)){
      d.orders.sort((a,b)=>a._sortKey.localeCompare(b._sortKey));
      d.orders=d.orders.map(({_sortKey,...rest})=>rest);
    }
    return {days,unknown,paid:paid.length};
  }

  function series(orders,period){
    const groups={};let missing=0;
    for(const o of orders){
      if(![3,4].includes(Number(o.invoice_state)))continue;
      const stamp=o.date_pay||o.purchase_date;
      if(!day(stamp)||!validAmount(o.amount)){missing++;continue}
      let key=day(stamp);
      if(period==='day'&&/^\d{4}-\d{2}-\d{2}T\d{2}:/.test(stamp))key=stamp.slice(0,13)+':00:00';
      if(period==='year')key=stamp.slice(0,7)+'-01';
      groups[key]=(groups[key]||0)+Math.round(Number(o.amount)*100);
    }
    return {entries:Object.entries(groups).sort().map(([key,cents])=>[key,cents/100]),missing};
  }

  function addDays(ymd,delta){
    const [y,m,d]=ymd.split('-').map(Number);
    const dt=new Date(Date.UTC(y,m-1,d+delta,12,0,0));
    return dt.toISOString().slice(0,10);
  }

  function periodBounds(period,now=new Date()){
    const w=warsawTime(now);
    const today=w.day;
    if(period==='day')return {start:today,end:today,warsawNow:w};
    if(period==='week')return {start:addDays(today,-6),end:today,warsawNow:w};
    if(period==='month')return {start:today.slice(0,8)+'01',end:today,warsawNow:w};
    if(period==='year')return {start:today.slice(0,5)+'01-01',end:today,warsawNow:w};
    return {start:'0000-01-01',end:today,warsawNow:w};
  }

  function bucketedSeries(orders,period,now=new Date()){
    const wNow=warsawTime(now);
    const paid=[];let missing=0;
    for(const o of orders){
      if(![3,4].includes(Number(o.invoice_state)))continue;
      const wt=warsawTime(o.date_pay||o.purchase_date);
      if(!wt||!validAmount(o.amount)){missing++;continue}
      paid.push({o,wt,cents:Math.round(Number(o.amount)*100)});
    }
    if(!paid.length)return {points:[],missing,granularity:period==='day'?'hour':period==='year'?'month':'day'};

    let granularity='day';
    const buckets=new Map();

    if(period==='day'||(period==='month'&&wNow.day.endsWith('-01'))){
      granularity='hour';
      for(let h=0;h<=wNow.hour;h++){
        const k=`${wNow.day}T${String(h).padStart(2,'0')}:00:00`;
        buckets.set(k,{date:k,cents:0,count:0});
      }
      for(const p of paid){
        if(p.wt.day!==wNow.day)continue;
        const k=`${p.wt.day}T${String(p.wt.hour).padStart(2,'0')}:00:00`;
        if(!buckets.has(k))buckets.set(k,{date:k,cents:0,count:0});
        const b=buckets.get(k);b.cents+=p.cents;b.count++;
      }
    }else if(period==='week'||period==='month'){
      granularity='day';
      const start=period==='week'?addDays(wNow.day,-6):wNow.day.slice(0,8)+'01';
      for(let cur=start;cur<=wNow.day;cur=addDays(cur,1)){
        buckets.set(cur,{date:cur,cents:0,count:0});
      }
      for(const p of paid){
        if(p.wt.day<start||p.wt.day>wNow.day)continue;
        const b=buckets.get(p.wt.day);
        if(b){b.cents+=p.cents;b.count++}
      }
    }else if(period==='year'&&!wNow.day.startsWith(wNow.year+'-01-')){
      granularity='month';
      const curMonth=Number(wNow.day.slice(5,7));
      for(let m=1;m<=curMonth;m++){
        const k=`${wNow.year}-${String(m).padStart(2,'0')}-01`;
        buckets.set(k,{date:k,cents:0,count:0});
      }
      for(const p of paid){
        if(p.wt.year!==wNow.year)continue;
        const k=`${p.wt.month}-01`;
        const b=buckets.get(k);
        if(b){b.cents+=p.cents;b.count++}
      }
    }else{
      const minDay=paid.reduce((m,p)=>p.wt.day<m?p.wt.day:m,paid[0].wt.day);
      const maxDay=wNow.day>minDay?wNow.day:minDay;
      const spanDays=Math.max(1,Math.round((Date.parse(maxDay+'T00:00:00Z')-Date.parse(minDay+'T00:00:00Z'))/86400000)+1);
      if(spanDays<=62){
        granularity='day';
        for(let cur=minDay;cur<=maxDay;cur=addDays(cur,1))buckets.set(cur,{date:cur,cents:0,count:0});
        for(const p of paid){const b=buckets.get(p.wt.day);if(b){b.cents+=p.cents;b.count++}}
      }else if(spanDays<=540){
        granularity='week';
        const weekMonday=ymd=>{const wt=warsawTime(ymd);return addDays(ymd,-wt.dow)};
        const firstMon=weekMonday(minDay),lastMon=weekMonday(maxDay);
        for(let cur=firstMon;cur<=lastMon;cur=addDays(cur,7))buckets.set(cur,{date:cur,cents:0,count:0});
        for(const p of paid){const k=weekMonday(p.wt.day);const b=buckets.get(k);if(b){b.cents+=p.cents;b.count++}}
      }else{
        granularity='month';
        for(const p of paid){
          const k=`${p.wt.month}-01`;
          if(!buckets.has(k))buckets.set(k,{date:k,cents:0,count:0});
          const b=buckets.get(k);b.cents+=p.cents;b.count++;
        }
      }
    }

    const points=[...buckets.values()].sort((a,b)=>a.date.localeCompare(b.date)).map(b=>({
      date:b.date,value:b.cents/100,count:b.count
    }));
    return {points,missing,granularity};
  }

  function comparePeriod(allOrders,period,currency,product='all',now=new Date(),historyTruncated=false){
    if(period==='all')return null;
    const wNow=warsawTime(now);
    const minutesNow=wNow.hour*60+wNow.minute;
    let curStart,curEnd=wNow.day,prevStart,prevEnd,label;

    if(period==='day'){
      curStart=wNow.day;
      prevStart=prevEnd=addDays(wNow.day,-1);
      label=`к вчера (${wNow.hhmm})`;
    }else if(period==='week'){
      curStart=addDays(wNow.day,-6);
      prevStart=addDays(wNow.day,-13);
      prevEnd=addDays(wNow.day,-7);
      label='к пред. 7 дн.';
    }else if(period==='month'){
      const [y,m,d]=wNow.day.split('-').map(Number);
      curStart=`${wNow.month}-01`;
      const prevMonthLast=new Date(Date.UTC(y,m-1,0));
      const py=prevMonthLast.getUTCFullYear(),pm=String(prevMonthLast.getUTCMonth()+1).padStart(2,'0');
      const pd=String(Math.min(d,prevMonthLast.getUTCDate())).padStart(2,'0');
      prevStart=`${py}-${pm}-01`;
      prevEnd=`${py}-${pm}-${pd}`;
      label=`к 1–${Number(pd)}.${pm}`;
    }else if(period==='year'){
      const y=Number(wNow.year)-1;
      curStart=`${wNow.year}-01-01`;
      prevStart=`${y}-01-01`;
      prevEnd=`${y}-${wNow.day.slice(5)}`;
      label=`к ${y}`;
    }else return null;

    let oldestDay='9999-99-99',curCents=0,prevCents=0,curCount=0,prevCount=0;
    for(const o of allOrders){
      const wt=warsawTime(o.date_pay||o.purchase_date);
      if(!wt)continue;
      if(wt.day<oldestDay)oldestDay=wt.day;
      if(o.currency_type!==currency)continue;
      if(product!=='all'&&String(o.item_id)!==product)continue;
      if(![3,4].includes(Number(o.invoice_state))||!validAmount(o.amount))continue;
      const mins=wt.hour*60+wt.minute;
      const cents=Math.round(Number(o.amount)*100);
      if(wt.day>=curStart&&wt.day<=curEnd&&(wt.day<curEnd||mins<=minutesNow)){
        curCents+=cents;curCount++;
      }else if(wt.day>=prevStart&&wt.day<=prevEnd&&(wt.day<prevEnd||mins<=minutesNow)){
        prevCents+=cents;prevCount++;
      }
    }

    if(historyTruncated&&prevStart<oldestDay)return {truncated:true,label:'вне глубины истории'};
    const pct=prevCents>0?((curCents-prevCents)/prevCents)*100:null;
    return {
      curAmount:curCents/100,prevAmount:prevCents/100,
      curCount,prevCount,countDiff:curCount-prevCount,
      pct,label,truncated:false
    };
  }

  function topProducts(ordersInWindow,products,resolveName,limit=5){
    const catalog=new Map((products||[]).map(p=>[String(p.id_goods),p]));
    const groups=new Map();
    let totalCents=0;
    for(const o of ordersInWindow){
      const pid=String(o.item_id??'unknown');
      if(!groups.has(pid)){
        const prod=catalog.get(pid);
        groups.set(pid,{
          id:pid,
          name:resolveName?resolveName(o):(prod?.name_goods||o.name||pid),
          visible:prod?Boolean(prod.visible):true,
          cents:0,paidCount:0,reviewCount:0,refundCount:0
        });
      }
      const g=groups.get(pid);
      const st=Number(o.invoice_state);
      if([3,4].includes(st)&&validAmount(o.amount)){
        const c=Math.round(Number(o.amount)*100);
        g.cents+=c;totalCents+=c;g.paidCount++;
        if(o.review_present)g.reviewCount++;
      }else if(st===5){
        g.refundCount++;
      }
    }
    const sorted=[...groups.values()].filter(g=>g.paidCount>0||g.refundCount>0).sort((a,b)=>b.cents-a.cents||b.paidCount-a.paidCount);
    const maxCents=sorted[0]?.cents||1;
    const head=sorted.slice(0,limit).map(g=>({
      ...g,
      credit:g.cents/100,
      sharePct:totalCents>0?(g.cents/totalCents)*100:0,
      barPct:maxCents>0?(g.cents/maxCents)*100:0,
      reviewPct:g.paidCount>0?Math.round((g.reviewCount/g.paidCount)*100):0
    }));
    const tailList=sorted.slice(limit).filter(g=>g.paidCount>0);
    const tail=tailList.length?{
      count:tailList.length,
      paidCount:tailList.reduce((s,g)=>s+g.paidCount,0),
      credit:tailList.reduce((s,g)=>s+g.cents,0)/100,
      sharePct:totalCents>0?(tailList.reduce((s,g)=>s+g.cents,0)/totalCents)*100:0
    }:null;
    return {items:head,tail,totalCredit:totalCents/100};
  }

  function activityMatrix(orders){
    const grid=Array.from({length:7},()=>Array.from({length:24},()=>({count:0,cents:0})));
    let totalCount=0,totalCents=0;
    for(const o of orders){
      if(![3,4].includes(Number(o.invoice_state))||!validAmount(o.amount))continue;
      const wt=warsawTime(o.date_pay||o.purchase_date);
      if(!wt)continue;
      const cell=grid[wt.dow][wt.hour];
      const c=Math.round(Number(o.amount)*100);
      cell.count++;cell.cents+=c;
      totalCount++;totalCents+=c;
    }
    let maxCount=0,maxCents=0;
    const dayTotals=grid.map((row,dow)=>{
      let cnt=0,cents=0;
      row.forEach(cell=>{
        cnt+=cell.count;cents+=cell.cents;
        if(cell.count>maxCount)maxCount=cell.count;
        if(cell.cents>maxCents)maxCents=cell.cents;
      });
      return {dow,count:cnt,amount:cents/100};
    });
    const hourTotals=Array.from({length:24},(_,h)=>grid.reduce((s,row)=>s+row[h].count,0));
    let bestWindowStart=0,bestWindowCount=0;
    for(let h=0;h<=21;h++){
      const sum=hourTotals[h]+hourTotals[h+1]+hourTotals[h+2];
      if(sum>bestWindowCount){bestWindowCount=sum;bestWindowStart=h}
    }
    const peakDay=[...dayTotals].sort((a,b)=>b.count-a.count||b.amount-a.amount)[0];
    return {
      grid:grid.map(row=>row.map(c=>({count:c.count,amount:c.cents/100}))),
      maxCount,maxAmount:maxCents/100,totalCount,totalAmount:totalCents/100,
      peakDay:peakDay?.count>0?peakDay:null,
      peakWindow:bestWindowCount>0?{
        startHour:bestWindowStart,
        endHour:bestWindowStart+3,
        count:bestWindowCount,
        sharePct:Math.round((bestWindowCount/totalCount)*100)
      }:null
    };
  }

  function orderHealth(ordersInWindow,orderCosts,currency){
    let holdCount=0,holdCents=0,doneCount=0,doneCents=0,refundCount=0,refundCents=0,otherCount=0;
    let reviewCount=0,costedCount=0,otherCurrCostCount=0,knownCostCents=0;
    for(const o of ordersInWindow){
      const st=Number(o.invoice_state);
      const amt=validAmount(o.amount)?Math.round(Number(o.amount)*100):0;
      if(st===3){holdCount++;holdCents+=amt}
      else if(st===4){doneCount++;doneCents+=amt}
      else if(st===5){refundCount++;refundCents+=amt}
      else otherCount++;
      if(st===3||st===4){
        if(o.review_present)reviewCount++;
        const cost=orderCosts?.[o.id];
        if(cost&&validAmount(cost.amount)){
          if(cost.currency===currency){
            costedCount++;
            knownCostCents+=Math.round(Number(cost.amount)*100);
          }else otherCurrCostCount++;
        }
      }
    }
    const paidCount=holdCount+doneCount;
    const noCostCount=Math.max(0,paidCount-costedCount-otherCurrCostCount);
    return {
      paidCount,paidAmount:(holdCents+doneCents)/100,
      holdCount,holdAmount:holdCents/100,
      doneCount,doneAmount:doneCents/100,
      refundCount,refundAmount:refundCents/100,
      otherCount,
      reviewCount,reviewPct:paidCount>0?Math.round((reviewCount/paidCount)*100):0,
      costedCount,otherCurrCostCount,noCostCount,
      missingCount:paidCount-costedCount,
      costPct:paidCount>0?Math.round((costedCount/paidCount)*100):0,
      knownCost:knownCostCents/100
    };
  }

  return {
    validAmount,day,warsawTime,periodBounds,localAvailable,formatAvailable,
    holdOrders,calendar,series,bucketedSeries,comparePeriod,topProducts,activityMatrix,orderHealth
  };
})();
if(typeof module!=='undefined')module.exports=Reporting;
