// supabase/functions/terabox-download/index.ts
//
// Прокси для скачивания файлов TeraBox.
// Принимает ?url=<dlink>&name=<fallback-name>.
// Имя файла берётся из upstream-заголовка Content-Disposition,
// а параметр `name` используется только как fallback.

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const TERABOX_COOKIE = Deno.env.get("TERABOX_COOKIE") ?? "";

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) " +
  "Chrome/120.0.0.0 Safari/537.36";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Range",
  "Access-Control-Expose-Headers":
    "Content-Length, Content-Range, Content-Disposition, Accept-Ranges",
};

/**
 * Извлекает имя файла из заголовка Content-Disposition.
 * Поддерживает:
 *   attachment; filename="file.exe"
 *   attachment; filename*=UTF-8''file.exe
 *   attachment; filename="file.exe"; filename*=UTF-8''file.exe
 */
function extractFilenameFromHeader(cd: string | null): string | null {
  if (!cd) return null;

  // 1. filename*=UTF-8''... (RFC 5987)
  const starMatch = cd.match(/filename\*\s*=\s*([^;]+)/i);
  if (starMatch) {
    const raw = starMatch[1].trim();
    const utf8Match = raw.match(/^UTF-8''(.+)$/i);
    if (utf8Match) {
      try {
        return decodeURIComponent(utf8Match[1]);
      } catch (_) { /* ignore */ }
    }
    // Иногда без префикса
    try {
      return decodeURIComponent(raw.replace(/^['"]|['"]$/g, ""));
    } catch (_) { /* ignore */ }
  }

  // 2. Обычный filename="..."
  const plainMatch = cd.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
  if (plainMatch) {
    const val = (plainMatch[1] || plainMatch[2] || "").trim();
    if (val) {
      // Попытка декодировать (иногда TeraBox присылает percent-encoded)
      try {
        return decodeURIComponent(val);
      } catch (_) {
        return val;
      }
    }
  }

  return null;
}

/**
 * Проверяет, что имя содержит расширение.
 */
function hasExtension(name: string): boolean {
  return /\.[a-zA-Z0-9]{1,8}$/.test(name);
}

/**
 * Обрезает слишком длинные имена, чистит запрещённые символы.
 */
function sanitizeFilename(name: string): string {
  let s = (name || "").replace(/["\r\n\t\\]/g, "_");
  // Ограничение по длине (обычно достаточно 200 символов)
  if (s.length > 200) {
    // Сохраняем расширение
    const dot = s.lastIndexOf(".");
    if (dot > 0 && dot > s.length - 10) {
      const ext = s.slice(dot);
      s = s.slice(0, 200 - ext.length) + ext;
    } else {
      s = s.slice(0, 200);
    }
  }
  return s;
}

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const reqUrl = new URL(req.url);
  const dlink = reqUrl.searchParams.get("url");
  const fallbackName = reqUrl.searchParams.get("name") || "file.bin";

  if (!dlink) {
    return json({ error: "missing ?url=" }, 400);
  }
  if (!TERABOX_COOKIE) {
    return json(
      { error: "server not configured: TERABOX_COOKIE missing" },
      500,
    );
  }

  // Собираем заголовки для TeraBox
  const upstreamHeaders: Record<string, string> = {
    "Cookie": `ndus=${TERABOX_COOKIE}`,
    "User-Agent": USER_AGENT,
    "Referer": "https://www.1024tera.com/",
    "Accept": "*/*",
  };

  const range = req.headers.get("range");
  if (range) upstreamHeaders["Range"] = range;

  let resp: Response;
  try {
    resp = await fetch(dlink, {
      method: "GET",
      headers: upstreamHeaders,
      redirect: "follow",
    });
  } catch (e) {
    return json({ error: "fetch failed", detail: String(e) }, 502);
  }

  if (!resp.ok) {
    let text = "";
    try { text = await resp.text(); } catch (_) { /* ignore */ }
    return new Response(
      JSON.stringify({
        error: "terabox upstream error",
        upstream_status: resp.status,
        upstream_body: text.slice(0, 800),
      }),
      {
        status: resp.status,
        headers: { "Content-Type": "application/json", ...CORS_HEADERS },
      },
    );
  }

  // ─── ОПРЕДЕЛЯЕМ ИМЯ ФАЙЛА ───
  // 1. Пытаемся взять из upstream Content-Disposition (самое правильное)
  const upstreamCD = resp.headers.get("content-disposition");
  const fromUpstream = extractFilenameFromHeader(upstreamCD);

  // 2. Fallback: параметр `name` (то, что прислал фронт)
  // 3. Fallback: "file.bin"

  let finalName: string;

  if (fromUpstream && hasExtension(fromUpstream)) {
    // Есть реальное имя с расширением — используем его
    finalName = sanitizeFilename(fromUpstream);
  } else if (fallbackName && hasExtension(fallbackName)) {
    // Фронт прислал осмысленное имя с расширением
    finalName = sanitizeFilename(fallbackName);
  } else if (fromUpstream) {
    // Upstream дал имя без расширения — оставим как есть
    finalName = sanitizeFilename(fromUpstream);
  } else {
    // Совсем ничего — используем fallback как есть
    finalName = sanitizeFilename(fallbackName || "file.bin");
  }

  // ─── ФОРМИРУЕМ ОТВЕТ ───
  const outHeaders = new Headers(CORS_HEADERS);

  const ct = resp.headers.get("content-type");
  if (ct) outHeaders.set("Content-Type", ct);
  else outHeaders.set("Content-Type", "application/octet-stream");

  const cl = resp.headers.get("content-length");
  if (cl) outHeaders.set("Content-Length", cl);

  const cr = resp.headers.get("content-range");
  if (cr) outHeaders.set("Content-Range", cr);

  const ar = resp.headers.get("accept-ranges");
  if (ar) outHeaders.set("Accept-Ranges", ar);
  else outHeaders.set("Accept-Ranges", "bytes");

  // Content-Disposition с правильным именем
  const asciiName = finalName.replace(/[^\x20-\x7E]/g, "_");
  outHeaders.set(
    "Content-Disposition",
    `attachment; filename="${asciiName}"; ` +
      `filename*=UTF-8''${encodeURIComponent(finalName)}`,
  );

  return new Response(resp.body, {
    status: resp.status,
    headers: outHeaders,
  });
});

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...CORS_HEADERS },
  });
}
