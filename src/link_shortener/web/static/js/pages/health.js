/**
 * health.js – Infrastructure health check page.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(async function() {
    try {
        var resp = await apiFetch('/api/v1/admin/health');
        if (!resp) return;
        if (!resp.ok) {
            // A health page that cannot reach the health endpoint used to
            // leave three dashes on screen, which reads as "unmeasured"
            // when the truthful answer is "the check itself failed".
            showLoadError('health-error', await apiErrorText(resp));
            paint(null);
            return;
        }
        paint(await resp.json());
    } catch(e) {
        showLoadError('health-error', t('unreachable'));
    }

    // Both paths through this page draw the same surfaces, so they are
    // listed once. Written as two branches, each naming five rows, a
    // sixth added to one and forgotten in the other left a stale value on
    // screen exactly when the page was reporting a failure. `null && x`
    // is `null`, which is the "unknown" value `render` already takes.
    function paint(data) {
        render('db', state(data, 'database', data && data.database));
        render('redis', state(data, 'cache', data && data.cache));
        render('celery', state(data, 'task_queue', data && data.task_queue));
        // The limiter fails open: with its backend gone it enforces
        // nothing and the service answers normally, so this row is the
        // only place the failure appears.
        render('limiter', state(data, 'rate_limiter', data && data.rate_limiter));
        renderLogging(data && data.logging);
    }

    // Four states, not two. A dependency that ran out of the check's
    // budget and one that answered no are both unusable, but only the
    // first says which dependency is hanging -- and a cache nobody
    // configured is not a broken cache at all. The endpoint reported one
    // boolean per row, so this page drew "Redis: answering" over a
    // deployment with no Redis, and "not answering" over a broker that
    // was merely slow. `/health` and `flask maintenance health` had told
    // all three apart from the same snapshot all along.
    function state(data, key, ok) {
        if (!data || ok === null || ok === undefined) return 'unknown';
        if ((data.timed_out || []).indexOf(key) !== -1) return 'timeout';
        if (key === 'cache' && data.cache_configured === false) {
            return 'absent';
        }
        return ok ? 'ok' : 'down';
    }

    // State is written as a class rather than as a colour in a style
    // attribute. A literal colour cannot follow the theme, and it said
    // nothing to anyone reading the page without seeing it; a dot is a
    // shape, and it survives being printed in grey.
    function render(name, verdict) {
        var word = document.getElementById('health-' + name);
        var dot = document.getElementById('dot-' + name);
        // Each key sits as a literal directly inside its own `t(...)`,
        // rather than the shorter `t(verdict)`. The test that checks the
        // scripts against the catalogue reads these calls out of the
        // file, and a key it cannot see is a key it reports as unused --
        // which would train the next reader to ignore it.
        if (word) {
            if (verdict === 'unknown') {
                word.textContent = t('unknown');
            } else if (verdict === 'timeout') {
                word.textContent = t('timed_out');
            } else if (verdict === 'absent') {
                word.textContent = t('not_configured');
            } else if (verdict === 'ok') {
                word.textContent = t('answering');
            } else {
                word.textContent = t('not_answering');
            }
        }
        if (!dot) return;
        // A cache that was never configured gets the neutral dot, not the
        // red one: nothing is wrong with it. A timeout gets the red one,
        // because the dependency is unusable either way -- the word beside
        // it is what says which kind of unusable.
        dot.className = 'dot' + (
            verdict === 'unknown' || verdict === 'absent'
                ? '' : (verdict === 'ok' ? ' dot--ok' : ' dot--danger')
        );
    }

    // The counters `FailoverService` keeps. They were published by the
    // endpoint and read by nobody, which is how an audit trail that had
    // stopped being written looked, from every surface an operator has,
    // exactly like one that was fine.
    //
    // `active` names the implementation actually doing the work -- the
    // primary, or the fallback it failed over to -- and until this page
    // read it, the only word about which one holds the work was a single
    // line at startup.
    function renderLogging(logging) {
        // Whose counters these are. They live in one worker process's
        // memory and a deployment runs several, so the same service in
        // the same state answers different numbers depending on which
        // worker took the request -- measured at 16, 27, 28 and 6 across
        // twelve requests after one broken journal. Unlabelled, the
        // number reads as the service's.
        var owner = document.getElementById('logging-worker');
        if (owner) {
            owner.textContent = logging
                ? t('logging_worker', {pid: logging.worker}) : '\u2014';
        }

        ['logger', 'audit'].forEach(function(chain) {
            // Not `state`: that name belongs to the function above, and
            // shadowing it here would leave the next reader looking at
            // two unrelated things spelled alike.
            var chainState = logging ? logging[chain] : null;
            var name = document.getElementById('logging-' + chain);
            if (name) name.textContent = chainState ? chainState.active : t('unknown');

            ['dropped_calls', 'failed_checks', 'lost_log_lines']
                .forEach(function(counter) {
                    var cell = document.getElementById(chain + '-' + counter);
                    if (!cell) return;
                    cell.textContent = chainState ? chainState[counter] : '\u2014';
                });
        });
    }
})();
