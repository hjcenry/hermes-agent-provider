import { FormEvent, useState } from "react";
import { api, type User } from "../api";

export function LoginPage({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const data = await api<{ user: User }>("/api/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onLogin(data.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    }
  }

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={submit}>
        <p className="brand">hermes-agent-provider</p>
        <p className="muted">给 Hermes Agent 接本机 Cursor、Qoder，以后也能加别的引擎。</p>
        <label className="field">
          <span>账号</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label className="field">
          <span>密码</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {error ? <div className="error-box">{error}</div> : null}
        <button className="btn primary" type="submit">进入设置</button>
      </form>
    </div>
  );
}
