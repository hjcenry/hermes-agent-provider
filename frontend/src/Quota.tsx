import type { EngineId, EngineStatus, QuotaBucket } from "./api";

const META: Record<EngineId, { title: string; login: string; plan: string; extra: string }> = {
  qoder: {
    title: "Qoder 用量",
    login: "qodercli login，或在右侧加载个人令牌",
    plan: "套餐内 Credits",
    extra: "资源包",
  },
  cursor: {
    title: "Cursor 用量",
    login: "在右侧加载 CURSOR_API_KEY，或本机 SDK 登录",
    plan: "Cursor 模型",
    extra: "其他模型",
  },
};

function isLoggedIn(status: EngineStatus) {
  return Boolean(status.ok || status.account?.id || status.expires_at) && status.fallback_reason !== "auth_invalid";
}

function fmt(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  if (Math.abs(value - Math.round(value)) < 0.05) return String(Math.round(value));
  return value.toFixed(1);
}

function usedOf(bucket?: QuotaBucket | null) {
  if (!bucket) return null;
  if (bucket.used != null) return bucket.used;
  if (bucket.remaining != null && bucket.total != null) return Math.max(bucket.total - bucket.remaining, 0);
  return null;
}

function usedPct(bucket?: QuotaBucket | null) {
  if (!bucket) return 0;
  if (bucket.percentage != null) return Math.min(100, Math.max(0, bucket.percentage));
  const used = usedOf(bucket);
  if (used != null && bucket.total) {
    return Math.min(100, Math.max(0, (used / bucket.total) * 100));
  }
  return 0;
}

function refreshHint(expiresAt?: string) {
  const match = (expiresAt || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return "";
  return `将于${Number(match[1])}年${Number(match[2])}月${Number(match[3])}日刷新`;
}

function planBadge(type?: string) {
  const key = (type || "").toLowerCase();
  if (key === "ultra") return "Ultra";
  if (key === "pro_plus" || key === "proplus" || key === "pro+") return "Pro+";
  if (key.includes("enterprise")) return "Enterprise";
  if (key.includes("team")) return "Teams";
  if (key === "pro") return "Pro";
  if (key === "free") return "Free";
  return "";
}

function accountName(status: EngineStatus) {
  const label = (status.account?.label || "").trim();
  if (!label) return "";
  if (label.includes("…") || label.includes("...")) return "";
  if (label.includes("登录") || label.includes("令牌") || label.includes("本地") || label.includes("密钥")) return "";
  return label;
}

function QuotaBlock({
  title,
  badge,
  hint,
  bucket,
  loading,
}: {
  title: string;
  badge?: string;
  hint?: string;
  bucket?: QuotaBucket | null;
  loading?: boolean;
}) {
  const pct = usedPct(bucket);
  return (
    <div className="quota-block">
      <div className="quota-head">
        <div className="quota-title">
          <b>{title}</b>
          {badge ? <em className="quota-badge">{badge}</em> : null}
        </div>
        {hint ? <span className="quota-hint">{hint}</span> : null}
      </div>
      <div
        className={`quota-bar${loading || !bucket ? " empty" : ""}`}
        role="progressbar"
        aria-label={title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div className="quota-bar-track" />
        <div className="quota-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="quota-meta">
        <span>
          {loading || !bucket
            ? "读取中…"
            : bucket.unit === "%"
              ? `已使用${Math.round(pct)}%`
              : `${fmt(usedOf(bucket))}/${fmt(bucket.total)}（已使用${Math.round(pct)}%）`}
        </span>
        <span>
          {loading || !bucket
            ? ""
            : bucket.unit === "%"
              ? `剩余${fmt(bucket.remaining)}%`
              : `剩余${fmt(bucket.remaining)}`}
        </span>
      </div>
      {bucket?.note ? <p className="quota-note">{bucket.note}</p> : null}
    </div>
  );
}

function RefreshIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path
        d="M21 12a9 9 0 1 1-3-6.7M21 4v6h-6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function EngineCard({
  status,
  engine,
  onRefresh,
  refreshing,
}: {
  status?: EngineStatus | null;
  engine: EngineId;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const meta = META[engine];
  const busy = Boolean(refreshing || status?.loading);
  if (!status) {
    return (
      <div className="qoder-card">
        <div className="qoder-card-top">
          <strong>{meta.title}</strong>
          <button className="qoder-refresh spin" type="button" disabled aria-label="正在读取用量">
            <RefreshIcon />
          </button>
        </div>
        <QuotaBlock title={meta.plan} loading />
        <QuotaBlock title={meta.extra} loading />
      </div>
    );
  }
  const loggedIn = isLoggedIn(status);
  const name = accountName(status);
  const plan = status.quota?.plan;
  const other = status.quota?.other;
  const shared = status.quota?.shared;
  const addOn = status.quota?.add_on;
  const showMeters = loggedIn && (plan || other || shared || addOn || status.loading);
  return (
    <div className={`qoder-card${loggedIn ? "" : " warn"}`}>
      <div className="qoder-card-top">
        <div className="qoder-card-head">
          <strong>{meta.title}</strong>
          {name ? <span className="qoder-card-name">{name}</span> : null}
        </div>
        <button
          className={`qoder-refresh${busy ? " spin" : ""}`}
          type="button"
          disabled={!onRefresh || refreshing}
          aria-label="刷新用量"
          onClick={() => onRefresh?.()}
        >
          <RefreshIcon />
        </button>
      </div>
      {showMeters ? (
        engine === "cursor" ? (
          <>
            <QuotaBlock
              title="Cursor 模型"
              badge={planBadge(status.account?.type)}
              hint={refreshHint(status.expires_at)}
              bucket={plan}
              loading={busy && !plan}
            />
            <QuotaBlock title="其他模型" bucket={other} loading={busy && !other} />
            {addOn ? <QuotaBlock title="按需额度" bucket={addOn} /> : null}
            {shared ? <QuotaBlock title="团队额度" bucket={shared} /> : null}
          </>
        ) : (
          <>
            <QuotaBlock
              title={meta.plan}
              badge={planBadge(status.account?.type)}
              hint={refreshHint(status.expires_at)}
              bucket={plan}
              loading={busy && !plan}
            />
            {shared || status.loading ? <QuotaBlock title="资源包" bucket={shared} loading={busy && !shared} /> : null}
            {addOn ? <QuotaBlock title="加量包" bucket={addOn} /> : null}
          </>
        )
      ) : (
        <p className="qoder-note">{loggedIn ? status.hint || status.quota?.text || "已登录，但暂时读不到额度" : meta.login}</p>
      )}
    </div>
  );
}

export function EnginePanel({
  qoder,
  cursor,
  viewing,
  onView,
  onRefresh,
  refreshing,
}: {
  qoder?: EngineStatus | null;
  cursor?: EngineStatus | null;
  viewing: EngineId;
  onView: (engine: EngineId) => void;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const status = viewing === "cursor" ? cursor : qoder;
  return (
    <div className="engine-panel">
      <div className="engine-switch" role="tablist" aria-label="查看额度">
        {(["qoder", "cursor"] as EngineId[]).map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={viewing === id}
            className={viewing === id ? "active" : ""}
            onClick={() => onView(id)}
          >
            {id === "qoder" ? "Qoder" : "Cursor"}
          </button>
        ))}
      </div>
      <EngineCard status={status} engine={viewing} onRefresh={onRefresh} refreshing={refreshing} />
    </div>
  );
}
