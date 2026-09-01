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
        var verdicts = (data && data.components) || {};
        render('db', verdicts.database);
        render('redis', verdicts.cache);
        render('celery', verdicts.task_queue);
        // The limiter fails open: with its backend gone it enforces
        // nothing and the service answers normally, so this row is the
        // only place the failure appears.
        render('limiter', verdicts.rate_limiter);
        renderLogging(data && data.logging);
    }

    // The verdict is read, not worked out. This page used to decide it
    // from the booleans the endpoint published -- the fourth place the
    // same three rules were spelled, after `/health`, the CLI and the
    // snapshot -- and it is the place they were spelled wrong: a queue
    // that does not exist was called "ok" until the rule for it was added
    // here too, and a cache keeping entries in the process reads "absent"
    // wherever the decision is made from `cache_configured` alone.
    //
    // `components` carries the snapshot's own vocabulary, and what is
    // left here is this page's words for it.
    var SAID = {
        ok: 'answering',
        unavailable: 'not_answering',
        timeout: 'timed_out',
        no_schema: 'no_schema',
        in_process: 'in_this_process',
        disabled: 'not_configured',
        inline: 'not_configured',
        enforcing: 'answering',
        not_enforcing: 'not_answering'
    };

    // Which verdicts are not a fault. A cache with no server and a queue
    // with no broker are deployments, not outages, and neither is a
    // cache keeping its entries in this process -- it works, it is just
    // not shared.
    var CALM = ['unknown', 'disabled', 'inline', 'in_process'];

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
        // Each key sits as a literal directly inside its own `t(...)`
        // for the reason below, so the branches stay written out even
        // though `SAID` names the same keys: the test that reads the
        // scripts against the catalogue takes these calls out of the
        // file, and a key it cannot see is a key it reports as unused.
        if (word) {
            var said = SAID[verdict];
            if (said === 'timed_out') {
                word.textContent = t('timed_out');
            } else if (said === 'not_configured') {
                word.textContent = t('not_configured');
            } else if (said === 'no_schema') {
                word.textContent = t('no_schema');
            } else if (said === 'in_this_process') {
                word.textContent = t('in_this_process');
            } else if (said === 'answering') {
                word.textContent = t('answering');
            } else if (said === 'not_answering') {
                word.textContent = t('not_answering');
            } else {
                word.textContent = t('unknown');
            }
        }
        if (!dot) return;
        // A cache that was never configured gets the neutral dot, not the
        // red one: nothing is wrong with it. A timeout gets the red one,
        // because the dependency is unusable either way -- the word beside
        // it is what says which kind of unusable.
        var calm = CALM.indexOf(verdict || 'unknown') !== -1;
        var well = verdict === 'ok' || verdict === 'enforcing';
        dot.className = 'dot' + (
            calm ? '' : (well ? ' dot--ok' : ' dot--danger')
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
            if (name) {
                // The name of the implementation was the whole report,
                // and it does not move when there is nowhere to move the
                // work to: with both audit implementations writing one
                // broken file, `active` read `structlog_audit`
                // throughout while the background round was calling it
                // unhealthy every check.
                name.textContent = chainState
                    ? t('chain_state', {
                        active: chainState.active,
                        finding: finding(chainState.last_check)
                    })
                    : t('unknown');
            }
            markChain(chain, chainState);

            ['dropped_calls', 'failed_checks', 'lost_log_lines']
                .forEach(function(counter) {
                    var cell = document.getElementById(chain + '-' + counter);
                    if (!cell) return;
                    cell.textContent = chainState ? chainState[counter] : '\u2014';
                });
        });

        renderJournals(logging);
    }

    // Each key sits as a literal inside its own `t(...)`, for the reason
    // written beside `render` above: the test that reads the scripts
    // against the catalogue takes these calls out of the file, and a key
    // it cannot see is a key it reports as unused.
    function finding(outcome) {
        if (outcome === 'healthy') return t('chain_healthy');
        if (outcome === 'unhealthy') return t('chain_unhealthy');
        // A probe that raises answers nothing, which is why no work is
        // moved on one -- a different finding from "answered no", and
        // told apart here the way `timed_out` is told apart above.
        if (outcome === 'probe failed') return t('chain_probe_failed');
        return t('chain_not_checked');
    }

    // Neutral until a round has found something: a chain nothing has
    // asked about is unexamined, and a green dot over it is the guess
    // this row exists to stop being made.
    function markChain(chain, chainState) {
        var dot = document.getElementById('dot-' + chain);
        if (!dot) return;

        var mark = '';
        if (chainState && chainState.last_check === 'healthy') {
            mark = ' dot--ok';
        } else if (
            chainState
            && (chainState.last_check === 'unhealthy'
                || chainState.last_check === 'probe failed')
        ) {
            mark = ' dot--danger';
        }
        dot.className = 'dot' + mark;
    }

    // The failure none of the counters above can report. A journal whose
    // file would not open has no handler at all, so nothing was dropped,
    // nothing was lost and no check failed -- every number reads zero
    // over a file being written by nobody.
    function renderJournals(logging) {
        // Asked by type and not for truth: `[]` is a truthy value in
        // this language and it is also the answer "every journal
        // opened", so a plain `logging.journals_unavailable ? ... :
        // null` cannot tell that answer from a body that carries no
        // such field at all. Only the second is unknown.
        var missing = logging && Array.isArray(logging.journals_unavailable)
            ? logging.journals_unavailable : null;

        var written = logging && Array.isArray(logging.journals_written)
            ? logging.journals_written : null;

        var cell = document.getElementById('logging-journals');
        if (cell) {
            if (!missing) {
                cell.textContent = t('unknown');
            } else if (missing.length) {
                // Each on its own, with the reason the operating system
                // gave: "the journal is broken" does not say whether to
                // fix a path, a mode or a disk.
                cell.textContent = missing.map(function(entry) {
                    return t('journal_unavailable', {
                        journal: entry.journal, reason: entry.reason
                    });
                }).join(' · ');
            } else if (written && written.length) {
                // Named rather than summarised: two journals of three is
                // also "nothing failed", and the row that says "all of
                // them" cannot be told from the row that means it.
                cell.textContent = written.join(' · ');
            } else {
                // No journals written and none refused -- a deployment
                // that writes no files, which `LOG_TO_FILE=false` makes
                // a configuration rather than a fault. The same word the
                // cache row uses for the same shape of answer.
                cell.textContent = t('not_configured');
            }
        }

        var dot = document.getElementById('dot-journals');
        if (!dot) return;
        // Spelled out rather than nested into one expression: the four
        // answers are unknown, refused, written and none configured, and
        // written as a chain of `?:` the "refused" case was reached only
        // when something else was being written -- a worker whose three
        // journals all failed to open drew the neutral dot.
        //
        // The neutral dot for a deployment that keeps no journals, the
        // way the cache row draws a cache nobody configured: nothing is
        // wrong with it, and a red dot there would train an operator to
        // ignore this row on the day it goes red for a reason.
        var mark = '';
        if (missing && missing.length) {
            mark = ' dot--danger';
        } else if (missing && written && written.length) {
            mark = ' dot--ok';
        }
        dot.className = 'dot' + mark;
    }
})();
