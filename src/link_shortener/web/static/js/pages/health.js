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
            render('db', null);
            render('redis', null);
            render('celery', null);
            render('limiter', null);
            renderLogging(null);
            return;
        }
        var data = await resp.json();
        render('db', data.database);
        render('redis', data.cache);
        render('celery', data.task_queue);
        // The limiter fails open: with its backend gone it enforces
        // nothing and the service answers normally, so this row is the
        // only place the failure appears.
        render('limiter', data.rate_limiter);
        renderLogging(data.logging);
    } catch(e) {
        showLoadError('health-error', t('unreachable'));
    }

    // State is written as a class rather than as a colour in a style
    // attribute. A literal colour cannot follow the theme, and it said
    // nothing to anyone reading the page without seeing it; a dot is a
    // shape, and it survives being printed in grey.
    function render(name, ok) {
        var word = document.getElementById('health-' + name);
        var dot = document.getElementById('dot-' + name);
        // Each key sits as a literal directly inside its own `t(...)`,
        // rather than the shorter `t(ok ? 'answering' : 'not_answering')`.
        // The test that checks the scripts against the catalogue reads
        // these calls out of the file, and a key it cannot see is a key it
        // reports as unused -- which would train the next reader to ignore
        // it.
        if (word) {
            if (ok === null) {
                word.textContent = t('unknown');
            } else {
                word.textContent = ok ? t('answering') : t('not_answering');
            }
        }
        if (!dot) return;
        dot.className = 'dot' + (ok === null ? '' : (ok ? ' dot--ok' : ' dot--danger'));
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
        ['logger', 'audit'].forEach(function(chain) {
            var state = logging ? logging[chain] : null;
            var name = document.getElementById('logging-' + chain);
            if (name) name.textContent = state ? state.active : t('unknown');

            ['dropped_calls', 'failed_checks', 'lost_log_lines']
                .forEach(function(counter) {
                    var cell = document.getElementById(chain + '-' + counter);
                    if (!cell) return;
                    cell.textContent = state ? state[counter] : '\u2014';
                });
        });
    }
})();
