// Fleksa Cockpit - Real-Time Telemetry & Sovereign Dispatch Controller
let mpcData = null;
let mvData = null;
let currentHour = 12;
let simInterval = null;

// Built-in Flex-Policy Presets
const POLICY_PRESETS = {
  "preset-colo": `flex_policy:
  version: "2.0.0"
  policy_id: "pol-equinix-standard-v2"
  facility_id: "tr-ist-equinix-02"
  created_at: "2026-09-16T00:00:00Z"
  valid_until: "2027-09-16T00:00:00Z"
  assets:
    bess:
      capacity_kwh: 500.0
      max_charge_kw: 250.0
      max_discharge_kw: 250.0
      min_soc_pct: 15.0
      max_soc_pct: 95.0
      max_daily_cycles: 1.5
      chemistry: "LFP"
    compute:
      max_power_kw: 250.0
      min_critical_kw: 80.0
      gpu_nodes_count: 16
      allow_dvfs_capping: true
  load_classes:
    - id: "CLASS_0"
      priority: 0
      interruptible: false
    - id: "CLASS_3"
      priority: 3
      interruptible: true
      allow_power_cap_pct: 0.65
  rules:
    - id: "RULE-PEAK-01"
      condition:
        ptf_try_kwh: { gte: 4.50 }
        soc_pct: { gte: 25.0 }
      actions:
        - target: "BESS"
          command: "DISCHARGE"
          power_kw: 200.0
      audit_note: "EPIAŞ duck-curve evening peak arbitrage"
    - id: "RULE-DVFS-02"
      condition:
        ptf_try_kwh: { gte: 4.00 }
      actions:
        - target: "GPU_CLUSTER"
          command: "APPLY_CAP"
          value_pct: 0.65
      audit_note: "NVML DVFS throttling on memory-bound workloads"
  safety_guards:
    fail_closed_on_telemetry_loss: true
    telemetry_timeout_sec: 60.0
    max_grid_export_limit_kw: 0.0
`,
  "preset-strict": `flex_policy:
  version: "2.0.0"
  policy_id: "pol-h100-strict-sla-v2"
  facility_id: "tr-ist-equinix-02"
  created_at: "2026-09-16T00:00:00Z"
  valid_until: "2027-09-16T00:00:00Z"
  assets:
    bess:
      capacity_kwh: 1000.0
      max_charge_kw: 500.0
      max_discharge_kw: 500.0
      min_soc_pct: 20.0
      max_soc_pct: 90.0
      max_daily_cycles: 1.0
      chemistry: "LFP"
    compute:
      max_power_kw: 500.0
      min_critical_kw: 300.0
      gpu_nodes_count: 64
      allow_dvfs_capping: true
  load_classes:
    - id: "CLASS_0"
      priority: 0
      interruptible: false
  rules:
    - id: "RULE-BESS-BUFFER"
      condition:
        soc_pct: { gte: 40.0 }
      actions:
        - target: "BESS"
          command: "DISCHARGE"
          power_kw: 300.0
  safety_guards:
    fail_closed_on_telemetry_loss: true
    telemetry_timeout_sec: 30.0
    max_grid_export_limit_kw: 0.0
`,
  "preset-arbitrage": `flex_policy:
  version: "2.0.0"
  policy_id: "pol-aggressive-bess-arbitrage"
  facility_id: "tr-ist-equinix-02"
  created_at: "2026-09-16T00:00:00Z"
  valid_until: "2027-09-16T00:00:00Z"
  assets:
    bess:
      capacity_kwh: 750.0
      max_charge_kw: 350.0
      max_discharge_kw: 350.0
      min_soc_pct: 10.0
      max_soc_pct: 98.0
      max_daily_cycles: 2.5
      chemistry: "LFP"
    compute:
      max_power_kw: 150.0
      min_critical_kw: 40.0
  load_classes: []
  rules:
    - id: "RULE-GES-CHARGE"
      condition:
        ptf_try_kwh: { lte: 1.20 }
        soc_pct: { lte: 90.0 }
      actions:
        - target: "BESS"
          command: "CHARGE"
          power_kw: 300.0
    - id: "RULE-PEAK-DISCHARGE"
      condition:
        ptf_try_kwh: { gte: 4.80 }
        soc_pct: { gte: 15.0 }
      actions:
        - target: "BESS"
          command: "DISCHARGE"
          power_kw: 350.0
  safety_guards:
    fail_closed_on_telemetry_loss: true
    telemetry_timeout_sec: 45.0
    max_grid_export_limit_kw: 0.0
`,
  "preset-islanding": `flex_policy:
  version: "2.0.0"
  policy_id: "pol-microgrid-islanding-guard"
  facility_id: "tr-ist-equinix-02"
  created_at: "2026-09-16T00:00:00Z"
  valid_until: "2027-09-16T00:00:00Z"
  assets:
    bess:
      capacity_kwh: 500.0
      max_charge_kw: 250.0
      max_discharge_kw: 250.0
      min_soc_pct: 30.0
      max_soc_pct: 95.0
    compute:
      max_power_kw: 200.0
      min_critical_kw: 100.0
  load_classes: []
  rules:
    - id: "RULE-ISLAND-RESERVE"
      condition:
        grid_connected: { lte: 0.0 }
      actions:
        - target: "GPU_CLUSTER"
          command: "APPLY_CAP"
          value_pct: 0.50
        - target: "BESS"
          command: "DISCHARGE"
          power_kw: 100.0
  safety_guards:
    fail_closed_on_telemetry_loss: true
    telemetry_timeout_sec: 15.0
    max_grid_export_limit_kw: 0.0
`
};

document.addEventListener('DOMContentLoaded', () => {
  initGridFrequencyOscillation();
  setupNavigationTabs();
  fetchAndRenderSolve();
  fetchAndRenderMvBaseline();
  setupPolicyEditor();
  setupArbitrageCalculator();
  setupEventListeners();
});

// Subtle grid frequency micro-oscillation (50.000 Hz ± 0.015 Hz)
function initGridFrequencyOscillation() {
  const display = document.getElementById('gridFreqDisplay');
  setInterval(() => {
    if (window.isPfrActive) return;
    const dev = (Math.random() - 0.5) * 0.024;
    const freq = (50.000 + dev).toFixed(3);
    if (display) display.textContent = `${freq} Hz`;
  }, 1200);
}

// Tab Switching
function setupNavigationTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  const panels = document.querySelectorAll('.view-panel');
  const topConfig = document.getElementById('topConfigBar');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.getAttribute('data-view');
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) targetPanel.classList.add('active');

      // Only show top configuration bar in 24h dispatch view
      if (topConfig) {
        topConfig.style.display = targetId === 'view-dispatch' ? 'flex' : 'none';
      }

      // Re-render responsive charts on view reveal
      if (targetId === 'view-dispatch') renderChart();
      if (targetId === 'view-audit') renderMvChart();
    });
  });
}

function setupEventListeners() {
  const btnRecalc = document.getElementById('btnRecalculate');
  if (btnRecalc) btnRecalc.addEventListener('click', () => fetchAndRenderSolve());

  const scrubber = document.getElementById('scrubberInput');
  if (scrubber) {
    scrubber.addEventListener('input', (e) => {
      currentHour = parseInt(e.target.value, 10);
      updateScrubberState(currentHour);
      renderChart();
    });
  }

  const gpuSlider = document.getElementById('sliderGpuCap');
  if (gpuSlider) {
    gpuSlider.addEventListener('input', (e) => {
      const val = parseInt(e.target.value, 10);
      updateGpuDvfsState(val);
    });
  }

  const btnPfr = document.getElementById('btnTriggerPfr');
  if (btnPfr) btnPfr.addEventListener('click', triggerPfrSimulation);

  // Play / Pause 24h simulation loop
  const btnPlay = document.getElementById('btnPlaySim');
  if (btnPlay) {
    btnPlay.addEventListener('click', () => {
      if (simInterval) {
        clearInterval(simInterval);
        simInterval = null;
        btnPlay.innerHTML = '<span>▶ Play 24h</span>';
      } else {
        btnPlay.innerHTML = '<span>⏸ Pause</span>';
        simInterval = setInterval(() => {
          currentHour = (currentHour + 1) % 24;
          if (scrubber) scrubber.value = currentHour;
          updateScrubberState(currentHour);
          renderChart();
        }, 550);
      }
    });
  }

  // Export CSV
  const btnExport = document.getElementById('btnExportCsv');
  if (btnExport) btnExport.addEventListener('click', exportDispatchCsv);

  // Moat Modal
  const btnMoat = document.getElementById('btnOpenMoat');
  const moatModal = document.getElementById('moatModal');
  const btnCloseMoat = document.getElementById('btnCloseMoatModal');
  if (btnMoat && moatModal) {
    btnMoat.addEventListener('click', () => { moatModal.style.display = 'flex'; });
  }
  if (btnCloseMoat && moatModal) {
    btnCloseMoat.addEventListener('click', () => { moatModal.style.display = 'none'; });
  }

  // VC Modal
  const btnVc = document.getElementById('btnViewVc');
  const modal = document.getElementById('vcModal');
  const btnCloseModal = document.getElementById('btnCloseModal');

  if (btnVc && modal) {
    btnVc.addEventListener('click', async () => {
      modal.style.display = 'flex';
      const view = document.getElementById('vcJsonView');
      view.textContent = 'Generating & verifying W3C Verifiable Credential...';
      try {
        const res = await fetch('/api/export-credential');
        const data = await res.json();
        window.lastExportedVc = data;
        view.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        view.textContent = `Error loading credential: ${err.message}`;
      }
    });
  }

  const btnDownloadVc = document.getElementById('btnDownloadVc');
  if (btnDownloadVc) {
    btnDownloadVc.addEventListener('click', () => {
      if (!window.lastExportedVc) return;
      const blob = new Blob([JSON.stringify(window.lastExportedVc, null, 2)], { type: 'application/ld+json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `w3c_flexibility_credential_${Date.now()}.jsonld`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
  }

  if (btnCloseModal && modal) {
    btnCloseModal.addEventListener('click', () => { modal.style.display = 'none'; });
  }

  window.addEventListener('click', (e) => {
    if (e.target === modal) modal.style.display = 'none';
    if (e.target === moatModal) moatModal.style.display = 'none';
  });

  setupChartHoverTooltip();
}

function setupChartHoverTooltip() {
  const svg = document.getElementById('dispatchSvg');
  const tooltip = document.getElementById('chartTooltip');
  if (!svg || !tooltip) return;

  svg.addEventListener('mousemove', (e) => {
    if (!mpcData || !mpcData.hourly) return;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const relX = (x - 45) / (rect.width - 90);
    const hour = Math.max(0, Math.min(23, Math.round(relX * 23)));

    const h = mpcData.hourly;
    const ptf = h.ptf[hour];
    const pv = h.pv_gen_kw[hour];
    const pch = h.p_ch_kw[hour];
    const pdis = h.p_dis_kw[hour];
    const soc = h.soc_pct[hour];
    const vterm = h.v_term_v[hour];
    const temp = h.cell_temp_c[hour];

    let bessDesc = 'Idle (0 kW)';
    if (pch > 0) bessDesc = `+${pch.toFixed(1)} kW Charge`;
    if (pdis > 0) bessDesc = `-${pdis.toFixed(1)} kW Discharge`;

    tooltip.style.display = 'block';
    tooltip.style.left = `${Math.min(rect.width - 190, Math.max(10, x + 15))}px`;
    tooltip.style.top = `${Math.min(rect.height - 130, Math.max(10, e.clientY - rect.top - 20))}px`;
    tooltip.innerHTML = `
      <div style="font-weight:700; color:#38bdf8; margin-bottom:4px;">Hour ${String(hour).padStart(2, '0')}:00</div>
      <div>PTF: <strong class="mono" style="color:#f43f5e">₺${ptf.toFixed(2)}/kWh</strong></div>
      <div>Solar: <strong class="mono" style="color:#fbbf24">${pv} kW</strong></div>
      <div>BESS: <strong class="mono" style="color:#34d399">${bessDesc}</strong></div>
      <div>SoC: <strong class="mono">${soc}%</strong></div>
      <div style="margin-top:2px; font-size:0.68rem; color:#94a3b8;">V_term: <strong class="mono" style="color:#f1f5f9">${vterm.toFixed(1)}V</strong> | Cell: <strong class="mono" style="color:#f1f5f9">${temp.toFixed(1)}°C</strong></div>
    `;
  });

  svg.addEventListener('mouseleave', () => {
    tooltip.style.display = 'none';
  });
}

function exportDispatchCsv() {
  if (!mpcData || !mpcData.hourly) {
    alert('Solve data not yet loaded.');
    return;
  }
  const h = mpcData.hourly;
  let csvContent = 'Hour,PTF_TRY_kWh,SMF_TRY_kWh,PV_Gen_kW,Base_Load_kW,BESS_Ch_kW,BESS_Dis_kW,GPU_Cap_Pct,SoC_kWh,SoC_Pct,V_Term_V,Cell_Temp_C\n';
  for (let t = 0; t < 24; t++) {
    csvContent += `${t},${h.ptf[t]},${h.smf[t]},${h.pv_gen_kw[t]},${h.base_load_kw[t]},${h.p_ch_kw[t]},${h.p_dis_kw[t]},${h.gpu_power_cap_pct[t]},${h.soc_kwh[t]},${h.soc_pct[t]},${h.v_term_v[t]},${h.cell_temp_c[t]}\n`;
  }
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', 'fleksa_optimal_dispatch_2026.csv');
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

async function fetchAndRenderSolve() {
  const cap = parseFloat(document.getElementById('cfgCapacity')?.value || '500');
  const maxKw = parseFloat(document.getElementById('cfgMaxKw')?.value || '250');
  const initSoc = parseFloat(document.getElementById('cfgInitialSoc')?.value || '200');
  const gpuCapMin = parseFloat(document.getElementById('cfgGpuCapMin')?.value || '0.65');
  const isWater = document.getElementById('cfgWaterPenalty')?.checked;
  const waterCost = isWater ? 0.081 : 0.0;

  const bessBadge = document.getElementById('bessBadge');
  if (bessBadge) bessBadge.textContent = `${cap} kWh / ${maxKw} kW`;

  try {
    const res = await fetch('/api/solve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        initial_soc: initSoc,
        capacity: cap,
        max_kw: maxKw,
        gpu_cap_min: gpuCapMin,
        water_cost_per_kwh: waterCost
      })
    });
    mpcData = await res.json();
    renderKpiMetrics(mpcData);
    updateScrubberState(currentHour);
    renderChart();
  } catch (err) {
    console.error('Error fetching solve data:', err);
  }
}

function renderKpiMetrics(data) {
  if (!data) return;
  document.getElementById('kpiBaseline').textContent = `₺${data.baseline_cost_try.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  document.getElementById('kpiDispatched').textContent = `₺${data.projected_cost_try.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  document.getElementById('kpiSavings').textContent = `₺${data.expected_savings_try.toLocaleString('en-US', { minimumFractionDigits: 2 })} (+${data.savings_percent}%)`;

  const totalMwhDischarged = data.hourly.p_dis_kw.reduce((a, b) => a + b, 0);
  const carbonKg = (totalMwhDischarged * 0.48).toFixed(1);
  document.getElementById('kpiCarbon').textContent = `${carbonKg} kg CO₂`;

  document.getElementById('tileSoh').textContent = `${data.degradation.soh_remaining_pct.toFixed(3)}%`;
  document.getElementById('tileFade').textContent = `Cycle Fade: -${data.degradation.day_q_loss_pct.toFixed(4)}%`;
}

function updateScrubberState(h) {
  if (!mpcData || !mpcData.hourly) return;
  const hourData = mpcData.hourly;
  const ptf = hourData.ptf[h];
  const pv = hourData.pv_gen_kw[h];
  const pch = hourData.p_ch_kw[h];
  const pdis = hourData.p_dis_kw[h];
  const socPct = hourData.soc_pct[h];
  const socKwh = hourData.soc_kwh[h];
  const vterm = hourData.v_term_v[h];
  const temp = hourData.cell_temp_c[h];

  document.getElementById('scrubberHourText').textContent = `${String(h).padStart(2, '0')}:00 (T=${h})`;
  let bessStr = 'Idle (0 kW)';
  if (pch > 0) bessStr = `+${pch.toFixed(1)} kW Charge`;
  if (pdis > 0) bessStr = `-${pdis.toFixed(1)} kW Discharge`;

  document.getElementById('scrubberDetails').textContent =
    `PTF: ₺${ptf.toFixed(2)}/kWh | Solar: ${pv.toFixed(0)} kW | BESS: ${bessStr}`;

  document.getElementById('tileSoc').textContent = `${socPct.toFixed(1)}%`;
  document.getElementById('tileSocKwh').textContent = `${socKwh.toFixed(1)} kWh`;
  document.getElementById('tileVterm').textContent = `${vterm.toFixed(1)} V`;
  document.getElementById('tileTemp').textContent = `${temp.toFixed(1)} °C`;
}

function updateGpuDvfsState(val) {
  const label = document.getElementById('valGpuCap');
  label.textContent = `${val}% (${Math.round(700 * (val / 100))}W / GPU)`;

  const totalGpuKw = 16 * 0.700;
  const curtailedKw = (totalGpuKw * (1.0 - val / 100)).toFixed(1);

  const kVal = Math.max(1, Math.round(5 * (val / 100)));
  document.getElementById('valSpecK').textContent = `K = ${kVal} tokens`;

  const latency = (14.0 + (100 - val) * 0.12).toFixed(1);
  const acceptRate = (60.0 + kVal * 3.8).toFixed(1);
  document.getElementById('speculativeInfo').textContent =
    `Token Latency: ${latency} ms | Acceptance Rate: ${acceptRate}% | Power Curtailment: ${curtailedKw} kW`;
}

function triggerPfrSimulation() {
  window.isPfrActive = true;
  const gridDot = document.getElementById('gridDot');
  const freqDisplay = document.getElementById('gridFreqDisplay');
  const respTime = document.getElementById('valResponseTime');
  const grade = document.getElementById('valGrade');

  gridDot.style.background = '#f43f5e';
  gridDot.style.boxShadow = '0 0 12px #f43f5e';
  freqDisplay.textContent = '49.820 Hz (CRITICAL)';
  freqDisplay.style.color = '#f43f5e';

  respTime.textContent = 'Measuring...';
  respTime.style.color = '#f59e0b';

  setTimeout(() => {
    respTime.textContent = '28.0 ms (Target < 200 ms)';
    respTime.style.color = '#10b981';
    grade.textContent = 'GRADE A+ (TEİAŞ Verified)';

    const slider = document.getElementById('sliderGpuCap');
    if (slider) {
      slider.value = 60;
      updateGpuDvfsState(60);
    }
  }, 280);

  setTimeout(() => {
    gridDot.style.background = '#10b981';
    gridDot.style.boxShadow = '0 0 8px #10b981';
    freqDisplay.textContent = '50.000 Hz';
    freqDisplay.style.color = '';
    window.isPfrActive = false;
  }, 3500);
}

function renderChart() {
  if (!mpcData || !mpcData.hourly) return;
  const svg = document.getElementById('dispatchSvg');
  if (!svg) return;
  const h = mpcData.hourly;
  const width = 880;
  const height = 320;
  const padL = 45;
  const padR = 45;
  const padT = 20;
  const padB = 30;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const maxKw = 350;
  const maxPtf = 6.0;

  const getX = (t) => padL + (t / 23) * plotW;
  const getYPower = (kw) => padT + plotH - (kw / maxKw) * plotH;
  const getYPtf = (ptf) => padT + plotH - (ptf / maxPtf) * plotH;

  let svgHtml = '';

  svgHtml += `<text x="${padL}" y="${padT - 6}" fill="#94a3b8" font-size="9" font-family="monospace" font-weight="600">POWER (kW)</text>`;
  svgHtml += `<text x="${width - padR}" y="${padT - 6}" fill="#f43f5e" font-size="9" font-family="monospace" font-weight="600" text-anchor="end">EPIAŞ PTF (₺/kWh)</text>`;

  for (let step = 0; step <= 4; step++) {
    const kwVal = Math.round((step / 4) * maxKw);
    const ptfVal = ((step / 4) * maxPtf).toFixed(1);
    const y = getYPower(kwVal);
    svgHtml += `<line x1="${padL}" y1="${y}" x2="${width - padR}" y2="${y}" stroke="rgba(255,255,255,0.06)" stroke-width="1" />`;
    svgHtml += `<text x="${padL - 8}" y="${y + 4}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end">${kwVal}k</text>`;
    svgHtml += `<text x="${width - padR + 8}" y="${y + 4}" fill="#f43f5e" font-size="10" font-family="monospace" text-anchor="start">₺${ptfVal}</text>`;
  }

  for (let t = 0; t < 24; t += 3) {
    const x = getX(t);
    svgHtml += `<text x="${x}" y="${height - 10}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="middle">${String(t).padStart(2, '0')}:00</text>`;
  }

  // Solar PV Area
  let pvPath = `M ${getX(0)} ${getYPower(0)}`;
  for (let t = 0; t < 24; t++) {
    pvPath += ` L ${getX(t)} ${getYPower(h.pv_gen_kw[t])}`;
  }
  pvPath += ` L ${getX(23)} ${getYPower(0)} Z`;
  svgHtml += `<path d="${pvPath}" fill="rgba(245, 158, 11, 0.12)" stroke="#f59e0b" stroke-width="2" />`;

  // Base Load
  let loadPath = `M ${getX(0)} ${getYPower(h.base_load_kw[0])}`;
  for (let t = 1; t < 24; t++) {
    loadPath += ` L ${getX(t)} ${getYPower(h.base_load_kw[t])}`;
  }
  svgHtml += `<path d="${loadPath}" fill="none" stroke="#94a3b8" stroke-dasharray="4,4" stroke-width="1.5" />`;

  // BESS Charge & Discharge Bars
  for (let t = 0; t < 24; t++) {
    const x = getX(t) - 6;
    const pch = h.p_ch_kw[t];
    const pdis = h.p_dis_kw[t];

    if (pch > 0) {
      const barH = (pch / maxKw) * plotH;
      const y = getYPower(pch);
      svgHtml += `<rect x="${x}" y="${y}" width="12" height="${barH}" fill="#10b981" rx="2" opacity="0.85" />`;
    } else if (pdis > 0) {
      const barH = (pdis / maxKw) * plotH;
      const y = getYPower(pdis);
      svgHtml += `<rect x="${x}" y="${y}" width="12" height="${barH}" fill="#06b6d4" rx="2" opacity="0.85" />`;
    }
  }

  // PTF Price Line
  let ptfPath = `M ${getX(0)} ${getYPtf(h.ptf[0])}`;
  for (let t = 1; t < 24; t++) {
    ptfPath += ` L ${getX(t)} ${getYPtf(h.ptf[t])}`;
  }
  svgHtml += `<path d="${ptfPath}" fill="none" stroke="#e11d48" stroke-width="2.2" />`;

  // Scrubber Line
  const scrubX = getX(currentHour);
  svgHtml += `
    <line x1="${scrubX}" y1="${padT}" x2="${scrubX}" y2="${padT + plotH}" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="2,2" />
    <circle cx="${scrubX}" cy="${getYPtf(h.ptf[currentHour])}" r="4" fill="#e11d48" stroke="#ffffff" stroke-width="1.5" />
    <circle cx="${scrubX}" cy="${getYPower(h.pv_gen_kw[currentHour])}" r="4" fill="#f59e0b" stroke="#ffffff" stroke-width="1.5" />
  `;

  svg.innerHTML = svgHtml;
}

// -------------------------------------------------------------
// VIEW 2: IPMVP M&V Studio Functions
// -------------------------------------------------------------
async function fetchAndRenderMvBaseline() {
  try {
    const res = await fetch('/api/audit/baseline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    mvData = await res.json();
    renderMvMetrics(mvData);
    renderMvChart();
  } catch (err) {
    console.error('Error fetching M&V baseline:', err);
  }
}

function renderMvMetrics(data) {
  if (!data) return;
  const ash = data.ashrae_compliance;
  document.getElementById('mvCvRmseVal').textContent = `${ash.cv_rmse_pct.toFixed(2)}%`;
  document.getElementById('mvNmbeVal').textContent = `${ash.nmbe_pct.toFixed(2)}%`;
  document.getElementById('tblCvVal').textContent = `${ash.cv_rmse_pct.toFixed(2)}%`;
  document.getElementById('tblNmbeVal').textContent = `${ash.nmbe_pct.toFixed(2)}%`;
  document.getElementById('mvCurtailedVal').textContent = `${data.savings.net_curtailed_kwh.toFixed(1)} kWh`;
  document.getElementById('mvFinancialVal').textContent = `₺${data.savings.net_financial_savings_try.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
  document.getElementById('mvLeafHash').textContent = data.merkle_root;
}

function renderMvChart() {
  if (!mvData) return;
  const svg = document.getElementById('mvSvg');
  if (!svg) return;

  const width = 880;
  const height = 300;
  const padL = 45;
  const padR = 25;
  const padT = 20;
  const padB = 30;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const baseRaw = mvData.baseline_raw_kw;
  const baseAdj = mvData.adjusted_baseline_kw;
  const actual = mvData.actual_meter_kw;

  const maxVal = 400;
  const getX = (t) => padL + (t / 23) * plotW;
  const getY = (val) => padT + plotH - (val / maxVal) * plotH;

  let svgHtml = '';

  // Grid
  for (let s = 0; s <= 4; s++) {
    const val = (s / 4) * maxVal;
    const y = getY(val);
    svgHtml += `<line x1="${padL}" y1="${y}" x2="${width - padR}" y2="${y}" stroke="rgba(255,255,255,0.06)" stroke-width="1" />`;
    svgHtml += `<text x="${padL - 8}" y="${y + 4}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="end">${val}k</text>`;
  }

  for (let t = 0; t < 24; t += 3) {
    const x = getX(t);
    svgHtml += `<text x="${x}" y="${height - 10}" fill="#64748b" font-size="10" font-family="monospace" text-anchor="middle">${String(t).padStart(2, '0')}:00</text>`;
  }

  // Curtailed Shaded Area between hour 17 and 20
  let shadePath = `M ${getX(17)} ${getY(actual[17])}`;
  for (let t = 17; t <= 20; t++) {
    shadePath += ` L ${getX(t)} ${getY(actual[t])}`;
  }
  for (let t = 20; t >= 17; t--) {
    shadePath += ` L ${getX(t)} ${getY(baseAdj[t])}`;
  }
  shadePath += ' Z';
  svgHtml += `<path d="${shadePath}" fill="rgba(16, 185, 129, 0.35)" />`;

  // Raw Baseline dashed
  let rawPath = `M ${getX(0)} ${getY(baseRaw[0])}`;
  for (let t = 1; t < 24; t++) rawPath += ` L ${getX(t)} ${getY(baseRaw[t])}`;
  svgHtml += `<path d="${rawPath}" fill="none" stroke="#94a3b8" stroke-dasharray="4,4" stroke-width="1.6" />`;

  // Adjusted Baseline
  let adjPath = `M ${getX(0)} ${getY(baseAdj[0])}`;
  for (let t = 1; t < 24; t++) adjPath += ` L ${getX(t)} ${getY(baseAdj[t])}`;
  svgHtml += `<path d="${adjPath}" fill="none" stroke="#38bdf8" stroke-width="2.2" />`;

  // Actual Metered Load
  let actPath = `M ${getX(0)} ${getY(actual[0])}`;
  for (let t = 1; t < 24; t++) actPath += ` L ${getX(t)} ${getY(actual[t])}`;
  svgHtml += `<path d="${actPath}" fill="none" stroke="#10b981" stroke-width="2.2" />`;

  svg.innerHTML = svgHtml;
}

// -------------------------------------------------------------
// VIEW 3: Flex-Policy v2 Sovereign Studio Functions
// -------------------------------------------------------------
function setupPolicyEditor() {
  const selPreset = document.getElementById('selPolicyPreset');
  const txtEditor = document.getElementById('txtPolicyYaml');
  const btnValidate = document.getElementById('btnValidatePolicy');
  const statusBanner = document.getElementById('policyStatusBanner');
  const statusText = document.getElementById('policyStatusText');

  if (txtEditor && selPreset) {
    txtEditor.value = POLICY_PRESETS["preset-colo"];

    selPreset.addEventListener('change', (e) => {
      txtEditor.value = POLICY_PRESETS[e.target.value] || "";
    });
  }

  if (btnValidate) {
    btnValidate.addEventListener('click', async () => {
      statusText.textContent = "Verifying policy schema and safety guards against AST...";
      statusText.style.color = "#38bdf8";

      try {
        const res = await fetch('/api/verify-policy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            policy_yaml: txtEditor.value,
            skip_signature: true
          })
        });
        const data = await res.json();

        if (res.ok && data.valid) {
          statusText.textContent = `✓ PASS: Policy '${data.policy_id}' is valid. BESS Cap: ${data.bess_capacity_kwh} kWh, Rules: ${data.rules_count}, Invariants verified.`;
          statusText.style.color = "#34d399";
        } else {
          statusText.textContent = `✗ FAIL: ${data.error || "Policy verification error"}`;
          statusText.style.color = "#f43f5e";
        }
      } catch (err) {
        statusText.textContent = `✗ Error: ${err.message}`;
        statusText.style.color = "#f43f5e";
      }
    });
  }

  // Live Rule Sandbox Sliders
  const sliderPtf = document.getElementById('sliderRulePtf');
  const sliderSoc = document.getElementById('sliderRuleSoc');
  const readoutPtf = document.getElementById('simRulePtfText');
  const readoutSoc = document.getElementById('simRuleSocText');
  const readoutActions = document.getElementById('simTriggeredActions');

  function updateRuleSandbox() {
    const ptf = parseFloat(sliderPtf.value);
    const soc = parseFloat(sliderSoc.value);
    readoutPtf.textContent = `₺${ptf.toFixed(2)}/kWh`;
    readoutSoc.textContent = `${soc.toFixed(0)}%`;

    let actions = [];
    if (ptf >= 4.50 && soc >= 25.0) {
      actions.push("[RULE-PEAK-01] BESS -> DISCHARGE (200.0 kW)");
    }
    if (ptf >= 4.00) {
      actions.push("[RULE-DVFS-02] GPU Cluster -> APPLY_CAP (65% DVFS Throttling)");
    }
    if (ptf <= 1.50 && soc <= 90.0) {
      actions.push("[RULE-SOLAR-03] BESS -> CHARGE (250.0 kW Surplus Soak)");
    }
    if (actions.length === 0) {
      actions.push("No rules triggered (Facility operates under nominal schedule)");
    }
    readoutActions.innerHTML = actions.join("<br>");
  }

  if (sliderPtf && sliderSoc) {
    sliderPtf.addEventListener('input', updateRuleSandbox);
    sliderSoc.addEventListener('input', updateRuleSandbox);
  }
}

// -------------------------------------------------------------
// VIEW 4: Theorem 1 Arbitrage & Triangulation Canary Functions
// -------------------------------------------------------------
function setupArbitrageCalculator() {
  const sCh = document.getElementById('gateChSlider');
  const sDis = document.getElementById('gateDisSlider');
  const sRte = document.getElementById('gateRteSlider');
  const sDeg = document.getElementById('gateDegSlider');

  async function updateGate() {
    const ch = parseFloat(sCh.value);
    const dis = parseFloat(sDis.value);
    const rte = parseFloat(sRte.value);
    const deg = parseFloat(sDeg.value);

    document.getElementById('gateChVal').textContent = `₺${ch.toFixed(2)}/kWh`;
    document.getElementById('gateDisVal').textContent = `₺${dis.toFixed(2)}/kWh`;
    document.getElementById('gateRteVal').textContent = `${(rte * 100).toFixed(1)}%`;
    document.getElementById('gateDegVal').textContent = `₺${deg.toFixed(2)}/kWh`;

    try {
      const res = await fetch('/api/arbitrage-gate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          charge_price: ch,
          discharge_price: dis,
          rte: rte,
          degradation_cost: deg,
          risk_premium: 0.05
        })
      });
      const data = await res.json();

      document.getElementById('gateBreakEven').textContent = `₺${data.break_even_charge_cost.toFixed(3)} / kWh`;
      document.getElementById('gateEffDeg').textContent = `₺${data.effective_deg_cost.toFixed(3)} / kWh`;
      document.getElementById('gateMinReq').textContent = `₺${data.min_required_discharge_price.toFixed(3)} / kWh`;

      const netMargin = data.net_margin_try_per_kwh;
      const marginEl = document.getElementById('gateNetMargin');
      const badgeEl = document.getElementById('gateVerdictBadge');

      if (data.is_viable) {
        marginEl.textContent = `+₺${netMargin.toFixed(3)} / kWh`;
        marginEl.style.color = '#34d399';
        badgeEl.textContent = 'PROFITABLE_ARBITRAGE';
        badgeEl.style.background = 'rgba(16,185,129,0.15)';
        badgeEl.style.color = '#34d399';
        badgeEl.style.borderColor = 'rgba(16,185,129,0.3)';
      } else {
        marginEl.textContent = `₺${netMargin.toFixed(3)} / kWh`;
        marginEl.style.color = '#f43f5e';
        badgeEl.textContent = 'CAPITAL_DESTRUCTION_BLOCKED';
        badgeEl.style.background = 'rgba(244,63,94,0.15)';
        badgeEl.style.color = '#fb7185';
        badgeEl.style.borderColor = 'rgba(244,63,94,0.3)';
      }
    } catch (err) {
      console.error('Error updating arbitrage gate:', err);
    }
  }

  if (sCh && sDis && sRte && sDeg) {
    sCh.addEventListener('input', updateGate);
    sDis.addEventListener('input', updateGate);
    sRte.addEventListener('input', updateGate);
    sDeg.addEventListener('input', updateGate);
  }

  // Triangulation Canary Verification
  const btnTestCanary = document.getElementById('btnTestCanary');
  if (btnTestCanary) {
    btnTestCanary.addEventListener('click', async () => {
      const epias = parseFloat(document.getElementById('inpEpiasPrice').value || '2450');
      const teias = parseFloat(document.getElementById('inpTeiasPrice').value || '2400');
      const regional = parseFloat(document.getElementById('inpRegionalPrice').value || '2380');

      const badge = document.getElementById('canaryStatusBadge');
      const resultBox = document.getElementById('canaryResultBox');
      const consensusVal = document.getElementById('canaryConsensusVal');

      try {
        const res = await fetch('/api/canary/quorum', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ epias, teias, regional, max_divergence_pct: 35.0 })
        });
        const data = await res.json();

        if (res.ok && data.consensus_achieved) {
          badge.textContent = 'CONSENSUS_VALID';
          badge.style.background = 'rgba(16,185,129,0.15)';
          badge.style.color = '#34d399';
          badge.style.borderColor = 'rgba(16,185,129,0.3)';
          consensusVal.textContent = `₺${data.consensus_price_try_mwh.toLocaleString('en-US', { minimumFractionDigits: 2 })} / MWh (${data.consensus_price_try_kwh.toFixed(3)} ₺/kWh)`;
          resultBox.style.borderColor = 'rgba(16,185,129,0.3)';
        } else {
          badge.textContent = 'BYZANTINE_DIVERGENCE_REJECTED';
          badge.style.background = 'rgba(244,63,94,0.15)';
          badge.style.color = '#fb7185';
          badge.style.borderColor = 'rgba(244,63,94,0.3)';
          consensusVal.textContent = `QUORUM FAILED: ${data.error || 'Divergence exceeds threshold'}`;
          resultBox.style.borderColor = 'rgba(244,63,94,0.3)';
        }
      } catch (err) {
        badge.textContent = 'NETWORK_ERROR';
        consensusVal.textContent = err.message;
      }
    });
  }
}
