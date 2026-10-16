// DataviewJS runtime for obsidian-pdf-exporter.
//
// Runs inside an embedded V8 (mini-racer) after luxon.min.js. It provides
// the `dv` API of Dataview's DataviewInlineApi with the DataArray, Link,
// Values and Widgets of Dataview (ported from the Dataview sources, MIT).
// Data that only the exporter knows (pages, query results, DQL functions,
// files) comes through `__dvBridge`: a call whose result is not known yet
// records a request and throws; the exporter answers the requests and runs
// the script again. Rendering calls append nodes to `dv.container`, which
// the exporter turns into Markdown.

(function () {
  "use strict";
  const { DateTime, Duration } = luxon;
  const G = globalThis;

  // ---------------------------------------------------------------- Link
  function getFileTitle(path) {
    if (path.includes("/")) path = path.substring(path.lastIndexOf("/") + 1);
    if (path.endsWith(".md")) path = path.substring(0, path.length - 3);
    return path;
  }

  function normalizeHeaderForLink(header) {
    return header
      .replace(/[^0-9\p{Letter}_\-\p{Extended_Pictographic}‍️]/gu, " ")
      .split(/\s+/)
      .join(" ")
      .trim();
  }

  class Link {
    static file(path, embed = false, display) {
      return new Link({ path, embed, display, subpath: undefined, type: "file" });
    }
    static infer(linkpath, embed = false, display) {
      if (linkpath.includes("#^")) {
        const split = linkpath.split("#^");
        return Link.block(split[0], split[1], embed, display);
      } else if (linkpath.includes("#")) {
        const split = linkpath.split("#");
        return Link.header(split[0], split[1], embed, display);
      }
      return Link.file(linkpath, embed, display);
    }
    static header(path, header, embed, display) {
      return new Link({ path, embed, display, subpath: normalizeHeaderForLink(header), type: "header" });
    }
    static block(path, blockId, embed, display) {
      return new Link({ path, embed, display, subpath: blockId, type: "block" });
    }
    static fromObject(object) {
      return new Link(object);
    }
    constructor(fields) {
      Object.assign(this, fields);
    }
    equals(other) {
      if (other == undefined || other == null) return false;
      return this.path == other.path && this.type == other.type && this.subpath == other.subpath;
    }
    toString() {
      return this.markdown();
    }
    toObject() {
      return { path: this.path, type: this.type, subpath: this.subpath, display: this.display, embed: this.embed };
    }
    withPath(path) {
      return new Link(Object.assign({}, this, { path }));
    }
    withDisplay(display) {
      return new Link(Object.assign({}, this, { display }));
    }
    withHeader(header) {
      return Link.header(this.path, header, this.embed, this.display);
    }
    toFile() {
      return Link.file(this.path, this.embed, this.display);
    }
    toEmbed() {
      if (this.embed) return this;
      const link = new Link(this);
      link.embed = true;
      return link;
    }
    fromEmbed() {
      if (!this.embed) return this;
      const link = new Link(this);
      link.embed = false;
      return link;
    }
    markdown() {
      let result = (this.embed ? "!" : "") + "[[" + this.obsidianLink();
      if (this.display) {
        result += "|" + this.display;
      } else {
        result += "|" + getFileTitle(this.path);
        if (this.type == "header" || this.type == "block") result += " > " + this.subpath;
      }
      return result + "]]";
    }
    obsidianLink() {
      const escaped = this.path.replaceAll("|", "\\|");
      if (this.type == "header") return escaped + "#" + this.subpath?.replaceAll("|", "\\|");
      if (this.type == "block") return escaped + "#^" + this.subpath?.replaceAll("|", "\\|");
      return escaped;
    }
    fileName() {
      return getFileTitle(this.path).replace(".md", "");
    }
  }

  // ------------------------------------------------------------- Widgets
  class Widget {
    constructor($widget) {
      this.$widget = $widget;
    }
  }
  class ListPairWidget extends Widget {
    constructor(key, value) {
      super("dataview:list-pair");
      this.key = key;
      this.value = value;
    }
    markdown() {
      return `${Values.toString(this.key)}: ${Values.toString(this.value)}`;
    }
  }
  class ExternalLinkWidget extends Widget {
    constructor(url, display) {
      super("dataview:external-link");
      this.url = url;
      this.display = display;
    }
    markdown() {
      return `[${this.display ?? this.url}](${this.url})`;
    }
  }
  const Widgets = {
    listPair: (key, value) => new ListPairWidget(key, value),
    externalLink: (url, display) => new ExternalLinkWidget(url, display),
    isListPair: w => w.$widget === "dataview:list-pair",
    isExternalLink: w => w.$widget === "dataview:external-link",
    isBuiltin: w => Widgets.isListPair(w) || Widgets.isExternalLink(w),
  };

  // -------------------------------------------------------------- Values
  let SETTINGS = {};

  function renderMinimalDuration(dur) {
    dur = dur.shiftToAll().normalize();
    dur = Duration.fromObject(Object.fromEntries(Object.entries(dur.toObject()).filter(([, q]) => q != 0)));
    return dur.toHuman();
  }

  const Values = {
    toString(field, setting = SETTINGS, recursive = false) {
      const wrapped = Values.wrapValue(field);
      if (!wrapped) return setting.renderNullAs;
      switch (wrapped.type) {
        case "null":
          return setting.renderNullAs;
        case "string":
          return wrapped.value;
        case "number":
        case "boolean":
          return "" + wrapped.value;
        case "html":
          return wrapped.value.outerHTML;
        case "widget":
          return wrapped.value.markdown();
        case "link":
          return wrapped.value.markdown();
        case "function":
          return "<function>";
        case "array": {
          let result = "";
          if (recursive) result += "[";
          result += wrapped.value.map(f => Values.toString(f, setting, true)).join(", ");
          if (recursive) result += "]";
          return result;
        }
        case "object":
          return (
            "{ " +
            Object.entries(wrapped.value)
              .map(e => e[0] + ": " + Values.toString(e[1], setting, true))
              .join(", ") +
            " }"
          );
        case "date":
          if (wrapped.value.second == 0 && wrapped.value.hour == 0 && wrapped.value.minute == 0) {
            return wrapped.value.toFormat(setting.defaultDateFormat);
          }
          return wrapped.value.toFormat(setting.defaultDateTimeFormat);
        case "duration":
          return renderMinimalDuration(wrapped.value);
      }
    },
    wrapValue(val) {
      if (Values.isNull(val)) return { type: "null", value: val };
      else if (Values.isNumber(val)) return { type: "number", value: val };
      else if (Values.isString(val)) return { type: "string", value: val };
      else if (Values.isBoolean(val)) return { type: "boolean", value: val };
      else if (Values.isDuration(val)) return { type: "duration", value: val };
      else if (Values.isDate(val)) return { type: "date", value: val };
      else if (Values.isWidget(val)) return { type: "widget", value: val };
      else if (Values.isArray(val)) return { type: "array", value: val };
      else if (Values.isLink(val)) return { type: "link", value: val };
      else if (Values.isFunction(val)) return { type: "function", value: val };
      else if (Values.isHtml(val)) return { type: "html", value: val };
      else if (Values.isObject(val)) return { type: "object", value: val };
      return undefined;
    },
    mapLeaves(val, func) {
      if (Values.isObject(val)) {
        const result = {};
        for (const [key, value] of Object.entries(val)) result[key] = Values.mapLeaves(value, func);
        return result;
      } else if (Values.isArray(val)) {
        return val.map(v => Values.mapLeaves(v, func));
      }
      return func(val);
    },
    compareValue(val1, val2, linkNormalizer) {
      if (val1 === undefined) val1 = null;
      if (val2 === undefined) val2 = null;
      if (val1 === null && val2 === null) return 0;
      else if (val1 === null) return -1;
      else if (val2 === null) return 1;
      const wrap1 = Values.wrapValue(val1);
      const wrap2 = Values.wrapValue(val2);
      if (wrap1 === undefined && wrap2 === undefined) return 0;
      else if (wrap1 === undefined) return -1;
      else if (wrap2 === undefined) return 1;
      if (wrap1.type != wrap2.type) return wrap1.type.localeCompare(wrap2.type);
      if (wrap1.value === wrap2.value) return 0;
      switch (wrap1.type) {
        case "string":
          return wrap1.value.localeCompare(wrap2.value);
        case "number":
          if (wrap1.value < wrap2.value) return -1;
          else if (wrap1.value == wrap2.value) return 0;
          return 1;
        case "null":
          return 0;
        case "boolean":
          if (wrap1.value == wrap2.value) return 0;
          return wrap1.value ? 1 : -1;
        case "link": {
          const link1 = wrap1.value;
          const link2 = wrap2.value;
          const normalize = linkNormalizer ?? (x => x);
          const pathCompare = normalize(link1.path).localeCompare(normalize(link2.path));
          if (pathCompare != 0) return pathCompare;
          const typeCompare = link1.type.localeCompare(link2.type);
          if (typeCompare != 0) return typeCompare;
          if (link1.subpath && !link2.subpath) return 1;
          if (!link1.subpath && link2.subpath) return -1;
          if (!link1.subpath && !link2.subpath) return 0;
          return (link1.subpath ?? "").localeCompare(link2.subpath ?? "");
        }
        case "date":
          return wrap1.value < wrap2.value ? -1 : wrap1.value.equals(wrap2.value) ? 0 : 1;
        case "duration":
          return wrap1.value < wrap2.value ? -1 : wrap1.value.equals(wrap2.value) ? 0 : 1;
        case "array": {
          const f1 = wrap1.value;
          const f2 = wrap2.value;
          for (let index = 0; index < Math.min(f1.length, f2.length); index++) {
            const comp = Values.compareValue(f1[index], f2[index]);
            if (comp != 0) return comp;
          }
          return f1.length - f2.length;
        }
        case "object": {
          const o1 = wrap1.value;
          const o2 = wrap2.value;
          const k1 = Array.from(Object.keys(o1)).sort();
          const k2 = Array.from(Object.keys(o2)).sort();
          const keyCompare = Values.compareValue(k1, k2);
          if (keyCompare != 0) return keyCompare;
          for (const key of k1) {
            const comp = Values.compareValue(o1[key], o2[key]);
            if (comp != 0) return comp;
          }
          return 0;
        }
        default:
          return 0;
      }
    },
    typeOf(val) {
      return Values.wrapValue(val)?.type;
    },
    isTruthy(field) {
      const wrapped = Values.wrapValue(field);
      if (!wrapped) return false;
      switch (wrapped.type) {
        case "number":
          return wrapped.value != 0;
        case "string":
          return wrapped.value.length > 0;
        case "boolean":
          return wrapped.value;
        case "link":
          return !!wrapped.value.path;
        case "date":
          return wrapped.value.toMillis() != 0;
        case "duration":
          return wrapped.value.as("seconds") != 0;
        case "object":
          return Object.keys(wrapped.value).length > 0;
        case "array":
          return wrapped.value.length > 0;
        case "null":
          return false;
        default:
          return true;
      }
    },
    deepCopy(field) {
      if (field === null || field === undefined) return field;
      if (Values.isArray(field)) return [].concat(field.map(v => Values.deepCopy(v)));
      if (Values.isObject(field)) {
        const result = {};
        for (const [key, value] of Object.entries(field)) result[key] = Values.deepCopy(value);
        return result;
      }
      return field;
    },
    isString: val => typeof val == "string",
    isNumber: val => typeof val == "number",
    isDate: val => val instanceof DateTime,
    isDuration: val => val instanceof Duration,
    isNull: val => val === null || val === undefined,
    isArray: val => Array.isArray(val),
    isBoolean: val => typeof val === "boolean",
    isLink: val => val instanceof Link,
    isWidget: val => val instanceof Widget,
    isHtml: val => val instanceof FakeElement,
    isObject: val =>
      typeof val == "object" &&
      !Values.isHtml(val) &&
      !Values.isWidget(val) &&
      !Values.isArray(val) &&
      !Values.isDuration(val) &&
      !Values.isDate(val) &&
      !Values.isLink(val) &&
      val !== undefined &&
      !Values.isNull(val),
    isFunction: val => typeof val == "function",
  };

  const Groupings = {
    isElementGroup: entry =>
      Values.isObject(entry) && Object.keys(entry).length == 2 && "key" in entry && "rows" in entry,
    isGrouping(entry) {
      for (const element of entry) if (!Groupings.isElementGroup(element)) return false;
      return true;
    },
    count(elements) {
      if (Groupings.isGrouping(elements)) {
        let result = 0;
        for (const subgroup of elements) result += Groupings.count(subgroup.rows);
        return result;
      }
      return elements.length;
    },
  };

  // ----------------------------------------------------------- DataArray
  const ARRAY_FUNCTIONS = new Set([
    "where", "filter", "map", "flatMap", "mutate", "slice", "concat", "indexOf", "limit", "find",
    "findIndex", "includes", "join", "sort", "sortInPlace", "groupBy", "groupIn", "distinct",
    "every", "some", "none", "first", "last", "to", "into", "lwrap", "expand", "forEach",
    "length", "values", "array", "defaultComparator", "toString", "settings", "sum", "avg",
    "min", "max",
  ]);

  const ARRAY_PROXY = {
    get(target, prop) {
      if (typeof prop === "symbol") return target[prop];
      else if (typeof prop === "number") return target.values[prop];
      else if (prop === "constructor") return target.values.constructor;
      else if (!isNaN(parseInt(prop))) return target.values[parseInt(prop)];
      else if (ARRAY_FUNCTIONS.has(prop.toString())) return target[prop.toString()];
      return target.to(prop);
    },
  };

  class DataArrayImpl {
    static wrap(arr, settings, defaultComparator = Values.compareValue) {
      return new Proxy(new DataArrayImpl(arr, settings, defaultComparator), ARRAY_PROXY);
    }
    constructor(values, settings, defaultComparator = Values.compareValue) {
      this.values = values;
      this.settings = settings;
      this.defaultComparator = defaultComparator;
      this.length = values.length;
    }
    lwrap(values) {
      return DataArrayImpl.wrap(values, this.settings, this.defaultComparator);
    }
    where(predicate) {
      return this.lwrap(this.values.filter(predicate));
    }
    filter(predicate) {
      return this.where(predicate);
    }
    map(f) {
      return this.lwrap(this.values.map(f));
    }
    flatMap(f) {
      const result = [];
      for (let index = 0; index < this.length; index++) {
        const value = f(this.values[index], index, this.values);
        if (!value || value.length == 0) continue;
        for (const r of value) result.push(r);
      }
      return this.lwrap(result);
    }
    mutate(f) {
      for (let index = 0; index < this.values.length; index++) f(this.values[index], index, this.values);
      return this;
    }
    limit(count) {
      return this.lwrap(this.values.slice(0, count));
    }
    slice(start, end) {
      return this.lwrap(this.values.slice(start, end));
    }
    concat(other) {
      return this.lwrap(this.values.concat(other.values ?? other));
    }
    indexOf(element, fromIndex) {
      return this.findIndex(e => this.defaultComparator(e, element) == 0, fromIndex);
    }
    find(pred) {
      const index = this.findIndex(pred);
      return index == -1 ? undefined : this.values[index];
    }
    findIndex(pred, fromIndex) {
      for (let index = fromIndex ?? 0; index < this.length; index++) {
        if (pred(this.values[index], index, this.values)) return index;
      }
      return -1;
    }
    includes(element) {
      return this.indexOf(element, 0) != -1;
    }
    join(sep) {
      return this.map(s => Values.toString(s, this.settings)).array().join(sep ?? ", ");
    }
    sort(key, direction, comparator) {
      if (this.values.length == 0) return this;
      const realComparator = comparator ?? this.defaultComparator;
      const realKey = key ?? (l => l);
      const copy = [].concat(this.array()).map((elem, index) => ({ index, value: elem }));
      copy.sort((a, b) => {
        const aKey = realKey(a.value, a.index, this.values);
        const bKey = realKey(b.value, b.index, this.values);
        return direction === "desc" ? -realComparator(aKey, bKey) : realComparator(aKey, bKey);
      });
      return this.lwrap(copy.map(e => e.value));
    }
    sortInPlace(key, direction, comparator) {
      if (this.values.length == 0) return this;
      const realComparator = comparator ?? this.defaultComparator;
      const realKey = key ?? (l => l);
      this.values.sort((a, b) => {
        const aKey = realKey(a);
        const bKey = realKey(b);
        return direction == "desc" ? -realComparator(aKey, bKey) : realComparator(aKey, bKey);
      });
      return this;
    }
    groupBy(key, comparator) {
      if (this.values.length == 0) return this.lwrap([]);
      const intermediate = this.sort(key, "asc", comparator);
      comparator = comparator ?? this.defaultComparator;
      const result = [];
      let currentRow = [intermediate[0]];
      let current = key(intermediate[0], 0, intermediate.values);
      for (let index = 1; index < intermediate.length; index++) {
        const newKey = key(intermediate[index], index, intermediate.values);
        if (comparator(current, newKey) != 0) {
          result.push({ key: current, rows: this.lwrap(currentRow) });
          current = newKey;
          currentRow = [intermediate[index]];
        } else {
          currentRow.push(intermediate[index]);
        }
      }
      result.push({ key: current, rows: this.lwrap(currentRow) });
      return this.lwrap(result);
    }
    groupIn(key, comparator) {
      if (Groupings.isGrouping(this.values)) {
        return this.map(v => ({
          key: v.key,
          rows: DataArray.wrap(v.rows, this.settings).groupIn(key, comparator),
        }));
      }
      return this.groupBy(key, comparator);
    }
    distinct(key, comparator) {
      if (this.values.length == 0) return this;
      const realKey = key ?? (x => x);
      const intermediate = this.map((x, index) => ({ key: realKey(x, index, this.values), value: x })).sort(
        x => x.key,
        "asc",
        comparator
      );
      comparator = comparator ?? this.defaultComparator;
      const result = [intermediate[0].value];
      for (let index = 1; index < intermediate.length; index++) {
        if (comparator(intermediate[index - 1].key, intermediate[index].key) != 0) {
          result.push(intermediate[index].value);
        }
      }
      return this.lwrap(result);
    }
    every(f) {
      return this.values.every(f);
    }
    some(f) {
      return this.values.some(f);
    }
    none(f) {
      return this.values.every((v, i, a) => !f(v, i, a));
    }
    first() {
      return this.values.length > 0 ? this.values[0] : undefined;
    }
    last() {
      return this.values.length > 0 ? this.values[this.values.length - 1] : undefined;
    }
    to(key) {
      const result = [];
      for (const child of this.values) {
        const value = child[key];
        if (value === undefined || value === null) continue;
        if (Array.isArray(value) || DataArray.isDataArray(value)) value.forEach(v => result.push(v));
        else result.push(value);
      }
      return this.lwrap(result);
    }
    into(key) {
      const result = [];
      for (const child of this.values) {
        const value = child[key];
        if (value === undefined || value === null) continue;
        result.push(value);
      }
      return this.lwrap(result);
    }
    expand(key) {
      const result = [];
      const queue = [].concat(this.values);
      while (queue.length > 0) {
        const next = queue.pop();
        const value = next[key];
        if (value === undefined || value === null) continue;
        if (Array.isArray(value)) value.forEach(v => queue.push(v));
        else if (value instanceof DataArrayImpl) value.forEach(v => queue.push(v));
        else queue.push(value);
        result.push(next);
      }
      return this.lwrap(result);
    }
    forEach(f) {
      for (let index = 0; index < this.values.length; index++) f(this.values[index], index, this.values);
    }
    sum() {
      return this.values.reduce((a, b) => a + b, 0);
    }
    avg() {
      return this.sum() / this.values.length;
    }
    min() {
      return Math.min(...this.values);
    }
    max() {
      return Math.max(...this.values);
    }
    array() {
      return [].concat(this.values);
    }
    [Symbol.iterator]() {
      return this.values[Symbol.iterator]();
    }
    toString() {
      return "[" + this.values.join(", ") + "]";
    }
  }

  const DataArray = {
    wrap(raw, settings) {
      if (DataArray.isDataArray(raw)) return raw;
      return DataArrayImpl.wrap(raw, settings);
    },
    from(raw, settings) {
      if (DataArray.isDataArray(raw)) return raw;
      const data = [];
      for (const elem of raw) data.push(elem);
      return DataArrayImpl.wrap(data, settings);
    },
    isDataArray: obj => obj instanceof DataArrayImpl,
  };

  const oldArrayIsArray = Array.isArray;
  Array.isArray = arg => oldArrayIsArray(arg) || DataArray.isDataArray(arg);

  class Result {
    constructor(successful, value, error) {
      this.successful = successful;
      if (successful) this.value = value;
      else this.error = error;
    }
    static success(value) {
      return new Result(true, value);
    }
    static failure(error) {
      return new Result(false, undefined, error);
    }
    map(f) {
      return this.successful ? Result.success(f(this.value)) : this;
    }
    flatMap(f) {
      return this.successful ? f(this.value) : this;
    }
    mapErr(f) {
      return this.successful ? this : Result.failure(f(this.error));
    }
    bimap(succ, fail) {
      return this.successful ? Result.success(succ(this.value)) : Result.failure(fail(this.error));
    }
    orElse(value) {
      return this.successful ? this.value : value;
    }
    cast() {
      return this;
    }
    orElseThrow(message) {
      if (this.successful) return this.value;
      throw new Error(message ? message(this.error) : "" + this.error);
    }
  }

  // ------------------------------------------------------------ Fake DOM
  const BLOCK_TAGS = new Set([
    "div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "thead", "tbody",
    "tr", "td", "th", "blockquote", "pre", "details", "summary", "section", "article", "hr",
    "figure", "figcaption", "dl", "dt", "dd", "header", "footer", "nav", "aside", "main",
  ]);

  class ClassList {
    constructor(el) {
      this.el = el;
    }
    add(...names) {
      for (const n of names) for (const c of String(n).split(/\s+/)) if (c && !this.el.cls.includes(c)) this.el.cls.push(c);
    }
    remove(...names) {
      this.el.cls = this.el.cls.filter(c => !names.includes(c));
    }
    toggle(name, force) {
      const has = this.el.cls.includes(name);
      if (force === true || (force === undefined && !has)) this.add(name);
      else this.remove(name);
    }
    contains(name) {
      return this.el.cls.includes(name);
    }
  }

  class FakeElement {
    constructor(tag) {
      this.tagName = String(tag).toUpperCase();
      this.tag = String(tag).toLowerCase();
      this.nodeName = this.tagName;
      this.children = [];
      this.cls = [];
      this.attrs = {};
      this.style = {};
      this.dataset = {};
      this.classList = new ClassList(this);
      this.parentElement = null;
    }
    get childNodes() {
      return this.children;
    }
    get className() {
      return this.cls.join(" ");
    }
    set className(v) {
      this.cls = String(v).split(/\s+/).filter(Boolean);
    }
    get id() {
      return this.attrs.id ?? "";
    }
    set id(v) {
      this.attrs.id = String(v);
    }
    get textContent() {
      return this.children.map(c => (c.nodeType === "text" ? c.text : c.textContent ?? "")).join("");
    }
    set textContent(v) {
      this.children = [];
      if (v !== undefined && v !== null && v !== "") this.children.push({ nodeType: "text", text: String(v) });
    }
    get innerText() {
      return this.textContent;
    }
    set innerText(v) {
      this.textContent = v;
    }
    get innerHTML() {
      return this.children.map(c => (c.nodeType === "html" ? c.html : c.nodeType === "text" ? c.text : "")).join("");
    }
    set innerHTML(v) {
      this.children = [];
      if (v) this.children.push({ nodeType: "html", html: String(v) });
    }
    get outerHTML() {
      return `<${this.tag}>${this.innerHTML}</${this.tag}>`;
    }
    setText(v) {
      this.textContent = v;
      return this;
    }
    appendText(v) {
      this.children.push({ nodeType: "text", text: String(v) });
    }
    setAttribute(k, v) {
      if (k === "class") this.className = v;
      else this.attrs[k] = String(v);
    }
    setAttr(k, v) {
      this.setAttribute(k, v);
    }
    getAttribute(k) {
      return k === "class" ? this.className : this.attrs[k] ?? null;
    }
    removeAttribute(k) {
      delete this.attrs[k];
    }
    addClass(...c) {
      this.classList.add(...c);
    }
    addClasses(c) {
      this.classList.add(...c);
    }
    removeClass(...c) {
      this.classList.remove(...c);
    }
    hasClass(c) {
      return this.classList.contains(c);
    }
    toggleClass(c, f) {
      this.classList.toggle(c, f);
    }
    appendChild(node) {
      if (node instanceof FakeFragment) {
        for (const c of node.children) this.appendChild(c);
        return node;
      }
      if (node && node.parentElement) node.parentElement.removeChild(node);
      if (node instanceof FakeElement) node.parentElement = this;
      this.children.push(node);
      return node;
    }
    append(...nodes) {
      for (const n of nodes) this.appendChild(typeof n === "string" ? { nodeType: "text", text: n } : n);
    }
    prepend(...nodes) {
      const items = nodes.map(n => (typeof n === "string" ? { nodeType: "text", text: n } : n));
      this.children.unshift(...items);
    }
    insertBefore(node, ref) {
      const i = this.children.indexOf(ref);
      if (i < 0) this.children.push(node);
      else this.children.splice(i, 0, node);
      return node;
    }
    replaceChildren(...nodes) {
      this.children = [];
      this.append(...nodes);
    }
    removeChild(node) {
      this.children = this.children.filter(c => c !== node);
      return node;
    }
    remove() {
      if (this.parentElement) this.parentElement.removeChild(this);
    }
    replaceWith(...nodes) {
      const p = this.parentElement;
      if (!p) return;
      const i = p.children.indexOf(this);
      const items = nodes.map(n => (typeof n === "string" ? { nodeType: "text", text: n } : n));
      p.children.splice(i, 1, ...items);
    }
    empty() {
      this.children = [];
    }
    insertAdjacentHTML(_where, html) {
      this.children.push({ nodeType: "html", html: String(html) });
    }
    createEl(tag, o, callback) {
      const el = new FakeElement(tag);
      applyInfo(el, o);
      this.appendChild(el);
      if (typeof callback === "function") callback(el);
      return el;
    }
    createDiv(o, callback) {
      return this.createEl("div", typeof o === "string" ? { cls: o } : o, callback);
    }
    createSpan(o, callback) {
      return this.createEl("span", typeof o === "string" ? { cls: o } : o, callback);
    }
    querySelector() {
      return null;
    }
    querySelectorAll() {
      return [];
    }
    addEventListener() {}
    removeEventListener() {}
    onClickEvent() {}
    on() {}
    setCssStyles(s) {
      Object.assign(this.style, s);
    }
    find() {
      return null;
    }
    findAll() {
      return [];
    }
    isShown() {
      return true;
    }
    cloneNode() {
      return this;
    }
  }

  class FakeFragment extends FakeElement {
    constructor() {
      super("#fragment");
    }
  }

  function applyInfo(el, o) {
    if (o === undefined || o === null) return;
    if (typeof o === "string") {
      el.textContent = o;
      return;
    }
    if (o.cls) el.classList.add(...(Array.isArray(o.cls) ? o.cls : [o.cls]));
    if (o.text !== undefined) {
      if (o.text instanceof FakeElement || o.text instanceof FakeFragment) el.appendChild(o.text);
      else el.textContent = o.text;
    }
    if (o.attr) for (const [k, v] of Object.entries(o.attr)) if (v !== null && v !== undefined && v !== false) el.setAttribute(k, v);
    if (o.title) el.attrs.title = o.title;
    if (o.href) el.attrs.href = o.href;
    if (o.type) el.attrs.type = o.type;
    if (o.value !== undefined) el.attrs.value = String(o.value);
    if (o.placeholder) el.attrs.placeholder = o.placeholder;
  }

  const fakeDocument = {
    createElement: tag => new FakeElement(tag),
    createTextNode: text => ({ nodeType: "text", text: String(text) }),
    createDocumentFragment: () => new FakeFragment(),
    createEl: (tag, o, cb) => {
      const el = new FakeElement(tag);
      applyInfo(el, o);
      if (typeof cb === "function") cb(el);
      return el;
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: () => null,
    body: new FakeElement("body"),
  };
  G.document = fakeDocument;
  G.createEl = fakeDocument.createEl;
  G.createDiv = (o, cb) => fakeDocument.createEl("div", typeof o === "string" ? { cls: o } : o, cb);
  G.createSpan = (o, cb) => fakeDocument.createEl("span", typeof o === "string" ? { cls: o } : o, cb);
  G.createFragment = cb => {
    const f = new FakeFragment();
    if (typeof cb === "function") cb(f);
    return f;
  };
  G.HTMLElement = FakeElement;
  G.window = G;
  const logs = [];
  G.console = {
    log: (...a) => logs.push(a.map(String).join(" ")),
    info: (...a) => logs.push(a.map(String).join(" ")),
    warn: (...a) => logs.push(a.map(String).join(" ")),
    error: (...a) => logs.push(a.map(String).join(" ")),
    debug: () => {},
  };

  // -------------------------------------------------------------- Bridge
  class BridgeMiss extends Error {
    constructor() {
      super("dataview bridge: waiting for the exporter");
      this.name = "BridgeMiss";
    }
  }

  const Bridge = {
    results: {},
    misses: [],
    call(kind, ...args) {
      const encodedArgs = encode(args);
      const key = kind + ":" + JSON.stringify(encodedArgs);
      if (key in Bridge.results) {
        const answer = JSON.parse(Bridge.results[key]);
        if ("error" in answer) throw new Error(answer.error);
        return revive(answer.value);
      }
      if (!Bridge.misses.some(m => m.key === key)) Bridge.misses.push({ key, kind, args: encodedArgs });
      throw new BridgeMiss();
    },
  };

  // Values to JSON for the exporter, and back.
  function encode(value, depth = 0) {
    if (depth > 60) return "...";
    if (value === undefined || value === null) return null;
    if (typeof value === "number") {
      if (Number.isFinite(value)) return value;
      return { $dv: "num", v: String(value) };
    }
    if (typeof value === "string" || typeof value === "boolean") return value;
    if (typeof value === "bigint") return Number(value);
    if (typeof value === "function") return { $dv: "fn" };
    if (DataArray.isDataArray(value)) return value.values.map(v => encode(v, depth + 1));
    if (oldArrayIsArray(value)) return value.map(v => encode(v, depth + 1));
    if (value instanceof DateTime) {
      const zone = value.zone.type === "system" ? "local" : value.zone.name;
      return { $dv: "date", ts: value.toMillis(), zone };
    }
    if (value instanceof Duration) return { $dv: "dur", v: value.toObject() };
    if (value instanceof Link) {
      return {
        $dv: "link",
        path: value.path,
        display: value.display ?? null,
        subpath: value.subpath ?? null,
        embed: !!value.embed,
        type: value.type,
      };
    }
    if (value instanceof ListPairWidget) return { $dv: "pair", k: encode(value.key, depth + 1), v: encode(value.value, depth + 1) };
    if (value instanceof ExternalLinkWidget) return { $dv: "elink", url: value.url, display: value.display ?? null };
    if (value instanceof Widget) return { $dv: "widget", name: value.$widget };
    if (value instanceof FakeElement) return { $dv: "el", el: encodeElement(value, depth + 1) };
    if (value instanceof Date) return { $dv: "date", ts: value.getTime(), zone: "local" };
    if (value instanceof Result) return { $dv: "class", name: "Result" };
    if (typeof value === "object") {
      const name = value.constructor?.name;
      if (name && name !== "Object") return { $dv: "class", name };
      const out = {};
      for (const [k, v] of Object.entries(value)) out[k] = encode(v, depth + 1);
      if ("$dv" in out) return { $dv: "obj", v: out };
      return out;
    }
    return null;
  }

  function encodeElement(el, depth = 0) {
    return {
      tag: el.tag,
      cls: el.cls,
      attrs: el.attrs,
      children: el.children.map(c => encodeNode(c, depth + 1)),
    };
  }

  function encodeNode(node, depth) {
    if (node instanceof FakeElement) return { t: "el", ...encodeElement(node, depth) };
    if (node && node.nodeType === "text") return { t: "text", text: node.text };
    if (node && node.nodeType === "html") return { t: "html", html: node.html };
    if (node && node.nodeType === "value") return { t: "value", v: encode(node.value, depth + 1), expand: node.expand };
    if (node && node.nodeType === "view") return { t: "view", kind: node.kind, data: encode(node.data, depth + 1) };
    if (node && node.nodeType === "query") return { t: "query", source: node.source };
    if (node && node.nodeType === "error") return { t: "error", text: node.text };
    return { t: "text", text: String(node) };
  }

  function revive(value) {
    if (value === null || typeof value !== "object") return value;
    if (oldArrayIsArray(value)) return value.map(revive);
    switch (value.$dv) {
      case "num":
        return Number(value.v);
      case "date": {
        const opts = value.zone && value.zone !== "local" ? { zone: value.zone } : {};
        return DateTime.fromMillis(value.ts, opts);
      }
      case "dur":
        return Duration.fromObject(value.v);
      case "link":
        return new Link({
          path: value.path,
          display: value.display ?? undefined,
          subpath: value.subpath ?? undefined,
          embed: value.embed,
          type: value.type,
        });
      case "pair":
        return new ListPairWidget(revive(value.k), revive(value.v));
      case "elink":
        return new ExternalLinkWidget(value.url, value.display ?? undefined);
      case "fn":
        return () => {
          throw new Error("functions cannot be passed between Dataview and the exporter");
        };
      case "obj":
        return reviveObject(value.v);
      case "page": {
        const page = reviveObject(value.v);
        for (const [key, v] of Object.entries(page.file)) {
          if (Array.isArray(v)) page.file[key] = DataArray.wrap(v, SETTINGS);
        }
        return page;
      }
      case "undefined":
        return undefined;
      case "result":
        return value.ok ? Result.success(revive(value.value)) : Result.failure(value.error);
      default:
        if ("$dv" in value) return value;
        return reviveObject(value);
    }
  }

  function reviveObject(obj) {
    const out = {};
    for (const [k, v] of Object.entries(obj)) out[k] = revive(v);
    return out;
  }

  // ---------------------------------------------------------------- dv API
  function valueNode(value, expand) {
    return { nodeType: "value", value, expand };
  }

  function markdownTable(headers, values, settings) {
    if (values.length > 0 && headers.length != values[0].length)
      throw new Error(`The number of headers (${headers.length}) must match the number of columns (${values[0].length})`);
    const escapeTable = text => text.split(/(?!\\)\|/i).join("\\|");
    const rawTableLiteral = (value, allowHtml) => {
      if (!allowHtml) return Values.toString(value, settings);
      if (Values.isArray(value)) return `<ul>${value.map(v => "<li>" + tableLiteral(v, allowHtml) + "</li>").join("")}</ul>`;
      if (Values.isObject(value)) {
        const inner = Object.entries(value)
          .map(([k, v]) => `<li><b>${tableLiteral(k, allowHtml)}</b>: ${tableLiteral(v, allowHtml)}</li>`)
          .join("");
        return `<ul>${inner}</ul>`;
      }
      return Values.toString(value, settings);
    };
    const tableLiteral = (value, allowHtml = true) => escapeTable(rawTableLiteral(value, allowHtml));
    const padright = (text, padding, length) => (text.length >= length ? text : text + padding.repeat(length - text.length));
    const mvalues = [];
    const maxLengths = Array.from(headers, v => escapeTable(v).length);
    for (let row = 0; row < values.length; row++) {
      const current = [];
      for (let col = 0; col < values[row].length; col++) {
        const text = tableLiteral(values[row][col], settings.allowHtml);
        current.push(text);
        maxLengths[col] = Math.max(maxLengths[col], text.length);
      }
      mvalues.push(current);
    }
    let table = `| ${headers.map((v, i) => padright(escapeTable(v), " ", maxLengths[i])).join(" | ")} |\n`;
    table += `| ${maxLengths.map(i => padright("", "-", i)).join(" | ")} |\n`;
    for (let row = 0; row < values.length; row++) {
      table += `| ${mvalues[row].map((v, i) => padright(v, " ", maxLengths[i])).join(" | ")} |\n`;
    }
    return table;
  }

  function markdownListRec(input, settings, depth = 0) {
    if (Values.isArray(input)) {
      let result = depth == 0 ? "" : "\n";
      for (const value of input) {
        result += "    ".repeat(depth) + "- ";
        result += markdownListRec(value, settings, depth);
        result += "\n";
      }
      return result;
    } else if (Values.isObject(input)) {
      let result = depth == 0 ? "" : "\n";
      for (const [key, value] of Object.entries(input)) {
        result += "    ".repeat(depth) + "- ";
        result += Values.toString(key) + ": ";
        result += markdownListRec(value, settings, depth);
        result += "\n";
      }
      return result;
    } else if (Values.isWidget(input) && Widgets.isListPair(input)) {
      return `${Values.toString(input.key)}: ${markdownListRec(input.value, settings, depth + 1)}`;
    }
    return Values.toString(input);
  }

  function listId(item) {
    return item.path + ":" + item.line;
  }

  function nestItems(raw) {
    const elements = new Map();
    for (const elem of raw) elements.set(listId(elem), elem);
    const enumerate = item => {
      if (!elements.has(listId(item))) elements.set(listId(item), item);
      for (const child of item.children) enumerate(child);
    };
    for (const elem of raw) enumerate(elem);
    const replaceChildren = els =>
      els.map(element => {
        element.children = replaceChildren(element.children);
        return elements.get(listId(element)) ?? element;
      });
    const roots = raw.filter(e => e.parent == undefined || e.parent == null || !elements.has(e.path + ":" + e.parent));
    return replaceChildren(roots);
  }

  function nestGroups(raw) {
    if (Groupings.isGrouping(raw)) return raw.map(g => ({ key: g.key, rows: nestGroups(g.rows) }));
    return nestItems(raw);
  }

  function markdownTaskList(tasks, settings, depth = 0) {
    if (Groupings.isGrouping(tasks)) {
      let result = "";
      for (const element of tasks) {
        result += "#".repeat(depth + 1) + " " + Values.toString(element.key) + "\n\n";
        result += markdownTaskList(element.rows, settings, depth + 1);
      }
      return result;
    }
    const dedupTasks = nestItems(tasks);
    let result = "";
    for (const element of dedupTasks) {
      result += "    ".repeat(depth) + "- ";
      if (element.task) result += `[${element.status}] ${(element.visual ?? element.text).split("\n").join(" ")}\n`;
      else result += `${(element.visual ?? element.text).split("\n").join(" ")}\n`;
      result += markdownTaskList(element.children, settings, depth + 1);
    }
    return result;
  }

  function makeIo(origin) {
    return {
      csv: (path, originFile) => Promise.resolve().then(() => {
        if (!Values.isLink(path) && !Values.isString(path))
          throw Error(`dv.io.csv only handles string or link paths; was provided type '${typeof path}'.`);
        return DataArray.from(Bridge.call("csv", Values.isLink(path) ? path.path : path, originFile || origin), SETTINGS);
      }),
      load: (path, originFile) => Promise.resolve().then(() => {
        if (!Values.isLink(path) && !Values.isString(path))
          throw Error(`dv.io.load only handles string or link paths; was provided type '${typeof path}'.`);
        return Bridge.call("load", Values.isLink(path) ? path.path : path, originFile || origin);
      }),
      normalize: (path, originFile) => Bridge.call("normalize", Values.isLink(path) ? path.path : path, originFile || origin),
    };
  }

  class DvApi {
    constructor(origin, container) {
      this.currentFilePath = origin;
      this.container = container;
      this.settings = SETTINGS;
      this.value = Values;
      this.widget = Widgets;
      this.luxon = luxon;
      this.io = makeIo(origin);
      this.version = { current: "0.5.68", compare: () => true, satisfies: () => true };
      const self = this;
      this.func = new Proxy(
        {},
        {
          get(_t, name) {
            if (typeof name !== "string") return undefined;
            return (...args) => {
              if (args.some(a => typeof a === "function"))
                throw new Error(`dv.func.${name} with a JavaScript function is not supported in the PDF export`);
              return Bridge.call("func", name, args, self.currentFilePath);
            };
          },
        }
      );
    }
    pagePaths(query) {
      return DataArray.from(Bridge.call("pagePaths", query ?? "", this.currentFilePath), SETTINGS);
    }
    page(path) {
      if (!(typeof path === "string") && !Values.isLink(path))
        throw Error("dv.page only handles string and link paths; was provided type '" + typeof path + "'");
      const result = Bridge.call("page", path instanceof Link ? path.path : path, this.currentFilePath);
      return result === null ? undefined : result;
    }
    pages(query) {
      return DataArray.from(Bridge.call("pages", query ?? "", this.currentFilePath), SETTINGS);
    }
    current() {
      return this.page(this.currentFilePath);
    }
    async query(source, originFile, settings) {
      return Bridge.call("query", source, originFile ?? this.currentFilePath, settings ?? null);
    }
    async tryQuery(source, originFile, settings) {
      return (await this.query(source, originFile, settings)).orElseThrow();
    }
    async queryMarkdown(source, originFile, settings) {
      const result = await this.query(source, originFile, settings);
      if (!result.successful) return result;
      const combined = Object.assign({}, SETTINGS, settings);
      switch (result.value.type) {
        case "list":
          return Result.success(markdownListRec(result.value.values, combined, 0));
        case "table":
          return Result.success(markdownTable(result.value.headers, result.value.values, combined));
        case "task":
          return Result.success(markdownTaskList(nestGroups(result.value.values), combined));
        default:
          return Result.failure("Cannot render calendar queries to markdown.");
      }
    }
    async tryQueryMarkdown(source, originFile, settings) {
      return (await this.queryMarkdown(source, originFile, settings)).orElseThrow();
    }
    evaluate(expression, context) {
      return Bridge.call("evaluate", expression, context ?? null, this.currentFilePath);
    }
    tryEvaluate(expression, context) {
      return this.evaluate(expression, context).orElseThrow();
    }
    async execute(source) {
      this.container.appendChild({ nodeType: "query", source });
    }
    async executeJs(code) {
      const sub = new FakeElement("div");
      this.container.appendChild(sub);
      await runScript(code, new DvApi(this.currentFilePath, sub), sub);
    }
    array(raw) {
      if (DataArray.isDataArray(raw)) return raw;
      if (Array.isArray(raw)) return DataArray.wrap(raw, SETTINGS);
      return DataArray.wrap([raw], SETTINGS);
    }
    isArray(raw) {
      return DataArray.isDataArray(raw) || Array.isArray(raw);
    }
    isDataArray(raw) {
      return DataArray.isDataArray(raw);
    }
    fileLink(path, embed = false, display) {
      return Link.file(path, embed, display);
    }
    sectionLink(path, section, embed = false, display) {
      return Link.header(path, section, embed, display);
    }
    blockLink(path, blockId, embed = false, display) {
      return Link.block(path, blockId, embed, display);
    }
    date(pathlike) {
      return this.func.date(pathlike);
    }
    duration(str) {
      return this.func.dur(str);
    }
    parse(value) {
      return Bridge.call("parse", value);
    }
    literal(value) {
      return Bridge.call("literal", value);
    }
    clone(value) {
      return Values.deepCopy(value);
    }
    compare(a, b) {
      return Values.compareValue(a, b);
    }
    equal(a, b) {
      return this.compare(a, b) == 0;
    }
    el(el, text, { container = this.container, ...options } = {}) {
      const wrapped = Values.wrapValue(text);
      const elem = new FakeElement(el);
      if (wrapped === null || wrapped === undefined) {
        applyInfo(elem, Object.assign({ text }, options));
        container.appendChild(elem);
        return elem;
      }
      applyInfo(elem, options);
      container.appendChild(elem);
      elem.children.push(valueNode(wrapped.value, true));
      return elem;
    }
    header(level, text, options) {
      const header = { 1: "h1", 2: "h2", 3: "h3", 4: "h4", 5: "h5", 6: "h6" }[level];
      if (!header) throw Error(`Unrecognized level '${level}' (expected 1, 2, 3, 4, 5, or 6)`);
      return this.el(header, text, options);
    }
    paragraph(text, options) {
      return this.el("p", text, options);
    }
    span(text, options) {
      return this.el("span", text, options);
    }
    async view(viewName, input) {
      const found = Bridge.call("view", viewName, this.currentFilePath);
      if (!found) {
        this.container.appendChild({
          nodeType: "error",
          text: `Dataview: custom view not found for '${viewName}.js' or '${viewName}/view.js'.`,
        });
        return;
      }
      let contents = found.code;
      if (contents.includes("await")) contents = "(async () => { " + contents + " })()";
      const func = new Function("dv", "input", contents);
      try {
        const result = await Promise.resolve(func(this, input));
        if (result) this.container.appendChild(valueNode(result, true));
      } catch (ex) {
        if (ex instanceof BridgeMiss) throw ex;
        this.container.appendChild({ nodeType: "error", text: `Dataview: Failed to execute view '${found.path}'.\n\n${ex}` });
      }
    }
    list(values) {
      if (!values) return;
      if (values !== undefined && values !== null && !Array.isArray(values) && !DataArray.isDataArray(values))
        values = Array.from(values);
      const sub = new FakeElement("div");
      this.container.appendChild(sub);
      sub.children.push({ nodeType: "view", kind: "list", data: values });
    }
    table(headers, values) {
      if (!headers) headers = [];
      if (!values) values = [];
      if (!Array.isArray(headers) && !DataArray.isDataArray(headers)) headers = Array.from(headers);
      const sub = new FakeElement("div");
      this.container.appendChild(sub);
      sub.children.push({ nodeType: "view", kind: "table", data: { headers, values } });
    }
    taskList(tasks, groupByFile = true) {
      const grouped =
        !Groupings.isGrouping(tasks) && groupByFile ? this.array(tasks).groupBy(t => Link.file(t.path)) : tasks;
      const sub = new FakeElement("div");
      this.container.appendChild(sub);
      sub.children.push({ nodeType: "view", kind: "tasks", data: grouped });
    }
    markdownTable(headers, values, settings) {
      if (!headers) headers = [];
      if (!values) values = [];
      return markdownTable(headers, values, Object.assign({}, SETTINGS, settings));
    }
    markdownList(values, settings) {
      if (!values) values = [];
      return markdownListRec(values, Object.assign({}, SETTINGS, settings), 0);
    }
    markdownTaskList(values, settings) {
      if (!values) values = [];
      return markdownTaskList(nestGroups(values), Object.assign({}, SETTINGS, settings));
    }
  }

  async function runScript(script, api) {
    const full = "const dataview = this;const dv = this;" + script;
    if (full.includes("await")) return G.__dvEval.call(api, "(async () => { " + full + " })()");
    return G.__dvEval.call(api, full);
  }

  // ------------------------------------------------------------ Entry points
  G.__dvBridge = Bridge;
  G.__dvState = { done: false, error: null, output: null, result: null };

  G.__dvSetup = function (settingsJson) {
    SETTINGS = JSON.parse(settingsJson);
  };

  function finish(state, container) {
    state.output = JSON.stringify(encodeElement(container));
  }

  G.__dvStart = function (script, origin, inline) {
    Bridge.misses = [];
    logs.length = 0;
    const container = new FakeElement("div");
    const api = new DvApi(origin, container);
    const state = { done: false, error: null, miss: false, output: null, result: null };
    G.__dvState = state;
    let promise;
    try {
      promise = Promise.resolve(runScript(script, api));
    } catch (e) {
      promise = Promise.reject(e);
    }
    return promise.then(
      result => {
        state.done = true;
        if (inline && result !== undefined) state.result = JSON.stringify(encode(result));
        finish(state, container);
        return JSON.stringify({ misses: Bridge.misses, state });
      },
      error => {
        state.done = true;
        state.miss = error instanceof BridgeMiss;
        state.error = inline ? String(error) : error && error.stack ? String(error.stack) : String(error);
        finish(state, container);
        return JSON.stringify({ misses: Bridge.misses, state });
      }
    );
  };

  G.__dvAnswer = function (key, answerJson) {
    Bridge.results[key] = answerJson;
  };

  G.__dvLink = Link;
  G.__dvDataArray = DataArray;
  G.__dvValues = Values;
  G.__dvWidgets = Widgets;
})();
