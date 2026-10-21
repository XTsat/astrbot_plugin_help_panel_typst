/**
 * 帮助面板「实时预览」页
 *
 * 页面由 AstrBot dashboard 以 iframe 加载，通信统一走注入的 bridge：
 *   bridge.ready() / bridge.apiGet("preview/options") / bridge.apiPost("preview/render", payload)
 *
 * 设计要点：
 * - 所有可变状态集中在 state，控件渲染（renderControls/sync*）与预览渲染（renderStage/renderPreview）分层
 * - 渲染请求串行化：同一时刻最多一个在途请求，期间的新改动标记 pending，响应回来后用最新状态再发一次（latest-wins）
 * - 旧预览图永远保留，直到新结果成功返回，避免切换模式/搜索时整块闪烁
 */

const bridge = window.AstrBotPluginPage || window.AstrBotPluginView || null;

const HEX_PATTERN = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.1;
const DEFAULT_DEBOUNCE_MS = 550;
const READY_TIMEOUT_MS = 15000;
const NOTICE_DURATION_MS = 4000;
/** 多页下载之间的间隔，避免同一轮的多次下载被浏览器合并成一次 */
const DOWNLOAD_STAGGER_MS = 150;
/** 「渲染用测试精度」只保存在本机，换浏览器/清缓存后回到 144 */
const TEST_PPI_KEY = "helpTypst.previewTestPpi";

/** 当前渲染在途的 Promise；用于合并并发请求 */
let inFlight = null;
/** color key -> { swatch, hex }，避免每次改色都重新查询 DOM */
const colorInputs = new Map();

const state = {
  options: null,
  ready: false,
  fatalError: "",
  importing: false,
  applying: false,
  renderError: "",
  warnings: [],
  notice: "",
  noticeTimer: null,
  debounceTimer: null,
  listenersBound: false,

  modes: [],
  presets: [],
  // 自定义模板：与内置预设分开管理，首条固定叫「自定义」，是配色改动的落脚点
  customPresets: [],
  customPresetMeta: { label: "自定义", max: 8, nameMax: 20 },
  renamingIndex: -1,
  pendingDeleteIndex: -1,
  colorGroups: [],
  fonts: [],
  backgrounds: [],
  plugins: [],
  limits: {
    pageWidth: { min: 360, max: 1200, step: 10 },
    ppi: { min: 72, max: 384, step: 8 },
    splitHeight: { min: 1000, max: 65500, step: 1000 },
    singleColumnThreshold: { min: 360, max: 1200, step: 10 },
    giantThreshold: { min: 100, max: 3000, step: 100 },
    timeoutAnalysis: { min: 3, max: 60, step: 1 },
    timeoutCompile: { min: 3, max: 60, step: 1 },
    formatMaxHeight: { webp: 16383, png: 32000, jpeg: 65500 },
    maxQueryLen: 80,
  },
  preview: { ppi: 144, maxPages: 4, debounceMs: DEFAULT_DEBOUNCE_MS },

  // 表单状态
  mode: "command",
  query: "",
  preset: "",
  colors: {},
  selectedFonts: [],
  pageWidth: 600,
  ppi: 128,
  testPpi: readStoredTestPpi(),
  splitHeight: 16000,
  singleColumnThreshold: 480,
  giantThreshold: 1500,
  outputFormat: "webp",
  timeoutAnalysis: 10,
  timeoutCompile: 30,
  pluginTwoLines: true,
  heroHeader: true,
  background: "",
  fontFilter: "",
  // 重新扫描字体期间禁用按钮, 避免连点触发多次全盘扫描
  reloadingFonts: false,
  ignoredSelected: [],
  ignoredCustom: [],
  pluginFilter: "",

  // 分类规则编辑器（导入自插件配置，应用时可写回）
  categoryFallback: "其他",
  categoryFallbackColor: "slot_0",
  categoryRules: [],
  categorySelected: 0,
  categoryOptions: {
    slots: [],
    standard: [],
    fallbackDefaults: { fallback: "其他", fallbackColor: "slot_0" },
    hotWords: [],
    matchTexts: [],
    limits: { name: 16, keyword: 24, rules: 30, keywords: 60, hotWords: 48 },
  },

  // 预览状态
  images: [],
  lastRender: null,
  rendering: false,
  dirty: false,
  pendingRerender: false,
  requestSeq: 0,
  zoom: 1,
  fitWidth: true,
};

const els = {
  app: document.getElementById("app"),
  topbarStatus: document.getElementById("topbar-status"),
  topbarStatusText: document.getElementById("topbar-status-text"),

  zoomOut: document.getElementById("zoom-out"),
  zoomValue: document.getElementById("zoom-value"),
  zoomIn: document.getElementById("zoom-in"),
  zoomFit: document.getElementById("zoom-fit"),
  metaPages: document.getElementById("meta-pages"),
  metaRender: document.getElementById("meta-render"),
  openImage: document.getElementById("btn-open-image"),

  error: document.getElementById("preview-error"),
  errorTitle: document.getElementById("preview-error-title"),
  errorText: document.getElementById("preview-error-text"),
  errorRetry: document.getElementById("preview-error-retry"),

  viewport: document.getElementById("preview-viewport"),
  skeleton: document.getElementById("preview-skeleton"),
  skeletonText: document.getElementById("preview-skeleton-text"),
  stage: document.getElementById("preview-stage"),
  empty: document.getElementById("preview-empty"),
  loading: document.getElementById("preview-loading"),
  previewHint: document.getElementById("preview-hint"),

  controlsBody: document.getElementById("controls-body"),
  modeSegmented: document.getElementById("mode-segmented"),
  queryInput: document.getElementById("query-input"),
  queryClear: document.getElementById("query-clear"),
  presetList: document.getElementById("preset-list"),

  pageWidthInput: document.getElementById("page-width"),
  pageWidthValue: document.getElementById("page-width-value"),
  splitHeightInput: document.getElementById("split-height"),
  splitHeightValue: document.getElementById("split-height-value"),
  ppiInput: document.getElementById("ppi"),
  ppiValue: document.getElementById("ppi-value"),
  previewPpiInput: document.getElementById("preview-ppi"),
  previewPpiValue: document.getElementById("preview-ppi-value"),
  singleColumnThresholdInput: document.getElementById("single-column-threshold"),
  singleColumnThresholdValue: document.getElementById("single-column-threshold-value"),
  giantThresholdInput: document.getElementById("giant-threshold"),
  giantThresholdValue: document.getElementById("giant-threshold-value"),
  outputFormatSelect: document.getElementById("output-format"),
  timeoutAnalysisInput: document.getElementById("timeout-analysis"),
  timeoutAnalysisValue: document.getElementById("timeout-analysis-value"),
  timeoutCompileInput: document.getElementById("timeout-compile"),
  timeoutCompileValue: document.getElementById("timeout-compile-value"),
  toggleTwoLines: document.getElementById("toggle-two-lines"),
  toggleHero: document.getElementById("toggle-hero"),
  backgroundRow: document.getElementById("background-row"),
  backgroundSelect: document.getElementById("background-select"),

  fontChips: document.getElementById("font-chips"),
  fontSearch: document.getElementById("font-search"),
  fontList: document.getElementById("font-list"),
  reloadFonts: document.getElementById("btn-reload-fonts"),

  pluginSearch: document.getElementById("plugin-search"),
  pluginList: document.getElementById("plugin-list"),
  pluginEmpty: document.getElementById("plugin-empty"),
  pluginCustom: document.getElementById("plugin-custom"),
  pluginSummary: document.getElementById("plugin-summary"),
  pluginSelfHint: document.getElementById("plugin-self-hint"),

  categoryRules: document.getElementById("category-rules"),
  categoryHotWords: document.getElementById("category-hot-words"),
  categoryHotTarget: document.getElementById("category-hot-target"),
  categoryFallback: document.getElementById("category-fallback"),
  categoryFallbackColor: document.getElementById("category-fallback-color"),
  categoryFallbackPicker: document.getElementById("category-fallback-picker"),
  categoryAdd: document.getElementById("btn-add-category"),
  categoryStandard: document.getElementById("btn-standard-category"),
  categorySummary: document.getElementById("category-summary"),

  colorGroups: document.getElementById("color-groups"),
  restoreColors: document.getElementById("btn-restore-colors"),

  footerStatus: document.getElementById("footer-status"),
  footerStatusText: document.getElementById("footer-status-text"),
  footerCached: document.getElementById("footer-cached"),
  footerError: document.getElementById("footer-error"),
  btnReset: document.getElementById("btn-reset"),
  btnImport: document.getElementById("btn-import"),
  btnApply: document.getElementById("btn-apply"),
  btnRefresh: document.getElementById("btn-refresh"),
};

/* ==========================================================================
   通用工具
   ========================================================================== */

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asNumber(value, fallback) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function asBool(value, fallback) {
  if (typeof value === "boolean") return value;
  if (value === "true" || value === 1 || value === "1") return true;
  if (value === "false" || value === 0 || value === "0") return false;
  return fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function setText(node, value) {
  if (node && node.textContent !== value) node.textContent = value;
}

function show(node, visible) {
  if (node) node.hidden = !visible;
}

function errorMessage(error) {
  if (error instanceof Error && error.message) return error.message;
  return String(error || "未知错误");
}

function formatSeconds(milliseconds) {
  return `${(milliseconds / 1000).toFixed(2)} s`;
}

/** 把 #RGB / #RRGGBB 统一成小写 #rrggbb；非法值返回 null（调用方据此拒绝写入状态） */
function normalizeHex(value) {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!HEX_PATTERN.test(text)) return null;
  const hex = text.slice(1);
  if (hex.length === 3) {
    return `#${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`.toLowerCase();
  }
  return `#${hex.toLowerCase()}`;
}

function normalizeColorMap(value) {
  const source = asObject(value);
  const colors = {};
  for (const [key, raw] of Object.entries(source)) {
    const hex = normalizeHex(raw);
    if (hex) colors[key] = hex;
  }
  return colors;
}

function withTimeout(promise, milliseconds, message) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(message)), milliseconds);
    Promise.resolve(promise).then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function extensionForMime(mime) {
  if (mime === "image/png") return "png";
  if (mime === "image/jpeg") return "jpg";
  if (mime === "image/webp") return "webp";
  if (mime === "image/gif") return "gif";
  return "img";
}

function clearNotice() {
  state.notice = "";
  if (state.noticeTimer !== null) {
    window.clearTimeout(state.noticeTimer);
    state.noticeTimer = null;
  }
}

function setNotice(message) {
  state.notice = message;
  if (state.noticeTimer !== null) window.clearTimeout(state.noticeTimer);
  state.noticeTimer = window.setTimeout(() => {
    state.notice = "";
    state.noticeTimer = null;
    updateStatus();
  }, NOTICE_DURATION_MS);
  updateStatus();
}

/* ==========================================================================
   接口数据归一化
   ========================================================================== */

function normalizeModes(rawModes, fallbackValue) {
  const modes = asArray(rawModes)
    .filter((item) => item && typeof item === "object" && typeof item.value === "string")
    .map((item) => ({ value: item.value, label: String(item.label || item.value) }));
  if (modes.length) return modes;
  return [{ value: fallbackValue, label: fallbackValue }];
}

function normalizePresets(rawPresets) {
  return asArray(rawPresets)
    .filter((item) => item && typeof item === "object" && typeof item.name === "string")
    .map((item) => ({
      name: item.name,
      label: String(item.label || item.name),
      colors: normalizeColorMap(item.colors),
    }));
}

// 自定义模板只关心名字与配色：颜色缺失的条目无法出卡，直接丢弃
function normalizeCustomPresets(rawPresets) {
  return asArray(rawPresets)
    .filter((item) => item && typeof item === "object")
    .map((item, index) => ({
      name:
        index === 0
          ? state.customPresetMeta.label
          : String(item.name || "").trim() || `${state.customPresetMeta.label} ${index + 1}`,
      colors: normalizeColorMap(item.colors),
    }))
    .filter((item) => Object.keys(item.colors).length > 0);
}

function normalizeColorGroups(rawGroups) {
  return asArray(rawGroups)
    .filter((group) => group && typeof group === "object" && typeof group.id === "string")
    .map((group) => ({
      id: group.id,
      label: String(group.label || group.id),
      colors: asArray(group.colors)
        .filter((item) => item && typeof item === "object" && typeof item.key === "string")
        .map((item) => ({
          key: item.key,
          label: String(item.label || item.key),
          value: normalizeHex(item.value) || "#000000",
        })),
    }))
    .filter((group) => group.colors.length > 0);
}

function normalizeFontList(rawFonts) {
  const seen = new Set();
  const fonts = [];
  for (const item of asArray(rawFonts)) {
    if (typeof item !== "string") continue;
    const name = item.trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    fonts.push(name);
  }
  return fonts;
}

function normalizeBackgrounds(rawBackgrounds) {
  const seen = new Set();
  const names = [];
  for (const item of asArray(rawBackgrounds)) {
    const name = typeof item === "string" ? item : item && typeof item.name === "string" ? item.name : "";
    if (!name || seen.has(name)) continue;
    seen.add(name);
    names.push(name);
  }
  return names;
}

/** 插件名列表（屏蔽名单）去空白、去空项、去重，保留首次出现顺序 */
function normalizeNameList(rawNames) {
  const seen = new Set();
  const names = [];
  for (const item of asArray(rawNames)) {
    if (typeof item !== "string") continue;
    const name = item.trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    names.push(name);
  }
  return names;
}

/** 已安装插件归一成 { name, displayName, disabled }，渲染层不再判断后端字段形态 */
function normalizePlugins(rawPlugins) {
  const seen = new Set();
  const plugins = [];
  for (const item of asArray(rawPlugins)) {
    const source = asObject(item);
    const name = typeof source.name === "string" ? source.name.trim() : "";
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const displayName = typeof source.display_name === "string" ? source.display_name.trim() : "";
    plugins.push({
      name,
      displayName: displayName || name,
      disabled: asBool(source.disabled, false),
    });
  }
  // 列表按展示名排序，名字只在展示名相同时兜底，保证每次渲染顺序稳定
  plugins.sort((left, right) => {
    const byDisplay = left.displayName.toLowerCase().localeCompare(right.displayName.toLowerCase());
    if (byDisplay !== 0) return byDisplay;
    return left.name.toLowerCase().localeCompare(right.name.toLowerCase());
  });
  return plugins;
}

/** 屏蔽名单按集合比较：勾选顺序变化不算配置变化 */
function sameNameSet(left, right) {
  const a = new Set(normalizeNameList(left));
  const b = new Set(normalizeNameList(right));
  if (a.size !== b.size) return false;
  for (const name of a) {
    if (!b.has(name)) return false;
  }
  return true;
}

function normalizeKeywordList(rawKeywords) {
  const seen = new Set();
  const keywords = [];
  for (const item of asArray(rawKeywords)) {
    if (typeof item !== "string") continue;
    const keyword = item.trim();
    if (!keyword) continue;
    const lower = keyword.toLowerCase();
    if (seen.has(lower)) continue;
    seen.add(lower);
    keywords.push(keyword);
  }
  return keywords;
}

/** 分类色：空串=按顺序自动分配，slot_N=跟随主题色槽，其余按 #rrggbb 固定 */
function normalizeRuleColor(value) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) return "";
  if (/^slot_\d+$/.test(text)) return text;
  return normalizeHex(text) || "";
}

function normalizeCategoryRule(rawRule) {
  const rule = asObject(rawRule);
  return {
    name: typeof rule.name === "string" ? rule.name.trim() : "",
    keywords: normalizeKeywordList(rule.keywords),
    enabled: asBool(rule.enabled, true),
    color: normalizeRuleColor(rule.color),
  };
}

/** 面板状态 / 服务端配置共用同一份归一化：{ fallback, fallbackColor, rules } */
function normalizeCategory(rawCategory) {
  const category = asObject(rawCategory);
  return {
    fallback: typeof category.fallback === "string" ? category.fallback.trim() : "",
    fallbackColor: normalizeRuleColor(category.fallback_color),
    rules: asArray(category.rules)
      .map(normalizeCategoryRule)
      .filter((rule) => rule.name),
  };
}

function normalizeCategoryOptions(rawOptions) {
  const options = asObject(rawOptions);
  const limits = asObject(options.limits);
  const fallbackDefaults = asObject(options.fallback_defaults);
  const slots = asArray(options.slots)
    .map((rawSlot) => {
      const slot = asObject(rawSlot);
      const value = typeof slot.value === "string" ? slot.value : "";
      return {
        value,
        label: String(slot.label || value),
        hex: normalizeHex(slot.hex) || "#8a93a3",
      };
    })
    .filter((slot) => slot.value);
  const standard = asArray(options.standard)
    .map((rawRule, index) => {
      const rule = normalizeCategoryRule(rawRule);
      // 标准分类没给颜色时按顺序轮流用主题槽，和自动分配保持一致
      if (!rule.color && slots.length) rule.color = slots[(index + 1) % slots.length].value;
      return rule;
    })
    .filter((rule) => rule.name);
  return {
    slots,
    standard,
    fallbackDefaults: {
      fallback: String(fallbackDefaults.fallback || "其他"),
      fallbackColor: normalizeRuleColor(fallbackDefaults.fallback_color) || slots[0]?.value || "slot_0",
    },
    hotWords: asArray(options.hot_words)
      .map((rawWord) => {
        const word = asObject(rawWord);
        return {
          word: typeof word.word === "string" ? word.word : "",
          count: Math.max(1, asNumber(word.count, 1)),
        };
      })
      .filter((word) => word.word),
    matchTexts: asArray(options.match_texts)
      .map((rawText) => {
        const entry = asObject(rawText);
        return { name: String(entry.name || ""), text: String(entry.text || "").toLowerCase() };
      })
      .filter((entry) => entry.name),
    limits: {
      name: Math.max(1, asNumber(limits.name, 16)),
      keyword: Math.max(1, asNumber(limits.keyword, 24)),
      rules: Math.max(1, asNumber(limits.rules, 30)),
      keywords: Math.max(1, asNumber(limits.keywords, 60)),
      hotWords: Math.max(1, asNumber(limits.hot_words, 48)),
    },
  };
}

/** 分类规则的稳定签名：关键词排序、忽略大小写与颜色写法差异 */
function categorySignature(rawCategory) {
  const category = normalizeCategory(rawCategory);
  return JSON.stringify({
    fallback: category.fallback,
    fallbackColor: category.fallbackColor.toLowerCase(),
    rules: category.rules.map((rule) => ({
      name: rule.name,
      keywords: rule.keywords.map((keyword) => keyword.toLowerCase()).sort(),
      enabled: rule.enabled,
      color: rule.color.toLowerCase(),
    })),
  });
}

/* ==========================================================================
   初始化
   ========================================================================== */

function applyThemeFallback() {
  if (!bridge) return;
  const root = document.documentElement;
  const apply = (isDark) => {
    if (typeof isDark !== "boolean") return;
    // data-theme 由 dashboard 注入且优先级更高；这里只在属性缺失时兜底
    if (!root.getAttribute("data-theme")) {
      root.setAttribute("data-theme", isDark ? "dark" : "light");
    }
  };
  try {
    const context = typeof bridge.getContext === "function" ? bridge.getContext() : null;
    if (context) apply(context.isDark);
  } catch {
    // 主题兜底失败不影响页面主流程，CSS 会回落到默认亮色
  }
  if (typeof bridge.onContext === "function") {
    try {
      bridge.onContext((context) => {
        if (context) apply(context.isDark);
      });
    } catch {
      // 同上：拿不到上下文时保持 CSS 默认主题
    }
  }
}

function setFatal(message) {
  state.fatalError = message;
  state.rendering = false;
  renderPreview();
}

async function init() {
  bindStaticEvents();
  applyThemeFallback();

  if (!bridge) {
    setFatal(
      "未检测到 AstrBot 页面桥接，无法加载预览。请从 AstrBot 管理面板的「插件页面」打开本页；如果你是直接打开了本地文件，请改用插件页面访问。",
    );
    return;
  }

  setText(els.skeletonText, "正在连接 AstrBot…");
  try {
    await withTimeout(bridge.ready(), READY_TIMEOUT_MS, "连接 AstrBot 超时");
  } catch (error) {
    setFatal(`连接 AstrBot 失败：${errorMessage(error)}。请刷新页面重试。`);
    return;
  }

  try {
    const options = await bridge.apiGet("preview/options");
    applyOptions(options);
  } catch (error) {
    setFatal(`加载预览选项失败：${errorMessage(error)}。请确认插件已启用，然后刷新页面重试。`);
    return;
  }

  state.ready = true;
  state.fatalError = "";
  renderPreview();
  void requestRender();
}

/* ==========================================================================
   选项应用与控件构建
   ========================================================================== */

/**
 * 应用服务端选项。options.keepView 为 true 时只导入样式，
 * 保留当前面板类型 / 搜索词 / 预览清晰度（「导入当前配置」用）。
 */
function applyOptions(rawOptions, viewOptions = {}) {
  if (!rawOptions || typeof rawOptions !== "object") {
    throw new Error("预览选项格式不正确");
  }
  const options = rawOptions;
  const active = asObject(options.active);
  const preview = asObject(options.preview);
  const limits = asObject(options.limits);
  const widthLimit = asObject(limits.page_width);
  const ppiLimit = asObject(limits.ppi);
  const splitLimit = asObject(limits.split_height);
  const singleColumnLimit = asObject(limits.single_column_threshold);
  const giantLimit = asObject(limits.giant_threshold);
  const analysisTimeoutLimit = asObject(limits.timeout_analysis);
  const compileTimeoutLimit = asObject(limits.timeout_compile);

  state.options = options;
  state.modes = normalizeModes(options.modes, String(active.mode || "command"));
  const customMeta = asObject(options.custom_preset);
  state.customPresetMeta = {
    label: String(customMeta.label || "自定义"),
    max: Math.max(1, Math.round(asNumber(customMeta.max, 8))),
    nameMax: Math.max(4, Math.round(asNumber(customMeta.name_max, 20))),
  };
  state.presets = normalizePresets(options.presets);
  state.customPresets = normalizeCustomPresets(options.custom_presets);
  state.renamingIndex = -1;
  state.pendingDeleteIndex = -1;
  state.colorGroups = normalizeColorGroups(options.color_groups);
  state.categoryOptions = normalizeCategoryOptions(options.category);
  state.fonts = normalizeFontList(options.fonts);
  state.backgrounds = normalizeBackgrounds(options.backgrounds);
  // 老版本 AstrBot 或读取失败时 plugins 可能缺失/非数组，按空数组降级
  state.plugins = normalizePlugins(options.plugins);
  // options.ignored 与 active.ignored 同源；旧后端只给 active 时仍要能回填
  const ignoredSource = asObject(options.ignored);
  const ignored =
    ignoredSource.selected !== undefined || ignoredSource.custom !== undefined
      ? ignoredSource
      : asObject(active.ignored);
  state.ignoredSelected = normalizeNameList(ignored.selected);
  state.ignoredCustom = normalizeNameList(ignored.custom);

  state.limits = {
    pageWidth: {
      min: asNumber(widthLimit.min, 360),
      max: asNumber(widthLimit.max, 1200),
      step: asNumber(widthLimit.step, 10),
    },
    ppi: {
      min: asNumber(ppiLimit.min, 72),
      max: asNumber(ppiLimit.max, 384),
      step: asNumber(ppiLimit.step, 8),
    },
    splitHeight: {
      min: asNumber(splitLimit.min, 200),
      max: asNumber(splitLimit.max, 65500),
      step: asNumber(splitLimit.step, 100),
    },
    singleColumnThreshold: {
      min: asNumber(singleColumnLimit.min, 360),
      max: asNumber(singleColumnLimit.max, 1200),
      step: asNumber(singleColumnLimit.step, 10),
    },
    giantThreshold: {
      min: asNumber(giantLimit.min, 100),
      max: asNumber(giantLimit.max, 3000),
      step: asNumber(giantLimit.step, 100),
    },
    timeoutAnalysis: {
      min: asNumber(analysisTimeoutLimit.min, 3),
      max: asNumber(analysisTimeoutLimit.max, 60),
      step: asNumber(analysisTimeoutLimit.step, 1),
    },
    timeoutCompile: {
      min: asNumber(compileTimeoutLimit.min, 3),
      max: asNumber(compileTimeoutLimit.max, 60),
      step: asNumber(compileTimeoutLimit.step, 1),
    },
    formatMaxHeight: normalizeFormatMaxHeight(limits.format_max_height),
    // 后端会拒绝超长关键词，输入框直接按同一上限截断，避免白跑一次请求
    maxQueryLen: Math.max(1, asNumber(limits.max_query_len, 80)),
  };
  state.preview = {
    ppi: clamp(asNumber(preview.ppi, 144), 36, 512),
    maxPages: asNumber(preview.max_pages, 4),
    debounceMs: clamp(asNumber(preview.debounce_ms, DEFAULT_DEBOUNCE_MS), 80, 2000),
  };

  if (viewOptions.keepView) {
    // 导入当前配置：只覆盖样式，保留正在预览的面板类型与搜索词
    importActiveStyle(active);
    if (!state.modes.some((mode) => mode.value === state.mode)) {
      state.mode = state.modes[0]?.value || "command";
    }
  } else {
    applyActive(active);
  }
  ensureCustomPreset();
  buildControls();
}

function normalizeFormatMaxHeight(raw) {
  const source = asObject(raw);
  const fallback = { webp: 16383, png: 32000, jpeg: 65500 };
  const normalized = {};
  for (const format of ["webp", "png", "jpeg"]) {
    normalized[format] = Math.max(1000, asNumber(source[format], fallback[format]));
  }
  return normalized;
}

function splitHeightMax() {
  const formatMax = state.limits.formatMaxHeight[state.outputFormat];
  return Math.min(state.limits.splitHeight.max, asNumber(formatMax, state.limits.splitHeight.max));
}

// 把插件当前配置里的样式字段写进表单状态；面板类型 / 搜索词由调用方决定是否重置
function importActiveStyle(rawActive) {
  const active = asObject(rawActive);
  state.colors = normalizeColorMap(active.colors);
  state.preset = typeof active.preset === "string" ? active.preset : state.presets[0]?.name || "";
  state.selectedFonts = normalizeFontList(active.fonts);
  state.pageWidth = clamp(asNumber(active.page_width, 600), state.limits.pageWidth.min, state.limits.pageWidth.max);
  state.outputFormat =
    typeof active.output_format === "string" && active.output_format in state.limits.formatMaxHeight
      ? active.output_format
      : "webp";
  state.singleColumnThreshold = clamp(
    asNumber(active.single_column_threshold, 480),
    state.limits.singleColumnThreshold.min,
    state.limits.singleColumnThreshold.max,
  );
  state.giantThreshold = clamp(
    asNumber(active.giant_threshold, 1500),
    state.limits.giantThreshold.min,
    state.limits.giantThreshold.max,
  );
  state.timeoutAnalysis = clamp(
    asNumber(active.timeout_analysis, 10),
    state.limits.timeoutAnalysis.min,
    state.limits.timeoutAnalysis.max,
  );
  state.timeoutCompile = clamp(
    asNumber(active.timeout_compile, 30),
    state.limits.timeoutCompile.min,
    state.limits.timeoutCompile.max,
  );
  // 分页高度默认跟随正式配置；上限受当前输出格式约束
  state.splitHeight = clamp(
    asNumber(active.split_height, 16000),
    state.limits.splitHeight.min,
    splitHeightMax(),
  );
  // 精度与插件设置里的「图片清晰度」是同一项，导入/恢复时一并回填
  state.ppi = clamp(
    asNumber(active.ppi, state.preview.ppi),
    state.limits.ppi.min,
    state.limits.ppi.max,
  );
  state.pluginTwoLines = asBool(active.plugin_two_lines, true);
  state.heroHeader = asBool(active.hero_header, true);
  state.background = typeof active.background === "string" ? active.background : "";
  const ignored = asObject(active.ignored);
  state.ignoredSelected = normalizeNameList(ignored.selected);
  state.ignoredCustom = normalizeNameList(ignored.custom);
  // 旧后端没有 category 字段时退回 options.category.active，避免整块规则被清空
  const categorySource =
    active.category !== undefined ? active.category : asObject(state.options?.category).active;
  const category = normalizeCategory(categorySource);
  state.categoryFallback = category.fallback || state.categoryOptions.fallbackDefaults.fallback;
  state.categoryFallbackColor = category.fallbackColor || state.categoryOptions.fallbackDefaults.fallbackColor;
  state.categoryRules = category.rules;
  state.categorySelected = 0;
  state.fontFilter = "";
  state.pluginFilter = "";
}

function applyActive(rawActive) {
  const active = asObject(rawActive);
  const activeMode = typeof active.mode === "string" ? active.mode : "";
  state.mode = state.modes.some((mode) => mode.value === activeMode)
    ? activeMode
    : state.modes[0]?.value || "command";
  state.query = "";
  importActiveStyle(active);
}

function buildControls() {
  buildModeControl();
  buildPresetControl();
  buildBackgroundControl();
  buildPluginControl();
  buildCategoryControl();
  buildOutputFormatControl();
  buildColorControl();
  configureRanges();
  syncControls();
}

const OUTPUT_FORMATS = [
  { value: "webp", label: "WebP（体积最小，默认）" },
  { value: "png", label: "PNG（无损，体积大）" },
  { value: "jpeg", label: "JPEG（体积接近 WebP）" },
];

function buildOutputFormatControl() {
  if (!els.outputFormatSelect) return;
  els.outputFormatSelect.replaceChildren();
  for (const format of OUTPUT_FORMATS) {
    const option = document.createElement("option");
    option.value = format.value;
    option.textContent = format.label;
    els.outputFormatSelect.appendChild(option);
  }
}

function buildModeControl() {
  els.modeSegmented.replaceChildren();
  for (const mode of state.modes) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.mode = mode.value;
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", "false");
    button.textContent = mode.label;
    els.modeSegmented.appendChild(button);
  }
  syncModeControl();
}

function syncModeControl() {
  for (const button of els.modeSegmented.querySelectorAll("button[data-mode]")) {
    button.setAttribute("aria-checked", String(button.dataset.mode === state.mode));
  }
}

function presetLabel(preset) {
  return preset.label || preset.name;
}

function findPreset(name) {
  return (
    state.presets.find((item) => item.name === name) ||
    state.customPresets.find((item) => item.name === name) ||
    null
  );
}

function isBuiltinPreset(name) {
  return state.presets.some((item) => item.name === name);
}

// 面板至少保留一张自定义卡：它承接「改内置模板」后的配色，也是保存配置时的落点
function ensureCustomPreset() {
  const label = state.customPresetMeta.label;
  if (!state.customPresets.length) {
    const colors = Object.keys(state.colors).length ? { ...state.colors } : {};
    state.customPresets = [{ name: label, colors }];
  }
  state.customPresets[0].name = label;
  if (state.preset && !findPreset(state.preset)) {
    state.preset = state.customPresets[0].name;
  }
}

function nextCustomPresetName() {
  const taken = new Set(state.customPresets.map((item) => item.name));
  const label = state.customPresetMeta.label;
  let counter = 2;
  let name = `${label} ${counter}`;
  while (taken.has(name)) {
    counter += 1;
    name = `${label} ${counter}`;
  }
  return name;
}

function buildPresetControl() {
  els.presetList.replaceChildren();

  if (state.presets.length) {
    const group = document.createElement("div");
    group.className = "preset-group";
    const heading = document.createElement("span");
    heading.className = "preset-group-label";
    heading.textContent = "内置模板";
    const cards = document.createElement("div");
    cards.className = "preset-cards";
    for (const preset of state.presets) {
      cards.appendChild(createPresetCard(preset));
    }
    group.append(heading, cards);
    els.presetList.appendChild(group);
  }

  const customGroup = document.createElement("div");
  customGroup.className = "preset-group";
  const customHeading = document.createElement("span");
  customHeading.className = "preset-group-label";
  customHeading.textContent = "自定义模板";
  const customCards = document.createElement("div");
  customCards.className = "preset-cards";
  state.customPresets.forEach((preset, index) => {
    customCards.appendChild(createPresetCard(preset, index));
  });
  customGroup.append(customHeading, customCards, createAddPresetButton());
  els.presetList.appendChild(customGroup);

  syncPresetControl();
}

function createPresetCard(preset, customIndex = -1) {
  const isCustom = customIndex >= 0;
  const item = document.createElement("div");
  item.className = "preset-item";
  item.dataset.preset = preset.name;
  if (isCustom) item.dataset.customIndex = String(customIndex);

  // 改名用卡片内联输入框：内置模板不可改名，首条自定义模板名固定；
  // 输入框不能嵌在 <button> 里（交互元素嵌套会让焦点与点击失效），改名时卡片降级成 div
  const renaming = isCustom && customIndex > 0 && state.renamingIndex === customIndex;

  const card = document.createElement(renaming ? "div" : "button");
  card.className = "preset-card";
  card.dataset.preset = preset.name;
  if (renaming) {
    card.classList.add("is-renaming");
  } else {
    card.type = "button";
    card.setAttribute("aria-pressed", "false");
    card.title = isCustom ? `套用「${preset.name}」的配色` : presetLabel(preset);
  }

  if (renaming) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "preset-rename";
    input.value = preset.name;
    input.maxLength = state.customPresetMeta.nameMax;
    input.dataset.renameIndex = String(customIndex);
    input.setAttribute("aria-label", "模板名称，回车保存，Esc 取消");
    card.appendChild(input);
  } else {
    const name = document.createElement("span");
    name.className = "preset-name";
    name.textContent = isCustom ? preset.name : presetLabel(preset);
    card.appendChild(name);
  }

  const dots = document.createElement("span");
  dots.className = "preset-dots";
  for (const color of Object.values(preset.colors).slice(0, 5)) {
    const dot = document.createElement("span");
    dot.className = "preset-dot";
    dot.style.background = color;
    dots.appendChild(dot);
  }
  card.appendChild(dots);
  item.appendChild(card);

  if (isCustom && customIndex > 0) {
    item.appendChild(createPresetActions(customIndex));
  }
  return item;
}

function createPresetActions(index) {
  const actions = document.createElement("div");
  actions.className = "preset-actions";

  const rename = document.createElement("button");
  rename.type = "button";
  rename.className = "preset-action";
  rename.dataset.action = "rename-preset";
  rename.dataset.presetIndex = String(index);
  rename.textContent = "改名";
  actions.appendChild(rename);

  // 删除需要二次确认：第一次点击只改写按钮文案，避免误删用户配好的模板
  const confirming = state.pendingDeleteIndex === index;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "preset-action is-danger";
  remove.dataset.action = "delete-preset";
  remove.dataset.presetIndex = String(index);
  remove.dataset.confirm = confirming ? "1" : "0";
  remove.textContent = confirming ? "确认删除" : "删除";
  actions.appendChild(remove);
  return actions;
}

function createAddPresetButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "preset-add";
  button.dataset.action = "add-preset";
  button.textContent = "＋ 新建模板";
  const full = state.customPresets.length >= state.customPresetMeta.max;
  button.disabled = full;
  button.title = full
    ? `自定义模板最多 ${state.customPresetMeta.max} 个`
    : "用当前配色新建一个自定义模板";
  return button;
}

function syncPresetControl() {
  for (const card of els.presetList.querySelectorAll(".preset-card")) {
    const name = card.dataset.preset;
    const isActive = name === state.preset;
    card.classList.toggle("is-active", isActive);
    // 改名时的卡片是 div（输入框不能嵌在 button 里），不能挂 aria-pressed
    if (card.tagName === "BUTTON") {
      card.setAttribute("aria-pressed", String(isActive));
    }
    const preset = findPreset(name);
    if (!preset) continue;
    // 只有内置模板才提示「已调整」：自定义模板本身就是可改的工作副本
    const modified = Boolean(isActive && isBuiltinPreset(name) && !colorsMatchPreset(preset));
    card.classList.toggle("is-modified", modified);
    const dots = card.querySelectorAll(".preset-dot");
    const values = Object.values(preset.colors).slice(0, 5);
    dots.forEach((dot, index) => {
      if (values[index]) dot.style.background = values[index];
    });
  }
}

function colorsMatchPreset(preset) {
  const entries = Object.entries(preset.colors);
  if (!entries.length) return false;
  return entries.every(([key, value]) => normalizeHex(state.colors[key]) === normalizeHex(value));
}

// 改色时把配色落到自定义模板：首条自定义模板承接「内置模板被改」的改动，
// 这样内置预设永远不会被写脏，也符合「保存到第一条自定义模板」的约定
function syncActivePresetColors() {
  const active = state.customPresets.find((item) => item.name === state.preset);
  const target = active || state.customPresets[0];
  if (!target) return;
  const converted = !active && isBuiltinPreset(state.preset);
  target.colors = { ...state.colors };
  if (!active) state.preset = target.name;
  syncPresetControl();
  if (converted) setNotice(`已将改动转存到「${target.name}」模板`);
}

function startRenamePreset(index) {
  if (index <= 0 || index >= state.customPresets.length) return;
  state.renamingIndex = index;
  state.pendingDeleteIndex = -1;
  buildPresetControl();
  const input = els.presetList.querySelector(`input[data-rename-index="${index}"]`);
  if (input) {
    input.focus();
    input.select();
  }
}

function normalizeCustomPresetName(rawValue, index) {
  if (index === 0) return state.customPresetMeta.label;
  const trimmed = String(rawValue || "").trim().slice(0, state.customPresetMeta.nameMax);
  if (!trimmed) return "";
  const taken = new Set([state.customPresetMeta.label]);
  for (const preset of state.presets) {
    taken.add(preset.name);
    taken.add(presetLabel(preset));
  }
  state.customPresets.forEach((item, itemIndex) => {
    if (itemIndex !== index) taken.add(item.name);
  });
  let candidate = trimmed;
  let counter = 2;
  while (taken.has(candidate)) {
    candidate = `${trimmed} ${counter}`;
    counter += 1;
  }
  return candidate.slice(0, state.customPresetMeta.nameMax);
}

function commitRenamePreset(index, rawValue) {
  if (state.renamingIndex !== index) return;
  const preset = state.customPresets[index];
  state.renamingIndex = -1;
  if (!preset) {
    buildPresetControl();
    return;
  }
  const name = normalizeCustomPresetName(rawValue, index);
  if (!name || name === preset.name) {
    buildPresetControl();
    return;
  }
  if (state.preset === preset.name) state.preset = name;
  preset.name = name;
  buildPresetControl();
  markDirty();
  setNotice(`模板已改名为「${name}」`);
}

function addCustomPreset() {
  if (state.customPresets.length >= state.customPresetMeta.max) return;
  const colors = Object.keys(state.colors).length
    ? { ...state.colors }
    : { ...(state.customPresets[0]?.colors || {}) };
  state.customPresets.push({ name: nextCustomPresetName(), colors });
  state.pendingDeleteIndex = -1;
  buildPresetControl();
  markDirty();
  setNotice("已用当前配色新建自定义模板");
}

function removeCustomPreset(index) {
  if (index <= 0 || index >= state.customPresets.length) return;
  if (state.pendingDeleteIndex !== index) {
    state.pendingDeleteIndex = index;
    buildPresetControl();
    setNotice("再次点击「确认删除」移除该模板");
    return;
  }
  const [removed] = state.customPresets.splice(index, 1);
  state.pendingDeleteIndex = -1;
  state.renamingIndex = -1;
  if (state.preset === removed.name) {
    state.preset = state.customPresets[0].name;
    Object.assign(state.colors, state.customPresets[0].colors);
    syncColorInputs();
  }
  buildPresetControl();
  markDirty();
  setNotice(`已删除模板「${removed.name}」`);
}

function buildBackgroundControl() {
  els.backgroundSelect.replaceChildren();
  const follow = document.createElement("option");
  follow.value = "";
  follow.textContent = "跟随插件配置";
  els.backgroundSelect.appendChild(follow);
  for (const name of state.backgrounds) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    els.backgroundSelect.appendChild(option);
  }
  syncBackgroundControl();
}

function syncBackgroundControl() {
  els.backgroundSelect.value = state.background || "";
  if (els.backgroundSelect.value === (state.background || "")) return;
  // 当前背景不在扫描结果里（文件被删除或来自自定义路径）时补占位项，避免下拉框显示错位
  const option = document.createElement("option");
  option.value = state.background;
  option.textContent = `${state.background}（未找到）`;
  els.backgroundSelect.appendChild(option);
  els.backgroundSelect.value = state.background;
}

function buildPluginControl() {
  renderPluginList();
  updatePluginSummary();
}

function syncPluginControl() {
  if (!els.pluginList) return;
  // 搜索框正在输入时不要回写，否则光标会跳回末尾
  if (els.pluginSearch && document.activeElement !== els.pluginSearch) {
    if (els.pluginSearch.value !== state.pluginFilter) {
      els.pluginSearch.value = state.pluginFilter;
    }
  }
  // 自定义条目同理：只在值真的不同时写回，避免每次同步都重置光标
  if (els.pluginCustom) {
    const text = state.ignoredCustom.join("\n");
    if (els.pluginCustom.value !== text) els.pluginCustom.value = text;
  }
  renderPluginList();
  updatePluginSummary();
}

function renderPluginList() {
  if (!els.pluginList) return;
  const keyword = state.pluginFilter.trim().toLowerCase();
  const pool = keyword
    ? state.plugins.filter(
        (plugin) =>
          plugin.name.toLowerCase().includes(keyword) ||
          plugin.displayName.toLowerCase().includes(keyword),
      )
    : state.plugins;

  const fragment = document.createDocumentFragment();
  for (const plugin of pool) {
    fragment.appendChild(buildPluginRow(plugin));
  }
  els.pluginList.replaceChildren(fragment);
  if (!pool.length && state.plugins.length) {
    const empty = document.createElement("p");
    empty.className = "plugin-list-empty";
    empty.textContent = "没有匹配的插件";
    els.pluginList.appendChild(empty);
  }

  // 只有「一个插件都没读到」才提示手动填写；搜索无结果不算
  show(els.pluginEmpty, !state.plugins.length);
  // 没有可选项时收起列表与搜索框，避免留下空边框让人以为加载失败
  show(els.pluginList, state.plugins.length > 0);
  if (els.pluginSearch) els.pluginSearch.disabled = !state.plugins.length;
  updatePluginSelfHint();
}

function buildPluginRow(plugin) {
  const row = document.createElement("label");
  row.className = "plugin-item";
  row.dataset.plugin = plugin.name;
  row.classList.toggle("is-disabled", plugin.disabled);

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "plugin-check";
  check.value = plugin.name;
  check.checked = state.ignoredSelected.includes(plugin.name);

  const text = document.createElement("span");
  text.className = "plugin-text";

  const line = document.createElement("span");
  line.className = "plugin-line";

  const name = document.createElement("span");
  name.className = "plugin-name";
  name.textContent = plugin.displayName;
  line.appendChild(name);

  if (plugin.disabled) {
    // 已禁用的插件仍可勾选：屏蔽与否和插件是否启用无关
    const tag = document.createElement("span");
    tag.className = "plugin-tag";
    tag.textContent = "（已禁用）";
    line.appendChild(tag);
  }

  const id = document.createElement("span");
  id.className = "plugin-id";
  id.textContent = plugin.name;

  text.append(line, id);
  row.append(check, text);
  return row;
}

function updatePluginSummary() {
  const selected = state.ignoredSelected.length;
  const custom = state.ignoredCustom.length;
  if (!selected && !custom) {
    setText(els.pluginSummary, "当前不屏蔽任何插件");
    return;
  }
  const parts = [];
  if (selected) parts.push(`已勾选 ${selected} 个已安装插件`);
  if (custom) parts.push(`另有 ${custom} 条自定义条目`);
  setText(els.pluginSummary, parts.join("，"));
}

function updatePluginSelfHint() {
  const selfNames = ["help_panel_typst", "astrbot_plugin_help_panel_typst"];
  show(els.pluginSelfHint, state.ignoredSelected.some((name) => selfNames.includes(name)));
}

/* ==========================================================================
   分类规则与高频热词
   ========================================================================== */

function buildCategoryControl() {
  if (!els.categoryRules) return;
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  updateCategoryTarget();
}

function syncCategoryControl() {
  if (!els.categoryRules) return;
  const limits = state.categoryOptions.limits;
  if (els.categoryFallback) {
    els.categoryFallback.maxLength = limits.name;
    if (document.activeElement !== els.categoryFallback) {
      els.categoryFallback.value = state.categoryFallback;
    }
  }
  if (els.categoryFallbackColor) {
    rebuildCategoryColorSelect(
      els.categoryFallbackColor,
      state.categoryFallbackColor,
      "默认（槽 0）",
      "fallback-color",
    );
  }
  syncFallbackColorPicker();
  if (state.categorySelected >= state.categoryRules.length) {
    state.categorySelected = Math.max(0, state.categoryRules.length - 1);
  }
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  updateCategoryTarget();
}

function syncFallbackColorPicker() {
  if (!els.categoryFallbackPicker) return;
  const isFixed = /^#[0-9a-f]{6}$/i.test(state.categoryFallbackColor);
  els.categoryFallbackPicker.hidden = !isFixed;
  if (isFixed) els.categoryFallbackPicker.value = state.categoryFallbackColor;
}

/** 重建分类色下拉：空串自动分配、主题槽、固定 hex，另给一项「自定义颜色…」 */
function rebuildCategoryColorSelect(select, value, autoLabel, action) {
  select.dataset.action = action;
  select.replaceChildren();
  select.appendChild(new Option(autoLabel, ""));
  for (const slot of state.categoryOptions.slots) {
    select.appendChild(new Option(`${slot.label} · ${slot.hex}`, slot.value));
  }
  select.appendChild(new Option("自定义颜色…", "__custom__"));
  updateCategoryColorSelect(select, value);
}

/** 只更新选中项：固定颜色在「自定义颜色…」之前插入/替换一项，避免整卡重画 */
function updateCategoryColorSelect(select, value) {
  const current = normalizeRuleColor(value);
  const fixed = select.querySelector('option[data-fixed="true"]');
  if (fixed) fixed.remove();
  if (current && !state.categoryOptions.slots.some((slot) => slot.value === current)) {
    // 固定颜色或主题里已不存在的槽位：补占位项，避免下拉显示错位
    const label = current.startsWith("#") ? `固定 ${current}` : `${current}（未找到）`;
    const option = new Option(label, current);
    option.dataset.fixed = "true";
    select.insertBefore(option, select.lastElementChild);
  }
  select.value = current;
}

function renderCategoryRules() {
  if (!els.categoryRules) return;
  els.categoryRules.replaceChildren();
  if (!state.categoryRules.length) {
    const empty = document.createElement("p");
    empty.className = "category-rule-empty";
    empty.textContent =
      "还没有分组，所有插件都会进兜底分组。可以点「套用标准分类」快速开始，或手动添加一个分组。";
    els.categoryRules.appendChild(empty);
    updateCategoryTarget();
    return;
  }
  const fragment = document.createDocumentFragment();
  state.categoryRules.forEach((rule, index) => {
    fragment.appendChild(buildCategoryRuleCard(rule, index));
  });
  els.categoryRules.appendChild(fragment);
}

function buildCategoryRuleCard(rule, index) {
  const card = document.createElement("div");
  card.className = "category-rule";
  card.dataset.index = String(index);
  card.classList.toggle("is-selected", index === state.categorySelected);
  card.classList.toggle("is-disabled", !rule.enabled);

  const head = document.createElement("div");
  head.className = "category-rule-head";

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "category-rule-check";
  check.dataset.action = "enabled";
  check.checked = rule.enabled;
  check.title = "启用这条分组规则";

  const name = document.createElement("input");
  name.type = "text";
  name.className = "category-rule-name";
  name.dataset.action = "name";
  name.value = rule.name;
  name.maxLength = state.categoryOptions.limits.name;
  name.placeholder = "分组名";
  name.setAttribute("aria-label", `第 ${index + 1} 个分组的名称`);

  const actions = document.createElement("div");
  actions.className = "category-rule-actions";
  const up = categoryIconButton("↑", "上移（越靠前优先级越高）", "up");
  up.disabled = index === 0;
  const down = categoryIconButton("↓", "下移", "down");
  down.disabled = index === state.categoryRules.length - 1;
  const remove = categoryIconButton("×", "删除该分组", "remove");
  remove.classList.add("is-danger");
  actions.append(up, down, remove);

  head.append(check, name, actions);

  const meta = document.createElement("div");
  meta.className = "category-rule-meta";
  const color = document.createElement("select");
  color.className = "category-color-select";
  rebuildCategoryColorSelect(color, rule.color, "自动分配颜色", "rule-color");
  color.setAttribute("aria-label", `${rule.name || "分组"}的颜色`);
  meta.appendChild(color);
  if (/^#[0-9a-f]{6}$/i.test(rule.color)) {
    // 固定颜色时多给一个取色器，比手改 hex 更直接
    const picker = document.createElement("input");
    picker.type = "color";
    picker.className = "category-color-picker";
    picker.dataset.action = "rule-color-picker";
    picker.value = rule.color;
    picker.title = "调整固定颜色";
    picker.setAttribute("aria-label", `${rule.name || "分组"}的固定颜色`);
    meta.appendChild(picker);
  }
  const count = document.createElement("span");
  count.className = "category-rule-count";
  count.textContent = rule.enabled ? `命中 ${countCategoryMatches(rule)} 个插件` : "已停用";
  meta.appendChild(count);

  const keywords = document.createElement("div");
  keywords.className = "category-keywords";
  for (const keyword of rule.keywords) {
    keywords.appendChild(buildKeywordChip(keyword, countKeywordMatches(keyword)));
  }

  const input = document.createElement("input");
  input.type = "text";
  input.className = "category-keyword-input";
  input.dataset.action = "keyword";
  input.maxLength = state.categoryOptions.limits.keyword;
  const reached = rule.keywords.length >= state.categoryOptions.limits.keywords;
  input.placeholder = reached ? "关键词已达上限" : "输入关键词后回车";
  input.disabled = reached;
  input.setAttribute("aria-label", `${rule.name || "分组"}的关键词`);
  keywords.appendChild(input);

  card.append(head, meta, keywords);
  return card;
}

function buildKeywordChip(keyword, matches) {
  const hits = Number.isFinite(matches) ? matches : countKeywordMatches(keyword);
  const chip = document.createElement("span");
  chip.className = "category-keyword";
  chip.title = `「${keyword}」命中 ${hits} 个插件`;

  const text = document.createElement("span");
  text.className = "category-keyword-text";
  text.textContent = keyword;

  const count = document.createElement("span");
  count.className = "category-keyword-count";
  count.classList.toggle("is-zero", hits === 0);
  count.textContent = String(hits);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "category-keyword-remove";
  remove.dataset.action = "remove-keyword";
  remove.dataset.keyword = keyword;
  remove.title = `移除关键词「${keyword}」`;
  remove.textContent = "×";

  chip.append(text, count, remove);
  return chip;
}

function categoryIconButton(label, title, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "category-icon-btn";
  button.dataset.action = action;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.textContent = label;
  return button;
}

function renderHotWords() {
  if (!els.categoryHotWords) return;
  els.categoryHotWords.replaceChildren();
  const words = state.categoryOptions.hotWords;
  if (!words.length) {
    const empty = document.createElement("p");
    empty.className = "hot-word-empty";
    empty.textContent = "插件名称与简介里还没有重复出现的词，先手动填关键词吧";
    els.categoryHotWords.appendChild(empty);
    return;
  }
  const used = new Set(
    state.categoryRules.flatMap((rule) => rule.keywords.map((keyword) => keyword.toLowerCase())),
  );
  const maxCount = Math.max(...words.map((word) => word.count));
  const fragment = document.createDocumentFragment();
  for (const entry of words.slice(0, state.categoryOptions.limits.hotWords)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hot-word";
    button.dataset.word = entry.word;
    button.title = `命中 ${entry.count} 个插件，点击加入选中的分组`;
    button.classList.toggle("is-used", used.has(entry.word.toLowerCase()));
    // 按出现次数做轻微字号分级，一眼看出哪些词更常见
    button.style.fontSize = `${11 + Math.round(2.5 * (entry.count / maxCount))}px`;

    const label = document.createElement("span");
    label.textContent = entry.word;
    const count = document.createElement("span");
    count.className = "hot-word-count";
    count.textContent = String(entry.count);
    button.append(label, count);
    fragment.appendChild(button);
  }
  els.categoryHotWords.appendChild(fragment);
}

/** 关键词是否命中插件文本：与归类规则一致，英文按整词、中文按片段 */
function keywordHitsText(keyword, text) {
  if (!keyword || !text) return false;
  if (/^[a-z0-9]+$/.test(keyword)) {
    return (text.match(/[a-z0-9]+/g) || []).includes(keyword);
  }
  return text.includes(keyword);
}

/** 单个关键词实际命中的可见插件数（不考虑分组顺序，和上方热词的计数口径一致） */
function countKeywordMatches(keyword) {
  const needle = String(keyword || "").toLowerCase();
  if (!needle) return 0;
  return state.categoryOptions.matchTexts.reduce(
    (total, entry) => total + (keywordHitsText(needle, entry.text) ? 1 : 0),
    0,
  );
}

/** 当前关键词能命中多少个插件（仅作参考：最终归属还受规则顺序影响） */
function countCategoryMatches(rule) {
  const enabledKeywords = rule.keywords.map((keyword) => keyword.toLowerCase()).filter(Boolean);
  if (!rule.enabled || !enabledKeywords.length) return 0;
  return state.categoryOptions.matchTexts.reduce(
    (total, entry) =>
      total + (enabledKeywords.some((keyword) => keywordHitsText(keyword, entry.text)) ? 1 : 0),
    0,
  );
}

function updateCategoryTarget() {
  if (!els.categoryHotTarget) return;
  const rule = state.categoryRules[state.categorySelected];
  setText(els.categoryHotTarget, rule ? `填入：${rule.name || "未命名分组"}` : "先添加一个分组");
}

function updateCategorySummary() {
  if (!els.categorySummary) return;
  const total = state.categoryOptions.matchTexts.length;
  if (!total) {
    setText(els.categorySummary, "");
    return;
  }
  const matched = state.categoryOptions.matchTexts.filter((entry) =>
    state.categoryRules.some(
      (rule) =>
        rule.enabled &&
        rule.keywords.some((keyword) => entry.text.includes(keyword.toLowerCase())),
    ),
  ).length;
  setText(
    els.categorySummary,
    `面板可见 ${total} 个插件：${matched} 个会被分组命中，${total - matched} 个进入「${state.categoryFallback || "其他"}」。`,
  );
}

function addCategoryRule() {
  const limits = state.categoryOptions.limits;
  if (state.categoryRules.length >= limits.rules) {
    setNotice(`最多只能添加 ${limits.rules} 个分组`);
    return;
  }
  // 预填一个能保存的名称：后端会丢弃无名分组，先给占位名再让用户直接改
  state.categoryRules.push({ name: "新分组", keywords: [], enabled: true, color: "" });
  state.categorySelected = state.categoryRules.length - 1;
  renderCategoryRules();
  updateCategoryTarget();
  const nameInput = els.categoryRules.querySelector(
    ".category-rule.is-selected .category-rule-name",
  );
  if (nameInput instanceof HTMLInputElement) {
    nameInput.focus();
    nameInput.select();
  }
}

function applyStandardCategories() {
  if (!state.categoryOptions.standard.length) {
    setNotice("没有可用的标准分类模板");
    return;
  }
  state.categoryRules = state.categoryOptions.standard.map((rule) => ({
    name: rule.name,
    keywords: [...rule.keywords],
    enabled: true,
    color: rule.color,
  }));
  state.categorySelected = 0;
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  updateCategoryTarget();
  markDirty();
  setNotice(`已套用 ${state.categoryRules.length} 个标准分组，可继续微调关键词`);
}

function selectCategoryRule(index) {
  if (index === state.categorySelected) return;
  state.categorySelected = index;
  for (const card of els.categoryRules.querySelectorAll(".category-rule")) {
    card.classList.toggle("is-selected", Number(card.dataset.index) === index);
  }
  updateCategoryTarget();
}

function addKeywordToSelectedRule(rawWord) {
  const keyword = String(rawWord || "").trim();
  if (!keyword) return;
  const limits = state.categoryOptions.limits;
  let rule = state.categoryRules[state.categorySelected];
  if (!rule) {
    if (state.categoryRules.length >= limits.rules) {
      setNotice(`最多只能添加 ${limits.rules} 个分组`);
      return;
    }
    rule = { name: "新分组", keywords: [], enabled: true, color: "" };
    state.categoryRules.push(rule);
    state.categorySelected = state.categoryRules.length - 1;
  }
  if (rule.keywords.length >= limits.keywords) {
    setNotice(`每个分组最多 ${limits.keywords} 个关键词`);
    return;
  }
  if (rule.keywords.some((item) => item.toLowerCase() === keyword.toLowerCase())) {
    setNotice(`「${rule.name || "当前分组"}」已包含关键词「${keyword}」`);
    return;
  }
  rule.keywords.push(keyword.slice(0, limits.keyword));
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  markDirty();
}

/** 提交关键词输入：支持一次粘贴多个词（逗号 / 顿号 / 空格 / 竖线分隔） */
function commitKeyword(index, rawValue) {
  const rule = state.categoryRules[index];
  if (!rule) return;
  const words = String(rawValue || "")
    .split(/[,，、;；\s|]+/)
    .filter(Boolean);
  for (const word of words) {
    if (rule.keywords.length >= state.categoryOptions.limits.keywords) break;
    const keyword = word.slice(0, state.categoryOptions.limits.keyword);
    if (rule.keywords.some((item) => item.toLowerCase() === keyword.toLowerCase())) continue;
    rule.keywords.push(keyword);
  }
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  markDirty();
}

function focusCategoryKeywordInput(index) {
  const card = els.categoryRules.querySelector(`.category-rule[data-index="${index}"]`);
  const input = card ? card.querySelector(".category-keyword-input") : null;
  if (input instanceof HTMLInputElement && !input.disabled) input.focus();
}

function moveCategoryRule(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= state.categoryRules.length) return;
  const [rule] = state.categoryRules.splice(index, 1);
  state.categoryRules.splice(target, 0, rule);
  state.categorySelected = target;
  renderCategoryRules();
  markDirty();
}

function removeCategoryRule(index) {
  const rule = state.categoryRules[index];
  if (!rule) return;
  state.categoryRules.splice(index, 1);
  if (state.categorySelected > index) state.categorySelected -= 1;
  state.categorySelected = Math.min(
    state.categorySelected,
    Math.max(0, state.categoryRules.length - 1),
  );
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  markDirty();
  setNotice(`已删除分组「${rule.name || "未命名"}」`);
}

function removeKeywordFromRule(index, keyword) {
  const rule = state.categoryRules[index];
  if (!rule) return;
  const position = rule.keywords.indexOf(keyword);
  if (position < 0) return;
  rule.keywords.splice(position, 1);
  renderCategoryRules();
  renderHotWords();
  updateCategorySummary();
  markDirty();
}

function handleCategoryClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const card = target.closest(".category-rule");
  if (!card) return;
  const index = Number(card.dataset.index);
  if (!Number.isInteger(index) || !state.categoryRules[index]) return;
  const actionTarget = target.closest("[data-action]");
  const action = actionTarget instanceof HTMLElement ? actionTarget.dataset.action : "";
  if (action === "up") {
    moveCategoryRule(index, -1);
    return;
  }
  if (action === "down") {
    moveCategoryRule(index, 1);
    return;
  }
  if (action === "remove") {
    removeCategoryRule(index);
    return;
  }
  if (action === "remove-keyword") {
    removeKeywordFromRule(index, actionTarget.dataset.keyword || "");
    return;
  }
  selectCategoryRule(index);
}

function handleCategoryInput(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.dataset.action !== "name") return;
  const card = target.closest(".category-rule");
  if (!card) return;
  const rule = state.categoryRules[Number(card.dataset.index)];
  if (!rule) return;
  rule.name = target.value.slice(0, state.categoryOptions.limits.name);
  updateCategoryTarget();
  markDirty();
}

function handleCategoryChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
  const card = target.closest(".category-rule");
  if (!card) return;
  const index = Number(card.dataset.index);
  const rule = state.categoryRules[index];
  if (!rule) return;
  const action = target.dataset.action;
  if (action === "enabled") {
    rule.enabled = target.checked;
    // 启停会影响每组命中数，整体重画最省事（行数远小于性能感知阈值）
    renderCategoryRules();
    updateCategorySummary();
    markDirty();
    return;
  }
  if (action === "rule-color") {
    let value = target.value;
    if (value === "__custom__") value = "#5b8def";
    rule.color = normalizeRuleColor(value);
    // 固定 hex 需要以「固定 #xxxxxx」的形式回显，直接重画下拉
    renderCategoryRules();
    markDirty();
    return;
  }
  if (action === "rule-color-picker") {
    const hex = normalizeHex(target.value);
    if (!hex) return;
    rule.color = hex;
    const select = card.querySelector('select[data-action="rule-color"]');
    if (select instanceof HTMLSelectElement) updateCategoryColorSelect(select, hex);
    markDirty();
    return;
  }
  if (action === "keyword") {
    const value = target.value;
    target.value = "";
    if (!value.trim()) return;
    commitKeyword(index, value);
    focusCategoryKeywordInput(index);
  }
}

function handleCategoryKeydown(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.dataset.action !== "keyword") return;
  if (event.key !== "Enter" && event.key !== "," && event.key !== "，") return;
  event.preventDefault();
  const card = target.closest(".category-rule");
  const index = card ? Number(card.dataset.index) : -1;
  const value = target.value;
  if (!value.trim()) return;
  target.value = "";
  commitKeyword(index, value);
  focusCategoryKeywordInput(index);
}

function buildColorControl() {
  colorInputs.clear();
  els.colorGroups.replaceChildren();

  if (!state.colorGroups.length) {
    const empty = document.createElement("p");
    empty.className = "color-empty";
    empty.textContent = "没有可调整的颜色项";
    els.colorGroups.appendChild(empty);
    return;
  }

  for (const group of state.colorGroups) {
    const details = document.createElement("details");
    details.className = "color-group";
    details.open = true;

    const summary = document.createElement("summary");
    const label = document.createElement("span");
    label.textContent = group.label;
    const count = document.createElement("span");
    count.className = "color-count";
    count.textContent = String(group.colors.length);
    summary.append(label, count);

    const body = document.createElement("div");
    body.className = "color-group-body";
    for (const item of group.colors) {
      body.appendChild(buildColorRow(item));
    }

    details.append(summary, body);
    els.colorGroups.appendChild(details);
  }
  syncColorInputs();
}

function buildColorRow(item) {
  const value = normalizeHex(state.colors[item.key]) || item.value;

  const row = document.createElement("div");
  row.className = "color-row";

  const swatch = document.createElement("input");
  swatch.type = "color";
  swatch.className = "color-swatch";
  swatch.value = value;
  swatch.dataset.colorKey = item.key;
  swatch.dataset.role = "swatch";
  swatch.setAttribute("aria-label", `${item.label} 颜色`);

  const label = document.createElement("span");
  label.className = "color-label";
  label.textContent = item.label;
  label.title = `${item.label}（${item.key}）`;

  const hex = document.createElement("input");
  hex.type = "text";
  hex.className = "color-hex";
  hex.value = value;
  hex.maxLength = 7;
  hex.spellcheck = false;
  hex.dataset.colorKey = item.key;
  hex.dataset.role = "hex";
  hex.setAttribute("aria-label", `${item.label} 色值`);

  row.append(swatch, label, hex);
  colorInputs.set(item.key, { swatch, hex });
  return row;
}

function syncColorInputs() {
  colorInputs.forEach((pair, key) => {
    const value = normalizeHex(state.colors[key]);
    if (!value) return;
    if (pair.swatch.value !== value) pair.swatch.value = value;
    // 正在编辑 hex 文本框时不要覆盖用户输入，失焦时再归一化
    if (document.activeElement !== pair.hex) {
      pair.hex.value = value;
      pair.hex.removeAttribute("aria-invalid");
    }
  });
}

function configureRanges() {
  applyRangeConfig(els.pageWidthInput, state.limits.pageWidth);
  applyRangeConfig(els.ppiInput, state.limits.ppi);
  applyRangeConfig(els.previewPpiInput, state.limits.ppi);
  applyRangeConfig(els.singleColumnThresholdInput, state.limits.singleColumnThreshold);
  applyRangeConfig(els.giantThresholdInput, state.limits.giantThreshold);
  applyRangeConfig(els.timeoutAnalysisInput, state.limits.timeoutAnalysis);
  applyRangeConfig(els.timeoutCompileInput, state.limits.timeoutCompile);
  updateSplitHeightLimit();
}

/** 分页高度上限随输出格式变化（WebP 16383 / PNG 32000 / JPEG 65500） */
function updateSplitHeightLimit() {
  const splitLimit = state.limits.splitHeight;
  const max = splitHeightMax();
  if (els.splitHeightInput) {
    els.splitHeightInput.min = String(splitLimit.min);
    els.splitHeightInput.max = String(max);
    els.splitHeightInput.step = String(splitLimit.step);
  }
  state.splitHeight = clamp(state.splitHeight, splitLimit.min, max);
}

function applyRangeConfig(input, limit) {
  if (!input) return;
  input.min = String(limit.min);
  input.max = String(limit.max);
  input.step = String(limit.step);
}

function syncRanges() {
  const widthLimit = state.limits.pageWidth;
  els.pageWidthInput.value = String(clamp(state.pageWidth, widthLimit.min, widthLimit.max));
  setText(els.pageWidthValue, `${Math.round(state.pageWidth)} pt`);

  const splitLimit = state.limits.splitHeight;
  const splitMax = splitHeightMax();
  els.splitHeightInput.value = String(clamp(state.splitHeight, splitLimit.min, splitMax));
  setText(els.splitHeightValue, `${Math.round(state.splitHeight)} px`);

  const ppiLimit = state.limits.ppi;
  els.ppiInput.value = String(clamp(state.ppi, ppiLimit.min, ppiLimit.max));
  setText(els.ppiValue, `${Math.round(state.ppi)} ppi`);
  const testPpi = clamp(state.testPpi, ppiLimit.min, ppiLimit.max);
  els.previewPpiInput.value = String(testPpi);
  setText(els.previewPpiValue, `${Math.round(testPpi)} ppi`);

  const singleColumnLimit = state.limits.singleColumnThreshold;
  els.singleColumnThresholdInput.value = String(
    clamp(state.singleColumnThreshold, singleColumnLimit.min, singleColumnLimit.max),
  );
  setText(els.singleColumnThresholdValue, `${Math.round(state.singleColumnThreshold)} pt`);

  const giantLimit = state.limits.giantThreshold;
  els.giantThresholdInput.value = String(
    clamp(state.giantThreshold, giantLimit.min, giantLimit.max),
  );
  setText(els.giantThresholdValue, `${Math.round(state.giantThreshold)} px`);

  const analysisLimit = state.limits.timeoutAnalysis;
  els.timeoutAnalysisInput.value = String(
    clamp(state.timeoutAnalysis, analysisLimit.min, analysisLimit.max),
  );
  setText(els.timeoutAnalysisValue, `${Math.round(state.timeoutAnalysis)} s`);

  const compileLimit = state.limits.timeoutCompile;
  els.timeoutCompileInput.value = String(
    clamp(state.timeoutCompile, compileLimit.min, compileLimit.max),
  );
  setText(els.timeoutCompileValue, `${Math.round(state.timeoutCompile)} s`);

  if (els.outputFormatSelect) {
    els.outputFormatSelect.value = state.outputFormat;
  }
}

/* ==========================================================================
   控件同步（只在初始化/恢复默认/导入配置/切预设时整体刷新）
   ========================================================================== */

function syncControls() {
  syncModeControl();

  if (document.activeElement !== els.queryInput) {
    els.queryInput.value = state.query;
  }
  els.queryInput.maxLength = state.limits.maxQueryLen;
  updateQueryClear();

  syncPresetControl();
  syncRanges();
  els.toggleTwoLines.checked = state.pluginTwoLines;
  els.toggleHero.checked = state.heroHeader;
  updateBackgroundVisibility();
  syncBackgroundControl();
  syncPluginControl();
  syncCategoryControl();

  els.fontSearch.value = "";
  renderFontList();
  buildFontChips();
  syncColorInputs();
}

function updateQueryClear() {
  show(els.queryClear, Boolean(state.query));
}

function updateBackgroundVisibility() {
  show(els.backgroundRow, state.heroHeader);
}

function buildFontChips() {
  els.fontChips.replaceChildren();
  if (!state.selectedFonts.length) {
    const empty = document.createElement("span");
    empty.className = "font-chips-empty";
    empty.textContent = "未选择字体，跟随插件配置";
    els.fontChips.appendChild(empty);
    return;
  }
  state.selectedFonts.forEach((name, index) => {
    const chip = document.createElement("span");
    chip.className = "font-chip";

    const order = document.createElement("span");
    order.className = "font-chip-order";
    order.textContent = String(index + 1);

    const label = document.createElement("span");
    label.className = "font-chip-name";
    label.textContent = name;
    label.title = name;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "font-chip-remove";
    remove.dataset.font = name;
    remove.textContent = "×";
    remove.title = `移除 ${name}`;
    remove.setAttribute("aria-label", `移除字体 ${name}`);

    chip.append(order, label, remove);
    els.fontChips.appendChild(chip);
  });
}

function renderFontList() {
  const keyword = state.fontFilter.trim().toLowerCase();
  const pool = keyword
    ? state.fonts.filter((name) => name.toLowerCase().includes(keyword))
    : state.fonts;

  els.fontList.replaceChildren();
  if (!pool.length) {
    const empty = document.createElement("p");
    empty.className = "font-list-empty";
    empty.textContent = keyword ? "没有匹配的字体" : "没有发现可用字体";
    els.fontList.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const name of pool) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "font-item";
    item.dataset.font = name;
    item.setAttribute("role", "checkbox");
    item.setAttribute("aria-checked", String(state.selectedFonts.includes(name)));

    const check = document.createElement("span");
    check.className = "font-check";
    check.setAttribute("aria-hidden", "true");

    const label = document.createElement("span");
    label.className = "font-name";
    label.textContent = name;

    item.append(check, label);
    fragment.appendChild(item);
  }
  els.fontList.appendChild(fragment);
}

function syncFontListStates() {
  for (const item of els.fontList.querySelectorAll(".font-item")) {
    item.setAttribute("aria-checked", String(state.selectedFonts.includes(item.dataset.font)));
  }
}

/* ==========================================================================
   控件交互
   ========================================================================== */

function bindStaticEvents() {
  if (state.listenersBound) return;
  state.listenersBound = true;

  els.zoomOut.addEventListener("click", () => changeZoom(-ZOOM_STEP));
  els.zoomIn.addEventListener("click", () => changeZoom(ZOOM_STEP));
  els.zoomFit.addEventListener("click", () => {
    state.fitWidth = true;
    applyZoom();
  });
  els.openImage.addEventListener("click", downloadCurrentImage);

  els.errorRetry.addEventListener("click", () => {
    if (state.options) {
      void requestRender();
      return;
    }
    state.fatalError = "";
    state.renderError = "";
    renderPreview();
    void init();
  });

  els.modeSegmented.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("button[data-mode]") : null;
    if (!button || button.dataset.mode === state.mode) return;
    state.mode = button.dataset.mode;
    syncModeControl();
    markDirty();
  });

  els.queryInput.addEventListener("input", () => {
    state.query = els.queryInput.value;
    updateQueryClear();
    markDirty();
  });
  els.queryClear.addEventListener("click", () => {
    state.query = "";
    els.queryInput.value = "";
    updateQueryClear();
    els.queryInput.focus();
    markDirty();
  });

  els.presetList.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.closest(".preset-rename")) return;
    const action = target.closest("[data-action]");
    if (action) {
      const index = Number(action.dataset.presetIndex);
      if (action.dataset.action === "add-preset") addCustomPreset();
      else if (action.dataset.action === "rename-preset") startRenamePreset(index);
      else if (action.dataset.action === "delete-preset") removeCustomPreset(index);
      return;
    }
    const card = target.closest(".preset-card");
    if (!card) return;
    if (state.pendingDeleteIndex >= 0) {
      state.pendingDeleteIndex = -1;
      buildPresetControl();
    }
    applyPreset(card.dataset.preset);
  });

  // 改名输入框：回车保存、Esc 取消、失焦保存（改完直接点别处也不丢）
  els.presetList.addEventListener("keydown", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.dataset.renameIndex === undefined) return;
    if (event.key === "Enter") {
      event.preventDefault();
      input.blur();
    } else if (event.key === "Escape") {
      event.preventDefault();
      state.renamingIndex = -1;
      buildPresetControl();
    }
  });
  els.presetList.addEventListener("focusout", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.dataset.renameIndex === undefined) return;
    commitRenamePreset(Number(input.dataset.renameIndex), input.value);
  });

  els.pageWidthInput.addEventListener("input", () => {
    state.pageWidth = Number(els.pageWidthInput.value);
    setText(els.pageWidthValue, `${Math.round(state.pageWidth)} pt`);
    markDirty();
  });
  els.splitHeightInput.addEventListener("input", () => {
    state.splitHeight = Number(els.splitHeightInput.value);
    setText(els.splitHeightValue, `${Math.round(state.splitHeight)} px`);
    markDirty();
  });
  els.ppiInput.addEventListener("input", () => {
    state.ppi = Number(els.ppiInput.value);
    setText(els.ppiValue, `${Math.round(state.ppi)} ppi`);
    markDirty();
  });
  els.previewPpiInput.addEventListener("input", () => {
    state.testPpi = Number(els.previewPpiInput.value);
    setText(els.previewPpiValue, `${Math.round(state.testPpi)} ppi`);
    storeTestPpi(state.testPpi);
    markDirty();
  });
  els.singleColumnThresholdInput.addEventListener("input", () => {
    state.singleColumnThreshold = Number(els.singleColumnThresholdInput.value);
    setText(els.singleColumnThresholdValue, `${Math.round(state.singleColumnThreshold)} pt`);
    markDirty();
  });
  els.giantThresholdInput.addEventListener("input", () => {
    state.giantThreshold = Number(els.giantThresholdInput.value);
    setText(els.giantThresholdValue, `${Math.round(state.giantThreshold)} px`);
    markDirty();
  });
  els.outputFormatSelect.addEventListener("change", () => {
    state.outputFormat = els.outputFormatSelect.value;
    // 切换格式会改变可承载的单页高度，超限时回落到新格式的最大值
    updateSplitHeightLimit();
    syncRanges();
    markDirty();
  });
  els.timeoutAnalysisInput.addEventListener("input", () => {
    state.timeoutAnalysis = Number(els.timeoutAnalysisInput.value);
    setText(els.timeoutAnalysisValue, `${Math.round(state.timeoutAnalysis)} s`);
    markDirty();
  });
  els.timeoutCompileInput.addEventListener("input", () => {
    state.timeoutCompile = Number(els.timeoutCompileInput.value);
    setText(els.timeoutCompileValue, `${Math.round(state.timeoutCompile)} s`);
    markDirty();
  });

  els.toggleTwoLines.addEventListener("change", () => {
    state.pluginTwoLines = els.toggleTwoLines.checked;
    markDirty();
  });
  els.toggleHero.addEventListener("change", () => {
    state.heroHeader = els.toggleHero.checked;
    updateBackgroundVisibility();
    markDirty();
  });
  els.backgroundSelect.addEventListener("change", () => {
    state.background = els.backgroundSelect.value;
    markDirty();
  });

  els.pluginSearch.addEventListener("input", () => {
    state.pluginFilter = els.pluginSearch.value;
    // 搜索只过滤显示，不影响渲染结果，所以不 markDirty
    renderPluginList();
  });
  els.pluginList.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") return;
    const name = target.value;
    if (!name) return;
    const index = state.ignoredSelected.indexOf(name);
    if (target.checked) {
      if (index < 0) state.ignoredSelected.push(name);
    } else if (index >= 0) {
      state.ignoredSelected.splice(index, 1);
    }
    updatePluginSelfHint();
    updatePluginSummary();
    markDirty();
  });
  els.pluginCustom.addEventListener("input", () => {
    state.ignoredCustom = normalizeNameList(els.pluginCustom.value.split(/\r?\n/));
    updatePluginSummary();
    markDirty();
  });

  if (els.categoryAdd) els.categoryAdd.addEventListener("click", addCategoryRule);
  if (els.categoryStandard) {
    els.categoryStandard.addEventListener("click", applyStandardCategories);
  }
  if (els.categoryFallback) {
    els.categoryFallback.addEventListener("input", () => {
      state.categoryFallback = els.categoryFallback.value;
      updateCategorySummary();
      markDirty();
    });
  }
  if (els.categoryFallbackColor) {
    els.categoryFallbackColor.addEventListener("change", () => {
      let value = els.categoryFallbackColor.value;
      if (value === "__custom__") value = "#5b8def";
      state.categoryFallbackColor = normalizeRuleColor(value);
      // 重画下拉，避免「自定义颜色…」一直停在选中态
      rebuildCategoryColorSelect(
        els.categoryFallbackColor,
        state.categoryFallbackColor,
        "默认（槽 0）",
        "fallback-color",
      );
      syncFallbackColorPicker();
      markDirty();
    });
  }
  if (els.categoryFallbackPicker) {
    els.categoryFallbackPicker.addEventListener("change", () => {
      const hex = normalizeHex(els.categoryFallbackPicker.value);
      if (!hex) return;
      state.categoryFallbackColor = hex;
      updateCategoryColorSelect(els.categoryFallbackColor, hex);
      markDirty();
    });
  }
  if (els.categoryHotWords) {
    els.categoryHotWords.addEventListener("click", (event) => {
      const button = event.target instanceof Element ? event.target.closest(".hot-word") : null;
      if (!button || !button.dataset.word) return;
      addKeywordToSelectedRule(button.dataset.word);
    });
  }
  if (els.categoryRules) {
    els.categoryRules.addEventListener("click", handleCategoryClick);
    els.categoryRules.addEventListener("input", handleCategoryInput);
    els.categoryRules.addEventListener("change", handleCategoryChange);
    els.categoryRules.addEventListener("keydown", handleCategoryKeydown);
  }

  els.fontSearch.addEventListener("input", () => {
    state.fontFilter = els.fontSearch.value;
    renderFontList();
  });
  els.fontList.addEventListener("click", (event) => {
    const item = event.target instanceof Element ? event.target.closest(".font-item") : null;
    if (!item || !item.dataset.font) return;
    toggleFont(item.dataset.font);
  });
  els.fontChips.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest(".font-chip-remove") : null;
    if (!button || !button.dataset.font) return;
    removeFont(button.dataset.font);
  });

  els.colorGroups.addEventListener("input", handleColorInput);
  els.colorGroups.addEventListener("change", handleColorCommit);
  els.restoreColors.addEventListener("click", restorePresetColors);

  if (els.reloadFonts) {
    els.reloadFonts.addEventListener("click", () => {
      void reloadFonts();
    });
  }

  els.btnReset.addEventListener("click", () => {
    resetToDefaults();
  });
  els.btnImport.addEventListener("click", () => {
    void importCurrentConfig();
  });
  els.btnApply.addEventListener("click", () => {
    void applyConfig();
  });
  els.btnRefresh.addEventListener("click", () => {
    cancelScheduledRender();
    void requestRender();
  });

  window.addEventListener("resize", () => {
    if (state.fitWidth) applyZoom();
  });
  if (typeof ResizeObserver === "function") {
    // 侧栏折叠、iframe 尺寸变化时 clientWidth 变化不一定触发 window.resize
    const observer = new ResizeObserver(() => {
      if (state.fitWidth) applyZoom();
    });
    observer.observe(els.viewport);
  }
}

function handleColorInput(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const key = target.dataset.colorKey;
  const role = target.dataset.role;
  if (!key || !role) return;
  const pair = colorInputs.get(key);
  if (!pair) return;

  if (role === "swatch") {
    const value = normalizeHex(target.value);
    if (!value) return;
    state.colors[key] = value;
    pair.hex.value = value;
    pair.hex.removeAttribute("aria-invalid");
  } else {
    const value = normalizeHex(target.value);
    if (!value) {
      // 非法 hex 不写入状态，只做视觉标红
      target.setAttribute("aria-invalid", "true");
      return;
    }
    target.removeAttribute("aria-invalid");
    state.colors[key] = value;
    pair.swatch.value = value;
  }

  // 改色一律落到自定义模板：内置预设只读，首条自定义模板承接改动
  syncActivePresetColors();
  markDirty();
}

function handleColorCommit(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement) || target.dataset.role !== "hex") return;
  const key = target.dataset.colorKey;
  const value = key ? normalizeHex(state.colors[key]) : null;
  if (!key || !value) return;
  target.value = value;
  target.removeAttribute("aria-invalid");
}

function applyPreset(name) {
  const preset = findPreset(name);
  if (!preset) return;
  state.preset = preset.name;
  Object.assign(state.colors, preset.colors);
  syncColorInputs();
  syncPresetControl();
  markDirty();
}

function restorePresetColors() {
  const preset =
    findPreset(state.preset) || state.presets[0] || state.customPresets[0] || null;
  if (!preset) return;
  state.preset = preset.name;
  Object.assign(state.colors, preset.colors);
  syncColorInputs();
  syncPresetControl();
  markDirty();
  setNotice(`已套用「${presetLabel(preset)}」主题色`);
}

function toggleFont(name) {
  const index = state.selectedFonts.indexOf(name);
  if (index >= 0) {
    state.selectedFonts.splice(index, 1);
  } else {
    state.selectedFonts.push(name);
  }
  buildFontChips();
  syncFontListStates();
  markDirty();
}

function removeFont(name) {
  const index = state.selectedFonts.indexOf(name);
  if (index < 0) return;
  state.selectedFonts.splice(index, 1);
  buildFontChips();
  syncFontListStates();
  markDirty();
}

/* ==========================================================================
   配置同步：从当前配置导入 / 应用配置
   ========================================================================== */

function buildStyleFromState(includePresets = false) {
  const style = {
    preset: state.preset,
    colors: { ...state.colors },
    fonts: [...state.selectedFonts],
    page_width: Math.round(state.pageWidth),
    ppi: Math.round(state.ppi),
    test_ppi: Math.round(state.testPpi),
    split_height: Math.round(state.splitHeight),
    single_column_threshold: Math.round(state.singleColumnThreshold),
    giant_threshold: Math.round(state.giantThreshold),
    output_format: state.outputFormat,
    timeout_analysis: Math.round(state.timeoutAnalysis),
    timeout_compile: Math.round(state.timeoutCompile),
    plugin_two_lines: state.pluginTwoLines,
    hero_header: state.heroHeader,
    background: state.background,
    ignored_plugins: [...state.ignoredSelected],
    ignored_plugins_custom: [...state.ignoredCustom],
    category: {
      fallback: state.categoryFallback,
      fallback_color: state.categoryFallbackColor,
      // 没填名称的分组没有意义，后端也会丢弃；这里先过滤，避免「应用后没变化」
      rules: state.categoryRules
        .filter((rule) => rule.name.trim())
        .map((rule) => ({
          name: rule.name,
          keywords: [...rule.keywords],
          enabled: rule.enabled,
          color: rule.color,
        })),
    },
  };
  // 预览渲染不关心模板清单，只有保存配置时才带上，避免模板改名/增删触发无谓的重渲染
  if (includePresets) {
    style.custom_presets = state.customPresets.map((item) => ({
      name: item.name,
      colors: { ...item.colors },
    }));
  }
  return style;
}

function readStoredTestPpi() {
  try {
    const value = Number(window.localStorage.getItem(TEST_PPI_KEY));
    return Number.isFinite(value) && value >= 72 && value <= 384 ? value : 144;
  } catch (error) {
    return 144;
  }
}

function storeTestPpi(value) {
  try {
    window.localStorage.setItem(TEST_PPI_KEY, String(Math.round(value)));
  } catch (error) {
    // 隐私模式等场景 localStorage 不可用，测试精度仅本次会话生效
  }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, ms)));
}

/** 恢复默认：回到打开页面时读到的配置样式，不会重新读取服务端。 */
function resetToDefaults() {
  if (!state.options || state.fatalError || state.importing || state.applying) return;
  applyActive(asObject(state.options.active));
  state.customPresets = normalizeCustomPresets(state.options.custom_presets);
  ensureCustomPreset();
  buildPresetControl();
  syncControls();
  markDirty();
  setNotice("已恢复默认样式");
}

/** 重新加载字体：让刚装进系统/自定义目录的字体立刻出现在列表里。 */
async function reloadFonts() {
  if (!bridge || !state.options || state.reloadingFonts) return;
  state.reloadingFonts = true;
  clearNotice();
  updateControlAvailability();
  try {
    const result = asObject(await bridge.apiPost("preview/fonts", {}));
    const fonts = normalizeFontList(result.fonts);
    const missing = asArray(result.missing)
      .map((name) => String(name).trim())
      .filter(Boolean);
    state.fonts = fonts;
    // 字体文件被删掉后已选条目会静默回退到别的字体，这里直接移除并提示
    const dropped = state.selectedFonts.filter((name) => !fonts.includes(name));
    if (dropped.length) {
      state.selectedFonts = state.selectedFonts.filter((name) => fonts.includes(name));
      buildFontChips();
      syncControls();
      void requestRender();
    }
    renderFontList();
    if (result.scan_ok === false) {
      setNotice("字体扫描失败，已保留原有字体列表，详情见插件日志");
    } else if (!fonts.length) {
      setNotice("没有发现可用字体，请检查字体目录后重试");
    } else if (dropped.length || missing.length) {
      setNotice(`已重新加载 ${fonts.length} 个字体；${dropped.length || missing.length} 个字体文件已失效`);
    } else {
      setNotice(`已重新加载 ${fonts.length} 个字体`);
    }
  } catch (error) {
    setNotice(`重新加载字体失败：${errorMessage(error)}`);
  } finally {
    state.reloadingFonts = false;
    updateControlAvailability();
  }
}

/** 导入当前配置：重新拉取服务端配置覆盖样式控件（未应用的修改会被丢弃）。 */
async function importCurrentConfig() {
  if (!bridge || !state.options || state.importing || state.applying) return;
  cancelScheduledRender();
  const before = JSON.stringify(buildStyleFromState(true));
  state.importing = true;
  state.renderError = "";
  clearNotice();
  renderPreview();
  try {
    const options = await bridge.apiGet("preview/options");
    applyOptions(options, { keepView: true });
    const changed = JSON.stringify(buildStyleFromState(true)) !== before;
    state.importing = false;
    if (changed) await requestRender();
    setNotice("已导入当前配置");
  } catch (error) {
    state.renderError = `导入配置失败：${errorMessage(error)}`;
  } finally {
    state.importing = false;
    renderPreview();
  }
}

/** 应用配置：把面板样式写入插件配置，插件随后自动重载使配置生效。 */
async function applyConfig() {
  if (!bridge || !state.options || state.applying) return;
  if (inFlight) {
    try {
      await inFlight;
    } catch {
      // 在途渲染失败不影响应用配置
    }
  }
  cancelScheduledRender();
  state.applying = true;
  state.renderError = "";
  clearNotice();
  renderPreview();
  try {
    const result = asObject(await bridge.apiPost("preview/apply", buildPayload(true)));
    const changed = asArray(result.changed).map((item) => String(item));
    const warnings = asArray(result.warnings).map((item) => String(item));
    if (!changed.length) {
      setNotice(warnings[0] || "面板样式与插件当前配置一致，无需应用");
      return;
    }
    if (result.reload !== true) {
      setNotice("样式已保存，但未能自动重载插件，请手动重载后生效");
      return;
    }
    setNotice("样式已保存，正在重载插件…");
    renderPreview();
    const options = await waitForAppliedConfig(buildStyleFromState(), asNumber(result.reload_in_ms, 1000));
    if (!options) {
      setNotice("配置已保存，但未能确认重载结果，请刷新页面查看");
      return;
    }
    applyOptions(options, { keepView: true });
    setNotice(`已应用 ${changed.length} 项配置`);
  } catch (error) {
    state.renderError = `应用配置失败：${errorMessage(error)}`;
  } finally {
    state.applying = false;
    renderPreview();
  }
}

/** 插件重载会短暂中断接口，轮询到配置回显与面板一致才认为生效。 */
async function waitForAppliedConfig(style, reloadInMs) {
  await sleep(reloadInMs + 400);
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    try {
      const options = await bridge.apiGet("preview/options");
      if (styleMatchesActive(asObject(options.active), style)) return options;
    } catch {
      // 重载窗口内接口暂不可用，继续重试
    }
    await sleep(400);
  }
  return null;
}

function styleMatchesActive(active, style) {
  const close = (left, right) => Math.abs(asNumber(left, -99999) - asNumber(right, -99998)) < 0.51;
  if (!close(active.page_width, style.page_width)) return false;
  if (!close(active.single_column_threshold, style.single_column_threshold)) return false;
  if (!close(active.giant_threshold, style.giant_threshold)) return false;
  if (!close(active.split_height, style.split_height)) return false;
  if (!close(active.timeout_analysis, style.timeout_analysis)) return false;
  if (!close(active.timeout_compile, style.timeout_compile)) return false;
  if (String(active.output_format || "") !== String(style.output_format || "")) return false;
  if (asBool(active.plugin_two_lines, true) !== asBool(style.plugin_two_lines, true)) return false;
  if (asBool(active.hero_header, true) !== asBool(style.hero_header, true)) return false;
  if (style.background && String(active.background || "") !== String(style.background)) return false;

  // 屏蔽名单按集合比较，勾选顺序不同不算配置变化
  const activeIgnored = asObject(active.ignored);
  if (!sameNameSet(activeIgnored.selected, style.ignored_plugins)) return false;
  if (!sameNameSet(activeIgnored.custom, style.ignored_plugins_custom)) return false;

  // 分类规则按签名比较：关键词顺序 / 大小写 / 颜色写法差异不算配置变化
  if (categorySignature(active.category) !== categorySignature(style.category)) return false;

  const currentColors = normalizeColorMap(active.colors);
  for (const [key, value] of Object.entries(normalizeColorMap(style.colors))) {
    if (currentColors[key] !== value) return false;
  }
  const appliedFonts = asArray(active.fonts).map(String);
  const expectedFonts = asArray(style.fonts).map(String).filter(Boolean);
  if (expectedFonts.length && appliedFonts.join("\u0000") !== expectedFonts.join("\u0000")) return false;
  return true;
}

/* ==========================================================================
   渲染请求：debounce + 串行化（latest-wins）
   ========================================================================== */

function markDirty() {
  if (!state.options || state.fatalError) return;
  state.dirty = true;
  scheduleRender();
}

function scheduleRender() {
  if (!state.options || !bridge || state.fatalError) return;
  if (inFlight) {
    // 在途期间不再叠定时器，等响应回来立刻用最新状态补一次
    state.pendingRerender = true;
    return;
  }
  cancelScheduledRender();
  state.debounceTimer = window.setTimeout(() => {
    state.debounceTimer = null;
    void requestRender();
  }, state.preview.debounceMs);
}

function cancelScheduledRender() {
  if (state.debounceTimer !== null) {
    window.clearTimeout(state.debounceTimer);
    state.debounceTimer = null;
  }
}

function buildPayload(includePresets = false) {
  return {
    mode: state.mode,
    query: state.query.trim(),
    style: buildStyleFromState(includePresets),
  };
}

async function requestRender() {
  if (!state.options || !bridge || state.fatalError) return;
  cancelScheduledRender();
  // 渲染状态优先于一次性提示，避免底部状态条长时间停留在旧提示上
  clearNotice();

  if (inFlight) {
    state.pendingRerender = true;
    return inFlight;
  }

  state.pendingRerender = false;
  state.dirty = false;
  state.rendering = true;
  state.renderError = "";
  const sequence = ++state.requestSeq;
  renderPreview();

  const promise = (async () => {
    try {
      const result = await bridge.apiPost("preview/render", buildPayload());
      if (sequence !== state.requestSeq) return;
      applyRenderResult(result);
    } catch (error) {
      if (sequence !== state.requestSeq) return;
      state.renderError = describeRenderError(error);
    } finally {
      if (sequence === state.requestSeq) {
        state.rendering = false;
        renderPreview();
      }
    }
  })();

  inFlight = promise;
  try {
    await promise;
  } finally {
    if (inFlight === promise) inFlight = null;
    if (state.pendingRerender) {
      state.pendingRerender = false;
      void requestRender();
    }
  }
}

function describeRenderError(error) {
  const message = errorMessage(error);
  if (/timeout|timed out|超时/i.test(message)) return `渲染超时：${message}`;
  if (/background|背景图/i.test(message)) return `背景图不可用：${message}`;
  return message;
}

function applyRenderResult(rawResult) {
  const result = asObject(rawResult);
  const images = [];

  asArray(result.images).forEach((rawImage, index) => {
    const image = asObject(rawImage);
    if (typeof image.data !== "string" || !image.data) return;
    images.push({
      page: asNumber(image.page, index + 1),
      mime: typeof image.mime === "string" && image.mime ? image.mime : "image/webp",
      data: image.data,
      width: asNumber(image.width, 0),
      height: asNumber(image.height, 0),
    });
  });
  images.sort((left, right) => left.page - right.page);

  state.images = images;
  state.warnings = asArray(result.warnings).map((warning) => String(warning)).filter(Boolean);
  state.renderError = "";
  state.lastRender = {
    elapsedMs: Math.max(0, asNumber(result.elapsed_ms, 0)),
    cached: result.cached === true,
    totalPages: Math.max(images.length, asNumber(result.total_pages, images.length)),
    truncated: result.truncated === true,
    width: images[0] ? images[0].width : 0,
    height: images[0] ? images[0].height : 0,
    at: Date.now(),
  };

  renderStage();
  renderPreview();
}

/* ==========================================================================
   预览渲染
   ========================================================================== */

function renderStage() {
  const fragment = document.createDocumentFragment();

  state.images.forEach((image, index) => {
    const page = document.createElement("div");
    page.className = "preview-page";
    page.dataset.width = String(image.width || 0);
    // 后端未给尺寸时先占满可用宽度，等图片 load 后再按 naturalWidth 计算缩放
    if (!image.width) page.style.width = "100%";

    const img = document.createElement("img");
    img.src = `data:${image.mime};base64,${image.data}`;
    img.alt = `第 ${image.page} 页预览`;
    img.decoding = "async";
    img.draggable = false;
    if (index > 0) img.loading = "lazy";
    // 后端没给尺寸时，等图片解码后用 naturalWidth 兜住缩放计算
    img.addEventListener("load", () => {
      if (!Number(page.dataset.width) && img.naturalWidth) {
        page.dataset.width = String(img.naturalWidth);
        applyZoom();
      }
    });

    const totalPages = Math.max(
      state.lastRender ? state.lastRender.totalPages : 0,
      state.images.length,
    );
    const badge = document.createElement("span");
    badge.className = "page-badge";
    badge.textContent = totalPages > 1 ? `第 ${image.page} / 共 ${totalPages} 页` : `第 ${image.page} 页`;

    page.append(img, badge);
    fragment.appendChild(page);
  });

  els.stage.replaceChildren(fragment);
  applyZoom();
}

function renderPreview() {
  const hasImages = state.images.length > 0;
  const fatal = Boolean(state.fatalError);
  const failed = Boolean(state.renderError);
  const loading = state.rendering;
  const firstLoad = !state.lastRender;

  show(els.skeleton, !hasImages && !fatal && !failed && (loading || firstLoad));
  setText(els.skeletonText, state.options ? "正在渲染预览…" : "正在加载预览…");

  show(els.empty, !hasImages && !fatal && !failed && Boolean(state.lastRender));
  show(els.previewHint, !fatal && Boolean(state.lastRender && state.lastRender.totalPages > 1));
  show(els.loading, loading && hasImages);
  els.stage.classList.toggle("is-stale", loading && hasImages);

  show(els.error, failed || fatal);
  if (failed || fatal) {
    setText(els.errorTitle, fatal ? "无法加载预览" : "渲染失败");
    setText(els.errorText, fatal ? state.fatalError : state.renderError);
    setText(els.errorRetry, fatal ? "重新加载" : "重试");
  }

  els.openImage.disabled = !hasImages;
  els.app.classList.toggle("is-fatal", fatal);
  updateMeta();
  updateStatus();
  updateControlAvailability();
}

function updateControlAvailability() {
  const disabled = !state.options || Boolean(state.fatalError);
  const busy = state.importing || state.applying;
  els.btnReset.disabled = disabled || busy;
  els.btnImport.disabled = disabled || busy;
  els.btnApply.disabled = disabled || busy;
  els.btnRefresh.disabled = disabled || state.applying;
  if (els.reloadFonts) els.reloadFonts.disabled = disabled || busy || state.reloadingFonts;
  els.previewPpiInput.disabled = disabled || busy;
  if ("inert" in els.controlsBody) els.controlsBody.inert = Boolean(state.fatalError) || busy;
}

function updateMeta() {
  const render = state.lastRender;

  if (!state.images.length) {
    setText(els.metaPages, render ? "0 页" : "");
  } else {
    const count = state.images.length;
    const total = Math.max(render ? render.totalPages : 0, count);
    let text = total > count ? `第 1–${count} 页 · 共 ${total} 页` : `${count} 页`;
    if (render && render.truncated) text += " · 已截断";
    setText(els.metaPages, text);
  }

  if (!render) {
    setText(els.metaRender, "");
    els.metaRender.removeAttribute("title");
    return;
  }

  const size = render.width && render.height ? `${render.width}×${render.height}` : "";
  const parts = [`渲染于 ${formatSeconds(render.elapsedMs)}`, size].filter(Boolean);
  setText(els.metaRender, parts.join(" · "));
  if (state.warnings.length) {
    els.metaRender.title = state.warnings.join("\n");
  } else {
    els.metaRender.removeAttribute("title");
  }
}

function updateStatus() {
  let topState = "idle";
  let topText = "准备就绪";
  let footerState = "idle";
  let footerText = "尚未渲染";

  if (state.fatalError) {
    topState = "error";
    topText = "加载失败";
    footerState = "error";
    footerText = "加载失败";
  } else if (!state.options) {
    topState = "loading";
    topText = "正在加载…";
    footerState = "loading";
    footerText = "正在加载…";
  } else if (state.applying) {
    topState = "loading";
    topText = "正在应用配置…";
    footerState = "loading";
    footerText = "正在应用配置…";
  } else if (state.importing) {
    topState = "loading";
    topText = "正在导入配置…";
    footerState = "loading";
    footerText = "正在导入配置…";
  } else if (state.rendering) {
    topState = "loading";
    topText = "正在渲染…";
    footerState = "loading";
    footerText = "正在渲染…";
  } else if (state.renderError) {
    topState = "error";
    topText = "渲染失败";
    footerState = "error";
    footerText = "渲染失败";
  } else if (state.lastRender) {
    const seconds = formatSeconds(state.lastRender.elapsedMs);
    topState = "ok";
    topText = `已更新 · ${seconds}`;
    footerState = "ok";
    footerText = `已更新 · ${seconds}`;
  }

  els.topbarStatus.dataset.state = topState;
  setText(els.topbarStatusText, topText);

  els.footerStatus.dataset.state = footerState;
  setText(els.footerStatusText, state.notice || footerText);
  els.footerCached.hidden = !(
    state.lastRender &&
    state.lastRender.cached &&
    !state.rendering &&
    !state.renderError &&
    !state.notice
  );

  setText(els.footerError, state.renderError);
  show(els.footerError, Boolean(state.renderError));
}

/* ==========================================================================
   缩放与图片操作
   ========================================================================== */

function computeFitScale() {
  const imageWidth = state.images[0] ? state.images[0].width : 0;
  // 24px 是 stage 两侧内边距
  const available = els.viewport.clientWidth - 48;
  if (!imageWidth || available <= 0) return state.zoom || 1;
  return clamp(available / imageWidth, ZOOM_MIN, 1);
}

function changeZoom(delta) {
  if (!state.images.length) return;
  state.fitWidth = false;
  state.zoom = clamp(Math.round((state.zoom + delta) * 100) / 100, ZOOM_MIN, ZOOM_MAX);
  applyZoom();
}

function applyZoom() {
  if (!state.images.length) {
    state.zoom = 1;
    updateZoomLabel();
    return;
  }
  if (state.fitWidth) state.zoom = computeFitScale();
  const scale = clamp(state.zoom, ZOOM_MIN, ZOOM_MAX);

  for (const page of els.stage.querySelectorAll(".preview-page")) {
    const image = page.querySelector("img");
    const naturalWidth = Number(page.dataset.width) || (image ? image.naturalWidth : 0) || 0;
    if (!naturalWidth) continue;
    page.style.width = `${Math.round(naturalWidth * scale)}px`;
  }

  updateZoomLabel();
  els.zoomFit.classList.toggle("is-active", state.fitWidth);
  els.zoomFit.setAttribute("aria-pressed", String(state.fitWidth));
}

function updateZoomLabel() {
  setText(els.zoomValue, `${Math.round((state.fitWidth ? computeFitScale() : state.zoom) * 100)}%`);
}

function downloadCurrentImage() {
  const images = state.images;
  if (!images.length) return;

  setNotice(images.length > 1 ? `已开始下载 ${images.length} 页` : "已开始下载第 1 页");
  // 首张留在点击手势内直接触发，其余逐页错开：同步连发会被浏览器合并或丢弃
  downloadImage(images[0]);
  images.slice(1).forEach((image, index) => {
    window.setTimeout(() => downloadImage(image), DOWNLOAD_STAGGER_MS * (index + 1));
  });
}

function downloadImage(image) {
  const link = document.createElement("a");
  link.href = `data:${image.mime};base64,${image.data}`;
  link.download = `help-panel-preview-${image.page}.${extensionForMime(image.mime)}`;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/* ==========================================================================
   启动
   ========================================================================== */

renderPreview();
void init();
