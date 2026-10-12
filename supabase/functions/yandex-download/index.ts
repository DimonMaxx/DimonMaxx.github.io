// ============================================================
// supabase/functions/yandex-download
// Версия 2: 302 redirect вместо стриминга.
// Возвращает прямую ссылку через Location-заголовок.
// Если Яндекс пропустит — egress Supabase = 0.
// ============================================================

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/120.0.0.0 Safari/537.36";

const ALLOWED_ORIGINS = [
  "https://dimonmaxx.github.io",
  "https://my-site-8vm.pages.dev",
];

function corsHeaders(origin: string) {
  const allowOrigin = ALLOWED_ORIGINS.includes(origin)
    ? origin
    : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, range",
    "Access-Control-Expose-Headers": "Location",
    "Access-Control-Allow-Credentials": "true",
    "Vary": "Origin",
  };
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  const cors = corsHeaders(origin);

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }

  const url = new URL(req.url);
  const folderUrl = url.searchParams.get("folder");
  let path = url.searchParams.get("path");

  if (!folderUrl || !path) {
    return new Response("Missing folder or path", {
      status: 400,
      headers: cors,
    });
  }

  try {
    // ─── Шаг 0: авто-отрезание префикса ───
    try {
      const metaUrl =
        `https://cloud-api.yandex.net/v1/disk/public/resources` +
        `?public_key=${encodeURIComponent(folderUrl)}&path=/`;
      const metaResp = await fetch(metaUrl, {
        headers: { "User-Agent": USER_AGENT },
      });
      if (metaResp.ok) {
        const meta = await metaResp.json();
        const rootName = meta.name;
        if (rootName) {
          const prefix = `/${rootName}/`;
          if (path.startsWith(prefix)) {
            path = path.slice(prefix.length - 1);
            console.log(`[yandex-download] авто-отрезан префикс «${prefix}»`);
          }
        }
      }
    } catch (e) {
      console.warn("[yandex-download] root-check:", e);
    }

    // ─── Шаг 1: получаем dlink у Яндекса ───
    const apiUrl =
      `https://cloud-api.yandex.net/v1/disk/public/resources/download` +
      `?public_key=${encodeURIComponent(folderUrl)}` +
      `&path=${encodeURIComponent(path)}`;

    const resp = await fetch(apiUrl, {
      headers: { "User-Agent": USER_AGENT },
    });

    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      return new Response(
        JSON.stringify({
          error: "Yandex API error",
          status: resp.status,
          body: text.slice(0, 500),
        }),
        {
          status: 502,
          headers: { ...cors, "Content-Type": "application/json" },
        },
      );
    }

    const meta = await resp.json();
    if (!meta.href) {
      return new Response(
        JSON.stringify({ error: "No href in Yandex response", details: meta }),
        {
          status: 502,
          headers: { ...cors, "Content-Type": "application/json" },
        },
      );
    }

    // ─── Шаг 2: 302 redirect на прямую ссылку ───
    console.log("[yandex-download] → 302 redirect на:", meta.href.slice(0, 80));

    return new Response(null, {
      status: 302,
      headers: {
        ...cors,
        "Location": meta.href,
        "Cache-Control": "no-store",
      },
    });
  } catch (e) {
    return new Response(
      JSON.stringify({ error: "Internal error", message: String(e) }),
      {
        status: 500,
        headers: { ...cors, "Content-Type": "application/json" },
      },
    );
  }
});
