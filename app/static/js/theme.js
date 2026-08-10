/* ══════════════════════════════════════════════════════════════
   ROBOTICS CONTROL PANEL  —  theme.js
   Animations & interactive effects for MerchOps Agent UI
══════════════════════════════════════════════════════════════ */

(function () {
    'use strict';

    /* ── Theme persistence ──────────────────────────────── */
    const THEME_KEY = 'theme';
    const html = document.documentElement;

   function initTheme() {
    try {
        const saved = localStorage.getItem(THEME_KEY) || 'dark';
        html.setAttribute('data-theme', saved);
    } catch (e) {
        html.setAttribute('data-theme', 'dark');
    }
}

    function bindThemeToggle() {
        const btn = document.getElementById('themeToggle');
        if (!btn) return;
        btn.addEventListener('click', function () {
            const current = html.getAttribute('data-theme') || 'dark';
            const next = current === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', next);
            try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
        });
    }

    /* ── Animate KPI/stat counters ──────────────────────── */
    function animateCounters() {
        document.querySelectorAll('[data-count]').forEach(function (el) {
            const target = parseInt(el.getAttribute('data-count'), 10);
            if (isNaN(target)) return;
            const duration = 800;
            const start = performance.now();
            function step(now) {
                const elapsed = now - start;
                const progress = Math.min(elapsed / duration, 1);
                const ease = 1 - Math.pow(1 - progress, 3);
                el.textContent = Math.round(target * ease).toLocaleString();
                if (progress < 1) requestAnimationFrame(step);
            }
            requestAnimationFrame(step);
        });
    }

    /* ── Animate progress bars on load ─────────────────── */
    function animateProgressBars() {
        document.querySelectorAll('[data-pct]').forEach(function (bar) {
            const pct = parseFloat(bar.getAttribute('data-pct')) || 0;
            bar.style.width = '0%';
            requestAnimationFrame(function () {
                setTimeout(function () {
                    bar.style.width = Math.min(pct, 100) + '%';
                }, 60);
            });
        });
    }

    /* ── Staggered fade-in for list/grid items ──────────── */
    function staggerItems() {
        document.querySelectorAll('.stagger-item').forEach(function (el, i) {
            el.style.opacity = '0';
            el.style.transform = 'translateY(8px)';
            el.style.transition = 'opacity .3s ease, transform .3s ease';
            setTimeout(function () {
                el.style.opacity = '1';
                el.style.transform = 'translateY(0)';
            }, 60 + i * 50);
        });
    }

    /* ── AI Toast ───────────────────────────────────────── */
    function initToast() {
        const toast = document.getElementById('__ai-toast');
        if (!toast) return;

        window.showAIToast = function (icon, msg) {
            toast.innerHTML = '<i class="fas fa-' + icon + '" style="font-size:13px;color:var(--accent)"></i> ' + msg;
            toast.style.opacity = '1';
            clearTimeout(toast._timer);
            toast._timer = setTimeout(function () { toast.style.opacity = '0'; }, 3200);
        };
    }

    /* ── Nav AI module click handlers ───────────────────── */
    function initPageLoader() {
        const overlay = document.getElementById('pageLoadingOverlay');
        const title = document.getElementById('pageLoadingTitle');
        const subtitle = document.getElementById('pageLoadingSubtitle');
        const progressBar = document.getElementById('pageLoadingProgressBar');
        const progressText = document.getElementById('pageLoadingPercent');
        if (!overlay) return;

        let activeForm = null;
        let progress = 0;
        let progressTimer = null;
        let stageTimer = null;

        function setProgress(value) {
            progress = Math.max(0, Math.min(99, Math.round(value)));
            if (progressBar) progressBar.style.width = progress + '%';
            if (progressText) progressText.textContent = progress + '%';
        }

        function startProgress(mode, stages) {
            clearInterval(progressTimer);
            clearInterval(stageTimer);
            setProgress(mode === 'upload' ? 8 : 14);
            if (stages && stages.length && subtitle) {
                let stageIndex = 0;
                subtitle.textContent = stages[stageIndex];
                stageTimer = setInterval(function () {
                    stageIndex = Math.min(stageIndex + 1, stages.length - 1);
                    subtitle.textContent = stages[stageIndex];
                    if (stageIndex >= stages.length - 1) clearInterval(stageTimer);
                }, mode === 'upload' ? 1800 : 1400);
            }
            progressTimer = setInterval(function () {
                const ceiling = mode === 'upload' ? 94 : 88;
                const step = mode === 'upload' ? Math.max(1, Math.round((ceiling - progress) * .08)) : 2;
                if (progress < ceiling) setProgress(progress + step);
            }, mode === 'upload' ? 420 : 650);
        }

        function show(nextTitle, nextSubtitle, mode, stages) {
            if (title) title.textContent = nextTitle || 'Loading data';
            if (subtitle) subtitle.textContent = nextSubtitle || 'Please wait while MerchOps prepares the page.';
            startProgress(mode || 'page', stages);
            overlay.classList.add('visible');
            overlay.setAttribute('aria-hidden', 'false');
            document.body.classList.add('page-loading-active');
        }

        function hide() {
            clearInterval(progressTimer);
            clearInterval(stageTimer);
            setProgress(100);
            overlay.classList.remove('visible');
            overlay.setAttribute('aria-hidden', 'true');
            document.body.classList.remove('page-loading-active');
            if (activeForm) {
                activeForm.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
                    button.disabled = false;
                });
                activeForm = null;
            }
            setTimeout(function () { setProgress(0); }, 180);
        }

        function textForForm(form) {
            const fileInput = form.querySelector('input[type="file"]');
            const action = (form.getAttribute('action') || '').toLowerCase();
            if (action.indexOf('/inventory') >= 0 && fileInput && fileInput.value) {
                return ['Uploading inventory', 'Reading workbook and validating columns.', [
                    'Reading workbook and validating columns.',
                    'Standardizing inventory fields.',
                    'Saving inventory rows into SQL Server.',
                    'Preparing the inventory view.'
                ]];
            }
            if (action.indexOf('/inventory') >= 0) {
                return ['Updating inventory', 'Applying inventory filters and requirement rules.', [
                    'Applying inventory filters and requirement rules.',
                    'Calculating brand coverage.',
                    'Preparing scorecard rows.'
                ]];
            }
            if (fileInput && fileInput.value) return ['Uploading file', 'Your data is being validated and saved.'];
            if (action.indexOf('upload') >= 0) return ['Uploading data', 'Please wait while rows are cleaned and inserted.'];
            if (action.indexOf('refresh') >= 0) return ['Refreshing report', 'Rebuilding indexes and loading updated results.'];
            return ['Saving changes', 'Please wait while MerchOps processes your request.'];
        }

        document.addEventListener('submit', function (event) {
            const form = event.target;
            if (!form || form.matches('[data-no-loader]')) return;
            const target = (form.getAttribute('target') || '').toLowerCase();
            if (target === '_blank') return;
            const copy = textForForm(form);
            const mode = form.querySelector('input[type="file"]') ? 'upload' : 'page';
            activeForm = form;
            form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
                button.disabled = true;
            });
            show(copy[0], copy[1], mode, copy[2]);
        }, true);

        document.addEventListener('click', function (event) {
            const link = event.target.closest('a[href]');
            if (!link || link.matches('[data-no-loader]')) return;
            const href = link.getAttribute('href') || '';
            if (!href || href === '#' || href.startsWith('#') || href.startsWith('javascript:')) return;
            if (link.target && link.target.toLowerCase() === '_blank') return;
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

            let url;
            try {
                url = new URL(href, window.location.href);
            } catch (e) {
                return;
            }
            if (url.origin !== window.location.origin) return;
            if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
            if (url.pathname.indexOf('/inventory') === 0) {
                show('Loading inventory', 'Fetching stock and sales scorecard data.', 'page', [
                    'Fetching stock and sales scorecard data.',
                    'Applying requirement settings.',
                    'Building brand coverage summary.',
                    'Trend charts will load after the page opens.'
                ]);
            } else {
                show('Loading page', 'Opening the selected workspace.', 'page');
            }
        }, true);

        window.addEventListener('beforeunload', function () {
            const isInventory = window.location.pathname.indexOf('/inventory') === 0;
            show(
                isInventory ? 'Loading inventory' : 'Loading data',
                isInventory ? 'Refreshing inventory scorecard.' : 'Please wait while MerchOps updates the page.',
                'page',
                isInventory ? ['Refreshing inventory scorecard.', 'Applying filters.', 'Preparing dashboard.'] : null
            );
        });
        window.addEventListener('pageshow', hide);
        window.showPageLoader = show;
        window.hidePageLoader = hide;
    }

    function bindNavModules() {
        [
            { id: 'emailNavLink', icon: 'robot',     name: 'Email Agent' },
            { id: 'faceNavLink',  icon: 'microchip', name: 'Face Login'  }
        ].forEach(function (mod) {
            const el = document.getElementById(mod.id);
            if (!el) return;
            el.addEventListener('click', function (e) {
                e.preventDefault();
                if (window.showAIToast) {
                    window.showAIToast(mod.icon, 'AI Module: ' + mod.name + ' — neural interface ready');
                }
                const card = document.querySelector('.container-card');
                if (card) {
                    const flash = document.createElement('div');
                    flash.className = 'flash flash-info';
                    flash.innerHTML = '<i class="fas fa-microchip"></i> ' + mod.name + ' module is being initialized…';
                    card.insertBefore(flash, card.firstChild);
                    setTimeout(function () {
                        flash.style.opacity = '0';
                        flash.style.transition = 'opacity .4s';
                        setTimeout(function () { flash.remove(); }, 400);
                    }, 3000);
                }
            });
        });
    }

    /* ── Mobile sidebar toggle ─────────────────────────── */
    function bindSidebarToggle() {
        var shell    = document.querySelector('.app-shell');
        var toggle   = document.getElementById('sidebarToggle');
        var backdrop = document.getElementById('sidebarBackdrop');
        if (!shell || !toggle) return;

        function openSidebar() {
            shell.classList.add('sidebar-open');
            if (backdrop) backdrop.classList.add('visible');
            document.body.style.overflow = 'hidden';
        }
        function closeSidebar() {
            shell.classList.remove('sidebar-open');
            if (backdrop) backdrop.classList.remove('visible');
            document.body.style.overflow = '';
        }

        toggle.addEventListener('click', function () {
            if (shell.classList.contains('sidebar-open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });

        if (backdrop) {
            backdrop.addEventListener('click', closeSidebar);
        }

        // Close on nav link click (navigating away on mobile)
        document.querySelectorAll('.nav-link').forEach(function (link) {
            link.addEventListener('click', function () {
                if (window.innerWidth <= 1024) closeSidebar();
            });
        });

        // Close when resizing back to desktop
        window.addEventListener('resize', function () {
            if (window.innerWidth > 1024) closeSidebar();
        });
    }

    /* ── Expandable sidebar sections ───────────────────── */
    function bindSidebarSections() {
        var storageKey = 'sidebarSectionState';
        var groups = Array.prototype.slice.call(document.querySelectorAll('.nav-group-expandable'));
        if (!groups.length) return;

        function readState() {
            try {
                return JSON.parse(localStorage.getItem(storageKey) || '{}');
            } catch (e) {
                return {};
            }
        }

        function writeState(state) {
            try {
                localStorage.setItem(storageKey, JSON.stringify(state));
            } catch (e) {}
        }

        function setPanelHeight(group, expanded) {
            var panel = group.querySelector('.nav-panel');
            if (!panel) return;
            if (expanded) {
                panel.style.maxHeight = panel.scrollHeight + 'px';
            } else {
                panel.style.maxHeight = panel.scrollHeight + 'px';
                requestAnimationFrame(function () {
                    panel.style.maxHeight = '0px';
                });
            }
        }

        function setExpanded(group, expanded, persist) {
            var button = group.querySelector('.nav-toggle');
            var key = group.getAttribute('data-nav-group');
            group.classList.toggle('is-collapsed', !expanded);
            if (button) button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            setPanelHeight(group, expanded);

            if (persist && key) {
                var state = readState();
                state[key] = expanded;
                writeState(state);
            }
        }

        var state = readState();

        groups.forEach(function (group) {
            var button = group.querySelector('.nav-toggle');
            var key = group.getAttribute('data-nav-group');
            var hasActiveLink = !!group.querySelector('.nav-link.active');
            var expanded = key && Object.prototype.hasOwnProperty.call(state, key) ? !!state[key] : true;

            if (hasActiveLink) expanded = true;
            setExpanded(group, expanded, false);

            if (button) {
                button.addEventListener('click', function () {
                    setExpanded(group, group.classList.contains('is-collapsed'), true);
                });
            }
        });

        window.addEventListener('resize', function () {
            groups.forEach(function (group) {
                if (!group.classList.contains('is-collapsed')) {
                    setPanelHeight(group, true);
                }
            });
        });
    }

    /* ── Active nav highlight on current path ───────────── */
    function highlightActiveNav() {
        const path = window.location.pathname;
        document.querySelectorAll('.nav-link[href]').forEach(function (link) {
            if (link.href && link.getAttribute('href') !== '#') {
                const href = link.getAttribute('href');
                if (path === href || (href !== '/' && path.startsWith(href))) {
                    link.classList.add('active');
                }
            }
        });
    }

    /* ── Shimmer placeholder removal ────────────────────── */
    function clearShimmers() {
        document.querySelectorAll('.shimmer-placeholder').forEach(function (el) {
            el.classList.remove('shimmer-placeholder', 'shimmer');
        });
    }

    /* ── Boot ───────────────────────────────────────────── */
    initTheme();

    document.addEventListener('DOMContentLoaded', function () {
        bindThemeToggle();
        bindSidebarToggle();
        highlightActiveNav();
        bindSidebarSections();
        initToast();
        initPageLoader();
        bindNavModules();
        animateCounters();
        animateProgressBars();
        staggerItems();
        clearShimmers();
    });

})();
