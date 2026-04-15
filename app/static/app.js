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
        (body.facturas || []).forEach((f) => {
            const tr = document.createElement('tr');
            tr.dataset.semaforo = f.semaforo;
            tr.className = 'semaforo-' + f.semaforo;
            const icono = { verde: '🟢', amarillo: '🟡', rojo: '🔴', gris: '⚪' }[f.semaforo] || '';
            const warn = f.advertencia_contabil ? ' ⚠️' : '';
            tr.innerHTML = `
                <td>${icono}${warn}</td>
                <td>${f.serie}${f.numero}</td>
                <td>${f.fecha}</td>
                <td>${f.cliente_codigo}</td>
                <td><code>${f.subcuenta || '—'}</code></td>
                <td class="right">${formatEur(f.total)} €</td>
                <td class="hint">${f.mensaje || ''}</td>
            `;
            tbody.appendChild(tr);
        });

        const seccion = $('section.preview');
        if (seccion) seccion.hidden = false;

        const btnGenerar = $('[data-action="generar-dat"]');
        if (btnGenerar) {
            const hayRojos = (r.rojos || 0) > 0;
            const hayExportables = (r.exportables || 0) > 0;
            btnGenerar.disabled = hayRojos || !hayExportables;
        }
    }

    // ─── Edición inline de mappings ─────────────────────────────────────────

    function inicializarEdicionInline() {
        document.addEventListener('click', async (e) => {
            const btnGuardar = e.target.closest('[data-action="guardar"]');
            if (btnGuardar) {
                await guardarMappingInline(btnGuardar);
                return;
            }
            const btnRevisar = e.target.closest('[data-action="revisado"]');
            if (btnRevisar) {
                await marcarRevisadoInline(btnRevisar);
                return;
            }
        });
    }

    async function guardarMappingInline(btn) {
        const tr = btn.closest('tr');
        if (!tr) return;
        const input = $('input[data-field]', tr);
        if (!input) return;
        const valor = input.value.trim();
        const esCliente = !!tr.dataset.codigo;
        const regex = esCliente ? RE_SUBCUENTA_CLIENTE : RE_SUBCUENTA_INGRESO;
        if (!regex.test(valor)) {
            alert(esCliente
                ? 'Subcuenta de cliente inválida (430XXX).'
                : 'Cuenta de ingreso inválida (700/705/755 XXX).');
            return;
        }
        const id = tr.dataset.codigo || tr.dataset.clave;
        const url = esCliente
            ? `/mappings/clientes/${encodeURIComponent(id)}`
            : `/mappings/articulos/${encodeURIComponent(id)}`;
        const payload = esCliente ? { subcuenta_a3: valor } : { cuenta_a3: valor };
        try {
            await postJSON(url, payload);
            input.classList.add('saved');
            setTimeout(() => input.classList.remove('saved'), 1500);
        } catch (err) {
            alert('Error: ' + err.message);
        }
    }

    async function marcarRevisadoInline(btn) {
        const tr = btn.closest('tr');
        if (!tr) return;
        const id = tr.dataset.codigo || tr.dataset.clave;
        const esCliente = !!tr.dataset.codigo;
        const url = esCliente
            ? `/mappings/clientes/${encodeURIComponent(id)}/revisar`
            : `/mappings/articulos/${encodeURIComponent(id)}/revisar`;
        try {
            await postJSON(url, { revisado: true });
            const estado = tr.querySelector('td:nth-last-child(2)');
            if (estado) estado.textContent = '✓';
        } catch (err) {
            alert('Error: ' + err.message);
        }
    }

    // ─── /config: verificar conexión DBF ────────────────────────────────────

    function inicializarVerificarDbf() {
        const btn = $('[data-action="verificar-dbf"]');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const input = $('input[name="dbf_path"]');
            if (!input) return;
            btn.disabled = true;
            try {
                const body = await postJSON('/config/verificar-dbf', { dbf_path: input.value });
                if (body.ok) {
                    alert(`Conexión OK: ${body.n_clientes} clientes, ${body.n_articulos} artículos.`);
                } else {
                    alert('Error: ' + (body.error || 'desconocido'));
                }
            } catch (e) {
                alert('Error: ' + e.message);
            } finally {
                btn.disabled = false;
            }
        });
    }

    // ─── Bootstrap ──────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        inicializarConstructorFiltros();
        inicializarPreview();
        inicializarEdicionInline();
        inicializarVerificarDbf();
    });
})();
