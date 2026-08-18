/**
 * security_counts.js – How many security events, and when.
 *
 * Loaded from the head for the reason `journals.js` is: it owns a timer,
 * and a timer's owner has to run once per tab rather than once per Turbo
 * navigation. The mounting lives in `pages/security_counts.js`.
 *
 * The chart is drawn with the primitives in `charts.js` -- the frame, the
 * axis, the tooltip. A second set beside them would be two ways for one
 * screen to draw an axis, and they would drift.
 */

var countsTimers = [];

function countsStopPolling() {
    countsTimers.forEach(function (id) { clearInterval(id); });
    countsTimers = [];
}

document.addEventListener('turbo:before-cache', countsStopPolling);

// Which series are drawn, in this order, and everything else is summed
// into one. Fourteen event types would be fourteen colours nobody can tell
// apart; these three are the ones an operator watches -- did people get
// in, were they refused, and did anything change about who may do what.
// The label is a function rather than a key, and that is not style: the
// catalogue and the scripts are checked against each other by reading the
// `t('...')` calls, so a key held in a variable is a key that check cannot
// see -- it reads as a sentence shipped to every page that nothing asks
// for, which is exactly what it said when this was written the other way.
var COUNTS_SERIES = [
    {
        key: 'LOGIN_SUCCEEDED',
        colour: 'var(--c-humans)',
        label: function () { return t('counts_signed_in'); }
    },
    {
        key: 'LOGIN_FAILED',
        colour: 'var(--c-danger)',
        label: function () { return t('counts_refused'); }
    },
    {
        key: 'ROLES_CHANGED',
        colour: 'var(--c-bots)',
        label: function () { return t('counts_roles'); }
    }
];

function countsRest(totals) {
    var named = COUNTS_SERIES.map(function (series) { return series.key; });
    return Object.keys(totals).reduce(function (sum, key) {
        return named.indexOf(key) === -1 ? sum + totals[key] : sum;
    }, 0);
}

// Stacked rather than side by side: the question the chart answers first
// is "how much happened at all", and three thin bars per interval at 90
// intervals are three things nobody can compare anyway.
function drawSecurityColumns(host, answer) {
    var buckets = answer.buckets;
    var series = COUNTS_SERIES.filter(function (one) {
        return answer.series[one.key];
    });

    var start = new Date(answer.since).getTime();
    var step = (new Date(answer.until).getTime() - start) / Math.max(1, buckets);

    var stacked = [];
    for (var i = 0; i < buckets; i++) {
        // `at` rather than the index alone: `chartAxis` takes the buckets
        // themselves and reads the moment off each one, the way the visit
        // charts hand them over. Passed a count instead, its loop reads
        // `undefined.length` and writes no labels at all -- which is an
        // axis with nothing on it and a chart that still looks drawn.
        var column = { total: 0, parts: [], at: new Date(start + step * i).toISOString() };
        series.forEach(function (one) {
            var value = answer.series[one.key][i] || 0;
            column.total += value;
            column.parts.push({
                value: value, colour: one.colour, label: one.label
            });
        });
        stacked.push(column);
    }

    var top = stacked.reduce(function (most, column) {
        return Math.max(most, column.total);
    }, 0);

    var frame = chartFrame(host, {
        max: top, size: CHART_WIDE, label: t('counts_chart_label')
    });
    var svg = frame.svg;
    var plot = frame.plot;
    var tip = chartTooltip(host, plot);
    var band = plot.w / Math.max(1, buckets);
    var width = Math.min(24, band - 3);
    // Hours on a day-long span, dates on the longer ones: "18.08.2026"
    // repeated twenty-four times is an axis that says nothing.
    var label = answer.period === '24h' ? formatTime : formatDate;

    stacked.forEach(function (column, index) {
        var x = plot.x0 + band * index + (band - width) / 2;
        var bottom = plot.y1;

        column.parts.forEach(function (part) {
            if (part.value <= 0) return;
            var height = plot.y1 - plot.y(part.value);
            var y = bottom - height;
            svg.appendChild(svgNode('rect', {
                x: x, y: y, width: width, height: Math.max(1, height),
                fill: part.colour
            }));
            bottom = y;
        });

        // The pointer is tested against the whole band rather than the
        // marks: an interval with nothing in it has no mark at all, and it
        // still has a value worth reading.
        var hit = svgNode('rect', {
            class: 'chart-hit',
            x: plot.x0 + band * index, y: plot.y0, width: band, height: plot.h
        });
        hit.addEventListener('mouseenter', function () {
            tip.show(
                column.parts.map(function (part) {
                    return { key: part.label(), value: part.value };
                }),
                label(column.at),
                plot.x0 + band * (index + 0.5),
                plot.y(column.total) - 8
            );
        });
        hit.addEventListener('mouseleave', tip.hide);
        svg.appendChild(hit);
    });

    chartAxis(svg, plot, stacked, Math.max(1, Math.round(buckets / 6)), label);
}

function mountSecurityCounts(root) {
    if (!root) return;

    var tiles = root.querySelector('[data-counts-tiles]');
    var chart = root.querySelector('[data-counts-chart]');
    var note = root.querySelector('[data-counts-note]');
    var buttons = Array.prototype.slice.call(
        root.querySelectorAll('[data-counts-period]')
    );

    var period = '7d';

    // `aria-pressed`, which is what this page's other button rows use and
    // what the stylesheet draws: a class of its own would be a second way
    // to say "this one is chosen", visible to the eye and not to a screen
    // reader.
    function paintButtons() {
        buttons.forEach(function (button) {
            button.setAttribute(
                'aria-pressed',
                String(button.getAttribute('data-counts-period') === period)
            );
        });
    }

    function tile(label, value, colour) {
        return '<div class="counts-tile">'
            + '<span class="counts-tile-dot" style="background:' + colour + '"></span>'
            + '<span class="counts-tile-value">' + escapeHtml(formatNumber(value)) + '</span>'
            + '<span class="counts-tile-label">' + escapeHtml(label) + '</span>'
            + '</div>';
    }

    function paint(answer) {
        var totals = answer.totals || {};
        var drawn = COUNTS_SERIES.map(function (one) {
            return tile(one.label(), totals[one.key] || 0, one.colour);
        });
        drawn.push(tile(t('counts_other'), countsRest(totals), 'var(--c-text-3)'));
        if (tiles) tiles.innerHTML = drawn.join('');

        if (chart) drawSecurityColumns(chart, answer);

        // What the figures are of, said in words: a chart with no span on
        // it is a chart that means whatever the reader last remembers
        // choosing.
        if (note) {
            note.textContent = t('counts_span', {
                since: formatDate(answer.since),
                until: formatDate(answer.until)
            });
        }
    }

    async function load() {
        try {
            var query = new URLSearchParams({ period: period });
            var resp = await apiFetch(
                '/api/v1/journals/counters' + '?' + query.toString()
            );
            if (!resp) return;
            if (!resp.ok) {
                showLoadError('counts-error', await apiErrorText(resp), null, 1);
                return;
            }
            paint(await resp.json());
        } catch (e) {
            showLoadError('counts-error', t('counts_failed'), null, 1);
        }
    }

    buttons.forEach(function (button) {
        button.addEventListener('click', function () {
            period = button.getAttribute('data-counts-period');
            paintButtons();
            load();
        });
    });

    paintButtons();
    load();
    // Slower than the journal's own poll, and deliberately: these are
    // aggregates over days, and a figure covering ninety of them does not
    // change in five seconds.
    countsTimers.push(setInterval(load, 60000));
}
