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

// One listener on `document`, bound the moment this file runs -- the same
// arrangement as `main.js`, and for the same reason: Turbo replaces the
// whole `<body>` on navigation, so a listener bound to the sidebar itself
// would stop working the first time the visitor goes anywhere. `pressed` is
// defined in `main.js`, which is loaded ahead of this file.
//
// This file is loaded from `<head>` as well, so it runs once per tab rather
// than once per navigation.
document.addEventListener('click', function(e) {
    // Collapse the sidebar to a rail of icons, and back
    var collapse = pressed(e, '#dash-collapse');
    if (collapse) {
        var dash = document.getElementById('dash');
        if (!dash) return;
        var railed = dash.classList.toggle('dash--rail');
        // The class is what the eye reads; this is what a screen reader
        // reads, and the two have to say the same thing.
        collapse.setAttribute('aria-expanded', railed ? 'false' : 'true');
        rememberSidebar(railed ? 'rail' : 'full');
        return;
    }

    // Logout button in sidebar
    if (pressed(e, '#logout-btn')) {
        logoutUser();
        return;
    }

    // Sidebar mobile toggle
    var side = document.getElementById('dash-side');
    if (!side) return;

    // `saysExpanded` comes from `main.js`, and it is the same call the
    // account menu makes -- both are "a thing that opens", both mark it
    // open with the `active` class, and both have to say so out loud. The
    // class is what the eye reads; without this the button announced
    // "Menu, button" before the press and after it alike.
    var toggle = pressed(e, '#dash-toggle');
    if (toggle) {
        side.classList.toggle('active');
        saysExpanded(toggle, side);
        return;
    }

    // A press anywhere else puts it away again. The press on the toggle
    // returned above, so this cannot close what that press just opened.
    if (side.classList.contains('active') && !side.contains(e.target)) {
        side.classList.remove('active');
        saysExpanded(document.getElementById('dash-toggle'), side);
    }
});

// Which entry is current is no longer decided here. It used to be found
// by comparing `location.pathname` against every link once the page had
// been painted, which marked the menu a frame late on every load and
// would stop happening altogether once navigation no longer reloads the
// document. The server renders `aria-current="page"`, because the server
// is the one that knows which endpoint it is answering.
