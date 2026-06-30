/**
 * dashboard.js – Dashboard sidebar toggle and logout.
 */
document.addEventListener('DOMContentLoaded', function() {
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
