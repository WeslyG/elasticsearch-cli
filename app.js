"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, cls = "", text = "") => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== null) node.textContent = text;
    return node;
};
const cache = new Map();
let index,
    renderToken = 0,
    currentRows = [],
    page = 1,
    detailToken = 0;
const params = new URLSearchParams(location.search);
const state = {
    v: params.get("v") || "",
    tab: params.get("tab") || "operations",
    q: params.get("q") || "",
    method: params.get("method") || "",
    status: params.get("status") || "",
    api: params.get("api") || "bulk",
    scope: params.has("scope") ? params.get("scope") : "target",
};
const labels = {
    partial: "Есть наблюдения",
    mismatch: "Есть расхождения",
    "not-tested": "Не проверено",
    passed: "Сценарий прошёл",
    failed: "Ожидание не совпало",
    blocked: "Заблокирован зависимостью",
    "infrastructure-error": "Ошибка транспорта / стенда",
    incomplete: "Проверка не завершена",
};
const fmt = (n) => new Intl.NumberFormat("ru-RU").format(n);
const semver = (a, b) => {
    const x = a.split(".").map(Number),
        y = b.split(".").map(Number);
    for (let i = 0; i < 3; i++) {
        if (x[i] !== y[i]) return x[i] - y[i];
    }
    return 0;
};
function badge(value, text) {
    return el("span", "badge " + value, text || labels[value] || value);
}
function method(value) {
    const node = el("span", "http", value);
    node.dataset.method = value;
    return node;
}
function toast(text) {
    $("toast").textContent = text;
    $("toast").classList.add("visible");
    setTimeout(() => $("toast").classList.remove("visible"), 2200);
}
async function getJSON(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok)
        throw new Error(
            "Не удалось загрузить " + url + " (" + response.status + ")",
        );
    return response.json();
}
function loadVersion(v) {
    if (!cache.has(v))
        cache.set(
            v,
            getJSON("data/versions/" + encodeURIComponent(v) + ".json").catch(
                (e) => {
                    cache.delete(v);
                    throw e;
                },
            ),
        );
    return cache.get(v);
}
async function pool(items, fn) {
    const result = new Array(items.length);
    let cursor = 0;
    await Promise.all(
        Array.from({ length: Math.min(4, items.length) }, async () => {
            while (cursor < items.length) {
                const i = cursor++;
                result[i] = await fn(items[i]);
            }
        }),
    );
    return result;
}
function saveURL() {
    const url = new URL(location.href);
    url.search = "";
    for (const [key, value] of Object.entries(state))
        if (value) url.searchParams.set(key, value);
    history.replaceState(null, "", url);
}
function option(select, value, text) {
    const node = el("option", "", text);
    node.value = value;
    select.append(node);
}
function syncControls() {
    $("version").value = state.v;
    $("query").value = state.q;
    $("method").value = state.method;
    $("scope").value = state.scope;
    $("compareApi").value = state.api;
    const old = state.status;
    $("status").replaceChildren();
    option($("status"), "", "Любое наблюдение");
    for (const value of state.tab === "scenarios"
        ? ["passed", "failed", "blocked", "infrastructure-error"]
        : ["partial", "mismatch", "not-tested"])
        option($("status"), value, labels[value]);
    state.status = [...$("status").options].some((o) => o.value === old)
        ? old
        : "";
    $("status").value = state.status;
    for (const button of document.querySelectorAll("[data-tab]"))
        button.setAttribute(
            "aria-pressed",
            String(button.dataset.tab === state.tab),
        );
    const methodPage = state.tab === "method",
        compare = state.tab === "compare",
        journal = state.tab === "journal" || state.tab === "findings";
    $("filters").hidden = methodPage;
    $("queryLabel").hidden = compare || journal;
    $("statusLabel").hidden = compare || journal;
    $("scopeLabel").hidden = compare || journal;
    $("methodLabel").hidden = journal;
    $("compareLabel").hidden = !compare;
    $("export").hidden = methodPage;
    for (const button of $("versions").children)
        button.classList.toggle("active", button.dataset.version === state.v);
}
function operationStatus(row) {
    const cases = state.method
        ? row.observations.filter((r) => r.method === state.method)
        : row.observations;
    return cases.some((r) => r.result === "failed")
        ? "mismatch"
        : cases.some((r) => r.executed !== false)
          ? "partial"
          : "not-tested";
}
function matching(row) {
    const scope = row.scope_category || "unknown";
    if (state.scope === "target" && ["excluded-xpack", "private", "example-metadata"].includes(scope)) return false;
    if (state.scope && state.scope !== "target" && state.scope !== scope) return false;
    const methods = row.routes
        ? [...new Set(row.routes.flatMap((r) => r.methods))]
        : [row.method];
    if (state.method && !methods.includes(state.method)) return false;
    const status = row.routes ? operationStatus(row) : row.result;
    if (state.status && state.status !== status) return false;
    const text = [
        row.api,
        row.scenario,
        row.path,
        ...(row.routes || []).map((r) => r.path),
        ...(row.params || []),
        ...Object.values(row.request_media_type_facts || {}).flat(),
    ]
        .join(" ")
        .toLowerCase();
    return !state.q || text.includes(state.q.toLowerCase());
}
function metric(value, title, note) {
    const node = el("div", "metric");
    node.append(
        el("strong", "", fmt(value)),
        el("span", "", title),
        el("small", "", note),
    );
    return node;
}
function metrics(payloads) {
    const cases = payloads.flatMap((p) => p.observations),
        done = payloads.filter((p) => p.state === "observed").length;
    $("metrics").replaceChildren(
        metric(
            done,
            "Релизов с наблюдениями",
            "из " + payloads.length + " выбранных",
        ),
        metric(
            cases.filter((r) => r.executed !== false).length,
            "Выполнений сценариев",
            "включая негативные и TLS",
        ),
        metric(
            cases.filter((r) => r.result === "passed").length,
            "Успешных сценариев",
            "не число поддержанных API",
        ),
        metric(
            cases.filter((r) => r.result === "failed").length,
            "Несовпадений ожиданий",
            "не автоматически ошибки ES",
        ),
    );
}
function table(headers) {
    const wrap = el("div", "table-wrap"),
        t = el("table"),
        head = el("thead"),
        tr = el("tr");
    for (const h of headers) {
        const th = el("th", "", h);
        th.scope = "col";
        tr.append(th);
    }
    head.append(tr);
    const body = el("tbody");
    t.append(head, body);
    wrap.append(t);
    return { wrap, body };
}
function td(tr, node, cls = "") {
    const cell = el("td", cls);
    if (node instanceof Node) cell.append(node);
    else cell.textContent = node;
    tr.append(cell);
    return cell;
}
function sourceURL(row) {
    return (
        "https://github.com/elastic/elasticsearch/blob/" +
        encodeURIComponent(row.source_commit) +
        "/" +
        row.source.split("/").map(encodeURIComponent).join("/")
    );
}
function external(url, text) {
    const a = el("a", "", text);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
}
function jsonBlock(parent, title, data) {
    parent.append(el("h3", "", title));
    const text =
        typeof data === "string" ? data : JSON.stringify(data, null, 2);
    const button = el("button", "quiet", "Скопировать");
    button.addEventListener("click", () => copy(text));
    parent.append(button, el("pre", "", text));
}
async function copy(text) {
    try {
        await navigator.clipboard.writeText(text);
        toast("Скопировано");
    } catch {
        toast("Буфер обмена недоступен в этом браузере");
    }
}
function showDialog(title) {
    detailToken++;
    const body = $("detailBody");
    body.replaceChildren(el("h2", "", title));
    if (!$("detail").open) $("detail").showModal();
    return body;
}
async function showCase(row) {
    const body = showDialog(row.scenario),
        token = detailToken;
    body.append(
        el(
            "p",
            "",
            "Версия " +
                row.version +
                " · " +
                (row.api || "TLS transport fixture"),
        ),
        badge(row.result),
    );
    if (row.in_source_catalogue === false)
        body.append(
            el(
                "p",
                "",
                "API ID не найден в собранном source-каталоге этой версии. HTTP-ответ не доказывает отсутствие или поддержку API.",
            ),
        );
    try {
        const raw = await getJSON(
            "data/raw/" +
                encodeURIComponent(row.version) +
                "/" +
                encodeURIComponent(row.file),
        );
        if (token !== detailToken || !$("detail").open) return;
        const record = raw.results[row.row_index];
        if (record.schema_version === 2) {
            body.append(el("p", "", row.purpose || ""));
            jsonBlock(body, "Реальный запрос (тело и байты сохранены явно)", record.request);
            jsonBlock(body, "Реальный ответ", record.response);
            jsonBlock(body, "Проверки ожиданий", record.assertions);
            if (raw.fixture_evidence) jsonBlock(body, "Независимая подготовка и проверка fixture", raw.fixture_evidence);
            jsonBlock(body, "Связи и происхождение", {
                scenario_id: record.scenario_id, run_id: record.run_id,
                depends_on: record.depends_on, verifies: record.verifies,
                blocked_by: record.blocked_by, reason: record.reason,
                dimensions: record.dimensions, elapsed_seconds: record.elapsed_seconds,
                timeouts: record.timeouts,
                source_jsonl_sha256: raw.source_jsonl_sha256, source_ref: raw.source_ref,
                fixture_context: raw.fixture_context, auxiliary_evidence_sha256: raw.auxiliary_evidence_sha256
            });
            for (const source of raw.code_sources || [])
                body.append(external(source.url, source.name + " · SHA-256 " + source.sha256));
            return;
        }
        if (record.method)
            jsonBlock(
                body,
                "Реальный запрос",
                record.method + " " + record.path,
            );
        if (record.fixture_adapter && record.fixture_adapter !== "none")
            body.append(
                el(
                    "p",
                    "",
                    "Fixture adapter: " +
                        record.fixture_adapter +
                        "; показан фактический wire path.",
                ),
            );
        jsonBlock(
            body,
            "Тело запроса",
            record.request_body ??
                "В этом прогоне тело запроса не сохранялось.",
        );
        if (record.headers)
            jsonBlock(body, "Сохранённые заголовки ответа", record.headers);
        jsonBlock(body, "Ответ / наблюдение", {
            expected_status: record.expected_status,
            status: record.status,
            response: record.response,
            error: record.error,
            verification_error: record.verification_error,
            elapsed_seconds: record.elapsed_seconds,
        });
        body.append(
            el(
                "p",
                "",
                row.file +
                    " · строка записи " +
                    (row.row_index + 1) +
                    " · данные fixture, не production-кластера",
            ),
        );
    } catch (error) {
        body.append(el("p", "", error.message));
    }
}
function scopeLabel(row) {
    return ({
        "public-core-source": "Public core: определение + регистрация в исходниках",
        "public-module-candidate": "Модуль: применимость требует проверки",
        "excluded-xpack": "X-Pack: вне целевого охвата",
        private: "Private: вне целевого охвата",
        "example-metadata": "Пример, не API кластера",
        unknown: "Область требует исследования",
    })[row.scope_category] || "Область требует исследования";
}
function showOperation(row) {
    const body = showDialog(row.api),
        meta = el("div", "dialog-meta");
    meta.append(
        badge(operationStatus(row)),
        el("span", "muted", row.version),
        badge(
            "",
            scopeLabel(row),
        ),
    );
    body.append(
        meta,
        el(
            "p",
            "",
            "Любое наблюдение здесь частичное: не все методы, пути, параметры и ошибки проверены.",
        ),
    );
    if (row.routes.some((r) => !r.path.startsWith("/")))
        body.append(
            el(
                "p",
                "",
                "В закреплённом source есть путь без начального /. Он показан дословно; применимость и нормализация ещё не проверены.",
            ),
        );
    for (const route of row.routes) {
        const line = el("div");
        for (const m of route.methods) line.append(method(m));
        line.append(el("code", "route", route.path));
        body.append(line);
    }
    const compatibilityMedia = [...new Set(Object.values(row.request_media_type_facts || {}).flat()
        .filter(value => value.includes("compatible-with=")))];
    if (compatibilityMedia.length)
        body.append(el("p", "", "В исходнике этот API объявлен для REST compatibility media: " +
            compatibilityMedia.join(", ") + ". Доступность в default режиме из этого не следует."));
    jsonBlock(body, "Параметры из исходников (не все проверены)", {
        query_parameters: row.params,
        path_parameters: [...new Set(row.routes.flatMap((r) => r.parts || []))],
        body_encoding_hint: row.body_encoding_hint,
        request_media_types: row.request_media_type_facts || {},
    });
    const sourceFacts = el("details", "source-facts");
    sourceFacts.append(el("summary", "", "Исходники и открытые проверки"));
    jsonBlock(sourceFacts, "Типы, значения и основание классификации (только исходники)", {
        scope: row.scope_category, basis: row.scope_basis,
        path_normalization_evidence: row.path_normalization_evidence,
        parameters: row.parameter_facts,
        additional_parameters_from_pinned_handlers: row.query_parameter_source_facts,
        open_dimensions: row.required_dimension_facts,
        note: "Наличие параметра в определении не подтверждает его семантику в живом кластере."
    });
    body.append(sourceFacts);
    body.append(
        external(
            sourceURL(row),
            "Определение в закреплённом исходниках upstream ↗",
        ),
    );
    body.append(el("h3", "", "Наблюдения (" + row.observations.length + ")"));
    const list = el("div", "case-list");
    for (const observation of row.observations) {
        const b = el(
            "button",
            "",
            observation.scenario +
                " · " +
                (observation.method || "TLS") +
                " " +
                (observation.status ?? "") +
                " · " +
                (labels[observation.result] || observation.result) +
                (observation.run_id ? " · " + observation.run_id : " · v1"),
        );
        b.addEventListener("click", () => showCase(observation));
        list.append(b);
    }
    if (!row.observations.length)
        list.append(
            el("p", "", "Живых сценариев для этого API ID не записано."),
        );
    body.append(list);
}
function renderTable(rows) {
    currentRows = rows;
    const start = (page - 1) * 50,
        visible = rows.slice(start, start + 50),
        isCases = state.tab === "scenarios";
    const { wrap, body } = table(
        isCases
            ? [
                  "Сценарий / API",
                  "Версия",
                  "Запрос",
                  "Ожидалось → ответ",
                  "Наблюдение",
              ]
            : [
                  "Операция",
                  "Версия",
                  "Методы / пути из исходников",
                  "Сценариев",
                  "Статус",
              ],
    );
    for (const row of visible) {
        const tr = el("tr"),
            name = el("div"),
            button = el(
                "button",
                "row-button",
                isCases ? row.scenario : row.api,
            );
        button.addEventListener("click", () =>
            isCases ? showCase(row) : showOperation(row),
        );
        name.append(button);
        if (isCases)
            name.append(el("small", "", row.api || "TLS proxy fixture"));
        else
            name.append(
                el(
                    "small",
                    "",
                    scopeLabel(row),
                ),
            );
        if (row.in_source_catalogue === false)
            name.append(el("small", "", "вне каталога исходников"));
        td(tr, name);
        td(tr, row.version, "version-cell");
        const routes = el("div", "route");
        if (isCases) {
            if (row.method) routes.append(method(row.method));
            routes.append(el("span", "", row.executed === false ? "HTTP не отправлялся · план: " + row.planned_path : row.path || "Локальная TLS fixture"));
        } else {
            const methods = [...new Set(row.routes.flatMap((r) => r.methods))];
            for (const m of methods) routes.append(method(m));
            for (const r of row.routes.slice(0, 2))
                routes.append(el("div", "", r.path));
            if (row.routes.length > 2)
                routes.append(
                    el(
                        "small",
                        "",
                        "ещё " + (row.routes.length - 2) + " маршрутов",
                    ),
                );
        }
        td(tr, routes);
        td(
            tr,
            isCases
                ? (row.expected_status ?? "—") + " → " + (row.status ?? (row.executed === false ? "не отправлен" : "TLS"))
                : String(
                      (state.method
                          ? row.observations.filter(
                                (r) => r.method === state.method,
                            )
                          : row.observations
                      ).length,
                  ),
        );
        td(tr, badge(isCases ? row.result : operationStatus(row)));
        body.append(tr);
    }
    $("results").replaceChildren(wrap);
    $("pagination").replaceChildren();
    const pages = Math.max(1, Math.ceil(rows.length / 50));
    const previous = el("button", "quiet", "← Назад"),
        next = el("button", "quiet", "Далее →");
    previous.disabled = page <= 1;
    next.disabled = page >= pages;
    previous.onclick = () => {
        page--;
        renderTable(rows);
    };
    next.onclick = () => {
        page++;
        renderTable(rows);
    };
    $("pagination").append(
        previous,
        el("span", "", page + " / " + pages),
        next,
    );
}
function methodology() {
    const article = el("article", "methodology");
    const sections = [
        ["Граница старой статической проверки", "Старый извлекатель Java-маршрутов (до версии 3) мог принимать строковый префикс выражения за полный путь. Поэтому старые совпадения обработчиков и списки кандидатов не подтверждают область API. Сохранённые HTTP-запросы и ответы от этого не меняются. Новая классификация опирается на строгий разбор, visibility и регистрацию; неизвестное остаётся неизвестным."],
        ["Новые проверки v2", "Записываются отдельные ожидания, точные байты, зависимости и независимое чтение результата. Ошибка стенда без HTTP не становится проверкой API; заблокированная зависимость не считается выполнением. Ссылка на код сценария закреплена SHA-256."],
        [
            "Что здесь считается доказательством",
            "Каталог исходников описывает объявленные маршруты и параметры. Literal match с Java handler указывает на исходник реализации, но не подтверждает публичность или лицензионную доступность. Живой сценарий фиксирует конкретный запрос, ответ и assertions на конкретном релизе.",
        ],
        [
            "Как читать статусы",
            "«Сценарий прошёл» означает совпадение с ожиданием, включая корректный отказ. «Есть наблюдения» у операции означает только частичную проверку. HTTP 200 может содержать ошибки bulk, а 404 не обязательно означает отсутствие API. Полного покрытия ни у одного релиза не заявлено.",
        ],
        [
            "Версии и применимость",
            "Матрица выбирает последний stable patch каждого minor и отдельный 6.0.0 anchor. Это не все patch-релизы. Если источник или прогон ещё не получены, версия явно помечена. Пропуски fixture не считаются успешными запросами.",
        ],
        [
            "Границы TLS-проверок",
            "TLS-сценарии используют stdlib Linux и локальный HTTPS proxy к настоящему Elasticsearch. Они не подтверждают native ES TLS, macOS, mTLS или поведение будущей библиотеки.",
        ],
        [
            "Что ещё предстоит сделать",
            "Полная классификация core/X-Pack/private/plugins, все варианты путей и параметров, fault injection, auth/mTLS, целевые Python/ОС, установленное ядро и CLI. Каждый релиз сохраняет gaps.",
        ],
        [
            "Технологии и приватность",
            "Статические HTML, CSS и JavaScript. Данные загружаются с того же хоста; внешние CDN, аналитика и обращения к Elasticsearch отсутствуют. Весь поиск и экспорт выполняются в браузере. Исторические request bodies могут отсутствовать — интерфейс их не придумывает.",
        ],
    ];
    for (const [title, text] of sections)
        article.append(el("h3", "", title), el("p", "", text));
    $("results").replaceChildren(article);
    $("pagination").replaceChildren();
    $("resultCount").textContent = "Методика и границы утверждений";
    currentRows = [];
}
function renderComparison(payloads) {
    const { wrap, body } = table([
        "Версия",
        "Каталог исходников",
        "Методы / пути",
        "Живых наблюдений",
        "Состояние",
    ]);
    const rows = [];
    for (const p of payloads) {
        const op = p.operations.find((r) => r.api === state.api),
            cases = p.observations.filter((r) => r.api === state.api);
        if (
            state.method &&
            op &&
            !op.routes.some((r) => r.methods.includes(state.method))
        )
            continue;
        const tr = el("tr");
        td(tr, p.version, "version-cell");
        td(
            tr,
            op
                ? "Определение найдено"
                : p.state === "not-started"
                  ? "Источник не собран"
                  : "Не найдено в каталоге",
        );
        const route = el("div", "route");
        if (op)
            for (const r of op.routes) {
                for (const m of r.methods) route.append(method(m));
                route.append(el("div", "", r.path));
            }
        td(tr, route);
        const button = el("button", "row-button", String(cases.length));
        if (op) button.onclick = () => showOperation(op);
        else if (cases.length) button.onclick = () => showCase(cases[0]);
        td(tr, button);
        td(
            tr,
            badge(
                op ? operationStatus(op) : "not-tested",
                op
                    ? labels[operationStatus(op)]
                    : "Нет утверждения о поддержке",
            ),
        );
        body.append(tr);
        rows.push({
            version: p.version,
            api: state.api,
            source_defined: Boolean(op),
            observations: cases.length,
        });
    }
    $("results").replaceChildren(wrap);
    $("pagination").replaceChildren();
    $("resultCount").textContent =
        state.api +
        " · " +
        rows.length +
        " версий · отсутствие в каталоге ≠ отсутствие endpoint";
    currentRows = rows;
}

function readableMarkdown(text) {
    const article = el("article", "methodology");
    const lines = text.split("\n");
    const clean = (value) =>
        value.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/\*\*|`/g, "");
    let paragraph = [];
    const flush = () => {
        if (paragraph.length)
            article.append(el("p", "", clean(paragraph.join(" "))));
        paragraph = [];
    };
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) {
            flush();
            continue;
        }
        if (line.startsWith("#")) {
            flush();
            article.append(
                el(
                    line.startsWith("# ") ? "h2" : "h3",
                    "",
                    clean(line.replace(/^#+\s*/, "")),
                ),
            );
            continue;
        }
        if (
            line.startsWith("|") &&
            lines[i + 1]?.trim().match(/^\|[\s:|\-]+\|$/)
        ) {
            flush();
            const cells = (value) =>
                value
                    .split("|")
                    .slice(1, -1)
                    .map((v) => clean(v.trim()));
            const { wrap, body } = table(cells(line));
            i++;
            while (lines[i + 1]?.trim().startsWith("|")) {
                const tr = el("tr");
                for (const value of cells(lines[++i])) td(tr, value);
                body.append(tr);
            }
            article.append(wrap);
            continue;
        }
        if (line.startsWith("- ")) {
            flush();
            const list = el("ul");
            do {
                let value = lines[i].trim().slice(2);
                while (
                    lines[i + 1]?.trim() &&
                    !lines[i + 1].trim().startsWith("- ") &&
                    !lines[i + 1].trim().startsWith("#")
                )
                    value += " " + lines[++i].trim();
                list.append(el("li", "", clean(value)));
                i++;
            } while (lines[i]?.trim().startsWith("- "));
            i--;
            article.append(list);
            continue;
        }
        paragraph.push(line);
    }
    flush();
    return article;
}
async function renderFindings() {
    const token = renderToken;
    try {
        const data = await getJSON("data/findings.json");
        if (token !== renderToken) return;
        const key = state.v === "all" ? "all" : state.v.split(".")[0];
        $("results").replaceChildren(readableMarkdown(data[key]));
        $("pagination").replaceChildren();
        $("resultCount").textContent =
            "Выводы · " +
            (key === "all" ? "сводный отчёт" : key + ".x") +
            " · ограничения сохранены";
        currentRows = [{ version: state.v, findings: data[key] }];
    } catch (error) {
        if (token === renderToken)
            $("results").replaceChildren(el("p", "empty", error.message));
    }
}

async function showNativeTLS(run) {
    const body = showDialog("Native TLS · " + run.name), token = detailToken;
    body.append(el("p", "", "Транспортные проверки на настоящем HTTPS Elasticsearch. TLS-отказы не увеличивают REST-покрытие. Кластеры были временными; доверие менялось только внутри девконтейнера."));
    try {
        const raw = await getJSON(run.file);
        if (token !== detailToken || !$("detail").open) return;
        jsonBlock(body, "Сводка и среда", raw.summary);
        const list = el("div", "case-list");
        for (const record of raw.records) {
            const outcome = record.response.status === null ? "TLS отказ" : "HTTP " + record.response.status;
            const button = el("button", "", record.case_id + " · " + outcome + " · " + record.state);
            button.onclick = () => {
                const detail = showDialog(record.case_id);
                detail.append(el("p", "", "Это исследование транспорта, а не проверка установленного core/CLI. Пути CA относятся к временному контейнеру; закрытые ключи и пароли не публикуются."));
                jsonBlock(detail, "Ожидания и проверки", record.assertions);
                jsonBlock(detail, "Запрос и SSL режим", record.request);
                jsonBlock(detail, "Ответ и TLS ошибка", {response: record.response, transport_error: record.transport_error, elapsed_seconds: record.elapsed_seconds});
                if (record.response.body_base64) {
                    const bytes = Uint8Array.from(atob(record.response.body_base64), c => c.charCodeAt(0));
                    const decoded = new TextDecoder().decode(bytes);
                    let value;
                    try { value = JSON.parse(decoded); } catch { value = decoded; }
                    jsonBlock(detail, "Расшифрованное тело HTTP-ответа", value);
                }
                jsonBlock(detail, "Публичный сертификат (ключ удалён)", raw.certificates[record.mode]);
                for (const source of raw.code_sources)
                    detail.append(external(source.url, source.name + " · SHA-256 " + source.sha256));
            };
            list.append(button);
        }
        body.append(list);
    } catch (error) {
        if (token === detailToken) body.append(el("p", "", error.message));
    }
}

async function showFaults(run) {
    const body = showDialog("Сетевые отказы · " + run.name), token = detailToken;
    body.append(el("p", "", "Контролируемый прокси внутри worker и настоящий Elasticsearch. Ожидаемая ошибка клиентского запроса может быть успешной проверкой отказа. Эти проверки не увеличивают API-покрытие и не проверяют установленное ядро/CLI."));
    try {
        const raw = await getJSON(run.file);
        if (token !== detailToken || !$("detail").open) return;
        jsonBlock(body, "Сводка и ограничения", raw.summary);
        const names = {"drop-write":"Запись завершена, ответ потерян", "socket-timeout":"Тайм-аут после записи",
            "wall-deadline":"Общий deadline после записи", "short-length":"Обрыв тела с Content-Length",
            "short-chunked":"Обрыв chunked тела", "response-limit":"Ограничение размера ответа",
            "delayed-read":"Медленный ответ в допустимом интервале", "redirect":"Без скрытого redirect",
            "connect-refused":"Отказ соединения"};
        const list = el("div", "case-list");
        for (const record of raw.records) {
            const b = el("button", "", (names[record.case_id] || record.case_id) + " · " + record.state);
            b.onclick = () => {
                const detail = showDialog(names[record.case_id] || record.case_id);
                jsonBlock(detail, "Проверки контракта", record.assertions);
                jsonBlock(detail, "Фактический клиентский запрос и исход",
                    raw.sessions[record.sample.session].find(row => row.scenario_id === record.sample.scenario_id));
                if (record.resolution)
                    jsonBlock(detail, "Независимая проверка на настоящем ES",
                        raw.sessions[record.resolution.session].find(row => row.scenario_id === record.resolution.scenario_id));
                jsonBlock(detail, "Что получил и переслал контролируемый прокси",
                    raw.proxy_events.filter(row => row.path === "/" + record.case_id));
                for (const source of raw.code_sources)
                    detail.append(external(source.url, source.name + " · SHA-256 " + source.sha256));
            };
            list.append(b);
        }
        body.append(list);
    } catch (error) {
        if (token === detailToken) body.append(el("p", "", error.message));
    }
}

function renderJournal(payloads) {
    const article = el("article", "methodology");
    for (const p of payloads) {
        article.append(el("h3", "", p.version + " · " + p.state));
        const m = p.manifest;
        article.append(
            el(
                "p",
                "",
                m
                    ? String(p.observations.filter(r => r.executed !== false).length) +
                          " выполнений; " + p.observations.filter(r => r.executed === false).length + " заблокированных записей. Базовый outcome: " +
                          m.outcome +
                          ". Контракты остаются неполными."
                    : "Законченного прогона в этом snapshot нет.",
            ),
        );
        if (m) {
            article.append(
                el("p", "", "Незакрыто в базовом v1-манифесте: " + (m.remaining || []).join("; ")),
            );
            const stages = el("ul");
            for (const row of m.stage_outcomes || [])
                stages.append(
                    el(
                        "li",
                        "",
                        row.stage +
                            " · exit " +
                            row.exit_code +
                            " · evidence " +
                            (row.evidence_copied ? "сохранено" : "не получено"),
                    ),
                );
            article.append(stages);
            const b = el(
                "button",
                "quiet",
                "Манифест, digest, хеши инструментов и учёт диска",
            );
            b.onclick = () =>
                jsonBlock(
                    showDialog(p.version + " · provenance"),
                    "Манифест",
                    m,
                );
            article.append(b);
        }
        for (const run of p.transport_runs || []) {
            const policy = run.summary.auth_policy === "required-basic" ? "обязательная Basic auth" : "без auth и Basic";
            const b = el("button", "quiet", "Native TLS" + (run.summary.suite === "mtls-validity" ? " · mTLS / сроки сертификатов" : "") + " · " + policy + " · " + run.summary.probes + " проверок · отдельно от REST");
            b.onclick = () => showNativeTLS(run);
            article.append(b);
        }
        for (const run of p.fault_runs || []) {
            const b = el("button", "quiet", "Сетевые отказы · " + run.summary.probes + " проверок · отдельно от REST");
            b.onclick = () => showFaults(run);
            article.append(b);
        }
        for (const [title, data] of [
            ["Подготовка transport: ошибки стенда", p.transport_setup_failures],
            ["Пропуски fixture (не тесты)", p.applicability],
            ["Попытки и история", p.attempts],
            ["Неразобранные literal route candidates", p.route_candidates],
        ]) {
            if (!data?.length) continue;
            const b = el("button", "quiet", title + " · " + data.length);
            b.onclick = () =>
                jsonBlock(showDialog(p.version + " · " + title), title, data);
            article.append(b);
        }
    }
    $("results").replaceChildren(article);
    $("pagination").replaceChildren();
    $("resultCount").textContent =
        payloads.length + " журналов · evidence отдельно от готовности";
    currentRows = payloads.map((p) => ({
        version: p.version,
        manifest: p.manifest,
        attempts: p.attempts,
        transport_runs: p.transport_runs,
        fault_runs: p.fault_runs,
        transport_setup_failures: p.transport_setup_failures,
        applicability: p.applicability,
        route_candidates: p.route_candidates,
    }));
}

async function render() {
    const token = ++renderToken;
    syncControls();
    saveURL();
    $("pagination").replaceChildren();
    if (state.tab === "method") {
        methodology();
        return;
    }
    $("results").replaceChildren(
        el("div", "loading", "Загрузка выбранных снимков…"),
    );
    try {
        const versions =
            state.v === "all"
                ? index.versions.map((r) => r.version)
                : [state.v];
        const payloads = await pool(versions, loadVersion);
        if (token !== renderToken) return;
        metrics(payloads);
        if (state.tab === "compare") {
            renderComparison(payloads);
            return;
        }
        if (state.tab === "findings") {
            await renderFindings();
            return;
        }
        if (state.tab === "journal") {
            renderJournal(payloads);
            return;
        }
        const rows = payloads
            .flatMap((p) =>
                state.tab === "scenarios" ? p.observations : p.operations,
            )
            .filter(matching);
        const stageFailures = payloads.flatMap((p) => p.stage_failures || []);
        $("resultCount").textContent =
            fmt(rows.length) +
            " записей" +
            (stageFailures.length
                ? " · есть незавершённые этапы fixture"
                : "") +
            " · покрытие API неполное";
        if (!rows.length) {
            const box = el("div", "empty");
            box.append(
                el("strong", "", "Нет записей для этой выборки"),
                el(
                    "p",
                    "",
                    payloads.every((p) => p.state !== "observed")
                        ? "Прогон ещё не записан. Данные из исходников не являются live-проверкой."
                        : "Попробуй другой API, метод или статус. Отсутствие записи не означает отсутствие API.",
                ),
            );
            $("results").replaceChildren(box);
            currentRows = [];
            return;
        }
        renderTable(rows);
    } catch (error) {
        if (token === renderToken) {
            $("results").replaceChildren(
                el(
                    "div",
                    "empty",
                    error.message +
                        " · Перезагрузи страницу или проверь статические файлы.",
                ),
            );
            $("resultCount").textContent = "Не удалось получить данные";
        }
    }
}
function change() {
    page = 1;
    render();
}
function download() {
    const blob = new Blob(
        [
            JSON.stringify(
                {
                    claim: "partial observations, not full API coverage",
                    filters: state,
                    rows: currentRows,
                },
                null,
                2,
            ),
        ],
        { type: "application/json" },
    );
    const url = URL.createObjectURL(blob),
        a = el("a");
    a.href = url;
    a.download = "elasticsearch-contracts.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function init() {
    try {
        index = await getJSON("data/index.json");
        if (
            !index.versions.some((r) => r.version === state.v) &&
            state.v !== "all"
        )
            state.v =
                [...index.versions]
                    .reverse()
                    .find((r) => r.state === "observed")?.version ||
                index.versions[0].version;
        if (
            ![
                "operations",
                "scenarios",
                "compare",
                "journal",
                "findings",
                "method",
            ].includes(state.tab)
        )
            state.tab = "operations";
        $("buildDate").textContent =
            "Сборка страницы: " +
            new Date(index.built_at).toLocaleString("ru-RU");
        option($("version"), "all", "Все версии");
        for (const major of [9, 8, 7, 6]) {
            const group = el("optgroup");
            group.label = major + ".x";
            for (const row of index.versions
                .filter((r) => r.version.startsWith(major + "."))
                .reverse()) {
                option(
                    group,
                    row.version,
                    row.version +
                        (row.state === "observed" ? "" : " · нет прогона"),
                );
            }
            $("version").append(group);
        }
        for (const api of index.api_ids) option($("compareApi"), api, api);
        if (!index.api_ids.includes(state.api)) state.api = "info";
        $("matrixCount").textContent =
            index.versions.filter((r) => r.state === "observed").length +
            " / " +
            index.versions.length +
            " с наблюдениями";
        for (const row of index.versions) {
            const b = el("button", "version-card");
            b.dataset.version = row.version;
            b.append(
                el("strong", "", row.version),
                el(
                    "small",
                    "",
                    row.state === "observed"
                        ? row.records + " сценариев · gaps"
                        : row.state === "source-only"
                          ? "исходники без прогона"
                          : "прогон не записан",
                ),
            );
            b.onclick = () => {
                state.v = row.version;
                change();
            };
            $("versions").append(b);
        }
        for (const button of document.querySelectorAll("[data-tab]"))
            button.onclick = () => {
                state.tab = button.dataset.tab;
                change();
            };
        $("version").onchange = (e) => {
            state.v = e.target.value;
            change();
        };
        $("method").onchange = (e) => {
            state.method = e.target.value;
            change();
        };
        $("scope").onchange = (e) => { state.scope = e.target.value; change(); };
        $("status").onchange = (e) => {
            state.status = e.target.value;
            change();
        };
        $("compareApi").onchange = (e) => {
            state.api = e.target.value;
            change();
        };
        let timer;
        $("query").oninput = (e) => {
            clearTimeout(timer);
            state.q = e.target.value;
            timer = setTimeout(change, 150);
        };
        $("reset").onclick = () => {
            state.q = "";
            state.method = "";
            state.status = "";
            state.scope = "target";
            change();
        };
        $("share").onclick = () => copy(location.href);
        $("export").onclick = download;
        $("closeDetail").onclick = () => $("detail").close();
        $("detail").addEventListener("close", () => {
            detailToken++;
        });
        document.addEventListener("keydown", (e) => {
            if (
                e.key === "/" &&
                !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) &&
                !$("queryLabel").hidden
            ) {
                e.preventDefault();
                $("query").focus();
            }
        });
        await render();
    } catch (error) {
        $("results").replaceChildren(
            el(
                "div",
                "empty",
                error.message +
                    " · Странице нужен статический HTTP-хостинг; file:// не поддерживает загрузку JSON.",
            ),
        );
        $("resultCount").textContent = "Ошибка загрузки снимка";
    }
}
init();
