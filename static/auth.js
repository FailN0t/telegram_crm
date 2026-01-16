const statusConnection = document.getElementById("status-connection");
      const statusAuth = document.getElementById("status-auth");
      const statusUser = document.getElementById("status-user");
      const authResult = document.getElementById("auth-result");

      const themeButton = document.getElementById("btn-theme");

      function setResult(ok, text) {
        authResult.className = "result " + (ok ? "ok" : "err");
        authResult.textContent = text;
      }

      async function refreshStatus() {
        try {
          const res = await fetch("/api/ui/status");
          const data = await res.json();
          statusConnection.textContent = "Connection: " + (data.connected ? "on" : "off");
          statusAuth.textContent = "Auth: " + (data.authorized ? "yes" : "no");
          statusUser.textContent = "User: " + (data.user ? data.user.username || data.user.id : "--");
        } catch (err) {
          statusConnection.textContent = "Connection: error";
          statusAuth.textContent = "Auth: error";
        }
      }

      function setThemeDark(enabled) {
        document.documentElement.classList.toggle("dark", enabled);
        if (themeButton) {
          const icon = themeButton.querySelector(".material-icons-outlined");
          if (icon) {
            icon.textContent = enabled ? "light_mode" : "dark_mode";
          }
        }
        try {
          localStorage.setItem("themeDark", enabled ? "1" : "0");
        } catch (err) {
          // ignore
        }
      }

      if (themeButton) {
        themeButton.addEventListener("click", () => {
          setThemeDark(!document.documentElement.classList.contains("dark"));
        });
        try {
          const saved = localStorage.getItem("themeDark");
          if (saved === "1") {
            setThemeDark(true);
          }
        } catch (err) {
          // ignore
        }
      }

      async function requestCode() {
        const phone = document.getElementById("auth-phone").value.trim();
        const res = await fetch("/api/ui/auth/request-code", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phone: phone || null })
        });
        const data = await res.json();
        setResult(data.success, data.message || data.status);
      }

      async function submitCode() {
        const phone = document.getElementById("auth-phone").value.trim();
        const code = document.getElementById("auth-code").value.trim();
        const res = await fetch("/api/ui/auth/submit-code", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phone: phone || null, code: code })
        });
        const data = await res.json();
        setResult(data.success, data.message || data.status);
        refreshStatus();
      }

      async function submitPassword() {
        const password = document.getElementById("auth-password").value.trim();
        const res = await fetch("/api/ui/auth/submit-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: password })
        });
        const data = await res.json();
        setResult(data.success, data.message || data.status);
        refreshStatus();
      }

      async function logout() {
        const res = await fetch("/api/ui/auth/logout", { method: "POST" });
        const data = await res.json();
        setResult(data.success, data.message || data.status);
        refreshStatus();
      }

      document.getElementById("btn-send-code").addEventListener("click", requestCode);
      document.getElementById("btn-submit-code").addEventListener("click", submitCode);
      document.getElementById("btn-submit-password").addEventListener("click", submitPassword);
      document.getElementById("btn-refresh-status").addEventListener("click", refreshStatus);
      document.getElementById("btn-logout").addEventListener("click", logout);

      function scheduleAuthStatus() {
        setTimeout(async () => {
          await refreshStatus();
          scheduleAuthStatus();
        }, 5000);
      }

      refreshStatus();
      scheduleAuthStatus();
