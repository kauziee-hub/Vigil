// A tab left open across a rebuild asks for code chunks by their OLD hashed names, which no longer exist.
// Reload once (per tab session) to pick up the new build instead of failing; a second failure is a real error.
const KEY = "vigil-chunk-reload";

export function withChunkReload<T>(load: () => Promise<T>): Promise<T> {
  return load().catch((err: unknown) => {
    const msg = String((err as Error)?.message ?? err);
    const stale = /dynamically imported module|Importing a module script failed|error loading dynamically/i.test(msg);
    let reloaded = false;
    try { reloaded = sessionStorage.getItem(KEY) === "1"; } catch { /* storage unavailable */ }
    if (stale && !reloaded) {
      try { sessionStorage.setItem(KEY, "1"); } catch { /* ignore */ }
      window.location.reload();
      return new Promise<T>(() => undefined);   // the page is reloading; never settle
    }
    throw err;
  });
}
