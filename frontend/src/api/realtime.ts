// One WebSocket per page, push-only, auto-reconnect with backoff. No polling.
import { useEffect, useRef, useState } from "react";
import { wsUrl } from "./client";
import type { WsEnvelope } from "./types";

export type ConnState = "connecting" | "open" | "closed";

export function useRealtime(topics: string[], onEvent: (e: WsEnvelope<any>) => void): ConnState {
  const [state, setState] = useState<ConnState>("connecting");
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const key = topics.join(",");

  useEffect(() => {
    if (!key) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let ping: number | undefined;
    let timer: number | undefined;

    const connect = () => {
      setState("connecting");
      ws = new WebSocket(wsUrl(key.split(",")));
      ws.onopen = () => {
        retry = 0;
        setState("open");
        ping = window.setInterval(() => ws?.readyState === 1 && ws.send("ping"), 20000);
      };
      ws.onmessage = (msg) => {
        try {
          const env = JSON.parse(msg.data) as WsEnvelope;
          if (env.type !== "pong") handler.current(env);
        } catch { /* ignore malformed */ }
      };
      ws.onclose = () => {
        window.clearInterval(ping);
        setState("closed");
        if (!closed) timer = window.setTimeout(connect, Math.min(5000, 400 * 2 ** retry++));
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearInterval(ping);
      window.clearTimeout(timer);
      ws?.close();
    };
  }, [key]);

  return state;
}
