// supabase/functions/github-dispatch/index.ts
import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const GITHUB_TOKEN  = Deno.env.get("GITHUB_TOKEN")!;
const GITHUB_OWNER  = Deno.env.get("GITHUB_OWNER")  ?? "DimonMaxx";
const GITHUB_REPO   = Deno.env.get("GITHUB_REPO")   ?? "DimonMaxx.github.io"; // Исправлено на актуальный репозиторий!
const SUPABASE_URL  = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_ANON = Deno.env.get("SUPABASE_ANON_KEY")!;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  if (req.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  // 1. Проверяем JWT
  const authHeader = req.headers.get("Authorization") || "";
  if (!authHeader.startsWith("Bearer ")) {
    return json({ error: "Missing or invalid Authorization header" }, 401);
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_ANON, {
    global: { headers: { Authorization: authHeader } },
  });

  const { data: userData, error: userErr } = await supabase.auth.getUser();
  if (userErr || !userData?.user) {
    return json({ error: "Unauthorized" }, 401);
  }

  // 2. Проверяем роль admin в profiles
  const { data: profile, error: profileErr } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", userData.user.id)
    .single();

  if (profileErr || profile?.role !== "admin") {
    return json({ error: "Forbidden: admin only" }, 403);
  }

  // 3. Принимаем тело запроса
  let body: { workflow?: string; inputs?: Record<string, any> };
  try {
    body = await req.json();
  } catch {
    return json({ error: "Invalid JSON body" }, 400);
  }

  const { workflow, inputs } = body;
  if (!workflow || typeof workflow !== "string" || !/^[a-z0-9._-]+\.yml$/i.test(workflow)) {
    return json({ error: "Invalid workflow name" }, 400);
  }
  if (!inputs || typeof inputs !== "object") {
    return json({ error: "Missing inputs" }, 400);
  }

  // ─── 4. ТРАНСФОРМАЦИЯ ВХОДНЫХ ДАННЫХ ───
  // Переводим старый формат { sections: "books,music" } 
  // в новый формат чекбоксов { sync_books: true, sync_music: true, ... }
  let finalInputs = { ...inputs };

  if (workflow === 'sync-content.yml') {
    const allowedSections = ['books', 'programs', 'music', 'games', 'movies', 'misc', 'articles', 'news'];
    
    // Базовые настройки для нового YAML
    const ghInputs: Record<string, any> = {
      mode: 'Полная синхронизация (GitHub + Sheets + JSON)',
      dry_run: inputs.dry_run === true
    };
    
    // По умолчанию снимаем все галочки
    allowedSections.forEach(sec => ghInputs[`sync_${sec}`] = false);
    
    // Если фронтенд передал строку sections, разбиваем её по запятой
    const sectionsStr = typeof inputs.sections === 'string' ? inputs.sections : '';
    
    // Если строка пустая, значит выбрано "обновить всё" (ставим true везде)
    const requestedSections = sectionsStr.trim() !== '' 
      ? sectionsStr.split(',') 
      : allowedSections;
      
    // Ставим галочки (true) только для выбранных разделов
    requestedSections.forEach((sec: string) => {
      const clean = sec.trim();
      if (allowedSections.includes(clean)) {
        ghInputs[`sync_${clean}`] = true;
      }
    });
    
    // Заменяем старые входные данные на новые
    finalInputs = ghInputs;
  }

  // 5. Проксируем на GitHub
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;
  
  let ghResp: Response;
  try {
    ghResp = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `token ${GITHUB_TOKEN}`,
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "MyFiles-Admin-Proxy",
      },
      body: JSON.stringify({ ref: "main", inputs: finalInputs }),
    });
  } catch (e) {
    return json({ error: "GitHub request failed: " + String(e) }, 502);
  }

  if (ghResp.status === 204) {
    return json({ ok: true });
  }
  
  const text = await ghResp.text();
  return json({ error: `GitHub API ${ghResp.status}: ${text}` }, ghResp.status);
});