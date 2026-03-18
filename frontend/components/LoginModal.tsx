"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { authApi, QrLoginStartResponse, SessionUserInfo } from "@/lib/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (sessionId: string, user: SessionUserInfo) => void;
}

export default function LoginModal({ isOpen, onClose, onSuccess }: Props) {
  const [tab, setTab] = useState<"browser" | "qrcode">("browser");
  const [loading, setLoading] = useState(false);
  const [qr, setQr] = useState<QrLoginStartResponse | null>(null);
  const [qrImage, setQrImage] = useState("");
  const [status, setStatus] = useState("准备登录");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen) {
      setTab("browser");
      setLoading(false);
      setQr(null);
      setQrImage("");
      setStatus("准备登录");
      setError("");
    }
  }, [isOpen]);

  useEffect(() => {
    if (!qr?.qr_url) {
      setQrImage("");
      return;
    }
    QRCode.toDataURL(qr.qr_url, {
      width: 240,
      margin: 1,
      color: {
        dark: "#1b1713",
        light: "#fffaf3",
      },
    })
      .then(setQrImage)
      .catch(() => setQrImage(""));
  }, [qr]);

  useEffect(() => {
    if (!isOpen || !qr) {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const res = await authApi.pollQRCode(qr.login_id);
        setStatus(res.message || res.status);
        if (res.authenticated && res.session_id && res.user) {
          window.clearInterval(timer);
          onSuccess(res.session_id, res.user);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "二维码状态查询失败");
      }
    }, 2000);

    return () => window.clearInterval(timer);
  }, [isOpen, onSuccess, qr]);

  const importBrowserSession = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await authApi.importBrowserLogin();
      if (res.authenticated && res.session_id && res.user) {
        onSuccess(res.session_id, res.user);
        return;
      }
      setError("浏览器登录态导入失败");
    } catch (err) {
      setError(err instanceof Error ? err.message : "浏览器登录态导入失败");
    } finally {
      setLoading(false);
    }
  };

  const startQRCode = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await authApi.startQRCode();
      setQr(res);
      setStatus("二维码已生成，请直接用手机小红书扫码并确认。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "二维码创建失败");
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div className="modal-title">登录 Rednote Atlas</div>
            <div className="modal-subtitle">优先复用本机已登录的小红书浏览器会话</div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="segmented">
          <button className={`segmented-item ${tab === "browser" ? "active" : ""}`} onClick={() => setTab("browser")}>
            浏览器导入
          </button>
          <button className={`segmented-item ${tab === "qrcode" ? "active" : ""}`} onClick={() => setTab("qrcode")}>
            二维码登录
          </button>
        </div>

        {tab === "browser" ? (
          <div className="login-pane">
            <p className="pane-copy">
              如果你已经在本机浏览器登录了小红书，直接导入即可生成当前应用的 `session_id`。
            </p>
            <button className="btn btn-primary btn-lg" onClick={importBrowserSession} disabled={loading}>
              {loading ? "导入中..." : "导入当前浏览器登录态"}
            </button>
          </div>
        ) : (
          <div className="login-pane">
            <p className="pane-copy">
              这条链路会创建一个扫码登录任务，并在当前弹窗里直接展示二维码。请用手机小红书扫码确认。
            </p>
            <div className="login-actions">
              <button className="btn btn-primary" onClick={startQRCode} disabled={loading}>
                {loading ? "生成中..." : "生成二维码"}
              </button>
              {qr?.qr_url ? (
                <a className="btn btn-outline" href={qr.qr_url} target="_blank" rel="noreferrer">
                  新窗口打开
                </a>
              ) : null}
            </div>
            <div className="login-status-card">
              <div className="status-pill">{qr ? "等待确认" : "未生成"}</div>
              <p>{status}</p>
              {qrImage ? <img src={qrImage} alt="小红书登录二维码" className="qr-image" /> : null}
              {qr?.qr_url ? <code className="code-inline">{qr.qr_url}</code> : null}
            </div>
          </div>
        )}

        {error ? <div className="error-banner">{error}</div> : null}
      </div>
    </div>
  );
}
