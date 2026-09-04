/**
 * The path prefix this app is being served under.
 *
 * Served directly (http://host:8002/) it is "" and every request is unchanged.
 * Behind the LILAK portal the app lives at `<portal>/p/<name>/`, and the portal's
 * proxy injects `window.__PORTAL_BASE__` -- along with a `<base href>` -- into the
 * HTML it returns (service_manager/app/proxy_util.py, inject_base). The `<base>`
 * covers relative URLs only: a root-absolute "/api/..." ignores it entirely and is
 * sent to the portal itself, which answers 404. So every URL this app builds has
 * to carry the prefix, whether it is fetched or put in an href.
 */
const injected = (window as unknown as { __PORTAL_BASE__?: string }).__PORTAL_BASE__

/** "" when served directly, "/p/<name>" behind the portal. Never a trailing slash. */
export const BASE = (injected ?? "").replace(/\/+$/, "")

/** A root-absolute app path ("/api/...") resolved against wherever we are served. */
export function url(path: string): string {
  return BASE + path
}
