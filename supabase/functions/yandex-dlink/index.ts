// ============================================================
// supabase/functions/yandex-dlink
// Возвращает прямую ссылку (dlink) на файл Яндекс.Диска.
// НЕ проксирует файл — только отдаёт URL.
// Пользователь скачивает файл напрямую из Яндекса,
// Supabase egress = ~2 КБ (только JSON-ответ).
// ============================================================

import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const ALLOWED_ORIGINS = [
  "https://dimonmaxx.github.io",
  "https://my-site-8vm.pages.dev",
];

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/120.0.0.0 Safari/537.36";

function corsHeaders(origin: string) {
  const allowOrigin = ALLOWED_ORIGINS.includes(origin)
    ? origin
    : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Credentials": "true",
    "Vary": "Origin",
  };
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  const cors = corsHeaders(origin);

  // Preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors });
  }

  const url = new URL(req.url);
  const folderUrl = url.searchParams.get("folder");
  let path = url.searchParams.get("path");

  if (!folderUrl || !path) {
    return new Response(
      JSON.stringify({ error: "Missing folder or path" }),
      {
        status: 400,
        headers: { ...cors, "Content-Type": "application/json" },
      },
    );
  }

  try {
    // ─── Шаг 0: авто-отрезание префикса (как в yandex-download) ───
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
            console.log(
              `[yandex-dlink] авто-отрезан префикс «${prefix}» → «${path}»`,
            );
          }
        }
      }
    } catch (e) {
      console.warn("[yandex-dlink] root-check:", e);
    }

    // ─── Шаг 1: получаем прямую ссылку у Яндекса ───
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

    // ─── Шаг 2: возвращаем JSON с прямой ссылкой ───
    const fileName = path.split("/").pop() || "file";

    return new Response(
      JSON.stringify({
        url: meta.href,
        filename: decodeURIComponent(fileName),
        expires_in: 1800, // 30 минут — стандарт Яндекса
      }),
      {
        status: 200,
        headers: {
          ...cors,
          "Content-Type": "application/json",
          "Cache-Control": "no-store",
        },
      },
    );
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
