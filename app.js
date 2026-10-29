const $ = (id) => document.getElementById(id);
let currentMode = 'cluster';
let latestData = null;
let refreshTimer = null;
const fmt = (n, digits=4) => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toLocaleString('en-US',{maximumFractionDigits:digits});
const priceFmt = (n) => { const v=Number(n); if(!Number.isFinite(v)) return '—'; return v>=1000?v.toLocaleString('en-US',{maximumFractionDigits:2}):v>=1?v.toLocaleString('en-US',{maximumFractionDigits:4}):v>=0.01?v.toLocaleString('en-US',{maximumFractionDigits:6}):v.toLocaleString('en-US',{maximumFractionDigits:9}); };
const pct = n => `${fmt(n,3)}%`;
function timeFmt(value){ if(!value)return '等待資料'; const d=new Date(value); return d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit',hour12:false}); }
function pillClass(text){ if(/金叉|偏多/.test(text))return 'green'; if(/死叉|偏空/.test(text))return 'red'; if(/可能/.test(text))return 'blue'; if(/重合/.test(text))return 'amber'; return 'gray'; }
function scoreCell(n){return `<span class="score"><span>${fmt(n,1)}</span><span class="score-track"><span class="score-fill" style="display:block;width:${Math.max(0,Math.min(100,Number(n)||0))}%"></span></span></span>`;}
function renderHeader(mode){
 const h=$('tableHead');
 if(mode==='resonance'){h.innerHTML='<tr><th>排名 / 幣種</th><th>共振分數</th><th>1H 糾纏</th><th>4H 糾纏</th><th>1H 狀態</th><th>4H 狀態</th><th>方向一致</th></tr>';return;}
 h.innerHTML='<tr><th>排名 / 幣種</th><th>最新價格*</th><th>糾纏分數</th><th>三線距離</th><th>EMA20–50 距離</th><th>碰頭狀態</th><th>方向</th></tr>';
}
function renderRows(data){
 const body=$('tableBody'); const mode=data.mode; let rows=mode==='resonance'?data.resonance:data.rows;
 renderHeader(mode); $('resultCount').textContent=`${rows.length} 筆結果`;
 if(!rows.length){body.innerHTML=`<tr><td colspan="7" class="empty">${data.meta.status==='scanning'?'掃描正在進行，資料會逐步出現。':'目前沒有符合這個條件的幣種。可切換其他分類查看。'}</td></tr>`;return;}
 body.innerHTML=rows.slice(0,300).map((r,i)=>{
   if(mode==='resonance') return `<tr><td><span class="symbol-cell">${i+1}. ${r.symbol}</span><span class="sub-symbol">USDT PERPETUAL</span></td><td>${scoreCell(r.score)}</td><td>${pct(r.one_hour_cluster_pct)}</td><td>${pct(r.four_hour_cluster_pct)}</td><td><span class="pill ${pillClass(r.one_hour_meeting)}">${r.one_hour_meeting}</span></td><td><span class="pill ${pillClass(r.four_hour_meeting)}">${r.four_hour_meeting}</span></td><td><span class="pill ${r.same_direction?'green':'gray'}">${r.same_direction?'一致':'不一致'}</span></td></tr>`;
   return `<tr><td><span class="symbol-cell">${i+1}. ${r.symbol}</span><span class="sub-symbol">${r.instId}</span></td><td>${priceFmt(r.price)}</td><td>${scoreCell(r.cluster_score)}</td><td>${pct(r.cluster_pct)}</td><td>${pct(r.distance_pct)}</td><td><span class="pill ${pillClass(r.meeting)}">${r.meeting}</span></td><td><span class="pill ${pillClass(r.direction)}">${r.direction}</span></td></tr>`;
 }).join('');
}
async function loadStatus(){
 try{
  const r=await fetch('/api/status',{cache:'no-store'}); const d=await r.json();
  $('statusText').textContent=d.status==='scanning'?`掃描中 ${d.completed}/${d.total}`:d.status==='ready'?'資料已連線':d.status==='error'?'資料讀取異常':'啟動中';
  $('totalCount').textContent=d.total||'—'; $('progressCount').textContent=d.total?`${d.completed}/${d.total}`:'—'; $('lastUpdated').textContent=timeFmt(d.updated_at);
  if(d.error){$('errorBanner').textContent=d.error;$('errorBanner').classList.remove('hidden');} else {$('errorBanner').classList.add('hidden');}
  if(d.status==='ready'){
   const all=await fetch('/api/scan?tf=1H&mode=cluster',{cache:'no-store'}).then(x=>x.json());
   const four=await fetch('/api/scan?tf=4H&mode=cluster',{cache:'no-store'}).then(x=>x.json());
   $('oneCount').textContent=all.rows.filter(x=>x.cluster_pct<=1).length;
   $('fourCount').textContent=four.rows.filter(x=>x.cluster_pct<=1).length;
   $('resonanceCount').textContent=all.resonance.length;
  }
 }catch(e){$('statusText').textContent='連線中斷';}
}
async function loadTable(){
 const tf=$('timeframe').value; const q=$('searchInput').value.trim();
 try{
  if(currentMode==='resonance'){
   const d=await fetch(`/api/scan?tf=${tf}&mode=cluster&q=${encodeURIComponent(q)}`,{cache:'no-store'}).then(r=>r.json());
   d.mode='resonance';d.resonance=d.resonance.filter(x=>!q||x.symbol.toUpperCase().includes(q.toUpperCase()));latestData=d;renderRows(d);
  }else{
   const d=await fetch(`/api/scan?tf=${tf}&mode=${currentMode}&q=${encodeURIComponent(q)}`,{cache:'no-store'}).then(r=>r.json());latestData=d;renderRows(d);
  }
 }catch(e){$('tableBody').innerHTML='<tr><td colspan="7" class="empty">暫時無法取得掃描結果，請稍後重試。</td></tr>';}
}
async function refreshAll(){ $('refreshBtn').textContent='↻ 更新中'; await loadStatus(); await loadTable(); $('refreshBtn').textContent='↻ 更新'; }
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');currentMode=btn.dataset.mode;loadTable();}));
$('timeframe').addEventListener('change',loadTable); $('searchInput').addEventListener('input',()=>{clearTimeout(window.searchDelay);window.searchDelay=setTimeout(loadTable,200);}); $('refreshBtn').addEventListener('click',refreshAll);
refreshAll(); refreshTimer=setInterval(async()=>{await loadStatus();await loadTable();},20000);
