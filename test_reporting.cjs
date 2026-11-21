const assert=require('node:assert/strict');
const report=require('./miniapp/reporting.js');
const order={id:'1',item_id:10,invoice_state:3,amount:1.25,currency_type:'USD',date_pay:'2026-11-06T12:20:00+03:00',available_at:'2026-11-13T12:20:00+03:00',availability_source:'verified-order-field'};
let result=report.calendar([order,{...order,id:'2',invoice_state:4},{...order,id:'3',invoice_state:5},{...order,id:'4',available_at:null}],'2026-11','USD');
assert.equal(result.days['2026-11-13'].orders.length,1);
assert.equal(result.days['2026-11-13'].totals.USD,1.25);
assert.equal(result.unknown,1);
result=report.calendar([order,{...order,id:'5',currency_type:'RUB',amount:100}],'2026-11','USD');
assert.deepEqual(result.days['2026-11-13'].totals,{USD:1.25,RUB:100});
assert.equal(report.calendar([{...order,availability_source:null}],'2026-11','USD').unknown,1);
// Naive local time (owner-confirmed Warsaw column) stays unshifted; offset ISO converts to Europe/Warsaw
assert.equal(report.formatAvailable('2026-11-12T21:05'),'2026-11-12 21:05');
assert.equal(report.formatAvailable('2026-11-12T23:05:59+03:00'),'2026-11-12 21:05');
const midnightMoscow={...order,id:'6',available_at:'2026-11-13T00:30:00+03:00'};
assert.equal(report.calendar([midnightMoscow],'2026-11','USD').days['2026-11-12'].orders.length,1);
assert.deepEqual(report.series([order,{...order,amount:2.5},{...order,invoice_state:5}],'day').entries,[['2026-11-06T12:00:00',3.75]]);
assert.deepEqual(report.series([order,{...order,date_pay:'2026-11-07T15:00:00+03:00'}],'year').entries,[['2026-11-01',2.5]]);
assert.equal(report.series([{...order,amount:null}],'month').missing,1);

// Verify Warsaw late-evening conversion (+03:00 -> Europe/Warsaw previous calendar day)
const lateOrder={...order,id:'7',date_pay:'2026-11-17T00:18:33+03:00',amount:10};
assert.equal(report.warsawTime(lateOrder.date_pay).day,'2026-11-16');
assert.equal(report.warsawTime(lateOrder.date_pay).hour,22);

// Continuous zero-filled weekly buckets
const anchor=new Date('2026-11-17T20:00:00Z');
const wk=report.bucketedSeries([lateOrder],'week',anchor);
assert.equal(wk.points.length,7);
assert.equal(wk.points.find(p=>p.date==='2026-11-16').value,10);
assert.equal(wk.points.find(p=>p.date==='2026-11-15').value,0);

// Top products, activity matrix, and order health
const tp=report.topProducts([lateOrder,{...order,id:'8',item_id:20,amount:5,review_present:true},{...order,id:'9',item_id:20,invoice_state:5,amount:5}],[{id_goods:10,name_goods:'Prod A',visible:1},{id_goods:20,name_goods:'Prod B',visible:0}]);
assert.equal(tp.items[0].id,'10');
assert.equal(tp.items[1].refundCount,1);
assert.equal(tp.items[1].reviewPct,100);

const mat=report.activityMatrix([lateOrder]);
assert.equal(mat.totalCount,1);
assert.equal(mat.grid[0][22].count,1); // 2026-11-16 is Monday (dow=0), 22:18 Warsaw

const hlth=report.orderHealth([lateOrder,{...order,id:'9',invoice_state:5}],{'7':{amount:'2.00',currency:'USD'}},'USD');
assert.equal(hlth.paidCount,1);
assert.equal(hlth.costedCount,1);
assert.equal(hlth.missingCount,0);
assert.equal(hlth.refundCount,1);

console.log('Reporting checks passed: statuses, Warsaw local times, zero-filled series, top products, heatmap matrix, order health.');
