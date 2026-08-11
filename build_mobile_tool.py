# -*- coding: utf-8 -*-
"""生成单文件手机版预测工具 HTML，数据直接内嵌，无需联网或安装软件。"""
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
OUT = BASE / "手机版预测工具.html"
OUT_INDEX = BASE / "index.html"


def load(name):
    with open(BASE / name, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    dlt = load("data/dlt_history_500.json")
    ssq = load("data/ssq_history_500.json")
    config = load("config.json")
    state = load("model_state.json")
    bt_path = BASE / "mobile_backtest.json"
    backtest = load("mobile_backtest.json") if bt_path.exists() else {
        "dlt": {
            "any_prize": 4.0,
            "layer1": 2.685,
            "layer2": 1.99,
            "layer3": 1.2,
            "main": 0.645,
            "back": 0.35,
        },
        "ssq": {
            "any_prize": 4.0,
            "layer1": 3.635,
            "layer2": 2.745,
            "layer3": 1.68,
            "main": 1.125,
            "back": 0.035,
        },
    }
    payload = {
        "dlt": dlt,
        "ssq": ssq,
        "config": config,
        "model_state": state,
        "backtest": backtest,
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    OUT.write_text(html, encoding="utf-8")
    OUT_INDEX.write_text(html, encoding="utf-8")
    print("saved", OUT, OUT.stat().st_size, "bytes")


TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>彩票技术分析手机版</title>
<style>
:root{--bg:#f3f1ec;--card:#fff;--ink:#24211c;--muted:#6f675b;--line:#ddd6c8;--green:#176b5a;--green2:#0d4f42;--soft:#e6f0ec;--amber:#b45309;--soft2:#f7ead9;--red:#b42318;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.55}
.wrap{max-width:760px;margin:0 auto;padding:16px 14px 40px}
.head{background:var(--green2);color:#fff;border-radius:12px;padding:18px 16px}
.head h1{font-size:20px;font-weight:800}
.head p{font-size:12px;opacity:.85;margin-top:4px}
.btn{width:100%;padding:14px;border:0;border-radius:10px;background:var(--green);color:#fff;font-size:16px;font-weight:800;cursor:pointer;margin:14px 0 6px}
.btn:active{transform:translateY(1px)}
.btn.small{width:auto;padding:8px 14px;font-size:13px;margin-top:8px}
.note{font-size:12px;color:var(--muted);margin:6px 2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:14px}
.card h2{font-size:16px;font-weight:800;margin-bottom:10px}
.game{display:grid;grid-template-columns:1fr;gap:12px;margin-top:10px}
.box{border:1px solid var(--line);border-radius:10px;padding:14px}
.box .name{font-weight:800;font-size:14px}
.box .issue{font-size:12px;color:var(--muted);margin-top:2px}
.combo{font-size:18px;font-weight:800;letter-spacing:1px;margin-top:8px;line-height:1.7}
.combo .back{color:var(--amber)}
.sum{font-size:12px;color:var(--muted);margin-top:6px}
.tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:999px;background:var(--soft);color:var(--green2);margin:2px 3px 0 0}
.tag.cold{background:var(--soft2);color:var(--amber)}
.tag.unpop{background:#e9edf5;color:#344a78}
.layer{margin-top:10px;padding:11px;background:#faf8f3;border:1px solid var(--line);border-radius:9px}
.layer .t{font-size:13px;font-weight:800;margin-bottom:5px}
.layer .nums{font-size:13px;word-break:break-word}
.layer .p{font-size:12px;color:var(--muted);margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
th,td{border:1px solid var(--line);padding:7px 5px;text-align:center}
th{background:var(--soft);color:var(--green2)}
.foot{margin-top:20px;font-size:11px;color:var(--muted);line-height:1.7}
.tabs{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.tab{flex:1;min-width:100px;padding:9px 6px;border:1px solid var(--line);background:#fff;border-radius:9px;font-size:13px;font-weight:700;color:var(--muted)}
.tab.active{background:var(--green);color:#fff;border-color:var(--green)}
.panel{display:none}
.panel.active{display:block}
.ref{background:#fff7f5;border:1px solid #efd3cd;border-radius:10px;padding:12px;font-size:12px;margin-top:10px}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>彩票技术分析手机版</h1>
    <p>超级大乐透 + 双色球 · 单文件离线工具</p>
  </div>
  <button class="btn" id="runBtn">生成下一期预测</button>
  <p class="note" id="genNote"></p>

  <div class="tabs">
    <button class="tab active" data-panel="one">本期一注</button>
    <button class="tab" data-panel="plans">多注方案</button>
    <button class="tab" data-panel="funnel">分层漏斗</button>
    <button class="tab" data-panel="trend">走势冷热</button>
    <button class="tab" data-panel="back">历史回测</button>
  </div>

  <div class="panel active" id="panel-one"></div>
  <div class="panel" id="panel-plans"></div>
  <div class="panel" id="panel-funnel"></div>
  <div class="panel" id="panel-trend"></div>
  <div class="panel" id="panel-back"></div>

  <div class="foot">
    数据更新至 <span id="dataDate"></span>。<br>
    本工具仅用于统计研究与娱乐参考，不构成购彩建议。彩票开奖是独立随机事件，任何工具都无法提高单注中奖概率。<br>
    请理性购彩，量力而行，未成年人禁止购买彩票。
  </div>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const DLT = DATA.dlt, SSQ = DATA.ssq, CFG = DATA.config, STATE = DATA.model_state, BT = DATA.backtest;
const W = STATE.weights || {bayes:0.35,hot:0.25,cold:0.2,trend:0.2};
const BOOST = STATE.position_boost || 0.2;
let RESULT = null;

function nCr(n,k){if(k<0||k>n)return 0;k=Math.min(k,n-k);let r=1;for(let i=0;i<k;i++){r=r*(n-i)/(i+1)}return r}
function range(a,b){const r=[];for(let i=a;i<=b;i++)r.push(i);return r}
function n2(x){return String(x).padStart(2,'0')}
function ranks(vals){const order=vals.map((v,i)=>[v,i]).sort((a,b)=>a[0]-b[0]);const out=new Array(vals.length);order.forEach((it,i)=>out[it[1]]=vals.length>1?i/(vals.length-1):0.5);return out}
function regionRanges(game,zone){if(game==='dlt')return zone==='front'?[[1,12],[13,24],[25,35]]:[[1,4],[5,8],[9,12]];return zone==='red'?[[1,11],[12,22],[23,33]]:[[1,5],[6,11],[12,16]]}
function zoneModel(train,zone,K,k,window){
  const tr=window&&train.length>window?train.slice(-window):train.slice();
  const n=tr.length, counts=new Array(K).fill(0), c30=new Array(K).fill(0), c100=new Array(K).fill(0), r5=new Array(K).fill(0), last=new Array(K).fill(-1);
  const pos=[], sums=[]; for(let p=0;p<k;p++)pos.push(new Array(K).fill(0));
  const s5=Math.max(0,n-5),s30=Math.max(0,n-30),s100=Math.max(0,n-100);
  tr.forEach((row,idx)=>{
    const balls=zone==='blue'?[row.blue]:row[zone].slice();
    balls.sort((a,b)=>a-b);
    sums.push(balls.reduce((a,b)=>a+b,0));
    balls.forEach(b=>{const i=b-1;counts[i]++;last[i]=idx;if(idx>=s100)c100[i]++;if(idx>=s30)c30[i]++;if(idx>=s5)r5[i]++;});
    balls.forEach((b,p)=>{pos[p][b-1]++});
  });
  const mean=sums.reduce((a,b)=>a+b,0)/n, std=Math.sqrt(sums.reduce((a,b)=>a+(b-mean)*(b-mean),0)/Math.max(1,n-1));
  const expRate=k/K, expGap=K/k, expAll=k*n/K;
  const bayes=[],hot=[],cold=[],trend=[],gap=[],feats=[];
  for(let i=0;i<K;i++){
    const g=last[i]>=0?n-1-last[i]:n; gap.push(g);
    bayes.push((1+counts[i])/(K+k*n));
    const hr=c30[i]/Math.max(1,Math.min(30,n)), mr=c100[i]/Math.max(1,Math.min(100,n));
    hot.push(expRate?hr/expRate:0); cold.push(g/expGap); trend.push(hr-mr);
    const z=(counts[i]-expAll)/Math.sqrt(n*expRate*(1-expRate));
    feats.push({number:i+1,count30:c30[i],gap:g,recent5:r5[i],z:isFinite(z)?+z.toFixed(2):0});
  }
  const rb=ranks(bayes),rh=ranks(hot),rc=ranks(cold),rt=ranks(trend),scores=[];
  for(let i=0;i<K;i++)scores.push(W.bayes*rb[i]+W.hot*rh[i]+W.cold*rc[i]+W.trend*rt[i]);
  feats.forEach((f,i)=>{f.score=+scores[i].toFixed(4);f.hotCold=f.count30>=Math.ceil(30*k/K*1.2)?'热':(f.gap>=expGap*1.5?'冷':'中');f.popularity=f.number<=31?'大众':'非大众';});
  const posProb=pos.map(p=>p.map(c=>(1+c)/(n+K)));
  const modes=pos.map(p=>p.indexOf(Math.max(...p))+1);
  return {scores,features:feats,mean,std,positionProb:posProb,positionModes:modes,expectedRate:expRate,kTotal:K,kPerDraw:k};
}
function posFit(zone,nums){nums=nums.slice().sort((a,b)=>a-b);const probs=nums.map((n,p)=>zone.positionProb[p][n-1]);return zone.expectedRate?probs.reduce((a,b)=>a+b,0)/nums.length/zone.expectedRate:1}
function balanced(zone,pool,target,min,ranges){
  pool=Array.from(new Set(pool)).sort((a,b)=>a-b);
  const sel=new Set();
  ranges.forEach(([lo,hi])=>{
    const c=pool.filter(n=>n>=lo&&n<=hi).sort((a,b)=>zone.scores[b-1]-zone.scores[a-1]);
    c.slice(0,Math.min(c.length,min)).forEach(n=>sel.add(n));
  });
  const rem=pool.filter(n=>!sel.has(n)).sort((a,b)=>zone.scores[b-1]-zone.scores[a-1]);
  let need=target-sel.size; if(need>0)rem.slice(0,need).forEach(n=>sel.add(n));
  let out=Array.from(sel).sort((a,b)=>a-b);
  while(out.length>target){out.sort((a,b)=>zone.scores[a-1]-zone.scores[b-1]);out.shift()}
  if(out.length<target){const extra=pool.filter(n=>!out.includes(n)).sort((a,b)=>zone.scores[b-1]-zone.scores[a-1]);out=out.concat(extra.slice(0,target-out.length)).sort((a,b)=>a-b)}
  return out;
}
function* combos(arr,k){if(k===0){yield [];return}for(let i=0;i<=arr.length-k;i++){for(const rest of combos(arr.slice(i+1),k-1))yield [arr[i],...rest]}}
function bestMain(layer3,zone,k){let best=null,bs=-Infinity;for(const c of combos(layer3,k)){const nums=c.slice().sort((a,b)=>a-b);let s=nums.reduce((a,n)=>a+zone.scores[n-1],0);s*=1+BOOST*posFit(zone,nums);if(s>bs){bs=s;best=nums}}return best}
function funnelPick(game,train){
  const dlt=game==='dlt', main=dlt?'front':'red', back=dlt?'back':'blue', K=dlt?35:33, k=dlt?5:6, BK=dlt?12:16, bk=dlt?2:1;
  const zFull=zoneModel(train,main,K,k,500);
  let l1=balanced(zFull,range(1,K),20,4,regionRanges(game,main));
  const z150=zoneModel(train,main,K,k,150);
  let l2=balanced(z150,l1,15,3,regionRanges(game,main));
  const z60=zoneModel(train,main,K,k,60);
  let l3=balanced(z60,l2,9,2,regionRanges(game,main));
  const mainCombo=bestMain(l3,z60,k);
  const zb=zoneModel(train,back,BK,bk,500);
  let bl1=balanced(zb,range(1,BK),8,2,regionRanges(game,back));
  const zb150=zoneModel(train,back,BK,bk,150);
  let bl2=balanced(zb150,bl1,5,1,regionRanges(game,back));
  let backCombo;
  if(dlt){let best=null,bs=-Infinity;for(const c of combos(bl2,2)){const nums=c.slice().sort((a,b)=>a-b);let s=nums.reduce((a,n)=>a+zb150.scores[n-1],0);s*=1+BOOST*posFit(zb,nums);if(s>bs){bs=s;best=nums}}backCombo=best}
  else{let best=null,bs=-Infinity;bl2.forEach(n=>{if(zb150.scores[n-1]>bs){bs=zb150.scores[n-1];best=[n]}});backCombo=best}
  let combo=dlt?[mainCombo,backCombo]:[mainCombo,backCombo];
  const hist=new Set();train.forEach(r=>{hist.add(JSON.stringify(dlt?[r.front,r.back]:[r.red,r.blue]))});
  let guard=0;const key=()=>JSON.stringify(dlt?[combo[0],combo[1]]:[combo[0],combo[1][0]]);
  while(hist.has(key())&&guard<5){guard++;const main=combo[0].slice().sort((a,b)=>z60.scores[a-1]-z60.scores[b-1]);let done=false;for(const n of main){for(const cand of l3.slice().sort((a,b)=>z60.scores[b-1]-z60.scores[a-1])){if(main.includes(cand))continue;const nm=Array.from(new Set([...main.filter(x=>x!==n),cand])).sort((a,b)=>a-b);const nc=dlt?[nm,combo[1]]:[nm,combo[1]];if(!hist.has(JSON.stringify(dlt?[nc[0],nc[1]]:[nc[0],nc[1][0]]))){combo=nc;done=true;break}}if(done)break}if(!done)break}
  return {game,combo,layers:{main:[l1,l2,l3],back:[bl1,bl2]},zones:{mainFull:zFull,main150:z150,main60:z60,backFull:zb,back150:zb150}};
}
function fmt(game,combo){const a=combo[0].map(n2).join('  '), b=game==='dlt'?combo[1].map(n2).join('  '):n2(combo[1][0]);return a+'  +  <span class="back">'+b+'</span>'}
function layerHtml(label,nums,ranges,zone,K,k,extra=''){const counts=ranges.map(([lo,hi])=>nums.filter(n=>n>=lo&&n<=hi).length);const exp=k*nums.length/K,p1=1-nCr(K-nums.length,k)/nCr(K,k);return '<div class="layer"><div class="t">'+label+'</div><div class="nums">'+nums.map(n2).join(' ')+'</div><div class="p">三区域 '+counts.join('/')+'；期望命中 '+exp.toFixed(2)+' 个，至少1个约 '+(p1*100).toFixed(1)+'%'+(extra?'；'+extra:'')+'</div></div>'}
const PLAN_TEXT = {};
function sortedByScore(arr, zone){return arr.slice().sort((a,b)=>zone.scores[b-1]-zone.scores[a-1])}
function planCombos(mainPool,k,backPool,backK,limit){
  const res=[], seen=new Set();let bi=0;
  outer: for(const mc of combos(mainPool,k)){
    const nums=mc.slice().sort((a,b)=>a-b);
    for(let j=0;j<backPool.length;j++){
      let bc;
      if(backK===2){
        const a=backPool[(bi+j)%backPool.length], b=backPool[(bi+j+1)%backPool.length];
        if(a===b) continue;
        bc=[a,b].sort((x,y)=>x-y);
      } else {
        bc=[backPool[(bi+j)%backPool.length]];
      }
      const key=JSON.stringify([nums,bc]);
      if(!seen.has(key)){seen.add(key);res.push({nums,back:bc});if(res.length>=limit)break outer}
    }
    bi++;
  }
  return res;
}
function fmtPlanTicket(game,p){const a=p.nums.map(n2).join(' ');const b=game==='dlt'?p.back.map(n2).join(' '):n2(p.back[0]);return a+' + '+b}
function danTuoPlan(game,pred){
  const main=game==='dlt'?'front':'red', k=game==='dlt'?5:6;
  const z60=pred.zones.main60, back=game==='dlt'?pred.zones.back150:pred.zones.back150;
  const l3=sortedByScore(pred.layers.main[2],z60);
  const l2=sortedByScore(pred.layers.main[1],z60);
  const dan=l3.slice(0,3);
  const tuo=l2.filter(n=>!dan.includes(n)).slice(0,5);
  const backPool=sortedByScore(pred.layers.back[1],back).slice(0,game==='dlt'?2:1);
  const res=[];
  for(const c of combos(tuo, k-dan.length)){
    const nums=dan.concat(c).sort((a,b)=>a-b);
    res.push({nums,back:backPool});
  }
  return res;
}
function plansHtml(dlt,ssq){
  const dltMain=sortedByScore(dlt.layers.main[2],dlt.zones.main60).slice(0,6);
  const dltBack=sortedByScore(dlt.layers.back[1],dlt.zones.back150).slice(0,2);
  const dlt6=dltMain.length>=6&&dltBack.length>=2?planCombos(dltMain,5,dltBack,2,6):[];
  const dltPack=planCombos(sortedByScore(dlt.layers.main[1],dlt.zones.main60),5,sortedByScore(dlt.layers.back[1],dlt.zones.back150),2,210);
  const dltDan=danTuoPlan('dlt',dlt);
  const ssqLayer=sortedByScore(ssq.layers.main[2],ssq.zones.main60);
  const ssqExtra=sortedByScore(ssq.layers.main[1],ssq.zones.main60).filter(n=>!ssqLayer.includes(n));
  const ssqMain=ssqLayer.concat(ssqExtra).slice(0,10);
  const ssqBack=sortedByScore(ssq.layers.back[1],ssq.zones.back150).slice(0,1);
  const ssq210=ssqMain.length>=10&&ssqBack.length>=1?planCombos(ssqMain,6,ssqBack,1,210):[];
  const ssqPack=planCombos(sortedByScore(ssq.layers.main[1],ssq.zones.main60),6,sortedByScore(ssq.layers.back[1],ssq.zones.back150),1,210);
  const ssqDan=danTuoPlan('ssq',ssq);
  PLAN_TEXT['dlt_single']=fmtPlanTicket('dlt',{nums:dlt.combo[0],back:dlt.combo[1]});
  PLAN_TEXT['dlt_6']=dlt6.map(p=>fmtPlanTicket('dlt',p)).join('\\n');
  PLAN_TEXT['dlt_210']=dltPack.map(p=>fmtPlanTicket('dlt',p)).join('\\n');
  PLAN_TEXT['dlt_dan']=dltDan.map(p=>fmtPlanTicket('dlt',p)).join('\\n');
  PLAN_TEXT['ssq_single']=fmtPlanTicket('ssq',{nums:ssq.combo[0],back:ssq.combo[1]});
  PLAN_TEXT['ssq_210']=ssq210.map(p=>fmtPlanTicket('ssq',p)).join('\\n');
  PLAN_TEXT['ssq_pack']=ssqPack.map(p=>fmtPlanTicket('ssq',p)).join('\\n');
  PLAN_TEXT['ssq_dan']=ssqDan.map(p=>fmtPlanTicket('ssq',p)).join('\\n');
  function block(title,desc,tickets,count,key){
    return '<div class="card"><h2>'+title+'</h2><p class="note">'+desc+'</p><div class="nums">'+tickets.slice(0,4).map(t=>fmtPlanTicket(title.indexOf('双色球')>=0?'ssq':'dlt',t)).join('<br>')+'</div><p class="note">共 '+count+' 注</p><button class="btn small copy-btn" data-key="'+key+'">复制全部</button></div>';
  }
  let h='<div class="card"><h2>给客户的多注方案</h2><p class="note">个人自用保留单式一注；客户版提供复式、胆拖和210注组合包。</p></div>';
  h+='<div class="card"><h2>大乐透</h2><p class="note">个人单式：'+PLAN_TEXT['dlt_single']+'</p></div>';
  h+=block('大乐透 6+2 复式','6个前区 + 2个后区',dlt6,dlt6.length,'dlt_6');
  h+=block('大乐透 胆拖','3胆 + 5拖 + 2后区',dltDan,dltDan.length,'dlt_dan');
  h+=block('大乐透 210注组合包','210注单式组合',dltPack,Math.min(210,dltPack.length),'dlt_210');
  h+='<div class="card"><h2>双色球</h2><p class="note">个人单式：'+PLAN_TEXT['ssq_single']+'</p></div>';
  h+=block('双色球 10+1 复式','10个红球 + 1个蓝球',ssq210,Math.min(210,ssq210.length),'ssq_210');
  h+=block('双色球 胆拖','3胆 + 5拖 + 1蓝球',ssqDan,ssqDan.length,'ssq_dan');
  h+=block('双色球 210注组合包','210注单式组合',ssqPack,Math.min(210,ssqPack.length),'ssq_pack');
  return h;
}
function copyPlan(key){
  const text=PLAN_TEXT[key]||'';
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(()=>alert('已复制 '+text.split('\\n').length+' 注'))}
  else alert('当前浏览器不支持一键复制');
}
function render(){
  const dltTrain=DLT.slice().reverse().slice(0,DLT.length-1);
  const ssqTrain=SSQ.slice().reverse().slice(0,SSQ.length-1);
  const dlt=funnelPick('dlt',dltTrain), ssq=funnelPick('ssq',ssqTrain);
  RESULT={dlt,ssq};
  document.getElementById('dataDate').textContent=CFG.generated_at.slice(0,10);
  const one='<div class="game">'+gameCard('大乐透',CFG.dlt_future[0],CFG.dlt_schedule[0].date,fmt('dlt',dlt.combo),dlt)+gameCard('双色球',CFG.ssq_future[0],CFG.ssq_schedule[0].date,fmt('ssq',ssq.combo),ssq)+'</div>';
  document.getElementById('panel-one').innerHTML=one;
  document.getElementById('panel-plans').innerHTML=plansHtml(dlt,ssq);
  document.getElementById('panel-funnel').innerHTML=funnelHtml('大乐透',dlt)+funnelHtml('双色球',ssq);
  document.getElementById('panel-trend').innerHTML=trendHtml('大乐透',dlt)+trendHtml('双色球',ssq);
  document.getElementById('panel-back').innerHTML=backHtml();
  document.getElementById('genNote').textContent='已生成：'+CFG.dlt_future[0]+' / '+CFG.ssq_future[0];
}
function gameCard(name,issue,date,combo,pred){const z=pred.zones.mainFull;const sum=pred.combo[0].reduce((a,b)=>a+b,0);return '<div class="box"><div class="name">'+name+'</div><div class="issue">'+issue+' · '+date+'</div><div class="combo">'+combo+'</div><div class="sum">和值 '+sum+'（参考，不参与选号）</div></div>'}
function funnelHtml(name,pred){const game=name==='大乐透'?'dlt':'ssq', main=game==='dlt'?'front':'red', K=game==='dlt'?35:33, k=game==='dlt'?5:6, z=pred.zones.mainFull, ranges=regionRanges(game,main);let h='<div class="card"><h2>'+name+' 分层漏斗</h2>';h+=layerHtml('第1层 20个',pred.layers.main[0],ranges,z,K,k);h+=layerHtml('第2层 15个',pred.layers.main[1],ranges,z,K,k);h+=layerHtml('第3层 '+pred.layers.main[2].length+'个',pred.layers.main[2],ranges,z,K,k);h+='</div>';return h}
function trendHtml(name,pred){const game=name==='大乐透'?'dlt':'ssq', main=game==='dlt'?'front':'red', by={};pred.zones.mainFull.features.forEach(f=>by[f.number]=f);let h='<div class="card"><h2>'+name+' 走势冷热</h2><table><tr><th>号码</th><th>近30期</th><th>遗漏</th><th>近5期</th><th>热冷</th><th>大众度</th></tr>';pred.combo[0].forEach(n=>{const f=by[n];h+='<tr><td>'+n2(n)+'</td><td>'+f.count30+'</td><td>'+f.gap+'</td><td>'+f.recent5+'</td><td>'+f.hotCold+'</td><td>'+f.popularity+'</td></tr>'});h+='</table></div>';return h}
function backHtml(){const row=(g)=>{const b=BT[g];return '<tr><td>'+ (g==='dlt'?'大乐透':'双色球') +'</td><td>'+b.any_prize+'%</td><td>'+b.layer1+'</td><td>'+b.layer2+'</td><td>'+b.layer3+'</td><td>'+(g==='dlt'?'6.67%':'6.71%')+'</td></tr>'};return '<div class="card"><h2>历史回测（200期）</h2><table><tr><th>玩法</th><th>任意奖级</th><th>第1层</th><th>第2层</th><th>第3层</th><th>随机理论</th></tr>'+row('dlt')+row('ssq')+'</table><div class="ref">回测显示模型命中率低于随机基线，说明工具不能提高单注中奖概率，仅用于研究与娱乐。</div></div>'}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById('panel-'+b.dataset.panel).classList.add('active')}));
document.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('.copy-btn'):null;if(b)copyPlan(b.getAttribute('data-key'));});
document.getElementById('runBtn').addEventListener('click',render);
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
