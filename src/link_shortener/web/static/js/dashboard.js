/**
 * dashboard.js – Dashboard sidebar toggle and logout.
 */

// How wide the sidebar is drawn, kept in a cookie rather than in
// localStorage. The server reads a cookie and renders the rail narrow from
// the first paint; state read from storage arrives after the full sidebar
// is already on screen, so every page load would flash it open and snap it
// shut. A year, path-wide, and not sent along to another site -- there is
// no secret in it, it says how wide a menu is.
function rememberSidebar(state) {
    document.cookie = 'dash_sidebar=' + state
        + ';path=/;max-age=31536000;samesite=Lax';
}

document.addEventListener('DOMContentLoaded', function() {
    // Collapse the sidebar to a rail of icons, and back
    var collapse = document.getElementById('dash-collapse');
    var dash = document.getElementById('dash');
    if (collapse && dash) {
        collapse.addEventListener('click', function() {
            var railed = dash.classList.toggle('dash--rail');
            // The class is what the eye reads; this is what a screen
            // reader reads, and the two have to say the same thing.
            collapse.setAttribute('aria-expanded', railed ? 'false' : 'true');
            rememberSidebar(railed ? 'rail' : 'full');
        });
    }

    // Sidebar mobile toggle
    var sideToggle = document.getElementById('dash-toggle');
    var side = document.getElementById('dash-side');
    if (sideToggle && side) {
        sideToggle.addEventListener('click', function() { side.classList.toggle('active'); });
        document.addEventListener('click', function(e) {
            if (side.classList.contains('active') && !side.contains(e.target) && e.target !== sideToggle) {
                side.classList.remove('active');
            }
        });
    }

    // Logout button in sidebar
    var logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function() { logoutUser(); });
    }

    // Mark active sidebar link
    var path = window.location.pathname;
    document.querySelectorAll('.dash-side a').forEach(function(a) {
        if (a.getAttribute('href') === path) a.classList.add('active');
    });
});
