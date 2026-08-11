(() => {
  var __defProp = Object.defineProperty;
  var __require = /* @__PURE__ */ ((x) => typeof require !== "undefined" ? require : typeof Proxy !== "undefined" ? new Proxy(x, {
    get: (a, b) => (typeof require !== "undefined" ? require : a)[b]
  }) : x)(function(x) {
    if (typeof require !== "undefined") return require.apply(this, arguments);
    throw Error('Dynamic require of "' + x + '" is not supported');
  });
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-web/dist/ort.webgpu.bundle.min.mjs
  var ort_webgpu_bundle_min_exports = {};
  __export(ort_webgpu_bundle_min_exports, {
    InferenceSession: () => qf,
    TRACE: () => Ga,
    TRACE_EVENT_BEGIN: () => $e,
    TRACE_EVENT_END: () => ze,
    TRACE_FUNC_BEGIN: () => tt,
    TRACE_FUNC_END: () => rt,
    Tensor: () => Le,
    default: () => gl,
    env: () => K,
    registerBackend: () => Ke
  });
  var import_meta = {};
  var jr = Object.defineProperty;
  var zf = Object.getOwnPropertyDescriptor;
  var Vf = Object.getOwnPropertyNames;
  var jf = Object.prototype.hasOwnProperty;
  var Hr = ((a) => typeof __require < "u" ? __require : typeof Proxy < "u" ? new Proxy(a, { get: (r, s) => (typeof __require < "u" ? __require : r)[s] }) : a)(function(a) {
    if (typeof __require < "u") return __require.apply(this, arguments);
    throw Error('Dynamic require of "' + a + '" is not supported');
  });
  var k = (a, r) => () => (a && (r = a(a = 0)), r);
  var At = (a, r) => {
    for (var s in r) jr(a, s, { get: r[s], enumerable: true });
  };
  var Hf = (a, r, s, f) => {
    if (r && typeof r == "object" || typeof r == "function") for (let i of Vf(r)) !jf.call(a, i) && i !== s && jr(a, i, { get: () => r[i], enumerable: !(f = zf(r, i)) || f.enumerable });
    return a;
  };
  var $t = (a) => Hf(jr({}, "__esModule", { value: true }), a);
  var zt;
  var Ze;
  var Ke;
  var Yf;
  var Ta;
  var Yr = k(() => {
    "use strict";
    zt = /* @__PURE__ */ new Map(), Ze = [], Ke = (a, r, s) => {
      if (r && typeof r.init == "function" && typeof r.createInferenceSessionHandler == "function") {
        let f = zt.get(a);
        if (f === void 0) zt.set(a, { backend: r, priority: s });
        else {
          if (f.priority > s) return;
          if (f.priority === s && f.backend !== r) throw new Error(`cannot register backend "${a}" using priority ${s}`);
        }
        if (s >= 0) {
          let i = Ze.indexOf(a);
          i !== -1 && Ze.splice(i, 1);
          for (let d = 0; d < Ze.length; d++) if (zt.get(Ze[d]).priority <= s) {
            Ze.splice(d, 0, a);
            return;
          }
          Ze.push(a);
        }
        return;
      }
      throw new TypeError("not a valid backend");
    }, Yf = async (a) => {
      let r = zt.get(a);
      if (!r) return "backend not found.";
      if (r.initialized) return r.backend;
      if (r.aborted) return r.error;
      {
        let s = !!r.initPromise;
        try {
          return s || (r.initPromise = r.backend.init(a)), await r.initPromise, r.initialized = true, r.backend;
        } catch (f) {
          return s || (r.error = `${f}`, r.aborted = true), r.error;
        } finally {
          delete r.initPromise;
        }
      }
    }, Ta = async (a) => {
      let r = a.executionProviders || [], s = r.map((y) => typeof y == "string" ? y : y.name), f = s.length === 0 ? Ze : s, i, d = [], l = /* @__PURE__ */ new Set();
      for (let y of f) {
        let w = await Yf(y);
        typeof w == "string" ? d.push({ name: y, err: w }) : (i || (i = w), i === w && l.add(y));
      }
      if (!i) throw new Error(`no available backend found. ERR: ${d.map((y) => `[${y.name}] ${y.err}`).join(", ")}`);
      for (let { name: y, err: w } of d) s.includes(y) && console.warn(`removing requested execution provider "${y}" from session options because it is not available: ${w}`);
      let m = r.filter((y) => l.has(typeof y == "string" ? y : y.name));
      return [i, new Proxy(a, { get: (y, w) => w === "executionProviders" ? m : Reflect.get(y, w) })];
    };
  });
  var va = k(() => {
    "use strict";
    Yr();
  });
  var Ea;
  var Sa = k(() => {
    "use strict";
    Ea = "1.24.0-dev.20251116-b39e144322";
  });
  var Aa;
  var ie;
  var qr = k(() => {
    "use strict";
    Sa();
    Aa = "warning", ie = { wasm: {}, webgl: {}, webgpu: {}, versions: { common: Ea }, set logLevel(a) {
      if (a !== void 0) {
        if (typeof a != "string" || ["verbose", "info", "warning", "error", "fatal"].indexOf(a) === -1) throw new Error(`Unsupported logging level: ${a}`);
        Aa = a;
      }
    }, get logLevel() {
      return Aa;
    } };
    Object.defineProperty(ie, "logLevel", { enumerable: true });
  });
  var K;
  var Ia = k(() => {
    "use strict";
    qr();
    K = ie;
  });
  var xa;
  var La;
  var Oa = k(() => {
    "use strict";
    xa = (a, r) => {
      let s = typeof document < "u" ? document.createElement("canvas") : new OffscreenCanvas(1, 1);
      s.width = a.dims[3], s.height = a.dims[2];
      let f = s.getContext("2d");
      if (f != null) {
        let i, d;
        r?.tensorLayout !== void 0 && r.tensorLayout === "NHWC" ? (i = a.dims[2], d = a.dims[3]) : (i = a.dims[3], d = a.dims[2]);
        let l = r?.format !== void 0 ? r.format : "RGB", m = r?.norm, y, w;
        m === void 0 || m.mean === void 0 ? y = [255, 255, 255, 255] : typeof m.mean == "number" ? y = [m.mean, m.mean, m.mean, m.mean] : (y = [m.mean[0], m.mean[1], m.mean[2], 0], m.mean[3] !== void 0 && (y[3] = m.mean[3])), m === void 0 || m.bias === void 0 ? w = [0, 0, 0, 0] : typeof m.bias == "number" ? w = [m.bias, m.bias, m.bias, m.bias] : (w = [m.bias[0], m.bias[1], m.bias[2], 0], m.bias[3] !== void 0 && (w[3] = m.bias[3]));
        let T = d * i, g = 0, v = T, S = T * 2, C = -1;
        l === "RGBA" ? (g = 0, v = T, S = T * 2, C = T * 3) : l === "RGB" ? (g = 0, v = T, S = T * 2) : l === "RBG" && (g = 0, S = T, v = T * 2);
        for (let R = 0; R < d; R++) for (let H = 0; H < i; H++) {
          let U2 = (a.data[g++] - w[0]) * y[0], M2 = (a.data[v++] - w[1]) * y[1], Y2 = (a.data[S++] - w[2]) * y[2], O = C === -1 ? 255 : (a.data[C++] - w[3]) * y[3];
          f.fillStyle = "rgba(" + U2 + "," + M2 + "," + Y2 + "," + O + ")", f.fillRect(H, R, 1, 1);
        }
        if ("toDataURL" in s) return s.toDataURL();
        throw new Error("toDataURL is not supported");
      } else throw new Error("Can not access image data");
    }, La = (a, r) => {
      let s = typeof document < "u" ? document.createElement("canvas").getContext("2d") : new OffscreenCanvas(1, 1).getContext("2d"), f;
      if (s != null) {
        let i, d, l;
        r?.tensorLayout !== void 0 && r.tensorLayout === "NHWC" ? (i = a.dims[2], d = a.dims[1], l = a.dims[3]) : (i = a.dims[3], d = a.dims[2], l = a.dims[1]);
        let m = r !== void 0 && r.format !== void 0 ? r.format : "RGB", y = r?.norm, w, T;
        y === void 0 || y.mean === void 0 ? w = [255, 255, 255, 255] : typeof y.mean == "number" ? w = [y.mean, y.mean, y.mean, y.mean] : (w = [y.mean[0], y.mean[1], y.mean[2], 255], y.mean[3] !== void 0 && (w[3] = y.mean[3])), y === void 0 || y.bias === void 0 ? T = [0, 0, 0, 0] : typeof y.bias == "number" ? T = [y.bias, y.bias, y.bias, y.bias] : (T = [y.bias[0], y.bias[1], y.bias[2], 0], y.bias[3] !== void 0 && (T[3] = y.bias[3]));
        let g = d * i;
        if (r !== void 0 && (r.format !== void 0 && l === 4 && r.format !== "RGBA" || l === 3 && r.format !== "RGB" && r.format !== "BGR")) throw new Error("Tensor format doesn't match input tensor dims");
        let v = 4, S = 0, C = 1, R = 2, H = 3, U2 = 0, M2 = g, Y2 = g * 2, O = -1;
        m === "RGBA" ? (U2 = 0, M2 = g, Y2 = g * 2, O = g * 3) : m === "RGB" ? (U2 = 0, M2 = g, Y2 = g * 2) : m === "RBG" && (U2 = 0, Y2 = g, M2 = g * 2), f = s.createImageData(i, d);
        for (let W2 = 0; W2 < d * i; S += v, C += v, R += v, H += v, W2++) f.data[S] = (a.data[U2++] - T[0]) * w[0], f.data[C] = (a.data[M2++] - T[1]) * w[1], f.data[R] = (a.data[Y2++] - T[2]) * w[2], f.data[H] = O === -1 ? 255 : (a.data[O++] - T[3]) * w[3];
      } else throw new Error("Can not access image data");
      return f;
    };
  });
  var Jr;
  var Ba;
  var Ma;
  var Ca;
  var Ua;
  var Da;
  var Pa = k(() => {
    "use strict";
    Vt();
    Jr = (a, r) => {
      if (a === void 0) throw new Error("Image buffer must be defined");
      if (r.height === void 0 || r.width === void 0) throw new Error("Image height and width must be defined");
      if (r.tensorLayout === "NHWC") throw new Error("NHWC Tensor layout is not supported yet");
      let { height: s, width: f } = r, i = r.norm ?? { mean: 255, bias: 0 }, d, l;
      typeof i.mean == "number" ? d = [i.mean, i.mean, i.mean, i.mean] : d = [i.mean[0], i.mean[1], i.mean[2], i.mean[3] ?? 255], typeof i.bias == "number" ? l = [i.bias, i.bias, i.bias, i.bias] : l = [i.bias[0], i.bias[1], i.bias[2], i.bias[3] ?? 0];
      let m = r.format !== void 0 ? r.format : "RGBA", y = r.tensorFormat !== void 0 && r.tensorFormat !== void 0 ? r.tensorFormat : "RGB", w = s * f, T = y === "RGBA" ? new Float32Array(w * 4) : new Float32Array(w * 3), g = 4, v = 0, S = 1, C = 2, R = 3, H = 0, U2 = w, M2 = w * 2, Y2 = -1;
      m === "RGB" && (g = 3, v = 0, S = 1, C = 2, R = -1), y === "RGBA" ? Y2 = w * 3 : y === "RBG" ? (H = 0, M2 = w, U2 = w * 2) : y === "BGR" && (M2 = 0, U2 = w, H = w * 2);
      for (let W2 = 0; W2 < w; W2++, v += g, C += g, S += g, R += g) T[H++] = (a[v] + l[0]) / d[0], T[U2++] = (a[S] + l[1]) / d[1], T[M2++] = (a[C] + l[2]) / d[2], Y2 !== -1 && R !== -1 && (T[Y2++] = (a[R] + l[3]) / d[3]);
      return y === "RGBA" ? new le("float32", T, [1, 4, s, f]) : new le("float32", T, [1, 3, s, f]);
    }, Ba = async (a, r) => {
      let s = typeof HTMLImageElement < "u" && a instanceof HTMLImageElement, f = typeof ImageData < "u" && a instanceof ImageData, i = typeof ImageBitmap < "u" && a instanceof ImageBitmap, d = typeof a == "string", l, m = r ?? {}, y = () => {
        if (typeof document < "u") return document.createElement("canvas");
        if (typeof OffscreenCanvas < "u") return new OffscreenCanvas(1, 1);
        throw new Error("Canvas is not supported");
      }, w = (T) => typeof HTMLCanvasElement < "u" && T instanceof HTMLCanvasElement || T instanceof OffscreenCanvas ? T.getContext("2d") : null;
      if (s) {
        let T = y();
        T.width = a.width, T.height = a.height;
        let g = w(T);
        if (g != null) {
          let v = a.height, S = a.width;
          if (r !== void 0 && r.resizedHeight !== void 0 && r.resizedWidth !== void 0 && (v = r.resizedHeight, S = r.resizedWidth), r !== void 0) {
            if (m = r, r.tensorFormat !== void 0) throw new Error("Image input config format must be RGBA for HTMLImageElement");
            m.tensorFormat = "RGBA", m.height = v, m.width = S;
          } else m.tensorFormat = "RGBA", m.height = v, m.width = S;
          g.drawImage(a, 0, 0), l = g.getImageData(0, 0, S, v).data;
        } else throw new Error("Can not access image data");
      } else if (f) {
        let T, g;
        if (r !== void 0 && r.resizedWidth !== void 0 && r.resizedHeight !== void 0 ? (T = r.resizedHeight, g = r.resizedWidth) : (T = a.height, g = a.width), r !== void 0 && (m = r), m.format = "RGBA", m.height = T, m.width = g, r !== void 0) {
          let v = y();
          v.width = g, v.height = T;
          let S = w(v);
          if (S != null) S.putImageData(a, 0, 0), l = S.getImageData(0, 0, g, T).data;
          else throw new Error("Can not access image data");
        } else l = a.data;
      } else if (i) {
        if (r === void 0) throw new Error("Please provide image config with format for Imagebitmap");
        let T = y();
        T.width = a.width, T.height = a.height;
        let g = w(T);
        if (g != null) {
          let v = a.height, S = a.width;
          return g.drawImage(a, 0, 0, S, v), l = g.getImageData(0, 0, S, v).data, m.height = v, m.width = S, Jr(l, m);
        } else throw new Error("Can not access image data");
      } else {
        if (d) return new Promise((T, g) => {
          let v = y(), S = w(v);
          if (!a || !S) return g();
          let C = new Image();
          C.crossOrigin = "Anonymous", C.src = a, C.onload = () => {
            v.width = C.width, v.height = C.height, S.drawImage(C, 0, 0, v.width, v.height);
            let R = S.getImageData(0, 0, v.width, v.height);
            m.height = v.height, m.width = v.width, T(Jr(R.data, m));
          };
        });
        throw new Error("Input data provided is not supported - aborted tensor creation");
      }
      if (l !== void 0) return Jr(l, m);
      throw new Error("Input data provided is not supported - aborted tensor creation");
    }, Ma = (a, r) => {
      let { width: s, height: f, download: i, dispose: d } = r, l = [1, f, s, 4];
      return new le({ location: "texture", type: "float32", texture: a, dims: l, download: i, dispose: d });
    }, Ca = (a, r) => {
      let { dataType: s, dims: f, download: i, dispose: d } = r;
      return new le({ location: "gpu-buffer", type: s ?? "float32", gpuBuffer: a, dims: f, download: i, dispose: d });
    }, Ua = (a, r) => {
      let { dataType: s, dims: f, download: i, dispose: d } = r;
      return new le({ location: "ml-tensor", type: s ?? "float32", mlTensor: a, dims: f, download: i, dispose: d });
    }, Da = (a, r, s) => new le({ location: "cpu-pinned", type: a, data: r, dims: s ?? [r.length] });
  });
  var et;
  var It;
  var _a;
  var Ra;
  var Na = k(() => {
    "use strict";
    et = /* @__PURE__ */ new Map([["float32", Float32Array], ["uint8", Uint8Array], ["int8", Int8Array], ["uint16", Uint16Array], ["int16", Int16Array], ["int32", Int32Array], ["bool", Uint8Array], ["float64", Float64Array], ["uint32", Uint32Array], ["int4", Uint8Array], ["uint4", Uint8Array]]), It = /* @__PURE__ */ new Map([[Float32Array, "float32"], [Uint8Array, "uint8"], [Int8Array, "int8"], [Uint16Array, "uint16"], [Int16Array, "int16"], [Int32Array, "int32"], [Float64Array, "float64"], [Uint32Array, "uint32"]]), _a = false, Ra = () => {
      if (!_a) {
        _a = true;
        let a = typeof BigInt64Array < "u" && BigInt64Array.from, r = typeof BigUint64Array < "u" && BigUint64Array.from, s = globalThis.Float16Array, f = typeof s < "u" && s.from;
        a && (et.set("int64", BigInt64Array), It.set(BigInt64Array, "int64")), r && (et.set("uint64", BigUint64Array), It.set(BigUint64Array, "uint64")), f ? (et.set("float16", s), It.set(s, "float16")) : et.set("float16", Uint16Array);
      }
    };
  });
  var ka;
  var Wa;
  var Fa = k(() => {
    "use strict";
    Vt();
    ka = (a) => {
      let r = 1;
      for (let s = 0; s < a.length; s++) {
        let f = a[s];
        if (typeof f != "number" || !Number.isSafeInteger(f)) throw new TypeError(`dims[${s}] must be an integer, got: ${f}`);
        if (f < 0) throw new RangeError(`dims[${s}] must be a non-negative integer, got: ${f}`);
        r *= f;
      }
      return r;
    }, Wa = (a, r) => {
      switch (a.location) {
        case "cpu":
          return new le(a.type, a.data, r);
        case "cpu-pinned":
          return new le({ location: "cpu-pinned", data: a.data, type: a.type, dims: r });
        case "texture":
          return new le({ location: "texture", texture: a.texture, type: a.type, dims: r });
        case "gpu-buffer":
          return new le({ location: "gpu-buffer", gpuBuffer: a.gpuBuffer, type: a.type, dims: r });
        case "ml-tensor":
          return new le({ location: "ml-tensor", mlTensor: a.mlTensor, type: a.type, dims: r });
        default:
          throw new Error(`tensorReshape: tensor location ${a.location} is not supported`);
      }
    };
  });
  var le;
  var Vt = k(() => {
    "use strict";
    Oa();
    Pa();
    Na();
    Fa();
    le = class {
      constructor(r, s, f) {
        Ra();
        let i, d;
        if (typeof r == "object" && "location" in r) switch (this.dataLocation = r.location, i = r.type, d = r.dims, r.location) {
          case "cpu-pinned": {
            let m = et.get(i);
            if (!m) throw new TypeError(`unsupported type "${i}" to create tensor from pinned buffer`);
            if (!(r.data instanceof m)) throw new TypeError(`buffer should be of type ${m.name}`);
            this.cpuData = r.data;
            break;
          }
          case "texture": {
            if (i !== "float32") throw new TypeError(`unsupported type "${i}" to create tensor from texture`);
            this.gpuTextureData = r.texture, this.downloader = r.download, this.disposer = r.dispose;
            break;
          }
          case "gpu-buffer": {
            if (i !== "float32" && i !== "float16" && i !== "int32" && i !== "int64" && i !== "uint32" && i !== "uint8" && i !== "bool" && i !== "uint4" && i !== "int4") throw new TypeError(`unsupported type "${i}" to create tensor from gpu buffer`);
            this.gpuBufferData = r.gpuBuffer, this.downloader = r.download, this.disposer = r.dispose;
            break;
          }
          case "ml-tensor": {
            if (i !== "float32" && i !== "float16" && i !== "int32" && i !== "int64" && i !== "uint32" && i !== "uint64" && i !== "int8" && i !== "uint8" && i !== "bool" && i !== "uint4" && i !== "int4") throw new TypeError(`unsupported type "${i}" to create tensor from MLTensor`);
            this.mlTensorData = r.mlTensor, this.downloader = r.download, this.disposer = r.dispose;
            break;
          }
          default:
            throw new Error(`Tensor constructor: unsupported location '${this.dataLocation}'`);
        }
        else {
          let m, y;
          if (typeof r == "string") if (i = r, y = f, r === "string") {
            if (!Array.isArray(s)) throw new TypeError("A string tensor's data must be a string array.");
            m = s;
          } else {
            let w = et.get(r);
            if (w === void 0) throw new TypeError(`Unsupported tensor type: ${r}.`);
            if (Array.isArray(s)) {
              if (r === "float16" && w === Uint16Array || r === "uint4" || r === "int4") throw new TypeError(`Creating a ${r} tensor from number array is not supported. Please use ${w.name} as data.`);
              r === "uint64" || r === "int64" ? m = w.from(s, BigInt) : m = w.from(s);
            } else if (s instanceof w) m = s;
            else if (s instanceof Uint8ClampedArray) if (r === "uint8") m = Uint8Array.from(s);
            else throw new TypeError("A Uint8ClampedArray tensor's data must be type of uint8");
            else if (r === "float16" && s instanceof Uint16Array && w !== Uint16Array) m = new globalThis.Float16Array(s.buffer, s.byteOffset, s.length);
            else throw new TypeError(`A ${i} tensor's data must be type of ${w}`);
          }
          else if (y = s, Array.isArray(r)) {
            if (r.length === 0) throw new TypeError("Tensor type cannot be inferred from an empty array.");
            let w = typeof r[0];
            if (w === "string") i = "string", m = r;
            else if (w === "boolean") i = "bool", m = Uint8Array.from(r);
            else throw new TypeError(`Invalid element type of data array: ${w}.`);
          } else if (r instanceof Uint8ClampedArray) i = "uint8", m = Uint8Array.from(r);
          else {
            let w = It.get(r.constructor);
            if (w === void 0) throw new TypeError(`Unsupported type for tensor data: ${r.constructor}.`);
            i = w, m = r;
          }
          if (y === void 0) y = [m.length];
          else if (!Array.isArray(y)) throw new TypeError("A tensor's dims must be a number array");
          d = y, this.cpuData = m, this.dataLocation = "cpu";
        }
        let l = ka(d);
        if (this.cpuData && l !== this.cpuData.length && !((i === "uint4" || i === "int4") && Math.ceil(l / 2) === this.cpuData.length)) throw new Error(`Tensor's size(${l}) does not match data length(${this.cpuData.length}).`);
        this.type = i, this.dims = d, this.size = l;
      }
      static async fromImage(r, s) {
        return Ba(r, s);
      }
      static fromTexture(r, s) {
        return Ma(r, s);
      }
      static fromGpuBuffer(r, s) {
        return Ca(r, s);
      }
      static fromMLTensor(r, s) {
        return Ua(r, s);
      }
      static fromPinnedBuffer(r, s, f) {
        return Da(r, s, f);
      }
      toDataURL(r) {
        return xa(this, r);
      }
      toImageData(r) {
        return La(this, r);
      }
      get data() {
        if (this.ensureValid(), !this.cpuData) throw new Error("The data is not on CPU. Use `getData()` to download GPU data to CPU, or use `texture` or `gpuBuffer` property to access the GPU data directly.");
        return this.cpuData;
      }
      get location() {
        return this.dataLocation;
      }
      get texture() {
        if (this.ensureValid(), !this.gpuTextureData) throw new Error("The data is not stored as a WebGL texture.");
        return this.gpuTextureData;
      }
      get gpuBuffer() {
        if (this.ensureValid(), !this.gpuBufferData) throw new Error("The data is not stored as a WebGPU buffer.");
        return this.gpuBufferData;
      }
      get mlTensor() {
        if (this.ensureValid(), !this.mlTensorData) throw new Error("The data is not stored as a WebNN MLTensor.");
        return this.mlTensorData;
      }
      async getData(r) {
        switch (this.ensureValid(), this.dataLocation) {
          case "cpu":
          case "cpu-pinned":
            return this.data;
          case "texture":
          case "gpu-buffer":
          case "ml-tensor": {
            if (!this.downloader) throw new Error("The current tensor is not created with a specified data downloader.");
            if (this.isDownloading) throw new Error("The current tensor is being downloaded.");
            try {
              this.isDownloading = true;
              let s = await this.downloader();
              return this.downloader = void 0, this.dataLocation = "cpu", this.cpuData = s, r && this.disposer && (this.disposer(), this.disposer = void 0), s;
            } finally {
              this.isDownloading = false;
            }
          }
          default:
            throw new Error(`cannot get data from location: ${this.dataLocation}`);
        }
      }
      dispose() {
        if (this.isDownloading) throw new Error("The current tensor is being downloaded.");
        this.disposer && (this.disposer(), this.disposer = void 0), this.cpuData = void 0, this.gpuTextureData = void 0, this.gpuBufferData = void 0, this.mlTensorData = void 0, this.downloader = void 0, this.isDownloading = void 0, this.dataLocation = "none";
      }
      ensureValid() {
        if (this.dataLocation === "none") throw new Error("The tensor is disposed.");
      }
      reshape(r) {
        if (this.ensureValid(), this.downloader || this.disposer) throw new Error("Cannot reshape a tensor that owns GPU resource.");
        return Wa(this, r);
      }
    };
  });
  var Le;
  var Xr = k(() => {
    "use strict";
    Vt();
    Le = le;
  });
  var Ga;
  var $a;
  var tt;
  var rt;
  var $e;
  var ze;
  var Qr = k(() => {
    "use strict";
    qr();
    Ga = (a, r) => {
      (typeof ie.trace > "u" ? !ie.wasm.trace : !ie.trace) || console.timeStamp(`${a}::ORT::${r}`);
    }, $a = (a, r) => {
      let s = new Error().stack?.split(/\r\n|\r|\n/g) || [], f = false;
      for (let i = 0; i < s.length; i++) {
        if (f && !s[i].includes("TRACE_FUNC")) {
          let d = `FUNC_${a}::${s[i].trim().split(" ")[1]}`;
          r && (d += `::${r}`), Ga("CPU", d);
          return;
        }
        s[i].includes("TRACE_FUNC") && (f = true);
      }
    }, tt = (a) => {
      (typeof ie.trace > "u" ? !ie.wasm.trace : !ie.trace) || $a("BEGIN", a);
    }, rt = (a) => {
      (typeof ie.trace > "u" ? !ie.wasm.trace : !ie.trace) || $a("END", a);
    }, $e = (a) => {
      (typeof ie.trace > "u" ? !ie.wasm.trace : !ie.trace) || console.time(`ORT::${a}`);
    }, ze = (a) => {
      (typeof ie.trace > "u" ? !ie.wasm.trace : !ie.trace) || console.timeEnd(`ORT::${a}`);
    };
  });
  var jt;
  var za = k(() => {
    "use strict";
    Yr();
    Xr();
    Qr();
    jt = class a {
      constructor(r) {
        this.handler = r;
      }
      async run(r, s, f) {
        tt(), $e("InferenceSession.run");
        let i = {}, d = {};
        if (typeof r != "object" || r === null || r instanceof Le || Array.isArray(r)) throw new TypeError("'feeds' must be an object that use input names as keys and OnnxValue as corresponding values.");
        let l = true;
        if (typeof s == "object") {
          if (s === null) throw new TypeError("Unexpected argument[1]: cannot be null.");
          if (s instanceof Le) throw new TypeError("'fetches' cannot be a Tensor");
          if (Array.isArray(s)) {
            if (s.length === 0) throw new TypeError("'fetches' cannot be an empty array.");
            l = false;
            for (let w of s) {
              if (typeof w != "string") throw new TypeError("'fetches' must be a string array or an object.");
              if (this.outputNames.indexOf(w) === -1) throw new RangeError(`'fetches' contains invalid output name: ${w}.`);
              i[w] = null;
            }
            if (typeof f == "object" && f !== null) d = f;
            else if (typeof f < "u") throw new TypeError("'options' must be an object.");
          } else {
            let w = false, T = Object.getOwnPropertyNames(s);
            for (let g of this.outputNames) if (T.indexOf(g) !== -1) {
              let v = s[g];
              (v === null || v instanceof Le) && (w = true, l = false, i[g] = v);
            }
            if (w) {
              if (typeof f == "object" && f !== null) d = f;
              else if (typeof f < "u") throw new TypeError("'options' must be an object.");
            } else d = s;
          }
        } else if (typeof s < "u") throw new TypeError("Unexpected argument[1]: must be 'fetches' or 'options'.");
        for (let w of this.inputNames) if (typeof r[w] > "u") throw new Error(`input '${w}' is missing in 'feeds'.`);
        if (l) for (let w of this.outputNames) i[w] = null;
        let m = await this.handler.run(r, i, d), y = {};
        for (let w in m) if (Object.hasOwnProperty.call(m, w)) {
          let T = m[w];
          T instanceof Le ? y[w] = T : y[w] = new Le(T.type, T.data, T.dims);
        }
        return ze("InferenceSession.run"), rt(), y;
      }
      async release() {
        return this.handler.dispose();
      }
      static async create(r, s, f, i) {
        tt(), $e("InferenceSession.create");
        let d, l = {};
        if (typeof r == "string") {
          if (d = r, typeof s == "object" && s !== null) l = s;
          else if (typeof s < "u") throw new TypeError("'options' must be an object.");
        } else if (r instanceof Uint8Array) {
          if (d = r, typeof s == "object" && s !== null) l = s;
          else if (typeof s < "u") throw new TypeError("'options' must be an object.");
        } else if (r instanceof ArrayBuffer || typeof SharedArrayBuffer < "u" && r instanceof SharedArrayBuffer) {
          let T = r, g = 0, v = r.byteLength;
          if (typeof s == "object" && s !== null) l = s;
          else if (typeof s == "number") {
            if (g = s, !Number.isSafeInteger(g)) throw new RangeError("'byteOffset' must be an integer.");
            if (g < 0 || g >= T.byteLength) throw new RangeError(`'byteOffset' is out of range [0, ${T.byteLength}).`);
            if (v = r.byteLength - g, typeof f == "number") {
              if (v = f, !Number.isSafeInteger(v)) throw new RangeError("'byteLength' must be an integer.");
              if (v <= 0 || g + v > T.byteLength) throw new RangeError(`'byteLength' is out of range (0, ${T.byteLength - g}].`);
              if (typeof i == "object" && i !== null) l = i;
              else if (typeof i < "u") throw new TypeError("'options' must be an object.");
            } else if (typeof f < "u") throw new TypeError("'byteLength' must be a number.");
          } else if (typeof s < "u") throw new TypeError("'options' must be an object.");
          d = new Uint8Array(T, g, v);
        } else throw new TypeError("Unexpected argument[0]: must be 'path' or 'buffer'.");
        let [m, y] = await Ta(l), w = await m.createInferenceSessionHandler(d, y);
        return ze("InferenceSession.create"), rt(), new a(w);
      }
      startProfiling() {
        this.handler.startProfiling();
      }
      endProfiling() {
        this.handler.endProfiling();
      }
      get inputNames() {
        return this.handler.inputNames;
      }
      get outputNames() {
        return this.handler.outputNames;
      }
      get inputMetadata() {
        return this.handler.inputMetadata;
      }
      get outputMetadata() {
        return this.handler.outputMetadata;
      }
    };
  });
  var qf;
  var Va = k(() => {
    "use strict";
    za();
    qf = jt;
  });
  var ja = k(() => {
    "use strict";
  });
  var Ha = k(() => {
    "use strict";
  });
  var Ya = k(() => {
    "use strict";
  });
  var qa = k(() => {
    "use strict";
  });
  var Zr = {};
  At(Zr, { InferenceSession: () => qf, TRACE: () => Ga, TRACE_EVENT_BEGIN: () => $e, TRACE_EVENT_END: () => ze, TRACE_FUNC_BEGIN: () => tt, TRACE_FUNC_END: () => rt, Tensor: () => Le, env: () => K, registerBackend: () => Ke });
  var Ve = k(() => {
    "use strict";
    va();
    Ia();
    Va();
    Xr();
    ja();
    Ha();
    Qr();
    Ya();
    qa();
  });
  var Ht = k(() => {
    "use strict";
  });
  var Za = {};
  At(Za, { default: () => Jf });
  var Xa;
  var Qa;
  var Jf;
  var Ka = k(() => {
    "use strict";
    Kr();
    je();
    Yt();
    Xa = "ort-wasm-proxy-worker", Qa = globalThis.self?.name === Xa;
    Qa && (self.onmessage = (a) => {
      let { type: r, in: s } = a.data;
      try {
        switch (r) {
          case "init-wasm":
            qt(s.wasm).then(() => {
              Jt(s).then(() => {
                postMessage({ type: r });
              }, (f) => {
                postMessage({ type: r, err: f });
              });
            }, (f) => {
              postMessage({ type: r, err: f });
            });
            break;
          case "init-ep": {
            let { epName: f, env: i } = s;
            Xt(i, f).then(() => {
              postMessage({ type: r });
            }, (d) => {
              postMessage({ type: r, err: d });
            });
            break;
          }
          case "copy-from": {
            let { buffer: f } = s, i = xt(f);
            postMessage({ type: r, out: i });
            break;
          }
          case "create": {
            let { model: f, options: i } = s;
            Qt(f, i).then((d) => {
              postMessage({ type: r, out: d });
            }, (d) => {
              postMessage({ type: r, err: d });
            });
            break;
          }
          case "release":
            Zt(s), postMessage({ type: r });
            break;
          case "run": {
            let { sessionId: f, inputIndices: i, inputs: d, outputIndices: l, options: m } = s;
            Kt(f, i, d, l, new Array(l.length).fill(null), m).then((y) => {
              y.some((w) => w[3] !== "cpu") ? postMessage({ type: r, err: "Proxy does not support non-cpu tensor location." }) : postMessage({ type: r, out: y }, tr([...d, ...y]));
            }, (y) => {
              postMessage({ type: r, err: y });
            });
            break;
          }
          case "end-profiling":
            er(s), postMessage({ type: r });
            break;
          default:
        }
      } catch (f) {
        postMessage({ type: r, err: f });
      }
    });
    Jf = Qa ? null : (a) => new Worker(a ?? ge, { type: "module", name: Xa });
  });
  var ts = {};
  At(ts, { default: () => Xf });
  async function es(a = {}) {
    var r = a, s = !!globalThis.window, f = !!globalThis.WorkerGlobalScope, i = f && self.name?.startsWith("em-pthread");
    r.mountExternalData = (e, t6) => {
      e.startsWith("./") && (e = e.substring(2)), (r.Uc || (r.Uc = /* @__PURE__ */ new Map())).set(e, t6);
    }, r.unmountExternalData = () => {
      delete r.Uc;
    }, globalThis.SharedArrayBuffer ?? new WebAssembly.Memory({ initial: 0, maximum: 0, shared: true }).buffer.constructor;
    let d = () => {
      let e = (t6) => (...n) => {
        let o = Me2;
        return n = t6(...n), Me2 != o ? new Promise((u, c) => {
          Lr2 = { resolve: u, reject: c };
        }) : n;
      };
      (() => {
        for (let t6 of ["_OrtAppendExecutionProvider", "_OrtCreateSession", "_OrtRun", "_OrtRunWithBinding", "_OrtBindInput"]) r[t6] = e(r[t6]);
      })(), typeof jsepRunAsync < "u" && (r._OrtRun = jsepRunAsync(r._OrtRun), r._OrtRunWithBinding = jsepRunAsync(r._OrtRunWithBinding)), d = void 0;
    };
    r.asyncInit = () => {
      d?.();
    };
    var l, m, y = (e, t6) => {
      throw t6;
    }, w = import_meta.url, T = "";
    if (s || f) {
      try {
        T = new URL(".", w).href;
      } catch {
      }
      f && (m = (e) => {
        var t6 = new XMLHttpRequest();
        return t6.open("GET", e, false), t6.responseType = "arraybuffer", t6.send(null), new Uint8Array(t6.response);
      }), l = async (e) => {
        if (oe2(e)) return new Promise((n, o) => {
          var u = new XMLHttpRequest();
          u.open("GET", e, true), u.responseType = "arraybuffer", u.onload = () => {
            u.status == 200 || u.status == 0 && u.response ? n(u.response) : o(u.status);
          }, u.onerror = o, u.send(null);
        });
        var t6 = await fetch(e, { credentials: "same-origin" });
        if (t6.ok) return t6.arrayBuffer();
        throw Error(t6.status + " : " + t6.url);
      };
    }
    var g, v, S, C, R, H, U2 = console.log.bind(console), M2 = console.error.bind(console), Y2 = U2, O = M2, W2 = false, oe2 = (e) => e.startsWith("file://");
    function p() {
      Fe2.buffer != X2.buffer && se2();
    }
    if (i) {
      let e = function(t6) {
        try {
          var n = t6.data, o = n.Oc;
          if (o === "load") {
            let u = [];
            self.onmessage = (c) => u.push(c), H = () => {
              postMessage({ Oc: "loaded" });
              for (let c of u) e(c);
              self.onmessage = e;
            };
            for (let c of n.ce) r[c] && !r[c].proxy || (r[c] = (...h2) => {
              postMessage({ Oc: "callHandler", be: c, args: h2 });
            }, c == "print" && (Y2 = r[c]), c == "printErr" && (O = r[c]));
            Fe2 = n.ie, se2(), v = n.je, bt2(), Gt2();
          } else if (o === "run") {
            (function(u) {
              var c = (p(), A)[u + 52 >>> 2 >>> 0];
              u = (p(), A)[u + 56 >>> 2 >>> 0], Co2(c, c - u), D(c);
            })(n.Nc), Wr2(n.Nc, 0, 0, 1, 0, 0), bn2(), Ar(n.Nc), ne2 || (po2(), ne2 = true);
            try {
              $s2(n.ge, n.Wc);
            } catch (u) {
              if (u != "unwind") throw u;
            }
          } else n.target !== "setimmediate" && (o === "checkMailbox" ? ne2 && Dt2() : o && (O(`worker: received unknown command ${o}`), O(n)));
        } catch (u) {
          throw xo2(), u;
        }
      };
      var vc2 = e, ne2 = false;
      self.onunhandledrejection = (t6) => {
        throw t6.reason || t6;
      }, self.onmessage = e;
    }
    var X2, J2, Ue2, Q2, x, A, _, ae2, me2, q2, we2, re = false;
    function se2() {
      var e = Fe2.buffer;
      r.HEAP8 = X2 = new Int8Array(e), Ue2 = new Int16Array(e), r.HEAPU8 = J2 = new Uint8Array(e), Q2 = new Uint16Array(e), r.HEAP32 = x = new Int32Array(e), r.HEAPU32 = A = new Uint32Array(e), _ = new Float32Array(e), ae2 = new Float64Array(e), me2 = new BigInt64Array(e), q2 = new BigUint64Array(e);
    }
    function hr2() {
      re = true, i ? H() : ke2._b();
    }
    function Te2(e) {
      throw O(e = "Aborted(" + e + ")"), W2 = true, e = new WebAssembly.RuntimeError(e + ". Build with -sASSERTIONS for more info."), R?.(e), e;
    }
    function Ye2() {
      return { a: { f: zs2, J: Vs2, k: js2, p: Hs2, l: Ys2, sa: qs2, b: Js2, ca: Xs2, Ja: Sn2, q: Qs2, da: Ln2, Za: On2, Fa: Bn2, Ha: Mn2, _a: Cn2, Xa: Un2, Qa: Dn2, Wa: Pn2, oa: _n2, Ga: Rn2, Xb: Nn2, Ya: kn2, Yb: Wn2, db: Zs2, Da: ei2, Sb: ti2, Qb: ni2, Ca: ai2, M: si2, I: ii2, Rb: ui2, ja: hi2, Tb: yi2, Ta: bi2, Vb: gi2, Ka: Ti2, Ob: vi2, ka: Ei2, Sa: Ar, ab: Si2, U: Li2, n: Ui2, c: Er2, rb: Di2, w: Pi2, L: _i2, z: Ri2, j: Ni2, o: Yn2, sb: ki2, G: Wi2, T: Fi2, h: Gi2, u: $i2, m: zi2, i: Vi2, Na: ji2, Oa: Hi2, Pa: Yi2, La: Qn2, Ma: Zn2, Pb: Kn2, eb: Ji2, cb: Zi2, Y: Ki2, qb: eu2, la: tu2, bb: Xi2, fb: ru2, $a: nu2, Wb: ou2, N: qi2, gb: au2, X: su2, Ub: iu2, nb: yu2, C: bu2, ra: wu2, qa: gu2, pb: Tu2, W: vu2, v: Eu2, mb: Su2, lb: Au2, kb: Iu2, ob: xu2, jb: Lu2, ib: Ou2, hb: Bu2, Ua: ao2, Va: so2, Ia: br2, V: io2, na: uo2, Ra: fo2, ma: co2, Cb: Ff2, xa: Pf2, Db: Wf2, ya: Df2, F: Ef2, e: ff2, s: sf2, x: af2, B: gf2, Fb: Mf2, ba: Bf2, D: lf2, za: Cf2, $: _f2, ga: Of2, Gb: Lf2, Hb: xf2, Ba: Sf2, Aa: If2, Ib: Af2, wa: kf2, aa: Uf2, d: uf2, A: df2, r: cf2, Bb: Gf2, t: mf2, y: Tf2, H: pf2, E: hf2, K: vf2, R: Rf2, ia: wf2, _: Nf2, Jb: bf2, Kb: yf2, g: Cu2, a: Fe2, Nb: qe2, Eb: Uu2, ha: Du2, O: Pu2, pa: _u2, Lb: Ru2, ta: Nu2, Q: ku2, yb: Wu2, zb: Fu2, ua: Gu2, ea: $u2, P: zu2, Ea: Vu2, va: ju2, Z: Hu2, wb: Yu2, Zb: qu2, S: Ju2, Ab: Xu2, tb: Qu2, ub: Ku2, vb: ef2, fa: tf2, xb: rf2, Mb: nf2 } };
    }
    async function bt2() {
      function e(o, u) {
        var c = ke2 = o.exports;
        o = {};
        for (let [h2, b] of Object.entries(c)) typeof b == "function" ? (c = Ai2(b), o[h2] = c) : o[h2] = b;
        return ke2 = o, ke2 = (function() {
          var h2 = ke2, b = (I) => (F2) => I(F2) >>> 0, E2 = (I) => () => I() >>> 0;
          return (h2 = Object.assign({}, h2)).$b = b(h2.$b), h2.Cc = E2(h2.Cc), h2.Ec = b(h2.Ec), h2.rd = /* @__PURE__ */ ((I) => (F2, j) => I(F2, j) >>> 0)(h2.rd), h2.wd = b(h2.wd), h2.xd = E2(h2.xd), h2.Bd = b(h2.Bd), h2;
        })(), hn2.push(ke2.id), lo2 = (o = ke2).$b, po2 = o.ac, r._OrtInit = o.bc, r._OrtGetLastError = o.cc, r._OrtCreateSessionOptions = o.dc, r._OrtAppendExecutionProvider = o.ec, r._OrtAddFreeDimensionOverride = o.fc, r._OrtAddSessionConfigEntry = o.gc, r._OrtReleaseSessionOptions = o.hc, r._OrtCreateSession = o.ic, r._OrtReleaseSession = o.jc, r._OrtGetInputOutputCount = o.kc, r._OrtGetInputOutputMetadata = o.lc, r._OrtFree = o.mc, r._OrtCreateTensor = o.nc, r._OrtGetTensorData = o.oc, r._OrtReleaseTensor = o.pc, r._OrtCreateRunOptions = o.qc, r._OrtAddRunConfigEntry = o.rc, r._OrtReleaseRunOptions = o.sc, r._OrtCreateBinding = o.tc, r._OrtBindInput = o.uc, r._OrtBindOutput = o.vc, r._OrtClearBoundOutputs = o.wc, r._OrtReleaseBinding = o.xc, r._OrtRunWithBinding = o.yc, r._OrtRun = o.zc, r._OrtEndProfiling = o.Ac, Dr2 = r._OrtGetWebGpuDevice = o.Bc, Wt2 = o.Cc, xe2 = r._free = o.Dc, pt2 = r._malloc = o.Ec, mo2 = r._wgpuBufferRelease = o.Fc, ho2 = r._wgpuCreateInstance = o.Gc, yo2 = o.Hc, bo2 = o.Ic, wo2 = o.Jc, go2 = o.Kc, To2 = o.Lc, vo2 = o.Pc, Eo2 = o.Zc, So2 = o._c, Ao2 = o.$c, Pr2 = o.bd, _r2 = o.cd, Rr2 = o.dd, Nr2 = o.ed, Et2 = o.fd, kr2 = o.gd, Io2 = o.hd, Wr2 = o.kd, xo2 = o.ld, Lo2 = o.md, Oo2 = o.nd, Fr2 = o.od, Bo2 = o.pd, Mo2 = o.qd, Gr2 = o.rd, N2 = o.sd, St2 = o.td, Co2 = o.ud, D = o.vd, Ft2 = o.wd, P2 = o.xd, Uo2 = o.yd, $r2 = o.zd, Do2 = o.Ad, Po2 = o.Bd, _o2 = o.Cd, zr2 = o.Dd, Ro2 = o.Ed, No2 = o.Fd, ko2 = o.Gd, Wo2 = o.Hd, Fo2 = o.Id, Go2 = o.Jd, $o2 = o.Kd, zo2 = o.Ld, Vo2 = o.Md, jo2 = o.Nd, Ho2 = o.Od, Yo2 = o.Pd, qo2 = o.Qd, Jo2 = o.Rd, Xo2 = o.Td, Qo2 = o.Ud, Zo2 = o.Vd, Ko2 = o.Wd, ea2 = o.Yd, ta2 = o.Zd, ra2 = o._d, na2 = o.$d, oa2 = o.ae, aa2 = o.oe, sa = o.pe, ia2 = o.qe, ua2 = o.re, fa2 = o.se, ca2 = o.te, da2 = o.ue, la2 = o.ve, pa2 = o.we, ma2 = o.xe, ha2 = o.ye, ya2 = o.Ye, ba2 = o.Ze, wa2 = o._e, ga2 = o.$e, v = u, ke2;
      }
      var t6, n = Ye2();
      return r.instantiateWasm ? new Promise((o) => {
        r.instantiateWasm(n, (u, c) => {
          o(e(u, c));
        });
      }) : i ? e(new WebAssembly.Instance(v, Ye2()), v) : (we2 ??= r.locateFile ? r.locateFile ? r.locateFile("ort-wasm-simd-threaded.asyncify.wasm", T) : T + "ort-wasm-simd-threaded.asyncify.wasm" : new URL("ort-wasm-simd-threaded.asyncify.wasm", import_meta.url).href, t6 = await (async function(o) {
        var u = we2;
        if (!g && !oe2(u)) try {
          var c = fetch(u, { credentials: "same-origin" });
          return await WebAssembly.instantiateStreaming(c, o);
        } catch (h2) {
          O(`wasm streaming compile failed: ${h2}`), O("falling back to ArrayBuffer instantiation");
        }
        return (async function(h2, b) {
          try {
            var E2 = await (async function(I) {
              if (!g) try {
                var F2 = await l(I);
                return new Uint8Array(F2);
              } catch {
              }
              if (I == we2 && g) I = new Uint8Array(g);
              else {
                if (!m) throw "both async and sync fetching of the wasm failed";
                I = m(I);
              }
              return I;
            })(h2);
            return await WebAssembly.instantiate(E2, b);
          } catch (I) {
            O(`failed to asynchronously prepare wasm: ${I}`), Te2(I);
          }
        })(u, o);
      })(n), e(t6.instance, t6.module));
    }
    class wt2 {
      name = "ExitStatus";
      constructor(t6) {
        this.message = `Program terminated with exit(${t6})`, this.status = t6;
      }
    }
    var Se2 = (e) => {
      e.terminate(), e.onmessage = () => {
      };
    }, Ae2 = [], Oe2 = 0, ee = null, Z = (e) => {
      We2.length == 0 && (gn2(), wn2(We2[0]));
      var t6 = We2.pop();
      if (!t6) return 6;
      gt2.push(t6), Je2[e.Nc] = t6, t6.Nc = e.Nc;
      var n = { Oc: "run", ge: e.fe, Wc: e.Wc, Nc: e.Nc };
      return t6.postMessage(n, e.Yc), 0;
    }, G = 0, V = (e, t6, ...n) => {
      var o, u = 16 * n.length, c = P2(), h2 = Ft2(u), b = h2 >>> 3;
      for (o of n) typeof o == "bigint" ? ((p(), me2)[b++ >>> 0] = 1n, (p(), me2)[b++ >>> 0] = o) : ((p(), me2)[b++ >>> 0] = 0n, (p(), ae2)[b++ >>> 0] = o);
      return e = Lo2(e, 0, u, h2, t6), D(c), e;
    };
    function qe2(e) {
      if (i) return V(0, 1, e);
      if (S = e, !(0 < G)) {
        for (var t6 of gt2) Se2(t6);
        for (t6 of We2) Se2(t6);
        We2 = [], gt2 = [], Je2 = {}, W2 = true;
      }
      y(0, new wt2(e));
    }
    function yr2(e) {
      if (i) return V(1, 0, e);
      br2(e);
    }
    var br2 = (e) => {
      if (S = e, i) throw yr2(e), "unwind";
      qe2(e);
    }, We2 = [], gt2 = [], hn2 = [], Je2 = {}, yn2 = (e) => {
      var t6 = e.Nc;
      delete Je2[t6], We2.push(e), gt2.splice(gt2.indexOf(e), 1), e.Nc = 0, Oo2(t6);
    };
    function bn2() {
      hn2.forEach((e) => e());
    }
    var wn2 = (e) => new Promise((t6) => {
      e.onmessage = (u) => {
        var c = u.data;
        if (u = c.Oc, c.Vc && c.Vc != Wt2()) {
          var h2 = Je2[c.Vc];
          h2 ? h2.postMessage(c, c.Yc) : O(`Internal error! Worker sent a message "${u}" to target pthread ${c.Vc}, but that thread no longer exists!`);
        } else u === "checkMailbox" ? Dt2() : u === "spawnThread" ? Z(c) : u === "cleanupThread" ? he2(() => {
          yn2(Je2[c.he]);
        }) : u === "loaded" ? (e.loaded = true, t6(e)) : c.target === "setimmediate" ? e.postMessage(c) : u === "uncaughtException" ? e.onerror(c.error) : u === "callHandler" ? r[c.be](...c.args) : u && O(`worker sent an unknown command ${u}`);
      }, e.onerror = (u) => {
        throw O(`worker sent an error! ${u.filename}:${u.lineno}: ${u.message}`), u;
      };
      var n, o = [];
      for (n of []) r.propertyIsEnumerable(n) && o.push(n);
      e.postMessage({ Oc: "load", ce: o, ie: Fe2, je: v });
    });
    function gn2() {
      var e = new Worker((() => {
        let t6 = URL;
        return import_meta.url > "file:" && import_meta.url < "file;" ? new t6("ort.webgpu.bundle.min.mjs", import_meta.url) : new URL(import_meta.url);
      })(), { type: "module", workerData: "em-pthread", name: "em-pthread" });
      We2.push(e);
    }
    var Fe2, $s2 = (e, t6) => {
      G = 0, e = zr2(e, t6), 0 < G ? S = e : Fr2(e);
    }, Ct2 = [], Ut2 = 0, ce2 = (e) => -9007199254740992 > e || 9007199254740992 < e ? NaN : Number(e);
    function zs2(e) {
      var t6 = new wr2(e >>>= 0);
      return (p(), X2)[t6.Qc + 12 >>> 0] == 0 && (Tn2(t6, true), Ut2--), vn2(t6, false), Ct2.push(t6), Po2(e);
    }
    var ft2 = 0, Vs2 = () => {
      N2(0, 0);
      var e = Ct2.pop();
      Uo2(e.Xc), ft2 = 0;
    };
    function Tn2(e, t6) {
      t6 = t6 ? 1 : 0, (p(), X2)[e.Qc + 12 >>> 0] = t6;
    }
    function vn2(e, t6) {
      t6 = t6 ? 1 : 0, (p(), X2)[e.Qc + 13 >>> 0] = t6;
    }
    class wr2 {
      constructor(t6) {
        this.Xc = t6, this.Qc = t6 - 24;
      }
    }
    var gr2 = (e) => {
      var t6 = ft2;
      if (!t6) return St2(0), 0;
      var n = new wr2(t6);
      (p(), A)[n.Qc + 16 >>> 2 >>> 0] = t6;
      var o = (p(), A)[n.Qc + 4 >>> 2 >>> 0];
      if (!o) return St2(0), t6;
      for (var u of e) {
        if (u === 0 || u === o) break;
        if (Do2(u, o, n.Qc + 16)) return St2(u), t6;
      }
      return St2(o), t6;
    };
    function js2() {
      return gr2([]);
    }
    function Hs2(e) {
      return gr2([e >>> 0]);
    }
    function Ys2(e, t6, n, o) {
      return gr2([e >>> 0, t6 >>> 0, n >>> 0, o >>> 0]);
    }
    var qs2 = () => {
      var e = Ct2.pop();
      e || Te2("no exception to throw");
      var t6 = e.Xc;
      throw (p(), X2)[e.Qc + 13 >>> 0] == 0 && (Ct2.push(e), vn2(e, true), Tn2(e, false), Ut2++), $r2(t6), ft2 = t6;
    };
    function Js2(e, t6, n) {
      var o = new wr2(e >>>= 0);
      throw t6 >>>= 0, n >>>= 0, (p(), A)[o.Qc + 16 >>> 2 >>> 0] = 0, (p(), A)[o.Qc + 4 >>> 2 >>> 0] = t6, (p(), A)[o.Qc + 8 >>> 2 >>> 0] = n, $r2(e), Ut2++, ft2 = e;
    }
    var Xs2 = () => Ut2;
    function En2(e, t6, n, o) {
      return i ? V(2, 1, e, t6, n, o) : Sn2(e, t6, n, o);
    }
    function Sn2(e, t6, n, o) {
      if (e >>>= 0, t6 >>>= 0, n >>>= 0, o >>>= 0, !globalThis.SharedArrayBuffer) return 6;
      var u = [];
      return i && u.length === 0 ? En2(e, t6, n, o) : (e = { fe: n, Nc: e, Wc: o, Yc: u }, i ? (e.Oc = "spawnThread", postMessage(e, u), 0) : Z(e));
    }
    function Qs2(e) {
      throw ft2 ||= e >>> 0, ft2;
    }
    var An2 = globalThis.TextDecoder && new TextDecoder(), In2 = (e, t6, n, o) => {
      if (n = t6 + n, o) return n;
      for (; e[t6] && !(t6 >= n); ) ++t6;
      return t6;
    }, xn2 = (e, t6 = 0, n, o) => {
      if (16 < (n = In2(e, t6 >>>= 0, n, o)) - t6 && e.buffer && An2) return An2.decode(e.buffer instanceof ArrayBuffer ? e.subarray(t6, n) : e.slice(t6, n));
      for (o = ""; t6 < n; ) {
        var u = e[t6++];
        if (128 & u) {
          var c = 63 & e[t6++];
          if ((224 & u) == 192) o += String.fromCharCode((31 & u) << 6 | c);
          else {
            var h2 = 63 & e[t6++];
            65536 > (u = (240 & u) == 224 ? (15 & u) << 12 | c << 6 | h2 : (7 & u) << 18 | c << 12 | h2 << 6 | 63 & e[t6++]) ? o += String.fromCharCode(u) : (u -= 65536, o += String.fromCharCode(55296 | u >> 10, 56320 | 1023 & u));
          }
        } else o += String.fromCharCode(u);
      }
      return o;
    }, ct2 = (e, t6, n) => (e >>>= 0) ? xn2((p(), J2), e, t6, n) : "";
    function Ln2(e, t6, n) {
      return i ? V(3, 1, e, t6, n) : 0;
    }
    function On2(e, t6) {
      if (i) return V(4, 1, e, t6);
    }
    function Bn2(e, t6) {
      if (i) return V(5, 1, e, t6);
    }
    function Mn2(e, t6, n) {
      if (i) return V(6, 1, e, t6, n);
    }
    function Cn2(e, t6, n) {
      return i ? V(7, 1, e, t6, n) : 0;
    }
    function Un2(e, t6) {
      if (i) return V(8, 1, e, t6);
    }
    function Dn2(e, t6, n) {
      if (i) return V(9, 1, e, t6, n);
    }
    function Pn2(e, t6, n, o) {
      if (i) return V(10, 1, e, t6, n, o);
    }
    function _n2(e, t6, n, o) {
      if (i) return V(11, 1, e, t6, n, o);
    }
    function Rn2(e, t6, n, o) {
      if (i) return V(12, 1, e, t6, n, o);
    }
    function Nn2(e) {
      if (i) return V(13, 1, e);
    }
    function kn2(e, t6) {
      if (i) return V(14, 1, e, t6);
    }
    function Wn2(e, t6, n) {
      if (i) return V(15, 1, e, t6, n);
    }
    var Zs2 = () => Te2(""), Be2 = (e) => {
      e >>>= 0;
      for (var t6 = ""; ; ) {
        var n = (p(), J2)[e++ >>> 0];
        if (!n) return t6;
        t6 += String.fromCharCode(n);
      }
    }, Tr2 = {}, vr2 = {}, Ks2 = {}, dt2 = class extends Error {
      constructor(e) {
        super(e), this.name = "BindingError";
      }
    };
    function De2(e, t6, n = {}) {
      return (function(o, u, c = {}) {
        var h2 = u.name;
        if (!o) throw new dt2(`type "${h2}" must have a positive integer typeid pointer`);
        if (vr2.hasOwnProperty(o)) {
          if (c.de) return;
          throw new dt2(`Cannot register type '${h2}' twice`);
        }
        vr2[o] = u, delete Ks2[o], Tr2.hasOwnProperty(o) && (u = Tr2[o], delete Tr2[o], u.forEach((b) => b()));
      })(e, t6, n);
    }
    var Fn2 = (e, t6, n) => {
      switch (t6) {
        case 1:
          return n ? (o) => (p(), X2)[o >>> 0] : (o) => (p(), J2)[o >>> 0];
        case 2:
          return n ? (o) => (p(), Ue2)[o >>> 1 >>> 0] : (o) => (p(), Q2)[o >>> 1 >>> 0];
        case 4:
          return n ? (o) => (p(), x)[o >>> 2 >>> 0] : (o) => (p(), A)[o >>> 2 >>> 0];
        case 8:
          return n ? (o) => (p(), me2)[o >>> 3 >>> 0] : (o) => (p(), q2)[o >>> 3 >>> 0];
        default:
          throw new TypeError(`invalid integer width (${t6}): ${e}`);
      }
    };
    function ei2(e, t6, n, o, u) {
      e >>>= 0, n >>>= 0, t6 = Be2(t6 >>> 0);
      let c = (h2) => h2;
      if (o = o === 0n) {
        let h2 = 8 * n;
        c = (b) => BigInt.asUintN(h2, b), u = c(u);
      }
      De2(e, { name: t6, Mc: c, Sc: (h2, b) => (typeof b == "number" && (b = BigInt(b)), b), Rc: Fn2(t6, n, !o), Tc: null });
    }
    function ti2(e, t6, n, o) {
      De2(e >>>= 0, { name: t6 = Be2(t6 >>> 0), Mc: function(u) {
        return !!u;
      }, Sc: function(u, c) {
        return c ? n : o;
      }, Rc: function(u) {
        return this.Mc((p(), J2)[u >>> 0]);
      }, Tc: null });
    }
    var Gn2 = [], Xe2 = [0, 1, , 1, null, 1, true, 1, false, 1];
    function Er2(e) {
      9 < (e >>>= 0) && --Xe2[e + 1] == 0 && (Xe2[e] = void 0, Gn2.push(e));
    }
    var ve2 = (e) => {
      if (!e) throw new dt2(`Cannot use deleted val. handle = ${e}`);
      return Xe2[e];
    }, Ie2 = (e) => {
      switch (e) {
        case void 0:
          return 2;
        case null:
          return 4;
        case true:
          return 6;
        case false:
          return 8;
        default:
          let t6 = Gn2.pop() || Xe2.length;
          return Xe2[t6] = e, Xe2[t6 + 1] = 1, t6;
      }
    };
    function Sr(e) {
      return this.Mc((p(), A)[e >>> 2 >>> 0]);
    }
    var ri2 = { name: "emscripten::val", Mc: (e) => {
      var t6 = ve2(e);
      return Er2(e), t6;
    }, Sc: (e, t6) => Ie2(t6), Rc: Sr, Tc: null };
    function ni2(e) {
      return De2(e >>> 0, ri2);
    }
    var oi2 = (e, t6) => {
      switch (t6) {
        case 4:
          return function(n) {
            return this.Mc((p(), _)[n >>> 2 >>> 0]);
          };
        case 8:
          return function(n) {
            return this.Mc((p(), ae2)[n >>> 3 >>> 0]);
          };
        default:
          throw new TypeError(`invalid float width (${t6}): ${e}`);
      }
    };
    function ai2(e, t6, n) {
      n >>>= 0, De2(e >>>= 0, { name: t6 = Be2(t6 >>> 0), Mc: (o) => o, Sc: (o, u) => u, Rc: oi2(t6, n), Tc: null });
    }
    function si2(e, t6, n, o, u) {
      e >>>= 0, n >>>= 0, t6 = Be2(t6 >>> 0);
      let c = (b) => b;
      if (o === 0) {
        var h2 = 32 - 8 * n;
        c = (b) => b << h2 >>> h2, u = c(u);
      }
      De2(e, { name: t6, Mc: c, Sc: (b, E2) => E2, Rc: Fn2(t6, n, o !== 0), Tc: null });
    }
    function ii2(e, t6, n) {
      function o(c) {
        var h2 = (p(), A)[c >>> 2 >>> 0];
        return c = (p(), A)[c + 4 >>> 2 >>> 0], new u((p(), X2).buffer, c, h2);
      }
      var u = [Int8Array, Uint8Array, Int16Array, Uint16Array, Int32Array, Uint32Array, Float32Array, Float64Array, BigInt64Array, BigUint64Array][t6];
      De2(e >>>= 0, { name: n = Be2(n >>> 0), Mc: o, Rc: o }, { de: true });
    }
    var Pe2 = (e, t6, n) => {
      var o = (p(), J2);
      if (t6 >>>= 0, 0 < n) {
        var u = t6;
        n = t6 + n - 1;
        for (var c = 0; c < e.length; ++c) {
          var h2 = e.codePointAt(c);
          if (127 >= h2) {
            if (t6 >= n) break;
            o[t6++ >>> 0] = h2;
          } else if (2047 >= h2) {
            if (t6 + 1 >= n) break;
            o[t6++ >>> 0] = 192 | h2 >> 6, o[t6++ >>> 0] = 128 | 63 & h2;
          } else if (65535 >= h2) {
            if (t6 + 2 >= n) break;
            o[t6++ >>> 0] = 224 | h2 >> 12, o[t6++ >>> 0] = 128 | h2 >> 6 & 63, o[t6++ >>> 0] = 128 | 63 & h2;
          } else {
            if (t6 + 3 >= n) break;
            o[t6++ >>> 0] = 240 | h2 >> 18, o[t6++ >>> 0] = 128 | h2 >> 12 & 63, o[t6++ >>> 0] = 128 | h2 >> 6 & 63, o[t6++ >>> 0] = 128 | 63 & h2, c++;
          }
        }
        o[t6 >>> 0] = 0, e = t6 - u;
      } else e = 0;
      return e;
    }, _e2 = (e) => {
      for (var t6 = 0, n = 0; n < e.length; ++n) {
        var o = e.charCodeAt(n);
        127 >= o ? t6++ : 2047 >= o ? t6 += 2 : 55296 <= o && 57343 >= o ? (t6 += 4, ++n) : t6 += 3;
      }
      return t6;
    };
    function ui2(e, t6) {
      De2(e >>>= 0, { name: t6 = Be2(t6 >>> 0), Mc(n) {
        var o = (p(), A)[n >>> 2 >>> 0];
        return o = ct2(n + 4, o, true), xe2(n), o;
      }, Sc(n, o) {
        o instanceof ArrayBuffer && (o = new Uint8Array(o));
        var u = typeof o == "string";
        if (!(u || ArrayBuffer.isView(o) && o.BYTES_PER_ELEMENT == 1)) throw new dt2("Cannot pass non-string to std::string");
        var c = u ? _e2(o) : o.length, h2 = pt2(4 + c + 1), b = h2 + 4;
        return (p(), A)[h2 >>> 2 >>> 0] = c, u ? Pe2(o, b, c + 1) : (p(), J2).set(o, b >>> 0), n !== null && n.push(xe2, h2), h2;
      }, Rc: Sr, Tc(n) {
        xe2(n);
      } });
    }
    var $n2 = globalThis.TextDecoder ? new TextDecoder("utf-16le") : void 0, fi2 = (e, t6, n) => {
      if (e >>>= 1, 16 < (t6 = In2((p(), Q2), e, t6 / 2, n)) - e && $n2) return $n2.decode((p(), Q2).slice(e, t6));
      for (n = ""; e < t6; ++e) {
        var o = (p(), Q2)[e >>> 0];
        n += String.fromCharCode(o);
      }
      return n;
    }, ci2 = (e, t6, n) => {
      if (n ??= 2147483647, 2 > n) return 0;
      var o = t6;
      n = (n -= 2) < 2 * e.length ? n / 2 : e.length;
      for (var u = 0; u < n; ++u) {
        var c = e.charCodeAt(u);
        (p(), Ue2)[t6 >>> 1 >>> 0] = c, t6 += 2;
      }
      return (p(), Ue2)[t6 >>> 1 >>> 0] = 0, t6 - o;
    }, di2 = (e) => 2 * e.length, li2 = (e, t6, n) => {
      var o = "";
      e >>>= 2;
      for (var u = 0; !(u >= t6 / 4); u++) {
        var c = (p(), A)[e + u >>> 0];
        if (!c && !n) break;
        o += String.fromCodePoint(c);
      }
      return o;
    }, pi2 = (e, t6, n) => {
      if (t6 >>>= 0, n ??= 2147483647, 4 > n) return 0;
      var o = t6;
      n = o + n - 4;
      for (var u = 0; u < e.length; ++u) {
        var c = e.codePointAt(u);
        if (65535 < c && u++, (p(), x)[t6 >>> 2 >>> 0] = c, (t6 += 4) + 4 > n) break;
      }
      return (p(), x)[t6 >>> 2 >>> 0] = 0, t6 - o;
    }, mi2 = (e) => {
      for (var t6 = 0, n = 0; n < e.length; ++n) 65535 < e.codePointAt(n) && n++, t6 += 4;
      return t6;
    };
    function hi2(e, t6, n) {
      if (e >>>= 0, t6 >>>= 0, n = Be2(n >>>= 0), t6 === 2) var o = fi2, u = ci2, c = di2;
      else o = li2, u = pi2, c = mi2;
      De2(e, { name: n, Mc: (h2) => {
        var b = (p(), A)[h2 >>> 2 >>> 0];
        return b = o(h2 + 4, b * t6, true), xe2(h2), b;
      }, Sc: (h2, b) => {
        if (typeof b != "string") throw new dt2(`Cannot pass non-string to C++ string type ${n}`);
        var E2 = c(b), I = pt2(4 + E2 + t6);
        return (p(), A)[I >>> 2 >>> 0] = E2 / t6, u(b, I + 4, E2 + t6), h2 !== null && h2.push(xe2, I), I;
      }, Rc: Sr, Tc(h2) {
        xe2(h2);
      } });
    }
    function yi2(e, t6) {
      De2(e >>>= 0, { ee: true, name: t6 = Be2(t6 >>> 0), Mc: () => {
      }, Sc: () => {
      } });
    }
    function bi2(e) {
      Wr2(e >>> 0, !f, 1, !s, 131072, false), bn2();
    }
    var he2 = (e) => {
      if (!W2) try {
        if (e(), !(0 < G)) try {
          i ? Wt2() && Fr2(S) : br2(S);
        } catch (t6) {
          t6 instanceof wt2 || t6 == "unwind" || y(0, t6);
        }
      } catch (t6) {
        t6 instanceof wt2 || t6 == "unwind" || y(0, t6);
      }
    }, wi2 = !Atomics.waitAsync || globalThis.navigator?.userAgent && 91 > Number((navigator.userAgent.match(/Chrom(e|ium)\/([0-9]+)\./) || [])[2]);
    function Ar(e) {
      e >>>= 0, wi2 || (Atomics.waitAsync((p(), x), e >>> 2, e).value.then(Dt2), e += 128, Atomics.store((p(), x), e >>> 2, 1));
    }
    var Dt2 = () => he2(() => {
      var e = Wt2();
      e && (Ar(e), Mo2());
    });
    function gi2(e, t6) {
      (e >>>= 0) == t6 >>> 0 ? setTimeout(Dt2) : i ? postMessage({ Vc: e, Oc: "checkMailbox" }) : (e = Je2[e]) && e.postMessage({ Oc: "checkMailbox" });
    }
    var Ir2 = [];
    function Ti2(e, t6, n, o, u) {
      for (t6 >>>= 0, u >>>= 0, Ir2.length = 0, n = u >>> 3, o = u + o >>> 3; n < o; ) {
        var c;
        c = (p(), me2)[n++ >>> 0] ? (p(), me2)[n++ >>> 0] : (p(), ae2)[n++ >>> 0], Ir2.push(c);
      }
      return (t6 ? Vr2[t6] : of2[e])(...Ir2);
    }
    var vi2 = () => {
      G = 0;
    };
    function Ei2(e) {
      e >>>= 0, i ? postMessage({ Oc: "cleanupThread", he: e }) : yn2(Je2[e]);
    }
    function Si2(e) {
    }
    var Pt2 = (e) => {
      try {
        e();
      } catch (t6) {
        Te2(t6);
      }
    };
    function Ai2(e) {
      var t6 = (...n) => {
        _t2.push(e);
        try {
          return e(...n);
        } finally {
          W2 || (_t2.pop(), Me2 && Ge2 === 1 && _t2.length === 0 && (Ge2 = 0, G += 1, Pt2(ba2), typeof Fibers < "u" && Fibers.Be()));
        }
      };
      return jn2.set(e, t6), t6;
    }
    var Ge2 = 0, Me2 = null, zn2 = 0, _t2 = [], xr2 = /* @__PURE__ */ new Map(), Vn2 = /* @__PURE__ */ new Map(), jn2 = /* @__PURE__ */ new Map(), Ii2 = 0, Lr2 = null, xi2 = [], Hn2 = (e) => (function(t6) {
      if (!W2) {
        if (Ge2 === 0) {
          var n = false, o = false;
          t6((u = 0) => {
            if (!W2 && (zn2 = u, n = true, o)) {
              Ge2 = 2, Pt2(() => wa2(Me2)), typeof MainLoop < "u" && MainLoop.Xd && MainLoop.resume(), u = false;
              try {
                var c = (function() {
                  var E2 = (p(), x)[Me2 + 8 >>> 2 >>> 0];
                  return E2 = Vn2.get(E2), E2 = jn2.get(E2), --G, E2();
                })();
              } catch (E2) {
                c = E2, u = true;
              }
              var h2 = false;
              if (!Me2) {
                var b = Lr2;
                b && (Lr2 = null, (u ? b.reject : b.resolve)(c), h2 = true);
              }
              if (u && !h2) throw c;
            }
          }), o = true, n || (Ge2 = 1, Me2 = (function() {
            var u = pt2(65548), c = u + 12;
            if ((p(), A)[u >>> 2 >>> 0] = c, (p(), A)[u + 4 >>> 2 >>> 0] = c + 65536, c = _t2[0], !xr2.has(c)) {
              var h2 = Ii2++;
              xr2.set(c, h2), Vn2.set(h2, c);
            }
            return c = xr2.get(c), (p(), x)[u + 8 >>> 2 >>> 0] = c, u;
          })(), typeof MainLoop < "u" && MainLoop.Xd && MainLoop.pause(), Pt2(() => ya2(Me2)));
        } else Ge2 === 2 ? (Ge2 = 0, Pt2(ga2), xe2(Me2), Me2 = null, xi2.forEach(he2)) : Te2(`invalid state: ${Ge2}`);
        return zn2;
      }
    })((t6) => {
      e().then(t6);
    });
    function Li2(e) {
      return e >>>= 0, Hn2(async () => {
        var t6 = await ve2(e);
        return Ie2(t6);
      });
    }
    var Or2 = [], Oi2 = (e) => {
      var t6 = Or2.length;
      return Or2.push(e), t6;
    }, Bi2 = (e, t6) => {
      for (var n = Array(e), o = 0; o < e; ++o) {
        var u = o, c = (p(), A)[t6 + 4 * o >>> 2 >>> 0], h2 = vr2[c];
        if (h2 === void 0) throw e = `parameter ${o}`, c = lo2(c), t6 = Be2(c), xe2(c), new dt2(`${e} has unknown type ${t6}`);
        n[u] = h2;
      }
      return n;
    }, Mi2 = (e, t6, n) => {
      var o = [];
      return e = e(o, n), o.length && ((p(), A)[t6 >>> 2 >>> 0] = Ie2(o)), e;
    }, Ci2 = {}, Rt2 = (e) => {
      var t6 = Ci2[e];
      return t6 === void 0 ? Be2(e) : t6;
    };
    function Ui2(e, t6, n) {
      var [o, ...u] = Bi2(e, t6 >>> 0);
      t6 = o.Sc.bind(o);
      var c = u.map((E2) => E2.Rc.bind(E2));
      e--;
      var h2 = { toValue: ve2 };
      switch (e = c.map((E2, I) => {
        var F2 = `argFromPtr${I}`;
        return h2[F2] = E2, `${F2}(args${I ? "+" + 8 * I : ""})`;
      }), n) {
        case 0:
          var b = "toValue(handle)";
          break;
        case 2:
          b = "new (toValue(handle))";
          break;
        case 3:
          b = "";
          break;
        case 1:
          h2.getStringOrSymbol = Rt2, b = "toValue(handle)[getStringOrSymbol(methodName)]";
      }
      return b += `(${e})`, o.ee || (h2.toReturnWire = t6, h2.emval_returnValue = Mi2, b = `return emval_returnValue(toReturnWire, destructorsRef, ${b})`), b = `return function (handle, methodName, destructorsRef, args) {
  ${b}
  }`, n = new Function(Object.keys(h2), b)(...Object.values(h2)), b = `methodCaller<(${u.map((E2) => E2.name)}) => ${o.name}>`, Oi2(Object.defineProperty(n, "name", { value: b }));
    }
    function Di2(e, t6) {
      return t6 >>>= 0, (e = ve2(e >>> 0)) == ve2(t6);
    }
    function Pi2(e) {
      return (e >>>= 0) ? (e = Rt2(e), Ie2(globalThis[e])) : Ie2(globalThis);
    }
    function _i2(e) {
      return e = Rt2(e >>> 0), Ie2(r[e]);
    }
    function Ri2(e, t6) {
      return t6 >>>= 0, e = ve2(e >>> 0), t6 = ve2(t6), Ie2(e[t6]);
    }
    function Ni2(e) {
      9 < (e >>>= 0) && (Xe2[e + 1] += 1);
    }
    function Yn2(e, t6, n, o, u) {
      return Or2[e >>> 0](t6 >>> 0, n >>> 0, o >>> 0, u >>> 0);
    }
    function ki2(e, t6, n, o, u) {
      return Yn2(e >>> 0, t6 >>> 0, n >>> 0, o >>> 0, u >>> 0);
    }
    function Wi2() {
      return Ie2([]);
    }
    function Fi2(e) {
      e = ve2(e >>> 0);
      for (var t6 = Array(e.length), n = 0; n < e.length; n++) t6[n] = e[n];
      return Ie2(t6);
    }
    function Gi2(e) {
      return Ie2(Rt2(e >>> 0));
    }
    function $i2() {
      return Ie2({});
    }
    function zi2(e) {
      for (var t6 = ve2(e >>>= 0); t6.length; ) {
        var n = t6.pop();
        t6.pop()(n);
      }
      Er2(e);
    }
    function Vi2(e, t6, n) {
      t6 >>>= 0, n >>>= 0, e = ve2(e >>> 0), t6 = ve2(t6), n = ve2(n), e[t6] = n;
    }
    function ji2(e, t6) {
      e = ce2(e), t6 >>>= 0, e = new Date(1e3 * e), (p(), x)[t6 >>> 2 >>> 0] = e.getUTCSeconds(), (p(), x)[t6 + 4 >>> 2 >>> 0] = e.getUTCMinutes(), (p(), x)[t6 + 8 >>> 2 >>> 0] = e.getUTCHours(), (p(), x)[t6 + 12 >>> 2 >>> 0] = e.getUTCDate(), (p(), x)[t6 + 16 >>> 2 >>> 0] = e.getUTCMonth(), (p(), x)[t6 + 20 >>> 2 >>> 0] = e.getUTCFullYear() - 1900, (p(), x)[t6 + 24 >>> 2 >>> 0] = e.getUTCDay(), e = (e.getTime() - Date.UTC(e.getUTCFullYear(), 0, 1, 0, 0, 0, 0)) / 864e5 | 0, (p(), x)[t6 + 28 >>> 2 >>> 0] = e;
    }
    var qn2 = (e) => e % 4 == 0 && (e % 100 != 0 || e % 400 == 0), Jn2 = [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335], Xn2 = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    function Hi2(e, t6) {
      e = ce2(e), t6 >>>= 0, e = new Date(1e3 * e), (p(), x)[t6 >>> 2 >>> 0] = e.getSeconds(), (p(), x)[t6 + 4 >>> 2 >>> 0] = e.getMinutes(), (p(), x)[t6 + 8 >>> 2 >>> 0] = e.getHours(), (p(), x)[t6 + 12 >>> 2 >>> 0] = e.getDate(), (p(), x)[t6 + 16 >>> 2 >>> 0] = e.getMonth(), (p(), x)[t6 + 20 >>> 2 >>> 0] = e.getFullYear() - 1900, (p(), x)[t6 + 24 >>> 2 >>> 0] = e.getDay();
      var n = (qn2(e.getFullYear()) ? Jn2 : Xn2)[e.getMonth()] + e.getDate() - 1 | 0;
      (p(), x)[t6 + 28 >>> 2 >>> 0] = n, (p(), x)[t6 + 36 >>> 2 >>> 0] = -60 * e.getTimezoneOffset(), n = new Date(e.getFullYear(), 6, 1).getTimezoneOffset();
      var o = new Date(e.getFullYear(), 0, 1).getTimezoneOffset();
      e = 0 | (n != o && e.getTimezoneOffset() == Math.min(o, n)), (p(), x)[t6 + 32 >>> 2 >>> 0] = e;
    }
    function Yi2(e) {
      e >>>= 0;
      var t6 = new Date((p(), x)[e + 20 >>> 2 >>> 0] + 1900, (p(), x)[e + 16 >>> 2 >>> 0], (p(), x)[e + 12 >>> 2 >>> 0], (p(), x)[e + 8 >>> 2 >>> 0], (p(), x)[e + 4 >>> 2 >>> 0], (p(), x)[e >>> 2 >>> 0], 0), n = (p(), x)[e + 32 >>> 2 >>> 0], o = t6.getTimezoneOffset(), u = new Date(t6.getFullYear(), 6, 1).getTimezoneOffset(), c = new Date(t6.getFullYear(), 0, 1).getTimezoneOffset(), h2 = Math.min(c, u);
      return 0 > n ? (p(), x)[e + 32 >>> 2 >>> 0] = +(u != c && h2 == o) : 0 < n != (h2 == o) && (u = Math.max(c, u), t6.setTime(t6.getTime() + 6e4 * ((0 < n ? h2 : u) - o))), (p(), x)[e + 24 >>> 2 >>> 0] = t6.getDay(), n = (qn2(t6.getFullYear()) ? Jn2 : Xn2)[t6.getMonth()] + t6.getDate() - 1 | 0, (p(), x)[e + 28 >>> 2 >>> 0] = n, (p(), x)[e >>> 2 >>> 0] = t6.getSeconds(), (p(), x)[e + 4 >>> 2 >>> 0] = t6.getMinutes(), (p(), x)[e + 8 >>> 2 >>> 0] = t6.getHours(), (p(), x)[e + 12 >>> 2 >>> 0] = t6.getDate(), (p(), x)[e + 16 >>> 2 >>> 0] = t6.getMonth(), (p(), x)[e + 20 >>> 2 >>> 0] = t6.getYear(), e = t6.getTime(), BigInt(isNaN(e) ? -1 : e / 1e3);
    }
    function Qn2(e, t6, n, o, u, c, h2) {
      return i ? V(16, 1, e, t6, n, o, u, c, h2) : -52;
    }
    function Zn2(e, t6, n, o, u, c) {
      if (i) return V(17, 1, e, t6, n, o, u, c);
    }
    var Tt2 = {}, qi2 = () => performance.timeOrigin + performance.now();
    function Kn2(e, t6) {
      if (i) return V(18, 1, e, t6);
      if (Tt2[e] && (clearTimeout(Tt2[e].id), delete Tt2[e]), !t6) return 0;
      var n = setTimeout(() => {
        delete Tt2[e], he2(() => Bo2(e, performance.timeOrigin + performance.now()));
      }, t6);
      return Tt2[e] = { id: n, Ae: t6 }, 0;
    }
    function Ji2(e, t6, n, o) {
      e >>>= 0, t6 >>>= 0, n >>>= 0, o >>>= 0;
      var u = (/* @__PURE__ */ new Date()).getFullYear(), c = new Date(u, 0, 1).getTimezoneOffset();
      u = new Date(u, 6, 1).getTimezoneOffset();
      var h2 = Math.max(c, u);
      (p(), A)[e >>> 2 >>> 0] = 60 * h2, (p(), x)[t6 >>> 2 >>> 0] = +(c != u), e = (t6 = (b) => {
        var E2 = Math.abs(b);
        return `UTC${0 <= b ? "-" : "+"}${String(Math.floor(E2 / 60)).padStart(2, "0")}${String(E2 % 60).padStart(2, "0")}`;
      })(c), t6 = t6(u), u < c ? (Pe2(e, n, 17), Pe2(t6, o, 17)) : (Pe2(e, o, 17), Pe2(t6, n, 17));
    }
    var Xi2 = () => Date.now(), Qi2 = 1;
    function Zi2(e, t6, n) {
      if (n >>>= 0, !(0 <= e && 3 >= e)) return 28;
      if (e === 0) e = Date.now();
      else {
        if (!Qi2) return 52;
        e = performance.timeOrigin + performance.now();
      }
      return e = Math.round(1e6 * e), (p(), me2)[n >>> 3 >>> 0] = BigInt(e), 0;
    }
    var Br2 = [], eo2 = (e, t6) => {
      Br2.length = 0;
      for (var n; n = (p(), J2)[e++ >>> 0]; ) {
        var o = n != 105;
        t6 += (o &= n != 112) && t6 % 8 ? 4 : 0, Br2.push(n == 112 ? (p(), A)[t6 >>> 2 >>> 0] : n == 106 ? (p(), me2)[t6 >>> 3 >>> 0] : n == 105 ? (p(), x)[t6 >>> 2 >>> 0] : (p(), ae2)[t6 >>> 3 >>> 0]), t6 += o ? 8 : 4;
      }
      return Br2;
    };
    function Ki2(e, t6, n) {
      return e >>>= 0, t6 = eo2(t6 >>> 0, n >>> 0), Vr2[e](...t6);
    }
    function eu2(e, t6, n) {
      return e >>>= 0, t6 = eo2(t6 >>> 0, n >>> 0), Vr2[e](...t6);
    }
    var tu2 = () => {
    };
    function ru2(e, t6) {
      return O(ct2(e >>> 0, t6 >>> 0));
    }
    var nu2 = () => {
      throw G += 1, "unwind";
    };
    function ou2() {
      return 4294901760;
    }
    var au2 = () => 1, su2 = () => navigator.hardwareConcurrency;
    function iu2(e) {
      e >>>= 0;
      var t6 = (p(), J2).length;
      if (e <= t6 || 4294901760 < e) return false;
      for (var n = 1; 4 >= n; n *= 2) {
        var o = t6 * (1 + 0.2 / n);
        o = Math.min(o, e + 100663296);
        e: {
          o = (Math.min(4294901760, 65536 * Math.ceil(Math.max(e, o) / 65536)) - Fe2.buffer.byteLength + 65535) / 65536 | 0;
          try {
            Fe2.grow(o), se2();
            var u = 1;
            break e;
          } catch {
          }
          u = void 0;
        }
        if (u) return true;
      }
      return false;
    }
    var Ce2 = (e) => {
      var t6 = _e2(e) + 1, n = Ft2(t6);
      return Pe2(e, n, t6), n;
    }, Mr = (e, t6) => {
      (p(), A)[e >>> 2 >>> 0] = t6;
      var n = (p(), A)[e >>> 2 >>> 0];
      (p(), A)[e + 4 >>> 2 >>> 0] = (t6 - n) / 4294967296;
    }, vt2 = (e) => (p(), A)[e >>> 2 >>> 0] + 4294967296 * (p(), x)[e + 4 >>> 2 >>> 0], de2 = [], uu2 = (e, t6) => {
      de2[e >>> 0] = t6;
    }, Re2 = [], Nt2 = [], lt2 = (e, t6) => {
      Nt2[e] = new Promise((n) => t6.finally(() => n(e)));
    }, L2 = (e) => {
      if (e) return de2[e >>> 0];
    }, fu2 = (e, t6) => {
      for (e = (p(), A)[e >>> 2 >>> 0]; e; e = (p(), A)[e >>> 2 >>> 0]) t6[(p(), x)[e + 4 >>> 2 >>> 0]](e);
    }, kt2 = (e, t6, n) => {
      (p(), A)[e >>> 2 >>> 0] = t6, (p(), A)[e + 4 >>> 2 >>> 0] = n;
    }, to2 = (e) => {
      var t6 = (p(), A)[e >>> 2 >>> 0];
      return e = (p(), A)[e + 4 >>> 2 >>> 0], ct2(t6, e);
    }, Ne2 = (e) => {
      var t6 = (p(), A)[e >>> 2 >>> 0];
      return e = (p(), A)[e + 4 >>> 2 >>> 0], t6 ? ct2(t6, e) : e === 0 ? "" : void 0;
    }, cu2 = (e) => {
      var t6 = Ne2(e + 4), n = (n = (p(), A)[e + 12 >>> 2 >>> 0]) ? L2(n) : "auto";
      if (e += 16) {
        var o = L2((p(), A)[e + 4 >>> 2 >>> 0]), u = (p(), A)[e + 16 >>> 2 >>> 0], c = (p(), A)[e + 20 >>> 2 >>> 0];
        if (u) {
          for (var h2 = {}, b = 0; b < u; ++b) {
            var E2 = c + 24 * b;
            h2[to2(E2 + 4)] = (p(), ae2)[E2 + 16 >>> 3 >>> 0];
          }
          u = h2;
        } else u = void 0;
        e = { module: o, constants: u, entryPoint: Ne2(e + 8) };
      } else e = void 0;
      return { label: t6, layout: n, compute: e };
    }, ro2 = (e, t6) => {
      function n(o, u) {
        o = e[o], (p(), A)[t6 + u >>> 2 >>> 0] = o;
      }
      n("maxTextureDimension1D", 4), n("maxTextureDimension2D", 8), n("maxTextureDimension3D", 12), n("maxTextureArrayLayers", 16), n("maxBindGroups", 20), n("maxBindGroupsPlusVertexBuffers", 24), n("maxBindingsPerBindGroup", 28), n("maxDynamicUniformBuffersPerPipelineLayout", 32), n("maxDynamicStorageBuffersPerPipelineLayout", 36), n("maxSampledTexturesPerShaderStage", 40), n("maxSamplersPerShaderStage", 44), n("maxStorageBuffersPerShaderStage", 48), n("maxStorageTexturesPerShaderStage", 52), n("maxUniformBuffersPerShaderStage", 56), n("minUniformBufferOffsetAlignment", 80), n("minStorageBufferOffsetAlignment", 84), Mr(t6 + 64, e.maxUniformBufferBindingSize), Mr(t6 + 72, e.maxStorageBufferBindingSize), n("maxVertexBuffers", 88), Mr(t6 + 96, e.maxBufferSize), n("maxVertexAttributes", 104), n("maxVertexBufferArrayStride", 108), n("maxInterStageShaderVariables", 112), n("maxColorAttachments", 116), n("maxColorAttachmentBytesPerSample", 120), n("maxComputeWorkgroupStorageSize", 124), n("maxComputeInvocationsPerWorkgroup", 128), n("maxComputeWorkgroupSizeX", 132), n("maxComputeWorkgroupSizeY", 136), n("maxComputeWorkgroupSizeZ", 140), n("maxComputeWorkgroupsPerDimension", 144), e.ze !== void 0 && n("maxImmediateSize", 148);
    }, du2 = [, "validation", "out-of-memory", "internal"], lu2 = [, "compatibility", "core"], no2 = { 1: "core-features-and-limits", 2: "depth-clip-control", 3: "depth32float-stencil8", 4: "texture-compression-bc", 5: "texture-compression-bc-sliced-3d", 6: "texture-compression-etc2", 7: "texture-compression-astc", 8: "texture-compression-astc-sliced-3d", 9: "timestamp-query", 10: "indirect-first-instance", 11: "shader-f16", 12: "rg11b10ufloat-renderable", 13: "bgra8unorm-storage", 14: "float32-filterable", 15: "float32-blendable", 16: "clip-distances", 17: "dual-source-blending", 18: "subgroups", 19: "texture-formats-tier1", 20: "texture-formats-tier2", 21: "primitive-index", 22: "texture-component-swizzle", 327692: "chromium-experimental-unorm16-texture-formats", 327729: "chromium-experimental-multi-draw-indirect" }, pu2 = [, "low-power", "high-performance"], mu2 = [, "occlusion", "timestamp"], hu2 = { undefined: 1, unknown: 1, destroyed: 2 };
    function yu2(e, t6, n, o, u, c) {
      t6 = ce2(t6), n = ce2(n), o >>>= 0, u >>>= 0, c >>>= 0;
      var h2 = L2(e >>> 0);
      if (e = {}, c) {
        var b = (p(), A)[c + 12 >>> 2 >>> 0];
        if (b) {
          var E2 = (p(), A)[c + 16 >>> 2 >>> 0];
          e.requiredFeatures = Array.from((p(), A).subarray(E2 >>> 2 >>> 0, E2 + 4 * b >>> 2 >>> 0), (B) => no2[B]);
        }
        var I = (p(), A)[c + 20 >>> 2 >>> 0];
        if (I) {
          let B = function(ye2, fe2, Qe2 = false) {
            fe2 = I + fe2, (fe2 = (p(), A)[fe2 >>> 2 >>> 0]) == 4294967295 || Qe2 && fe2 == 0 || (F2[ye2] = fe2);
          }, ue2 = function(ye2, fe2) {
            fe2 = I + fe2;
            var Qe2 = (p(), A)[fe2 >>> 2 >>> 0], $f2 = (p(), A)[fe2 + 4 >>> 2 >>> 0];
            Qe2 == 4294967295 && $f2 == 4294967295 || (F2[ye2] = vt2(fe2));
          };
          var j = B, te2 = ue2, F2 = {};
          B("maxTextureDimension1D", 4), B("maxTextureDimension2D", 8), B("maxTextureDimension3D", 12), B("maxTextureArrayLayers", 16), B("maxBindGroups", 20), B("maxBindGroupsPlusVertexBuffers", 24), B("maxDynamicUniformBuffersPerPipelineLayout", 32), B("maxDynamicStorageBuffersPerPipelineLayout", 36), B("maxSampledTexturesPerShaderStage", 40), B("maxSamplersPerShaderStage", 44), B("maxStorageBuffersPerShaderStage", 48), B("maxStorageTexturesPerShaderStage", 52), B("maxUniformBuffersPerShaderStage", 56), B("minUniformBufferOffsetAlignment", 80), B("minStorageBufferOffsetAlignment", 84), ue2("maxUniformBufferBindingSize", 64), ue2("maxStorageBufferBindingSize", 72), B("maxVertexBuffers", 88), ue2("maxBufferSize", 96), B("maxVertexAttributes", 104), B("maxVertexBufferArrayStride", 108), B("maxInterStageShaderVariables", 112), B("maxColorAttachments", 116), B("maxColorAttachmentBytesPerSample", 120), B("maxComputeWorkgroupStorageSize", 124), B("maxComputeInvocationsPerWorkgroup", 128), B("maxComputeWorkgroupSizeX", 132), B("maxComputeWorkgroupSizeY", 136), B("maxComputeWorkgroupSizeZ", 140), B("maxComputeWorkgroupsPerDimension", 144), B("maxImmediateSize", 148, true), e.requiredLimits = F2;
        }
        (b = (p(), A)[c + 24 >>> 2 >>> 0]) && (b = { label: Ne2(b + 4) }, e.defaultQueue = b), e.label = Ne2(c + 4);
      }
      G += 1, lt2(t6, h2.requestDevice(e).then((B) => {
        --G, he2(() => {
          de2[u >>> 0] = B.queue, de2[o >>> 0] = B, G += 1, lt2(n, B.lost.then((ue2) => {
            he2(() => {
              B.onuncapturederror = () => {
              };
              var ye2 = P2(), fe2 = Ce2(ue2.message);
              _r2(n, hu2[ue2.reason], fe2), D(ye2);
            }), --G;
          })), B.onuncapturederror = (ue2) => {
            var ye2 = 5;
            ue2.error instanceof GPUValidationError ? ye2 = 2 : ue2.error instanceof GPUOutOfMemoryError ? ye2 = 3 : ue2.error instanceof GPUInternalError && (ye2 = 4);
            var fe2 = P2();
            ue2 = Ce2(ue2.error.message), Io2(o, ye2, ue2), D(fe2);
          }, "adapterInfo" in B || (B.adapterInfo = h2.info), kr2(t6, 1, o, 0);
        });
      }, (B) => {
        --G, he2(() => {
          var ue2 = P2(), ye2 = Ce2(B.message);
          kr2(t6, 3, o, ye2), n && _r2(n, 4, ye2), D(ue2);
        });
      }));
    }
    function bu2(e) {
      var t6 = L2(e >>>= 0), n = Re2[e];
      if (n) {
        for (var o = 0; o < n.length; ++o) n[o]();
        delete Re2[e];
      }
      t6.destroy();
    }
    function wu2(e, t6, n) {
      n >>>= 0;
      var o = L2(e >>>= 0);
      n == 4294967295 && (n = void 0);
      try {
        var u = o.getMappedRange(t6 >>> 0, n);
      } catch {
        return 0;
      }
      var c = Gr2(16, u.byteLength);
      return (p(), J2).set(new Uint8Array(u), c >>> 0), Re2[e].push(() => xe2(c)), c;
    }
    function gu2(e, t6, n) {
      n >>>= 0;
      var o = L2(e >>>= 0);
      n == 4294967295 && (n = void 0);
      try {
        var u = o.getMappedRange(t6 >>> 0, n);
      } catch {
        return 0;
      }
      var c = Gr2(16, u.byteLength);
      return (p(), J2).fill(0, c, u.byteLength), Re2[e].push(() => {
        new Uint8Array(u).set((p(), J2).subarray(c >>> 0, c + u.byteLength >>> 0)), xe2(c);
      }), c;
    }
    function Tu2(e, t6, n, o, u) {
      e >>>= 0, t6 = ce2(t6), n = ce2(n), u >>>= 0;
      var c = L2(e);
      Re2[e] = [], u == 4294967295 && (u = void 0), G += 1, lt2(t6, c.mapAsync(n, o >>> 0, u).then(() => {
        --G, he2(() => {
          Rr2(t6, 1, 0);
        });
      }, (h2) => {
        --G, he2(() => {
          P2();
          var b = Ce2(h2.message);
          Rr2(t6, h2.name === "AbortError" ? 4 : h2.name === "OperationError" ? 3 : 0, b), delete Re2[e];
        });
      }));
    }
    function vu2(e) {
      var t6 = L2(e >>>= 0), n = Re2[e];
      if (n) {
        for (var o = 0; o < n.length; ++o) n[o]();
        delete Re2[e], t6.unmap();
      }
    }
    function Eu2(e) {
      delete de2[e >>> 0];
    }
    function Su2(e, t6, n) {
      e >>>= 0, t6 >>>= 0, n >>>= 0;
      var o = !!(p(), A)[t6 + 32 >>> 2 >>> 0];
      t6 = { label: Ne2(t6 + 4), usage: (p(), A)[t6 + 16 >>> 2 >>> 0], size: vt2(t6 + 24), mappedAtCreation: o }, e = L2(e);
      try {
        var u = e.createBuffer(t6);
      } catch {
        return false;
      }
      return de2[n >>> 0] = u, o && (Re2[n] = []), true;
    }
    function Au2(e, t6, n, o) {
      e >>>= 0, t6 = ce2(t6), o >>>= 0, n = cu2(n >>> 0), e = L2(e), G += 1, lt2(t6, e.createComputePipelineAsync(n).then((u) => {
        --G, he2(() => {
          de2[o >>> 0] = u, Pr2(t6, 1, o, 0);
        });
      }, (u) => {
        --G, he2(() => {
          var c = P2(), h2 = Ce2(u.message);
          Pr2(t6, u.reason === "validation" ? 3 : u.reason === "internal" ? 4 : 0, o, h2), D(c);
        });
      }));
    }
    function Iu2(e, t6, n) {
      e >>>= 0, t6 >>>= 0, n >>>= 0;
      var o = (p(), A)[t6 >>> 2 >>> 0], u = (p(), x)[o + 4 >>> 2 >>> 0];
      t6 = { label: Ne2(t6 + 4), code: "" }, u === 2 && (t6.code = to2(o + 8)), e = L2(e).createShaderModule(t6), de2[n >>> 0] = e;
    }
    var xu2 = (e) => {
      (e = L2(e)).onuncapturederror = null, e.destroy();
    };
    function Lu2(e, t6) {
      t6 = ce2(t6), e = L2(e >>> 0), G += 1, lt2(t6, e.popErrorScope().then((n) => {
        --G, he2(() => {
          var o = 5;
          n ? n instanceof GPUValidationError ? o = 2 : n instanceof GPUOutOfMemoryError ? o = 3 : n instanceof GPUInternalError && (o = 4) : o = 1;
          var u = P2(), c = n ? Ce2(n.message) : 0;
          Nr2(t6, 1, o, c), D(u);
        });
      }, (n) => {
        --G, he2(() => {
          var o = P2(), u = Ce2(n.message);
          Nr2(t6, 1, 5, u), D(o);
        });
      }));
    }
    function Ou2(e, t6, n, o) {
      if (t6 = ce2(t6), o >>>= 0, n >>>= 0) {
        var u = { featureLevel: lu2[(p(), x)[n + 4 >>> 2 >>> 0]], powerPreference: pu2[(p(), x)[n + 8 >>> 2 >>> 0]], forceFallbackAdapter: !!(p(), A)[n + 12 >>> 2 >>> 0] };
        (e = (p(), A)[n >>> 2 >>> 0]) !== 0 && (p(), u.De = !!(p(), A)[e + 8 >>> 2 >>> 0]);
      }
      "gpu" in navigator ? (G += 1, lt2(t6, navigator.gpu.requestAdapter(u).then((c) => {
        --G, he2(() => {
          if (c) de2[o >>> 0] = c, Et2(t6, 1, o, 0);
          else {
            var h2 = P2(), b = Ce2("WebGPU not available on this browser (requestAdapter returned null)");
            Et2(t6, 3, o, b), D(h2);
          }
        });
      }, (c) => {
        --G, he2(() => {
          var h2 = P2(), b = Ce2(c.message);
          Et2(t6, 4, o, b), D(h2);
        });
      }))) : (u = P2(), e = Ce2("WebGPU not available on this browser (navigator.gpu is not available)"), Et2(t6, 3, o, e), D(u));
    }
    function Bu2(e, t6, n) {
      return e >>>= 0, t6 >>>= 0, n >>>= 0, Hn2(async () => {
        var o = [];
        if (n) {
          var u = (p(), x)[n >>> 2 >>> 0];
          o.length = t6 + 1, o[t6] = new Promise((b) => setTimeout(b, u, 0));
        } else o.length = t6;
        for (var c = 0; c < t6; ++c) {
          var h2 = vt2(e + 8 * c);
          if (!(h2 in Nt2)) return h2;
          o[c] = Nt2[h2];
        }
        return o = await Promise.race(o), delete Nt2[o], o;
      });
    }
    var Cr2, Ur2 = {}, oo2 = () => {
      if (!Cr2) {
        var e, t6 = { USER: "web_user", LOGNAME: "web_user", PATH: "/", PWD: "/", HOME: "/home/web_user", LANG: (globalThis.navigator?.language ?? "C").replace("-", "_") + ".UTF-8", _: "./this.program" };
        for (e in Ur2) Ur2[e] === void 0 ? delete t6[e] : t6[e] = Ur2[e];
        var n = [];
        for (e in t6) n.push(`${e}=${t6[e]}`);
        Cr2 = n;
      }
      return Cr2;
    };
    function ao2(e, t6) {
      if (i) return V(19, 1, e, t6);
      e >>>= 0, t6 >>>= 0;
      var n, o = 0, u = 0;
      for (n of oo2()) {
        var c = t6 + o;
        (p(), A)[e + u >>> 2 >>> 0] = c, o += Pe2(n, c, 1 / 0) + 1, u += 4;
      }
      return 0;
    }
    function so2(e, t6) {
      if (i) return V(20, 1, e, t6);
      e >>>= 0, t6 >>>= 0;
      var n = oo2();
      for (var o of ((p(), A)[e >>> 2 >>> 0] = n.length, e = 0, n)) e += _e2(o) + 1;
      return (p(), A)[t6 >>> 2 >>> 0] = e, 0;
    }
    function io2(e) {
      return i ? V(21, 1, e) : 52;
    }
    function uo2(e, t6, n, o) {
      return i ? V(22, 1, e, t6, n, o) : 52;
    }
    function fo2(e, t6, n, o) {
      return i ? V(23, 1, e, t6, n, o) : 70;
    }
    var Mu2 = [null, [], []];
    function co2(e, t6, n, o) {
      if (i) return V(24, 1, e, t6, n, o);
      t6 >>>= 0, n >>>= 0, o >>>= 0;
      for (var u = 0, c = 0; c < n; c++) {
        var h2 = (p(), A)[t6 >>> 2 >>> 0], b = (p(), A)[t6 + 4 >>> 2 >>> 0];
        t6 += 8;
        for (var E2 = 0; E2 < b; E2++) {
          var I = e, F2 = (p(), J2)[h2 + E2 >>> 0], j = Mu2[I];
          F2 === 0 || F2 === 10 ? ((I === 1 ? Y2 : O)(xn2(j)), j.length = 0) : j.push(F2);
        }
        u += b;
      }
      return (p(), A)[o >>> 2 >>> 0] = u, 0;
    }
    function Cu2(e) {
      return e >>> 0;
    }
    function Uu2(e, t6) {
      return ro2(L2(e >>> 0).limits, t6 >>> 0), 1;
    }
    function Du2(e, t6) {
      return L2(e >>> 0).features.has(no2[t6]);
    }
    function Pu2(e) {
      return BigInt(L2(e >>> 0).size);
    }
    function _u2(e) {
      return BigInt(L2(e >>> 0).usage);
    }
    function Ru2(e, t6) {
      if (e >>>= 0, t6 >>>= 0) {
        var n = Ne2(t6 + 4);
        n = { label: n, timestampWrites: t6 = (t6 = (p(), A)[t6 + 12 >>> 2 >>> 0]) !== 0 ? { querySet: L2((p(), A)[t6 + 4 >>> 2 >>> 0]), beginningOfPassWriteIndex: (p(), A)[t6 + 8 >>> 2 >>> 0], endOfPassWriteIndex: (p(), A)[t6 + 12 >>> 2 >>> 0] } : void 0 };
      }
      return t6 = L2(e), e = To2(0), n = t6.beginComputePass(n), de2[e >>> 0] = n, e;
    }
    function Nu2(e, t6, n, o) {
      n = ce2(n), (o = ce2(o)) == -1 && (o = void 0), (e = L2(e >>> 0)).clearBuffer(L2(t6 >>> 0), n, o);
    }
    function ku2(e, t6, n, o, u, c) {
      n = ce2(n), u = ce2(u), c = ce2(c), L2(e >>> 0).copyBufferToBuffer(L2(t6 >>> 0), n, L2(o >>> 0), u, c);
    }
    function Wu2(e) {
      var t6 = L2(e >>> 0);
      return e = wo2(0), t6 = t6.finish(), de2[e >>> 0] = t6, e;
    }
    function Fu2(e, t6, n, o, u, c) {
      c = ce2(c), L2(e >>> 0).resolveQuerySet(L2(t6 >>> 0), n, o, L2(u >>> 0), c);
    }
    function Gu2(e, t6, n, o) {
      L2(e >>> 0).dispatchWorkgroups(t6, n, o);
    }
    function $u2(e, t6, n) {
      n = ce2(n), L2(e >>> 0).dispatchWorkgroupsIndirect(L2(t6 >>> 0), n);
    }
    function zu2(e) {
      L2(e >>> 0).end();
    }
    function Vu2(e, t6, n, o, u) {
      o >>>= 0, u >>>= 0, e = L2(e >>> 0), n = L2(n >>> 0), o == 0 ? e.setBindGroup(t6, n) : e.setBindGroup(t6, n, (p(), A), u >>> 2, o);
    }
    function ju2(e, t6) {
      L2(e >>> 0).setPipeline(L2(t6 >>> 0));
    }
    function Hu2(e, t6, n) {
      L2(e >>> 0).Ce(L2(t6 >>> 0), n);
    }
    function Yu2(e, t6) {
      var n = L2(e >>> 0);
      return e = bo2(0), t6 = n.getBindGroupLayout(t6), de2[e >>> 0] = t6, e;
    }
    function qu2(e, t6) {
      function n(u) {
        var c = (p(), A)[u + 8 >>> 2 >>> 0], h2 = (p(), A)[u + 32 >>> 2 >>> 0], b = (p(), A)[u + 36 >>> 2 >>> 0], E2 = 0;
        return fu2(u, { 327681: (I) => {
          E2 = (p(), A)[I + 8 >>> 2 >>> 0];
        } }), c ? ((h2 = vt2(u + 24)) == -1 && (h2 = void 0), c = { buffer: L2(c), offset: vt2(u + 16), size: h2 }) : c = L2(h2 || b || E2), { binding: (p(), A)[u + 4 >>> 2 >>> 0], resource: c };
      }
      e >>>= 0, t6 = { label: Ne2(4 + (t6 >>>= 0)), layout: L2((p(), A)[t6 + 12 >>> 2 >>> 0]), entries: (function(u, c) {
        for (var h2 = [], b = 0; b < u; ++b) h2.push(n(c + 40 * b));
        return h2;
      })((p(), A)[t6 + 16 >>> 2 >>> 0], (p(), A)[t6 + 20 >>> 2 >>> 0]) }, e = L2(e);
      var o = yo2(0);
      return uu2(o, e.createBindGroup(t6)), o;
    }
    function Ju2(e, t6) {
      var n;
      return e >>>= 0, (t6 >>>= 0) && (n = { label: Ne2(t6 + 4) }), t6 = L2(e), e = go2(0), n = t6.createCommandEncoder(n), de2[e >>> 0] = n, e;
    }
    function Xu2(e, t6) {
      e >>>= 0, t6 >>>= 0, t6 = { type: mu2[(p(), x)[t6 + 12 >>> 2 >>> 0]], count: (p(), A)[t6 + 16 >>> 2 >>> 0] };
      var n = L2(e);
      return e = vo2(0), t6 = n.createQuerySet(t6), de2[e >>> 0] = t6, e;
    }
    function Qu2(e, t6) {
      e = L2(e >>> 0).adapterInfo, t6 >>>= 0, (p(), A)[t6 + 52 >>> 2 >>> 0] = e.subgroupMinSize, (p(), A)[t6 + 56 >>> 2 >>> 0] = e.subgroupMaxSize;
      var n = e.vendor + e.architecture + e.device + e.description, o = _e2(n) + 1, u = pt2(o);
      return u && Pe2(n, u, o), n = u, o = _e2(e.vendor), kt2(t6 + 4, n, o), n += o, o = _e2(e.architecture), kt2(t6 + 12, n, o), n += o, o = _e2(e.device), kt2(t6 + 20, n, o), kt2(t6 + 28, n + o, _e2(e.description)), (p(), x)[t6 + 36 >>> 2 >>> 0] = 2, e = e.isFallbackAdapter ? 3 : 4, (p(), x)[t6 + 40 >>> 2 >>> 0] = e, (p(), A)[t6 + 44 >>> 2 >>> 0] = 0, (p(), A)[t6 + 48 >>> 2 >>> 0] = 0, 1;
    }
    var Zu2 = { "core-features-and-limits": 1, "depth-clip-control": 2, "depth32float-stencil8": 3, "texture-compression-bc": 4, "texture-compression-bc-sliced-3d": 5, "texture-compression-etc2": 6, "texture-compression-astc": 7, "texture-compression-astc-sliced-3d": 8, "timestamp-query": 9, "indirect-first-instance": 10, "shader-f16": 11, "rg11b10ufloat-renderable": 12, "bgra8unorm-storage": 13, "float32-filterable": 14, "float32-blendable": 15, "clip-distances": 16, "dual-source-blending": 17, subgroups: 18, "texture-formats-tier1": 19, "texture-formats-tier2": 20, "primitive-index": 21, "texture-component-swizzle": 22, "chromium-experimental-unorm16-texture-formats": 327692, "chromium-experimental-multi-draw-indirect": 327729 };
    function Ku2(e, t6) {
      t6 >>>= 0;
      var n = L2(e >>> 0);
      e = pt2(4 * n.features.size);
      var o = 0, u = 0;
      for (let c of n.features) 0 <= (n = Zu2[c]) && ((p(), x)[e + o >>> 2 >>> 0] = n, o += 4, u++);
      (p(), A)[t6 + 4 >>> 2 >>> 0] = e, (p(), A)[t6 >>> 2 >>> 0] = u;
    }
    function ef2(e, t6) {
      return ro2(L2(e >>> 0).limits, t6 >>> 0), 1;
    }
    function tf2(e, t6) {
      L2(e >>> 0).pushErrorScope(du2[t6]);
    }
    function rf2(e, t6, n) {
      t6 >>>= 0, n >>>= 0, e = L2(e >>> 0), t6 = Array.from((p(), x).subarray(n >>> 2 >>> 0, n + 4 * t6 >>> 2 >>> 0), (o) => L2(o)), e.submit(t6);
    }
    function nf2(e, t6, n, o, u) {
      n = ce2(n), o >>>= 0, u >>>= 0, e = L2(e >>> 0), t6 = L2(t6 >>> 0), o = (p(), J2).subarray(o >>> 0, o + u >>> 0), e.writeBuffer(t6, n, o, 0, u);
    }
    i || (function() {
      for (var e = r.numThreads - 1; e--; ) gn2();
      Ae2.push(async () => {
        var t6 = (async function() {
          if (!i) return Promise.all(We2.map(wn2));
        })();
        Oe2++, await t6, --Oe2 == 0 && ee && (t6 = ee, ee = null, t6());
      });
    })(), i || (Fe2 = new WebAssembly.Memory({ initial: 256, maximum: 65536, shared: true }), se2()), r.wasmBinary && (g = r.wasmBinary), r.stackSave = () => P2(), r.stackRestore = (e) => D(e), r.stackAlloc = (e) => Ft2(e), r.setValue = function(e, t6, n = "i8") {
      switch (n.endsWith("*") && (n = "*"), n) {
        case "i1":
        case "i8":
          (p(), X2)[e >>> 0] = t6;
          break;
        case "i16":
          (p(), Ue2)[e >>> 1 >>> 0] = t6;
          break;
        case "i32":
          (p(), x)[e >>> 2 >>> 0] = t6;
          break;
        case "i64":
          (p(), me2)[e >>> 3 >>> 0] = BigInt(t6);
          break;
        case "float":
          (p(), _)[e >>> 2 >>> 0] = t6;
          break;
        case "double":
          (p(), ae2)[e >>> 3 >>> 0] = t6;
          break;
        case "*":
          (p(), A)[e >>> 2 >>> 0] = t6;
          break;
        default:
          Te2(`invalid type for setValue: ${n}`);
      }
    }, r.getValue = function(e, t6 = "i8") {
      switch (t6.endsWith("*") && (t6 = "*"), t6) {
        case "i1":
        case "i8":
          return (p(), X2)[e >>> 0];
        case "i16":
          return (p(), Ue2)[e >>> 1 >>> 0];
        case "i32":
          return (p(), x)[e >>> 2 >>> 0];
        case "i64":
          return (p(), me2)[e >>> 3 >>> 0];
        case "float":
          return (p(), _)[e >>> 2 >>> 0];
        case "double":
          return (p(), ae2)[e >>> 3 >>> 0];
        case "*":
          return (p(), A)[e >>> 2 >>> 0];
        default:
          Te2(`invalid type for getValue: ${t6}`);
      }
    }, r.UTF8ToString = ct2, r.stringToUTF8 = Pe2, r.lengthBytesUTF8 = _e2;
    var lo2, po2, Dr2, Wt2, xe2, pt2, mo2, ho2, yo2, bo2, wo2, go2, To2, vo2, Eo2, So2, Ao2, Pr2, _r2, Rr2, Nr2, Et2, kr2, Io2, Wr2, xo2, Lo2, Oo2, Fr2, Bo2, Mo2, Gr2, N2, St2, Co2, D, Ft2, P2, Uo2, $r2, Do2, Po2, _o2, zr2, Ro2, No2, ko2, Wo2, Fo2, Go2, $o2, zo2, Vo2, jo2, Ho2, Yo2, qo2, Jo2, Xo2, Qo2, Zo2, Ko2, ea2, ta2, ra2, na2, oa2, aa2, sa, ia2, ua2, fa2, ca2, da2, la2, pa2, ma2, ha2, ya2, ba2, wa2, ga2, ke2, of2 = [qe2, yr2, En2, Ln2, On2, Bn2, Mn2, Cn2, Un2, Dn2, Pn2, _n2, Rn2, Nn2, kn2, Wn2, Qn2, Zn2, Kn2, ao2, so2, io2, uo2, fo2, co2], Vr2 = { 970348: (e, t6, n, o, u) => {
      if (r === void 0 || !r.Uc) return 1;
      if ((e = ct2(Number(e >>> 0))).startsWith("./") && (e = e.substring(2)), !(e = r.Uc.get(e))) return 2;
      if (t6 = Number(t6 >>> 0), n = Number(n >>> 0), o = Number(o >>> 0), t6 + n > e.byteLength) return 3;
      try {
        let c = e.subarray(t6, t6 + n);
        switch (u) {
          case 0:
            (p(), J2).set(c, o >>> 0);
            break;
          case 1:
            r.ad ? r.ad(o, c) : r.ne(o, c);
            break;
          default:
            return 4;
        }
        return 0;
      } catch {
        return 4;
      }
    }, 971172: (e, t6, n) => {
      r.Sd(e, (p(), J2).subarray(t6 >>> 0, t6 + n >>> 0));
    }, 971236: () => r.le(), 971278: (e) => {
      r.jd(e);
    }, 971315: () => typeof wasmOffsetConverter < "u" };
    function af2(e, t6, n, o) {
      var u = P2();
      try {
        return zo2(e, t6, n, o);
      } catch (c) {
        if (D(u), c !== c + 0) throw c;
        N2(1, 0);
      }
    }
    function sf2(e, t6, n) {
      var o = P2();
      try {
        return Fo2(e, t6, n);
      } catch (u) {
        if (D(o), u !== u + 0) throw u;
        N2(1, 0);
      }
    }
    function uf2(e) {
      var t6 = P2();
      try {
        Ro2(e);
      } catch (n) {
        if (D(t6), n !== n + 0) throw n;
        N2(1, 0);
      }
    }
    function ff2(e, t6) {
      var n = P2();
      try {
        return zr2(e, t6);
      } catch (o) {
        if (D(n), o !== o + 0) throw o;
        N2(1, 0);
      }
    }
    function cf2(e, t6, n) {
      var o = P2();
      try {
        _o2(e, t6, n);
      } catch (u) {
        if (D(o), u !== u + 0) throw u;
        N2(1, 0);
      }
    }
    function df2(e, t6) {
      var n = P2();
      try {
        Vo2(e, t6);
      } catch (o) {
        if (D(n), o !== o + 0) throw o;
        N2(1, 0);
      }
    }
    function lf2(e, t6, n, o, u, c, h2) {
      var b = P2();
      try {
        return Wo2(e, t6, n, o, u, c, h2);
      } catch (E2) {
        if (D(b), E2 !== E2 + 0) throw E2;
        N2(1, 0);
      }
    }
    function pf2(e, t6, n, o, u, c) {
      var h2 = P2();
      try {
        No2(e, t6, n, o, u, c);
      } catch (b) {
        if (D(h2), b !== b + 0) throw b;
        N2(1, 0);
      }
    }
    function mf2(e, t6, n, o) {
      var u = P2();
      try {
        $o2(e, t6, n, o);
      } catch (c) {
        if (D(u), c !== c + 0) throw c;
        N2(1, 0);
      }
    }
    function hf2(e, t6, n, o, u, c, h2) {
      var b = P2();
      try {
        Ho2(e, t6, n, o, u, c, h2);
      } catch (E2) {
        if (D(b), E2 !== E2 + 0) throw E2;
        N2(1, 0);
      }
    }
    function yf2(e, t6, n, o, u, c, h2) {
      var b = P2();
      try {
        Yo2(e, t6, n, o, u, c, h2);
      } catch (E2) {
        if (D(b), E2 !== E2 + 0) throw E2;
        N2(1, 0);
      }
    }
    function bf2(e, t6, n, o, u, c, h2, b) {
      var E2 = P2();
      try {
        ra2(e, t6, n, o, u, c, h2, b);
      } catch (I) {
        if (D(E2), I !== I + 0) throw I;
        N2(1, 0);
      }
    }
    function wf2(e, t6, n, o, u, c, h2, b, E2, I, F2, j) {
      var te2 = P2();
      try {
        qo2(e, t6, n, o, u, c, h2, b, E2, I, F2, j);
      } catch (B) {
        if (D(te2), B !== B + 0) throw B;
        N2(1, 0);
      }
    }
    function gf2(e, t6, n, o, u) {
      var c = P2();
      try {
        return jo2(e, t6, n, o, u);
      } catch (h2) {
        if (D(c), h2 !== h2 + 0) throw h2;
        N2(1, 0);
      }
    }
    function Tf2(e, t6, n, o, u) {
      var c = P2();
      try {
        ko2(e, t6, n, o, u);
      } catch (h2) {
        if (D(c), h2 !== h2 + 0) throw h2;
        N2(1, 0);
      }
    }
    function vf2(e, t6, n, o, u, c, h2, b) {
      var E2 = P2();
      try {
        Go2(e, t6, n, o, u, c, h2, b);
      } catch (I) {
        if (D(E2), I !== I + 0) throw I;
        N2(1, 0);
      }
    }
    function Ef2(e) {
      var t6 = P2();
      try {
        return na2(e);
      } catch (n) {
        if (D(t6), n !== n + 0) throw n;
        N2(1, 0);
      }
    }
    function Sf2(e, t6, n) {
      var o = P2();
      try {
        return oa2(e, t6, n);
      } catch (u) {
        if (D(o), u !== u + 0) throw u;
        N2(1, 0);
      }
    }
    function Af2(e, t6) {
      var n = P2();
      try {
        return ha2(e, t6);
      } catch (o) {
        if (D(n), o !== o + 0) throw o;
        return N2(1, 0), 0n;
      }
    }
    function If2(e) {
      var t6 = P2();
      try {
        return Jo2(e);
      } catch (n) {
        if (D(t6), n !== n + 0) throw n;
        return N2(1, 0), 0n;
      }
    }
    function xf2(e, t6, n, o) {
      var u = P2();
      try {
        return aa2(e, t6, n, o);
      } catch (c) {
        if (D(u), c !== c + 0) throw c;
        N2(1, 0);
      }
    }
    function Lf2(e, t6, n, o, u) {
      var c = P2();
      try {
        return sa(e, t6, n, o, u);
      } catch (h2) {
        if (D(c), h2 !== h2 + 0) throw h2;
        N2(1, 0);
      }
    }
    function Of2(e, t6, n, o, u, c) {
      var h2 = P2();
      try {
        return ia2(e, t6, n, o, u, c);
      } catch (b) {
        if (D(h2), b !== b + 0) throw b;
        N2(1, 0);
      }
    }
    function Bf2(e, t6, n, o, u, c) {
      var h2 = P2();
      try {
        return ea2(e, t6, n, o, u, c);
      } catch (b) {
        if (D(h2), b !== b + 0) throw b;
        N2(1, 0);
      }
    }
    function Mf2(e, t6, n, o, u, c) {
      var h2 = P2();
      try {
        return ua2(e, t6, n, o, u, c);
      } catch (b) {
        if (D(h2), b !== b + 0) throw b;
        N2(1, 0);
      }
    }
    function Cf2(e, t6, n, o, u, c, h2, b) {
      var E2 = P2();
      try {
        return ta2(e, t6, n, o, u, c, h2, b);
      } catch (I) {
        if (D(E2), I !== I + 0) throw I;
        N2(1, 0);
      }
    }
    function Uf2(e, t6, n, o, u) {
      var c = P2();
      try {
        return fa2(e, t6, n, o, u);
      } catch (h2) {
        if (D(c), h2 !== h2 + 0) throw h2;
        return N2(1, 0), 0n;
      }
    }
    function Df2(e, t6, n, o) {
      var u = P2();
      try {
        return ca2(e, t6, n, o);
      } catch (c) {
        if (D(u), c !== c + 0) throw c;
        N2(1, 0);
      }
    }
    function Pf2(e, t6, n, o) {
      var u = P2();
      try {
        return da2(e, t6, n, o);
      } catch (c) {
        if (D(u), c !== c + 0) throw c;
        N2(1, 0);
      }
    }
    function _f2(e, t6, n, o, u, c, h2, b, E2, I, F2, j) {
      var te2 = P2();
      try {
        return la2(e, t6, n, o, u, c, h2, b, E2, I, F2, j);
      } catch (B) {
        if (D(te2), B !== B + 0) throw B;
        N2(1, 0);
      }
    }
    function Rf2(e, t6, n, o, u, c, h2, b, E2, I, F2) {
      var j = P2();
      try {
        pa2(e, t6, n, o, u, c, h2, b, E2, I, F2);
      } catch (te2) {
        if (D(j), te2 !== te2 + 0) throw te2;
        N2(1, 0);
      }
    }
    function Nf2(e, t6, n, o, u, c, h2, b, E2, I, F2, j, te2, B, ue2, ye2) {
      var fe2 = P2();
      try {
        ma2(e, t6, n, o, u, c, h2, b, E2, I, F2, j, te2, B, ue2, ye2);
      } catch (Qe2) {
        if (D(fe2), Qe2 !== Qe2 + 0) throw Qe2;
        N2(1, 0);
      }
    }
    function kf2(e, t6, n) {
      var o = P2();
      try {
        return Qo2(e, t6, n);
      } catch (u) {
        if (D(o), u !== u + 0) throw u;
        return N2(1, 0), 0n;
      }
    }
    function Wf2(e, t6, n) {
      var o = P2();
      try {
        return Xo2(e, t6, n);
      } catch (u) {
        if (D(o), u !== u + 0) throw u;
        N2(1, 0);
      }
    }
    function Ff2(e, t6, n) {
      var o = P2();
      try {
        return Zo2(e, t6, n);
      } catch (u) {
        if (D(o), u !== u + 0) throw u;
        N2(1, 0);
      }
    }
    function Gf2(e, t6, n, o) {
      var u = P2();
      try {
        Ko2(e, t6, n, o);
      } catch (c) {
        if (D(u), c !== c + 0) throw c;
        N2(1, 0);
      }
    }
    function Gt2() {
      if (0 < Oe2) ee = Gt2;
      else if (i) C?.(r), hr2();
      else {
        for (var e = Ae2; 0 < e.length; ) e.shift()(r);
        0 < Oe2 ? ee = Gt2 : (r.calledRun = true, W2 || (hr2(), C?.(r)));
      }
    }
    return i || (ke2 = await bt2(), Gt2()), r.PTR_SIZE = 4, r.webgpuInit = (e) => {
      let t6 = /* @__PURE__ */ new WeakMap(), n, o, u = 1;
      r.webgpuRegisterDevice = (b) => {
        if (o !== void 0) throw Error("another WebGPU EP inference session is being created.");
        if (b) {
          var E2 = t6.get(b);
          if (!E2) {
            let I = ((F2, j = 0) => {
              var te2 = Ao2(j);
              return j = So2(j, te2), de2[te2 >>> 0] = F2.queue, de2[j >>> 0] = F2, j;
            })(b, E2 = ho2(0));
            E2 = [u++, E2, I], t6.set(b, E2);
          }
          return n = b, o = E2[0], E2;
        }
        n = void 0, o = 0;
      };
      let c = /* @__PURE__ */ new Map();
      r.webgpuOnCreateSession = (b) => {
        if (o !== void 0) {
          var E2 = o;
          if (o = void 0, b) {
            let I = Dr2(E2);
            c.set(b, I), E2 === 0 && e(n ?? L2(I));
          }
          n = void 0;
        }
      }, r.webgpuOnReleaseSession = (b) => {
        c.delete(b);
      };
      let h2 = /* @__PURE__ */ Symbol("gpuBufferMetadata");
      r.webgpuRegisterBuffer = (b, E2, I) => {
        if (I) return b[h2] = [I, NaN], I;
        if (I = b[h2]) return I[1]++, I[0];
        if ((E2 = c.get(E2)) === void 0) throw Error("Invalid session handle passed to webgpuRegisterBuffer");
        return E2 = ((F2, j = 0) => (F2.mapState === "unmapped" || Te2(), j = Eo2(j), de2[j >>> 0] = F2, j))(b, E2), b[h2] = [E2, 1], E2;
      }, r.webgpuUnregisterBuffer = (b) => {
        let E2 = b[h2];
        if (!E2) throw Error("Buffer is not registered");
        E2[1]--, E2[1] === 0 && (mo2(E2[0]), delete b[h2]);
      }, r.webgpuGetBuffer = (b) => L2(b), r.webgpuCreateDownloader = (b, E2, I) => {
        if ((I = c.get(I)) === void 0) throw Error("Invalid session handle passed to webgpuRegisterBuffer");
        let F2 = L2(I), j = 16 * Math.ceil(Number(E2) / 16);
        return async () => {
          let te2 = F2.createBuffer({ size: j, usage: 9 });
          try {
            let B = F2.createCommandEncoder();
            return B.copyBufferToBuffer(b, 0, te2, 0, j), F2.queue.submit([B.finish()]), await te2.mapAsync(GPUMapMode.READ), te2.getMappedRange().slice(0, E2);
          } finally {
            te2.destroy();
          }
        };
      }, r.ad = (b, E2) => {
        var I = E2.buffer;
        let F2 = E2.byteOffset, j = E2.byteLength;
        if (E2 = 16 * Math.ceil(Number(j) / 16), b = L2(b), !n) {
          var te2 = Dr2(o);
          n = L2(te2);
        }
        let B = (te2 = n.createBuffer({ mappedAtCreation: true, size: E2, usage: 6 })).getMappedRange();
        new Uint8Array(B).set(new Uint8Array(I, F2, j)), te2.unmap(), (I = n.createCommandEncoder()).copyBufferToBuffer(te2, 0, b, 0, E2), n.queue.submit([I.finish()]), te2.destroy();
      };
    }, r.webnnInit = (e) => {
      let t6 = e[0];
      [r.le, r.jd, r.webnnEnsureTensor, r.Sd, r.webnnDownloadTensor, r.ke, r.webnnEnableTraceEvent] = e.slice(1), r.webnnReleaseTensorId = r.jd, r.webnnUploadTensor = r.Sd, r.webnnRegisterMLContext = r.ke, r.webnnOnRunStart = (n) => t6.onRunStart(n), r.webnnOnRunEnd = t6.onRunEnd.bind(t6), r.webnnOnReleaseSession = (n) => {
        t6.onReleaseSession(n);
      }, r.webnnCreateMLTensorDownloader = (n, o) => t6.createMLTensorDownloader(n, o), r.webnnRegisterMLTensor = (n, o, u, c) => t6.registerMLTensor(n, o, u, c), r.webnnCreateMLContext = (n) => t6.createMLContext(n), r.webnnRegisterMLConstant = (n, o, u, c, h2, b) => t6.registerMLConstant(n, o, u, c, h2, r.Uc, b), r.webnnRegisterGraphInput = t6.registerGraphInput.bind(t6), r.webnnIsGraphInput = t6.isGraphInput.bind(t6), r.webnnRegisterGraphOutput = t6.registerGraphOutput.bind(t6), r.webnnIsGraphOutput = t6.isGraphOutput.bind(t6), r.webnnCreateTemporaryTensor = t6.createTemporaryTensor.bind(t6), r.webnnIsGraphInputOutputTypeSupported = t6.isGraphInputOutputTypeSupported.bind(t6);
    }, re ? r : new Promise((e, t6) => {
      C = e, R = t6;
    });
  }
  var Xf;
  var Qf;
  var rs = k(() => {
    "use strict";
    Xf = es, Qf = globalThis.self?.name?.startsWith("em-pthread");
    Qf && es();
  });
  var as;
  var tn;
  var Zf;
  var ge;
  var ss;
  var en;
  var Kf;
  var ec;
  var is;
  var tc;
  var ns;
  var us;
  var os;
  var fs;
  var Yt = k(() => {
    "use strict";
    Ht();
    as = typeof location > "u" ? void 0 : location.origin, tn = import_meta.url > "file:" && import_meta.url < "file;", Zf = () => {
      if (true) {
        if (tn) {
          let a = URL;
          return new URL(new a("ort.webgpu.bundle.min.mjs", import_meta.url).href, as).href;
        }
        return import_meta.url;
      }
    }, ge = Zf(), ss = () => {
      if (ge && !ge.startsWith("blob:")) return ge.substring(0, ge.lastIndexOf("/") + 1);
    }, en = (a, r) => {
      try {
        let s = r ?? ge;
        return (s ? new URL(a, s) : new URL(a)).origin === as;
      } catch {
        return false;
      }
    }, Kf = (a, r) => {
      let s = r ?? ge;
      try {
        return (s ? new URL(a, s) : new URL(a)).href;
      } catch {
        return;
      }
    }, ec = (a, r) => `${r ?? "./"}${a}`, is = async (a) => {
      let s = await (await fetch(a, { credentials: "same-origin" })).blob();
      return URL.createObjectURL(s);
    }, tc = async (a) => (await import(
      /*webpackIgnore:true*/
      /*@vite-ignore*/
      a
    )).default, ns = (Ka(), $t(Za)).default, us = async () => {
      if (!ge) throw new Error("Failed to load proxy worker: cannot determine the script source URL.");
      if (en(ge)) return [void 0, ns()];
      let a = await is(ge);
      return [a, ns(a)];
    }, os = (rs(), $t(ts)).default, fs = async (a, r, s, f) => {
      let i = os && !(a || r);
      if (i) if (ge) i = en(ge) || f && !s;
      else if (f && !s) i = true;
      else throw new Error("cannot determine the script source URL.");
      if (i) return [void 0, os];
      {
        let d = "ort-wasm-simd-threaded.asyncify.mjs", l = a ?? Kf(d, r), m = s && l && !en(l, r), y = m ? await is(l) : l ?? ec(d, r);
        return [m ? y : void 0, await tc(y)];
      }
    };
  });
  var rn;
  var nn;
  var rr;
  var cs;
  var rc;
  var nc;
  var oc;
  var qt;
  var z;
  var je = k(() => {
    "use strict";
    Yt();
    nn = false, rr = false, cs = false, rc = () => {
      if (typeof SharedArrayBuffer > "u") return false;
      try {
        return typeof MessageChannel < "u" && new MessageChannel().port1.postMessage(new SharedArrayBuffer(1)), WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 4, 1, 96, 0, 0, 3, 2, 1, 0, 5, 4, 1, 3, 1, 1, 10, 11, 1, 9, 0, 65, 0, 254, 16, 2, 0, 26, 11]));
      } catch {
        return false;
      }
    }, nc = () => {
      try {
        return WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 4, 1, 96, 0, 0, 3, 2, 1, 0, 10, 30, 1, 28, 0, 65, 0, 253, 15, 253, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 253, 186, 1, 26, 11]));
      } catch {
        return false;
      }
    }, oc = () => {
      try {
        return WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 19, 1, 17, 0, 65, 1, 253, 15, 65, 2, 253, 15, 65, 3, 253, 15, 253, 147, 2, 11]));
      } catch {
        return false;
      }
    }, qt = async (a) => {
      if (nn) return Promise.resolve();
      if (rr) throw new Error("multiple calls to 'initializeWebAssembly()' detected.");
      if (cs) throw new Error("previous call to 'initializeWebAssembly()' failed.");
      rr = true;
      let r = a.initTimeout, s = a.numThreads;
      if (a.simd !== false) {
        if (a.simd === "relaxed") {
          if (!oc()) throw new Error("Relaxed WebAssembly SIMD is not supported in the current environment.");
        } else if (!nc()) throw new Error("WebAssembly SIMD is not supported in the current environment.");
      }
      let f = rc();
      s > 1 && !f && (typeof self < "u" && !self.crossOriginIsolated && console.warn("env.wasm.numThreads is set to " + s + ", but this will not work unless you enable crossOriginIsolated mode. See https://web.dev/cross-origin-isolation-guide/ for more info."), console.warn("WebAssembly multi-threading is not supported in the current environment. Falling back to single-threading."), a.numThreads = s = 1);
      let i = a.wasmPaths, d = typeof i == "string" ? i : void 0, l = i?.mjs, m = l?.href ?? l, y = i?.wasm, w = y?.href ?? y, T = a.wasmBinary, [g, v] = await fs(m, d, s > 1, !!T || !!w), S = false, C = [];
      if (r > 0 && C.push(new Promise((R) => {
        setTimeout(() => {
          S = true, R();
        }, r);
      })), C.push(new Promise((R, H) => {
        let U2 = { numThreads: s };
        if (T) U2.wasmBinary = T, U2.locateFile = (M2) => M2;
        else if (w || d) U2.locateFile = (M2) => w ?? d + M2;
        else if (m && m.indexOf("blob:") !== 0) U2.locateFile = (M2) => new URL(M2, m).href;
        else if (g) {
          let M2 = ss();
          M2 && (U2.locateFile = (Y2) => M2 + Y2);
        }
        v(U2).then((M2) => {
          rr = false, nn = true, rn = M2, R(), g && URL.revokeObjectURL(g);
        }, (M2) => {
          rr = false, cs = true, H(M2);
        });
      })), await Promise.race(C), S) throw new Error(`WebAssembly backend initializing failed due to timeout: ${r}ms`);
    }, z = () => {
      if (nn && rn) return rn;
      throw new Error("WebAssembly is not initialized yet.");
    };
  });
  var be;
  var Lt;
  var $;
  var nr = k(() => {
    "use strict";
    je();
    be = (a, r) => {
      let s = z(), f = s.lengthBytesUTF8(a) + 1, i = s._malloc(f);
      return s.stringToUTF8(a, i, f), r.push(i), i;
    }, Lt = (a, r, s, f) => {
      if (typeof a == "object" && a !== null) {
        if (s.has(a)) throw new Error("Circular reference in options");
        s.add(a);
      }
      Object.entries(a).forEach(([i, d]) => {
        let l = r ? r + i : i;
        if (typeof d == "object") Lt(d, l + ".", s, f);
        else if (typeof d == "string" || typeof d == "number") f(l, d.toString());
        else if (typeof d == "boolean") f(l, d ? "1" : "0");
        else throw new Error(`Can't handle extra config type: ${typeof d}`);
      });
    }, $ = (a) => {
      let r = z(), s = r.stackSave();
      try {
        let f = r.PTR_SIZE, i = r.stackAlloc(2 * f);
        r._OrtGetLastError(i, i + f);
        let d = Number(r.getValue(i, f === 4 ? "i32" : "i64")), l = r.getValue(i + f, "*"), m = l ? r.UTF8ToString(l) : "";
        throw new Error(`${a} ERROR_CODE: ${d}, ERROR_MESSAGE: ${m}`);
      } finally {
        r.stackRestore(s);
      }
    };
  });
  var ds;
  var ls = k(() => {
    "use strict";
    je();
    nr();
    ds = (a) => {
      let r = z(), s = 0, f = [], i = a || {};
      try {
        if (a?.logSeverityLevel === void 0) i.logSeverityLevel = 2;
        else if (typeof a.logSeverityLevel != "number" || !Number.isInteger(a.logSeverityLevel) || a.logSeverityLevel < 0 || a.logSeverityLevel > 4) throw new Error(`log severity level is not valid: ${a.logSeverityLevel}`);
        if (a?.logVerbosityLevel === void 0) i.logVerbosityLevel = 0;
        else if (typeof a.logVerbosityLevel != "number" || !Number.isInteger(a.logVerbosityLevel)) throw new Error(`log verbosity level is not valid: ${a.logVerbosityLevel}`);
        a?.terminate === void 0 && (i.terminate = false);
        let d = 0;
        return a?.tag !== void 0 && (d = be(a.tag, f)), s = r._OrtCreateRunOptions(i.logSeverityLevel, i.logVerbosityLevel, !!i.terminate, d), s === 0 && $("Can't create run options."), a?.extra !== void 0 && Lt(a.extra, "", /* @__PURE__ */ new WeakSet(), (l, m) => {
          let y = be(l, f), w = be(m, f);
          r._OrtAddRunConfigEntry(s, y, w) !== 0 && $(`Can't set a run config entry: ${l} - ${m}.`);
        }), [s, f];
      } catch (d) {
        throw s !== 0 && r._OrtReleaseRunOptions(s), f.forEach((l) => r._free(l)), d;
      }
    };
  });
  var ac;
  var sc;
  var ic;
  var on;
  var ot;
  var uc;
  var ps;
  var ms = k(() => {
    "use strict";
    je();
    nr();
    ac = (a) => {
      switch (a) {
        case "disabled":
          return 0;
        case "basic":
          return 1;
        case "extended":
          return 2;
        case "layout":
          return 3;
        case "all":
          return 99;
        default:
          throw new Error(`unsupported graph optimization level: ${a}`);
      }
    }, sc = (a) => {
      switch (a) {
        case "sequential":
          return 0;
        case "parallel":
          return 1;
        default:
          throw new Error(`unsupported execution mode: ${a}`);
      }
    }, ic = (a) => {
      a.extra || (a.extra = {}), a.extra.session || (a.extra.session = {});
      let r = a.extra.session;
      r.use_ort_model_bytes_directly || (r.use_ort_model_bytes_directly = "1"), a.executionProviders && a.executionProviders.some((s) => (typeof s == "string" ? s : s.name) === "webgpu") && (a.enableMemPattern = false);
    }, on = (a, r, s, f) => {
      let i = be(r, f), d = be(s, f);
      z()._OrtAddSessionConfigEntry(a, i, d) !== 0 && $(`Can't set a session config entry: ${r} - ${s}.`);
    }, ot = (a, r, s, f) => {
      let i = be(r, f), d = be(s, f);
      a.push([i, d]);
    }, uc = async (a, r, s) => {
      let f = r.executionProviders;
      for (let i of f) {
        let d = typeof i == "string" ? i : i.name, l = [];
        switch (d) {
          case "webnn":
            if (d = "WEBNN", typeof i != "string") {
              let v = i?.deviceType;
              v && on(a, "deviceType", v, s);
            }
            break;
          case "webgpu":
            {
              d = "WebGPU";
              let g;
              if (typeof i != "string") {
                let S = i;
                if (S.device) if (typeof GPUDevice < "u" && S.device instanceof GPUDevice) g = S.device;
                else throw new Error("Invalid GPU device set in WebGPU EP options.");
                let { enableGraphCapture: C } = r;
                if (typeof C == "boolean" && C && ot(l, "enableGraphCapture", "1", s), typeof S.preferredLayout == "string" && ot(l, "preferredLayout", S.preferredLayout, s), S.forceCpuNodeNames) {
                  let R = Array.isArray(S.forceCpuNodeNames) ? S.forceCpuNodeNames : [S.forceCpuNodeNames];
                  ot(l, "forceCpuNodeNames", R.join(`
`), s);
                }
                S.validationMode && ot(l, "validationMode", S.validationMode, s);
              }
              let v = z().webgpuRegisterDevice(g);
              if (v) {
                let [S, C, R] = v;
                ot(l, "deviceId", S.toString(), s), ot(l, "webgpuInstance", C.toString(), s), ot(l, "webgpuDevice", R.toString(), s);
              }
            }
            break;
          case "wasm":
          case "cpu":
            continue;
          default:
            throw new Error(`not supported execution provider: ${d}`);
        }
        let m = be(d, s), y = l.length, w = 0, T = 0;
        if (y > 0) {
          w = z()._malloc(y * z().PTR_SIZE), s.push(w), T = z()._malloc(y * z().PTR_SIZE), s.push(T);
          for (let g = 0; g < y; g++) z().setValue(w + g * z().PTR_SIZE, l[g][0], "*"), z().setValue(T + g * z().PTR_SIZE, l[g][1], "*");
        }
        await z()._OrtAppendExecutionProvider(a, m, w, T, y) !== 0 && $(`Can't append execution provider: ${d}.`);
      }
    }, ps = async (a) => {
      let r = z(), s = 0, f = [], i = a || {};
      ic(i);
      try {
        let d = ac(i.graphOptimizationLevel ?? "all"), l = sc(i.executionMode ?? "sequential"), m = typeof i.logId == "string" ? be(i.logId, f) : 0, y = i.logSeverityLevel ?? 2;
        if (!Number.isInteger(y) || y < 0 || y > 4) throw new Error(`log severity level is not valid: ${y}`);
        let w = i.logVerbosityLevel ?? 0;
        if (!Number.isInteger(w) || w < 0 || w > 4) throw new Error(`log verbosity level is not valid: ${w}`);
        let T = typeof i.optimizedModelFilePath == "string" ? be(i.optimizedModelFilePath, f) : 0;
        if (s = r._OrtCreateSessionOptions(d, !!i.enableCpuMemArena, !!i.enableMemPattern, l, !!i.enableProfiling, 0, m, y, w, T), s === 0 && $("Can't create session options."), i.executionProviders && await uc(s, i, f), i.enableGraphCapture !== void 0) {
          if (typeof i.enableGraphCapture != "boolean") throw new Error(`enableGraphCapture must be a boolean value: ${i.enableGraphCapture}`);
          on(s, "enableGraphCapture", i.enableGraphCapture.toString(), f);
        }
        if (i.freeDimensionOverrides) for (let [g, v] of Object.entries(i.freeDimensionOverrides)) {
          if (typeof g != "string") throw new Error(`free dimension override name must be a string: ${g}`);
          if (typeof v != "number" || !Number.isInteger(v) || v < 0) throw new Error(`free dimension override value must be a non-negative integer: ${v}`);
          let S = be(g, f);
          r._OrtAddFreeDimensionOverride(s, S, v) !== 0 && $(`Can't set a free dimension override: ${g} - ${v}.`);
        }
        return i.extra !== void 0 && Lt(i.extra, "", /* @__PURE__ */ new WeakSet(), (g, v) => {
          on(s, g, v, f);
        }), [s, f];
      } catch (d) {
        throw s !== 0 && r._OrtReleaseSessionOptions(s) !== 0 && $("Can't release session options."), f.forEach((l) => r._free(l)), d;
      }
    };
  });
  var He;
  var or;
  var mt;
  var at;
  var Ot;
  var ar;
  var sr;
  var an;
  var st = k(() => {
    "use strict";
    He = (a) => {
      switch (a) {
        case "int8":
          return 3;
        case "uint8":
          return 2;
        case "bool":
          return 9;
        case "int16":
          return 5;
        case "uint16":
          return 4;
        case "int32":
          return 6;
        case "uint32":
          return 12;
        case "float16":
          return 10;
        case "float32":
          return 1;
        case "float64":
          return 11;
        case "string":
          return 8;
        case "int64":
          return 7;
        case "uint64":
          return 13;
        case "int4":
          return 22;
        case "uint4":
          return 21;
        default:
          throw new Error(`unsupported data type: ${a}`);
      }
    }, or = (a) => {
      switch (a) {
        case 3:
          return "int8";
        case 2:
          return "uint8";
        case 9:
          return "bool";
        case 5:
          return "int16";
        case 4:
          return "uint16";
        case 6:
          return "int32";
        case 12:
          return "uint32";
        case 10:
          return "float16";
        case 1:
          return "float32";
        case 11:
          return "float64";
        case 8:
          return "string";
        case 7:
          return "int64";
        case 13:
          return "uint64";
        case 22:
          return "int4";
        case 21:
          return "uint4";
        default:
          throw new Error(`unsupported data type: ${a}`);
      }
    }, mt = (a, r) => {
      let s = [-1, 4, 1, 1, 2, 2, 4, 8, -1, 1, 2, 8, 4, 8, -1, -1, -1, -1, -1, -1, -1, 0.5, 0.5][a], f = typeof r == "number" ? r : r.reduce((i, d) => i * d, 1);
      return s > 0 ? Math.ceil(f * s) : void 0;
    }, at = (a) => {
      switch (a) {
        case "float16":
          return typeof Float16Array < "u" && Float16Array.from ? Float16Array : Uint16Array;
        case "float32":
          return Float32Array;
        case "uint8":
          return Uint8Array;
        case "int8":
          return Int8Array;
        case "uint16":
          return Uint16Array;
        case "int16":
          return Int16Array;
        case "int32":
          return Int32Array;
        case "bool":
          return Uint8Array;
        case "float64":
          return Float64Array;
        case "uint32":
          return Uint32Array;
        case "int64":
          return BigInt64Array;
        case "uint64":
          return BigUint64Array;
        default:
          throw new Error(`unsupported type: ${a}`);
      }
    }, Ot = (a) => {
      switch (a) {
        case "verbose":
          return 0;
        case "info":
          return 1;
        case "warning":
          return 2;
        case "error":
          return 3;
        case "fatal":
          return 4;
        default:
          throw new Error(`unsupported logging level: ${a}`);
      }
    }, ar = (a) => a === "float32" || a === "float16" || a === "int32" || a === "int64" || a === "uint32" || a === "uint8" || a === "bool" || a === "uint4" || a === "int4", sr = (a) => a === "float32" || a === "float16" || a === "int32" || a === "int64" || a === "uint32" || a === "uint64" || a === "int8" || a === "uint8" || a === "bool" || a === "uint4" || a === "int4", an = (a) => {
      switch (a) {
        case "none":
          return 0;
        case "cpu":
          return 1;
        case "cpu-pinned":
          return 2;
        case "texture":
          return 3;
        case "gpu-buffer":
          return 4;
        case "ml-tensor":
          return 5;
        default:
          throw new Error(`unsupported data location: ${a}`);
      }
    };
  });
  var Bt;
  var sn = k(() => {
    "use strict";
    Ht();
    Bt = async (a) => {
      if (typeof a == "string") if (false) try {
        let { readFile: r } = Hr("node:fs/promises");
        return new Uint8Array(await r(a));
      } catch (r) {
        if (r.code === "ERR_FS_FILE_TOO_LARGE") {
          let { createReadStream: s } = Hr("node:fs"), f = s(a), i = [];
          for await (let d of f) i.push(d);
          return new Uint8Array(Buffer.concat(i));
        }
        throw r;
      }
      else {
        let r = await fetch(a);
        if (!r.ok) throw new Error(`failed to load external data file: ${a}`);
        let s = r.headers.get("Content-Length"), f = s ? parseInt(s, 10) : 0;
        if (f < 1073741824) return new Uint8Array(await r.arrayBuffer());
        {
          if (!r.body) throw new Error(`failed to load external data file: ${a}, no response body.`);
          let i = r.body.getReader(), d;
          try {
            d = new ArrayBuffer(f);
          } catch (m) {
            if (m instanceof RangeError) {
              let y = Math.ceil(f / 65536);
              d = new WebAssembly.Memory({ initial: y, maximum: y }).buffer;
            } else throw m;
          }
          let l = 0;
          for (; ; ) {
            let { done: m, value: y } = await i.read();
            if (m) break;
            let w = y.byteLength;
            new Uint8Array(d, l, w).set(y), l += w;
          }
          return new Uint8Array(d, 0, f);
        }
      }
      else return a instanceof Blob ? new Uint8Array(await a.arrayBuffer()) : a instanceof Uint8Array ? a : new Uint8Array(a);
    };
  });
  var hs;
  var ys = k(() => {
    "use strict";
    st();
    hs = (a, r) => new (at(r))(a);
  });
  var fc;
  var cc;
  var bs;
  var ws;
  var gs;
  var dc;
  var pe;
  var un = k(() => {
    "use strict";
    st();
    fc = ["V", "I", "W", "E", "F"], cc = (a, r) => {
      console.log(`[${fc[a]},${(/* @__PURE__ */ new Date()).toISOString()}]${r}`);
    }, gs = (a, r) => {
      bs = a, ws = r;
    }, dc = (a, r) => {
      let s = Ot(a), f = Ot(bs);
      s >= f && cc(s, typeof r == "function" ? r() : r);
    }, pe = (...a) => {
      ws && dc(...a);
    };
  });
  var vs;
  var cn;
  var Es;
  var lc;
  var Ts;
  var pc;
  var Ss;
  var ir;
  var ur;
  var fn;
  var As;
  var Is = k(() => {
    "use strict";
    st();
    un();
    vs = /* @__PURE__ */ new Map([["float32", 32], ["float16", 16], ["int32", 32], ["uint32", 32], ["int64", 64], ["uint64", 64], ["int8", 8], ["uint8", 8], ["int4", 4], ["uint4", 4]]), cn = (a, r) => {
      if (r === "int32") return a;
      let s = vs.get(r);
      if (!s) throw new Error(`WebNN backend does not support data type: ${r}`);
      let f = s / 8;
      if (a.byteLength % f !== 0) throw new Error(`Invalid Uint8Array length - must be a multiple of ${f}.`);
      let i = a.byteLength / f, d = new (at(r))(a.buffer, a.byteOffset, i);
      switch (r) {
        case "int64":
        case "uint64": {
          let l = new Int32Array(i);
          for (let m = 0; m < i; m++) {
            let y = d[m];
            if (y > 2147483647n || y < -2147483648n) throw new Error("Can not convert int64 data to int32 - value out of range.");
            l[m] = Number(y);
          }
          return new Uint8Array(l.buffer);
        }
        case "int8":
        case "uint8":
        case "uint32": {
          if (r === "uint32" && d.some((m) => m > 2147483647)) throw new Error("Can not convert uint32 data to int32 - value out of range.");
          let l = Int32Array.from(d, Number);
          return new Uint8Array(l.buffer);
        }
        default:
          throw new Error(`Unsupported data conversion from ${r} to 'int32'`);
      }
    }, Es = (a, r) => {
      if (r === "int32") return a;
      if (a.byteLength % 4 !== 0) throw new Error("Invalid Uint8Array length - must be a multiple of 4 (int32).");
      let s = a.byteLength / 4, f = new Int32Array(a.buffer, a.byteOffset, s);
      switch (r) {
        case "int64": {
          let i = BigInt64Array.from(f, BigInt);
          return new Uint8Array(i.buffer);
        }
        case "uint64": {
          if (f.some((d) => d < 0)) throw new Error("Can not convert int32 data to uin64 - negative value found.");
          let i = BigUint64Array.from(f, BigInt);
          return new Uint8Array(i.buffer);
        }
        case "int8": {
          if (f.some((d) => d < -128 || d > 127)) throw new Error("Can not convert int32 data to int8 - value out of range.");
          let i = Int8Array.from(f, Number);
          return new Uint8Array(i.buffer);
        }
        case "uint8": {
          if (f.some((i) => i < 0 || i > 255)) throw new Error("Can not convert int32 data to uint8 - value out of range.");
          return Uint8Array.from(f, Number);
        }
        case "uint32": {
          if (f.some((d) => d < 0)) throw new Error("Can not convert int32 data to uint32 - negative value found.");
          let i = Uint32Array.from(f, Number);
          return new Uint8Array(i.buffer);
        }
        default:
          throw new Error(`Unsupported data conversion from 'int32' to ${r}`);
      }
    }, lc = 1, Ts = () => lc++, pc = /* @__PURE__ */ new Map([["int8", "int32"], ["uint8", "int32"], ["uint32", "int32"], ["int64", "int32"]]), Ss = (a, r) => {
      let s = vs.get(a);
      if (!s) throw new Error(`WebNN backend does not support data type: ${a}`);
      return r.length > 0 ? Math.ceil(r.reduce((f, i) => f * i) * s / 8) : 0;
    }, ir = class {
      constructor(r) {
        this.isDataConverted = false;
        let { sessionId: s, context: f, tensor: i, dataType: d, shape: l, fallbackDataType: m } = r;
        this.sessionId = s, this.mlContext = f, this.mlTensor = i, this.dataType = d, this.tensorShape = l, this.fallbackDataType = m;
      }
      get tensor() {
        return this.mlTensor;
      }
      get type() {
        return this.dataType;
      }
      get fallbackType() {
        return this.fallbackDataType;
      }
      get shape() {
        return this.tensorShape;
      }
      get byteLength() {
        return Ss(this.dataType, this.tensorShape);
      }
      destroy() {
        pe("verbose", () => "[WebNN] TensorWrapper.destroy"), this.mlTensor.destroy();
      }
      write(r) {
        this.mlContext.writeTensor(this.mlTensor, r);
      }
      async read(r) {
        if (this.fallbackDataType) {
          let s = await this.mlContext.readTensor(this.mlTensor), f = Es(new Uint8Array(s), this.dataType);
          if (r) {
            (r instanceof ArrayBuffer ? new Uint8Array(r) : new Uint8Array(r.buffer, r.byteOffset, r.byteLength)).set(f);
            return;
          } else return f.buffer;
        } else return r ? this.mlContext.readTensor(this.mlTensor, r) : this.mlContext.readTensor(this.mlTensor);
      }
      canReuseTensor(r, s, f) {
        return this.mlContext === r && this.dataType === s && this.tensorShape.length === f.length && this.tensorShape.every((i, d) => i === f[d]);
      }
      setIsDataConverted(r) {
        this.isDataConverted = r;
      }
    }, ur = class {
      constructor(r, s) {
        this.tensorManager = r;
        this.wrapper = s;
      }
      get tensorWrapper() {
        return this.wrapper;
      }
      releaseTensor() {
        this.tensorWrapper && (this.tensorManager.releaseTensor(this.tensorWrapper), this.wrapper = void 0);
      }
      async ensureTensor(r, s, f, i) {
        let d = this.tensorManager.getMLContext(r), l = this.tensorManager.getMLOpSupportLimits(r), m;
        if (!l?.input.dataTypes.includes(s)) {
          if (m = pc.get(s), !m || l?.input.dataTypes.includes(m)) throw new Error(`WebNN backend does not support data type: ${s}`);
          pe("verbose", () => `[WebNN] TensorIdTracker.ensureTensor: fallback dataType from ${s} to ${m}`);
        }
        if (this.wrapper) {
          if (this.wrapper.canReuseTensor(d, s, f)) return this.wrapper.tensor;
          if (i) {
            if (this.wrapper.byteLength !== Ss(s, f)) throw new Error("Unable to copy data to tensor with different size.");
            this.activeUpload = new Uint8Array(await this.wrapper.read());
          }
          this.tensorManager.releaseTensor(this.wrapper);
        }
        let y = typeof MLTensorUsage > "u" ? void 0 : MLTensorUsage.READ | MLTensorUsage.WRITE;
        return this.wrapper = await this.tensorManager.getCachedTensor(r, s, f, y, true, true, m), i && this.activeUpload && (this.wrapper.write(this.activeUpload), this.activeUpload = void 0), this.wrapper.tensor;
      }
      upload(r) {
        let s = r;
        if (this.wrapper) {
          if (this.wrapper.fallbackType) if (this.wrapper.fallbackType === "int32") s = cn(r, this.wrapper.type), this.wrapper.setIsDataConverted(true);
          else throw new Error(`Unsupported fallback data type: ${this.wrapper.fallbackType}`);
          if (r.byteLength === this.wrapper.byteLength) {
            this.wrapper.write(s);
            return;
          } else pe("verbose", () => "Data size does not match tensor size. Releasing tensor."), this.releaseTensor();
        }
        this.activeUpload ? this.activeUpload.set(s) : this.activeUpload = new Uint8Array(s);
      }
      async download(r) {
        if (this.activeUpload) {
          let s = this.wrapper?.isDataConverted ? Es(this.activeUpload, this.wrapper?.type) : this.activeUpload;
          if (r) {
            r instanceof ArrayBuffer ? new Uint8Array(r).set(s) : new Uint8Array(r.buffer, r.byteOffset, r.byteLength).set(s);
            return;
          } else return s.buffer;
        }
        if (!this.wrapper) throw new Error("Tensor has not been created.");
        return r ? this.wrapper.read(r) : this.wrapper.read();
      }
    }, fn = class {
      constructor(r) {
        this.backend = r;
        this.tensorTrackersById = /* @__PURE__ */ new Map();
        this.freeTensors = [];
        this.externalTensors = /* @__PURE__ */ new Set();
      }
      getMLContext(r) {
        let s = this.backend.getMLContext(r);
        if (!s) throw new Error("MLContext not found for session.");
        return s;
      }
      getMLOpSupportLimits(r) {
        return this.backend.getMLOpSupportLimits(r);
      }
      reserveTensorId() {
        let r = Ts();
        return this.tensorTrackersById.set(r, new ur(this)), r;
      }
      releaseTensorId(r) {
        let s = this.tensorTrackersById.get(r);
        s && (this.tensorTrackersById.delete(r), s.tensorWrapper && this.releaseTensor(s.tensorWrapper));
      }
      async ensureTensor(r, s, f, i, d) {
        pe("verbose", () => `[WebNN] TensorManager.ensureTensor {tensorId: ${s}, dataType: ${f}, shape: ${i}, copyOld: ${d}}`);
        let l = this.tensorTrackersById.get(s);
        if (!l) throw new Error("Tensor not found.");
        return l.ensureTensor(r, f, i, d);
      }
      upload(r, s) {
        let f = this.tensorTrackersById.get(r);
        if (!f) throw new Error("Tensor not found.");
        f.upload(s);
      }
      async download(r, s) {
        pe("verbose", () => `[WebNN] TensorManager.download {tensorId: ${r}, dstBuffer: ${s?.byteLength}}`);
        let f = this.tensorTrackersById.get(r);
        if (!f) throw new Error("Tensor not found.");
        return f.download(s);
      }
      releaseTensorsForSession(r) {
        for (let s of this.freeTensors) s.sessionId === r && s.destroy();
        this.freeTensors = this.freeTensors.filter((s) => s.sessionId !== r);
      }
      registerTensor(r, s, f, i) {
        let d = this.getMLContext(r), l = Ts(), m = new ir({ sessionId: r, context: d, tensor: s, dataType: f, shape: i });
        return this.tensorTrackersById.set(l, new ur(this, m)), this.externalTensors.add(m), l;
      }
      async getCachedTensor(r, s, f, i, d, l, m) {
        let y = this.getMLContext(r);
        for (let [T, g] of this.freeTensors.entries()) if (g.canReuseTensor(y, s, f)) {
          pe("verbose", () => `[WebNN] Reusing tensor {dataType: ${s}, ${m ? `fallbackDataType: ${m},` : ""} shape: ${f}`);
          let v = this.freeTensors.splice(T, 1)[0];
          return v.sessionId = r, v;
        }
        pe("verbose", () => `[WebNN] MLContext.createTensor {dataType: ${s}, ${m ? `fallbackDataType: ${m},` : ""} shape: ${f}}`);
        let w = await y.createTensor({ dataType: m ?? s, shape: f, dimensions: f, usage: i, writable: d, readable: l });
        return new ir({ sessionId: r, context: y, tensor: w, dataType: s, shape: f, fallbackDataType: m });
      }
      releaseTensor(r) {
        this.externalTensors.has(r) && this.externalTensors.delete(r), this.freeTensors.push(r);
      }
    }, As = (...a) => new fn(...a);
  });
  var xs = {};
  At(xs, { WebNNBackend: () => dn });
  var fr;
  var mc;
  var dn;
  var Ls = k(() => {
    "use strict";
    st();
    je();
    ys();
    Is();
    un();
    fr = /* @__PURE__ */ new Map([[1, "float32"], [10, "float16"], [6, "int32"], [12, "uint32"], [7, "int64"], [13, "uint64"], [22, "int4"], [21, "uint4"], [3, "int8"], [2, "uint8"], [9, "uint8"]]), mc = (a, r) => {
      if (a === r) return true;
      if (a === void 0 || r === void 0) return false;
      let s = Object.keys(a).sort(), f = Object.keys(r).sort();
      return s.length === f.length && s.every((i, d) => i === f[d] && a[i] === r[i]);
    }, dn = class {
      constructor(r) {
        this.tensorManager = As(this);
        this.mlContextBySessionId = /* @__PURE__ */ new Map();
        this.sessionIdsByMLContext = /* @__PURE__ */ new Map();
        this.mlContextCache = [];
        this.sessionGraphInputs = /* @__PURE__ */ new Map();
        this.sessionGraphOutputs = /* @__PURE__ */ new Map();
        this.temporaryGraphInputs = [];
        this.temporaryGraphOutputs = [];
        this.temporarySessionTensorIds = /* @__PURE__ */ new Map();
        this.mlOpSupportLimitsBySessionId = /* @__PURE__ */ new Map();
        gs(r.logLevel, !!r.debug);
      }
      get currentSessionId() {
        if (this.activeSessionId === void 0) throw new Error("No active session");
        return this.activeSessionId;
      }
      onRunStart(r) {
        pe("verbose", () => `[WebNN] onRunStart {sessionId: ${r}}`), this.activeSessionId = r;
      }
      onRunEnd(r) {
        pe("verbose", () => `[WebNN] onRunEnd {sessionId: ${r}}`);
        let s = this.temporarySessionTensorIds.get(r);
        if (s) {
          for (let f of s) pe("verbose", () => `[WebNN] releasing temporary tensor {tensorId: ${f}}`), this.tensorManager.releaseTensorId(f);
          this.temporarySessionTensorIds.delete(r), this.activeSessionId = void 0;
        }
      }
      async createMLContext(r) {
        if (r instanceof GPUDevice) {
          let f = this.mlContextCache.findIndex((i) => i.gpuDevice === r);
          if (f !== -1) return this.mlContextCache[f].mlContext;
          {
            let i = await navigator.ml.createContext(r);
            return this.mlContextCache.push({ gpuDevice: r, mlContext: i }), i;
          }
        } else if (r === void 0) {
          let f = this.mlContextCache.findIndex((i) => i.options === void 0 && i.gpuDevice === void 0);
          if (f !== -1) return this.mlContextCache[f].mlContext;
          {
            let i = await navigator.ml.createContext();
            return this.mlContextCache.push({ mlContext: i }), i;
          }
        }
        let s = this.mlContextCache.findIndex((f) => mc(f.options, r));
        if (s !== -1) return this.mlContextCache[s].mlContext;
        {
          let f = await navigator.ml.createContext(r);
          return this.mlContextCache.push({ options: r, mlContext: f }), f;
        }
      }
      registerMLContext(r, s) {
        this.mlContextBySessionId.set(r, s);
        let f = this.sessionIdsByMLContext.get(s);
        f || (f = /* @__PURE__ */ new Set(), this.sessionIdsByMLContext.set(s, f)), f.add(r), this.mlOpSupportLimitsBySessionId.has(r) || this.mlOpSupportLimitsBySessionId.set(r, s.opSupportLimits()), this.temporaryGraphInputs.length > 0 && (this.sessionGraphInputs.set(r, this.temporaryGraphInputs), this.temporaryGraphInputs = []), this.temporaryGraphOutputs.length > 0 && (this.sessionGraphOutputs.set(r, this.temporaryGraphOutputs), this.temporaryGraphOutputs = []);
      }
      onReleaseSession(r) {
        this.sessionGraphInputs.delete(r), this.sessionGraphOutputs.delete(r);
        let s = this.mlContextBySessionId.get(r);
        if (!s) return;
        this.tensorManager.releaseTensorsForSession(r), this.mlContextBySessionId.delete(r), this.mlOpSupportLimitsBySessionId.delete(r);
        let f = this.sessionIdsByMLContext.get(s);
        if (f.delete(r), f.size === 0) {
          this.sessionIdsByMLContext.delete(s);
          let i = this.mlContextCache.findIndex((d) => d.mlContext === s);
          i !== -1 && this.mlContextCache.splice(i, 1);
        }
      }
      getMLContext(r) {
        return this.mlContextBySessionId.get(r);
      }
      getMLOpSupportLimits(r) {
        return this.mlOpSupportLimitsBySessionId.get(r);
      }
      reserveTensorId() {
        return this.tensorManager.reserveTensorId();
      }
      releaseTensorId(r) {
        pe("verbose", () => `[WebNN] releaseTensorId {tensorId: ${r}}`), this.tensorManager.releaseTensorId(r);
      }
      async ensureTensor(r, s, f, i, d) {
        let l = fr.get(f);
        if (!l) throw new Error(`Unsupported ONNX data type: ${f}`);
        return this.tensorManager.ensureTensor(r ?? this.currentSessionId, s, l, i, d);
      }
      async createTemporaryTensor(r, s, f) {
        pe("verbose", () => `[WebNN] createTemporaryTensor {onnxDataType: ${s}, shape: ${f}}`);
        let i = fr.get(s);
        if (!i) throw new Error(`Unsupported ONNX data type: ${s}`);
        let d = this.tensorManager.reserveTensorId();
        await this.tensorManager.ensureTensor(r, d, i, f, false);
        let l = this.temporarySessionTensorIds.get(r);
        return l ? l.push(d) : this.temporarySessionTensorIds.set(r, [d]), d;
      }
      uploadTensor(r, s) {
        if (!z().shouldTransferToMLTensor) throw new Error("Trying to upload to a MLTensor while shouldTransferToMLTensor is false");
        pe("verbose", () => `[WebNN] uploadTensor {tensorId: ${r}, data: ${s.byteLength}}`), this.tensorManager.upload(r, s);
      }
      async downloadTensor(r, s) {
        return this.tensorManager.download(r, s);
      }
      createMLTensorDownloader(r, s) {
        return async () => {
          let f = await this.tensorManager.download(r);
          return hs(f, s);
        };
      }
      registerMLTensor(r, s, f, i) {
        let d = fr.get(f);
        if (!d) throw new Error(`Unsupported ONNX data type: ${f}`);
        let l = this.tensorManager.registerTensor(r, s, d, i);
        return pe("verbose", () => `[WebNN] registerMLTensor {tensor: ${s}, dataType: ${d}, dimensions: ${i}} -> {tensorId: ${l}}`), l;
      }
      registerMLConstant(r, s, f, i, d, l, m = false) {
        if (!l) throw new Error("External mounted files are not available.");
        let y = r;
        r.startsWith("./") && (y = r.substring(2));
        let w = l.get(y);
        if (!w) throw new Error(`File with name ${y} not found in preloaded files.`);
        if (s + f > w.byteLength) throw new Error("Out of bounds: data offset and length exceed the external file data size.");
        let T = w.slice(s, s + f).buffer, g;
        switch (d.dataType) {
          case "float32":
            g = new Float32Array(T);
            break;
          case "float16":
            g = typeof Float16Array < "u" && Float16Array.from ? new Float16Array(T) : new Uint16Array(T);
            break;
          case "int32":
            g = new Int32Array(T);
            break;
          case "uint32":
            g = new Uint32Array(T);
            break;
          case "int64":
            if (m) {
              let v = cn(new Uint8Array(T), "int64");
              g = new Int32Array(v.buffer), d.dataType = "int32";
            } else g = new BigInt64Array(T);
            break;
          case "uint64":
            g = new BigUint64Array(T);
            break;
          case "int8":
            g = new Int8Array(T);
            break;
          case "int4":
          case "uint4":
          case "uint8":
            g = new Uint8Array(T);
            break;
          default:
            throw new Error(`Unsupported data type: ${d.dataType} in creating WebNN Constant from external data.`);
        }
        return pe("verbose", () => `[WebNN] registerMLConstant {dataType: ${d.dataType}, shape: ${d.shape}}} ${m ? "(Note: it was int64 data type and registered to int32 as workaround)" : ""}`), i.constant(d, g);
      }
      registerGraphInput(r) {
        this.temporaryGraphInputs.push(r);
      }
      registerGraphOutput(r) {
        this.temporaryGraphOutputs.push(r);
      }
      isGraphInput(r, s) {
        let f = this.sessionGraphInputs.get(r);
        return f ? f.includes(s) : false;
      }
      isGraphOutput(r, s) {
        let f = this.sessionGraphOutputs.get(r);
        return f ? f.includes(s) : false;
      }
      isGraphInputOutputTypeSupported(r, s, f = true) {
        let i = fr.get(He(s)), d = this.mlOpSupportLimitsBySessionId.get(r);
        return typeof i > "u" ? false : f ? !!d?.input.dataTypes.includes(i) : !!d?.output.dataTypes.includes(i);
      }
      flush() {
      }
    };
  });
  var hc;
  var Jt;
  var Xt;
  var it;
  var yc;
  var Os;
  var xt;
  var Qt;
  var Zt;
  var Bs;
  var Kt;
  var er;
  var tr;
  var Kr = k(() => {
    "use strict";
    Ve();
    ls();
    ms();
    st();
    je();
    nr();
    sn();
    hc = (a, r) => {
      z()._OrtInit(a, r) !== 0 && $("Can't initialize onnxruntime.");
    }, Jt = async (a) => {
      hc(a.wasm.numThreads, Ot(a.logLevel));
    }, Xt = async (a, r) => {
      z().asyncInit?.();
      let s = a.webgpu.adapter;
      if (r === "webgpu") {
        if (typeof navigator > "u" || !navigator.gpu) throw new Error("WebGPU is not supported in current environment");
        if (s) {
          if (typeof s.limits != "object" || typeof s.features != "object" || typeof s.requestDevice != "function") throw new Error("Invalid GPU adapter set in `env.webgpu.adapter`. It must be a GPUAdapter object.");
        } else {
          let f = a.webgpu.powerPreference;
          if (f !== void 0 && f !== "low-power" && f !== "high-performance") throw new Error(`Invalid powerPreference setting: "${f}"`);
          let i = a.webgpu.forceFallbackAdapter;
          if (i !== void 0 && typeof i != "boolean") throw new Error(`Invalid forceFallbackAdapter setting: "${i}"`);
          if (s = await navigator.gpu.requestAdapter({ powerPreference: f, forceFallbackAdapter: i }), !s) throw new Error('Failed to get GPU adapter. You may need to enable flag "--enable-unsafe-webgpu" if you are using Chrome.');
        }
      }
      if (r === "webnn" && (typeof navigator > "u" || !navigator.ml)) throw new Error("WebNN is not supported in current environment");
      if (r === "webgpu" && z().webgpuInit((f) => {
        a.webgpu.device = f;
      }), r === "webnn") {
        let f = new (Ls(), $t(xs)).WebNNBackend(a);
        z().webnnInit([f, () => f.reserveTensorId(), (i) => f.releaseTensorId(i), async (i, d, l, m, y) => f.ensureTensor(i, d, l, m, y), (i, d) => {
          f.uploadTensor(i, d);
        }, async (i, d) => f.downloadTensor(i, d), (i, d) => f.registerMLContext(i, d), !!a.trace]);
      }
    }, it = /* @__PURE__ */ new Map(), yc = (a) => {
      let r = z(), s = r.stackSave();
      try {
        let f = r.PTR_SIZE, i = r.stackAlloc(2 * f);
        r._OrtGetInputOutputCount(a, i, i + f) !== 0 && $("Can't get session input/output count.");
        let l = f === 4 ? "i32" : "i64";
        return [Number(r.getValue(i, l)), Number(r.getValue(i + f, l))];
      } finally {
        r.stackRestore(s);
      }
    }, Os = (a, r) => {
      let s = z(), f = s.stackSave(), i = 0;
      try {
        let d = s.PTR_SIZE, l = s.stackAlloc(2 * d);
        s._OrtGetInputOutputMetadata(a, r, l, l + d) !== 0 && $("Can't get session input/output metadata.");
        let y = Number(s.getValue(l, "*"));
        i = Number(s.getValue(l + d, "*"));
        let w = s.HEAP32[i / 4];
        if (w === 0) return [y, 0];
        let T = s.HEAPU32[i / 4 + 1], g = [];
        for (let v = 0; v < T; v++) {
          let S = Number(s.getValue(i + 8 + v * d, "*"));
          g.push(S !== 0 ? s.UTF8ToString(S) : Number(s.getValue(i + 8 + (v + T) * d, "*")));
        }
        return [y, w, g];
      } finally {
        s.stackRestore(f), i !== 0 && s._OrtFree(i);
      }
    }, xt = (a) => {
      let r = z(), s = r._malloc(a.byteLength);
      if (s === 0) throw new Error(`Can't create a session. failed to allocate a buffer of size ${a.byteLength}.`);
      return r.HEAPU8.set(a, s), [s, a.byteLength];
    }, Qt = async (a, r) => {
      let s, f, i = z();
      Array.isArray(a) ? [s, f] = a : a.buffer === i.HEAPU8.buffer ? [s, f] = [a.byteOffset, a.byteLength] : [s, f] = xt(a);
      let d = 0, l = 0, m = 0, y = [], w = [], T = [];
      try {
        if ([l, y] = await ps(r), r?.externalData && i.mountExternalData) {
          let O = [];
          for (let W2 of r.externalData) {
            let oe2 = typeof W2 == "string" ? W2 : W2.path;
            O.push(Bt(typeof W2 == "string" ? W2 : W2.data).then((p) => {
              i.mountExternalData(oe2, p);
            }));
          }
          await Promise.all(O);
        }
        for (let O of r?.executionProviders ?? []) if ((typeof O == "string" ? O : O.name) === "webnn") {
          if (i.shouldTransferToMLTensor = false, typeof O != "string") {
            let oe2 = O, p = oe2?.context, ne2 = oe2?.gpuDevice, X2 = oe2?.deviceType, J2 = oe2?.powerPreference;
            p ? i.currentContext = p : ne2 ? i.currentContext = await i.webnnCreateMLContext(ne2) : i.currentContext = await i.webnnCreateMLContext({ deviceType: X2, powerPreference: J2 });
          } else i.currentContext = await i.webnnCreateMLContext();
          break;
        }
        d = await i._OrtCreateSession(s, f, l), i.webgpuOnCreateSession?.(d), d === 0 && $("Can't create a session."), i.jsepOnCreateSession?.(), i.currentContext && (i.webnnRegisterMLContext(d, i.currentContext), i.currentContext = void 0, i.shouldTransferToMLTensor = true);
        let [g, v] = yc(d), S = !!r?.enableGraphCapture, C = [], R = [], H = [], U2 = [], M2 = [];
        for (let O = 0; O < g; O++) {
          let [W2, oe2, p] = Os(d, O);
          W2 === 0 && $("Can't get an input name."), w.push(W2);
          let ne2 = i.UTF8ToString(W2);
          C.push(ne2), H.push(oe2 === 0 ? { name: ne2, isTensor: false } : { name: ne2, isTensor: true, type: or(oe2), shape: p });
        }
        for (let O = 0; O < v; O++) {
          let [W2, oe2, p] = Os(d, O + g);
          W2 === 0 && $("Can't get an output name."), T.push(W2);
          let ne2 = i.UTF8ToString(W2);
          R.push(ne2), U2.push(oe2 === 0 ? { name: ne2, isTensor: false } : { name: ne2, isTensor: true, type: or(oe2), shape: p });
          {
            if (S && r?.preferredOutputLocation === void 0) {
              M2.push("gpu-buffer");
              continue;
            }
            let X2 = typeof r?.preferredOutputLocation == "string" ? r.preferredOutputLocation : r?.preferredOutputLocation?.[ne2] ?? "cpu", J2 = i.webnnIsGraphOutput;
            if (X2 === "cpu" && J2 && J2(d, ne2)) {
              M2.push("ml-tensor-cpu-output");
              continue;
            }
            if (X2 !== "cpu" && X2 !== "cpu-pinned" && X2 !== "gpu-buffer" && X2 !== "ml-tensor") throw new Error(`Not supported preferred output location: ${X2}.`);
            if (S && X2 !== "gpu-buffer") throw new Error(`Not supported preferred output location: ${X2}. Only 'gpu-buffer' location is supported when enableGraphCapture is true.`);
            M2.push(X2);
          }
        }
        let Y2 = null;
        return M2.some((O) => O === "gpu-buffer" || O === "ml-tensor" || O === "ml-tensor-cpu-output") && (m = i._OrtCreateBinding(d), m === 0 && $("Can't create IO binding."), Y2 = { handle: m, outputPreferredLocations: M2, outputPreferredLocationsEncoded: M2.map((O) => O === "ml-tensor-cpu-output" ? "ml-tensor" : O).map((O) => an(O)) }), it.set(d, [d, w, T, Y2, S, false]), [d, C, R, H, U2];
      } catch (g) {
        throw w.forEach((v) => i._OrtFree(v)), T.forEach((v) => i._OrtFree(v)), m !== 0 && i._OrtReleaseBinding(m) !== 0 && $("Can't release IO binding."), d !== 0 && i._OrtReleaseSession(d) !== 0 && $("Can't release session."), g;
      } finally {
        i._free(s), l !== 0 && i._OrtReleaseSessionOptions(l) !== 0 && $("Can't release session options."), y.forEach((g) => i._free(g)), i.unmountExternalData?.();
      }
    }, Zt = (a) => {
      let r = z(), s = it.get(a);
      if (!s) throw new Error(`cannot release session. invalid session id: ${a}`);
      let [f, i, d, l, m] = s;
      l && (m && r._OrtClearBoundOutputs(l.handle) !== 0 && $("Can't clear bound outputs."), r._OrtReleaseBinding(l.handle) !== 0 && $("Can't release IO binding.")), r.jsepOnReleaseSession?.(a), r.webnnOnReleaseSession?.(a), r.webgpuOnReleaseSession?.(a), i.forEach((y) => r._OrtFree(y)), d.forEach((y) => r._OrtFree(y)), r._OrtReleaseSession(f) !== 0 && $("Can't release session."), it.delete(a);
    }, Bs = async (a, r, s, f, i, d, l = false) => {
      if (!a) {
        r.push(0);
        return;
      }
      let m = z(), y = m.PTR_SIZE, w = a[0], T = a[1], g = a[3], v = g, S, C;
      if (w === "string" && (g === "gpu-buffer" || g === "ml-tensor")) throw new Error("String tensor is not supported on GPU.");
      if (l && g !== "gpu-buffer") throw new Error(`External buffer must be provided for input/output index ${d} when enableGraphCapture is true.`);
      if (g === "gpu-buffer") {
        let U2 = a[2].gpuBuffer;
        C = mt(He(w), T);
        {
          let M2 = m.webgpuRegisterBuffer;
          if (!M2) throw new Error('Tensor location "gpu-buffer" is not supported without using WebGPU.');
          S = M2(U2, f);
        }
      } else if (g === "ml-tensor") {
        let U2 = a[2].mlTensor;
        C = mt(He(w), T);
        let M2 = m.webnnRegisterMLTensor;
        if (!M2) throw new Error('Tensor location "ml-tensor" is not supported without using WebNN.');
        S = M2(f, U2, He(w), T);
      } else {
        let U2 = a[2];
        if (Array.isArray(U2)) {
          C = y * U2.length, S = m._malloc(C), s.push(S);
          for (let M2 = 0; M2 < U2.length; M2++) {
            if (typeof U2[M2] != "string") throw new TypeError(`tensor data at index ${M2} is not a string`);
            m.setValue(S + M2 * y, be(U2[M2], s), "*");
          }
        } else {
          let M2 = m.webnnIsGraphInput, Y2 = m.webnnIsGraphOutput;
          if (w !== "string" && M2 && Y2) {
            let O = m.UTF8ToString(i);
            if (M2(f, O) || Y2(f, O)) {
              let W2 = He(w);
              C = mt(W2, T), v = "ml-tensor";
              let oe2 = m.webnnCreateTemporaryTensor, p = m.webnnUploadTensor;
              if (!oe2 || !p) throw new Error('Tensor location "ml-tensor" is not supported without using WebNN.');
              let ne2 = await oe2(f, W2, T);
              p(ne2, new Uint8Array(U2.buffer, U2.byteOffset, U2.byteLength)), S = ne2;
            } else C = U2.byteLength, S = m._malloc(C), s.push(S), m.HEAPU8.set(new Uint8Array(U2.buffer, U2.byteOffset, C), S);
          } else C = U2.byteLength, S = m._malloc(C), s.push(S), m.HEAPU8.set(new Uint8Array(U2.buffer, U2.byteOffset, C), S);
        }
      }
      let R = m.stackSave(), H = m.stackAlloc(4 * T.length);
      try {
        T.forEach((M2, Y2) => m.setValue(H + Y2 * y, M2, y === 4 ? "i32" : "i64"));
        let U2 = m._OrtCreateTensor(He(w), S, C, H, T.length, an(v));
        U2 === 0 && $(`Can't create tensor for input/output. session=${f}, index=${d}.`), r.push(U2);
      } finally {
        m.stackRestore(R);
      }
    }, Kt = async (a, r, s, f, i, d) => {
      let l = z(), m = l.PTR_SIZE, y = it.get(a);
      if (!y) throw new Error(`cannot run inference. invalid session id: ${a}`);
      let w = y[0], T = y[1], g = y[2], v = y[3], S = y[4], C = y[5], R = r.length, H = f.length, U2 = 0, M2 = [], Y2 = [], O = [], W2 = [], oe2 = [], p = l.stackSave(), ne2 = l.stackAlloc(R * m), X2 = l.stackAlloc(R * m), J2 = l.stackAlloc(H * m), Ue2 = l.stackAlloc(H * m);
      try {
        [U2, M2] = ds(d), $e("wasm prepareInputOutputTensor");
        for (let _ = 0; _ < R; _++) await Bs(s[_], Y2, W2, a, T[r[_]], r[_], S);
        for (let _ = 0; _ < H; _++) await Bs(i[_], O, W2, a, g[f[_]], R + f[_], S);
        ze("wasm prepareInputOutputTensor");
        for (let _ = 0; _ < R; _++) l.setValue(ne2 + _ * m, Y2[_], "*"), l.setValue(X2 + _ * m, T[r[_]], "*");
        for (let _ = 0; _ < H; _++) l.setValue(J2 + _ * m, O[_], "*"), l.setValue(Ue2 + _ * m, g[f[_]], "*");
        if (v && !C) {
          let { handle: _, outputPreferredLocations: ae2, outputPreferredLocationsEncoded: me2 } = v;
          if (T.length !== R) throw new Error(`input count from feeds (${R}) is expected to be always equal to model's input count (${T.length}).`);
          $e("wasm bindInputsOutputs");
          for (let q2 = 0; q2 < R; q2++) {
            let we2 = r[q2];
            await l._OrtBindInput(_, T[we2], Y2[q2]) !== 0 && $(`Can't bind input[${q2}] for session=${a}.`);
          }
          for (let q2 = 0; q2 < H; q2++) {
            let we2 = f[q2];
            i[q2]?.[3] ? (oe2.push(O[q2]), l._OrtBindOutput(_, g[we2], O[q2], 0) !== 0 && $(`Can't bind pre-allocated output[${q2}] for session=${a}.`)) : l._OrtBindOutput(_, g[we2], 0, me2[we2]) !== 0 && $(`Can't bind output[${q2}] to ${ae2[q2]} for session=${a}.`);
          }
          ze("wasm bindInputsOutputs"), it.set(a, [w, T, g, v, S, true]);
        }
        l.jsepOnRunStart?.(w), l.webnnOnRunStart?.(w);
        let Q2;
        v ? Q2 = await l._OrtRunWithBinding(w, v.handle, H, J2, U2) : Q2 = await l._OrtRun(w, X2, ne2, R, Ue2, H, J2, U2), Q2 !== 0 && $("failed to call OrtRun().");
        let x = [], A = [];
        $e("wasm ProcessOutputTensor");
        for (let _ = 0; _ < H; _++) {
          let ae2 = Number(l.getValue(J2 + _ * m, "*"));
          if (ae2 === O[_] || oe2.includes(O[_])) {
            x.push(i[_]), ae2 !== O[_] && l._OrtReleaseTensor(ae2) !== 0 && $("Can't release tensor.");
            continue;
          }
          let me2 = l.stackSave(), q2 = l.stackAlloc(4 * m), we2 = false, re, se2 = 0;
          try {
            l._OrtGetTensorData(ae2, q2, q2 + m, q2 + 2 * m, q2 + 3 * m) !== 0 && $(`Can't access output tensor data on index ${_}.`);
            let Te2 = m === 4 ? "i32" : "i64", Ye2 = Number(l.getValue(q2, Te2));
            se2 = l.getValue(q2 + m, "*");
            let bt2 = l.getValue(q2 + m * 2, "*"), wt2 = Number(l.getValue(q2 + m * 3, Te2)), Se2 = [];
            for (let ee = 0; ee < wt2; ee++) Se2.push(Number(l.getValue(bt2 + ee * m, Te2)));
            l._OrtFree(bt2) !== 0 && $("Can't free memory for tensor dims.");
            let Ae2 = Se2.reduce((ee, Z) => ee * Z, 1);
            re = or(Ye2);
            let Oe2 = v?.outputPreferredLocations[f[_]];
            if (re === "string") {
              if (Oe2 === "gpu-buffer" || Oe2 === "ml-tensor") throw new Error("String tensor is not supported on GPU.");
              let ee = [];
              for (let Z = 0; Z < Ae2; Z++) {
                let G = l.getValue(se2 + Z * m, "*"), V = l.getValue(se2 + (Z + 1) * m, "*"), qe2 = Z === Ae2 - 1 ? void 0 : V - G;
                ee.push(l.UTF8ToString(G, qe2));
              }
              x.push([re, Se2, ee, "cpu"]);
            } else if (Oe2 === "gpu-buffer" && Ae2 > 0) {
              let ee = l.webgpuGetBuffer;
              if (!ee) throw new Error('preferredLocation "gpu-buffer" is not supported without using WebGPU.');
              let Z = ee(se2), G = mt(Ye2, Ae2);
              if (G === void 0 || !ar(re)) throw new Error(`Unsupported data type: ${re}`);
              we2 = true;
              {
                l.webgpuRegisterBuffer(Z, a, se2);
                let V = l.webgpuCreateDownloader(Z, G, a);
                x.push([re, Se2, { gpuBuffer: Z, download: async () => {
                  let qe2 = await V();
                  return new (at(re))(qe2);
                }, dispose: () => {
                  l._OrtReleaseTensor(ae2) !== 0 && $("Can't release tensor.");
                } }, "gpu-buffer"]);
              }
            } else if (Oe2 === "ml-tensor" && Ae2 > 0) {
              let ee = l.webnnEnsureTensor, Z = l.webnnIsGraphInputOutputTypeSupported;
              if (!ee || !Z) throw new Error('preferredLocation "ml-tensor" is not supported without using WebNN.');
              if (mt(Ye2, Ae2) === void 0 || !sr(re)) throw new Error(`Unsupported data type: ${re}`);
              if (!Z(a, re, false)) throw new Error(`preferredLocation "ml-tensor" for ${re} output is not supported by current WebNN Context.`);
              let V = await ee(a, se2, Ye2, Se2, false);
              we2 = true, x.push([re, Se2, { mlTensor: V, download: l.webnnCreateMLTensorDownloader(se2, re), dispose: () => {
                l.webnnReleaseTensorId(se2), l._OrtReleaseTensor(ae2);
              } }, "ml-tensor"]);
            } else if (Oe2 === "ml-tensor-cpu-output" && Ae2 > 0) {
              let ee = l.webnnCreateMLTensorDownloader(se2, re)(), Z = x.length;
              we2 = true, A.push((async () => {
                let G = [Z, await ee];
                return l.webnnReleaseTensorId(se2), l._OrtReleaseTensor(ae2), G;
              })()), x.push([re, Se2, [], "cpu"]);
            } else {
              let ee = at(re), Z = new ee(Ae2);
              new Uint8Array(Z.buffer, Z.byteOffset, Z.byteLength).set(l.HEAPU8.subarray(se2, se2 + Z.byteLength)), x.push([re, Se2, Z, "cpu"]);
            }
          } finally {
            l.stackRestore(me2), re === "string" && se2 && l._free(se2), we2 || l._OrtReleaseTensor(ae2);
          }
        }
        v && !S && (l._OrtClearBoundOutputs(v.handle) !== 0 && $("Can't clear bound outputs."), it.set(a, [w, T, g, v, S, false]));
        for (let [_, ae2] of await Promise.all(A)) x[_][2] = ae2;
        return ze("wasm ProcessOutputTensor"), x;
      } finally {
        l.webnnOnRunEnd?.(w), l.stackRestore(p), s.forEach((Q2) => {
          Q2 && Q2[3] === "gpu-buffer" && l.webgpuUnregisterBuffer(Q2[2].gpuBuffer);
        }), i.forEach((Q2) => {
          Q2 && Q2[3] === "gpu-buffer" && l.webgpuUnregisterBuffer(Q2[2].gpuBuffer);
        }), Y2.forEach((Q2) => l._OrtReleaseTensor(Q2)), O.forEach((Q2) => l._OrtReleaseTensor(Q2)), W2.forEach((Q2) => l._free(Q2)), U2 !== 0 && l._OrtReleaseRunOptions(U2), M2.forEach((Q2) => l._free(Q2));
      }
    }, er = (a) => {
      let r = z(), s = it.get(a);
      if (!s) throw new Error("invalid session id");
      let f = s[0], i = r._OrtEndProfiling(f);
      i === 0 && $("Can't get an profile file name."), r._OrtFree(i);
    }, tr = (a) => {
      let r = [];
      for (let s of a) {
        let f = s[2];
        !Array.isArray(f) && "buffer" in f && r.push(f.buffer);
      }
      return r;
    };
  });
  var ut;
  var Ee;
  var Mt;
  var dr;
  var lr;
  var cr;
  var ln;
  var pn;
  var ht;
  var yt;
  var wc;
  var Ms;
  var Cs;
  var Us;
  var Ds;
  var Ps;
  var _s;
  var Rs;
  var mn = k(() => {
    "use strict";
    Ve();
    Kr();
    je();
    Yt();
    ut = () => !!K.wasm.proxy && typeof document < "u", Mt = false, dr = false, lr = false, pn = /* @__PURE__ */ new Map(), ht = (a, r) => {
      let s = pn.get(a);
      s ? s.push(r) : pn.set(a, [r]);
    }, yt = () => {
      if (Mt || !dr || lr || !Ee) throw new Error("worker not ready");
    }, wc = (a) => {
      switch (a.data.type) {
        case "init-wasm":
          Mt = false, a.data.err ? (lr = true, ln[1](a.data.err)) : (dr = true, ln[0]()), cr && (URL.revokeObjectURL(cr), cr = void 0);
          break;
        case "init-ep":
        case "copy-from":
        case "create":
        case "release":
        case "run":
        case "end-profiling": {
          let r = pn.get(a.data.type);
          a.data.err ? r.shift()[1](a.data.err) : r.shift()[0](a.data.out);
          break;
        }
        default:
      }
    }, Ms = async () => {
      if (!dr) {
        if (Mt) throw new Error("multiple calls to 'initWasm()' detected.");
        if (lr) throw new Error("previous call to 'initWasm()' failed.");
        if (Mt = true, ut()) return new Promise((a, r) => {
          Ee?.terminate(), us().then(([s, f]) => {
            try {
              Ee = f, Ee.onerror = (d) => r(d), Ee.onmessage = wc, ln = [a, r];
              let i = { type: "init-wasm", in: K };
              !i.in.wasm.wasmPaths && (s || tn) && (i.in.wasm.wasmPaths = { wasm: new URL("ort-wasm-simd-threaded.asyncify.wasm", import_meta.url).href }), Ee.postMessage(i), cr = s;
            } catch (i) {
              r(i);
            }
          }, r);
        });
        try {
          await qt(K.wasm), await Jt(K), dr = true;
        } catch (a) {
          throw lr = true, a;
        } finally {
          Mt = false;
        }
      }
    }, Cs = async (a) => {
      if (ut()) return yt(), new Promise((r, s) => {
        ht("init-ep", [r, s]);
        let f = { type: "init-ep", in: { epName: a, env: K } };
        Ee.postMessage(f);
      });
      await Xt(K, a);
    }, Us = async (a) => ut() ? (yt(), new Promise((r, s) => {
      ht("copy-from", [r, s]);
      let f = { type: "copy-from", in: { buffer: a } };
      Ee.postMessage(f, [a.buffer]);
    })) : xt(a), Ds = async (a, r) => {
      if (ut()) {
        if (r?.preferredOutputLocation) throw new Error('session option "preferredOutputLocation" is not supported for proxy.');
        return yt(), new Promise((s, f) => {
          ht("create", [s, f]);
          let i = { type: "create", in: { model: a, options: { ...r } } }, d = [];
          a instanceof Uint8Array && d.push(a.buffer), Ee.postMessage(i, d);
        });
      } else return Qt(a, r);
    }, Ps = async (a) => {
      if (ut()) return yt(), new Promise((r, s) => {
        ht("release", [r, s]);
        let f = { type: "release", in: a };
        Ee.postMessage(f);
      });
      Zt(a);
    }, _s = async (a, r, s, f, i, d) => {
      if (ut()) {
        if (s.some((l) => l[3] !== "cpu")) throw new Error("input tensor on GPU is not supported for proxy.");
        if (i.some((l) => l)) throw new Error("pre-allocated output tensor is not supported for proxy.");
        return yt(), new Promise((l, m) => {
          ht("run", [l, m]);
          let y = s, w = { type: "run", in: { sessionId: a, inputIndices: r, inputs: y, outputIndices: f, options: d } };
          Ee.postMessage(w, tr(y));
        });
      } else return Kt(a, r, s, f, i, d);
    }, Rs = async (a) => {
      if (ut()) return yt(), new Promise((r, s) => {
        ht("end-profiling", [r, s]);
        let f = { type: "end-profiling", in: a };
        Ee.postMessage(f);
      });
      er(a);
    };
  });
  var Ns;
  var gc;
  var pr;
  var ks = k(() => {
    "use strict";
    Ve();
    mn();
    st();
    Ht();
    sn();
    Ns = (a, r) => {
      switch (a.location) {
        case "cpu":
          return [a.type, a.dims, a.data, "cpu"];
        case "gpu-buffer":
          return [a.type, a.dims, { gpuBuffer: a.gpuBuffer }, "gpu-buffer"];
        case "ml-tensor":
          return [a.type, a.dims, { mlTensor: a.mlTensor }, "ml-tensor"];
        default:
          throw new Error(`invalid data location: ${a.location} for ${r()}`);
      }
    }, gc = (a) => {
      switch (a[3]) {
        case "cpu":
          return new Le(a[0], a[2], a[1]);
        case "gpu-buffer": {
          let r = a[0];
          if (!ar(r)) throw new Error(`not supported data type: ${r} for deserializing GPU tensor`);
          let { gpuBuffer: s, download: f, dispose: i } = a[2];
          return Le.fromGpuBuffer(s, { dataType: r, dims: a[1], download: f, dispose: i });
        }
        case "ml-tensor": {
          let r = a[0];
          if (!sr(r)) throw new Error(`not supported data type: ${r} for deserializing MLTensor tensor`);
          let { mlTensor: s, download: f, dispose: i } = a[2];
          return Le.fromMLTensor(s, { dataType: r, dims: a[1], download: f, dispose: i });
        }
        default:
          throw new Error(`invalid data location: ${a[3]}`);
      }
    }, pr = class {
      async fetchModelAndCopyToWasmMemory(r) {
        return Us(await Bt(r));
      }
      async loadModel(r, s) {
        tt();
        let f;
        typeof r == "string" ? f = await this.fetchModelAndCopyToWasmMemory(r) : f = r, [this.sessionId, this.inputNames, this.outputNames, this.inputMetadata, this.outputMetadata] = await Ds(f, s), rt();
      }
      async dispose() {
        return Ps(this.sessionId);
      }
      async run(r, s, f) {
        tt();
        let i = [], d = [];
        Object.entries(r).forEach((v) => {
          let S = v[0], C = v[1], R = this.inputNames.indexOf(S);
          if (R === -1) throw new Error(`invalid input '${S}'`);
          i.push(C), d.push(R);
        });
        let l = [], m = [];
        Object.entries(s).forEach((v) => {
          let S = v[0], C = v[1], R = this.outputNames.indexOf(S);
          if (R === -1) throw new Error(`invalid output '${S}'`);
          l.push(C), m.push(R);
        });
        let y = i.map((v, S) => Ns(v, () => `input "${this.inputNames[d[S]]}"`)), w = l.map((v, S) => v ? Ns(v, () => `output "${this.outputNames[m[S]]}"`) : null), T = await _s(this.sessionId, d, y, m, w, f), g = {};
        for (let v = 0; v < T.length; v++) g[this.outputNames[m[v]]] = l[v] ?? gc(T[v]);
        return rt(), g;
      }
      startProfiling() {
      }
      endProfiling() {
        Rs(this.sessionId);
      }
    };
  });
  var Fs = {};
  At(Fs, { OnnxruntimeWebAssemblyBackend: () => mr, initializeFlags: () => Ws, wasmBackend: () => Tc });
  var Ws;
  var mr;
  var Tc;
  var Gs = k(() => {
    "use strict";
    Ve();
    mn();
    ks();
    Ws = () => {
      (typeof K.wasm.initTimeout != "number" || K.wasm.initTimeout < 0) && (K.wasm.initTimeout = 0);
      let a = K.wasm.simd;
      if (typeof a != "boolean" && a !== void 0 && a !== "fixed" && a !== "relaxed" && (console.warn(`Property "env.wasm.simd" is set to unknown value "${a}". Reset it to \`false\` and ignore SIMD feature checking.`), K.wasm.simd = false), typeof K.wasm.proxy != "boolean" && (K.wasm.proxy = false), typeof K.wasm.trace != "boolean" && (K.wasm.trace = false), typeof K.wasm.numThreads != "number" || !Number.isInteger(K.wasm.numThreads) || K.wasm.numThreads <= 0) if (typeof self < "u" && !self.crossOriginIsolated) K.wasm.numThreads = 1;
      else {
        let r = typeof navigator > "u" ? Hr("node:os").cpus().length : navigator.hardwareConcurrency;
        K.wasm.numThreads = Math.min(4, Math.ceil((r || 1) / 2));
      }
    }, mr = class {
      async init(r) {
        Ws(), await Ms(), await Cs(r);
      }
      async createInferenceSessionHandler(r, s) {
        let f = new pr();
        return await f.loadModel(r, s), f;
      }
    }, Tc = new mr();
  });
  Ve();
  Ve();
  Ve();
  var Ja = "1.26.0-dev.20260416-b7804b056c";
  var gl = Zr;
  {
    let a = (Gs(), $t(Fs)).wasmBackend;
    Ke("webgpu", a, 5), Ke("webnn", a, 5), Ke("cpu", a, 10), Ke("wasm", a, 10);
  }
  Object.defineProperty(K.versions, "web", { value: Ja, enumerable: true });

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/version.js
  var version = "1.21.1";

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/env-impl.js
  var logLevelValue = "warning";
  var env = {
    wasm: {},
    webgl: {},
    webgpu: {},
    versions: { common: version },
    set logLevel(value) {
      if (value === void 0) {
        return;
      }
      if (typeof value !== "string" || ["verbose", "info", "warning", "error", "fatal"].indexOf(value) === -1) {
        throw new Error(`Unsupported logging level: ${value}`);
      }
      logLevelValue = value;
    },
    get logLevel() {
      return logLevelValue;
    }
  };
  Object.defineProperty(env, "logLevel", { enumerable: true });

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/tensor-conversion-impl.js
  var tensorToDataURL = (tensor, options) => {
    const canvas = typeof document !== "undefined" ? document.createElement("canvas") : new OffscreenCanvas(1, 1);
    canvas.width = tensor.dims[3];
    canvas.height = tensor.dims[2];
    const pixels2DContext = canvas.getContext("2d");
    if (pixels2DContext != null) {
      let width;
      let height;
      if (options?.tensorLayout !== void 0 && options.tensorLayout === "NHWC") {
        width = tensor.dims[2];
        height = tensor.dims[3];
      } else {
        width = tensor.dims[3];
        height = tensor.dims[2];
      }
      const inputformat = options?.format !== void 0 ? options.format : "RGB";
      const norm = options?.norm;
      let normMean;
      let normBias;
      if (norm === void 0 || norm.mean === void 0) {
        normMean = [255, 255, 255, 255];
      } else {
        if (typeof norm.mean === "number") {
          normMean = [norm.mean, norm.mean, norm.mean, norm.mean];
        } else {
          normMean = [norm.mean[0], norm.mean[1], norm.mean[2], 0];
          if (norm.mean[3] !== void 0) {
            normMean[3] = norm.mean[3];
          }
        }
      }
      if (norm === void 0 || norm.bias === void 0) {
        normBias = [0, 0, 0, 0];
      } else {
        if (typeof norm.bias === "number") {
          normBias = [norm.bias, norm.bias, norm.bias, norm.bias];
        } else {
          normBias = [norm.bias[0], norm.bias[1], norm.bias[2], 0];
          if (norm.bias[3] !== void 0) {
            normBias[3] = norm.bias[3];
          }
        }
      }
      const stride = height * width;
      let rTensorPointer = 0, gTensorPointer = stride, bTensorPointer = stride * 2, aTensorPointer = -1;
      if (inputformat === "RGBA") {
        rTensorPointer = 0;
        gTensorPointer = stride;
        bTensorPointer = stride * 2;
        aTensorPointer = stride * 3;
      } else if (inputformat === "RGB") {
        rTensorPointer = 0;
        gTensorPointer = stride;
        bTensorPointer = stride * 2;
      } else if (inputformat === "RBG") {
        rTensorPointer = 0;
        bTensorPointer = stride;
        gTensorPointer = stride * 2;
      }
      for (let i = 0; i < height; i++) {
        for (let j = 0; j < width; j++) {
          const R = (tensor.data[rTensorPointer++] - normBias[0]) * normMean[0];
          const G = (tensor.data[gTensorPointer++] - normBias[1]) * normMean[1];
          const B = (tensor.data[bTensorPointer++] - normBias[2]) * normMean[2];
          const A = aTensorPointer === -1 ? 255 : (tensor.data[aTensorPointer++] - normBias[3]) * normMean[3];
          pixels2DContext.fillStyle = "rgba(" + R + "," + G + "," + B + "," + A + ")";
          pixels2DContext.fillRect(j, i, 1, 1);
        }
      }
      if ("toDataURL" in canvas) {
        return canvas.toDataURL();
      } else {
        throw new Error("toDataURL is not supported");
      }
    } else {
      throw new Error("Can not access image data");
    }
  };
  var tensorToImageData = (tensor, options) => {
    const pixels2DContext = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : new OffscreenCanvas(1, 1).getContext("2d");
    let image;
    if (pixels2DContext != null) {
      let width;
      let height;
      let channels;
      if (options?.tensorLayout !== void 0 && options.tensorLayout === "NHWC") {
        width = tensor.dims[2];
        height = tensor.dims[1];
        channels = tensor.dims[3];
      } else {
        width = tensor.dims[3];
        height = tensor.dims[2];
        channels = tensor.dims[1];
      }
      const inputformat = options !== void 0 ? options.format !== void 0 ? options.format : "RGB" : "RGB";
      const norm = options?.norm;
      let normMean;
      let normBias;
      if (norm === void 0 || norm.mean === void 0) {
        normMean = [255, 255, 255, 255];
      } else {
        if (typeof norm.mean === "number") {
          normMean = [norm.mean, norm.mean, norm.mean, norm.mean];
        } else {
          normMean = [norm.mean[0], norm.mean[1], norm.mean[2], 255];
          if (norm.mean[3] !== void 0) {
            normMean[3] = norm.mean[3];
          }
        }
      }
      if (norm === void 0 || norm.bias === void 0) {
        normBias = [0, 0, 0, 0];
      } else {
        if (typeof norm.bias === "number") {
          normBias = [norm.bias, norm.bias, norm.bias, norm.bias];
        } else {
          normBias = [norm.bias[0], norm.bias[1], norm.bias[2], 0];
          if (norm.bias[3] !== void 0) {
            normBias[3] = norm.bias[3];
          }
        }
      }
      const stride = height * width;
      if (options !== void 0) {
        if (options.format !== void 0 && channels === 4 && options.format !== "RGBA" || channels === 3 && options.format !== "RGB" && options.format !== "BGR") {
          throw new Error("Tensor format doesn't match input tensor dims");
        }
      }
      const step = 4;
      let rImagePointer = 0, gImagePointer = 1, bImagePointer = 2, aImagePointer = 3;
      let rTensorPointer = 0, gTensorPointer = stride, bTensorPointer = stride * 2, aTensorPointer = -1;
      if (inputformat === "RGBA") {
        rTensorPointer = 0;
        gTensorPointer = stride;
        bTensorPointer = stride * 2;
        aTensorPointer = stride * 3;
      } else if (inputformat === "RGB") {
        rTensorPointer = 0;
        gTensorPointer = stride;
        bTensorPointer = stride * 2;
      } else if (inputformat === "RBG") {
        rTensorPointer = 0;
        bTensorPointer = stride;
        gTensorPointer = stride * 2;
      }
      image = pixels2DContext.createImageData(width, height);
      for (let i = 0; i < height * width; rImagePointer += step, gImagePointer += step, bImagePointer += step, aImagePointer += step, i++) {
        image.data[rImagePointer] = (tensor.data[rTensorPointer++] - normBias[0]) * normMean[0];
        image.data[gImagePointer] = (tensor.data[gTensorPointer++] - normBias[1]) * normMean[1];
        image.data[bImagePointer] = (tensor.data[bTensorPointer++] - normBias[2]) * normMean[2];
        image.data[aImagePointer] = aTensorPointer === -1 ? 255 : (tensor.data[aTensorPointer++] - normBias[3]) * normMean[3];
      }
    } else {
      throw new Error("Can not access image data");
    }
    return image;
  };

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/tensor-factory-impl.js
  var bufferToTensor = (buffer, options) => {
    if (buffer === void 0) {
      throw new Error("Image buffer must be defined");
    }
    if (options.height === void 0 || options.width === void 0) {
      throw new Error("Image height and width must be defined");
    }
    if (options.tensorLayout === "NHWC") {
      throw new Error("NHWC Tensor layout is not supported yet");
    }
    const { height, width } = options;
    const norm = options.norm ?? { mean: 255, bias: 0 };
    let normMean;
    let normBias;
    if (typeof norm.mean === "number") {
      normMean = [norm.mean, norm.mean, norm.mean, norm.mean];
    } else {
      normMean = [norm.mean[0], norm.mean[1], norm.mean[2], norm.mean[3] ?? 255];
    }
    if (typeof norm.bias === "number") {
      normBias = [norm.bias, norm.bias, norm.bias, norm.bias];
    } else {
      normBias = [norm.bias[0], norm.bias[1], norm.bias[2], norm.bias[3] ?? 0];
    }
    const inputformat = options.format !== void 0 ? options.format : "RGBA";
    const outputformat = options.tensorFormat !== void 0 ? options.tensorFormat !== void 0 ? options.tensorFormat : "RGB" : "RGB";
    const stride = height * width;
    const float32Data = outputformat === "RGBA" ? new Float32Array(stride * 4) : new Float32Array(stride * 3);
    let step = 4, rImagePointer = 0, gImagePointer = 1, bImagePointer = 2, aImagePointer = 3;
    let rTensorPointer = 0, gTensorPointer = stride, bTensorPointer = stride * 2, aTensorPointer = -1;
    if (inputformat === "RGB") {
      step = 3;
      rImagePointer = 0;
      gImagePointer = 1;
      bImagePointer = 2;
      aImagePointer = -1;
    }
    if (outputformat === "RGBA") {
      aTensorPointer = stride * 3;
    } else if (outputformat === "RBG") {
      rTensorPointer = 0;
      bTensorPointer = stride;
      gTensorPointer = stride * 2;
    } else if (outputformat === "BGR") {
      bTensorPointer = 0;
      gTensorPointer = stride;
      rTensorPointer = stride * 2;
    }
    for (let i = 0; i < stride; i++, rImagePointer += step, bImagePointer += step, gImagePointer += step, aImagePointer += step) {
      float32Data[rTensorPointer++] = (buffer[rImagePointer] + normBias[0]) / normMean[0];
      float32Data[gTensorPointer++] = (buffer[gImagePointer] + normBias[1]) / normMean[1];
      float32Data[bTensorPointer++] = (buffer[bImagePointer] + normBias[2]) / normMean[2];
      if (aTensorPointer !== -1 && aImagePointer !== -1) {
        float32Data[aTensorPointer++] = (buffer[aImagePointer] + normBias[3]) / normMean[3];
      }
    }
    const outputTensor = outputformat === "RGBA" ? new Tensor("float32", float32Data, [1, 4, height, width]) : new Tensor("float32", float32Data, [1, 3, height, width]);
    return outputTensor;
  };
  var tensorFromImage = async (image, options) => {
    const isHTMLImageEle = typeof HTMLImageElement !== "undefined" && image instanceof HTMLImageElement;
    const isImageDataEle = typeof ImageData !== "undefined" && image instanceof ImageData;
    const isImageBitmap = typeof ImageBitmap !== "undefined" && image instanceof ImageBitmap;
    const isString = typeof image === "string";
    let data;
    let bufferToTensorOptions = options ?? {};
    const createCanvas = () => {
      if (typeof document !== "undefined") {
        return document.createElement("canvas");
      } else if (typeof OffscreenCanvas !== "undefined") {
        return new OffscreenCanvas(1, 1);
      } else {
        throw new Error("Canvas is not supported");
      }
    };
    const createCanvasContext = (canvas) => {
      if (typeof HTMLCanvasElement !== "undefined" && canvas instanceof HTMLCanvasElement) {
        return canvas.getContext("2d");
      } else if (canvas instanceof OffscreenCanvas) {
        return canvas.getContext("2d");
      } else {
        return null;
      }
    };
    if (isHTMLImageEle) {
      const canvas = createCanvas();
      canvas.width = image.width;
      canvas.height = image.height;
      const pixels2DContext = createCanvasContext(canvas);
      if (pixels2DContext != null) {
        let height = image.height;
        let width = image.width;
        if (options !== void 0 && options.resizedHeight !== void 0 && options.resizedWidth !== void 0) {
          height = options.resizedHeight;
          width = options.resizedWidth;
        }
        if (options !== void 0) {
          bufferToTensorOptions = options;
          if (options.tensorFormat !== void 0) {
            throw new Error("Image input config format must be RGBA for HTMLImageElement");
          } else {
            bufferToTensorOptions.tensorFormat = "RGBA";
          }
          bufferToTensorOptions.height = height;
          bufferToTensorOptions.width = width;
        } else {
          bufferToTensorOptions.tensorFormat = "RGBA";
          bufferToTensorOptions.height = height;
          bufferToTensorOptions.width = width;
        }
        pixels2DContext.drawImage(image, 0, 0);
        data = pixels2DContext.getImageData(0, 0, width, height).data;
      } else {
        throw new Error("Can not access image data");
      }
    } else if (isImageDataEle) {
      let height;
      let width;
      if (options !== void 0 && options.resizedWidth !== void 0 && options.resizedHeight !== void 0) {
        height = options.resizedHeight;
        width = options.resizedWidth;
      } else {
        height = image.height;
        width = image.width;
      }
      if (options !== void 0) {
        bufferToTensorOptions = options;
      }
      bufferToTensorOptions.format = "RGBA";
      bufferToTensorOptions.height = height;
      bufferToTensorOptions.width = width;
      if (options !== void 0) {
        const tempCanvas = createCanvas();
        tempCanvas.width = width;
        tempCanvas.height = height;
        const pixels2DContext = createCanvasContext(tempCanvas);
        if (pixels2DContext != null) {
          pixels2DContext.putImageData(image, 0, 0);
          data = pixels2DContext.getImageData(0, 0, width, height).data;
        } else {
          throw new Error("Can not access image data");
        }
      } else {
        data = image.data;
      }
    } else if (isImageBitmap) {
      if (options === void 0) {
        throw new Error("Please provide image config with format for Imagebitmap");
      }
      const canvas = createCanvas();
      canvas.width = image.width;
      canvas.height = image.height;
      const pixels2DContext = createCanvasContext(canvas);
      if (pixels2DContext != null) {
        const height = image.height;
        const width = image.width;
        pixels2DContext.drawImage(image, 0, 0, width, height);
        data = pixels2DContext.getImageData(0, 0, width, height).data;
        bufferToTensorOptions.height = height;
        bufferToTensorOptions.width = width;
        return bufferToTensor(data, bufferToTensorOptions);
      } else {
        throw new Error("Can not access image data");
      }
    } else if (isString) {
      return new Promise((resolve, reject) => {
        const canvas = createCanvas();
        const context = createCanvasContext(canvas);
        if (!image || !context) {
          return reject();
        }
        const newImage = new Image();
        newImage.crossOrigin = "Anonymous";
        newImage.src = image;
        newImage.onload = () => {
          canvas.width = newImage.width;
          canvas.height = newImage.height;
          context.drawImage(newImage, 0, 0, canvas.width, canvas.height);
          const img = context.getImageData(0, 0, canvas.width, canvas.height);
          bufferToTensorOptions.height = canvas.height;
          bufferToTensorOptions.width = canvas.width;
          resolve(bufferToTensor(img.data, bufferToTensorOptions));
        };
      });
    } else {
      throw new Error("Input data provided is not supported - aborted tensor creation");
    }
    if (data !== void 0) {
      return bufferToTensor(data, bufferToTensorOptions);
    } else {
      throw new Error("Input data provided is not supported - aborted tensor creation");
    }
  };
  var tensorFromTexture = (texture, options) => {
    const { width, height, download, dispose } = options;
    const dims = [1, height, width, 4];
    return new Tensor({ location: "texture", type: "float32", texture, dims, download, dispose });
  };
  var tensorFromGpuBuffer = (gpuBuffer, options) => {
    const { dataType, dims, download, dispose } = options;
    return new Tensor({ location: "gpu-buffer", type: dataType ?? "float32", gpuBuffer, dims, download, dispose });
  };
  var tensorFromMLTensor = (mlTensor, options) => {
    const { dataType, dims, download, dispose } = options;
    return new Tensor({ location: "ml-tensor", type: dataType ?? "float32", mlTensor, dims, download, dispose });
  };
  var tensorFromPinnedBuffer = (type, buffer, dims) => new Tensor({ location: "cpu-pinned", type, data: buffer, dims: dims ?? [buffer.length] });

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/tensor-impl-type-mapping.js
  var NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP = /* @__PURE__ */ new Map([
    ["float32", Float32Array],
    ["uint8", Uint8Array],
    ["int8", Int8Array],
    ["uint16", Uint16Array],
    ["int16", Int16Array],
    ["int32", Int32Array],
    ["bool", Uint8Array],
    ["float64", Float64Array],
    ["uint32", Uint32Array],
    ["int4", Uint8Array],
    ["uint4", Uint8Array]
  ]);
  var NUMERIC_TENSOR_TYPEDARRAY_TO_TYPE_MAP = /* @__PURE__ */ new Map([
    [Float32Array, "float32"],
    [Uint8Array, "uint8"],
    [Int8Array, "int8"],
    [Uint16Array, "uint16"],
    [Int16Array, "int16"],
    [Int32Array, "int32"],
    [Float64Array, "float64"],
    [Uint32Array, "uint32"]
  ]);
  var isTypedArrayChecked = false;
  var checkTypedArray = () => {
    if (!isTypedArrayChecked) {
      isTypedArrayChecked = true;
      const isBigInt64ArrayAvailable = typeof BigInt64Array !== "undefined" && BigInt64Array.from;
      const isBigUint64ArrayAvailable = typeof BigUint64Array !== "undefined" && BigUint64Array.from;
      const Float16Array2 = globalThis.Float16Array;
      const isFloat16ArrayAvailable = typeof Float16Array2 !== "undefined" && Float16Array2.from;
      if (isBigInt64ArrayAvailable) {
        NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP.set("int64", BigInt64Array);
        NUMERIC_TENSOR_TYPEDARRAY_TO_TYPE_MAP.set(BigInt64Array, "int64");
      }
      if (isBigUint64ArrayAvailable) {
        NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP.set("uint64", BigUint64Array);
        NUMERIC_TENSOR_TYPEDARRAY_TO_TYPE_MAP.set(BigUint64Array, "uint64");
      }
      if (isFloat16ArrayAvailable) {
        NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP.set("float16", Float16Array2);
        NUMERIC_TENSOR_TYPEDARRAY_TO_TYPE_MAP.set(Float16Array2, "float16");
      } else {
        NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP.set("float16", Uint16Array);
      }
    }
  };

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/tensor-utils-impl.js
  var calculateSize = (dims) => {
    let size = 1;
    for (let i = 0; i < dims.length; i++) {
      const dim = dims[i];
      if (typeof dim !== "number" || !Number.isSafeInteger(dim)) {
        throw new TypeError(`dims[${i}] must be an integer, got: ${dim}`);
      }
      if (dim < 0) {
        throw new RangeError(`dims[${i}] must be a non-negative integer, got: ${dim}`);
      }
      size *= dim;
    }
    return size;
  };
  var tensorReshape = (tensor, dims) => {
    switch (tensor.location) {
      case "cpu":
        return new Tensor(tensor.type, tensor.data, dims);
      case "cpu-pinned":
        return new Tensor({
          location: "cpu-pinned",
          data: tensor.data,
          type: tensor.type,
          dims
        });
      case "texture":
        return new Tensor({
          location: "texture",
          texture: tensor.texture,
          type: tensor.type,
          dims
        });
      case "gpu-buffer":
        return new Tensor({
          location: "gpu-buffer",
          gpuBuffer: tensor.gpuBuffer,
          type: tensor.type,
          dims
        });
      case "ml-tensor":
        return new Tensor({
          location: "ml-tensor",
          mlTensor: tensor.mlTensor,
          type: tensor.type,
          dims
        });
      default:
        throw new Error(`tensorReshape: tensor location ${tensor.location} is not supported`);
    }
  };

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/tensor-impl.js
  var Tensor = class {
    /**
     * implementation.
     */
    constructor(arg0, arg1, arg2) {
      checkTypedArray();
      let type;
      let dims;
      if (typeof arg0 === "object" && "location" in arg0) {
        this.dataLocation = arg0.location;
        type = arg0.type;
        dims = arg0.dims;
        switch (arg0.location) {
          case "cpu-pinned": {
            const expectedTypedArrayConstructor = NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP.get(type);
            if (!expectedTypedArrayConstructor) {
              throw new TypeError(`unsupported type "${type}" to create tensor from pinned buffer`);
            }
            if (!(arg0.data instanceof expectedTypedArrayConstructor)) {
              throw new TypeError(`buffer should be of type ${expectedTypedArrayConstructor.name}`);
            }
            this.cpuData = arg0.data;
            break;
          }
          case "texture": {
            if (type !== "float32") {
              throw new TypeError(`unsupported type "${type}" to create tensor from texture`);
            }
            this.gpuTextureData = arg0.texture;
            this.downloader = arg0.download;
            this.disposer = arg0.dispose;
            break;
          }
          case "gpu-buffer": {
            if (type !== "float32" && type !== "float16" && type !== "int32" && type !== "int64" && type !== "uint32" && type !== "uint8" && type !== "bool" && type !== "uint4" && type !== "int4") {
              throw new TypeError(`unsupported type "${type}" to create tensor from gpu buffer`);
            }
            this.gpuBufferData = arg0.gpuBuffer;
            this.downloader = arg0.download;
            this.disposer = arg0.dispose;
            break;
          }
          case "ml-tensor": {
            if (type !== "float32" && type !== "float16" && type !== "int32" && type !== "int64" && type !== "uint32" && type !== "uint64" && type !== "int8" && type !== "uint8" && type !== "bool" && type !== "uint4" && type !== "int4") {
              throw new TypeError(`unsupported type "${type}" to create tensor from MLTensor`);
            }
            this.mlTensorData = arg0.mlTensor;
            this.downloader = arg0.download;
            this.disposer = arg0.dispose;
            break;
          }
          default:
            throw new Error(`Tensor constructor: unsupported location '${this.dataLocation}'`);
        }
      } else {
        let data;
        let maybeDims;
        if (typeof arg0 === "string") {
          type = arg0;
          maybeDims = arg2;
          if (arg0 === "string") {
            if (!Array.isArray(arg1)) {
              throw new TypeError("A string tensor's data must be a string array.");
            }
            data = arg1;
          } else {
            const typedArrayConstructor = NUMERIC_TENSOR_TYPE_TO_TYPEDARRAY_MAP.get(arg0);
            if (typedArrayConstructor === void 0) {
              throw new TypeError(`Unsupported tensor type: ${arg0}.`);
            }
            if (Array.isArray(arg1)) {
              if (arg0 === "float16" && typedArrayConstructor === Uint16Array || arg0 === "uint4" || arg0 === "int4") {
                throw new TypeError(`Creating a ${arg0} tensor from number array is not supported. Please use ${typedArrayConstructor.name} as data.`);
              } else if (arg0 === "uint64" || arg0 === "int64") {
                data = typedArrayConstructor.from(arg1, BigInt);
              } else {
                data = typedArrayConstructor.from(arg1);
              }
            } else if (arg1 instanceof typedArrayConstructor) {
              data = arg1;
            } else if (arg1 instanceof Uint8ClampedArray) {
              if (arg0 === "uint8") {
                data = Uint8Array.from(arg1);
              } else {
                throw new TypeError(`A Uint8ClampedArray tensor's data must be type of uint8`);
              }
            } else if (arg0 === "float16" && arg1 instanceof Uint16Array && typedArrayConstructor !== Uint16Array) {
              data = new globalThis.Float16Array(arg1.buffer, arg1.byteOffset, arg1.length);
            } else {
              throw new TypeError(`A ${type} tensor's data must be type of ${typedArrayConstructor}`);
            }
          }
        } else {
          maybeDims = arg1;
          if (Array.isArray(arg0)) {
            if (arg0.length === 0) {
              throw new TypeError("Tensor type cannot be inferred from an empty array.");
            }
            const firstElementType = typeof arg0[0];
            if (firstElementType === "string") {
              type = "string";
              data = arg0;
            } else if (firstElementType === "boolean") {
              type = "bool";
              data = Uint8Array.from(arg0);
            } else {
              throw new TypeError(`Invalid element type of data array: ${firstElementType}.`);
            }
          } else if (arg0 instanceof Uint8ClampedArray) {
            type = "uint8";
            data = Uint8Array.from(arg0);
          } else {
            const mappedType = NUMERIC_TENSOR_TYPEDARRAY_TO_TYPE_MAP.get(arg0.constructor);
            if (mappedType === void 0) {
              throw new TypeError(`Unsupported type for tensor data: ${arg0.constructor}.`);
            }
            type = mappedType;
            data = arg0;
          }
        }
        if (maybeDims === void 0) {
          maybeDims = [data.length];
        } else if (!Array.isArray(maybeDims)) {
          throw new TypeError("A tensor's dims must be a number array");
        }
        dims = maybeDims;
        this.cpuData = data;
        this.dataLocation = "cpu";
      }
      const size = calculateSize(dims);
      if (this.cpuData && size !== this.cpuData.length) {
        if ((type === "uint4" || type === "int4") && Math.ceil(size / 2) === this.cpuData.length) {
        } else {
          throw new Error(`Tensor's size(${size}) does not match data length(${this.cpuData.length}).`);
        }
      }
      this.type = type;
      this.dims = dims;
      this.size = size;
    }
    // #endregion
    // #region factory
    static async fromImage(image, options) {
      return tensorFromImage(image, options);
    }
    static fromTexture(texture, options) {
      return tensorFromTexture(texture, options);
    }
    static fromGpuBuffer(gpuBuffer, options) {
      return tensorFromGpuBuffer(gpuBuffer, options);
    }
    static fromMLTensor(mlTensor, options) {
      return tensorFromMLTensor(mlTensor, options);
    }
    static fromPinnedBuffer(type, buffer, dims) {
      return tensorFromPinnedBuffer(type, buffer, dims);
    }
    // #endregion
    // #region conversions
    toDataURL(options) {
      return tensorToDataURL(this, options);
    }
    toImageData(options) {
      return tensorToImageData(this, options);
    }
    // #endregion
    // #region properties
    get data() {
      this.ensureValid();
      if (!this.cpuData) {
        throw new Error("The data is not on CPU. Use `getData()` to download GPU data to CPU, or use `texture` or `gpuBuffer` property to access the GPU data directly.");
      }
      return this.cpuData;
    }
    get location() {
      return this.dataLocation;
    }
    get texture() {
      this.ensureValid();
      if (!this.gpuTextureData) {
        throw new Error("The data is not stored as a WebGL texture.");
      }
      return this.gpuTextureData;
    }
    get gpuBuffer() {
      this.ensureValid();
      if (!this.gpuBufferData) {
        throw new Error("The data is not stored as a WebGPU buffer.");
      }
      return this.gpuBufferData;
    }
    get mlTensor() {
      this.ensureValid();
      if (!this.mlTensorData) {
        throw new Error("The data is not stored as a WebNN MLTensor.");
      }
      return this.mlTensorData;
    }
    // #endregion
    // #region methods
    async getData(releaseData) {
      this.ensureValid();
      switch (this.dataLocation) {
        case "cpu":
        case "cpu-pinned":
          return this.data;
        case "texture":
        case "gpu-buffer":
        case "ml-tensor": {
          if (!this.downloader) {
            throw new Error("The current tensor is not created with a specified data downloader.");
          }
          if (this.isDownloading) {
            throw new Error("The current tensor is being downloaded.");
          }
          try {
            this.isDownloading = true;
            const data = await this.downloader();
            this.downloader = void 0;
            this.dataLocation = "cpu";
            this.cpuData = data;
            if (releaseData && this.disposer) {
              this.disposer();
              this.disposer = void 0;
            }
            return data;
          } finally {
            this.isDownloading = false;
          }
        }
        default:
          throw new Error(`cannot get data from location: ${this.dataLocation}`);
      }
    }
    dispose() {
      if (this.isDownloading) {
        throw new Error("The current tensor is being downloaded.");
      }
      if (this.disposer) {
        this.disposer();
        this.disposer = void 0;
      }
      this.cpuData = void 0;
      this.gpuTextureData = void 0;
      this.gpuBufferData = void 0;
      this.mlTensorData = void 0;
      this.downloader = void 0;
      this.isDownloading = void 0;
      this.dataLocation = "none";
    }
    // #endregion
    // #region tensor utilities
    ensureValid() {
      if (this.dataLocation === "none") {
        throw new Error("The tensor is disposed.");
      }
    }
    reshape(dims) {
      this.ensureValid();
      if (this.downloader || this.disposer) {
        throw new Error("Cannot reshape a tensor that owns GPU resource.");
      }
      return tensorReshape(this, dims);
    }
  };

  // ../../../../../../../../../../private/tmp/autoeditor-vision-install.e6mBJn/creative-runtime.with-node-vision/node_modules/onnxruntime-common/dist/esm/tensor.js
  var Tensor2 = Tensor;

  // ../../desktop/helper/vision/transformers.web.min.js
  var import_meta2 = {};
  var Lk = Object.defineProperty;
  var Os2 = (t6, e) => {
    for (var s in e) Lk(t6, s, { get: e[s], enumerable: true });
  };
  var Fe = {};
  var Ye = {};
  var Dy = {};
  var $k = "4.2.0";
  var Bc = typeof self < "u";
  var Is2 = !Wy(Fe);
  var By = !Wy(Ye);
  var ra = Bc && "caches" in self;
  var Fk = typeof globalThis.Deno < "u";
  var BM = typeof globalThis.Bun < "u";
  var oa = Fk && ra && !Is2;
  var Uy = typeof process < "u";
  var Gy = Uy && process?.release?.name === "node" && !oa;
  var Uc = typeof window < "u" && typeof window.document < "u";
  var Gc = Bc && ["DedicatedWorkerGlobalScope", "ServiceWorkerGlobalScope", "SharedWorkerGlobalScope"].includes(self.constructor?.name);
  var Rk = Uc || Gc || oa;
  var Dk = Gy || typeof navigator < "u" && "gpu" in navigator;
  var qk = typeof navigator < "u" && "ml" in navigator;
  var jk = typeof crypto < "u" && typeof crypto.getRandomValues == "function";
  var Bk = typeof chrome < "u" && typeof chrome.runtime < "u" && typeof chrome.runtime.id == "string";
  var Uk = typeof ServiceWorkerGlobalScope < "u" && Bc && self instanceof ServiceWorkerGlobalScope;
  var Gk = () => {
    if (typeof navigator > "u") return false;
    let t6 = navigator.userAgent, s = (navigator.vendor || "").indexOf("Apple") > -1, r = !t6.match(/CriOS|FxiOS|EdgiOS|OPiOS|mercury|brave/i) && !t6.includes("Chrome") && !t6.includes("Android");
    return s && r;
  };
  var Wk = Gk();
  var K2 = Object.freeze({ IS_BROWSER_ENV: Uc, IS_WEBWORKER_ENV: Gc, IS_WEB_ENV: Rk, IS_SERVICE_WORKER_ENV: Uk, IS_DENO_WEB_RUNTIME: oa, IS_WEB_CACHE_AVAILABLE: ra, IS_WEBGPU_AVAILABLE: Dk, IS_WEBNN_AVAILABLE: qk, IS_SAFARI: Wk, IS_PROCESS_AVAILABLE: Uy, IS_NODE_ENV: Gy, IS_FS_AVAILABLE: Is2, IS_PATH_AVAILABLE: By, IS_CRYPTO_AVAILABLE: jk, IS_CHROME_AVAILABLE: Bk });
  var Wc = Is2 && By;
  var na = "./";
  if (Wc) {
    let t6 = Object(import_meta2).url;
    t6 ? na = Ye.dirname(Ye.dirname(Dy.fileURLToPath(t6))) : typeof __dirname < "u" && (na = Ye.dirname(__dirname));
  }
  var Vk = Wc ? Ye.join(na, "/.cache/") : null;
  var qy = "/models/";
  var Hk = Wc ? Ye.join(na, qy) : qy;
  var Kk = typeof globalThis.fetch == "function" ? globalThis.fetch.bind(globalThis) : void 0;
  var Ge = Object.freeze({ DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, NONE: 50 });
  var jy = Ge.WARNING;
  var J = { version: $k, backends: { onnx: {} }, get logLevel() {
    return jy;
  }, set logLevel(t6) {
    jy = t6, J.backends.onnx?.setLogLevel?.(t6);
  }, allowRemoteModels: true, remoteHost: "https://huggingface.co/", remotePathTemplate: "{model}/resolve/{revision}/", allowLocalModels: !(Uc || Gc || oa), localModelPath: Hk, useFS: Is2, useBrowserCache: ra, useFSCache: Is2, cacheDir: Vk, useCustomCache: false, customCache: null, useWasmCache: ra || Is2, cacheKey: "transformers-cache", experimental_useCrossOriginStorage: false, fetch: Kk };
  function Wy(t6) {
    return Object.keys(t6).length === 0;
  }
  var xe = class {
    constructor() {
      let t6 = function(...e) {
        return t6._call(...e);
      };
      return Object.setPrototypeOf(t6, new.target.prototype);
    }
    _call(...t6) {
      throw Error("Must implement _call method in subclass");
    }
  };
  function _t(t6, e) {
    t6 && t6(e);
  }
  var ts2 = class extends xe {
    constructor(e, s) {
      super(), this.callback = e, this.files_loading = s;
    }
    _call(e) {
      if (e.status === "progress") {
        this.files_loading[e.file] = { loaded: e.loaded, total: e.total };
        let s = Object.values(this.files_loading).reduce((o, i) => o + i.loaded, 0), r = Object.values(this.files_loading).reduce((o, i) => o + i.total, 0), n = r > 0 ? s / r * 100 : 0;
        this.callback({ status: "progress_total", name: e.name, progress: n, loaded: s, total: r, files: structuredClone(this.files_loading) });
      }
      this.callback(e);
    }
  };
  function Vy(t6) {
    return Number.isInteger(t6) || typeof t6 == "bigint";
  }
  function Vc(t6) {
    return t6 == null || t6 === -1;
  }
  function Hc(t6) {
    let e = [], s = t6;
    for (; Array.isArray(s); ) e.push(s.length), s = s[0];
    return e;
  }
  function Re(...t6) {
    return Array.prototype.concat.apply([], t6);
  }
  function Hy(...t6) {
    return t6.reduce((e, s) => e.flatMap((r) => s.map((n) => [r, n])));
  }
  function zs(t6, e) {
    return Math.abs((t6 + e) % (2 * e) - e);
  }
  function we(t6, e) {
    return Object.assign({}, ...e.map((s) => {
      if (t6[s] !== void 0) return { [s]: t6[s] };
    }));
  }
  function Ky(t6, e) {
    let s = 0;
    for (let r of t6) r === e && ++s;
    return s;
  }
  var F = { error(...t6) {
    J.logLevel <= Ge.ERROR && console.error(...t6);
  }, warn(...t6) {
    J.logLevel <= Ge.WARNING && console.warn(...t6);
  }, info(...t6) {
    J.logLevel <= Ge.INFO && console.log(...t6);
  }, debug(...t6) {
    J.logLevel <= Ge.DEBUG && console.log(...t6);
  }, log(...t6) {
    this.info(...t6);
  } };
  var Xk = class {
    constructor(t6) {
      this.trie = this._build_trie(t6);
    }
    _build_trie(t6) {
      let e = /* @__PURE__ */ Object.create(null);
      for (let s of t6) {
        let r = e;
        for (let n = 0; n < s.length; ++n) {
          let o = s[n];
          r = r[o] ??= /* @__PURE__ */ Object.create(null);
        }
        r.end = s;
      }
      return e;
    }
    split(t6) {
      let e = [], s = t6.length, r = 0, n = 0;
      for (; n < s; ) {
        let o = this.trie, i = null, a = n;
        for (; a < s && (o = o[t6[a]]); ) o.end && (i = o.end), ++a;
        i ? (n > r && e.push(t6.slice(r, n)), e.push(i), n += i.length, r = n) : ++n;
      }
      return r < s && e.push(t6.slice(r)), e;
    }
  };
  var Xy = Xk;
  var Qk = class {
    constructor(t6) {
      this.content = t6.content, this.id = t6.id, this.single_word = t6.single_word ?? false, this.lstrip = t6.lstrip ?? false, this.rstrip = t6.rstrip ?? false, this.special = t6.special ?? false, this.normalized = t6.normalized ?? !this.special;
    }
  };
  var Yk = Qk;
  var s0 = (() => {
    let t6 = [...Array.from({ length: 94 }, (n, o) => o + 33), ...Array.from({ length: 12 }, (n, o) => o + 161), ...Array.from({ length: 82 }, (n, o) => o + 174)], e = t6.slice(), s = 0;
    for (let n = 0; n < 256; ++n) t6.includes(n) || (t6.push(n), e.push(256 + s), s += 1);
    let r = e.map((n) => String.fromCharCode(n));
    return Object.fromEntries(t6.map((n, o) => [n, r[o]]));
  })();
  var Jk = (t6) => Object.fromEntries(Object.entries(t6).map(([e, s]) => [s, e]));
  var Zk = Jk(s0);
  var Qy = ".,!?\u2026\u3002\uFF0C\u3001\u0964\u06D4\u060C";
  var e1 = /* @__PURE__ */ new Map([["(?i:'s|'t|'re|'ve|'m|'ll|'d)", "(?:'([sS]|[tT]|[rR][eE]|[vV][eE]|[mM]|[lL][lL]|[dD]))"], ["(?i:[sdmt]|ll|ve|re)", "(?:[sS]|[dD]|[mM]|[tT]|[lL][lL]|[vV][eE]|[rR][eE])"], ["[^\\r\\n\\p{L}\\p{N}]?+", "[^\\r\\n\\p{L}\\p{N}]?"], ["[^\\s\\p{L}\\p{N}]++", "[^\\s\\p{L}\\p{N}]+"], ["(?>\\p{Nd}{510})", "(?:\\p{Nd}{510})"], ["\\p{Nd}{3}+", "(?:\\p{Nd}{3})+"], ["\\G", ""], [` ?[^(\\s|[${Qy}])]+`, ` ?[^\\s${Qy}]+`]]);
  var ia = "\\p{P}\\u0021-\\u002F\\u003A-\\u0040\\u005B-\\u0060\\u007B-\\u007E";
  var Xc = (t6) => t6.replace(/ \./g, ".").replace(/ \?/g, "?").replace(/ \!/g, "!").replace(/ ,/g, ",").replace(/ \' /g, "'").replace(/ n't/g, "n't").replace(/ 'm/g, "'m").replace(/ 's/g, "'s").replace(/ 've/g, "'ve").replace(/ 're/g, "'re");
  var aa = (t6, e = true) => {
    if (t6.Regex !== void 0) {
      let s = t6.Regex.replace(/\\([#&~])/g, "$1");
      s = s.replace(/\\A/g, "^").replace(/\\z/g, "$").replace(/\\Z/g, "(?=\\r?\\n?$)");
      for (let [r, n] of e1) s = s.replaceAll(r, n);
      try {
        return new RegExp(s, "gu");
      } catch (r) {
        if (!(r instanceof SyntaxError) || !r.message.toLowerCase().includes("invalid property name")) throw r;
        let n = false, o = s.replace(/(\\[pP])\{([^}=]+)\}/g, (i, a, l) => {
          try {
            return new RegExp(`\\p{${l}}`, "u"), `${a}{${l}}`;
          } catch {
            return n = true, `${a}{Script=${l}}`;
          }
        });
        if (!n) throw r;
        try {
          return new RegExp(o, "gu");
        } catch {
          throw r;
        }
      }
    } else if (t6.String !== void 0) {
      let s = t1(t6.String);
      return new RegExp(e ? s : `(${s})`, "gu");
    } else return console.warn("Unknown pattern type:", t6), null;
  };
  var t1 = (t6) => t6.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  var s1 = (t6, e, s) => {
    let r = [], n = 0;
    for (; n < t6.length; ) {
      if (r.push(t6[n]), (e.get(t6[n]) ?? s) !== s) {
        ++n;
        continue;
      }
      for (; ++n < t6.length && (e.get(t6[n]) ?? s) === s; ) e.get(r.at(-1)) !== s && (r[r.length - 1] += t6[n]);
    }
    return r;
  };
  var r1 = (t6) => t6 >= 19968 && t6 <= 40959 || t6 >= 13312 && t6 <= 19903 || t6 >= 131072 && t6 <= 173791 || t6 >= 173824 && t6 <= 177983 || t6 >= 177984 && t6 <= 178207 || t6 >= 178208 && t6 <= 183983 || t6 >= 63744 && t6 <= 64255 || t6 >= 194560 && t6 <= 195103;
  var n1 = (t6) => Number.isInteger(t6) || typeof t6 == "bigint";
  var o1 = (t6) => {
    let e = 0;
    for (let s of t6) ++e;
    return e;
  };
  var i1 = (t6) => r0(t6.toLowerCase());
  var rt2 = (...t6) => Array.prototype.concat.apply([], t6);
  var Qc = (t6) => new Map(Object.entries(t6));
  var a1 = (t6, e) => {
    let s = [], r = 0;
    for (let n of t6.matchAll(e)) {
      let o = n[0];
      r < n.index && s.push(t6.slice(r, n.index)), o.length > 0 && s.push(o), r = n.index + o.length;
    }
    return r < t6.length && s.push(t6.slice(r)), s;
  };
  var r0 = (t6) => t6.replace(new RegExp("\\p{M}", "gu"), "");
  var Yy = (t6, e, s = []) => {
    if (!t6 || Array.isArray(t6) || typeof t6 != "object") return `${e} must be a valid object`;
    for (let r of s) if (!(r in t6)) return `${e} must contain a "${r}" property`;
    return null;
  };
  var l1 = (t6) => t6.match(/\S+/g) || [];
  var c1 = class {
    constructor() {
      let t6 = function(...e) {
        return t6._call(...e);
      };
      return Object.setPrototypeOf(t6, new.target.prototype);
    }
  };
  var Or = c1;
  var p1 = class extends Or {
    constructor(t6) {
      super(), this.config = t6;
    }
    _call(t6) {
      return this.normalize(t6);
    }
  };
  var yt2 = p1;
  var u1 = class extends yt2 {
    tokenize_chinese_chars(t6) {
      let e = [];
      for (let s = 0; s < t6.length; ++s) {
        let r = t6[s], n = r.charCodeAt(0);
        r1(n) ? (e.push(" "), e.push(r), e.push(" ")) : e.push(r);
      }
      return e.join("");
    }
    strip_accents(t6) {
      return t6.normalize("NFD").replace(new RegExp("\\p{Mn}", "gu"), "");
    }
    is_control(t6) {
      switch (t6) {
        case "	":
        case `
`:
        case "\r":
          return false;
        default:
          return new RegExp("^\\p{Cc}|\\p{Cf}|\\p{Co}|\\p{Cs}$", "u").test(t6);
      }
    }
    clean_text(t6) {
      let e = [];
      for (let s of t6) {
        let r = s.charCodeAt(0);
        r === 0 || r === 65533 || this.is_control(s) || (/^\s$/.test(s) ? e.push(" ") : e.push(s));
      }
      return e.join("");
    }
    normalize(t6) {
      return this.config.clean_text && (t6 = this.clean_text(t6)), this.config.handle_chinese_chars && (t6 = this.tokenize_chinese_chars(t6)), this.config.lowercase ? (t6 = t6.toLowerCase(), this.config.strip_accents !== false && (t6 = this.strip_accents(t6))) : this.config.strip_accents && (t6 = this.strip_accents(t6)), t6;
    }
  };
  var _1 = u1;
  var d1 = class extends yt2 {
    constructor(t6) {
      super(t6), this.charsmap = t6.precompiled_charsmap ?? null;
    }
    normalize(t6) {
      return t6 = t6.replace(/[\u0001-\u0008\u000B\u000E-\u001F\u007F\u008F\u009F]/gm, ""), t6 = t6.replace(/[\u0009\u000A\u000C\u000D\u00A0\u1680\u2000-\u200F\u2028\u2029\u202F\u205F\u2581\u3000\uFEFF\uFFFD]/gm, " "), t6.includes("\uFF5E") ? t6 = t6.split("\uFF5E").map((s) => s.normalize("NFKC")).join("\uFF5E") : t6 = t6.normalize("NFKC"), t6;
    }
  };
  var f1 = d1;
  var m1 = class extends yt2 {
    constructor(t6) {
      super(t6), this.normalizers = (t6.normalizers ?? []).map((e) => n0(e));
    }
    normalize(t6) {
      return this.normalizers.reduce((e, s) => s ? s.normalize(e) : e, t6);
    }
  };
  var h1 = m1;
  var g1 = class extends yt2 {
    normalize(t6) {
      let e = aa(this.config.pattern ?? {});
      return e === null ? t6 : t6.replaceAll(e, this.config.content ?? "");
    }
  };
  var x1 = g1;
  var w1 = class extends yt2 {
    constructor() {
      super(...arguments), this.form = "NFC";
    }
    normalize(t6) {
      return t6 = t6.normalize(this.form), t6;
    }
  };
  var la = w1;
  var y1 = class extends la {
    constructor() {
      super(...arguments), this.form = "NFC";
    }
  };
  var b1 = y1;
  var k1 = class extends la {
    constructor() {
      super(...arguments), this.form = "NFD";
    }
  };
  var v1 = k1;
  var E1 = class extends la {
    constructor() {
      super(...arguments), this.form = "NFKC";
    }
  };
  var A1 = E1;
  var M1 = class extends la {
    constructor() {
      super(...arguments), this.form = "NFKD";
    }
  };
  var S1 = M1;
  var O1 = class extends yt2 {
    normalize(t6) {
      return this.config.strip_left && this.config.strip_right ? t6 = t6.trim() : (this.config.strip_left && (t6 = t6.trimStart()), this.config.strip_right && (t6 = t6.trimEnd())), t6;
    }
  };
  var I1 = O1;
  var z1 = class extends yt2 {
    normalize(t6) {
      return r0(t6);
    }
  };
  var T1 = z1;
  var C1 = class extends yt2 {
    normalize(t6) {
      return t6.toLowerCase();
    }
  };
  var P1 = C1;
  var N1 = class extends yt2 {
    normalize(t6) {
      return t6 = this.config.prepend + t6, t6;
    }
  };
  var L1 = N1;
  function $1(t6) {
    if (t6 === null) return null;
    switch (t6.type) {
      case "BertNormalizer":
        return new _1(t6);
      case "Precompiled":
        return new f1(t6);
      case "Sequence":
        return new h1(t6);
      case "Replace":
        return new x1(t6);
      case "NFC":
        return new b1(t6);
      case "NFD":
        return new v1(t6);
      case "NFKC":
        return new A1(t6);
      case "NFKD":
        return new S1(t6);
      case "Strip":
        return new I1(t6);
      case "StripAccents":
        return new T1(t6);
      case "Lowercase":
        return new P1(t6);
      case "Prepend":
        return new L1(t6);
      default:
        throw new Error(`Unknown Normalizer type: ${t6.type}`);
    }
  }
  var n0 = $1;
  var F1 = class extends Or {
    pre_tokenize(t6, e) {
      return (Array.isArray(t6) ? t6.map((s) => this.pre_tokenize_text(s, e)) : this.pre_tokenize_text(t6, e)).flat();
    }
    _call(t6, e) {
      return this.pre_tokenize(t6, e);
    }
  };
  var nt = F1;
  var R1 = class extends nt {
    constructor(t6) {
      super(), this.config = t6, this.add_prefix_space = this.config.add_prefix_space ?? false, this.trim_offsets = this.config.trim_offsets ?? false, this.use_regex = this.config.use_regex ?? true, this.pattern = new RegExp("'s|'t|'re|'ve|'m|'ll|'d| ?\\p{L}+| ?\\p{N}+| ?[^\\s\\p{L}\\p{N}]+|\\s+(?!\\S)|\\s+", "gu"), this.byte_encoder = s0, this.text_encoder = new TextEncoder();
    }
    pre_tokenize_text(t6, e) {
      return this.add_prefix_space && !t6.startsWith(" ") && (t6 = " " + t6), (this.use_regex ? t6.match(this.pattern) || [] : [t6]).map((r) => Array.from(this.text_encoder.encode(r), (n) => this.byte_encoder[n]).join(""));
    }
  };
  var D1 = R1;
  var q1 = class extends nt {
    pre_tokenize_text(t6, e) {
      return t6.match(/\w+|[^\w\s]+/g) || [];
    }
  };
  var j1 = q1;
  var B1 = class extends nt {
    constructor(t6) {
      super(), this.replacement = t6.replacement ?? "\u2581", this.str_rep = t6.str_rep || this.replacement, this.prepend_scheme = t6.prepend_scheme ?? "always";
    }
    pre_tokenize_text(t6, e) {
      let { section_index: s = void 0 } = e ?? {}, r = t6.replaceAll(" ", this.str_rep);
      return !r.startsWith(this.replacement) && (this.prepend_scheme === "always" || this.prepend_scheme === "first" && s === 0) && (r = this.str_rep + r), [r];
    }
  };
  var U1 = B1;
  var G1 = class extends nt {
    constructor(t6) {
      super(), this.config = t6, this.pattern = aa(this.config.pattern ?? {}, this.config.invert ?? true);
    }
    pre_tokenize_text(t6) {
      return this.pattern === null ? [] : this.config.invert ? t6.match(this.pattern) || [] : this.config.behavior?.toLowerCase() === "removed" ? t6.split(this.pattern).filter((e) => e) : a1(t6, this.pattern);
    }
  };
  var W1 = G1;
  var V1 = class extends nt {
    constructor(t6) {
      super(), this.config = t6, this.pattern = new RegExp(`[^${ia}]+|[${ia}]+`, "gu");
    }
    pre_tokenize_text(t6) {
      return t6.match(this.pattern) || [];
    }
  };
  var H1 = V1;
  var K1 = class extends nt {
    constructor(t6) {
      super(), this.config = t6;
      let e = `[^\\d]+|\\d${this.config.individual_digits ? "" : "+"}`;
      this.pattern = new RegExp(e, "gu");
    }
    pre_tokenize_text(t6) {
      return t6.match(this.pattern) || [];
    }
  };
  var X1 = K1;
  var Q1 = class extends nt {
    constructor() {
      super(), this.pattern = new RegExp(`[^\\s${ia}]+|[${ia}]`, "gu");
    }
    pre_tokenize_text(t6, e) {
      return t6.trim().match(this.pattern) || [];
    }
  };
  var Y1 = Q1;
  var J1 = class extends nt {
    constructor(t6) {
      super(), this.config = t6, this.pattern = aa(this.config.pattern ?? {}), this.content = this.config.content ?? "";
    }
    pre_tokenize_text(t6) {
      return this.pattern === null ? [t6] : [t6.replaceAll(this.pattern, this.config.content ?? "")];
    }
  };
  var Z1 = J1;
  var ev = class extends nt {
    constructor(t6) {
      super(), this.tokenizers = (t6.pretokenizers ?? []).map((e) => o0(e));
    }
    pre_tokenize_text(t6, e) {
      return this.tokenizers.reduce((s, r) => r ? r.pre_tokenize(s, e) : s, [t6]);
    }
  };
  var tv = ev;
  var sv = class extends nt {
    pre_tokenize_text(t6) {
      return l1(t6);
    }
  };
  var rv = sv;
  var nv = class extends nt {
    constructor(t6) {
      super(), this.config = t6, this._length = t6.length;
    }
    pre_tokenize_text(t6) {
      let e = [];
      for (let s = 0; s < t6.length; s += this._length) e.push(t6.slice(s, s + this._length));
      return e;
    }
  };
  var ov = nv;
  function iv(t6) {
    if (t6 === null) return null;
    switch (t6.type) {
      case "BertPreTokenizer":
        return new Y1();
      case "Sequence":
        return new tv(t6);
      case "Whitespace":
        return new j1();
      case "WhitespaceSplit":
        return new rv();
      case "Metaspace":
        return new U1(t6);
      case "ByteLevel":
        return new D1(t6);
      case "Split":
        return new W1(t6);
      case "Punctuation":
        return new H1(t6);
      case "Digits":
        return new X1(t6);
      case "Replace":
        return new Z1(t6);
      case "FixedLength":
        return new ov(t6);
      default:
        throw new Error(`Unknown PreTokenizer type: ${t6.type}`);
    }
  }
  var o0 = iv;
  var av = class extends Or {
    constructor(t6) {
      super(), this.config = t6, this.vocab = [], this.tokens_to_ids = /* @__PURE__ */ new Map(), this.unk_token_id = void 0, this.unk_token = void 0, this.end_of_word_suffix = void 0, this.fuse_unk = this.config.fuse_unk ?? false;
    }
    _call(t6) {
      let e = this.encode(t6);
      return this.fuse_unk && (e = s1(e, this.tokens_to_ids, this.unk_token_id)), e;
    }
  };
  var ca = av;
  var lv = class extends ca {
    constructor(t6) {
      super(t6), this.max_input_chars_per_word = 100, this.tokens_to_ids = Qc(t6.vocab), this.unk_token_id = this.tokens_to_ids.get(t6.unk_token), this.unk_token = t6.unk_token, this.max_input_chars_per_word = t6.max_input_chars_per_word ?? 100, this.vocab = new Array(this.tokens_to_ids.size);
      for (let [e, s] of this.tokens_to_ids) this.vocab[s] = e;
    }
    encode(t6) {
      let e = [];
      for (let s of t6) {
        let r = [...s];
        if (r.length > this.max_input_chars_per_word) {
          e.push(this.unk_token);
          continue;
        }
        let n = false, o = 0, i = [];
        for (; o < r.length; ) {
          let a = r.length, l = null;
          for (; o < a; ) {
            let c = r.slice(o, a).join("");
            if (o > 0 && (c = this.config.continuing_subword_prefix + c), this.tokens_to_ids.has(c)) {
              l = c;
              break;
            }
            --a;
          }
          if (l === null) {
            n = true;
            break;
          }
          i.push(l), o = a;
        }
        n ? e.push(this.unk_token) : e.push(...i);
      }
      return e;
    }
  };
  var Jy = lv;
  var Zy = class i0 {
    constructor(e, s) {
      this.is_leaf = e, this.children = s;
    }
    static default() {
      return new i0(false, /* @__PURE__ */ new Map());
    }
  };
  var cv = class {
    constructor() {
      this.root = Zy.default();
    }
    extend(t6) {
      for (let e of t6) this.push(e);
    }
    push(t6) {
      let e = this.root;
      for (let s of t6) {
        let r = e.children.get(s);
        r === void 0 && (r = Zy.default(), e.children.set(s, r)), e = r;
      }
      e.is_leaf = true;
    }
    *common_prefix_search(t6) {
      let e = this.root;
      if (e === void 0) return;
      let s = "";
      for (let r of t6) {
        if (s += r, e = e.children.get(r), e === void 0) return;
        e.is_leaf && (yield s);
      }
    }
  };
  var pv = cv;
  var Kc = class a0 {
    constructor(e, s, r, n, o) {
      this.token_id = e, this.node_id = s, this.pos = r, this.length = n, this.score = o, this.prev = null, this.backtrace_score = 0;
    }
    clone() {
      let e = new a0(this.token_id, this.node_id, this.pos, this.length, this.score);
      return e.prev = this.prev, e.backtrace_score = this.backtrace_score, e;
    }
  };
  var uv = class {
    constructor(t6, e, s) {
      this.chars = Array.from(t6), this.len = this.chars.length, this.bos_token_id = e, this.eos_token_id = s, this.nodes = [], this.begin_nodes = Array.from({ length: this.len + 1 }, () => []), this.end_nodes = Array.from({ length: this.len + 1 }, () => []);
      let r = new Kc(this.bos_token_id ?? 0, 0, 0, 0, 0), n = new Kc(this.eos_token_id ?? 0, 1, this.len, 0, 0);
      this.nodes.push(r.clone()), this.nodes.push(n.clone()), this.begin_nodes[this.len].push(n), this.end_nodes[0].push(r);
    }
    insert(t6, e, s, r) {
      let n = this.nodes.length, o = new Kc(r, n, t6, e, s);
      this.begin_nodes[t6].push(o), this.end_nodes[t6 + e].push(o), this.nodes.push(o);
    }
    viterbi() {
      let t6 = this.len, e = 0;
      for (; e <= t6; ) {
        if (this.begin_nodes[e].length == 0) return [];
        for (let i of this.begin_nodes[e]) {
          i.prev = null;
          let a = 0, l = null;
          for (let c of this.end_nodes[e]) {
            let p = c.backtrace_score + i.score;
            (l === null || p > a) && (l = c.clone(), a = p);
          }
          if (l !== null) i.prev = l, i.backtrace_score = a;
          else return [];
        }
        ++e;
      }
      let s = [], n = this.begin_nodes[t6][0].prev;
      if (n === null) return [];
      let o = n.clone();
      for (; o.prev !== null; ) s.push(o.clone()), o = o.clone().prev.clone();
      return s.reverse(), s;
    }
    piece(t6) {
      return this.chars.slice(t6.pos, t6.pos + t6.length).join("");
    }
    tokens() {
      return this.viterbi().map((e) => this.piece(e));
    }
    token_ids() {
      return this.viterbi().map((e) => e.token_id);
    }
  };
  var _v = uv;
  function dv(t6) {
    if (t6.length === 0) throw new Error("Array must not be empty");
    let e = t6[0], s = 0;
    for (let r = 1; r < t6.length; ++r) t6[r] < e && (e = t6[r], s = r);
    return [e, s];
  }
  var fv = class extends ca {
    constructor(t6, e) {
      super(t6);
      let s = t6.vocab.length;
      this.vocab = new Array(s), this.scores = new Array(s);
      for (let r = 0; r < s; ++r) [this.vocab[r], this.scores[r]] = t6.vocab[r];
      this.unk_token_id = t6.unk_id, this.unk_token = this.vocab[t6.unk_id], this.tokens_to_ids = new Map(this.vocab.map((r, n) => [r, n])), this.bos_token = " ", this.bos_token_id = this.tokens_to_ids.get(this.bos_token), this.eos_token = e, this.eos_token_id = this.tokens_to_ids.get(this.eos_token), this.unk_token = this.vocab[this.unk_token_id], this.min_score = dv(this.scores)[0], this.unk_score = this.min_score - 10, this.scores[this.unk_token_id] = this.unk_score, this.trie = new pv(), this.trie.extend(this.vocab), this.fuse_unk = true;
    }
    populate_nodes(t6) {
      let e = t6.chars, s = 1, r = 0;
      for (; r < e.length; ) {
        let n = false, o = [], i = e.slice(r).join(""), a = this.trie.common_prefix_search(i);
        for (let l of a) {
          o.push(l);
          let c = this.tokens_to_ids.get(l), p = this.scores[c], u = o1(l);
          t6.insert(r, u, p, c), !n && u === s && (n = true);
        }
        n || t6.insert(r, s, this.unk_score, this.unk_token_id), r += s;
      }
    }
    tokenize(t6) {
      let e = new _v(t6, this.bos_token_id, this.eos_token_id);
      return this.populate_nodes(e), e.tokens();
    }
    encode(t6) {
      let e = [];
      for (let s of t6) {
        let r = this.tokenize(s);
        e.push(...r);
      }
      return e;
    }
  };
  var e0 = fv;
  var mv = class {
    constructor(t6 = (s, r) => s > r, e = 1 / 0) {
      this._heap = [], this._comparator = t6, this._max_size = e;
    }
    get size() {
      return this._heap.length;
    }
    is_empty() {
      return this.size === 0;
    }
    peek() {
      return this._heap[0];
    }
    push(...t6) {
      return this.extend(t6);
    }
    extend(t6) {
      for (let e of t6) if (this.size < this._max_size) this._heap.push(e), this._sift_up();
      else {
        let s = this._smallest();
        this._comparator(e, this._heap[s]) && (this._heap[s] = e, this._sift_up_from(s));
      }
      return this.size;
    }
    pop() {
      let t6 = this.peek(), e = this.size - 1;
      return e > 0 && this._swap(0, e), this._heap.pop(), this._sift_down(), t6;
    }
    replace(t6) {
      let e = this.peek();
      return this._heap[0] = t6, this._sift_down(), e;
    }
    _parent(t6) {
      return (t6 + 1 >>> 1) - 1;
    }
    _left(t6) {
      return (t6 << 1) + 1;
    }
    _right(t6) {
      return t6 + 1 << 1;
    }
    _greater(t6, e) {
      return this._comparator(this._heap[t6], this._heap[e]);
    }
    _swap(t6, e) {
      let s = this._heap[t6];
      this._heap[t6] = this._heap[e], this._heap[e] = s;
    }
    _sift_up() {
      this._sift_up_from(this.size - 1);
    }
    _sift_up_from(t6) {
      for (; t6 > 0 && this._greater(t6, this._parent(t6)); ) this._swap(t6, this._parent(t6)), t6 = this._parent(t6);
    }
    _sift_down() {
      let t6 = 0;
      for (; this._left(t6) < this.size && this._greater(this._left(t6), t6) || this._right(t6) < this.size && this._greater(this._right(t6), t6); ) {
        let e = this._right(t6) < this.size && this._greater(this._right(t6), this._left(t6)) ? this._right(t6) : this._left(t6);
        this._swap(t6, e), t6 = e;
      }
    }
    _smallest() {
      return 2 ** Math.floor(Math.log2(this.size)) - 1;
    }
  };
  var hv = mv;
  var gv = class {
    constructor(t6) {
      this.capacity = t6, this.cache = /* @__PURE__ */ new Map();
    }
    get(t6) {
      if (!this.cache.has(t6)) return;
      let e = this.cache.get(t6);
      return this.cache.delete(t6), this.cache.set(t6, e), e;
    }
    put(t6, e) {
      this.cache.has(t6) && this.cache.delete(t6), this.cache.set(t6, e), this.cache.size > this.capacity && this.cache.delete(this.cache.keys().next().value);
    }
    clear() {
      this.cache.clear();
    }
  };
  var xv = gv;
  var wv = class extends ca {
    constructor(t6) {
      super(t6), this.tokens_to_ids = Qc(t6.vocab), this.unk_token_id = this.tokens_to_ids.get(t6.unk_token), this.unk_token = t6.unk_token, this.vocab = new Array(this.tokens_to_ids.size);
      for (let [s, r] of this.tokens_to_ids) this.vocab[r] = s;
      let e = Array.isArray(t6.merges[0]);
      this.merges = e ? t6.merges : t6.merges.map((s) => s.split(" ", 2)), this.bpe_ranks = new Map(this.merges.map((s, r) => [JSON.stringify(s), r])), this.end_of_word_suffix = t6.end_of_word_suffix, this.continuing_subword_suffix = t6.continuing_subword_suffix ?? null, this.byte_fallback = this.config.byte_fallback ?? false, this.byte_fallback && (this.text_encoder = new TextEncoder()), this.ignore_merges = this.config.ignore_merges ?? false, this.max_length_to_cache = 256, this.cache_capacity = 1e4, this.cache = new xv(this.cache_capacity);
    }
    clear_cache() {
      this.cache.clear();
    }
    bpe(t6) {
      if (t6.length === 0) return [];
      let e = this.cache.get(t6);
      if (e !== void 0) return e;
      let s = Array.from(t6);
      this.end_of_word_suffix && (s[s.length - 1] += this.end_of_word_suffix);
      let r = [];
      if (s.length > 1) {
        let n = new hv((a, l) => a.score < l.score), o = { token: s[0], bias: 0, prev: null, next: null }, i = o;
        for (let a = 1; a < s.length; ++a) {
          let l = { bias: a / s.length, token: s[a], prev: i, next: null };
          i.next = l, this.add_node(n, i), i = l;
        }
        for (; !n.is_empty(); ) {
          let a = n.pop();
          if (a.deleted || !a.next || a.next.deleted) continue;
          if (a.deleted = true, a.next.deleted = true, a.prev) {
            let c = { ...a.prev };
            a.prev.deleted = true, a.prev = c, c.prev ? c.prev.next = c : o = c;
          }
          let l = { token: a.token + a.next.token, bias: a.bias, prev: a.prev, next: a.next.next };
          l.prev ? (l.prev.next = l, this.add_node(n, l.prev)) : o = l, l.next && (l.next.prev = l, this.add_node(n, l));
        }
        for (let a = o; a !== null; a = a.next) r.push(a.token);
      } else r = s;
      if (this.continuing_subword_suffix) for (let n = 0; n < r.length - 1; ++n) r[n] += this.continuing_subword_suffix;
      return t6.length < this.max_length_to_cache && this.cache.put(t6, r), r;
    }
    add_node(t6, e) {
      let s = this.bpe_ranks.get(JSON.stringify([e.token, e.next.token]));
      s !== void 0 && (e.score = s + e.bias, t6.push(e));
    }
    encode(t6) {
      let e = [];
      for (let s of t6) {
        if (this.ignore_merges && this.tokens_to_ids.has(s)) {
          e.push(s);
          continue;
        }
        let r = this.bpe(s);
        for (let n of r) if (this.tokens_to_ids.has(n)) e.push(n);
        else if (this.byte_fallback) {
          let o = Array.from(this.text_encoder.encode(n)).map((i) => `<0x${i.toString(16).toUpperCase().padStart(2, "0")}>`);
          o.every((i) => this.tokens_to_ids.has(i)) ? e.push(...o) : this.unk_token != null && e.push(this.unk_token);
        } else this.unk_token != null && e.push(this.unk_token);
      }
      return e;
    }
  };
  var t0 = wv;
  var yv = class extends ca {
    constructor(t6, e) {
      super(t6);
      let s = t6.vocab;
      this.tokens_to_ids = Qc(e.target_lang ? s[e.target_lang] : s), this.bos_token = e.bos_token, this.bos_token_id = this.tokens_to_ids.get(this.bos_token), this.eos_token = e.eos_token, this.eos_token_id = this.tokens_to_ids.get(this.eos_token), this.pad_token = e.pad_token, this.pad_token_id = this.tokens_to_ids.get(this.pad_token), this.unk_token = e.unk_token, this.unk_token_id = this.tokens_to_ids.get(this.unk_token), this.vocab = new Array(this.tokens_to_ids.size);
      for (let [r, n] of this.tokens_to_ids) this.vocab[n] = r;
    }
    encode(t6) {
      return t6;
    }
  };
  var bv = yv;
  function kv(t6, e) {
    switch (t6.type) {
      case "WordPiece":
        return new Jy(t6);
      case "Unigram":
        return new e0(t6, e.eos_token);
      case "BPE":
        return new t0(t6);
      default:
        if (t6.vocab) return Array.isArray(t6.vocab) ? new e0(t6, e.eos_token) : Object.hasOwn(t6, "continuing_subword_prefix") && Object.hasOwn(t6, "unk_token") ? Object.hasOwn(t6, "merges") ? new t0(t6) : new Jy(t6) : new bv(t6, { target_lang: e.target_lang, bos_token: e.bos_token, eos_token: e.eos_token, pad_token: e.pad_token, unk_token: e.unk_token });
        throw new Error(`Unknown TokenizerModel type: ${t6?.type}`);
    }
  }
  var vv = kv;
  var Ev = class extends Or {
    constructor(t6) {
      super(), this.config = t6;
    }
    _call(t6, ...e) {
      return this.post_process(t6, ...e);
    }
  };
  var Ir = Ev;
  var Av = class extends Ir {
    post_process(t6, e = null, s = true) {
      let r = e === null ? this.config.single : this.config.pair, n = [], o = [];
      for (let i of r) "SpecialToken" in i ? s && (n.push(i.SpecialToken.id), o.push(i.SpecialToken.type_id)) : "Sequence" in i && (i.Sequence.id === "A" ? (n = rt2(n, t6), o = rt2(o, new Array(t6.length).fill(i.Sequence.type_id))) : i.Sequence.id === "B" && (n = rt2(n, e), o = rt2(o, new Array(e.length).fill(i.Sequence.type_id))));
      return { tokens: n, token_type_ids: o };
    }
  };
  var Mv = Av;
  var Sv = class extends Ir {
    post_process(t6, e = null) {
      return { tokens: t6, tokens_pair: e };
    }
  };
  var Ov = Sv;
  var Iv = class extends Ir {
    constructor(t6) {
      super(t6), this.sep = t6.sep, this.cls = t6.cls;
    }
    post_process(t6, e = null, s = true) {
      s && (t6 = rt2([this.cls[0]], t6, [this.sep[0]]));
      let r = new Array(t6.length).fill(0);
      if (e) {
        let n = [], o = s ? [this.sep[0]] : [];
        t6 = rt2(t6, n, e, o), r = rt2(r, new Array(e.length + n.length + o.length).fill(1));
      }
      return { tokens: t6, token_type_ids: r };
    }
  };
  var zv = Iv;
  var Tv = class extends Ir {
    constructor(t6) {
      super(t6), this.sep = t6.sep, this.cls = t6.cls;
    }
    post_process(t6, e, s = true) {
      s && (t6 = rt2([this.cls[0]], t6, [this.sep[0]]));
      let r = new Array(t6.length).fill(0);
      if (e) {
        let n = s ? [this.sep[0]] : [], o = s ? [this.sep[0]] : [];
        t6 = rt2(t6, n, e, o), r = rt2(r, new Array(e.length + n.length + o.length).fill(1));
      }
      return { tokens: t6, token_type_ids: r };
    }
  };
  var Cv = Tv;
  var Pv = class extends Ir {
    constructor(t6) {
      super(t6), this.processors = (t6.processors ?? []).map((e) => l0(e));
    }
    post_process(t6, e = null, s = true) {
      let r = { tokens: t6, tokens_pair: e };
      for (let n of this.processors) r = n.post_process(r.tokens, r.tokens_pair, s);
      return r;
    }
  };
  var Nv = Pv;
  function Lv(t6) {
    if (t6 === null) return null;
    switch (t6.type) {
      case "TemplateProcessing":
        return new Mv(t6);
      case "ByteLevel":
        return new Ov(t6);
      case "BertProcessing":
        return new zv(t6);
      case "RobertaProcessing":
        return new Cv(t6);
      case "Sequence":
        return new Nv(t6);
      default:
        throw new Error(`Unknown PostProcessor type: ${t6.type}`);
    }
  }
  var l0 = Lv;
  var $v = class extends Or {
    constructor(t6) {
      super(), this.config = t6, this.added_tokens = [], this.end_of_word_suffix = null, this.trim_offsets = "trim_offsets" in t6 ? t6.trim_offsets : false;
    }
    _call(t6) {
      return this.decode(t6);
    }
    decode(t6) {
      return this.decode_chain(t6).join("");
    }
  };
  var Je = $v;
  var Fv = class extends Je {
    constructor(t6) {
      super(t6), this.byte_decoder = Zk, this.text_decoder = new TextDecoder("utf-8", { fatal: false, ignoreBOM: true }), this.end_of_word_suffix = null;
    }
    convert_tokens_to_string(t6) {
      let e = t6.join(""), s = new Uint8Array([...e].map((r) => this.byte_decoder[r]));
      return this.text_decoder.decode(s);
    }
    decode_chain(t6) {
      let e = [], s = [];
      for (let r of t6) this.added_tokens.find((n) => n.content === r) !== void 0 ? (s.length > 0 && (e.push(this.convert_tokens_to_string(s)), s = []), e.push(r)) : s.push(r);
      return s.length > 0 && e.push(this.convert_tokens_to_string(s)), e;
    }
  };
  var Rv = Fv;
  var Dv = class extends Je {
    constructor(t6) {
      super(t6), this.cleanup = t6.cleanup;
    }
    decode_chain(t6) {
      return t6.map((e, s) => {
        if (s !== 0) {
          let r = this.config.prefix;
          r && e.startsWith(r) ? e = e.replace(r, "") : e = " " + e;
        }
        return this.cleanup && (e = Xc(e)), e;
      });
    }
  };
  var qv = Dv;
  var jv = class extends Je {
    constructor(t6) {
      super(t6), this.replacement = t6.replacement ?? "\u2581";
    }
    decode_chain(t6) {
      let e = [];
      for (let s = 0; s < t6.length; ++s) {
        let r = t6[s].replaceAll(this.replacement, " ");
        s == 0 && r.startsWith(" ") && (r = r.substring(1)), e.push(r);
      }
      return e;
    }
  };
  var Bv = jv;
  var Uv = class extends Je {
    constructor(t6) {
      super(t6), this.suffix = t6.suffix ?? "";
    }
    decode_chain(t6) {
      return t6.map((e, s) => e.replaceAll(this.suffix, s === t6.length - 1 ? "" : " "));
    }
  };
  var Gv = Uv;
  var Wv = class extends Je {
    constructor(t6) {
      super(t6), this.pad_token = t6.pad_token ?? "", this.word_delimiter_token = t6.word_delimiter_token ?? "", this.cleanup = t6.cleanup;
    }
    convert_tokens_to_string(t6) {
      if (t6.length === 0) return "";
      let e = [t6[0]];
      for (let n = 1; n < t6.length; ++n) t6[n] !== e.at(-1) && e.push(t6[n]);
      let r = e.filter((n) => n !== this.pad_token).join("");
      return this.cleanup && (r = Xc(r).replaceAll(this.word_delimiter_token, " ").trim()), r;
    }
    decode_chain(t6) {
      return [this.convert_tokens_to_string(t6)];
    }
  };
  var Vv = Wv;
  var Hv = class extends Je {
    constructor(t6) {
      super(t6), this.decoders = (t6.decoders ?? []).map((e) => c0(e));
    }
    decode_chain(t6) {
      return this.decoders.reduce((e, s) => s.decode_chain(e), t6);
    }
  };
  var Kv = Hv;
  var Xv = class extends Je {
    decode_chain(t6) {
      let e = aa(this.config.pattern), s = this.config.content ?? "";
      return e === null ? t6 : t6.map((r) => r.replaceAll(e, s));
    }
  };
  var Qv = Xv;
  var Yv = class extends Je {
    decode_chain(t6) {
      return [t6.join("")];
    }
  };
  var Jv = Yv;
  var Zv = class extends Je {
    constructor(t6) {
      super(t6), this.content = t6.content ?? "", this.start = t6.start ?? 0, this.stop = t6.stop ?? 0;
    }
    decode_chain(t6) {
      return t6.map((e) => {
        let s = 0;
        for (let n = 0; n < this.start && e[n] === this.content; ++n) {
          s = n + 1;
          continue;
        }
        let r = e.length;
        for (let n = 0; n < this.stop; ++n) {
          let o = e.length - n - 1;
          if (e[o] === this.content) {
            r = o;
            continue;
          } else break;
        }
        return e.slice(s, r);
      });
    }
  };
  var eE = Zv;
  var tE = class extends Je {
    constructor(t6) {
      super(t6), this.text_decoder = new TextDecoder();
    }
    decode_chain(t6) {
      let e = [], s = [];
      for (let r of t6) {
        let n = null;
        if (r.length === 6 && r.startsWith("<0x") && r.endsWith(">")) {
          let o = parseInt(r.slice(3, 5), 16);
          isNaN(o) || (n = o);
        }
        if (n !== null) s.push(n);
        else {
          if (s.length > 0) {
            let o = this.text_decoder.decode(Uint8Array.from(s));
            e.push(o), s = [];
          }
          e.push(r);
        }
      }
      if (s.length > 0) {
        let r = this.text_decoder.decode(Uint8Array.from(s));
        e.push(r), s = [];
      }
      return e;
    }
  };
  var sE = tE;
  function rE(t6) {
    if (t6 === null) return null;
    switch (t6.type) {
      case "ByteLevel":
        return new Rv(t6);
      case "WordPiece":
        return new qv(t6);
      case "Metaspace":
        return new Bv(t6);
      case "BPEDecoder":
        return new Gv(t6);
      case "CTC":
        return new Vv(t6);
      case "Sequence":
        return new Kv(t6);
      case "Replace":
        return new Qv(t6);
      case "Fuse":
        return new Jv(t6);
      case "Strip":
        return new eE(t6);
      case "ByteFallback":
        return new sE(t6);
      default:
        throw new Error(`Unknown Decoder type: ${t6.type}`);
    }
  }
  var c0 = rE;
  var nE = class {
    constructor(t6, e) {
      let s = Yy(t6, "Tokenizer", ["model", "decoder", "post_processor", "pre_tokenizer", "normalizer"]);
      if (s) throw new Error(s);
      let r = Yy(e, "Config");
      if (r) throw new Error(r);
      this.tokenizer = t6, this.config = e, this.normalizer = n0(this.tokenizer.normalizer), this.pre_tokenizer = o0(this.tokenizer.pre_tokenizer), this.model = vv(this.tokenizer.model, this.config), this.post_processor = l0(this.tokenizer.post_processor), this.decoder = c0(this.tokenizer.decoder), this.special_tokens = [], this.all_special_ids = [], this.added_tokens = [];
      let n = [], o = [];
      this.added_tokens_map = /* @__PURE__ */ new Map();
      for (let i of this.tokenizer.added_tokens) {
        let a = new Yk(i);
        if (this.added_tokens.push(a), this.model.tokens_to_ids.set(a.content, a.id), this.model.vocab[a.id] = a.content, a.special && (this.special_tokens.push(a.content), this.all_special_ids.push(a.id)), this.added_tokens_map.set(a.content, a), a.normalized && this.normalizer !== null) {
          let l = this.normalizer(a.content);
          o.push(l), this.added_tokens_map.set(l, a);
        } else n.push(a.content);
      }
      (this.config.additional_special_tokens ?? []).forEach((i) => {
        this.special_tokens.includes(i) || this.special_tokens.push(i);
      }), this.decoder && (this.decoder.added_tokens = this.added_tokens, this.decoder.end_of_word_suffix = this.model.end_of_word_suffix), this.splitter_unnormalized = new Xy(n), this.splitter_normalized = new Xy(o), this.remove_space = this.config.remove_space, this.clean_up_tokenization_spaces = this.config.clean_up_tokenization_spaces ?? true, this.do_lowercase_and_remove_accent = this.config.do_lowercase_and_remove_accent ?? false;
    }
    encode(t6, { text_pair: e = null, add_special_tokens: s = true, return_token_type_ids: r = null } = {}) {
      let { tokens: n, token_type_ids: o } = this.tokenize_helper(t6, { text_pair: e, add_special_tokens: s }), i = n.map((l) => this.added_tokens_map.get(l)?.id ?? this.model.tokens_to_ids.get(l) ?? this.model.unk_token_id), a = { ids: i, tokens: n, attention_mask: new Array(i.length).fill(1) };
      return r && o && (a.token_type_ids = o), a;
    }
    decode(t6, e = {}) {
      if (!Array.isArray(t6) || t6.length === 0 || !n1(t6[0])) throw Error("token_ids must be a non-empty array of integers.");
      let s = t6.map((n) => this.model.vocab[Number(n)] ?? this.model.unk_token);
      e.skip_special_tokens && (s = s.filter((n) => !this.special_tokens.includes(n)));
      let r = this.decoder ? this.decoder(s) : s.join(" ");
      return this.decoder && this.decoder.end_of_word_suffix && (r = r.replaceAll(this.decoder.end_of_word_suffix, " "), e.skip_special_tokens && (r = r.trim())), (e.clean_up_tokenization_spaces ?? this.clean_up_tokenization_spaces) && (r = Xc(r)), r;
    }
    tokenize(t6, { text_pair: e = null, add_special_tokens: s = false } = {}) {
      return this.tokenize_helper(t6, { text_pair: e, add_special_tokens: s }).tokens;
    }
    encode_text(t6) {
      if (t6 === null) return null;
      let e = this.splitter_unnormalized.split(t6);
      return e.forEach((s, r) => {
        let n = this.added_tokens_map.get(s);
        n && (n.lstrip && r > 0 && (e[r - 1] = e[r - 1].trimEnd()), n.rstrip && r < e.length - 1 && (e[r + 1] = e[r + 1].trimStart()));
      }), e.flatMap((s, r) => {
        if (s.length === 0) return [];
        if (this.added_tokens_map.has(s)) return [s];
        if (this.remove_space === true && (s = s.trim().split(/\s+/).join(" ")), this.do_lowercase_and_remove_accent && (s = i1(s)), this.normalizer !== null && (s = this.normalizer(s)), s.length === 0) return [];
        let n = this.splitter_normalized.split(s);
        return n.forEach((o, i) => {
          let a = this.added_tokens_map.get(o);
          a && (a.lstrip && i > 0 && (n[i - 1] = n[i - 1].trimEnd()), a.rstrip && i < n.length - 1 && (n[i + 1] = n[i + 1].trimStart()));
        }), n.flatMap((o) => {
          if (o.length === 0) return [];
          if (this.added_tokens_map.has(o)) return [o];
          let i = this.pre_tokenizer !== null ? this.pre_tokenizer(o, { section_index: r }) : [o];
          return this.model(i);
        });
      });
    }
    tokenize_helper(t6, { text_pair: e = null, add_special_tokens: s = true }) {
      let r = this.encode_text(t6), n = this.encode_text(e || null);
      return this.post_processor ? this.post_processor(r, n, s) : { tokens: rt2(r ?? [], n ?? []) };
    }
    token_to_id(t6) {
      return this.model.tokens_to_ids.get(t6);
    }
    id_to_token(t6) {
      return this.model.vocab[t6];
    }
    get_added_tokens_decoder() {
      let t6 = /* @__PURE__ */ new Map();
      for (let e of this.added_tokens) t6.set(e.id, e);
      return t6;
    }
    get_vocab(t6 = true) {
      let e = /* @__PURE__ */ new Map();
      for (let s = 0; s < this.model.vocab.length; ++s) {
        let r = this.model.vocab[s];
        (t6 || !this.added_tokens_map.has(r)) && e.set(r, s);
      }
      return e;
    }
  };
  var p0 = nE;
  var M = Object.freeze({ Text: "Text", NumericLiteral: "NumericLiteral", StringLiteral: "StringLiteral", Identifier: "Identifier", Equals: "Equals", OpenParen: "OpenParen", CloseParen: "CloseParen", OpenStatement: "OpenStatement", CloseStatement: "CloseStatement", OpenExpression: "OpenExpression", CloseExpression: "CloseExpression", OpenSquareBracket: "OpenSquareBracket", CloseSquareBracket: "CloseSquareBracket", OpenCurlyBracket: "OpenCurlyBracket", CloseCurlyBracket: "CloseCurlyBracket", Comma: "Comma", Dot: "Dot", Colon: "Colon", Pipe: "Pipe", CallOperator: "CallOperator", AdditiveBinaryOperator: "AdditiveBinaryOperator", MultiplicativeBinaryOperator: "MultiplicativeBinaryOperator", ComparisonBinaryOperator: "ComparisonBinaryOperator", UnaryOperator: "UnaryOperator", Comment: "Comment" });
  var Ze2 = class {
    constructor(t6, e) {
      this.value = t6, this.type = e;
    }
  };
  function u0(t6) {
    return /\w/.test(t6);
  }
  function zr(t6) {
    return /[0-9]/.test(t6);
  }
  function _0(t6) {
    return /\s/.test(t6);
  }
  var oE = [["{%", M.OpenStatement], ["%}", M.CloseStatement], ["{{", M.OpenExpression], ["}}", M.CloseExpression], ["(", M.OpenParen], [")", M.CloseParen], ["{", M.OpenCurlyBracket], ["}", M.CloseCurlyBracket], ["[", M.OpenSquareBracket], ["]", M.CloseSquareBracket], [",", M.Comma], [".", M.Dot], [":", M.Colon], ["|", M.Pipe], ["<=", M.ComparisonBinaryOperator], [">=", M.ComparisonBinaryOperator], ["==", M.ComparisonBinaryOperator], ["!=", M.ComparisonBinaryOperator], ["<", M.ComparisonBinaryOperator], [">", M.ComparisonBinaryOperator], ["+", M.AdditiveBinaryOperator], ["-", M.AdditiveBinaryOperator], ["~", M.AdditiveBinaryOperator], ["*", M.MultiplicativeBinaryOperator], ["/", M.MultiplicativeBinaryOperator], ["%", M.MultiplicativeBinaryOperator], ["=", M.Equals]];
  var iE = /* @__PURE__ */ new Map([["n", `
`], ["t", "	"], ["r", "\r"], ["b", "\b"], ["f", "\f"], ["v", "\v"], ["'", "'"], ['"', '"'], ["\\", "\\"]]);
  function aE(t6, e = {}) {
    return t6.endsWith(`
`) && (t6 = t6.slice(0, -1)), e.lstrip_blocks && (t6 = t6.replace(/^[ \t]*({[#%-])/gm, "$1")), e.trim_blocks && (t6 = t6.replace(/([#%-]})\n/g, "$1")), t6.replace(/{%\s*(end)?generation\s*%}/gs, "");
  }
  function lE(t6, e = {}) {
    let s = [], r = aE(t6, e), n = 0, o = 0, i = (c) => {
      let p = "";
      for (; c(r[n]); ) {
        if (r[n] === "\\") {
          if (++n, n >= r.length) throw new SyntaxError("Unexpected end of input");
          let u = r[n++], _ = iE.get(u);
          if (_ === void 0) throw new SyntaxError(`Unexpected escaped character: ${u}`);
          p += _;
          continue;
        }
        if (p += r[n++], n >= r.length) throw new SyntaxError("Unexpected end of input");
      }
      return p;
    }, a = () => {
      let c = s.at(-1);
      c && c.type === M.Text && (c.value = c.value.trimEnd(), c.value === "" && s.pop());
    }, l = () => {
      for (; n < r.length && _0(r[n]); ) ++n;
    };
    e: for (; n < r.length; ) {
      let c = s.at(-1)?.type;
      if (c === void 0 || c === M.CloseStatement || c === M.CloseExpression || c === M.Comment) {
        let u = "";
        for (; n < r.length && !(r[n] === "{" && (r[n + 1] === "%" || r[n + 1] === "{" || r[n + 1] === "#")); ) u += r[n++];
        if (u.length > 0) {
          s.push(new Ze2(u, M.Text));
          continue;
        }
      }
      if (r[n] === "{" && r[n + 1] === "#") {
        n += 2;
        let u = r[n] === "-";
        u && ++n;
        let _ = "";
        for (; r[n] !== "#" || r[n + 1] !== "}"; ) {
          if (n + 2 >= r.length) throw new SyntaxError("Missing end of comment tag");
          _ += r[n++];
        }
        let d = _.endsWith("-");
        d && (_ = _.slice(0, -1)), u && a(), s.push(new Ze2(_, M.Comment)), n += 2, d && l();
        continue;
      }
      if (r.slice(n, n + 3) === "{%-") {
        a(), s.push(new Ze2("{%", M.OpenStatement)), n += 3;
        continue;
      }
      if (r.slice(n, n + 3) === "{{-") {
        a(), s.push(new Ze2("{{", M.OpenExpression)), o = 0, n += 3;
        continue;
      }
      if (i(_0), r.slice(n, n + 3) === "-%}") {
        s.push(new Ze2("%}", M.CloseStatement)), n += 3, l();
        continue;
      }
      if (r.slice(n, n + 3) === "-}}") {
        s.push(new Ze2("}}", M.CloseExpression)), n += 3, l();
        continue;
      }
      let p = r[n];
      if (p === "-" || p === "+") {
        let u = s.at(-1)?.type;
        if (u === M.Text || u === void 0) throw new SyntaxError(`Unexpected character: ${p}`);
        switch (u) {
          case M.Identifier:
          case M.NumericLiteral:
          case M.StringLiteral:
          case M.CloseParen:
          case M.CloseSquareBracket:
            break;
          default: {
            ++n;
            let _ = i(zr);
            s.push(new Ze2(`${p}${_}`, _.length > 0 ? M.NumericLiteral : M.UnaryOperator));
            continue;
          }
        }
      }
      for (let [u, _] of oE) {
        if (u === "}}" && o > 0) continue;
        if (r.slice(n, n + u.length) === u) {
          s.push(new Ze2(u, _)), _ === M.OpenExpression ? o = 0 : _ === M.OpenCurlyBracket ? ++o : _ === M.CloseCurlyBracket && --o, n += u.length;
          continue e;
        }
      }
      if (p === "'" || p === '"') {
        ++n;
        let u = i((_) => _ !== p);
        s.push(new Ze2(u, M.StringLiteral)), ++n;
        continue;
      }
      if (zr(p)) {
        let u = i(zr);
        if (r[n] === "." && zr(r[n + 1])) {
          ++n;
          let _ = i(zr);
          u = `${u}.${_}`;
        }
        s.push(new Ze2(u, M.NumericLiteral));
        continue;
      }
      if (u0(p)) {
        let u = i(u0);
        s.push(new Ze2(u, M.Identifier));
        continue;
      }
      throw new SyntaxError(`Unexpected character: ${p}`);
    }
    return s;
  }
  var it2 = class {
    type = "Statement";
  };
  var cE = class extends it2 {
    constructor(t6) {
      super(), this.body = t6;
    }
    type = "Program";
  };
  var pE = class extends it2 {
    constructor(t6, e, s) {
      super(), this.test = t6, this.body = e, this.alternate = s;
    }
    type = "If";
  };
  var uE = class extends it2 {
    constructor(t6, e, s, r) {
      super(), this.loopvar = t6, this.iterable = e, this.body = s, this.defaultBlock = r;
    }
    type = "For";
  };
  var _E = class extends it2 {
    type = "Break";
  };
  var dE = class extends it2 {
    type = "Continue";
  };
  var fE = class extends it2 {
    constructor(t6, e, s) {
      super(), this.assignee = t6, this.value = e, this.body = s;
    }
    type = "Set";
  };
  var mE = class extends it2 {
    constructor(t6, e, s) {
      super(), this.name = t6, this.args = e, this.body = s;
    }
    type = "Macro";
  };
  var hE = class extends it2 {
    constructor(t6) {
      super(), this.value = t6;
    }
    type = "Comment";
  };
  var Ke2 = class extends it2 {
    type = "Expression";
  };
  var gE = class extends Ke2 {
    constructor(t6, e, s) {
      super(), this.object = t6, this.property = e, this.computed = s;
    }
    type = "MemberExpression";
  };
  var d0 = class extends Ke2 {
    constructor(t6, e) {
      super(), this.callee = t6, this.args = e;
    }
    type = "CallExpression";
  };
  var Ts2 = class extends Ke2 {
    constructor(t6) {
      super(), this.value = t6;
    }
    type = "Identifier";
  };
  var Cs2 = class extends Ke2 {
    constructor(t6) {
      super(), this.value = t6;
    }
    type = "Literal";
  };
  var xE = class extends Cs2 {
    type = "IntegerLiteral";
  };
  var wE = class extends Cs2 {
    type = "FloatLiteral";
  };
  var f0 = class extends Cs2 {
    type = "StringLiteral";
  };
  var yE = class extends Cs2 {
    type = "ArrayLiteral";
  };
  var m0 = class extends Cs2 {
    type = "TupleLiteral";
  };
  var bE = class extends Cs2 {
    type = "ObjectLiteral";
  };
  var Tr = class extends Ke2 {
    constructor(t6, e, s) {
      super(), this.operator = t6, this.left = e, this.right = s;
    }
    type = "BinaryExpression";
  };
  var kE = class extends Ke2 {
    constructor(t6, e) {
      super(), this.operand = t6, this.filter = e;
    }
    type = "FilterExpression";
  };
  var vE = class extends it2 {
    constructor(t6, e) {
      super(), this.filter = t6, this.body = e;
    }
    type = "FilterStatement";
  };
  var EE = class extends Ke2 {
    constructor(t6, e) {
      super(), this.lhs = t6, this.test = e;
    }
    type = "SelectExpression";
  };
  var AE = class extends Ke2 {
    constructor(t6, e, s) {
      super(), this.operand = t6, this.negate = e, this.test = s;
    }
    type = "TestExpression";
  };
  var ME = class extends Ke2 {
    constructor(t6, e) {
      super(), this.operator = t6, this.argument = e;
    }
    type = "UnaryExpression";
  };
  var SE = class extends Ke2 {
    constructor(t6 = void 0, e = void 0, s = void 0) {
      super(), this.start = t6, this.stop = e, this.step = s;
    }
    type = "SliceExpression";
  };
  var OE = class extends Ke2 {
    constructor(t6, e) {
      super(), this.key = t6, this.value = e;
    }
    type = "KeywordArgumentExpression";
  };
  var IE = class extends Ke2 {
    constructor(t6) {
      super(), this.argument = t6;
    }
    type = "SpreadExpression";
  };
  var zE = class extends it2 {
    constructor(t6, e, s) {
      super(), this.call = t6, this.callerArgs = e, this.body = s;
    }
    type = "CallStatement";
  };
  var TE = class extends Ke2 {
    constructor(t6, e, s) {
      super(), this.condition = t6, this.trueExpr = e, this.falseExpr = s;
    }
    type = "Ternary";
  };
  function CE(t6) {
    let e = new cE([]), s = 0;
    function r(A, O) {
      let T = t6[s++];
      if (!T || T.type !== A) throw new Error(`Parser Error: ${O}. ${T.type} !== ${A}.`);
      return T;
    }
    function n(A) {
      if (!l(A)) throw new SyntaxError(`Expected ${A}`);
      ++s;
    }
    function o() {
      switch (t6[s].type) {
        case M.Comment:
          return new hE(t6[s++].value);
        case M.Text:
          return c();
        case M.OpenStatement:
          return p();
        case M.OpenExpression:
          return u();
        default:
          throw new SyntaxError(`Unexpected token type: ${t6[s].type}`);
      }
    }
    function i(...A) {
      return s + A.length <= t6.length && A.every((O, T) => O === t6[s + T].type);
    }
    function a(...A) {
      return t6[s]?.type === M.OpenStatement && t6[s + 1]?.type === M.Identifier && A.includes(t6[s + 1]?.value);
    }
    function l(...A) {
      return s + A.length <= t6.length && A.every((O, T) => t6[s + T].type === "Identifier" && O === t6[s + T].value);
    }
    function c() {
      return new f0(r(M.Text, "Expected text token").value);
    }
    function p() {
      if (r(M.OpenStatement, "Expected opening statement token"), t6[s].type !== M.Identifier) throw new SyntaxError(`Unknown statement, got ${t6[s].type}`);
      let A = t6[s].value, O;
      switch (A) {
        case "set":
          ++s, O = _();
          break;
        case "if":
          ++s, O = d(), r(M.OpenStatement, "Expected {% token"), n("endif"), r(M.CloseStatement, "Expected %} token");
          break;
        case "macro":
          ++s, O = m(), r(M.OpenStatement, "Expected {% token"), n("endmacro"), r(M.CloseStatement, "Expected %} token");
          break;
        case "for":
          ++s, O = g(), r(M.OpenStatement, "Expected {% token"), n("endfor"), r(M.CloseStatement, "Expected %} token");
          break;
        case "call": {
          ++s;
          let T = null;
          i(M.OpenParen) && (T = C());
          let G = D();
          if (G.type !== "Identifier") throw new SyntaxError("Expected identifier following call statement");
          let ee = C();
          r(M.CloseStatement, "Expected closing statement token");
          let $e2 = [];
          for (; !a("endcall"); ) $e2.push(o());
          r(M.OpenStatement, "Expected '{%'"), n("endcall"), r(M.CloseStatement, "Expected closing statement token");
          let re = new d0(G, ee);
          O = new zE(re, T, $e2);
          break;
        }
        case "break":
          ++s, r(M.CloseStatement, "Expected closing statement token"), O = new _E();
          break;
        case "continue":
          ++s, r(M.CloseStatement, "Expected closing statement token"), O = new dE();
          break;
        case "filter": {
          ++s;
          let T = D();
          T instanceof Ts2 && i(M.OpenParen) && (T = $2(T)), r(M.CloseStatement, "Expected closing statement token");
          let G = [];
          for (; !a("endfilter"); ) G.push(o());
          r(M.OpenStatement, "Expected '{%'"), n("endfilter"), r(M.CloseStatement, "Expected '%}'"), O = new vE(T, G);
          break;
        }
        default:
          throw new SyntaxError(`Unknown statement type: ${A}`);
      }
      return O;
    }
    function u() {
      r(M.OpenExpression, "Expected opening expression token");
      let A = w();
      return r(M.CloseExpression, "Expected closing expression token"), A;
    }
    function _() {
      let A = f(), O = null, T = [];
      if (i(M.Equals)) ++s, O = f();
      else {
        for (r(M.CloseStatement, "Expected %} token"); !a("endset"); ) T.push(o());
        r(M.OpenStatement, "Expected {% token"), n("endset");
      }
      return r(M.CloseStatement, "Expected closing statement token"), new fE(A, O, T);
    }
    function d() {
      let A = w();
      r(M.CloseStatement, "Expected closing statement token");
      let O = [], T = [];
      for (; !a("elif", "else", "endif"); ) O.push(o());
      if (a("elif")) {
        ++s, ++s;
        let G = d();
        T.push(G);
      } else if (a("else")) for (++s, ++s, r(M.CloseStatement, "Expected closing statement token"); !a("endif"); ) T.push(o());
      return new pE(A, O, T);
    }
    function m() {
      let A = D();
      if (A.type !== "Identifier") throw new SyntaxError("Expected identifier following macro statement");
      let O = C();
      r(M.CloseStatement, "Expected closing statement token");
      let T = [];
      for (; !a("endmacro"); ) T.push(o());
      return new mE(A, O, T);
    }
    function f(A = false) {
      let O = A ? D : w, T = [O()], G = i(M.Comma);
      for (; G && (++s, T.push(O()), !!i(M.Comma)); ) ;
      return G ? new m0(T) : T[0];
    }
    function g() {
      let A = f(true);
      if (!(A instanceof Ts2 || A instanceof m0)) throw new SyntaxError(`Expected identifier/tuple for the loop variable, got ${A.type} instead`);
      if (!l("in")) throw new SyntaxError("Expected `in` keyword following loop variable");
      ++s;
      let O = w();
      r(M.CloseStatement, "Expected closing statement token");
      let T = [];
      for (; !a("endfor", "else"); ) T.push(o());
      let G = [];
      if (a("else")) for (++s, ++s, r(M.CloseStatement, "Expected closing statement token"); !a("endfor"); ) G.push(o());
      return new uE(A, O, T, G);
    }
    function w() {
      return x();
    }
    function x() {
      let A = y();
      if (l("if")) {
        ++s;
        let O = y();
        if (l("else")) {
          ++s;
          let T = x();
          return new TE(O, A, T);
        } else return new EE(A, O);
      }
      return A;
    }
    function y() {
      let A = b();
      for (; l("or"); ) {
        let O = t6[s];
        ++s;
        let T = b();
        A = new Tr(O, A, T);
      }
      return A;
    }
    function b() {
      let A = v();
      for (; l("and"); ) {
        let O = t6[s];
        ++s;
        let T = v();
        A = new Tr(O, A, T);
      }
      return A;
    }
    function v() {
      let A;
      for (; l("not"); ) {
        let O = t6[s];
        ++s;
        let T = v();
        A = new ME(O, T);
      }
      return A ?? k2();
    }
    function k2() {
      let A = S();
      for (; ; ) {
        let O;
        if (l("not", "in")) O = new Ze2("not in", M.Identifier), s += 2;
        else if (l("in")) O = t6[s++];
        else if (i(M.ComparisonBinaryOperator)) O = t6[s++];
        else break;
        let T = S();
        A = new Tr(O, A, T);
      }
      return A;
    }
    function S() {
      let A = j();
      for (; i(M.AdditiveBinaryOperator); ) {
        let O = t6[s];
        ++s;
        let T = j();
        A = new Tr(O, A, T);
      }
      return A;
    }
    function I() {
      let A = H(D());
      return i(M.OpenParen) ? $2(A) : A;
    }
    function $2(A) {
      let O = new d0(A, C());
      return O = H(O), i(M.OpenParen) && (O = $2(O)), O;
    }
    function C() {
      r(M.OpenParen, "Expected opening parenthesis for arguments list");
      let A = R();
      return r(M.CloseParen, "Expected closing parenthesis for arguments list"), A;
    }
    function R() {
      let A = [];
      for (; !i(M.CloseParen); ) {
        let O;
        if (t6[s].type === M.MultiplicativeBinaryOperator && t6[s].value === "*") {
          ++s;
          let T = w();
          O = new IE(T);
        } else if (O = w(), i(M.Equals)) {
          if (++s, !(O instanceof Ts2)) throw new SyntaxError("Expected identifier for keyword argument");
          let T = w();
          O = new OE(O, T);
        }
        A.push(O), i(M.Comma) && ++s;
      }
      return A;
    }
    function V() {
      let A = [], O = false;
      for (; !i(M.CloseSquareBracket); ) i(M.Colon) ? (A.push(void 0), ++s, O = true) : (A.push(w()), i(M.Colon) && (++s, O = true));
      if (A.length === 0) throw new SyntaxError("Expected at least one argument for member/slice expression");
      if (O) {
        if (A.length > 3) throw new SyntaxError("Expected 0-3 arguments for slice expression");
        return new SE(...A);
      }
      return A[0];
    }
    function H(A) {
      for (; i(M.Dot) || i(M.OpenSquareBracket); ) {
        let O = t6[s];
        ++s;
        let T, G = O.type === M.OpenSquareBracket;
        if (G) T = V(), r(M.CloseSquareBracket, "Expected closing square bracket");
        else if (T = D(), T.type !== "Identifier") throw new SyntaxError("Expected identifier following dot operator");
        A = new gE(A, T, G);
      }
      return A;
    }
    function j() {
      let A = B();
      for (; i(M.MultiplicativeBinaryOperator); ) {
        let O = t6[s++], T = B();
        A = new Tr(O, A, T);
      }
      return A;
    }
    function B() {
      let A = Z();
      for (; l("is"); ) {
        ++s;
        let O = l("not");
        O && ++s;
        let T = D();
        if (!(T instanceof Ts2)) throw new SyntaxError("Expected identifier for the test");
        A = new AE(A, O, T);
      }
      return A;
    }
    function Z() {
      let A = I();
      for (; i(M.Pipe); ) {
        ++s;
        let O = D();
        if (!(O instanceof Ts2)) throw new SyntaxError("Expected identifier for the filter");
        i(M.OpenParen) && (O = $2(O)), A = new kE(A, O);
      }
      return A;
    }
    function D() {
      let A = t6[s++];
      switch (A.type) {
        case M.NumericLiteral: {
          let O = A.value;
          return O.includes(".") ? new wE(Number(O)) : new xE(Number(O));
        }
        case M.StringLiteral: {
          let O = A.value;
          for (; i(M.StringLiteral); ) O += t6[s++].value;
          return new f0(O);
        }
        case M.Identifier:
          return new Ts2(A.value);
        case M.OpenParen: {
          let O = f();
          return r(M.CloseParen, "Expected closing parenthesis, got ${tokens[current].type} instead."), O;
        }
        case M.OpenSquareBracket: {
          let O = [];
          for (; !i(M.CloseSquareBracket); ) O.push(w()), i(M.Comma) && ++s;
          return ++s, new yE(O);
        }
        case M.OpenCurlyBracket: {
          let O = /* @__PURE__ */ new Map();
          for (; !i(M.CloseCurlyBracket); ) {
            let T = w();
            r(M.Colon, "Expected colon between key and value in object literal");
            let G = w();
            O.set(T, G), i(M.Comma) && ++s;
          }
          return ++s, new bE(O);
        }
        default:
          throw new SyntaxError(`Unexpected token: ${A.type}`);
      }
    }
    for (; s < t6.length; ) e.body.push(o());
    return e;
  }
  function PE(t6, e, s = 1) {
    if (e === void 0 && (e = t6, t6 = 0), s === 0) throw new Error("range() step must not be zero");
    let r = [];
    if (s > 0) for (let n = t6; n < e; n += s) r.push(n);
    else for (let n = t6; n > e; n += s) r.push(n);
    return r;
  }
  function h0(t6, e, s, r = 1) {
    let n = Math.sign(r);
    n >= 0 ? (e = (e ??= 0) < 0 ? Math.max(t6.length + e, 0) : Math.min(e, t6.length), s = (s ??= t6.length) < 0 ? Math.max(t6.length + s, 0) : Math.min(s, t6.length)) : (e = (e ??= t6.length - 1) < 0 ? Math.max(t6.length + e, -1) : Math.min(e, t6.length - 1), s = (s ??= -1) < -1 ? Math.max(t6.length + s, -1) : Math.min(s, t6.length - 1));
    let o = [];
    for (let i = e; n * i < n * s; i += r) o.push(t6[i]);
    return o;
  }
  function NE(t6) {
    return t6.replace(/\b\w/g, (e) => e.toUpperCase());
  }
  function LE(t6) {
    return $E(/* @__PURE__ */ new Date(), t6);
  }
  function $E(t6, e) {
    let s = new Intl.DateTimeFormat(void 0, { month: "long" }), r = new Intl.DateTimeFormat(void 0, { month: "short" }), n = (o) => o < 10 ? "0" + o : o.toString();
    return e.replace(/%[YmdbBHM%]/g, (o) => {
      switch (o) {
        case "%Y":
          return t6.getFullYear().toString();
        case "%m":
          return n(t6.getMonth() + 1);
        case "%d":
          return n(t6.getDate());
        case "%b":
          return r.format(t6);
        case "%B":
          return s.format(t6);
        case "%H":
          return n(t6.getHours());
        case "%M":
          return n(t6.getMinutes());
        case "%%":
          return "%";
        default:
          return o;
      }
    });
  }
  function FE(t6) {
    return t6.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  function RE(t6, e, s, r) {
    if (r === 0) return t6;
    let n = r == null || r < 0 ? 1 / 0 : r, o = e.length === 0 ? new RegExp("(?=)", "gu") : new RegExp(FE(e), "gu");
    return t6.replaceAll(o, (i) => n > 0 ? (--n, s) : i);
  }
  var g0 = class extends Error {
  };
  var x0 = class extends Error {
  };
  var dt = class {
    type = "RuntimeValue";
    value;
    builtins = /* @__PURE__ */ new Map();
    constructor(t6 = void 0) {
      this.value = t6;
    }
    __bool__() {
      return new Q(!!this.value);
    }
    toString() {
      return String(this.value);
    }
  };
  var te = class extends dt {
    type = "IntegerValue";
  };
  var Ae = class extends dt {
    type = "FloatValue";
    toString() {
      return this.value % 1 === 0 ? this.value.toFixed(1) : this.value.toString();
    }
  };
  var q = class extends dt {
    type = "StringValue";
    builtins = /* @__PURE__ */ new Map([["upper", new be2(() => new q(this.value.toUpperCase()))], ["lower", new be2(() => new q(this.value.toLowerCase()))], ["strip", new be2(() => new q(this.value.trim()))], ["title", new be2(() => new q(NE(this.value)))], ["capitalize", new be2(() => new q(this.value.charAt(0).toUpperCase() + this.value.slice(1)))], ["length", new te(this.value.length)], ["rstrip", new be2(() => new q(this.value.trimEnd()))], ["lstrip", new be2(() => new q(this.value.trimStart()))], ["startswith", new be2((t6) => {
      if (t6.length === 0) throw new Error("startswith() requires at least one argument");
      let e = t6[0];
      if (e instanceof q) return new Q(this.value.startsWith(e.value));
      if (e instanceof oe) {
        for (let s of e.value) {
          if (!(s instanceof q)) throw new Error("startswith() tuple elements must be strings");
          if (this.value.startsWith(s.value)) return new Q(true);
        }
        return new Q(false);
      }
      throw new Error("startswith() argument must be a string or tuple of strings");
    })], ["endswith", new be2((t6) => {
      if (t6.length === 0) throw new Error("endswith() requires at least one argument");
      let e = t6[0];
      if (e instanceof q) return new Q(this.value.endsWith(e.value));
      if (e instanceof oe) {
        for (let s of e.value) {
          if (!(s instanceof q)) throw new Error("endswith() tuple elements must be strings");
          if (this.value.endsWith(s.value)) return new Q(true);
        }
        return new Q(false);
      }
      throw new Error("endswith() argument must be a string or tuple of strings");
    })], ["split", new be2((t6) => {
      let e = t6[0] ?? new ke();
      if (!(e instanceof q || e instanceof ke)) throw new Error("sep argument must be a string or null");
      let s = t6[1] ?? new te(-1);
      if (!(s instanceof te)) throw new Error("maxsplit argument must be a number");
      let r = [];
      if (e instanceof ke) {
        let n = this.value.trimStart();
        for (let { 0: o, index: i } of n.matchAll(/\S+/g)) {
          if (s.value !== -1 && r.length >= s.value && i !== void 0) {
            r.push(o + n.slice(i + o.length));
            break;
          }
          r.push(o);
        }
      } else {
        if (e.value === "") throw new Error("empty separator");
        r = this.value.split(e.value), s.value !== -1 && r.length > s.value && r.push(r.splice(s.value).join(e.value));
      }
      return new oe(r.map((n) => new q(n)));
    })], ["replace", new be2((t6) => {
      if (t6.length < 2) throw new Error("replace() requires at least two arguments");
      let e = t6[0], s = t6[1];
      if (!(e instanceof q && s instanceof q)) throw new Error("replace() arguments must be strings");
      let r;
      if (t6.length > 2 ? t6[2].type === "KeywordArgumentsValue" ? r = t6[2].value.get("count") ?? new ke() : r = t6[2] : r = new ke(), !(r instanceof te || r instanceof ke)) throw new Error("replace() count argument must be a number or null");
      return new q(RE(this.value, e.value, s.value, r.value));
    })]]);
  };
  var Q = class extends dt {
    type = "BooleanValue";
  };
  var DE = /[\x7f-\uffff]/g;
  function w0(t6) {
    return t6.replace(DE, (e) => "\\u" + e.charCodeAt(0).toString(16).padStart(4, "0"));
  }
  function rs2(t6, e = {}, s = 0, r = true) {
    let { indent: n = null, ensureAscii: o = false, separators: i = null, sortKeys: a = false } = e, l, c;
    switch (i ? [l, c] = i : n ? (l = ",", c = ": ") : (l = ", ", c = ": "), t6.type) {
      case "NullValue":
        return "null";
      case "UndefinedValue":
        return r ? "null" : "undefined";
      case "IntegerValue":
      case "FloatValue":
      case "BooleanValue":
        return JSON.stringify(t6.value);
      case "StringValue": {
        let p = JSON.stringify(t6.value);
        return o && (p = w0(p)), p;
      }
      case "ArrayValue":
      case "ObjectValue": {
        let p = n ? " ".repeat(n) : "", u = `
` + p.repeat(s), _ = u + p;
        if (t6.type === "ArrayValue") {
          let d = t6.value.map((m) => rs2(m, e, s + 1, r));
          return n ? `[${_}${d.join(`${l}${_}`)}${u}]` : `[${d.join(l)}]`;
        } else {
          let d = Array.from(t6.value.entries());
          a && (d = d.sort(([f], [g]) => f.localeCompare(g)));
          let m = d.map(([f, g]) => {
            let w = JSON.stringify(f);
            o && (w = w0(w));
            let x = `${w}${c}${rs2(g, e, s + 1, r)}`;
            return n ? `${_}${x}` : x;
          });
          return n ? `{${m.join(l)}${u}}` : `{${m.join(l)}}`;
        }
      }
      default:
        throw new Error(`Cannot convert to JSON: ${t6.type}`);
    }
  }
  var Ne = class extends dt {
    type = "ObjectValue";
    __bool__() {
      return new Q(this.value.size > 0);
    }
    builtins = /* @__PURE__ */ new Map([["get", new be2(([t6, e]) => {
      if (!(t6 instanceof q)) throw new Error(`Object key must be a string: got ${t6.type}`);
      return this.value.get(t6.value) ?? e ?? new ke();
    })], ["items", new be2(() => this.items())], ["keys", new be2(() => this.keys())], ["values", new be2(() => this.values())], ["dictsort", new be2((t6) => {
      let e = /* @__PURE__ */ new Map(), s = t6.filter((a) => a instanceof Cr ? (e = a.value, false) : true), r = s.at(0) ?? e.get("case_sensitive") ?? new Q(false);
      if (!(r instanceof Q)) throw new Error("case_sensitive must be a boolean");
      let n = s.at(1) ?? e.get("by") ?? new q("key");
      if (!(n instanceof q)) throw new Error("by must be a string");
      if (!["key", "value"].includes(n.value)) throw new Error("by must be either 'key' or 'value'");
      let o = s.at(2) ?? e.get("reverse") ?? new Q(false);
      if (!(o instanceof Q)) throw new Error("reverse must be a boolean");
      let i = Array.from(this.value.entries()).map(([a, l]) => new oe([new q(a), l])).sort((a, l) => {
        let c = n.value === "key" ? 0 : 1, p = a.value[c], u = l.value[c], _ = Yc(p, u, r.value);
        return o.value ? -_ : _;
      });
      return new oe(i);
    })]]);
    items() {
      return new oe(Array.from(this.value.entries()).map(([t6, e]) => new oe([new q(t6), e])));
    }
    keys() {
      return new oe(Array.from(this.value.keys()).map((t6) => new q(t6)));
    }
    values() {
      return new oe(Array.from(this.value.values()));
    }
    toString() {
      return rs2(this, {}, 0, false);
    }
  };
  var Cr = class extends Ne {
    type = "KeywordArgumentsValue";
  };
  var oe = class extends dt {
    type = "ArrayValue";
    builtins = /* @__PURE__ */ new Map([["length", new te(this.value.length)]]);
    __bool__() {
      return new Q(this.value.length > 0);
    }
    toString() {
      return rs2(this, {}, 0, false);
    }
  };
  var y0 = class extends oe {
    type = "TupleValue";
  };
  var be2 = class extends dt {
    type = "FunctionValue";
  };
  var ke = class extends dt {
    type = "NullValue";
  };
  var ye = class extends dt {
    type = "UndefinedValue";
  };
  var ss2 = class {
    constructor(t6) {
      this.parent = t6;
    }
    variables = /* @__PURE__ */ new Map([["namespace", new be2((t6) => {
      if (t6.length === 0) return new Ne(/* @__PURE__ */ new Map());
      if (t6.length !== 1 || !(t6[0] instanceof Ne)) throw new Error("`namespace` expects either zero arguments or a single object argument");
      return t6[0];
    })]]);
    tests = /* @__PURE__ */ new Map([["boolean", (t6) => t6.type === "BooleanValue"], ["callable", (t6) => t6 instanceof be2], ["odd", (t6) => {
      if (!(t6 instanceof te)) throw new Error(`cannot odd on ${t6.type}`);
      return t6.value % 2 !== 0;
    }], ["even", (t6) => {
      if (!(t6 instanceof te)) throw new Error(`cannot even on ${t6.type}`);
      return t6.value % 2 === 0;
    }], ["false", (t6) => t6.type === "BooleanValue" && !t6.value], ["true", (t6) => t6.type === "BooleanValue" && t6.value], ["none", (t6) => t6.type === "NullValue"], ["string", (t6) => t6.type === "StringValue"], ["number", (t6) => t6 instanceof te || t6 instanceof Ae], ["integer", (t6) => t6 instanceof te], ["iterable", (t6) => t6.type === "ArrayValue" || t6.type === "StringValue"], ["mapping", (t6) => t6 instanceof Ne], ["sequence", (t6) => t6 instanceof oe || t6 instanceof Ne || t6 instanceof q], ["lower", (t6) => {
      let e = t6.value;
      return t6.type === "StringValue" && e === e.toLowerCase();
    }], ["upper", (t6) => {
      let e = t6.value;
      return t6.type === "StringValue" && e === e.toUpperCase();
    }], ["none", (t6) => t6.type === "NullValue"], ["defined", (t6) => t6.type !== "UndefinedValue"], ["undefined", (t6) => t6.type === "UndefinedValue"], ["equalto", (t6, e) => t6.value === e.value], ["eq", (t6, e) => t6.value === e.value]]);
    set(t6, e) {
      return this.declareVariable(t6, pa(e));
    }
    declareVariable(t6, e) {
      if (this.variables.has(t6)) throw new SyntaxError(`Variable already declared: ${t6}`);
      return this.variables.set(t6, e), e;
    }
    setVariable(t6, e) {
      return this.variables.set(t6, e), e;
    }
    resolve(t6) {
      if (this.variables.has(t6)) return this;
      if (this.parent) return this.parent.resolve(t6);
      throw new Error(`Unknown variable: ${t6}`);
    }
    lookupVariable(t6) {
      try {
        return this.resolve(t6).variables.get(t6) ?? new ye();
      } catch {
        return new ye();
      }
    }
  };
  function qE(t6) {
    t6.set("false", false), t6.set("true", true), t6.set("none", null), t6.set("raise_exception", (e) => {
      throw new Error(e);
    }), t6.set("range", PE), t6.set("strftime_now", LE), t6.set("True", true), t6.set("False", false), t6.set("None", null);
  }
  function b0(t6, e) {
    let s = e.split("."), r = t6;
    for (let n of s) if (r instanceof Ne) r = r.value.get(n) ?? new ye();
    else if (r instanceof oe) {
      let o = parseInt(n, 10);
      if (!isNaN(o) && o >= 0 && o < r.value.length) r = r.value[o];
      else return new ye();
    } else return new ye();
    return r;
  }
  function Yc(t6, e, s = false) {
    if (t6 instanceof ke && e instanceof ke) return 0;
    if (t6 instanceof ke || e instanceof ke) throw new Error(`Cannot compare ${t6.type} with ${e.type}`);
    if (t6 instanceof ye && e instanceof ye) return 0;
    if (t6 instanceof ye || e instanceof ye) throw new Error(`Cannot compare ${t6.type} with ${e.type}`);
    let r = (o) => o instanceof te || o instanceof Ae || o instanceof Q, n = (o) => o instanceof Q ? o.value ? 1 : 0 : o.value;
    if (r(t6) && r(e)) {
      let o = n(t6), i = n(e);
      return o < i ? -1 : o > i ? 1 : 0;
    }
    if (t6.type !== e.type) throw new Error(`Cannot compare different types: ${t6.type} and ${e.type}`);
    if (t6.type === "StringValue") {
      let o = t6.value, i = e.value;
      return s || (o = o.toLowerCase(), i = i.toLowerCase()), o < i ? -1 : o > i ? 1 : 0;
    } else throw new Error(`Cannot compare type: ${t6.type}`);
  }
  var jE = class {
    global;
    constructor(t6) {
      this.global = t6 ?? new ss2();
    }
    run(t6) {
      return this.evaluate(t6, this.global);
    }
    evaluateBinaryExpression(t6, e) {
      let s = this.evaluate(t6.left, e);
      switch (t6.operator.value) {
        case "and":
          return s.__bool__().value ? this.evaluate(t6.right, e) : s;
        case "or":
          return s.__bool__().value ? s : this.evaluate(t6.right, e);
      }
      let r = this.evaluate(t6.right, e);
      switch (t6.operator.value) {
        case "==":
          return new Q(s.value == r.value);
        case "!=":
          return new Q(s.value != r.value);
      }
      if (s instanceof ye || r instanceof ye) {
        if (r instanceof ye && ["in", "not in"].includes(t6.operator.value)) return new Q(t6.operator.value === "not in");
        throw new Error(`Cannot perform operation ${t6.operator.value} on undefined values`);
      } else {
        if (s instanceof ke || r instanceof ke) throw new Error("Cannot perform operation on null values");
        if (t6.operator.value === "~") return new q(s.value.toString() + r.value.toString());
        if ((s instanceof te || s instanceof Ae) && (r instanceof te || r instanceof Ae)) {
          let n = s.value, o = r.value;
          switch (t6.operator.value) {
            case "+":
            case "-":
            case "*": {
              let i = t6.operator.value === "+" ? n + o : t6.operator.value === "-" ? n - o : n * o;
              return s instanceof Ae || r instanceof Ae ? new Ae(i) : new te(i);
            }
            case "/":
              return new Ae(n / o);
            case "%": {
              let i = n % o;
              return s instanceof Ae || r instanceof Ae ? new Ae(i) : new te(i);
            }
            case "<":
              return new Q(n < o);
            case ">":
              return new Q(n > o);
            case ">=":
              return new Q(n >= o);
            case "<=":
              return new Q(n <= o);
          }
        } else if (s instanceof oe && r instanceof oe) {
          if (t6.operator.value === "+") return new oe(s.value.concat(r.value));
        } else if (r instanceof oe) {
          let n = r.value.find((o) => o.value === s.value) !== void 0;
          switch (t6.operator.value) {
            case "in":
              return new Q(n);
            case "not in":
              return new Q(!n);
          }
        }
      }
      if ((s instanceof q || r instanceof q) && t6.operator.value === "+") return new q(s.value.toString() + r.value.toString());
      if (s instanceof q && r instanceof q) switch (t6.operator.value) {
        case "in":
          return new Q(r.value.includes(s.value));
        case "not in":
          return new Q(!r.value.includes(s.value));
      }
      if (s instanceof q && r instanceof Ne) switch (t6.operator.value) {
        case "in":
          return new Q(r.value.has(s.value));
        case "not in":
          return new Q(!r.value.has(s.value));
      }
      throw new SyntaxError(`Unknown operator "${t6.operator.value}" between ${s.type} and ${r.type}`);
    }
    evaluateArguments(t6, e) {
      let s = [], r = /* @__PURE__ */ new Map();
      for (let n of t6) if (n.type === "SpreadExpression") {
        let o = n, i = this.evaluate(o.argument, e);
        if (!(i instanceof oe)) throw new Error(`Cannot unpack non-iterable type: ${i.type}`);
        for (let a of i.value) s.push(a);
      } else if (n.type === "KeywordArgumentExpression") {
        let o = n;
        r.set(o.key.value, this.evaluate(o.value, e));
      } else {
        if (r.size > 0) throw new Error("Positional arguments must come before keyword arguments");
        s.push(this.evaluate(n, e));
      }
      return [s, r];
    }
    applyFilter(t6, e, s) {
      if (e.type === "Identifier") {
        let r = e;
        if (r.value === "safe") return t6;
        if (r.value === "tojson") return new q(rs2(t6, {}));
        if (t6 instanceof oe) switch (r.value) {
          case "list":
            return t6;
          case "first":
            return t6.value[0];
          case "last":
            return t6.value[t6.value.length - 1];
          case "length":
            return new te(t6.value.length);
          case "reverse":
            return new oe(t6.value.slice().reverse());
          case "sort":
            return new oe(t6.value.slice().sort((n, o) => Yc(n, o, false)));
          case "join":
            return new q(t6.value.map((n) => n.value).join(""));
          case "string":
            return new q(rs2(t6, {}, 0, false));
          case "unique": {
            let n = /* @__PURE__ */ new Set(), o = [];
            for (let i of t6.value) n.has(i.value) || (n.add(i.value), o.push(i));
            return new oe(o);
          }
          default:
            throw new Error(`Unknown ArrayValue filter: ${r.value}`);
        }
        else if (t6 instanceof q) switch (r.value) {
          case "length":
          case "upper":
          case "lower":
          case "title":
          case "capitalize": {
            let n = t6.builtins.get(r.value);
            if (n instanceof be2) return n.value([], s);
            if (n instanceof te) return n;
            throw new Error(`Unknown StringValue filter: ${r.value}`);
          }
          case "trim":
            return new q(t6.value.trim());
          case "indent":
            return new q(t6.value.split(`
`).map((n, o) => o === 0 || n.length === 0 ? n : "    " + n).join(`
`));
          case "join":
          case "string":
            return t6;
          case "int": {
            let n = parseInt(t6.value, 10);
            return new te(isNaN(n) ? 0 : n);
          }
          case "float": {
            let n = parseFloat(t6.value);
            return new Ae(isNaN(n) ? 0 : n);
          }
          default:
            throw new Error(`Unknown StringValue filter: ${r.value}`);
        }
        else if (t6 instanceof te || t6 instanceof Ae) switch (r.value) {
          case "abs":
            return t6 instanceof te ? new te(Math.abs(t6.value)) : new Ae(Math.abs(t6.value));
          case "int":
            return new te(Math.floor(t6.value));
          case "float":
            return new Ae(t6.value);
          case "string":
            return new q(t6.toString());
          default:
            throw new Error(`Unknown NumericValue filter: ${r.value}`);
        }
        else if (t6 instanceof Ne) switch (r.value) {
          case "items":
            return new oe(Array.from(t6.value.entries()).map(([n, o]) => new oe([new q(n), o])));
          case "length":
            return new te(t6.value.size);
          default: {
            let n = t6.builtins.get(r.value);
            if (n) return n instanceof be2 ? n.value([], s) : n;
            throw new Error(`Unknown ObjectValue filter: ${r.value}`);
          }
        }
        else if (t6 instanceof Q) switch (r.value) {
          case "bool":
            return new Q(t6.value);
          case "int":
            return new te(t6.value ? 1 : 0);
          case "float":
            return new Ae(t6.value ? 1 : 0);
          case "string":
            return new q(t6.value ? "true" : "false");
          default:
            throw new Error(`Unknown BooleanValue filter: ${r.value}`);
        }
        throw new Error(`Cannot apply filter "${r.value}" to type: ${t6.type}`);
      } else if (e.type === "CallExpression") {
        let r = e;
        if (r.callee.type !== "Identifier") throw new Error(`Unknown filter: ${r.callee.type}`);
        let n = r.callee.value;
        if (n === "tojson") {
          let [, o] = this.evaluateArguments(r.args, s), i = o.get("indent") ?? new ke();
          if (!(i instanceof te || i instanceof ke)) throw new Error("If set, indent must be a number");
          let a = o.get("ensure_ascii") ?? new Q(false);
          if (!(a instanceof Q)) throw new Error("If set, ensure_ascii must be a boolean");
          let l = o.get("sort_keys") ?? new Q(false);
          if (!(l instanceof Q)) throw new Error("If set, sort_keys must be a boolean");
          let c = o.get("separators") ?? new ke(), p = null;
          if (c instanceof oe || c instanceof y0) {
            if (c.value.length !== 2) throw new Error("separators must be a tuple of two strings");
            let [u, _] = c.value;
            if (!(u instanceof q) || !(_ instanceof q)) throw new Error("separators must be a tuple of two strings");
            p = [u.value, _.value];
          } else if (!(c instanceof ke)) throw new Error("If set, separators must be a tuple of two strings");
          return new q(rs2(t6, { indent: i.value, ensureAscii: a.value, sortKeys: l.value, separators: p }));
        } else if (n === "join") {
          let o;
          if (t6 instanceof q) o = Array.from(t6.value);
          else if (t6 instanceof oe) o = t6.value.map((c) => c.value);
          else throw new Error(`Cannot apply filter "${n}" to type: ${t6.type}`);
          let [i, a] = this.evaluateArguments(r.args, s), l = i.at(0) ?? a.get("separator") ?? new q("");
          if (!(l instanceof q)) throw new Error("separator must be a string");
          return new q(o.join(l.value));
        } else if (n === "int" || n === "float") {
          let [o, i] = this.evaluateArguments(r.args, s), a = o.at(0) ?? i.get("default") ?? (n === "int" ? new te(0) : new Ae(0));
          if (t6 instanceof q) {
            let l = n === "int" ? parseInt(t6.value, 10) : parseFloat(t6.value);
            return isNaN(l) ? a : n === "int" ? new te(l) : new Ae(l);
          } else {
            if (t6 instanceof te || t6 instanceof Ae) return t6;
            if (t6 instanceof Q) return n === "int" ? new te(t6.value ? 1 : 0) : new Ae(t6.value ? 1 : 0);
            throw new Error(`Cannot apply filter "${n}" to type: ${t6.type}`);
          }
        } else if (n === "default") {
          let [o, i] = this.evaluateArguments(r.args, s), a = o[0] ?? new q(""), l = o[1] ?? i.get("boolean") ?? new Q(false);
          if (!(l instanceof Q)) throw new Error("`default` filter flag must be a boolean");
          return t6 instanceof ye || l.value && !t6.__bool__().value ? a : t6;
        }
        if (t6 instanceof oe) {
          switch (n) {
            case "sort": {
              let [o, i] = this.evaluateArguments(r.args, s), a = o.at(0) ?? i.get("reverse") ?? new Q(false);
              if (!(a instanceof Q)) throw new Error("reverse must be a boolean");
              let l = o.at(1) ?? i.get("case_sensitive") ?? new Q(false);
              if (!(l instanceof Q)) throw new Error("case_sensitive must be a boolean");
              let c = o.at(2) ?? i.get("attribute") ?? new ke();
              if (!(c instanceof q || c instanceof te || c instanceof ke)) throw new Error("attribute must be a string, integer, or null");
              let p = (u) => {
                if (c instanceof ke) return u;
                let _ = c instanceof te ? String(c.value) : c.value;
                return b0(u, _);
              };
              return new oe(t6.value.slice().sort((u, _) => {
                let d = p(u), m = p(_), f = Yc(d, m, l.value);
                return a.value ? -f : f;
              }));
            }
            case "selectattr":
            case "rejectattr": {
              let o = n === "selectattr";
              if (t6.value.some((u) => !(u instanceof Ne))) throw new Error(`\`${n}\` can only be applied to array of objects`);
              if (r.args.some((u) => u.type !== "StringLiteral")) throw new Error(`arguments of \`${n}\` must be strings`);
              let [i, a, l] = r.args.map((u) => this.evaluate(u, s)), c;
              if (a) {
                let u = s.tests.get(a.value);
                if (!u) throw new Error(`Unknown test: ${a.value}`);
                c = u;
              } else c = (...u) => u[0].__bool__().value;
              let p = t6.value.filter((u) => {
                let _ = u.value.get(i.value), d = _ ? c(_, l) : false;
                return o ? d : !d;
              });
              return new oe(p);
            }
            case "map": {
              let [, o] = this.evaluateArguments(r.args, s);
              if (o.has("attribute")) {
                let i = o.get("attribute");
                if (!(i instanceof q)) throw new Error("attribute must be a string");
                let a = o.get("default"), l = t6.value.map((c) => {
                  if (!(c instanceof Ne)) throw new Error("items in map must be an object");
                  let p = b0(c, i.value);
                  return p instanceof ye ? a ?? new ye() : p;
                });
                return new oe(l);
              } else throw new Error("`map` expressions without `attribute` set are not currently supported.");
            }
          }
          throw new Error(`Unknown ArrayValue filter: ${n}`);
        } else if (t6 instanceof q) {
          switch (n) {
            case "indent": {
              let [o, i] = this.evaluateArguments(r.args, s), a = o.at(0) ?? i.get("width") ?? new te(4);
              if (!(a instanceof te)) throw new Error("width must be a number");
              let l = o.at(1) ?? i.get("first") ?? new Q(false), c = o.at(2) ?? i.get("blank") ?? new Q(false), p = t6.value.split(`
`), u = " ".repeat(a.value), _ = p.map((d, m) => !l.value && m === 0 || !c.value && d.length === 0 ? d : u + d);
              return new q(_.join(`
`));
            }
            case "replace": {
              let o = t6.builtins.get("replace");
              if (!(o instanceof be2)) throw new Error("replace filter not available");
              let [i, a] = this.evaluateArguments(r.args, s);
              return o.value([...i, new Cr(a)], s);
            }
          }
          throw new Error(`Unknown StringValue filter: ${n}`);
        } else if (t6 instanceof Ne) {
          let o = t6.builtins.get(n);
          if (o && o instanceof be2) {
            let [i, a] = this.evaluateArguments(r.args, s);
            return a.size > 0 && i.push(new Cr(a)), o.value(i, s);
          }
          throw new Error(`Unknown ObjectValue filter: ${n}`);
        } else throw new Error(`Cannot apply filter "${n}" to type: ${t6.type}`);
      }
      throw new Error(`Unknown filter: ${e.type}`);
    }
    evaluateFilterExpression(t6, e) {
      let s = this.evaluate(t6.operand, e);
      return this.applyFilter(s, t6.filter, e);
    }
    evaluateTestExpression(t6, e) {
      let s = this.evaluate(t6.operand, e), r = e.tests.get(t6.test.value);
      if (!r) throw new Error(`Unknown test: ${t6.test.value}`);
      let n = r(s);
      return new Q(t6.negate ? !n : n);
    }
    evaluateSelectExpression(t6, e) {
      return this.evaluate(t6.test, e).__bool__().value ? this.evaluate(t6.lhs, e) : new ye();
    }
    evaluateUnaryExpression(t6, e) {
      let s = this.evaluate(t6.argument, e);
      if (t6.operator.value === "not") return new Q(!s.value);
      throw new SyntaxError(`Unknown operator: ${t6.operator.value}`);
    }
    evaluateTernaryExpression(t6, e) {
      return this.evaluate(t6.condition, e).__bool__().value ? this.evaluate(t6.trueExpr, e) : this.evaluate(t6.falseExpr, e);
    }
    evalProgram(t6, e) {
      return this.evaluateBlock(t6.body, e);
    }
    evaluateBlock(t6, e) {
      let s = "";
      for (let r of t6) {
        let n = this.evaluate(r, e);
        n.type !== "NullValue" && n.type !== "UndefinedValue" && (s += n.toString());
      }
      return new q(s);
    }
    evaluateIdentifier(t6, e) {
      return e.lookupVariable(t6.value);
    }
    evaluateCallExpression(t6, e) {
      let [s, r] = this.evaluateArguments(t6.args, e);
      r.size > 0 && s.push(new Cr(r));
      let n = this.evaluate(t6.callee, e);
      if (n.type !== "FunctionValue") throw new Error(`Cannot call something that is not a function: got ${n.type}`);
      return n.value(s, e);
    }
    evaluateSliceExpression(t6, e, s) {
      if (!(t6 instanceof oe || t6 instanceof q)) throw new Error("Slice object must be an array or string");
      let r = this.evaluate(e.start, s), n = this.evaluate(e.stop, s), o = this.evaluate(e.step, s);
      if (!(r instanceof te || r instanceof ye)) throw new Error("Slice start must be numeric or undefined");
      if (!(n instanceof te || n instanceof ye)) throw new Error("Slice stop must be numeric or undefined");
      if (!(o instanceof te || o instanceof ye)) throw new Error("Slice step must be numeric or undefined");
      return t6 instanceof oe ? new oe(h0(t6.value, r.value, n.value, o.value)) : new q(h0(Array.from(t6.value), r.value, n.value, o.value).join(""));
    }
    evaluateMemberExpression(t6, e) {
      let s = this.evaluate(t6.object, e), r;
      if (t6.computed) {
        if (t6.property.type === "SliceExpression") return this.evaluateSliceExpression(s, t6.property, e);
        r = this.evaluate(t6.property, e);
      } else r = new q(t6.property.value);
      let n;
      if (s instanceof Ne) {
        if (!(r instanceof q)) throw new Error(`Cannot access property with non-string: got ${r.type}`);
        n = s.value.get(r.value) ?? s.builtins.get(r.value);
      } else if (s instanceof oe || s instanceof q) if (r instanceof te) n = s.value.at(r.value), s instanceof q && (n = new q(s.value.at(r.value)));
      else if (r instanceof q) n = s.builtins.get(r.value);
      else throw new Error(`Cannot access property with non-string/non-number: got ${r.type}`);
      else {
        if (!(r instanceof q)) throw new Error(`Cannot access property with non-string: got ${r.type}`);
        n = s.builtins.get(r.value);
      }
      return n instanceof dt ? n : new ye();
    }
    evaluateSet(t6, e) {
      let s = t6.value ? this.evaluate(t6.value, e) : this.evaluateBlock(t6.body, e);
      if (t6.assignee.type === "Identifier") {
        let r = t6.assignee.value;
        e.setVariable(r, s);
      } else if (t6.assignee.type === "TupleLiteral") {
        let r = t6.assignee;
        if (!(s instanceof oe)) throw new Error(`Cannot unpack non-iterable type in set: ${s.type}`);
        let n = s.value;
        if (n.length !== r.value.length) throw new Error(`Too ${r.value.length > n.length ? "few" : "many"} items to unpack in set`);
        for (let o = 0; o < r.value.length; ++o) {
          let i = r.value[o];
          if (i.type !== "Identifier") throw new Error(`Cannot unpack to non-identifier in set: ${i.type}`);
          e.setVariable(i.value, n[o]);
        }
      } else if (t6.assignee.type === "MemberExpression") {
        let r = t6.assignee, n = this.evaluate(r.object, e);
        if (!(n instanceof Ne)) throw new Error("Cannot assign to member of non-object");
        if (r.property.type !== "Identifier") throw new Error("Cannot assign to member with non-identifier property");
        n.value.set(r.property.value, s);
      } else throw new Error(`Invalid LHS inside assignment expression: ${JSON.stringify(t6.assignee)}`);
      return new ke();
    }
    evaluateIf(t6, e) {
      let s = this.evaluate(t6.test, e);
      return this.evaluateBlock(s.__bool__().value ? t6.body : t6.alternate, e);
    }
    evaluateFor(t6, e) {
      let s = new ss2(e), r, n;
      if (t6.iterable.type === "SelectExpression") {
        let c = t6.iterable;
        n = this.evaluate(c.lhs, s), r = c.test;
      } else n = this.evaluate(t6.iterable, s);
      if (!(n instanceof oe || n instanceof Ne)) throw new Error(`Expected iterable or object type in for loop: got ${n.type}`);
      n instanceof Ne && (n = n.keys());
      let o = [], i = [];
      for (let c = 0; c < n.value.length; ++c) {
        let p = new ss2(s), u = n.value[c], _;
        if (t6.loopvar.type === "Identifier") _ = (d) => d.setVariable(t6.loopvar.value, u);
        else if (t6.loopvar.type === "TupleLiteral") {
          let d = t6.loopvar;
          if (u.type !== "ArrayValue") throw new Error(`Cannot unpack non-iterable type: ${u.type}`);
          let m = u;
          if (d.value.length !== m.value.length) throw new Error(`Too ${d.value.length > m.value.length ? "few" : "many"} items to unpack`);
          _ = (f) => {
            for (let g = 0; g < d.value.length; ++g) {
              if (d.value[g].type !== "Identifier") throw new Error(`Cannot unpack non-identifier type: ${d.value[g].type}`);
              f.setVariable(d.value[g].value, m.value[g]);
            }
          };
        } else throw new Error(`Invalid loop variable(s): ${t6.loopvar.type}`);
        r && (_(p), !this.evaluate(r, p).__bool__().value) || (o.push(u), i.push(_));
      }
      let a = "", l = true;
      for (let c = 0; c < o.length; ++c) {
        let p = /* @__PURE__ */ new Map([["index", new te(c + 1)], ["index0", new te(c)], ["revindex", new te(o.length - c)], ["revindex0", new te(o.length - c - 1)], ["first", new Q(c === 0)], ["last", new Q(c === o.length - 1)], ["length", new te(o.length)], ["previtem", c > 0 ? o[c - 1] : new ye()], ["nextitem", c < o.length - 1 ? o[c + 1] : new ye()]]);
        s.setVariable("loop", new Ne(p)), i[c](s);
        try {
          let u = this.evaluateBlock(t6.body, s);
          a += u.value;
        } catch (u) {
          if (u instanceof x0) continue;
          if (u instanceof g0) break;
          throw u;
        }
        l = false;
      }
      if (l) {
        let c = this.evaluateBlock(t6.defaultBlock, s);
        a += c.value;
      }
      return new q(a);
    }
    evaluateMacro(t6, e) {
      return e.setVariable(t6.name.value, new be2((s, r) => {
        let n = new ss2(r);
        s = s.slice();
        let o;
        s.at(-1)?.type === "KeywordArgumentsValue" && (o = s.pop());
        for (let i = 0; i < t6.args.length; ++i) {
          let a = t6.args[i], l = s[i];
          if (a.type === "Identifier") {
            let c = a;
            if (!l) throw new Error(`Missing positional argument: ${c.value}`);
            n.setVariable(c.value, l);
          } else if (a.type === "KeywordArgumentExpression") {
            let c = a, p = l ?? o?.value.get(c.key.value) ?? this.evaluate(c.value, n);
            n.setVariable(c.key.value, p);
          } else throw new Error(`Unknown argument type: ${a.type}`);
        }
        return this.evaluateBlock(t6.body, n);
      })), new ke();
    }
    evaluateCallStatement(t6, e) {
      let s = new be2((a, l) => {
        let c = new ss2(l);
        if (t6.callerArgs) for (let p = 0; p < t6.callerArgs.length; ++p) {
          let u = t6.callerArgs[p];
          if (u.type !== "Identifier") throw new Error(`Caller parameter must be an identifier, got ${u.type}`);
          c.setVariable(u.value, a[p] ?? new ye());
        }
        return this.evaluateBlock(t6.body, c);
      }), [r, n] = this.evaluateArguments(t6.call.args, e);
      r.push(new Cr(n));
      let o = this.evaluate(t6.call.callee, e);
      if (o.type !== "FunctionValue") throw new Error(`Cannot call something that is not a function: got ${o.type}`);
      let i = new ss2(e);
      return i.setVariable("caller", s), o.value(r, i);
    }
    evaluateFilterStatement(t6, e) {
      let s = this.evaluateBlock(t6.body, e);
      return this.applyFilter(s, t6.filter, e);
    }
    evaluate(t6, e) {
      if (!t6) return new ye();
      switch (t6.type) {
        case "Program":
          return this.evalProgram(t6, e);
        case "Set":
          return this.evaluateSet(t6, e);
        case "If":
          return this.evaluateIf(t6, e);
        case "For":
          return this.evaluateFor(t6, e);
        case "Macro":
          return this.evaluateMacro(t6, e);
        case "CallStatement":
          return this.evaluateCallStatement(t6, e);
        case "Break":
          throw new g0();
        case "Continue":
          throw new x0();
        case "IntegerLiteral":
          return new te(t6.value);
        case "FloatLiteral":
          return new Ae(t6.value);
        case "StringLiteral":
          return new q(t6.value);
        case "ArrayLiteral":
          return new oe(t6.value.map((s) => this.evaluate(s, e)));
        case "TupleLiteral":
          return new y0(t6.value.map((s) => this.evaluate(s, e)));
        case "ObjectLiteral": {
          let s = /* @__PURE__ */ new Map();
          for (let [r, n] of t6.value) {
            let o = this.evaluate(r, e);
            if (!(o instanceof q)) throw new Error(`Object keys must be strings: got ${o.type}`);
            s.set(o.value, this.evaluate(n, e));
          }
          return new Ne(s);
        }
        case "Identifier":
          return this.evaluateIdentifier(t6, e);
        case "CallExpression":
          return this.evaluateCallExpression(t6, e);
        case "MemberExpression":
          return this.evaluateMemberExpression(t6, e);
        case "UnaryExpression":
          return this.evaluateUnaryExpression(t6, e);
        case "BinaryExpression":
          return this.evaluateBinaryExpression(t6, e);
        case "FilterExpression":
          return this.evaluateFilterExpression(t6, e);
        case "FilterStatement":
          return this.evaluateFilterStatement(t6, e);
        case "TestExpression":
          return this.evaluateTestExpression(t6, e);
        case "SelectExpression":
          return this.evaluateSelectExpression(t6, e);
        case "Ternary":
          return this.evaluateTernaryExpression(t6, e);
        case "Comment":
          return new ke();
        default:
          throw new SyntaxError(`Unknown node type: ${t6.type}`);
      }
    }
  };
  function pa(t6) {
    switch (typeof t6) {
      case "number":
        return Number.isInteger(t6) ? new te(t6) : new Ae(t6);
      case "string":
        return new q(t6);
      case "boolean":
        return new Q(t6);
      case "undefined":
        return new ye();
      case "object":
        return t6 === null ? new ke() : Array.isArray(t6) ? new oe(t6.map(pa)) : new Ne(new Map(Object.entries(t6).map(([e, s]) => [e, pa(s)])));
      case "function":
        return new be2((e, s) => {
          let r = t6(...e.map((n) => n.value)) ?? null;
          return pa(r);
        });
      default:
        throw new Error(`Cannot convert to runtime value: ${t6}`);
    }
  }
  var Te = `
`;
  var BE = "{%- ";
  var UE = " -%}";
  function GE(t6) {
    switch (t6.operator.type) {
      case "MultiplicativeBinaryOperator":
        return 4;
      case "AdditiveBinaryOperator":
        return 3;
      case "ComparisonBinaryOperator":
        return 2;
      case "Identifier":
        return t6.operator.value === "and" ? 1 : t6.operator.value === "in" || t6.operator.value === "not in" ? 2 : 0;
    }
    return 0;
  }
  function WE(t6, e = "	") {
    let s = typeof e == "number" ? " ".repeat(e) : e;
    return ot2(t6.body, 0, s).replace(/\n$/, "");
  }
  function De(...t6) {
    return BE + t6.join(" ") + UE;
  }
  function ot2(t6, e, s) {
    return t6.map((r) => VE(r, e, s)).join(Te);
  }
  function VE(t6, e, s) {
    let r = s.repeat(e);
    switch (t6.type) {
      case "Program":
        return ot2(t6.body, e, s);
      case "If":
        return HE(t6, e, s);
      case "For":
        return KE(t6, e, s);
      case "Set":
        return XE(t6, e, s);
      case "Macro":
        return QE(t6, e, s);
      case "Break":
        return r + De("break");
      case "Continue":
        return r + De("continue");
      case "CallStatement":
        return YE(t6, e, s);
      case "FilterStatement":
        return JE(t6, e, s);
      case "Comment":
        return r + "{# " + t6.value + " #}";
      default:
        return r + "{{- " + ae(t6) + " -}}";
    }
  }
  function HE(t6, e, s) {
    let r = s.repeat(e), n = [], o = t6;
    for (; o && (n.push({ test: o.test, body: o.body }), o.alternate.length === 1 && o.alternate[0].type === "If"); ) o = o.alternate[0];
    let i = r + De("if", ae(n[0].test)) + Te + ot2(n[0].body, e + 1, s);
    for (let a = 1; a < n.length; ++a) i += Te + r + De("elif", ae(n[a].test)) + Te + ot2(n[a].body, e + 1, s);
    return o && o.alternate.length > 0 && (i += Te + r + De("else") + Te + ot2(o.alternate, e + 1, s)), i += Te + r + De("endif"), i;
  }
  function KE(t6, e, s) {
    let r = s.repeat(e), n = "";
    if (t6.iterable.type === "SelectExpression") {
      let i = t6.iterable;
      n = `${ae(i.lhs)} if ${ae(i.test)}`;
    } else n = ae(t6.iterable);
    let o = r + De("for", ae(t6.loopvar), "in", n) + Te + ot2(t6.body, e + 1, s);
    return t6.defaultBlock.length > 0 && (o += Te + r + De("else") + Te + ot2(t6.defaultBlock, e + 1, s)), o += Te + r + De("endfor"), o;
  }
  function XE(t6, e, s) {
    let r = s.repeat(e), n = ae(t6.assignee), o = t6.value ? ae(t6.value) : "", i = r + De("set", `${n}${t6.value ? " = " + o : ""}`);
    return t6.body.length === 0 ? i : i + Te + ot2(t6.body, e + 1, s) + Te + r + De("endset");
  }
  function QE(t6, e, s) {
    let r = s.repeat(e), n = t6.args.map(ae).join(", ");
    return r + De("macro", `${t6.name.value}(${n})`) + Te + ot2(t6.body, e + 1, s) + Te + r + De("endmacro");
  }
  function YE(t6, e, s) {
    let r = s.repeat(e), n = t6.callerArgs && t6.callerArgs.length > 0 ? `(${t6.callerArgs.map(ae).join(", ")})` : "", o = ae(t6.call), i = r + De(`call${n}`, o) + Te;
    return i += ot2(t6.body, e + 1, s) + Te, i += r + De("endcall"), i;
  }
  function JE(t6, e, s) {
    let r = s.repeat(e), n = t6.filter.type === "Identifier" ? t6.filter.value : ae(t6.filter), o = r + De("filter", n) + Te;
    return o += ot2(t6.body, e + 1, s) + Te, o += r + De("endfilter"), o;
  }
  function ae(t6, e = -1) {
    switch (t6.type) {
      case "SpreadExpression":
        return `*${ae(t6.argument)}`;
      case "Identifier":
        return t6.value;
      case "IntegerLiteral":
        return `${t6.value}`;
      case "FloatLiteral":
        return `${t6.value}`;
      case "StringLiteral":
        return JSON.stringify(t6.value);
      case "BinaryExpression": {
        let s = t6, r = GE(s), n = ae(s.left, r), o = ae(s.right, r + 1), i = `${n} ${s.operator.value} ${o}`;
        return r < e ? `(${i})` : i;
      }
      case "UnaryExpression": {
        let s = t6;
        return s.operator.value + (s.operator.value === "not" ? " " : "") + ae(s.argument, 1 / 0);
      }
      case "CallExpression": {
        let s = t6, r = s.args.map(ae).join(", ");
        return `${ae(s.callee)}(${r})`;
      }
      case "MemberExpression": {
        let s = t6, r = ae(s.object);
        ["Identifier", "MemberExpression", "CallExpression", "StringLiteral", "IntegerLiteral", "FloatLiteral", "ArrayLiteral", "TupleLiteral", "ObjectLiteral"].includes(s.object.type) || (r = `(${r})`);
        let n = ae(s.property);
        return !s.computed && s.property.type !== "Identifier" && (n = `(${n})`), s.computed ? `${r}[${n}]` : `${r}.${n}`;
      }
      case "FilterExpression": {
        let s = t6, r = ae(s.operand, 1 / 0);
        return s.filter.type === "CallExpression" ? `${r} | ${ae(s.filter)}` : `${r} | ${s.filter.value}`;
      }
      case "SelectExpression": {
        let s = t6;
        return `${ae(s.lhs)} if ${ae(s.test)}`;
      }
      case "TestExpression": {
        let s = t6;
        return `${ae(s.operand)} is${s.negate ? " not" : ""} ${s.test.value}`;
      }
      case "ArrayLiteral":
      case "TupleLiteral": {
        let s = t6.value.map(ae), r = t6.type === "ArrayLiteral" ? "[]" : "()";
        return `${r[0]}${s.join(", ")}${r[1]}`;
      }
      case "ObjectLiteral":
        return `{${Array.from(t6.value.entries()).map(([r, n]) => `${ae(r)}: ${ae(n)}`).join(", ")}}`;
      case "SliceExpression": {
        let s = t6, r = s.start ? ae(s.start) : "", n = s.stop ? ae(s.stop) : "", o = s.step ? `:${ae(s.step)}` : "";
        return `${r}:${n}${o}`;
      }
      case "KeywordArgumentExpression": {
        let s = t6;
        return `${s.key.value}=${ae(s.value)}`;
      }
      case "Ternary": {
        let s = t6, r = `${ae(s.trueExpr)} if ${ae(s.condition, 0)} else ${ae(s.falseExpr)}`;
        return e > -1 ? `(${r})` : r;
      }
      default:
        throw new Error(`Unknown expression type: ${t6.type}`);
    }
  }
  var k0 = class {
    parsed;
    constructor(t6) {
      let e = lE(t6, { lstrip_blocks: true, trim_blocks: true });
      this.parsed = CE(e);
    }
    render(t6) {
      let e = new ss2();
      if (qE(e), t6) for (let [n, o] of Object.entries(t6)) e.set(n, o);
      return new jE(e).run(this.parsed).value;
    }
    format(t6) {
      return WE(this.parsed, t6?.indent || "	");
    }
  };
  var ZE = { txt: "text/plain", html: "text/html", css: "text/css", js: "text/javascript", json: "application/json", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif" };
  var St = class t {
    constructor(e) {
      if (this.filePath = e, this.headers = new Headers(), this.exists = Fe.existsSync(e), this.exists) {
        this.status = 200, this.statusText = "OK";
        let s = Fe.statSync(e);
        this.headers.set("content-length", s.size.toString()), this.updateContentType();
        let r = Fe.createReadStream(e);
        this.body = new ReadableStream({ start(n) {
          r.on("data", (o) => n.enqueue(o)), r.on("end", () => n.close()), r.on("error", (o) => n.error(o));
        }, cancel() {
          r.destroy();
        } });
      } else this.status = 404, this.statusText = "Not Found", this.body = null;
    }
    updateContentType() {
      let e = this.filePath.toString().split(".").pop().toLowerCase();
      this.headers.set("content-type", ZE[e] ?? "application/octet-stream");
    }
    clone() {
      let e = new t(this.filePath);
      return e.exists = this.exists, e.status = this.status, e.statusText = this.statusText, e.headers = new Headers(this.headers), e;
    }
    async arrayBuffer() {
      return (await Fe.promises.readFile(this.filePath)).buffer;
    }
    async blob() {
      let e = await Fe.promises.readFile(this.filePath);
      return new Blob([e], { type: this.headers.get("content-type") });
    }
    async text() {
      return await Fe.promises.readFile(this.filePath, "utf8");
    }
    async json() {
      return JSON.parse(await this.text());
    }
  };
  var Ot2 = class {
    constructor(e) {
      this._mt = new Uint32Array(624), this._idx = 625, this._gauss_next = null, this._random_fn = this.random.bind(this), this.seed(e);
    }
    seed(e) {
      if (e == null) if (K2.IS_CRYPTO_AVAILABLE) {
        let a = new Uint32Array(1);
        crypto.getRandomValues(a), e = a[0];
      } else e = Date.now() >>> 0;
      let s = this._mt, r = (a, l) => Math.imul(a, l) >>> 0, n = [];
      for (let a = e || 0; a > 0; a = Math.floor(a / 4294967296)) n.push(a & 4294967295);
      n.length || n.push(0), s[0] = 19650218;
      for (let a = 1; a < 624; ++a) s[a] = r(1812433253, s[a - 1] ^ s[a - 1] >>> 30) + a >>> 0;
      let o = 1, i = 0;
      for (let a = Math.max(624, n.length); a > 0; --a, ++o, ++i) o >= 624 && (s[0] = s[623], o = 1), i >= n.length && (i = 0), s[o] = (s[o] ^ r(s[o - 1] ^ s[o - 1] >>> 30, 1664525)) + n[i] + i >>> 0;
      for (let a = 623; a > 0; --a, ++o) o >= 624 && (s[0] = s[623], o = 1), s[o] = (s[o] ^ r(s[o - 1] ^ s[o - 1] >>> 30, 1566083941)) - o >>> 0;
      s[0] = 2147483648, this._idx = 624, this._gauss_next = null;
    }
    _int32() {
      let e = this._mt;
      if (this._idx >= 624) {
        for (let r = 0; r < 624; ++r) {
          let n = e[r] & 2147483648 | e[(r + 1) % 624] & 2147483647;
          e[r] = (e[(r + 397) % 624] ^ n >>> 1 ^ (n & 1 ? 2567483615 : 0)) >>> 0;
        }
        this._idx = 0;
      }
      let s = e[this._idx++];
      return s ^= s >>> 11, s ^= s << 7 & 2636928640, s ^= s << 15 & 4022730752, s ^= s >>> 18, s >>> 0;
    }
    random() {
      return ((this._int32() >>> 5) * 67108864 + (this._int32() >>> 6)) / 9007199254740992;
    }
    gauss(e = 0, s = 1) {
      let r = this._gauss_next;
      if (this._gauss_next = null, r === null) {
        let n = this.random() * 2 * Math.PI, o = Math.sqrt(-2 * Math.log(1 - this.random()));
        r = Math.cos(n) * o, this._gauss_next = Math.sin(n) * o;
      }
      return e + r * s;
    }
    shuffle(e) {
      for (let s = e.length - 1; s > 0; --s) {
        let r = 32 - Math.clz32(s + 1), n = this._int32() >>> 32 - r;
        for (; n > s; ) n = this._int32() >>> 32 - r;
        let o = e[s];
        e[s] = e[n], e[n] = o;
      }
    }
    choices(e, s) {
      return e[v0(this._random_fn, s)];
    }
  };
  function v0(t6, e) {
    let s = 0;
    for (let n = 0; n < e.length; ++n) s += e[n];
    let r = t6() * s;
    for (let n = 0; n < e.length; ++n) if (r -= e[n], r < 0) return n;
    return e.length - 1;
  }
  var ft = new Ot2();
  var ns2 = Object.freeze({ Random: Ot2, seed: ft.seed.bind(ft), random: ft.random.bind(ft), gauss: ft.gauss.bind(ft), shuffle: ft.shuffle.bind(ft), choices: ft.choices.bind(ft) });
  var E0 = (t6) => v0(ns2.random, t6);
  var eA = new Ot2();
  var Ps2 = class {
    constructor(e) {
      this.path = e;
    }
    async match(e) {
      let s = Ye.join(this.path, e), r = new St(s);
      if (r.exists) return r;
    }
    async put(e, s, r = void 0) {
      let n = Ye.join(this.path, e), o = K2.IS_PROCESS_AVAILABLE ? process.pid : Date.now(), i = eA._int32().toString(36), a = n + `.tmp.${o}.${i}`;
      try {
        let l = s.headers.get("Content-Length"), c = parseInt(l ?? "0"), p = 0;
        await Fe.promises.mkdir(Ye.dirname(n), { recursive: true });
        let u = Fe.createWriteStream(a), _ = s.body.getReader();
        for (; ; ) {
          let { done: d, value: m } = await _.read();
          if (d) break;
          await new Promise((g, w) => {
            u.write(m, (x) => {
              if (x) {
                w(x);
                return;
              }
              g();
            });
          }), p += m.length;
          let f = c ? p / c * 100 : 0;
          r?.({ progress: f, loaded: p, total: c });
        }
        await new Promise((d, m) => {
          u.close((f) => f ? m(f) : d());
        }), await Fe.promises.rename(a, n);
      } catch (l) {
        try {
          await Fe.promises.unlink(a);
        } catch {
        }
        throw l;
      }
    }
    async delete(e) {
      let s = Ye.join(this.path, e);
      try {
        return await Fe.promises.unlink(s), true;
      } catch {
        return false;
      }
    }
  };
  var A0 = { 400: "Bad request error occurred while trying to load file", 401: "Unauthorized access to file", 403: "Forbidden access to file", 404: "Could not locate file", 408: "Request timeout error occurred while trying to load file", 500: "Internal server error error occurred while trying to load file", 502: "Bad gateway error occurred while trying to load file", 503: "Service unavailable error occurred while trying to load file", 504: "Gateway timeout error occurred while trying to load file" };
  var ua = 100;
  var M0 = /^(\b[\w\-.]+\b\/)?\b[\w\-.]{1,96}\b$/;
  function Pr(...t6) {
    return t6 = t6.map((e, s) => (s && (e = e.replace(new RegExp("^/"), "")), s !== t6.length - 1 && (e = e.replace(new RegExp("/$"), "")), e)), t6.join("/");
  }
  function It2(t6, e = null, s = null) {
    let r;
    try {
      r = new URL(t6);
    } catch {
      return false;
    }
    return !(e && !e.includes(r.protocol) || s && !s.includes(r.hostname));
  }
  function S0(t6) {
    return !(!M0.test(t6) || t6.includes("..") || t6.includes("--") || t6.endsWith(".git") || t6.endsWith(".ipynb"));
  }
  function O0(t6, e, s) {
    if (!s) return null;
    let r = A0[t6] ?? `Error (${t6}) occurred while trying to load file`;
    throw Error(`${r}: "${e}".`);
  }
  async function I0(t6, e, s) {
    let r = t6.headers.get("Content-Length"), n = r ? parseInt(r, 10) : s ?? 0;
    r === null && !s && F.warn("Unable to determine content-length from response headers. Will expand buffer when needed.");
    let o = new Uint8Array(n), i = 0, a = t6.body.getReader();
    async function l() {
      let { done: c, value: p } = await a.read();
      if (c) return;
      let u = i + p.length;
      if (u > n) {
        n = u;
        let d = new Uint8Array(n);
        d.set(o), o = d;
      }
      o.set(p, i), i = u;
      let _ = i / n * 100;
      return e({ progress: _, loaded: i, total: n }), l();
    }
    return await l(), o;
  }
  function Jc(t6) {
    return It2(t6, ["blob:"]);
  }
  function Zc(t6) {
    let e;
    if (typeof location < "u" && location.href) e = location.href;
    else if (typeof import_meta2 < "u" && import_meta2.url) e = import_meta2.url;
    else return t6;
    return new URL(t6, e).href;
  }
  var T0 = "SHA-256";
  var tA = "experimental_transformers-hash-cache";
  var z0 = (t6) => ({ algorithm: T0, value: t6 });
  var Nr = class {
    #t = null;
    _getHashCache = () => (this.#t ??= caches.open(tA), this.#t);
    static isAvailable = () => typeof navigator < "u" && "crossOriginStorage" in navigator;
    match = async (e) => {
      let s = await this._getFileHash(e);
      if (s) try {
        let [r] = await navigator.crossOriginStorage.requestFileHandles([z0(s)]), n = await r.getFile();
        return new Response(n, { headers: { "Content-Length": String(n.size) } });
      } catch {
        return;
      }
    };
    put = async (e, s) => {
      let r = await this._getFileHash(e);
      if (r) {
        let n = await s.blob();
        await this._storeBlobInCOS(n, r);
      } else this._processAndStore(e, s.body);
    };
    _storeBlobInCOS = async (e, s) => {
      let [r] = await navigator.crossOriginStorage.requestFileHandles([z0(s)], { create: true }), n = await r.createWritable();
      await n.write(e), await n.close();
    };
    _processAndStore = async (e, s) => {
      try {
        let r = [];
        for await (let i of s) r.push(i);
        let n = new Blob(r), o = await this._getBlobHash(n);
        await this._storeBlobInCOS(n, o);
        try {
          await (await this._getHashCache()).put(e, new Response(o));
        } catch {
        }
      } catch {
      }
    };
    delete = async (e) => {
      try {
        return await (await this._getHashCache()).delete(e);
      } catch {
        return false;
      }
    };
    _getFileHash = async (e) => {
      try {
        let s = await this._getHashCache(), r = await s.match(e);
        if (r) return r.text();
        let n = await this._getLfsFileHash(e);
        return n ? (await s.put(e, new Response(n)), n) : null;
      } catch {
        return null;
      }
    };
    _getLfsFileHash = async (e) => {
      if (!e.includes("/resolve/")) return null;
      let s = e.replace("/resolve/", "/raw/");
      try {
        let n = (await fetch(s).then((o) => o.text())).match(/^oid sha256:([0-9a-f]+)$/m);
        return n ? n[1] : null;
      } catch {
        return null;
      }
    };
    _getBlobHash = async (e) => {
      let s = await e.arrayBuffer(), r = await crypto.subtle.digest(T0, s);
      return Array.from(new Uint8Array(r)).map((o) => o.toString(16).padStart(2, "0")).join("");
    };
  };
  async function at2(t6 = null) {
    let e = null;
    if (J.useCustomCache) {
      if (!J.customCache) throw Error("`env.useCustomCache=true`, but `env.customCache` is not defined.");
      if (!J.customCache.match || !J.customCache.put) throw new Error("`env.customCache` must be an object which implements the `match` and `put` functions of the Web Cache API. For more information, see https://developer.mozilla.org/en-US/docs/Web/API/Cache");
      e = J.customCache;
    }
    if (!e && J.experimental_useCrossOriginStorage && Nr.isAvailable() && (e = new Nr()), !e && J.useBrowserCache) {
      if (typeof caches > "u") throw Error("Browser cache is not available in this environment.");
      try {
        e = await caches.open(J.cacheKey);
      } catch (s) {
        F.warn("An error occurred while opening the browser cache:", s);
      }
    }
    if (!e && J.useFSCache) {
      if (!K2.IS_FS_AVAILABLE) throw Error("File System Cache is not available in this environment.");
      e = new Ps2(t6 ?? J.cacheDir);
    }
    return e;
  }
  async function C0(t6, ...e) {
    for (let s of e) try {
      let r = await t6.match(s);
      if (r) return r;
    } catch {
      continue;
    }
  }
  var _a2 = class {
    #t;
    #e;
    constructor(e) {
      this.#t = e, this.#e = /* @__PURE__ */ new Map();
    }
    get(e) {
      if (!this.#e.has(e)) return;
      let s = this.#e.get(e);
      return this.#e.delete(e), this.#e.set(e, s), s;
    }
    put(e, s) {
      this.#e.has(e) && this.#e.delete(e), this.#e.set(e, s), this.#e.size > this.#t && this.#e.delete(this.#e.keys().next().value);
    }
    delete(e) {
      return this.#e.delete(e);
    }
    clear() {
      this.#e.clear();
    }
  };
  var sA = 100;
  var ep = new _a2(sA);
  function da(t6, e) {
    let s = ep.get(t6);
    if (s !== void 0) return s;
    let r = e().then((n) => n, (n) => (ep.delete(t6), Promise.reject(n)));
    return ep.put(t6, r), r;
  }
  async function rA(t6) {
    if (!It2(t6, ["http:", "https:"])) return null;
    let e = tp(t6);
    return e.set("Range", "bytes=0-0"), J.fetch(t6, { method: "GET", headers: e, cache: "no-store" });
  }
  function We(t6, e, s = {}) {
    let r = JSON.stringify([t6, e, s?.revision, s?.cache_dir, s?.local_files_only]);
    return da(r, () => nA(t6, e, s));
  }
  async function nA(t6, e, s) {
    let r = await at2(s?.cache_dir), { localPath: n, remoteURL: o, proposedCacheKey: i, validModelId: a } = Tt(t6, e, s, r), l = await Ct(r, n, i);
    if (l !== void 0 && typeof l != "string") {
      let c = l.headers.get("content-length"), p = l.headers.get("content-type");
      return { exists: true, size: c ? parseInt(c, 10) : void 0, contentType: p || void 0, fromCache: true };
    }
    if (J.allowLocalModels && !It2(n, ["http:", "https:"])) try {
      let p = await zt2(n);
      if (typeof p != "string" && p.status !== 404) {
        let u = p.headers.get("content-length"), _ = p.headers.get("content-type");
        return { exists: true, size: u ? parseInt(u, 10) : void 0, contentType: _ || void 0, fromCache: false };
      }
    } catch {
    }
    if (J.allowRemoteModels && !s.local_files_only && a) try {
      let c = await rA(o);
      if (c && c.status >= 200 && c.status < 300) {
        let p, u = c.headers.get("content-type");
        if (c.status === 206) {
          let _ = c.headers.get("content-range");
          if (_) {
            let d = _.match(/bytes \d+-\d+\/(\d+)/);
            d && (p = parseInt(d[1], 10));
          }
        } else if (c.status === 200) try {
          await c.body?.cancel();
        } catch {
        }
        if (p === void 0) {
          let _ = c.headers.get("content-length");
          p = _ ? parseInt(_, 10) : void 0;
        }
        return { exists: true, size: p, contentType: u || void 0, fromCache: false };
      }
    } catch (c) {
      F.warn(`Unable to fetch file metadata for "${o}": ${c}`);
    }
    return { exists: false, fromCache: false };
  }
  async function zt2(t6) {
    return J.useFS && !It2(t6, ["http:", "https:", "blob:"]) ? new St(t6 instanceof URL ? t6.protocol === "file:" ? t6.pathname : t6.toString() : t6) : J.fetch(t6, { headers: tp(t6) });
  }
  function tp(t6) {
    let e = typeof process < "u" && process?.release?.name === "node", s = new Headers();
    if (e) {
      let r = !!process.env?.TESTING_REMOTELY, n = J.version;
      if (s.set("User-Agent", `transformers.js/${n}; is_ci/${r};`), It2(t6, ["http:", "https:"], ["huggingface.co", "hf.co"])) {
        let i = process.env?.HF_TOKEN ?? process.env?.HF_ACCESS_TOKEN;
        i && s.set("Authorization", `Bearer ${i}`);
      }
    }
    return s;
  }
  function Tt(t6, e, s = {}, r = null) {
    let n = s.revision ?? "main", o = Pr(t6, e), i = S0(t6), a = i ? Pr(J.localModelPath, o) : o, l = Pr(J.remoteHost, J.remotePathTemplate.replaceAll("{model}", t6).replaceAll("{revision}", encodeURIComponent(n)), e), c = r instanceof Ps2 ? n === "main" ? o : Pr(t6, n, e) : l;
    return { requestURL: o, localPath: a, remoteURL: l, proposedCacheKey: c, validModelId: i };
  }
  async function Ct(t6, e, s) {
    if (t6) return await C0(t6, e, s);
  }
  async function oA(t6, e, s, r, n, o, i = {}) {
    if (await s.match(r) === void 0) if (o) {
      if (typeof n != "string") {
        let a = new Headers(n.headers);
        a.set("content-length", o.byteLength.toString()), await s.put(r, new Response(o, { headers: a })).catch((l) => {
          F.warn(`Unable to add response to browser cache: ${l}.`);
        });
      }
    } else {
      let a = i.progress_callback ? (l) => _t(i.progress_callback, { status: "progress", name: t6, file: e, ...l }) : void 0;
      await s.put(r, n, a);
    }
  }
  async function iA(t6, e, s = true, r = {}, n = false, o = null) {
    let { requestURL: i, localPath: a, remoteURL: l, proposedCacheKey: c, validModelId: p } = Tt(t6, e, r, o), u, _ = false, d;
    d = await Ct(o, a, c);
    let m = d !== void 0;
    if (m) u = c;
    else {
      if (J.allowLocalModels) if (It2(i, ["http:", "https:"])) {
        if (r.local_files_only) throw new Error(`\`local_files_only=true\`, but attempted to load a remote file from: ${i}.`);
        if (!J.allowRemoteModels) throw new Error(`\`env.allowRemoteModels=false\`, but attempted to load a remote file from: ${i}.`);
      } else try {
        d = await zt2(a), u = a;
      } catch (x) {
        F.warn(`Unable to load from local path "${a}": "${x}"`);
      }
      if (d === void 0 || typeof d != "string" && d.status === 404) {
        if (r.local_files_only || !J.allowRemoteModels) {
          if (s) throw Error(`\`local_files_only=true\` or \`env.allowRemoteModels=false\` and file was not found locally at "${a}".`);
          return null;
        }
        if (!p) throw Error(`Local file missing at "${a}" and download aborted due to invalid model ID "${t6}".`);
        if (d = await zt2(l), d.status !== 200) return O0(d.status, l, s);
        u = c;
      }
      _ = o && typeof Response < "u" && d instanceof Response && d.status === 200;
    }
    _t(r.progress_callback, { status: "download", name: t6, file: e });
    let f;
    if (!(K2.IS_NODE_ENV && n)) {
      let w;
      if (typeof d != "string") if (!r.progress_callback) w = new Uint8Array(await d.arrayBuffer());
      else if (m && typeof navigator < "u" && /firefox/i.test(navigator.userAgent)) w = new Uint8Array(await d.arrayBuffer()), _t(r.progress_callback, { status: "progress", name: t6, file: e, progress: 100, loaded: w.length, total: w.length });
      else {
        let x, y = d.headers.get("content-length");
        if (y) x = parseInt(y, 10);
        else try {
          let b = await We(t6, e, r);
          b.size && (x = b.size);
        } catch {
        }
        w = await I0(d, (b) => {
          _t(r.progress_callback, { status: "progress", name: t6, file: e, ...b });
        }, x);
      }
      f = w;
    }
    if (_ && u && typeof d != "string" && await oA(t6, e, o, u, d, f, r), K2.IS_NODE_ENV && n && r.progress_callback && typeof d != "string") {
      let w = parseInt(d.headers.get("content-length"), 10) || 0;
      _t(r.progress_callback, { status: "progress", name: t6, file: e, progress: 100, loaded: w, total: w });
    }
    if (_t(r.progress_callback, { status: "done", name: t6, file: e }), f) {
      if (!K2.IS_NODE_ENV && n) throw new Error("Cannot return path in a browser environment.");
      return f;
    }
    if (d instanceof St) return d.filePath;
    let g = await o?.match(u);
    if (g instanceof St) return g.filePath;
    if (g instanceof Response) return new Uint8Array(await g.arrayBuffer());
    if (typeof g == "string") return g;
    throw new Error("Unable to get model file path or buffer.");
  }
  var fa = /* @__PURE__ */ new Map();
  async function Lr(t6, e, s = true, r = {}, n = false) {
    if (!J.allowLocalModels) {
      if (r.local_files_only) throw Error("Invalid configuration detected: local models are disabled (`env.allowLocalModels=false`) but you have requested to only use local models (`local_files_only=true`).");
      if (!J.allowRemoteModels) throw Error("Invalid configuration detected: both local and remote models are disabled. Fix by setting `env.allowLocalModels` or `env.allowRemoteModels` to `true`.");
    }
    _t(r.progress_callback, { status: "initiate", name: t6, file: e });
    let o = `${t6}::${e}`, i = fa.get(o);
    if (!i) {
      let a = await at2(r?.cache_dir);
      i = iA(t6, e, s, r, n, a).then((l) => (fa.delete(o), l), (l) => {
        throw fa.delete(o), l;
      }), fa.set(o, i);
    }
    return await i;
  }
  async function $r(t6, e, s = true, r = {}) {
    let n = await Lr(t6, e, s, r, false);
    return n === null ? null : new TextDecoder("utf-8").decode(n);
  }
  async function Ie(t6, e, s = true, r = {}) {
    let n = await $r(t6, e, s, r);
    return n === null ? {} : JSON.parse(n);
  }
  function N0(t6, [e, s, r], [n, o], i = "bilinear", a = false) {
    let l = o / r, c = n / s, p = new t6.constructor(n * o * e), u = s * r, _ = n * o;
    for (let d = 0; d < n; ++d) for (let m = 0; m < o; ++m) {
      let f = d * o + m, g = (m + 0.5) / l - 0.5, w = (d + 0.5) / c - 0.5, x = Math.floor(g), y = Math.floor(w), b = Math.min(x + 1, r - 1), v = Math.min(y + 1, s - 1);
      x = Math.max(x, 0), y = Math.max(y, 0);
      let k2 = g - x, S = w - y, I = (1 - k2) * (1 - S), $2 = k2 * (1 - S), C = (1 - k2) * S, R = k2 * S, V = y * r, H = v * r, j = V + x, B = V + b, Z = H + x, D = H + b;
      for (let A = 0; A < e; ++A) {
        let O = A * u;
        p[A * _ + f] = I * t6[O + j] + $2 * t6[O + B] + C * t6[O + Z] + R * t6[O + D];
      }
    }
    return p;
  }
  function L0(t6, e, s) {
    let r = new Array(s.length), n = new Array(s.length);
    for (let a = s.length - 1, l = 1; a >= 0; --a) n[a] = l, r[a] = e[s[a]], l *= r[a];
    let o = s.map((a, l) => n[s.indexOf(l)]), i = new t6.constructor(t6.length);
    for (let a = 0; a < t6.length; ++a) {
      let l = 0;
      for (let c = e.length - 1, p = a; c >= 0; --c) l += p % e[c] * o[c], p = Math.floor(p / e[c]);
      i[l] = t6[a];
    }
    return [i, r];
  }
  function me(t6) {
    let e = de(t6)[0], s = t6.map((o) => Math.exp(o - e)), r = s.reduce((o, i) => o + i, 0);
    return s.map((o) => o / r);
  }
  function rp(t6) {
    let e = de(t6)[0], s = 0;
    for (let o = 0; o < t6.length; ++o) s += Math.exp(t6[o] - e);
    let r = Math.log(s);
    return t6.map((o) => o - e - r);
  }
  function Fr(t6) {
    if (t6.length === 0) throw Error("Array must not be empty");
    let e = t6[0], s = 0;
    for (let r = 1; r < t6.length; ++r) t6[r] < e && (e = t6[r], s = r);
    return [e, s];
  }
  function de(t6) {
    if (t6.length === 0) throw Error("Array must not be empty");
    let e = t6[0], s = 0;
    for (let r = 1; r < t6.length; ++r) t6[r] > e && (e = t6[r], s = r);
    return [e, s];
  }
  function F0(t6) {
    return t6 > 0 && (t6 & t6 - 1) === 0;
  }
  var ma = class {
    constructor(e) {
      if (this.size = e | 0, this.size <= 1 || !F0(this.size)) throw new Error("FFT size must be a power of two larger than 1");
      this._csize = e << 1, this.table = new Float64Array(this.size * 2);
      for (let r = 0; r < this.table.length; r += 2) {
        let n = Math.PI * r / this.size;
        this.table[r] = Math.cos(n), this.table[r + 1] = -Math.sin(n);
      }
      let s = 0;
      for (let r = 1; this.size > r; r <<= 1) ++s;
      this._width = s % 2 === 0 ? s - 1 : s, this._bitrev = new Int32Array(1 << this._width);
      for (let r = 0; r < this._bitrev.length; ++r) {
        this._bitrev[r] = 0;
        for (let n = 0; n < this._width; n += 2) {
          let o = this._width - n - 2;
          this._bitrev[r] |= (r >>> n & 3) << o;
        }
      }
    }
    createComplexArray() {
      return new Float64Array(this._csize);
    }
    fromComplexArray(e, s) {
      let r = s || new Array(e.length >>> 1);
      for (let n = 0; n < e.length; n += 2) r[n >>> 1] = e[n];
      return r;
    }
    toComplexArray(e, s) {
      let r = s || this.createComplexArray();
      for (let n = 0; n < r.length; n += 2) r[n] = e[n >>> 1], r[n + 1] = 0;
      return r;
    }
    transform(e, s) {
      if (e === s) throw new Error("Input and output buffers must be different");
      this._transform4(e, s, 1);
    }
    realTransform(e, s) {
      if (e === s) throw new Error("Input and output buffers must be different");
      this._realTransform4(e, s, 1);
    }
    inverseTransform(e, s) {
      if (e === s) throw new Error("Input and output buffers must be different");
      this._transform4(e, s, -1);
      for (let r = 0; r < e.length; ++r) e[r] /= this.size;
    }
    _transform4(e, s, r) {
      let n = this._csize, i = 1 << this._width, a = n / i << 1, l, c, p = this._bitrev;
      if (a === 4) for (l = 0, c = 0; l < n; l += a, ++c) {
        let _ = p[c];
        this._singleTransform2(s, e, l, _, i);
      }
      else for (l = 0, c = 0; l < n; l += a, ++c) {
        let _ = p[c];
        this._singleTransform4(s, e, l, _, i, r);
      }
      let u = this.table;
      for (i >>= 2; i >= 2; i >>= 2) {
        a = n / i << 1;
        let _ = a >>> 2;
        for (l = 0; l < n; l += a) {
          let d = l + _ - 1;
          for (let m = l, f = 0; m < d; m += 2, f += i) {
            let g = m, w = g + _, x = w + _, y = x + _, b = e[g], v = e[g + 1], k2 = e[w], S = e[w + 1], I = e[x], $2 = e[x + 1], C = e[y], R = e[y + 1], V = u[f], H = r * u[f + 1], j = k2 * V - S * H, B = k2 * H + S * V, Z = u[2 * f], D = r * u[2 * f + 1], A = I * Z - $2 * D, O = I * D + $2 * Z, T = u[3 * f], G = r * u[3 * f + 1], ee = C * T - R * G, $e2 = C * G + R * T, re = b + A, ut2 = v + O, He2 = b - A, Ar = v - O, Ms2 = j + ee, Ss2 = B + $e2, Mr = r * (j - ee), Sr = r * (B - $e2);
            e[g] = re + Ms2, e[g + 1] = ut2 + Ss2, e[w] = He2 + Sr, e[w + 1] = Ar - Mr, e[x] = re - Ms2, e[x + 1] = ut2 - Ss2, e[y] = He2 - Sr, e[y + 1] = Ar + Mr;
          }
        }
      }
    }
    _singleTransform2(e, s, r, n, o) {
      let i = e[n], a = e[n + 1], l = e[n + o], c = e[n + o + 1];
      s[r] = i + l, s[r + 1] = a + c, s[r + 2] = i - l, s[r + 3] = a - c;
    }
    _singleTransform4(e, s, r, n, o, i) {
      let a = o * 2, l = o * 3, c = e[n], p = e[n + 1], u = e[n + o], _ = e[n + o + 1], d = e[n + a], m = e[n + a + 1], f = e[n + l], g = e[n + l + 1], w = c + d, x = p + m, y = c - d, b = p - m, v = u + f, k2 = _ + g, S = i * (u - f), I = i * (_ - g);
      s[r] = w + v, s[r + 1] = x + k2, s[r + 2] = y + I, s[r + 3] = b - S, s[r + 4] = w - v, s[r + 5] = x - k2, s[r + 6] = y - I, s[r + 7] = b + S;
    }
    _realTransform4(e, s, r) {
      let n = this._csize, i = 1 << this._width, a = n / i << 1, l, c, p = this._bitrev;
      if (a === 4) for (l = 0, c = 0; l < n; l += a, ++c) {
        let d = p[c];
        this._singleRealTransform2(s, e, l, d >>> 1, i >>> 1);
      }
      else for (l = 0, c = 0; l < n; l += a, ++c) {
        let d = p[c];
        this._singleRealTransform4(s, e, l, d >>> 1, i >>> 1, r);
      }
      let u = this.table;
      for (i >>= 2; i >= 2; i >>= 2) {
        a = n / i << 1;
        let d = a >>> 1, m = d >>> 1, f = m >>> 1;
        for (l = 0; l < n; l += a) for (let g = 0, w = 0; g <= f; g += 2, w += i) {
          let x = l + g, y = x + m, b = y + m, v = b + m, k2 = e[x], S = e[x + 1], I = e[y], $2 = e[y + 1], C = e[b], R = e[b + 1], V = e[v], H = e[v + 1], j = k2, B = S, Z = u[w], D = r * u[w + 1], A = I * Z - $2 * D, O = I * D + $2 * Z, T = u[2 * w], G = r * u[2 * w + 1], ee = C * T - R * G, $e2 = C * G + R * T, re = u[3 * w], ut2 = r * u[3 * w + 1], He2 = V * re - H * ut2, Ar = V * ut2 + H * re, Ms2 = j + ee, Ss2 = B + $e2, Mr = j - ee, Sr = B - $e2, qc = A + He2, jc = O + Ar, Ly = r * (A - He2), $y = r * (O - Ar);
          if (e[x] = Ms2 + qc, e[x + 1] = Ss2 + jc, e[y] = Mr + $y, e[y + 1] = Sr - Ly, g === 0) {
            e[b] = Ms2 - qc, e[b + 1] = Ss2 - jc;
            continue;
          }
          if (g === f) continue;
          let Fy = l + m - g, Ry = l + d - g;
          e[Fy] = Mr - r * $y, e[Fy + 1] = -Sr - r * Ly, e[Ry] = Ms2 - r * qc, e[Ry + 1] = -Ss2 + r * jc;
        }
      }
      let _ = n >>> 1;
      for (let d = 2; d < _; d += 2) e[n - d] = e[d], e[n - d + 1] = -e[d + 1];
    }
    _singleRealTransform2(e, s, r, n, o) {
      let i = e[n], a = e[n + o];
      s[r] = i + a, s[r + 1] = 0, s[r + 2] = i - a, s[r + 3] = 0;
    }
    _singleRealTransform4(e, s, r, n, o, i) {
      let a = o * 2, l = o * 3, c = e[n], p = e[n + o], u = e[n + a], _ = e[n + l], d = c + u, m = c - u, f = p + _, g = i * (p - _);
      s[r] = d + f, s[r + 1] = 0, s[r + 2] = m, s[r + 3] = -g, s[r + 4] = d - f, s[r + 5] = 0, s[r + 6] = m, s[r + 7] = g;
    }
  };
  var sp = class {
    constructor(e) {
      let s = 2 * (e - 1), r = 2 * (2 * e - 1), n = 2 ** Math.ceil(Math.log2(r));
      this.bufferSize = n, this._a = s;
      let o = new Float64Array(r), i = new Float64Array(n);
      this._chirpBuffer = new Float64Array(n), this._buffer1 = new Float64Array(n), this._buffer2 = new Float64Array(n), this._outBuffer1 = new Float64Array(n), this._outBuffer2 = new Float64Array(n);
      let a = -2 * Math.PI / e, l = Math.cos(a), c = Math.sin(a);
      for (let p = 0; p < r >> 1; ++p) {
        let u = (p + 1 - e) ** 2 / 2, _ = Math.sqrt(l ** 2 + c ** 2) ** u, d = u * Math.atan2(c, l), m = 2 * p;
        o[m] = _ * Math.cos(d), o[m + 1] = _ * Math.sin(d), i[m] = o[m], i[m + 1] = -o[m + 1];
      }
      this._slicedChirpBuffer = o.subarray(s, r), this._f = new ma(n >> 1), this._f.transform(this._chirpBuffer, i);
    }
    _transform(e, s, r) {
      let n = this._buffer1, o = this._buffer2, i = this._outBuffer1, a = this._outBuffer2, l = this._chirpBuffer, c = this._slicedChirpBuffer, p = this._a;
      if (r) for (let u = 0; u < c.length; u += 2) {
        let _ = u + 1, d = u >> 1, m = s[d];
        n[u] = m * c[u], n[_] = m * c[_];
      }
      else for (let u = 0; u < c.length; u += 2) {
        let _ = u + 1;
        n[u] = s[u] * c[u] - s[_] * c[_], n[_] = s[u] * c[_] + s[_] * c[u];
      }
      this._f.transform(i, n);
      for (let u = 0; u < l.length; u += 2) {
        let _ = u + 1;
        o[u] = i[u] * l[u] - i[_] * l[_], o[_] = i[u] * l[_] + i[_] * l[u];
      }
      this._f.inverseTransform(a, o);
      for (let u = 0; u < a.length; u += 2) {
        let _ = a[u + p], d = a[u + p + 1], m = c[u], f = c[u + 1];
        e[u] = _ * m - d * f, e[u + 1] = _ * f + d * m;
      }
    }
    transform(e, s) {
      this._transform(e, s, false);
    }
    realTransform(e, s) {
      this._transform(e, s, true);
    }
  };
  var ha = class {
    constructor(e) {
      this.fft_length = e, this.isPowerOfTwo = F0(e), this.isPowerOfTwo ? (this.fft = new ma(e), this.outputBufferSize = 2 * e) : (this.fft = new sp(e), this.outputBufferSize = this.fft.bufferSize);
    }
    realTransform(e, s) {
      this.fft.realTransform(e, s);
    }
    transform(e, s) {
      this.fft.transform(e, s);
    }
  };
  function R0(t6, e) {
    if (e % 2 === 0 || e <= 0) throw new Error("Window size must be a positive odd number");
    let s = new t6.constructor(t6.length), r = new t6.constructor(e), n = Math.floor(e / 2);
    for (let o = 0; o < t6.length; ++o) {
      let i = 0;
      for (let a = -n; a <= n; ++a) {
        let l = o + a;
        l < 0 ? l = Math.abs(l) : l >= t6.length && (l = 2 * (t6.length - 1) - l), r[i++] = t6[l];
      }
      r.sort(), s[o] = r[n];
    }
    return s;
  }
  function os2(t6, e) {
    let s = Math.pow(10, e);
    return Math.round(t6 * s) / s;
  }
  function D0(t6) {
    let e = Math.round(t6);
    return Math.abs(t6) % 1 === 0.5 ? e % 2 === 0 ? e : e - 1 : e;
  }
  function q0(t6) {
    let e = t6.length, s = t6[0].length, r = [e + 1, s + 1], n = Array.from({ length: r[0] }, () => Array(r[1]).fill(1 / 0));
    n[0][0] = 0;
    let o = Array.from({ length: r[0] }, () => Array(r[1]).fill(-1));
    for (let p = 1; p < r[1]; ++p) for (let u = 1; u < r[0]; ++u) {
      let _ = n[u - 1][p - 1], d = n[u - 1][p], m = n[u][p - 1], f, g;
      _ < d && _ < m ? (f = _, g = 0) : d < _ && d < m ? (f = d, g = 1) : (f = m, g = 2), n[u][p] = t6[u - 1][p - 1] + f, o[u][p] = g;
    }
    for (let p = 0; p < r[1]; ++p) o[0][p] = 2;
    for (let p = 0; p < r[0]; ++p) o[p][0] = 1;
    let i = e, a = s, l = [], c = [];
    for (; i > 0 || a > 0; ) switch (l.push(i - 1), c.push(a - 1), o[i][a]) {
      case 0:
        --i, --a;
        break;
      case 1:
        --i;
        break;
      case 2:
        --a;
        break;
      default:
        throw new Error(`Internal error in dynamic time warping. Unexpected trace[${i}, ${a}]. Please file a bug report.`);
    }
    return l.reverse(), c.reverse(), [l, c];
  }
  var j0 = /* @__PURE__ */ (function() {
    let t6 = null;
    return function(e) {
      if (!t6) {
        t6 = new Float32Array(65536);
        let o = new ArrayBuffer(4), i = new Uint32Array(o), a = new Float32Array(o);
        for (let l = 0; l < t6.length; ++l) {
          let c = 0, p = (l & 32768) << 16, u = (l & 31744) >> 10, _ = l & 1023;
          if (u === 31) c = p | 2139095040 | _ << 13;
          else if (u === 0) if (_ === 0) c = p;
          else {
            let d = 113;
            for (; (_ & 1024) === 0; ) _ <<= 1, --d;
            _ &= -1025, c = p | d << 23 | _ << 13;
          }
          else c = p | u + 112 << 23 | _ << 13;
          i[0] = c, t6[l] = a[0];
        }
      }
      let s = e.length, r = t6, n = new Float32Array(s);
      for (let o = 0; o < s; ++o) n[o] = r[e[o]];
      return n;
    };
  })();
  var np = {};
  Os2(np, { default: () => lA });
  var lA = {};
  async function B0(t6) {
    let e = t6.split("/").pop(), s;
    try {
      if (s = await at2(), s) {
        let n = await s.match(t6);
        if (n) return n;
      }
    } catch (n) {
      F.warn(`Failed to load ${e} from cache:`, n);
    }
    let r = await J.fetch(t6);
    if (!r.ok) throw new Error(`Failed to fetch ${e}: ${r.status} ${r.statusText}`);
    if (s) try {
      await s.put(t6, r.clone());
    } catch (n) {
      F.warn(`Failed to cache ${e}:`, n);
    }
    return r;
  }
  async function U0(t6) {
    let e = await B0(t6);
    if (!e || typeof e == "string") return null;
    try {
      return await e.arrayBuffer();
    } catch (s) {
      return F.warn("Failed to read WASM binary:", s), null;
    }
  }
  async function G0(t6) {
    if (K2.IS_SERVICE_WORKER_ENV || K2.IS_CHROME_AVAILABLE) return t6;
    let e = await B0(t6);
    if (!e || typeof e == "string") return null;
    try {
      let s = await e.text();
      s = s.replaceAll("globalThis.process?.versions?.node", "false");
      let r = new Blob([s], { type: "text/javascript" });
      return URL.createObjectURL(r);
    } catch (s) {
      return F.warn("Failed to read WASM factory:", s), null;
    }
  }
  var pA = Object.freeze({ auto: null, gpu: null, cpu: "cpu", wasm: "wasm", webgpu: "webgpu", cuda: "cuda", dml: "dml", coreml: "coreml", webnn: { name: "webnn", deviceType: "cpu" }, "webnn-npu": { name: "webnn", deviceType: "npu" }, "webnn-gpu": { name: "webnn", deviceType: "gpu" }, "webnn-cpu": { name: "webnn", deviceType: "cpu" } });
  function K0(t6) {
    return t6 <= Ge.DEBUG ? 0 : t6 <= Ge.INFO ? 2 : t6 <= Ge.WARNING || t6 <= Ge.ERROR ? 3 : 4;
  }
  var uA = { 0: "verbose", 1: "info", 2: "warning", 3: "error", 4: "fatal" };
  var et2 = [];
  var op;
  var Ls2;
  var W0 = /* @__PURE__ */ Symbol.for("onnxruntime");
  if (W0 in globalThis) Ls2 = globalThis[W0];
  else if (K2.IS_NODE_ENV) {
    switch (Ls2 = np, process.platform) {
      case "win32":
        et2.push("dml");
        break;
      case "linux":
        process.arch === "x64" && et2.push("cuda");
        break;
      case "darwin":
        et2.push("coreml");
        break;
    }
    et2.push("webgpu"), et2.push("cpu"), op = ["cpu"];
  } else Ls2 = ort_webgpu_bundle_min_exports, K2.IS_WEBNN_AVAILABLE && et2.push("webnn-npu", "webnn-gpu", "webnn-cpu", "webnn"), K2.IS_WEBGPU_AVAILABLE && et2.push("webgpu"), et2.push("wasm"), op = ["wasm"];
  var _A = Ls2.InferenceSession;
  function X0(t6 = null) {
    if (!t6) return op;
    switch (t6) {
      case "auto":
        return et2;
      case "gpu":
        return et2.filter((e) => ["webgpu", "cuda", "dml", "webnn-gpu"].includes(e));
    }
    if (et2.includes(t6)) return [pA[t6] ?? t6];
    throw new Error(`Unsupported device: "${t6}". Should be one of: ${et2.join(", ")}.`);
  }
  var V0 = Promise.resolve();
  var Ns2 = null;
  async function dA() {
    if (Ns2) return Ns2;
    if (!(J.useWasmCache && typeof Ce?.wasm?.wasmPaths == "object" && Ce?.wasm?.wasmPaths?.wasm && Ce?.wasm?.wasmPaths?.mjs)) {
      if (K2.IS_DENO_WEB_RUNTIME) throw new Error("env.useWasmCache=false is not supported in Deno's web runtime. Remove the useWasmCache override.");
      return Ns2 = Promise.resolve(), Ns2;
    }
    return Ns2 = (async () => {
      let e = Ce.wasm.wasmPaths, s = false;
      await Promise.all([e.wasm && !Jc(e.wasm) ? (async () => {
        try {
          let r = await U0(Zc(e.wasm));
          r && (Ce.wasm.wasmBinary = r, s = true);
        } catch (r) {
          F.warn("Failed to pre-load WASM binary:", r);
        }
      })() : Promise.resolve(), e.mjs && !Jc(e.mjs) ? (async () => {
        try {
          let r = await G0(Zc(e.mjs));
          r && (Ce.wasm.wasmPaths.mjs = r);
        } catch (r) {
          F.warn("Failed to pre-load WASM factory:", r);
        }
      })() : Promise.resolve()]), s || (Ce.wasm.wasmPaths.mjs = e.mjs);
    })(), Ns2;
  }
  async function ga(t6, e, s) {
    await dA();
    let r = K0(J.logLevel ?? Ge.WARNING), n = () => _A.create(t6, { logSeverityLevel: r, ...e }), o = await (K2.IS_WEB_ENV ? V0 = V0.then(n) : n());
    return o.config = s, o;
  }
  var H0 = Promise.resolve();
  async function xa2(t6, e) {
    let s = () => t6.run(e);
    return K2.IS_WEB_ENV ? H0 = H0.then(s) : s();
  }
  function wa(t6) {
    return t6 instanceof Ls2.Tensor;
  }
  var Ce = Ls2?.env;
  function Rr() {
    return Ce?.wasm?.proxy;
  }
  if (Ce) {
    let t6 = function(e) {
      let s = K0(e);
      Ce.logLevel = uA[s];
    };
    if (Ce.wasm) {
      if (!(typeof ServiceWorkerGlobalScope < "u" && self instanceof ServiceWorkerGlobalScope) && Ce.versions?.web && !Ce.wasm.wasmPaths) {
        let e = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${Ce.versions.web}/dist/`;
        Ce.wasm.wasmPaths = K2.IS_SAFARI ? { mjs: `${e}ort-wasm-simd-threaded.mjs`, wasm: `${e}ort-wasm-simd-threaded.wasm` } : { mjs: `${e}ort-wasm-simd-threaded.asyncify.mjs`, wasm: `${e}ort-wasm-simd-threaded.asyncify.wasm` };
      }
      Ce.wasm.proxy = false;
    }
    Ce.webgpu && (Ce.webgpu.powerPreference = "high-performance"), t6(J.logLevel ?? Ge.WARNING), J.backends.onnx = { ...Ce, setLogLevel: t6 };
  }
  var Pt = async (t6, e, s) => {
    let r = await ga(new Uint8Array(t6), e);
    return (async (n) => {
      let o = Rr(), i = Object.fromEntries(Object.entries(n).map(([l, c]) => [l, (o ? c.clone() : c).ort_tensor])), a = await xa2(r, i);
      return Array.isArray(s) ? s.map((l) => new E(a[l])) : new E(a[s]);
    });
  };
  var mt2 = class {
    static session_options = {};
    static get nearest_interpolate_4d() {
      return this._nearest_interpolate_4d || (this._nearest_interpolate_4d = Pt([8, 10, 18, 0, 58, 129, 1, 10, 41, 10, 1, 120, 10, 0, 10, 0, 10, 1, 115, 18, 1, 121, 34, 6, 82, 101, 115, 105, 122, 101, 42, 18, 10, 4, 109, 111, 100, 101, 34, 7, 110, 101, 97, 114, 101, 115, 116, 160, 1, 3, 18, 1, 114, 90, 31, 10, 1, 120, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 99, 10, 3, 18, 1, 104, 10, 3, 18, 1, 119, 90, 15, 10, 1, 115, 18, 10, 10, 8, 8, 7, 18, 4, 10, 2, 8, 4, 98, 31, 10, 1, 121, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 99, 10, 3, 18, 1, 104, 10, 3, 18, 1, 119, 66, 2, 16, 21], this.session_options, "y")), this._nearest_interpolate_4d;
    }
    static get bilinear_interpolate_4d() {
      return this._bilinear_interpolate_4d || (this._bilinear_interpolate_4d = Pt([8, 9, 18, 0, 58, 128, 1, 10, 40, 10, 1, 120, 10, 0, 10, 0, 10, 1, 115, 18, 1, 121, 34, 6, 82, 101, 115, 105, 122, 101, 42, 17, 10, 4, 109, 111, 100, 101, 34, 6, 108, 105, 110, 101, 97, 114, 160, 1, 3, 18, 1, 114, 90, 31, 10, 1, 120, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 99, 10, 3, 18, 1, 104, 10, 3, 18, 1, 119, 90, 15, 10, 1, 115, 18, 10, 10, 8, 8, 7, 18, 4, 10, 2, 8, 4, 98, 31, 10, 1, 121, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 99, 10, 3, 18, 1, 104, 10, 3, 18, 1, 119, 66, 2, 16, 20], this.session_options, "y")), this._bilinear_interpolate_4d;
    }
    static get bicubic_interpolate_4d() {
      return this._bicubic_interpolate_4d || (this._bicubic_interpolate_4d = Pt([8, 9, 18, 0, 58, 127, 10, 39, 10, 1, 120, 10, 0, 10, 0, 10, 1, 115, 18, 1, 121, 34, 6, 82, 101, 115, 105, 122, 101, 42, 16, 10, 4, 109, 111, 100, 101, 34, 5, 99, 117, 98, 105, 99, 160, 1, 3, 18, 1, 114, 90, 31, 10, 1, 120, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 99, 10, 3, 18, 1, 104, 10, 3, 18, 1, 119, 90, 15, 10, 1, 115, 18, 10, 10, 8, 8, 7, 18, 4, 10, 2, 8, 4, 98, 31, 10, 1, 121, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 99, 10, 3, 18, 1, 104, 10, 3, 18, 1, 119, 66, 2, 16, 20], this.session_options, "y")), this._bicubic_interpolate_4d;
    }
    static get matmul() {
      return this._matmul || (this._matmul = Pt([8, 9, 18, 0, 58, 55, 10, 17, 10, 1, 97, 10, 1, 98, 18, 1, 99, 34, 6, 77, 97, 116, 77, 117, 108, 18, 1, 114, 90, 9, 10, 1, 97, 18, 4, 10, 2, 8, 1, 90, 9, 10, 1, 98, 18, 4, 10, 2, 8, 1, 98, 9, 10, 1, 99, 18, 4, 10, 2, 8, 1, 66, 2, 16, 20], this.session_options, "c")), this._matmul;
    }
    static get stft() {
      return this._stft || (this._stft = Pt([8, 7, 18, 0, 58, 148, 1, 10, 38, 10, 1, 115, 10, 1, 106, 10, 1, 119, 10, 1, 108, 18, 1, 111, 34, 4, 83, 84, 70, 84, 42, 15, 10, 8, 111, 110, 101, 115, 105, 100, 101, 100, 24, 1, 160, 1, 2, 18, 1, 115, 90, 26, 10, 1, 115, 18, 21, 10, 19, 8, 1, 18, 15, 10, 3, 18, 1, 98, 10, 3, 18, 1, 115, 10, 3, 18, 1, 99, 90, 11, 10, 1, 106, 18, 6, 10, 4, 8, 7, 18, 0, 90, 16, 10, 1, 119, 18, 11, 10, 9, 8, 1, 18, 5, 10, 3, 18, 1, 119, 90, 11, 10, 1, 108, 18, 6, 10, 4, 8, 7, 18, 0, 98, 31, 10, 1, 111, 18, 26, 10, 24, 8, 1, 18, 20, 10, 3, 18, 1, 98, 10, 3, 18, 1, 102, 10, 3, 18, 1, 100, 10, 3, 18, 1, 99, 66, 2, 16, 17], this.session_options, "o")), this._stft;
    }
    static get rfft() {
      return this._rfft || (this._rfft = Pt([8, 9, 18, 0, 58, 97, 10, 33, 10, 1, 120, 10, 0, 10, 1, 97, 18, 1, 121, 34, 3, 68, 70, 84, 42, 15, 10, 8, 111, 110, 101, 115, 105, 100, 101, 100, 24, 1, 160, 1, 2, 18, 1, 100, 90, 21, 10, 1, 120, 18, 16, 10, 14, 8, 1, 18, 10, 10, 3, 18, 1, 115, 10, 3, 18, 1, 99, 90, 11, 10, 1, 97, 18, 6, 10, 4, 8, 7, 18, 0, 98, 21, 10, 1, 121, 18, 16, 10, 14, 8, 1, 18, 10, 10, 3, 18, 1, 115, 10, 3, 18, 1, 99, 66, 2, 16, 20], this.session_options, "y")), this._rfft;
    }
    static get top_k() {
      return this._top_k || (this._top_k = Pt([8, 10, 18, 0, 58, 73, 10, 18, 10, 1, 120, 10, 1, 107, 18, 1, 118, 18, 1, 105, 34, 4, 84, 111, 112, 75, 18, 1, 116, 90, 9, 10, 1, 120, 18, 4, 10, 2, 8, 1, 90, 15, 10, 1, 107, 18, 10, 10, 8, 8, 7, 18, 4, 10, 2, 8, 1, 98, 9, 10, 1, 118, 18, 4, 10, 2, 8, 1, 98, 9, 10, 1, 105, 18, 4, 10, 2, 8, 7, 66, 2, 16, 21], this.session_options, ["v", "i"])), this._top_k;
    }
    static get slice() {
      return this._slice || (this._slice = Pt([8, 7, 18, 0, 58, 96, 10, 25, 10, 1, 120, 10, 1, 115, 10, 1, 101, 10, 1, 97, 10, 1, 116, 18, 1, 121, 34, 5, 83, 108, 105, 99, 101, 18, 1, 114, 90, 9, 10, 1, 120, 18, 4, 10, 2, 8, 1, 90, 9, 10, 1, 115, 18, 4, 10, 2, 8, 7, 90, 9, 10, 1, 101, 18, 4, 10, 2, 8, 7, 90, 9, 10, 1, 97, 18, 4, 10, 2, 8, 7, 90, 9, 10, 1, 116, 18, 4, 10, 2, 8, 7, 98, 9, 10, 1, 121, 18, 4, 10, 2, 8, 1, 66, 2, 16, 13], this.session_options, "y")), this._slice;
    }
  };
  var Y0 = Object.freeze({ auto: "auto", gpu: "gpu", cpu: "cpu", wasm: "wasm", webgpu: "webgpu", cuda: "cuda", dml: "dml", coreml: "coreml", webnn: "webnn", "webnn-npu": "webnn-npu", "webnn-gpu": "webnn-gpu", "webnn-cpu": "webnn-cpu" });
  var ip = K2.IS_NODE_ENV ? "cpu" : "wasm";
  function ya(t6, e, { warn: s } = {}) {
    return t6 ? typeof t6 == "string" ? t6 : t6.hasOwnProperty(e) ? t6[e] : (s && s(`device not specified for "${e}". Using the default device (${ip}).`), ip) : ip;
  }
  var eb = /* @__PURE__ */ (function() {
    let t6;
    return async function() {
      if (t6 === void 0) if (!K2.IS_WEBGPU_AVAILABLE) t6 = false;
      else try {
        t6 = (await navigator.gpu.requestAdapter()).features.has("shader-f16");
      } catch {
        t6 = false;
      }
      return t6;
    };
  })();
  var Oe = Object.freeze({ auto: "auto", fp32: "fp32", fp16: "fp16", q8: "q8", int8: "int8", uint8: "uint8", q4: "q4", bnb4: "bnb4", q4f16: "q4f16", q2: "q2", q2f16: "q2f16", q1: "q1", q1f16: "q1f16" });
  var J0 = Oe.fp32;
  var Z0 = Object.freeze({ [Y0.wasm]: Oe.q8 });
  var Nt = Object.freeze({ [Oe.fp32]: "", [Oe.fp16]: "_fp16", [Oe.int8]: "_int8", [Oe.uint8]: "_uint8", [Oe.q8]: "_quantized", [Oe.q4]: "_q4", [Oe.q2]: "_q2", [Oe.q1]: "_q1", [Oe.q4f16]: "_q4f16", [Oe.q2f16]: "_q2f16", [Oe.q1f16]: "_q1f16", [Oe.bnb4]: "_bnb4" });
  function ba(t6, e, s, { configDtype: r = null, warn: n } = {}) {
    let o, i = false;
    t6 && typeof t6 != "string" ? t6.hasOwnProperty(e) ? o = t6[e] : (o = null, i = true) : o = t6;
    let a;
    if (o === Oe.auto) {
      if (r) {
        let l = typeof r == "string" ? r : r?.[e];
        if (l && l !== Oe.auto && Oe.hasOwnProperty(l)) return l;
      }
      a = Z0[s] ?? J0;
    } else o && Oe.hasOwnProperty(o) ? a = o : a = Z0[s] ?? J0;
    return i && n && n(`dtype not specified for "${e}". Using the default dtype (${a}) for this device (${s}).`), a;
  }
  var Lt2 = Object.freeze({ float32: Float32Array, float16: typeof Float16Array < "u" ? Float16Array : Uint16Array, float64: Float64Array, string: Array, int8: Int8Array, uint8: Uint8Array, int16: Int16Array, uint16: Uint16Array, int32: Int32Array, uint32: Uint32Array, int64: BigInt64Array, uint64: BigUint64Array, bool: Uint8Array, uint4: Uint8Array, int4: Int8Array });
  var E = class t2 {
    get dims() {
      return this.ort_tensor.dims;
    }
    set dims(e) {
      this.ort_tensor.dims = e;
    }
    get type() {
      return this.ort_tensor.type;
    }
    get data() {
      return this.ort_tensor.data;
    }
    get size() {
      return this.ort_tensor.size;
    }
    get location() {
      return this.ort_tensor.location;
    }
    ort_tensor;
    constructor(...e) {
      return wa(e[0]) ? this.ort_tensor = e[0] : this.ort_tensor = new Tensor2(e[0], e[1], e[2]), new Proxy(this, { get: (s, r) => {
        if (typeof r == "string") {
          let n = Number(r);
          if (Number.isInteger(n)) return s._getitem(n);
        }
        return s[r];
      }, set: (s, r, n) => s[r] = n });
    }
    dispose() {
      this.ort_tensor.dispose();
    }
    *[Symbol.iterator]() {
      let [e, ...s] = this.dims;
      if (s.length > 0) {
        let r = s.reduce((n, o) => n * o);
        for (let n = 0; n < e; ++n) yield this._subarray(n, r, s);
      } else yield* this.data;
    }
    _getitem(e) {
      let [s, ...r] = this.dims;
      if (e = ht2(e, s), r.length > 0) {
        let n = r.reduce((o, i) => o * i);
        return this._subarray(e, n, r);
      } else return new t2(this.type, [this.data[e]], r);
    }
    indexOf(e) {
      let s = this.data;
      for (let r = 0; r < s.length; ++r) if (s[r] == e) return r;
      return -1;
    }
    _subarray(e, s, r) {
      let n = e * s, o = (e + 1) * s, i = "subarray" in this.data ? this.data.subarray(n, o) : this.data.slice(n, o);
      return new t2(this.type, i, r);
    }
    item() {
      let e = this.data;
      if (e.length !== 1) throw new Error(`a Tensor with ${e.length} elements cannot be converted to Scalar`);
      return e[0];
    }
    tolist() {
      return fA(this.data, this.dims);
    }
    sigmoid() {
      return this.clone().sigmoid_();
    }
    sigmoid_() {
      let e = this.data;
      for (let s = 0; s < e.length; ++s) e[s] = 1 / (1 + Math.exp(-e[s]));
      return this;
    }
    map(e) {
      return this.clone().map_(e);
    }
    map_(e) {
      let s = this.data;
      for (let r = 0; r < s.length; ++r) s[r] = e(s[r], r, s);
      return this;
    }
    mul(e) {
      return this.clone().mul_(e);
    }
    mul_(e) {
      let s = this.data;
      for (let r = 0; r < s.length; ++r) s[r] *= e;
      return this;
    }
    div(e) {
      return this.clone().div_(e);
    }
    div_(e) {
      let s = this.data;
      for (let r = 0; r < s.length; ++r) s[r] /= e;
      return this;
    }
    add(e) {
      return this.clone().add_(e);
    }
    add_(e) {
      let s = this.data;
      for (let r = 0; r < s.length; ++r) s[r] += e;
      return this;
    }
    sub(e) {
      return this.clone().sub_(e);
    }
    sub_(e) {
      let s = this.data;
      for (let r = 0; r < s.length; ++r) s[r] -= e;
      return this;
    }
    clone() {
      return new t2(this.type, this.data.slice(), this.dims.slice());
    }
    slice(...e) {
      let s = [], r = [];
      for (let p = 0; p < this.dims.length; ++p) {
        let u = e[p];
        if (u == null) r.push([0, this.dims[p]]), s.push(this.dims[p]);
        else if (typeof u == "number") u = ht2(u, this.dims[p], p), r.push([u, u + 1]);
        else if (Array.isArray(u) && u.length === 2) {
          let [_, d] = u;
          if (_ = _ === null ? 0 : ht2(_, this.dims[p], p, false), d = d === null ? this.dims[p] : ht2(d, this.dims[p], p, false), _ > d) throw new Error(`Invalid slice: ${u}`);
          let m = [Math.max(_, 0), Math.min(d, this.dims[p])];
          r.push(m), s.push(m[1] - m[0]);
        } else throw new Error(`Invalid slice: ${u}`);
      }
      let n = r.map(([p, u]) => u - p), o = n.reduce((p, u) => p * u), i = this.data, a = new i.constructor(o), l = this.stride(), c = true;
      for (let p = 1; p < n.length; ++p) if (r[p][0] !== 0 || r[p][1] !== this.dims[p]) {
        c = false;
        break;
      }
      if (c) {
        let p = r[0][0] * l[0], u = r[0][1] * l[0];
        if (ArrayBuffer.isView(i)) a.set(i.subarray(p, u));
        else if (Array.isArray(i)) {
          let _ = i.slice(p, u);
          for (let d = 0; d < _.length; ++d) a[d] = _[d];
        } else throw new Error("Unsupported data type for slicing");
      } else for (let p = 0; p < o; ++p) {
        let u = 0;
        for (let _ = n.length - 1, d = p; _ >= 0; --_) {
          let m = n[_];
          u += (d % m + r[_][0]) * l[_], d = Math.floor(d / m);
        }
        a[p] = i[u];
      }
      return new t2(this.type, a, s);
    }
    permute(...e) {
      return mA(this, e);
    }
    transpose(...e) {
      return this.permute(...e);
    }
    sum(e = null, s = false) {
      return this.norm(1, e, s);
    }
    norm(e = "fro", s = null, r = false) {
      if (e === "fro") e = 2;
      else if (typeof e == "string") throw Error(`Unsupported norm: ${e}`);
      let n = this.data, o = n instanceof BigInt64Array || n instanceof BigUint64Array;
      if (o && e !== 1) throw Error(`Expected a floating point tensor as input. Got ${this.type}`);
      let i, a;
      if (o ? (i = (u, _) => u + _, a = 0n) : (i = (u, _) => u + _ ** e, a = 0), s === null) {
        let u = n.reduce(i, a);
        return e !== 1 && (u = u ** (1 / e)), new t2(this.type, [u], []);
      }
      let [l, c, p] = Dr(i, this, s, r);
      if (e !== 1) for (let u = 0; u < c.length; ++u) c[u] = c[u] ** (1 / e);
      return new t2(l, c, p);
    }
    normalize_(e = 2, s = 1) {
      s = ht2(s, this.dims.length);
      let r = this.norm(e, s, true), n = this.data, o = r.data;
      for (let i = 0; i < n.length; ++i) {
        let a = 0;
        for (let l = this.dims.length - 1, c = i, p = 1; l >= 0; --l) {
          let u = this.dims[l];
          if (l !== s) {
            let _ = c % u;
            a += _ * p, p *= this.dims[l];
          }
          c = Math.floor(c / u);
        }
        n[i] /= o[a];
      }
      return this;
    }
    normalize(e = 2, s = 1) {
      return this.clone().normalize_(e, s);
    }
    stride() {
      return ap(this.dims);
    }
    squeeze(e = null) {
      return new t2(this.type, this.data, tb(this.dims, e));
    }
    squeeze_(e = null) {
      return this.dims = tb(this.dims, e), this;
    }
    unsqueeze(e) {
      return new t2(this.type, this.data, sb(this.dims, e));
    }
    unsqueeze_(e) {
      return this.dims = sb(this.dims, e), this;
    }
    flatten_(e = 0, s = -1) {
      s = (s + this.dims.length) % this.dims.length;
      let r = this.dims.slice(0, e), n = this.dims.slice(e, s + 1), o = this.dims.slice(s + 1);
      return this.dims = [...r, n.reduce((i, a) => i * a, 1), ...o], this;
    }
    flatten(e = 0, s = -1) {
      return this.clone().flatten_(e, s);
    }
    view(...e) {
      let s = -1;
      for (let n = 0; n < e.length; ++n) if (e[n] === -1) {
        if (s !== -1) throw new Error("Only one dimension can be inferred");
        s = n;
      }
      let r = this.data;
      if (s !== -1) {
        let n = e.reduce((o, i, a) => a !== s ? o * i : o, 1);
        e[s] = r.length / n;
      }
      return new t2(this.type, r, e);
    }
    neg_() {
      let e = this.data;
      for (let s = 0; s < e.length; ++s) e[s] = -e[s];
      return this;
    }
    neg() {
      return this.clone().neg_();
    }
    gt(e) {
      let s = new Uint8Array(this.data.length), r = this.data;
      for (let n = 0; n < r.length; ++n) s[n] = r[n] > e ? 1 : 0;
      return new t2("bool", s, this.dims);
    }
    lt(e) {
      let s = new Uint8Array(this.data.length), r = this.data;
      for (let n = 0; n < r.length; ++n) s[n] = r[n] < e ? 1 : 0;
      return new t2("bool", s, this.dims);
    }
    clamp_(e, s) {
      let r = this.data;
      for (let n = 0; n < r.length; ++n) r[n] = Math.min(Math.max(r[n], e), s);
      return this;
    }
    clamp(e, s) {
      return this.clone().clamp_(e, s);
    }
    round_() {
      let e = this.data;
      for (let s = 0; s < e.length; ++s) e[s] = Math.round(e[s]);
      return this;
    }
    round() {
      return this.clone().round_();
    }
    mean(e = null, s = false) {
      return Ea2(this, e, s);
    }
    min(e = null, s = false) {
      if (e === null) {
        let i = Fr(this.data)[0];
        return new t2(this.type, [i], []);
      }
      let [r, n, o] = Dr((i, a) => Math.min(i, a), this, e, s, 1 / 0);
      return new t2(r, n, o);
    }
    max(e = null, s = false) {
      if (e === null) {
        let i = de(this.data)[0];
        return new t2(this.type, [i], []);
      }
      let [r, n, o] = Dr((i, a) => Math.max(i, a), this, e, s, -1 / 0);
      return new t2(r, n, o);
    }
    argmin(e = null, s = false) {
      if (e !== null) throw new Error("`dim !== null` not yet implemented.");
      let r = Fr(this.data)[1];
      return new t2("int64", [BigInt(r)], []);
    }
    argmax(e = null, s = false) {
      if (e !== null) throw new Error("`dim !== null` not yet implemented.");
      let r = de(this.data)[1];
      return new t2("int64", [BigInt(r)], []);
    }
    repeat(...e) {
      if (e.length < this.dims.length) throw new Error(`Number of dimensions of repeat dims (${e.length}) cannot be smaller than number of dimensions of tensor (${this.dims.length})`);
      if (e.every((p) => p === 1)) {
        if (e.length === this.dims.length) return this.clone();
        let p = e.length - this.dims.length, u = Array(p).fill(1).concat(this.dims);
        return new t2(this.type, this.data.slice(), u);
      }
      let s = e.length - this.dims.length, r = Array(s).fill(1).concat(this.dims), n = r.map((p, u) => p * e[u]), o = n.reduce((p, u) => p * u, 1), i = this.data, a = new i.constructor(o), l = ap(r), c = ap(n);
      for (let p = 0; p < o; ++p) {
        let u = p, _ = 0;
        for (let d = 0; d < n.length; ++d) {
          let m = Math.floor(u / c[d]);
          u = u % c[d];
          let f = m % r[d];
          _ += f * l[d];
        }
        a[p] = i[_];
      }
      return new t2(this.type, a, n);
    }
    tile(...e) {
      if (e.length < this.dims.length) {
        let s = this.dims.length - e.length;
        e = Array(s).fill(1).concat(e);
      }
      return this.repeat(...e);
    }
    to(e) {
      if (this.type === e) return this;
      if (!Lt2.hasOwnProperty(e)) throw new Error(`Unsupported type: ${e}`);
      let s, r = ["int64", "uint64"].includes(this.type), n = ["int64", "uint64"].includes(e);
      if (r && !n) s = Number;
      else if (!r && n) ["float16", "float32", "float64"].includes(this.type) ? s = (o) => BigInt(Math.floor(o)) : s = BigInt;
      else if (this.type === "float16" && e == "float32" && this.data instanceof Uint16Array) return new t2(e, j0(this.data), this.dims);
      return new t2(e, Lt2[e].from(this.data, s), this.dims);
    }
  };
  function fA(t6, e) {
    let s = t6.length, r = e.reduce((o, i) => o * i);
    if (s !== r) throw Error(`cannot reshape array of size ${s} into shape (${e})`);
    let n = t6;
    for (let o = e.length - 1; o >= 0; o--) n = n.reduce((i, a) => {
      let l = i[i.length - 1];
      return l.length < e[o] ? l.push(a) : i.push([a]), i;
    }, [[]]);
    return n[0];
  }
  function mA(t6, e) {
    let [s, r] = L0(t6.data, t6.dims, e);
    return new E(t6.type, s, r);
  }
  function lp(t6, [e, s], r = "bilinear", n = false) {
    let o = t6.dims.at(-3) ?? 1, i = t6.dims.at(-2), a = t6.dims.at(-1), l = N0(t6.data, [o, i, a], [e, s], r, n);
    return new E(t6.type, l, [o, e, s]);
  }
  async function je2(t6, { size: e = null, mode: s = "bilinear" } = {}) {
    if (t6.dims.length !== 4) throw new Error("`interpolate_4d` currently only supports 4D input.");
    if (!e) throw new Error("`interpolate_4d` requires a `size` argument.");
    let r;
    if (e.length === 2) r = [...t6.dims.slice(0, 2), ...e];
    else if (e.length === 3) r = [t6.dims[0], ...e];
    else if (e.length === 4) r = e;
    else throw new Error("`size` must be of length 2, 3, or 4.");
    let n;
    if (s === "nearest") n = await mt2.nearest_interpolate_4d;
    else if (s === "bilinear") n = await mt2.bilinear_interpolate_4d;
    else if (s === "bicubic") n = await mt2.bicubic_interpolate_4d;
    else throw new Error(`Unsupported mode: ${s}`);
    let o = new E("int64", new BigInt64Array(r.map(BigInt)), [r.length]);
    return await n({ x: t6, s: o });
  }
  async function rb(t6, e) {
    return await (await mt2.matmul)({ a: t6, b: e });
  }
  async function lt(t6, e) {
    let s = await mt2.top_k;
    return e == null ? e = t6.dims.at(-1) : e = Math.min(e, t6.dims.at(-1)), await s({ x: t6, k: new E("int64", [BigInt(e)], [1]) });
  }
  var ka2 = (t6) => new E("int64", t6, [t6.length]);
  async function va2(t6, e, s, r, n) {
    return await (await mt2.slice)({ x: t6, s: ka2(e), e: ka2(s), a: ka2(r), t: ka2(n ?? new Array(r.length).fill(1)) });
  }
  function nb(t6, e) {
    let s = t6.data, r = e.data, n = [t6.dims[0], t6.dims[2]], o = new s.constructor(n[0] * n[1]), [i, a, l] = t6.dims, c = 0;
    for (let p = 0; p < i; ++p) {
      let u = p * l * a;
      for (let _ = 0; _ < l; ++_) {
        let d = 0, m = 0, f = p * a, g = u + _;
        for (let x = 0; x < a; ++x) {
          let y = Number(r[f + x]);
          m += y, d += s[g + x * l] * y;
        }
        let w = d / m;
        o[c++] = w;
      }
    }
    return new E(t6.type, o, n);
  }
  function tb(t6, e) {
    return t6 = t6.slice(), e === null ? t6 = t6.filter((s) => s !== 1) : typeof e == "number" ? t6[e] === 1 && t6.splice(e, 1) : Array.isArray(e) && (t6 = t6.filter((s, r) => s !== 1 || !e.includes(r))), t6;
  }
  function sb(t6, e) {
    return e = ht2(e, t6.length + 1), t6 = t6.slice(), t6.splice(e, 0, 1), t6;
  }
  function ht2(t6, e, s = null, r = true) {
    if (t6 < -e || t6 >= e) {
      if (r) throw new Error(`IndexError: index ${t6} is out of bounds for dimension${s === null ? "" : " " + s} with size ${e}`);
      return t6 < -e ? 0 : e;
    }
    return t6 < 0 && (t6 = (t6 % e + e) % e), t6;
  }
  function ie2(t6, e = 0) {
    e = ht2(e, t6[0].dims.length);
    let s = t6[0].dims.slice();
    s[e] = t6.reduce((i, a) => i + a.dims[e], 0);
    let r = s.reduce((i, a) => i * a, 1), n = new t6[0].data.constructor(r), o = t6[0].type;
    if (e === 0) {
      let i = 0;
      for (let a of t6) {
        let l = a.data;
        n.set(l, i), i += l.length;
      }
    } else {
      let i = 0;
      for (let a = 0; a < t6.length; ++a) {
        let { data: l, dims: c } = t6[a];
        for (let p = 0; p < l.length; ++p) {
          let u = 0;
          for (let _ = c.length - 1, d = p, m = 1; _ >= 0; --_) {
            let f = c[_], g = d % f;
            _ === e && (g += i), u += g * m, m *= s[_], d = Math.floor(d / f);
          }
          n[u] = l[p];
        }
        i += c[e];
      }
    }
    return new E(o, n, s);
  }
  function qe(t6, e = 0) {
    return ie2(t6.map((s) => s.unsqueeze(e)), e);
  }
  function Dr(t6, e, s, r = false, n = null) {
    let o = e.data, i = e.dims;
    s = ht2(s, i.length);
    let a = i.slice();
    a[s] = 1;
    let l = new o.constructor(o.length / i[s]);
    n !== null && l.fill(n);
    for (let c = 0; c < o.length; ++c) {
      let p = 0;
      for (let u = i.length - 1, _ = c, d = 1; u >= 0; --u) {
        let m = i[u];
        if (u !== s) {
          let f = _ % m;
          p += f * d, d *= a[u];
        }
        _ = Math.floor(_ / m);
      }
      l[p] = t6(l[p], o[c], c, p);
    }
    return r || a.splice(s, 1), [e.type, l, a];
  }
  function cp(t6, e = null, s = 1, r = false) {
    let n = t6.data, o = t6.dims;
    if (e === null) {
      let d = n.reduce((w, x) => w + x, 0) / n.length, m = Math.sqrt(n.reduce((w, x) => w + (x - d) ** 2, 0) / (n.length - s)), f = new E(t6.type, [d], []);
      return [new E(t6.type, [m], []), f];
    }
    e = ht2(e, o.length);
    let i = Ea2(t6, e, r), a = i.data, [l, c, p] = Dr((_, d, m, f) => _ + (d - a[f]) ** 2, t6, e, r);
    for (let _ = 0; _ < c.length; ++_) c[_] = Math.sqrt(c[_] / (o[e] - s));
    return [new E(l, c, p), i];
  }
  function Ea2(t6, e = null, s = false) {
    let r = t6.dims, n = t6.data;
    if (e === null) {
      let l = n.reduce((c, p) => c + p, 0);
      return new E(t6.type, [l / n.length], []);
    }
    e = ht2(e, r.length);
    let [o, i, a] = Dr((l, c) => l + c, t6, e, s);
    if (r[e] !== 1) for (let l = 0; l < i.length; ++l) i[l] /= r[e];
    return new E(o, i, a);
  }
  function ap(t6) {
    let e = new Array(t6.length);
    for (let s = t6.length - 1, r = 1; s >= 0; --s) e[s] = r, r *= t6[s];
    return e;
  }
  function pp(t6, e, s, r) {
    let n = t6.reduce((o, i) => o * i, 1);
    return new E(s, new r(n).fill(e), t6);
  }
  function ve(t6, e) {
    let s, r;
    if (typeof e == "number") s = "float32", r = Float32Array;
    else if (typeof e == "bigint") s = "int64", r = BigInt64Array;
    else if (typeof e == "boolean") s = "bool", r = Uint8Array;
    else throw new Error(`Unsupported data type: ${typeof e}`);
    return pp(t6, e, s, r);
  }
  function qr2(t6, e) {
    return ve(t6.dims, e);
  }
  function Me(t6) {
    return pp(t6, 1n, "int64", BigInt64Array);
  }
  function Aa2(t6) {
    return Me(t6.dims);
  }
  function up(t6) {
    return pp(t6, 0n, "int64", BigInt64Array);
  }
  function _p(t6) {
    return up(t6.dims);
  }
  function ob(t6) {
    let e = t6.reduce((s, r) => s * r, 1);
    return new E("float32", Float32Array.from({ length: e }, () => ns2.gauss()), t6);
  }
  function ib(t6, e) {
    if (t6.dims.length !== 2) throw new Error("The tensor must have 2 dimensions");
    if (t6.dims.at(-1) % 8 !== 0) throw new Error("The last dimension of the tensor must be a multiple of 8");
    if (!["binary", "ubinary"].includes(e)) throw new Error("The precision must be either 'binary' or 'ubinary'");
    let s = e === "binary", r = s ? "int8" : "uint8", n = s ? Int8Array : Uint8Array, o = t6.data, i = new n(o.length / 8);
    for (let a = 0; a < o.length; ++a) {
      let l = o[a] > 0 ? 1 : 0, c = Math.floor(a / 8), p = a % 8;
      i[c] |= l << 7 - p, s && p === 0 && (i[c] -= 128);
    }
    return new E(r, i, [t6.dims[0], t6.dims[1] / 8]);
  }
  async function $s(t6) {
    if (!t6) throw new Error("modelId is required for get_tokenizer_files");
    return (await We(t6, "tokenizer_config.json", {})).exists ? ["tokenizer.json", "tokenizer_config.json"] : [];
  }
  async function dp(t6, e) {
    let s = await $s(t6);
    return await Promise.all(s.map((r) => Ie(t6, r, true, e)));
  }
  function jr2(t6) {
    let e = t6.dims;
    switch (e.length) {
      case 1:
        return t6.tolist();
      case 2:
        if (e[0] !== 1) throw new Error("Unable to decode tensor with `batch size !== 1`. Use `tokenizer.batch_decode(...)` for batched inputs.");
        return t6.tolist()[0];
      default:
        throw new Error(`Expected tensor to have 1-2 dimensions, got ${e.length}.`);
    }
  }
  var hA = ["bos_token", "eos_token", "unk_token", "sep_token", "pad_token", "cls_token", "mask_token"];
  function gA(t6, e, s, r) {
    for (let n of Object.keys(t6)) {
      let o = e - t6[n].length, i = s(n), a = new Array(o).fill(i);
      t6[n] = r === "right" ? Re(t6[n], a) : Re(a, t6[n]);
    }
  }
  function xA(t6, e) {
    for (let s of Object.keys(t6)) t6[s].length = e;
  }
  function is2(t6, ...e) {
    for (let s of e) {
      if (!Object.hasOwn(t6, s)) continue;
      let r = t6[s];
      if (r) if (typeof r == "object") {
        if (r.__type === "AddedToken") return r.content;
        throw Error(`Unknown token: ${r}`);
      } else return r;
    }
    return null;
  }
  function wA(t6) {
    let e = [];
    for (let s of t6.get_added_tokens_decoder().values()) s.special && e.push(s);
    return e;
  }
  var P = class extends xe {
    return_token_type_ids = false;
    padding_side = "right";
    constructor(e, s) {
      if (super(), this._tokenizerJSON = e, this._tokenizerConfig = s, this._tokenizer = new p0(e, s), this.config = s, this.padding_side = s.padding_side ?? this.padding_side, this.mask_token = is2(s, "mask_token"), this.mask_token_id = this._tokenizer.token_to_id(this.mask_token), this.pad_token = is2(s, "pad_token", "eos_token"), this.pad_token_id = this._tokenizer.token_to_id(this.pad_token), this.sep_token = is2(s, "sep_token"), this.sep_token_id = this._tokenizer.token_to_id(this.sep_token), this.unk_token = is2(s, "unk_token"), this.unk_token_id = this._tokenizer.token_to_id(this.unk_token), this.bos_token = is2(s, "bos_token"), this.bos_token_id = this._tokenizer.token_to_id(this.bos_token), this.eos_token = is2(s, "eos_token"), this.eos_token_id = this._tokenizer.token_to_id(this.eos_token), this.chat_template = s.chat_template ?? null, Array.isArray(this.chat_template)) {
        let n = /* @__PURE__ */ Object.create(null);
        for (let { name: o, template: i } of this.chat_template) {
          if (typeof o != "string" || typeof i != "string") throw new Error('Chat template must be a list of objects with "name" and "template" properties');
          n[o] = i;
        }
        this.chat_template = n;
      }
      this._compiled_template_cache = /* @__PURE__ */ new Map();
      let r = wA(this._tokenizer);
      this.all_special_ids = r.map((n) => n.id), this.all_special_tokens = r.map((n) => n.content);
    }
    static async from_pretrained(e, { progress_callback: s = null, config: r = null, cache_dir: n = null, local_files_only: o = false, revision: i = "main" } = {}) {
      let a = await dp(e, { progress_callback: s, config: r, cache_dir: n, local_files_only: o, revision: i });
      return new this(...a);
    }
    get_vocab() {
      return this._tokenizer.get_vocab();
    }
    get model_max_length() {
      return this._tokenizerConfig.model_max_length ?? 1 / 0;
    }
    get add_eos_token() {
      return this._tokenizerConfig.add_eos_token;
    }
    get add_bos_token() {
      return this._tokenizerConfig.add_bos_token;
    }
    convert_tokens_to_ids(e) {
      return typeof e == "string" ? this._tokenizer.token_to_id(e) : e.map((s) => this._tokenizer.token_to_id(s));
    }
    _call(e, s = {}) {
      let { text_pair: r = null, add_special_tokens: n = true, padding: o = false, return_token_type_ids: i = null } = s, { truncation: a = null, max_length: l = null } = s, c = s.return_tensor ?? true, p = Array.isArray(e), u;
      if (p) {
        if (e.length === 0) throw Error("text array must be non-empty");
        if (r !== null) {
          if (Array.isArray(r)) {
            if (e.length !== r.length) throw Error("text and text_pair must have the same length");
          } else throw Error("text_pair must also be an array");
          u = e.map((d, m) => this._encode_plus(d, { text_pair: r[m], add_special_tokens: n, return_token_type_ids: i }));
        } else u = e.map((d) => this._encode_plus(d, { add_special_tokens: n, return_token_type_ids: i }));
      } else {
        if (e == null) throw Error("text may not be null or undefined");
        if (Array.isArray(r)) throw Error("When specifying `text_pair`, since `text` is a string, `text_pair` must also be a string (i.e., not an array).");
        u = [this._encode_plus(e, { text_pair: r, add_special_tokens: n, return_token_type_ids: i })];
      }
      if (l === null ? l = this.model_max_length : a === null && (o === true ? (F.warn("`max_length` is ignored when `padding: true` and there is no truncation strategy. To pad to max length, use `padding: 'max_length'`."), l = this.model_max_length) : o === false && (F.warn("Truncation was not explicitly activated but `max_length` is provided a specific value, please use `truncation: true` to explicitly truncate examples to max length."), a = true)), o === true && (l = Math.min(de(u.map((d) => d.input_ids.length))[0], l ?? 1 / 0)), l = Math.min(l, this.model_max_length ?? 1 / 0), o || a) for (let d = 0; d < u.length; ++d) u[d].input_ids.length !== l && (u[d].input_ids.length > l ? a && xA(u[d], l) : o && gA(u[d], l, (m) => m === "input_ids" ? this.pad_token_id : 0, this.padding_side));
      let _ = {};
      if (c) {
        if (!(o && a) && u.some((m) => {
          for (let f of Object.keys(m)) if (m[f].length !== u[0][f]?.length) return true;
          return false;
        })) throw Error("Unable to create tensor, you should probably activate truncation and/or padding with 'padding=true' and 'truncation=true' to have batched tensors with the same length.");
        let d = [u.length, u[0].input_ids.length];
        for (let m of Object.keys(u[0])) _[m] = new E("int64", BigInt64Array.from(u.flatMap((f) => f[m]).map(BigInt)), d);
      } else {
        for (let d of Object.keys(u[0])) _[d] = u.map((m) => m[d]);
        if (!p) for (let d of Object.keys(_)) _[d] = _[d][0];
      }
      return _;
    }
    _encode_text(e) {
      return e === null ? null : this._tokenizer.encode(e).tokens;
    }
    _encode_plus(e, { text_pair: s = null, add_special_tokens: r = true, return_token_type_ids: n = null } = {}) {
      let { ids: o, attention_mask: i, token_type_ids: a } = this._tokenizer.encode(e, { text_pair: s, add_special_tokens: r, return_token_type_ids: n ?? this.return_token_type_ids });
      return { input_ids: o, attention_mask: i, ...a ? { token_type_ids: a } : {} };
    }
    tokenize(e, { pair: s = null, add_special_tokens: r = false } = {}) {
      return this._tokenizer.tokenize(e, { text_pair: s, add_special_tokens: r });
    }
    encode(e, { text_pair: s = null, add_special_tokens: r = true, return_token_type_ids: n = null } = {}) {
      return this._tokenizer.encode(e, { text_pair: s, add_special_tokens: r, return_token_type_ids: n }).ids;
    }
    batch_decode(e, s = {}) {
      return e instanceof E && (e = e.tolist()), e.map((r) => this.decode(r, s));
    }
    decode(e, s = {}) {
      if (e instanceof E && (e = jr2(e)), !Array.isArray(e) || e.length === 0 || !Vy(e[0])) throw Error("token_ids must be a non-empty array of integers.");
      return this.decode_single(e, s);
    }
    decode_single(e, { skip_special_tokens: s = false, clean_up_tokenization_spaces: r = null }) {
      return this._tokenizer.decode(e, { skip_special_tokens: s, clean_up_tokenization_spaces: r });
    }
    get_chat_template({ chat_template: e = null, tools: s = null } = {}) {
      if (this.chat_template && typeof this.chat_template == "object") {
        let r = this.chat_template;
        if (e !== null && Object.hasOwn(r, e)) e = r[e];
        else if (e === null) if (s !== null && "tool_use" in r) e = r.tool_use;
        else if ("default" in r) e = r.default;
        else throw Error(`This model has multiple chat templates with no default specified! Please either pass a chat template or the name of the template you wish to use to the 'chat_template' argument. Available template names are ${Object.keys(r).sort()}.`);
      } else if (e === null) if (this.chat_template) e = this.chat_template;
      else throw Error("Cannot use apply_chat_template() because tokenizer.chat_template is not set and no template argument was passed! For information about writing templates and setting the tokenizer.chat_template attribute, please see the documentation at https://huggingface.co/docs/transformers/main/en/chat_templating");
      return e;
    }
    apply_chat_template(e, s = {}) {
      let { tools: r = null, documents: n = null, chat_template: o = null, add_generation_prompt: i = false, tokenize: a = true, padding: l = false, truncation: c = false, max_length: p = null, return_tensor: u = true, return_dict: _ = true, tokenizer_kwargs: d = {}, ...m } = s;
      if (o = this.get_chat_template({ chat_template: o, tools: r }), typeof o != "string") throw Error(`chat_template must be a string, but got ${typeof o}`);
      let f = this._compiled_template_cache.get(o);
      f === void 0 && (f = new k0(o), this._compiled_template_cache.set(o, f));
      let g = /* @__PURE__ */ Object.create(null);
      for (let x of hA) {
        let y = is2(this.config, x);
        y && (g[x] = y);
      }
      let w = f.render({ messages: e, add_generation_prompt: i, tools: r, documents: n, ...g, ...m });
      if (a) {
        let x = this._call(w, { add_special_tokens: false, padding: l, truncation: c, max_length: p, return_tensor: u, ...d });
        return _ ? x : x.input_ids;
      }
      return w;
    }
  };
  function Fs2(t6, e, s, r) {
    if (!("language_codes" in t6) || !Array.isArray(t6.language_codes)) throw new Error("Tokenizer must have `language_codes` attribute set and it should be an array of language ids.");
    if (!("languageRegex" in t6) || !(t6.languageRegex instanceof RegExp)) throw new Error("Tokenizer must have `languageRegex` attribute set and it should be a regular expression.");
    if (!("lang_to_token" in t6) || typeof t6.lang_to_token != "function") throw new Error("Tokenizer must have `lang_to_token` attribute set and it should be a function.");
    let n = r.src_lang, o = r.tgt_lang;
    if (!t6.language_codes.includes(o)) throw new Error(`Target language code "${o}" is not valid. Must be one of: {${t6.language_codes.join(", ")}}`);
    if (n !== void 0) {
      if (!t6.language_codes.includes(n)) throw new Error(`Source language code "${n}" is not valid. Must be one of: {${t6.language_codes.join(", ")}}`);
      for (let i of t6._tokenizer.post_processor.config.single) if ("SpecialToken" in i && t6.languageRegex.test(i.SpecialToken.id)) {
        i.SpecialToken.id = t6.lang_to_token(n);
        break;
      }
    }
    return r.forced_bos_token_id = t6._tokenizer.token_to_id(t6.lang_to_token(o)), t6._call(e, s);
  }
  var ou = {};
  Os2(ou, { AlbertTokenizer: () => fp, AutoTokenizer: () => W, BartTokenizer: () => mp, BertTokenizer: () => hp, BlenderbotSmallTokenizer: () => gp, BlenderbotTokenizer: () => xp, BloomTokenizer: () => wp, CLIPTokenizer: () => bp, CamembertTokenizer: () => yp, CodeGenTokenizer: () => vp, CodeLlamaTokenizer: () => kp, CohereAsrTokenizer: () => Ap, CohereTokenizer: () => Ep, ConvBertTokenizer: () => Mp, DebertaTokenizer: () => Op, DebertaV2Tokenizer: () => Sp, DistilBertTokenizer: () => Ip, ElectraTokenizer: () => zp, EsmTokenizer: () => Tp, FalconTokenizer: () => Cp, GPT2Tokenizer: () => Lp, GPTNeoXTokenizer: () => Np, GemmaTokenizer: () => Pp, HerbertTokenizer: () => $p, LlamaTokenizer: () => Fp, M2M100Tokenizer: () => Rp, MBart50Tokenizer: () => qp, MBartTokenizer: () => Br, MPNetTokenizer: () => Up, MarianTokenizer: () => Dp, MgpstrTokenizer: () => jp, MobileBertTokenizer: () => Bp, NllbTokenizer: () => Gp, NougatTokenizer: () => Wp, PreTrainedTokenizer: () => P, Qwen2Tokenizer: () => Vp, RoFormerTokenizer: () => Kp, RobertaTokenizer: () => Hp, SiglipTokenizer: () => Xp, SpeechT5Tokenizer: () => Qp, SqueezeBertTokenizer: () => Yp, T5Tokenizer: () => Jp, TokenizersBackend: () => P, VitsTokenizer: () => eu, Wav2Vec2CTCTokenizer: () => tu, WhisperTokenizer: () => su, XLMRobertaTokenizer: () => ru, XLMTokenizer: () => nu });
  var fp = class extends P {
    return_token_type_ids = true;
  };
  var mp = class extends P {
  };
  var hp = class extends P {
    return_token_type_ids = true;
  };
  var gp = class extends P {
  };
  var xp = class extends P {
  };
  var wp = class extends P {
  };
  var yp = class extends P {
  };
  var bp = class extends P {
  };
  var kp = class extends P {
  };
  var vp = class extends P {
  };
  var Ep = class extends P {
  };
  var Ap = class extends P {
  };
  var Mp = class extends P {
    return_token_type_ids = true;
  };
  var Sp = class extends P {
    return_token_type_ids = true;
  };
  var Op = class extends P {
    return_token_type_ids = true;
  };
  var Ip = class extends P {
  };
  var zp = class extends P {
    return_token_type_ids = true;
  };
  var Tp = class extends P {
  };
  var Cp = class extends P {
  };
  var Pp = class extends P {
  };
  var Np = class extends P {
  };
  var Lp = class extends P {
  };
  var $p = class extends P {
    return_token_type_ids = true;
  };
  var Fp = class extends P {
    padding_side = "left";
  };
  var Rp = class extends P {
    constructor(e, s) {
      super(e, s), this.languageRegex = /^__[a-z]{2,3}__$/, this.language_codes = this.all_special_tokens.filter((r) => this.languageRegex.test(r)).map((r) => r.slice(2, -2)), this.lang_to_token = (r) => `__${r}__`;
    }
    _build_translation_inputs(e, s, r) {
      return Fs2(this, e, s, r);
    }
  };
  var Dp = class extends P {
    constructor(e, s) {
      super(e, s), this.languageRegex = /^(>>\w+<<)\s*/g, this.supported_language_codes = Array.from(this.get_vocab().keys()).filter((r) => this.languageRegex.test(r)), F.warn('WARNING: `MarianTokenizer` is not yet supported by Hugging Face\'s "fast" tokenizers library. Therefore, you may experience slightly inaccurate results.');
    }
    _encode_text(e) {
      if (e === null) return null;
      let [s, ...r] = e.trim().split(this.languageRegex);
      if (r.length === 0) return super._encode_text(s);
      if (r.length === 2) {
        let [n, o] = r;
        return this.supported_language_codes.includes(n) || F.warn(`Unsupported language code "${n}" detected, which may lead to unexpected behavior. Should be one of: ${JSON.stringify(this.supported_language_codes)}`), Re([n], super._encode_text(o));
      }
    }
  };
  var Br = class extends P {
    constructor(e, s) {
      super(e, s), this.languageRegex = /^[a-z]{2}_[A-Z]{2}$/, this.language_codes = this.all_special_tokens.filter((r) => this.languageRegex.test(r)).map((r) => r), this.lang_to_token = (r) => r;
    }
    _build_translation_inputs(e, s, r) {
      return Fs2(this, e, s, r);
    }
  };
  var qp = class extends Br {
  };
  var jp = class extends P {
  };
  var Bp = class extends P {
    return_token_type_ids = true;
  };
  var Up = class extends P {
  };
  var Gp = class extends P {
    constructor(e, s) {
      super(e, s), this.languageRegex = /^[a-z]{3}_[A-Z][a-z]{3}$/, this.language_codes = this.all_special_tokens.filter((r) => this.languageRegex.test(r)), this.lang_to_token = (r) => r;
    }
    _build_translation_inputs(e, s, r) {
      return Fs2(this, e, s, r);
    }
  };
  var Wp = class extends P {
  };
  var Vp = class extends P {
  };
  var Hp = class extends P {
  };
  var Kp = class extends P {
    return_token_type_ids = true;
  };
  var Xp = class extends P {
  };
  var Qp = class extends P {
  };
  var Yp = class extends P {
    return_token_type_ids = true;
  };
  var Jp = class extends P {
  };
  var Zp = class extends Je {
    decode_chain(e) {
      let s = "";
      for (let r = 1; r < e.length; r += 2) s += e[r];
      return [s];
    }
  };
  var eu = class extends P {
    constructor(e, s) {
      super(e, s), this._tokenizer.decoder = new Zp({ type: "VitsDecoder" });
    }
  };
  var tu = class extends P {
  };
  var ab = [["en", "english"], ["zh", "chinese"], ["de", "german"], ["es", "spanish"], ["ru", "russian"], ["ko", "korean"], ["fr", "french"], ["ja", "japanese"], ["pt", "portuguese"], ["tr", "turkish"], ["pl", "polish"], ["ca", "catalan"], ["nl", "dutch"], ["ar", "arabic"], ["sv", "swedish"], ["it", "italian"], ["id", "indonesian"], ["hi", "hindi"], ["fi", "finnish"], ["vi", "vietnamese"], ["he", "hebrew"], ["uk", "ukrainian"], ["el", "greek"], ["ms", "malay"], ["cs", "czech"], ["ro", "romanian"], ["da", "danish"], ["hu", "hungarian"], ["ta", "tamil"], ["no", "norwegian"], ["th", "thai"], ["ur", "urdu"], ["hr", "croatian"], ["bg", "bulgarian"], ["lt", "lithuanian"], ["la", "latin"], ["mi", "maori"], ["ml", "malayalam"], ["cy", "welsh"], ["sk", "slovak"], ["te", "telugu"], ["fa", "persian"], ["lv", "latvian"], ["bn", "bengali"], ["sr", "serbian"], ["az", "azerbaijani"], ["sl", "slovenian"], ["kn", "kannada"], ["et", "estonian"], ["mk", "macedonian"], ["br", "breton"], ["eu", "basque"], ["is", "icelandic"], ["hy", "armenian"], ["ne", "nepali"], ["mn", "mongolian"], ["bs", "bosnian"], ["kk", "kazakh"], ["sq", "albanian"], ["sw", "swahili"], ["gl", "galician"], ["mr", "marathi"], ["pa", "punjabi"], ["si", "sinhala"], ["km", "khmer"], ["sn", "shona"], ["yo", "yoruba"], ["so", "somali"], ["af", "afrikaans"], ["oc", "occitan"], ["ka", "georgian"], ["be", "belarusian"], ["tg", "tajik"], ["sd", "sindhi"], ["gu", "gujarati"], ["am", "amharic"], ["yi", "yiddish"], ["lo", "lao"], ["uz", "uzbek"], ["fo", "faroese"], ["ht", "haitian creole"], ["ps", "pashto"], ["tk", "turkmen"], ["nn", "nynorsk"], ["mt", "maltese"], ["sa", "sanskrit"], ["lb", "luxembourgish"], ["my", "myanmar"], ["bo", "tibetan"], ["tl", "tagalog"], ["mg", "malagasy"], ["as", "assamese"], ["tt", "tatar"], ["haw", "hawaiian"], ["ln", "lingala"], ["ha", "hausa"], ["ba", "bashkir"], ["jw", "javanese"], ["su", "sundanese"]];
  var Ur = new Map(ab);
  var yA = new Map([...ab.map(([t6, e]) => [e, t6]), ["burmese", "my"], ["valencian", "ca"], ["flemish", "nl"], ["haitian", "ht"], ["letzeburgesch", "lb"], ["pushto", "ps"], ["panjabi", "pa"], ["moldavian", "ro"], ["moldovan", "ro"], ["sinhalese", "si"], ["castilian", "es"]]);
  function lb(t6) {
    t6 = t6.toLowerCase();
    let e = yA.get(t6);
    if (e === void 0) {
      let s = t6.match(/^<\|([a-z]{2})\|>$/);
      if (s && (t6 = s[1]), Ur.has(t6)) e = t6;
      else {
        let n = t6.length === 2 ? Ur.keys() : Ur.values();
        throw new Error(`Language "${t6}" is not supported. Must be one of: ${JSON.stringify(Array.from(n))}`);
      }
    }
    return e;
  }
  var bA = "\\p{P}\\u0021-\\u002F\\u003A-\\u0040\\u005B-\\u0060\\u007B-\\u007E";
  var cb = new RegExp(`^[${bA}]+$`, "gu");
  var kA = 0.1;
  var su = class extends P {
    get timestamp_begin() {
      return this._tokenizer.token_to_id("<|notimestamps|>") + 1;
    }
    _decode_asr(e, { return_timestamps: s = false, return_language: r = false, time_precision: n = null, force_full_sequences: o = true } = {}) {
      if (n === null) throw Error("Must specify time_precision");
      let i = null, a = s === "word";
      function l() {
        return { language: i, timestamp: [null, null], text: "" };
      }
      let c = [], p = l(), u = 0, _ = this.timestamp_begin, m = _ + 1500, f = [], g = [], w = false, x = null, y = new Set(this.all_special_ids);
      for (let k2 of e) {
        let S = k2.tokens, I = a ? k2.token_timestamps : null, $2 = null, C = _;
        if ("stride" in k2) {
          let [H, j, B] = k2.stride;
          if (u -= j, x = H - B, j && (C = j / n + _), B) for (let Z = S.length - 1; Z >= 0; --Z) {
            let D = Number(S[Z]);
            if (D >= _) {
              if ($2 !== null && (D - _) * n < x) break;
              $2 = D;
            }
          }
        }
        let R = [], V = [];
        for (let H = 0; H < S.length; ++H) {
          let j = Number(S[H]);
          if (y.has(j)) {
            let B = this.decode([j]), Z = Ur.get(B.slice(2, -2));
            if (Z !== void 0) {
              if (i !== null && Z !== i && !s) {
                f.push(R);
                let D = this.findLongestCommonSequence(f)[0], A = this.decode(D);
                p.text = A, c.push(p), f = [], R = [], p = l();
              }
              i = p.language = Z;
            }
          } else if (j >= _ && j <= m) {
            let B = (j - _) * n + u, Z = os2(B, 2);
            if ($2 !== null && j >= $2) w = true;
            else if (w || f.length > 0 && j < C) w = false;
            else if (p.timestamp[0] === null) p.timestamp[0] = Z;
            else if (Z !== p.timestamp[0]) {
              p.timestamp[1] = Z, f.push(R), a && g.push(V);
              let [D, A] = this.findLongestCommonSequence(f, g), O = this.decode(D);
              if (p.text = O, a && (p.words = this.collateWordTimestamps(D, A, i), p.words.length > 0 && p.timestamp[1] !== null)) for (let T of p.words) T.timestamp[1] > p.timestamp[1] && p.timestamp[1] >= T.timestamp[0] && (T.timestamp[1] = p.timestamp[1]);
              c.push(p), f = [], R = [], g = [], V = [], p = l();
            }
          } else if (R.push(j), a) {
            let B = os2(I[H] + u, 2), Z;
            if (H + 1 < I.length) {
              Z = os2(I[H + 1] + u, 2);
              let D = this.decode([j]);
              cb.test(D) && (Z = os2(Math.min(B + n, Z), 2));
            } else Z = null;
            V.push([B, Z]);
          }
        }
        if ("stride" in k2) {
          let [H, j, B] = k2.stride;
          u += H - B;
        }
        R.length > 0 ? (f.push(R), a && g.push(V)) : f.every((H) => H.length === 0) && (p = l(), f = [], R = [], g = [], V = []);
      }
      if (f.length > 0) {
        if (o && s) throw new Error("Whisper did not predict an ending timestamp, which can happen if audio is cut off in the middle of a word. Also make sure WhisperTimeStampLogitsProcessor was used during generation.");
        let [k2, S] = this.findLongestCommonSequence(f, g), I = this.decode(k2);
        p.text = I, a && (p.words = this.collateWordTimestamps(k2, S, i)), c.push(p);
      }
      let b = /* @__PURE__ */ Object.create(null), v = c.map((k2) => k2.text).join("");
      if (s || r) {
        for (let k2 = 0; k2 < c.length; ++k2) {
          let S = c[k2];
          s || delete S.timestamp, r || delete S.language;
        }
        if (a) {
          let k2 = [];
          for (let S of c) for (let I of S.words) k2.push(I);
          b = { chunks: k2 };
        } else b = { chunks: c };
      }
      return [v, b];
    }
    findLongestCommonSequence(e, s = null) {
      let r = e[0], n = r.length, o = [], i = Array.isArray(s) && s.length > 0, a = i ? [] : null, l = i ? s[0] : null;
      for (let c = 1; c < e.length; ++c) {
        let p = e[c], u = 0, _ = [n, n, 0, 0], d = p.length;
        for (let b = 1; b < n + d; ++b) {
          let v = Math.max(0, n - b), k2 = Math.min(n, n + d - b), S = r.slice(v, k2), I = Math.max(0, b - n), $2 = Math.min(d, b), C = p.slice(I, $2);
          if (S.length !== C.length) throw new Error("There is a bug within whisper `decode_asr` function, please report it. Dropping to prevent bad inference.");
          let R;
          i ? R = S.filter((j, B) => j === C[B] && l[v + B][0] - kA <= s[c][I + B][0]).length : R = S.filter((j, B) => j === C[B]).length;
          let V = b / 1e4, H = R / b + V;
          R > 1 && H > u && (u = H, _ = [v, k2, I, $2]);
        }
        let [m, f, g, w] = _, x = Math.floor((f + m) / 2), y = Math.floor((w + g) / 2);
        if (i && u === 0 && n > 0) {
          let b = l[n - 1][0], v = s[c].findIndex((k2) => k2[0] >= b);
          y = v === -1 ? p.length : v;
        }
        o.push(...r.slice(0, x)), r = p.slice(y), n = r.length, i && (a.push(...l.slice(0, x)), l = s[c].slice(y));
      }
      return o.push(...r), i ? (a.push(...l), [o, a]) : [o, []];
    }
    collateWordTimestamps(e, s, r) {
      let [n, o, i] = this.combineTokensIntoWords(e, r), a = [];
      for (let l = 0; l < n.length; ++l) {
        let c = i[l];
        a.push({ text: n[l], timestamp: [s[c.at(0)][0], s[c.at(-1)][1]] });
      }
      return a;
    }
    combineTokensIntoWords(e, s, r = `"'\u201C\xA1\xBF([{-`, n = `"'.\u3002,\uFF0C!\uFF01?\uFF1F:\uFF1A\u201D)]}\u3001`) {
      s = s ?? "english";
      let o, i, a;
      return ["chinese", "japanese", "thai", "lao", "myanmar"].includes(s) ? [o, i, a] = this.splitTokensOnUnicode(e) : [o, i, a] = this.splitTokensOnSpaces(e), this.mergePunctuations(o, i, a, r, n);
    }
    decode(e, s) {
      let r;
      return s?.decode_with_timestamps ? (e instanceof E && (e = jr2(e)), r = this.decodeWithTimestamps(e, s)) : r = super.decode(e, s), r;
    }
    decodeWithTimestamps(e, s) {
      let r = s?.time_precision ?? 0.02, n = this.all_special_ids.at(-1) + 1, o = [[]];
      for (let i of e) if (i = Number(i), i >= n) {
        let a = ((i - n) * r).toFixed(2);
        o.push(`<|${a}|>`), o.push([]);
      } else o[o.length - 1].push(i);
      return o = o.map((i) => typeof i == "string" ? i : super.decode(i, s)), o.join("");
    }
    splitTokensOnUnicode(e) {
      let s = this.decode(e, { decode_with_timestamps: true }), r = "\uFFFD", n = [], o = [], i = [], a = [], l = [], c = 0;
      for (let p = 0; p < e.length; ++p) {
        let u = e[p];
        a.push(u), l.push(p);
        let _ = this.decode(a, { decode_with_timestamps: true });
        (!_.includes(r) || s[c + _.indexOf(r)] === r) && (n.push(_), o.push(a), i.push(l), a = [], l = [], c += _.length);
      }
      return [n, o, i];
    }
    splitTokensOnSpaces(e) {
      let [s, r, n] = this.splitTokensOnUnicode(e), o = [], i = [], a = [];
      for (let l = 0; l < s.length; ++l) {
        let c = s[l], p = r[l], u = n[l], _ = p[0] >= this._tokenizer.token_to_id("<|endoftext|>"), d = c.startsWith(" "), m = c.trim(), f = cb.test(m);
        if (_ || d || f || o.length === 0) o.push(c), i.push(p), a.push(u);
        else {
          let g = o.length - 1;
          o[g] += c, i[g].push(...p), a[g].push(...u);
        }
      }
      return [o, i, a];
    }
    mergePunctuations(e, s, r, n, o) {
      let i = structuredClone(e), a = structuredClone(s), l = structuredClone(r), c = i.length - 2, p = i.length - 1;
      for (; c >= 0; ) i[c].startsWith(" ") && n.includes(i[c].trim()) ? (i[p] = i[c] + i[p], a[p] = Re(a[c], a[p]), l[p] = Re(l[c], l[p]), i[c] = "", a[c] = [], l[c] = []) : p = c, --c;
      for (c = 0, p = 1; p < i.length; ) !i[c].endsWith(" ") && o.includes(i[p]) ? (i[c] += i[p], a[c] = Re(a[c], a[p]), l[c] = Re(l[c], l[p]), i[p] = "", a[p] = [], l[p] = []) : c = p, ++p;
      return [i.filter((u) => u), a.filter((u) => u.length > 0), l.filter((u) => u.length > 0)];
    }
  };
  var ru = class extends P {
  };
  var nu = class extends P {
    return_token_type_ids = true;
    constructor(e, s) {
      super(e, s), F.warn('WARNING: `XLMTokenizer` is not yet supported by Hugging Face\'s "fast" tokenizers library. Therefore, you may experience slightly inaccurate results.');
    }
  };
  var W = class {
    static async from_pretrained(e, { progress_callback: s = null, config: r = null, cache_dir: n = null, local_files_only: o = false, revision: i = "main" } = {}) {
      let [a, l] = await dp(e, { progress_callback: s, config: r, cache_dir: n, local_files_only: o, revision: i }), c = l.tokenizer_class?.replace(/Fast$/, "") ?? "PreTrainedTokenizer", p = ou[c];
      return p || (F.warn(`Unknown tokenizer class "${c}", attempting to construct from base class.`), p = P), new p(a, l);
    }
  };
  var $t2 = "https://github.com/huggingface/transformers.js/issues/new/choose";
  var Gr = "preprocessor_config.json";
  var bt = Gr;
  var Ma2 = "processor_config.json";
  var Sa2 = "chat_template.jinja";
  var U = class extends xe {
    static classes = ["image_processor_class", "tokenizer_class", "feature_extractor_class"];
    static uses_processor_config = false;
    static uses_chat_template_file = false;
    constructor(e, s, r) {
      super(), this.config = e, this.components = s, this.chat_template = r;
    }
    get image_processor() {
      return this.components.image_processor;
    }
    get tokenizer() {
      return this.components.tokenizer;
    }
    get feature_extractor() {
      return this.components.feature_extractor;
    }
    apply_chat_template(e, s = {}) {
      if (!this.tokenizer) throw new Error("Unable to apply chat template without a tokenizer.");
      return this.tokenizer.apply_chat_template(e, { tokenize: false, chat_template: this.chat_template ?? void 0, ...s });
    }
    batch_decode(...e) {
      if (!this.tokenizer) throw new Error("Unable to decode without a tokenizer.");
      return this.tokenizer.batch_decode(...e);
    }
    decode(...e) {
      if (!this.tokenizer) throw new Error("Unable to decode without a tokenizer.");
      return this.tokenizer.decode(...e);
    }
    async _call(e, ...s) {
      for (let r of [this.image_processor, this.feature_extractor, this.tokenizer]) if (r) return r(e, ...s);
      throw new Error("No image processor, feature extractor, or tokenizer found.");
    }
    static async from_pretrained(e, s = {}) {
      let [r, n, o] = await Promise.all([this.uses_processor_config ? Ie(e, Ma2, true, s) : {}, Promise.all(this.classes.filter((i) => i in this).map(async (i) => {
        let a = await this[i].from_pretrained(e, s);
        return [i.replace(/_class$/, ""), a];
      })).then(Object.fromEntries), this.uses_chat_template_file ? $r(e, Sa2, true, s) : null]);
      return new this(r, n, o);
    }
  };
  var Za2 = {};
  Os2(Za2, { ChatterboxProcessor: () => bu, CohereAsrProcessor: () => ku, Florence2Processor: () => f_, Gemma3Processor: () => m_, Gemma3nProcessor: () => h_, Gemma4Processor: () => g_, Glm46VProcessor: () => x_, GraniteSpeechProcessor: () => w_, GroundingDinoProcessor: () => y_, Idefics3Processor: () => Xa2, JinaCLIPProcessor: () => k_, Lfm2VlProcessor: () => v_, LlavaProcessor: () => E_, MgpstrProcessor: () => A_, MoonshineProcessor: () => M_, OwlViTProcessor: () => S_, PaliGemmaProcessor: () => O_, Phi3VProcessor: () => I_, PixtralProcessor: () => z_, Processor: () => U, PyAnnoteProcessor: () => T_, Qwen2VLProcessor: () => ls2, Qwen2_5_VLProcessor: () => sn2, Qwen3VLProcessor: () => C_, Sam2Processor: () => Qa2, Sam2VideoProcessor: () => P_, SamProcessor: () => rn2, SmolVLMProcessor: () => Xa2, SpeechT5Processor: () => N_, UltravoxProcessor: () => L_, VLChatProcessor: () => b_, VoxtralProcessor: () => $_, VoxtralRealtimeProcessor: () => R_, Wav2Vec2Processor: () => D_, Wav2Vec2ProcessorWithLM: () => q_, WhisperProcessor: () => j_ });
  var le2 = class extends xe {
    constructor(e) {
      super(), this.config = e;
    }
    static async from_pretrained(e, s = {}) {
      let r = await Ie(e, Gr, true, s);
      return new this(r);
    }
  };
  function ce(t6, e) {
    if (!(t6 instanceof Float32Array || t6 instanceof Float64Array)) throw new Error(`${e} expects input to be a Float32Array or a Float64Array, but got ${t6?.constructor?.name ?? typeof t6} instead. If using the feature extractor directly, remember to use \`read_audio(url, sampling_rate)\` to obtain the raw audio data of the file/url.`);
  }
  var Jr2 = {};
  Os2(Jr2, { ASTFeatureExtractor: () => lu, ChatterboxFeatureExtractor: () => cu, ClapFeatureExtractor: () => pu, CohereAsrFeatureExtractor: () => uu, DacFeatureExtractor: () => Kr2, EncodecFeatureExtractor: () => Vr, FeatureExtractor: () => le2, Gemma3nAudioFeatureExtractor: () => Xr2, Gemma4AudioFeatureExtractor: () => Qr2, GraniteSpeechFeatureExtractor: () => _u, MoonshineFeatureExtractor: () => du, ParakeetFeatureExtractor: () => Hr2, PyAnnoteFeatureExtractor: () => Yr2, SeamlessM4TFeatureExtractor: () => fu, SnacFeatureExtractor: () => mu, SpeechT5FeatureExtractor: () => hu, VoxtralRealtimeFeatureExtractor: () => wu, Wav2Vec2FeatureExtractor: () => gu, WeSpeakerFeatureExtractor: () => xu, WhisperFeatureExtractor: () => yu });
  var vA = () => {
  };
  var pb = { fromWeb: vA };
  var EA = () => {
  };
  var ub = EA;
  async function Oa2(t6, e) {
    if (K2.IS_BROWSER_ENV) {
      if (K2.IS_WEBWORKER_ENV) throw new Error("Unable to save a file from a Web Worker.");
      let s = URL.createObjectURL(e), r = document.createElement("a");
      r.href = s, r.download = t6, r.click(), r.remove(), URL.revokeObjectURL(s);
    } else if (K2.IS_FS_AVAILABLE) {
      let s = e.stream(), r = pb.fromWeb(s), n = Fe.createWriteStream(t6);
      await ub(r, n);
    } else throw new Error("Unable to save because filesystem is disabled in this environment.");
  }
  async function fb(t6, e) {
    if (typeof AudioContext > "u") throw Error("Unable to load audio from path/URL since `AudioContext` is not available in your environment. Instead, audio data should be passed directly to the pipeline/processor. For more information and some example code, see https://huggingface.co/docs/transformers.js/guides/node-audio-processing.");
    let s = await (await zt2(t6)).arrayBuffer(), r = new AudioContext({ sampleRate: e });
    typeof e > "u" && F.warn(`No sampling rate provided, using default of ${r.sampleRate}Hz.`);
    let n = await r.decodeAudioData(s), o;
    if (n.numberOfChannels === 2) {
      let i = Math.sqrt(2), a = n.getChannelData(0), l = n.getChannelData(1);
      o = new Float32Array(a.length);
      for (let c = 0; c < n.length; ++c) o[c] = i * (a[c] + l[c]) / 2;
    } else o = n.getChannelData(0);
    return o;
  }
  var au = fb;
  function mb(t6, e) {
    if (t6 < 1) return new Float64Array();
    if (t6 === 1) return new Float64Array([1]);
    let s = 1 - e, r = 2 * Math.PI / (t6 - 1), n = new Float64Array(t6);
    for (let o = 0; o < t6; ++o) n[o] = e - s * Math.cos(o * r);
    return n;
  }
  function _b(t6) {
    return mb(t6, 0.5);
  }
  function AA(t6) {
    return mb(t6, 0.54);
  }
  var MA = { htk: (t6) => 2595 * Math.log10(1 + t6 / 700), kaldi: (t6) => 1127 * Math.log(1 + t6 / 700), slaney: (t6, e = 1e3, s = 15, r = 27 / Math.log(6.4)) => t6 >= e ? s + Math.log(t6 / e) * r : 3 * t6 / 200 };
  function iu(t6, e = "htk") {
    let s = MA[e];
    if (!s) throw new Error('mel_scale should be one of "htk", "slaney" or "kaldi".');
    return typeof t6 == "number" ? s(t6) : t6.map((r) => s(r));
  }
  var SA = { htk: (t6) => 700 * (10 ** (t6 / 2595) - 1), kaldi: (t6) => 700 * (Math.exp(t6 / 1127) - 1), slaney: (t6, e = 1e3, s = 15, r = Math.log(6.4) / 27) => t6 >= s ? e * Math.exp(r * (t6 - s)) : 200 * t6 / 3 };
  function OA(t6, e = "htk") {
    let s = SA[e];
    if (!s) throw new Error('mel_scale should be one of "htk", "slaney" or "kaldi".');
    return typeof t6 == "number" ? s(t6) : t6.map((r) => s(r));
  }
  function IA(t6, e) {
    let s = Float64Array.from({ length: e.length - 1 }, (i, a) => e[a + 1] - e[a]), r = Array.from({ length: t6.length }, () => new Array(e.length));
    for (let i = 0; i < t6.length; ++i) {
      let a = r[i];
      for (let l = 0; l < e.length; ++l) a[l] = e[l] - t6[i];
    }
    let n = e.length - 2, o = Array.from({ length: n }, () => new Array(t6.length));
    for (let i = 0; i < t6.length; ++i) {
      let a = r[i];
      for (let l = 0; l < n; ++l) {
        let c = -a[l] / s[l], p = a[l + 2] / s[l + 1];
        o[l][i] = Math.max(0, Math.min(c, p));
      }
    }
    return o;
  }
  function db(t6, e, s) {
    let r = (e - t6) / (s - 1);
    return Float64Array.from({ length: s }, (n, o) => t6 + r * o);
  }
  function Pe(t6, e, s, r, n, o = null, i = "htk", a = false) {
    if (o !== null && o !== "slaney") throw new Error('norm must be one of null or "slaney"');
    if (t6 < 2) throw new Error(`Require num_frequency_bins: ${t6} >= 2`);
    if (s > r) throw new Error(`Require min_frequency: ${s} <= max_frequency: ${r}`);
    let l = iu(s, i), c = iu(r, i), p = db(l, c, e + 2), u = OA(p, i), _;
    if (a) {
      let m = n / ((t6 - 1) * 2);
      _ = iu(Float64Array.from({ length: t6 }, (f, g) => g * m), i), u = p;
    } else _ = db(0, Math.floor(n / 2), t6);
    let d = IA(_, u);
    if (o !== null && o === "slaney") for (let m = 0; m < e; ++m) {
      let f = d[m], g = 2 / (u[m + 2] - u[m]);
      for (let w = 0; w < t6; ++w) f[w] *= g;
    }
    return d;
  }
  function zA(t6, e, s) {
    let r = new t6.constructor(t6.length + e + s), n = t6.length - 1;
    for (let o = 0; o < t6.length; ++o) r[e + o] = t6[o];
    for (let o = 1; o <= e; ++o) r[e - o] = t6[zs(o, n)];
    for (let o = 1; o <= s; ++o) r[n + e + o] = t6[zs(n - o, n)];
    return r;
  }
  function hb(t6, e, s, r, n) {
    if (s <= 0) throw new Error("reference must be greater than zero");
    if (r <= 0) throw new Error("min_value must be greater than zero");
    s = Math.max(r, s);
    let o = Math.log10(s);
    for (let i = 0; i < t6.length; ++i) t6[i] = e * Math.log10(Math.max(r, t6[i]) - o);
    if (n !== null) {
      if (n <= 0) throw new Error("db_range must be greater than zero");
      let i = de(t6)[0] - n;
      for (let a = 0; a < t6.length; ++a) t6[a] = Math.max(t6[a], i);
    }
    return t6;
  }
  function TA(t6, e = 1, s = 1e-5, r = null) {
    return hb(t6, 20, e, s, r);
  }
  function CA(t6, e = 1, s = 1e-10, r = null) {
    return hb(t6, 10, e, s, r);
  }
  async function ze2(t6, e, s, r, { fft_length: n = null, power: o = 1, center: i = true, pad_mode: a = "reflect", onesided: l = true, preemphasis: c = null, preemphasis_htk_flavor: p = true, mel_filters: u = null, mel_floor: _ = 1e-10, log_mel: d = null, max_log_mel: m = null, reference: f = 1, min_value: g = 1e-10, db_range: w = null, remove_dc_offset: x = null, min_num_frames: y = null, max_num_frames: b = null, do_pad: v = true, transpose: k2 = false, mel_offset: S = 0, mel_floor_mode: I = "clamp" } = {}) {
    let $2 = e.length;
    if (n === null && (n = s), s > n) throw Error(`frame_length (${s}) may not be larger than fft_length (${n})`);
    if ($2 !== s) throw new Error(`Length of the window (${$2}) must equal frame_length (${s})`);
    if (r <= 0) throw new Error("hop_length must be greater than zero");
    if (o === null && u !== null) throw new Error("You have provided `mel_filters` but `power` is `None`. Mel spectrogram computation is not yet supported for complex-valued spectrogram. Specify `power` to fix this issue.");
    if (!p) throw new Error("`preemphasis_htk_flavor=false` is not currently supported.");
    if (i) {
      let G = Math.floor(s / 2);
      switch (a) {
        case "reflect": {
          t6 = zA(t6, G, G);
          break;
        }
        case "constant": {
          let ee = new t6.constructor(t6.length + 2 * G);
          ee.set(t6, G), t6 = ee;
          break;
        }
        case "semicausal": {
          let ee = new t6.constructor(t6.length + G);
          ee.set(t6, G), t6 = ee;
          break;
        }
        default:
          throw new Error(`pad_mode="${a}" not implemented yet.`);
      }
    }
    let C = Math.floor(1 + Math.floor((t6.length - s) / r));
    y !== null && C < y && (C = y);
    let R = l ? Math.floor(n / 2) + 1 : n, V = C, H = C;
    b !== null && (b > C ? v && (H = b) : H = V = b);
    let j = new ha(n), B = new Float64Array(n), Z = new Float64Array(j.outputBufferSize), D = new Float32Array(R * H);
    for (let G = 0; G < V; ++G) {
      let ee = G * r, $e2 = Math.min(t6.length - ee, s);
      $e2 !== s && B.fill(0, 0, s);
      for (let re = 0; re < $e2; ++re) B[re] = t6[ee + re];
      if (x) {
        let re = 0;
        for (let He2 = 0; He2 < $e2; ++He2) re += B[He2];
        let ut2 = re / $e2;
        for (let He2 = 0; He2 < $e2; ++He2) B[He2] -= ut2;
      }
      if (c !== null) {
        for (let re = $e2 - 1; re >= 1; --re) B[re] -= c * B[re - 1];
        B[0] *= 1 - c;
      }
      for (let re = 0; re < e.length; ++re) B[re] *= e[re];
      j.realTransform(Z, B);
      for (let re = 0; re < R; ++re) {
        let ut2 = re << 1;
        D[re * H + G] = Z[ut2] ** 2 + Z[ut2 + 1] ** 2;
      }
    }
    if (o !== null && o !== 2) {
      let G = o / 2;
      for (let ee = 0; ee < D.length; ++ee) D[ee] **= G;
    }
    let A = u.length, O = await rb(new E("float32", u.flat(), [A, R]), new E("float32", D, [R, H]));
    k2 && (O = O.transpose(1, 0));
    let T = O.data;
    if (I === "add") for (let G = 0; G < T.length; ++G) T[G] = S + T[G] + _;
    else for (let G = 0; G < T.length; ++G) T[G] = S + Math.max(_, T[G]);
    if (o !== null && d !== null) {
      let G = Math.min(T.length, V * A);
      switch (d) {
        case "log":
          for (let ee = 0; ee < G; ++ee) T[ee] = Math.log(T[ee]);
          break;
        case "log10":
          for (let ee = 0; ee < G; ++ee) T[ee] = Math.log10(T[ee]);
          break;
        case "log10_max_norm": {
          for (let re = 0; re < G; ++re) T[re] = Math.log10(T[re]);
          let $e2 = (m ?? de(T)[0]) - 8;
          for (let re = 0; re < G; ++re) T[re] = (Math.max(T[re], $e2) + 4) / 4;
          break;
        }
        case "dB":
          if (o === 1) TA(T, f, g, w);
          else if (o === 2) CA(T, f, g, w);
          else throw new Error(`Cannot use log_mel option '${d}' with power ${o}`);
          break;
        default:
          throw new Error(`log_mel must be one of null, 'log', 'log10', 'log10_max_norm', or 'dB'. Got '${d}'`);
      }
    }
    return O;
  }
  function Le2(t6, e, { periodic: s = true, frame_length: r = null, center: n = true } = {}) {
    let o = s ? t6 + 1 : t6, i;
    switch (e) {
      case "boxcar":
        i = new Float64Array(o).fill(1);
        break;
      case "hann":
      case "hann_window":
        i = _b(o);
        break;
      case "hamming":
        i = AA(o);
        break;
      case "povey":
        i = _b(o).map((c) => Math.pow(c, 0.85));
        break;
      default:
        throw new Error(`Unknown window type ${e}.`);
    }
    if (s && (i = i.subarray(0, t6)), r === null || t6 === r) return i;
    if (t6 > r) throw new Error(`Length of the window (${t6}) may not be larger than frame_length (${r})`);
    let a = new Float64Array(r), l = n ? Math.floor((r - t6) / 2) : 0;
    return a.set(i, l), a;
  }
  function PA(t6, e) {
    let s = t6.reduce((o, i) => o + i.length, 0), r = new ArrayBuffer(44), n = new DataView(r);
    return Ia2(n, 0, "RIFF"), n.setUint32(4, 36 + s * 4, true), Ia2(n, 8, "WAVE"), Ia2(n, 12, "fmt "), n.setUint32(16, 16, true), n.setUint16(20, 3, true), n.setUint16(22, 1, true), n.setUint32(24, e, true), n.setUint32(28, e * 4, true), n.setUint16(32, 4, true), n.setUint16(34, 32, true), Ia2(n, 36, "data"), n.setUint32(40, s * 4, true), new Blob([r, ...t6.map((o) => o.buffer)], { type: "audio/wav" });
  }
  function Ia2(t6, e, s) {
    for (let r = 0; r < s.length; ++r) t6.setUint8(e + r, s.charCodeAt(r));
  }
  var Wr = class {
    constructor(e, s) {
      this.audio = e, this.sampling_rate = s;
    }
    get data() {
      if (Array.isArray(this.audio)) {
        if (this.audio.length === 0) return new Float32Array(0);
        if (this.audio.length === 1) return this.audio[0];
        let e = this.audio.reduce((n, o) => n + o.length, 0), s = new Float32Array(e), r = 0;
        for (let n of this.audio) s.set(n, r), r += n.length;
        return s;
      } else return this.audio;
    }
    toBlob() {
      let e = this.audio;
      return e instanceof Float32Array && (e = [e]), PA(e, this.sampling_rate);
    }
    async save(e) {
      return Oa2(e, this.toBlob());
    }
  };
  var lu = class extends le2 {
    constructor(e) {
      super(e);
      let s = this.config.sampling_rate, r = Pe(257, this.config.num_mel_bins, 20, Math.floor(s / 2), s, null, "kaldi", true);
      this.mel_filters = r, this.window = Le2(400, "hann", { periodic: false }), this.mean = this.config.mean, this.std = this.config.std;
    }
    async _extract_fbank_features(e, s) {
      return ze2(e, this.window, 400, 160, { fft_length: 512, power: 2, center: false, preemphasis: 0.97, mel_filters: this.mel_filters, log_mel: "log", mel_floor: 1192092955078125e-22, remove_dc_offset: true, max_num_frames: s, transpose: true });
    }
    async _call(e) {
      ce(e, "ASTFeatureExtractor");
      let s = await this._extract_fbank_features(e, this.config.max_length);
      if (this.config.do_normalize) {
        let r = this.std * 2, n = s.data;
        for (let o = 0; o < n.length; ++o) n[o] = (n[o] - this.mean) / r;
      }
      return { input_values: s.unsqueeze_(0) };
    }
  };
  var Vr = class extends le2 {
    async _call(e) {
      ce(e, "EncodecFeatureExtractor"), e instanceof Float64Array && (e = new Float32Array(e));
      let s = this.config.feature_size;
      if (e.length % s !== 0) throw new Error(`The length of the audio data must be a multiple of the number of channels (${s}).`);
      let r = [1, s, e.length / s];
      return { input_values: new E("float32", e, r) };
    }
  };
  var cu = class extends le2 {
    async _call(e) {
      ce(e, "ChatterboxFeatureExtractor"), e instanceof Float64Array && (e = new Float32Array(e));
      let s = [1, e.length];
      return { input_values: new E("float32", e, s) };
    }
  };
  var pu = class extends le2 {
    constructor(e) {
      super(e), this.mel_filters = Pe(this.config.nb_frequency_bins, this.config.feature_size, this.config.frequency_min, this.config.frequency_max, this.config.sampling_rate, null, "htk"), this.mel_filters_slaney = Pe(this.config.nb_frequency_bins, this.config.feature_size, this.config.frequency_min, this.config.frequency_max, this.config.sampling_rate, "slaney", "slaney"), this.window = Le2(this.config.fft_window_size, "hann");
    }
    async _get_input_mel(e, s, r, n) {
      let o, i = false, a = e.length - s;
      if (a > 0) if (r === "rand_trunc") {
        i = true;
        let l = Math.floor(ns2.random() * (a + 1));
        e = e.subarray(l, l + s), o = await this._extract_fbank_features(e, this.mel_filters_slaney, this.config.nb_max_samples);
      } else throw new Error(`Truncation strategy "${r}" not implemented`);
      else {
        if (a < 0) {
          let l = new Float64Array(s);
          if (l.set(e), n === "repeat") for (let c = e.length; c < s; c += e.length) l.set(e.subarray(0, Math.min(e.length, s - c)), c);
          else if (n === "repeatpad") for (let c = e.length; c < -a; c += e.length) l.set(e, c);
          e = l;
        }
        if (r === "fusion") throw new Error(`Truncation strategy "${r}" not implemented`);
        o = await this._extract_fbank_features(e, this.mel_filters_slaney, this.config.nb_max_samples);
      }
      return o.unsqueeze_(0);
    }
    async _extract_fbank_features(e, s, r = null) {
      return ze2(e, this.window, this.config.fft_window_size, this.config.hop_length, { power: 2, mel_filters: s, log_mel: "dB", max_num_frames: r, do_pad: false, transpose: true });
    }
    async _call(e, { max_length: s = null } = {}) {
      return ce(e, "ClapFeatureExtractor"), { input_features: (await this._get_input_mel(e, s ?? this.config.nb_max_samples, this.config.truncation, this.config.padding)).unsqueeze_(0) };
    }
  };
  var NA = 1e-5;
  var Hr2 = class extends le2 {
    constructor(e) {
      super(e), this.config.mel_filters ??= Pe(Math.floor(1 + this.config.n_fft / 2), this.config.feature_size, 0, this.config.sampling_rate / 2, this.config.sampling_rate, "slaney", "slaney");
      let s = Le2(this.config.win_length, "hann", { periodic: false });
      this.window = new Float64Array(this.config.n_fft);
      let r = Math.floor((this.config.n_fft - this.config.win_length) / 2);
      this.window.set(s, r);
    }
    async _extract_fbank_features(e) {
      let s = this.config.preemphasis;
      e = new Float64Array(e);
      for (let n = e.length - 1; n >= 1; --n) e[n] -= s * e[n - 1];
      return await ze2(e, this.window, this.window.length, this.config.hop_length, { fft_length: this.config.n_fft, power: 2, mel_filters: this.config.mel_filters, log_mel: "log", mel_floor: -1 / 0, pad_mode: "constant", center: true, transpose: true, mel_offset: 2 ** -24 });
    }
    async _call(e) {
      ce(e, "ParakeetFeatureExtractor");
      let s = await this._extract_fbank_features(e), r = Math.floor((e.length + Math.floor(this.config.n_fft / 2) * 2 - this.config.n_fft) / this.config.hop_length), n = s.data;
      n.fill(0, r * s.dims[1]);
      let [o, i] = s.dims, a = new Float64Array(i), l = new Float64Array(i);
      for (let u = 0; u < r; ++u) {
        let _ = u * i;
        for (let d = 0; d < i; ++d) {
          let m = n[_ + d];
          a[d] += m, l[d] += m * m;
        }
      }
      let c = r > 1 ? r - 1 : 1;
      for (let u = 0; u < i; ++u) {
        let _ = a[u] / r, d = (l[u] - r * _ * _) / c, f = 1 / (Math.sqrt(d) + NA);
        for (let g = 0; g < r; ++g) {
          let w = g * i + u;
          n[w] = (n[w] - _) * f;
        }
      }
      let p = new BigInt64Array(o);
      return p.fill(1n, 0, r), { input_features: s.unsqueeze_(0), attention_mask: new E("int64", p, [1, o]) };
    }
  };
  var uu = class extends Hr2 {
    _apply_dither(e) {
      let s = this.config.dither ?? 0;
      if (s <= 0) return e;
      let r = new Ot2(e.length);
      for (let n = 0; n < e.length; ++n) e[n] += s * r.gauss();
      return e;
    }
    split_audio(e) {
      let s = this.config.max_audio_clip_s ?? 35, r = this.config.overlap_chunk_second ?? 5, n = this.config.min_energy_window_samples ?? 1600, o = this.config.sampling_rate, i = Math.max(1, Math.round(s * o)), a = Math.max(1, Math.round(r * o));
      if (e.length <= i) return [e];
      let l = [], c = 0, p = e.length;
      for (; c < p; ) {
        if (c + i >= p) {
          l.push(e.slice(c, p));
          break;
        }
        let u = Math.max(c, c + i - a), _ = Math.min(c + i, p), d;
        _ <= u ? d = c + i : d = this._find_split_point_energy(e, u, _, n), d = Math.max(c + 1, Math.min(d, p)), l.push(e.slice(c, d)), c = d;
      }
      return l;
    }
    _find_split_point_energy(e, s, r, n) {
      let o = r - s;
      if (o <= n) return Math.floor((s + r) / 2);
      let i = 1 / 0, a = s, l = o - n;
      for (let c = 0; c <= l; c += n) {
        let p = 0;
        for (let u = 0; u < n; ++u) {
          let _ = e[s + c + u];
          p += _ * _;
        }
        p = Math.sqrt(p / n), p < i && (i = p, a = s + c);
      }
      return a;
    }
    async _call(e) {
      ce(e, "CohereAsrFeatureExtractor");
      let s = new Float64Array(e);
      return this._apply_dither(s), super._call(s);
    }
  };
  var Kr2 = class extends Vr {
  };
  var Xr2 = class extends le2 {
    constructor(e) {
      super(e);
      let { fft_length: s, feature_size: r, min_frequency: n, max_frequency: o, sampling_rate: i, frame_length: a } = this.config, l = Pe(Math.floor(1 + s / 2), r, n, o, i, null, "htk", false);
      this.mel_filters = l, this.window = Le2(a, "hann");
    }
    async _extract_fbank_features(e, s) {
      return ze2(e, this.window, this.config.frame_length, this.config.hop_length, { fft_length: this.config.fft_length, center: false, onesided: true, preemphasis: this.config.preemphasis, preemphasis_htk_flavor: this.config.preemphasis_htk_flavor, mel_filters: this.mel_filters, log_mel: "log", mel_floor: this.config.mel_floor, remove_dc_offset: false, transpose: true });
    }
    async _call(e, { max_length: s = 48e4, truncation: r = true, padding: n = true, pad_to_multiple_of: o = 128 } = {}) {
      if (ce(e, "Gemma3nAudioFeatureExtractor"), r && e.length > s && (e = e.slice(0, s)), n && e.length % o !== 0) {
        let l = o - e.length % o, c = new Float64Array(e.length + l);
        c.set(e), this.config.padding_value !== 0 && c.fill(this.config.padding_value, e.length), e = c;
      }
      let i = await this._extract_fbank_features(e, this.config.max_length), a = ve([1, i.dims[0]], true);
      return { input_features: i.unsqueeze_(0), input_features_mask: a };
    }
  };
  var Qr2 = class extends Xr2 {
    async _extract_fbank_features(e, s) {
      let { frame_length: r, hop_length: n, fft_length: o } = this.config, i = Math.floor(r / 2), a = Math.floor((e.length + i - (r + 1)) / n) + 1;
      return ze2(e, this.window, r, n, { fft_length: o, center: true, pad_mode: "semicausal", onesided: true, preemphasis: this.config.preemphasis, preemphasis_htk_flavor: this.config.preemphasis_htk_flavor, mel_filters: this.mel_filters, log_mel: "log", mel_floor: this.config.mel_floor, mel_floor_mode: "add", remove_dc_offset: false, transpose: true, max_num_frames: a });
    }
    async _call(e, s = {}) {
      ce(e, "Gemma4AudioFeatureExtractor");
      let r = e.length, n = await super._call(e, s), { input_features: o } = n, [, i, a] = o.dims, { frame_length: l, hop_length: c } = this.config, p = Math.floor(l / 2), u = l + 1, _ = new Uint8Array(r + p + (s.pad_to_multiple_of ?? 128));
      _.fill(1, p, p + r);
      let d = new Uint8Array(i);
      for (let f = 0; f < i; ++f) d[f] = _[f * c + u - 1] ? 1 : 0;
      let m = o.data;
      for (let f = 0; f < i; ++f) d[f] || m.fill(0, f * a, (f + 1) * a);
      return n.input_features_mask = new E("bool", d, [1, i]), n;
    }
  };
  var _u = class extends le2 {
    constructor(e) {
      super(e);
      let { n_fft: s, win_length: r, n_mels: n, sample_rate: o } = e.melspec_kwargs;
      this.mel_filters = Pe(Math.floor(1 + s / 2), n, 0, o / 2, o, null, "htk");
      let i = Le2(r, "hann");
      this.window = new Float64Array(s);
      let a = Math.floor((s - r) / 2);
      this.window.set(i, a);
    }
    async _call(e) {
      ce(e, "GraniteSpeechFeatureExtractor");
      let { n_fft: s, hop_length: r, n_mels: n } = this.config.melspec_kwargs, o = 1 + Math.floor((e.length - 1) / r), i = o - o % 2;
      return { input_features: (await ze2(e, this.window, s, r, { power: 2, mel_filters: this.mel_filters, log_mel: "log10_max_norm", transpose: true, max_num_frames: i, do_pad: false })).view(-1, 2 * n).unsqueeze_(0) };
    }
  };
  var du = class extends le2 {
    async _call(e) {
      ce(e, "MoonshineFeatureExtractor"), e instanceof Float64Array && (e = new Float32Array(e));
      let s = [1, e.length];
      return { input_values: new E("float32", e, s) };
    }
  };
  var Yr2 = class extends le2 {
    async _call(e) {
      ce(e, "PyAnnoteFeatureExtractor"), e instanceof Float64Array && (e = new Float32Array(e));
      let s = [1, 1, e.length];
      return { input_values: new E("float32", e, s) };
    }
    samples_to_frames(e) {
      return (e - this.config.offset) / this.config.step;
    }
    post_process_speaker_diarization(e, s) {
      let r = s / this.samples_to_frames(s) / this.config.sampling_rate, n = [];
      for (let o of e.tolist()) {
        let i = [], a = -1;
        for (let l = 0; l < o.length; ++l) {
          let c = me(o[l]), [p, u] = de(c), [_, d] = [l, l + 1];
          u !== a ? (a = u, i.push({ id: u, start: _, end: d, score: p })) : (i.at(-1).end = d, i.at(-1).score += p);
        }
        n.push(i.map(({ id: l, start: c, end: p, score: u }) => ({ id: l, start: c * r, end: p * r, confidence: u / (p - c) })));
      }
      return n;
    }
  };
  var fu = class extends le2 {
    constructor(e) {
      super(e);
      let s = this.config.sampling_rate, r = Pe(257, this.config.num_mel_bins, 20, Math.floor(s / 2), s, null, "kaldi", true);
      this.mel_filters = r, this.window = Le2(400, "povey", { periodic: false });
    }
    async _extract_fbank_features(e, s) {
      return e = e.map((r) => r * 32768), ze2(e, this.window, 400, 160, { fft_length: 512, power: 2, center: false, preemphasis: 0.97, mel_filters: this.mel_filters, log_mel: "log", mel_floor: 1192092955078125e-22, remove_dc_offset: true, max_num_frames: s, transpose: true });
    }
    async _call(e, { padding: s = true, pad_to_multiple_of: r = 2, do_normalize_per_mel_bins: n = true, return_attention_mask: o = true } = {}) {
      ce(e, "SeamlessM4TFeatureExtractor");
      let i = await this._extract_fbank_features(e, this.config.max_length);
      if (n) {
        let [m, f] = i.dims, g = i.data;
        for (let w = 0; w < f; ++w) {
          let x = 0;
          for (let k2 = 0; k2 < m; ++k2) x += g[k2 * f + w];
          let y = x / m, b = 0;
          for (let k2 = 0; k2 < m; ++k2) b += (g[k2 * f + w] - y) ** 2;
          b /= m - 1;
          let v = Math.sqrt(b + 1e-7);
          for (let k2 = 0; k2 < m; ++k2) {
            let S = k2 * f + w;
            g[S] = (g[S] - y) / v;
          }
        }
      }
      let a;
      if (s) {
        let [m, f] = i.dims, g = i.data, w = m % r;
        if (w > 0) {
          let x = new Float32Array(f * (m + w));
          x.set(g), x.fill(this.config.padding_value, g.length);
          let y = m + w;
          i = new E(i.type, x, [y, f]), o && (a = new E("int64", new BigInt64Array(y), [1, y]), a.data.fill(1n, 0, m));
        }
      }
      let [l, c] = i.dims, p = this.config.stride;
      if (l % p !== 0) throw new Error(`The number of frames (${l}) must be a multiple of the stride (${p}).`);
      let _ = i.view(1, Math.floor(l / p), c * p), d = { input_features: _ };
      if (o) {
        let m = _.dims[1], f = new BigInt64Array(m);
        if (a) {
          let g = a.data;
          for (let w = 1, x = 0; w < l; w += p, ++x) f[x] = g[w];
        } else f.fill(1n);
        d.attention_mask = new E("int64", f, [1, m]);
      }
      return d;
    }
  };
  var mu = class extends Kr2 {
  };
  var hu = class extends le2 {
  };
  var gu = class extends le2 {
    _zero_mean_unit_var_norm(e) {
      let r = e.reduce((o, i) => o + i, 0) / e.length, n = e.reduce((o, i) => o + (i - r) ** 2, 0) / e.length;
      return e.map((o) => (o - r) / Math.sqrt(n + 1e-7));
    }
    async _call(e) {
      ce(e, "Wav2Vec2FeatureExtractor"), e instanceof Float64Array && (e = new Float32Array(e));
      let s = e;
      this.config.do_normalize && (s = this._zero_mean_unit_var_norm(s));
      let r = [1, s.length];
      return { input_values: new E("float32", s, r), attention_mask: new E("int64", new BigInt64Array(s.length).fill(1n), r) };
    }
  };
  var xu = class extends le2 {
    constructor(e) {
      super(e);
      let s = this.config.sampling_rate, r = Pe(257, this.config.num_mel_bins, 20, Math.floor(s / 2), s, null, "kaldi", true);
      this.mel_filters = r, this.window = Le2(400, "hamming", { periodic: false }), this.min_num_frames = this.config.min_num_frames;
    }
    async _extract_fbank_features(e) {
      return e = e.map((s) => s * 32768), ze2(e, this.window, 400, 160, { fft_length: 512, power: 2, center: false, preemphasis: 0.97, mel_filters: this.mel_filters, log_mel: "log", mel_floor: 1192092955078125e-22, remove_dc_offset: true, transpose: true, min_num_frames: this.min_num_frames });
    }
    async _call(e) {
      ce(e, "WeSpeakerFeatureExtractor");
      let s = (await this._extract_fbank_features(e)).unsqueeze_(0);
      if (this.config.fbank_centering_span === null) {
        let r = s.mean(1).data, n = s.data, [o, i, a] = s.dims;
        for (let l = 0; l < o; ++l) {
          let c = l * i * a, p = l * a;
          for (let u = 0; u < i; ++u) {
            let _ = c + u * a;
            for (let d = 0; d < a; ++d) n[_ + d] -= r[p + d];
          }
        }
      }
      return { input_features: s };
    }
  };
  var wu = class extends le2 {
    constructor(e) {
      super(e), this.config.mel_filters ??= Pe(Math.floor(1 + this.config.n_fft / 2), this.config.feature_size, 0, 8e3, this.config.sampling_rate, "slaney", "slaney"), this.window = Le2(this.config.n_fft, "hann");
    }
    async _extract_fbank_features(e, { center: s = true } = {}) {
      let { n_fft: r, hop_length: n, mel_filters: o, global_log_mel_max: i } = this.config, a = Math.floor(s ? e.length / n : (e.length - r) / n);
      return await ze2(e, this.window, r, n, { power: 2, mel_filters: o, log_mel: "log10_max_norm", max_log_mel: i, center: s, max_num_frames: a, do_pad: false });
    }
    async _call(e, { center: s = true } = {}) {
      return ce(e, "VoxtralRealtimeFeatureExtractor"), { input_features: (await this._extract_fbank_features(e, { center: s })).unsqueeze_(0) };
    }
  };
  var yu = class extends le2 {
    constructor(e) {
      super(e), this.config.mel_filters ??= Pe(Math.floor(1 + this.config.n_fft / 2), this.config.feature_size, 0, 8e3, this.config.sampling_rate, "slaney", "slaney"), this.window = Le2(this.config.n_fft, "hann");
    }
    async _extract_fbank_features(e) {
      return await ze2(e, this.window, this.config.n_fft, this.config.hop_length, { power: 2, mel_filters: this.config.mel_filters, log_mel: "log10_max_norm", max_num_frames: Math.min(Math.floor(e.length / this.config.hop_length), this.config.nb_max_frames) });
    }
    async _call(e, { max_length: s = null } = {}) {
      ce(e, "WhisperFeatureExtractor");
      let r, n = s ?? this.config.n_samples;
      return e.length > n ? (e.length > this.config.n_samples && F.warn("Attempting to extract features for audio longer than 30 seconds. If using a pipeline to extract transcript from a long audio clip, remember to specify `chunk_length_s` and/or `stride_length_s`."), r = e.slice(0, n)) : (r = new Float32Array(n), r.set(e)), { input_features: (await this._extract_fbank_features(r)).unsqueeze_(0) };
    }
  };
  var ge2 = class {
    static async from_pretrained(e, s = {}) {
      let r = await Ie(e, Gr, true, s), n = r.feature_extractor_type, o = Jr2[n];
      if (!o) throw new Error(`Unknown feature_extractor_type: '${n}'. Please report this at ${$t2}.`);
      return new o(r);
    }
  };
  var bu = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    async _call(e, s = null) {
      let r = this.tokenizer(e), n = s ? await this.feature_extractor(s) : {};
      return { ...r, ...n };
    }
  };
  var LA = /* @__PURE__ */ new Set(["ja", "zh"]);
  var ku = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    static uses_processor_config = true;
    get_decoder_prompt_ids(e = "en") {
      let s = ["\u2581", "<|startofcontext|>", "<|startoftranscript|>", "<|emo:undefined|>", `<|${e}|>`, `<|${e}|>`, "<|pnc|>", "<|noitn|>", "<|notimestamp|>", "<|nodiarize|>"];
      return this.tokenizer.convert_tokens_to_ids(s);
    }
    static join_chunks(e, s = "en") {
      let r = e.filter((i) => i && i.trim());
      if (r.length === 0) return "";
      let n = LA.has(s) ? "" : " ";
      return [r[0].trimEnd(), ...r.slice(1).map((i) => i.trim())].join(n);
    }
    async _call(e) {
      return await this.feature_extractor(e);
    }
  };
  var za2 = {};
  var as2;
  var gb;
  var Ft;
  if (K2.IS_WEB_ENV) as2 = (t6, e) => {
    if (!self.OffscreenCanvas) throw new Error("OffscreenCanvas not supported by this environment.");
    return new self.OffscreenCanvas(t6, e);
  }, Ft = self.createImageBitmap, gb = self.ImageData;
  else if (za2) Ft = async (t6) => {
    let s = (await t6.metadata()).channels, { data: r, info: n } = await t6.rotate().raw().toBuffer({ resolveWithObject: true }), o = new Ee2(new Uint8ClampedArray(r), n.width, n.height, n.channels);
    return s !== void 0 && s !== n.channels && o.convert(s), o;
  };
  else throw new Error("Unable to load image processing library.");
  var $A = { 0: "nearest", 1: "lanczos", 2: "bilinear", 3: "bicubic", 4: "box", 5: "hamming" };
  var FA = /* @__PURE__ */ new Map([["png", "image/png"], ["jpg", "image/jpeg"], ["jpeg", "image/jpeg"], ["gif", "image/gif"]]);
  var Ee2 = class t3 {
    constructor(e, s, r, n) {
      this.data = e, this.width = s, this.height = r, this.channels = n;
    }
    get size() {
      return [this.width, this.height];
    }
    static async read(e) {
      if (e instanceof t3) return e;
      if (typeof e == "string" || e instanceof URL) return await this.fromURL(e);
      if (e instanceof Blob) return await this.fromBlob(e);
      if (typeof HTMLCanvasElement < "u" && e instanceof HTMLCanvasElement || typeof OffscreenCanvas < "u" && e instanceof OffscreenCanvas) return this.fromCanvas(e);
      throw new Error(`Unsupported input type: ${typeof e}`);
    }
    static fromCanvas(e) {
      if (!K2.IS_WEB_ENV) throw new Error("fromCanvas() is only supported in browser environments.");
      let r = e.getContext("2d").getImageData(0, 0, e.width, e.height).data;
      return new t3(r, e.width, e.height, 4);
    }
    static async fromURL(e) {
      let s = await zt2(e);
      if (s.status !== 200) throw new Error(`Unable to read image from "${e}" (${s.status} ${s.statusText})`);
      let r = await s.blob();
      return this.fromBlob(r);
    }
    static async fromBlob(e) {
      if (K2.IS_WEB_ENV) {
        let s = await Ft(e), r = as2(s.width, s.height).getContext("2d");
        return r.drawImage(s, 0, 0), new this(r.getImageData(0, 0, s.width, s.height).data, s.width, s.height, 4);
      } else {
        let s = za2(await e.arrayBuffer());
        return await Ft(s);
      }
    }
    static fromTensor(e, s = "CHW") {
      if (e.dims.length !== 3) throw new Error(`Tensor should have 3 dimensions, but has ${e.dims.length} dimensions.`);
      if (s === "CHW") e = e.transpose(1, 2, 0);
      else if (s !== "HWC") throw new Error(`Unsupported channel format: ${s}`);
      if (!(e.data instanceof Uint8ClampedArray || e.data instanceof Uint8Array)) throw new Error(`Unsupported tensor type: ${e.type}`);
      switch (e.dims[2]) {
        case 1:
        case 2:
        case 3:
        case 4:
          return new t3(e.data, e.dims[1], e.dims[0], e.dims[2]);
        default:
          throw new Error(`Unsupported number of channels: ${e.dims[2]}`);
      }
    }
    grayscale() {
      if (this.channels === 1) return this;
      let e = new Uint8ClampedArray(this.width * this.height * 1);
      switch (this.channels) {
        case 3:
        case 4:
          for (let s = 0, r = 0; s < this.data.length; s += this.channels) {
            let n = this.data[s], o = this.data[s + 1], i = this.data[s + 2];
            e[r++] = Math.round(0.2989 * n + 0.587 * o + 0.114 * i);
          }
          break;
        default:
          throw new Error(`Conversion failed due to unsupported number of channels: ${this.channels}`);
      }
      return this._update(e, this.width, this.height, 1);
    }
    rgb() {
      if (this.channels === 3) return this;
      let e = new Uint8ClampedArray(this.width * this.height * 3);
      switch (this.channels) {
        case 1:
          for (let s = 0, r = 0; s < this.data.length; ++s) e[r++] = this.data[s], e[r++] = this.data[s], e[r++] = this.data[s];
          break;
        case 4:
          for (let s = 0, r = 0; s < this.data.length; s += 4) e[r++] = this.data[s], e[r++] = this.data[s + 1], e[r++] = this.data[s + 2];
          break;
        default:
          throw new Error(`Conversion failed due to unsupported number of channels: ${this.channels}`);
      }
      return this._update(e, this.width, this.height, 3);
    }
    rgba() {
      if (this.channels === 4) return this;
      let e = new Uint8ClampedArray(this.width * this.height * 4);
      switch (this.channels) {
        case 1:
          for (let s = 0, r = 0; s < this.data.length; ++s) e[r++] = this.data[s], e[r++] = this.data[s], e[r++] = this.data[s], e[r++] = 255;
          break;
        case 3:
          for (let s = 0, r = 0; s < this.data.length; s += 3) e[r++] = this.data[s], e[r++] = this.data[s + 1], e[r++] = this.data[s + 2], e[r++] = 255;
          break;
        default:
          throw new Error(`Conversion failed due to unsupported number of channels: ${this.channels}`);
      }
      return this._update(e, this.width, this.height, 4);
    }
    putAlpha(e) {
      if (e.width !== this.width || e.height !== this.height) throw new Error(`Expected mask size to be ${this.width}x${this.height}, but got ${e.width}x${e.height}`);
      if (e.channels !== 1) throw new Error(`Expected mask to have 1 channel, but got ${e.channels}`);
      let s = this.data, r = e.data, n = this.width * this.height;
      if (this.channels === 3) {
        let o = new Uint8ClampedArray(n * 4);
        for (let i = 0, a = 0, l = 0; i < n; ++i) o[l++] = s[a++], o[l++] = s[a++], o[l++] = s[a++], o[l++] = r[i];
        return this._update(o, this.width, this.height, 4);
      } else if (this.channels === 4) {
        for (let o = 0; o < n; ++o) s[4 * o + 3] = r[o];
        return this;
      }
      throw new Error(`Expected image to have 3 or 4 channels, but got ${this.channels}`);
    }
    async resize(e, s, { resample: r = 2 } = {}) {
      if (this.width === e && this.height === s) return this;
      let n = $A[r] ?? r, o = Vc(e), i = Vc(s);
      if (o && i) return this;
      if (o ? e = s / this.height * this.width : i && (s = e / this.width * this.height), K2.IS_WEB_ENV) {
        let a = this.channels, l = this.toCanvas(), c = as2(e, s).getContext("2d");
        return c.drawImage(l, 0, 0, e, s), new t3(c.getImageData(0, 0, e, s).data, e, s, 4).convert(a);
      } else {
        let a = this.toSharp();
        switch (n) {
          case "box":
          case "hamming":
            (n === "box" || n === "hamming") && (F.warn(`Resampling method ${n} is not yet supported. Using bilinear instead.`), n = "bilinear");
          case "nearest":
          case "bilinear":
          case "bicubic":
            a = a.affine([e / this.width, 0, 0, s / this.height], { interpolator: n });
            break;
          case "lanczos":
            a = a.resize({ width: e, height: s, fit: "fill", kernel: "lanczos3" });
            break;
          default:
            throw new Error(`Resampling method ${n} is not supported.`);
        }
        return await Ft(a);
      }
    }
    async pad([e, s, r, n]) {
      if (e = Math.max(e, 0), s = Math.max(s, 0), r = Math.max(r, 0), n = Math.max(n, 0), e === 0 && s === 0 && r === 0 && n === 0) return this;
      if (K2.IS_WEB_ENV) {
        let o = this.channels, i = this.toCanvas(), a = this.width + e + s, l = this.height + r + n, c = as2(a, l).getContext("2d");
        return c.drawImage(i, 0, 0, this.width, this.height, e, r, this.width, this.height), new t3(c.getImageData(0, 0, a, l).data, a, l, 4).convert(o);
      } else {
        let o = this.toSharp().extend({ left: e, right: s, top: r, bottom: n });
        return await Ft(o);
      }
    }
    async crop([e, s, r, n]) {
      if (e = Math.max(e, 0), s = Math.max(s, 0), r = Math.min(r, this.width - 1), n = Math.min(n, this.height - 1), e === 0 && s === 0 && r === this.width - 1 && n === this.height - 1) return this;
      let o = r - e + 1, i = n - s + 1;
      if (K2.IS_WEB_ENV) {
        let a = this.channels, l = this.toCanvas(), c = as2(o, i).getContext("2d");
        return c.drawImage(l, e, s, o, i, 0, 0, o, i), new t3(c.getImageData(0, 0, o, i).data, o, i, 4).convert(a);
      } else {
        let a = this.toSharp().extract({ left: e, top: s, width: o, height: i });
        return await Ft(a);
      }
    }
    async center_crop(e, s) {
      if (this.width === e && this.height === s) return this;
      let r = (this.width - e) / 2, n = (this.height - s) / 2;
      if (K2.IS_WEB_ENV) {
        let o = this.channels, i = this.toCanvas(), a = as2(e, s).getContext("2d"), l = 0, c = 0, p = 0, u = 0;
        return r >= 0 ? l = r : p = -r, n >= 0 ? c = n : u = -n, a.drawImage(i, l, c, e, s, p, u, e, s), new t3(a.getImageData(0, 0, e, s).data, e, s, 4).convert(o);
      } else {
        let o = this.toSharp();
        if (r >= 0 && n >= 0) o = o.extract({ left: Math.floor(r), top: Math.floor(n), width: e, height: s });
        else if (r <= 0 && n <= 0) {
          let i = Math.floor(-n), a = Math.floor(-r);
          o = o.extend({ top: i, left: a, right: e - this.width - a, bottom: s - this.height - i });
        } else {
          let i = [0, 0], a = 0;
          n < 0 ? (i[0] = Math.floor(-n), i[1] = s - this.height - i[0]) : a = Math.floor(n);
          let l = [0, 0], c = 0;
          r < 0 ? (l[0] = Math.floor(-r), l[1] = e - this.width - l[0]) : c = Math.floor(r), o = o.extend({ top: i[0], bottom: i[1], left: l[0], right: l[1] }).extract({ left: c, top: a, width: e, height: s });
        }
        return await Ft(o);
      }
    }
    async toBlob(e = "image/png", s = 1) {
      if (!K2.IS_WEB_ENV) throw new Error("toBlob() is only supported in browser environments.");
      return await this.toCanvas().convertToBlob({ type: e, quality: s });
    }
    toTensor(e = "CHW") {
      let s = new E("uint8", new Uint8Array(this.data), [this.height, this.width, this.channels]);
      if (e !== "HWC") if (e === "CHW") s = s.permute(2, 0, 1);
      else throw new Error(`Unsupported channel format: ${e}`);
      return s;
    }
    toCanvas() {
      if (!K2.IS_WEB_ENV) throw new Error("toCanvas() is only supported in browser environments.");
      let e = this.clone().rgba(), s = as2(e.width, e.height), r = new gb(e.data, e.width, e.height);
      return s.getContext("2d").putImageData(r, 0, 0), s;
    }
    split() {
      let { data: e, width: s, height: r, channels: n } = this, o = e.constructor, i = e.length / n, a = Array.from({ length: n }, () => new o(i));
      for (let l = 0; l < i; ++l) {
        let c = n * l;
        for (let p = 0; p < n; ++p) a[p][l] = e[c + p];
      }
      return a.map((l) => new t3(l, s, r, 1));
    }
    _update(e, s, r, n = null) {
      return this.data = e, this.width = s, this.height = r, n !== null && (this.channels = n), this;
    }
    clone() {
      return new t3(this.data.slice(), this.width, this.height, this.channels);
    }
    convert(e) {
      if (this.channels === e) return this;
      switch (e) {
        case 1:
          this.grayscale();
          break;
        case 3:
          this.rgb();
          break;
        case 4:
          this.rgba();
          break;
        default:
          throw new Error(`Conversion failed due to unsupported number of channels: ${this.channels}`);
      }
      return this;
    }
    async save(e) {
      if (K2.IS_WEB_ENV) {
        if (K2.IS_WEBWORKER_ENV) throw new Error("Unable to save an image from a Web Worker.");
        let s = e.split(".").pop().toLowerCase(), r = FA.get(s) ?? "image/png", n = await this.toBlob(r);
        return Oa2(e, n);
      } else if (K2.IS_FS_AVAILABLE) await this.toSharp().toFile(e);
      else throw new Error("Unable to save the image because filesystem is disabled in this environment.");
    }
    toSharp() {
      if (K2.IS_WEB_ENV) throw new Error("toSharp() is only supported in server-side environments.");
      return za2(this.data, { raw: { width: this.width, height: this.height, channels: this.channels } });
    }
  };
  var RA = Ee2.read.bind(Ee2);
  function xb(t6, e, s = 0, r = null) {
    let n = t6 / e, o = D0(n) * e;
    return r !== null && o > r && (o = Math.floor(n) * e), o < s && (o = Math.ceil(n) * e), o;
  }
  function wb([t6, e], s) {
    return [Math.max(Math.floor(t6 / s), 1) * s, Math.max(Math.floor(e / s), 1) * s];
  }
  function vu([t6, e, s, r]) {
    return [t6 - s / 2, e - r / 2, t6 + s / 2, e + r / 2];
  }
  function Rt(t6, e = 0.5, s = null, r = false) {
    let n = t6.logits, o = t6.pred_boxes, [i, a, l] = n.dims;
    if (s !== null && s.length !== i) throw Error("Make sure that you pass in as many target sizes as the batch dimension of the logits");
    let c = [];
    for (let p = 0; p < i; ++p) {
      let u = s !== null ? s[p] : null, _ = { boxes: [], classes: [], scores: [] }, d = n[p], m = o[p];
      for (let f = 0; f < a; ++f) {
        let g = d[f], w = [], x;
        if (r) {
          x = g.sigmoid().data;
          for (let y = 0; y < x.length; ++y) x[y] > e && w.push(y);
        } else {
          let y = de(g.data)[1];
          if (y === l - 1 || (x = me(g.data), x[y] < e)) continue;
          w.push(y);
        }
        for (let y of w) {
          let b = m[f].data;
          b = vu(b), u !== null && (b = b.map((v, k2) => v * u[(k2 + 1) % 2])), _.boxes.push(b), _.classes.push(y), _.scores.push(x[y]);
        }
      }
      c.push(_);
    }
    return c;
  }
  function Ta2(t6, e = null) {
    let s = t6.logits, r = s.dims[0];
    if (e !== null && e.length !== r) throw Error("Make sure that you pass in as many target sizes as the batch dimension of the logits");
    let n = [];
    for (let o = 0; o < r; ++o) {
      let i = e !== null ? e[o] : null, a = s[o];
      i !== null && (a = lp(a, i, "bilinear", false));
      let [l, c] = i ?? a.dims.slice(-2), p = new E("int32", new Int32Array(l * c), [l, c]), u = a[0].data, _ = p.data;
      for (let f = 1; f < a.dims[0]; ++f) {
        let g = a[f].data;
        for (let w = 0; w < g.length; ++w) g[w] > u[w] && (u[w] = g[w], _[w] = f);
      }
      let d = new Array(a.dims[0]);
      for (let f = 0; f < _.length; ++f) {
        let g = _[f];
        d[g] = g;
      }
      let m = d.filter((f) => f !== void 0);
      n.push({ segmentation: p, labels: m });
    }
    return n;
  }
  function DA(t6, e, s, r) {
    let n = [], o = [], i = [];
    for (let a = 0; a < t6.dims[0]; ++a) {
      let l = t6[a], c = e[a], p = de(l.data)[1];
      if (p === r) continue;
      let _ = me(l.data)[p];
      _ > s && (n.push(c), o.push(_), i.push(p));
    }
    return [n, o, i];
  }
  function qA(t6, e, s, r = 0.5, n = 0.8) {
    let o = [], i = 0, a = 0, l = e[s].data;
    for (let p = 0; p < t6.length; ++p) t6[p] === s && (o.push(p), ++i), l[p] >= r && ++a;
    let c = i > 0 && a > 0;
    return c && (c = i / a > n), [c, o];
  }
  function jA(t6, e, s, r, n, o = null, i = null) {
    let [a, l] = i ?? t6[0].dims, c = new E("int32", new Int32Array(a * l), [a, l]), p = [];
    if (i !== null) for (let f = 0; f < t6.length; ++f) t6[f] = lp(t6[f], i, "bilinear", false);
    let u = new Int32Array(t6[0].data.length), _ = new Float32Array(t6[0].data.length);
    for (let f = 0; f < t6.length; ++f) {
      let g = e[f], w = t6[f].data;
      for (let x = 0; x < w.length; ++x) w[x] *= g, w[x] > _[x] && (u[x] = f, _[x] = w[x]);
    }
    let d = 0, m = c.data;
    for (let f = 0; f < s.length; ++f) {
      let g = s[f], [w, x] = qA(u, t6, f, r, n);
      if (w) {
        ++d;
        for (let y of x) m[y] = d;
        p.push({ id: d, label_id: g, score: e[f] });
      }
    }
    return [c, p];
  }
  function Rs2(t6, e, s = 28, r = 3136, n = 784 * 1280, o = 1) {
    if (t6 < s || e < s) {
      let l = Math.max(s / t6, s / e);
      t6 = Math.round(t6 * l), e = Math.round(e * l);
    }
    if (Math.max(t6, e) / Math.min(t6, e) > 200) throw new Error(`absolute aspect ratio must be smaller than 200, got ${Math.max(t6, e) / Math.min(t6, e)}`);
    let i = Math.round(t6 / s) * s, a = Math.round(e / s) * s;
    if (o * i * a > n) {
      let l = Math.sqrt(o * t6 * e / n);
      i = Math.max(s, Math.floor(t6 / l / s) * s), a = Math.max(s, Math.floor(e / l / s) * s);
    } else if (o * i * a < r) {
      let l = Math.sqrt(r / (o * t6 * e));
      i = Math.ceil(t6 * l / s) * s, a = Math.ceil(e * l / s) * s;
    }
    return [a, i];
  }
  function Ca2(t6, e = 0.5, s = 0.5, r = 0.8, n = null, o = null) {
    n === null && (F.warn("`label_ids_to_fuse` unset. No instance will be fused."), n = /* @__PURE__ */ new Set());
    let i = t6.class_queries_logits ?? t6.logits, l = (t6.masks_queries_logits ?? t6.pred_masks).sigmoid(), [c, p, u] = i.dims;
    if (u -= 1, o !== null && o.length !== c) throw Error("Make sure that you pass in as many target sizes as the batch dimension of the logits");
    let _ = [];
    for (let d = 0; d < c; ++d) {
      let m = o !== null ? o[d] : null, f = i[d], g = l[d], [w, x, y] = DA(f, g, e, u);
      if (y.length === 0) {
        let [k2, S] = m ?? g.dims.slice(-2), I = new E("int32", new Int32Array(k2 * S).fill(-1), [k2, S]);
        _.push({ segmentation: I, segments_info: [] });
        continue;
      }
      let [b, v] = jA(w, x, y, s, r, n, m);
      _.push({ segmentation: b, segments_info: v });
    }
    return _;
  }
  function Pa2(t6, e = 0.5, s = null) {
    throw new Error("`post_process_instance_segmentation` is not yet implemented.");
  }
  var L = class extends xe {
    constructor(e) {
      super(), this.image_mean = e.image_mean ?? e.mean, this.image_std = e.image_std ?? e.std, this.resample = e.resample ?? 2, this.do_rescale = e.do_rescale ?? true, this.rescale_factor = e.rescale_factor ?? 1 / 255, this.do_normalize = e.do_normalize, this.do_thumbnail = e.do_thumbnail, this.size = e.size ?? e.image_size, this.do_resize = e.do_resize ?? this.size !== void 0, this.size_divisibility = e.size_divisibility ?? e.size_divisor, this.do_center_crop = e.do_center_crop, this.crop_size = e.crop_size, this.do_convert_rgb = e.do_convert_rgb ?? true, this.do_crop_margin = e.do_crop_margin, this.pad_size = e.pad_size, this.do_pad = e.do_pad, this.min_pixels = e.min_pixels, this.max_pixels = e.max_pixels, this.do_pad && !this.pad_size && !this.size_divisibility && this.size && this.size.width !== void 0 && this.size.height !== void 0 && (this.pad_size = this.size), this.do_flip_channel_order = e.do_flip_channel_order ?? false, this.config = e;
    }
    async thumbnail(e, s, r = 2) {
      let n = e.height, o = e.width, i = s.height, a = s.width, l = Math.min(n, i), c = Math.min(o, a);
      return l === n && c === o ? e : (n > o ? c = Math.floor(o * l / n) : o > n && (l = Math.floor(n * c / o)), await e.resize(c, l, { resample: r }));
    }
    async crop_margin(e, s = 200) {
      let r = e.clone().grayscale(), n = Fr(r.data)[0], i = de(r.data)[0] - n;
      if (i === 0) return e;
      let a = s / 255, l = r.width, c = r.height, p = 0, u = 0, _ = r.data;
      for (let d = 0; d < r.height; ++d) {
        let m = d * r.width;
        for (let f = 0; f < r.width; ++f) (_[m + f] - n) / i < a && (l = Math.min(l, f), c = Math.min(c, d), p = Math.max(p, f), u = Math.max(u, d));
      }
      return e = await e.crop([l, c, p, u]), e;
    }
    pad_image(e, s, r, { mode: n = "constant", center: o = false, constant_values: i = 0 } = {}) {
      let [a, l, c] = s, p, u;
      if (typeof r == "number" ? (p = r, u = r) : r === "square" ? p = u = Math.max(a, l) : (p = r.width, u = r.height), p !== l || u !== a) {
        let _ = new Float32Array(p * u * c);
        if (Array.isArray(i)) for (let f = 0; f < _.length; ++f) _[f] = i[f % c];
        else i !== 0 && _.fill(i);
        let [d, m] = o ? [Math.floor((p - l) / 2), Math.floor((u - a) / 2)] : [0, 0];
        for (let f = 0; f < a; ++f) {
          let g = (f + m) * p, w = f * l;
          for (let x = 0; x < l; ++x) {
            let y = (g + x + d) * c, b = (w + x) * c;
            for (let v = 0; v < c; ++v) _[y + v] = e[b + v];
          }
        }
        if (n === "symmetric") {
          if (o) throw new Error("`center` padding is not supported when `mode` is set to `symmetric`.");
          let f = a - 1, g = l - 1;
          for (let w = 0; w < u; ++w) {
            let x = w * p, y = zs(w, f) * l;
            for (let b = 0; b < p; ++b) {
              if (w < a && b < l) continue;
              let v = (x + b) * c, k2 = (y + zs(b, g)) * c;
              for (let S = 0; S < c; ++S) _[v + S] = e[k2 + S];
            }
          }
        }
        e = _, s = [u, p, c];
      }
      return [e, s];
    }
    rescale(e) {
      for (let s = 0; s < e.length; ++s) e[s] = this.rescale_factor * e[s];
    }
    get_resize_output_image_size(e, s) {
      let [r, n] = e.size, o, i;
      if (this.do_thumbnail) {
        let { height: a, width: l } = s;
        o = Math.min(a, l);
      } else Number.isInteger(s) ? (o = s, i = this.config.max_size ?? o) : s !== void 0 && (o = s.shortest_edge, i = s.longest_edge);
      if (o !== void 0 || i !== void 0) {
        let a = o === void 0 ? 1 : Math.max(o / r, o / n), l = r * a, c = n * a, p = i === void 0 ? 1 : Math.min(i / l, i / c), u = Math.floor(Number((l * p).toFixed(2))), _ = Math.floor(Number((c * p).toFixed(2)));
        return this.size_divisibility !== void 0 && ([u, _] = wb([u, _], this.size_divisibility)), [u, _];
      } else if (s !== void 0 && s.width !== void 0 && s.height !== void 0) {
        let a = s.width, l = s.height;
        if (this.config.keep_aspect_ratio && this.config.ensure_multiple_of) {
          let c = l / n, p = a / r;
          Math.abs(1 - p) < Math.abs(1 - c) ? c = p : p = c, l = xb(c * n, this.config.ensure_multiple_of), a = xb(p * r, this.config.ensure_multiple_of);
        }
        return [a, l];
      } else {
        if (this.size_divisibility !== void 0) return wb([r, n], this.size_divisibility);
        throw new Error(`Could not resize image due to unsupported \`this.size\` option in config: ${JSON.stringify(s)}`);
      }
    }
    async resize(e) {
      let [s, r] = this.get_resize_output_image_size(e, this.size);
      return await e.resize(s, r, { resample: this.resample });
    }
    async preprocess(e, { do_normalize: s = null, do_pad: r = null, do_convert_rgb: n = null, do_convert_grayscale: o = null, do_flip_channel_order: i = null } = {}) {
      this.do_crop_margin && (e = await this.crop_margin(e));
      let [a, l] = e.size;
      if (n ?? this.do_convert_rgb ? e = e.rgb() : o && (e = e.grayscale()), this.do_resize && (e = await this.resize(e)), this.do_thumbnail && (e = await this.thumbnail(e, this.size, this.resample)), this.do_center_crop) {
        let d, m;
        Number.isInteger(this.crop_size) ? (d = this.crop_size, m = this.crop_size) : (d = this.crop_size.width, m = this.crop_size.height), e = await e.center_crop(d, m);
      }
      let c = [e.height, e.width], p = Float32Array.from(e.data), u = [e.height, e.width, e.channels];
      if (this.do_rescale && this.rescale(p), s ?? this.do_normalize) {
        let d = this.image_mean;
        Array.isArray(this.image_mean) || (d = new Array(e.channels).fill(d));
        let m = this.image_std;
        if (Array.isArray(this.image_std) || (m = new Array(e.channels).fill(m)), d.length !== e.channels || m.length !== e.channels) throw new Error(`When set to arrays, the length of \`image_mean\` (${d.length}) and \`image_std\` (${m.length}) must match the number of channels in the image (${e.channels}).`);
        for (let f = 0; f < p.length; f += e.channels) for (let g = 0; g < e.channels; ++g) p[f + g] = (p[f + g] - d[g]) / m[g];
      }
      if (r ?? this.do_pad) {
        if (this.pad_size) [p, u] = this.pad_image(p, [e.height, e.width, e.channels], this.pad_size);
        else if (this.size_divisibility) {
          let d = Math.ceil(u[1] / this.size_divisibility) * this.size_divisibility, m = Math.ceil(u[0] / this.size_divisibility) * this.size_divisibility;
          [p, u] = this.pad_image(p, u, { width: d, height: m });
        }
      }
      if (i ?? this.do_flip_channel_order) {
        if (u[2] !== 3) throw new Error("Flipping channel order is only supported for RGB images.");
        for (let d = 0; d < p.length; d += 3) {
          let m = p[d];
          p[d] = p[d + 2], p[d + 2] = m;
        }
      }
      let _ = new E("float32", p, u).permute(2, 0, 1);
      return { original_size: [l, a], reshaped_input_size: c, pixel_values: _ };
    }
    async _call(e, ...s) {
      Array.isArray(e) || (e = [e]);
      let r = await Promise.all(e.map((o) => this.preprocess(o)));
      return { pixel_values: qe(r.map((o) => o.pixel_values), 0), original_sizes: r.map((o) => o.original_size), reshaped_input_sizes: r.map((o) => o.reshaped_input_size) };
    }
    static async from_pretrained(e, s = {}) {
      let r = await Ie(e, bt, true, s);
      return new this(r);
    }
  };
  var Us2 = {};
  Os2(Us2, { BeitFeatureExtractor: () => Eu, BitImageProcessor: () => Au, CHMv2ImageProcessor: () => Su, CLIPFeatureExtractor: () => Ou, CLIPImageProcessor: () => Na2, ChineseCLIPFeatureExtractor: () => Mu, ConvNextFeatureExtractor: () => Iu, ConvNextImageProcessor: () => La2, DINOv3ViTImageProcessor: () => Cu, DPTFeatureExtractor: () => Nu, DPTImageProcessor: () => Ra2, DeiTFeatureExtractor: () => zu, DeiTImageProcessor: () => $a2, DetrFeatureExtractor: () => Tu, DetrImageProcessor: () => Fa2, DonutFeatureExtractor: () => Pu, DonutImageProcessor: () => Ds2, EfficientNetImageProcessor: () => Lu, GLPNFeatureExtractor: () => Ru, Gemma3ImageProcessor: () => $u, Gemma4ImageProcessor: () => Zr2, Glm46VImageProcessor: () => Fu, GroundingDinoImageProcessor: () => Du, Idefics3ImageProcessor: () => Da2, ImageFeatureExtractor: () => L, ImageProcessor: () => L, JinaCLIPImageProcessor: () => ju, Lfm2VlImageProcessor: () => Bu, LlavaOnevisionImageProcessor: () => Uu, Mask2FormerImageProcessor: () => Wu, MaskFormerFeatureExtractor: () => Gu, MaskFormerImageProcessor: () => qs, MobileNetV1FeatureExtractor: () => Vu, MobileNetV1ImageProcessor: () => qa2, MobileNetV2FeatureExtractor: () => Hu, MobileNetV2ImageProcessor: () => ja2, MobileNetV3FeatureExtractor: () => Ku, MobileNetV3ImageProcessor: () => Ba2, MobileNetV4FeatureExtractor: () => Xu, MobileNetV4ImageProcessor: () => Ua2, MobileViTFeatureExtractor: () => Qu, MobileViTImageProcessor: () => Ga2, NougatImageProcessor: () => Yu, OwlViTFeatureExtractor: () => Ju, OwlViTImageProcessor: () => js, Owlv2ImageProcessor: () => Zu, Phi3VImageProcessor: () => s_, PixtralImageProcessor: () => r_, PvtImageProcessor: () => n_, Qwen2VLImageProcessor: () => en2, RTDetrImageProcessor: () => o_, Sam2ImageProcessor: () => tn2, Sam3ImageProcessor: () => tn2, SamImageProcessor: () => tn2, SapiensFeatureExtractor: () => i_, SapiensImageProcessor: () => Wa2, SegformerFeatureExtractor: () => a_, SegformerImageProcessor: () => Va2, SiglipImageProcessor: () => l_, SmolVLMImageProcessor: () => Da2, Swin2SRImageProcessor: () => c_, VLMImageProcessor: () => qu, ViTFeatureExtractor: () => p_, ViTImageProcessor: () => Ha2, VitMatteImageProcessor: () => u_, VitPoseImageProcessor: () => __, YolosFeatureExtractor: () => d_, YolosImageProcessor: () => Ka2 });
  var Eu = class extends L {
  };
  var Au = class extends L {
  };
  var Mu = class extends L {
  };
  var Su = class extends L {
  };
  var Na2 = class extends L {
  };
  var Ou = class extends Na2 {
  };
  var La2 = class extends L {
    constructor(e) {
      super(e), this.crop_pct = this.config.crop_pct ?? 224 / 256;
    }
    async resize(e) {
      let s = this.size?.shortest_edge;
      if (s === void 0) throw new Error("Size dictionary must contain 'shortest_edge' key.");
      if (s < 384) {
        let r = Math.floor(s / this.crop_pct), [n, o] = this.get_resize_output_image_size(e, { shortest_edge: r });
        e = await e.resize(n, o, { resample: this.resample }), e = await e.center_crop(s, s);
      } else e = await e.resize(s, s, { resample: this.resample });
      return e;
    }
  };
  var Iu = class extends La2 {
  };
  var $a2 = class extends L {
  };
  var zu = class extends $a2 {
  };
  var Fa2 = class extends L {
    async _call(e) {
      let s = await super._call(e), r = [s.pixel_values.dims[0], 64, 64], n = ve(r, 1n);
      return { ...s, pixel_mask: n };
    }
    post_process_object_detection(...e) {
      return Rt(...e);
    }
    post_process_panoptic_segmentation(...e) {
      return Ca2(...e);
    }
    post_process_instance_segmentation(...e) {
      return Pa2(...e);
    }
  };
  var Tu = class extends Fa2 {
  };
  var Cu = class extends L {
  };
  var Ds2 = class extends L {
    pad_image(e, s, r, n = {}) {
      let [o, i, a] = s, l = this.image_mean;
      Array.isArray(this.image_mean) || (l = new Array(a).fill(l));
      let c = this.image_std;
      Array.isArray(c) || (c = new Array(a).fill(l));
      let p = l.map((u, _) => -u / c[_]);
      return super.pad_image(e, s, r, { center: true, constant_values: p, ...n });
    }
  };
  var Pu = class extends Ds2 {
  };
  var Ra2 = class extends L {
  };
  var Nu = class extends Ra2 {
  };
  var Lu = class extends L {
    constructor(e) {
      super(e), this.include_top = this.config.include_top ?? true, this.include_top && (this.image_std = this.image_std.map((s) => s * s));
    }
  };
  var $u = class extends L {
  };
  function BA(t6, e, s, r, n) {
    let o = r * s ** 2, i = Math.sqrt(o / (t6 * e)), a = n * s, l = Math.floor(i * t6 / a) * a, c = Math.floor(i * e / a) * a;
    if (l === 0 && c === 0) throw new Error(`Attempting to resize to a 0 x 0 image. Resized height should be divisible by \`pooling_kernel_size * patch_size\`=${a}.`);
    let p = Math.floor(r / n ** 2) * a;
    return l === 0 ? (l = a, c = Math.min(Math.floor(e / t6) * a, p)) : c === 0 && (c = a, l = Math.min(Math.floor(t6 / e) * a, p)), [l, c];
  }
  function UA(t6, e, s, r, n, o, i) {
    let a = Math.floor(e / n), l = Math.floor(s / n), c = a * l, p = n * n * r, u = new Float32Array(o * p), _ = 0;
    for (let f = 0; f < a; ++f) for (let g = 0; g < l; ++g) for (let w = 0; w < n; ++w) {
      let x = (f * n + w) * s * r + g * n * r;
      for (let y = 0; y < n; ++y) {
        let b = x + y * r;
        for (let v = 0; v < r; ++v) u[_++] = t6[b + v];
      }
    }
    let d = new BigInt64Array(o * 2).fill(-1n), m = 0;
    for (let f = 0; f < a; ++f) for (let g = 0; g < l; ++g) d[m++] = BigInt(g), d[m++] = BigInt(f);
    return { patches: new E("float32", u, [o, p]), positions: new E("int64", d, [o, 2]), num_soft_tokens: Math.floor(c / i ** 2) };
  }
  var Zr2 = class extends xe {
    constructor(e) {
      super(), this.config = e, this.patch_size = e.patch_size ?? 16, this.max_soft_tokens = e.max_soft_tokens ?? 280, this.pooling_kernel_size = e.pooling_kernel_size ?? 3, this.resample = e.resample ?? 3, this.rescale_factor = e.rescale_factor ?? 1 / 255, this.do_rescale = e.do_rescale ?? true, this.do_resize = e.do_resize ?? true, this.do_convert_rgb = e.do_convert_rgb ?? true;
    }
    async _call(e) {
      Array.isArray(e) || (e = [e]);
      let { patch_size: s, pooling_kernel_size: r } = this, n = this.max_soft_tokens * r ** 2, o = [], i = [], a = [];
      for (let l of e) {
        if (this.do_convert_rgb && (l = l.rgb()), this.do_resize) {
          let [d, m] = BA(l.height, l.width, s, n, r);
          (d !== l.height || m !== l.width) && (l = await l.resize(m, d, { resample: this.resample }));
        }
        let c = Float32Array.from(l.data);
        if (this.do_rescale) for (let d = 0; d < c.length; ++d) c[d] *= this.rescale_factor;
        let { patches: p, positions: u, num_soft_tokens: _ } = UA(c, l.height, l.width, l.channels, s, n, r);
        o.push(p), i.push(u), a.push(_);
      }
      return { pixel_values: qe(o, 0), image_position_ids: qe(i, 0), num_soft_tokens_per_image: a };
    }
  };
  var en2 = class extends L {
    constructor(e) {
      super(e), this.min_pixels = e.min_pixels ?? e.size?.shortest_edge, this.max_pixels = e.max_pixels ?? e.size?.longest_edge, this.patch_size = e.patch_size, this.merge_size = e.merge_size;
    }
    get_resize_output_image_size(e, s) {
      let r = this.patch_size * this.merge_size;
      return Rs2(e.height, e.width, r, this.min_pixels, this.max_pixels);
    }
    async _call(e, ...s) {
      let { pixel_values: r, original_sizes: n, reshaped_input_sizes: o } = await super._call(e, ...s), i = r, { temporal_patch_size: a, merge_size: l, patch_size: c } = this.config;
      i.dims[0] === 1 && (i = ie2(Array.from({ length: a }, () => i), 0));
      let p = i.dims[0] / a, u = i.dims[1], _ = Math.floor(i.dims[2] / c), d = Math.floor(i.dims[3] / c), m = i.view(p, a, u, Math.floor(_ / l), l, c, Math.floor(d / l), l, c).permute(0, 3, 6, 4, 7, 2, 1, 5, 8).view(p * _ * d, u * a * c * c), f = new E("int64", [p, _, d], [1, 3]);
      return { pixel_values: m, image_grid_thw: f, original_sizes: n, reshaped_input_sizes: o };
    }
  };
  var Fu = class extends en2 {
    get_resize_output_image_size(e, s) {
      let r = this.patch_size * this.merge_size, n = this.config.temporal_patch_size ?? 2;
      return Rs2(e.height, e.width, r, this.min_pixels, this.max_pixels, n);
    }
  };
  var Ru = class extends L {
  };
  var Du = class extends L {
    async _call(e) {
      let s = await super._call(e), r = s.pixel_values.dims, n = Me([r[0], r[2], r[3]]);
      return { ...s, pixel_mask: n };
    }
  };
  var Da2 = class extends L {
    constructor(e) {
      super(e), this.do_image_splitting = e.do_image_splitting ?? true, this.max_image_size = e.max_image_size;
    }
    get_resize_for_vision_encoder(e, s) {
      let [r, n] = e.dims.slice(-2), o = n / r;
      return n >= r ? (n = Math.ceil(n / s) * s, r = Math.floor(n / o), r = Math.ceil(r / s) * s) : (r = Math.ceil(r / s) * s, n = Math.floor(r * o), n = Math.ceil(n / s) * s), { height: r, width: n };
    }
    async _call(e, { do_image_splitting: s = null, return_row_col_info: r = false } = {}) {
      let n;
      if (!Array.isArray(e)) n = [[e]];
      else {
        if (e.length === 0 || !e[0]) throw new Error("No images provided.");
        Array.isArray(e[0]) ? n = e : n = [e];
      }
      let o = [], i = [], a = [], l = [], c = [];
      for (let w of n) {
        let x = await Promise.all(w.map((v) => this.preprocess(v)));
        l.push(...x.map((v) => v.original_size)), c.push(...x.map((v) => v.reshaped_input_size)), x.forEach((v) => v.pixel_values.unsqueeze_(0));
        let { longest_edge: y } = this.max_image_size, b;
        if (s ?? this.do_image_splitting) {
          let v = new Array(x.length), k2 = new Array(x.length);
          b = await Promise.all(x.map(async (S, I) => {
            let $2 = this.get_resize_for_vision_encoder(S.pixel_values, y), C = await je2(S.pixel_values, { size: [$2.height, $2.width] }), { frames: R, num_splits_h: V, num_splits_w: H } = await this.split_image(C, this.max_image_size);
            return v[I] = V, k2[I] = H, ie2(R, 0);
          })), i.push(v), a.push(k2);
        } else {
          let v = [y, y];
          b = await Promise.all(x.map((k2) => je2(k2.pixel_values, { size: v }))), i.push(new Array(x.length).fill(0)), a.push(new Array(x.length).fill(0));
        }
        o.push(ie2(b, 0));
      }
      let p = o.length, [u, _, d, m] = o[0].dims, f, g;
      if (p === 1) f = o[0].unsqueeze_(0), g = ve([p, u, d, m], true);
      else {
        let w = Math.max(...o.map((b) => b.dims.at(0)));
        g = ve([p, w, d, m], true);
        let x = g.data, y = w * d * m;
        for (let b = 0; b < p; ++b) {
          let v = o[b].dims[0];
          if (v < w) {
            o[b] = ie2([o[b], ve([w - v, _, d, m], 0)], 0);
            let k2 = b * y + v * d * m, S = (b + 1) * y;
            x.fill(false, k2, S);
          }
        }
        f = qe(o, 0);
      }
      return { pixel_values: f, pixel_attention_mask: g, original_sizes: l, reshaped_input_sizes: c, ...r ? { rows: i, cols: a } : {} };
    }
    async split_image(e, { longest_edge: s }) {
      let r = s, n = s, o = [], [i, a] = e.dims.slice(-2), l = 0, c = 0;
      if (i > r || a > n) {
        l = Math.ceil(i / r), c = Math.ceil(a / n);
        let p = Math.ceil(i / l), u = Math.ceil(a / c);
        for (let m = 0; m < l; ++m) for (let f = 0; f < c; ++f) {
          let g, w, x, y;
          m === l - 1 ? (w = i - p, y = i) : (w = m * p, y = (m + 1) * p), f === c - 1 ? (g = a - u, x = a) : (g = f * u, x = (f + 1) * u);
          let k2 = await va2(e, [w, g], [y, x], [2, 3]);
          o.push(k2);
        }
        let _ = r, d = n;
        (i !== _ || a !== d) && (e = await je2(e, { size: [_, d] }));
      }
      return o.push(e), { frames: o, num_splits_h: l, num_splits_w: c };
    }
  };
  var qu = class extends L {
    constructor(e) {
      super({ do_pad: true, pad_size: { width: e.image_size, height: e.image_size }, ...e }), this.constant_values = this.config.background_color.map((s) => s * this.rescale_factor);
    }
    pad_image(e, s, r, n) {
      return super.pad_image(e, s, r, { constant_values: this.constant_values, center: true, ...n });
    }
  };
  var ju = class extends L {
    constructor(e) {
      let { resize_mode: s, fill_color: r, interpolation: n, size: o, ...i } = e, a = s === "squash" ? { width: o, height: o } : s === "shortest" ? { shortest_edge: o } : { longest_edge: o }, l = n === "bicubic" ? 3 : 2;
      super({ ...i, size: a, resample: l, do_center_crop: true, crop_size: o, do_normalize: true });
    }
  };
  function yb(t6, e) {
    return Math.round(t6 / e) * e;
  }
  function GA(t6, e, s, r, n) {
    let o = 1 / 0, i = [1, 1], a = s * r;
    for (let l of e) {
      let c = Math.abs(t6 - l[0] / l[1]);
      c < o ? (o = c, i = l) : c === o && a > 0.5 * n * n * l[0] * l[1] && (i = l);
    }
    return i;
  }
  function WA(t6, e) {
    let s = [], r = /* @__PURE__ */ new Set();
    for (let n = t6; n <= e; ++n) for (let o = 1; o <= n; ++o) for (let i = 1; i <= n; ++i) {
      let a = o * i;
      if (a >= t6 && a <= e) {
        let l = o << 16 | i;
        r.has(l) || (r.add(l), s.push([o, i]));
      }
    }
    return s.sort((n, o) => n[0] * n[1] - o[0] * o[1]);
  }
  function VA(t6, e) {
    let [s, r, n, o] = t6.dims, i = Math.floor(n / e), a = Math.floor(o / e), l = e * e * r, c = t6.data, p = new Float32Array(s * i * a * l), u = n * o;
    for (let _ = 0; _ < s; ++_) {
      let d = _ * r * u, m = _ * i * a * l;
      for (let f = 0; f < i; ++f) for (let g = 0; g < a; ++g) {
        let w = m + (f * a + g) * l;
        for (let x = 0; x < e; ++x) {
          let y = (f * e + x) * o + g * e;
          for (let b = 0; b < e; ++b) {
            let v = y + b;
            for (let k2 = 0; k2 < r; ++k2) p[w++] = c[d + k2 * u + v];
          }
        }
      }
    }
    return new E("float32", p, [s, i * a, l]);
  }
  function HA(t6, e) {
    let [, s, r] = t6.dims, n = new BigInt64Array(e);
    n.fill(1n, 0, s);
    let o = t6;
    if (s < e) {
      let i = new Float32Array(e * r);
      i.set(t6.data), o = new E("float32", i, [1, e, r]);
    }
    return { padded: o, mask: new E("int64", n, [e]) };
  }
  var Bu = class extends L {
    constructor(e) {
      super(e), this.downsample_factor = e.downsample_factor ?? 2, this.do_image_splitting = e.do_image_splitting ?? true, this.min_tiles = e.min_tiles ?? 2, this.max_tiles = e.max_tiles ?? 10, this.use_thumbnail = e.use_thumbnail ?? true, this.min_image_tokens = e.min_image_tokens ?? 64, this.max_image_tokens = e.max_image_tokens ?? 256, this.encoder_patch_size = e.encoder_patch_size ?? e.patch_size ?? 16, this.tile_size = e.tile_size ?? 512, this.max_pixels_tolerance = e.max_pixels_tolerance ?? 2, this.return_row_col_info = e.return_row_col_info ?? false;
      let s = this.max_image_tokens * this.downsample_factor ** 2, r = this.do_image_splitting ? (this.tile_size / this.encoder_patch_size) ** 2 : 0;
      this.max_num_patches = Math.max(s, r);
    }
    _is_image_too_large(e, s) {
      let r = this.encoder_patch_size * this.downsample_factor, n = Math.max(this.encoder_patch_size, yb(e, r)), o = Math.max(this.encoder_patch_size, yb(s, r));
      return n * o > this.max_image_tokens * (this.encoder_patch_size * this.downsample_factor) ** 2 * this.max_pixels_tolerance;
    }
    _get_grid_layout(e, s) {
      let r = WA(this.min_tiles, this.max_tiles), [n, o] = GA(s / e, r, s, e, this.tile_size);
      return { grid_width: n, grid_height: o, target_width: this.tile_size * n, target_height: this.tile_size * o };
    }
    async _call(e, { return_row_col_info: s = null } = {}) {
      let r;
      Array.isArray(e) ? Array.isArray(e[0]) ? r = e : r = [e] : r = [[e]];
      let n = [], o = [], i = [], a = [], l = [], c = [];
      for (let u of r) {
        let _ = await Promise.all(u.map((d) => this.preprocess(d, { do_pad: false })));
        for (let { pixel_values: d } of _) {
          let [, m, f] = d.dims, g = d.unsqueeze_(0), w = this.encoder_patch_size * this.downsample_factor, x = w ** 2, [y, b] = Rs2(Math.max(w, m), Math.max(w, f), w, this.min_image_tokens * x, this.max_image_tokens * x).map((C) => Math.max(w, C)), v, k2 = 1, S = 1, I = this._is_image_too_large(m, f), $2 = this.do_image_splitting && !(this.min_tiles === 1 && this.max_tiles === 1);
          if (I && $2) {
            let { grid_width: C, grid_height: R, target_width: V, target_height: H } = this._get_grid_layout(m, f);
            k2 = R, S = C;
            let j = await je2(g, { size: [H, V] });
            v = [];
            for (let B = 0; B < R; ++B) for (let Z = 0; Z < C; ++Z) {
              let D = B * this.tile_size, A = Z * this.tile_size;
              v.push(j.slice(null, null, [D, D + this.tile_size], [A, A + this.tile_size]));
            }
            this.use_thumbnail && C * R !== 1 && v.push(await je2(g, { size: [b, y] }));
          } else v = [await je2(g, { size: [b, y] })];
          for (let C of v) {
            let [, , R, V] = C.dims, H = VA(C, this.encoder_patch_size), { padded: j, mask: B } = HA(H, this.max_num_patches);
            n.push(j), o.push(B), i.push([Math.floor(R / this.encoder_patch_size), Math.floor(V / this.encoder_patch_size)]);
          }
          a.push(k2), l.push(S), c.push([b, y]);
        }
      }
      let p = { pixel_values: ie2(n, 0), pixel_attention_mask: qe(o, 0), spatial_shapes: new E("int64", BigInt64Array.from(i.flat(), BigInt), [i.length, 2]) };
      return (s ?? this.return_row_col_info) && (p.image_rows = a, p.image_cols = l, p.image_sizes = c), p;
    }
  };
  var Uu = class extends L {
  };
  var qs = class extends L {
    post_process_panoptic_segmentation(...e) {
      return Ca2(...e);
    }
    post_process_instance_segmentation(...e) {
      return Pa2(...e);
    }
  };
  var Gu = class extends qs {
  };
  var Wu = class extends qs {
  };
  var qa2 = class extends L {
  };
  var Vu = class extends qa2 {
  };
  var ja2 = class extends L {
  };
  var Hu = class extends ja2 {
  };
  var Ba2 = class extends L {
  };
  var Ku = class extends Ba2 {
  };
  var Ua2 = class extends L {
  };
  var Xu = class extends Ua2 {
  };
  var Ga2 = class extends L {
  };
  var Qu = class extends Ga2 {
  };
  var Yu = class extends Ds2 {
  };
  var js = class extends L {
    post_process_object_detection(...e) {
      return Rt(...e);
    }
  };
  var Ju = class extends js {
  };
  var Zu = class extends js {
  };
  var Xe = 336;
  var KA = [2, 3];
  var { ceil: e_, floor: Bs2, sqrt: t_ } = Math;
  var s_ = class extends L {
    constructor(e) {
      super({ ...e, do_normalize: true, do_pad: true, pad_size: "custom", do_convert_rgb: true, do_resize: true }), this._num_crops = e.num_crops;
    }
    calc_num_image_tokens_from_image_size(e, s) {
      let { num_img_tokens: r } = this.config;
      return Bs2((Bs2(s / Xe) * Bs2(e / Xe) + 1) * r + 1 + (Bs2(s / Xe) + 1) * t_(r));
    }
    get_resize_output_image_size(e, s) {
      let r = this._num_crops, [n, o] = e.size, i = n / o, a = 1;
      for (; a * Math.ceil(a / i) <= r; ) a += 1;
      a -= 1;
      let l = Math.floor(a * 336), c = Math.floor(l / i);
      return [l, c];
    }
    pad_image(e, s, r, n = {}) {
      let [o, i] = s, a = Xe * e_(o / Xe), l = Xe * e_(i / Xe), c = [1, 1, 1].map((p, u) => (p - this.image_mean[u]) / this.image_std[u]);
      return super.pad_image(e, s, { width: l, height: a }, { center: true, constant_values: c, ...n });
    }
    async _call(e, { num_crops: s = null } = {}) {
      if (this._num_crops = s ??= this.config.num_crops, s < 4 || t_(s) % 1 !== 0) throw new Error("num_crops must be a square number >= 4");
      Array.isArray(e) || (e = [e]);
      let r = e.length, n = await Promise.all(e.map((_) => this.preprocess(_))), o = n.map((_) => _.original_size), i = n.map((_) => _.reshaped_input_size), a = [];
      for (let { pixel_values: _ } of n) {
        _.unsqueeze_(0);
        let [d, m] = _.dims.slice(-2), f = await je2(_, { size: [Xe, Xe], mode: "bicubic" });
        if (s > 0) {
          let g = [], w = t_(s), x = Bs2(m / w), y = Bs2(d / w);
          for (let v = 0; v < w; ++v) for (let k2 = 0; k2 < w; ++k2) {
            let S, I, $2, C;
            v === w - 1 ? (I = d - y, C = d) : (I = v * y, C = (v + 1) * y), k2 === w - 1 ? (S = m - x, $2 = m) : (S = k2 * x, $2 = (k2 + 1) * x);
            let H = await va2(_, [I, S], [C, $2], KA);
            g.push(H);
          }
          let b = await je2(ie2(g, 0), { size: [Xe, Xe], mode: "bicubic" });
          a.push(ie2([f, b], 0));
        } else a.push(f);
      }
      let l = qe(a, 0), c = i.map((_) => _.map((d) => Xe * e_(d / Xe))), p = new E("int64", c.flat(), [r, 2]), u = c.map(([_, d]) => this.calc_num_image_tokens_from_image_size(d, _));
      return { pixel_values: l, original_sizes: o, reshaped_input_sizes: i, image_sizes: p, num_img_tokens: u };
    }
  };
  var r_ = class extends L {
    get_resize_output_image_size(e, s) {
      let { longest_edge: r } = s;
      if (r === void 0) throw new Error("size must contain 'longest_edge'");
      let [n, o] = e.size, i = Math.max(n, o) / r, a = n, l = o;
      i > 1 && (a = Math.floor(n / i), l = Math.floor(o / i));
      let { patch_size: c, spatial_merge_size: p } = this.config;
      if (!p) throw new Error("config must contain 'spatial_merge_size'");
      let u = c * p, _ = Math.floor((a - 1) / u) + 1, d = Math.floor((l - 1) / u) + 1;
      return [_ * u, d * u];
    }
  };
  var n_ = class extends L {
  };
  var o_ = class extends L {
    post_process_object_detection(...e) {
      return Rt(...e);
    }
  };
  var tn2 = class extends L {
    reshape_input_points(e, s, r, n = false) {
      e = structuredClone(e);
      let o = Hc(e);
      if (o.length === 3) n || (o = [1, ...o]), e = [e];
      else if (o.length !== 4) throw Error("The input_points must be a 4D tensor of shape `batch_size`, `point_batch_size`, `nb_points_per_image`, `2`.");
      for (let i = 0; i < e.length; ++i) {
        let [a, l] = s[i], [c, p] = r[i], u = [p / l, c / a];
        for (let _ = 0; _ < e[i].length; ++_) for (let d = 0; d < e[i][_].length; ++d) for (let m = 0; m < e[i][_][d].length; ++m) e[i][_][d][m] *= u[m % 2];
      }
      return new E("float32", Float32Array.from(e.flat(1 / 0)), o);
    }
    add_input_labels(e, s) {
      let r = Hc(e);
      if (r.length === 2) r = [1, ...r], e = [e];
      else if (r.length !== 3) throw Error("The input_points must be a 4D tensor of shape `batch_size`, `point_batch_size`, `nb_points_per_image`, `2`.");
      if (r.some((n, o) => n !== s.dims[o])) throw Error(`The first ${r.length} dimensions of 'input_points' and 'input_labels' must be the same.`);
      return new E("int64", e.flat(1 / 0).map(BigInt), r);
    }
    async _call(e, { input_points: s = null, input_labels: r = null, input_boxes: n = null } = {}) {
      let o = await super._call(e);
      if (s && (o.input_points = this.reshape_input_points(s, o.original_sizes, o.reshaped_input_sizes)), r) {
        if (!o.input_points) throw Error("`input_points` must be provided if `input_labels` are provided.");
        o.input_labels = this.add_input_labels(r, o.input_points);
      }
      return n && (o.input_boxes = this.reshape_input_points(n, o.original_sizes, o.reshaped_input_sizes, true)), o;
    }
    async post_process_masks(e, s, r, { mask_threshold: n = 0, binarize: o = true, pad_size: i = null } = {}) {
      let a = [];
      i = i ?? this.pad_size ?? this.size;
      let l = [i.height, i.width];
      for (let c = 0; c < s.length; ++c) {
        let p = s[c], u = r[c], _ = await je2(e[c], { mode: "bilinear", size: l });
        if (_ = _.slice(null, null, [0, u[0]], [0, u[1]]), _ = await je2(_, { mode: "bilinear", size: p }), o) {
          let d = _.data, m = new Uint8Array(d.length);
          for (let f = 0; f < d.length; ++f) d[f] > n && (m[f] = 1);
          _ = new E("bool", m, _.dims);
        }
        a.push(_);
      }
      return a;
    }
    generate_crop_boxes(e, s, { crop_n_layers: r = 0, overlap_ratio: n = 512 / 1500, points_per_crop: o = 32, crop_n_points_downscale_factor: i = 1 } = {}) {
    }
  };
  var Wa2 = class extends L {
    post_process_semantic_segmentation(...e) {
      return Ta2(...e);
    }
  };
  var i_ = class extends Wa2 {
  };
  var Va2 = class extends L {
    post_process_semantic_segmentation(...e) {
      return Ta2(...e);
    }
  };
  var a_ = class extends Va2 {
  };
  var l_ = class extends L {
  };
  var c_ = class extends L {
    pad_image(e, s, r, n = {}) {
      let [o, i, a] = s;
      return super.pad_image(e, s, { width: i + (r - i % r) % r, height: o + (r - o % r) % r }, { mode: "symmetric", center: false, constant_values: -1, ...n });
    }
  };
  var Ha2 = class extends L {
  };
  var p_ = class extends Ha2 {
  };
  var u_ = class extends L {
    async _call(e, s) {
      Array.isArray(e) || (e = [e]), Array.isArray(s) || (s = [s]);
      let r = await Promise.all(e.map((i) => this.preprocess(i))), n = await Promise.all(s.map((i) => this.preprocess(i, { do_normalize: false, do_convert_rgb: false, do_convert_grayscale: true })));
      return { pixel_values: qe(r.map((i, a) => ie2([i.pixel_values, n[a].pixel_values], 0)), 0), original_sizes: r.map((i) => i.original_size), reshaped_input_sizes: r.map((i) => i.reshaped_input_size) };
    }
  };
  var __ = class extends L {
    post_process_pose_estimation(e, s, { threshold: r = null } = {}) {
      let n = e.tolist(), [o, i, a, l] = e.dims, c = [];
      for (let p = 0; p < o; ++p) {
        let u = n[p], _ = s[p], d = [];
        for (let m = 0; m < _.length; ++m) {
          let f = _[m], g = [], w = [], x = [], y = f.at(-2) / l, b = f.at(-1) / a;
          for (let v = 0; v < u.length; ++v) {
            let [k2, S] = [0, 0], I = 0, $2 = -1 / 0, C = u[v];
            for (let V = 0; V < C.length; ++V) {
              let H = C[V];
              for (let j = 0; j < H.length; ++j) {
                let B = H[j];
                I += B, $2 = Math.max($2, B), k2 += (j + 0.5) * B, S += V * B;
              }
            }
            if (r != null && $2 < r) continue;
            let R = [y * k2 / I, b * S / I];
            g.push(R), x.push(v), w.push($2);
          }
          d.push({ bbox: f, scores: w, labels: x, keypoints: g });
        }
        c.push(d);
      }
      return c;
    }
  };
  var Ka2 = class extends L {
    post_process_object_detection(...e) {
      return Rt(...e);
    }
  };
  var d_ = class extends Ka2 {
  };
  var pe2 = class {
    static async from_pretrained(e, s = {}) {
      let r = await Ie(e, bt, true, s), n = r.image_processor_type ?? r.feature_extractor_type, o = Us2[n?.replace(/Fast$/, "")];
      return o || (n !== void 0 && F.warn(`Image processor type '${n}' not found, assuming base ImageProcessor. Please report this at ${$t2}.`), o = L), new o(r);
    }
  };
  var f_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    constructor(e, s, r) {
      super(e, s, r);
      let { tasks_answer_post_processing_type: n, task_prompts_without_inputs: o, task_prompts_with_input: i } = this.image_processor.config;
      this.tasks_answer_post_processing_type = new Map(Object.entries(n ?? {})), this.task_prompts_without_inputs = new Map(Object.entries(o ?? {})), this.task_prompts_with_input = new Map(Object.entries(i ?? {})), this.regexes = { quad_boxes: /(.+?)<loc_(\d+)><loc_(\d+)><loc_(\d+)><loc_(\d+)><loc_(\d+)><loc_(\d+)><loc_(\d+)><loc_(\d+)>/gm, bboxes: /([^<]+)?<loc_(\d+)><loc_(\d+)><loc_(\d+)><loc_(\d+)>/gm }, this.size_per_bin = 1e3;
    }
    construct_prompts(e) {
      typeof e == "string" && (e = [e]);
      let s = [];
      for (let r of e) if (this.task_prompts_without_inputs.has(r)) s.push(this.task_prompts_without_inputs.get(r));
      else {
        for (let [n, o] of this.task_prompts_with_input) if (r.includes(n)) {
          s.push(o.replaceAll("{input}", r).replaceAll(n, ""));
          break;
        }
        s.length !== e.length && s.push(r);
      }
      return s;
    }
    post_process_generation(e, s, r) {
      let n = this.tasks_answer_post_processing_type.get(s) ?? "pure_text";
      e = e.replaceAll("<s>", "").replaceAll("</s>", "");
      let o;
      switch (n) {
        case "pure_text":
          o = e;
          break;
        case "description_with_bboxes":
        case "bboxes":
        case "phrase_grounding":
        case "ocr":
          let i = n === "ocr" ? "quad_boxes" : "bboxes", a = e.matchAll(this.regexes[i]), l = [], c = [];
          for (let [p, u, ..._] of a) l.push(u ? u.trim() : l.at(-1) ?? ""), c.push(_.map((d, m) => (Number(d) + 0.5) / this.size_per_bin * r[m % 2]));
          o = { labels: l, [i]: c };
          break;
        default:
          throw new Error(`Task "${s}" (of type "${n}") not yet implemented.`);
      }
      return { [s]: o };
    }
    async _call(e, s = null, r = {}) {
      if (!e && !s) throw new Error("Either text or images must be provided");
      let n = await this.image_processor(e, r), o = s ? this.tokenizer(this.construct_prompts(s), r) : {};
      return { ...n, ...o };
    }
  };
  var m_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    static uses_processor_config = true;
    static uses_chat_template_file = true;
    constructor(e, s, r) {
      super(e, s, r), this.image_seq_length = this.config.image_seq_length;
      let { boi_token: n, image_token: o, eoi_token: i } = this.tokenizer.config;
      this.boi_token = n, this.image_token = o, this.eoi_token = i;
      let a = o.repeat(this.image_seq_length);
      this.full_image_sequence = `

${n}${a}${i}

`;
    }
    async _call(e, s = null, r = {}) {
      typeof e == "string" && (e = [e]);
      let n;
      return s && (n = await this.image_processor(s, r), e = e.map((i) => i.replaceAll(this.boi_token, this.full_image_sequence))), { ...this.tokenizer(e, r), ...n };
    }
  };
  var h_ = class extends U {
    static image_processor_class = pe2;
    static feature_extractor_class = ge2;
    static tokenizer_class = W;
    static uses_processor_config = true;
    static uses_chat_template_file = true;
    constructor(e, s, r) {
      super(e, s, r), this.audio_seq_length = this.config.audio_seq_length, this.image_seq_length = this.config.image_seq_length;
      let { audio_token_id: n, boa_token: o, audio_token: i, eoa_token: a, image_token_id: l, boi_token: c, image_token: p, eoi_token: u } = this.tokenizer.config;
      this.audio_token_id = n, this.boa_token = o, this.audio_token = i;
      let _ = i.repeat(this.audio_seq_length);
      this.full_audio_sequence = `

${o}${_}${a}

`, this.image_token_id = l, this.boi_token = c, this.image_token = p;
      let d = p.repeat(this.image_seq_length);
      this.full_image_sequence = `

${c}${d}${u}

`;
    }
    async _call(e, s = null, r = null, n = {}) {
      typeof e == "string" && (e = [e]);
      let o;
      r && (o = await this.feature_extractor(r, n), e = e.map((l) => l.replaceAll(this.audio_token, this.full_audio_sequence)));
      let i;
      return s && (i = await this.image_processor(s, n), e = e.map((l) => l.replaceAll(this.image_token, this.full_image_sequence))), { ...this.tokenizer(e, n), ...i, ...o };
    }
  };
  var g_ = class extends U {
    static uses_processor_config = true;
    static uses_chat_template_file = true;
    constructor(e, s, r) {
      super(e, s, r), this.audio_ms_per_token = this.config.audio_ms_per_token ?? 40, this.audio_seq_length = this.config.audio_seq_length ?? 750, this.image_seq_length = this.config.image_seq_length ?? 280;
      let { audio_token: n, boa_token: o, eoa_token: i, image_token: a, boi_token: l, eoi_token: c } = this.tokenizer.config;
      this.audio_token = n, this.boa_token = o, this.eoa_token = i, this.image_token = a, this.boi_token = l, this.eoi_token = c;
    }
    static async from_pretrained(e, s = {}) {
      let [r, n, o] = await Promise.all([Ie(e, Ma2, true, s), W.from_pretrained(e, s), $r(e, Sa2, false, s)]), i = { tokenizer: n };
      return r.image_processor && (i.image_processor = new Zr2(r.image_processor)), r.feature_extractor && (i.feature_extractor = new Qr2(r.feature_extractor)), new this(r, i, o);
    }
    _compute_audio_num_tokens(e, s) {
      let r = Math.round(s * 20 / 1e3), n = Math.round(s * 10 / 1e3), o = Math.floor(r / 2), i = Math.floor((e + o - r - 1) / n) + 1;
      if (i <= 0) return 0;
      for (let a = 0; a < 2; ++a) i = Math.floor((i - 1) / 2) + 1;
      return Math.min(i, this.audio_seq_length);
    }
    async _call(e, s = null, r = null, n = {}) {
      typeof e == "string" && (e = [e]);
      let o;
      if (s) {
        o = await this.image_processor(s, n);
        let a = o.num_soft_tokens_per_image, l = 0;
        e = e.map((c) => c.replaceAll(this.image_token, () => `

${this.boi_token}${this.image_token.repeat(a[l++])}${this.eoi_token}

`));
      }
      let i;
      if (r) {
        let a = Array.isArray(r) ? r : [r];
        i = await this.feature_extractor(a[0], n);
        let l = this.feature_extractor.config.sampling_rate ?? 16e3, c = 0;
        e = e.map((p) => p.replaceAll(this.audio_token, () => `

${this.boa_token}${this.audio_token.repeat(this._compute_audio_num_tokens(a[c++].length, l))}${this.eoa_token}

`));
      }
      return { ...this.tokenizer(e, n), ...o, ...i };
    }
  };
  var ls2 = class extends U {
    static image_processor_class = pe2;
    static tokenizer_class = W;
    static image_token = "<|image_pad|>";
    async _call(e, s = null, ...r) {
      Array.isArray(e) || (e = [e]);
      let n, o;
      if (s && (n = await this.image_processor(s), o = n.image_grid_thw), o) {
        let a = this.image_processor.config.merge_size ** 2, l = 0, c = this.constructor.image_token, p = o.tolist();
        e = e.map((u) => {
          for (; u.includes(c); ) {
            let _ = Number(p[l++].reduce((d, m) => d * m, 1n));
            u = u.replace(c, "<|placeholder|>".repeat(Math.floor(_ / a)));
          }
          return u.replaceAll("<|placeholder|>", c);
        });
      }
      return { ...this.tokenizer(e), ...n };
    }
  };
  var x_ = class extends ls2 {
    static image_token = "<|image|>";
  };
  var w_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    static uses_processor_config = true;
    _get_num_audio_features(e) {
      let { hop_length: s } = this.feature_extractor.config.melspec_kwargs, { projector_window_size: r, projector_downsample_rate: n } = this.feature_extractor.config, o = Math.floor(r / n), i = Math.floor(e / s) + 1, a = Math.floor(i / 2);
      return Math.ceil(a / r) * o;
    }
    async _call(e, s = null, r = {}) {
      if (Array.isArray(e)) throw new Error("Batched inputs are not supported yet.");
      let n = {};
      if (s) {
        let { input_features: i } = await this.feature_extractor(s);
        n.input_features = i;
        let a = this._get_num_audio_features(s.length), l = new Uint8Array(a).fill(1);
        n.input_features_mask = new E("bool", l, [1, a]);
        let c = this.config.audio_token ?? "<|audio|>";
        if (!e.includes(c)) throw new Error(`The input text does not contain the audio token ${c}.`);
        e = e.replaceAll(c, c.repeat(a));
      }
      return { ...this.tokenizer(e, { add_special_tokens: false, ...r }), ...n };
    }
  };
  function XA(t6, e) {
    let r = t6.dims.at(-1) - 1, n = t6.tolist();
    n.fill(false, 0, 1), n.fill(false, r);
    let o = e.tolist();
    return n.map((i, a) => i ? a : null).filter((i) => i !== null).map((i) => o[i]);
  }
  var y_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    async _call(e, s, r = {}) {
      let n = e ? await this.image_processor(e, r) : {};
      return { ...s ? this.tokenizer(s, r) : {}, ...n };
    }
    post_process_grounded_object_detection(e, s, { box_threshold: r = 0.25, text_threshold: n = 0.25, target_sizes: o = null } = {}) {
      let { logits: i, pred_boxes: a } = e, l = i.dims[0];
      if (o !== null && o.length !== l) throw Error("Make sure that you pass in as many target sizes as the batch dimension of the logits");
      let c = i.dims.at(1), p = i.sigmoid(), u = p.max(-1).tolist(), _ = a.tolist().map((m) => m.map((f) => vu(f))), d = [];
      for (let m = 0; m < l; ++m) {
        let f = o !== null ? o[m] : null;
        f !== null && (_[m] = _[m].map((b) => b.map((v, k2) => v * f[(k2 + 1) % 2])));
        let g = u[m], w = [], x = [], y = [];
        for (let b = 0; b < c; ++b) {
          let v = g[b];
          if (v <= r) continue;
          let k2 = _[m][b], S = p[m][b];
          w.push(v), y.push(k2);
          let I = XA(S.gt(n), s[m]);
          x.push(I);
        }
        d.push({ scores: w, boxes: y, labels: this.batch_decode(x) });
      }
      return d;
    }
  };
  function QA(t6, e, s, r, n, o) {
    let i = "";
    for (let a = 0; a < e; ++a) {
      for (let l = 0; l < s; ++l) i += r + `<row_${a + 1}_col_${l + 1}>` + n.repeat(t6);
      i += `
`;
    }
    return i += `
${r}${o}` + n.repeat(t6) + `${r}`, i;
  }
  function YA(t6, e, s, r) {
    return `${e}${r}` + s.repeat(t6) + `${e}`;
  }
  function JA(t6, e, s, r, n, o) {
    return t6 === 0 && e === 0 ? YA(s, r, n, o) : QA(s, t6, e, r, n, o);
  }
  var Xa2 = class extends U {
    static image_processor_class = pe2;
    static tokenizer_class = W;
    static uses_processor_config = true;
    fake_image_token = "<fake_token_around_image>";
    image_token = "<image>";
    global_img_token = "<global-img>";
    async _call(e, s = null, r = {}) {
      r.return_row_col_info ??= true;
      let n;
      s && (n = await this.image_processor(s, r)), Array.isArray(e) || (e = [e]);
      let o = n.rows ?? [new Array(e.length).fill(0)], i = n.cols ?? [new Array(e.length).fill(0)], a = this.config.image_seq_len, l = [], c = [];
      for (let u = 0; u < e.length; ++u) {
        let _ = e[u], d = o[u], m = i[u];
        l.push(Ky(_, this.image_token));
        let f = d.map((x, y) => JA(x, m[y], a, this.fake_image_token, this.image_token, this.global_img_token)), g = _.split(this.image_token);
        if (g.length === 0) throw new Error("The image token should be present in the text.");
        let w = g[0];
        for (let x = 0; x < f.length; ++x) w += f[x] + g[x + 1];
        c.push(w);
      }
      return { ...this.tokenizer(c), ...n };
    }
  };
  var b_ = class extends U {
    static image_processor_class = pe2;
    static tokenizer_class = W;
    static uses_processor_config = true;
    constructor(e, s, r) {
      super(e, s, r), this.image_tag = this.config.image_tag, this.image_start_tag = this.config.image_start_tag, this.image_end_tag = this.config.image_end_tag, this.num_image_tokens = this.config.num_image_tokens;
    }
    async _call(e, { images: s = null, chat_template: r = "default" } = {}) {
      s ? Array.isArray(s) || (s = [s]) : s = await Promise.all(e.filter((g) => g.images).flatMap((g) => g.images).map((g) => Ee2.read(g)));
      let n = this.tokenizer, o = n.apply_chat_template(e, { tokenize: false, add_generation_prompt: true, chat_template: r }), i = (g) => n.encode(g, { add_special_tokens: false }), a = o.split(this.image_tag), l = a.length - 1;
      if (s.length !== l) throw new Error(`Number of images provided (${s.length}) does not match number of "${this.image_tag}" image tags (${l})`);
      let [c, p, u] = n.convert_tokens_to_ids([this.image_tag, this.image_start_tag, this.image_end_tag]), _ = i(a[0]), d = new Array(_.length).fill(false);
      for (let g = 1; g < a.length; ++g) {
        let w = new Array(this.num_image_tokens).fill(c), x = i(a[g]);
        _ = Re(_, [p], w, [u], x);
        let y = new Array(this.num_image_tokens).fill(true);
        d = Re(d, [false], y, [false], new Array(x.length).fill(false));
      }
      let m = [1, _.length], f = { input_ids: new E("int64", _, m), attention_mask: new E("int64", new Array(_.length).fill(1), m), images_seq_mask: new E("bool", d, m), images_emb_mask: new E("bool", new Array(l * this.num_image_tokens).fill(true), [1, l, this.num_image_tokens]) };
      if (s && s.length > 0) {
        let g = await this.image_processor(s);
        return g.pixel_values.unsqueeze_(0), { ...f, ...g };
      }
      return f;
    }
  };
  var k_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    async _call(e = null, s = null, r = {}) {
      if (!e && !s) throw new Error("Either text or images must be provided");
      let n = e ? this.tokenizer(e, r) : {}, o = s ? await this.image_processor(s, r) : {};
      return { ...n, ...o };
    }
  };
  var v_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    async _call(e, s = null, r = {}) {
      let { image_rows: n, image_cols: o, image_sizes: i, ...a } = await this.image_processor(e, { ...r, return_row_col_info: true });
      if (s) {
        let l = this.config.image_token ?? "<image>", { tile_size: c = 512, downsample_factor: p = 2, encoder_patch_size: u = 16, use_thumbnail: _ = true } = this.image_processor.config, d = (y) => Math.ceil(Math.floor(y / u) / p), m = d(c) ** 2, f = this.config.image_start_token ?? "<|image_start|>", g = this.config.image_end_token ?? "<|image_end|>", w = this.config.image_thumbnail ?? "<|img_thumbnail|>";
        Array.isArray(s) || (s = [s]);
        let x = 0;
        s = s.map((y) => {
          let b = y.split(l);
          return b[0] + b.slice(1).map((v) => {
            let k2 = x++, [S, I] = i[k2], $2 = n[k2], C = o[k2], R = d(S) * d(I), V = f;
            if ($2 > 1 || C > 1) {
              let H = l.repeat(m);
              for (let j = 0; j < $2; ++j) for (let B = 0; B < C; ++B) V += `<|img_row_${j + 1}_col_${B + 1}|>` + H;
              _ && (V += w + l.repeat(R));
            } else V += l.repeat(R);
            return V + g + v;
          }).join("");
        });
      }
      return { ...a, ...s ? this.tokenizer(s, r) : {} };
    }
  };
  var E_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    static uses_processor_config = true;
    async _call(e, s = null, r = {}) {
      let n = await this.image_processor(e, r);
      if (s) {
        let [i, a] = n.pixel_values.dims.slice(-2), { image_token: l, patch_size: c, num_additional_image_tokens: p } = this.config, u = Math.floor(i / c) * Math.floor(a / c) + p;
        s = structuredClone(s), Array.isArray(s) || (s = [s]);
        for (let _ = 0; _ < s.length; ++_) s[_] = s[_].replace(l, l.repeat(u));
      }
      let o = s ? this.tokenizer(s, r) : {};
      return { ...n, ...o };
    }
  };
  var bb = { char: ["char_decode", 1], bpe: ["bpe_decode", 2], wp: ["wp_decode", 102] };
  var A_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    get char_tokenizer() {
      return this.components.char_tokenizer;
    }
    get bpe_tokenizer() {
      return this.components.bpe_tokenizer;
    }
    get wp_tokenizer() {
      return this.components.wp_tokenizer;
    }
    _decode_helper(e, s) {
      if (!bb.hasOwnProperty(s)) throw new Error(`Format ${s} is not supported.`);
      let [r, n] = bb[s], o = this[r].bind(this), [i, a] = e.dims, l = [], c = [], p = e.tolist();
      for (let _ = 0; _ < i; ++_) {
        let d = p[_], m = [], f = [];
        for (let w = 1; w < a; ++w) {
          let [x, y] = de(me(d[w]));
          if (f.push(x), y == n) break;
          m.push(y);
        }
        let g = f.length > 0 ? f.reduce((w, x) => w * x, 1) : 0;
        c.push(m), l.push(g);
      }
      return [o(c), l];
    }
    char_decode(e) {
      return this.char_tokenizer.batch_decode(e).map((s) => s.replaceAll(" ", ""));
    }
    bpe_decode(e) {
      return this.bpe_tokenizer.batch_decode(e);
    }
    wp_decode(e) {
      return this.wp_tokenizer.batch_decode(e).map((s) => s.replaceAll(" ", ""));
    }
    batch_decode([e, s, r]) {
      let [n, o] = this._decode_helper(e, "char"), [i, a] = this._decode_helper(s, "bpe"), [l, c] = this._decode_helper(r, "wp"), p = [], u = [];
      for (let _ = 0; _ < n.length; ++_) {
        let [d, m] = de([o[_], a[_], c[_]]);
        p.push([n[_], i[_], l[_]][m]), u.push(d);
      }
      return { generated_text: p, scores: u, char_preds: n, bpe_preds: i, wp_preds: l };
    }
    static async from_pretrained(...e) {
      let s = await super.from_pretrained(...e), r = await W.from_pretrained("Xenova/gpt2"), n = await W.from_pretrained("Xenova/bert-base-uncased");
      return s.components = { image_processor: s.image_processor, char_tokenizer: s.tokenizer, bpe_tokenizer: r, wp_tokenizer: n }, s;
    }
    async _call(e, s = null) {
      let r = await this.image_processor(e);
      return s && (r.labels = this.tokenizer(s).input_ids), r;
    }
  };
  var M_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    async _call(e) {
      return await this.feature_extractor(e);
    }
  };
  var S_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
  };
  var Gs2 = "<image>";
  function ZA(t6, e, s, r, n) {
    return `${r.repeat(s * n)}${e}${t6}
`;
  }
  var O_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    static uses_processor_config = false;
    async _call(e, s = null, r = {}) {
      s || (F.warn("You are using PaliGemma without a text prefix. It will perform as a picture-captioning model."), s = ""), Array.isArray(e) || (e = [e]), Array.isArray(s) || (s = [s]);
      let n = this.tokenizer.bos_token, o = this.image_processor.config.image_seq_length, i;
      s.some((c) => c.includes(Gs2)) ? i = s.map((c) => {
        let p = c.replaceAll(Gs2, Gs2.repeat(o)), u = p.lastIndexOf(Gs2), _ = u === -1 ? 0 : u + Gs2.length;
        return p.slice(0, _) + n + p.slice(_) + `
`;
      }) : (F.warn("You are passing both `text` and `images` to `PaliGemmaProcessor`. The processor expects special image tokens in the text, as many tokens as there are images per each text. It is recommended to add `<image>` tokens in the very beginning of your text. For this call, we will infer how many images each text has and add special tokens."), i = s.map((c) => ZA(c, n, o, Gs2, e.length)));
      let a = this.tokenizer(i, r);
      return { ...await this.image_processor(e, r), ...a };
    }
  };
  var kb = "<|image|>";
  var eM = /<\|image_\d+\|>/g;
  var I_ = class extends U {
    static image_processor_class = pe2;
    static tokenizer_class = W;
    async _call(e, s = null, { padding: r = true, truncation: n = true, num_crops: o = null } = {}) {
      Array.isArray(e) || (e = [e]);
      let i, a;
      if (s) {
        a = await this.image_processor(s, { num_crops: o });
        let { num_img_tokens: l } = a, c = e.map((u, _) => u.split(eM).join(kb.repeat(l[_])));
        i = this.tokenizer(c, { padding: r, truncation: n });
        let p = this.tokenizer._tokenizer.token_to_id(kb);
        i.input_ids.map_((u) => u == p ? -u : u);
      } else i = this.tokenizer(e);
      return { ...i, ...a };
    }
  };
  var z_ = class extends U {
    static tokenizer_class = W;
    static image_processor_class = pe2;
    static uses_processor_config = true;
    async _call(e, s = null, r = {}) {
      let n = await this.image_processor(e, r);
      if (s) {
        let [i, a] = n.pixel_values.dims.slice(-2), { image_token: l, image_break_token: c, image_end_token: p, patch_size: u, spatial_merge_size: _ } = this.config, d = u * _, m = Math.floor(i / d), f = Math.floor(a / d);
        s = structuredClone(s), Array.isArray(s) || (s = [s]);
        for (let g = 0; g < s.length; ++g) {
          let w = l.repeat(f), x = w + c, y = w + p, b = x.repeat(m - 1) + y;
          s[g] = s[g].replace(l, b);
        }
      }
      let o = s ? this.tokenizer(s, r) : {};
      return { ...n, ...o };
    }
  };
  var T_ = class extends U {
    static feature_extractor_class = Yr2;
    async _call(e) {
      return await this.feature_extractor(e);
    }
    post_process_speaker_diarization(...e) {
      return this.feature_extractor.post_process_speaker_diarization(...e);
    }
    get sampling_rate() {
      return this.feature_extractor.config.sampling_rate;
    }
  };
  var sn2 = class extends ls2 {
  };
  var C_ = class extends sn2 {
  };
  var rn2 = class extends U {
    static image_processor_class = pe2;
    async _call(...e) {
      return await this.image_processor(...e);
    }
    post_process_masks(...e) {
      return this.image_processor.post_process_masks(...e);
    }
    reshape_input_points(...e) {
      return this.image_processor.reshape_input_points(...e);
    }
  };
  var Qa2 = class extends rn2 {
  };
  var P_ = class extends Qa2 {
  };
  var N_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    async _call(e) {
      return await this.feature_extractor(e);
    }
  };
  var L_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    static uses_processor_config = true;
    async _call(e, s = null, r = {}) {
      if (Array.isArray(e)) throw new Error("Batched inputs are not supported yet.");
      let n = {};
      if (s) {
        let i = s.length, { input_features: a } = await this.feature_extractor(s, { ...r, max_length: i }), l = Math.round(i / this.config.encoder_ds_factor + 1e-4), c = 1 + Math.ceil(l / this.config.stack_factor);
        n.audio_token_len = [c], n.audio_values = a;
        let p = this.config.audio_placeholder;
        if (!e.includes(p)) throw new Error(`The input text does not contain the image token ${p}.`);
        e = e.replaceAll(p, p.repeat(c));
      }
      return { ...this.tokenizer(e, { add_special_tokens: false, ...r }), ...n };
    }
  };
  var Ya2 = "[AUDIO]";
  var tM = "[BEGIN_AUDIO]";
  var sM = 375;
  function rM(t6, e) {
    let s = [];
    for (let r = 0; r < t6.length; r += e) s.push(t6.subarray(r, Math.min(r + e, t6.length)));
    return s;
  }
  var $_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    static uses_processor_config = false;
    async _call(e, s = null, r = {}) {
      if (Array.isArray(e)) throw new Error("Batched inputs are not supported yet.");
      let n = {};
      if (s) {
        if (!e.includes(Ya2)) throw new Error(`The input text does not contain the audio token ${Ya2}.`);
        Array.isArray(s) || (s = [s]);
        let i = e.split(Ya2), a = i.length - 1;
        if (a !== s.length) throw new Error(`The number of audio inputs (${s.length}) does not match the number of audio tokens in the text (${a}).`);
        let l = this.feature_extractor.config.n_samples, c = s.map((m) => rM(m, l)), p = c.map((m) => m.length), u = c.flat(), _ = (await Promise.all(u.map((m) => this.feature_extractor(m, r)))).map((m) => m.input_features);
        n.audio_values = _.length > 1 ? ie2(_, 0) : _[0];
        let d = i[0];
        for (let m = 0; m < p.length; ++m) {
          d += tM;
          for (let f = 0; f < p[m]; ++f) d += Ya2.repeat(sM);
          d += i[m + 1];
        }
        e = d;
      }
      return { ...this.tokenizer(e, { add_special_tokens: false, ...r }), ...n };
    }
  };
  var vb = 32;
  var F_ = 6;
  var Ja2 = 8;
  var nM = 10;
  var oM = 32;
  var R_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    static uses_processor_config = false;
    get num_mel_frames_first_audio_chunk() {
      return (F_ + 1) * Ja2;
    }
    get num_samples_first_audio_chunk() {
      let { hop_length: e, n_fft: s } = this.feature_extractor.config;
      return (this.num_mel_frames_first_audio_chunk - 1) * e + Math.floor(s / 2);
    }
    get num_samples_per_audio_chunk() {
      let { hop_length: e, n_fft: s } = this.feature_extractor.config;
      return Ja2 * e + s;
    }
    get num_right_pad_tokens() {
      return F_ + 1 + nM;
    }
    get audio_length_per_tok() {
      return Ja2;
    }
    get raw_audio_length_per_tok() {
      return Ja2 * this.feature_extractor.config.hop_length;
    }
    async _call(e, { is_streaming: s = false, is_first_audio_chunk: r = true } = {}) {
      if (ce(e, "VoxtralRealtimeProcessor"), !s && !r) throw new Error("In non-streaming mode (`is_streaming=false`), `is_first_audio_chunk` must be `true`.");
      if (r) if (s) {
        let n = vb * this.raw_audio_length_per_tok, o = new Float32Array(n + e.length);
        o.set(e, n);
        let i = await this.feature_extractor(o, { center: true }), l = 1 + (vb + F_), c = new BigInt64Array(l).fill(BigInt(oM));
        return c[0] = 1n, { input_ids: new E("int64", c, [1, l]), ...i };
      } else {
        let n = this.num_right_pad_tokens * this.raw_audio_length_per_tok, o = new Float32Array(e.length + n);
        return o.set(e), await this.feature_extractor(o, { center: true });
      }
      else return await this.feature_extractor(e, { center: false });
    }
  };
  var D_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    async _call(e) {
      return await this.feature_extractor(e);
    }
  };
  var q_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    async _call(e) {
      return await this.feature_extractor(e);
    }
  };
  var j_ = class extends U {
    static tokenizer_class = W;
    static feature_extractor_class = ge2;
    async _call(e) {
      return await this.feature_extractor(e);
    }
  };
  var el = class {
    static async from_pretrained(e, s = {}) {
      let r = await Ie(e, bt, true, s), { image_processor_type: n, feature_extractor_type: o, processor_class: i } = r;
      if (i && Za2[i]) return Za2[i].from_pretrained(e, s);
      if (!n && !o) throw new Error("No `image_processor_type` or `feature_extractor_type` found in the config.");
      let a = {};
      if (n) {
        let c = Us2[n.replace(/Fast$/, "")];
        if (!c) throw new Error(`Unknown image_processor_type: '${n}'.`);
        a.image_processor = new c(r);
      }
      if (o) {
        let c = Us2[o];
        if (c) a.image_processor = new c(r);
        else {
          let p = Jr2[o];
          if (!p) throw new Error(`Unknown feature_extractor_type: '${o}'.`);
          a.feature_extractor = new p(r);
        }
      }
      let l = {};
      return new U(l, a, null);
    }
  };
  async function iM(t6, e) {
    return await Ie(t6, "config.json", true, e);
  }
  function Ws2(t6) {
    let e = {}, s = {};
    switch (t6.model_type) {
      case "llava":
      case "paligemma":
      case "gemma3":
      case "florence2":
      case "llava_onevision":
      case "idefics3":
      case "granite_speech":
      case "ultravox":
      case "voxtral":
      case "voxtral_realtime":
      case "smolvlm":
      case "gemma3n":
      case "gemma4":
      case "lfm2_vl":
      case "chatterbox":
      case "lighton_ocr":
      case "glm_ocr":
      case "mistral3":
      case "qwen2_5_vl":
      case "qwen3_vl":
      case "qwen3_vl_moe":
        s = Ws2(t6.text_config);
        break;
      case "moondream1":
        s = Ws2(t6.phi_config);
        break;
      case "musicgen":
        s = Ws2(t6.decoder);
        break;
      case "multi_modality":
        s = Ws2(t6.language_config);
        break;
      case "gpt2":
      case "gptj":
      case "jais":
      case "codegen":
      case "gpt_bigcode":
        e.num_heads = "n_head", e.num_layers = "n_layer", e.hidden_size = "n_embd";
        break;
      case "gpt_neox":
      case "stablelm":
      case "opt":
      case "falcon":
      case "modernbert-decoder":
        e.num_heads = "num_attention_heads", e.num_layers = "num_hidden_layers", e.hidden_size = "hidden_size";
        break;
      case "gpt_oss":
      case "llama":
      case "llama4_text":
      case "nanochat":
      case "apertus":
      case "arcee":
      case "afmoe":
      case "lfm2":
      case "lfm2_moe":
      case "smollm3":
      case "olmo":
      case "olmo2":
      case "olmo3":
      case "mobilellm":
      case "granite":
      case "granitemoehybrid":
      case "cohere":
      case "cohere2":
      case "mistral":
      case "voxtral_realtime_text":
      case "voxtral_realtime_encoder":
      case "starcoder2":
      case "qwen2":
      case "qwen2_moe":
      case "qwen2_vl":
      case "qwen2_vl_text":
      case "qwen2_5_vl_text":
      case "qwen3_moe":
      case "qwen3_vl_text":
      case "qwen3_vl_moe_text":
      case "phi":
      case "phi3":
      case "phi3_v":
      case "llava_qwen2":
        e.num_heads = "num_key_value_heads", e.num_layers = "num_hidden_layers", e.hidden_size = "hidden_size", e.num_attention_heads = "num_attention_heads", e.dim_kv = "head_dim";
        break;
      case "qwen3":
      case "solar_open":
      case "glm_ocr_text":
      case "gemma":
      case "gemma2":
      case "vaultgemma":
      case "gemma3_text":
      case "gemma3n_text":
      case "gemma4_text":
      case "glm":
      case "helium":
      case "ernie4_5":
      case "hunyuan_v1_dense":
      case "falcon_h1":
      case "nemotron_h":
      case "ministral":
      case "ministral3":
        e.num_heads = "num_key_value_heads", e.num_layers = "num_hidden_layers", e.dim_kv = "head_dim";
        break;
      case "openelm":
        e.num_heads = "num_kv_heads", e.num_layers = "num_transformer_layers", e.dim_kv = "head_dim";
        break;
      case "gpt_neo":
      case "donut-swin":
        e.num_heads = "num_heads", e.num_layers = "num_layers", e.hidden_size = "hidden_size";
        break;
      case "bloom":
        e.num_heads = "n_head", e.num_layers = "n_layer", e.hidden_size = "hidden_size";
        break;
      case "mpt":
        e.num_heads = "n_heads", e.num_layers = "n_layers", e.hidden_size = "d_model";
        break;
      case "exaone":
        e.num_heads = "num_key_value_heads", e.num_layers = "num_layers", e.dim_kv = "head_dim", e.num_attention_heads = "num_attention_heads";
        break;
      case "youtu":
      case "deepseek_v3":
      case "glm_moe_dsa":
      case "mistral4":
        e.num_heads = "num_key_value_heads", e.num_layers = "num_hidden_layers", e.dim_kv = "qk_head_dim", e.num_attention_heads = "num_attention_heads";
        break;
      case "t5":
      case "mt5":
      case "longt5":
        e.num_decoder_layers = "num_decoder_layers", e.num_decoder_heads = "num_heads", e.decoder_dim_kv = "d_kv", e.num_encoder_layers = "num_layers", e.num_encoder_heads = "num_heads", e.encoder_dim_kv = "d_kv";
        break;
      case "bart":
      case "mbart":
      case "marian":
      case "whisper":
      case "lite-whisper":
      case "m2m_100":
      case "blenderbot":
      case "blenderbot-small":
      case "florence2_language":
        e.num_decoder_layers = "decoder_layers", e.num_decoder_heads = "decoder_attention_heads", e.decoder_hidden_size = "d_model", e.num_encoder_layers = "encoder_layers", e.num_encoder_heads = "encoder_attention_heads", e.encoder_hidden_size = "d_model";
        break;
      case "speecht5":
        e.num_decoder_layers = "decoder_layers", e.num_decoder_heads = "decoder_attention_heads", e.decoder_hidden_size = "hidden_size", e.num_encoder_layers = "encoder_layers", e.num_encoder_heads = "encoder_attention_heads", e.encoder_hidden_size = "hidden_size";
        break;
      case "trocr":
        e.num_encoder_layers = e.num_decoder_layers = "decoder_layers", e.num_encoder_heads = e.num_decoder_heads = "decoder_attention_heads", e.encoder_hidden_size = e.decoder_hidden_size = "d_model";
        break;
      case "musicgen_decoder":
        e.num_encoder_layers = e.num_decoder_layers = "num_hidden_layers", e.num_encoder_heads = e.num_decoder_heads = "num_attention_heads", e.encoder_hidden_size = e.decoder_hidden_size = "hidden_size";
        break;
      case "moonshine":
        e.num_decoder_layers = "decoder_num_hidden_layers", e.num_decoder_heads = "decoder_num_key_value_heads", e.num_encoder_layers = "encoder_num_hidden_layers", e.num_encoder_heads = "encoder_num_key_value_heads", e.encoder_hidden_size = e.decoder_hidden_size = "hidden_size";
        break;
      case "cohere_asr":
        e.num_decoder_layers = "num_hidden_layers", e.num_decoder_heads = "num_key_value_heads", e.decoder_hidden_size = "hidden_size", e.decoder_dim_kv = "head_dim";
        let { num_hidden_layers: n, num_attention_heads: o, hidden_size: i } = t6.encoder_config;
        s = { num_encoder_layers: n, num_encoder_heads: o, encoder_hidden_size: i, encoder_dim_kv: t6.head_dim };
        break;
      case "vision-encoder-decoder":
        let a = Ws2(t6.decoder), l = "num_decoder_layers" in a, c = we(t6, ["model_type", "is_encoder_decoder"]);
        return l ? (c.num_decoder_layers = a.num_decoder_layers, c.num_decoder_heads = a.num_decoder_heads, c.decoder_hidden_size = a.decoder_hidden_size, c.num_encoder_layers = a.num_encoder_layers, c.num_encoder_heads = a.num_encoder_heads, c.encoder_hidden_size = a.encoder_hidden_size) : (c.num_layers = a.num_layers, c.num_heads = a.num_heads, c.hidden_size = a.hidden_size), c;
    }
    let r = { ...s, ...we(t6, ["model_type", "multi_query", "is_encoder_decoder"]) };
    for (let n in e) r[n] = t6[e[n]];
    return r;
  }
  function cs2(t6, e) {
    t6 instanceof Vs || (t6 = new Vs(t6));
    let s = e?.prefix ?? "past_key_values", r = s === "present" ? "present" : "past", n = /* @__PURE__ */ new Set();
    if (["lfm2", "lfm2_moe"].includes(t6.model_type)) {
      let { layer_types: o } = t6;
      for (let i = 0; i < o.length; ++i) if (o[i] === "full_attention") n.add(`${s}.${i}.key`), n.add(`${s}.${i}.value`);
      else if (o[i] === "conv") n.add(`${r}_conv.${i}`);
      else throw new Error(`Unsupported layer type: ${o[i]}`);
      return n;
    } else if (["granitemoehybrid", "falcon_h1", "nemotron_h"].includes(t6.model_type)) {
      let o = t6, i = o.layer_types ?? o.layers_block_type, a = o.num_hidden_layers ?? i?.length;
      for (let l = 0; l < a; ++l) (!i || i[l] === "mamba") && (n.add(`${r}_conv.${l}`), n.add(`${r}_ssm.${l}`)), (!i || i[l] === "attention") && (n.add(`${s}.${l}.key`), n.add(`${s}.${l}.value`));
      return n;
    } else if (["qwen3_next", "qwen3_5_text", "qwen3_5_moe_text", "olmo_hybrid"].includes(t6.model_type)) {
      let { layer_types: o } = t6;
      for (let i = 0; i < o.length; ++i) if (o[i] === "full_attention") n.add(`${s}.${i}.key`), n.add(`${s}.${i}.value`);
      else if (o[i] === "linear_attention") t6.model_type === "olmo_hybrid" ? (n.add(`${r}_conv.${i}.key`), n.add(`${r}_conv.${i}.value`), n.add(`${r}_conv.${i}.query`)) : n.add(`${r}_conv.${i}`), n.add(`${r}_recurrent.${i}`);
      else throw new Error(`Unsupported layer type: ${o[i]}`);
      return n;
    } else if (["gemma4", "gemma4_text"].includes(t6.model_type)) {
      let o = t6.model_type === "gemma4" ? t6.text_config : t6, i = o.num_hidden_layers, a = o.num_kv_shared_layers ?? 0, l = i - a;
      for (let c = 0; c < l; ++c) n.add(`${s}.${c}.key`), n.add(`${s}.${c}.value`);
      return n;
    } else if (["lfm2_vl", "qwen3_5", "qwen3_5_moe", "voxtral_realtime"].includes(t6.model_type)) {
      let o;
      return t6.model_type === "voxtral_realtime" && e?.session_name === "audio_encoder" ? o = t6.audio_config : o = t6.text_config, cs2(o, e);
    }
    return aM(t6, { prefix: s });
  }
  function aM(t6, { prefix: e = "past_key_values" } = {}) {
    let s = /* @__PURE__ */ new Set(), r = t6.normalized_config;
    if (r.is_encoder_decoder && "num_encoder_heads" in r && "num_decoder_heads" in r) for (let n = 0; n < r.num_decoder_layers; ++n) s.add(`${e}.${n}.encoder.key`), s.add(`${e}.${n}.encoder.value`), s.add(`${e}.${n}.decoder.key`), s.add(`${e}.${n}.decoder.value`);
    else if (r.multi_query) for (let n = 0; n < r.num_layers; ++n) s.add(`${e}.${n}.key_value`);
    else for (let n = 0; n < r.num_layers; ++n) s.add(`${e}.${n}.key`), s.add(`${e}.${n}.value`);
    return s;
  }
  var Vs = class t4 {
    model_type = null;
    is_encoder_decoder = false;
    max_position_embeddings;
    "transformers.js_config";
    constructor(e) {
      Object.assign(this, e), this.normalized_config = Ws2(this);
    }
    static async from_pretrained(e, { progress_callback: s = null, config: r = null, cache_dir: n = null, local_files_only: o = false, revision: i = "main" } = {}) {
      r && !(r instanceof t4) && (r = new t4(r));
      let a = r ?? await iM(e, { progress_callback: s, config: r, cache_dir: n, local_files_only: o, revision: i });
      return new this(a);
    }
  };
  var tt2 = class {
    static async from_pretrained(...e) {
      return Vs.from_pretrained(...e);
    }
  };
  function B_(t6, e, s) {
    return t6 ? typeof t6 == "object" && t6 !== null ? t6.hasOwnProperty(e) ? +t6[e] : t6.hasOwnProperty(s) ? +t6[s] : 0 : +t6 : 0;
  }
  function U_(t6, e) {
    let s = [];
    for (let r = 0; r < e; ++r) s.push(`${t6}_data${r === 0 ? "" : "_" + r}`);
    return s;
  }
  async function Eb(t6, e, s, r) {
    let n = `${e}${r}.onnx`, o = `${s.subfolder ?? ""}/${n}`;
    return await Lr(t6, o, true, s, K2.IS_NODE_ENV);
  }
  async function Ab(t6, e, s, r, n, o = {}) {
    let i = `${e}${s}.onnx`, a = K2.IS_NODE_ENV, l = [], c = B_(n, i, e);
    if (c > 0) {
      if (c > ua) throw new Error(`The number of external data chunks (${c}) exceeds the maximum allowed value (${ua}).`);
      let p = U_(i, c);
      for (let u of p) {
        let _ = `${r.subfolder ?? ""}/${u}`;
        l.push(new Promise(async (d, m) => {
          let f = await Lr(t6, _, true, r, a);
          d(f instanceof Uint8Array ? { path: u, data: f } : u);
        }));
      }
    } else o.externalData !== void 0 && (l = o.externalData.map(async (p) => {
      if (typeof p.data == "string") {
        let u = await Lr(t6, p.data, true, r);
        return { ...p, data: u };
      }
      return p;
    }));
    return Promise.all(l);
  }
  async function lM(t6, e, s, r = false, n = void 0) {
    let o = s.config?.["transformers.js_config"] ?? {}, i = ya(s.device ?? o.device, e, { warn: (x) => F.info(x) }), a = X0(i), l = o.device_config ?? {};
    l.hasOwnProperty(i) && (o = { ...o, ...l[i] });
    let c = ba(s.dtype ?? o.dtype, e, i, { configDtype: o.dtype, warn: (x) => F.info(x) });
    if (Nt.hasOwnProperty(c)) {
      if (i === "webgpu" && !K2.IS_NODE_ENV && c === Oe.fp16 && !await eb()) throw new Error(`The device (${i}) does not support fp16.`);
    } else throw new Error(`Invalid dtype: ${c}. Should be one of: ${Object.keys(Oe).join(", ")}`);
    let p = Nt[c], u = { ...s.session_options };
    u.executionProviders ??= a;
    let _ = o.free_dimension_overrides;
    _ ? u.freeDimensionOverrides ??= _ : i.startsWith("webnn") && !u.freeDimensionOverrides && F.warn(`WebNN does not currently support dynamic shapes and requires 'free_dimension_overrides' to be set in config.json, preferably as a field within config["transformers.js_config"]["device_config"]["${i}"]. When 'free_dimension_overrides' is not set, you may experience significant performance degradation.`);
    let d = Eb(t6, e, s, p), m = s.use_external_data_format ?? o.use_external_data_format, f = await Ab(t6, e, p, s, m, u);
    if (f.length > 0 && (!K2.IS_NODE_ENV || f.some((x) => typeof x != "string")) && (u.externalData = f), r && i === "webgpu") {
      let x = cs2(s.config, { prefix: "present", session_name: n });
      if (x.size > 0 && !Rr()) {
        let y = {};
        for (let b of x) y[b] = "gpu-buffer";
        u.preferredOutputLocation = y;
      }
    }
    return { buffer_or_path: await d, session_options: u, session_config: { dtype: c, device: i } };
  }
  async function Mb(t6, e, s, r = void 0) {
    return Object.fromEntries(await Promise.all(Object.keys(e).map(async (n) => {
      let o = r?.[n] ?? false, { buffer_or_path: i, session_options: a, session_config: l } = await lM(t6, e[n], s, o, n), c = await ga(i, a, l);
      return [n, c];
    })));
  }
  function Sb(t6) {
    for (let e in t6) wa(t6[e]) ? t6[e] = new E(t6[e]) : typeof t6[e] == "object" && Sb(t6[e]);
    return t6;
  }
  async function X(t6, e) {
    let s = cM(t6, e);
    try {
      let r = Object.fromEntries(Object.entries(s).map(([o, i]) => {
        let a = i.ort_tensor;
        return K2.IS_NODE_ENV && typeof Float16Array < "u" && a.cpuData instanceof Float16Array && (a.cpuData = new Uint16Array(a.cpuData.buffer)), [o, a];
      })), n = await xa2(t6, r);
      return Sb(n);
    } catch (r) {
      let n = Object.fromEntries(Object.entries(s).map(([o, i]) => {
        let a = { type: i.type, dims: i.dims, location: i.location };
        return a.location !== "gpu-buffer" && (a.data = i.data), [o, a];
      }));
      throw F.error(`An error occurred during model execution: "${r}".`), F.error("Inputs given to model:", n), r;
    }
  }
  function cM(t6, e) {
    let s = /* @__PURE__ */ Object.create(null), r = [];
    for (let i of t6.inputNames) {
      let a = e[i];
      if (!(a instanceof E)) {
        r.push(i);
        continue;
      }
      s[i] = Rr() ? a.clone() : a;
    }
    if (r.length > 0) throw new Error(`An error occurred during model execution: "Missing the following inputs: ${r.join(", ")}.`);
    let n = Object.keys(e).length, o = t6.inputNames.length;
    if (n > o) {
      let i = Object.keys(e).filter((a) => !t6.inputNames.includes(a));
      F.warn(`WARNING: Too many inputs were provided (${n} > ${o}). The following inputs will be ignored: "${i.join(", ")}".`);
    }
    return s;
  }
  var he = class {
  };
  var z2 = class extends he {
    constructor({ logits: e, ...s }) {
      super(), this.logits = e;
      let r = Object.values(s);
      r.length > 0 && (this.attentions = r);
    }
  };
  var se = class extends he {
    constructor({ logits: e }) {
      super(), this.logits = e;
    }
  };
  var ne = class extends he {
    constructor({ logits: e }) {
      super(), this.logits = e;
    }
  };
  var ue = class extends he {
    constructor({ start_logits: e, end_logits: s }) {
      super(), this.start_logits = e, this.end_logits = s;
    }
  };
  var Be = class extends he {
    constructor({ logits: e }) {
      super(), this.logits = e;
    }
  };
  var tl = class extends he {
    constructor({ alphas: e }) {
      super(), this.alphas = e;
    }
  };
  var Qe = class extends xe {
    _call(e, s) {
      throw Error("`_call` should be implemented in a subclass");
    }
  };
  var nn2 = class extends xe {
    _call(e, s) {
      throw Error("`_call` should be implemented in a subclass");
    }
  };
  var ps2 = class extends xe {
    constructor() {
      super(), this.processors = [];
    }
    push(e) {
      this.processors.push(e);
    }
    extend(e) {
      this.processors.push(...e);
    }
    _call(e, s) {
      let r = s;
      for (let n of this.processors) r = n(e, r);
      return r;
    }
    [Symbol.iterator]() {
      return this.processors.values();
    }
  };
  var sl = class extends Qe {
    constructor(e) {
      super(), this.bos_token_id = e;
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) if (e[r].length === 1) {
        let n = s[r].data;
        n.fill(-1 / 0), n[this.bos_token_id] = 0;
      }
      return s;
    }
  };
  var rl = class extends Qe {
    constructor(e, s) {
      super(), this.max_length = e, this.eos_token_id = Array.isArray(s) ? s : [s];
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) if (e[r].length === this.max_length - 1) {
        let n = s[r].data;
        n.fill(-1 / 0);
        for (let o of this.eos_token_id) n[o] = 0;
      }
      return s;
    }
  };
  var nl = class extends Qe {
    constructor(e) {
      super(), this.suppress_tokens = e;
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) {
        let n = s[r].data;
        for (let o of this.suppress_tokens) n[o] = -1 / 0;
      }
      return s;
    }
  };
  var Hs = class extends Qe {
    constructor(e, s) {
      super(), this.begin_suppress_tokens = e, this.begin_index = s;
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) if (e[r].length === this.begin_index) {
        let n = s[r].data;
        for (let o of this.begin_suppress_tokens) n[o] = -1 / 0;
      }
      return s;
    }
  };
  var ol = class extends Qe {
    constructor(e, s) {
      super(), this.eos_token_id = Array.isArray(e.eos_token_id) ? e.eos_token_id[0] : e.eos_token_id, this.no_timestamps_token_id = e.no_timestamps_token_id, this.timestamp_begin = this.no_timestamps_token_id + 1, this.begin_index = s.length, s.at(-1) === this.no_timestamps_token_id && (this.begin_index -= 1), this.max_initial_timestamp_index = e.max_initial_timestamp_index;
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) {
        let n = s[r].data;
        if (n[this.no_timestamps_token_id] = -1 / 0, e[r].length === this.begin_index) {
          n.subarray(0, this.timestamp_begin).fill(-1 / 0);
          continue;
        }
        let o = e[r].slice(this.begin_index), i = o.length >= 1 && o[o.length - 1] >= this.timestamp_begin, a = o.length < 2 || o[o.length - 2] >= this.timestamp_begin;
        if (i && (a ? n.subarray(this.timestamp_begin).fill(-1 / 0) : n.subarray(0, this.eos_token_id).fill(-1 / 0)), e[r].length === this.begin_index && this.max_initial_timestamp_index !== null) {
          let u = this.timestamp_begin + this.max_initial_timestamp_index;
          n.subarray(u + 1).fill(-1 / 0);
        }
        let l = rp(n), c = Math.log(l.subarray(this.timestamp_begin).map(Math.exp).reduce((u, _) => u + _)), p = de(l.subarray(0, this.timestamp_begin))[0];
        c > p && n.subarray(0, this.timestamp_begin).fill(-1 / 0);
      }
      return s;
    }
  };
  var il = class extends Qe {
    constructor(e) {
      super(), this.no_repeat_ngram_size = e;
    }
    getNgrams(e) {
      let s = e.length, r = [];
      for (let o = 0; o < s + 1 - this.no_repeat_ngram_size; ++o) {
        let i = [];
        for (let a = 0; a < this.no_repeat_ngram_size; ++a) i.push(e[o + a]);
        r.push(i.map(Number));
      }
      let n = /* @__PURE__ */ new Map();
      for (let o of r) {
        let i = o.slice(0, o.length - 1), a = JSON.stringify(i), l = n.get(a) ?? [];
        l.push(o[o.length - 1]), n.set(a, l);
      }
      return n;
    }
    getGeneratedNgrams(e, s) {
      let r = s.slice(s.length + 1 - this.no_repeat_ngram_size, s.length);
      return e.get(JSON.stringify(r.map(Number))) ?? [];
    }
    calcBannedNgramTokens(e) {
      let s = [];
      if (e.length + 1 < this.no_repeat_ngram_size) return s;
      {
        let r = this.getNgrams(e);
        return this.getGeneratedNgrams(r, e);
      }
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) {
        let n = s[r].data, o = this.calcBannedNgramTokens(e[r]);
        for (let i of o) n[i] = -1 / 0;
      }
      return s;
    }
  };
  var al = class extends Qe {
    constructor(e) {
      super(), this.penalty = e;
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) {
        let n = s[r].data;
        for (let o of new Set(e[r])) {
          let i = Number(o);
          n[i] < 0 ? n[i] *= this.penalty : n[i] /= this.penalty;
        }
      }
      return s;
    }
  };
  var ll = class extends Qe {
    constructor(e, s) {
      super(), this.min_length = e, this.eos_token_id = Array.isArray(s) ? s : [s];
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) if (e[r].length < this.min_length) {
        let n = s[r].data;
        for (let o of this.eos_token_id) n[o] = -1 / 0;
      }
      return s;
    }
  };
  var cl = class extends Qe {
    constructor(e, s, r) {
      super(), this.prompt_length_to_skip = e, this.min_new_tokens = s, this.eos_token_id = Array.isArray(r) ? r : [r];
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) if (e[r].length - this.prompt_length_to_skip < this.min_new_tokens) {
        let o = s[r].data;
        for (let i of this.eos_token_id) o[i] = -1 / 0;
      }
      return s;
    }
  };
  var pl = class extends Qe {
    constructor(e, s) {
      super(), this.bad_words_ids = e, this.eos_token_id = Array.isArray(s) ? s : [s];
    }
    _call(e, s) {
      for (let r = 0; r < e.length; ++r) {
        let n = s[r].data, o = e[r];
        for (let i of this.bad_words_ids) {
          if (o.length < i.length - 1) continue;
          let a = true;
          for (let l = 1; l <= i.length - 1; ++l) if (i.at(-l - 1) != o.at(-l)) {
            a = false;
            break;
          }
          a && (n[i.at(-1)] = -1 / 0);
        }
      }
      return s;
    }
  };
  var ul = class extends Qe {
    constructor(e) {
      if (super(), e <= 1) throw new Error(`Require guidance scale >1 to use the classifier free guidance processor, got guidance scale ${e}.`);
      this.guidance_scale = e;
    }
    _call(e, s) {
      if (s.dims[0] !== 2 * e.length) throw new Error(`Logits should have twice the batch size of the input ids, the first half of batches corresponding to the conditional inputs, and the second half of batches corresponding to the unconditional inputs. Got batch size ${s.dims[0]} for the logits and ${e.length} for the input ids.`);
      let r = e.length, n = s.slice([0, r], null), o = s.slice([r, s.dims[0]], null);
      for (let i = 0; i < o.data.length; ++i) o.data[i] += (n.data[i] - o.data[i]) * this.guidance_scale;
      return o;
    }
  };
  var _l = class extends nn2 {
    constructor(e) {
      if (super(), typeof e != "number" || e <= 0) {
        let s = `\`temperature\` (=${e}) must be a strictly positive float, otherwise your next token scores will be invalid.`;
        e === 0 && (s += " If you're looking for greedy decoding strategies, set `do_sample=false`.");
      }
      this.temperature = e;
    }
    _call(e, s) {
      let r = s.data;
      for (let n = 0; n < r.length; ++n) r[n] /= this.temperature;
      return s;
    }
  };
  var Ks = class {
    max_length = 20;
    max_new_tokens = null;
    min_length = 0;
    min_new_tokens = null;
    early_stopping = false;
    max_time = null;
    do_sample = false;
    num_beams = 1;
    num_beam_groups = 1;
    penalty_alpha = null;
    use_cache = true;
    temperature = 1;
    top_k = 50;
    top_p = 1;
    typical_p = 1;
    epsilon_cutoff = 0;
    eta_cutoff = 0;
    diversity_penalty = 0;
    repetition_penalty = 1;
    encoder_repetition_penalty = 1;
    length_penalty = 1;
    no_repeat_ngram_size = 0;
    bad_words_ids = null;
    force_words_ids = null;
    renormalize_logits = false;
    constraints = null;
    forced_bos_token_id = null;
    forced_eos_token_id = null;
    remove_invalid_values = false;
    exponential_decay_length_penalty = null;
    suppress_tokens = null;
    streamer = null;
    begin_suppress_tokens = null;
    forced_decoder_ids = null;
    guidance_scale = null;
    num_return_sequences = 1;
    output_attentions = false;
    output_hidden_states = false;
    output_scores = false;
    return_dict_in_generate = false;
    pad_token_id = null;
    bos_token_id = null;
    eos_token_id = null;
    encoder_no_repeat_ngram_size = 0;
    decoder_start_token_id = null;
    generation_kwargs = {};
    constructor(e) {
      Object.assign(this, we(e, Object.getOwnPropertyNames(this)));
    }
  };
  var Dt = class extends xe {
    _call(e, s) {
      throw Error("StoppingCriteria needs to be subclassed");
    }
  };
  var Xs = class t5 extends xe {
    constructor() {
      super(), this.criteria = [];
    }
    push(e) {
      this.criteria.push(e);
    }
    extend(e) {
      e instanceof t5 ? e = e.criteria : e instanceof Dt && (e = [e]), this.criteria.push(...e);
    }
    _call(e, s) {
      let r = new Array(e.length).fill(false);
      for (let n of this.criteria) {
        let o = n(e, s);
        for (let i = 0; i < r.length; ++i) r[i] ||= o[i];
      }
      return r;
    }
    [Symbol.iterator]() {
      return this.criteria.values();
    }
  };
  var dl = class extends Dt {
    constructor(e, s = null) {
      super(), this.max_length = e, this.max_position_embeddings = s;
    }
    _call(e) {
      return e.map((s) => s.length >= this.max_length);
    }
  };
  var fl = class extends Dt {
    constructor(e) {
      super(), Array.isArray(e) || (e = [e]), this.eos_token_id = e;
    }
    _call(e, s) {
      return e.map((r) => {
        let n = r.at(-1);
        return this.eos_token_id.some((o) => n == o);
      });
    }
  };
  var us2 = class extends xe {
    constructor(e) {
      super(), this.generation_config = e;
    }
    async _call(e) {
      return this.sample(e);
    }
    async sample(e) {
      throw Error("sample should be implemented in subclasses.");
    }
    getLogits(e, s) {
      let r = e.dims.at(-1), n = e.data;
      if (s === -1) n = n.slice(-r);
      else {
        let o = s * r;
        n = n.slice(o, o + r);
      }
      return n;
    }
    randomSelect(e) {
      return E0(e);
    }
    static getSampler(e) {
      if (e.do_sample) return new W_(e);
      if (e.num_beams > 1) return new V_(e);
      if (e.num_return_sequences > 1) throw Error(`num_return_sequences has to be 1 when doing greedy search, but is ${e.num_return_sequences}.`);
      return new G_(e);
    }
  };
  var G_ = class extends us2 {
    async sample(e) {
      let s = de(e.data)[1];
      return [[BigInt(s), 0]];
    }
  };
  var W_ = class extends us2 {
    async sample(e) {
      let s = e.dims.at(-1);
      this.generation_config.top_k > 0 && (s = Math.min(this.generation_config.top_k, s));
      let [r, n] = await lt(e, s), o = me(r.data);
      return Array.from({ length: this.generation_config.num_beams }, () => {
        let i = this.randomSelect(o);
        return [n.data[i], Math.log(o[i])];
      });
    }
  };
  var V_ = class extends us2 {
    async sample(e) {
      let s = e.dims.at(-1);
      this.generation_config.top_k > 0 && (s = Math.min(this.generation_config.top_k, s));
      let [r, n] = await lt(e, s), o = me(r.data);
      return Array.from({ length: this.generation_config.num_beams }, (i, a) => [n.data[a], Math.log(o[a])]);
    }
  };
  var H_ = class {
    constructor(e) {
      if (e) for (let s in e) {
        if (s in this) throw new TypeError(`Key "${s}" conflicts with an existing property on DynamicCache`);
        let r = e[s];
        if (!(r instanceof E)) throw new TypeError(`Expected a Tensor for key "${s}", got ${typeof r}`);
        this[s] = r;
      }
    }
    get_seq_length() {
      let e = this;
      if (Object.keys(e).length === 0) return 0;
      for (let s in e) if (s.startsWith("past_key_values.")) return e[s].dims.at(-2);
      throw new Error("Unable to determine sequence length from the cache.");
    }
    update(e) {
      for (let s in e) {
        let r = this[s], n = e[s];
        r && r !== n && r.location === "gpu-buffer" && r.dispose(), this[s] = n;
      }
    }
    async dispose() {
      let e = [];
      for (let s of Object.values(this)) s.location === "gpu-buffer" && e.push(s.dispose());
      await Promise.all(e);
    }
  };
  var Qs = H_;
  var N = { EncoderOnly: 0, EncoderDecoder: 1, Seq2Seq: 2, Vision2Seq: 3, DecoderOnly: 4, DecoderOnlyWithoutHead: 5, MaskGeneration: 6, ImageTextToText: 7, Musicgen: 8, MultiModality: 9, Phi3V: 10, AudioTextToText: 11, AutoEncoder: 12, ImageAudioTextToText: 13, Supertonic: 14, Chatterbox: 15, VoxtralRealtime: 16 };
  var gt = { [N.DecoderOnly]: { sessions: (t6, e) => ({ model: e.model_file_name ?? "model" }), cache_sessions: { model: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.DecoderOnlyWithoutHead]: { sessions: (t6, e) => ({ model: e.model_file_name ?? "model" }) }, [N.Seq2Seq]: { sessions: () => ({ model: "encoder_model", decoder_model_merged: "decoder_model_merged" }), cache_sessions: { decoder_model_merged: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.Vision2Seq]: { sessions: () => ({ model: "encoder_model", decoder_model_merged: "decoder_model_merged" }), cache_sessions: { decoder_model_merged: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.Musicgen]: { sessions: () => ({ model: "text_encoder", decoder_model_merged: "decoder_model_merged", encodec_decode: "encodec_decode" }), cache_sessions: { decoder_model_merged: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.EncoderDecoder]: { sessions: () => ({ model: "encoder_model", decoder_model_merged: "decoder_model_merged" }), cache_sessions: { decoder_model_merged: true } }, [N.MaskGeneration]: { sessions: () => ({ model: "vision_encoder", prompt_encoder_mask_decoder: "prompt_encoder_mask_decoder" }) }, [N.ImageTextToText]: { text_only_sessions: { embed_tokens: "embed_tokens", decoder_model_merged: "decoder_model_merged" }, sessions: (t6, e, s) => {
    let r = { ...gt[N.ImageTextToText].text_only_sessions };
    return s || (r.vision_encoder = "vision_encoder"), t6.is_encoder_decoder && (r.model = "encoder_model"), r;
  }, cache_sessions: { decoder_model_merged: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.AudioTextToText]: { text_only_sessions: { embed_tokens: "embed_tokens", decoder_model_merged: "decoder_model_merged" }, sessions: (t6, e, s) => {
    let r = { ...gt[N.AudioTextToText].text_only_sessions };
    return s || (r.audio_encoder = "audio_encoder"), r;
  }, cache_sessions: { decoder_model_merged: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.ImageAudioTextToText]: { text_only_sessions: { embed_tokens: "embed_tokens", decoder_model_merged: "decoder_model_merged" }, sessions: (t6, e, s) => {
    let r = { ...gt[N.ImageAudioTextToText].text_only_sessions };
    return s || (r.audio_encoder = "audio_encoder", r.vision_encoder = "vision_encoder"), r;
  }, optional_configs: { generation_config: "generation_config.json" } }, [N.Phi3V]: { sessions: () => ({ prepare_inputs_embeds: "prepare_inputs_embeds", model: "model", vision_encoder: "vision_encoder" }), cache_sessions: { model: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.MultiModality]: { sessions: () => ({ prepare_inputs_embeds: "prepare_inputs_embeds", model: "language_model", lm_head: "lm_head", gen_head: "gen_head", gen_img_embeds: "gen_img_embeds", image_decode: "image_decode" }), cache_sessions: { model: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.AutoEncoder]: { sessions: () => ({ encoder_model: "encoder_model", decoder_model: "decoder_model" }) }, [N.Supertonic]: { sessions: () => ({ text_encoder: "text_encoder", latent_denoiser: "latent_denoiser", voice_decoder: "voice_decoder" }) }, [N.Chatterbox]: { sessions: () => ({ embed_tokens: "embed_tokens", speech_encoder: "speech_encoder", model: "language_model", conditional_decoder: "conditional_decoder" }), cache_sessions: { model: true }, optional_configs: { generation_config: "generation_config.json" } }, [N.VoxtralRealtime]: { text_only_sessions: { embed_tokens: "embed_tokens", decoder_model_merged: "decoder_model_merged" }, sessions: (t6, e, s) => {
    let r = { ...gt[N.VoxtralRealtime].text_only_sessions };
    return s || (r.audio_encoder = "audio_encoder"), r;
  }, cache_sessions: { decoder_model_merged: true, audio_encoder: true }, optional_configs: { generation_config: "generation_config.json" } }, default: { sessions: (t6, e) => ({ model: e.model_file_name ?? "model" }) } };
  function on2(t6, e, s = {}) {
    let r = gt[t6] ?? gt.default;
    return { sessions: r.sessions(e, s, s.textOnly ?? false), cache_sessions: r.cache_sessions, optional_configs: r.optional_configs };
  }
  function Ys(t6, { warn: e = true } = {}) {
    let s = t6.architectures || [];
    for (let r of s) {
      let n = ct.get(r);
      if (n !== void 0) return n;
    }
    if (t6.model_type) {
      let r = ct.get(t6.model_type);
      if (r !== void 0) return r;
      for (let n of Object.values(_s2)) if (n.has(t6.model_type)) {
        let o = ct.get(n.get(t6.model_type));
        if (o !== void 0) return o;
      }
    }
    if (e) {
      let r = s.length > 0 ? s.join(", ") : "(none)";
      F.warn(`[resolve_model_type] Architecture(s) not found in MODEL_TYPE_MAPPING: [${r}] for model type '${t6.model_type}'. Falling back to EncoderOnly (single model.onnx file). If you encounter issues, please report at: ${$t2}`);
    }
    return N.EncoderOnly;
  }
  function an2(t6, { config: e = null, cache_dir: s = null, local_files_only: r = false, revision: n = "main" } = {}) {
    if (e !== null) return tt2.from_pretrained(t6, { config: e, cache_dir: s, local_files_only: r, revision: n });
    let o = JSON.stringify([t6, s, r, n]);
    return da(o, () => tt2.from_pretrained(t6, { config: e, cache_dir: s, local_files_only: r, revision: n }));
  }
  async function Js(t6, { config: e = null, dtype: s = null, device: r = null, model_file_name: n = null } = {}) {
    e = await an2(t6, { config: e });
    let o = ["config.json"], i = e["transformers.js_config"] ?? {}, a = i.use_external_data_format, l = "onnx", c = r ?? i.device, p = s ?? i.dtype, u = Ys(e), _ = (f, g = null) => {
      g = g ?? f;
      let w = ya(c, f), x = ba(p, f, w), y = Nt[x] ?? "", b = `${g}${y}.onnx`, v = l ? `${l}/${b}` : b;
      o.push(v);
      let k2 = B_(a, b, f);
      for (let S of U_(b, k2)) {
        let I = l ? `${l}/${S}` : S;
        o.push(I);
      }
    }, { sessions: d, optional_configs: m } = on2(u, e, { model_file_name: n });
    for (let [f, g] of Object.entries(d)) _(f, g);
    if (m) for (let f of Object.values(m)) o.push(f);
    return o;
  }
  var _s2 = null;
  function Pb(t6) {
    _s2 = t6;
  }
  function X_(t6) {
    if (t6 instanceof E) return t6;
    if (t6.length === 0) throw Error("items must be non-empty");
    if (Array.isArray(t6[0])) {
      if (t6.some((e) => e.length !== t6[0].length)) throw Error("Unable to create tensor, you should probably activate truncation and/or padding with 'padding=True' and/or 'truncation=True' to have batched tensors with the same length.");
      return new E("int64", BigInt64Array.from(t6.flat().map((e) => BigInt(e))), [t6.length, t6[0].length]);
    } else return new E("int64", BigInt64Array.from(t6.map((e) => BigInt(e))), [1, t6.length]);
  }
  function Q_(t6) {
    return new E("bool", [t6], [1]);
  }
  var Tb = { [N.DecoderOnly]: { can_generate: true, forward: Ve2, prepare_inputs: Zs }, [N.DecoderOnlyWithoutHead]: { can_generate: false, forward: Ve2, prepare_inputs: Zs }, [N.Seq2Seq]: { can_generate: true, forward: ml, prepare_inputs: ln2 }, [N.Vision2Seq]: { can_generate: true, forward: ml, prepare_inputs: ln2 }, [N.Musicgen]: { can_generate: true, forward: ml }, [N.EncoderDecoder]: { can_generate: false, forward: ml }, [N.ImageTextToText]: { can_generate: true, forward: dM, prepare_inputs: hl }, [N.AudioTextToText]: { can_generate: true, forward: _M, prepare_inputs: hl }, [N.ImageAudioTextToText]: { can_generate: true, prepare_inputs: hl }, [N.Phi3V]: { can_generate: true, prepare_inputs: hl }, [N.MultiModality]: { can_generate: true }, [N.AutoEncoder]: { can_generate: false, forward: pM }, [N.Chatterbox]: { can_generate: true, forward: st2 }, [N.VoxtralRealtime]: { can_generate: true, prepare_inputs: Zs }, default: { can_generate: false, forward: st2 } };
  function Cb(t6, e) {
    let s = ct.get(t6), r = false, n = e?.architectures?.[0];
    if (n && n !== t6 && t6?.endsWith("ForCausalLM") && n.endsWith("ForConditionalGeneration")) {
      let a = ct.get(n);
      a !== void 0 && (s = a, r = true);
    }
    let o = Tb[s] ?? Tb.default, i = gt[s] ?? gt.default;
    return { typeConfig: { ...o, ...i }, textOnly: r, modelType: s };
  }
  var ct = /* @__PURE__ */ new Map();
  var xl = /* @__PURE__ */ new Map();
  var ds2 = /* @__PURE__ */ new Map();
  var h = class extends xe {
    main_input_name = "input_ids";
    forward_params = ["input_ids", "attention_mask"];
    _return_dict_in_generate_keys = null;
    constructor(e, s, r) {
      super(), this.config = e, this.sessions = s, this.configs = r;
      let n = ds2.get(this.constructor), { typeConfig: o } = Cb(n, e);
      this.can_generate = o.can_generate, this._forward = o.forward, this._prepare_inputs_for_generation = o.prepare_inputs, this.can_generate && this.forward_params.push("past_key_values"), this.custom_config = this.config["transformers.js_config"] ?? {};
    }
    async dispose() {
      let e = [];
      for (let s of Object.values(this.sessions)) e.push(s.release?.());
      return await Promise.all(e);
    }
    static async from_pretrained(e, { progress_callback: s = null, config: r = null, cache_dir: n = null, local_files_only: o = false, revision: i = "main", model_file_name: a = null, subfolder: l = "onnx", device: c = null, dtype: p = null, use_external_data_format: u = null, session_options: _ = {} } = {}) {
      let d = { progress_callback: s, config: r, cache_dir: n, local_files_only: o, revision: i, model_file_name: a, subfolder: l, device: c, dtype: p, use_external_data_format: u, session_options: _ }, m = ds2.get(this);
      r = d.config = await tt2.from_pretrained(e, d);
      let { typeConfig: f, textOnly: g, modelType: w } = Cb(m, r);
      if (w === void 0) {
        let v = m ?? r?.model_type;
        v !== "custom" && F.warn(`Model type for '${v}' not found, assuming encoder-only architecture. Please report this at ${$t2}.`);
      }
      if (s && !(s instanceof ts2)) {
        let v = {};
        try {
          let k2 = await Js(e, { config: r, dtype: p, device: c, model_file_name: a });
          (await Promise.all(k2.map((I) => We(e, I, d)))).forEach((I, $2) => {
            if (I.exists) {
              let C = k2[$2] === "config.json";
              v[k2[$2]] = { loaded: C ? I.size ?? 0 : 0, total: I.size ?? 0 };
            }
          });
        } catch (k2) {
          F.warn(`Unable to fetch model file metadata for total progress tracking: ${k2}`);
        }
        Object.keys(v).length > 0 && (d.progress_callback = new ts2(s, v));
      }
      let x = f.sessions(r, d, g), y = [Mb(e, x, d, f.cache_sessions)];
      f.optional_configs && y.push(mM(e, f.optional_configs, d));
      let b = await Promise.all(y);
      return new this(r, ...b);
    }
    async _call(e) {
      return await this.forward(e);
    }
    async forward(e) {
      return await this._forward(this, e);
    }
    get generation_config() {
      return this.configs?.generation_config ?? null;
    }
    _get_logits_processor(e, s, r = null) {
      let n = new ps2();
      if (e.repetition_penalty !== null && e.repetition_penalty !== 1 && n.push(new al(e.repetition_penalty)), e.no_repeat_ngram_size !== null && e.no_repeat_ngram_size > 0 && n.push(new il(e.no_repeat_ngram_size)), e.bad_words_ids !== null && n.push(new pl(e.bad_words_ids, e.eos_token_id)), e.min_length !== null && e.eos_token_id !== null && e.min_length > 0 && n.push(new ll(e.min_length, e.eos_token_id)), e.min_new_tokens !== null && e.eos_token_id !== null && e.min_new_tokens > 0 && n.push(new cl(s, e.min_new_tokens, e.eos_token_id)), e.forced_bos_token_id !== null && n.push(new sl(e.forced_bos_token_id)), e.forced_eos_token_id !== null && n.push(new rl(e.max_length, e.forced_eos_token_id)), e.suppress_tokens !== null && n.push(new nl(e.suppress_tokens)), e.begin_suppress_tokens !== null) {
        let o = s > 1 || e.forced_bos_token_id === null ? s : s + 1;
        n.push(new Hs(e.begin_suppress_tokens, o));
      }
      return e.guidance_scale !== null && e.guidance_scale > 1 && n.push(new ul(e.guidance_scale)), e.temperature === 0 && e.do_sample && (F.warn("`do_sample` changed to false because `temperature: 0` implies greedy sampling (always selecting the most likely token), which is incompatible with `do_sample: true`."), e.do_sample = false), e.do_sample && e.temperature !== null && e.temperature !== 1 && n.push(new _l(e.temperature)), r !== null && n.extend(r), n;
    }
    _prepare_generation_config(e, s, r = Ks) {
      let n = { ...this.config };
      for (let i of ["decoder", "generator", "text_config"]) i in n && Object.assign(n, n[i]);
      let o = new r(n);
      return Object.assign(o, this.generation_config ?? {}), e && Object.assign(o, e), s && Object.assign(o, we(s, Object.getOwnPropertyNames(o))), o;
    }
    _get_stopping_criteria(e, s = null) {
      let r = new Xs();
      return e.max_length !== null && r.push(new dl(e.max_length, this.config.max_position_embeddings ?? null)), e.eos_token_id !== null && r.push(new fl(e.eos_token_id)), s && r.extend(s), r;
    }
    _validate_model_class() {
      if (!this.can_generate) {
        let e = [_s2.MODEL_FOR_CAUSAL_LM_MAPPING_NAMES, _s2.MODEL_FOR_VISION_2_SEQ_MAPPING_NAMES, _s2.MODEL_FOR_SEQ_TO_SEQ_CAUSAL_LM_MAPPING_NAMES, _s2.MODEL_FOR_SPEECH_SEQ_2_SEQ_MAPPING_NAMES].filter(Boolean), s = ds2.get(this.constructor), r = /* @__PURE__ */ new Set(), n = this.config.model_type;
        for (let i of e) {
          let a = i?.get(n);
          a && r.add(a);
        }
        let o = `The current model class (${s}) is not compatible with \`.generate()\`, as it doesn't have a language model head.`;
        throw r.size > 0 && (o += ` Please use the following class instead: ${[...r].join(", ")}`), Error(o);
      }
    }
    prepare_inputs_for_generation(...e) {
      if (!this._prepare_inputs_for_generation) throw new Error("prepare_inputs_for_generation is not implemented for this model.");
      return this._prepare_inputs_for_generation(this, ...e);
    }
    _update_model_kwargs_for_generation({ generated_input_ids: e, outputs: s, model_inputs: r, is_encoder_decoder: n }) {
      return r.past_key_values = gl2(s, r.past_key_values), r.input_ids = new E("int64", e.flat(), [e.length, 1]), n ? "decoder_attention_mask" in r && (r.decoder_attention_mask = ie2([r.decoder_attention_mask, Me([r.decoder_attention_mask.dims[0], 1])], 1)) : r.attention_mask = ie2([r.attention_mask, Me([r.attention_mask.dims[0], 1])], 1), r.position_ids = null, r;
    }
    _prepare_model_inputs({ inputs: e, bos_token_id: s, model_kwargs: r }) {
      let n = we(r, this.forward_params), o = this.main_input_name;
      if (o in n) {
        if (e) throw new Error("`inputs`: {inputs}` were passed alongside {input_name} which is not allowed. Make sure to either pass {inputs} or {input_name}=...");
      } else n[o] = e;
      return { inputs_tensor: n[o], model_inputs: n, model_input_name: o };
    }
    async _prepare_encoder_decoder_kwargs_for_generation({ inputs_tensor: e, model_inputs: s, model_input_name: r, generation_config: n }) {
      if (this.sessions.model.inputNames.includes("inputs_embeds") && !s.inputs_embeds && "_prepare_inputs_embeds" in this) {
        let { input_ids: i, pixel_values: a, attention_mask: l, ...c } = s, p = await this._prepare_inputs_embeds(s);
        s = { ...c, ...we(p, ["inputs_embeds", "attention_mask"]) };
      }
      let { last_hidden_state: o } = await st2(this, s);
      if (n.guidance_scale !== null && n.guidance_scale > 1) o = ie2([o, qr2(o, 0)], 0), "attention_mask" in s && (s.attention_mask = ie2([s.attention_mask, _p(s.attention_mask)], 0));
      else if (s.decoder_input_ids) {
        let i = X_(s.decoder_input_ids).dims[0];
        if (i !== o.dims[0]) {
          if (o.dims[0] !== 1) throw new Error(`The encoder outputs have a different batch size (${o.dims[0]}) than the decoder inputs (${i}).`);
          o = ie2(Array.from({ length: i }, () => o), 0);
        }
      }
      return s.encoder_outputs = o, s;
    }
    _prepare_decoder_input_ids_for_generation({ batch_size: e, model_input_name: s, model_kwargs: r, decoder_start_token_id: n, bos_token_id: o, generation_config: i }) {
      let { decoder_input_ids: a, ...l } = r;
      if (!(a instanceof E)) {
        if (a) Array.isArray(a[0]) || (a = Array.from({ length: e }, () => a));
        else if (n ??= o, this.config.model_type === "musicgen") a = Array.from({ length: e * this.config.decoder.num_codebooks }, () => [n]);
        else if (Array.isArray(n)) {
          if (n.length !== e) throw new Error(`\`decoder_start_token_id\` expcted to have length ${e} but got ${n.length}`);
          a = n;
        } else a = Array.from({ length: e }, () => [n]);
        a = X_(a);
      }
      return l.decoder_attention_mask = Aa2(a), { input_ids: a, model_inputs: l };
    }
    async generate({ inputs: e = null, generation_config: s = null, logits_processor: r = null, stopping_criteria: n = null, streamer: o = null, ...i }) {
      this._validate_model_class(), s = this._prepare_generation_config(s, i);
      let { inputs_tensor: a, model_inputs: l, model_input_name: c } = this._prepare_model_inputs({ inputs: e, model_kwargs: i }), p = this.config.is_encoder_decoder;
      p && ("encoder_outputs" in l || (l = await this._prepare_encoder_decoder_kwargs_for_generation({ inputs_tensor: a, model_inputs: l, model_input_name: c, generation_config: s })));
      let u;
      p ? { input_ids: u, model_inputs: l } = this._prepare_decoder_input_ids_for_generation({ batch_size: l[c].dims.at(0), model_input_name: c, model_kwargs: l, decoder_start_token_id: s.decoder_start_token_id, bos_token_id: s.bos_token_id, generation_config: s }) : u = l[c];
      let _ = u.dims.at(-1);
      s.max_new_tokens !== null && (s.max_length = _ + s.max_new_tokens);
      let d = this._get_logits_processor(s, _, r), m = this._get_stopping_criteria(s, n), f = l[c].dims.at(0), g = us2.getSampler(s), w = new Array(f).fill(0), x = u.tolist();
      o && o.put(x);
      let y, b = {}, v = {};
      for (; ; ) {
        if (l = this.prepare_inputs_for_generation(x, l, s), y = await this.forward(l), s.return_dict_in_generate) if (s.output_attentions) {
          let j = uM(y);
          for (let B in j) B in b || (b[B] = []), b[B].push(j[B]);
        } else this._return_dict_in_generate_keys && Object.assign(v, we(y, this._return_dict_in_generate_keys));
        let C = y.logits.slice(null, -1, null).to("float32"), R = d(x, C), V = [];
        for (let j = 0; j < R.dims.at(0); ++j) {
          let B = R[j], Z = await g(B);
          for (let [D, A] of Z) {
            let O = BigInt(D);
            w[j] += A, x[j].push(O), V.push([O]);
            break;
          }
        }
        if (o && o.put(V), m(x).every((j) => j)) break;
        l = this._update_model_kwargs_for_generation({ generated_input_ids: V, outputs: y, model_inputs: l, is_encoder_decoder: p });
      }
      o && o.end();
      let k2 = new E("int64", x.flat(), [x.length, x[0].length]), S = gl2(y, l.past_key_values), I = new Set(Object.values(S));
      for (let C of Object.values(y)) C.location === "gpu-buffer" && !I.has(C) && C.dispose();
      return "past_key_values" in i || s.return_dict_in_generate || await S.dispose(), s.return_dict_in_generate ? { sequences: k2, past_key_values: S, ...b, ...v } : k2;
    }
    async _encode_input(e, s, r) {
      if (!Object.hasOwn(this.sessions, e)) throw new Error(`Model does not have a ${e} session.`);
      let n = this.sessions[e];
      return (await X(n, we(s, n.inputNames)))[r];
    }
    async encode_image(e) {
      return this._encode_input("vision_encoder", e, "image_features");
    }
    async encode_text(e) {
      return this._encode_input("embed_tokens", e, "inputs_embeds");
    }
    async encode_audio(e) {
      return this._encode_input("audio_encoder", e, "audio_features");
    }
  };
  async function ml(t6, e) {
    let { encoder_outputs: s, input_ids: r, decoder_input_ids: n, decoder_attention_mask: o, ...i } = e;
    if (!s) {
      let a = we(e, t6.sessions.model.inputNames);
      s = (await st2(t6, a)).last_hidden_state;
    }
    return i.input_ids = n, i.encoder_hidden_states = s, t6.sessions.decoder_model_merged.inputNames.includes("encoder_attention_mask") && (i.encoder_attention_mask = e.attention_mask), o && !i.attention_mask && (i.attention_mask = o), await Ve2(t6, i, true);
  }
  async function st2(t6, e) {
    let s = t6.sessions.model, r = we(e, s.inputNames);
    if (s.inputNames.includes("inputs_embeds") && !r.inputs_embeds) {
      if (!e.input_ids) throw new Error("Both `input_ids` and `inputs_embeds` are missing in the model inputs.");
      r.inputs_embeds = await t6.encode_text({ input_ids: e.input_ids });
    }
    if (s.inputNames.includes("token_type_ids") && !r.token_type_ids) {
      if (!r.input_ids) throw new Error("Both `input_ids` and `token_type_ids` are missing in the model inputs.");
      r.token_type_ids = _p(r.input_ids);
    }
    if (s.inputNames.includes("pixel_mask") && !r.pixel_mask) {
      if (!r.pixel_values) throw new Error("Both `pixel_values` and `pixel_mask` are missing in the model inputs.");
      let n = r.pixel_values.dims;
      r.pixel_mask = Me([n[0], n[2], n[3]]);
    }
    return await X(s, r);
  }
  async function pM(t6, e) {
    let s = await t6.encode(e);
    return await t6.decode(s);
  }
  function gl2(t6, e) {
    let s = /* @__PURE__ */ Object.create(null);
    for (let r in t6) if (r.startsWith("present")) {
      let n = r.replace("present_ssm", "past_ssm").replace("present_conv", "past_conv").replace("present_recurrent", "past_recurrent").replace("present", "past_key_values");
      r.includes("encoder") && e ? s[n] = e[n] : s[n] = t6[r];
    }
    return e ? (e.update(s), e) : new Qs(s);
  }
  function uM(t6) {
    let e = {};
    for (let s of ["cross_attentions", "encoder_attentions", "decoder_attentions"]) for (let r in t6) r.startsWith(s) && (s in e || (e[s] = []), e[s].push(t6[r]));
    return e;
  }
  function Y_(t6, e) {
    return t6.map((s) => typeof s == "number" ? s : e[s] ?? 0);
  }
  function cn2(t6, e, s) {
    if (s && Object.keys(s).length > 0) return Object.assign(e, s), s;
    let r = t6.sessions.decoder_model_merged ?? t6.sessions.model, n = (e[t6.main_input_name] ?? e.attention_mask)?.dims?.[0] ?? 1, o = cs2(t6.config), i = t6.config?.normalized_config?.num_heads, a = { batch_size: n };
    typeof i == "number" && (a["batch_size x num_heads"] = n * i);
    let l = /* @__PURE__ */ Object.create(null);
    for (let c of r.inputMetadata) {
      if (!o.has(c.name)) continue;
      let p = Y_(c.shape, a), u = p.reduce((m, f) => m * f, 1), _ = Lt2[c.type], d = new E(c.type, new _(u), p);
      e[c.name] = d, l[c.name] = d;
    }
    return s ? (s.update(l), s) : new Qs(l);
  }
  async function Ve2(t6, e, s = false) {
    let r = t6.sessions[s ? "decoder_model_merged" : "model"], { past_key_values: n, ...o } = e;
    if (r.inputNames.includes("use_cache_branch") && (o.use_cache_branch = Q_(n != null && Object.keys(n).length > 0)), r.inputNames.includes("position_ids") && o.attention_mask && !o.position_ids) {
      let a = ["paligemma", "gemma3_text", "gemma3"].includes(t6.config.model_type) ? 1 : 0;
      o.position_ids = fM(o, n, a);
    }
    r.inputNames.includes("num_logits_to_keep") && !o.num_logits_to_keep && (o.num_logits_to_keep = new E("int64", [0n], [])), cn2(t6, o, n);
    let i = we(o, r.inputNames);
    return await X(r, i);
  }
  async function Nb(t6, { encode_function: e, merge_function: s, modality_input_names: r, modality_output_name: n, input_ids: o = null, attention_mask: i = null, position_ids: a = null, inputs_embeds: l = null, past_key_values: c = null, generation_config: p = null, logits_processor: u = null, ..._ }) {
    if (!l) {
      l = await t6.encode_text({ input_ids: o, ..._ });
      let m = we(_, r);
      if (Object.keys(m).length > 0) {
        if (o.dims[1] !== 1) {
          let f = await e({ ...m, ..._ });
          ({ inputs_embeds: l, attention_mask: i } = s({ [n]: f, inputs_embeds: l, input_ids: o, attention_mask: i }));
        } else if (c && o.dims[1] === 1) {
          let f = o.dims[1], g = c.get_seq_length();
          i = ie2([Me([o.dims[0], g]), i.slice(null, [i.dims[1] - f, i.dims[1]])], 1);
        }
      }
    }
    if (!a && ["qwen2_vl", "qwen2_vl_text", "qwen2_5_vl", "qwen2_5_vl_text", "qwen3_vl", "qwen3_vl_text", "qwen3_vl_moe", "qwen3_vl_moe_text", "qwen3_5", "qwen3_5_text", "qwen3_5_moe", "qwen3_5_moe_text", "glm_ocr", "glm_ocr_text"].includes(t6.config.model_type)) {
      let { image_grid_thw: m, video_grid_thw: f } = _;
      [a] = t6.get_rope_index(o, m, f, i);
    }
    return await Ve2(t6, { inputs_embeds: l, past_key_values: c, attention_mask: i, position_ids: a, generation_config: p, logits_processor: u }, true);
  }
  async function _M(t6, e) {
    return await Nb(t6, { ...e, modality_input_names: ["audio_values", "input_features"], modality_output_name: "audio_features", encode_function: t6.encode_audio.bind(t6), merge_function: t6._merge_input_ids_with_audio_features.bind(t6) });
  }
  async function dM(t6, e) {
    return await Nb(t6, { ...e, modality_input_names: ["pixel_values"], modality_output_name: "image_features", encode_function: t6.encode_image.bind(t6), merge_function: t6._merge_input_ids_with_image_features.bind(t6) });
  }
  function J_(t6, e = 0) {
    let [s, r] = t6.dims, n = t6.data, o = new BigInt64Array(n.length);
    for (let i = 0; i < s; ++i) {
      let a = i * r, l = BigInt(e);
      for (let c = 0; c < r; ++c) {
        let p = a + c;
        n[p] === 0n ? o[p] = BigInt(1) : (o[p] = l, l += n[p]);
      }
    }
    return { data: o, dims: t6.dims };
  }
  function fM(t6, e = null, s = 0) {
    let { input_ids: r, inputs_embeds: n, attention_mask: o } = t6, { data: i, dims: a } = J_(o, s), l = new E("int64", i, a);
    if (e) {
      let c = -(r ?? n).dims.at(1);
      l = l.slice(null, [c, null]);
    }
    return l;
  }
  function Zs(t6, e, s, r) {
    let n = s.past_key_values ? s.past_key_values.get_seq_length() : 0;
    if ((t6.sessions.decoder_model_merged ?? t6.sessions.model)?.inputNames.includes("num_logits_to_keep") && !s.num_logits_to_keep && (s.num_logits_to_keep = new E("int64", [1n], [])), !s.attention_mask) {
      let i;
      for (let a of ["input_ids", "inputs_embeds", "position_ids"]) if (s[a]) {
        i = s[a].dims;
        break;
      }
      if (!i) throw new Error("attention_mask is not provided, and unable to infer its shape from model inputs.");
      s.attention_mask = Me([i[0], n + i[1]]);
    }
    if (s.past_key_values) {
      let { input_ids: i, attention_mask: a } = s;
      a && a.dims[1] > i.dims[1] || n < i.dims[1] && (s.input_ids = i.slice(null, [n, null]));
    }
    return s;
  }
  function ln2(t6, e, s, r) {
    return s.past_key_values && (e = e.map((n) => [n.at(-1)])), { ...s, decoder_input_ids: X_(e) };
  }
  function hl(t6, ...e) {
    return t6.config.is_encoder_decoder ? ln2(t6, ...e) : Zs(t6, ...e);
  }
  function Lb({ modality_token_id: t6, inputs_embeds: e, modality_features: s, input_ids: r, attention_mask: n }) {
    let o = r.tolist().map((c) => c.reduce((p, u, _) => (u == t6 && p.push(_), p), [])), i = o.reduce((c, p) => c + p.length, 0), a = s.dims[0];
    if (i !== a) throw new Error(`Number of tokens and features do not match: tokens: ${i}, features ${a}`);
    let l = 0;
    for (let c = 0; c < o.length; ++c) {
      let p = o[c], u = e[c];
      for (let _ = 0; _ < p.length; ++_) u[p[_]].data.set(s[l++].data);
    }
    return { inputs_embeds: e, attention_mask: n };
  }
  function er2({ image_token_id: t6, inputs_embeds: e, image_features: s, input_ids: r, attention_mask: n }) {
    return Lb({ modality_token_id: t6, inputs_embeds: e, modality_features: s, input_ids: r, attention_mask: n });
  }
  function wl({ audio_token_id: t6, inputs_embeds: e, audio_features: s, input_ids: r, attention_mask: n }) {
    return Lb({ modality_token_id: t6, inputs_embeds: e, modality_features: s, input_ids: r, attention_mask: n });
  }
  async function mM(t6, e, s) {
    return Object.fromEntries(await Promise.all(Object.keys(e).map(async (r) => {
      let n = await Ie(t6, e[r], false, s);
      return [r, n];
    })));
  }
  var Si = {};
  Os2(Si, { ASTForAudioClassification: () => pd, ASTModel: () => cd, ASTPreTrainedModel: () => dn2, AfmoeForCausalLM: () => id, AfmoeModel: () => od, AfmoePreTrainedModel: () => un2, AlbertForMaskedLM: () => sd, AlbertForQuestionAnswering: () => td, AlbertForSequenceClassification: () => ed, AlbertModel: () => Z_, AlbertPreTrainedModel: () => fs2, ApertusForCausalLM: () => nd, ApertusModel: () => rd, ApertusPreTrainedModel: () => pn2, ArceeForCausalLM: () => ld, ArceeModel: () => ad, ArceePreTrainedModel: () => _n, BartForConditionalGeneration: () => _d, BartForSequenceClassification: () => dd, BartModel: () => ud, BartPretrainedModel: () => tr2, BeitForImageClassification: () => md, BeitModel: () => fd, BeitPreTrainedModel: () => fn2, BertForMaskedLM: () => gd, BertForQuestionAnswering: () => yd, BertForSequenceClassification: () => xd, BertForTokenClassification: () => wd, BertModel: () => hd, BertPreTrainedModel: () => qt2, BlenderbotForConditionalGeneration: () => kd, BlenderbotModel: () => bd, BlenderbotPreTrainedModel: () => mn2, BlenderbotSmallForConditionalGeneration: () => Ed, BlenderbotSmallModel: () => vd, BlenderbotSmallPreTrainedModel: () => hn, BloomForCausalLM: () => Md, BloomModel: () => Ad, BloomPreTrainedModel: () => gn, CHMv2ForDepthEstimation: () => Pd, CHMv2PreTrainedModel: () => kl, CLIPModel: () => Ld, CLIPPreTrainedModel: () => xt2, CLIPSegForImageSegmentation: () => qd, CLIPSegModel: () => Dd, CLIPSegPreTrainedModel: () => kn, CLIPTextModel: () => $d, CLIPTextModelWithProjection: () => bn, CLIPVisionModel: () => Fd, CLIPVisionModelWithProjection: () => Rd, CamembertForMaskedLM: () => Od, CamembertForQuestionAnswering: () => Td, CamembertForSequenceClassification: () => Id, CamembertForTokenClassification: () => zd, CamembertModel: () => Sd, CamembertPreTrainedModel: () => jt2, ChatterboxModel: () => xn, ChatterboxPreTrainedModel: () => yl, ChineseCLIPModel: () => Cd, ChineseCLIPPreTrainedModel: () => bl, ClapAudioModelWithProjection: () => yn, ClapModel: () => Nd, ClapPreTrainedModel: () => sr2, ClapTextModelWithProjection: () => wn, CodeGenForCausalLM: () => Bd, CodeGenModel: () => jd, CodeGenPreTrainedModel: () => vn, Cohere2ForCausalLM: () => Vd, Cohere2Model: () => Wd, Cohere2PreTrainedModel: () => An, CohereAsrForConditionalGeneration: () => Kd, CohereAsrModel: () => Hd, CohereAsrPreTrainedModel: () => Mn, CohereForCausalLM: () => Gd, CohereModel: () => Ud, CoherePreTrainedModel: () => En, ConvBertForMaskedLM: () => Qd, ConvBertForQuestionAnswering: () => Zd, ConvBertForSequenceClassification: () => Yd, ConvBertForTokenClassification: () => Jd, ConvBertModel: () => Xd, ConvBertPreTrainedModel: () => Bt2, ConvNextForImageClassification: () => tf, ConvNextModel: () => ef, ConvNextPreTrainedModel: () => Sn, ConvNextV2ForImageClassification: () => rf, ConvNextV2Model: () => sf, ConvNextV2PreTrainedModel: () => On, DFineForObjectDetection: () => lf, DFineModel: () => af, DFinePreTrainedModel: () => zn, DINOv3ConvNextModel: () => Nf, DINOv3ConvNextPreTrainedModel: () => Il, DINOv3ViTModel: () => Lf, DINOv3ViTPreTrainedModel: () => zl, DPTForDepthEstimation: () => Uf, DPTModel: () => Bf, DPTPreTrainedModel: () => Fn, DacDecoderModel: () => Cn, DacDecoderOutput: () => El, DacEncoderModel: () => Tn, DacEncoderOutput: () => vl, DacModel: () => cf, DacPreTrainedModel: () => rr2, DebertaForMaskedLM: () => uf, DebertaForQuestionAnswering: () => ff, DebertaForSequenceClassification: () => _f, DebertaForTokenClassification: () => df, DebertaModel: () => pf, DebertaPreTrainedModel: () => Ut, DebertaV2ForMaskedLM: () => xf, DebertaV2ForQuestionAnswering: () => bf, DebertaV2ForSequenceClassification: () => wf, DebertaV2ForTokenClassification: () => yf, DebertaV2Model: () => gf, DebertaV2PreTrainedModel: () => Gt, DecisionTransformerModel: () => kf, DecisionTransformerPreTrainedModel: () => Al, DeepseekV3ForCausalLM: () => hf, DeepseekV3Model: () => mf, DeepseekV3PreTrainedModel: () => Pn, DeiTForImageClassification: () => Ef, DeiTModel: () => vf, DeiTPreTrainedModel: () => Nn, DepthAnythingForDepthEstimation: () => Af, DepthAnythingPreTrainedModel: () => Ml, DepthProForDepthEstimation: () => Mf, DepthProPreTrainedModel: () => Sl, DetrForObjectDetection: () => Of, DetrForSegmentation: () => If, DetrModel: () => Sf, DetrObjectDetectionOutput: () => or2, DetrPreTrainedModel: () => nr2, DetrSegmentationOutput: () => Ol, Dinov2ForImageClassification: () => Tf, Dinov2Model: () => zf2, Dinov2PreTrainedModel: () => Ln, Dinov2WithRegistersForImageClassification: () => Pf, Dinov2WithRegistersModel: () => Cf, Dinov2WithRegistersPreTrainedModel: () => $n, DistilBertForMaskedLM: () => qf2, DistilBertForQuestionAnswering: () => Df, DistilBertForSequenceClassification: () => Ff, DistilBertForTokenClassification: () => Rf, DistilBertModel: () => $f, DistilBertPreTrainedModel: () => Wt, DonutSwinModel: () => jf2, DonutSwinPreTrainedModel: () => Tl, EdgeTamModel: () => ew, EfficientNetForImageClassification: () => Wf, EfficientNetModel: () => Gf, EfficientNetPreTrainedModel: () => Rn, ElectraForMaskedLM: () => Hf2, ElectraForQuestionAnswering: () => Qf2, ElectraForSequenceClassification: () => Kf2, ElectraForTokenClassification: () => Xf2, ElectraModel: () => Vf2, ElectraPreTrainedModel: () => Vt2, Ernie4_5ForCausalLM: () => Jf2, Ernie4_5Model: () => Yf2, Ernie4_5PretrainedModel: () => Dn, EsmForMaskedLM: () => em, EsmForSequenceClassification: () => tm, EsmForTokenClassification: () => sm, EsmModel: () => Zf2, EsmPreTrainedModel: () => ms2, EuroBertForMaskedLM: () => nm, EuroBertForSequenceClassification: () => om, EuroBertForTokenClassification: () => im, EuroBertModel: () => rm, EuroBertPreTrainedModel: () => hs2, ExaoneForCausalLM: () => lm, ExaoneModel: () => am, ExaonePreTrainedModel: () => qn, FalconForCausalLM: () => pm, FalconH1ForCausalLM: () => _m, FalconH1Model: () => um, FalconH1PreTrainedModel: () => Bn, FalconModel: () => cm, FalconPreTrainedModel: () => jn, FastViTForImageClassification: () => fm, FastViTModel: () => dm, FastViTPreTrainedModel: () => Un, Florence2ForConditionalGeneration: () => mm, Florence2PreTrainedModel: () => Cl, GLPNForDepthEstimation: () => Cm, GLPNModel: () => Tm, GLPNPreTrainedModel: () => Qn, GPT2LMHeadModel: () => Bm, GPT2Model: () => jm, GPT2PreTrainedModel: () => to, GPTBigCodeForCausalLM: () => Nm, GPTBigCodeModel: () => Pm, GPTBigCodePreTrainedModel: () => Yn, GPTJForCausalLM: () => Gm, GPTJModel: () => Um, GPTJPreTrainedModel: () => so, GPTNeoForCausalLM: () => $m, GPTNeoModel: () => Lm, GPTNeoPreTrainedModel: () => Jn, GPTNeoXForCausalLM: () => Rm, GPTNeoXModel: () => Fm, GPTNeoXPreTrainedModel: () => Zn, Gemma2ForCausalLM: () => wm, Gemma2Model: () => xm, Gemma2PreTrainedModel: () => Wn, Gemma3ForCausalLM: () => vm, Gemma3ForConditionalGeneration: () => Ll, Gemma3Model: () => km, Gemma3PreTrainedModel: () => Nl, Gemma3nForCausalLM: () => Em, Gemma3nForConditionalGeneration: () => Ht2, Gemma3nPreTrainedModel: () => $l, Gemma4ForCausalLM: () => Am, Gemma4ForConditionalGeneration: () => ir2, GemmaForCausalLM: () => gm, GemmaModel: () => hm, GemmaPreTrainedModel: () => Gn, GlmForCausalLM: () => Sm, GlmModel: () => Mm, GlmMoeDsaForCausalLM: () => Im, GlmMoeDsaModel: () => Om, GlmMoeDsaPreTrainedModel: () => Hn, GlmOcrForConditionalGeneration: () => zm, GlmPreTrainedModel: () => Vn, GptOssForCausalLM: () => qm, GptOssModel: () => Dm, GptOssPreTrainedModel: () => eo, GraniteForCausalLM: () => Vm, GraniteModel: () => Wm, GraniteMoeHybridForCausalLM: () => Km, GraniteMoeHybridModel: () => Hm, GraniteMoeHybridPreTrainedModel: () => no, GranitePreTrainedModel: () => ro, GraniteSpeechForConditionalGeneration: () => Xm, GroundingDinoForObjectDetection: () => Qm, GroundingDinoPreTrainedModel: () => Dl, GroupViTModel: () => Ym, GroupViTPreTrainedModel: () => ql, HeliumForCausalLM: () => Zm, HeliumModel: () => Jm, HeliumPreTrainedModel: () => oo, HieraForImageClassification: () => th, HieraModel: () => eh, HieraPreTrainedModel: () => io, HubertForCTC: () => lh, HubertForSequenceClassification: () => ch, HubertModel: () => ah, HubertPreTrainedModel: () => ih, HunYuanDenseV1ForCausalLM: () => uh, HunYuanDenseV1Model: () => ph, HunYuanDenseV1PreTrainedModel: () => ao, IJepaForImageClassification: () => dh, IJepaModel: () => _h, IJepaPreTrainedModel: () => co, Idefics3ForConditionalGeneration: () => lo, JAISLMHeadModel: () => mh, JAISModel: () => fh, JAISPreTrainedModel: () => po, JinaCLIPModel: () => hh, JinaCLIPPreTrainedModel: () => lr2, JinaCLIPTextModel: () => uo, JinaCLIPVisionModel: () => gh, Lfm2ForCausalLM: () => wh, Lfm2Model: () => xh, Lfm2MoeForCausalLM: () => kh, Lfm2MoeModel: () => bh, Lfm2MoePreTrainedModel: () => fo, Lfm2PreTrainedModel: () => _o, Lfm2VlForConditionalGeneration: () => vh, LightOnOcrForConditionalGeneration: () => yh, LiteWhisperForConditionalGeneration: () => hy, Llama4ForCausalLM: () => Mh, Llama4PreTrainedModel: () => jl, LlamaForCausalLM: () => Ah, LlamaModel: () => Eh, LlamaPreTrainedModel: () => mo, LlavaForConditionalGeneration: () => Ue, LlavaOnevisionForConditionalGeneration: () => Ue, LlavaPreTrainedModel: () => Pl, LlavaQwen2ForCausalLM: () => bm, LongT5ForConditionalGeneration: () => Oh, LongT5Model: () => Sh, LongT5PreTrainedModel: () => ho, M2M100ForConditionalGeneration: () => zh, M2M100Model: () => Ih, M2M100PreTrainedModel: () => go, MBartForCausalLM: () => Rh, MBartForConditionalGeneration: () => $h, MBartForSequenceClassification: () => Fh, MBartModel: () => Lh, MBartPreTrainedModel: () => ws2, MPNetForMaskedLM: () => Eg, MPNetForQuestionAnswering: () => Sg, MPNetForSequenceClassification: () => Ag, MPNetForTokenClassification: () => Mg, MPNetModel: () => vg, MPNetPreTrainedModel: () => Kt2, MT5ForConditionalGeneration: () => Tg, MT5Model: () => zg, MT5PreTrainedModel: () => zo, MarianMTModel: () => Ch, MarianModel: () => Th, MarianPreTrainedModel: () => xo, MaskFormerForInstanceSegmentation: () => Nh, MaskFormerModel: () => Ph, MaskFormerPreTrainedModel: () => wo, Metric3DForDepthEstimation: () => Dh, Metric3DPreTrainedModel: () => Bl, Metric3Dv2ForDepthEstimation: () => qh, Metric3Dv2PreTrainedModel: () => Ul, MgpstrForSceneTextRecognition: () => jh, MgpstrModelOutput: () => Gl, MgpstrPreTrainedModel: () => Wl, MimiDecoderModel: () => bo, MimiDecoderOutput: () => Hl, MimiEncoderModel: () => yo, MimiEncoderOutput: () => Vl, MimiModel: () => Bh, MimiPreTrainedModel: () => cr2, Mistral4ForCausalLM: () => Vh, Mistral4Model: () => Wh, Mistral4PreTrainedModel: () => vo, MistralForCausalLM: () => Gh, MistralModel: () => Uh, MistralPreTrainedModel: () => ko, MobileBertForMaskedLM: () => Kh, MobileBertForQuestionAnswering: () => Qh, MobileBertForSequenceClassification: () => Xh, MobileBertModel: () => Hh, MobileBertPreTrainedModel: () => ys2, MobileLLMForCausalLM: () => Jh, MobileLLMModel: () => Yh, MobileLLMPreTrainedModel: () => Eo, MobileNetV1ForImageClassification: () => eg, MobileNetV1ForSemanticSegmentation: () => tg, MobileNetV1Model: () => Zh, MobileNetV1PreTrainedModel: () => pr2, MobileNetV2ForImageClassification: () => rg, MobileNetV2ForSemanticSegmentation: () => ng, MobileNetV2Model: () => sg, MobileNetV2PreTrainedModel: () => ur2, MobileNetV3ForImageClassification: () => ig, MobileNetV3ForSemanticSegmentation: () => ag, MobileNetV3Model: () => og, MobileNetV3PreTrainedModel: () => _r, MobileNetV4ForImageClassification: () => cg, MobileNetV4ForSemanticSegmentation: () => pg, MobileNetV4Model: () => lg, MobileNetV4PreTrainedModel: () => dr2, MobileViTForImageClassification: () => _g, MobileViTModel: () => ug, MobileViTPreTrainedModel: () => Ao, MobileViTV2ForImageClassification: () => fg, MobileViTV2Model: () => dg, MobileViTV2PreTrainedModel: () => Mo, ModernBertDecoderForCausalLM: () => yg, ModernBertDecoderModel: () => wg, ModernBertDecoderPreTrainedModel: () => So, ModernBertForMaskedLM: () => hg, ModernBertForSequenceClassification: () => gg, ModernBertForTokenClassification: () => xg, ModernBertModel: () => mg, ModernBertPreTrainedModel: () => bs2, Moondream1ForConditionalGeneration: () => ym, MoonshineForConditionalGeneration: () => kg, MoonshineModel: () => bg, MoonshinePreTrainedModel: () => Oo, MptForCausalLM: () => Ig, MptModel: () => Og, MptPreTrainedModel: () => Io, MultiModalityCausalLM: () => Cg, MultiModalityPreTrainedModel: () => Kl, MusicgenForCausalLM: () => Ng, MusicgenForConditionalGeneration: () => Co, MusicgenModel: () => Pg, MusicgenPreTrainedModel: () => To, NanoChatForCausalLM: () => $g, NanoChatModel: () => Lg, NanoChatPreTrainedModel: () => Po, NemotronHForCausalLM: () => Rg, NemotronHModel: () => Fg, NemotronHPreTrainedModel: () => No, NeoBertForMaskedLM: () => qg, NeoBertForQuestionAnswering: () => Ug, NeoBertForSequenceClassification: () => jg, NeoBertForTokenClassification: () => Bg, NeoBertModel: () => Dg, NeoBertPreTrainedModel: () => Xt2, NomicBertModel: () => Gg, NomicBertPreTrainedModel: () => Xl, OPTForCausalLM: () => nx, OPTModel: () => rx, OPTPreTrainedModel: () => jo, Olmo2ForCausalLM: () => Kg, Olmo2Model: () => Hg, Olmo2PreTrainedModel: () => $o, Olmo3ForCausalLM: () => Qg, Olmo3Model: () => Xg, Olmo3PreTrainedModel: () => Fo, OlmoForCausalLM: () => Vg, OlmoHybridForCausalLM: () => Jg, OlmoHybridModel: () => Yg, OlmoHybridPreTrainedModel: () => Ro, OlmoModel: () => Wg, OlmoPreTrainedModel: () => Lo, OpenAIPrivacyFilterForTokenClassification: () => ex, OpenAIPrivacyFilterModel: () => Zg, OpenAIPrivacyFilterPreTrainedModel: () => Do, OpenELMForCausalLM: () => sx, OpenELMModel: () => tx, OpenELMPreTrainedModel: () => qo, OwlViTForObjectDetection: () => lx, OwlViTModel: () => ax, OwlViTPreTrainedModel: () => Uo, Owlv2ForObjectDetection: () => ix, Owlv2Model: () => ox, Owlv2PreTrainedModel: () => Bo, PaliGemmaForConditionalGeneration: () => cx, ParakeetForCTC: () => px, ParakeetPreTrainedModel: () => Ql, PatchTSMixerForPrediction: () => _x, PatchTSMixerModel: () => ux, PatchTSMixerPreTrainedModel: () => Go, PatchTSTForPrediction: () => fx, PatchTSTModel: () => dx, PatchTSTPreTrainedModel: () => Wo, Phi3ForCausalLM: () => xx, Phi3Model: () => gx, Phi3PreTrainedModel: () => Ho, Phi3VForCausalLM: () => Ko, Phi3VPreTrainedModel: () => Yl, PhiForCausalLM: () => hx, PhiModel: () => mx, PhiPreTrainedModel: () => Vo, PreTrainedModel: () => h, PvtForImageClassification: () => yx, PvtModel: () => wx, PvtPreTrainedModel: () => Xo, PyAnnoteForAudioFrameClassification: () => kx, PyAnnoteModel: () => bx, PyAnnotePreTrainedModel: () => Qo, Qwen2ForCausalLM: () => Ex, Qwen2Model: () => vx, Qwen2MoeForCausalLM: () => Mx, Qwen2MoeModel: () => Ax, Qwen2MoePreTrainedModel: () => Jo, Qwen2PreTrainedModel: () => Yo, Qwen2VLForCausalLM: () => Kn, Qwen2VLForConditionalGeneration: () => ar2, Qwen2VLPreTrainedModel: () => Fl, Qwen2_5_VLForCausalLM: () => Xn, Qwen2_5_VLForConditionalGeneration: () => gs2, Qwen3ForCausalLM: () => Ox, Qwen3Model: () => Sx, Qwen3MoeForCausalLM: () => zx, Qwen3MoeModel: () => Ix, Qwen3MoePreTrainedModel: () => ei, Qwen3NextForCausalLM: () => Cx, Qwen3NextModel: () => Tx, Qwen3NextPreTrainedModel: () => ti, Qwen3PreTrainedModel: () => Zo, Qwen3VLForCausalLM: () => si, Qwen3VLForConditionalGeneration: () => ks2, Qwen3VLMoeForCausalLM: () => Nx, Qwen3VLMoeForConditionalGeneration: () => Px, Qwen3_5ForCausalLM: () => ri, Qwen3_5ForConditionalGeneration: () => fr2, Qwen3_5MoeForCausalLM: () => $x, Qwen3_5MoeForConditionalGeneration: () => Lx, RFDetrForObjectDetection: () => qx, RFDetrModel: () => Dx, RFDetrObjectDetectionOutput: () => Jl, RFDetrPreTrainedModel: () => oi, RTDetrForObjectDetection: () => of, RTDetrModel: () => nf, RTDetrObjectDetectionOutput: () => wt, RTDetrPreTrainedModel: () => In, RTDetrV2ForObjectDetection: () => Jx, RTDetrV2Model: () => Yx, RTDetrV2ObjectDetectionOutput: () => Zl, RTDetrV2PreTrainedModel: () => ii, ResNetForImageClassification: () => Rx, ResNetModel: () => Fx, ResNetPreTrainedModel: () => ni, RoFormerForMaskedLM: () => Hx, RoFormerForQuestionAnswering: () => Qx, RoFormerForSequenceClassification: () => Kx, RoFormerForTokenClassification: () => Xx, RoFormerModel: () => Vx, RoFormerPreTrainedModel: () => Yt2, RobertaForMaskedLM: () => Bx, RobertaForQuestionAnswering: () => Wx, RobertaForSequenceClassification: () => Ux, RobertaForTokenClassification: () => Gx, RobertaModel: () => jx, RobertaPreTrainedModel: () => Qt2, Sam2ImageSegmentationOutput: () => sc2, Sam2Model: () => ai, Sam2PreTrainedModel: () => rc2, Sam3TrackerModel: () => tw, SamImageSegmentationOutput: () => ec2, SamModel: () => Zx, SamPreTrainedModel: () => tc2, SapiensForDepthEstimation: () => rw, SapiensForNormalEstimation: () => nw, SapiensForSemanticSegmentation: () => sw, SapiensPreTrainedModel: () => mr2, SegformerForImageClassification: () => iw, SegformerForSemanticSegmentation: () => aw, SegformerModel: () => ow, SegformerPreTrainedModel: () => hr, SiglipModel: () => lw, SiglipPreTrainedModel: () => li, SiglipTextModel: () => ci, SiglipVisionModel: () => cw, SmolLM3ForCausalLM: () => uw, SmolLM3Model: () => pw, SmolLM3PreTrainedModel: () => pi, SmolVLMForConditionalGeneration: () => _w, SnacDecoderModel: () => _i, SnacEncoderModel: () => ui, SnacModel: () => dw, SnacPreTrainedModel: () => gr, SolarOpenForCausalLM: () => mw, SolarOpenModel: () => fw, SolarOpenPreTrainedModel: () => di, SpeechT5ForSpeechToText: () => gw, SpeechT5ForTextToSpeech: () => xw, SpeechT5HifiGan: () => ww, SpeechT5Model: () => hw, SpeechT5PreTrainedModel: () => xr, SqueezeBertForMaskedLM: () => bw, SqueezeBertForQuestionAnswering: () => vw, SqueezeBertForSequenceClassification: () => kw, SqueezeBertModel: () => yw, SqueezeBertPreTrainedModel: () => vs2, StableLmForCausalLM: () => Aw, StableLmModel: () => Ew, StableLmPreTrainedModel: () => fi, Starcoder2ForCausalLM: () => Sw, Starcoder2Model: () => Mw, Starcoder2PreTrainedModel: () => mi, StyleTextToSpeech2Model: () => Ow, StyleTextToSpeech2PreTrainedModel: () => nc2, SupertonicForConditionalGeneration: () => hi, SupertonicPreTrainedModel: () => oc2, Swin2SRForImageSuperResolution: () => Pw, Swin2SRModel: () => Cw, Swin2SRPreTrainedModel: () => gi, SwinForImageClassification: () => zw, SwinForSemanticSegmentation: () => Tw, SwinModel: () => Iw, SwinPreTrainedModel: () => wr, T5ForConditionalGeneration: () => Lw, T5Model: () => Nw, T5PreTrainedModel: () => xi, TableTransformerForObjectDetection: () => Fw, TableTransformerModel: () => $w, TableTransformerObjectDetectionOutput: () => ic2, TableTransformerPreTrainedModel: () => wi, TrOCRForCausalLM: () => Rw, TrOCRPreTrainedModel: () => ac2, UltravoxModel: () => xs2, UltravoxPreTrainedModel: () => Rl, UniSpeechForCTC: () => qw, UniSpeechForSequenceClassification: () => jw, UniSpeechModel: () => Dw, UniSpeechPreTrainedModel: () => yr, UniSpeechSatForAudioFrameClassification: () => Ww, UniSpeechSatForCTC: () => Uw, UniSpeechSatForSequenceClassification: () => Gw, UniSpeechSatModel: () => Bw, UniSpeechSatPreTrainedModel: () => Es2, VaultGemmaForCausalLM: () => Hw, VaultGemmaModel: () => Vw, VaultGemmaPreTrainedModel: () => yi, ViTForImageClassification: () => Qw, ViTMAEModel: () => Yw, ViTMAEPreTrainedModel: () => lc2, ViTMSNForImageClassification: () => Zw, ViTMSNModel: () => Jw, ViTMSNPreTrainedModel: () => ki, ViTModel: () => Xw, ViTPreTrainedModel: () => bi, VisionEncoderDecoderModel: () => Kw, VitMatteForImageMatting: () => ey, VitMattePreTrainedModel: () => cc2, VitPoseForPoseEstimation: () => ty, VitPosePreTrainedModel: () => pc2, VitsModel: () => sy, VitsModelOutput: () => uc2, VitsPreTrainedModel: () => _c, VoxtralForConditionalGeneration: () => ry, VoxtralRealtimeForConditionalGeneration: () => vi, VoxtralRealtimePreTrainedModel: () => dc2, Wav2Vec2BertForCTC: () => ay, Wav2Vec2BertForSequenceClassification: () => ly, Wav2Vec2BertModel: () => iy, Wav2Vec2BertPreTrainedModel: () => br, Wav2Vec2ForAudioFrameClassification: () => oh, Wav2Vec2ForCTC: () => rh, Wav2Vec2ForSequenceClassification: () => nh, Wav2Vec2Model: () => sh, Wav2Vec2PreTrainedModel: () => pt, WavLMForAudioFrameClassification: () => dy, WavLMForCTC: () => py, WavLMForSequenceClassification: () => uy, WavLMForXVector: () => _y, WavLMModel: () => cy, WavLMPreTrainedModel: () => Jt2, WeSpeakerResNetModel: () => fy, WeSpeakerResNetPreTrainedModel: () => mc2, WhisperForConditionalGeneration: () => gc2, WhisperModel: () => my, WhisperPreTrainedModel: () => Ei, XLMForQuestionAnswering: () => by, XLMForSequenceClassification: () => wy, XLMForTokenClassification: () => yy, XLMModel: () => gy, XLMPreTrainedModel: () => Zt2, XLMRobertaForMaskedLM: () => vy, XLMRobertaForQuestionAnswering: () => My, XLMRobertaForSequenceClassification: () => Ey, XLMRobertaForTokenClassification: () => Ay, XLMRobertaModel: () => ky, XLMRobertaPreTrainedModel: () => es2, XLMWithLMHeadModel: () => xy, XVectorOutput: () => fc2, YolosForObjectDetection: () => Oy, YolosModel: () => Sy, YolosObjectDetectionOutput: () => xc, YolosPreTrainedModel: () => Ai, YoutuForCausalLM: () => zy, YoutuModel: () => Iy, YoutuPreTrainedModel: () => Mi });
  var fs2 = class extends h {
  };
  var Z_ = class extends fs2 {
  };
  var ed = class extends fs2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var td = class extends fs2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var sd = class extends fs2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var pn2 = class extends h {
  };
  var rd = class extends pn2 {
  };
  var nd = class extends pn2 {
  };
  var un2 = class extends h {
  };
  var od = class extends un2 {
  };
  var id = class extends un2 {
  };
  var _n = class extends h {
  };
  var ad = class extends _n {
  };
  var ld = class extends _n {
  };
  var dn2 = class extends h {
  };
  var cd = class extends dn2 {
  };
  var pd = class extends dn2 {
  };
  var tr2 = class extends h {
  };
  var ud = class extends tr2 {
  };
  var _d = class extends tr2 {
  };
  var dd = class extends tr2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var fn2 = class extends h {
  };
  var fd = class extends fn2 {
  };
  var md = class extends fn2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var qt2 = class extends h {
  };
  var hd = class extends qt2 {
  };
  var gd = class extends qt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var xd = class extends qt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var wd = class extends qt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var yd = class extends qt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var mn2 = class extends h {
  };
  var bd = class extends mn2 {
  };
  var kd = class extends mn2 {
  };
  var hn = class extends h {
  };
  var vd = class extends hn {
  };
  var Ed = class extends hn {
  };
  var gn = class extends h {
  };
  var Ad = class extends gn {
  };
  var Md = class extends gn {
  };
  var jt2 = class extends h {
  };
  var Sd = class extends jt2 {
  };
  var Od = class extends jt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Id = class extends jt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var zd = class extends jt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Td = class extends jt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var hM = 4299n;
  var $b = 6561n;
  var yl = class extends h {
    forward_params = ["input_ids", "inputs_embeds", "attention_mask", "position_ids", "audio_values", "exaggeration", "audio_features", "audio_tokens", "speaker_embeddings", "speaker_features", "past_key_values"];
    main_input_name = "input_ids";
    _return_dict_in_generate_keys = ["audio_tokens", "speaker_embeddings", "speaker_features"];
  };
  var xn = class extends yl {
    async encode_speech(e) {
      return X(this.sessions.speech_encoder, { audio_values: e });
    }
    async forward({ input_ids: e = null, attention_mask: s = null, audio_values: r = null, exaggeration: n = null, position_ids: o = null, inputs_embeds: i = null, past_key_values: a = null, generation_config: l = null, logits_processor: c = null, audio_features: p = null, audio_tokens: u = null, speaker_embeddings: _ = null, speaker_features: d = null, ...m }) {
      let f;
      if (!i) {
        let w = this.sessions.embed_tokens.inputNames, x = { input_ids: e };
        if (w.includes("exaggeration")) {
          if (!(n instanceof E)) {
            let y = e.dims[0];
            if (n == null) n = ve([y], 0.5);
            else if (typeof n == "number") n = ve([y], n);
            else if (Array.isArray(n)) n = new E("float32", n, [y]);
            else throw new Error("Unsupported type for `exaggeration` input");
          }
          x.exaggeration = n;
        }
        if (w.includes("position_ids") && (x.position_ids = o), { inputs_embeds: i } = await X(this.sessions.embed_tokens, x), p && u && _ && d && (f = { audio_features: p, audio_tokens: u, speaker_embeddings: _, speaker_features: d }), f || r) f ??= await this.encode_speech(r), i = ie2([f.audio_features, i], 1), s = Me([i.dims[0], i.dims[1]]);
        else {
          let y = i.dims[1];
          if (!a || y !== 1) throw new Error("Incorrect state encountered during generation.");
          let b = a.get_seq_length();
          s = Me([i.dims[0], b + y]);
        }
      }
      return { ...await Ve2(this, { inputs_embeds: i, past_key_values: a, attention_mask: s, generation_config: l, logits_processor: c }, false), ...f };
    }
    prepare_inputs_for_generation(e, s, r) {
      if (!s.position_ids && this.sessions.embed_tokens.inputNames.includes("position_ids")) if (s.input_ids.dims[1] === 1) {
        let n = Array.from({ length: e.length }, (o, i) => e[i].length - e[i].findLastIndex((a) => a == $b) - 1);
        s.position_ids = new E("int64", n, [e.length, 1]);
      } else {
        let o = s.input_ids.tolist().map((i) => {
          let a = 0;
          return i.map((l) => l >= $b ? 0 : a++);
        });
        s.position_ids = new E("int64", o.flat(), s.input_ids.dims);
      }
      return s.input_ids.dims[1] === 1 && (delete s.audio_values, delete s.audio_features, delete s.audio_tokens, delete s.speaker_embeddings, delete s.speaker_features), Zs(this, e, s, r);
    }
    async generate(e) {
      let { sequences: s, audio_tokens: r, speaker_embeddings: n, speaker_features: o } = await super.generate({ ...e, return_dict_in_generate: true }), i = s.slice(null, [e.input_ids.dims[1], -1]), a = ve([i.dims[0], 3], hM), l = ie2([r, i, a], 1), { waveform: c } = await X(this.sessions.conditional_decoder, { speech_tokens: l, speaker_features: o, speaker_embeddings: n });
      return c;
    }
  };
  var bl = class extends h {
  };
  var Cd = class extends bl {
  };
  var kl = class extends h {
  };
  var Pd = class extends kl {
  };
  var sr2 = class extends h {
  };
  var Nd = class extends sr2 {
  };
  var wn = class extends sr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "text_model" });
    }
  };
  var yn = class extends sr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "audio_model" });
    }
  };
  var xt2 = class extends h {
  };
  var Ld = class extends xt2 {
  };
  var $d = class extends xt2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "text_model" });
    }
  };
  var bn = class extends xt2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "text_model" });
    }
  };
  var Fd = class extends xt2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "vision_model" });
    }
  };
  var Rd = class extends xt2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "vision_model" });
    }
  };
  var kn = class extends h {
  };
  var Dd = class extends kn {
  };
  var qd = class extends kn {
  };
  var vn = class extends h {
  };
  var jd = class extends vn {
  };
  var Bd = class extends vn {
  };
  var En = class extends h {
  };
  var Ud = class extends En {
  };
  var Gd = class extends En {
  };
  var An = class extends h {
  };
  var Wd = class extends An {
  };
  var Vd = class extends An {
  };
  var Mn = class extends h {
    requires_attention_mask = false;
    main_input_name = "input_features";
    forward_params = ["input_features", "decoder_input_ids", "decoder_attention_mask", "past_key_values"];
  };
  var Hd = class extends Mn {
  };
  var Kd = class extends Mn {
  };
  var Bt2 = class extends h {
  };
  var Xd = class extends Bt2 {
  };
  var Qd = class extends Bt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Yd = class extends Bt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Jd = class extends Bt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Zd = class extends Bt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Sn = class extends h {
  };
  var ef = class extends Sn {
  };
  var tf = class extends Sn {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var On = class extends h {
  };
  var sf = class extends On {
  };
  var rf = class extends On {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var In = class extends h {
  };
  var nf = class extends In {
  };
  var of = class extends In {
    async _call(e) {
      return new wt(await super._call(e));
    }
  };
  var wt = class extends he {
    constructor({ logits: e, pred_boxes: s }) {
      super(), this.logits = e, this.pred_boxes = s;
    }
  };
  var zn = class extends h {
  };
  var af = class extends zn {
  };
  var lf = class extends zn {
    async _call(e) {
      return new wt(await super._call(e));
    }
  };
  var vl = class extends he {
    constructor({ audio_codes: e }) {
      super(), this.audio_codes = e;
    }
  };
  var El = class extends he {
    constructor({ audio_values: e }) {
      super(), this.audio_values = e;
    }
  };
  var rr2 = class extends h {
    main_input_name = "input_values";
    forward_params = ["input_values"];
  };
  var cf = class extends rr2 {
    async encode(e) {
      return new vl(await X(this.sessions.encoder_model, e));
    }
    async decode(e) {
      return new El(await X(this.sessions.decoder_model, e));
    }
  };
  var Tn = class extends rr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "encoder_model" });
    }
  };
  var Cn = class extends rr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "decoder_model" });
    }
  };
  var Ut = class extends h {
  };
  var pf = class extends Ut {
  };
  var uf = class extends Ut {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var _f = class extends Ut {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var df = class extends Ut {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var ff = class extends Ut {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Pn = class extends h {
  };
  var mf = class extends Pn {
  };
  var hf = class extends Pn {
  };
  var Gt = class extends h {
  };
  var gf = class extends Gt {
  };
  var xf = class extends Gt {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var wf = class extends Gt {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var yf = class extends Gt {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var bf = class extends Gt {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Al = class extends h {
  };
  var kf = class extends Al {
  };
  var Nn = class extends h {
  };
  var vf = class extends Nn {
  };
  var Ef = class extends Nn {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Ml = class extends h {
  };
  var Af = class extends Ml {
  };
  var Sl = class extends h {
  };
  var Mf = class extends Sl {
  };
  var nr2 = class extends h {
  };
  var Sf = class extends nr2 {
  };
  var Of = class extends nr2 {
    async _call(e) {
      return new or2(await super._call(e));
    }
  };
  var If = class extends nr2 {
    async _call(e) {
      return new Ol(await super._call(e));
    }
  };
  var or2 = class extends he {
    constructor({ logits: e, pred_boxes: s }) {
      super(), this.logits = e, this.pred_boxes = s;
    }
  };
  var Ol = class extends he {
    constructor({ logits: e, pred_boxes: s, pred_masks: r }) {
      super(), this.logits = e, this.pred_boxes = s, this.pred_masks = r;
    }
  };
  var Ln = class extends h {
  };
  var zf2 = class extends Ln {
  };
  var Tf = class extends Ln {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var $n = class extends h {
  };
  var Cf = class extends $n {
  };
  var Pf = class extends $n {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Il = class extends h {
  };
  var Nf = class extends Il {
  };
  var zl = class extends h {
  };
  var Lf = class extends zl {
  };
  var Wt = class extends h {
  };
  var $f = class extends Wt {
  };
  var Ff = class extends Wt {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Rf = class extends Wt {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Df = class extends Wt {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var qf2 = class extends Wt {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Tl = class extends h {
  };
  var jf2 = class extends Tl {
  };
  var Fn = class extends h {
  };
  var Bf = class extends Fn {
  };
  var Uf = class extends Fn {
  };
  var Rn = class extends h {
  };
  var Gf = class extends Rn {
  };
  var Wf = class extends Rn {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Vt2 = class extends h {
  };
  var Vf2 = class extends Vt2 {
  };
  var Hf2 = class extends Vt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Kf2 = class extends Vt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Xf2 = class extends Vt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Qf2 = class extends Vt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Dn = class extends h {
  };
  var Yf2 = class extends Dn {
  };
  var Jf2 = class extends Dn {
  };
  var ms2 = class extends h {
  };
  var Zf2 = class extends ms2 {
  };
  var em = class extends ms2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var tm = class extends ms2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var sm = class extends ms2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var hs2 = class extends h {
  };
  var rm = class extends hs2 {
  };
  var nm = class extends hs2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var om = class extends hs2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var im = class extends hs2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var qn = class extends h {
  };
  var am = class extends qn {
  };
  var lm = class extends qn {
  };
  var jn = class extends h {
  };
  var cm = class extends jn {
  };
  var pm = class extends jn {
  };
  var Bn = class extends h {
  };
  var um = class extends Bn {
  };
  var _m = class extends Bn {
  };
  var Un = class extends h {
  };
  var dm = class extends Un {
  };
  var fm = class extends Un {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Cl = class extends h {
    forward_params = ["input_ids", "inputs_embeds", "attention_mask", "pixel_values", "encoder_outputs", "decoder_input_ids", "decoder_inputs_embeds", "decoder_attention_mask", "past_key_values"];
    main_input_name = "inputs_embeds";
  };
  var mm = class extends Cl {
    _merge_input_ids_with_image_features({ inputs_embeds: e, image_features: s, input_ids: r, attention_mask: n }) {
      return { inputs_embeds: ie2([s, e], 1), attention_mask: ie2([Me(s.dims.slice(0, 2)), n], 1) };
    }
    async _prepare_inputs_embeds({ input_ids: e, pixel_values: s, inputs_embeds: r, attention_mask: n }) {
      if (!e && !s) throw new Error("Either `input_ids` or `pixel_values` should be provided.");
      let o, i;
      return e && (o = await this.encode_text({ input_ids: e })), s && (i = await this.encode_image({ pixel_values: s })), o && i ? { inputs_embeds: r, attention_mask: n } = this._merge_input_ids_with_image_features({ inputs_embeds: o, image_features: i, input_ids: e, attention_mask: n }) : r = o || i, { inputs_embeds: r, attention_mask: n };
    }
    async forward({ input_ids: e, pixel_values: s, attention_mask: r, decoder_input_ids: n, decoder_attention_mask: o, encoder_outputs: i, past_key_values: a, inputs_embeds: l, decoder_inputs_embeds: c }) {
      if (l || ({ inputs_embeds: l, attention_mask: r } = await this._prepare_inputs_embeds({ input_ids: e, pixel_values: s, inputs_embeds: l, attention_mask: r })), !i) {
        let { last_hidden_state: u } = await st2(this, { inputs_embeds: l, attention_mask: r });
        i = u;
      }
      if (!c) {
        if (!n) throw new Error("Either `decoder_input_ids` or `decoder_inputs_embeds` should be provided.");
        c = await this.encode_text({ input_ids: n });
      }
      return await Ve2(this, { inputs_embeds: c, attention_mask: o, encoder_attention_mask: r, encoder_hidden_states: i, past_key_values: a }, true);
    }
  };
  var Gn = class extends h {
  };
  var hm = class extends Gn {
  };
  var gm = class extends Gn {
  };
  var Wn = class extends h {
  };
  var xm = class extends Wn {
  };
  var wm = class extends Wn {
  };
  var Pl = class extends h {
    forward_params = ["input_ids", "attention_mask", "pixel_values", "position_ids", "past_key_values"];
  };
  var Ue = class extends Pl {
    _merge_input_ids_with_image_features(e) {
      let s = e.image_features.dims.at(-1), r = e.image_features.view(-1, s);
      return er2({ image_token_id: this.config.image_token_index ?? this.config.image_token_id, ...e, image_features: r });
    }
  };
  var ym = class extends Ue {
  };
  var bm = class extends Ue {
  };
  var Nl = class extends h {
  };
  var km = class extends Nl {
  };
  var Ll = class extends Ue {
  };
  var vm = class extends Ll {
  };
  var $l = class extends h {
    forward_params = ["input_ids", "attention_mask", "inputs_embeds", "per_layer_inputs", "position_ids", "pixel_values", "input_features", "input_features_mask", "past_key_values"];
  };
  var Ht2 = class extends $l {
    async forward({ input_ids: e = null, attention_mask: s = null, pixel_values: r = null, input_features: n = null, input_features_mask: o = null, position_ids: i = null, inputs_embeds: a = null, per_layer_inputs: l = null, past_key_values: c = null, generation_config: p = null, logits_processor: u = null, ..._ }) {
      if ((!a || !l) && ({ inputs_embeds: a, per_layer_inputs: l } = await X(this.sessions.embed_tokens, { input_ids: e }), e.dims[1] !== 1)) {
        if (r) {
          let { image_features: m } = await this._encode_vision({ pixel_values: r, ..._ });
          ({ inputs_embeds: a, attention_mask: s } = this._merge_input_ids_with_image_features({ image_features: m, inputs_embeds: a, input_ids: e, attention_mask: s }));
        }
        if (n) {
          let { audio_features: m } = await X(this.sessions.audio_encoder, { input_features: n, input_features_mask: o });
          ({ inputs_embeds: a, attention_mask: s } = this._merge_input_ids_with_audio_features({ audio_features: m, inputs_embeds: a, input_ids: e, attention_mask: s }));
        }
      }
      return await Ve2(this, { inputs_embeds: a, per_layer_inputs: l, past_key_values: c, attention_mask: s, position_ids: i, generation_config: p, logits_processor: u }, true);
    }
    _encode_vision(e) {
      return X(this.sessions.vision_encoder, { pixel_values: e.pixel_values });
    }
    _merge_input_ids_with_image_features(e) {
      let s = e.image_features.dims.at(-1), r = e.image_features.view(-1, s);
      return er2({ image_token_id: this.config.image_token_id, ...e, image_features: r });
    }
    _merge_input_ids_with_audio_features(e) {
      let s = e.audio_features.dims.at(-1), r = e.audio_features.view(-1, s);
      return wl({ audio_token_id: this.config.audio_token_id, ...e, audio_features: r });
    }
  };
  var Em = class extends Ht2 {
  };
  var ir2 = class extends Ht2 {
    forward_params = ["input_ids", "attention_mask", "inputs_embeds", "per_layer_inputs", "position_ids", "pixel_values", "image_position_ids", "input_features", "input_features_mask", "past_key_values"];
    _encode_vision(e) {
      return X(this.sessions.vision_encoder, { pixel_values: e.pixel_values, pixel_position_ids: e.image_position_ids });
    }
  };
  var Am = class extends ir2 {
  };
  var Vn = class extends h {
  };
  var Mm = class extends Vn {
  };
  var Sm = class extends Vn {
  };
  var Hn = class extends h {
  };
  var Om = class extends Hn {
  };
  var Im = class extends Hn {
  };
  var Fl = class extends h {
    forward_params = ["input_ids", "attention_mask", "position_ids", "past_key_values", "pixel_values", "image_grid_thw"];
  };
  var ar2 = class extends Fl {
    image_grid_thw_name = "grid_thw";
    _get_text_only_rope_index(e, s) {
      if (s) {
        let { data: r, dims: n } = J_(s), o = BigInt64Array.from({ length: 3 * r.length }, (a, l) => r[l % r.length]), i = Array.from({ length: n[0] }, (a, l) => de(r.subarray(n[1] * l, n[1] * (l + 1)))[0] + 1n + BigInt(n[1]));
        return [new E("int64", o, [3, ...n]), new E("int64", i, [i.length, 1])];
      } else {
        let [r, n] = e.dims, o = BigInt64Array.from({ length: 3 * r * n }, (i, a) => BigInt(Math.floor(a % n / r)));
        return [new E("int64", o, [3, ...e.dims]), up([r, 1])];
      }
    }
    _reorder_and_write_positions(e, s, r, n) {
      let o = e.reduce((c, p) => c + p.length, 0), i = new Array(o), a = 0;
      for (let c = 0; c < 3; ++c) for (let p of e) {
        let u = p.length / 3;
        for (let _ = c * u; _ < (c + 1) * u; ++_) i[a++] = p[_];
      }
      let l = 0;
      for (let c = 0; c < s.length; ++c) if (s[c] == 1) {
        for (let p = 0; p < 3; ++p) r[p][n][c] = i[p * o / 3 + l];
        ++l;
      }
      return i;
    }
    _get_multimodal_rope_positions({ filtered_ids: e, image_grid_thw_list: s, video_grid_thw_list: r, spatial_merge_size: n, state: o }) {
      let { image_token_id: i, video_token_id: a, vision_start_token_id: l } = this.config, c = e, u = c.reduce((x, y, b) => (y == l && x.push(b), x), []).map((x) => c[x + 1]), _ = u.filter((x) => x == i).length, d = u.filter((x) => x == a).length, m = [], f = 0, g = _, w = d;
      for (let x = 0; x < u.length; ++x) {
        let y = c.findIndex((G, ee) => ee > f && G == i), b = c.findIndex((G, ee) => ee > f && G == a), v = g > 0 && y !== -1 ? y : c.length + 1, k2 = w > 0 && b !== -1 ? b : c.length + 1, S, I, $2, C;
        v < k2 ? ([I, $2, C] = s[o.image_index], ++o.image_index, --g, S = v) : ([I, $2, C] = r[o.video_index], ++o.video_index, --w, S = k2);
        let [R, V, H] = [Number(I), Math.floor(Number($2) / n), Math.floor(Number(C) / n)], j = S - f, B = m.length > 0 ? de(m.at(-1))[0] + 1 : 0;
        m.push(Array.from({ length: 3 * j }, (G, ee) => B + ee % j));
        let Z = j + B, D = R * V * H, A = Array.from({ length: D }, (G, ee) => Z + Math.floor(ee / (V * H))), O = Array.from({ length: D }, (G, ee) => Z + Math.floor(ee / H) % V), T = Array.from({ length: D }, (G, ee) => Z + ee % H);
        m.push([A, O, T].flat()), f = S + D;
      }
      if (f < c.length) {
        let x = m.length > 0 ? de(m.at(-1))[0] + 1 : 0, y = c.length - f;
        m.push(Array.from({ length: 3 * y }, (b, v) => x + v % y));
      }
      return m;
    }
    get_rope_index(e, s, r, n) {
      let { vision_config: o } = this.config, i = o.spatial_merge_size ?? 2;
      if (s || r) {
        let a = e.tolist();
        n || (n = Aa2(e));
        let l = n.tolist(), c = Array.from({ length: 3 }, () => Array.from({ length: e.dims[0] }, () => Array.from({ length: e.dims[1] }, () => 0))), p = s ? s.tolist() : [], u = r ? r.tolist() : [], _ = { image_index: 0, video_index: 0 }, d = [];
        for (let m = 0; m < a.length; ++m) {
          let f = a[m].filter((x, y) => l[m][y] == 1), g = this._get_multimodal_rope_positions({ filtered_ids: f, image_grid_thw_list: p, video_grid_thw_list: u, spatial_merge_size: i, state: _ }), w = this._reorder_and_write_positions(g, l[m], c, m);
          d.push(de(w)[0] + 1 - a[m].length);
        }
        return [new E("int64", c.flat(1 / 0), [3, e.dims[0], e.dims[1]]), new E("int64", d, [d.length, 1])];
      } else return this._get_text_only_rope_index(e, n);
    }
    async encode_image({ pixel_values: e, image_grid_thw: s }) {
      return (await X(this.sessions.vision_encoder, { pixel_values: e, [this.image_grid_thw_name]: s })).image_features;
    }
    _merge_input_ids_with_image_features(e) {
      return er2({ image_token_id: this.config.image_token_id, ...e });
    }
    prepare_inputs_for_generation(e, s, r) {
      if (!s.attention_mask || s.position_ids || !(this.sessions.decoder_model_merged ?? this.sessions.model).inputNames.includes("position_ids")) return s;
      if (!s.past_key_values) [s.position_ids, s.rope_deltas] = this.get_rope_index(s.input_ids, s.image_grid_thw, s.video_grid_thw, s.attention_mask);
      else {
        s.pixel_values = null;
        let o = s.past_key_values.get_seq_length();
        if (o < s.input_ids.dims[1]) {
          let [i, a] = this.get_rope_index(s.input_ids, s.image_grid_thw, s.video_grid_thw, s.attention_mask);
          s.rope_deltas = a, s.position_ids = i.slice(null, null, [o, null]), s.input_ids = s.input_ids.slice(null, [o, null]);
        } else {
          s.rope_deltas || ([, s.rope_deltas] = this.get_rope_index(s.input_ids, s.image_grid_thw, s.video_grid_thw, s.attention_mask));
          let i = BigInt(o), a = s.rope_deltas.map((l) => i + l);
          s.position_ids = qe([a, a, a], 0);
        }
      }
      return s;
    }
  };
  var Kn = class extends ar2 {
  };
  var gs2 = class extends ar2 {
    image_grid_thw_name = "image_grid_thw";
  };
  var Xn = class extends Kn {
    image_grid_thw_name = "image_grid_thw";
  };
  var zm = class extends gs2 {
    get_vision_position_ids(e, s, r, n) {
      let o = Math.floor(s[0] / r), i = Math.floor(s[1] / n), a = Math.floor(s[2] / n), l = i * a * o, c = Array.from({ length: l }, () => e), p = Array.from({ length: l }, (_, d) => e + Math.floor(d / (a * o))), u = Array.from({ length: l }, (_, d) => e + d % a);
      return [...c, ...p, ...u];
    }
    _get_multimodal_rope_positions({ filtered_ids: e, image_grid_thw_list: s, video_grid_thw_list: r, spatial_merge_size: n, state: o }) {
      let { image_token_id: i } = this.config, a = [], l = 0, c = e[0] == i ? 1 : 0;
      for (let _ = 1; _ <= e.length; ++_) {
        let d = _ < e.length ? e[_] == i ? 1 : 0 : -1;
        d !== c && (a.push([c, l, _]), l = _, c = d);
      }
      let p = 0, u = [];
      for (let [_, d, m] of a) if (_ === 0) {
        let f = m - d;
        u.push(Array.from({ length: 3 * f }, (g, w) => p + w % f)), p += f;
      } else {
        let f = s[o.image_index++].map(Number), g = f[0];
        u.push(this.get_vision_position_ids(p, f, g, n)), p += Math.max(f[1], f[2]) / n;
      }
      return u;
    }
  };
  var Qn = class extends h {
  };
  var Tm = class extends Qn {
  };
  var Cm = class extends Qn {
  };
  var Yn = class extends h {
  };
  var Pm = class extends Yn {
  };
  var Nm = class extends Yn {
  };
  var Jn = class extends h {
  };
  var Lm = class extends Jn {
  };
  var $m = class extends Jn {
  };
  var Zn = class extends h {
  };
  var Fm = class extends Zn {
  };
  var Rm = class extends Zn {
  };
  var eo = class extends h {
  };
  var Dm = class extends eo {
  };
  var qm = class extends eo {
  };
  var to = class extends h {
  };
  var jm = class extends to {
  };
  var Bm = class extends to {
  };
  var so = class extends h {
  };
  var Um = class extends so {
  };
  var Gm = class extends so {
  };
  var ro = class extends h {
  };
  var Wm = class extends ro {
  };
  var Vm = class extends ro {
  };
  var no = class extends h {
  };
  var Hm = class extends no {
  };
  var Km = class extends no {
  };
  var Rl = class extends h {
    forward_params = ["input_ids", "attention_mask", "position_ids", "audio_values", "past_key_values"];
  };
  var xs2 = class extends Rl {
    _merge_input_ids_with_audio_features(e) {
      let s = e.audio_features.dims.at(-1), r = e.audio_features.view(-1, s);
      return wl({ audio_token_id: this.config.ignore_index ?? this.config.audio_token_id ?? this.config.audio_token_index, ...e, audio_features: r });
    }
  };
  var Xm = class extends xs2 {
    forward_params = ["input_ids", "attention_mask", "input_features", "past_key_values"];
  };
  var Dl = class extends h {
  };
  var Qm = class extends Dl {
  };
  var ql = class extends h {
  };
  var Ym = class extends ql {
  };
  var oo = class extends h {
  };
  var Jm = class extends oo {
  };
  var Zm = class extends oo {
  };
  var io = class extends h {
  };
  var eh = class extends io {
  };
  var th = class extends io {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var pt = class extends h {
  };
  var sh = class extends pt {
  };
  var rh = class extends pt {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var nh = class extends pt {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var oh = class extends pt {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var ih = class extends h {
  };
  var ah = class extends pt {
  };
  var lh = class extends pt {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var ch = class extends pt {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var ao = class extends h {
  };
  var ph = class extends ao {
  };
  var uh = class extends ao {
  };
  var lo = class extends Ue {
    forward_params = ["input_ids", "attention_mask", "pixel_values", "pixel_attention_mask", "position_ids", "past_key_values"];
  };
  var co = class extends h {
  };
  var _h = class extends co {
  };
  var dh = class extends co {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var po = class extends h {
  };
  var fh = class extends po {
  };
  var mh = class extends po {
  };
  var lr2 = class extends h {
  };
  var hh = class extends lr2 {
    async forward(e) {
      let s = !e.input_ids, r = !e.pixel_values;
      if (s && r) throw new Error("Either `input_ids` or `pixel_values` should be provided.");
      if (s && (e.input_ids = Me([e.pixel_values.dims[0], 1])), r) {
        let { image_size: c } = this.config.vision_config;
        e.pixel_values = ve([0, 3, c, c], 0);
      }
      let { text_embeddings: n, image_embeddings: o, l2norm_text_embeddings: i, l2norm_image_embeddings: a } = await super.forward(e), l = {};
      return s || (l.text_embeddings = n, l.l2norm_text_embeddings = i), r || (l.image_embeddings = o, l.l2norm_image_embeddings = a), l;
    }
  };
  var uo = class extends lr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "text_model" });
    }
  };
  var gh = class extends lr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "vision_model" });
    }
  };
  var _o = class extends h {
  };
  var xh = class extends _o {
  };
  var wh = class extends _o {
  };
  var yh = class extends Ue {
  };
  var fo = class extends h {
  };
  var bh = class extends fo {
  };
  var kh = class extends fo {
  };
  var vh = class extends Ue {
    forward_params = ["input_ids", "attention_mask", "pixel_values", "pixel_attention_mask", "spatial_shapes", "position_ids", "past_key_values"];
  };
  var mo = class extends h {
  };
  var Eh = class extends mo {
  };
  var Ah = class extends mo {
  };
  var jl = class extends h {
  };
  var Mh = class extends jl {
  };
  var ho = class extends h {
  };
  var Sh = class extends ho {
  };
  var Oh = class extends ho {
  };
  var go = class extends h {
  };
  var Ih = class extends go {
  };
  var zh = class extends go {
  };
  var xo = class extends h {
  };
  var Th = class extends xo {
  };
  var Ch = class extends xo {
  };
  var wo = class extends h {
  };
  var Ph = class extends wo {
  };
  var Nh = class extends wo {
  };
  var ws2 = class extends h {
  };
  var Lh = class extends ws2 {
  };
  var $h = class extends ws2 {
  };
  var Fh = class extends ws2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Rh = class extends ws2 {
  };
  var Bl = class extends h {
  };
  var Dh = class extends Bl {
  };
  var Ul = class extends h {
  };
  var qh = class extends Ul {
  };
  var Gl = class extends he {
    constructor({ char_logits: e, bpe_logits: s, wp_logits: r }) {
      super(), this.char_logits = e, this.bpe_logits = s, this.wp_logits = r;
    }
    get logits() {
      return [this.char_logits, this.bpe_logits, this.wp_logits];
    }
  };
  var Wl = class extends h {
  };
  var jh = class extends Wl {
    async _call(e) {
      return new Gl(await super._call(e));
    }
  };
  var Vl = class extends he {
    constructor({ audio_codes: e }) {
      super(), this.audio_codes = e;
    }
  };
  var Hl = class extends he {
    constructor({ audio_values: e }) {
      super(), this.audio_values = e;
    }
  };
  var cr2 = class extends h {
    main_input_name = "input_values";
    forward_params = ["input_values"];
  };
  var Bh = class extends cr2 {
    async encode(e) {
      return new Vl(await X(this.sessions.encoder_model, e));
    }
    async decode(e) {
      return new Hl(await X(this.sessions.decoder_model, e));
    }
  };
  var yo = class extends cr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "encoder_model" });
    }
  };
  var bo = class extends cr2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "decoder_model" });
    }
  };
  var ko = class extends h {
  };
  var Uh = class extends ko {
  };
  var Gh = class extends ko {
  };
  var vo = class extends h {
  };
  var Wh = class extends vo {
  };
  var Vh = class extends vo {
  };
  var ys2 = class extends h {
  };
  var Hh = class extends ys2 {
  };
  var Kh = class extends ys2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Xh = class extends ys2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Qh = class extends ys2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Eo = class extends h {
  };
  var Yh = class extends Eo {
  };
  var Jh = class extends Eo {
  };
  var pr2 = class extends h {
  };
  var Zh = class extends pr2 {
  };
  var eg = class extends pr2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var tg = class extends pr2 {
  };
  var ur2 = class extends h {
  };
  var sg = class extends ur2 {
  };
  var rg = class extends ur2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var ng = class extends ur2 {
  };
  var _r = class extends h {
  };
  var og = class extends _r {
  };
  var ig = class extends _r {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var ag = class extends _r {
  };
  var dr2 = class extends h {
  };
  var lg = class extends dr2 {
  };
  var cg = class extends dr2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var pg = class extends dr2 {
  };
  var Ao = class extends h {
  };
  var ug = class extends Ao {
  };
  var _g = class extends Ao {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Mo = class extends h {
  };
  var dg = class extends Mo {
  };
  var fg = class extends Mo {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var bs2 = class extends h {
  };
  var mg = class extends bs2 {
  };
  var hg = class extends bs2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var gg = class extends bs2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var xg = class extends bs2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var So = class extends h {
  };
  var wg = class extends So {
  };
  var yg = class extends So {
  };
  var Oo = class extends h {
    requires_attention_mask = false;
    main_input_name = "input_values";
    forward_params = ["input_values", "decoder_input_ids", "past_key_values"];
  };
  var bg = class extends Oo {
  };
  var kg = class extends Oo {
  };
  var Kt2 = class extends h {
  };
  var vg = class extends Kt2 {
  };
  var Eg = class extends Kt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Ag = class extends Kt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Mg = class extends Kt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Sg = class extends Kt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Io = class extends h {
  };
  var Og = class extends Io {
  };
  var Ig = class extends Io {
  };
  var zo = class extends h {
  };
  var zg = class extends zo {
  };
  var Tg = class extends zo {
  };
  var Kl = class extends h {
  };
  var Cg = class extends Kl {
    forward_params = ["input_ids", "pixel_values", "images_seq_mask", "images_emb_mask", "attention_mask", "position_ids", "past_key_values"];
    constructor(...e) {
      super(...e), this._generation_mode = "text";
    }
    async forward(e) {
      let s = this._generation_mode ?? "text", r;
      if (s === "text" || !e.past_key_values) {
        let l = this.sessions.prepare_inputs_embeds, c = we(e, l.inputNames);
        r = await X(l, c);
      } else {
        let l = this.sessions.gen_img_embeds, c = we({ image_ids: e.input_ids }, l.inputNames);
        r = await X(l, c);
      }
      let n = { ...e, ...r }, o = await Ve2(this, n), i = this.sessions[s === "text" ? "lm_head" : "gen_head"];
      if (!i) throw new Error(`Unable to find "${i}" generation head`);
      let a = await X(i, we(o, i.inputNames));
      return { ...r, ...o, ...a };
    }
    prepare_inputs_for_generation(e, s, r) {
      let n = !!s.past_key_values;
      return r.guidance_scale !== null && r.guidance_scale > 1 && (n ? s.input_ids = ie2([s.input_ids, s.input_ids], 0) : (s.input_ids = ie2([s.input_ids, qr2(s.input_ids, BigInt(r.pad_token_id))], 0), s.attention_mask = ie2([s.attention_mask, qr2(s.attention_mask, 0n)], 0))), (n || !s.pixel_values) && (s.pixel_values = ve([0, 0, 3, 384, 384], 1)), n && (s.images_seq_mask = new E("bool", new Array(1).fill(true).fill(false, 0, 1), [1, 1]), s.images_emb_mask = new E("bool", new Array(0).fill(false), [1, 1, 0])), s;
    }
    async generate(e) {
      return this._generation_mode = "text", super.generate(e);
    }
    async generate_images(e) {
      this._generation_mode = "image";
      let s = (e.inputs ?? e[this.main_input_name]).dims[1], n = (await super.generate(e)).slice(null, [s, null]), o = this.sessions.image_decode, { decoded_image: i } = await X(o, { generated_tokens: n }), a = i.add_(1).mul_(255 / 2).clamp_(0, 255).to("uint8"), l = [];
      for (let c of a) {
        let p = Ee2.fromTensor(c);
        l.push(p);
      }
      return l;
    }
  };
  var To = class extends h {
  };
  var Pg = class extends To {
  };
  var Ng = class extends To {
  };
  var Co = class extends h {
    forward_params = ["input_ids", "attention_mask", "encoder_outputs", "decoder_input_ids", "decoder_attention_mask", "past_key_values"];
    _apply_and_filter_by_delay_pattern_mask(e) {
      let [s, r] = e.dims, n = this.config.decoder.num_codebooks, o = r - n, i = 0;
      for (let c = 0; c < e.size; ++c) {
        if (e.data[c] == this.config.decoder.pad_token_id) continue;
        let p = c % r, u = Math.floor(c / r) % n, _ = p - u;
        _ > 0 && _ <= o && (e.data[i++] = e.data[c]);
      }
      let a = Math.floor(s / n), l = i / (a * n);
      return new E(e.type, e.data.slice(0, i), [a, n, l]);
    }
    prepare_inputs_for_generation(e, s, r) {
      let n = BigInt(this.config.decoder.pad_token_id), o = structuredClone(e);
      for (let i = 0; i < o.length; ++i) for (let a = 0; a < o[i].length; ++a) i % this.config.decoder.num_codebooks >= a && (o[i][a] = n);
      return r.guidance_scale !== null && r.guidance_scale > 1 && (o = o.concat(o)), ln2(this, o, s, r);
    }
    async generate(e) {
      let s = await super.generate(e), r = this._apply_and_filter_by_delay_pattern_mask(s).unsqueeze_(0), { audio_values: n } = await X(this.sessions.encodec_decode, { audio_codes: r });
      return n;
    }
  };
  var Po = class extends h {
  };
  var Lg = class extends Po {
  };
  var $g = class extends Po {
  };
  var No = class extends h {
  };
  var Fg = class extends No {
  };
  var Rg = class extends No {
  };
  var Xt2 = class extends h {
  };
  var Dg = class extends Xt2 {
  };
  var qg = class extends Xt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var jg = class extends Xt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Bg = class extends Xt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Ug = class extends Xt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Xl = class extends h {
  };
  var Gg = class extends Xl {
  };
  var Lo = class extends h {
  };
  var Wg = class extends Lo {
  };
  var Vg = class extends Lo {
  };
  var $o = class extends h {
  };
  var Hg = class extends $o {
  };
  var Kg = class extends $o {
  };
  var Fo = class extends h {
  };
  var Xg = class extends Fo {
  };
  var Qg = class extends Fo {
  };
  var Ro = class extends h {
  };
  var Yg = class extends Ro {
  };
  var Jg = class extends Ro {
  };
  var Do = class extends h {
  };
  var Zg = class extends Do {
  };
  var ex = class extends Do {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var qo = class extends h {
  };
  var tx = class extends qo {
  };
  var sx = class extends qo {
  };
  var jo = class extends h {
  };
  var rx = class extends jo {
  };
  var nx = class extends jo {
  };
  var Bo = class extends h {
  };
  var ox = class extends Bo {
  };
  var ix = class extends Bo {
  };
  var Uo = class extends h {
  };
  var ax = class extends Uo {
  };
  var lx = class extends Uo {
  };
  var cx = class extends Ue {
  };
  var Ql = class extends h {
  };
  var px = class extends Ql {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var Go = class extends h {
  };
  var ux = class extends Go {
  };
  var _x = class extends Go {
  };
  var Wo = class extends h {
  };
  var dx = class extends Wo {
  };
  var fx = class extends Wo {
  };
  var Vo = class extends h {
  };
  var mx = class extends Vo {
  };
  var hx = class extends Vo {
  };
  var Ho = class extends h {
  };
  var gx = class extends Ho {
  };
  var xx = class extends Ho {
  };
  var Yl = class extends h {
    forward_params = ["input_ids", "inputs_embeds", "attention_mask", "position_ids", "pixel_values", "image_sizes", "past_key_values"];
  };
  var Ko = class extends Yl {
    async forward({ input_ids: e = null, attention_mask: s = null, pixel_values: r = null, image_sizes: n = null, position_ids: o = null, inputs_embeds: i = null, past_key_values: a = null, generation_config: l = null, logits_processor: c = null, ...p }) {
      if (!i) {
        let _;
        if (r && e.dims[1] !== 1) {
          if (!n) throw new Error("`image_sizes` must be provided when `pixel_values` is provided.");
          ({ image_features: _ } = await X(this.sessions.vision_encoder, { pixel_values: r, image_sizes: n }));
        } else {
          let d = this.config.normalized_config.hidden_size;
          _ = new E("float32", [], [0, d]);
        }
        ({ inputs_embeds: i } = await X(this.sessions.prepare_inputs_embeds, { input_ids: e, image_features: _ }));
      }
      return await Ve2(this, { inputs_embeds: i, past_key_values: a, attention_mask: s, position_ids: o, generation_config: l, logits_processor: c }, false);
    }
  };
  var Xo = class extends h {
  };
  var wx = class extends Xo {
  };
  var yx = class extends Xo {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Qo = class extends h {
  };
  var bx = class extends Qo {
  };
  var kx = class extends Qo {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Yo = class extends h {
  };
  var vx = class extends Yo {
  };
  var Ex = class extends Yo {
  };
  var Jo = class extends h {
  };
  var Ax = class extends Jo {
  };
  var Mx = class extends Jo {
  };
  var Zo = class extends h {
  };
  var Sx = class extends Zo {
  };
  var Ox = class extends Zo {
  };
  var ei = class extends h {
  };
  var Ix = class extends ei {
  };
  var zx = class extends ei {
  };
  var ti = class extends h {
  };
  var Tx = class extends ti {
  };
  var Cx = class extends ti {
  };
  var ks2 = class extends gs2 {
  };
  var si = class extends Xn {
  };
  var Px = class extends ks2 {
  };
  var Nx = class extends si {
  };
  var fr2 = class extends ks2 {
  };
  var ri = class extends fr2 {
  };
  var Lx = class extends fr2 {
  };
  var $x = class extends ri {
  };
  var ni = class extends h {
  };
  var Fx = class extends ni {
  };
  var Rx = class extends ni {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var oi = class extends h {
  };
  var Dx = class extends oi {
  };
  var qx = class extends oi {
    async _call(e) {
      return new Jl(await super._call(e));
    }
  };
  var Jl = class extends wt {
  };
  var Qt2 = class extends h {
  };
  var jx = class extends Qt2 {
  };
  var Bx = class extends Qt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Ux = class extends Qt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Gx = class extends Qt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Wx = class extends Qt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Yt2 = class extends h {
  };
  var Vx = class extends Yt2 {
  };
  var Hx = class extends Yt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Kx = class extends Yt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Xx = class extends Yt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var Qx = class extends Yt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var ii = class extends h {
  };
  var Yx = class extends ii {
  };
  var Jx = class extends ii {
    async _call(e) {
      return new Zl(await super._call(e));
    }
  };
  var Zl = class extends wt {
  };
  var ec2 = class extends he {
    constructor({ iou_scores: e, pred_masks: s }) {
      super(), this.iou_scores = e, this.pred_masks = s;
    }
  };
  var tc2 = class extends h {
  };
  var Zx = class extends tc2 {
    async get_image_embeddings({ pixel_values: e }) {
      return await st2(this, { pixel_values: e });
    }
    async forward(e) {
      !e.image_embeddings || !e.image_positional_embeddings ? e = { ...e, ...await this.get_image_embeddings(e) } : e = { ...e }, e.input_labels ??= Me(e.input_points.dims.slice(0, -1));
      let s = { image_embeddings: e.image_embeddings, image_positional_embeddings: e.image_positional_embeddings };
      return e.input_points && (s.input_points = e.input_points), e.input_labels && (s.input_labels = e.input_labels), e.input_boxes && (s.input_boxes = e.input_boxes), await X(this.sessions.prompt_encoder_mask_decoder, s);
    }
    async _call(e) {
      return new ec2(await super._call(e));
    }
  };
  var sc2 = class extends he {
    constructor({ iou_scores: e, pred_masks: s, object_score_logits: r }) {
      super(), this.iou_scores = e, this.pred_masks = s, this.object_score_logits = r;
    }
  };
  var rc2 = class extends h {
  };
  var ai = class extends rc2 {
    async get_image_embeddings({ pixel_values: e }) {
      return await st2(this, { pixel_values: e });
    }
    async forward(e) {
      let { num_feature_levels: s } = this.config.vision_config;
      if (Array.from({ length: s }, (i, a) => `image_embeddings.${a}`).some((i) => !e[i]) ? e = { ...e, ...await this.get_image_embeddings(e) } : e = { ...e }, e.input_points) {
        if (e.input_boxes && e.input_boxes.dims[1] !== 1) throw new Error("When both `input_points` and `input_boxes` are provided, the number of boxes per image must be 1.");
        let i = e.input_points.dims;
        e.input_labels ??= Me(i.slice(0, -1)), e.input_boxes ??= ve([i[0], 0, 4], 0);
      } else if (e.input_boxes) {
        let i = e.input_boxes.dims;
        e.input_labels = ve([i[0], i[1], 0], -1n), e.input_points = ve([i[0], 1, 0, 2], 0);
      } else throw new Error("At least one of `input_points` or `input_boxes` must be provided.");
      let n = this.sessions.prompt_encoder_mask_decoder, o = we(e, n.inputNames);
      return await X(n, o);
    }
    async _call(e) {
      return new sc2(await super._call(e));
    }
  };
  var ew = class extends ai {
  };
  var tw = class extends ai {
  };
  var mr2 = class extends h {
  };
  var sw = class extends mr2 {
  };
  var rw = class extends mr2 {
  };
  var nw = class extends mr2 {
  };
  var hr = class extends h {
  };
  var ow = class extends hr {
  };
  var iw = class extends hr {
  };
  var aw = class extends hr {
  };
  var li = class extends h {
  };
  var lw = class extends li {
  };
  var ci = class extends li {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "text_model" });
    }
  };
  var cw = class extends xt2 {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "vision_model" });
    }
  };
  var pi = class extends h {
  };
  var pw = class extends pi {
  };
  var uw = class extends pi {
  };
  var _w = class extends lo {
  };
  var gr = class extends h {
    main_input_name = "input_values";
    forward_params = ["input_values"];
  };
  var dw = class extends gr {
    async encode(e) {
      return await X(this.sessions.encoder_model, e);
    }
    async decode(e) {
      return await X(this.sessions.decoder_model, e);
    }
  };
  var ui = class extends gr {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "encoder_model" });
    }
  };
  var _i = class extends gr {
    static async from_pretrained(e, s = {}) {
      return super.from_pretrained(e, { ...s, model_file_name: s.model_file_name ?? "decoder_model" });
    }
  };
  var di = class extends h {
  };
  var fw = class extends di {
  };
  var mw = class extends di {
  };
  var xr = class extends h {
  };
  var hw = class extends xr {
  };
  var gw = class extends xr {
  };
  var xw = class extends xr {
    async generate_speech(e, s, { threshold: r = 0.5, minlenratio: n = 0, maxlenratio: o = 20, vocoder: i = null } = {}) {
      let a = { input_ids: e }, { encoder_outputs: l, encoder_attention_mask: c } = await st2(this, a), p = l.dims[1] / this.config.reduction_factor, u = Math.floor(p * o), _ = Math.floor(p * n), d = this.config.num_mel_bins, m = [], f = null, g = null, w = 0;
      for (; ; ) {
        ++w;
        let b = Q_(!!g), v;
        g ? v = g.output_sequence_out : v = new E("float32", new Float32Array(d), [1, 1, d]);
        let k2 = { use_cache_branch: b, output_sequence: v, encoder_attention_mask: c, speaker_embeddings: s, encoder_hidden_states: l };
        cn2(this, k2, f), g = await X(this.sessions.decoder_model_merged, k2), f = gl2(g, f);
        let { prob: S, spectrum: I } = g;
        if (m.push(I), w >= _ && (Array.from(S.data).filter(($2) => $2 >= r).length > 0 || w >= u)) break;
      }
      let x = ie2(m), { waveform: y } = await X(i.sessions.model, { spectrogram: x });
      return { spectrogram: x, waveform: y };
    }
  };
  var ww = class extends h {
    main_input_name = "spectrogram";
  };
  var vs2 = class extends h {
  };
  var yw = class extends vs2 {
  };
  var bw = class extends vs2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var kw = class extends vs2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var vw = class extends vs2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var fi = class extends h {
  };
  var Ew = class extends fi {
  };
  var Aw = class extends fi {
  };
  var mi = class extends h {
  };
  var Mw = class extends mi {
  };
  var Sw = class extends mi {
  };
  var nc2 = class extends h {
  };
  var Ow = class extends nc2 {
  };
  var oc2 = class extends h {
  };
  var hi = class extends oc2 {
    async generate_speech({ input_ids: e, attention_mask: s, style: r, num_inference_steps: n = 5, speed: o = 1.05 }) {
      let { sampling_rate: i, chunk_compress_factor: a, base_chunk_size: l, latent_dim: c } = this.config, { last_hidden_state: p, durations: u } = await X(this.sessions.text_encoder, { input_ids: e, attention_mask: s, style: r }), _ = u.div(o).mul_(i), d = l * a, m = _.data, f = Int32Array.from(m, (C) => Math.ceil(C / d)), g = Math.max(...f), w = e.dims[0], x = new BigInt64Array(w * g);
      for (let C = 0; C < w; ++C) x.fill(1n, C * g, C * g + f[C]);
      let y = new E("int64", x, [w, g]), b = c * a, v = b * g, k2 = ob([w, b, g]), S = k2.data;
      for (let C = 0; C < w; ++C) if (f[C] !== g) for (let R = 0; R < b; ++R) S.fill(0, C * v + R * g + f[C], C * v + (R + 1) * g);
      let I = ve([w], n);
      for (let C = 0; C < n; ++C) {
        let R = ve([w], C);
        ({ denoised_latents: k2 } = await X(this.sessions.latent_denoiser, { style: r, noisy_latents: k2, latent_mask: y, encoder_outputs: p, attention_mask: s, timestep: R, num_inference_steps: I }));
      }
      let { waveform: $2 } = await X(this.sessions.voice_decoder, { latents: k2 });
      return { waveform: $2, durations: _ };
    }
  };
  var wr = class extends h {
  };
  var Iw = class extends wr {
  };
  var zw = class extends wr {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Tw = class extends wr {
  };
  var gi = class extends h {
  };
  var Cw = class extends gi {
  };
  var Pw = class extends gi {
  };
  var xi = class extends h {
    forward_params = ["input_ids", "attention_mask", "encoder_outputs", "decoder_input_ids", "decoder_attention_mask", "past_key_values"];
  };
  var Nw = class extends xi {
  };
  var Lw = class extends xi {
  };
  var wi = class extends h {
  };
  var $w = class extends wi {
  };
  var Fw = class extends wi {
    async _call(e) {
      return new ic2(await super._call(e));
    }
  };
  var ic2 = class extends or2 {
  };
  var ac2 = class extends h {
  };
  var Rw = class extends ac2 {
  };
  var yr = class extends h {
  };
  var Dw = class extends yr {
  };
  var qw = class extends yr {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var jw = class extends yr {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Es2 = class extends h {
  };
  var Bw = class extends Es2 {
  };
  var Uw = class extends Es2 {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var Gw = class extends Es2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Ww = class extends Es2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var yi = class extends h {
  };
  var Vw = class extends yi {
  };
  var Hw = class extends yi {
  };
  var Kw = class extends h {
    main_input_name = "pixel_values";
    forward_params = ["pixel_values", "decoder_input_ids", "encoder_hidden_states", "past_key_values"];
  };
  var bi = class extends h {
  };
  var Xw = class extends bi {
  };
  var Qw = class extends bi {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var lc2 = class extends h {
  };
  var Yw = class extends lc2 {
  };
  var ki = class extends h {
  };
  var Jw = class extends ki {
  };
  var Zw = class extends ki {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var cc2 = class extends h {
  };
  var ey = class extends cc2 {
    async _call(e) {
      return new tl(await super._call(e));
    }
  };
  var pc2 = class extends h {
  };
  var ty = class extends pc2 {
  };
  var uc2 = class extends he {
    constructor({ waveform: e, spectrogram: s }) {
      super(), this.waveform = e, this.spectrogram = s;
    }
  };
  var _c = class extends h {
  };
  var sy = class extends _c {
    async _call(e) {
      return new uc2(await super._call(e));
    }
  };
  var ry = class extends xs2 {
  };
  var Fb = 2;
  var gM = 1;
  var ny = /* @__PURE__ */ new WeakMap();
  function xM(t6, e) {
    let { text_config: s, audio_config: r } = t6.config, n = t6.sessions.audio_encoder, { num_mel_bins: o, hidden_size: i } = r, a = o + i, l = new Qs(), c = cs2(r), p = { batch_size: 1 }, u = "float32";
    for (let f of n.inputMetadata) {
      if (f.name === "past_padding_cache") {
        u = f.type;
        continue;
      }
      if (!c.has(f.name)) continue;
      let g = Y_(f.shape, p), w = g.reduce((y, b) => y * b, 1), x = Lt2[f.type];
      l[f.name] = new E(f.type, new x(w), g);
    }
    let _ = Lt2[u], d = new E(u, new _(a * Fb), [1, a, Fb]), m = e[Symbol.asyncIterator]?.() ?? e[Symbol.iterator]?.();
    if (!m) throw new Error("input_features must be iterable or async iterable");
    return { encoder_session: n, enc_kv_cache: l, enc_padding_cache: d, enc_past_seq_len: 0, audio_embed_queue: [], audio_embed_total_tokens: 0, audio_queue_offset: 0, audio_consumed: 0, stream_exhausted: false, chunks_iter: m, text_hidden_size: s.hidden_size };
  }
  async function wM(t6, e) {
    let s = e.dims[2], r = Math.floor((gM + s - 3) / 2) + 1, n = new E("int64", BigInt64Array.from({ length: r }, (p, u) => BigInt(t6.enc_past_seq_len + u)), [1, r]), o = t6.enc_past_seq_len + r, i = Me([1, o]), { audio_embeds: a, present_padding_cache: l, ...c } = await X(t6.encoder_session, { input_features: e, attention_mask: i, position_ids: n, past_padding_cache: t6.enc_padding_cache, ...t6.enc_kv_cache });
    t6.enc_padding_cache.location === "gpu-buffer" && t6.enc_padding_cache.dispose(), t6.enc_padding_cache = l;
    for (let p in c) if (p.startsWith("present.")) {
      let u = p.replace("present", "past_key_values"), _ = t6.enc_kv_cache[u];
      _?.location === "gpu-buffer" && _.dispose(), t6.enc_kv_cache[u] = c[p];
    }
    return t6.enc_past_seq_len = o, a;
  }
  async function yM(t6, e) {
    for (; t6.audio_embed_total_tokens < e && !t6.stream_exhausted; ) {
      let s = await t6.chunks_iter.next();
      if (s.done) {
        t6.stream_exhausted = true;
        break;
      }
      let r = await wM(t6, s.value);
      t6.audio_embed_queue.push({ data: r.data, tokens: r.dims[1] }), t6.audio_embed_total_tokens += r.dims[1];
    }
  }
  function bM(t6, e, s) {
    if (t6.audio_embed_queue.length === 0) return;
    let r = e.data, n = 0, o = s;
    for (; o > 0 && t6.audio_embed_queue.length > 0; ) {
      let i = t6.audio_embed_queue[0], a = i.tokens - t6.audio_queue_offset, l = Math.min(o, a), c = t6.audio_queue_offset * t6.text_hidden_size;
      for (let p = 0; p < l * t6.text_hidden_size; ++p) r[n * t6.text_hidden_size + p] += i.data[c + p];
      n += l, o -= l, t6.audio_queue_offset += l, t6.audio_queue_offset >= i.tokens && (t6.audio_embed_queue.shift(), t6.audio_queue_offset = 0);
    }
    t6.audio_consumed += s - o;
  }
  var oy = class extends Dt {
    constructor(e) {
      super(), this._s = e;
    }
    _call(e) {
      let s = this._s.stream_exhausted && this._s.audio_embed_queue.length === 0;
      return e.map(() => s);
    }
  };
  var dc2 = class extends h {
    forward_params = ["input_ids", "attention_mask", "position_ids", "past_key_values"];
  };
  var vi = class extends dc2 {
    async forward({ input_ids: e, past_key_values: s, ...r }) {
      let n = e.dims[1], o = ny.get(this);
      o && await yM(o, o.audio_consumed + n);
      let { inputs_embeds: i } = await X(this.sessions.embed_tokens, { input_ids: e });
      o && bM(o, i, n);
      let a = { inputs_embeds: i, ...r };
      cn2(this, a, s);
      let l = this.sessions.decoder_model_merged, c = we(a, l.inputNames);
      return await X(l, c);
    }
    async generate({ input_features: e, stopping_criteria: s, ...r }) {
      if (!e) throw new Error("input_features (generator/iterable) must be provided");
      let n = xM(this, e);
      ny.set(this, n);
      let o = new Xs();
      o.push(new oy(n)), s && o.extend(s);
      try {
        return await super.generate({ ...r, stopping_criteria: o });
      } finally {
        n.enc_kv_cache.dispose(), ny.delete(this);
      }
    }
  };
  var br = class extends h {
  };
  var iy = class extends br {
  };
  var ay = class extends br {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var ly = class extends br {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var fc2 = class extends he {
    constructor({ logits: e, embeddings: s }) {
      super(), this.logits = e, this.embeddings = s;
    }
  };
  var Jt2 = class extends h {
  };
  var cy = class extends Jt2 {
  };
  var py = class extends Jt2 {
    async _call(e) {
      return new Be(await super._call(e));
    }
  };
  var uy = class extends Jt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var _y = class extends Jt2 {
    async _call(e) {
      return new fc2(await super._call(e));
    }
  };
  var dy = class extends Jt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var mc2 = class extends h {
  };
  var fy = class extends mc2 {
  };
  var hc2 = class extends Ks {
    return_timestamps = null;
    return_token_timestamps = null;
    num_frames = null;
    alignment_heads = null;
    task = null;
    language = null;
    no_timestamps_token_id = null;
    prompt_ids = null;
    is_multilingual = null;
    lang_to_id = null;
    task_to_id = null;
    max_initial_timestamp_index = 1;
  };
  var Ei = class extends h {
    requires_attention_mask = false;
    main_input_name = "input_features";
    forward_params = ["input_features", "attention_mask", "decoder_input_ids", "decoder_attention_mask", "past_key_values"];
  };
  var my = class extends Ei {
  };
  var gc2 = class extends Ei {
    _prepare_generation_config(e, s) {
      return super._prepare_generation_config(e, s, hc2);
    }
    _retrieve_init_tokens(e) {
      let s = [e.decoder_start_token_id], r = e.language, n = e.task;
      if (e.is_multilingual) {
        r || (F.warn("No language specified - defaulting to English (en)."), r = "en");
        let i = `<|${lb(r)}|>`;
        s.push(e.lang_to_id[i]), s.push(e.task_to_id[n ?? "transcribe"]);
      } else if (r || n) throw new Error("Cannot specify `task` or `language` for an English-only model. If the model is intended to be multilingual, pass `is_multilingual=true` to generate, or update the generation config.");
      return !e.return_timestamps && e.no_timestamps_token_id && s.at(-1) !== e.no_timestamps_token_id ? s.push(e.no_timestamps_token_id) : e.return_timestamps && s.at(-1) === e.no_timestamps_token_id && (F.warn("<|notimestamps|> prompt token is removed from generation_config since `return_timestamps` is set to `true`."), s.pop()), s.filter((o) => o != null);
    }
    async generate({ inputs: e = null, generation_config: s = null, logits_processor: r = null, stopping_criteria: n = null, ...o }) {
      s = this._prepare_generation_config(s, o);
      let i = o.decoder_input_ids instanceof E ? jr2(o.decoder_input_ids) : o.decoder_input_ids ?? this._retrieve_init_tokens(s);
      if (s.return_timestamps && (r ??= new ps2(), r.push(new ol(s, i))), s.begin_suppress_tokens && (r ??= new ps2(), r.push(new Hs(s.begin_suppress_tokens, i.length))), s.return_token_timestamps) {
        if (!s.alignment_heads) throw new Error("Model generation config has no `alignment_heads`, token-level timestamps not available. See https://gist.github.com/hollance/42e32852f24243b748ae6bc1f985b13a on how to add this property to the generation config.");
        s.task === "translate" && F.warn("Token-level timestamps may not be reliable for task 'translate'."), s.output_attentions = true, s.return_dict_in_generate = true;
      }
      if (s.return_timestamps && !o.max_new_tokens) return this._generate_with_seek({ inputs: e, generation_config: s, logits_processor: r, init_tokens: i, kwargs: o });
      let a = await super.generate({ inputs: e, generation_config: s, logits_processor: r, decoder_input_ids: i, ...o });
      return s.return_token_timestamps && (a.token_timestamps = this._extract_token_timestamps(a, s.alignment_heads, s.num_frames, 0.02, i.length)), a;
    }
    async _generate_with_seek({ inputs: e, generation_config: s, logits_processor: r, init_tokens: n, kwargs: o }) {
      let i = s.no_timestamps_token_id + 1, a = Array.isArray(s.eos_token_id) ? s.eos_token_id[0] : s.eos_token_id, l = s.return_token_timestamps, c = e, p = c.dims[2], u = 2, _ = this.config.max_source_positions, d = u * _, m = 0, f = [], g = [];
      for (; m < p; ) {
        let x = Math.min(m + d, p), y = c.slice(null, null, [m, x]), b, v = y.dims[2];
        if (v < d) {
          let D = c.dims[1], A = new Float32Array(D * d), O = y.data;
          for (let T = 0; T < D; ++T) A.set(O.subarray(T * v, (T + 1) * v), T * d);
          b = new E("float32", A, [1, D, d]);
        } else b = y;
        if (r) for (let D of r) "begin_index" in D && (D.begin_index = n.length);
        let k2 = await super.generate({ inputs: b, generation_config: s, logits_processor: r, decoder_input_ids: n, ...o }), I = (l ? k2.sequences : k2)[0].tolist().map(Number).slice(n.length), $2;
        if (l) {
          k2.token_timestamps = this._extract_token_timestamps(k2, s.alignment_heads, Math.floor((x - m) / u), 0.02, n.length);
          let D = m / u * 0.02;
          $2 = k2.token_timestamps[0].tolist().slice(n.length).map((A) => A + D);
        }
        if (I.length > 0 && I.at(-1) === a && I.pop(), I.length === 0) break;
        let C = I.map((D) => D >= i), R = I.length >= 2 && C[I.length - 1] && !C[I.length - 2], V = [];
        for (let D = 0; D < I.length - 1; ++D) C[D] && C[D + 1] && V.push(D + 1);
        let H, j = I.length;
        if (V.length > 0) if (R) H = x - m;
        else {
          let D = V.at(-1);
          H = (I[D - 1] - i) * u, j = D;
        }
        else H = x - m;
        let B = Math.floor(m / u), Z = i + 1500;
        for (let D = 0; D < j; ++D) I[D] >= i && (I[D] = Math.min(I[D] + B, Z));
        f.push(...I.slice(0, j)), $2 && g.push(...$2.slice(0, j)), m += H;
      }
      f.push(a);
      let w = [...n, ...f];
      if (l) {
        let x = new E("int64", w.map(BigInt), [1, w.length]), y = [...new Array(n.length).fill(0), ...g, 0], b = new E("float32", new Float32Array(y), [1, y.length]);
        return { sequences: x, token_timestamps: b };
      }
      return new E("int64", w.map(BigInt), [1, w.length]);
    }
    _extract_token_timestamps(e, s, r = null, n = 0.02, o = 0) {
      if (!e.cross_attentions) throw new Error("Model outputs must contain cross attentions to extract timestamps. This is most likely because the model was not exported with `output_attentions=True`.");
      r == null && F.warn("`num_frames` has not been set, meaning the entire audio will be analyzed. This may lead to inaccurate token-level timestamps for short audios (< 30 seconds).");
      let i = this.config.median_filter_width;
      i === void 0 && (F.warn("Model config has no `median_filter_width`, using default value of 7."), i = 7);
      let a = e.cross_attentions, l = Array.from({ length: this.config.decoder_layers }, (w, x) => ie2(a.map((y) => y[x]), 2)), c = qe(s.map(([w, x]) => {
        if (w >= l.length) throw new Error(`Layer index ${w} is out of bounds for cross attentions (length ${l.length}).`);
        return r ? l[w].slice(null, x, null, [0, r]) : l[w].slice(null, x);
      })).transpose(1, 0, 2, 3), [p, u] = cp(c, -2, 0, true), _ = c.clone();
      for (let w = 0; w < _.dims[0]; ++w) {
        let x = _[w];
        for (let y = 0; y < x.dims[0]; ++y) {
          let b = x[y], v = p[w][y][0].data, k2 = u[w][y][0].data;
          for (let S = 0; S < b.dims[0]; ++S) {
            let I = b[S].data;
            for (let $2 = 0; $2 < I.length; ++$2) I[$2] = (I[$2] - k2[$2]) / v[$2];
            I.set(R0(I, i));
          }
        }
      }
      let d = o > 0 ? _.slice(null, null, [o, _.dims[2]], null) : _, m = [Ea2(d, 1)], f = e.sequences.dims, g = new E("float32", new Float32Array(f[0] * f[1]), f);
      for (let w = 0; w < f[0]; ++w) {
        let x = m[w].neg().squeeze_(0), [y, b] = q0(x.tolist()), v = Array.from({ length: y.length - 1 }, ($2, C) => y[C + 1] - y[C]), k2 = Re([1], v).map(($2) => !!$2), S = [];
        for (let $2 = 0; $2 < k2.length; ++$2) k2[$2] && S.push(b[$2] * n);
        let I = new Array(o).fill(0);
        I.push(...S), S.length > 0 && I.push(S.at(-1)), g[w].data.set(I);
      }
      return g;
    }
  };
  var hy = class extends gc2 {
  };
  var Zt2 = class extends h {
  };
  var gy = class extends Zt2 {
  };
  var xy = class extends Zt2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var wy = class extends Zt2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var yy = class extends Zt2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var by = class extends Zt2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var es2 = class extends h {
  };
  var ky = class extends es2 {
  };
  var vy = class extends es2 {
    async _call(e) {
      return new ne(await super._call(e));
    }
  };
  var Ey = class extends es2 {
    async _call(e) {
      return new z2(await super._call(e));
    }
  };
  var Ay = class extends es2 {
    async _call(e) {
      return new se(await super._call(e));
    }
  };
  var My = class extends es2 {
    async _call(e) {
      return new ue(await super._call(e));
    }
  };
  var Ai = class extends h {
  };
  var Sy = class extends Ai {
  };
  var Oy = class extends Ai {
    async _call(e) {
      return new xc(await super._call(e));
    }
  };
  var xc = class extends he {
    constructor({ logits: e, pred_boxes: s }) {
      super(), this.logits = e, this.pred_boxes = s;
    }
  };
  var Mi = class extends h {
  };
  var Iy = class extends Mi {
  };
  var zy = class extends Mi {
  };
  var kM = /* @__PURE__ */ new Map([["bert", "BertModel"], ["eurobert", "EuroBertModel"], ["neobert", "NeoBertModel"], ["modernbert", "ModernBertModel"], ["nomic_bert", "NomicBertModel"], ["roformer", "RoFormerModel"], ["electra", "ElectraModel"], ["esm", "EsmModel"], ["convbert", "ConvBertModel"], ["camembert", "CamembertModel"], ["deberta", "DebertaModel"], ["deberta-v2", "DebertaV2Model"], ["mpnet", "MPNetModel"], ["albert", "AlbertModel"], ["distilbert", "DistilBertModel"], ["roberta", "RobertaModel"], ["xlm", "XLMModel"], ["xlm-roberta", "XLMRobertaModel"], ["clap", "ClapModel"], ["clip", "CLIPModel"], ["clipseg", "CLIPSegModel"], ["chinese_clip", "ChineseCLIPModel"], ["siglip", "SiglipModel"], ["jina_clip", "JinaCLIPModel"], ["mobilebert", "MobileBertModel"], ["squeezebert", "SqueezeBertModel"], ["wav2vec2", "Wav2Vec2Model"], ["wav2vec2-bert", "Wav2Vec2BertModel"], ["unispeech", "UniSpeechModel"], ["unispeech-sat", "UniSpeechSatModel"], ["hubert", "HubertModel"], ["wavlm", "WavLMModel"], ["audio-spectrogram-transformer", "ASTModel"], ["vits", "VitsModel"], ["pyannote", "PyAnnoteModel"], ["wespeaker-resnet", "WeSpeakerResNetModel"], ["detr", "DetrModel"], ["rt_detr", "RTDetrModel"], ["rt_detr_v2", "RTDetrV2Model"], ["rf_detr", "RFDetrModel"], ["d_fine", "DFineModel"], ["table-transformer", "TableTransformerModel"], ["vit", "ViTModel"], ["ijepa", "IJepaModel"], ["pvt", "PvtModel"], ["vit_msn", "ViTMSNModel"], ["vit_mae", "ViTMAEModel"], ["groupvit", "GroupViTModel"], ["fastvit", "FastViTModel"], ["mobilevit", "MobileViTModel"], ["mobilevitv2", "MobileViTV2Model"], ["owlvit", "OwlViTModel"], ["owlv2", "Owlv2Model"], ["beit", "BeitModel"], ["deit", "DeiTModel"], ["hiera", "HieraModel"], ["convnext", "ConvNextModel"], ["convnextv2", "ConvNextV2Model"], ["dinov2", "Dinov2Model"], ["dinov2_with_registers", "Dinov2WithRegistersModel"], ["dinov3_vit", "DINOv3ViTModel"], ["dinov3_convnext", "DINOv3ConvNextModel"], ["resnet", "ResNetModel"], ["swin", "SwinModel"], ["swin2sr", "Swin2SRModel"], ["donut-swin", "DonutSwinModel"], ["yolos", "YolosModel"], ["dpt", "DPTModel"], ["glpn", "GLPNModel"], ["hifigan", "SpeechT5HifiGan"], ["efficientnet", "EfficientNetModel"], ["decision_transformer", "DecisionTransformerModel"], ["patchtst", "PatchTSTModel"], ["patchtsmixer", "PatchTSMixerModel"], ["mobilenet_v1", "MobileNetV1Model"], ["mobilenet_v2", "MobileNetV2Model"], ["mobilenet_v3", "MobileNetV3Model"], ["mobilenet_v4", "MobileNetV4Model"], ["maskformer", "MaskFormerModel"], ["mgp-str", "MgpstrForSceneTextRecognition"], ["style_text_to_speech_2", "StyleTextToSpeech2Model"], ["openai_privacy_filter", "OpenAIPrivacyFilterModel"]]);
  var vM = /* @__PURE__ */ new Map([["t5", "T5Model"], ["longt5", "LongT5Model"], ["mt5", "MT5Model"], ["bart", "BartModel"], ["mbart", "MBartModel"], ["marian", "MarianModel"], ["whisper", "WhisperModel"], ["cohere_asr", "CohereAsrModel"], ["m2m_100", "M2M100Model"], ["blenderbot", "BlenderbotModel"], ["blenderbot-small", "BlenderbotSmallModel"]]);
  var EM = /* @__PURE__ */ new Map([["mimi", "MimiModel"], ["dac", "DacModel"], ["snac", "SnacModel"]]);
  var AM = /* @__PURE__ */ new Map([["bloom", "BloomModel"], ["jais", "JAISModel"], ["gpt2", "GPT2Model"], ["gpt_oss", "GptOssModel"], ["gptj", "GPTJModel"], ["gpt_bigcode", "GPTBigCodeModel"], ["gpt_neo", "GPTNeoModel"], ["gpt_neox", "GPTNeoXModel"], ["codegen", "CodeGenModel"], ["llama", "LlamaModel"], ["apertus", "ApertusModel"], ["nanochat", "NanoChatModel"], ["arcee", "ArceeModel"], ["afmoe", "AfmoeModel"], ["lfm2", "Lfm2Model"], ["lfm2_moe", "Lfm2MoeModel"], ["smollm3", "SmolLM3Model"], ["exaone", "ExaoneModel"], ["olmo", "OlmoModel"], ["olmo2", "Olmo2Model"], ["olmo3", "Olmo3Model"], ["olmo_hybrid", "OlmoHybridModel"], ["mobilellm", "MobileLLMModel"], ["granite", "GraniteModel"], ["granitemoehybrid", "GraniteMoeHybridModel"], ["cohere", "CohereModel"], ["cohere2", "Cohere2Model"], ["gemma", "GemmaModel"], ["gemma2", "Gemma2Model"], ["vaultgemma", "VaultGemmaModel"], ["gemma3_text", "Gemma3Model"], ["helium", "HeliumModel"], ["glm", "GlmModel"], ["glm_moe_dsa", "GlmMoeDsaModel"], ["openelm", "OpenELMModel"], ["qwen2", "Qwen2Model"], ["qwen2_moe", "Qwen2MoeModel"], ["qwen3", "Qwen3Model"], ["qwen3_moe", "Qwen3MoeModel"], ["qwen3_next", "Qwen3NextModel"], ["phi", "PhiModel"], ["phi3", "Phi3Model"], ["mpt", "MptModel"], ["opt", "OPTModel"], ["mistral", "MistralModel"], ["mistral4", "Mistral4Model"], ["ministral", "MinistralModel"], ["ministral3", "Ministral3Model"], ["ernie4_5", "Ernie4_5ForCausalLM"], ["starcoder2", "Starcoder2Model"], ["deepseek_v3", "DeepseekV3Model"], ["falcon", "FalconModel"], ["falcon_h1", "FalconH1Model"], ["nemotron_h", "NemotronHModel"], ["solar_open", "SolarOpenModel"], ["stablelm", "StableLmModel"], ["modernbert-decoder", "ModernBertDecoderModel"], ["hunyuan_v1_dense", "HunYuanDenseV1Model"], ["youtu", "YoutuModel"]]);
  var Rb = /* @__PURE__ */ new Map([["speecht5", "SpeechT5ForSpeechToText"], ["whisper", "WhisperForConditionalGeneration"], ["lite-whisper", "LiteWhisperForConditionalGeneration"], ["moonshine", "MoonshineForConditionalGeneration"], ["cohere_asr", "CohereAsrForConditionalGeneration"]]);
  var Db = /* @__PURE__ */ new Map([["speecht5", "SpeechT5ForTextToSpeech"]]);
  var qb = /* @__PURE__ */ new Map([["vits", "VitsModel"], ["musicgen", "MusicgenForConditionalGeneration"], ["supertonic", "SupertonicForConditionalGeneration"]]);
  var jb = /* @__PURE__ */ new Map([["bert", "BertForSequenceClassification"], ["eurobert", "EuroBertForSequenceClassification"], ["neobert", "NeoBertForSequenceClassification"], ["modernbert", "ModernBertForSequenceClassification"], ["roformer", "RoFormerForSequenceClassification"], ["electra", "ElectraForSequenceClassification"], ["esm", "EsmForSequenceClassification"], ["convbert", "ConvBertForSequenceClassification"], ["camembert", "CamembertForSequenceClassification"], ["deberta", "DebertaForSequenceClassification"], ["deberta-v2", "DebertaV2ForSequenceClassification"], ["mpnet", "MPNetForSequenceClassification"], ["albert", "AlbertForSequenceClassification"], ["distilbert", "DistilBertForSequenceClassification"], ["roberta", "RobertaForSequenceClassification"], ["xlm", "XLMForSequenceClassification"], ["xlm-roberta", "XLMRobertaForSequenceClassification"], ["bart", "BartForSequenceClassification"], ["mbart", "MBartForSequenceClassification"], ["mobilebert", "MobileBertForSequenceClassification"], ["squeezebert", "SqueezeBertForSequenceClassification"]]);
  var Bb = /* @__PURE__ */ new Map([["bert", "BertForTokenClassification"], ["eurobert", "EuroBertForTokenClassification"], ["neobert", "NeoBertForTokenClassification"], ["modernbert", "ModernBertForTokenClassification"], ["roformer", "RoFormerForTokenClassification"], ["electra", "ElectraForTokenClassification"], ["esm", "EsmForTokenClassification"], ["convbert", "ConvBertForTokenClassification"], ["camembert", "CamembertForTokenClassification"], ["deberta", "DebertaForTokenClassification"], ["deberta-v2", "DebertaV2ForTokenClassification"], ["mpnet", "MPNetForTokenClassification"], ["distilbert", "DistilBertForTokenClassification"], ["roberta", "RobertaForTokenClassification"], ["xlm", "XLMForTokenClassification"], ["xlm-roberta", "XLMRobertaForTokenClassification"], ["openai_privacy_filter", "OpenAIPrivacyFilterForTokenClassification"]]);
  var Ub = /* @__PURE__ */ new Map([["t5", "T5ForConditionalGeneration"], ["longt5", "LongT5ForConditionalGeneration"], ["mt5", "MT5ForConditionalGeneration"], ["bart", "BartForConditionalGeneration"], ["mbart", "MBartForConditionalGeneration"], ["marian", "MarianMTModel"], ["m2m_100", "M2M100ForConditionalGeneration"], ["blenderbot", "BlenderbotForConditionalGeneration"], ["blenderbot-small", "BlenderbotSmallForConditionalGeneration"]]);
  var Gb = /* @__PURE__ */ new Map([["bloom", "BloomForCausalLM"], ["gpt2", "GPT2LMHeadModel"], ["gpt_oss", "GptOssForCausalLM"], ["jais", "JAISLMHeadModel"], ["gptj", "GPTJForCausalLM"], ["gpt_bigcode", "GPTBigCodeForCausalLM"], ["gpt_neo", "GPTNeoForCausalLM"], ["gpt_neox", "GPTNeoXForCausalLM"], ["codegen", "CodeGenForCausalLM"], ["llama", "LlamaForCausalLM"], ["nanochat", "NanoChatForCausalLM"], ["apertus", "ApertusForCausalLM"], ["llama4_text", "Llama4ForCausalLM"], ["arcee", "ArceeForCausalLM"], ["afmoe", "AfmoeForCausalLM"], ["lfm2", "Lfm2ForCausalLM"], ["lfm2_moe", "Lfm2MoeForCausalLM"], ["smollm3", "SmolLM3ForCausalLM"], ["exaone", "ExaoneForCausalLM"], ["olmo", "OlmoForCausalLM"], ["olmo2", "Olmo2ForCausalLM"], ["olmo3", "Olmo3ForCausalLM"], ["olmo_hybrid", "OlmoHybridForCausalLM"], ["mobilellm", "MobileLLMForCausalLM"], ["granite", "GraniteForCausalLM"], ["granitemoehybrid", "GraniteMoeHybridForCausalLM"], ["cohere", "CohereForCausalLM"], ["cohere2", "Cohere2ForCausalLM"], ["gemma", "GemmaForCausalLM"], ["gemma2", "Gemma2ForCausalLM"], ["vaultgemma", "VaultGemmaForCausalLM"], ["gemma3_text", "Gemma3ForCausalLM"], ["gemma3", "Gemma3ForCausalLM"], ["helium", "HeliumForCausalLM"], ["glm", "GlmForCausalLM"], ["glm_moe_dsa", "GlmMoeDsaForCausalLM"], ["openelm", "OpenELMForCausalLM"], ["qwen2", "Qwen2ForCausalLM"], ["qwen2_moe", "Qwen2MoeForCausalLM"], ["qwen3", "Qwen3ForCausalLM"], ["qwen3_moe", "Qwen3MoeForCausalLM"], ["qwen3_next", "Qwen3NextForCausalLM"], ["qwen2_vl", "Qwen2VLForCausalLM"], ["qwen2_5_vl", "Qwen2_5_VLForCausalLM"], ["qwen3_vl", "Qwen3VLForCausalLM"], ["qwen3_vl_moe", "Qwen3VLMoeForCausalLM"], ["qwen3_5", "Qwen3_5ForCausalLM"], ["qwen3_5_text", "Qwen3_5ForCausalLM"], ["qwen3_5_moe", "Qwen3_5MoeForCausalLM"], ["gemma3n", "Gemma3nForCausalLM"], ["gemma4", "Gemma4ForCausalLM"], ["phi", "PhiForCausalLM"], ["phi3", "Phi3ForCausalLM"], ["mpt", "MptForCausalLM"], ["opt", "OPTForCausalLM"], ["mbart", "MBartForCausalLM"], ["mistral", "MistralForCausalLM"], ["mistral4", "Mistral4ForCausalLM"], ["ministral", "MinistralForCausalLM"], ["ministral3", "Ministral3ForCausalLM"], ["ernie4_5", "Ernie4_5ForCausalLM"], ["starcoder2", "Starcoder2ForCausalLM"], ["deepseek_v3", "DeepseekV3ForCausalLM"], ["falcon", "FalconForCausalLM"], ["falcon_h1", "FalconH1ForCausalLM"], ["nemotron_h", "NemotronHForCausalLM"], ["trocr", "TrOCRForCausalLM"], ["solar_open", "SolarOpenForCausalLM"], ["stablelm", "StableLmForCausalLM"], ["modernbert-decoder", "ModernBertDecoderForCausalLM"], ["hunyuan_v1_dense", "HunYuanDenseV1ForCausalLM"], ["youtu", "YoutuForCausalLM"], ["phi3_v", "Phi3VForCausalLM"]]);
  var MM = /* @__PURE__ */ new Map([["multi_modality", "MultiModalityCausalLM"]]);
  var Wb = /* @__PURE__ */ new Map([["bert", "BertForMaskedLM"], ["eurobert", "EuroBertForMaskedLM"], ["neobert", "NeoBertForMaskedLM"], ["modernbert", "ModernBertForMaskedLM"], ["roformer", "RoFormerForMaskedLM"], ["electra", "ElectraForMaskedLM"], ["esm", "EsmForMaskedLM"], ["convbert", "ConvBertForMaskedLM"], ["camembert", "CamembertForMaskedLM"], ["deberta", "DebertaForMaskedLM"], ["deberta-v2", "DebertaV2ForMaskedLM"], ["mpnet", "MPNetForMaskedLM"], ["albert", "AlbertForMaskedLM"], ["distilbert", "DistilBertForMaskedLM"], ["roberta", "RobertaForMaskedLM"], ["xlm", "XLMWithLMHeadModel"], ["xlm-roberta", "XLMRobertaForMaskedLM"], ["mobilebert", "MobileBertForMaskedLM"], ["squeezebert", "SqueezeBertForMaskedLM"]]);
  var Vb = /* @__PURE__ */ new Map([["bert", "BertForQuestionAnswering"], ["neobert", "NeoBertForQuestionAnswering"], ["roformer", "RoFormerForQuestionAnswering"], ["electra", "ElectraForQuestionAnswering"], ["convbert", "ConvBertForQuestionAnswering"], ["camembert", "CamembertForQuestionAnswering"], ["deberta", "DebertaForQuestionAnswering"], ["deberta-v2", "DebertaV2ForQuestionAnswering"], ["mpnet", "MPNetForQuestionAnswering"], ["albert", "AlbertForQuestionAnswering"], ["distilbert", "DistilBertForQuestionAnswering"], ["roberta", "RobertaForQuestionAnswering"], ["xlm", "XLMForQuestionAnswering"], ["xlm-roberta", "XLMRobertaForQuestionAnswering"], ["mobilebert", "MobileBertForQuestionAnswering"], ["squeezebert", "SqueezeBertForQuestionAnswering"]]);
  var Hb = /* @__PURE__ */ new Map([["vision-encoder-decoder", "VisionEncoderDecoderModel"], ["idefics3", "Idefics3ForConditionalGeneration"], ["smolvlm", "SmolVLMForConditionalGeneration"]]);
  var Kb = /* @__PURE__ */ new Map([["llava", "LlavaForConditionalGeneration"], ["llava_onevision", "LlavaOnevisionForConditionalGeneration"], ["moondream1", "Moondream1ForConditionalGeneration"], ["florence2", "Florence2ForConditionalGeneration"], ["qwen2_vl", "Qwen2VLForConditionalGeneration"], ["qwen2_5_vl", "Qwen2_5_VLForConditionalGeneration"], ["qwen3_vl", "Qwen3VLForConditionalGeneration"], ["qwen3_vl_moe", "Qwen3VLMoeForConditionalGeneration"], ["qwen3_5", "Qwen3_5ForConditionalGeneration"], ["qwen3_5_moe", "Qwen3_5MoeForConditionalGeneration"], ["lfm2_vl", "Lfm2VlForConditionalGeneration"], ["idefics3", "Idefics3ForConditionalGeneration"], ["smolvlm", "SmolVLMForConditionalGeneration"], ["paligemma", "PaliGemmaForConditionalGeneration"], ["llava_qwen2", "LlavaQwen2ForCausalLM"], ["gemma3", "Gemma3ForConditionalGeneration"], ["gemma3n", "Gemma3nForConditionalGeneration"], ["gemma4", "Gemma4ForConditionalGeneration"], ["mistral3", "Mistral3ForConditional" + "Generation"], ["lighton_ocr", "LightOnOcrForConditionalGeneration"], ["glm_ocr", "GlmOcrForConditionalGeneration"]]);
  var Xb = /* @__PURE__ */ new Map([["granite_speech", "GraniteSpeechForConditionalGeneration"], ["ultravox", "UltravoxModel"], ["voxtral", "VoxtralForConditionalGeneration"], ["voxtral_realtime", "VoxtralRealtimeForConditionalGeneration"]]);
  var SM = /* @__PURE__ */ new Map([["vision-encoder-decoder", "VisionEncoderDecoderModel"]]);
  var Qb = /* @__PURE__ */ new Map([["vit", "ViTForImageClassification"], ["ijepa", "IJepaForImageClassification"], ["pvt", "PvtForImageClassification"], ["vit_msn", "ViTMSNForImageClassification"], ["fastvit", "FastViTForImageClassification"], ["mobilevit", "MobileViTForImageClassification"], ["mobilevitv2", "MobileViTV2ForImageClassification"], ["beit", "BeitForImageClassification"], ["deit", "DeiTForImageClassification"], ["hiera", "HieraForImageClassification"], ["convnext", "ConvNextForImageClassification"], ["convnextv2", "ConvNextV2ForImageClassification"], ["dinov2", "Dinov2ForImageClassification"], ["dinov2_with_registers", "Dinov2WithRegistersForImageClassification"], ["resnet", "ResNetForImageClassification"], ["swin", "SwinForImageClassification"], ["segformer", "SegformerForImageClassification"], ["efficientnet", "EfficientNetForImageClassification"], ["mobilenet_v1", "MobileNetV1ForImageClassification"], ["mobilenet_v2", "MobileNetV2ForImageClassification"], ["mobilenet_v3", "MobileNetV3ForImageClassification"], ["mobilenet_v4", "MobileNetV4ForImageClassification"]]);
  var Yb = /* @__PURE__ */ new Map([["detr", "DetrForObjectDetection"], ["rt_detr", "RTDetrForObjectDetection"], ["rt_detr_v2", "RTDetrV2ForObjectDetection"], ["rf_detr", "RFDetrForObjectDetection"], ["d_fine", "DFineForObjectDetection"], ["table-transformer", "TableTransformerForObjectDetection"], ["yolos", "YolosForObjectDetection"]]);
  var Jb = /* @__PURE__ */ new Map([["owlvit", "OwlViTForObjectDetection"], ["owlv2", "Owlv2ForObjectDetection"], ["grounding-dino", "GroundingDinoForObjectDetection"]]);
  var kr = /* @__PURE__ */ new Map([["detr", "DetrForSegmentation"], ["clipseg", "CLIPSegForImageSegmentation"]]);
  var Zb = /* @__PURE__ */ new Map([["segformer", "SegformerForSemanticSegmentation"], ["sapiens", "SapiensForSemanticSegmentation"], ["swin", "SwinForSemanticSegmentation"], ["mobilenet_v1", "MobileNetV1ForSemanticSegmentation"], ["mobilenet_v2", "MobileNetV2ForSemanticSegmentation"], ["mobilenet_v3", "MobileNetV3ForSemanticSegmentation"], ["mobilenet_v4", "MobileNetV4ForSemanticSegmentation"]]);
  var ek = /* @__PURE__ */ new Map([["detr", "DetrForSegmentation"], ["maskformer", "MaskFormerForInstanceSegmentation"]]);
  var tk = /* @__PURE__ */ new Map([["sam", "SamModel"], ["sam2", "Sam2Model"], ["edgetam", "EdgeTamModel"], ["sam3_tracker", "Sam3TrackerModel"]]);
  var sk = /* @__PURE__ */ new Map([["wav2vec2", "Wav2Vec2ForCTC"], ["wav2vec2-bert", "Wav2Vec2BertForCTC"], ["unispeech", "UniSpeechForCTC"], ["unispeech-sat", "UniSpeechSatForCTC"], ["wavlm", "WavLMForCTC"], ["hubert", "HubertForCTC"], ["parakeet_ctc", "ParakeetForCTC"]]);
  var rk = /* @__PURE__ */ new Map([["wav2vec2", "Wav2Vec2ForSequenceClassification"], ["wav2vec2-bert", "Wav2Vec2BertForSequenceClassification"], ["unispeech", "UniSpeechForSequenceClassification"], ["unispeech-sat", "UniSpeechSatForSequenceClassification"], ["wavlm", "WavLMForSequenceClassification"], ["hubert", "HubertForSequenceClassification"], ["audio-spectrogram-transformer", "ASTForAudioClassification"]]);
  var nk = /* @__PURE__ */ new Map([["wavlm", "WavLMForXVector"]]);
  var ok = /* @__PURE__ */ new Map([["unispeech-sat", "UniSpeechSatForAudioFrameClassification"], ["wavlm", "WavLMForAudioFrameClassification"], ["wav2vec2", "Wav2Vec2ForAudioFrameClassification"], ["pyannote", "PyAnnoteForAudioFrameClassification"]]);
  var ik = /* @__PURE__ */ new Map([["vitmatte", "VitMatteForImageMatting"]]);
  var OM = /* @__PURE__ */ new Map([["patchtst", "PatchTSTForPrediction"], ["patchtsmixer", "PatchTSMixerForPrediction"]]);
  var ak = /* @__PURE__ */ new Map([["swin2sr", "Swin2SRForImageSuperResolution"]]);
  var lk = /* @__PURE__ */ new Map([["chmv2", "CHMv2ForDepthEstimation"], ["dpt", "DPTForDepthEstimation"], ["depth_anything", "DepthAnythingForDepthEstimation"], ["glpn", "GLPNForDepthEstimation"], ["sapiens", "SapiensForDepthEstimation"], ["depth_pro", "DepthProForDepthEstimation"], ["metric3d", "Metric3DForDepthEstimation"], ["metric3dv2", "Metric3Dv2ForDepthEstimation"]]);
  var ck = /* @__PURE__ */ new Map([["sapiens", "SapiensForNormalEstimation"]]);
  var pk = /* @__PURE__ */ new Map([["vitpose", "VitPoseForPoseEstimation"]]);
  var uk = /* @__PURE__ */ new Map([["clip", "CLIPVisionModelWithProjection"], ["siglip", "SiglipVisionModel"], ["jina_clip", "JinaCLIPVisionModel"]]);
  var Ty = [[kM, N.EncoderOnly], [vM, N.EncoderDecoder], [AM, N.DecoderOnlyWithoutHead], [EM, N.AutoEncoder], [jb, N.EncoderOnly], [Bb, N.EncoderOnly], [Ub, N.Seq2Seq], [Rb, N.Seq2Seq], [Gb, N.DecoderOnly], [MM, N.MultiModality], [Wb, N.EncoderOnly], [Vb, N.EncoderOnly], [Hb, N.Vision2Seq], [Kb, N.ImageTextToText], [Xb, N.AudioTextToText], [Qb, N.EncoderOnly], [kr, N.EncoderOnly], [ek, N.EncoderOnly], [Zb, N.EncoderOnly], [ik, N.EncoderOnly], [OM, N.EncoderOnly], [ak, N.EncoderOnly], [lk, N.EncoderOnly], [ck, N.EncoderOnly], [pk, N.EncoderOnly], [Yb, N.EncoderOnly], [Jb, N.EncoderOnly], [tk, N.MaskGeneration], [sk, N.EncoderOnly], [rk, N.EncoderOnly], [Db, N.Seq2Seq], [qb, N.EncoderOnly], [nk, N.EncoderOnly], [ok, N.EncoderOnly], [uk, N.EncoderOnly]];
  for (let [t6, e] of Ty) for (let s of t6.values()) {
    ct.set(s, e);
    let r = Si[s];
    ds2.set(r, s), xl.set(s, r);
  }
  var IM = [["MusicgenForConditionalGeneration", Co, N.Musicgen], ["Phi3VForCausalLM", Ko, N.Phi3V], ["CLIPTextModelWithProjection", bn, N.EncoderOnly], ["SiglipTextModel", ci, N.EncoderOnly], ["JinaCLIPTextModel", uo, N.EncoderOnly], ["ClapTextModelWithProjection", wn, N.EncoderOnly], ["ClapAudioModelWithProjection", yn, N.EncoderOnly], ["DacEncoderModel", Tn, N.EncoderOnly], ["DacDecoderModel", Cn, N.EncoderOnly], ["MimiEncoderModel", yo, N.EncoderOnly], ["MimiDecoderModel", bo, N.EncoderOnly], ["SnacEncoderModel", ui, N.EncoderOnly], ["SnacDecoderModel", _i, N.EncoderOnly], ["Gemma3nForConditionalGeneration", Ht2, N.ImageAudioTextToText], ["Gemma4ForConditionalGeneration", ir2, N.ImageAudioTextToText], ["SupertonicForConditionalGeneration", hi, N.Supertonic], ["ChatterboxModel", xn, N.Chatterbox], ["VoxtralRealtimeForConditionalGeneration", vi, N.VoxtralRealtime]];
  for (let [t6, e, s] of IM) ct.set(t6, s), ds2.set(e, t6), xl.set(t6, e);
  var _k = /* @__PURE__ */ new Map([["modnet", kr], ["birefnet", kr], ["isnet", kr], ["ben", kr]]);
  for (let [t6, e] of _k.entries()) e.set(t6, "PreTrainedModel"), ct.set(t6, N.EncoderOnly), xl.set(t6, h);
  var dk = new Set(_k.keys());
  ct.set("PreTrainedModel", N.EncoderOnly);
  ds2.set(h, "PreTrainedModel");
  var fe = { MODEL_FOR_SEQUENCE_CLASSIFICATION_MAPPING_NAMES: jb, MODEL_FOR_TOKEN_CLASSIFICATION_MAPPING_NAMES: Bb, MODEL_FOR_TEXT_TO_SPECTROGRAM_MAPPING_NAMES: Db, MODEL_FOR_TEXT_TO_WAVEFORM_MAPPING_NAMES: qb, MODEL_FOR_MASKED_LM_MAPPING_NAMES: Wb, MODEL_FOR_QUESTION_ANSWERING_MAPPING_NAMES: Vb, MODEL_FOR_IMAGE_CLASSIFICATION_MAPPING_NAMES: Qb, MODEL_FOR_IMAGE_SEGMENTATION_MAPPING_NAMES: kr, MODEL_FOR_SEMANTIC_SEGMENTATION_MAPPING_NAMES: Zb, MODEL_FOR_UNIVERSAL_SEGMENTATION_MAPPING_NAMES: ek, MODEL_FOR_OBJECT_DETECTION_MAPPING_NAMES: Yb, MODEL_FOR_ZERO_SHOT_OBJECT_DETECTION_MAPPING_NAMES: Jb, MODEL_FOR_MASK_GENERATION_MAPPING_NAMES: tk, MODEL_FOR_CTC_MAPPING_NAMES: sk, MODEL_FOR_AUDIO_CLASSIFICATION_MAPPING_NAMES: rk, MODEL_FOR_AUDIO_XVECTOR_MAPPING_NAMES: nk, MODEL_FOR_AUDIO_FRAME_CLASSIFICATION_MAPPING_NAMES: ok, MODEL_FOR_DOCUMENT_QUESTION_ANSWERING_MAPPING_NAMES: SM, MODEL_FOR_IMAGE_MATTING_MAPPING_NAMES: ik, MODEL_FOR_IMAGE_TO_IMAGE_MAPPING_NAMES: ak, MODEL_FOR_DEPTH_ESTIMATION_MAPPING_NAMES: lk, MODEL_FOR_NORMAL_ESTIMATION_MAPPING_NAMES: ck, MODEL_FOR_POSE_ESTIMATION_MAPPING_NAMES: pk, MODEL_FOR_IMAGE_FEATURE_EXTRACTION_MAPPING_NAMES: uk, MODEL_FOR_IMAGE_TEXT_TO_TEXT_MAPPING_NAMES: Kb, MODEL_FOR_AUDIO_TEXT_TO_TEXT_MAPPING_NAMES: Xb, MODEL_FOR_SEQ_TO_SEQ_CAUSAL_LM_MAPPING_NAMES: Ub, MODEL_FOR_SPEECH_SEQ_2_SEQ_MAPPING_NAMES: Rb, MODEL_FOR_CAUSAL_LM_MAPPING_NAMES: Gb, MODEL_FOR_VISION_2_SEQ_MAPPING_NAMES: Hb };
  Pb(fe);
  var _e = class {
    static MODEL_CLASS_MAPPINGS = null;
    static BASE_IF_FAIL = false;
    static supports(e) {
      if (!this.MODEL_CLASS_MAPPINGS) return false;
      for (let s of this.MODEL_CLASS_MAPPINGS) if (s.has(e)) return true;
      return this.BASE_IF_FAIL;
    }
    static async from_pretrained(e, { progress_callback: s = null, config: r = null, cache_dir: n = null, local_files_only: o = false, revision: i = "main", model_file_name: a = null, subfolder: l = "onnx", device: c = null, dtype: p = null, use_external_data_format: u = null, session_options: _ = {} } = {}) {
      let d = { progress_callback: s, config: r, cache_dir: n, local_files_only: o, revision: i, model_file_name: a, subfolder: l, device: c, dtype: p, use_external_data_format: u, session_options: _ };
      if (d.config = await tt2.from_pretrained(e, d), !this.MODEL_CLASS_MAPPINGS) throw new Error("`MODEL_CLASS_MAPPINGS` not implemented for this type of `AutoClass`: " + this.name);
      let { model_type: m } = d.config;
      for (let f of this.MODEL_CLASS_MAPPINGS) {
        let g = f.get(m);
        if (!g) {
          for (let w of f.values()) if (w[0] === m) {
            g = w;
            break;
          }
          if (!g) continue;
        }
        return await Si[g].from_pretrained(e, d);
      }
      if (this.BASE_IF_FAIL) return dk.has(m) || F.warn(`Unknown model class "${m}", attempting to construct from base class.`), await h.from_pretrained(e, d);
      throw Error(`Unsupported model type: ${m}`);
    }
  };
  var kt = class extends _e {
    static MODEL_CLASS_MAPPINGS = Ty.map((e) => e[0]);
    static BASE_IF_FAIL = true;
  };
  var Oi = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_SEQUENCE_CLASSIFICATION_MAPPING_NAMES];
  };
  var wc2 = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_TOKEN_CLASSIFICATION_MAPPING_NAMES];
  };
  var vr = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_SEQ_TO_SEQ_CAUSAL_LM_MAPPING_NAMES];
  };
  var yc2 = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_SPEECH_SEQ_2_SEQ_MAPPING_NAMES];
  };
  var bc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_TEXT_TO_SPECTROGRAM_MAPPING_NAMES];
  };
  var kc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_TEXT_TO_WAVEFORM_MAPPING_NAMES];
  };
  var vc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_CAUSAL_LM_MAPPING_NAMES];
  };
  var Ec = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_MASKED_LM_MAPPING_NAMES];
  };
  var Ac = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_QUESTION_ANSWERING_MAPPING_NAMES];
  };
  var Mc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_VISION_2_SEQ_MAPPING_NAMES];
  };
  var Sc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_IMAGE_CLASSIFICATION_MAPPING_NAMES];
  };
  var Ii = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_IMAGE_SEGMENTATION_MAPPING_NAMES];
  };
  var zi = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_SEMANTIC_SEGMENTATION_MAPPING_NAMES];
  };
  var Ti = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_UNIVERSAL_SEGMENTATION_MAPPING_NAMES];
  };
  var Oc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_OBJECT_DETECTION_MAPPING_NAMES];
  };
  var Ic = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_ZERO_SHOT_OBJECT_DETECTION_MAPPING_NAMES];
  };
  var fk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_MASK_GENERATION_MAPPING_NAMES];
  };
  var zc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_CTC_MAPPING_NAMES];
  };
  var Tc2 = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_AUDIO_CLASSIFICATION_MAPPING_NAMES];
  };
  var mk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_AUDIO_XVECTOR_MAPPING_NAMES];
  };
  var hk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_AUDIO_FRAME_CLASSIFICATION_MAPPING_NAMES];
  };
  var Cc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_DOCUMENT_QUESTION_ANSWERING_MAPPING_NAMES];
  };
  var gk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_IMAGE_MATTING_MAPPING_NAMES];
  };
  var Pc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_IMAGE_TO_IMAGE_MAPPING_NAMES];
  };
  var Nc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_DEPTH_ESTIMATION_MAPPING_NAMES];
  };
  var xk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_NORMAL_ESTIMATION_MAPPING_NAMES];
  };
  var wk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_POSE_ESTIMATION_MAPPING_NAMES];
  };
  var Lc = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_IMAGE_FEATURE_EXTRACTION_MAPPING_NAMES];
  };
  var yk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_IMAGE_TEXT_TO_TEXT_MAPPING_NAMES];
  };
  var bk = class extends _e {
    static MODEL_CLASS_MAPPINGS = [fe.MODEL_FOR_AUDIO_TEXT_TO_TEXT_MAPPING_NAMES];
  };
  async function Se(t6) {
    return Array.isArray(t6) || (t6 = [t6]), await Promise.all(t6.map((e) => Ee2.read(e)));
  }
  async function vt(t6, e) {
    return Array.isArray(t6) || (t6 = [t6]), await Promise.all(t6.map((s) => typeof s == "string" || s instanceof URL ? au(s, e) : s instanceof Float64Array ? new Float32Array(s) : s));
  }
  function Ci(t6, e) {
    e && (t6 = t6.map((i) => i | 0));
    let [s, r, n, o] = t6;
    return { xmin: s, ymin: r, xmax: n, ymax: o };
  }
  var Y = class extends xe {
    constructor({ task: e, model: s, tokenizer: r = null, processor: n = null }) {
      super(), this.task = e, this.model = s, this.tokenizer = r, this.processor = n;
    }
    async dispose() {
      await this.model.dispose();
    }
  };
  var Pi = class extends Y {
    async _call(e, { top_k: s = 1 } = {}) {
      let r = this.tokenizer(e, { padding: true, truncation: true }), n = await this.model(r), { problem_type: o, id2label: i } = this.model.config, a = o === "multi_label_classification" ? (c) => c.sigmoid() : (c) => new E("float32", me(c.data), c.dims), l = [];
      for (let c of n.logits) {
        let p = a(c), u = await lt(p, s), _ = u[0].tolist(), m = u[1].tolist().map((f, g) => ({ label: i ? i[f] : `LABEL_${f}`, score: _[g] }));
        s === 1 ? l.push(...m) : l.push(m);
      }
      return Array.isArray(e) || s === 1 ? l : l[0];
    }
  };
  var Ni = class extends Y {
    async _call(e, { ignore_labels: s = ["O"], aggregation_strategy: r = "none" } = {}) {
      if (r !== "none" && r !== "simple") throw new Error(`Invalid aggregation_strategy: "${r}". Must be one of "none" or "simple".`);
      let n = Array.isArray(e), o = this.tokenizer(n ? e : [e], { padding: true, truncation: true }), a = (await this.model(o)).logits, l = this.model.config.id2label, c = [];
      for (let p = 0; p < a.dims[0]; ++p) {
        let u = o.input_ids[p].tolist(), _ = a[p], d = [];
        for (let m = 0; m < _.dims[0]; ++m) {
          let f = _[m], g = de(f.data)[1], w = l ? l[g] : `LABEL_${g}`;
          if (s.includes(w)) continue;
          let x = this.tokenizer.decode([u[m]], { skip_special_tokens: true });
          if (x === "") continue;
          let y = me(f.data);
          d.push({ entity: w, score: y[g], index: m, word: x });
        }
        c.push(r === "simple" ? TM(d, u, this.tokenizer) : d);
      }
      return n ? c : c[0];
    }
  };
  function zM(t6) {
    let e = t6[0];
    return t6[1] === "-" && (e === "B" || e === "I" || e === "E" || e === "S") ? [e, t6.slice(2)] : ["I", t6];
  }
  function TM(t6, e, s) {
    let r = [], n = null;
    for (let o = 0; o < t6.length; ++o) {
      let [i, a] = zM(t6[o].entity);
      n === a && i !== "B" && i !== "S" ? (r[r.length - 1].end = o + 1, i === "E" && (n = null)) : (r.push({ tag: a, start: o, end: o + 1 }), n = i === "S" ? null : a);
    }
    return r.map(({ tag: o, start: i, end: a }) => {
      let l = 0, c = [];
      for (let p = i; p < a; ++p) l += t6[p].score, c.push(e[t6[p].index]);
      return { entity_group: o, score: l / (a - i), word: s.decode(c, { skip_special_tokens: true }) };
    });
  }
  var Li = class extends Y {
    async _call(e, s, { top_k: r = 1 } = {}) {
      let n = this.tokenizer(e, { text_pair: s, padding: true, truncation: true }), o = Array.isArray(e), { start_logits: i, end_logits: a } = await this.model(n), l = n.input_ids.tolist(), c = n.attention_mask.tolist(), { all_special_ids: p, sep_token_id: u } = this.tokenizer, _ = [];
      for (let d = 0; d < i.dims[0]; ++d) {
        let m = l[d], f = m.findIndex((k2) => k2 == u), g = i[d].tolist(), w = a[d].tolist();
        for (let k2 = 1; k2 < g.length; ++k2) (c[d] == 0 || k2 <= f || p.findIndex((S) => S == m[k2]) !== -1) && (g[k2] = -1 / 0, w[k2] = -1 / 0);
        let x = me(g).map((k2, S) => [k2, S]), y = me(w).map((k2, S) => [k2, S]);
        x[0][0] = 0, y[0][0] = 0;
        let b = Hy(x, y).filter((k2) => k2[0][1] <= k2[1][1]).map((k2) => [k2[0][1], k2[1][1], k2[0][0] * k2[1][0]]).sort((k2, S) => S[2] - k2[2]), v = [];
        for (let k2 = 0; k2 < Math.min(b.length, r); ++k2) {
          let [S, I, $2] = b[k2], C = m.slice(S, I + 1), R = this.tokenizer.decode(C, { skip_special_tokens: true });
          v.push({ answer: R, score: $2 });
        }
        r === 1 ? _.push(...v) : _.push(v);
      }
      return o ? _ : _[0];
    }
  };
  var $i = class extends Y {
    async _call(e, { top_k: s = 5 } = {}) {
      let { mask_token_id: r, mask_token: n } = this.tokenizer, o = this.tokenizer(e, { padding: true, truncation: true }), { logits: i } = await this.model(o), a = [], l = o.input_ids.tolist();
      for (let c = 0; c < l.length; ++c) {
        let p = l[c], u = p.findIndex((g) => g == r);
        if (u === -1) throw Error(`Mask token (${n}) not found in text.`);
        let _ = i[c][u], d = await lt(new E("float32", me(_.data), _.dims), s), m = d[0].tolist(), f = d[1].tolist();
        a.push(f.map((g, w) => {
          let x = p.slice();
          return x[u] = g, { score: m[w], token: Number(g), token_str: this.tokenizer.decode([g]), sequence: this.tokenizer.decode(x, { skip_special_tokens: true }) };
        }));
      }
      return Array.isArray(e) ? a : a[0];
    }
  };
  var Et = class extends Y {
    _default_generation_config = { max_new_tokens: 256 };
    _key = "generated_text";
    async _call(e, s = {}) {
      Array.isArray(e) || (e = [e]), this.model.config.prefix && (e = e.map((l) => this.model.config.prefix + l));
      let r = this.model.config.task_specific_params;
      r && r[this.task] && r[this.task].prefix && (e = e.map((l) => r[this.task].prefix + l));
      let n = this.tokenizer, o = { padding: true, truncation: true }, i;
      this.task === "translation" && "_build_translation_inputs" in n ? i = n._build_translation_inputs(e, o, s) : i = n(e, o);
      let a = await this.model.generate({ ...i, ...this._default_generation_config, ...s });
      return n.batch_decode(a, { skip_special_tokens: true }).map((l) => ({ [this._key]: l }));
    }
  };
  var Fi = class extends Et {
    _key = "summary_text";
  };
  var Ri = class extends Et {
    _key = "translation_text";
  };
  function kk(t6) {
    return Array.isArray(t6) && t6.every((e) => "role" in e && "content" in e);
  }
  var Di = class extends Y {
    _default_generation_config = { max_new_tokens: 256 };
    async _call(e, s = {}) {
      let { add_special_tokens: r, return_full_text: n, tools: o, documents: i, chat_template: a, tokenizer_encode_kwargs: l, ...c } = s, p = false, u = false, _ = r ?? (this.tokenizer.add_bos_token || this.tokenizer.add_eos_token) ?? false, d = l, m;
      if (typeof e == "string") m = e = [e];
      else if (Array.isArray(e) && e.every((v) => typeof v == "string")) p = true, m = e;
      else {
        if (kk(e)) e = [e];
        else if (Array.isArray(e) && e.every(kk)) p = true;
        else throw new Error("Input must be a string, an array of strings, a Chat, or an array of Chats");
        u = true;
        let v = { tokenize: false, add_generation_prompt: true, ...we({ tools: o, documents: i, chat_template: a }, ["tools", "documents", "chat_template"]), ...d };
        m = e.map((k2) => this.tokenizer.apply_chat_template(k2, v)), _ = false, d = void 0;
      }
      let f = u ? false : n ?? true;
      this.tokenizer.padding_side = "left";
      let g = this.tokenizer(m, { add_special_tokens: _, padding: true, truncation: true, ...d }), w = await this.model.generate({ ...g, ...this._default_generation_config, ...c }), x = this.tokenizer.batch_decode(w, { skip_special_tokens: true }), y;
      !f && g.input_ids.dims.at(-1) > 0 && (y = this.tokenizer.batch_decode(g.input_ids, { skip_special_tokens: true }).map((v) => v.length));
      let b = Array.from({ length: e.length }, (v) => []);
      for (let v = 0; v < x.length; ++v) {
        let k2 = Math.floor(v / w.dims[0] * e.length);
        y && (x[v] = x[v].slice(y[k2])), b[k2].push({ generated_text: u ? [...e[k2], { role: "assistant", content: x[v] }] : x[v] });
      }
      return !p && b.length === 1 ? b[0] : b;
    }
  };
  var qi = class extends Y {
    constructor(e) {
      super(e), this.label2id = Object.fromEntries(Object.entries(this.model.config.label2id).map(([s, r]) => [s.toLowerCase(), r])), this.entailment_id = this.label2id.entailment, this.entailment_id === void 0 && (F.warn("Could not find 'entailment' in label2id mapping. Using 2 as entailment_id."), this.entailment_id = 2), this.contradiction_id = this.label2id.contradiction ?? this.label2id.not_entailment, this.contradiction_id === void 0 && (F.warn("Could not find 'contradiction' in label2id mapping. Using 0 as contradiction_id."), this.contradiction_id = 0);
    }
    async _call(e, s, { hypothesis_template: r = "This example is {}.", multi_label: n = false } = {}) {
      let o = Array.isArray(e);
      o || (e = [e]), Array.isArray(s) || (s = [s]);
      let i = s.map((c) => r.replace("{}", c)), a = n || s.length === 1, l = [];
      for (let c of e) {
        let p = [];
        for (let d of i) {
          let m = this.tokenizer(c, { text_pair: d, padding: true, truncation: true }), f = await this.model(m);
          a ? p.push([f.logits.data[this.contradiction_id], f.logits.data[this.entailment_id]]) : p.push(f.logits.data[this.entailment_id]);
        }
        let _ = (a ? p.map((d) => me(d)[1]) : me(p)).map((d, m) => [d, m]).sort((d, m) => m[0] - d[0]);
        l.push({ sequence: c, labels: _.map((d) => s[d[1]]), scores: _.map((d) => d[0]) });
      }
      return o ? l : l[0];
    }
  };
  var ji = class extends Y {
    async _call(e, { top_k: s = 5 } = {}) {
      let r = this.processor.feature_extractor.config.sampling_rate, n = await vt(e, r), o = this.model.config.id2label, i = [];
      for (let a of n) {
        let l = await this.processor(a), p = (await this.model(l)).logits[0], u = await lt(new E("float32", me(p.data), p.dims), s), _ = u[0].tolist(), m = u[1].tolist().map((f, g) => ({ label: o ? o[f] : `LABEL_${f}`, score: _[g] }));
        i.push(m);
      }
      return Array.isArray(e) ? i : i[0];
    }
  };
  var Bi = class extends Y {
    async _call(e, s, { hypothesis_template: r = "This is a sound of {}." } = {}) {
      let n = !Array.isArray(e);
      n && (e = [e]);
      let o = s.map((p) => r.replace("{}", p)), i = this.tokenizer(o, { padding: true, truncation: true }), a = this.processor.feature_extractor.config.sampling_rate, l = await vt(e, a), c = [];
      for (let p of l) {
        let u = await this.processor(p), _ = await this.model({ ...i, ...u }), d = me(_.logits_per_audio.data);
        c.push([...d].map((m, f) => ({ score: m, label: s[f] })));
      }
      return n ? c[0] : c;
    }
  };
  var Ui = class extends Y {
    _default_generation_config = {};
    async _call(e, s = {}) {
      switch (s = { ...this._default_generation_config, ...s }, this.model.config.model_type) {
        case "whisper":
        case "lite-whisper":
          return this._call_whisper(e, s);
        case "wav2vec2":
        case "wav2vec2-bert":
        case "unispeech":
        case "unispeech-sat":
        case "hubert":
        case "parakeet_ctc":
          return this._call_wav2vec2(e, s);
        case "moonshine":
          return this._call_moonshine(e, s);
        case "cohere_asr":
          return this._call_cohere_asr(e, s);
        default:
          throw new Error(`AutomaticSpeechRecognitionPipeline does not support model type '${this.model.config.model_type}'.`);
      }
    }
    async _call_wav2vec2(e, s) {
      s.language && F.warn('`language` parameter is not yet supported for `wav2vec2` models, defaulting to "English".'), s.task && F.warn('`task` parameter is not yet supported for `wav2vec2` models, defaulting to "transcribe".');
      let r = !Array.isArray(e), n = r ? [e] : e, o = this.processor.feature_extractor.config.sampling_rate, i = await vt(n, o), a = [];
      for (let l of i) {
        let c = await this.processor(l), u = (await this.model(c)).logits[0], _ = [];
        for (let m of u) _.push(de(m.data)[1]);
        let d = this.tokenizer.decode(_, { skip_special_tokens: true }).trim();
        a.push({ text: d });
      }
      return r ? a[0] : a;
    }
    async _call_whisper(e, s) {
      let r = s.return_timestamps ?? false, n = s.chunk_length_s ?? 0, o = s.force_full_sequences ?? false, i = s.stride_length_s ?? null, a = { ...s };
      r === "word" && (a.return_token_timestamps = true, a.return_timestamps = true);
      let l = !Array.isArray(e), c = l ? [e] : e, p = this.processor.feature_extractor.config, u = p.chunk_length / this.model.config.max_source_positions, _ = p.hop_length, d = p.sampling_rate, m = await vt(c, d), f = [];
      for (let g of m) {
        let w = [];
        if (n > 0) {
          if (i === null) i = n / 6;
          else if (n <= i) throw Error("`chunk_length_s` must be larger than `stride_length_s`.");
          let b = d * n, v = d * i, k2 = b - 2 * v, S = 0;
          for (; ; ) {
            let I = S + b, $2 = g.subarray(S, I), C = await this.processor($2), R = S === 0, V = I >= g.length;
            if (w.push({ stride: [$2.length, R ? 0 : v, V ? 0 : v], input_features: C.input_features, is_last: V }), V) break;
            S += k2;
          }
        } else w = [{ stride: [g.length, 0, 0], input_features: (await this.processor(g)).input_features, is_last: true }];
        for (let b of w) {
          a.num_frames = Math.floor(b.stride[0] / _);
          let v = await this.model.generate({ inputs: b.input_features, ...a });
          if (r === "word") {
            let k2 = v.sequences.tolist()[0], S = v.token_timestamps.tolist()[0], I = this.tokenizer.timestamp_begin, $2 = Math.max(k2.findIndex((C) => Number(C) >= I), 0);
            b.tokens = k2.slice($2), b.token_timestamps = S.slice($2).map((C) => os2(C, 2));
          } else b.tokens = v[0].tolist();
          b.stride = b.stride.map((k2) => k2 / d);
        }
        let [x, y] = this.tokenizer._decode_asr(w, { time_precision: u, return_timestamps: r, force_full_sequences: o });
        f.push({ text: x, ...y });
      }
      return l ? f[0] : f;
    }
    async _call_moonshine(e, s) {
      let r = !Array.isArray(e), n = r ? [e] : e, o = this.processor.feature_extractor.config.sampling_rate, i = await vt(n, o), a = [];
      for (let l of i) {
        let c = await this.processor(l), p = Math.floor(l.length / o) * 6, u = await this.model.generate({ max_new_tokens: p, ...s, ...c }), _ = this.processor.batch_decode(u, { skip_special_tokens: true })[0];
        a.push({ text: _ });
      }
      return r ? a[0] : a;
    }
    async _call_cohere_asr(e, s) {
      let r = !Array.isArray(e), n = r ? [e] : e, o = this.processor.feature_extractor, i = o.config.sampling_rate, a = await vt(n, i), l = s.language ?? "en", c = this.processor.get_decoder_prompt_ids(l), p = [];
      for (let u of a) {
        let _ = o.split_audio(u), d = [];
        for (let f of _) {
          let g = await this.processor(f), w = await this.model.generate({ ...g, decoder_input_ids: c, ...s }), x = this.tokenizer.decode(w[0].tolist(), { skip_special_tokens: true }).trim();
          d.push(x);
        }
        let m = this.processor.constructor.join_chunks(d, l);
        p.push({ text: m });
      }
      return r ? p[0] : p;
    }
  };
  var Gi = class extends Y {
    DEFAULT_VOCODER_ID = "Xenova/speecht5_hifigan";
    constructor(e) {
      super(e), this.vocoder = e.vocoder ?? null;
    }
    async _prepare_speaker_embeddings(e, s) {
      if ((typeof e == "string" || e instanceof URL) && (e = new Float32Array(await (await J.fetch(e)).arrayBuffer())), e instanceof Float32Array) e = new E("float32", e, [e.length]);
      else if (!(e instanceof E)) throw new Error("Speaker embeddings must be a `Tensor`, `Float32Array`, `string`, or `URL`.");
      if (s > 1) {
        if (e.dims[0] === 1) e = e.repeat(s, 1);
        else if (e.dims[0] !== s) throw new Error(`Expected speaker embeddings batch size to be 1 or ${s}, but got ${e.dims[0]}.`);
      }
      return e;
    }
    _postprocess_waveform(e, s, r, n = null) {
      let o = s.data, [i, a] = s.dims, l = n ? n.data : null, c = [];
      for (let p = 0; p < i; ++p) {
        let u = l ? Math.min(Math.ceil(l[p]), a) : a, _ = p * a;
        c.push(new Wr(o.slice(_, _ + u), r));
      }
      return Array.isArray(e) ? c : c[0];
    }
    async _call(e, s) {
      return this.processor ? this._call_text_to_spectrogram(e, s) : this.model.config.model_type === "supertonic" ? this._call_supertonic(e, s) : this._call_text_to_waveform(e);
    }
    async _call_supertonic(e, { speaker_embeddings: s, num_inference_steps: r, speed: n }) {
      if (!s) throw new Error("Speaker embeddings must be provided for Supertonic models.");
      let { sampling_rate: o, style_dim: i } = this.model.config, a = this.tokenizer(e, { padding: true, truncation: true }), l = a.input_ids.dims[0];
      s = await this._prepare_speaker_embeddings(s, l), s = s.view(l, -1, i);
      let { waveform: c, durations: p } = await this.model.generate_speech({ ...a, style: s, num_inference_steps: r, speed: n });
      return this._postprocess_waveform(e, c, o, p);
    }
    async _call_text_to_waveform(e) {
      let s = this.tokenizer(e, { padding: true, truncation: true }), { waveform: r } = await this.model(s), n = this.model.config.sampling_rate;
      return this._postprocess_waveform(e, r, n);
    }
    async _call_text_to_spectrogram(e, { speaker_embeddings: s }) {
      this.vocoder || (F.info("No vocoder specified, using default HifiGan vocoder."), this.vocoder = await kt.from_pretrained(this.DEFAULT_VOCODER_ID, { dtype: "fp32" }));
      let { input_ids: r } = this.tokenizer(e, { padding: true, truncation: true }), n = r.dims[0];
      s = await this._prepare_speaker_embeddings(s, n), s = s.view(n, -1);
      let { waveform: o } = await this.model.generate_speech(r, s, { vocoder: this.vocoder }), i = this.processor.feature_extractor.config.sampling_rate;
      return this._postprocess_waveform(e, o, i);
    }
  };
  var Wi = class extends Y {
    async _call(e, s = {}) {
      let r = Array.isArray(e), n = await Se(e), { pixel_values: o } = await this.processor(n), i = [];
      for (let a of o) {
        a.dims = [1, ...a.dims];
        let l = await this.model.generate({ inputs: a, ...s }), c = this.tokenizer.batch_decode(l, { skip_special_tokens: true }).map((p) => ({ generated_text: p.trim() }));
        i.push(c);
      }
      return r ? i : i[0];
    }
  };
  var Vi = class extends Y {
    async _call(e, { top_k: s = 5 } = {}) {
      let r = await Se(e), { pixel_values: n } = await this.processor(r), o = await this.model({ pixel_values: n }), { id2label: i } = this.model.config, a = [];
      for (let l of o.logits) {
        let c = await lt(new E("float32", me(l.data), l.dims), s), p = c[0].tolist(), _ = c[1].tolist().map((d, m) => ({ label: i ? i[d] : `LABEL_${d}`, score: p[m] }));
        a.push(_);
      }
      return Array.isArray(e) ? a : a[0];
    }
  };
  var vk = { panoptic: "post_process_panoptic_segmentation", instance: "post_process_instance_segmentation", semantic: "post_process_semantic_segmentation" };
  var As2 = class extends Y {
    async _call(e, { threshold: s = 0.5, mask_threshold: r = 0.5, overlap_mask_area_threshold: n = 0.8, label_ids_to_fuse: o = null, target_sizes: i = null, subtask: a = null } = {}) {
      if (Array.isArray(e) && e.length !== 1) throw Error("Image segmentation pipeline currently only supports a batch size of 1.");
      let c = await Se(e), p = c.map((x) => [x.height, x.width]), u = await this.processor(c), { inputNames: _, outputNames: d } = this.model.sessions.model;
      if (!_.includes("pixel_values")) {
        if (_.length !== 1) throw Error(`Expected a single input name, but got ${_.length} inputs: ${_}.`);
        let x = _[0];
        if (x in u) throw Error(`Input name ${x} already exists in the inputs.`);
        u[x] = u.pixel_values;
      }
      let m = await this.model(u), f = null;
      if (a !== null) f = vk[a];
      else if (this.processor.image_processor) {
        for (let [x, y] of Object.entries(vk)) if (y in this.processor.image_processor) {
          f = this.processor.image_processor[y].bind(this.processor.image_processor), a = x;
          break;
        }
      }
      let g = this.model.config.id2label, w = [];
      if (a) if (a === "panoptic" || a === "instance") {
        let x = f(m, s, r, n, o, i ?? p)[0], y = x.segmentation;
        for (let b of x.segments_info) {
          let v = new Uint8ClampedArray(y.data.length);
          for (let S = 0; S < y.data.length; ++S) y.data[S] === b.id && (v[S] = 255);
          let k2 = new Ee2(v, y.dims[1], y.dims[0], 1);
          w.push({ score: b.score, label: g[b.label_id], mask: k2 });
        }
      } else if (a === "semantic") {
        let { segmentation: x, labels: y } = f(m, i ?? p)[0];
        for (let b of y) {
          let v = new Uint8ClampedArray(x.data.length);
          for (let S = 0; S < x.data.length; ++S) x.data[S] === b && (v[S] = 255);
          let k2 = new Ee2(v, x.dims[1], x.dims[0], 1);
          w.push({ score: null, label: g[b], mask: k2 });
        }
      } else throw Error(`Subtask ${a} not supported.`);
      else {
        let y = m[d[0]];
        for (let b = 0; b < p.length; ++b) {
          let v = p[b], k2 = y[b];
          k2.data.some((I) => I < -1e-5 || I > 1 + 1e-5) && k2.sigmoid_();
          let S = await Ee2.fromTensor(k2.mul_(255).to("uint8")).resize(v[1], v[0]);
          w.push({ label: null, score: null, mask: S });
        }
      }
      return w;
    }
  };
  var Hi = class extends As2 {
    async _call(e, s = {}) {
      let r = await Se(e), n = await super._call(e, s), o = r.map((i, a) => {
        let l = i.clone();
        return l.putAlpha(n[a].mask), l;
      });
      return Array.isArray(e) ? o : o[0];
    }
  };
  var Ki = class extends Y {
    async _call(e, s, { hypothesis_template: r = "This is a photo of {}" } = {}) {
      let n = Array.isArray(e), o = await Se(e), i = s.map((_) => r.replace("{}", _)), a = this.tokenizer(i, { padding: this.model.config.model_type === "siglip" ? "max_length" : true, truncation: true }), { pixel_values: l } = await this.processor(o), c = await this.model({ ...a, pixel_values: l }), p = this.model.config.model_type === "siglip" ? (_) => _.sigmoid().data : (_) => me(_.data), u = [];
      for (let _ of c.logits_per_image) {
        let m = [...p(_)].map((f, g) => ({ score: f, label: s[g] }));
        m.sort((f, g) => g.score - f.score), u.push(m);
      }
      return n ? u : u[0];
    }
  };
  var Xi = class extends Y {
    async _call(e, { threshold: s = 0.9, percentage: r = false } = {}) {
      let n = Array.isArray(e);
      if (n && e.length !== 1) throw Error("Object detection pipeline currently only supports a batch size of 1.");
      let o = await Se(e), i = r ? null : o.map((d) => [d.height, d.width]), { pixel_values: a, pixel_mask: l } = await this.processor(o), c = await this.model({ pixel_values: a, pixel_mask: l }), p = this.processor.image_processor.post_process_object_detection(c, s, i), { id2label: u } = this.model.config, _ = p.map((d) => d.boxes.map((m, f) => ({ score: d.scores[f], label: u[d.classes[f]], box: Ci(m, !r) })));
      return n ? _ : _[0];
    }
  };
  var Qi = class extends Y {
    async _call(e, s, { threshold: r = 0.1, top_k: n = null, percentage: o = false } = {}) {
      let i = Array.isArray(e), a = await Se(e), l = this.tokenizer(s, { padding: true, truncation: true }), c = await this.processor(a), p = [];
      for (let u = 0; u < a.length; ++u) {
        let _ = a[u], d = o ? null : [[_.height, _.width]], m = c.pixel_values[u].unsqueeze_(0), f = await this.model({ ...l, pixel_values: m }), g;
        if ("post_process_grounded_object_detection" in this.processor) {
          let w = this.processor.post_process_grounded_object_detection(f, l.input_ids, { box_threshold: r, text_threshold: r, target_sizes: d })[0];
          g = w.boxes.map((x, y) => ({ score: w.scores[y], label: w.labels[y], box: Ci(x, !o) }));
        } else {
          let w = this.processor.image_processor.post_process_object_detection(f, r, d, true)[0];
          g = w.boxes.map((x, y) => ({ score: w.scores[y], label: s[w.classes[y]], box: Ci(x, !o) }));
        }
        g.sort((w, x) => x.score - w.score), n !== null && (g = g.slice(0, n)), p.push(g);
      }
      return i ? p : p[0];
    }
  };
  var Yi = class extends Y {
    _default_generation_config = { max_new_tokens: 256 };
    async _call(e, s, r = {}) {
      if (Array.isArray(e)) {
        if (e.length !== 1) throw Error("Document Question Answering pipeline currently only supports a batch size of 1.");
        e = e[0];
      }
      let n = (await Se(e))[0], { pixel_values: o } = await this.processor(n), i = `<s_docvqa><s_question>${s}</s_question><s_answer>`, a = this.tokenizer(i, { add_special_tokens: false, padding: true, truncation: true }).input_ids, l = await this.model.generate({ inputs: o, max_length: this.model.config.decoder.max_position_embeddings, decoder_input_ids: a, ...this._default_generation_config, ...r }), p = this.tokenizer.batch_decode(l)[0].match(/<s_answer>(.*?)<\/s_answer>/), u = null;
      return p && p.length >= 2 && (u = p[1].trim()), [{ answer: u }];
    }
  };
  var Ji = class extends Y {
    async _call(e) {
      let s = await Se(e), r = await this.processor(s), n = await this.model(r), o = [];
      for (let i of n.reconstruction) {
        let a = i.squeeze().clamp_(0, 1).mul_(255).round_().to("uint8");
        o.push(Ee2.fromTensor(a));
      }
      return Array.isArray(e) ? o : o[0];
    }
  };
  var Zi = class extends Y {
    async _call(e) {
      let s = await Se(e), r = await this.processor(s), { predicted_depth: n } = await this.model(r), o = [];
      for (let i = 0; i < s.length; ++i) {
        let a = n[i], [l, c] = a.dims.slice(-2), [p, u] = s[i].size, _ = (await je2(a.view(1, 1, l, c), { size: [u, p], mode: "bilinear" })).view(u, p), d = _.min().item(), m = _.max().item(), f = _.sub(d).div_(m - d).mul_(255).to("uint8").unsqueeze(0), g = Ee2.fromTensor(f);
        o.push({ predicted_depth: _, depth: g });
      }
      return Array.isArray(e) ? o : o[0];
    }
  };
  var ea = class extends Y {
    async _call(e, { pooling: s = "none", normalize: r = false, quantize: n = false, precision: o = "binary" } = {}) {
      let i = this.tokenizer(e, { padding: true, truncation: true }), a = await this.model(i), l = a.last_hidden_state ?? a.logits ?? a.token_embeddings;
      switch (s) {
        case "none":
          break;
        case "mean":
          l = nb(l, i.attention_mask);
          break;
        case "first_token":
        case "cls":
          l = l.slice(null, 0);
          break;
        case "last_token":
        case "eos":
          l = l.slice(null, -1);
          break;
        default:
          throw Error(`Pooling method '${s}' not supported.`);
      }
      return r && (l = l.normalize(2, -1)), n && (l = ib(l, o)), l;
    }
  };
  var ta = class extends Y {
    async _call(e, { pool: s = null } = {}) {
      let r = await Se(e), { pixel_values: n } = await this.processor(r), o = await this.model({ pixel_values: n }), i;
      if (s) {
        if (!("pooler_output" in o)) throw Error("No pooled output was returned. Make sure the model has a 'pooler' layer when using the 'pool' option.");
        i = o.pooler_output;
      } else i = o.last_hidden_state ?? o.logits ?? o.image_embeds;
      return i;
    }
  };
  var Er = Object.freeze({ "text-classification": { pipeline: Pi, model: Oi, default: { model: "Xenova/distilbert-base-uncased-finetuned-sst-2-english" }, type: "text" }, "token-classification": { pipeline: Ni, model: wc2, default: { model: "Xenova/bert-base-multilingual-cased-ner-hrl" }, type: "text" }, "question-answering": { pipeline: Li, model: Ac, default: { model: "Xenova/distilbert-base-cased-distilled-squad" }, type: "text" }, "fill-mask": { pipeline: $i, model: Ec, default: { model: "onnx-community/ettin-encoder-32m-ONNX", dtype: "fp32" }, type: "text" }, summarization: { pipeline: Fi, model: vr, default: { model: "Xenova/distilbart-cnn-6-6" }, type: "text" }, translation: { pipeline: Ri, model: vr, default: { model: "Xenova/t5-small" }, type: "text" }, "text2text-generation": { pipeline: Et, model: vr, default: { model: "Xenova/flan-t5-small" }, type: "text" }, "text-generation": { pipeline: Di, model: vc, default: { model: "onnx-community/Qwen3-0.6B-ONNX", dtype: "q4" }, type: "text" }, "zero-shot-classification": { pipeline: qi, model: Oi, default: { model: "Xenova/distilbert-base-uncased-mnli" }, type: "text" }, "audio-classification": { pipeline: ji, model: Tc2, default: { model: "Xenova/wav2vec2-base-superb-ks" }, type: "audio" }, "zero-shot-audio-classification": { pipeline: Bi, model: kt, default: { model: "Xenova/clap-htsat-unfused" }, type: "multimodal" }, "automatic-speech-recognition": { pipeline: Ui, model: [yc2, zc], default: { model: "Xenova/whisper-tiny.en" }, type: "multimodal" }, "text-to-audio": { pipeline: Gi, model: [kc, bc], default: { model: "onnx-community/Supertonic-TTS-ONNX", dtype: "fp32" }, type: "text" }, "image-to-text": { pipeline: Wi, model: Mc, default: { model: "Xenova/vit-gpt2-image-captioning" }, type: "multimodal" }, "image-classification": { pipeline: Vi, model: Sc, default: { model: "Xenova/vit-base-patch16-224" }, type: "multimodal" }, "image-segmentation": { pipeline: As2, model: [Ii, zi, Ti], default: { model: "Xenova/detr-resnet-50-panoptic" }, type: "multimodal" }, "background-removal": { pipeline: Hi, model: [Ii, zi, Ti], default: { model: "Xenova/modnet" }, type: "image" }, "zero-shot-image-classification": { pipeline: Ki, model: kt, default: { model: "Xenova/clip-vit-base-patch32" }, type: "multimodal" }, "object-detection": { pipeline: Xi, model: Oc, default: { model: "Xenova/detr-resnet-50" }, type: "multimodal" }, "zero-shot-object-detection": { pipeline: Qi, model: Ic, default: { model: "Xenova/owlvit-base-patch32" }, type: "multimodal" }, "document-question-answering": { pipeline: Yi, model: Cc, default: { model: "Xenova/donut-base-finetuned-docvqa" }, type: "multimodal" }, "image-to-image": { pipeline: Ji, model: Pc, default: { model: "Xenova/swin2SR-classical-sr-x2-64" }, type: "image" }, "depth-estimation": { pipeline: Zi, model: Nc, default: { model: "onnx-community/depth-anything-v2-small" }, type: "image" }, "feature-extraction": { pipeline: ea, model: kt, default: { model: "onnx-community/all-MiniLM-L6-v2-ONNX", dtype: "fp32" }, type: "text" }, "image-feature-extraction": { pipeline: ta, model: [Lc, kt], default: { model: "onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX", dtype: "fp32" }, type: "image" } });
  var $c = Object.freeze({ "sentiment-analysis": "text-classification", ner: "token-classification", asr: "automatic-speech-recognition", "text-to-speech": "text-to-audio", embeddings: "feature-extraction" });
  var Ek = K2.IS_PROCESS_AVAILABLE ? (t6) => process.stdout.write(t6) : (t6) => console.log(t6);
  var NM = Object.keys(Nt);

  // ../../desktop/helper/vision/vision-worker.js
  var MODEL_ID = "HuggingFaceTB/SmolVLM2-256M-Video-Instruct";
  var MODEL_REVISION = "067788b187b95ebe7b2e040b3e4299e342e5b8fd";
  var MAX_IMAGES = 8;
  var MAX_IMAGE_CHARS = 3 * 1024 * 1024;
  var runtimePromise = null;
  J.allowRemoteModels = true;
  J.allowLocalModels = false;
  J.backends.onnx.wasm.wasmPaths = "autoeditor-vision://runtime/";
  J.backends.onnx.wasm.numThreads = 1;
  function progressReporter(id2) {
    const seen = /* @__PURE__ */ new Map();
    return (event) => {
      if (!event || event.status !== "progress" || !Number.isFinite(event.progress)) return;
      const percent = Math.max(0, Math.min(100, Math.floor(event.progress / 10) * 10));
      const file = String(event.file || "vision model").slice(0, 120);
      if (seen.get(file) === percent) return;
      seen.set(file, percent);
      if (percent === 0 || percent === 100 || percent % 20 === 0) {
        self.postMessage({
          id: id2,
          status: "progress",
          line: `Local vision model: ${file} ${percent}%`
        });
      }
    };
  }
  async function getRuntime(id2) {
    if (!runtimePromise) {
      runtimePromise = (async () => {
        const progress_callback = progressReporter(id2);
        self.postMessage({
          id: id2,
          status: "progress",
          line: "Loading the free local vision model. The first use downloads it once..."
        });
        let webgpu = false;
        try {
          const adapter = await navigator.gpu?.requestAdapter();
          webgpu = !!adapter;
        } catch (_) {
        }
        const processor = await el.from_pretrained(MODEL_ID, {
          revision: MODEL_REVISION,
          progress_callback
        });
        if (webgpu) {
          try {
            const model2 = await Mc.from_pretrained(MODEL_ID, {
              revision: MODEL_REVISION,
              dtype: "q4",
              device: "webgpu",
              progress_callback
            });
            return { processor, model: model2, device: "webgpu", dtype: "q4" };
          } catch (error) {
            self.postMessage({
              id: id2,
              status: "progress",
              line: "WebGPU was unavailable for this model. Continuing locally with WASM..."
            });
          }
        }
        const model = await Mc.from_pretrained(MODEL_ID, {
          revision: MODEL_REVISION,
          dtype: "q4",
          device: "wasm",
          progress_callback
        });
        return { processor, model, device: "wasm", dtype: "q4" };
      })().catch((error) => {
        runtimePromise = null;
        throw error;
      });
    }
    return runtimePromise;
  }
  function cleanResult(value) {
    let text = String(value || "").replace(/\0/g, "").trim();
    const marker = text.lastIndexOf("Assistant:");
    if (marker >= 0) text = text.slice(marker + "Assistant:".length).trim();
    return text.slice(0, 5e3);
  }
  async function describe(id2, images) {
    if (!Array.isArray(images) || images.length < 1 || images.length > MAX_IMAGES || images.some((image) => typeof image !== "string" || !image.startsWith("data:image/jpeg;base64,") || image.length > MAX_IMAGE_CHARS)) {
      throw new Error("local vision frames were invalid");
    }
    const { processor, model, device, dtype } = await getRuntime(id2);
    self.postMessage({
      id: id2,
      status: "progress",
      line: `Watching ${images.length} representative frames locally with ${device}/${dtype}...`
    });
    const frames = await Promise.all(images.map((image) => RA(image)));
    const messages = [{ role: "user", content: [
      ...frames.map(() => ({ type: "image" })),
      { type: "text", text: [
        "These are chronological frames sampled from one attached video.",
        "Describe only visibly supported people, actions, objects, setting, products,",
        "readable on-screen text, camera framing, composition, and meaningful changes.",
        "Note uncertainty. Do not invent names or dialogue. Return one concise factual",
        "production report for a video editor."
      ].join(" ") }
    ] }];
    const prompt = processor.apply_chat_template(messages, { add_generation_prompt: true });
    const inputs = await processor(prompt, frames, { do_image_splitting: false });
    const output = await model.generate({
      ...inputs,
      do_sample: false,
      repetition_penalty: 1.05,
      max_new_tokens: 220
    });
    const decoded = processor.batch_decode(output, { skip_special_tokens: true });
    const result = cleanResult(decoded.at(-1));
    if (!result) throw new Error("local vision model returned no description");
    return result;
  }
  self.addEventListener("message", async (event) => {
    const id2 = event.data?.id;
    if (!Number.isSafeInteger(id2) || id2 < 1) return;
    try {
      const result = await describe(id2, event.data.images);
      self.postMessage({ id: id2, status: "complete", result });
    } catch (error) {
      self.postMessage({
        id: id2,
        status: "error",
        error: String(error?.message || error).slice(0, 1e3)
      });
    }
  });
})();
