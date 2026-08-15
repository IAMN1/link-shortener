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
    // Turbo's own page cache needs no clearing here, and a `clearCache()`
    // call that used to stand at this line was doing nothing: the
    // assignment below is a full load, which discards everything this tab
    // was holding, Turbo's snapshots included.
    //
    // What it does not discard is the browser's HTTP cache, and that used
    // to leave the previous account's dashboard one Back press away --
    // their address, their links, served with `transferSize` zero and no
    // request reaching the service. No front-end code can close that; it
    // is closed by `Cache-Control: no-store`, which `web/middleware/
    // cache_control.py` puts on every response belonging to an account.
    //
    // Home, not the login form. Signing out is the end of a visit rather
    // than the start of a sign-in, and the form asks for the credentials
    // of the account just left. The header carries a Login link for the
    // person who did mean to switch accounts.
    //
    // Assigned after the call rather than before: `apiFetch` sends its own
    // 401 to the login page, and a logout whose session had already
    // expired would otherwise land there.
    //
    // A full load rather than `Turbo.visit`, deliberately: it drops every
    // scrap of state this tab is holding -- caches, timers, whatever a page
    // script left on `window` -- which is exactly what leaving an account
    // should do.
    window.location.href = '/';
}

// What went wrong, in the words the service used. Every page that loads
// data used to answer a refusal with `if (!resp.ok) return;`, which left
// the screen on "Loading..." for good: a 403 and a slow network looked
// exactly alike to the person waiting.
async function apiErrorText(resp) {
    if (!resp) return 'The service could not be reached.';
    try {
        var data = await resp.json();
        return data.message || data.error || ('Request failed (' + resp.status + ')');
    } catch (e) {
        return 'Request failed (' + resp.status + ')';
    }
}

// Puts a message where the page reserved room for one, and falls back to
// the table body so a failure is never invisible.
function showLoadError(elementId, message, tbodyId, columns) {
    var el = document.getElementById(elementId);
    if (el) {
        el.textContent = message;
        el.classList.remove('hidden');
    }
    var tbody = tbodyId ? document.getElementById(tbodyId) : null;
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="' + (columns || 4)
            + '" class="text-muted text-center">' + escapeHtml(message) + '</td></tr>';
    }
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatDate(iso) {
    if (!iso) return '-';
    return new Date(iso).toLocaleDateString();
}

// `pressed` and `saysExpanded` are on the list because `dashboard.js` and
// the page scripts use them. The others are here because a page may call
// them directly.
window.pressed = pressed;
window.saysExpanded = saysExpanded;
window.apiFetch = apiFetch;
window.csrfHeaders = csrfHeaders;
window.logoutUser = logoutUser;
window.escapeHtml = escapeHtml;
window.formatDate = formatDate;
window.apiErrorText = apiErrorText;
window.showLoadError = showLoadError;

// How the page is painted, kept in a cookie rather than in localStorage, for
// the same reason the sidebar's width is: the server reads a cookie and can
// stamp `data-theme` on the document before the first frame. State read from
// storage arrives after the other theme is already on screen, so every page
// load would flash. A year, path-wide, and not sent along to another site --
// there is no secret in it, it says which of two palettes to use.
function rememberTheme(state) {
    document.cookie = 'theme=' + state
        + ';path=/;max-age=31536000;samesite=Lax';
}

// Which control was pressed, given the thing actually clicked. A click
// lands on whatever is under the pointer -- the label inside the button,
// the path inside the icon -- so the handler has to walk up to find the
// control it belongs to. Guarded because a click can be reported against a
// node that has no `closest`, such as the document itself.
function pressed(event, selector) {
    var el = event.target;
    if (!el || typeof el.closest !== 'function') return null;
    return el.closest(selector);
}

// The class is what the eye reads; `aria-expanded` is what a screen reader
// reads, and the two have to say the same thing.
function saysExpanded(toggle, menu) {
    if (!toggle || !menu) return;
    toggle.setAttribute('aria-expanded',
        menu.classList.contains('active') ? 'true' : 'false');
}

function toggleTheme() {
    var root = document.documentElement;
    var now = root.getAttribute('data-theme');
    // With nothing chosen yet the page is following the system, so the
    // first press has to start from what is actually on screen -- otherwise
    // it appears to do nothing.
    if (!now) {
        now = window.matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark' : 'light';
    }
    var next = now === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    rememberTheme(next);
}

// One listener on `document`, not one per control, and bound the moment
// this file runs rather than on `DOMContentLoaded`.
//
// Turbo replaces the whole `<body>` on every navigation. Listeners bound to
// elements inside it die with the body they were bound to, so the theme
// switch, the account menu and the logout link would all go quiet after the
// first navigation -- with their ids, their markup and their hooks intact,
// which is the kind of breakage a test that asserts on markup cannot see.
// `document` survives every navigation, so a listener here is bound once
// and keeps working for elements that did not exist when it was bound.
//
// The counterpart of that: this file is loaded from `<head>`. Turbo merges
// the head and leaves a script it already has alone, so this runs exactly
// once per tab. Loaded from the end of `<body>` it would be re-executed on
// every navigation, and each pass would add another listener to `document`
// -- the duplicate handlers this design exists to make impossible.
document.addEventListener('click', function(e) {
    // The theme switch deliberately does not return: this press still has
    // to reach the closing branch at the end of the handler. Before the
    // move to delegation these were two independent listeners, and a press
    // on the switch closed an open account menu as a side effect. A `return`
    // here left the menu hanging open, `aria-expanded` still saying "true".
    if (pressed(e, '#theme-toggle')) {
        toggleTheme();
    } else if (pressed(e, '#logout-link')) {
        // This one does return -- the page is being left.
        e.preventDefault();
        logoutUser();
        return;
    }

    // Looked up per click rather than held in a variable: after a
    // navigation the elements on screen are not the ones a variable would
    // still be pointing at.
    var toggle = document.getElementById('dropdown-toggle');
    var menu = document.getElementById('dropdown-menu');
    if (!toggle || !menu) return;

    if (pressed(e, '#dropdown-toggle')) {
        menu.classList.toggle('active');
        saysExpanded(toggle, menu);
        return;
    }

    // Anywhere else closes it. The press on the trigger returned above, so
    // this no longer needs `stopPropagation` to keep the opening click from
    // immediately closing the menu again -- both cases are now decided in
    // one place, in order.
    if (!menu.contains(e.target)) {
        menu.classList.remove('active');
        saysExpanded(toggle, menu);
    }
});

document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var menu = document.getElementById('dropdown-menu');
    if (!menu) return;
    menu.classList.remove('active');
    saysExpanded(document.getElementById('dropdown-toggle'), menu);
});
