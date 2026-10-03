/* What the scripts in docs/js share: the one global, GWT, that each of them
 * adds a module to. Every module on it is typed `any` here. The scripts are
 * plain scripts, each an IIFE, so no type a file declares inside its IIFE can
 * be named from outside it; GWT.core's functions are typed where they are
 * written, in gwt-core.js, and checked there. */
interface GWTNamespace {
  [module: string]: any;
}

interface Window {
  GWT: GWTNamespace;
}

/* gwt-worker.js is loaded both as a page script and as a Web Worker, and
 * looks for importScripts on its global to tell which. The DOM library this
 * project checks against has no worker globals, so the one it uses is
 * declared here, optional, as the page sees it. */
interface Window {
  importScripts?: (...urls: string[]) => void;
}
