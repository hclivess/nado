// three.js r187's WebGPU build under ONE URL. land.html's import map sends "three/webgpu" here, and this path is stamped
// by the node (?v=<hash>) exactly as three's own files stamp their relative imports of each other — so land.js, the
// post-processing add-ons and three itself all load the same instance. Mapping the bare name straight to the vendored
// file left it unstamped while three.webgpu.js imported "./three.tsl.js?v=…": two TSL instances, a black page (2026-11-06).
export * from "/static/vendor/three/three.webgpu.js";
