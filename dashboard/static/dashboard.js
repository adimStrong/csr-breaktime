/**
 * CSR Breaktime Dashboard - Frontend JavaScript
 */

const API_BASE = window.location.origin;
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
const REFRESH_INTERVAL = 30000; // 30 seconds fallback

// Chart instances
let distributionChart = null;
let trendChart = null;
let hourlyChart = null;

// State
let dashboardData = null;
let agentData = [];
let websocket = null;
let wsReconnectAttempts = 0;

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    loadDashboard();
    connectWebSocket();

    // Fallback polling if WebSocket fails
    setInterval(() => {
        if (!websocket || websocket.readyState !== WebSocket.OPEN) {
            loadDashboard();
        }
    }, REFRESH_INTERVAL);

    // Search functionality
    document.getElementById('agentSearch').addEventListener('input', filterAgents);
});

// ============================================
// WEBSOCKET
// ============================================

function connectWebSocket() {
    try {
        websocket = new WebSocket(WS_URL);

        websocket.onopen = () => {
            console.log('[WS] Connected');
            wsReconnectAttempts = 0;
            updateConnectionStatus(true);
        };

        websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'realtime_update') {
                handleRealtimeUpdate(data.data);
            }
        };

        websocket.onclose = () => {
            console.log('[WS] Disconnected');
            updateConnectionStatus(false);
            // Reconnect with exponential backoff
            const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts), 30000);
            wsReconnectAttempts++;
            setTimeout(connectWebSocket, delay);
        };

        websocket.onerror = (error) => {
            console.error('[WS] Error:', error);
        };
    } catch (e) {
        console.error('[WS] Connection failed:', e);
    }
}

function handleRealtimeUpdate(data) {
    updateStats(data.metrics);
    updateActiveBreaks(data.active_breaks);
    updateLastRefresh();

    if (data.overdue_count > 0) {
        showOverdueAlert(data.overdue_breaks);
    }
}

// ============================================
// API CALLS
// ============================================

async function fetchAPI(endpoint) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`API Error: ${endpoint}`, error);
        updateConnectionStatus(false);
        return null;
    }
}

async function loadDashboard() {
    const data = await fetchAPI('/api/dashboard');
    if (!data) return;

    dashboardData = data;
    updateConnectionStatus(true);
    updateLastRefresh();

    // Update all components
    updateStats(data.realtime);
    updateActiveBreaks(data.active_breaks);
    updateDistributionChart(data.break_distribution);
    updateTrendChart(data.compliance_trend);
    updateAgentTable(data.agent_performance);
    updateHourlyChart(data.hourly_distribution);

    // Check for overdue breaks
    const overdue = data.active_breaks.filter(b => b.is_overdue);
    if (overdue.length > 0) {
        showOverdueAlert(overdue);
    }
}

// ============================================
// UI UPDATES
// ============================================

function updateStats(realtime) {
    document.getElementById('activeBreaks').textContent = realtime.active_breaks;
    document.getElementById('complianceRate').textContent = `${realtime.compliance_rate}%`;
    document.getElementById('completedToday').textContent = realtime.completed_breaks_today;
    document.getElementById('totalBreakTime').textContent = formatDuration(realtime.total_break_time_today);
    document.getElementById('agentsActive').textContent = `${realtime.agents_active_today} agents active`;
    document.getElementById('overdueCount').textContent = `${realtime.overdue_breaks} overdue`;

    // Update compliance icon color
    const icon = document.getElementById('complianceIcon');
    if (realtime.compliance_rate >= 90) {
        icon.className = 'w-12 h-12 bg-green-100 rounded-full flex items-center justify-center';
        icon.innerHTML = '<i class="fas fa-check-circle text-green-500 text-xl"></i>';
    } else if (realtime.compliance_rate >= 80) {
        icon.className = 'w-12 h-12 bg-yellow-100 rounded-full flex items-center justify-center';
        icon.innerHTML = '<i class="fas fa-exclamation-circle text-yellow-500 text-xl"></i>';
    } else {
        icon.className = 'w-12 h-12 bg-red-100 rounded-full flex items-center justify-center';
        icon.innerHTML = '<i class="fas fa-times-circle text-red-500 text-xl"></i>';
    }
}

function updateActiveBreaks(breaks) {
    const container = document.getElementById('activeBreaksList');
    document.getElementById('activeBreaksBadge').textContent = breaks.length;

    if (breaks.length === 0) {
        container.innerHTML = '<p class="text-gray-400 text-center py-8"><i class="fas fa-coffee text-3xl mb-2 block"></i>No active breaks</p>';
        return;
    }

    container.innerHTML = breaks.map(b => {
        const statusClass = b.is_overdue ? 'border-red-200 bg-red-50' : 'border-gray-200';
        const timeClass = b.is_overdue ? 'text-red-600 font-bold' : 'text-gray-600';
        const badge = b.is_overdue
            ? `<span class="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">+${b.over_limit_minutes.toFixed(0)}m over</span>`
            : '';

        return `
            <div class="border ${statusClass} rounded-lg p-3 mb-2">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <div class="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center text-sm font-medium">
                            ${getInitials(b.full_name)}
                        </div>
                        <div>
                            <p class="font-medium text-gray-800">${b.full_name}</p>
                            <p class="text-xs text-gray-500">${b.break_type}</p>
                        </div>
                    </div>
                    <div class="text-right">
                        <p class="${timeClass}">${b.duration_minutes.toFixed(0)}m</p>
                        ${badge}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function updateAgentTable(agents) {
    agentData = agents;
    renderAgentTable(agents);
}

function renderAgentTable(agents) {
    const tbody = document.getElementById('agentTable');

    if (agents.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="px-4 py-8 text-center text-gray-400">No agents active today</td></tr>';
        return;
    }

    tbody.innerHTML = agents.map(a => {
        const statusDot = a.status === 'on_break'
            ? (a.current_break_duration > 30 ? 'status-overdue' : 'status-on_break')
            : 'status-available';
        const statusText = a.status === 'on_break'
            ? `${a.current_break_type} (${a.current_break_duration?.toFixed(0)}m)`
            : 'Available';

        const complianceColor = a.compliance_rate >= 90 ? 'text-green-600'
            : a.compliance_rate >= 80 ? 'text-yellow-600' : 'text-red-600';

        const complianceBar = `
            <div class="w-full bg-gray-200 rounded-full h-2">
                <div class="h-2 rounded-full ${a.compliance_rate >= 90 ? 'bg-green-500' : a.compliance_rate >= 80 ? 'bg-yellow-500' : 'bg-red-500'}"
                     style="width: ${Math.min(a.compliance_rate, 100)}%"></div>
            </div>
        `;

        return `
            <tr class="table-row">
                <td class="px-4 py-3">
                    <div class="flex items-center gap-2">
                        <div class="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center text-xs font-medium">
                            ${getInitials(a.full_name)}
                        </div>
                        <span class="font-medium text-gray-800">${a.full_name}</span>
                    </div>
                </td>
                <td class="px-4 py-3 text-center">
                    <div class="flex items-center justify-center gap-2">
                        <span class="status-dot ${statusDot}"></span>
                        <span class="text-sm text-gray-600">${statusText}</span>
                    </div>
                </td>
                <td class="px-4 py-3 text-center">
                    <span class="font-medium">${a.total_breaks}</span>
                    <span class="text-xs text-gray-400 block">${a.over_limit} over limit</span>
                </td>
                <td class="px-4 py-3 text-center">
                    <span class="font-medium">${a.total_duration.toFixed(0)}m</span>
                    <span class="text-xs text-gray-400 block">avg ${a.avg_duration.toFixed(1)}m</span>
                </td>
                <td class="px-4 py-3">
                    <div class="flex items-center gap-2">
                        <span class="font-medium ${complianceColor}">${a.compliance_rate.toFixed(0)}%</span>
                        <div class="flex-1">${complianceBar}</div>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function filterAgents() {
    const search = document.getElementById('agentSearch').value.toLowerCase();
    const filtered = agentData.filter(a => a.full_name.toLowerCase().includes(search));
    renderAgentTable(filtered);
}

// ============================================
// CHARTS
// ============================================

function initCharts() {
    // Distribution Chart (Doughnut)
    const distCtx = document.getElementById('distributionChart').getContext('2d');
    distributionChart = new Chart(distCtx, {
        type: 'doughnut',
        data: {
            labels: [],
            datasets: [{
                data: [],
                backgroundColor: ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { padding: 15, usePointStyle: true } }
            },
            cutout: '60%'
        }
    });

    // Trend Chart (Line)
    const trendCtx = document.getElementById('trendChart').getContext('2d');
    trendChart = new Chart(trendCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Compliance %',
                data: [],
                borderColor: '#22c55e',
                backgroundColor: 'rgba(34, 197, 94, 0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointBackgroundColor: '#22c55e'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { min: 0, max: 100, ticks: { callback: v => v + '%' } },
                x: { grid: { display: false } }
            }
        }
    });

    // Hourly Chart (Bar)
    const hourlyCtx = document.getElementById('hourlyChart').getContext('2d');
    hourlyChart = new Chart(hourlyCtx, {
        type: 'bar',
        data: {
            labels: [],
            datasets: [{
                label: 'Break Outs',
                data: [],
                backgroundColor: '#3b82f6',
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
                x: { grid: { display: false } }
            }
        }
    });
}

function updateDistributionChart(distribution) {
    const labels = distribution.map(d => d.break_type);
    const data = distribution.map(d => d.count);

    distributionChart.data.labels = labels;
    distributionChart.data.datasets[0].data = data;
    distributionChart.update();
}

function updateTrendChart(trend) {
    const labels = trend.map(t => {
        const d = new Date(t.date);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const data = trend.map(t => t.compliance_rate);

    trendChart.data.labels = labels;
    trendChart.data.datasets[0].data = data;
    trendChart.update();
}

function updateHourlyChart(hourly) {
    // Filter to working hours (6 AM - 10 PM)
    const filtered = hourly.filter(h => h.hour >= 6 && h.hour <= 22);
    const labels = filtered.map(h => h.hour_label);
    const data = filtered.map(h => h.break_outs);

    hourlyChart.data.labels = labels;
    hourlyChart.data.datasets[0].data = data;
    hourlyChart.update();
}

// ============================================
// ALERTS & MODALS
// ============================================

function showOverdueAlert(overdue) {
    const modal = document.getElementById('overdueModal');
    const list = document.getElementById('overdueList');

    list.innerHTML = overdue.map(b => `
        <div class="border border-red-200 bg-red-50 rounded-lg p-3 mb-2">
            <div class="flex items-center justify-between">
                <div>
                    <p class="font-medium text-gray-800">${b.full_name}</p>
                    <p class="text-sm text-gray-500">${b.break_type}</p>
                </div>
                <div class="text-right">
                    <p class="text-red-600 font-bold">${b.duration_minutes.toFixed(0)} min</p>
                    <p class="text-xs text-red-500">+${b.over_limit_minutes.toFixed(0)} over limit</p>
                </div>
            </div>
        </div>
    `).join('');

    // Only show modal if there are new overdue breaks
    if (!modal.classList.contains('flex')) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function closeModal() {
    const modal = document.getElementById('overdueModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

// ============================================
// UTILITIES
// ============================================

function formatDuration(minutes) {
    if (minutes < 60) return `${minutes.toFixed(0)}m`;
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    return `${hours}h ${mins}m`;
}

function getInitials(name) {
    return name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
}

function updateLastRefresh() {
    const now = new Date();
    document.getElementById('lastUpdate').innerHTML =
        `<i class="fas fa-sync-alt mr-1"></i> ${now.toLocaleTimeString()}`;
}

function updateConnectionStatus(connected) {
    const status = document.getElementById('connectionStatus');
    if (connected) {
        status.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-green-500/20 text-green-300 text-sm';
        status.innerHTML = '<span class="status-dot status-available"></span> Connected';
    } else {
        status.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/20 text-red-300 text-sm';
        status.innerHTML = '<span class="status-dot status-overdue"></span> Disconnected';
    }
}

// Close modal on backdrop click
document.getElementById('overdueModal').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});

// Keyboard shortcut to close modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ============================================
// EXPORT FUNCTIONS
// ============================================

function exportCSV(days = 7) {
    const end = new Date().toISOString().split('T')[0];
    const start = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    window.open(`${API_BASE}/api/export/csv?start=${start}&end=${end}`, '_blank');
}

function exportReport(type = 'daily') {
    window.open(`${API_BASE}/api/export/report?report_type=${type}`, '_blank');
}

function showExportModal() {
    const modal = document.createElement('div');
    modal.id = 'exportModal';
    modal.className = 'fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50';
    modal.innerHTML = `
        <div class="bg-white rounded-xl shadow-2xl max-w-sm w-full mx-4 overflow-hidden">
            <div class="bg-indigo-500 px-4 py-3 flex items-center justify-between">
                <h3 class="font-semibold text-white"><i class="fas fa-download mr-2"></i>Export Data</h3>
                <button onclick="closeExportModal()" class="text-white/80 hover:text-white"><i class="fas fa-times"></i></button>
            </div>
            <div class="p-4 space-y-3">
                <button onclick="exportCSV(7); closeExportModal();" class="w-full py-2 px-4 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
                    <i class="fas fa-file-csv mr-2"></i>Export CSV (Last 7 Days)
                </button>
                <button onclick="exportCSV(30); closeExportModal();" class="w-full py-2 px-4 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition">
                    <i class="fas fa-file-csv mr-2"></i>Export CSV (Last 30 Days)
                </button>
                <button onclick="exportReport('daily'); closeExportModal();" class="w-full py-2 px-4 bg-green-500 text-white rounded-lg hover:bg-green-600 transition">
                    <i class="fas fa-file-alt mr-2"></i>Daily Report (JSON)
                </button>
                <button onclick="exportReport('weekly'); closeExportModal();" class="w-full py-2 px-4 bg-green-500 text-white rounded-lg hover:bg-green-600 transition">
                    <i class="fas fa-file-alt mr-2"></i>Weekly Report (JSON)
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.onclick = (e) => { if (e.target === modal) closeExportModal(); };
}

function closeExportModal() {
    const modal = document.getElementById('exportModal');
    if (modal) modal.remove();
}
