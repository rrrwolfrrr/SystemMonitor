/* SystemMonitor standalone theme package: styling and behavior in one file. */

(function (global) {
function createAnalogGaugeTheme(api) {
  var STORAGE_KEY = "systemMonitorAnalogGaugeTheme.v1";
  var savedState = {};
  try { savedState = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") || {}; }
  catch (error) { console.error("Не удалось загрузить настройки темы приборов:", error); }
  var state = savedState.state && typeof savedState.state === "object"
      ? savedState.state : { displayMode: "cards", analogGauges: [] },
      layout = savedState.layout && typeof savedState.layout === "object" ? savedState.layout : {};
  if (!Array.isArray(state.analogGauges)) state.analogGauges = [];
  if (state.displayMode !== "analog-gauges") state.displayMode = "cards";
  function persistThemeState() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ state: state, layout: layout })); }
    catch (error) { console.error("Не удалось сохранить настройки темы приборов:", error); showToast("Не удалось сохранить настройки приборов", "error"); }
  }
  var board = api.board,
      sourceData = api.sourceData,
      sourceErrors = api.sourceErrors,
      selectableSensorEntries = api.selectableSensorEntries,
      sensorDeviceLabel = api.sensorDeviceLabel,
      defaultLabelForSensorKey = api.defaultLabelForSensorKey,
      getDataSources = api.getDataSources,
      fmt = api.fmt,
      el = api.el,
      clearNode = api.clearNode,
      makeDraggable = api.makeDraggable,
      saveState = persistThemeState,
      saveLayout = saveAnalogGaugeLayout,
      showToast = api.showToast,
      openModal = api.openModal,
      closeModal = api.closeModal,
      alignValueToGrid = api.alignValueToGrid,
      applyBoardGrid = api.applyBoardGrid,
      adjustBoardHeight = api.adjustBoardHeight,
      createCards = api.createCards,
      renderCachedSources = api.renderCachedSources,
      zCounter = api.getZCounter(),
      unregisterBoardView = null;

function saveAnalogGaugeLayout() {
  api.saveLayout();
  state.analogGauges.forEach(function (gauge) {
    var card = board.querySelector('[data-gauge-id="' + gauge.id + '"]');
    if (!card) return;
    layout[gauge.id] = {
      left: Math.round(card.offsetLeft),
      top: Math.round(card.offsetTop),
      width: Math.round(card.offsetWidth),
      height: Math.round(card.offsetHeight),
      z: Math.min(4000, Math.max(1, Number(card.style.zIndex) || 1))
    };
  });
  persistThemeState();
}

/* Sentinel-значения, которые не двигают стрелку */
var ANALOG_GAUGE_SENTINELS = new Set([-999, -9999, -2147483648]);

/* Переключить режим отображения дашборда (карточки / приборы) */
function applyDashboardDisplayMode() {
  var enabled = state.displayMode === "analog-gauges",
      button = document.getElementById("analogGaugeThemeModeBtn"),
      addButton = document.getElementById("analogGaugeThemeAddBtn");
  document.body.classList.toggle("analog-gauge-mode", enabled);
  if (board) board.classList.toggle("analog-gauge-board", enabled);
  if (button) {
    button.textContent = enabled ? "\u25A6 Карточки" : "\u25B4 Стрелочные приборы";
    button.setAttribute("aria-pressed", enabled ? "true" : "false");
    button.title = enabled
      ? "Вернуться к карточкам Dashboard"
      : "Показать датчики как аналоговые приборы";
  }
  if (addButton) addButton.classList.toggle("hidden", !enabled);
}

/* Проверка валидности показания для стрелочного прибора */
function isValidAnalogGaugeReading(value) {
  return typeof value === "number" && Number.isFinite(value) && !ANALOG_GAUGE_SENTINELS.has(value);
}

/* Проверка валидности сенсора */
function analogGaugeHasValidReading(sensor) {
  return !!sensor && sensor.valid !== false && isValidAnalogGaugeReading(sensor.value);
}

/* Статус недоступности сенсора */
function analogGaugeUnavailableStatus(sensor) {
  if (sensor && sensor.hardware_type === "Cpu" && sensor.reason === "zero") {
    return "CPU-сенсор вернул 0; попробуйте запустить SystemMonitor от имени администратора";
  }
  if (sensor && sensor.reason === "zero") {
    return "Источник вернул 0 — проверьте доступность датчика";
  }
  if (sensor && sensor.reason === "missing") {
    return "Источник не предоставил значение";
  }
  return sensor ? "Нет показаний" : "Датчик недоступен";
}

/* Подбор сенсора для прибора с fallback на CPU-частоту */
function analogGaugeSensorForEntry(data, sensor) {
  if (analogGaugeHasValidReading(sensor)) return sensor;
  var name = String(sensor && sensor.name || ""),
      cpu = data && data.cpu,
      frequency = cpu && cpu.frequency;
  if (!sensor || sensor.hardware_type !== "Cpu" || sensor.type !== "Clock" ||
      !/^Cores \(Average(?: Effective)?\)$/i.test(name) ||
      !isValidAnalogGaugeReading(frequency) || frequency <= 0) {
    return sensor;
  }
  var metadata = data.metadata && data.metadata["cpu.frequency"];
  return Object.assign({}, sensor, {
    value: frequency,
    unit: sensor.unit || "MHz",
    valid: true,
    reason: null,
    fallbackSource: metadata && metadata.source || "резервный источник"
  });
}

/* Получить текущее показание сенсора для прибора */
function analogGaugeSensor(gauge) {
  var data = sourceData[gauge.sourceId];
  if (!data) return null;
  var entry = selectableSensorEntries(data).find(function (item) {
    return item.key === gauge.sensorKey;
  });
  return entry ? analogGaugeSensorForEntry(data, entry.sensor) : null;
}

/* Метка сенсора для прибора */
function analogGaugeSensorLabel(sensor, sensorKey) {
  if (!sensor) return defaultLabelForSensorKey(sensorKey);
  return [sensorDeviceLabel(sensor), sensor.name || "Датчик"].filter(Boolean).join(" \u00b7 ");
}

/* Диапазон шкалы по умолчанию по типу сенсора */
function analogGaugeDefaultRange(sensor) {
  var type = String(sensor && sensor.type || "").toLowerCase(),
      value = analogGaugeHasValidReading(sensor) ? sensor.value : 0;
  if (type === "temperature") return { min: -20, max: 120 };
  if (type === "load" || type === "level") return { min: 0, max: 100 };
  if (type === "voltage") return { min: 0, max: 5 };
  if (type === "power") return { min: 0, max: 500 };
  if (type === "clock" || type === "frequency") return { min: 0, max: 10000 };
  if (type === "fan") return { min: 0, max: 10000 };
  if (type === "current") return { min: -10, max: 10 };
  if (value < 0) return { min: Math.floor(value * 1.25), max: 0 };
  return { min: 0, max: Math.max(1, Math.ceil(value * 1.25)) };
}

/* Форматирование метки деления шкалы */
function formatAnalogGaugeTick(value) {
  var absolute = Math.abs(value), scaled = value, suffix = "";
  if (absolute >= 1000000) { scaled = value / 1000000; suffix = "M"; }
  else if (absolute >= 1000) { scaled = value / 1000; suffix = "k"; }
  var text = Number.isInteger(scaled) ? String(scaled) : scaled.toFixed(Math.abs(scaled) < 10 ? 1 : 0);
  return text + suffix;
}

/* Создание SVG шкалы прибора */
function createAnalogGaugeSvg(gauge) {
  var namespace = "http://www.w3.org/2000/svg",
      svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("class", "analog-gauge-svg");
  svg.setAttribute("viewBox", "0 0 480 176");
  svg.setAttribute("aria-hidden", "true");
  var arc = document.createElementNS(namespace, "path");
  arc.setAttribute("class", "analog-gauge-arc");
  arc.setAttribute("d", "M 40 100 Q 240 8 440 100");
  svg.appendChild(arc);
  for (var index = 0; index <= 40; index++) {
    var position = index / 40,
        x1 = 40 + 400 * position,
        y1 = 100 - 184 * position * (1 - position);
    var slope = .46 * (2 * position - 1),
        normalLength = Math.sqrt(1 + slope * slope);
    var tickLength = index % 10 === 0 ? 12 : index % 5 === 0 ? 8 : 4;
    var tick = document.createElementNS(namespace, "line");
    tick.setAttribute("class", "analog-gauge-tick");
    tick.setAttribute("x1", x1.toFixed(2));
    tick.setAttribute("y1", y1.toFixed(2));
    tick.setAttribute("x2", (x1 - slope * tickLength / normalLength).toFixed(2));
    tick.setAttribute("y2", (y1 + tickLength / normalLength).toFixed(2));
    tick.setAttribute("stroke-width", index % 10 === 0 ? "2" : index % 5 === 0 ? "1.5" : "1");
    svg.appendChild(tick);
    if (index % 10 === 0) {
      var label = document.createElementNS(namespace, "text");
      label.setAttribute("class", "analog-gauge-label");
      label.setAttribute("x", x1.toFixed(2));
      label.setAttribute("y", (y1 - 11).toFixed(2));
      label.textContent = formatAnalogGaugeTick(gauge.min + ((gauge.max - gauge.min) * index / 40));
      svg.appendChild(label);
    }
  }
  var needleGroup = document.createElementNS(namespace, "g");
  needleGroup.setAttribute("class", "analog-gauge-needle-group");
  needleGroup.setAttribute("data-gauge-needle", "");
  var needle = document.createElementNS(namespace, "line");
  needle.setAttribute("class", "analog-gauge-needle");
  needle.setAttribute("x1", "240"); needle.setAttribute("y1", "160");
  needle.setAttribute("x2", "240"); needle.setAttribute("y2", "80");
  needleGroup.appendChild(needle);
  svg.appendChild(needleGroup);
  var hub = document.createElementNS(namespace, "circle");
  hub.setAttribute("class", "analog-gauge-hub");
  hub.setAttribute("cx", "240"); hub.setAttribute("cy", "160"); hub.setAttribute("r", "6");
  hub.setAttribute("data-gauge-hub", "");
  svg.appendChild(hub);
  return svg;
}

/* Кнопка управления прибором */
function createAnalogGaugeControl(label, title, action, disabled) {
  var button = el("button", "", label);
  button.type = "button";
  button.title = title;
  button.setAttribute("aria-label", title);
  button.disabled = !!disabled;
  button.addEventListener("click", action);
  return button;
}

/* Вычислить ширину прибора */
function analogGaugeLayoutSize(gauge) {
  return Math.min(gauge.size, Math.max(1, board.clientWidth - 24));
}

/* Вычислить высоту прибора */
function analogGaugeLayoutHeight(gauge) {
  return Math.ceil(analogGaugeLayoutSize(gauge) * .4 + 110);
}

/* Расчёт позиций приборов на доске */
function getAnalogGaugePositions() {
  var positions = {}, occupied = [], gauges = state.analogGauges,
      step = Math.max(1, Number(api.getGridSize()) || 20);
  zCounter = api.getZCounter();
  gauges.forEach(function (gauge) {
    var saved = layout && layout[gauge.id];
    if (!saved || !Number.isFinite(Number(saved.left)) || !Number.isFinite(Number(saved.top))) return;
    occupied.push({
      left: Math.max(0, Number(saved.left)),
      top: Math.max(0, Number(saved.top)),
      width: analogGaugeLayoutSize(gauge),
      height: analogGaugeLayoutHeight(gauge)
    });
  });
  gauges.forEach(function (gauge, index) {
    var saved = layout && layout[gauge.id], position;
    if (saved && Number.isFinite(Number(saved.left)) && Number.isFinite(Number(saved.top))) {
      position = {
        left: Math.max(0, Math.round(Number(saved.left))),
        top: Math.max(0, Math.round(Number(saved.top))),
        z: Math.min(4000, Math.max(1, Number(saved.z) || index + 1))
      };
    } else {
      var width = analogGaugeLayoutSize(gauge),
          height = analogGaugeLayoutHeight(gauge);
      var start = Math.max(0, alignValueToGrid(12)),
          maxLeft = Math.max(start, board.clientWidth - width - start),
          left = start, top = start, found = false;
      for (var candidateTop = start; candidateTop <= 50000 && !found; candidateTop += step) {
        for (var candidateLeft = start; candidateLeft <= maxLeft; candidateLeft += step) {
          var collision = occupied.some(function (item) {
            return candidateLeft < item.left + item.width + 16 &&
                   candidateLeft + width + 16 > item.left &&
                   candidateTop < item.top + item.height + 16 &&
                   candidateTop + height + 16 > item.top;
          });
          if (!collision) {
            left = candidateLeft; top = candidateTop; found = true; break;
          }
        }
      }
      position = { left: left, top: top, z: index + 1 };
      occupied.push({ left: position.left, top: position.top, width: width, height: height });
    }
    positions[gauge.id] = position;
    zCounter = Math.min(4000, Math.max(zCounter, position.z));
  });
  api.setZCounter(zCounter);
  return positions;
}

/* Создание DOM-элемента прибора */
function createAnalogGaugeElement(gauge, position) {
  var card = el("section", "analog-gauge dashboard-widget");
  card.dataset.gaugeId = gauge.id;
  card.dataset.layoutKey = gauge.id;
  card.style.setProperty("--analog-gauge-width", gauge.size + "px");
  card.style.left = position.left + "px";
  card.style.top = position.top + "px";
  card.style.zIndex = String(position.z);
  card.setAttribute("role", "group");
  card.setAttribute("aria-label", gauge.name);
  var face = el("div", "analog-gauge-face"),
      svg = createAnalogGaugeSvg(gauge);
  face.appendChild(svg);
  var settingsButton = createAnalogGaugeControl(
    "\u2699", "Настроить: " + gauge.name,
    function () { openAnalogGaugeEditor(gauge.id); }, false
  );
  settingsButton.className = "analog-gauge-settings";
  face.appendChild(settingsButton);
  var readout = el("output", "analog-gauge-readout", "\u2014");
  readout.dataset.gaugeReadout = "";
  readout.setAttribute("aria-label", gauge.name + " — текущее значение");
  face.appendChild(readout);
  var gaugeName = el("div", "analog-gauge-name", gauge.name);
  gaugeName.dataset.gaugeName = "";
  face.appendChild(gaugeName);
  var status = el("div", "analog-gauge-status", "\u041e\u0436\u0438\u0434\u0430\u043d\u0438\u0435 \u0434\u0430\u043d\u043d\u044b\u0445");
  status.dataset.gaugeStatus = "";
  status.setAttribute("aria-live", "off");
  face.appendChild(status);
  var minLabel = el("span", "", fmt(gauge.min, 1, ""));
  var maxLabel = el("span", "", fmt(gauge.max, 1, ""));
  var range = el("div", "analog-gauge-range");
  range.setAttribute("aria-label", "\u0414\u0438\u0430\u043f\u0430\u0437\u043e\u043d \u0448\u043a\u0430\u043b\u044b");
  range.appendChild(minLabel);
  range.appendChild(el("span", "", "\u0448\u043a\u0430\u043b\u0430"));
  range.appendChild(maxLabel);
  range.dataset.gaugeRange = "";
  face.appendChild(range);
  card.appendChild(face);
  var meter = el("meter", "analog-gauge-meter");
  meter.min = gauge.min;
  meter.max = gauge.max;
  meter.value = gauge.min;
  meter.setAttribute("aria-label", gauge.name + " — текущее значение");
  meter.dataset.gaugeMeter = "";
  card.appendChild(meter);
  if (api.isLocked()) card.classList.add("locked");
  makeDraggable(card, face);
  return card;
}

/* Обновить отображение одного прибора */
function updateAnalogGaugeReading(gauge, card) {
  if (!card) return;
  var sensor = analogGaugeSensor(gauge),
      sourceError = sourceErrors[gauge.sourceId],
      valid = !sourceError && analogGaugeHasValidReading(sensor);
  var readout = card.querySelector("[data-gauge-readout]"),
      status = card.querySelector("[data-gauge-status]"),
      needle = card.querySelector("[data-gauge-needle]"),
      hub = card.querySelector("[data-gauge-hub]"),
      meter = card.querySelector("[data-gauge-meter]");
  var range = card.querySelector("[data-gauge-range]");
  if (range) {
    range.firstElementChild.textContent = fmt(gauge.min, 1, sensor && sensor.unit || "");
    range.lastElementChild.textContent = fmt(gauge.max, 1, sensor && sensor.unit || "");
  }
  if (meter) {
    meter.min = gauge.min;
    meter.max = gauge.max;
    meter.setAttribute("aria-label", gauge.name + " — " +
      (valid ? fmt(sensor.value, 1, sensor.unit || "") : "нет показаний") +
      "; шкала от " + fmt(gauge.min, 1, sensor && sensor.unit || "") +
      " до " + fmt(gauge.max, 1, sensor && sensor.unit || ""));
  }
  if (!valid) {
    if (readout) readout.textContent = "\u2014";
    if (readout) readout.setAttribute("aria-label", gauge.name + " — нет показаний; диапазон от " +
      fmt(gauge.min, 1, sensor && sensor.unit || "") +
      " до " + fmt(gauge.max, 1, sensor && sensor.unit || ""));
    if (status) {
      status.textContent = sourceError ? "Нет связи с источником" : analogGaugeUnavailableStatus(sensor);
      status.className = "analog-gauge-status is-unavailable";
    }
    if (needle) needle.setAttribute("visibility", "hidden");
    if (hub) hub.setAttribute("visibility", "hidden");
    if (meter) {
      meter.setAttribute("aria-valuetext", "Нет показаний");
      meter.hidden = true;
    }
    return;
  }
  var value = sensor.value,
      ratio = Math.max(0, Math.min(1, (value - gauge.min) / (gauge.max - gauge.min))),
      angle = (ratio - .5) * 44,
      formattedValue = fmt(value, 1, sensor.unit || "");
  if (readout) {
    readout.textContent = formattedValue;
    readout.setAttribute("aria-label", gauge.name + " — текущее значение " + formattedValue +
      "; диапазон от " + fmt(gauge.min, 1, sensor.unit || "") +
      " до " + fmt(gauge.max, 1, sensor.unit || ""));
  }
  if (status) {
    var rangeWarning = value < gauge.min ? "Ниже диапазона" :
      value > gauge.max ? "Выше диапазона" : "";
    status.textContent = (sensor.fallbackSource ?
      "Резервный источник: " + sensor.fallbackSource +
      (rangeWarning ? " \u00b7 " : "") : "") + rangeWarning;
    status.className = "analog-gauge-status" + (rangeWarning ? " is-warning" : "");
  }
  if (needle) {
    needle.setAttribute("transform", "rotate(" + angle.toFixed(2) + " 240 160)");
    needle.removeAttribute("visibility");
  }
  if (hub) hub.removeAttribute("visibility");
  if (meter) {
    meter.value = Math.max(gauge.min, Math.min(gauge.max, value));
    meter.setAttribute("aria-valuetext", formattedValue);
    meter.hidden = false;
  }
}

/* Обновить все приборы */
function updateAnalogGauges(sourceId) {
  if (state.displayMode !== "analog-gauges" || !board) return;
  state.analogGauges.forEach(function (gauge) {
    if (sourceId && gauge.sourceId !== sourceId) return;
    updateAnalogGaugeReading(gauge, board.querySelector('[data-gauge-id="' + gauge.id + '"]'));
  });
}

/* Удалить прибор */
function removeAnalogGauge(id) {
  var gauge = state.analogGauges.find(function (item) { return item.id === id; });
  if (!gauge || !window.confirm("Удалить прибор \u00ab" + gauge.name + "\u00bb?")) return false;
  state.analogGauges = state.analogGauges.filter(function (item) { return item.id !== id; });
  delete layout[id];
  saveState(); createCards(); saveLayout(); showToast("Стрелочный индикатор удалён", "success");
  return true;
}

/* Удалить текущий прибор из редактора */
function deleteCurrentAnalogGauge() {
  if (currentAnalogGaugeId && removeAnalogGauge(currentAnalogGaugeId)) closeAnalogGaugeEditor();
}

/* Отрисовать доску приборов */
function renderAnalogGaugeBoard() {
  clearNode(board);
  var win = document.querySelector(".window");
  board.style.minHeight = win && win.classList.contains("window-resizable") ? "0" : "520px";
  if (!state.analogGauges.length) {
    var empty = el("div", "analog-gauge-empty");
    empty.appendChild(el("h2", "", "\u041f\u043e\u043a\u0430 \u043d\u0435\u0442 \u043f\u0440\u0438\u0431\u043e\u0440\u043e\u0432"));
    empty.appendChild(el("p", "", "\u0421\u043e\u0437\u0434\u0430\u0442\u0435 \u043f\u0435\u0440\u0432\u044b\u0439 \u0441\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u044b\u0439 \u0438\u043d\u0434\u0438\u043a\u0430\u0442\u043e\u0440 \u0438 \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043e\u0434\u0438\u043d \u0434\u0430\u0442\u0447\u0438\u043a \u0438\u0437 \u043a\u0430\u0442\u0430\u043b\u043e\u0433\u0430. \u0418\u0441\u0445\u043e\u0434\u043d\u044b\u0435 \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438 \u043e\u0441\u0442\u0430\u043d\u0443\u0442\u044c\u0441\u044f \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b \u0438 \u0432\u0435\u0440\u043d\u0443\u0442\u0443\u0442\u0441\u044f \u043f\u0440\u0438 \u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0438 \u0442\u0435\u043c\u044b."));
    var button = el("button", "", "\u002b \u0421\u043e\u0437\u0434\u0430\u0442\u044c \u043f\u0435\u0440\u0432\u044b\u0439 \u043f\u0440\u0438\u0431\u043e\u0440");
    button.type = "button";
    button.addEventListener("click", function () { openAnalogGaugeEditor(); });
    empty.appendChild(button);
    board.appendChild(empty);
    return;
  }
  var positions = getAnalogGaugePositions();
  state.analogGauges.forEach(function (gauge) {
    board.appendChild(createAnalogGaugeElement(gauge, positions[gauge.id]));
  });
  applyBoardGrid();
  adjustBoardHeight();
  updateAnalogGauges();
}

/* Отрисовать опции сенсоров в редакторе */
function renderAnalogGaugeSensorOptions(preferredKey) {
  var list = document.getElementById("analogGaugeSensor"),
      sourceSelect = document.getElementById("analogGaugeSource"),
      search = document.getElementById("analogGaugeSearch"),
      typeFilter = document.getElementById("analogGaugeTypeFilter");
  if (!list || !sourceSelect) return;
  var sourceId = sourceSelect.value || "local",
      term = search ? search.value.trim().toLowerCase() : "",
      selectedType = typeFilter ? typeFilter.value : "";
  var entries = selectableSensorEntries(sourceData[sourceId]),
      selectedKey = preferredKey !== undefined ? preferredKey : list.value;
  clearNode(list);
  var placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = entries.length ? "\u2014 \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043e\u0434\u0438\u043d \u0434\u0430\u0442\u0447\u0438\u043a —" : "\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0445 \u0434\u0430\u0442\u0447\u0438\u043a\u043e\u0432";
  placeholder.disabled = true;
  list.appendChild(placeholder);
  var matchedSelection = false,
      selectedSensorAvailable = entries.some(function (entry) { return entry.key === selectedKey; });
  var typeLabels = new Map(), typeOrder = new Map(), groups = new Map();
  if (typeFilter) {
    Array.prototype.forEach.call(typeFilter.options, function (option, index) {
      if (option.value) {
        typeLabels.set(option.value, option.textContent.trim());
        typeOrder.set(option.value, index);
      }
    });
  }
  entries.forEach(function (entry) {
    var sensor = analogGaugeSensorForEntry(sourceData[sourceId], entry.sensor),
        label = [sensorDeviceLabel(sensor), sensor.hardware || "", sensor.name || "Датчик"].filter(Boolean).join(" \u00b7 ");
    var searchable = (label + " " + (sensor.type || "") + " " + (sensor.unit || "")).toLowerCase();
    if ((selectedType && sensor.type !== selectedType) || (term && searchable.indexOf(term) === -1)) return;
    var option = document.createElement("option");
    option.value = entry.key;
    option.textContent = label + " [" + (sensor.type || "Датчик") + "]" +
      (sensor.valid === false ?
        (sensor.reason === "zero" ? " \u00b7 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a \u0432\u0435\u0440\u043d\u0441\u0443 \u0432\u0435\u0440\u043d\u0443 0" : " \u00b7 \u043d\u0435\u0442 \u043f\u043e\u043a\u0430\u0437\u0430\u043d\u0438\u044f") :
        "") +
      (sensor.value === null || sensor.value === undefined ? " = \u2014" : " = " + fmt(sensor.value, 1, sensor.unit));
    option.dataset.type = sensor.type || "";
    var groupKey = sensor.type || "";
    if (!groups.has(groupKey)) groups.set(groupKey, document.createElement("optgroup"));
    groups.get(groupKey).appendChild(option);
    if (entry.key === selectedKey) matchedSelection = true;
  });
  Array.from(groups.keys()).sort(function (a, b) {
    var ai = typeOrder.has(a) ? typeOrder.get(a) : Number.MAX_SAFE_INTEGER;
    var bi = typeOrder.has(b) ? typeOrder.get(b) : Number.MAX_SAFE_INTEGER;
    return ai === bi ? a.localeCompare(b) : ai - bi;
  }).forEach(function (type) {
    var group = groups.get(type);
    group.label = typeLabels.get(type) || (type || "\u0411\u0435\u0437 \u0442\u0438\u043f\u0430");
    list.appendChild(group);
  });
  if (!matchedSelection && currentAnalogGaugeId) {
    var current = state.analogGauges.find(function (gauge) { return gauge.id === currentAnalogGaugeId; });
    if (current && current.sourceId === sourceId && current.sensorKey === selectedKey) {
      var missing = document.createElement("option");
      missing.value = current.sensorKey;
      missing.textContent = defaultLabelForSensorKey(current.sensorKey) +
        (selectedSensorAvailable ? " [\u0441\u043a\u0440\u044b\u0442 \u0444\u0438\u043b\u044c\u0442\u0440\u043e\u043c]" : " [\u0434\u0430\u0442\u0447\u0438\u043a \u0441\u0435\u0439\u0447\u0430\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d]");
      list.appendChild(missing);
      matchedSelection = true;
    }
  }
  list.value = matchedSelection ? selectedKey : "";
  var saveButton = document.getElementById("analogGaugeSaveBtn");
  if (saveButton) saveButton.disabled = list.value === "";
}

/* Установить диапазон по умолчанию из выбранного сенсора */
function setAnalogGaugeDefaultRange() {
  var sourceSelect = document.getElementById("analogGaugeSource"),
      sensorSelect = document.getElementById("analogGaugeSensor");
  var saveButton = document.getElementById("analogGaugeSaveBtn");
  if (saveButton && sensorSelect) saveButton.disabled = !sensorSelect.value;
  if (!sourceSelect || !sensorSelect || !sensorSelect.value) return;
  var data = sourceData[sourceSelect.value],
      entry = selectableSensorEntries(data).find(function (item) { return item.key === sensorSelect.value; });
  var range = analogGaugeDefaultRange(entry && analogGaugeSensorForEntry(data, entry.sensor)),
      min = document.getElementById("analogGaugeMin"),
      max = document.getElementById("analogGaugeMax"),
      name = document.getElementById("analogGaugeName");
  if (min) min.value = String(range.min);
  if (max) max.value = String(range.max);
  if (name && entry) name.value = analogGaugeSensorLabel(analogGaugeSensorForEntry(data, entry.sensor), entry.key).slice(0, 80);
}

/* Открыть редактор прибора */
function openAnalogGaugeEditor(gaugeId) {
  currentAnalogGaugeId = gaugeId || null;
  var sourceSelect = document.getElementById("analogGaugeSource"),
      title = document.getElementById("analogGaugeDialogTitle"),
      name = document.getElementById("analogGaugeName"),
      min = document.getElementById("analogGaugeMin"),
      max = document.getElementById("analogGaugeMax"),
      size = document.getElementById("analogGaugeSize"),
      sizeValue = document.getElementById("analogGaugeSizeValue"),
      search = document.getElementById("analogGaugeSearch"),
      typeFilter = document.getElementById("analogGaugeTypeFilter"),
      save = document.getElementById("analogGaugeSaveBtn"),
      deleteButton = document.getElementById("analogGaugeDeleteBtn");
  var existing = currentAnalogGaugeId && state.analogGauges.find(function (gauge) { return gauge.id === currentAnalogGaugeId; });
  if (!sourceSelect || !name || !min || !max || !size || !search || !typeFilter || !save) return;
  clearNode(sourceSelect);
  getDataSources().forEach(function (source) {
    var option = document.createElement("option");
    option.value = source.id;
    option.textContent = source.name;
    sourceSelect.appendChild(option);
  });
  sourceSelect.value = existing ? existing.sourceId : "local";
  name.value = existing ? existing.name : "";
  search.value = "";
  typeFilter.value = "";
  if (title) title.textContent = existing ?
    "\u2699 \u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0441\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u043e\u0433\u043e \u0438\u043d\u0434\u0438\u043a\u0430\u0442\u043e\u0440\u0430" :
    "\u002b \u041d\u043e\u0432\u044b\u0439 \u0441\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u044b\u0439 \u0438\u043d\u0434\u0438\u043a\u0430\u0442\u043e\u0440";
  save.textContent = existing ? "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043f\u0440\u0438\u0431\u043e\u0440" : "\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u043f\u0440\u0438\u0431\u043e\u0440";
  if (deleteButton) deleteButton.classList.toggle("hidden", !existing);
  if (existing) { min.value = String(existing.min); max.value = String(existing.max); }
  else { min.value = ""; max.value = ""; }
  size.value = String(existing ? existing.size : 360);
  if (sizeValue) sizeValue.value = size.value + " px";
  renderAnalogGaugeSensorOptions(existing ? existing.sensorKey : "");
  if (!existing && document.getElementById("analogGaugeSensor").value) setAnalogGaugeDefaultRange();
  openModal("analogGaugePanel", "analogGaugeOverlay");
  document.getElementById("analogGaugeSensor").focus();
}

/* Закрыть редактор прибора */
function closeAnalogGaugeEditor() {
  currentAnalogGaugeId = null;
  closeModal("analogGaugePanel", "analogGaugeOverlay");
}

/* Сохранить прибор из формы редактора */
function saveAnalogGaugeFromForm() {
  var sourceSelect = document.getElementById("analogGaugeSource"),
      sensorSelect = document.getElementById("analogGaugeSensor");
  var nameInput = document.getElementById("analogGaugeName"),
      minInput = document.getElementById("analogGaugeMin"),
      maxInput = document.getElementById("analogGaugeMax");
  var sizeInput = document.getElementById("analogGaugeSize");
  var sourceId = sourceSelect ? sourceSelect.value : "";
  var sensorKey = sensorSelect ? sensorSelect.value : "";
  var minimum = minInput && minInput.value.trim() !== "" ? Number(minInput.value) : NaN;
  var maximum = maxInput && maxInput.value.trim() !== "" ? Number(maxInput.value) : NaN;
  var size = sizeInput ? Number(sizeInput.value) : 360;
  if (!getDataSources().some(function (source) { return source.id === sourceId; }) || !sensorKey) {
    showToast("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043e\u0434\u0438\u043d \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0439 \u0434\u0430\u0442\u0447\u0438\u043a", "warning");
    return;
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || minimum >= maximum) {
    showToast("\u041c\u0438\u043d\u0438\u043c\u0443\u043c \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u043c\u0435\u043d\u044c\u0448\u0435 \u043c\u0430\u043a\u0441\u0438\u043c\u0443\u043c\u0430", "warning");
    return;
  }
  if (!Number.isFinite(size) || size < 240 || size > 640) {
    showToast("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0448\u0438\u0440\u0438\u043d\u0443 \u043f\u0440\u0438\u0431\u043e\u0440\u0430 \u043e\u0442 240 \u0434\u043e 640 px", "warning");
    return;
  }
  var name = nameInput && nameInput.value.trim()
    ? nameInput.value.trim().slice(0, 80)
    : analogGaugeSensorLabel(analogGaugeSensor({ sourceId: sourceId, sensorKey: sensorKey }), sensorKey).slice(0, 80);
  var gauge = currentAnalogGaugeId && state.analogGauges.find(function (item) { return item.id === currentAnalogGaugeId; });
  if (gauge) {
    gauge.name = name;
    gauge.sourceId = sourceId;
    gauge.sensorKey = sensorKey;
    gauge.min = minimum;
    gauge.max = maximum;
    gauge.size = size;
  } else {
    if (state.analogGauges.length >= 60) {
      showToast("\u0414\u043e\u0441\u0442\u0438\u0433\u043d\u0443\u0442 \u043f\u0440\u0435\u0434\u0435\u043b: 60 \u043f\u0440\u0438\u0431\u043e\u0440\u043e\u0432 \u043d\u0430 \u0432\u043a\u043b\u0430\u0434\u043a\u0443", "warning");
      return;
    }
    state.analogGauges.push({
      id: "gauge-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8),
      name: name,
      sourceId: sourceId,
      sensorKey: sensorKey,
      min: minimum,
      max: maximum,
      size: size
    });
  }
  saveState();
  closeAnalogGaugeEditor();
  createCards();
  renderCachedSources();
  showToast(gauge ?
    "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u043f\u0440\u0438\u0431\u043e\u0440\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b" :
    "\u0421\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u044b\u0439 \u0438\u043d\u0434\u0438\u043a\u0430\u0442\u043e\u0440 \u0441\u043e\u0437\u0434\u0430\u043d", "success");
}

function mountThemeInterface() {
  var toolbar = api.toolbar,
      modeButton = el("button", "", "\u25B4 Стрелочные приборы"),
      addButton = el("button", "hidden", "＋ Прибор"),
      overlay = el("div", "overlay hidden"),
      panel = el("div", "modal analog-gauge-panel hidden");
  modeButton.id = "analogGaugeThemeModeBtn";
  modeButton.type = "button";
  modeButton.setAttribute("aria-pressed", "false");
  modeButton.title = "Показать датчики как аналоговые приборы";
  addButton.id = "analogGaugeThemeAddBtn";
  addButton.type = "button";
  if (api.toolbarGroup) api.toolbarGroup.hidden = false;
  overlay.id = "analogGaugeOverlay";
  panel.id = "analogGaugePanel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "true");
  panel.setAttribute("aria-labelledby", "analogGaugeDialogTitle");
  panel.innerHTML = '<h2 id="analogGaugeDialogTitle">＋ Новый стрелочный индикатор</h2><small class="muted analog-gauge-resize-hint">Потяните за нижний правый угол окна, чтобы увеличить список датчиков.</small><label class="muted" for="analogGaugeSource">Источник данных</label><select id="analogGaugeSource" class="custom-input"></select><label class="muted" for="analogGaugeTypeFilter">Тип датчика</label><select id="analogGaugeTypeFilter" class="custom-input" aria-label="Тип датчика"></select><label class="muted" for="analogGaugeSearch">Поиск по датчикам</label><input id="analogGaugeSearch" class="custom-input" type="search" placeholder="Устройство, датчик или тип"><label class="muted" for="analogGaugeSensor">Датчик — выберите один</label><select id="analogGaugeSensor" class="custom-input" size="7" aria-describedby="analogGaugeSensorHint"></select><small id="analogGaugeSensorHint" class="muted">Каждый прибор показывает ровно один датчик.</small><label class="muted" for="analogGaugeName">Название прибора</label><input id="analogGaugeName" class="custom-input" type="text" maxlength="80" placeholder="Например, Температура CPU"><div class="analog-gauge-range-fields"><label for="analogGaugeMin">Минимум<input id="analogGaugeMin" class="custom-input" type="number" step="any"></label><label for="analogGaugeMax">Максимум<input id="analogGaugeMax" class="custom-input" type="number" step="any"></label></div><label class="analog-gauge-size-label" for="analogGaugeSize">Ширина индикатора</label><div class="analog-gauge-size-control"><input id="analogGaugeSize" type="range" min="240" max="640" step="20" value="360" aria-describedby="analogGaugeSizeValue"><output id="analogGaugeSizeValue" for="analogGaugeSize">360 px</output></div><small class="muted">Диапазон шкалы настраиваемый; показание вне него не обрезается в цифровом значении.</small><div class="modal-actions"><button id="analogGaugeSaveBtn" type="button">Создать прибор</button><button id="analogGaugeDeleteBtn" class="hidden" type="button">Удалить прибор</button><button id="analogGaugeCancelBtn" type="button">Отмена</button></div>';
  var filter = panel.querySelector("#analogGaugeTypeFilter");
  [{value:"",label:"Все типы"},{value:"Temperature",label:"Температура"},{value:"Voltage",label:"Напряжение"},{value:"Power",label:"Мощность"},{value:"Clock",label:"Частота (Clock)"},{value:"Frequency",label:"Частота (Frequency)"},{value:"Load",label:"Загрузка"},{value:"Fan",label:"Вентилятор"},{value:"Data",label:"Данные"},{value:"SmallData",label:"Малые данные"},{value:"Throughput",label:"Пропускная способность"},{value:"Level",label:"Уровень"},{value:"Current",label:"Ток"},{value:"Control",label:"Управление"},{value:"Timing",label:"Тайминги"},{value:"Noise",label:"Шум"},{value:"Energy",label:"Энергия"},{value:"Factor",label:"Коэффициент"}].forEach(function (item) { filter.appendChild(new Option(item.label, item.value)); });
  toolbar.appendChild(modeButton);
  toolbar.appendChild(addButton);
  document.body.appendChild(overlay);
  document.body.appendChild(panel);
  modeButton.addEventListener("click", function () { state.displayMode = state.displayMode === "analog-gauges" ? "cards" : "analog-gauges"; saveState(); applyDashboardDisplayMode(); createCards(); renderCachedSources(); });
  addButton.addEventListener("click", function () { openAnalogGaugeEditor(); });
  panel.querySelector("#analogGaugeSaveBtn").addEventListener("click", saveAnalogGaugeFromForm);
  panel.querySelector("#analogGaugeDeleteBtn").addEventListener("click", deleteCurrentAnalogGauge);
  panel.querySelector("#analogGaugeCancelBtn").addEventListener("click", closeAnalogGaugeEditor);
  overlay.addEventListener("click", closeAnalogGaugeEditor);
  panel.querySelector("#analogGaugeSource").addEventListener("change", function () { renderAnalogGaugeSensorOptions(""); });
  panel.querySelector("#analogGaugeTypeFilter").addEventListener("change", function () { renderAnalogGaugeSensorOptions(); });
  panel.querySelector("#analogGaugeSearch").addEventListener("input", function () { renderAnalogGaugeSensorOptions(); });
  panel.querySelector("#analogGaugeSensor").addEventListener("change", setAnalogGaugeDefaultRange);
  panel.querySelector("#analogGaugeSize").addEventListener("input", function () { panel.querySelector("#analogGaugeSizeValue").value = this.value + " px"; });
  panel.addEventListener("keydown", function (event) { if (event.key === "Escape") { event.preventDefault(); closeAnalogGaugeEditor(); } });
  applyDashboardDisplayMode();
  return { modeButton: modeButton, addButton: addButton, overlay: overlay, panel: panel };
}

var ui = mountThemeInterface();
unregisterBoardView = api.registerBoardView({
  isActive: function () { return state.displayMode === "analog-gauges"; },
  render: renderAnalogGaugeBoard,
  update: function (data, sourceId) { updateAnalogGauges(sourceId); },
  saveLayout: saveLayout,
  reset: function () { state.analogGauges.forEach(function (gauge) { delete layout[gauge.id]; }); saveState(); }
});
if (state.displayMode === "analog-gauges") { createCards(); renderCachedSources(); }
return {
  destroy: function () {
    state.displayMode = "cards";
    saveState();
    if (unregisterBoardView) {
      unregisterBoardView();
      unregisterBoardView = null;
    } else {
      createCards();
      renderCachedSources();
    }
    document.body.classList.remove("analog-gauge-mode");
    if (board) board.classList.remove("analog-gauge-board");
    ui.modeButton.remove(); ui.addButton.remove(); ui.overlay.remove(); ui.panel.remove();
    if (api.toolbarGroup) api.toolbarGroup.hidden = true;
  }
};
}

var THEME_CSS = "/* ============================================================\n   SystemMonitor \u2014 \u0421\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u0430\u044f \u0442\u0435\u043c\u0430 (analog gauge)\n   \u0412\u043d\u0435\u0448\u043d\u044f\u044f CSS-\u0442\u0435\u043c\u0430. \u0418\u043c\u043f\u043e\u0440\u0442\u0438\u0440\u0443\u0439\u0442\u0435 \u0435\u0451 \u0447\u0435\u0440\u0435\u0437 \u00ab\u0422\u0435\u043c\u044b \u043e\u0444\u043e\u0440\u043c\u043b\u0435\u043d\u0438\u044f\u00bb \u0432 Dashboard.\n   ============================================================ */\n\n/* \u0421\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u0440\u0442\u043e\u0447\u043d\u044b\u0435 \u044d\u043b\u0435\u043c\u0435\u043d\u0442\u044b \u0432 \u0441\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u043e\u043c \u0440\u0435\u0436\u0438\u043c\u0435 */\nbody.analog-gauge-mode #addCustomBtn,\nbody.analog-gauge-mode #addFpsCardBtn,\nbody.analog-gauge-mode #fpsPanelCompactBtn,\nbody.analog-gauge-mode #fpsPanel { display: none !important; }\n\n/* \u0414\u043e\u0441\u043a\u0430 \u0432 \u0441\u0442\u0440\u0435\u043b\u043e\u0447\u043d\u043e\u043c \u0440\u0435\u0436\u0438\u043c\u0435 */\nbody.analog-gauge-mode .board.analog-gauge-board {\n  display: block;\n  overflow: auto;\n  min-height: min(60vh, 560px);\n  background: #10191d;\n  border: 1px solid #34454a;\n  padding: clamp(12px, 2vw, 24px);\n}\n\n/* \u0411\u0430\u0437\u043e\u0432\u044b\u0439 \u043f\u0440\u0438\u0431\u043e\u0440 */\n.analog-gauge {\n  position: absolute;\n  width: var(--analog-gauge-width, 360px);\n  max-width: 100%;\n  min-width: 0;\n  padding: 0;\n  border: 0;\n  background: transparent;\n  color: #e2f0ef;\n  cursor: grab;\n  touch-action: none;\n  user-select: none;\n}\n.analog-gauge.dragging { cursor: grabbing; }\n.analog-gauge.locked { cursor: default; }\n\n/* \u0426\u0438\u0444\u0435\u0440\u0431\u043b\u0430\u0442 */\n.analog-gauge-face {\n  position: relative;\n  padding: 3px 9px 8px;\n  border: 1px solid #294044;\n  border-radius: 4px;\n  background: linear-gradient(180deg, #030809 0%, #0c171a 100%);\n  box-shadow: inset 0 0 0 1px #152629, inset 0 3px 10px rgba(0, 0, 0, .8);\n  color: #ddf8f2;\n}\n\n/* \u041a\u043d\u043e\u043f\u043a\u0430 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043a (\u0448\u0435\u0441\u0442\u0451\u0440\u043a\u0430) \u043d\u0430 \u0446\u0438\u0444\u0435\u0440\u0431\u043b\u0430\u0442\u0435 */\n.analog-gauge-settings {\n  position: absolute;\n  top: 8px;\n  right: 8px;\n  z-index: 1;\n  display: grid;\n  place-items: center;\n  width: 30px;\n  height: 30px;\n  padding: 0;\n  border: 1px solid rgba(198, 219, 217, .2);\n  border-radius: 50%;\n  background: rgba(221, 240, 238, .08);\n  color: rgba(221, 240, 238, .48);\n  opacity: .68;\n  font: 16px/1 \"Segoe UI Symbol\", \"Segoe UI\", sans-serif;\n}\n.analog-gauge-settings:hover { border-color: rgba(221, 240, 238, .42); background: rgba(221, 240, 238, .14); color: rgba(245, 255, 253, .9); opacity: 1; }\n.analog-gauge-settings:focus-visible { opacity: 1; }\n\n/* Focus-visible \u043d\u0430 \u044d\u043b\u0435\u043c\u0435\u043d\u0442\u0430\u0445 \u043f\u0430\u043d\u0435\u043b\u0438 \u043f\u0440\u0438\u0431\u043e\u0440\u043e\u0432 */\n.analog-gauge button:focus-visible,\n.analog-gauge-panel button:focus-visible,\n.analog-gauge-panel select:focus-visible,\n.analog-gauge-panel input:focus-visible {\n  outline: 3px solid #007f87;\n  outline-offset: 2px;\n}\n\n/* SVG \u0448\u043a\u0430\u043b\u0430 */\n.analog-gauge-svg { display: block; width: 100%; height: auto; overflow: visible; }\n.analog-gauge-arc { fill: none; stroke: #43d5d0; stroke-width: 2.2; filter: drop-shadow(0 0 2px rgba(67, 213, 208, .72)); }\n.analog-gauge-tick { stroke: #54d9d2; stroke-linecap: square; filter: drop-shadow(0 0 1.5px rgba(84, 217, 210, .65)); }\n.analog-gauge-label { fill: #b4f4eb; font: 11px \"Segoe UI\", Tahoma, Arial, sans-serif; text-anchor: middle; filter: drop-shadow(0 0 2px rgba(84, 217, 210, .45)); }\n.analog-gauge-needle-group { transition: transform .28s ease-out; }\n.analog-gauge-needle { stroke: #f04e4e; stroke-width: 3; stroke-linecap: round; filter: drop-shadow(0 0 2px rgba(240, 78, 78, .65)); }\n.analog-gauge-hub { fill: #e85a53; stroke: #ffd1c9; stroke-width: 1.5; }\n\n/* \u0426\u0438\u0444\u0440\u043e\u0432\u043e\u0435 \u0447\u0442\u0435\u043d\u0438\u0435 */\n.analog-gauge-readout {\n  display: block;\n  margin-top: -1px;\n  color: #edfffa;\n  font: 700 clamp(23px, 3vw, 31px)/1.15 \"Segoe UI\", Tahoma, Arial, sans-serif;\n  font-variant-numeric: tabular-nums;\n  text-align: center;\n  overflow-wrap: anywhere;\n}\n\n/* \u0421\u0442\u0430\u0442\u0443\u0441 \u0438 \u0438\u043c\u044f \u043f\u0440\u0438\u0431\u043e\u0440\u0430 */\n.analog-gauge-status {\n  min-height: 0;\n  margin-top: 0;\n  color: #9ccbc5;\n  font-size: 11px;\n  text-align: center;\n}\n.analog-gauge-name {\n  margin-top: 3px;\n  color: #9ccbc5;\n  font-size: 13px;\n  text-align: center;\n  overflow-wrap: anywhere;\n}\n.analog-gauge-status.is-warning,\n.analog-gauge-status.is-unavailable { min-height: 17px; margin-top: 3px; }\n.analog-gauge-status.is-warning { color: #ffd17a; }\n.analog-gauge-status.is-unavailable { color: #ffaaa1; }\n\n/* \u0414\u0438\u0430\u043f\u0430\u0437\u043e\u043d \u0448\u043a\u0430\u043b\u044b */\n.analog-gauge-range {\n  display: flex;\n  justify-content: space-between;\n  gap: 8px;\n  margin-top: 6px;\n  color: #a7ccc6;\n  font-size: 10px;\n  font-variant-numeric: tabular-nums;\n}\n\n/* \u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043a\u043e\u0433\u0434\u0430 \u043d\u0435\u0442 \u043f\u0440\u0438\u0431\u043e\u0440\u043e\u0432 */\n.analog-gauge-empty {\n  grid-column: 1 / -1;\n  display: grid;\n  justify-items: center;\n  gap: 10px;\n  padding: clamp(32px, 8vh, 80px) 20px;\n  border: 1px dashed #5e8586;\n  color: #d8f3ed;\n  text-align: center;\n}\n.analog-gauge-empty h2 { margin: 0; font-size: clamp(20px, 3vw, 28px); }\n.analog-gauge-empty p { max-width: 48ch; margin: 0; color: #a9ccc6; line-height: 1.5; }\n.analog-gauge-empty button { padding: 9px 14px; border: 1px solid #70d7cf; background: #12363a; color: #e6fffa; }\n\n/* \u0421\u043a\u0440\u044b\u0442\u044b\u0439 \u0438\u0437\u043c\u0435\u0440\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u044d\u043b\u0435\u043c\u0435\u043d\u0442 (a11y) */\n.analog-gauge-meter {\n  position: absolute;\n  width: 1px;\n  height: 1px;\n  padding: 0;\n  margin: -1px;\n  overflow: hidden;\n  clip: rect(0, 0, 0, 0);\n  clip-path: inset(50%);\n  white-space: nowrap;\n}\n\n/* \u041f\u043e\u043b\u044f \u0432\u0432\u043e\u0434\u0430 \u0432 \u0440\u0435\u0434\u0430\u043a\u0442\u043e\u0440\u0435 \u043f\u0440\u0438\u0431\u043e\u0440\u0430 */\n.analog-gauge-range-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }\n.analog-gauge-range-fields label { display: block; min-width: 0; color: var(--muted); font-size: 13px; }\n.analog-gauge-range-fields input { display: block; width: 100%; margin-top: 4px; }\n.analog-gauge-size-label { display: block; margin-top: 12px; color: var(--muted); font-size: 13px; }\n.analog-gauge-size-control { display: flex; align-items: center; gap: 10px; margin-top: 4px; }\n.analog-gauge-size-control input { flex: 1; min-width: 0; }\n.analog-gauge-size-control output { min-width: 52px; text-align: right; font-variant-numeric: tabular-nums; }\n\n/* \u041c\u043e\u0434\u0430\u043b\u044c\u043d\u0430\u044f \u043f\u0430\u043d\u0435\u043b\u044c \u0440\u0435\u0434\u0430\u043a\u0442\u043e\u0440\u0430 \u043f\u0440\u0438\u0431\u043e\u0440\u0430 */\n.analog-gauge-panel {\n  display: flex;\n  flex-direction: column;\n  box-sizing: border-box;\n  width: min(820px, calc(100vw - 24px));\n  height: min(840px, calc(100vh - 32px));\n  min-width: min(420px, calc(100vw - 24px));\n  min-height: min(480px, calc(100vh - 32px));\n  max-width: calc(100vw - 24px);\n  resize: both;\n  overflow: auto;\n}\n.analog-gauge-panel #analogGaugeSensor { flex: 1 1 240px; min-height: 180px; }\n.analog-gauge-resize-hint { margin: -6px 0 8px; font-size: 12px; }\n\n@media (max-width: 600px) {\n  .analog-gauge-panel {\n    width: calc(100vw - 24px);\n    height: min(840px, calc(100vh - 24px));\n    min-width: 0;\n    min-height: min(420px, calc(100vh - 24px));\n    resize: none;\n  }\n  .analog-gauge-resize-hint { display: none; }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .analog-gauge *, .analog-gauge *::before, .analog-gauge *::after {\n    scroll-behavior: auto !important;\n    animation-duration: .01ms !important;\n    animation-iteration-count: 1 !important;\n    transition-duration: .01ms !important;\n  }\n}\n";
global.SystemMonitorThemePackage = {
  name: "Стрелочные приборы",
  activate: function (api) {
    var style = document.createElement("style");
    style.id = "systemMonitorAnalogGaugeThemeStyles";
    style.textContent = THEME_CSS;
    document.head.appendChild(style);
    try {
      var extension = createAnalogGaugeTheme(api);
      return { destroy: function () { try { extension.destroy(); } finally { style.remove(); } } };
    } catch (error) {
      style.remove();
      throw error;
    }
  }
};
})(window);
