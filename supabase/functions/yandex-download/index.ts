import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// ─── Разрешённые домены ───
// Сюда перечислите ВСЕ домены, с которых ваш сайт может обращаться.
// Если у вас GitHub Pages + пользовательский домен, добавьте оба.
const ALLOWED_HOSTS = [
  "dimonmaxx.github.io",
  // "ваш-домен.ru",
  // "my-site.pages.dev",
];

function hostAllowed(url: string): boolean {
  // Пустая строка и строка "null" — это «заголовок не передан».
  // Их обрабатываем в вызывающем коде отдельно, не блокируя.
  if (!url || url === "null") return false;
  try {
    const u = new URL(url);
    return ALLOWED_HOSTS.some(h =>
      u.hostname === h || u.hostname.endsWith("." + h)
    );
  } catch {
    return false;
  }
}

/**
 * Есть ли у запроса осмысленные Origin/Referer?
 * Пустая строка и строка "null" считаются отсутствием заголовка.
 */
function hasOriginInfo(origin: string, referer: string): boolean {
  const o = origin && origin !== "null" ? origin : "";
  const r = referer && referer !== "null" ? referer : "";
  return Boolean(o || r);
}

function buildCors(origin: string) {
  // Эхо Origin — правильнее, чем "*", когда мы уже ограничили список.
  // Если origin пустой или "null" — отдаём "*" (запрос всё равно уйдёт).
  const allowOrigin = origin && origin !== "null" ? origin : "*";
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Headers":
      "authorization, x-client-info, apikey, content-type, range",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Expose-Headers":
      "Content-Length, Content-Range, Accept-Ranges, Content-Type",
    "Vary": "Origin, Referer",
  };
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  const referer = req.headers.get("referer") || "";
  const corsHeaders = buildCors(origin);

  // ─── Preflight ───
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  // ─── Проверка Origin/Referer ───
  //
  // Логика:
  //   • Если браузер не прислал ни Origin, ни Referer
  //     (приватный режим, блокировщик, навигационный запрос без Referer) —
  //     НЕ блокируем. Это не хотлинк, а легитимный запрос.
  //   • Если Origin/Referer пришли — проверяем по белому списку.
  //     Если не прошли — блокируем (это уже хотлинк с чужого сайта).
  //
  // Хотлинк-защита сохранена: <img src="...">, <video src="...">,
  // fetch() с чужого сайта всегда отправляют Referer или Origin.
  if (hasOriginInfo(origin, referer)) {
    const originOk  = hostAllowed(origin);
    const refererOk = hostAllowed(referer);
    if (!originOk && !refererOk) {
      console.warn("[yandex-download] заблокировано (чужой origin/referer):", {
        origin, referer, ua: req.headers.get("user-agent"),
      });
      return new Response("Forbidden: invalid origin/referer", {
        status: 403,
        headers: corsHeaders,
      });
    }
  } else {
    console.log("[yandex-download] пропуск без origin/referer (навигация без Referer)");
  }

  const url = new URL(req.url);
  const folderUrl = url.searchParams.get("folder");
  let path = url.searchParams.get("path");

  if (!folderUrl || !path) {
    return new Response("Missing folder or path", {
      status: 400,
      headers: corsHeaders,
    });
  }

  try {
    // ─── Шаг 0: авто-отрезание префикса ───
    try {
      const metaUrl =
        `https://cloud-api.yandex.net/v1/disk/public/resources?public_key=${
          encodeURIComponent(folderUrl)
        }&path=/`;
      const metaResp = await fetch(metaUrl, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        },
      });
      if (metaResp.ok) {
        const meta = await metaResp.json();
        const rootName = meta.name;
        if (rootName) {
          const prefix = `/${rootName}/`;
          if (path.startsWith(prefix)) {
            path = path.slice(prefix.length - 1);
            console.log(
              `[yandex-download] авто-отрезан префикс «${prefix}» → «${path}»`,
            );
          }
        }
      }
    } catch (e) {
      console.warn("[yandex-download] root-check:", e);
    }

    // ─── Шаг 1: получаем прямую ссылку у Яндекса ───
    const apiUrl =
      `https://cloud-api.yandex.net/v1/disk/public/resources/download?public_key=${
        encodeURIComponent(folderUrl)
      }&path=${encodeURIComponent(path)}`;
    const metaResp = await fetch(apiUrl, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
      },
    });
    const meta = await metaResp.json();

    if (!metaResp.ok || !meta.href) {
      return new Response(`Yandex API error: ${JSON.stringify(meta)}`, {
        status: 500,
        headers: corsHeaders,
      });
    }

    // ─── Шаг 2: пробрасываем Range ───
    const rangeHeader = req.headers.get("range") || req.headers.get("Range");
    const upstreamHeaders: Record<string, string> = {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
      "Referer": "https://disk.yandex.ru/",
    };
    if (rangeHeader) upstreamHeaders["Range"] = rangeHeader;

    const fileResp = await fetch(meta.href, { headers: upstreamHeaders });

    if (!fileResp.ok && fileResp.status !== 206) {
      return new Response(`Yandex download error: ${fileResp.status}`, {
        status: fileResp.status,
        headers: corsHeaders,
      });
    }

    // ─── Шаг 3: формируем ответ ───
    const fileName = path.split("/").pop() || "file";
    const headers = new Headers(corsHeaders);
    headers.set(
      "Content-Type",
      fileResp.headers.get("Content-Type") || "application/octet-stream",
    );
    headers.set(
      "Content-Disposition",
      `attachment; filename*=UTF-8''${encodeURIComponent(fileName)}`,
    );
    headers.set("Accept-Ranges", "bytes");

    const contentLength = fileResp.headers.get("Content-Length");
    if (contentLength) headers.set("Content-Length", contentLength);
    const contentRange = fileResp.headers.get("Content-Range");
    if (contentRange) headers.set("Content-Range", contentRange);

    return new Response(fileResp.body, {
      status: fileResp.status,
      headers,
    });
  } catch (e) {
    return new Response(`Error: ${e.message}`, {
      status: 500,
      headers: corsHeaders,
    });
  }
});
