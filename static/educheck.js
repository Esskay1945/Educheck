"use strict";

const byId = (id) => document.getElementById(id);
const documentText = byId("documentText");
const fileInput = byId("fileInput");
const dropzone = byId("dropzone");
const sentinelResults = byId("sentinelResults");
const copyResult = byId("copyResultBtn");
const revisionPanels = ["artisanOutputDisplay", "scoreDeltaSection", "artisanDetailsSection"];
let revision = 0;
let uploadSequence = 0;
let auditToken = null;
let editedText = "";
let toastTimer;

function showToast(message) {
    const toast = byId("toastMessage");
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 5000);
}

function selectTab(upload) {
    byId("tabTextBtn").classList.toggle("active", !upload);
    byId("tabUploadBtn").classList.toggle("active", upload);
    byId("textInputContainer").style.display = upload ? "none" : "block";
    byId("uploadContainer").style.display = upload ? "block" : "none";
}

byId("tabTextBtn").addEventListener("click", () => selectTab(false));
byId("tabUploadBtn").addEventListener("click", () => selectTab(true));

function documentChanged() {
    revision += 1;
    uploadSequence += 1;
    auditToken = null;
    editedText = "";
    const text = documentText.value.trim();
    const words = text ? text.split(/\s+/).length : 0;
    byId("wordCountLabel").textContent = words + " words | " + Array.from(text).length + " characters";
    sentinelResults.style.display = "none";
    copyResult.style.display = "none";
    for (const panel of revisionPanels) {
        byId(panel).style.display = "none";
    }
    byId("verificationStatus").hidden = true;
    byId("verificationSources").hidden = true;
    byId("artisanPlaceholder").style.display = "block";
}

documentText.addEventListener("input", documentChanged);
byId("clearTextBtn").addEventListener("click", () => {
    documentText.value = "";
    selectTab(false);
    documentChanged();
    documentText.focus();
    showToast("Document cleared.");
});

async function post(path, payload) {
    const options = {method: "POST", body: payload};
    if (!(payload instanceof FormData)) {
        options.headers = {"Content-Type": "application/json"};
        options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const isJson = response.headers.get("Content-Type")?.includes("application/json");
    const data = isJson ? await response.json() : {};
    if (!response.ok || !isJson) {
        throw new Error(data.error || "The request could not be completed.");
    }
    return data;
}

async function uploadFile(file) {
    const sequence = ++uploadSequence;
    const payload = new FormData();
    payload.append("file", file);
    showToast("Extracting " + file.name);
    try {
        const data = await post("/api/upload", payload);
        if (sequence !== uploadSequence) return;
        documentText.value = data.text;
        documentChanged();
        selectTab(false);
        const notes = [...data.warnings];
        if (data.ocr_pages) notes.unshift("OCR processed " + data.ocr_pages + " scanned pages.");
        showToast(["Extracted " + data.word_count + " words.", ...notes].join(" "));
    } catch (error) {
        if (sequence === uploadSequence) showToast(error.message);
    }
}

dropzone.addEventListener("click", (event) => {
    if (event.target !== fileInput) fileInput.click();
});
dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInput.click();
    }
});
fileInput.addEventListener("change", () => {
    if (fileInput.files.length) uploadFile(fileInput.files[0]);
    fileInput.value = "";
});
for (const target of [documentText, dropzone]) {
    target.addEventListener("dragover", (event) => {
        event.preventDefault();
        target.classList.add("dragover");
    });
    target.addEventListener("dragleave", () => target.classList.remove("dragover"));
    target.addEventListener("drop", (event) => {
        event.preventDefault();
        target.classList.remove("dragover");
        if (event.dataTransfer.files.length) uploadFile(event.dataTransfer.files[0]);
    });
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function renderSources(container, sources, emptyMessage) {
    container.replaceChildren();
    for (const source of sources) {
        let url;
        try {
            url = new URL(source.url);
        } catch {
            continue;
        }
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) continue;

        const item = element("a", "source-pill");
        item.href = url.href;
        item.target = "_blank";
        item.rel = "noopener noreferrer";
        const row = element("div", "source-pill-row");
        const title = element("div", "source-name", source.title || source.domain);
        title.title = title.textContent;
        const pct = Math.min(100, Math.max(0, Number(source.match_percentage) || 0));
        row.append(title, element("div", "source-pct", pct + "% match"));
        const bar = element("div", "source-bar-wrap");
        const fill = element("div", "source-bar-fill");
        fill.style.width = pct + "%";
        bar.append(fill);
        item.append(row, bar);
        container.append(item);
    }
    if (!container.childElementCount && emptyMessage) {
        container.append(element("p", "metric-sub", emptyMessage));
    }
}

function renderAnnotatedText(text, flags) {
    const characters = Array.from(text);
    const positions = new Array(characters.length);
    for (const flag of flags) {
        if (!Number.isInteger(flag.start) || !Number.isInteger(flag.end)) continue;
        if (flag.start < 0 || flag.end > characters.length || flag.end <= flag.start) continue;
        for (let index = flag.start; index < flag.end; index += 1) {
            const previous = positions[index];
            if (!previous || (flag.type === "plagiarism" && previous.type !== "plagiarism")) {
                positions[index] = flag;
            }
        }
    }

    const fragment = document.createDocumentFragment();
    for (let start = 0; start < characters.length;) {
        const flag = positions[start];
        let end = start + 1;
        while (end < characters.length && positions[end] === flag) end += 1;
        const excerpt = characters.slice(start, end).join("");
        if (!flag) {
            fragment.append(excerpt);
        } else {
            const mark = element("mark", flag.type === "plagiarism" ? "mark-plagiarism" : "mark-ai", excerpt);
            mark.title = flag.reason || "";
            fragment.append(mark);
        }
        start = end;
    }
    byId("annotatedTextDisplay").replaceChildren(fragment);
}

const styleLabels = {"provider": "Provider assessment", "partial": "Provider and local checks", "local": "Local checks"};
const coverageLabels = {"complete": "Web sources checked", "partial": "Partial coverage", "unavailable": "Unavailable"};

function formatScore(value, suffix) {
    return Number.isFinite(value) ? value + suffix : "Unavailable";
}

function renderSentinel(report, text) {
    const coverage = report.similarity_coverage;
    const style = report.ai_analysis;
    byId("metricSimilarity").textContent = formatScore(report.similarity_score, "%");
    byId("badgeSimVerdict").textContent = coverageLabels[coverage.status];
    byId("metricAI").textContent = formatScore(report.ai_score, "/100");
    byId("badgeAIVerdict").textContent = styleLabels[style.method];
    byId("auditCoverage").textContent = [
        coverage.message,
        "Excerpts searched: " + coverage.queries + ". Pages checked: " + coverage.checked + ".",
        style.warning,
    ].filter(Boolean).join(" ");

    const anomaliesList = byId("anomaliesList");
    anomaliesList.replaceChildren();
    byId("flagsCountBadge").textContent = report.flags_and_anomalies.length + " observations";
    for (const anomaly of report.flags_and_anomalies) {
        const item = element("div", "anomaly-item");
        const heading = element("div", "anomaly-item-header");
        heading.append(
            element("span", "anomaly-name", anomaly.title),
            element("span", "anomaly-badge", anomaly.badge || anomaly.category)
        );
        item.append(heading, element("div", "anomaly-desc", anomaly.description));
        anomaliesList.append(item);
    }
    if (!anomaliesList.childElementCount) {
        anomaliesList.append(element("p", "metric-sub", "No formatting or structure flags found."));
    }
    byId("sourceCountBadge").textContent = report.sources.length + " sources matched";
    const emptyMessage = coverage.status === "unavailable"
        ? "Source matches are unavailable."
        : "No matches found among the pages checked.";
    renderSources(byId("sourcesList"), report.sources, emptyMessage);
    renderAnnotatedText(text, report.flagged_segments);
    sentinelResults.style.display = "flex";
}

function renderArtisan(data) {
    editedText = data.humanized_text;
    byId("artisanPlaceholder").style.display = "none";
    byId("artisanOutputDisplay").textContent = editedText;
    byId("artisanOutputDisplay").style.display = "block";
    copyResult.style.display = "inline-block";
    byId("scoreDeltaSection").style.display = "block";
    const before = data.before_scores;
    const after = data.after_scores;
    byId("deltaPlagOld").textContent = formatScore(before.similarity_score, "%");
    byId("deltaPlagNew").textContent = formatScore(after.similarity_score, "%");
    byId("deltaAIOld").textContent = formatScore(before.ai_score, "/100");
    byId("deltaAINew").textContent = formatScore(after.ai_score, "/100");

    const status = [
        "Original: " + coverageLabels[before.similarity_coverage.status] +
            " (" + before.similarity_coverage.checked + " pages).",
        "Edited: " + coverageLabels[after.similarity_coverage.status] +
            " (" + after.similarity_coverage.checked + " pages).",
        "Style methods: " + styleLabels[before.ai_method] + " → " + styleLabels[after.ai_method] + ".",
        ...new Set([before.ai_warning, after.ai_warning, ...data.warnings].filter(Boolean)),
    ];
    byId("verificationStatus").textContent = status.join(" ");
    byId("verificationStatus").hidden = false;
    renderSources(byId("verificationSourcesList"), data.verification_sources);
    byId("verificationSources").hidden = !byId("verificationSourcesList").childElementCount;

    byId("artisanDetailsSection").style.display = "flex";
    const changes = data.changes_summary.length ? data.changes_summary : [data.improvements];
    byId("changesList").replaceChildren(...changes.map((change) => element("li", "", change)));
}

function registerAction(engine, path, runningLabel, render) {
    const button = byId(engine === "sentinel" ? "runSentinelBtn" : "runArtisanBtn");
    const spinner = byId(engine + "Spinner");
    const label = byId(engine + "BtnText");
    const idle = label.textContent;
    button.addEventListener("click", async () => {
        const text = documentText.value.trim();
        if (!text) {
            showToast("Enter or upload a document first.");
            return;
        }
        const startedWith = revision;
        const payload = {text};
        if (engine === "artisan" && auditToken) payload.audit_token = auditToken;
        button.disabled = true;
        spinner.style.display = "inline-block";
        label.textContent = runningLabel;
        try {
            const data = await post(path, payload);
            if (revision === startedWith) render(data, text);
        } catch (error) {
            if (revision === startedWith) showToast(error.message);
        } finally {
            button.disabled = false;
            spinner.style.display = "none";
            label.textContent = idle;
        }
    });
}

registerAction("sentinel", "/api/agent1/check", "Sentinel is checking the document…", (data, text) => {
    auditToken = data.audit_token;
    renderSentinel(data, text);
});
registerAction("artisan", "/api/agent2/humanize", "Artisan is editing and verifying…", renderArtisan);
copyResult.addEventListener("click", async () => {
    if (!editedText) return;
    try {
        await navigator.clipboard.writeText(editedText);
        showToast("Edited text copied.");
    } catch {
        showToast("Clipboard access is unavailable. Select and copy the edited text directly.");
    }
});
