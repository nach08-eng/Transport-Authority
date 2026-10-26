let dashboardData = {alerts:[], vehicles:[], allocations:[], totals:{}, hourly:[], hotspots:[]};
let hourChart = null;
const $ = id => document.getElementById(id);
function esc(v){return String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDate(s){try{return new Date(s).toLocaleString()}catch{return s||'—'}}
function typeLabel(t){return ({crowd:'Crowd report',overcrowding:'Overcrowding',congestion:'Congestion',medical_emergency:'Medical emergency',driver_injured:'Driver injured',vehicle_breakdown:'Vehicle breakdown',safety_threat:'Safety threat',door_obstruction:'Door obstruction',other:'Other incident'})[t]||t}
function renderAlerts(){
 const filter=$('alertFilter').value;
 const list=dashboardData.alerts.filter(a=>filter==='ALL'||a.status===filter);
 $('alertRows').innerHTML=list.length?list.map(a=>`<tr>
 <td><span class="priority ${esc(a.severity)}">${esc(a.severity.toUpperCase())}</span></td>
 <td><strong>${esc(typeLabel(a.event_type))}</strong><br><small>${esc(fmtDate(a.created_at))}</small><br><small>${esc(a.source)}</small></td>
 <td><strong>${esc(a.vehicle_id)}</strong><br><small>${esc(a.route)}</small></td>
 <td>${esc(a.stop_name)}<br><small>${esc(a.message)}</small></td>
 <td>${a.occupancy==null?'—':esc(a.occupancy)}${a.capacity==null?'':` / ${esc(a.capacity)}`}</td>
 <td><span class="status ${esc(a.status)}">${esc(a.status)}</span></td>
 <td><div class="row-actions">${a.status==='NEW'?`<button class="mini-btn" onclick="setAlertStatus(${a.id},'ACKNOWLEDGED')">Acknowledge</button>`:''}${a.status!=='RESOLVED'?`<button class="mini-btn" onclick="setAlertStatus(${a.id},'RESOLVED')">Resolve</button>`:''}<button class="mini-btn" onclick="deleteAlert(${a.id})">Delete</button>${['crowd','overcrowding','congestion'].includes(a.event_type)?`<button class="mini-btn" onclick="prepareAllocation(${a.id})">Allocate bus</button>`:''}</div></td>
 </tr>`).join(''):`<tr><td colspan="7" class="empty">No alerts match this filter.</td></tr>`;
 $('allocationAlert').innerHTML='<option value="">No linked alert</option>'+dashboardData.alerts.filter(a=>a.status!=='RESOLVED').map(a=>`<option value="${a.id}">#${a.id} · ${esc(a.vehicle_id)} · ${esc(typeLabel(a.event_type))}</option>`).join('');
}
function renderVehicles(){
 const available=dashboardData.vehicles.filter(v=>v.status==='AVAILABLE');
 $('availableBuses').textContent=available.length;
 $('fleetCount').textContent=`${dashboardData.vehicles.length} VEHICLES`;
 $('allocationVehicle').innerHTML=available.length?available.map(v=>`<option value="${esc(v.vehicle_id)}">${esc(v.vehicle_id)} — ${esc(v.last_location)}</option>`).join(''):'<option value="">No available buses</option>';
 $('fleetList').innerHTML=dashboardData.vehicles.map(v=>`<div class="fleet-item"><div><strong>${esc(v.vehicle_id)}</strong><small>${esc(v.route)} · ${esc(v.driver_name||'Driver not assigned')} · ${esc(v.last_location)}</small></div><span class="fleet-status ${esc(v.status)}">${esc(v.status)}</span></div>`).join('')||'<p class="empty">No vehicles registered.</p>';
}
function renderAllocations(){
 $('allocationList').innerHTML=dashboardData.allocations.map(a=>`<div class="assignment"><div><strong>${esc(a.vehicle_id)} → ${esc(a.route)}</strong><small>${esc(a.stop_name||'Route assignment')} · ETA ${esc(a.eta_minutes)} min · ${esc(a.assigned_to)}</small></div><select aria-label="Assignment status" onchange="updateAllocation(${a.id},this.value)"><option ${a.status==='ASSIGNED'?'selected':''}>ASSIGNED</option><option ${a.status==='EN_ROUTE'?'selected':''}>EN_ROUTE</option><option ${a.status==='ARRIVED'?'selected':''}>ARRIVED</option><option ${a.status==='COMPLETED'?'selected':''}>COMPLETED</option><option ${a.status==='CANCELLED'?'selected':''}>CANCELLED</option></select></div>`).join('')||'<p class="empty">No bus assignments yet.</p>';
}
function renderHotspots(){
 $('hotspotList').innerHTML=dashboardData.hotspots.map(h=>`<div class="hotspot"><div><strong>${esc(h.stop_name)}</strong><small>${esc(h.route)} · Last: ${esc(fmtDate(h.last_seen))}</small></div><span class="tag">${h.events} reports</span></div>`).join('')||'<p class="empty">No crowd history yet. Incoming crowd reports will build this list.</p>';
 const ctx=$('hourChart');
 if(hourChart)hourChart.destroy();
 hourChart=new Chart(ctx,{type:'bar',data:{labels:Array.from({length:24},(_,i)=>`${String(i).padStart(2,'0')}:00`),datasets:[{label:'Crowd reports',data:dashboardData.hourly,backgroundColor:'#5472f5',borderRadius:5,maxBarThickness:20}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:8}},y:{beginAtZero:true,ticks:{precision:0},grid:{color:'#edf0f6'}}}}});
}
async function loadDashboard(){
 try{
  const res=await fetch('/api/dashboard');if(!res.ok)throw new Error('Could not load dashboard');
  dashboardData=await res.json();
  $('activeAlerts').textContent=dashboardData.totals.active_alerts;
  $('emergencies').textContent=dashboardData.totals.emergencies;
  $('crowdEvents').textContent=dashboardData.totals.crowd_events;
  renderAlerts();renderVehicles();renderAllocations();renderHotspots();
 }catch(e){console.error(e);alert('Could not load authority data. Check the Flask terminal.');}
}
async function setAlertStatus(id,status){
 const res=await fetch(`/api/alerts/${id}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
 const d=await res.json();if(!res.ok){alert(d.error||'Update failed');return}loadDashboard();
}
async function deleteAlert(id){if(!confirm(`Delete alert #${id}? This cannot be undone.`))return;await fetch(`/api/alerts/${id}`,{method:'DELETE'});loadDashboard();}
async function clearHistory(){if(!confirm('Clear ALL alert history? This cannot be undone.'))return;const r=await fetch('/api/alerts',{method:'DELETE'});if(r.ok)loadDashboard();}
function prepareAllocation(id){$('allocationAlert').value=String(id);const a=dashboardData.alerts.find(x=>x.id===id);if(a){$('allocationRoute').value=a.route;$('allocationEta').focus()}$('dispatch').scrollIntoView({behavior:'smooth'});}
async function updateAllocation(id,status){const r=await fetch(`/api/allocations/${id}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});const d=await r.json();if(!r.ok)alert(d.error||'Could not update assignment');loadDashboard();}
$('reportForm').addEventListener('submit',async e=>{
 e.preventDefault();const type=$('reportType').value;
 const payload={vehicle_id:$('reportVehicle').value,route:$('reportRoute').value,event_type:type,severity:$('reportSeverity').value,stop_name:$('reportLocation').value,occupancy:$('reportOccupancy').value,message:$('reportMessage').value,source:'driver'};
 const r=await fetch('/api/driver-report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();
 $('reportMsg').textContent=r.ok?`Report received by authority. Alert ID #${d.alert_id}.`:(d.error||'Could not send report.');
 if(r.ok){$('reportMessage').value='';loadDashboard();}
});
$('allocationForm').addEventListener('submit',async e=>{
 e.preventDefault();const payload={alert_id:$('allocationAlert').value||null,vehicle_id:$('allocationVehicle').value,route:$('allocationRoute').value,eta_minutes:$('allocationEta').value,assigned_to:$('assignedTo').value};
 const r=await fetch('/api/allocations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();
 $('allocationMsg').textContent=r.ok?`Bus ${d.vehicle_id} assigned to ${d.route}.`:(d.error||'Allocation failed.');
 if(r.ok)loadDashboard();
});
$('vehicleForm').addEventListener('submit',async e=>{
 e.preventDefault();const payload={vehicle_id:$('newVehicleId').value,route:$('newVehicleRoute').value,status:'AVAILABLE',last_location:'Depot'};
 const r=await fetch('/api/vehicles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();
 if(!r.ok){alert(d.error||'Could not add vehicle');return}
 $('newVehicleId').value='';loadDashboard();
});
function tick(){ $('clock').textContent=new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
tick();setInterval(tick,1000);loadDashboard();setInterval(loadDashboard,15000);
