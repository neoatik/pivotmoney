/**
 * ═══════════════════════════════════════════════════════════════
 * PivotMoney — Premium Financial Dashboard · app.js
 * Vanilla JS, zero dependencies
 * ═══════════════════════════════════════════════════════════════
 */

'use strict';

/* ──────────────────────────────────────────────────────────────
   CONFIG
────────────────────────────────────────────────────────────── */
const API_BASE = 'http://localhost:8000/api/v1';

const CHART_COLORS = [
  '#FFFFFF', '#E4E4E7', '#A1A1AA', '#71717A',
  '#52525B', '#3F3F46', '#27272A', '#18181B'
];

const TYPE_BADGE_MAP = {
  'Stock':       'badge-stock',
  'ETF':         'badge-etf',
  'Bond':        'badge-bond',
  'Cash':        'badge-cash',
  'Mutual Fund': 'badge-mutual',
  'Option':      'badge-option',
};

const STATUS_CLASSES = {
  pending:    'status-pending',
  processing: 'status-processing',
  success:    'status-success',
  completed:  'status-success',
  failed:     'status-failed',
  error:      'status-failed',
};

const LOG_ICONS = { info: 'ℹ️', warning: '⚠️', warn: '⚠️', error: '❌', debug: '🔍' };

/* ──────────────────────────────────────────────────────────────
   STATE MANAGEMENT
────────────────────────────────────────────────────────────── */
const AppState = {
  statements:       [],
  holdings:         [],
  portfolioSummary: null,
  allocation:       [],
  activeTab:        'dashboard',
  filters: {
    search:             '',
    type:               '',
    statementId:        '',
    dashboardAccountId: '',
  },
  sort: {
    col: 'market_value',
    dir: 'desc',
  },
  pagination: {
    page:     1,
    perPage:  10,
  },
  loading:     {},
  pollingIds:  {},      // statementId → intervalId for status polling
  selectedStmtForLogs: null,
  _listeners: {},
};

/**
 * Update state and notify listeners.
 * @param {string} key
 * @param {*} value
 */
function setState(key, value) {
  AppState[key] = value;
  const cbs = AppState._listeners[key] || [];
  cbs.forEach(cb => cb(value));
}

function onStateChange(key, cb) {
  if (!AppState._listeners[key]) AppState._listeners[key] = [];
  AppState._listeners[key].push(cb);
}

/* ──────────────────────────────────────────────────────────────
   API CLIENT
────────────────────────────────────────────────────────────── */
const apiClient = {
  async _request(method, endpoint, body = null, isForm = false) {
    const url = `${API_BASE}${endpoint}`;
    const opts = {
      method,
      headers: isForm ? {} : { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = isForm ? body : JSON.stringify(body);

    const res = await fetch(url, opts);

    if (!res.ok) {
      let errMsg = `HTTP ${res.status}: ${res.statusText}`;
      try {
        const data = await res.json();
        errMsg = data.detail || data.message || errMsg;
      } catch (_) { /* ignore parse error */ }
      throw new Error(errMsg);
    }

    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) return res.json();
    return res.text();
  },

  get(endpoint)         { return this._request('GET',    endpoint); },
  post(endpoint, body)  { return this._request('POST',   endpoint, body); },
  delete(endpoint)      { return this._request('DELETE', endpoint); },

  uploadFile(endpoint, file, onProgress) {
    return new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append('file', file);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}${endpoint}`);

      xhr.upload.addEventListener('progress', e => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });

      xhr.addEventListener('load', () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)); }
          catch (_) { resolve(xhr.responseText); }
        } else {
          let msg = `Upload failed (${xhr.status})`;
          try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (_) {}
          reject(new Error(msg));
        }
      });

      xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
      xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));
      xhr.send(formData);
    });
  },
};

/* ──────────────────────────────────────────────────────────────
   TOAST NOTIFICATIONS
────────────────────────────────────────────────────────────── */
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
    <span class="toast-msg">${escapeHtml(message)}</span>
    <button class="toast-close" aria-label="Dismiss">×</button>
  `;

  container.appendChild(toast);

  const dismiss = () => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 300);
  };

  toast.querySelector('.toast-close').addEventListener('click', dismiss);
  setTimeout(dismiss, 4500);
}

/* ──────────────────────────────────────────────────────────────
   UTILITY FUNCTIONS
────────────────────────────────────────────────────────────── */

/** Format a number as currency (USD default). */
function formatCurrency(value, currency = 'USD') {
  if (value == null || isNaN(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: value >= 10000 ? 0 : 2,
    minimumFractionDigits: value >= 10000 ? 0 : 2,
  }).format(value);
}

/** Format a number as a percentage. */
function formatPercent(value, decimals = 2) {
  if (value == null || isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${Number(value).toFixed(decimals)}%`;
}

/** Format a plain number with commas. */
function formatNumber(value, decimals = 4) {
  if (value == null || isNaN(value)) return '—';
  if (Math.abs(value) >= 1000) return Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 });
  return Number(value).toFixed(decimals);
}

/** Escape HTML special characters. */
function formatAssetType(type) {
  if (!type) return 'Other';
  const mapping = {
    'stock': 'Equities',
    'etf': 'ETFs',
    'cash': 'Cash & Cash Equivalents',
    'other': 'Other Assets'
  };
  const normalized = type.toLowerCase();
  return mapping[normalized] || type.charAt(0).toUpperCase() + type.slice(1);
}

/** Escape HTML special characters. */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/** Debounce a function. */
function debounce(fn, delay = 300) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), delay);
  };
}

/** Format an ISO date string to a readable form. */
function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }).format(new Date(iso));
  } catch (_) { return iso; }
}

/** Animated number counter. */
function animateNumber(el, targetVal, formatter) {
  if (!el) return;
  const start = 0;
  const duration = 900;
  const startTime = performance.now();

  function tick(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 4); // ease-out quartic
    const current = start + (targetVal - start) * ease;
    el.textContent = formatter(current);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/** Get badge class for asset type. */
function typeBadgeClass(type) {
  return TYPE_BADGE_MAP[type] || 'badge-other';
}

/** Get status badge class. */
function statusBadgeClass(status) {
  return STATUS_CLASSES[(status || '').toLowerCase()] || 'status-pending';
}

/* ──────────────────────────────────────────────────────────────
   NAVIGATION / TAB ROUTING
────────────────────────────────────────────────────────────── */
function initNavigation() {
  const tabs    = document.querySelectorAll('.nav-tab');
  const panels  = document.querySelectorAll('.tab-panel');

  function switchTab(tabId) {
    // update state
    setState('activeTab', tabId);

    // nav tabs
    tabs.forEach(t => {
      t.classList.toggle('active', t.dataset.tab === tabId);
    });

    // panels
    panels.forEach(p => {
      const isActive = p.dataset.panel === tabId;
      p.hidden = !isActive;
    });

    // hash
    window.location.hash = tabId;

    // lazy-load tab data
    if (tabId === 'holdings')   fetchHoldings();
    if (tabId === 'statements') fetchStatements();
    if (tabId === 'portfolio')  renderPortfolioTab();
    if (tabId === 'dashboard')  fetchPortfolioSummary();
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', e => {
      e.preventDefault();
      switchTab(tab.dataset.tab);
    });
  });

  // hash-based routing on load
  const hash = window.location.hash.replace('#', '');
  const validTabs = ['dashboard', 'holdings', 'statements', 'portfolio'];
  switchTab(validTabs.includes(hash) ? hash : 'dashboard');

  // Navbar scroll shadow
  window.addEventListener('scroll', () => {
    document.getElementById('navbar').classList.toggle('scrolled', window.scrollY > 10);
  }, { passive: true });

  // Quick upload buttons
  document.getElementById('navUploadBtn')?.addEventListener('click', () => switchTab('dashboard'));
  document.getElementById('stmtUploadBtn')?.addEventListener('click', () => {
    switchTab('dashboard');
    document.getElementById('uploadZone')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

/* ──────────────────────────────────────────────────────────────
   API HEALTH CHECK
────────────────────────────────────────────────────────────── */
async function checkApiHealth() {
  const dot   = document.getElementById('statusDot');
  const label = document.getElementById('statusLabel');
  try {
    await apiClient.get('/health');
    dot.className   = 'status-dot connected';
    label.textContent = 'Connected';
  } catch (_) {
    dot.className   = 'status-dot error';
    label.textContent = 'Offline';
  }
}

/* ──────────────────────────────────────────────────────────────
   UPLOAD HANDLER
────────────────────────────────────────────────────────────── */
function initUpload() {
  const zone         = document.getElementById('uploadZone');
  const fileInput    = document.getElementById('fileInput');
  const progressWrap = document.getElementById('uploadProgressWrap');
  const progressBar  = document.getElementById('uploadProgressBar');
  const pctLabel     = document.getElementById('uploadPct');
  const filenameEl   = document.getElementById('uploadFilename');
  const statusMsg    = document.getElementById('uploadStatusMsg');

  // Drag events
  ['dragenter', 'dragover'].forEach(ev => {
    zone.addEventListener(ev, e => {
      e.preventDefault();
      e.stopPropagation();
      zone.classList.add('drag-over');
    });
  });

  ['dragleave', 'dragend'].forEach(ev => {
    zone.addEventListener(ev, e => {
      // Only remove if truly leaving the zone
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove('drag-over');
      }
    });
  });

  zone.addEventListener('drop', e => {
    e.preventDefault();
    e.stopPropagation();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleFileUpload(file);
  });

  zone.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (file) handleFileUpload(file);
    fileInput.value = ''; // reset so same file can be re-uploaded
  });

  async function handleFileUpload(file) {
    // Validate type
    if (!file.type.includes('pdf') && !file.name.toLowerCase().endsWith('.pdf')) {
      showToast('Please upload a PDF file.', 'error');
      return;
    }
    // Validate size (<50 MB)
    if (file.size > 50 * 1024 * 1024) {
      showToast('File too large. Maximum size is 50 MB.', 'error');
      return;
    }

    // Show progress UI
    progressWrap.hidden = false;
    filenameEl.textContent = file.name;
    setProgress(0, 'Uploading…');

    try {
      const result = await apiClient.uploadFile('/statements/upload', file, pct => {
        setProgress(pct, `Uploading… ${pct}%`);
      });

      setProgress(100, 'Upload complete! Parsing statement…');
      showToast(`"${file.name}" uploaded successfully. Parsing in progress.`, 'success');

      // Poll for statement status
      const stmtId = result.id || result.statement_id;
      if (stmtId) pollStatementStatus(stmtId, file.name);

      // Refresh statements list
      fetchStatements();

    } catch (err) {
      setProgress(0, `Upload failed: ${err.message}`);
      statusMsg.style.color = 'var(--color-error)';
      showToast(`Upload failed: ${err.message}`, 'error');
      setTimeout(() => { progressWrap.hidden = true; statusMsg.style.color = ''; }, 4000);
    }
  }

  function setProgress(pct, msg) {
    progressBar.style.width = `${pct}%`;
    pctLabel.textContent    = `${pct}%`;
    statusMsg.textContent   = msg;
  }
}

/** Poll statement status every 2s until it's no longer pending/processing. */
function pollStatementStatus(stmtId, filename = '') {
  // Prevent duplicate polls
  if (AppState.pollingIds[stmtId]) return;

  const intervalId = setInterval(async () => {
    try {
      const stmt = await apiClient.get(`/statements/${stmtId}`);
      const status = (stmt.parse_status || '').toLowerCase();

      if (status !== 'pending' && status !== 'processing') {
        clearInterval(intervalId);
        delete AppState.pollingIds[stmtId];

        if (status === 'success' || status === 'completed') {
          showToast(`"${filename || stmt.filename}" parsed successfully!`, 'success');
          fetchStatements();
          fetchPortfolioSummary();
          fetchHoldings();
          fetchRecentActivities();
        } else if (status === 'failed' || status === 'error') {
          showToast(`Parsing failed for "${filename || stmt.filename}". Please try again.`, 'error');
          fetchStatements();
        }

        // Hide progress bar
        const progressWrap = document.getElementById('uploadProgressWrap');
        if (progressWrap) setTimeout(() => { progressWrap.hidden = true; }, 2000);
      } else {
        // Update status message
        const statusMsg = document.getElementById('uploadStatusMsg');
        if (statusMsg) statusMsg.textContent = `Parsing… (${status})`;
      }
    } catch (err) {
      clearInterval(intervalId);
      delete AppState.pollingIds[stmtId];
    }
  }, 2000);

  AppState.pollingIds[stmtId] = intervalId;
}

/* ──────────────────────────────────────────────────────────────
   PORTFOLIO SUMMARY
────────────────────────────────────────────────────────────── */
async function fetchPortfolioSummary() {
  const accountId = AppState.filters.dashboardAccountId;
  try {
    // Portfolio summary endpoint
    let url = '/portfolio/summary';
    if (accountId) {
      url += `?account_id=${accountId}`;
    }
    const summary = await apiClient.get(url);
    setState('portfolioSummary', summary);
    renderSummaryCards(summary);
    fetchRecentActivities(accountId);
    populateAccountSelector();

    // Allocation data
    if (summary.allocation || summary.asset_allocation) {
      const alloc = summary.allocation || summary.asset_allocation;
      setState('allocation', alloc);
      renderDonutChart(alloc);
      renderPortfolioTab();
    }
  } catch (err) {
    // API not available — render placeholder cards
    renderSummaryCards(null);
  }
}

function renderSummaryCards(data) {
  const safe = data || {};

  // Total Value
  const totalVal = safe.total_value ?? safe.total_portfolio_value ?? 0;
  const elTotalVal = document.getElementById('valTotalValue');
  if (elTotalVal) {
    elTotalVal.classList.remove('skeleton');
    if (totalVal) animateNumber(elTotalVal, totalVal, v => formatCurrency(v));
    else elTotalVal.textContent = data ? '$0.00' : '—';
  }
  const metaTotal = document.getElementById('metaTotalValue');
  if (metaTotal) metaTotal.textContent = safe.currency ? `In ${safe.currency}` : 'All accounts';

  // Holdings count
  const holdCount = safe.num_holdings ?? safe.total_holdings ?? safe.holding_count ?? 0;
  const elHold = document.getElementById('valHoldings');
  if (elHold) {
    elHold.classList.remove('skeleton');
    elHold.textContent = data ? holdCount.toLocaleString() : '—';
  }
  const metaHold = document.getElementById('metaHoldings');
  if (metaHold && data) {
    const alloc = safe.asset_allocation || safe.allocation || [];
    const types = alloc.length || safe.asset_types || safe.num_asset_types || 0;
    metaHold.textContent = types ? `Across ${types} asset types` : 'Across all types';
  }

  // Accounts count
  const accCount = safe.num_accounts ?? safe.total_accounts ?? safe.account_count ?? 0;
  const elAcc = document.getElementById('valAccounts');
  if (elAcc) {
    elAcc.classList.remove('skeleton');
    elAcc.textContent = data ? accCount.toLocaleString() : '—';
  }
  const metaAcc = document.getElementById('metaAccounts');
  if (metaAcc && data) {
    const stmts = safe.num_statements ?? safe.statement_count ?? safe.total_statements ?? 0;
    metaAcc.textContent = stmts ? `From ${stmts} statement${stmts !== 1 ? 's' : ''}` : 'All brokers';
  }
}

async function fetchRecentActivities(accountId = '') {
  try {
    let url = '/activities?limit=15';
    if (accountId) {
      url += `&account_id=${accountId}`;
    }
    const data = await apiClient.get(url);
    const activities = Array.isArray(data) ? data : (data.items || data.activities || []);
    renderRecentActivities(activities);
  } catch (err) {
    renderRecentActivities([]);
  }
}

function renderRecentActivities(activities) {
  const tbody = document.getElementById('activityBody');
  if (!tbody) return;

  if (!activities || !activities.length) {
    tbody.innerHTML = `
      <tr class="empty-state-row">
        <td colspan="6">
          <div class="empty-state" style="padding: 2rem 0;">
            <p>No transactions recorded yet.<br/>Upload a brokerage statement to get started.</p>
          </div>
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = activities.map(act => {
    let dateStr = '—';
    if (act.trade_date) {
      try {
        const parts = act.trade_date.split('-');
        if (parts.length === 3) {
          dateStr = `${parts[1]}/${parts[2]}/${parts[0]}`;
        } else {
          dateStr = new Intl.DateTimeFormat('en-US', {
            month: '2-digit', day: '2-digit', year: 'numeric'
          }).format(new Date(act.trade_date));
        }
      } catch (_) {
        dateStr = act.trade_date;
      }
    }

    const type = act.activity_type || 'OTHER';
    const typeLabel = type.toUpperCase();
    let badgeClass = 'badge-act-other';
    if (typeLabel === 'BUY') badgeClass = 'badge-act-buy';
    else if (typeLabel === 'SELL') badgeClass = 'badge-act-sell';
    else if (typeLabel === 'DIVIDEND') badgeClass = 'badge-act-dividend';
    else if (typeLabel === 'DEPOSIT') badgeClass = 'badge-act-deposit';
    else if (typeLabel === 'WITHDRAWAL') badgeClass = 'badge-act-withdrawal';

    const desc = act.description || '—';
    const qty = act.quantity;
    const price = act.price;
    const amt = act.amount;

    let amtStr = '—';
    if (amt != null) {
      if (amt < 0) {
        amtStr = `(${formatCurrency(Math.abs(amt))})`;
      } else {
        amtStr = formatCurrency(amt);
      }
    }

    let priceStr = price != null ? formatCurrency(price) : '—';
    let qtyStr = qty != null ? formatNumber(qty, 4) : '—';

    let amtClass = '';
    if (typeLabel === 'DIVIDEND' || typeLabel === 'DEPOSIT') {
      amtClass = 'gl-positive';
    } else if (typeLabel === 'WITHDRAWAL') {
      amtClass = 'gl-negative';
    }

    return `
      <tr>
        <td style="font-variant-numeric: tabular-nums;">${dateStr}</td>
        <td><span class="type-badge ${badgeClass}">${typeLabel}</span></td>
        <td><div class="activity-desc" title="${escapeHtml(desc)}">${escapeHtml(desc)}</div></td>
        <td class="num-col">${qtyStr}</td>
        <td class="num-col">${priceStr}</td>
        <td class="num-col ${amtClass}">${amtStr}</td>
      </tr>`;
  }).join('');
}

/* ──────────────────────────────────────────────────────────────
   DONUT CHART (Pure SVG)
────────────────────────────────────────────────────────────── */
function renderDonutChart(data) {
  const container = document.getElementById('donutChart');
  const legend    = document.getElementById('donutLegend');
  if (!container || !legend) return;
  if (!data || !data.length) return;

  const size   = 200;
  const cx     = 100;
  const cy     = 100;
  const R      = 78;
  const r      = 52;  // inner radius → stroke-width = R - r
  const strokeW = R - r;

  // Normalize percentages
  const total = data.reduce((s, d) => s + (d.total_value || d.value || 0), 0);
  const items = data.map((d, i) => ({
    label: formatAssetType(d.asset_type || d.type || d.label || 'Other'),
    value: d.total_value || d.value || 0,
    pct:   d.pct ?? (total ? (d.total_value || d.value || 0) / total * 100 : 0),
    count: d.count || 0,
    color: CHART_COLORS[i % CHART_COLORS.length],
  }));

  const circumference = 2 * Math.PI * (r + strokeW / 2);  // midpoint radius
  const midR = r + strokeW / 2;

  // Build SVG arcs
  let svgPaths = '';
  let cumPct = 0;

  items.forEach((item, idx) => {
    const dashArr    = (item.pct / 100) * circumference;
    const dashOffset = circumference - (cumPct / 100) * circumference;
    const animDelay  = idx * 80;

    svgPaths += `
      <circle
        class="donut-arc"
        cx="${cx}" cy="${cy}" r="${midR}"
        fill="none"
        stroke="${item.color}"
        stroke-width="${strokeW}"
        stroke-dasharray="${dashArr} ${circumference - dashArr}"
        stroke-dashoffset="${dashOffset}"
        stroke-linecap="butt"
        style="
          animation: draw-arc 0.8s ${animDelay}ms cubic-bezier(0.23,1,0.32,1) both;
          transform-origin: ${cx}px ${cy}px;
        "
      >
        <title>${item.label}: ${item.pct.toFixed(1)}%</title>
      </circle>`;

    cumPct += item.pct;
  });

  // Center text
  const totalFmt = formatCurrency(total, 'USD');

  container.innerHTML = `
    <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}"
         style="transform:rotate(-90deg); overflow:visible;">
      <style>
        @keyframes draw-arc {
          from { stroke-dasharray: 0 ${circumference}; }
        }
      </style>
      <!-- Background ring -->
      <circle cx="${cx}" cy="${cy}" r="${midR}"
              fill="none" stroke="rgba(255,255,255,0.04)"
              stroke-width="${strokeW}"/>
      ${svgPaths}
    </svg>
    <div class="donut-center-text">
      <span class="donut-center-label">Total</span>
      <span class="donut-center-value">${formatCurrency(total)}</span>
    </div>`;

  // Legend
  legend.innerHTML = items.map(item => `
    <div class="legend-item">
      <span class="legend-dot" style="background:${item.color}"></span>
      <span class="legend-label">${escapeHtml(item.label)}</span>
      <span class="legend-pct">${item.pct.toFixed(1)}%</span>
      <span class="legend-val">${formatCurrency(item.value)}</span>
    </div>`).join('');
}

/* ──────────────────────────────────────────────────────────────
   HOLDINGS TABLE
────────────────────────────────────────────────────────────── */
async function fetchHoldings() {
  try {
    const params = new URLSearchParams();
    if (AppState.filters.dashboardAccountId) params.append('account_id', AppState.filters.dashboardAccountId);
    if (AppState.filters.statementId) params.append('statement_id', AppState.filters.statementId);
    const data = await apiClient.get(`/holdings?${params}`);
    const holdings = Array.isArray(data) ? data : (data.holdings || data.items || []);
    setState('holdings', holdings);
    renderHoldingsTable();
    populateStatementFilter(holdings);
  } catch (err) {
    setState('holdings', []);
    renderHoldingsTable();
  }
}

/** Populate statement filter dropdown from unique statement IDs in holdings. */
function populateStatementFilter(holdings) {
  const sel = document.getElementById('statementFilter');
  if (!sel) return;
  const stmts = AppState.statements;

  // Keep first option
  while (sel.options.length > 1) sel.remove(1);

  const ids = [...new Set(holdings.map(h => h.statement_id).filter(Boolean))];
  ids.forEach(id => {
    const stmt = stmts.find(s => s.id === id);
    const label = stmt ? (stmt.original_filename || stmt.filename || `Statement ${id}`) : `Statement ${id}`;
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = label.length > 30 ? label.slice(0, 27) + '…' : label;
    sel.appendChild(opt);
  });
}

function getFilteredSortedHoldings() {
  let items = [...AppState.holdings];

  // Search filter
  const q = AppState.filters.search.toLowerCase().trim();
  if (q) {
    items = items.filter(h =>
      (h.asset_name || h.name || '').toLowerCase().includes(q) ||
      (h.ticker || '').toLowerCase().includes(q)
    );
  }

  // Type filter
  const type = AppState.filters.type;
  if (type) {
    items = items.filter(h => (h.asset_type || h.type || '') === type);
  }

  // Statement filter
  const stmtId = AppState.filters.statementId;
  if (stmtId) {
    items = items.filter(h => String(h.statement_id) === String(stmtId));
  }

  // Sort
  const { col, dir } = AppState.sort;
  if (col) {
    items.sort((a, b) => {
      let va = a[col];
      let vb = b[col];
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      if (va == null) va = dir === 'asc' ? Infinity : -Infinity;
      if (vb == null) vb = dir === 'asc' ? Infinity : -Infinity;
      return dir === 'asc' ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });
  }

  return items;
}

function renderHoldingsTable() {
  const tbody     = document.getElementById('holdingsBody');
  const countEl   = document.getElementById('resultsCount');
  if (!tbody) return;

  const filtered  = getFilteredSortedHoldings();
  const visibleTotal = filtered.reduce((sum, item) => sum + (item.market_value || 0), 0);
  const total     = filtered.length;
  const { page, perPage } = AppState.pagination;
  const start     = (page - 1) * perPage;
  const pageItems = filtered.slice(start, start + perPage);

  if (countEl) countEl.textContent = `${total} holding${total !== 1 ? 's' : ''}`;

  if (!pageItems.length) {
    tbody.innerHTML = `
      <tr class="empty-state-row">
        <td colspan="9">
          <div class="empty-state">
            <svg viewBox="0 0 64 64" fill="none" width="56" height="56">
              <circle cx="32" cy="32" r="30" stroke="rgba(255,255,255,0.07)" stroke-width="2"/>
              <path d="M22 32h20M22 24h12M22 40h16" stroke="rgba(255,255,255,0.2)" stroke-width="2" stroke-linecap="round"/>
            </svg>
            <p>${AppState.holdings.length ? 'No holdings match your filters.' : 'No holdings yet.<br/>Upload a brokerage statement to get started.'}</p>
          </div>
        </td>
      </tr>`;
    renderPagination(0, 0);
    return;
  }

  tbody.innerHTML = pageItems.map(h => {
    const name      = h.asset_name || h.name || '—';
    const ticker    = h.ticker || '—';
    const type      = h.asset_type || h.type || 'Other';
    const qty       = h.quantity;
    const price     = h.current_price;
    const mktVal    = h.market_value;
    const badgeClass= typeBadgeClass(type);

    return `
      <tr>
        <td>
          <div class="holding-name">${escapeHtml(name)}</div>
        </td>
        <td>
          <span class="ticker-cell">${escapeHtml(ticker)}</span>
        </td>
        <td><span class="type-badge ${badgeClass}">${escapeHtml(type)}</span></td>
        <td class="num-col">${qty != null ? formatNumber(qty) : '—'}</td>
        <td class="num-col">${price != null ? formatCurrency(price) : '—'}</td>
        <td class="num-col">${mktVal != null ? formatCurrency(mktVal) : '—'}</td>
      </tr>`;
  }).join('');

  renderPagination(total, page);
  updateSortIndicators();
}

function renderPagination(total, currentPage) {
  const { perPage } = AppState.pagination;
  const totalPages  = Math.ceil(total / perPage);
  const prevBtn     = document.getElementById('prevPage');
  const nextBtn     = document.getElementById('nextPage');
  const pageNums    = document.getElementById('pageNumbers');
  if (!prevBtn || !nextBtn || !pageNums) return;

  prevBtn.disabled = currentPage <= 1;
  nextBtn.disabled = currentPage >= totalPages;

  if (totalPages <= 1) {
    pageNums.innerHTML = '';
    return;
  }

  // Show at most 7 page buttons, with ellipsis
  const pages = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i);
  } else {
    pages.push(1);
    if (currentPage > 3) pages.push('…');
    for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) pages.push(i);
    if (currentPage < totalPages - 2) pages.push('…');
    pages.push(totalPages);
  }

  pageNums.innerHTML = pages.map(p =>
    typeof p === 'number'
      ? `<button class="page-num${p === currentPage ? ' active' : ''}" data-page="${p}">${p}</button>`
      : `<span class="page-num" style="cursor:default;opacity:0.4">…</span>`
  ).join('');
}

function updateSortIndicators() {
  const { col, dir } = AppState.sort;
  document.querySelectorAll('.holdings-table th.sortable').forEach(th => {
    const isActive = th.dataset.col === col;
    th.classList.toggle('sort-active', isActive);
    const icon = th.querySelector('.sort-icon');
    if (icon) icon.textContent = isActive ? (dir === 'asc' ? '↑' : '↓') : '↕';
  });
}

function initHoldingsControls() {
  // Search (debounced)
  const searchInput = document.getElementById('holdingSearch');
  if (searchInput) {
    searchInput.addEventListener('input', debounce(() => {
      AppState.filters.search = searchInput.value;
      AppState.pagination.page = 1;
      renderHoldingsTable();
    }, 300));
  }

  // Type filter
  const typeFilter = document.getElementById('typeFilter');
  if (typeFilter) {
    typeFilter.addEventListener('change', () => {
      AppState.filters.type = typeFilter.value;
      AppState.pagination.page = 1;
      renderHoldingsTable();
    });
  }

  // Statement filter
  const stmtFilter = document.getElementById('statementFilter');
  if (stmtFilter) {
    stmtFilter.addEventListener('change', () => {
      AppState.filters.statementId = stmtFilter.value;
      AppState.pagination.page = 1;
      renderHoldingsTable();
    });
  }

  // Sortable headers (event delegation)
  const table = document.getElementById('holdingsTable');
  if (table) {
    table.querySelector('thead').addEventListener('click', e => {
      const th = e.target.closest('th.sortable');
      if (!th) return;
      const col = th.dataset.col;
      if (AppState.sort.col === col) {
        AppState.sort.dir = AppState.sort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        AppState.sort.col = col;
        AppState.sort.dir = 'desc';
      }
      AppState.pagination.page = 1;
      renderHoldingsTable();
    });
  }

  // Pagination (event delegation on container)
  document.getElementById('pagination')?.addEventListener('click', e => {
    if (e.target.id === 'prevPage' || e.target.closest('#prevPage')) {
      AppState.pagination.page = Math.max(1, AppState.pagination.page - 1);
      renderHoldingsTable();
    } else if (e.target.id === 'nextPage' || e.target.closest('#nextPage')) {
      const filtered  = getFilteredSortedHoldings();
      const totalPgs  = Math.ceil(filtered.length / AppState.pagination.perPage);
      AppState.pagination.page = Math.min(totalPgs, AppState.pagination.page + 1);
      renderHoldingsTable();
    } else if (e.target.classList.contains('page-num') && e.target.dataset.page) {
      AppState.pagination.page = parseInt(e.target.dataset.page, 10);
      renderHoldingsTable();
    }
  });

  // Export CSV
  document.getElementById('exportCsvBtn')?.addEventListener('click', exportHoldingsCsv);
}

function exportHoldingsCsv() {
  const items = getFilteredSortedHoldings();
  if (!items.length) { showToast('No data to export.', 'info'); return; }

  const cols = ['asset_name', 'ticker', 'asset_type', 'quantity', 'current_price', 'market_value'];
  const header = ['Asset Name','Ticker','Type','Quantity','Price','Market Value'];

  const rows = items.map(h =>
    cols.map(c => {
      const v = h[c];
      if (v == null) return '';
      if (typeof v === 'string' && v.includes(',')) return `"${v}"`;
      return v;
    }).join(',')
  );

  const csv  = [header.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `pivotmoney-holdings-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('Holdings exported as CSV.', 'success');
}

/* ──────────────────────────────────────────────────────────────
   STATEMENTS PANEL
────────────────────────────────────────────────────────────── */
async function fetchStatements() {
  try {
    const params = new URLSearchParams();
    if (AppState.filters.dashboardAccountId) {
      params.append('account_id', AppState.filters.dashboardAccountId);
    }
    const data = await apiClient.get(`/statements?${params}`);
    const stmts = Array.isArray(data) ? data : (data.statements || data.items || []);
    setState('statements', stmts);
    renderStatements(stmts);
    updateLogCount();
  } catch (err) {
    setState('statements', []);
    renderStatements([]);
  }
}

function renderStatements(statements) {
  const grid = document.getElementById('statementsGrid');
  if (!grid) return;

  if (!statements.length) {
    grid.innerHTML = `
      <div class="empty-state-card">
        <div class="empty-state">
          <svg viewBox="0 0 64 64" fill="none" width="56" height="56">
            <rect x="12" y="8" width="40" height="48" rx="4" stroke="rgba(255,255,255,0.1)" stroke-width="2"/>
            <path d="M20 20h24M20 28h24M20 36h16" stroke="rgba(255,255,255,0.15)" stroke-width="2" stroke-linecap="round"/>
          </svg>
          <p>No statements uploaded yet.<br/>Click <strong>Upload Statement</strong> to get started.</p>
        </div>
      </div>`;
    return;
  }

  grid.innerHTML = statements.map(stmt => buildStatementCard(stmt)).join('');
  attachStatementEvents();
}

function buildStatementCard(stmt) {
  const id         = stmt.id || stmt.statement_id;
  const filename   = stmt.original_filename || stmt.filename || 'Unknown file';
  const uploadDate = formatDate(stmt.uploaded_at || stmt.created_at);
  const stmtDate   = stmt.statement_date ? formatDate(stmt.statement_date) : '—';
  const status     = (stmt.parse_status || 'pending').toLowerCase();
  const statusCls  = statusBadgeClass(status);
  const confidence = stmt.confidence_score != null ? Math.round(stmt.confidence_score * 100) : null;
  const holdCount  = stmt.holding_count ?? stmt.total_holdings ?? 0;
  const broker     = stmt.broker || stmt.brokerage || '';

  return `
    <div class="statement-card reveal" data-stmt-id="${id}">
      <div class="stmt-card-header">
        <div class="stmt-file-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
            <polyline points="10 9 9 9 8 9"/>
          </svg>
        </div>
        <div class="stmt-title-wrap">
          <div class="stmt-filename" title="${escapeHtml(filename)}">${escapeHtml(filename)}</div>
          <div class="stmt-meta">
            Uploaded ${uploadDate}${broker ? ` · ${escapeHtml(broker)}` : ''}
          </div>
        </div>
        <span class="status-badge ${statusCls}">${status}</span>
      </div>

      <div style="display:flex;gap:.75rem;flex-wrap:wrap;font-size:.8125rem;color:var(--color-text-sec)">
        <span>📅 Statement: <strong style="color:var(--color-text)">${stmtDate}</strong></span>
        ${holdCount ? `<span>📊 <strong style="color:var(--color-text)">${holdCount}</strong> holdings</span>` : ''}
      </div>

      <div class="stmt-card-actions">
        <button class="btn btn-secondary btn-sm stmt-view-btn" data-stmt-id="${id}">
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/></svg>
          View Holdings
        </button>
        <button class="btn btn-ghost btn-sm stmt-logs-btn" data-stmt-id="${id}" data-filename="${escapeHtml(filename)}">
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h6a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>
          Logs
        </button>
        <button class="btn btn-danger btn-sm stmt-delete-btn" data-stmt-id="${id}" data-filename="${escapeHtml(filename)}">
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
        </button>
      </div>
    </div>`;
}

function attachStatementEvents() {
  const grid = document.getElementById('statementsGrid');
  if (!grid) return;

  grid.addEventListener('click', e => {
    // View Holdings
    const viewBtn = e.target.closest('.stmt-view-btn');
    if (viewBtn) {
      const stmtId = viewBtn.dataset.stmtId;
      viewStatementHoldings(stmtId);
      return;
    }
    // Logs
    const logsBtn = e.target.closest('.stmt-logs-btn');
    if (logsBtn) {
      const stmtId   = logsBtn.dataset.stmtId;
      const filename = logsBtn.dataset.filename;
      fetchParseLogs(stmtId, filename);
      return;
    }
    // Delete
    const delBtn = e.target.closest('.stmt-delete-btn');
    if (delBtn) {
      const stmtId   = delBtn.dataset.stmtId;
      const filename = delBtn.dataset.filename;
      confirmDeleteStatement(stmtId, filename);
    }
  });

  // Trigger reveal animations
  requestAnimationFrame(() => {
    grid.querySelectorAll('.reveal').forEach((el, i) => {
      setTimeout(() => el.classList.add('visible'), i * 60);
    });
  });
}

function viewStatementHoldings(stmtId) {
  AppState.filters.statementId = stmtId;
  AppState.pagination.page = 1;
  // Switch to holdings tab
  document.querySelector('.nav-tab[data-tab="holdings"]')?.click();
  // Update filter dropdown after tab switch
  setTimeout(() => {
    const sel = document.getElementById('statementFilter');
    if (sel) sel.value = stmtId;
    renderHoldingsTable();
  }, 100);
}

/* ──────────────────────────────────────────────────────────────
   DELETE STATEMENT
────────────────────────────────────────────────────────────── */
function confirmDeleteStatement(stmtId, filename) {
  const backdrop = document.getElementById('confirmBackdrop');
  const msgEl    = document.getElementById('confirmMsg');
  const okBtn    = document.getElementById('confirmOk');
  const cancelBtn= document.getElementById('confirmCancel');
  if (!backdrop) return;

  msgEl.textContent = `Are you sure you want to delete "${filename}"? This will also remove all associated holdings. This action cannot be undone.`;
  backdrop.hidden = false;

  const handleOk = async () => {
    backdrop.hidden = true;
    okBtn.removeEventListener('click', handleOk);
    cancelBtn.removeEventListener('click', handleCancel);
    await deleteStatement(stmtId);
  };

  const handleCancel = () => {
    backdrop.hidden = true;
    okBtn.removeEventListener('click', handleOk);
    cancelBtn.removeEventListener('click', handleCancel);
  };

  okBtn.addEventListener('click', handleOk);
  cancelBtn.addEventListener('click', handleCancel);
  backdrop.addEventListener('click', e => { if (e.target === backdrop) handleCancel(); }, { once: true });
}

async function deleteStatement(stmtId) {
  try {
    await apiClient.delete(`/statements/${stmtId}`);
    showToast('Statement deleted successfully.', 'success');
    fetchStatements();
    fetchPortfolioSummary();
    fetchRecentActivities();
    // Remove from holdings if filtered by this statement
    if (AppState.filters.statementId === stmtId) {
      AppState.filters.statementId = '';
    }
    fetchHoldings();
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, 'error');
  }
}

/* ──────────────────────────────────────────────────────────────
   PARSE LOGS
────────────────────────────────────────────────────────────── */
async function fetchParseLogs(stmtId, filename = '') {
  const logsBody   = document.getElementById('logsBody');
  const logsToggle = document.getElementById('logsToggle');
  const stmtLabel  = document.getElementById('logsStmtLabel');
  const entriesEl  = document.getElementById('logEntries');

  if (!logsBody || !entriesEl) return;

  // Expand logs panel
  logsBody.hidden = false;
  logsToggle.setAttribute('aria-expanded', 'true');
  if (stmtLabel) stmtLabel.textContent = `Logs for: ${filename || stmtId}`;

  entriesEl.innerHTML = `<div class="log-entry log-info"><span class="log-level-icon">ℹ️</span><span class="log-msg">Loading logs…</span><span class="log-ts">—</span></div>`;

  try {
    const data = await apiClient.get(`/statements/${stmtId}/logs`);
    const logs = Array.isArray(data) ? data : (data.logs || data.entries || []);

    setState('selectedStmtForLogs', stmtId);
    updateLogCount(logs.length);

    if (!logs.length) {
      entriesEl.innerHTML = `<div class="log-entry log-info"><span class="log-level-icon">ℹ️</span><span class="log-msg">No log entries for this statement.</span><span class="log-ts">—</span></div>`;
      return;
    }

    entriesEl.innerHTML = logs.map(log => {
      const level  = (log.level || log.log_level || 'info').toLowerCase();
      const msg    = log.message || log.msg || '—';
      const ts     = log.timestamp || log.created_at || '';
      const icon   = LOG_ICONS[level] || 'ℹ️';
      const cls    = level === 'error' ? 'log-error' : level === 'warning' || level === 'warn' ? 'log-warning' : 'log-info';

      return `
        <div class="log-entry ${cls}">
          <span class="log-level-icon">${icon}</span>
          <span class="log-msg">${escapeHtml(msg)}</span>
          <span class="log-ts">${ts ? formatDate(ts) : '—'}</span>
        </div>`;
    }).join('');

    // Scroll to bottom
    entriesEl.scrollTop = entriesEl.scrollHeight;
    logsBody.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  } catch (err) {
    entriesEl.innerHTML = `<div class="log-entry log-error"><span class="log-level-icon">❌</span><span class="log-msg">Failed to load logs: ${escapeHtml(err.message)}</span><span class="log-ts">—</span></div>`;
  }
}

function updateLogCount(count) {
  const badge = document.getElementById('logCount');
  if (badge) badge.textContent = count != null ? count : (AppState.statements.length || 0);
}

function initLogsPanel() {
  const toggle  = document.getElementById('logsToggle');
  const body    = document.getElementById('logsBody');
  const clearBtn= document.getElementById('clearLogsView');

  toggle?.addEventListener('click', () => {
    const expanded = body.hidden;
    body.hidden = !expanded;
    toggle.setAttribute('aria-expanded', expanded);
  });

  clearBtn?.addEventListener('click', () => {
    const entriesEl = document.getElementById('logEntries');
    if (entriesEl) entriesEl.innerHTML = `<div class="log-entry log-info"><span class="log-level-icon">ℹ️</span><span class="log-msg">Select a statement above to view its parse logs.</span><span class="log-ts">—</span></div>`;
    const stmtLabel = document.getElementById('logsStmtLabel');
    if (stmtLabel) stmtLabel.textContent = 'Select a statement to view logs';
    updateLogCount(0);
  });
}

/* ──────────────────────────────────────────────────────────────
   PORTFOLIO TAB
────────────────────────────────────────────────────────────── */
function renderPortfolioTab() {
  renderAllocationTable();
  renderTopHoldings();
}

function renderAllocationTable() {
  const container = document.getElementById('allocationTable');
  if (!container) return;

  const alloc = AppState.allocation;
  if (!alloc || !alloc.length) {
    container.innerHTML = `<div class="empty-state" style="padding:2rem 0"><p>Upload a statement to see allocation details.</p></div>`;
    return;
  }

  const total = alloc.reduce((s, a) => s + (a.total_value || a.value || 0), 0);

  container.innerHTML = alloc.map((a, i) => {
    const label = formatAssetType(a.asset_type || a.type || a.label || 'Other');
    const val   = a.total_value || a.value || 0;
    const pct   = a.pct ?? (total ? val / total * 100 : 0);
    const color = CHART_COLORS[i % CHART_COLORS.length];
    const count = a.count || a.holding_count || 0;

    return `
      <div class="alloc-row">
        <span class="alloc-dot" style="background:${color}"></span>
        <span class="alloc-label">${escapeHtml(label)}${count ? ` <small style="opacity:.5">(${count})</small>` : ''}</span>
        <div class="alloc-bar-wrap">
          <div class="alloc-bar-track">
            <div class="alloc-bar-fill" style="width:${pct.toFixed(2)}%;background:${color}"></div>
          </div>
        </div>
        <span class="alloc-pct">${pct.toFixed(1)}%</span>
        <span class="alloc-val">${formatCurrency(val)}</span>
      </div>`;
  }).join('');
}

function renderTopHoldings() {
  const container = document.getElementById('topHoldingsList');
  if (!container) return;

  const holdings = AppState.portfolioSummary?.top_holdings || [];

  if (!holdings.length) {
    container.innerHTML = `<div class="empty-state" style="padding:2rem 0"><p>No data available yet.</p></div>`;
    return;
  }

  const maxVal = holdings[0].market_value || 1;
  const summaryTotal = AppState.portfolioSummary?.total_value || 1;

  container.innerHTML = holdings.map((h, i) => {
    const name   = h.asset_name || h.name || '—';
    const ticker = h.ticker || '';
    const val    = h.market_value || 0;
    const pct    = summaryTotal ? (val / summaryTotal * 100) : 0;
    const barPct = (val / maxVal) * 100;

    return `
      <div class="top-holding-item">
        <span class="top-holding-rank">${i + 1}</span>
        <div class="top-holding-info">
          <div class="top-holding-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
          ${ticker ? `<div class="top-holding-ticker">${escapeHtml(ticker)}</div>` : ''}
        </div>
        <div class="top-holding-bar-wrap">
          <div class="top-holding-bar-track">
            <div class="top-holding-bar-fill" style="width:${barPct.toFixed(1)}%"></div>
          </div>
        </div>
        <span class="top-holding-val">${formatCurrency(val)}</span>
        <span class="top-holding-pct">${pct.toFixed(1)}%</span>
      </div>`;
  }).join('');
}

/* ──────────────────────────────────────────────────────────────
   MODAL
────────────────────────────────────────────────────────────── */
function initModal() {
  const backdrop   = document.getElementById('modalBackdrop');
  const closeBtn   = document.getElementById('modalClose');
  const closeBtnFt = document.getElementById('modalCloseBtn');

  const close = () => { backdrop.hidden = true; };
  closeBtn?.addEventListener('click', close);
  closeBtnFt?.addEventListener('click', close);
  backdrop?.addEventListener('click', e => { if (e.target === backdrop) close(); });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !backdrop.hidden) close();
  });
}

function openStatementModal(stmt) {
  const backdrop = document.getElementById('modalBackdrop');
  const title    = document.getElementById('modalTitle');
  const body     = document.getElementById('modalBody');
  const viewBtn  = document.getElementById('modalViewHoldings');
  if (!backdrop) return;

  title.textContent = stmt.original_filename || stmt.filename || 'Statement Detail';

  const rows = [
    ['Filename',    stmt.original_filename || stmt.filename],
    ['Status',      stmt.parse_status],
    ['Broker',      stmt.broker || stmt.brokerage],
    ['Stmt Date',   stmt.statement_date ? formatDate(stmt.statement_date) : null],
    ['Uploaded',    formatDate(stmt.uploaded_at || stmt.created_at)],
    ['Holdings',    stmt.holding_count ?? stmt.total_holdings],
    ['Account #',   stmt.account_number],
  ].filter(([, v]) => v != null && v !== '');

  body.innerHTML = rows.map(([label, val]) => `
    <div class="modal-detail-row">
      <span class="modal-detail-label">${label}</span>
      <span class="modal-detail-value">${escapeHtml(String(val))}</span>
    </div>`).join('');

  viewBtn.onclick = () => {
    backdrop.hidden = true;
    viewStatementHoldings(stmt.id || stmt.statement_id);
  };

  backdrop.hidden = false;
}

/* ──────────────────────────────────────────────────────────────
   SCROLL REVEAL
────────────────────────────────────────────────────────────── */
function initScrollReveal() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
}



/* ──────────────────────────────────────────────────────────────
   INITIALIZATION
────────────────────────────────────────────────────────────── */
async function init() {
  // Navigation
  initNavigation();

  // Upload
  initUpload();

  // Holdings controls
  initHoldingsControls();

  // Logs panel
  initLogsPanel();

  // Modal
  initModal();

  // Account selector
  initAccountSelector();

  // Scroll reveal
  initScrollReveal();

  // Check API health
  await checkApiHealth();

  // Load data from API
  try {
    await fetchPortfolioSummary();
    await fetchStatements();
    await fetchRecentActivities();
    // Holdings are loaded lazily when the tab is switched
  } catch (err) {
    showToast('Failed to load portfolio data from server.', 'error');
  }

  // Reveal summary cards with stagger
  document.querySelectorAll('.summary-card').forEach((card, i) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(16px)';
    card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    setTimeout(() => {
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, 100 + i * 80);
  });
}

/* ──────────────────────────────────────────────────────────────
   ACCOUNT SELECTOR BINDINGS
   ────────────────────────────────────────────────────────────── */
const ACCOUNT_SELECTORS = [
  { selectId: 'dashboardAccountSelect', wrapId: 'dashboardAccountSelectWrap' },
  { selectId: 'holdingsAccountSelect',  wrapId: 'holdingsAccountSelectWrap' },
  { selectId: 'portfolioAccountSelect', wrapId: 'portfolioAccountSelectWrap' }
];

async function populateAccountSelector() {
  try {
    const accounts = await apiClient.get('/portfolio/accounts');
    
    ACCOUNT_SELECTORS.forEach(selInfo => {
      const select = document.getElementById(selInfo.selectId);
      const wrap = document.getElementById(selInfo.wrapId);
      if (!select || !wrap) return;

      if (accounts && accounts.length > 1) {
        const currentVal = select.value || AppState.filters.dashboardAccountId;
        
        // Clear previous options except the first one
        while (select.options.length > 1) select.remove(1);

        accounts.forEach(acc => {
          const opt = document.createElement('option');
          opt.value = acc.account_id;
          
          let label = '';
          if (acc.account_name) {
            label = `${acc.account_name} (${acc.account_number})`;
          } else {
            const broker = acc.broker_name ? `${acc.broker_name} · ` : '';
            label = `${broker}${acc.account_number}`;
          }
          
          opt.textContent = label;
          select.appendChild(opt);
        });

        select.value = currentVal;
        wrap.hidden = false;
      } else {
        wrap.hidden = true;
      }
    });
  } catch (err) {
    ACCOUNT_SELECTORS.forEach(selInfo => {
      const wrap = document.getElementById(selInfo.wrapId);
      if (wrap) wrap.hidden = true;
    });
  }
}

function initAccountSelector() {
  ACCOUNT_SELECTORS.forEach(selInfo => {
    const select = document.getElementById(selInfo.selectId);
    if (!select) return;

    select.addEventListener('change', () => {
      const selectedVal = select.value;
      AppState.filters.dashboardAccountId = selectedVal;

      // Sync all select elements to the same value
      ACCOUNT_SELECTORS.forEach(s => {
        const el = document.getElementById(s.selectId);
        if (el) el.value = selectedVal;
      });

      // Refresh all data tabs so everything is in sync immediately
      fetchPortfolioSummary();
      fetchHoldings();
      fetchStatements();
      fetchRecentActivities(selectedVal);
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
