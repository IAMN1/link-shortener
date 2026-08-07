/**
 * main.js – Global utilities: API helpers, dropdown, logout.
 */

var SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS', 'TRACE'];

// The session lives in HttpOnly cookies, which scripts cannot read. The only
// token the page handles is the CSRF one, which is readable by design.
function getCsrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : null;
}

// Adds the CSRF header to state-changing requests. Exposed for the few pages
// that call fetch directly instead of going through apiFetch.
function csrfHeaders(base, method) {
    var headers = Object.assign({ 'Content-Type': 'application/json' }, base || {});
    if (SAFE_METHODS.indexOf((method || 'POST').toUpperCase()) === -1) {
        var csrf = getCsrfToken();
        if (csrf) headers['X-CSRF-Token'] = csrf;
    }
    return headers;
}

async function apiFetch(url, opts) {
    opts = opts || {};
    opts.headers = csrfHeaders(opts.headers, opts.method || 'GET');
    opts.credentials = 'same-origin';
    var resp = await fetch(url, opts);
    if (resp.status === 401) {
        window.location.href = '/login';
        return null;
    }
    return resp;
}

async function logoutUser() {
    await apiFetch('/api/v1/auth/logout', { method: 'POST' });
    window.location.href = '/login';
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatDate(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleDateString();
}

window.apiFetch = apiFetch;
window.csrfHeaders = csrfHeaders;
window.logoutUser = logoutUser;
window.escapeHtml = escapeHtml;
window.formatDate = formatDate;

document.addEventListener('DOMContentLoaded', function() {
    // Dropdown toggle
    var toggle = document.getElementById('dropdown-toggle');
    var menu = document.getElementById('dropdown-menu');
    if (toggle && menu) {
        toggle.addEventListener('click', function(e) {
            e.stopPropagation();
            menu.classList.toggle('active');
        });
        document.addEventListener('click', function(e) {
            if (!toggle.contains(e.target) && !menu.contains(e.target)) {
                menu.classList.remove('active');
            }
        });
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') menu.classList.remove('active');
        });
    }

    // Mobile nav toggle
    var navToggle = document.getElementById('nav-toggle');
    if (navToggle) {
        navToggle.addEventListener('click', function() {
            if (menu) menu.classList.toggle('active');
        });
    }

    // Logout link
    var logoutLink = document.getElementById('logout-link');
    if (logoutLink) {
        logoutLink.addEventListener('click', function(e) {
            e.preventDefault();
            logoutUser();
        });
    }
});
