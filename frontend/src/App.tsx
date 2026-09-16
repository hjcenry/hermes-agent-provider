import { useEffect, useState } from "react";
import { api, type User } from "./api";
import { LoginPage } from "./pages/Login";
import { SettingsPage } from "./pages/Settings";

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api<{ user: User }>("/api/me")
      .then((data) => setUser(data.user))
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, []);

  if (!ready) {
    return (
      <div className="login-wrap">
        <p className="brand">正在检查登录…</p>
      </div>
    );
  }
  if (!user) {
    return <LoginPage onLogin={setUser} />;
  }
  return <SettingsPage user={user} onLogout={() => setUser(null)} />;
}
