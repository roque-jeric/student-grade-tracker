// Small behaviours for the grade tracker: the phone menu, the dialogs, confirmations and printing.
(() => {
    const sidebar = document.getElementById('site-nav');
    const menuButton = document.querySelector('[data-menu]');
    const closeButton = document.querySelector('[data-menu-close]');

    const setMenu = (open) => {
        sidebar.classList.toggle('is-open', open);
        document.body.classList.toggle('menu-open', open);
        menuButton.setAttribute('aria-expanded', String(open));
        (open ? closeButton : menuButton).focus();
    };

    if (menuButton && sidebar) {
        menuButton.addEventListener('click', () => setMenu(true));
        closeButton.addEventListener('click', () => setMenu(false));
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && sidebar.classList.contains('is-open')) setMenu(false);
        });
    }

    document.querySelectorAll('[data-open]').forEach((button) => {
        button.addEventListener('click', () => {
            document.getElementById(button.dataset.open).showModal();
        });
    });

    document.querySelectorAll('dialog').forEach((dialog) => {
        dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
        // A click on the backdrop lands on the dialog itself.
        dialog.addEventListener('click', (event) => {
            if (event.target === dialog) dialog.close();
        });
    });

    // The correction slip shows the change as it will read on the record.
    document.querySelectorAll('[data-preview]').forEach((preview) => {
        const input = preview.closest('form').querySelector('input[name="grade"]');
        const was = Number(preview.dataset.was);

        const draw = () => {
            const now = Number(input.value);
            preview.replaceChildren();
            if (input.value === '' || now === was) {
                const same = document.createElement('span');
                same.className = 'grade';
                same.textContent = was;
                preview.append(same);
                return;
            }
            const change = now - was;
            const wrap = document.createElement('span');
            wrap.className = 'correction';
            const old = document.createElement('s');
            old.className = 'correction-old';
            old.textContent = was;
            const next = document.createElement('span');
            next.className = 'correction-new';
            next.textContent = now;
            const diff = document.createElement('span');
            diff.className = 'correction-change';
            diff.textContent = `${change > 0 ? '+' : '−'}${Math.abs(change)}`;
            wrap.append(old, next, diff);
            preview.append(wrap);
        };

        input.addEventListener('input', draw);
    });

    document.querySelectorAll('form[data-confirm]').forEach((form) => {
        form.addEventListener('submit', (event) => {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        });
    });

    // The class roster: search, standing filter and sort. Without script the full list still shows.
    const roster = document.querySelector('[data-roster]');
    if (roster) {
        const body = roster.tBodies[0];
        const rows = [...body.rows];
        const tools = document.querySelector('[data-roster-tools]');
        const search = document.querySelector('[data-roster-search]');
        const standing = document.querySelector('[data-roster-standing]');
        const count = document.querySelector('[data-roster-count]');
        const empty = document.querySelector('[data-roster-empty]');
        tools.hidden = false;

        const apply = () => {
            const query = search.value.trim().toLowerCase();
            const wanted = standing.value;
            let shown = 0;
            rows.forEach((row) => {
                const match = row.dataset.name.includes(query) && (!wanted || row.dataset.standing === wanted);
                row.hidden = !match;
                if (match) shown += 1;
            });
            const filtered = query || wanted;
            count.textContent = filtered ? `${shown} of ${rows.length} students` : `${rows.length} student${rows.length === 1 ? '' : 's'}`;
            empty.hidden = shown > 0;
            roster.hidden = shown === 0;
        };
        search.addEventListener('input', apply);
        standing.addEventListener('change', apply);

        roster.querySelectorAll('[data-sort]').forEach((button) => {
            button.addEventListener('click', () => {
                const header = button.closest('th');
                const ascending = header.getAttribute('aria-sort') !== 'ascending';
                const key = button.dataset.sort;
                roster.querySelectorAll('th[aria-sort]').forEach((th) => th.removeAttribute('aria-sort'));
                header.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
                const value = (row) => Number(key === 'average' ? row.dataset.average : row.dataset.order);
                [...rows]
                    .sort((a, b) => (ascending ? value(a) - value(b) : value(b) - value(a)))
                    .forEach((row) => body.append(row));
            });
        });
    }

    document.querySelectorAll('[data-print]').forEach((button) => {
        button.addEventListener('click', () => window.print());
    });
})();
