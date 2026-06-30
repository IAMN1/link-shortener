/**
 * main.js – Global utilities: API helpers, dropdown, logout.
 */

function getToken() { return localStorage.getItem('admin_token'); }
function setToken(t) { localStorage.setItem('admin_token', t); }

async function apiFetch(url, opts) {
    opts = opts || {};
    var headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    var token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    opts.headers = headers;
    opts.credentials = 'same-origin';
    var resp = await fetch(url, opts);
    if (resp.status === 401) {
        localStorage.removeItem('admin_token');
        window.location.href = '/login';
        return null;
    }
    return resp;
}

async function logoutUser() {
    localStorage.removeItem('admin_token');
    await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
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
