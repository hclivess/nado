// Node has no relay. Browser clients import their protocol constants from the relay's GET /protocol.js
// (ops/client_protocol.py, protocol.CLIENT_EXPORTS); in a Node test that absolute specifier would resolve to
// file:///protocol.js. This hook renders the module with THE SAME Python the relay runs and maps the specifier
// (stamped or not) to it, so a test exercises the values the browser would get — never a copy kept for the test.
//
// USE: import this FIRST, then load any static/ module that (transitively) imports "/protocol.js" with a
// DYNAMIC import — static imports are linked before this module runs, so they would miss the hook:
//     import { P } from "./protocol_hook.mjs";
//     const { NadoDapp } = await import("../static/nadodapp.js");
// `P` is the rendered module itself (P.EPOCH_LENGTH, ...), for tests that lift source text and must inject values.
// Rendering imports ops/client_protocol (protocol.py only) under a throwaway HOME: nothing touches a node database.
import { register } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PY = "import atexit,os,shutil,sys,tempfile\n" +
  "h=tempfile.mkdtemp(prefix='nado-protojs-'); os.environ['HOME']=h; atexit.register(shutil.rmtree,h,True)\n" +
  "sys.path.insert(0, sys.argv[1])\n" +
  "from ops.client_protocol import render_js\n" +
  "sys.stdout.write(render_js().decode('utf-8'))\n";
export const PROTOCOL_JS = execFileSync(process.env.NADO_TEST_PYTHON || "python3", ["-c", PY, ROOT], { encoding: "utf8" });
const URL_ = "data:text/javascript;base64," + Buffer.from(PROTOCOL_JS).toString("base64");
register("data:text/javascript," + encodeURIComponent(
  "export async function resolve(s, c, next) {" +
  "  if (/^\\/protocol\\.js(\\?[^\"']*)?$/.test(s)) return { url: " + JSON.stringify(URL_) + ", shortCircuit: true };" +
  "  return next(s, c);" +
  "}"));
export const P = await import("/protocol.js");
