// gesdai-exporter — JS de cliente, vanilla, sin frameworks.
// Responsabilidades:
//   - Constructor visual de filtros AND/OR sobre el árbol Filtros/Condicion
//   - Previsualización asíncrona y generación de DAT
//   - Edición inline de mappings (subcuentas) con validación regex
//   - Semáforo automático tras cada preview

(function () {
    'use strict';

    const RE_SUBCUENTA_CLIENTE = /^430\d{3}$/;
    const RE_SUBCUENTA_INGRESO = /^(700|705|755)\d{3}$/;

    // ─── Helpers ────────────────────────────────────────────────────────────

    function $(sel, ctx) { return (ctx || document).querySelector(sel); }
    function $$(sel, ctx) { return Array.from((ctx || document).querySelectorAll(sel)); }

    async function postJSON(url, data) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data || {}),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok || body.ok === false) {
            throw new Error(body.error || `HTTP ${res.status}`);
        }
        return body;
    }

    function formatEur(valorStr) {
        const n = parseFloat(valorStr || '0');
        return n.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // ─── Constructor de filtros ─────────────────────────────────────────────

    // El árbol se mantiene en memoria como:
    //   { operador: 'AND'|'OR', condiciones: [ {campo, operador, valor} | subgrupo ] }
    // y se re-renderiza cada vez que cambia. El front NUNCA lee del DOM el
    // estado — siempre del objeto JS — así evitamos desincronización.

    const CAMPOS_DISPONIBLES = [
        { valor: 'fecha',      etiqueta: 'Fecha',   operadores: ['entre', 'antes_de', 'despues_de', 'igual'] },
        { valor: 'cliente',    etiqueta: 'Cliente', operadores: ['igual', 'no_igual', 'contiene'] },
        { valor: 'serie',      etiqueta: 'Serie',   operadores: ['igual', 'no_igual'] },
        { valor: 'importe',    etiqueta: 'Importe', operadores: ['mayor_que', 'menor_que', 'entre', 'igual'] },
        { valor: 'resolucion', etiqueta: 'Semáforo', operadores: ['igual'] },
    ];

    const OPERADOR_ETIQUETAS = {
        'igual': 'es',
        'no_igual': 'no es',
        'contiene': 'contiene',
        'entre': 'entre',
        'antes_de': 'antes de',
        'despues_de': 'después de',
        'mayor_que': 'mayor que',
        'menor_que': 'menor que',
    };

    let estadoFiltros = { operador: 'AND', condiciones: [] };
    let rootEl = null;

    function inicializarConstructorFiltros() {
        rootEl = $('#constructor-filtros');
        if (!rootEl) return;

        // Estado inicial desde data-inicial (server-side)
        const inicial = rootEl.dataset.inicial;
        if (inicial) {
            try {
                estadoFiltros = JSON.parse(inicial);
                if (!estadoFiltros.operador) estadoFiltros.operador = 'AND';
                if (!Array.isArray(estadoFiltros.condiciones)) estadoFiltros.condiciones = [];
            } catch (e) {
                console.warn('filtros-iniciales JSON inválido, usando vacío');
                estadoFiltros = { operador: 'AND', condiciones: [] };
            }
        }
        renderFiltros();

        // Botones de toolbar
        $$('[data-action="add-condicion"]').forEach((btn) =>
            btn.addEventListener('click', () => {
                estadoFiltros.condiciones.push({
                    campo: 'fecha', operador: 'entre', valor: ['', ''],
                });
                renderFiltros();
            }),
        );
        $$('[data-action="add-grupo"]').forEach((btn) =>
            btn.addEventListener('click', () => {
                estadoFiltros.condiciones.push({
                    operador: 'OR', condiciones: [],
                });
                renderFiltros();
            }),
        );
        $$('[data-action="limpiar-filtros"]').forEach((btn) =>
            btn.addEventListener('click', () => {
                estadoFiltros = { operador: 'AND', condiciones: [] };
                renderFiltros();
            }),
        );
    }

    function renderFiltros() {
        if (!rootEl) return;
        rootEl.innerHTML = '';
        rootEl.appendChild(renderGrupo(estadoFiltros, []));
    }

    function renderGrupo(grupo, path) {
        const div = document.createElement('div');
        div.className = 'filtro-grupo';

        const header = document.createElement('div');
        header.className = 'filtro-grupo-header';
        const sel = document.createElement('select');
        ['AND', 'OR'].forEach((op) => {
            const opt = document.createElement('option');
            opt.value = op;
            opt.textContent = op;
            if (grupo.operador === op) opt.selected = true;
            sel.appendChild(opt);
        });
        sel.addEventListener('change', () => {
            grupo.operador = sel.value;
        });
        header.appendChild(sel);

        if (path.length > 0) {
            const btnDel = document.createElement('button');
            btnDel.type = 'button';
            btnDel.textContent = '✕ grupo';
            btnDel.addEventListener('click', () => {
                eliminarEnPath(path);
                renderFiltros();
            });
            header.appendChild(btnDel);
        }

        const btnAddCond = document.createElement('button');
        btnAddCond.type = 'button';
        btnAddCond.textContent = '+ condición';
        btnAddCond.addEventListener('click', () => {
            grupo.condiciones.push({ campo: 'fecha', operador: 'entre', valor: ['', ''] });
            renderFiltros();
        });
        header.appendChild(btnAddCond);

        const btnAddGrupo = document.createElement('button');
        btnAddGrupo.type = 'button';
        btnAddGrupo.textContent = '+ subgrupo';
        btnAddGrupo.addEventListener('click', () => {
            grupo.condiciones.push({ operador: 'OR', condiciones: [] });
            renderFiltros();
        });
        header.appendChild(btnAddGrupo);

        div.appendChild(header);

        grupo.condiciones.forEach((cond, idx) => {
            const childPath = path.concat([idx]);
            if ('condiciones' in cond) {
                div.appendChild(renderGrupo(cond, childPath));
            } else {
                div.appendChild(renderCondicion(cond, childPath));
            }
        });

        return div;
    }

    function renderCondicion(cond, path) {
        const row = document.createElement('div');
        row.className = 'filtro-condicion';

        const selCampo = document.createElement('select');
        CAMPOS_DISPONIBLES.forEach((c) => {
            const opt = document.createElement('option');
            opt.value = c.valor;
            opt.textContent = c.etiqueta;
            if (cond.campo === c.valor) opt.selected = true;
            selCampo.appendChild(opt);
        });
        selCampo.addEventListener('change', () => {
            cond.campo = selCampo.value;
            const defs = CAMPOS_DISPONIBLES.find((c) => c.valor === cond.campo);
            if (defs && !defs.operadores.includes(cond.operador)) {
                cond.operador = defs.operadores[0];
            }
            renderFiltros();
        });
        row.appendChild(selCampo);

        const campoDef = CAMPOS_DISPONIBLES.find((c) => c.valor === cond.campo);
        const selOp = document.createElement('select');
        (campoDef ? campoDef.operadores : []).forEach((op) => {
            const opt = document.createElement('option');
            opt.value = op;
            opt.textContent = OPERADOR_ETIQUETAS[op] || op;
            if (cond.operador === op) opt.selected = true;
            selOp.appendChild(opt);
        });
        selOp.addEventListener('change', () => {
            cond.operador = selOp.value;
            // entre ↔ igual cambia la forma del valor
            if (cond.operador === 'entre' && !Array.isArray(cond.valor)) {
                cond.valor = ['', ''];
            } else if (cond.operador !== 'entre' && Array.isArray(cond.valor)) {
                cond.valor = cond.valor[0] || '';
            }
            renderFiltros();
        });
        row.appendChild(selOp);

        // Inputs del valor
        if (cond.operador === 'entre') {
            const tipoInput = cond.campo === 'fecha' ? 'date' : 'number';
            if (!Array.isArray(cond.valor)) cond.valor = ['', ''];
            [0, 1].forEach((i) => {
                const inp = document.createElement('input');
                inp.type = tipoInput;
                inp.value = cond.valor[i] || '';
                inp.addEventListener('input', () => { cond.valor[i] = inp.value; });
                row.appendChild(inp);
            });
        } else if (cond.campo === 'resolucion') {
            const sel = document.createElement('select');
            ['verde', 'amarillo', 'rojo', 'gris'].forEach((v) => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                if (cond.valor === v) opt.selected = true;
                sel.appendChild(opt);
            });
            sel.addEventListener('change', () => { cond.valor = sel.value; });
            row.appendChild(sel);
        } else {
            const inp = document.createElement('input');
            inp.type = cond.campo === 'fecha' ? 'date'
                     : cond.campo === 'importe' ? 'number'
                     : 'text';
            inp.value = typeof cond.valor === 'string' ? cond.valor : '';
            inp.addEventListener('input', () => { cond.valor = inp.value; });
            row.appendChild(inp);
        }

        const btnDel = document.createElement('button');
        btnDel.type = 'button';
        btnDel.textContent = '✕';
        btnDel.addEventListener('click', () => {
            eliminarEnPath(path);
            renderFiltros();
        });
        row.appendChild(btnDel);

        return row;
    }

    function eliminarEnPath(path) {
        let nodo = estadoFiltros;
        for (let i = 0; i < path.length - 1; i++) {
            nodo = nodo.condiciones[path[i]];
        }
        nodo.condiciones.splice(path[path.length - 1], 1);
    }

    // ─── Preview de exportación ─────────────────────────────────────────────

    function inicializarPreview() {
        const btnPreview = $('[data-action="preview"]');
        if (btnPreview) {
            btnPreview.addEventListener('click', async () => {
                btnPreview.disabled = true;
                try {
                    const body = await postJSON('/export/preview', { filtros: estadoFiltros });
                    actualizarTablaPreview(body);
                } catch (e) {
                    alert('Error al previsualizar: ' + e.message);
                } finally {
                    btnPreview.disabled = false;
                }
            });
        }

        const btnGenerar = $('[data-action="generar-dat"]');
        if (btnGenerar) {
            btnGenerar.addEventListener('click', async () => {
                if (!confirm('¿Generar SUENLACE.DAT con las facturas previsualizadas?')) return;
                btnGenerar.disabled = true;
                try {
                    const body = await postJSON('/export/generar', { filtros: estadoFiltros });
                    if (body.download_url) {
                        window.location.href = body.download_url;
                    } else {
                        alert(`DAT generado: ${body.num_facturas} facturas, SHA ${body.sha256.slice(0, 12)}…`);
                    }
                } catch (e) {
                    alert('Error al generar DAT: ' + e.message);
                    btnGenerar.disabled = false;
                }
            });
        }

        const btnExcel = $('[data-action="export-preview-excel"]');
        if (btnExcel) {
            btnExcel.addEventListener('click', async () => {
                const res = await fetch('/export/preview/excel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filtros: estadoFiltros }),
                });
                if (!res.ok) { alert('Error: ' + res.status); return; }
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'preview_export.xlsx';
                a.click();
                URL.revokeObjectURL(url);
            });
        }
    }

    function actualizarTablaPreview(body) {
        const r = body.resumen || {};
        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        set('r-facturas', r.total || 0);
        set('r-exportables', r.exportables || 0);
        set('r-verdes', r.verdes || 0);
        set('r-amarillos', r.amarillos || 0);
        set('r-rojos', r.rojos || 0);
        set('r-grises', r.grises || 0);
        set('r-importe', formatEur(r.importe_total) + ' €');

        const tbody = $('#tabla-preview tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        const facturas = body.facturas || [];
        facturas.forEach((f) => {
            const tr = document.createElement('tr');
            tr.dataset.semaforo = f.semaforo;
            tr.dataset.codigo = f.codigo;
            tr.dataset.cliente = f.cliente_codigo;
            tr.className = 'semaforo-' + f.semaforo + ' preview-row';
            tr.style.cursor = 'pointer';
            const icono = { verde: '🟢', amarillo: '🟡', rojo: '🔴', gris: '⚪' }[f.semaforo] || '';
            const warn = f.advertencia_contabil ? ' ⚠️' : '';
            const sub = f.subcuenta || '';
            tr.innerHTML = `
                <td>${icono}${warn}</td>
                <td class="mono">${escapeHtml(f.serie)}${escapeHtml(f.numero)}</td>
                <td>${escapeHtml(f.fecha)}</td>
                <td>${escapeHtml(f.cliente_codigo)}</td>
                <td>
                    <input type="text"
                           pattern="^430\\d{3}$"
                           maxlength="6"
                           inputmode="numeric"
                           value="${escapeHtml(sub)}"
                           data-autosave="cliente"
                           data-id="${escapeHtml(f.cliente_codigo)}"
                           data-last="${escapeHtml(sub)}"
                           placeholder="430001">
                </td>
                <td class="right">${formatEur(f.total)} €</td>
                <td class="hint">${escapeHtml(f.mensaje || '')}</td>
            `;
            tbody.appendChild(tr);
        });
        // Re-wire de los inputs recién creados.
        $$('#tabla-preview input[data-autosave]').forEach(wireAutosaveInput);

        const empty = document.getElementById('preview-empty');
        if (empty) empty.hidden = facturas.length > 0;

        const seccion = $('section.preview');
        if (seccion) seccion.hidden = false;

        const btnGenerar = $('[data-action="generar-dat"]');
        if (btnGenerar) {
            const hayRojos = (r.rojos || 0) > 0;
            const hayExportables = (r.exportables || 0) > 0;
            btnGenerar.disabled = hayRojos || !hayExportables;
        }
    }

    // ─── Modal detalle de factura ─────────────────────────────────────────────

    // Marcamos el modal como "dirty" cada vez que se guarda con éxito una
    // cuenta de artículo desde sus inputs internos. Al cerrar el modal con
    // cambios, re-disparamos la preview para que el semáforo y la resolución
    // de las facturas que usan ese artículo reflejen la nueva cuenta.
    let modalDirty = false;

    function inicializarModalFactura() {
        const modal = document.getElementById('modal-factura');
        if (!modal) return;

        // Delegated click on preview rows.
        // No abrimos modal si el click es sobre un input editable (subcuenta)
        // dentro de la fila — eso es edición inline, no navegación al detalle.
        document.addEventListener('click', (e) => {
            if (e.target.closest('input, button, a')) return;
            const row = e.target.closest('.preview-row');
            if (row && row.dataset.codigo) {
                abrirModalFactura(row.dataset.codigo, row.dataset.semaforo);
            }
        });

        const cerrarModal = () => {
            modal.hidden = true;
            if (modalDirty) {
                modalDirty = false;
                // Re-disparamos la preview para refrescar semáforo/subcuentas
                // tras los mapeos guardados desde el modal.
                const btnPreview = $('[data-action="preview"]');
                if (btnPreview) btnPreview.click();
            }
        };

        // Close modal
        modal.addEventListener('click', (e) => {
            if (e.target === modal || e.target.closest('[data-action="close-modal"]')) {
                cerrarModal();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !modal.hidden) {
                cerrarModal();
            }
        });
    }

    async function abrirModalFactura(codigo, semaforo) {
        const modal = document.getElementById('modal-factura');
        if (!modal) return;

        const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        const setHTML = (id, v) => { const el = document.getElementById(id); if (el) el.innerHTML = v; };

        // Show modal with loading state
        set('md-title', 'Cargando...');
        set('md-subtitle', '');
        setHTML('md-lineas-body', '');
        modal.hidden = false;

        try {
            const res = await fetch('/export/factura/' + encodeURIComponent(codigo));
            const body = await res.json();
            if (!res.ok || body.ok === false) {
                set('md-title', 'Error');
                set('md-subtitle', body.error || 'No se pudo cargar la factura');
                return;
            }

            const f = body.factura;
            const cli = body.cliente;

            // Header
            set('md-title', 'Factura ' + f.serie + f.numero);
            set('md-subtitle', f.fecha + ' · Serie ' + f.serie + ' · ' + cli.nombre);

            // Meta
            set('md-cliente', cli.nombre);
            set('md-nif', cli.nif || '—');
            set('md-subcuenta', body.subcuenta || '—');
            set('md-base', formatEur(f.total_base) + ' €');
            set('md-total', formatEur(f.total_con_iva) + ' €');

            // Semaphore badge
            const sem = semaforo || 'gris';
            const semLabel = { verde: 'Verde', amarillo: 'Amarillo', rojo: 'Rojo', gris: 'Gris' }[sem] || sem;
            setHTML('md-semaforo',
                '<span class="chip chip-' + sem + '" style="font-size:12px; padding:4px 10px;">' +
                '<span class="chip-dot"></span>' + semLabel + '</span>'
            );

            // Lines table
            const lineas = body.lineas || [];
            set('md-lineas-count', lineas.length + ' articulos');
            let hasKeywordOrDefault = false;
            let lineasHTML = '';
            lineas.forEach((l) => {
                const isAlt = l.resolucion_tipo === 'keyword' || l.resolucion_tipo === 'default';
                if (isAlt) hasKeywordOrDefault = true;
                const rowClass = isAlt ? 'row-keyword' : '';
                const articulo = l.articulo || '';
                const descripcion = l.comentario || l.articulo || '';
                const resolMark = isAlt
                    ? '<br><span style="font-size:11px; color:#92400E;">texto libre · resolución por ' + l.resolucion_tipo + '</span>'
                    : '';
                const articuloCell = articulo
                    ? escapeHtml(articulo.substring(0, 8))
                    : '<span class="hint">—</span>';
                // Cada línea de la factura es editable:
                //   - Con clave → guarda en mappings_articulos
                //                 (data-autosave="articulo", id=clave).
                //   - Sin clave (texto libre) → guarda como keyword usando
                //                 el comentario como patrón
                //                 (data-autosave="keyword", id=comentario).
                // En ambos casos, al recargar la preview, el cambio se aplica
                // automáticamente a todas las facturas que coincidan.
                let cuentaCell;
                if (articulo) {
                    cuentaCell = '<input type="text"' +
                        ' pattern="^(700|705|755)\\d{3}$"' +
                        ' maxlength="6" inputmode="numeric"' +
                        ' value="' + escapeHtml(l.cuenta_a3 || '') + '"' +
                        ' data-autosave="articulo"' +
                        ' data-id="' + escapeHtml(articulo) + '"' +
                        ' data-last="' + escapeHtml(l.cuenta_a3 || '') + '"' +
                        ' data-modal="1"' +
                        ' placeholder="700001"' +
                        ' style="width:110px;">';
                } else if (l.comentario) {
                    cuentaCell = '<input type="text"' +
                        ' pattern="^(700|705|755)\\d{3}$"' +
                        ' maxlength="6" inputmode="numeric"' +
                        ' value="' + escapeHtml(l.cuenta_a3 || '') + '"' +
                        ' data-autosave="keyword"' +
                        ' data-id="' + escapeHtml(l.comentario) + '"' +
                        ' data-last="' + escapeHtml(l.cuenta_a3 || '') + '"' +
                        ' data-modal="1"' +
                        ' title="Crea/actualiza una keyword usando el comentario completo"' +
                        ' placeholder="700001"' +
                        ' style="width:110px;">';
                } else {
                    const cuentaColor = isAlt ? '#92400E' : 'var(--primary)';
                    cuentaCell = '<span class="mono" style="font-size:11px; font-weight:500; color:' +
                        cuentaColor + ';">' + escapeHtml(l.cuenta_a3 || '') + '</span>';
                }
                lineasHTML += '<tr class="' + rowClass + '">' +
                    '<td class="mono" style="font-size:12px;">' + articuloCell + '</td>' +
                    '<td style="font-size:13px;">' + escapeHtml(descripcion) + resolMark + '</td>' +
                    '<td class="right mono" style="font-size:12px;">' + l.cantidad + '</td>' +
                    '<td class="right mono" style="font-size:12px;">' + formatEur(l.precio) + ' €</td>' +
                    '<td class="right mono" style="font-size:12px; font-weight:500;">' + formatEur(l.total_linea) + ' €</td>' +
                    '<td class="center">' + cuentaCell + '</td>' +
                    '</tr>';
            });
            setHTML('md-lineas-body', lineasHTML);
            // Wire-up auto-save en los inputs recién creados.
            $$('#md-lineas-body input[data-autosave]').forEach(wireAutosaveInput);
            // Combobox con buscador para las cuentas 700/705/755 — comparte
            // catálogo cacheado entre todas las líneas y modales abiertos
            // durante la sesión.
            const cuentaInputs = $$('#md-lineas-body input[data-autosave="articulo"], #md-lineas-body input[data-autosave="keyword"]');
            if (cuentaInputs.length > 0) {
                let cuentasCargadas = [];
                getCuentasCatalog().then((opts) => { cuentasCargadas = opts; });
                cuentaInputs.forEach((inp) => attachCombobox(inp, () => cuentasCargadas));
            }

            // IVA breakdown
            let ivaHTML = '';
            const bases = [
                { base: f.ptsbase1, iva: f.iva1, label: '21%' },
                { base: f.ptsbase2, iva: f.iva2, label: '10%' },
                { base: f.ptsbase3, iva: f.iva3, label: '4%' },
            ];
            bases.forEach((b) => {
                const baseVal = parseFloat(b.base || '0');
                if (baseVal > 0) {
                    ivaHTML += '<div class="modal-iva-row"><span>Base ' + b.label + '</span><span>' + formatEur(b.base) + ' €</span></div>';
                    ivaHTML += '<div class="modal-iva-row"><span>Cuota ' + b.label + '</span><span>' + formatEur(b.iva) + ' €</span></div>';
                }
            });
            setHTML('md-iva-rows', ivaHTML);

            // Totals
            const totalBase = parseFloat(f.total_base || '0');
            const totalIva = parseFloat(f.total_con_iva || '0') - totalBase;
            set('md-tot-base', formatEur(f.total_base) + ' €');
            set('md-tot-iva', formatEur(String(totalIva)) + ' €');
            set('md-tot-total', formatEur(f.total_con_iva) + ' €');

            // Show tip if there are keyword/default lines
            const tip = document.getElementById('md-tip');
            if (tip) tip.hidden = !hasKeywordOrDefault;

        } catch (err) {
            set('md-title', 'Error');
            set('md-subtitle', err.message);
        }
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ─── Edición inline de mappings (autosave) ──────────────────────────────
    //
    // Filosofía: el único usuario escribe la subcuenta directamente en el
    // input. Al cumplir la regex (430XXX / 700-705-755 XXX) se POSTea al backend
    // con un pequeño debounce (evita guardar en cada pulsación mientras se
    // teclea). Guardar = marcar revisado. Un duplicado devuelve 409 y se
    // resalta en rojo con el mensaje del backend.

    const AUTOSAVE_DEBOUNCE_MS = 400;

    function inicializarEdicionInline() {
        $$('input[data-autosave]').forEach(wireAutosaveInput);
    }

    // Wire-up del auto-save para un único input. Se exporta como helper para
    // poder enganchar inputs creados dinámicamente (preview tras filtros,
    // modal de detalle de factura) sin duplicar el cableado de eventos.
    function wireAutosaveInput(input) {
        if (input.dataset.wired === '1') return;
        input.dataset.wired = '1';

        let timer = null;
        const scheduleSave = () => {
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => tryAutosave(input), AUTOSAVE_DEBOUNCE_MS);
        };

        input.addEventListener('input', () => {
            input.classList.remove('is-saved', 'is-error');
            const raw = input.value.trim();
            const normalizado = normalizar(raw, input);
            if (raw === '' || regexFor(input).test(normalizado)) {
                scheduleSave();
            }
        });

        input.addEventListener('blur', () => {
            if (timer) { clearTimeout(timer); timer = null; }
            tryAutosave(input);
        });

        input.addEventListener('keydown', (e) => {
            // Enter = guardar ya y saltar al siguiente. Tab salta solo por
            // orden natural del DOM (no hay botones intermedios).
            if (e.key === 'Enter') {
                e.preventDefault();
                if (timer) { clearTimeout(timer); timer = null; }
                tryAutosave(input).then(() => focusSiguiente(input));
            }
        });

        // Las filas de preview son clickables (abren modal). Detenemos la
        // propagación para que escribir en el input no abra el modal.
        ['click', 'mousedown'].forEach((evt) => {
            input.addEventListener(evt, (e) => e.stopPropagation());
        });
    }

    function regexFor(input) {
        // 'cliente' usa subcuentas 430XXX; 'articulo' y 'keyword' usan ingresos 700/705/755 XXX.
        return input.dataset.autosave === 'cliente'
            ? RE_SUBCUENTA_CLIENTE
            : RE_SUBCUENTA_INGRESO;
    }

    // 1-3 dígitos = sufijo de la cuenta por defecto, padeado a 3 con ceros a
    // la izquierda (430 clientes, 700 artículos). Escribir los 6 dígitos
    // completos permite usar 705/755 puntualmente.
    //   "1"     → "430001" / "700001"
    //   "12"    → "430012" / "700012"
    //   "123"   → "430123" / "700123"
    //   "705042"→ tal cual
    function normalizar(raw, input) {
        if (/^\d{1,3}$/.test(raw)) {
            const sufijo = raw.padStart(3, '0');
            return (input.dataset.autosave === 'cliente' ? '430' : '700') + sufijo;
        }
        return raw;
    }

    async function tryAutosave(input) {
        const tr = input.closest('tr');
        if (!tr) return;
        const raw = input.value.trim();
        const tipo = input.dataset.autosave;  // 'cliente' | 'articulo' | 'keyword'
        const esCliente = tipo === 'cliente';
        const esKeyword = tipo === 'keyword';

        // Vacío: nada que guardar (y no mostramos error).
        if (raw === '') {
            pintarEstado(tr, 'empty', '—');
            return;
        }

        // Expande 3 dígitos al prefijo por defecto. Actualiza el input para
        // que el usuario vea el valor real guardado.
        const valor = normalizar(raw, input);
        if (valor !== raw) {
            input.value = valor;
        }

        if (!regexFor(input).test(valor)) {
            pintarEstado(tr, 'error', esCliente ? 'Formato 430XXX' : 'Formato 700/705/755XXX');
            input.classList.add('is-error');
            return;
        }

        // Si no ha cambiado respecto al último valor guardado, no repitas POST.
        if (input.dataset.last === valor) {
            pintarEstado(tr, 'ok', '✓');
            input.classList.add('is-saved');
            return;
        }

        // Preferimos `data-id` del input — necesario cuando el id de la fila
        // no coincide con el id del mapping (p.ej. en preview la fila es la
        // factura, pero el mapping es por cliente_codigo, o en el modal una
        // línea de texto libre usa el comentario como id de keyword).
        const id = input.dataset.id || tr.dataset.codigo || tr.dataset.clave;
        if (!id) {
            pintarEstado(tr, 'error', 'Sin identificador');
            input.classList.add('is-error');
            return;
        }
        let url, payload;
        if (esCliente) {
            url = `/mappings/clientes/${encodeURIComponent(id)}`;
            payload = { subcuenta_a3: valor };
        } else if (esKeyword) {
            url = '/keywords/upsert';
            payload = { keyword: id, cuenta_a3: valor };
        } else {
            url = `/mappings/articulos/${encodeURIComponent(id)}`;
            payload = { cuenta_a3: valor };
        }

        pintarEstado(tr, 'saving', '…');
        input.classList.remove('is-error', 'is-saved');

        try {
            const body = await postJSON(url, payload);
            input.dataset.last = valor;
            input.classList.add('is-saved');
            input.classList.remove('is-error');
            tr.dataset.revisado = '1';
            pintarEstado(tr, 'ok', '✓');
            if (body.progreso) actualizarProgreso(body.progreso);
            // Si el input vive dentro del modal de detalle, marcamos el modal
            // como dirty para refrescar la preview al cerrarlo. Para los
            // inputs de la propia tabla de preview, refrescamos la fila
            // afectada (cliente_codigo igual) optimistamente.
            if (input.dataset.modal === '1') {
                modalDirty = true;
                // Si lo que se guardó es una cuenta de artículo, el catálogo
                // del combobox puede haber ganado una entrada (artículo recién
                // revisado). Invalidamos la cache para que el próximo modal
                // la incluya.
                if (!esCliente) invalidarCuentasCatalog();
            } else if (esCliente) {
                propagarSubcuentaACliente(id, valor);
            }
        } catch (err) {
            input.classList.add('is-error');
            input.classList.remove('is-saved');
            pintarEstado(tr, 'error', err.message || 'Error');
        }
    }

    // Tras guardar la subcuenta de un cliente desde la tabla de preview,
    // propagamos el valor al resto de filas del mismo cliente (mismo
    // `data-cliente`) para evitar que el usuario tenga que recargar la
    // preview para verlo replicado. El semáforo no se recalcula aquí
    // — el usuario re-disparará "Vista previa" cuando quiera la imagen
    // completa, o lo hacemos automáticamente al cerrar el modal.
    function propagarSubcuentaACliente(clienteCodigo, valor) {
        $$('#tabla-preview tbody tr').forEach((tr) => {
            if (tr.dataset.cliente !== clienteCodigo) return;
            const inp = tr.querySelector('input[data-autosave="cliente"]');
            if (inp && inp.value.trim() !== valor) {
                inp.value = valor;
                inp.dataset.last = valor;
                inp.classList.add('is-saved');
                inp.classList.remove('is-error');
            }
        });
    }

    function pintarEstado(tr, estado, texto) {
        const span = tr.querySelector('.mapping-status');
        if (!span) return;
        span.className = 'mapping-status status-' + estado;
        span.textContent = texto;
        span.title = texto;
    }

    function actualizarProgreso(progreso) {
        const r = document.getElementById('progreso-revisados');
        const t = document.getElementById('progreso-total');
        if (r && typeof progreso.revisados === 'number') r.textContent = progreso.revisados;
        if (t && typeof progreso.total === 'number') t.textContent = progreso.total;
    }

    function focusSiguiente(input) {
        const inputs = $$('input[data-autosave]');
        const idx = inputs.indexOf(input);
        if (idx >= 0 && idx < inputs.length - 1) {
            const next = inputs[idx + 1];
            next.focus();
            next.select();
        }
    }

    // ─── Buscador in-page de tablas de mappings ─────────────────────────────

    function inicializarBuscador() {
        const buscador = document.getElementById('buscador-tabla');
        if (!buscador) return;
        const selector = buscador.dataset.target || '#tabla-articulos';
        const tabla = document.querySelector(selector);
        if (!tabla) return;
        const filas = Array.from(tabla.querySelectorAll('tbody tr'));

        // Shortcut: "/" enfoca el buscador desde cualquier parte de la página.
        document.addEventListener('keydown', (e) => {
            if (e.key === '/' && document.activeElement.tagName !== 'INPUT'
                && document.activeElement.tagName !== 'TEXTAREA') {
                e.preventDefault();
                buscador.focus();
                buscador.select();
            }
        });

        const aplicar = () => {
            const q = buscador.value.trim().toLowerCase();
            if (q === '') {
                filas.forEach((tr) => { tr.hidden = false; });
                return;
            }
            const tokens = q.split(/\s+/);
            filas.forEach((tr) => {
                const hay = tr.dataset.search || '';
                tr.hidden = !tokens.every((t) => hay.includes(t));
            });
        };
        buscador.addEventListener('input', aplicar);
        buscador.addEventListener('search', aplicar);
    }

    // ─── /config: verificar conexión DBF ────────────────────────────────────

    function inicializarVerificarDbf() {
        const btn = $('[data-action="verificar-dbf"]');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const input = $('input[name="dbf_path"]');
            if (!input) return;
            btn.disabled = true;
            const resultEl = document.getElementById('verify-result');
            const textEl = document.getElementById('verify-text');
            try {
                const body = await postJSON('/config/verificar-dbf', { dbf_path: input.value });
                if (resultEl && textEl) {
                    if (body.ok) {
                        resultEl.className = 'verify-result is-ok';
                        textEl.textContent = `Conexión OK — ${body.n_clientes} clientes, ${body.n_articulos} artículos encontrados`;
                    } else {
                        resultEl.className = 'verify-result is-error';
                        textEl.textContent = 'Error: ' + (body.error || 'desconocido');
                    }
                    resultEl.style.display = 'flex';
                } else if (body.ok) {
                    alert(`Conexión OK: ${body.n_clientes} clientes, ${body.n_articulos} artículos.`);
                } else {
                    alert('Error: ' + (body.error || 'desconocido'));
                }
            } catch (e) {
                if (resultEl && textEl) {
                    resultEl.className = 'verify-result is-error';
                    textEl.textContent = 'Error: ' + e.message;
                    resultEl.style.display = 'flex';
                } else {
                    alert('Error: ' + e.message);
                }
            } finally {
                btn.disabled = false;
            }
        });
    }

    // ─── Keywords: probador ────────────────────────────────────────────────

    function inicializarProbador() {
        const form = document.getElementById('form-probar');
        if (!form) return;
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const texto = form.querySelector('input[name="texto"]').value.trim();
            if (!texto) return;
            const resultDiv = document.getElementById('resultado-probar');
            if (!resultDiv) return;
            try {
                const body = await postJSON(form.action, { texto });
                if (body.match) {
                    resultDiv.className = 'tester-result is-match';
                    resultDiv.innerHTML = `
                        <strong>Match encontrado</strong><br>
                        <span>Keyword: <strong>${body.keyword}</strong></span><br>
                        <span>Cuenta: <strong>${body.cuenta_a3}</strong></span><br>
                        <span>Prioridad: <strong>${body.prioridad}</strong></span>
                    `;
                } else {
                    resultDiv.className = 'tester-result is-no-match';
                    resultDiv.textContent = 'Sin coincidencia — se usará la cuenta por defecto.';
                }
            } catch (err) {
                resultDiv.className = 'tester-result is-no-match';
                resultDiv.textContent = 'Error: ' + err.message;
            }
        });
    }

    // ─── Combobox reusable (autocompletado con buscador) ──────────────────
    //
    // Convierte cualquier <input> de texto en un combobox con dropdown
    // filtrable. No reemplaza el input — lo decora — para que la lógica
    // existente (autosave, validación regex, navegación con Tab/Enter)
    // siga funcionando intacta.
    //
    // Uso:
    //   attachCombobox(inputElement, () => [
    //     { value: '700027', label: 'SELLOS OFICIALES COLEGIO' },
    //     ...
    //   ]);
    //
    // El callback `getOptions` se evalúa en cada apertura del dropdown — útil
    // para listas que pueden cambiar (p.ej. cache de catálogo recién cargado).
    //
    // Búsqueda: substring case-insensitive contra `value + ' ' + label`. El
    // ranking prioriza prefijo en value, luego prefijo en label, luego
    // coincidencias en frontera de palabra, finalmente cualquier substring.

    function attachCombobox(input, getOptions) {
        if (input.dataset.combobox === '1') return;
        input.dataset.combobox = '1';

        let dropdown = null;
        let lastFiltered = [];
        let activeIdx = -1;

        function ensureDropdown() {
            if (dropdown) return dropdown;
            dropdown = document.createElement('div');
            dropdown.className = 'combobox-dropdown';
            dropdown.setAttribute('role', 'listbox');
            dropdown.hidden = true;
            document.body.appendChild(dropdown);
            return dropdown;
        }

        function posicionar() {
            if (!dropdown) return;
            const r = input.getBoundingClientRect();
            dropdown.style.left = r.left + 'px';
            dropdown.style.top = (r.bottom + 4) + 'px';
            dropdown.style.minWidth = Math.max(r.width, 280) + 'px';
        }

        function ocultar() {
            if (dropdown) dropdown.hidden = true;
            activeIdx = -1;
        }

        function rankear(opts, query) {
            if (!query) {
                return opts.slice().sort(
                    (a, b) => a.value.localeCompare(b.value),
                ).slice(0, 60);
            }
            const q = query.toLowerCase();
            const scored = [];
            for (const o of opts) {
                const val = (o.value || '').toLowerCase();
                const lab = (o.label || '').toLowerCase();
                const todo = val + ' ' + lab;
                if (!todo.includes(q)) continue;
                let score;
                if (val.startsWith(q)) score = 100;
                else if (lab.startsWith(q)) score = 80;
                else if ((' ' + lab).includes(' ' + q)) score = 70;
                else if (val.includes(q)) score = 50;
                else score = 40;
                scored.push({ o, score });
            }
            scored.sort(
                (a, b) => b.score - a.score || a.o.value.localeCompare(b.o.value),
            );
            return scored.slice(0, 60).map((s) => s.o);
        }

        function pintar() {
            const dd = ensureDropdown();
            const opts = (typeof getOptions === 'function') ? (getOptions() || []) : (getOptions || []);
            lastFiltered = rankear(opts, input.value.trim());
            if (lastFiltered.length === 0) {
                dd.hidden = true;
                return;
            }
            let html = '';
            for (let i = 0; i < lastFiltered.length; i++) {
                const o = lastFiltered[i];
                const cls = 'combobox-item' + (i === activeIdx ? ' is-active' : '');
                html += '<div class="' + cls + '" role="option" data-idx="' + i + '">' +
                    '<span class="combobox-value">' + escapeHtml(o.value) + '</span>' +
                    '<span class="combobox-label">' + escapeHtml(o.label || '') + '</span>' +
                    '</div>';
            }
            dd.innerHTML = html;
            dd.hidden = false;
            posicionar();
            // Scroll item activo a la vista
            if (activeIdx >= 0) {
                const activeEl = dd.querySelector('.combobox-item.is-active');
                if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
            }
        }

        function elegir(idx) {
            const opt = lastFiltered[idx];
            if (!opt) return;
            input.value = opt.value;
            // Disparar `input` para que el autosave detecte el cambio y guarde.
            input.dispatchEvent(new Event('input', { bubbles: true }));
            ocultar();
            input.focus();
        }

        // Mostrar/refrescar al ganar foco o al escribir
        input.addEventListener('focus', () => { activeIdx = -1; pintar(); });
        input.addEventListener('input', () => { activeIdx = -1; pintar(); });

        // Capturar el keydown ANTES del handler de autosave (capture: true)
        // — solo intervenimos cuando el dropdown está visible para no
        // estorbar a Enter/Tab cuando no hay sugerencias.
        input.addEventListener('keydown', (e) => {
            if (!dropdown || dropdown.hidden) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                e.stopImmediatePropagation();
                activeIdx = Math.min(activeIdx + 1, lastFiltered.length - 1);
                if (activeIdx < 0) activeIdx = 0;
                pintar();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                e.stopImmediatePropagation();
                activeIdx = Math.max(activeIdx - 1, 0);
                pintar();
            } else if (e.key === 'Enter' && activeIdx >= 0) {
                e.preventDefault();
                e.stopImmediatePropagation();
                elegir(activeIdx);
            } else if (e.key === 'Escape') {
                e.stopImmediatePropagation();
                ocultar();
            }
        }, { capture: true });

        // Ocultar al perder foco (con delay para permitir click en items)
        input.addEventListener('blur', () => {
            setTimeout(ocultar, 150);
        });

        // Click delegado en items del dropdown (mousedown para anticiparse al blur)
        document.addEventListener('mousedown', (e) => {
            if (!dropdown || dropdown.hidden) return;
            const item = e.target.closest('.combobox-item');
            if (item && dropdown.contains(item)) {
                e.preventDefault();
                elegir(parseInt(item.dataset.idx, 10));
            }
        });

        // Reposicionar al hacer scroll o resize
        window.addEventListener('scroll', () => {
            if (dropdown && !dropdown.hidden) posicionar();
        }, true);
        window.addEventListener('resize', () => {
            if (dropdown && !dropdown.hidden) posicionar();
        });
    }

    // Catálogo de cuentas 700/705/755 conocidas — se carga una vez y se
    // reutiliza en todos los inputs de cuenta del modal. Lazy: la primera
    // apertura del modal lo dispara.
    let cuentasCatalogPromise = null;
    function getCuentasCatalog() {
        if (!cuentasCatalogPromise) {
            cuentasCatalogPromise = fetch('/mappings/articulos/cuentas')
                .then((r) => r.json())
                .then((body) => {
                    if (!body.ok) return [];
                    return (body.cuentas || []).map((c) => ({
                        value: c.cuenta,
                        label: c.descripcion,
                    }));
                })
                .catch(() => []);
        }
        return cuentasCatalogPromise;
    }

    // Invalidar la cache cuando se guarda una cuenta nueva (revisado=1) — así
    // la siguiente apertura del modal verá las cuentas recién bendecidas.
    function invalidarCuentasCatalog() {
        cuentasCatalogPromise = null;
    }

    // ─── Bootstrap ──────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        inicializarConstructorFiltros();
        inicializarPreview();
        inicializarModalFactura();
        inicializarEdicionInline();
        inicializarBuscador();
        inicializarVerificarDbf();
        inicializarProbador();
    });
})();
