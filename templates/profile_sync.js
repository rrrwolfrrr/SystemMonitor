// Profile Sync Functions
const SERVER_PROFILE_ENABLED = true;

let fullProfilePushTimer = null;
let suppressProfilePush = false;

const PROFILE_SYNC_KEYS = [
    "systemMonitorDashboard.v2",
    "systemMonitorDashboardLayout.v2",
    "systemMonitorThemes.v1",
    "systemMonitorDashboardPresets.v1",
    "systemMonitorActiveTheme.v1"
];

const originalStorageSetItem = Storage.prototype.setItem;

Storage.prototype.setItem = function (key, value) {
    originalStorageSetItem.call(this, key, value);

    if (!suppressProfilePush && PROFILE_SYNC_KEYS.includes(key)) {
        scheduleFullProfilePush();
    }
};

function withSuppressProfilePush(fn) {
    suppressProfilePush = true;

    try {
        fn();
    } finally {
        suppressProfilePush = false;
    }
}

function normalizeFullProfileState(raw) {
    const result = {
        interval: 2000,
        dark: false,
        cards: {
            cpu: true,
            gpu: true,
            ram: true,
            network: true,
            disks: true,
            fans: true,
            motherboard: true,
            system: true,
            other: false
        },
        customCards: [],
        cardConfig: {},
        snap: {
            enabled: true,
            size: 20
        }
    };

    if (!raw || typeof raw !== "object") {
        return result;
    }

    const allowedIntervals = [1000, 2000, 5000, 10000, 30000, 60000];
    const interval = Number(raw.interval);

    if (allowedIntervals.includes(interval)) {
        result.interval = interval;
    }

    if (typeof raw.dark === "boolean") {
        result.dark = raw.dark;
    }

    if (raw.cards && typeof raw.cards === "object") {
        const cardTypes = ["cpu", "gpu", "ram", "network", "disks", "fans", "motherboard", "system", "other"];
        cardTypes.forEach(function (type) {
            if (typeof raw.cards[type] === "boolean") {
                result.cards[type] = raw.cards[type];
            }
        });
    }

    if (Array.isArray(raw.customCards)) {
        result.customCards = raw.customCards
            .filter(function (card) {
                return card &&
                    typeof card.id === "string" &&
                    /^[A-Za-z0-9_-]+$/.test(card.id) &&
                    typeof card.name === "string" &&
                    Array.isArray(card.sensors);
            })
            .map(function (card) {
                return {
                    id: card.id,
                    name: String(card.name).slice(0, 80),
                    sensors: card.sensors.filter(function (key) {
                        return typeof key === "string";
                    })
                };
            });
    }

    if (raw.cardConfig && typeof raw.cardConfig === "object") {
        const cfg = {};

        Object.keys(raw.cardConfig).forEach(function (cardId) {
            const item = raw.cardConfig[cardId];

            if (!item || typeof item !== "object") {
                return;
            }

            const hidden = Array.isArray(item.hidden)
                ? item.hidden.filter(function (key) {
                    return typeof key === "string";
                })
                : [];

            const labels = {};

            if (item.labels && typeof item.labels === "object") {
                Object.keys(item.labels).forEach(function (key) {
                    const value = item.labels[key];

                    if (typeof key === "string" && typeof value === "string" && value.trim()) {
                        labels[key] = value.trim().slice(0, 120);
                    }
                });
            }

            cfg[cardId] = {
                hidden: hidden,
                labels: labels
            };
        });

        result.cardConfig = cfg;
    }

    if (raw.snap && typeof raw.snap === "object") {
        if (typeof raw.snap.enabled === "boolean") {
            result.snap.enabled = raw.snap.enabled;
        }

        const size = Number(raw.snap.size);
        if ([10, 20, 40, 80].includes(size)) {
            result.snap.size = size;
        }
    }

    return result;
}

function normalizeFullProfileLayout(raw) {
    const result = {};

    if (!raw || typeof raw !== "object") {
        return result;
    }

    Object.keys(raw).forEach(function (key) {
        const pos = raw[key];

        if (!pos || typeof pos !== "object") {
            return;
        }

        const left = Number(pos.left);
        const top = Number(pos.top);
        const width = Number(pos.width);
        const height = Number(pos.height);
        const z = Number(pos.z);

        if (
            Number.isFinite(left) &&
            Number.isFinite(top) &&
            Number.isFinite(width) &&
            Number.isFinite(height)
        ) {
            result[key] = {
                left: Math.max(0, Math.round(left)),
                top: Math.max(0, Math.round(top)),
                width: Math.max(100, Math.round(width)),
                height: Math.max(80, Math.round(height)),
                z: Number.isFinite(z) ? Math.max(1, Math.round(z)) : 1
            };
        }
    });

    return result;
}

function buildFullProfilePayload() {
    const state = JSON.parse(localStorage.getItem("systemMonitorDashboard.v2") || "{}");
    const layout = JSON.parse(localStorage.getItem("systemMonitorDashboardLayout.v2") || "{}");
    const themes = JSON.parse(localStorage.getItem("systemMonitorThemes.v1") || "{}");
    const presets = JSON.parse(localStorage.getItem("systemMonitorDashboardPresets.v1") || "{}");
    const activeThemeId = localStorage.getItem("systemMonitorActiveTheme.v1") || "builtin-classic";

    return {
        schemaVersion: 1,
        activeThemeId: activeThemeId,
        themes: Object.values(themes),
        presets: Object.values(presets),
        dashboard: {
            interval: state.interval || 2000,
            dark: state.dark || false,
            cards: state.cards || {
                cpu: true,
                gpu: true,
                ram: true,
                network: true,
                disks: true,
                fans: true,
                motherboard: true,
                system: true,
                other: false
            },
            customCards: state.customCards || [],
            cardConfig: state.cardConfig || {},
            snap: state.snap || { enabled: true, size: 20 },
            layout: layout
        }
    };
}

function pushFullProfileToServer() {
    if (!SERVER_PROFILE_ENABLED) {
        return;
    }

    const payload = buildFullProfilePayload();

    fetch("/api/profile", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    }).catch(function (err) {
        console.warn("Не удалось отправить профиль на сервер:", err);
    });
}

function scheduleFullProfilePush() {
    if (!SERVER_PROFILE_ENABLED) {
        return;
    }

    if (fullProfilePushTimer) {
        clearTimeout(fullProfilePushTimer);
    }

    fullProfilePushTimer = setTimeout(function () {
        pushFullProfileToServer();
    }, 800);
}

function hasLocalProfileData() {
    try {
        return !!localStorage.getItem("systemMonitorDashboard.v2") ||
            !!localStorage.getItem("systemMonitorDashboardLayout.v2") ||
            !!localStorage.getItem("systemMonitorThemes.v1") ||
            !!localStorage.getItem("systemMonitorDashboardPresets.v1") ||
            !!localStorage.getItem("systemMonitorActiveTheme.v1") ||
            Object.keys(JSON.parse(localStorage.getItem("systemMonitorThemes.v1") || "{}")).length > 0 ||
            Object.keys(JSON.parse(localStorage.getItem("systemMonitorDashboardPresets.v1") || "{}")).length > 0;
    } catch (err) {
        return false;
    }
}

async function loadFullProfileFromServer() {
    if (!SERVER_PROFILE_ENABLED) {
        return;
    }

    try {
        const response = await fetch("/api/profile", {
            cache: "no-store"
        });

        if (!response.ok) {
            return;
        }

        const profile = await response.json();

        if (!profile || typeof profile !== "object") {
            return;
        }

        const hasServerProfile = profile.exists === true;

        withSuppressProfilePush(function () {
            if (Array.isArray(profile.themes)) {
                const themes = {};

                profile.themes.forEach(function (rawTheme) {
                    if (!rawTheme || typeof rawTheme !== "object") {
                        return;
                    }

                    if (rawTheme.builtin) {
                        return;
                    }

                    const normalized = normalizeThemeObject(rawTheme);

                    if (normalized) {
                        themes[normalized.id] = normalized;
                    }
                });

                localStorage.setItem(
                    "systemMonitorThemes.v1",
                    JSON.stringify(themes)
                );
            }

            if (Array.isArray(profile.presets)) {
                const presets = {};

                profile.presets.forEach(function (rawPreset) {
                    const normalized = normalizePresetObject(rawPreset);

                    if (normalized) {
                        presets[normalized.id] = normalized;
                    }
                });

                localStorage.setItem(
                    "systemMonitorDashboardPresets.v1",
                    JSON.stringify(presets)
                );
            }

            if (typeof profile.activeThemeId === "string" && profile.activeThemeId) {
                localStorage.setItem(
                    "systemMonitorActiveTheme.v1",
                    profile.activeThemeId
                );
            }

            if (profile.dashboard && typeof profile.dashboard === "object") {
                const state = normalizeFullProfileState(profile.dashboard);
                const layout = normalizeFullProfileLayout(profile.dashboard.layout);

                localStorage.setItem(
                    "systemMonitorDashboard.v2",
                    JSON.stringify(state)
                );

                localStorage.setItem(
                    "systemMonitorDashboardLayout.v2",
                    JSON.stringify(layout)
                );
            }
        });

        // Refresh UI
        if (typeof renderThemesList === "function") renderThemesList();
        if (typeof renderPresetsList === "function") renderPresetsList();
        if (typeof syncSettings === "function") syncSettings();
        if (typeof updateSnapUI === "function") updateSnapUI();
        if (typeof createCards === "function") createCards();

        if (typeof latestData !== "undefined" && latestData) {
            if (typeof updateAll === "function") updateAll(latestData);
        }

        withSuppressProfilePush(function () {
            let activeId = localStorage.getItem("systemMonitorActiveTheme.v1") || "builtin-classic";

            if (typeof getAllThemes === "function") {
                const theme = getAllThemes().find(function (item) {
                    return item.id === activeId;
                });

                if (theme) {
                    if (typeof applyThemeByIdSilent === "function") {
                        applyThemeByIdSilent(activeId);
                    } else if (typeof applyThemeById === "function") {
                        applyThemeById(activeId);
                    }
                } else {
                    if (typeof applyThemeByIdSilent === "function") {
                        applyThemeByIdSilent("builtin-classic");
                    } else if (typeof applyThemeById === "function") {
                        applyThemeById("builtin-classic");
                    }
                }
            }
        });

        if (!hasServerProfile && hasLocalProfileData()) {
            pushFullProfileToServer();
        }
    } catch (err) {
        console.warn("Ошибка загрузки полного профиля с сервера:", err);
    }
}

// Helper functions that need to be defined
function normalizeThemeObject(raw) {
    if (!raw || typeof raw !== "object") return null;

    const hasVars = raw.variables && typeof raw.variables === "object" &&
        Object.keys(raw.variables).length > 0;
    const hasCss = typeof raw.customCss === "string" && raw.customCss.trim();

    if (!hasVars && !hasCss) return null;

    const variables = {};

    if (hasVars) {
        Object.keys(raw.variables).forEach(function (key) {
            const value = raw.variables[key];
            if (typeof value !== "string" && typeof value !== "number") return;

            let cleanKey = String(key).trim();
            if (cleanKey.indexOf("--") !== 0) cleanKey = "--" + cleanKey;

            variables[cleanKey] = String(value).replace(/[;{}<>]/g, "").slice(0, 200);
        });
    }

    return {
        id: typeof raw.id === "string" && /^[A-Za-z0-9_-]+$/.test(raw.id)
            ? raw.id
            : "theme-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8),
        name: String(raw.name || "Тема").slice(0, 80),
        author: typeof raw.author === "string" ? raw.author.slice(0, 80) : "",
        description: typeof raw.description === "string" ? raw.description.slice(0, 200) : "",
        dark: typeof raw.dark === "boolean" ? raw.dark : false,
        variables: variables,
        customCss: typeof raw.customCss === "string" ? raw.customCss.replace(/<\/style/gi, "").slice(0, 20000) : ""
    };
}

function normalizePresetObject(raw) {
    if (!raw || typeof raw !== "object") {
        return null;
    }

    const hasState = raw.state && typeof raw.state === "object";
    const hasLayout = raw.layout && typeof raw.layout === "object";

    if (!hasState && !hasLayout) {
        return null;
    }

    return {
        id: typeof raw.id === "string" && /^[A-Za-z0-9_-]+$/.test(raw.id)
            ? raw.id
            : "preset-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8),
        name: String(raw.name || "Пресет").slice(0, 80),
        createdAt: typeof raw.createdAt === "string"
            ? raw.createdAt
            : new Date().toISOString(),
        updatedAt: typeof raw.updatedAt === "string"
            ? raw.updatedAt
            : new Date().toISOString(),
        state: normalizeFullProfileState(hasState ? raw.state : {}),
        layout: normalizeFullProfileLayout(hasLayout ? raw.layout : {})
    };
}