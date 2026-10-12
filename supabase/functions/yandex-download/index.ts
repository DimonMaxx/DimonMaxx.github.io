// ============================================================
// supabase/functions/yandex-download
// Стриминг: проксирует файл с Яндекса через Supabase.
// dlink Яндекса привязана к IP запросившего, поэтому прямые
// ссылки пользователю не работают — нужен прокси.
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
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, range",
    "Access-Control-Expose-Headers":
      "Content-Length, Content-Range, Accept-Ranges, Content-Disposition",
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
    // ─── Авто-отрезание префикса ───
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
          }
        }
      }
    } catch (e) {
      console.warn("[yandex-download] root-check:", e);
    }

    // ─── Получаем dlink ───
    const apiUrl =
      `https://cloud-api.yandex.net/v1/disk/public/resources/download` +
      `?public_key=${encodeURIComponent(folderUrl)}` +
      `&path=${encodeURIComponent(path)}`;
    const metaResp = await fetch(apiUrl, {
      headers: { "User-Agent": USER_AGENT },
    });
    const meta = await metaResp.json();

    if (!metaResp.ok || !meta.href) {
      return new Response(`Yandex API error: ${JSON.stringify(meta)}`, {
        status: 500,
        headers: cors,
      });
    }

    // ─── Пробрасываем Range ───
    const rangeHeader = req.headers.get("range") || req.headers.get("Range");
    const upstreamHeaders: Record<string, string> = {
      "User-Agent": USER_AGENT,
      "Referer": "https://disk.yandex.ru/",
    };
    if (rangeHeader) upstreamHeaders["Range"] = rangeHeader;

    const fileResp = await fetch(meta.href, { headers: upstreamHeaders });

    if (!fileResp.ok && fileResp.status !== 206) {
      return new Response(`Yandex download error: ${fileResp.status}`, {
        status: fileResp.status,
        headers: cors,
      });
    }

    const fileName = path.split("/").pop() || "file";
    const headers = new Headers(cors);
    headers.set(
      "Content-Type",
      fileResp.headers.get("Content-Type") || "application/octet-stream",
    );
    headers.set(
      "Content-Disposition",
      `attachment; filename*=UTF-8''${encodeURIComponent(fileName)}`,
    );
    headers.set("Accept-Ranges", "bytes");

    const cl = fileResp.headers.get("Content-Length");
    if (cl) headers.set("Content-Length", cl);
    const cr = fileResp.headers.get("Content-Range");
    if (cr) headers.set("Content-Range", cr);

    return new Response(fileResp.body, {
      status: fileResp.status,
      headers,
    });
  } catch (e) {
    return new Response(`Error: ${e.message}`, {
      status: 500,
      headers: cors,
    });
  }
});
