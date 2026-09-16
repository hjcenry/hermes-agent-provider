import { FormEvent, useEffect, useMemo, useState } from "react";
import { EnginePanel } from "../Quota";
import {
  api,
  type EngineId,
  type EnginesPayload,
  type HermesConnect,
  type ModelItem,
  type SecretHints,
  type ParseStats,
  type SettingsPayload,
  type User,
} from "../api";

export function SettingsPage({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [engines, setEngines] = useState<EnginesPayload | null>(null);
  const [models, setModels] = useState<ModelItem[]>([]);
  const [snippet, setSnippet] = useState("");
  const [connect, setConnect] = useState<HermesConnect | null>(null);
  const [cursorKey, setCursorKey] = useState("");
  const [qoderKey, setQoderKey] = useState("");
  const [proxyKey, setProxyKey] = useState("");
  const [tokenBusy, setTokenBusy] = useState(false);
  const [engine, setEngine] = useState<EngineId>("qoder");
  const [model, setModel] = useState("");
  const [workspace, setWorkspace] = useState("data/workspace");
  const [timeoutSec, setTimeoutSec] = useState(180);
  const [concurrency, setConcurrency] = useState(2);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [quotaView, setQuotaView] = useState<EngineId>("qoder");
  const [parseStats, setParseStats] = useState<ParseStats | null>(null);

  const publicId = useMemo(() => `${engine}/${model || "…"}`, [engine, model]);

  async function loadForm() {
    const [nextSettings, nextSnippet, nextConnect, nextStats] = await Promise.all([
      api<SettingsPayload>("/api/settings"),
      api<{ text: string }>("/api/hermes-snippet"),
      api<HermesConnect>("/api/hermes-connect"),
      api<ParseStats>("/api/parse-stats"),
    ]);
    setSettings(nextSettings);
    setSnippet(nextSnippet.text);
    setConnect(nextConnect);
    setParseStats(nextStats);
    setEngine(nextSettings.engine);
    setQuotaView(nextSettings.engine);
    setModel(nextSettings.models[nextSettings.engine]);
    setWorkspace(nextSettings.workspace);
    setTimeoutSec(nextSettings.timeout_sec);
    setConcurrency(nextSettings.max_concurrency);
    const listed = await api<{ items: ModelItem[]; default: string }>(
      `/api/engines/models?engine=${nextSettings.engine}`,
    );
    setModels(listed.items);
    if (!listed.items.some((item) => item.id === nextSettings.models[nextSettings.engine])) {
      setModel(listed.default);
    }
  }

  async function loadQuota(refresh = false) {
    setEngines(await api<EnginesPayload>(`/api/engines/status${refresh ? "?refresh=true" : ""}`));
    api<ParseStats>("/api/parse-stats")
      .then(setParseStats)
      .catch(() => undefined);
  }

  useEffect(() => {
    loadForm()
      .then(() => loadQuota())
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "加载失败"));
  }, []);

  const quotaPending = Boolean(engines?.qoder?.loading || engines?.cursor?.loading);
  useEffect(() => {
    if (!quotaPending) return;
    const timer = window.setInterval(() => {
      loadQuota().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [quotaPending]);

  async function changeEngine(next: EngineId) {
    setEngine(next);
    setQuotaView(next);
    setError("");
    try {
      await api("/api/engines/active", { method: "PUT", body: JSON.stringify({ engine: next }) });
      const listed = await api<{ items: ModelItem[]; default: string }>(`/api/engines/models?engine=${next}`);
      setModels(listed.items);
      const preferred = settings?.models[next] || listed.default;
      setModel(listed.items.some((item) => item.id === preferred) ? preferred : listed.default);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换引擎失败");
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          engine,
          models: {
            qoder: engine === "qoder" ? model : settings?.models.qoder,
            cursor: engine === "cursor" ? model : settings?.models.cursor,
          },
          workspace,
          timeout_sec: timeoutSec,
          max_concurrency: concurrency,
        }),
      });
      await loadForm();
      await loadQuota();
      setMessage("已保存，下一轮 /v1 会走新的默认引擎和模型。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function refreshQuota() {
    setRefreshing(true);
    setError("");
    try {
      await loadQuota(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新额度失败");
    } finally {
      setRefreshing(false);
    }
  }

  async function copyText(text: string, label: string) {
    await navigator.clipboard.writeText(text);
    setMessage(`已复制${label}。`);
  }

  function applyHints(hints: SecretHints) {
    setSettings((current) =>
      current
        ? {
            ...current,
            proxy_key_hint: hints.proxy_key_hint,
            cursor_key_hint: hints.cursor_key_hint,
            qoder_key_hint: hints.qoder_key_hint,
          }
        : current,
    );
  }

  async function saveTokens() {
    setTokenBusy(true);
    setError("");
    setMessage("");
    try {
      const hints = await api<SecretHints>("/api/secrets", {
        method: "PUT",
        body: JSON.stringify({
          cursor_api_key: cursorKey || undefined,
          qoder_token: qoderKey || undefined,
          proxy_api_key: proxyKey || undefined,
        }),
      });
      applyHints(hints);
      setCursorKey("");
      setQoderKey("");
      setProxyKey("");
      setConnect(await api<HermesConnect>("/api/hermes-connect"));
      setMessage("令牌已写入 secrets.env 并立即生效，不用重启。");
      loadQuota(true).catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载令牌失败");
    } finally {
      setTokenBusy(false);
    }
  }

  async function reloadTokens() {
    setTokenBusy(true);
    setError("");
    setMessage("");
    try {
      applyHints(await api<SecretHints>("/api/secrets/reload", { method: "POST" }));
      setConnect(await api<HermesConnect>("/api/hermes-connect"));
      setMessage("已从 secrets.env 重新加载令牌。");
      loadQuota(true).catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新加载失败");
    } finally {
      setTokenBusy(false);
    }
  }

  async function logout() {
    await api("/api/logout", { method: "POST" });
    onLogout();
  }

  if (!settings) {
    return (
      <div className="login-wrap">
        <p className="brand">{error || "正在加载设置…"}</p>
      </div>
    );
  }

  return (
    <div className="app">
      <aside className="side">
        <div className="brand-block">
          <p className="brand">hermes-agent-provider</p>
          <p className="muted">Hermes Agent 的本地引擎供应</p>
        </div>
        <div className="side-body">
          <EnginePanel
            qoder={engines?.qoder}
            cursor={engines?.cursor}
            viewing={quotaView}
            onView={setQuotaView}
            onRefresh={refreshQuota}
            refreshing={refreshing}
          />
        </div>
        <div className="side-foot">
          <strong>{user.display_name}</strong>
          <span>{user.role === "admin" ? "管理员" : user.role}</span>
          <button className="btn" type="button" onClick={logout}>
            退出
          </button>
        </div>
      </aside>
      <main className="main">
        <form className="board" onSubmit={save}>
          <section className="card">
            <h2>当前主模型</h2>
            <p className="muted">Hermes 里把 model 写成 default 时，走这里的引擎和模型。</p>
            <div className="choice-row">
              {(["qoder", "cursor"] as EngineId[]).map((id) => (
                <label key={id} className={engine === id ? "choice on" : "choice"}>
                  <input type="radio" name="engine" checked={engine === id} onChange={() => changeEngine(id)} />
                  {id === "qoder" ? "Qoder" : "Cursor"}
                </label>
              ))}
            </div>
            <label className="field">
              <span>模型</span>
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {models.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="public-id">
              Hermes 完整 id：<code>{publicId}</code>
            </p>
          </section>
          <section className="card">
            <h2>最近一次解析</h2>
            <p className="muted">看围栏有没有被 Hermes 认成工具。连续降级再收紧 prompt，不改回嵌套 Agent。</p>
            {parseStats && (parseStats.counts.fence_ok + parseStats.counts.text + parseStats.counts.degraded) > 0 ? (
              <>
                <div className="stat-row">
                  <div>
                    <strong>{parseStats.counts.fence_ok}</strong>
                    <span>成功围栏</span>
                  </div>
                  <div>
                    <strong>{parseStats.counts.text}</strong>
                    <span>纯文本</span>
                  </div>
                  <div>
                    <strong>{parseStats.counts.degraded}</strong>
                    <span>降级文本</span>
                  </div>
                </div>
                <p className="public-id">
                  最近：<code>{parseStats.last.label || "—"}</code>
                  {parseStats.last.tools.length ? ` · ${parseStats.last.tools.join(", ")}` : ""}
                </p>
              </>
            ) : (
              <p className="muted">还没有 /v1 解析记录</p>
            )}
          </section>
          <section className="card">
            <h2>运行</h2>
            <div className="grid-2">
              <label className="field">
                <span>最大并发</span>
                <input type="number" min={1} value={concurrency} onChange={(e) => setConcurrency(Number(e.target.value))} />
              </label>
              <label className="field">
                <span>引擎超时（秒）</span>
                <input type="number" min={1} value={timeoutSec} onChange={(e) => setTimeoutSec(Number(e.target.value))} />
              </label>
            </div>
          </section>
          <section className="card wide">
            <h2>接入 Hermes</h2>
            <p className="muted">
              选 <b>30. Custom endpoint (enter URL manually)</b>。29 也会问同一组字段，但 30 才是官方的手动填地址向导。
            </p>
            <p className="muted">{connect?.howto}</p>
            <div className="connect-grid">
              <div className="stack-in">
                {(connect?.fields || []).map((field) => (
                  <div className="copy-row" key={field.id}>
                    <label className="field">
                      <span>
                        {field.label}
                        {field.hint ? ` · ${field.hint}` : ""}
                      </span>
                      <input
                        readOnly
                        value={field.value}
                        type={field.secret ? "password" : "text"}
                      />
                    </label>
                    <button className="btn" type="button" onClick={() => copyText(field.value, field.label)}>
                      复制
                    </button>
                  </div>
                ))}
              </div>
              <div className="stack-in">
                <pre className="snippet">{connect?.snippet || snippet}</pre>
                <button className="btn" type="button" onClick={() => copyText(connect?.snippet || snippet, "Hermes 配置片段")}>
                  复制 YAML 片段
                </button>
              </div>
            </div>
          </section>
          <section className="card wide">
            <h2>引擎令牌</h2>
            <p className="muted">粘贴后点「加载并生效」，写入 secrets.env 并立刻给当前进程用，不用重启。空白表示保持原值。</p>
            <div className="token-grid">
              <label className="field">
                <span>CURSOR_API_KEY · 当前 {settings.cursor_key_hint || "未配置"}</span>
                <input
                  type="password"
                  autoComplete="off"
                  placeholder="粘贴新的 Cursor token"
                  value={cursorKey}
                  onChange={(e) => setCursorKey(e.target.value)}
                />
              </label>
              <label className="field">
                <span>QODER_PERSONAL_ACCESS_TOKEN · 当前 {settings.qoder_key_hint || "未配置"}</span>
                <input
                  type="password"
                  autoComplete="off"
                  placeholder="粘贴新的 Qoder 令牌"
                  value={qoderKey}
                  onChange={(e) => setQoderKey(e.target.value)}
                />
              </label>
              <label className="field">
                <span>PROXY_API_KEY · 当前 {settings.proxy_key_hint || "未配置"}</span>
                <input
                  type="password"
                  autoComplete="off"
                  placeholder="粘贴新的 Hermes 调用密钥"
                  value={proxyKey}
                  onChange={(e) => setProxyKey(e.target.value)}
                />
              </label>
            </div>
            <div className="choice-row">
              <button className="btn primary" type="button" disabled={tokenBusy || !(cursorKey || qoderKey || proxyKey)} onClick={saveTokens}>
                {tokenBusy ? "加载中" : "加载并生效"}
              </button>
              <button className="btn" type="button" disabled={tokenBusy} onClick={reloadTokens}>
                从 secrets.env 重新加载
              </button>
            </div>
          </section>
          <section className="card wide">
            <h2>连接</h2>
            <p className="muted">
              监听 {settings.listen} · base_url <code>{settings.base_url}</code>
            </p>
            <label className="field">
              <span>工作目录</span>
              <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} />
            </label>
            <p className="muted">{settings.restart_hint}</p>
          </section>
          {error ? <div className="error-box wide">{error}</div> : null}
          {message ? <div className="ok-box wide">{message}</div> : null}
          <button className="btn primary wide" type="submit" disabled={saving}>
            {saving ? "保存中" : "保存"}
          </button>
        </form>
      </main>
    </div>
  );
}
