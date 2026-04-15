// gesdai-exporter — JS de cliente, vanilla, sin frameworks.
// Responsabilidades:
//   - Constructor visual de filtros AND/OR
//   - Tabla de preview con clases de semáforo
//   - Edición inline de mappings con POST asíncrono
//   - Validación de subcuentas con regex en cliente

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
            body: JSON.stringify(data),
        });
        if (!res.ok) {
            const text = await res.text();
            throw new Error(`${res.status}: ${text}`);
        }
        return res.json();
    }

    // ─── Constructor de filtros ─────────────────────────────────────────────

    function inicializarConstructorFiltros() {
        const root = $('#constructor-filtros');
        if (!root) return;
        // TODO Fase 4: render de árbol Filtros/Condicion editable
    }

    // ─── Preview de exportación ─────────────────────────────────────────────

    function inicializarPreview() {
        const btn = $('[data-action="preview"]');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            // TODO Fase 4: serializar filtros + POST /export/preview + render tabla
        });
    }

    function actualizarSemaforo() {
        $$('#tabla-preview tbody tr').forEach((tr) => {
            const tipo = tr.dataset.semaforo;
            tr.classList.add('semaforo-' + (tipo || 'gris'));
        });
        const hayRojos = $$('#tabla-preview tbody tr[data-semaforo="rojo"]').length > 0;
        const btnGenerar = $('[data-action="generar-dat"]');
        if (btnGenerar) btnGenerar.disabled = hayRojos;
    }

    // ─── Edición inline de mappings ─────────────────────────────────────────

    function inicializarEdicionInline() {
        document.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-action="guardar"]');
            if (!btn) return;
            const tr = btn.closest('tr');
            const input = $('input[data-field]', tr);
            const valor = input.value.trim();
            const esCliente = !!tr.dataset.codigo;
            const re = esCliente ? RE_SUBCUENTA_CLIENTE : RE_SUBCUENTA_INGRESO;
            if (!re.test(valor)) {
                alert('Subcuenta no válida.');
                return;
            }
            // TODO Fase 4: POST a la ruta apropiada
        });
    }

    // ─── Bootstrap ──────────────────────────────────────────────────────────

    document.addEventListener('DOMContentLoaded', () => {
        inicializarConstructorFiltros();
        inicializarPreview();
        inicializarEdicionInline();
        actualizarSemaforo();
    });
})();
