/**
 * journals.js – The end of a journal, refreshed by polling.
 */
// Loaded from `<head>` with `defer`, beside `charts.js`, and for the
// identical reason: Turbo merges the head across navigations and leaves a
// script it already has alone, so this file runs exactly once per tab.
// This file owns a timer. Executed again on every navigation it would add
// a `turbo:before-cache` listener each time, and the leak the listener
// exists to stop -- a page still being polled after it has left the screen
// -- would be caused by the cure.
//
// The reading is a poll rather than a held connection, and that is a
// property of the deployment rather than a preference: production is
// `gunicorn --worker-class sync --workers 4`, where a request occupies a
// worker for its whole life. Four operators with a streaming journal page
// open would be the entire service, with nothing left to answer a
// redirect.

// Everything this file has started, so all of it can be stopped when the
// page goes away. Two, held apart for the reason `charts.js` holds its two
// apart: the freshness clock must survive a change of interval, and it was
// in the same list as the poll timer until choosing an interval stopped
// the clock.
var journalTimers = [];
var journalPollTimer = null;

function journalStopPolling() {
    journalTimers.forEach(function (id) { clearInterval(id); });
    journalTimers = [];
    journalPollTimer = null;
}

function journalTrack(id) {
    journalTimers.push(id);
    return id;
}

function journalStartPolling(seconds, work) {
    if (journalPollTimer !== null) {
        clearInterval(journalPollTimer);
        journalTimers = journalTimers.filter(function (id) {
            return id !== journalPollTimer;
        });
        journalPollTimer = null;
    }
    if (!seconds) return;
    journalPollTimer = journalTrack(setInterval(work, seconds * 1000));
}

document.addEventListener('turbo:before-cache', journalStopPolling);

// The intervals the controls offer, in seconds, with 0 for "not at all".
// Here as well as in the template because a value arriving from storage is
// not to be trusted: a stale or hand-edited preference would otherwise set
// an interval no button can undo.
var JOURNAL_INTERVALS = [0, 5, 10, 30, 60, 300];

// How many lines the controls offer. The service refuses anything above
// its own ceiling, and a preference naming 5000 would otherwise turn every
// poll into a 400 with nothing on screen to say why.
var JOURNAL_LINE_COUNTS = [50, 200, 1000];

// The reader's settings, kept the way the charts keep theirs: in
// `localStorage`, so walking to another page and back does not reset them.
// Wrapped, because storage throws rather than returning null in a browser
// that has it switched off.
function journalRemember(name, value) {
    try {
        if (value === undefined) return localStorage.getItem('linkr.journal.' + name);
        localStorage.setItem('linkr.journal.' + name, value);
    } catch (e) {
        return null;
    }
    return value;
}

// The fields every record carries, drawn in their own columns. What is
// left over goes into `Details`, which is where a record's own subject
// lives -- `short_code`, `remote_addr`, `status`.
var JOURNAL_COLUMNS = ['timestamp', 'level', 'event'];

// `logger` is dropped from `Details` rather than shown: every line carries
// it, it repeats the module name already implied by the event, and on a
// narrow screen it pushes the fields somebody is actually reading out of
// sight. It stays in the raw line, which is one click away.
var JOURNAL_QUIET = ['logger'];

function journalDetails(fields) {
    var parts = [];
    Object.keys(fields).forEach(function (key) {
        if (JOURNAL_COLUMNS.indexOf(key) !== -1) return;
        if (JOURNAL_QUIET.indexOf(key) !== -1) return;
        var value = fields[key];
        if (value === null || value === undefined) return;
        if (typeof value === 'object') value = JSON.stringify(value);
        parts.push(key + '=' + value);
    });
    return parts.join('  ');
}

// A level as a word plus a shape, never as a colour alone: the colour is
// lost to a screenshot, to a printer and to a reader who cannot see it,
// and "error" is exactly the row somebody is scanning for.
function journalLevelMarkup(level) {
    if (!level) return '';
    var known = ['debug', 'info', 'warning', 'error', 'critical'];
    var name = String(level).toLowerCase();
    var suffix = known.indexOf(name) === -1 ? '' : ' journal-level--' + name;
    return '<span class="journal-level' + suffix + '">' + escapeHtml(level) + '</span>';
}

function journalRow(line) {
    // A line nothing could parse is shown as it was written and marked as
    // such. Dropping it would make this viewer least trustworthy exactly
    // when it matters most -- a write torn by rotation, a traceback a
    // library printed itself -- and showing it as an empty record would
    // say the service wrote a record with nothing in it.
    if (!line.parsed) {
        return '<tr class="journal-row journal-row--raw">'
            + '<td colspan="3" class="journal-raw">' + escapeHtml(line.raw) + '</td>'
            + '<td class="journal-source">' + escapeHtml(t('journal_unparsed')) + '</td>'
            + '</tr>';
    }

    var fields = line.fields || {};
    var details = journalDetails(fields);
    // The raw line under the row it came from, hidden until asked for.
    // Everything on the row above is a rendering, and an operator
    // reconstructing an incident eventually needs the bytes.
    return '<tr class="journal-row" tabindex="0" data-journal-row>'
        + '<td class="journal-time" title="' + escapeHtml(journalLocal(fields.timestamp))
        + '">' + escapeHtml(journalMoment(fields.timestamp)) + '</td>'
        + '<td>' + journalLevelMarkup(fields.level) + '</td>'
        + '<td class="journal-event">' + escapeHtml(fields.event || '') + '</td>'
        + '<td class="journal-details"><span class="truncate">' + escapeHtml(details) + '</span></td>'
        + '</tr>'
        + '<tr class="journal-expanded hidden"><td colspan="4">'
        + '<pre class="journal-raw">' + escapeHtml(line.raw) + '</pre>'
        + '</td></tr>';
}

// The timestamp exactly as the file carries it, with the `T` opened out so
// it can be read at a glance. Not converted to local time: the journals are
// stamped in UTC on purpose -- one clock for every process that writes --
// and a page that quietly shifted them would leave an operator comparing a
// screen against a file and finding them three hours apart.
//
// The local reading is offered as the cell's tooltip instead. It was in the
// cell to begin with, in brackets, and looking at the page settled it: on a
// journal every line of which is the same second, a third of the table's
// width went to saying the same time twice.
function journalMoment(stamp) {
    if (!stamp) return '';
    return String(stamp).replace('T', ' ');
}

function journalLocal(stamp) {
    if (!stamp) return '';
    var local = formatTime(stamp);
    return local === '-' ? '' : local;
}

function mountJournals(root) {
    if (!root) return;

    var body = root.querySelector('[data-journal-body]');
    var scroller = root.querySelector('[data-journal-scroll]');
    var title = root.querySelector('[data-journal-title]');
    var reach = root.querySelector('[data-journal-reach]');
    var errorBox = document.getElementById('journal-error');
    var freshness = root.querySelector('[data-journal-fresh-text]');
    var freshDot = root.querySelector('[data-journal-fresh-dot]');
    var journalButtons = Array.prototype.slice.call(root.querySelectorAll('[data-journal]'));
    var lineButtons = Array.prototype.slice.call(root.querySelectorAll('[data-journal-lines]'));
    var everyButtons = Array.prototype.slice.call(root.querySelectorAll('[data-journal-every]'));
    var archivesButton = root.querySelector('[data-journal-archives]');
    var refreshButton = root.querySelector('[data-journal-refresh]');
    var searchForm = root.querySelector('[data-journal-search]');
    var clearButton = root.querySelector('[data-journal-clear]');
    var termInputs = Array.prototype.slice.call(
        root.querySelectorAll('[data-journal-term]')
    );

    // Which journals this caller may read is decided by the server: the
    // buttons for the others are not rendered at all. So the offered set
    // is read off the markup rather than listed here, and a remembered
    // choice the caller has since lost the permission for falls back to
    // whatever they can still read.
    var offered = journalButtons.map(function (button) {
        return button.getAttribute('data-journal');
    });
    if (!offered.length) return;

    var journal = journalRemember('journal');
    if (offered.indexOf(journal) === -1) journal = offered[0];

    var lines = Number(journalRemember('lines'));
    if (JOURNAL_LINE_COUNTS.indexOf(lines) === -1) lines = 200;

    // Read before it is converted, because `Number(null)` is 0 and 0 is a
    // legal interval here -- it is the off switch. Read the other way, a
    // first visit opens with polling already off, looking exactly like a
    // deliberate choice nobody made.
    var storedEvery = journalRemember('every');
    var every = (storedEvery === null || storedEvery === '') ? 10 : Number(storedEvery);
    if (isNaN(every) || JOURNAL_INTERVALS.indexOf(every) === -1) every = 10;

    var archives = journalRemember('archives') === 'yes';

    // The terms are not remembered between visits, unlike the journal and
    // the interval. A search is a question somebody is asking now, and a
    // page that reopened still filtered would answer it with a journal
    // that looks empty -- with the reason two scrolls up, in a field they
    // filled in yesterday.
    function terms() {
        var asked = {};
        termInputs.forEach(function (input) {
            var value = (input.value || '').trim();
            if (value) asked[input.getAttribute('data-journal-term')] = value;
        });
        return asked;
    }

    function searching() {
        return Object.keys(terms()).length > 0;
    }
    var loadedAt = null;

    function pressed(buttons, matches) {
        buttons.forEach(function (button) {
            button.setAttribute('aria-pressed', String(matches(button)));
        });
    }

    function everyWords() {
        var chosen = everyButtons.filter(function (button) {
            return Number(button.getAttribute('data-journal-every')) === every;
        })[0];
        // Spelled by the button the reader pressed, so "every 5 min" and
        // the control that set it cannot disagree -- and the words stay in
        // the template where `gettext` can reach them.
        return chosen ? chosen.textContent.trim() : '';
    }

    function journalWords() {
        var chosen = journalButtons.filter(function (button) {
            return button.getAttribute('data-journal') === journal;
        })[0];
        return chosen ? chosen.textContent.trim() : journal;
    }

    function paintFreshness() {
        if (!freshness) return;
        var text;
        if (loadedAt === null) {
            text = '';
        } else {
            var seconds = Math.round((Date.now() - loadedAt) / 1000);
            if (seconds < 5) text = t('chart_updated_now');
            else if (seconds < 60) text = t('chart_updated_seconds', { count: seconds });
            else text = t('chart_updated_minutes', { count: Math.floor(seconds / 60) });
        }
        var suffix = every
            ? t('chart_every', { interval: everyWords() })
            : t('chart_polling_off');
        freshness.textContent = text ? text + ' · ' + suffix : suffix;
        if (freshDot) {
            freshDot.classList.toggle('chart-fresh-dot--off', !every);
        }
    }

    function showError(message) {
        if (!errorBox) return;
        errorBox.textContent = message;
        errorBox.classList.remove('hidden');
    }

    function clearError() {
        if (errorBox) errorBox.classList.add('hidden');
    }

    // What this answer reached, as against what exists. Without it the
    // oldest line on screen reads as the beginning of the journal, when it
    // is nearly always the point at which the page filled up.
    function paintReach(page) {
        if (!reach) return;
        var said = [t('journal_lines_read', {
            count: formatNumber(page.lines.length),
            files: page.files_read.join(', ') || '—',
        })];

        // With terms in play the two numbers stop being the same one, and
        // the difference is the answer: "five in fifty thousand lines" is
        // a different fact from "five lines in this journal".
        if (searching()) {
            said.push(t('journal_found', {
                found: formatNumber(page.lines.length),
                scanned: formatNumber(page.total_scanned),
            }));
            // A search that ran out of window has not looked at the whole
            // journal, and saying "this is the start" there would tell a
            // reader the account they are after was never here.
            said.push(page.reached_start
                ? t('journal_begins')
                : t('journal_window_ended'));
        } else {
            said.push(page.reached_start ? t('journal_begins') : t('journal_more'));
        }

        if (page.oldest_available && !archives) {
            said.push(t('journal_archives_reach', { name: page.oldest_available }));
        }
        reach.textContent = said.join(' ');
    }

    function paint(page) {
        if (title) title.textContent = journalWords();
        if (!body) return;

        // Whether the reader is watching the tail, asked before the rows
        // underneath them are replaced.
        //
        // Only this case is handled, and that is a measurement rather than
        // an oversight. A reader stopped partway keeps their place by
        // themselves: replacing the rows through `innerHTML` leaves the
        // box's `scrollTop` where it was, so restoring it -- which the
        // first version of this did -- was a line that changed nothing.
        // Measured by removing it: 300 before the poll and 300 after.
        // Somebody at the bottom is the case the browser gets wrong: the
        // new lines are added below them and the box does not follow, so
        // two polls at five seconds left them 204 pixels behind the tail
        // they were watching.
        var atTheTail = scroller
            ? scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 40
            : false;

        if (!page.lines.length) {
            // Both keys asked for by name rather than through one `t()`
            // over a conditional: the catalogue and the scripts are
            // checked against each other by reading the `t('...')` calls,
            // and a key computed at run time is a key that check cannot
            // see -- it reads as a sentence shipped to every page that
            // nothing ever asks for.
            var nothing = searching() ? t('journal_no_matches') : t('journal_empty');
            body.innerHTML = '<tr><td colspan="4" class="text-muted text-center">'
                + escapeHtml(nothing) + '</td></tr>';
        } else {
            body.innerHTML = page.lines.map(journalRow).join('');
        }
        paintReach(page);

        if (scroller && atTheTail) {
            scroller.scrollTop = scroller.scrollHeight - scroller.clientHeight;
        }
    }

    // `following` says this request continues a reading the audit journal
    // has already recorded, and it is the only thing that decides whether
    // this one is recorded too. Without it every poll would write a line
    // into the journal being displayed -- twelve a minute, each of them
    // then shown to the reader who came to look at something else.
    async function load(following) {
        try {
            // Built rather than pasted together, for the reason
            // `chartQuery` is: `URLSearchParams` escapes the values, and a
            // line count arriving from storage is a value like any other.
            var query = new URLSearchParams({
                limit: lines,
                archives: archives ? 'true' : 'false',
                follow: following ? 'true' : 'false',
            });
            var asked = terms();
            Object.keys(asked).forEach(function (name) {
                query.set(name, asked[name]);
            });
            var resp = await apiFetch(
                '/api/v1/journals/' + journal + '?' + query.toString()
            );
            if (!resp) return;
            if (!resp.ok) {
                showLoadError('journal-error', await apiErrorText(resp),
                              null, 4);
                return;
            }
            clearError();
            var page = await resp.json();
            paint(page);
            loadedAt = Date.now();
            paintFreshness();
        } catch (e) {
            showError(t('journal_failed'));
        }
    }

    function repoll() {
        journalStartPolling(every, function () { load(true); });
    }

    // A different journal, or a different number of lines, is a different
    // reading -- so it opens at its newest line rather than at whatever
    // offset the previous one happened to be scrolled to. Done by sending
    // the box to the bottom first, which is what `paint` then reads as
    // "this reader is watching the tail".
    function loadFresh() {
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
        // Not a continuation: a different journal, or a different depth of
        // the same one, is somebody going to look at something else, and
        // the audit journal records it as such.
        load(false);
    }

    journalButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            journal = button.getAttribute('data-journal');
            journalRemember('journal', journal);
            pressed(journalButtons, function (other) {
                return other === button;
            });
            loadFresh();
        });
    });

    lineButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            lines = Number(button.getAttribute('data-journal-lines'));
            journalRemember('lines', lines);
            pressed(lineButtons, function (other) { return other === button; });
            loadFresh();
        });
    });

    everyButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            every = Number(button.getAttribute('data-journal-every'));
            journalRemember('every', every);
            pressed(everyButtons, function (other) { return other === button; });
            paintFreshness();
            repoll();
        });
    });

    if (archivesButton) {
        archivesButton.addEventListener('click', function () {
            archives = !archives;
            journalRemember('archives', archives ? 'yes' : 'no');
            archivesButton.setAttribute('aria-pressed', String(archives));
            loadFresh();
        });
    }

    if (refreshButton) {
        // `load(false)` rather than `load`: a listener passes the event as
        // the first argument, and `load` reads its first argument as "this
        // is a poll following a reading already recorded". A `MouseEvent`
        // is truthy, so pressing Refresh marked itself as a poll and left
        // no trace in the audit journal -- while being the one press on
        // this page that is unmistakably somebody going to look.
        refreshButton.addEventListener('click', function () { load(false); });
    }

    if (searchForm) {
        searchForm.addEventListener('submit', function (event) {
            // The answer is fetched, not navigated to.
            event.preventDefault();
            loadFresh();
        });
    }

    if (clearButton) {
        clearButton.addEventListener('click', function () {
            termInputs.forEach(function (input) { input.value = ''; });
            loadFresh();
        });
    }

    // Delegated rather than bound per row, because the rows are replaced
    // on every poll: listeners bound to them would be thrown away and
    // rebuilt every few seconds, and an expanded line would collapse under
    // the reader on the next refresh either way -- which is why the toggle
    // is on the row's own next sibling rather than in remembered state.
    if (body) {
        body.addEventListener('click', function (event) {
            var row = event.target.closest('[data-journal-row]');
            if (!row) return;
            var raw = row.nextElementSibling;
            if (raw && raw.classList.contains('journal-expanded')) {
                raw.classList.toggle('hidden');
            }
        });
        body.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            var row = event.target.closest('[data-journal-row]');
            if (!row) return;
            // A row is focusable, so it has to answer the keyboard as well
            // as the pointer; space would otherwise scroll the page under
            // somebody who is trying to open a line.
            event.preventDefault();
            var raw = row.nextElementSibling;
            if (raw && raw.classList.contains('journal-expanded')) {
                raw.classList.toggle('hidden');
            }
        });
    }

    pressed(journalButtons, function (button) {
        return button.getAttribute('data-journal') === journal;
    });
    pressed(lineButtons, function (button) {
        return Number(button.getAttribute('data-journal-lines')) === lines;
    });
    pressed(everyButtons, function (button) {
        return Number(button.getAttribute('data-journal-every')) === every;
    });
    if (archivesButton) archivesButton.setAttribute('aria-pressed', String(archives));

    paintFreshness();
    // Every second, so "updated 40 s ago" is a reading rather than a
    // number frozen at whatever it was when the page last fetched.
    journalTrack(setInterval(paintFreshness, 1000));
    // The first read of the page, which is the one that gets recorded;
    // everything `repoll` starts after it says it is following.
    load(false);
    repoll();
}
