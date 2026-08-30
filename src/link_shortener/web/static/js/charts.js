/**
 * charts.js – Recorded visits, drawn as SVG.
 */
// Loaded from `<head>` with `defer`, beside `main.js` and `dashboard.js`,
// and for the same reason they are: Turbo merges the head across
// navigations and leaves a script it already has alone, so this file runs
// exactly once per tab. That matters here more than anywhere else in the
// project, because this file owns a timer. Re-executed on every navigation
// it would register a second `turbo:before-cache` listener each time, and
// the very thing the listener exists to prevent -- a page being polled by
// the timers of every page visited before it -- would be caused by the
// cure.
//
// No library. The whole drawing surface is `document.createElementNS`, and
// the shapes below are the four a page of visit statistics needs: a
// stacked column, a ring, a row of bars, and the frame that says "nothing
// happened here" without going blank.

var SVG_NS = 'http://www.w3.org/2000/svg';

// The system of coordinates a chart is drawn in. Not pixels: the SVG is
// scaled to whatever the panel is wide, so these numbers only decide the
// *proportions* and the size of the text relative to the plot -- the same
// 11px label stretched across a 720-wide viewBox in a half-width panel
// renders at about 7px, which is how a chart ends up with axis text
// nobody can read.
//
// One frame, because every panel that draws a chart here is a full-width
// card. A second, narrower one stood beside this and was named in exactly
// one place: the branch where the daily chart failed to load. So that
// chart was 720 wide when it drew, 720 wide when it had nothing to draw,
// and 400 wide when the request behind it went wrong -- three sizes for
// one panel, and the odd one out only ever appeared when something was
// already broken.
var CHART_WIDE = { w: 720, h: 240 };
var CHART_PAD = { top: 12, right: 8, bottom: 26, left: 40 };

// Three hues and a tail, and the count is measured rather than chosen --
// the reasoning, and the numbers behind it, are in `main.css` where the
// values live. Colour belongs to the category, so the same row keeps its
// colour when the shape is switched between the ring and the bars.
var CHART_CATEGORY_COLORS = ['var(--c-cat-1)', 'var(--c-cat-2)', 'var(--c-cat-3)'];
var CHART_TAIL_COLOR = 'var(--c-cat-other)';

// The 2px of surface that parts one mark from the next, in the units of
// the frame above. A gap rather than a stroke: a stroke is ink that is not
// data, and around a two-pixel segment it weighs more than the segment.
var CHART_GAP = 2;


/* ------------------------------------------------------------------ */
/* The frame                                                           */
/* ------------------------------------------------------------------ */

function svgNode(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    for (var key in attrs) {
        if (attrs[key] !== undefined && attrs[key] !== null) {
            node.setAttribute(key, attrs[key]);
        }
    }
    return node;
}

// Where the axis ends and how far apart its lines stand.
//
// By step, not by dividing the top by four: visits are whole things, and
// "50 across four lines" prints 12.5 visits on the axis. The step comes
// from 1, 2 or 5 on a decimal rung, and as many lines as fit in five.
//
// A span with nothing in it still gets an axis of 0..4 rather than 0..0 --
// a plot whose top is zero divides by zero, and every mark in it lands on
// the baseline.
function chartScale(value) {
    if (!value || value <= 0) return { max: 4, step: 1 };
    var rung = Math.pow(10, Math.floor(Math.log10(value)));
    var steps = [rung / 10, rung / 5, rung / 2, rung, rung * 2, rung * 5, rung * 10];
    for (var i = 0; i < steps.length; i++) {
        var step = steps[i];
        if (step < 1) continue;
        if (Math.ceil(value / step) <= 5) {
            return { max: Math.ceil(value / step) * step, step: step };
        }
    }
    return { max: Math.ceil(value), step: Math.ceil(value / 4) };
}

// Empties the host, puts an SVG in it, draws the grid, and hands back the
// plot: the rectangle the marks go in and the function that turns a value
// into a vertical position.
function chartFrame(host, options) {
    host.textContent = '';
    host.classList.remove('chart-figure--failed');

    var size = options.size || CHART_WIDE;
    var svg = svgNode('svg', {
        viewBox: '0 0 ' + size.w + ' ' + size.h,
        role: 'img',
        'aria-label': options.label || ''
    });
    host.appendChild(svg);

    var plot = {
        x0: CHART_PAD.left,
        x1: size.w - CHART_PAD.right,
        y0: CHART_PAD.top,
        y1: size.h - CHART_PAD.bottom,
        width: size.w,
        height: size.h
    };
    plot.w = plot.x1 - plot.x0;
    plot.h = plot.y1 - plot.y0;

    var scale = chartScale(options.max);
    plot.y = function (value) {
        return plot.y1 - (value / scale.max) * plot.h;
    };

    // Hairline, solid, one step off the surface: the grid is there to be
    // measured against, not looked at.
    for (var value = 0; value <= scale.max + 0.001; value += scale.step) {
        var y = plot.y(value);
        svg.appendChild(svgNode('line', {
            class: 'chart-grid', x1: plot.x0, x2: plot.x1, y1: y, y2: y
        }));
        var tick = svgNode('text', {
            class: 'chart-axis chart-axis--num',
            x: plot.x0 - 8, y: y + 4, 'text-anchor': 'end'
        });
        tick.textContent = formatNumber(value);
        svg.appendChild(tick);
    }

    return { svg: svg, plot: plot };
}

// One label per `every` buckets along the bottom. Every date on the axis
// would collide with its neighbours at 28 buckets and be unreadable at 90.
function chartAxis(svg, plot, buckets, every, format) {
    var band = plot.w / buckets.length;
    for (var i = 0; i < buckets.length; i += every) {
        var label = svgNode('text', {
            class: 'chart-axis',
            x: plot.x0 + band * (i + 0.5),
            y: plot.y1 + 16,
            'text-anchor': 'middle'
        });
        label.textContent = format(buckets[i].at);
        svg.appendChild(label);
    }
}

// A column with a rounded cap and a square foot. The radius is clamped to
// the mark: a one-visit column is three pixels tall, and a 4px radius on
// it draws a lens rather than a bar.
function chartColumnPath(x, y, width, height, radius) {
    if (height <= 0) return '';
    var r = Math.min(radius, width / 2, height);
    return 'M' + x + ',' + (y + height)
        + 'L' + x + ',' + (y + r)
        + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y
        + 'L' + (x + width - r) + ',' + y
        + 'Q' + (x + width) + ',' + y + ' ' + (x + width) + ',' + (y + r)
        + 'L' + (x + width) + ',' + (y + height) + 'Z';
}


/* ------------------------------------------------------------------ */
/* The tooltip                                                         */
/* ------------------------------------------------------------------ */

// An HTML element rather than SVG text: it has to sit above the chart,
// wrap nothing, and carry the panel's own border and background.
//
// Positioned in percentages of the frame, because the frame is scaled to
// the panel and a position in frame units would be wrong at every width
// but one.
function chartTooltip(host, plot) {
    var tip = document.createElement('div');
    tip.className = 'chart-tip';
    host.appendChild(tip);
    return {
        show: function (rows, heading, x, y) {
            tip.textContent = '';
            var head = document.createElement('div');
            head.className = 'chart-tip-head';
            head.textContent = heading;
            tip.appendChild(head);
            rows.forEach(function (row) {
                var line = document.createElement('div');
                line.className = 'chart-tip-row';
                var key = document.createElement('span');
                key.className = 'chart-tip-key';
                key.textContent = row.key;
                var value = document.createElement('span');
                value.className = 'chart-tip-val';
                value.textContent = formatNumber(row.value);
                line.appendChild(key);
                line.appendChild(value);
                tip.appendChild(line);
            });
            tip.style.left = (x / plot.width * 100) + '%';
            tip.style.top = (y / plot.height * 100) + '%';
            tip.classList.add('active');
        },
        hide: function () { tip.classList.remove('active'); }
    };
}


/* ------------------------------------------------------------------ */
/* Visits over time                                                    */
/* ------------------------------------------------------------------ */

// Columns, with the robots' share stacked on top of the people's.
//
// Columns rather than a line, and this is the case that decided it: a span
// with one busy day in it draws one column, which is the truth, where a
// line draws a single point -- a dot of two pixels that reads as an empty
// chart. The stack rather than a second line or a toggle: "how many" and
// "how many of those were robots" are one question about one column, and
// the reader should not have to press anything to see the second half of
// the answer.
function drawVisitColumns(host, buckets, options) {
    options = options || {};
    var top = buckets.reduce(function (most, bucket) {
        return Math.max(most, bucket.total);
    }, 0);

    var frame = chartFrame(host, {
        max: top, size: options.size, label: options.label
    });
    var svg = frame.svg;
    var plot = frame.plot;
    var tip = chartTooltip(host, plot);
    var band = plot.w / buckets.length;
    var width = Math.min(24, band - 3);
    var format = options.format || formatDate;

    buckets.forEach(function (bucket, index) {
        var x = plot.x0 + band * index + (band - width) / 2;
        var humans = bucket.total - bucket.bots;
        var yTotal = plot.y(bucket.total);
        var yHumans = plot.y(humans);
        var botsHeight = yHumans - yTotal;

        if (botsHeight > 0.5) {
            svg.appendChild(svgNode('path', {
                d: chartColumnPath(x, yTotal, width, Math.max(0, botsHeight - CHART_GAP), 4),
                fill: 'var(--c-bots)'
            }));
            svg.appendChild(svgNode('rect', {
                x: x, y: yHumans, width: width, height: plot.y1 - yHumans,
                fill: 'var(--c-humans)'
            }));
        } else if (bucket.total > 0) {
            svg.appendChild(svgNode('path', {
                d: chartColumnPath(x, yHumans, width, plot.y1 - yHumans, 4),
                fill: 'var(--c-humans)'
            }));
        }

        // The pointer is tested against the whole band, not the mark: an
        // empty bucket has no mark at all, and it still has a value worth
        // reading.
        var hit = svgNode('rect', {
            class: 'chart-hit',
            x: plot.x0 + band * index, y: plot.y0, width: band, height: plot.h
        });
        hit.addEventListener('mouseenter', function () {
            tip.show([
                { key: t('chart_total'), value: bucket.total },
                { key: t('chart_humans'), value: humans },
                { key: t('chart_bots'), value: bucket.bots }
            ], format(bucket.at), plot.x0 + band * (index + 0.5), plot.y(bucket.total) - 8);
        });
        hit.addEventListener('mouseleave', tip.hide);
        svg.appendChild(hit);
    });

    chartAxis(svg, plot, buckets, options.tickEvery || 4, format);
}

// What an empty span and a failed request look like. Neither is a blank
// rectangle: the frame stays, so the panel still reads as a chart, and the
// sentence in the middle says which of the two happened.
function drawChartMessage(host, kind, options) {
    options = options || {};
    var frame = chartFrame(host, { max: 0, size: options.size, label: options.label });
    var svg = frame.svg;
    var plot = frame.plot;

    if (kind === 'failed') host.classList.add('chart-figure--failed');

    var middle = (plot.x0 + plot.x1) / 2;
    var line = svgNode('text', {
        class: 'chart-empty-text', x: middle, y: plot.y0 + plot.h / 2 - 4,
        'text-anchor': 'middle'
    });
    line.textContent = kind === 'failed' ? t('chart_failed') : t('chart_no_visits');
    svg.appendChild(line);

    if (kind !== 'failed') {
        var hint = svgNode('text', {
            class: 'chart-empty-hint', x: middle, y: plot.y0 + plot.h / 2 + 14,
            'text-anchor': 'middle'
        });
        hint.textContent = t('chart_no_visits_hint');
        svg.appendChild(hint);
    }
}


/* ------------------------------------------------------------------ */
/* Shares: the ring and the bars                                       */
/* ------------------------------------------------------------------ */

function chartCategoryColor(index, isTail) {
    if (isTail || index >= CHART_CATEGORY_COLORS.length) return CHART_TAIL_COLOR;
    return CHART_CATEGORY_COLORS[index];
}

// The ring needs a short list -- three colours and a tail. The bars do
// not: every row there carries its own label, so the tail stays split into
// the rows it is made of, and switching the shape shows more rather than
// something else.
function chartFoldTail(rows) {
    if (CHART_CATEGORY_COLORS.length + 1 >= rows.length) return rows.slice();
    var head = rows.slice(0, CHART_CATEGORY_COLORS.length);
    var rest = rows.slice(CHART_CATEGORY_COLORS.length).reduce(function (sum, row) {
        return sum + row.total;
    }, 0);
    return head.concat([{ label: t('chart_other'), total: rest, isTail: true }]);
}

// Rows with a label, a track and a value.
//
// Built as elements, not as a string of markup: `label` is whatever the
// data carries -- a browser family, a device class -- and `textContent`
// cannot be talked into becoming a tag, which a concatenated string can.
function drawShareBars(host, rows) {
    host.textContent = '';
    var grid = document.createElement('div');
    grid.className = 'chart-bars';
    var most = rows.reduce(function (top, row) { return Math.max(top, row.total); }, 0);

    rows.forEach(function (row, index) {
        var label = document.createElement('div');
        label.className = 'chart-bars-label';
        label.textContent = row.label;

        var track = document.createElement('div');
        track.className = 'chart-bars-track';
        var fill = document.createElement('div');
        fill.className = 'chart-bars-fill';
        // A floor of 2%, so a category with one visit is a mark rather
        // than nothing at all.
        fill.style.width = (most ? Math.max(2, row.total / most * 100) : 0) + '%';
        fill.style.background = chartCategoryColor(index, row.isTail);
        track.appendChild(fill);

        var value = document.createElement('div');
        value.className = 'chart-bars-val';
        value.textContent = formatNumber(row.total);

        grid.appendChild(label);
        grid.appendChild(track);
        grid.appendChild(value);
    });

    host.appendChild(grid);
}

function chartRingSlice(cx, radius, thickness, from, to) {
    var inner = radius - thickness;
    var large = (to - from) > Math.PI ? 1 : 0;
    return 'M' + (cx + radius * Math.cos(from)) + ',' + (cx + radius * Math.sin(from))
        + 'A' + radius + ',' + radius + ' 0 ' + large + ' 1 '
        + (cx + radius * Math.cos(to)) + ',' + (cx + radius * Math.sin(to))
        + 'L' + (cx + inner * Math.cos(to)) + ',' + (cx + inner * Math.sin(to))
        + 'A' + inner + ',' + inner + ' 0 ' + large + ' 0 '
        + (cx + inner * Math.cos(from)) + ',' + (cx + inner * Math.sin(from))
        + 'Z';
}

// The ring, with its rows beside it. The rows are the legend: a ring
// without one asks the reader to match colours from memory.
function drawShareRing(host, rows) {
    host.textContent = '';
    var shown = chartFoldTail(rows);
    var sum = shown.reduce(function (total, row) { return total + row.total; }, 0);

    var wrap = document.createElement('div');
    wrap.className = 'chart-ring';
    var figure = document.createElement('div');
    var list = document.createElement('div');
    list.className = 'chart-ring-rows';
    wrap.appendChild(figure);
    wrap.appendChild(list);

    var size = 148;
    var centre = size / 2;
    var radius = 58;
    var svg = svgNode('svg', { viewBox: '0 0 ' + size + ' ' + size, role: 'img' });
    var angle = -Math.PI / 2;

    shown.forEach(function (row, index) {
        var share = sum ? row.total / sum : 0;
        var color = chartCategoryColor(index, row.isTail);
        // The same 2px of surface that parts the halves of a column,
        // expressed as the angle that spans it at this radius.
        var gap = CHART_GAP / radius;
        var from = angle + gap / 2;
        var to = angle + share * Math.PI * 2 - gap / 2;
        angle += share * Math.PI * 2;
        if (to > from) {
            svg.appendChild(svgNode('path', {
                d: chartRingSlice(centre, radius, 20, from, to), fill: color
            }));
        }

        var swatch = document.createElement('span');
        swatch.className = 'chart-swatch';
        swatch.style.background = color;
        var name = document.createElement('span');
        name.className = 'chart-ring-name';
        name.textContent = row.label;
        var value = document.createElement('span');
        value.className = 'chart-ring-val';
        value.textContent = formatNumber(row.total) + ' · ' + Math.round(share * 100) + '%';
        list.appendChild(swatch);
        list.appendChild(name);
        list.appendChild(value);
    });

    var total = svgNode('text', {
        class: 'chart-ring-total', x: centre, y: centre + 2, 'text-anchor': 'middle'
    });
    total.textContent = formatNumber(sum);
    svg.appendChild(total);

    figure.appendChild(svg);
    host.appendChild(wrap);
}


/* ------------------------------------------------------------------ */
/* Polling                                                             */
/* ------------------------------------------------------------------ */

// Every timer this file has started, so that all of them can be stopped
// at once when the page goes away.
//
// A page script is executed again on every Turbo navigation, and a timer
// it started is not stopped by the body being swapped: two navigations
// leave two timers polling, ten leave ten, and each one is still asking
// for the statistics of a page that is no longer on screen. `setInterval`
// outliving its page is the single most expensive mistake available here,
// which is why the timer is owned by this file rather than by the pages.
// Two of them, and they are not interchangeable. `chartTimers` is
// everything that has to stop when the page goes away; `chartPollTimer` is
// the one the interval buttons replace. Held apart on purpose: with a
// single list, changing the interval cleared the list -- and the clock
// that counts "updated 40 s ago" was in it, so choosing an interval
// stopped the freshness note. Found before it shipped, and the shape below
// is what stops it coming back.
var chartTimers = [];
var chartPollTimer = null;

function chartStopPolling() {
    chartTimers.forEach(function (id) { clearInterval(id); });
    chartTimers = [];
    chartPollTimer = null;
}

function chartTrack(id) {
    chartTimers.push(id);
    return id;
}

function chartStartPolling(seconds, work) {
    if (chartPollTimer !== null) {
        clearInterval(chartPollTimer);
        chartTimers = chartTimers.filter(function (id) { return id !== chartPollTimer; });
        chartPollTimer = null;
    }
    if (!seconds) return;
    chartPollTimer = chartTrack(setInterval(work, seconds * 1000));
}

// Turbo caches the page before it leaves it; this is the moment the page
// is still whole and is known to be going. Bound to `document`, once,
// because this file runs once per tab -- see the note at the top.
document.addEventListener('turbo:before-cache', chartStopPolling);


/* ------------------------------------------------------------------ */
/* Preferences                                                         */
/* ------------------------------------------------------------------ */

// The span, the interval and the shape are settings of a reader, not of a
// page: kept in `localStorage` so that walking to another page and back
// does not reset them. Wrapped, because storage throws rather than
// returning null in a browser that has it switched off, and a chart that
// cannot be drawn because a preference could not be read would be a poor
// trade.
function chartRemember(name, value) {
    try {
        if (value === undefined) return localStorage.getItem('maizlink.chart.' + name);
        localStorage.setItem('maizlink.chart.' + name, value);
    } catch (e) {
        return null;
    }
    return value;
}


/* ------------------------------------------------------------------ */
/* The page                                                            */
/* ------------------------------------------------------------------ */

// How the spans are cut, and how their axis is labelled. The bucket counts
// are the service's, not ours -- `/api/v1/stats/visits` returns 24, 28, 30
// and 90 of them -- and the numbers here only decide how often a label is
// printed under them.
// The intervals the controls offer, in seconds, with 0 for "not at all".
// Here as well as in the template because a value arriving from storage is
// not to be trusted: a stale or hand-edited preference would otherwise set
// an interval no button can undo.
var CHART_INTERVALS = [0, 5, 10, 30, 60, 300];

var CHART_PERIODS = {
    '24h': { tickEvery: 4, format: formatTime },
    '7d': { tickEvery: 4, format: formatDate },
    '30d': { tickEvery: 5, format: formatDate },
    '90d': { tickEvery: 15, format: formatDate }
};

// The query half of a request. The first page in this project to send
// parameters at all, so it is built rather than pasted: `URLSearchParams`
// escapes the values, and a scope or a span arriving from storage is a
// value like any other.
function chartQuery(params) {
    var carried = {};
    for (var key in params) {
        // A null is a parameter that does not apply to this page, and
        // `URLSearchParams` would send it as the four letters "null".
        if (params[key] !== null && params[key] !== undefined) carried[key] = params[key];
    }
    return '?' + new URLSearchParams(carried).toString();
}

function chartPressed(buttons, chosen) {
    buttons.forEach(function (button) {
        button.setAttribute('aria-pressed', String(button === chosen));
    });
}

// Everything a statistics page does, given the block it was drawn into.
// Both pages call this with nothing but a scope; the markup is one
// template, so the two cannot drift apart.
function mountVisitCharts(root) {
    if (!root) return;

    var scope = root.getAttribute('data-visit-scope') || 'service';
    // Present only on the page about a single link. Left out of the query
    // entirely when absent rather than sent empty: `code=` is a code of
    // zero characters, which the service is right to refuse.
    var code = root.getAttribute('data-visit-code') || null;
    var columns = root.querySelector('[data-visit-columns]');
    var daily = root.querySelector('[data-visit-daily]');
    var errorBox = root.querySelector('[data-visit-error]');
    var freshness = root.querySelector('[data-visit-fresh-text]');
    var freshDot = root.querySelector('[data-visit-fresh-dot]');
    var periodButtons = Array.prototype.slice.call(root.querySelectorAll('[data-visit-period]'));
    var everyButtons = Array.prototype.slice.call(root.querySelectorAll('[data-visit-every]'));
    var refreshButton = root.querySelector('[data-visit-refresh]');

    var period = chartRemember('period') || '7d';
    if (!CHART_PERIODS[period]) period = '7d';
    // Read before it is converted, because `Number(null)` is 0 and 0 is a
    // legal interval here -- it is the off switch. A first visit therefore
    // opened with polling already off, looking exactly like a deliberate
    // choice nobody had made. Found by opening the page and reading the
    // note beside the charts, which is the only place it showed.
    var storedEvery = chartRemember('every');
    var every = (storedEvery === null || storedEvery === '') ? 10 : Number(storedEvery);
    if (isNaN(every) || CHART_INTERVALS.indexOf(every) === -1) every = 10;
    var loadedAt = null;

    function everyWords() {
        var chosen = everyButtons.filter(function (button) {
            return Number(button.getAttribute('data-visit-every')) === every;
        })[0];
        // The interval is spelled by the button the reader pressed, so
        // "every 5 min" and the control that set it cannot disagree, and
        // the words themselves stay in the template where `gettext` can
        // reach them.
        return chosen ? chosen.textContent.trim() : '';
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
        if (!errorBox) return;
        errorBox.textContent = '';
        errorBox.classList.add('hidden');
    }

    // One shape per breakdown, remembered per breakdown: a reader who
    // wants devices as bars and browsers as a ring gets both.
    function mountShare(name) {
        var host = root.querySelector('[data-visit-share=' + name + ']');
        var toggle = root.querySelector('[data-visit-shape=' + name + ']');
        if (!host) return null;
        var shape = chartRemember('shape.' + name) === 'bars' ? 'bars' : 'ring';
        var rows = [];

        function paint() {
            if (!rows.length) {
                host.textContent = '';
                var empty = document.createElement('p');
                empty.className = 'text-muted';
                empty.textContent = t('chart_no_visits');
                host.appendChild(empty);
            } else if (shape === 'bars') {
                drawShareBars(host, rows);
            } else {
                drawShareRing(host, rows);
            }
            if (toggle) {
                // Named for where it goes, not for what is on screen: a
                // button that says "Ring" while a ring is showing reads as
                // a label, and a reader has no way to tell which.
                toggle.textContent = shape === 'bars' ? t('chart_show_ring') : t('chart_show_bars');
            }
        }

        if (toggle) {
            toggle.addEventListener('click', function () {
                shape = shape === 'bars' ? 'ring' : 'bars';
                chartRemember('shape.' + name, shape);
                paint();
            });
        }

        return function (data) {
            rows = data || [];
            paint();
        };
    }

    var paintDevices = mountShare('devices');
    var paintBrowsers = mountShare('browsers');

    async function load() {
        var settings = CHART_PERIODS[period];
        try {
            var resp = await apiFetch('/api/v1/stats/visits'
                + chartQuery({ scope: scope, period: period, code: code }));
            if (!resp) return;
            if (!resp.ok) {
                showError(await apiErrorText(resp));
                drawChartMessage(columns, 'failed', {});
                return;
            }
            clearError();
            var data = await resp.json();
            if (data.total > 0) {
                drawVisitColumns(columns, data.buckets, {
                    tickEvery: settings.tickEvery, format: settings.format
                });
            } else {
                // Zero visits is not zero data: the reader asked a
                // question and the answer is "none", which the frame says
                // and an empty panel does not.
                drawChartMessage(columns, 'empty', {});
            }
            if (paintDevices) paintDevices(data.devices);
            if (paintBrowsers) paintBrowsers(data.browsers);
            loadedAt = Date.now();
            paintFreshness();
        } catch (e) {
            showError(t('unreachable'));
            drawChartMessage(columns, 'failed', {});
        }
    }

    // The daily chart answers from the roll-up, which changes once a day.
    // Polling it every five seconds would be five hundred queries an hour
    // against a table that gained one row, so it is loaded with the page
    // and on an explicit refresh, and left alone by the timer.
    async function loadDaily() {
        if (!daily) return;
        try {
            var resp = await apiFetch('/api/v1/stats/visits/daily'
                + chartQuery({ scope: scope, days: 90, code: code }));
            if (!resp) return;
            if (!resp.ok) {
                drawChartMessage(daily, 'failed', {});
                return;
            }
            var data = await resp.json();
            var busy = data.days.some(function (day) { return day.total > 0; });
            if (busy) {
                drawVisitColumns(daily, data.days, { tickEvery: 15, format: formatDate });
            } else {
                drawChartMessage(daily, 'empty', {});
            }
        } catch (e) {
            drawChartMessage(daily, 'failed', {});
        }
    }

    periodButtons.forEach(function (button) {
        if (button.getAttribute('data-visit-period') === period) chartPressed(periodButtons, button);
        button.addEventListener('click', function () {
            period = button.getAttribute('data-visit-period');
            chartRemember('period', period);
            chartPressed(periodButtons, button);
            load();
        });
    });

    everyButtons.forEach(function (button) {
        if (Number(button.getAttribute('data-visit-every')) === every) chartPressed(everyButtons, button);
        button.addEventListener('click', function () {
            every = Number(button.getAttribute('data-visit-every'));
            chartRemember('every', every);
            chartPressed(everyButtons, button);
            chartStartPolling(every, load);
            paintFreshness();
        });
    });

    if (refreshButton) {
        refreshButton.addEventListener('click', function () {
            load();
            loadDaily();
        });
    }

    // The clock beside the charts ticks whether or not anything is being
    // fetched: "updated 40 s ago" is the reading that matters when polling
    // is off, and it is the one a stopped clock gets wrong.
    chartTrack(setInterval(paintFreshness, 1000));

    paintFreshness();
    load();
    loadDaily();
    chartStartPolling(every, load);
}

window.mountVisitCharts = mountVisitCharts;
window.drawVisitColumns = drawVisitColumns;
window.drawShareRing = drawShareRing;
window.drawShareBars = drawShareBars;
window.drawChartMessage = drawChartMessage;
