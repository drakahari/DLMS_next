/* Known instants only. SQLite UTC is opt-in; date-only values stay calendar dates. */
(() => {
    "use strict";
    const zoned = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;
    const sqlite = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;
    function format(value, {sqliteUTC = false} = {}) {
        const raw = String(value || "").trim();
        if (!raw) return "Time unavailable";
        const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw);
        const instant = sqliteUTC && sqlite.test(raw) ? raw.replace(" ", "T") + "Z" : raw;
        if (!dateOnly && !zoned.test(instant)) return `${raw} (timezone unknown)`;
        const parts = instant.slice(0, 10).split("-").map(Number);
        const calendar = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
        if (calendar.getUTCFullYear() !== parts[0] || calendar.getUTCMonth() !== parts[1] - 1 || calendar.getUTCDate() !== parts[2]) return "Time unavailable (invalid timestamp)";
        if (dateOnly) return `${raw} (date only)`;
        // Date accepts 24:00 as the next day; storage requires a real instant's
        // ordinary clock fields, matching the server's strict parser.
        if (Number(instant.slice(11, 13)) > 23 || Number(instant.slice(14, 16)) > 59 || Number(instant.slice(17, 19)) > 59) return "Time unavailable (invalid timestamp)";
        const date = new Date(instant);
        if (!Number.isFinite(date.getTime())) return "Time unavailable (invalid timestamp)";
        return date.toLocaleString(undefined, {year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"});
    }
    window.DLMSLocalTime = {format};
    function render() {
        document.querySelectorAll("[data-local-instant]").forEach(node => {
            node.textContent = format(node.dataset.localInstant, {sqliteUTC: node.dataset.sqliteUtc === "true"});
        });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
    else render();
})();
