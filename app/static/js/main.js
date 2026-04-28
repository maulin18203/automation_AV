/* ═══════════════════════════════════════════════════════════════════════════════
   BRIGHTHAVEN — Main JavaScript
   Sidebar toggle, live clock, SSE real-time, toast notifications, utilities
   ═══════════════════════════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', function() {
    initSidebar();
    initClock();
    initAutoAlertDismiss();
    initSSE();
});

/**
 * EXCLUSIVE FETCH MANAGER
 * Automatically aborts previous pending requests on the same channel/endpoint.
 * This ensures the "last request wins" and prevents race conditions.
 */
const _activeRequests = new Map();

window.exclusiveFetch = async function(url, options = {}) {
    // Use the URL (without query params) as the unique channel key
    const channel = options.channel || url.split('?')[0];
    
    if (_activeRequests.has(channel)) {
        _activeRequests.get(channel).abort();
    }
    
    const controller = new AbortController();
    _activeRequests.set(channel, controller);
    
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        _activeRequests.delete(channel);
        return response;
    } catch (err) {
        if (err.name === 'AbortError') {
            console.warn(`[Network] Aborted overlapping request: ${url}`);
            // Return a dummy object that won't crash .json() calls but can be identified
            return { ok: false, status: 499, json: () => Promise.resolve({ error: 'Aborted' }) };
        }
        _activeRequests.delete(channel);
        throw err;
    }
};

// ─── SIDEBAR TOGGLE ──────────────────────────────────────────────────────────
function initSidebar() {
    const toggle   = document.getElementById('sidebarToggle');
    const sidebar  = document.getElementById('sidebar');
    const overlay  = document.getElementById('sidebarOverlay');

    if (!toggle || !sidebar) return;

    toggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        if (overlay) overlay.classList.toggle('open');
    });
    if (overlay) {
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('open');
        });
    }
}

// ─── LIVE CLOCK ──────────────────────────────────────────────────────────────
function initClock() {
    const el = document.getElementById('liveClock');
    if (!el) return;

    function update() {
        const now = new Date();
        el.textContent = now.toLocaleTimeString('en-IN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true
        });
    }
    update();
    setInterval(update, 1000);
}

// ─── ALERT AUTO-DISMISS ──────────────────────────────────────────────────────
function initAutoAlertDismiss() {
    document.querySelectorAll('[data-auto-dismiss]').forEach(el => {
        setTimeout(() => {
            el.style.transition = 'opacity 0.4s, transform 0.4s';
            el.style.opacity = '0';
            el.style.transform = 'translateY(-10px)';
            setTimeout(() => el.remove(), 400);
        }, 5000);
    });
}

// ─── TOAST NOTIFICATIONS ─────────────────────────────────────────────────────
let _toastContainer = null;

function showToast(message, type = 'info') {
    if (!_toastContainer) {
        _toastContainer = document.createElement('div');
        Object.assign(_toastContainer.style, {
            position: 'fixed', bottom: '24px', right: '24px',
            zIndex: '9999', display: 'flex', flexDirection: 'column-reverse',
            gap: '8px', maxWidth: '380px'
        });
        document.body.appendChild(_toastContainer);
    }

    const icons = {
        success: 'bi-check-circle-fill',
        error:   'bi-x-circle-fill',
        warning: 'bi-exclamation-triangle-fill',
        info:    'bi-info-circle-fill'
    };
    const colors = {
        success: { bg: 'rgba(39,174,96,0.95)', border: '#27ae60' },
        error:   { bg: 'rgba(192,57,43,0.95)', border: '#c0392b' },
        warning: { bg: 'rgba(212,175,55,0.95)', border: '#d4af37' },
        info:    { bg: 'rgba(52,152,219,0.95)', border: '#3498db' }
    };

    const c = colors[type] || colors.info;
    const toast = document.createElement('div');
    Object.assign(toast.style, {
        padding: '12px 18px',
        borderRadius: '10px',
        background: c.bg,
        color: '#fff',
        fontSize: '0.875rem',
        fontWeight: '500',
        fontFamily: "'DM Sans', sans-serif",
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
        backdropFilter: 'blur(12px)',
        animation: 'slideUp 0.3s ease',
        overflow: 'hidden',
        position: 'relative'
    });

    // Progress bar
    const progress = document.createElement('div');
    Object.assign(progress.style, {
        position: 'absolute', bottom: '0', left: '0',
        height: '2px', width: '100%',
        background: 'rgba(255,255,255,0.3)',
        transformOrigin: 'left',
        animation: 'shrink 4s linear forwards'
    });

    toast.innerHTML = `<i class="bi ${icons[type] || icons.info}" style="font-size:1rem;flex-shrink:0"></i> ${message}`;
    toast.appendChild(progress);
    _toastContainer.appendChild(toast);

    // Remove after 4.5s
    setTimeout(() => {
        toast.style.transition = 'opacity 0.3s, transform 0.3s';
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

// Add toast animation keyframes
if (!document.getElementById('toastStyles')) {
    const style = document.createElement('style');
    style.id = 'toastStyles';
    style.textContent = `
        @keyframes slideUp {
            from { opacity:0; transform:translateY(20px); }
            to   { opacity:1; transform:translateY(0); }
        }
        @keyframes shrink {
            from { transform: scaleX(1); }
            to   { transform: scaleX(0); }
        }
    `;
    document.head.appendChild(style);
}

// ─── SSE (Server-Sent Events) ────────────────────────────────────────────────
function initSSE() {
    const indicator = document.getElementById('sseIndicator');

    // Only connect on user pages (not public pages)
    if (!document.querySelector('.sidebar')) return;

    let retryCount = 0;
    const maxRetry = 5;

    function connect() {
        try {
            const es = new EventSource('/user/api/sse');

            es.onopen = () => {
                retryCount = 0;
                if (indicator) {
                    indicator.classList.remove('disconnected');
                    indicator.classList.add('connected');
                    indicator.title = 'Real-time: Connected';
                }
            };

            es.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    handleSSEEvent(data);
                } catch (e) {}
            };

            es.onerror = () => {
                es.close();
                if (indicator) {
                    indicator.classList.remove('connected');
                    indicator.classList.add('disconnected');
                    indicator.title = 'Real-time: Disconnected';
                }

                if (retryCount < maxRetry) {
                    retryCount++;
                    setTimeout(connect, Math.min(5000 * retryCount, 30000));
                }
            };
        } catch (e) {
            // SSE not supported or endpoint not available
        }
    }

    connect();
}

function handleSSEEvent(data) {
    if (data.type === 'device_status') {
        // Update device card if visible
        const card = document.getElementById('card_' + data.deviceId);
        if (card) {
            const isOn = data.data && data.data.state === 'ON';
            if (isOn) card.classList.add('device-on');
            else      card.classList.remove('device-on');

            const status = document.getElementById('status_' + data.deviceId);
            if (status) status.textContent = isOn ? 'ON' : 'OFF';

            const checkbox = card.querySelector('[data-device]');
            if (checkbox) checkbox.checked = isOn;
        }
    } else if (data.type === 'device_offline') {
        showToast(`Device ${data.deviceId} went offline`, 'warning');
    }
}

// ─── CONFIRMATION MODAL ──────────────────────────────────────────────────────
function showConfirm(title, message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay open';
    overlay.innerHTML = `
        <div class="modal-box">
            <h3>${title}</h3>
            <p>${message}</p>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="modalCancel">Cancel</button>
                <button class="btn btn-primary" id="modalConfirm" style="width:auto">Confirm</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector('#modalCancel').onclick = () => overlay.remove();
    overlay.querySelector('#modalConfirm').onclick = () => { onConfirm(); overlay.remove(); };
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
}

// ─── PASSWORD STRENGTH ───────────────────────────────────────────────────────
function checkPasswordStrength(password) {
    let strength = 0;
    if (password.length >= 8) strength++;
    if (/[A-Z]/.test(password) && /[a-z]/.test(password)) strength++;
    if (/[0-9]/.test(password) && /[^A-Za-z0-9]/.test(password)) strength++;
    return strength; // 0=none, 1=weak, 2=medium, 3=strong
}

// ─── QUICK TIMER ─────────────────────────────────────────────────────────────
function setQuickTimer(deviceId, deviceName, minutes) {
    showToast(`Timer set: ${deviceName} will turn OFF in ${minutes} min`, 'info');

    setTimeout(() => {
        fetch('/user/api/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({device: deviceId, state: false})
        })
        .then(r => r.json())
        .then(d => {
            if (d.ok) {
                showToast(`Timer expired: ${deviceName} turned OFF`, 'success');
                // Update UI
                const card = document.getElementById('card_' + deviceId);
                if (card) {
                    card.classList.remove('device-on');
                    const status = card.querySelector('.device-status');
                    if (status) status.textContent = 'OFF';
                    const checkbox = card.querySelector('[data-device]');
                    if (checkbox) checkbox.checked = false;
                }
            }
        });
    }, minutes * 60 * 1000);
}
