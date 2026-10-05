import "jsr:@supabase/functions-js/edge-runtime.d.ts";

// ─── Настройки CORS ───
// Разрешаем только ваш домен — защищает от сторонних вызовов.
const ALLOWED_HOSTS = [
  "dimonmaxx.github.io",
  // "ваш-домен.ru",
];

function hostAllowed(origin: string): boolean {
  if (!origin) return false;
  try {
    const u = new URL(origin);
    return ALLOWED_HOSTS.some(h =>
      u.hostname === h || u.hostname.endsWith("." + h)
    );
  } catch {
    return false;
  }
}

function buildCors(origin: string) {
  return {
    "Access-Control-Allow-Origin": hostAllowed(origin) ? origin : ALLOWED_HOSTS[0],
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

// ─── Простая защита от спама ───
// Хранится в памяти инстанса Edge Function. Для надёжной защиты
// можно вынести в таблицу Supabase, но и это отсекает 95% спама.
const RATE_LIMIT_WINDOW_MS = 60_000;    // 1 минута
const RATE_LIMIT_MAX = 3;               // 3 заявки в минуту с одного IP
const ipHits = new Map<string, number[]>();

function rateLimitOk(ip: string): boolean {
  const now = Date.now();
  const hits = (ipHits.get(ip) || []).filter(t => now - t < RATE_LIMIT_WINDOW_MS);
  if (hits.length >= RATE_LIMIT_MAX) return false;
  hits.push(now);
  ipHits.set(ip, hits);
  return true;
}

// ─── Экранирование HTML ───
function esc(s: unknown): string {
  if (s === null || s === undefined) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ─── Формирование письма ───
// Названия полей → человекочитаемые подписи
const FIELD_LABELS: Record<string, string> = {
  name: "Имя отправителя",
  email: "Email отправителя",
  category: "Категория",
  title: "Название материала",
  description: "Описание",
  download_link: "Ссылка для скачивания",
  // Книги
  author: "Автор",
  format: "Формат",
  // Программы
  version: "Версия",
  size: "Размер",
  // Музыка
  artist: "Исполнитель",
  music_year: "Год (музыка)",
  // Игры
  platform: "Платформа",
  game_year: "Год (игра)",
  // Фильмы
  movie_year: "Год (фильм)",
  movie_format: "Формат (фильм)",
  // Общее
  comment: "Дополнительная информация",
};

const CATEGORY_LABELS: Record<string, string> = {
  programs: "💻 Программы",
  books: "📚 Книги",
  music: "🎵 Музыка",
  games: "🎮 Игры",
  movies: "🎬 Фильмы",
  articles: "✍️ Статьи",
  misc: "📦 Разное",
};

function buildHtml(data: Record<string, string>): string {
  const rows: string[] = [];
  // Сначала важные поля
  const order = [
    "name", "email", "category", "title", "description", "download_link",
    "author", "format", "version", "size",
    "artist", "music_year",
    "platform", "game_year",
    "movie_year", "movie_format",
    "comment",
  ];
  for (const key of order) {
    if (!data[key]) continue;
    let value = data[key];
    if (key === "category") {
      value = CATEGORY_LABELS[value] || value;
    }
    if (key === "download_link") {
      const safe = esc(value);
      value = `<a href="${safe}" target="_blank" rel="noopener">${safe}</a>`;
    } else {
      value = esc(value).replace(/\n/g, "<br>");
    }
    rows.push(
      `<tr>
        <td style="padding:8px 12px; background:#f8fafc; font-weight:600; width:180px; vertical-align:top; border-bottom:1px solid #e5e7eb;">${FIELD_LABELS[key] || key}</td>
        <td style="padding:8px 12px; border-bottom:1px solid #e5e7eb;">${value}</td>
      </tr>`
    );
  }
  const now = new Date().toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
  return `
  <!DOCTYPE html>
  <html>
  <head><meta charset="utf-8"></head>
  <body style="font-family:Arial,sans-serif; background:#f8fafc; padding:20px;">
    <div style="max-width:700px; margin:0 auto; background:white; border-radius:12px; overflow:hidden; box-shadow:0 4px 16px rgba(0,0,0,0.06);">
      <div style="background:#2563eb; color:white; padding:20px 24px;">
        <h2 style="margin:0; font-size:20px;">📥 Новая заявка на материал</h2>
        <div style="opacity:0.85; margin-top:4px; font-size:13px;">Получено: ${esc(now)} (МСК)</div>
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:14px; color:#1e293b;">
        ${rows.join("")}
      </table>
      <div style="padding:16px 24px; background:#f1f5f9; font-size:12px; color:#64748b;">
        Отправлено через форму на сайте MyFiles.
      </div>
    </div>
  </body>
  </html>`;
}

function buildText(data: Record<string, string>): string {
  const lines = ["Новая заявка на материал", ""];
  for (const key of Object.keys(data)) {
    if (!data[key]) continue;
    const label = FIELD_LABELS[key] || key;
    lines.push(`${label}: ${data[key]}`);
  }
  return lines.join("\n");
}

// ─── Основной обработчик ───
Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  const corsHeaders = buildCors(origin);

  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", {
      status: 405,
      headers: corsHeaders,
    });
  }

  // Проверка Origin
  if (!hostAllowed(origin)) {
    return new Response("Forbidden", { status: 403, headers: corsHeaders });
  }

  // Rate-limit по IP
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "unknown";
  if (!rateLimitOk(ip)) {
    return new Response(
      JSON.stringify({ ok: false, error: "Слишком много заявок. Попробуйте позже." }),
      { status: 429, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  // Парсим тело
  let body: Record<string, string> = {};
  try {
    const contentType = req.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      body = await req.json();
    } else {
      const form = await req.formData();
      for (const [k, v] of form.entries()) {
        if (typeof v === "string") body[k] = v;
      }
    }
  } catch (e) {
    return new Response(
      JSON.stringify({ ok: false, error: "Некорректные данные" }),
      { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  // Honeypot (анти-бот): если заполнено поле bot-field — тихо игнорируем
  if (body["bot-field"]) {
    return new Response(
      JSON.stringify({ ok: true }),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  // Валидация обязательных полей
  const required = ["name", "email", "category", "title", "description", "download_link"];
  const missing = required.filter(k => !body[k]?.trim());
  if (missing.length > 0) {
    return new Response(
      JSON.stringify({ ok: false, error: "Не заполнены обязательные поля: " + missing.join(", ") }),
      { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  // Проверка email
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body["email"])) {
    return new Response(
      JSON.stringify({ ok: false, error: "Некорректный email" }),
      { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  // Читаем секреты
  const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");
  const CONTACT_EMAIL = Deno.env.get("CONTACT_EMAIL");
  const FROM_EMAIL = Deno.env.get("FROM_EMAIL") || "onboarding@resend.dev";

  if (!RESEND_API_KEY || !CONTACT_EMAIL) {
    console.error("Не заданы RESEND_API_KEY или CONTACT_EMAIL");
    return new Response(
      JSON.stringify({ ok: false, error: "Сервер не настроен" }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  // Формируем письмо
  const subject = `📥 Новая заявка: ${body["title"]} (${CATEGORY_LABELS[body["category"]] || body["category"]})`;
  const html = buildHtml(body);
  const text = buildText(body);

  // Отправляем через Resend
  try {
    const resp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: `MyFiles Forms <${FROM_EMAIL}>`,
        to: [CONTACT_EMAIL],
        reply_to: body["email"],
        subject,
        html,
        text,
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      console.error("Resend error:", resp.status, errText);
      return new Response(
        JSON.stringify({ ok: false, error: "Ошибка отправки письма" }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    return new Response(
      JSON.stringify({ ok: true }),
      { status: 200, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (e) {
    console.error("Ошибка запроса к Resend:", e);
    return new Response(
      JSON.stringify({ ok: false, error: "Ошибка сети" }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
