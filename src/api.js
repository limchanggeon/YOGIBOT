// 백엔드(Uvicorn/FastAPI) 연결 헬퍼.
// .env.local 에 VITE_API_URL / VITE_WS_URL 을 정의하면 자동으로 사용됩니다.

export const API_URL = import.meta.env.VITE_API_URL || '';
export const WS_URL  = import.meta.env.VITE_WS_URL  || '';
export const API_ENABLED = !!API_URL;

async function postJSON(path, body) {
  if (!API_ENABLED) return { ok: false, reason: 'no_api_url' };
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (err) {
    console.error(`POST ${path} failed`, err);
    return { ok: false, reason: 'network_error' };
  }
}

async function getJSON(path) {
  if (!API_ENABLED) return null;
  try {
    const res = await fetch(`${API_URL}${path}`);
    return await res.json();
  } catch (err) {
    console.error(`GET ${path} failed`, err);
    return null;
  }
}

async function deleteJSON(path) {
  if (!API_ENABLED) return { ok: false, reason: 'no_api_url' };
  try {
    const res = await fetch(`${API_URL}${path}`, { method: 'DELETE' });
    return await res.json();
  } catch (err) {
    console.error(`DELETE ${path} failed`, err);
    return { ok: false, reason: 'network_error' };
  }
}

export const api = {
  sendCmdVel:      (linear_x, angular_z) => postJSON('/api/cmd_vel', { linear_x, angular_z }),
  sendEStop:       (engaged)             => postJSON('/api/emergency_stop', { engaged }),
  sendGoal:        (x, y, yaw)           => postJSON('/api/goal', { x, y, yaw }),
  sendMission:     (action)              => postJSON('/api/mission', { action }),
  fetchEvents:     ()                    => getJSON('/api/events'),
  fetchLogs:       ()                    => getJSON('/api/logs'),
  // 자율주행 추가
  sendInitialPose: (x, y, yaw)           => postJSON('/api/initialpose', { x, y, yaw }),
  fetchWaypoints:  ()                    => getJSON('/api/waypoints'),
  addWaypoint:     (x, y, yaw = 0, label = null) => postJSON('/api/waypoints', { x, y, yaw, label }),
  deleteWaypoint:  (id)                  => deleteJSON(`/api/waypoints/${id}`),
  clearWaypoints:  ()                    => postJSON('/api/waypoints/clear', {}),
  missionGoto:     (id)                  => postJSON(`/api/mission/goto/${id}`, {}),
};

// 텔레메트리 WebSocket 구독. 자동 재연결 포함.
// onMessage(data) 로 서버 텔레메트리 객체가 전달됩니다.
export function connectTelemetry(onMessage) {
  if (!WS_URL) return () => {};
  let ws = null;
  let closed = false;
  let retryTimer = null;

  const open = () => {
    if (closed) return;
    ws = new WebSocket(`${WS_URL}/ws/telemetry`);
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)); }
      catch (err) { console.error('telemetry parse error', err); }
    };
    ws.onclose = () => {
      if (closed) return;
      retryTimer = setTimeout(open, 2000);
    };
    ws.onerror = () => { try { ws.close(); } catch {} };
  };

  open();

  return () => {
    closed = true;
    if (retryTimer) clearTimeout(retryTimer);
    if (ws) try { ws.close(); } catch {}
  };
}
