import React, { useEffect, useRef, useState } from 'react';
import { Bot, MapPin, Video, ScrollText, Calendar, Search, Filter, ArrowLeftRight, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Square, Gauge, Send, Power, Play, Pause, RotateCcw, Terminal, Radio } from 'lucide-react';
import { MapContainer, TileLayer, Marker, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { PieChart, Pie, Cell, ResponsiveContainer, LineChart, Line, XAxis, YAxis, BarChart, Bar } from 'recharts';
import { api, connectTelemetry, API_ENABLED } from './api';

// ============================================================
// 유틸
// ============================================================
function quatToYaw(q) {
  const yaw = Math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z));
  return (yaw * 180 / Math.PI).toFixed(1);
}

const BASE_LAT = 36.3268;
const BASE_LNG = 127.3386;
const DEMO_MODE = import.meta.env.VITE_DEMO === '1';

// ============================================================
// 데모용 더미 데이터
// ============================================================
const DEMO_INIT = {
  odom: { twist: { linear: { x: 0.42 }, angular: { z: 0.18 } } },
  battery: { percentage: 0.84, voltage: 12.4, current: 1.6 },
  sensorState: { bumper: 0, cliff: 0, torque: true },
  amclPose: {
    pose: { pose: {
      position: { x: 3.21, y: -1.85 },
      orientation: { x: 0, y: 0, z: 0.38, w: 0.92 }
    }}
  },
  goal: { pose: { position: { x: 8.4, y: 4.2 } } },
  planData: { poses: Array.from({ length: 12 }, (_, i) => ({
    pose: { position: {
      x: 3.21 + (8.4 - 3.21) * (i / 11) + Math.sin(i / 2) * 0.3,
      y: -1.85 + (4.2 - (-1.85)) * (i / 11) + Math.cos(i / 2) * 0.2
    }}
  })) },
  events: [
    { event_type: 'MISSION_COMPLETE', result: 'SUCCESS', mission_id: 'M-1042', duration_sec: 187, distance_m: 64.3, timestamp: '2026-05-08T11:22:14' },
    { event_type: 'OBSTACLE_DETECTED', pose: { x: 5.3, y: 2.1 }, min_range_m: 0.42, action: 'REPLAN', timestamp: '2026-05-08T11:18:51' },
    { event_type: 'BATTERY_LOW', voltage: 11.6, percentage: 0.18, action: 'RETURN_HOME', timestamp: '2026-05-08T10:54:09' },
    { event_type: 'MISSION_COMPLETE', result: 'SUCCESS', mission_id: 'M-1041', duration_sec: 142, distance_m: 51.7, timestamp: '2026-05-08T10:33:28' },
    { event_type: 'MISSION_COMPLETE', result: 'FAIL',    mission_id: 'M-1040', duration_sec: 92,  distance_m: 28.4, timestamp: '2026-05-08T10:11:02' },
  ],
  speedHistory: [
    { time: '-50s', v: 0.18 }, { time: '-40s', v: 0.32 }, { time: '-30s', v: 0.48 },
    { time: '-20s', v: 0.41 }, { time: '-10s', v: 0.36 }, { time: '현재', v: 0.42 },
  ],
  logs: {
    totalMissions: 1042,
    avgDurationSec: 168,
    totalDistanceKm: 312.7,
    weekly: [
      { name: '월', count: 142 }, { name: '화', count: 168 }, { name: '수', count: 134 },
      { name: '목', count: 192 }, { name: '금', count: 211 }, { name: '토', count: 88 }, { name: '일', count: 107 },
    ],
    rows: [
      { id: 'M-1042', date: '2026-05-08 11:22', from: '본부 A', to: '301호',  duration: '3분 7초',  distance: '64.3m', result: 'SUCCESS' },
      { id: 'M-1041', date: '2026-05-08 10:33', from: '본부 A', to: '208호',  duration: '2분 22초', distance: '51.7m', result: 'SUCCESS' },
      { id: 'M-1040', date: '2026-05-08 10:11', from: '본부 A', to: '102호',  duration: '1분 32초', distance: '28.4m', result: 'FAIL'    },
      { id: 'M-1039', date: '2026-05-08 09:48', from: '본부 B', to: '405호',  duration: '4분 12초', distance: '88.1m', result: 'SUCCESS' },
      { id: 'M-1038', date: '2026-05-08 09:21', from: '본부 A', to: '212호',  duration: '2분 51초', distance: '47.6m', result: 'SUCCESS' },
      { id: 'M-1037', date: '2026-05-08 08:55', from: '본부 A', to: '309호',  duration: '3분 33초', distance: '71.0m', result: 'SUCCESS' },
      { id: 'M-1036', date: '2026-05-08 08:30', from: '본부 B', to: '101호',  duration: '1분 58초', distance: '34.2m', result: 'SUCCESS' },
    ],
  }
};
function odomToLatLng(x, y) {
  return {
    lat: BASE_LAT + y / 111320,
    lng: BASE_LNG + x / (111320 * Math.cos(BASE_LAT * Math.PI / 180)),
  };
}

// ============================================================
// 이벤트 렌더 헬퍼
// ============================================================
function EventBadge({ event }) {
  const { event_type, result } = event;
  if (event_type === 'MISSION_COMPLETE')
    return result === 'SUCCESS'
      ? <span className="text-green-600 font-bold text-[9px] bg-green-50 px-2 py-0.5 rounded-full border border-green-100 whitespace-nowrap">완료</span>
      : <span className="text-red-600 font-bold text-[9px] bg-red-50 px-2 py-0.5 rounded-full border border-red-100 whitespace-nowrap">실패</span>;
  if (event_type === 'OBSTACLE_DETECTED')
    return <span className="text-orange-600 font-bold text-[9px] bg-orange-50 px-2 py-0.5 rounded-full border border-orange-100 whitespace-nowrap">장애물</span>;
  if (event_type === 'BATTERY_LOW')
    return <span className="text-red-500 font-bold text-[9px] bg-red-50 px-2 py-0.5 rounded-full border border-red-100 whitespace-nowrap">배터리↓</span>;
  return null;
}

function EventDetail({ event }) {
  if (event.event_type === 'MISSION_COMPLETE')
    return <span className="font-mono">#{event.mission_id} · {event.duration_sec}s · {event.distance_m}m</span>;
  if (event.event_type === 'OBSTACLE_DETECTED')
    return <span className="font-mono">({event.pose.x.toFixed(1)}, {event.pose.y.toFixed(1)}) · {event.min_range_m}m → {event.action}</span>;
  if (event.event_type === 'BATTERY_LOW')
    return <span className="font-mono">{event.voltage}V · {Math.round(event.percentage * 100)}% → {event.action}</span>;
  return null;
}

// ============================================================
// Leaflet 설정
// ============================================================
const robotIcon = new L.Icon({
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

const goalIcon = new L.DivIcon({
  html: '<div style="width:14px;height:14px;background:#ef4444;border-radius:50%;border:2.5px solid white;box-shadow:0 0 8px rgba(239,68,68,0.7)"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
  className: '',
});

function Recenter({ lat, lng }) {
  const map = useMap();
  useEffect(() => { if (lat && lng) map.setView([lat, lng], 17); }, [lat, lng]);
  return null;
}

// ============================================================
// 실시간 모니터링 페이지
// ============================================================
const MonitoringPage = ({ robotPos, goalPos, planPath, odom, amclPose, battery, sensorState, goal, speedHistory, events, videoRef }) => {
  const batteryPct = battery != null ? Math.round(battery.percentage * 100) : null;
  const linearVel  = odom?.twist.linear.x ?? null;
  const angularVel = odom?.twist.angular.z ?? null;
  const yawDeg     = amclPose ? quatToYaw(amclPose.pose.pose.orientation) : null;
  const isMoving   = linearVel != null && Math.abs(linearVel) > 0.01;

  return (
    <main className="flex-1 grid grid-cols-12 gap-3 p-3 pt-2 min-h-0">
      {/* 좌측: 지도 + 카메라 */}
      <div className="col-span-5 flex flex-col gap-3 min-h-0">
        <section className="flex-1 bg-white border border-gray-200 rounded-lg p-2 flex flex-col shadow-sm min-h-0">
          <div className="flex items-center justify-between mb-1 px-1 border-b border-gray-50 pb-1">
            <h2 className="text-[10px] font-bold text-gray-400 flex items-center gap-1.5"><MapPin size={12}/> 이동 경로</h2>
            <div className="flex items-center gap-2">
              <span className="text-[8px] font-mono text-gray-300">● 로봇</span>
              <span className="text-[8px] font-mono text-red-400">● 목표</span>
              <span className="text-[8px] font-mono text-blue-400">— 경로</span>
            </div>
          </div>
          <div className="flex-1 rounded-md overflow-hidden">
            <MapContainer center={[robotPos.lat, robotPos.lng]} zoom={17} style={{ height: '100%', width: '100%' }}>
              <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              <Marker position={[robotPos.lat, robotPos.lng]} icon={robotIcon} />
              {goalPos && <Marker position={[goalPos.lat, goalPos.lng]} icon={goalIcon} />}
              {planPath.length > 0 && <Polyline positions={planPath} color="#3b82f6" weight={2.5} opacity={0.65} dashArray="7 5" />}
              <Recenter lat={robotPos.lat} lng={robotPos.lng} />
            </MapContainer>
          </div>
        </section>
        <section className="flex-1 bg-white border border-gray-200 rounded-lg p-2 flex flex-col shadow-sm min-h-0">
          <div className="flex items-center justify-between mb-1 px-1 border-b border-gray-50 pb-1">
            <h2 className="text-[10px] font-bold text-gray-400 flex items-center gap-1.5"><Video size={12}/> 카메라 화면</h2>
            <span className="text-[9px] font-bold text-red-500 animate-pulse uppercase">● 실시간 스트리밍</span>
          </div>
          <div className="flex-1 bg-black rounded-md overflow-hidden">
            <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
          </div>
        </section>
      </div>

      {/* 우측: 상태 카드 + 이벤트 로그 */}
      <div className="col-span-7 flex flex-col gap-3 min-h-0">
        <div className="flex flex-col gap-2">
          <h2 className="text-[11px] font-bold text-gray-400 px-1 uppercase tracking-wider">로봇 상태 정보</h2>
          <div className="grid grid-cols-3 gap-3 h-44 shrink-0">

            {/* 주행 속도 — /odom › twist.linear.x */}
            <div className="bg-white border border-gray-200 p-3 rounded-lg shadow-sm flex flex-col overflow-hidden">
              <div className="flex justify-between items-center mb-0.5">
                <span className="text-[10px] font-bold text-gray-400">주행 속도</span>
                <span className="text-blue-600 font-mono text-xs font-bold">
                  {linearVel != null ? `${linearVel.toFixed(2)} m/s` : '--'}
                </span>
              </div>
              <span className="text-[8px] font-mono text-gray-300 mb-1">/odom › twist.linear.x</span>
              <div className="flex-1 pr-1">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={speedHistory} margin={{ top: 5, right: 5, left: -25, bottom: 8 }}>
                    <XAxis dataKey="time" stroke="#d1d5db" fontSize={8} tickLine={false} axisLine={false} />
                    <YAxis stroke="#d1d5db" fontSize={8} tickLine={false} axisLine={false} domain={[0, 1.2]} />
                    <Line type="monotone" dataKey="v" stroke="#3b82f6" strokeWidth={2.5} dot={{ r: 2 }} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-between items-center mt-0.5 px-0.5">
                <span className="text-[8px] text-gray-300 font-mono">각속도</span>
                <span className="text-[8px] text-gray-500 font-mono font-bold">
                  {angularVel != null ? `${angularVel.toFixed(2)} rad/s` : '--'}
                </span>
              </div>
            </div>

            {/* 배터리 잔량 — /battery_state */}
            <div className="bg-white border border-gray-200 p-3 rounded-lg shadow-sm flex flex-col relative overflow-hidden">
              <span className="text-[10px] font-bold text-gray-400 mb-0.5">배터리 잔량</span>
              <span className="text-[8px] font-mono text-gray-300 mb-0.5">/battery_state › percentage</span>
              <div className="flex-1">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={batteryPct != null
                        ? [{ v: batteryPct }, { v: 100 - batteryPct }]
                        : [{ v: 0 }, { v: 100 }]
                      }
                      innerRadius="60%" outerRadius="85%"
                      dataKey="v" startAngle={90} endAngle={-270}
                    >
                      <Cell fill={batteryPct != null ? (batteryPct > 20 ? '#10b981' : '#ef4444') : '#e5e7eb'} stroke="none" />
                      <Cell fill="#f3f4f6" stroke="none" />
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="absolute inset-0 flex items-center justify-center pt-3">
                  <span className="text-xl font-black text-gray-900">
                    {batteryPct != null ? `${batteryPct}%` : '--'}
                  </span>
                </div>
              </div>
              <div className="flex justify-between text-[8px] font-mono mt-0.5 px-0.5">
                <span className="text-gray-500"><span className="text-gray-300">전압 </span>{battery?.voltage ?? '--'}V</span>
                <span className="text-gray-500"><span className="text-gray-300">전류 </span>{battery?.current ?? '--'}A</span>
              </div>
            </div>

            {/* 우측 3개 소형 카드 */}
            <div className="flex flex-col gap-2">
              {/* AMCL 위치 — /amcl_pose */}
              <div className="flex-1 bg-white border border-gray-200 px-3 rounded-lg flex flex-col justify-center shadow-sm">
                <div className="flex justify-between items-center">
                  <span className="text-[9px] font-bold text-gray-400 uppercase">AMCL 위치</span>
                  <span className="text-[8px] font-mono text-gray-400">
                    yaw {yawDeg ?? '--'}°
                  </span>
                </div>
                <div className="flex gap-2 mt-0.5">
                  <span className="text-[10px] font-mono text-gray-700">
                    x <span className="font-bold">{amclPose?.pose.pose.position.x.toFixed(3) ?? '--'}</span>m
                  </span>
                  <span className="text-[10px] font-mono text-gray-700">
                    y <span className="font-bold">{amclPose?.pose.pose.position.y.toFixed(3) ?? '--'}</span>m
                  </span>
                </div>
              </div>

              {/* 하드웨어 상태 — /sensor_state */}
              <div className="flex-1 bg-white border border-gray-200 px-3 rounded-lg flex flex-col justify-center shadow-sm">
                <div className="flex justify-between items-center">
                  <span className="text-[9px] font-bold text-gray-400">하드웨어 상태</span>
                  <span className={`text-[9px] font-bold ${
                    sensorState == null ? 'text-gray-300' :
                    sensorState.bumper === 0 && sensorState.cliff === 0 ? 'text-green-600' : 'text-red-500'
                  }`}>
                    {sensorState == null ? '--' : sensorState.bumper === 0 && sensorState.cliff === 0 ? '정상' : '경고'}
                  </span>
                </div>
                <div className="flex gap-2 mt-0.5">
                  {sensorState != null ? (
                    <>
                      <span className={`text-[8px] font-bold ${sensorState.bumper === 0 ? 'text-gray-400' : 'text-red-500'}`}>범퍼{sensorState.bumper === 0 ? ' OK' : ' !'}</span>
                      <span className={`text-[8px] font-bold ${sensorState.cliff === 0 ? 'text-gray-400' : 'text-red-500'}`}>낭떠러지{sensorState.cliff === 0 ? ' OK' : ' !'}</span>
                      <span className={`text-[8px] font-bold ${sensorState.torque ? 'text-blue-500' : 'text-gray-400'}`}>토크{sensorState.torque ? ' ON' : ' OFF'}</span>
                    </>
                  ) : (
                    <span className="text-[8px] text-gray-300 font-mono">수신 대기 중</span>
                  )}
                </div>
              </div>

              {/* 미션 상태 — /navigate_to_pose + /goal_pose */}
              <div className="flex-1 bg-white border border-gray-200 px-3 rounded-lg flex flex-col justify-center shadow-sm">
                <div className="flex justify-between items-center">
                  <span className="text-[9px] font-bold text-gray-400">미션 상태</span>
                  <span className={`text-[9px] font-bold uppercase italic ${
                    odom == null ? 'text-gray-300' : isMoving ? 'text-blue-600' : 'text-gray-400'
                  }`}>
                    {odom == null ? '--' : isMoving ? 'NAVIGATING' : 'IDLE'}
                  </span>
                </div>
                <div className="mt-0.5">
                  <span className="text-[8px] font-mono text-gray-400">
                    {goal != null
                      ? `목표 (${goal.pose.position.x.toFixed(1)}, ${goal.pose.position.y.toFixed(1)})`
                      : '목표 --'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 이벤트 로그 */}
        <section className="flex-1 bg-[#ebecef] border border-gray-200 rounded-lg p-3 flex flex-col min-h-0 shadow-inner">
          <h2 className="text-[11px] font-bold text-gray-400 mb-2 flex items-center gap-2 px-1">
            <ScrollText size={12}/> 실시간 이벤트 로그
          </h2>
          <div className="flex-1 bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
            <table className="w-full text-[11px] text-left border-collapse">
              <thead className="bg-gray-50 text-gray-400 font-bold border-b">
                <tr>
                  <th className="px-4 py-2">상태</th>
                  <th className="px-4 py-2">시각</th>
                  <th className="px-4 py-2">상세</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-gray-600">
                {events.length > 0 ? events.map((event, i) => (
                  <tr key={i} className="hover:bg-blue-50/50 transition-colors cursor-pointer">
                    <td className="px-4 py-2.5"><EventBadge event={event} /></td>
                    <td className="px-4 py-2.5 font-mono text-[10px] text-gray-400 whitespace-nowrap">
                      {event.timestamp.slice(0, 10)} {event.timestamp.slice(11, 19)}
                    </td>
                    <td className="px-4 py-2.5 text-[10px] text-gray-500"><EventDetail event={event} /></td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-center text-[10px] text-gray-300 font-mono">
                      수신 대기 중...
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
};

// ============================================================
// 로그 & 이력 페이지
// ============================================================
const LogsPage = () => {
  const [remote, setRemote] = useState(null);
  useEffect(() => {
    if (DEMO_MODE || !API_ENABLED) return;
    api.fetchLogs().then(setRemote);
  }, []);
  const demo = DEMO_MODE ? DEMO_INIT.logs : remote;
  const statsData = demo
    ? demo.weekly
    : [
        { name: '월', count: 0 }, { name: '화', count: 0 }, { name: '수', count: 0 },
        { name: '목', count: 0 }, { name: '금', count: 0 }, { name: '토', count: 0 }, { name: '일', count: 0 }
      ];
  const fmtDuration = (s) => `${Math.floor(s / 60)}분 ${s % 60}초`;

  return (
    <main className="flex-1 p-4 overflow-y-auto bg-[#f8f9fa]">
      <div className="max-w-6xl mx-auto flex flex-col gap-4">
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm flex flex-col gap-1">
            <span className="text-[10px] font-bold text-gray-400 uppercase">총 배송 횟수</span>
            <span className={`text-2xl font-black ${demo ? 'text-gray-900' : 'text-gray-300'}`}>
              {demo ? demo.totalMissions.toLocaleString() : '--'}
            </span>
          </div>
          <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm flex flex-col gap-1">
            <span className="text-[10px] font-bold text-gray-400 uppercase">평균 배송 시간</span>
            <span className={`text-2xl font-black ${demo ? 'text-gray-900' : 'text-gray-300'}`}>
              {demo ? fmtDuration(demo.avgDurationSec) : '--'}
            </span>
          </div>
          <div className="col-span-2 bg-white p-4 rounded-xl border border-gray-200 shadow-sm flex items-center gap-6">
            <div className="flex-1 h-12">
              <span className="text-[10px] font-bold text-gray-400 uppercase block mb-1">요일별 배송 추이</span>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={statsData}>
                  <Bar dataKey="count" fill={demo ? '#3b82f6' : '#e5e7eb'} radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="w-px h-full bg-gray-100" />
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-gray-400 uppercase">누적 주행 거리</span>
              <span className={`text-xl font-black ${demo ? 'text-gray-900' : 'text-gray-300'}`}>
                {demo ? `${demo.totalDistanceKm.toFixed(1)} km` : '--'}
              </span>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm flex flex-col overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100 flex justify-between items-center bg-white">
            <div className="flex items-center gap-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
                <input type="text" placeholder="ID 또는 목적지 검색..." className="pl-9 pr-4 py-1.5 bg-gray-50 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/20 w-64" />
              </div>
              <button className="flex items-center gap-2 px-3 py-1.5 border border-gray-200 rounded-lg text-xs font-bold text-gray-600 hover:bg-gray-50">
                <Filter size={14} /> 필터 설정
              </button>
            </div>
            <div className="flex items-center gap-2 text-xs font-bold text-gray-400">
              <Calendar size={14} />
              <span>{demo ? '2026-05-01 ~ 2026-05-08' : '--'}</span>
            </div>
          </div>

          <table className="w-full text-left border-collapse">
            <thead className="bg-gray-50/50 text-[10px] font-bold text-gray-400 uppercase tracking-wider">
              <tr>
                <th className="px-6 py-3 border-b">미션 ID</th>
                <th className="px-6 py-3 border-b">날짜/시간</th>
                <th className="px-6 py-3 border-b">경로 (출발 → 도착)</th>
                <th className="px-6 py-3 border-b">소요 시간</th>
                <th className="px-6 py-3 border-b">거리</th>
                <th className="px-6 py-3 border-b text-right">결과</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 text-sm">
              {demo ? demo.rows.map(r => (
                <tr key={r.id} className="hover:bg-blue-50/50 transition-colors">
                  <td className="px-6 py-3 font-mono text-xs text-gray-700 font-bold">{r.id}</td>
                  <td className="px-6 py-3 font-mono text-xs text-gray-500">{r.date}</td>
                  <td className="px-6 py-3 text-xs text-gray-700">{r.from} → <span className="font-bold">{r.to}</span></td>
                  <td className="px-6 py-3 font-mono text-xs text-gray-600">{r.duration}</td>
                  <td className="px-6 py-3 font-mono text-xs text-gray-600">{r.distance}</td>
                  <td className="px-6 py-3 text-right">
                    {r.result === 'SUCCESS'
                      ? <span className="text-green-600 font-bold text-[10px] bg-green-50 px-2 py-0.5 rounded-full border border-green-100">완료</span>
                      : <span className="text-red-600 font-bold text-[10px] bg-red-50 px-2 py-0.5 rounded-full border border-red-100">실패</span>}
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={6} className="px-6 py-10 text-center text-xs text-gray-300 font-mono">
                    수신 대기 중...
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="px-6 py-4 border-t border-gray-50 flex justify-center gap-2">
            {[1, 2, 3, 4, 5].map(n => (
              <button key={n} className={`w-8 h-8 rounded-lg text-xs font-bold transition-colors ${n === 1 ? 'bg-blue-600 text-white shadow-md shadow-blue-200' : 'text-gray-400 hover:bg-gray-100'}`}>
                {n}
              </button>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
};

// ============================================================
// 원격 제어 페이지
// ============================================================
const DirButton = ({ dir, icon: Icon, label, activeDir, eStop, onPress, onRelease }) => {
  const isActive = activeDir === dir;
  return (
    <button
      onMouseDown={() => onPress(dir)}
      onMouseUp={onRelease}
      onMouseLeave={() => isActive && onRelease()}
      onTouchStart={(e) => { e.preventDefault(); onPress(dir); }}
      onTouchEnd={onRelease}
      disabled={eStop}
      className={`aspect-square rounded-xl border flex flex-col items-center justify-center gap-1 transition-all shadow-sm select-none
        ${eStop ? 'bg-gray-50 border-gray-100 text-gray-300 cursor-not-allowed'
          : isActive ? 'bg-blue-600 border-blue-700 text-white shadow-blue-200 shadow-lg scale-95'
          : 'bg-white border-gray-200 text-gray-600 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-600 active:scale-95'}`}
    >
      <Icon size={22} strokeWidth={2.5} />
      <span className="text-[9px] font-bold uppercase tracking-wider">{label}</span>
    </button>
  );
};

const ControlPage = ({ odom, battery, amclPose }) => {
  const [linearSpeed, setLinearSpeed]   = useState(0.22);   // m/s
  const [angularSpeed, setAngularSpeed] = useState(1.0);    // rad/s
  const [activeDir, setActiveDir]       = useState(null);   // 'F'|'B'|'L'|'R'|null
  const [eStop, setEStop]               = useState(false);
  const [missionState, setMissionState] = useState('IDLE'); // IDLE|RUNNING|PAUSED
  const [goalX, setGoalX] = useState('');
  const [goalY, setGoalY] = useState('');
  const [goalYaw, setGoalYaw] = useState('');
  const [cmdLog, setCmdLog] = useState([]);

  const pushLog = (topic, payload) => {
    const ts = new Date().toTimeString().slice(0, 8);
    setCmdLog(prev => [{ ts, topic, payload }, ...prev].slice(0, 30));
  };

  const sendCmdVel = (dir) => {
    if (eStop) return;
    setActiveDir(dir);
    const v = { F:  linearSpeed, B: -linearSpeed, L: 0, R: 0, S: 0 }[dir] ?? 0;
    const w = { F: 0, B: 0, L:  angularSpeed, R: -angularSpeed, S: 0 }[dir] ?? 0;
    pushLog('/cmd_vel', `linear.x=${v.toFixed(2)} angular.z=${w.toFixed(2)}`);
    if (API_ENABLED) api.sendCmdVel(v, w);
  };
  const stopCmdVel = () => {
    setActiveDir(null);
    pushLog('/cmd_vel', 'linear.x=0.00 angular.z=0.00');
    if (API_ENABLED) api.sendCmdVel(0, 0);
  };

  const triggerEStop = () => {
    setEStop(true);
    setActiveDir(null);
    setMissionState('IDLE');
    pushLog('/emergency_stop', 'engaged=true');
    if (API_ENABLED) api.sendEStop(true);
  };
  const releaseEStop = () => {
    setEStop(false);
    pushLog('/emergency_stop', 'engaged=false');
    if (API_ENABLED) api.sendEStop(false);
  };

  const sendGoal = () => {
    if (eStop) return;
    const x = parseFloat(goalX), y = parseFloat(goalY), yaw = parseFloat(goalYaw) || 0;
    if (Number.isNaN(x) || Number.isNaN(y)) return;
    setMissionState('RUNNING');
    pushLog('/goal_pose', `x=${x.toFixed(2)} y=${y.toFixed(2)} yaw=${yaw.toFixed(1)}°`);
    if (API_ENABLED) api.sendGoal(x, y, yaw);
  };

  const handleMission = (action) => {
    if (action === 'start')  { setMissionState('RUNNING'); pushLog('/mission', 'START'); }
    if (action === 'pause')  { setMissionState('PAUSED');  pushLog('/mission', 'PAUSE'); }
    if (action === 'cancel') { setMissionState('IDLE');    pushLog('/mission', 'CANCEL'); }
    if (action === 'return') { setMissionState('RUNNING'); pushLog('/mission', 'RETURN_HOME'); }
    if (API_ENABLED) api.sendMission(action);
  };

  const dirProps = { activeDir, eStop, onPress: sendCmdVel, onRelease: stopCmdVel };

  const batteryPct = battery != null ? Math.round(battery.percentage * 100) : null;
  const linearVel  = odom?.twist.linear.x ?? null;
  const yawDeg     = amclPose ? quatToYaw(amclPose.pose.pose.orientation) : null;

  return (
    <main className="flex-1 grid grid-cols-12 gap-3 p-3 pt-2 min-h-0">
      {/* 좌측: 수동 주행 */}
      <div className="col-span-5 flex flex-col gap-3 min-h-0">
        {/* 비상 정지 */}
        <section className={`rounded-lg border p-3 flex items-center justify-between shadow-sm transition-colors
          ${eStop ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'}`}>
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${eStop ? 'bg-red-500/15 text-red-600 border border-red-200' : 'bg-gray-100 text-gray-400 border border-gray-200'}`}>
              <Power size={18} />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">비상 정지</span>
              <span className={`text-xs font-bold ${eStop ? 'text-red-600' : 'text-gray-600'}`}>
                {eStop ? '● 정지 중 — 모든 명령 차단' : '○ 대기 — 명령 송신 가능'}
              </span>
            </div>
          </div>
          {eStop
            ? <button onClick={releaseEStop} className="px-4 py-2 bg-white border border-red-200 text-red-600 rounded-lg text-xs font-bold hover:bg-red-100 shadow-sm">해제</button>
            : <button onClick={triggerEStop} className="px-4 py-2 bg-red-600 text-white rounded-lg text-xs font-bold hover:bg-red-700 shadow-md shadow-red-200">E-STOP</button>
          }
        </section>

        {/* 방향 제어 */}
        <section className="flex-1 bg-white border border-gray-200 rounded-lg p-3 flex flex-col shadow-sm min-h-0">
          <div className="flex items-center justify-between mb-2 px-1 border-b border-gray-50 pb-1.5">
            <h2 className="text-[10px] font-bold text-gray-400 flex items-center gap-1.5"><Gauge size={12}/> 수동 주행 제어</h2>
            <span className="text-[8px] font-mono text-gray-300">/cmd_vel › Twist</span>
          </div>

          <div className="flex-1 grid grid-cols-3 grid-rows-3 gap-2 max-w-xs mx-auto w-full py-2">
            <div />
            <DirButton dir="F" icon={ArrowUp} label="전진" {...dirProps} />
            <div />
            <DirButton dir="L" icon={ArrowLeft} label="좌회전" {...dirProps} />
            <button
              onClick={stopCmdVel}
              disabled={eStop}
              className={`aspect-square rounded-xl border flex flex-col items-center justify-center gap-1 shadow-sm
                ${eStop ? 'bg-gray-50 border-gray-100 text-gray-300 cursor-not-allowed'
                  : 'bg-gray-900 border-gray-900 text-white hover:bg-gray-800 active:scale-95'}`}
            >
              <Square size={20} strokeWidth={2.5} />
              <span className="text-[9px] font-bold uppercase tracking-wider">정지</span>
            </button>
            <DirButton dir="R" icon={ArrowRight} label="우회전" {...dirProps} />
            <div />
            <DirButton dir="B" icon={ArrowDown} label="후진" {...dirProps} />
            <div />
          </div>

          {/* 속도 슬라이더 */}
          <div className="mt-2 flex flex-col gap-2 px-1">
            <div className="flex flex-col gap-1">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-bold text-gray-400">선속도</span>
                <span className="text-[10px] font-mono font-bold text-blue-600">{linearSpeed.toFixed(2)} m/s</span>
              </div>
              <input
                type="range" min={0} max={0.5} step={0.01}
                value={linearSpeed}
                onChange={e => setLinearSpeed(parseFloat(e.target.value))}
                className="w-full accent-blue-600"
              />
            </div>
            <div className="flex flex-col gap-1">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-bold text-gray-400">각속도</span>
                <span className="text-[10px] font-mono font-bold text-blue-600">{angularSpeed.toFixed(2)} rad/s</span>
              </div>
              <input
                type="range" min={0} max={2.5} step={0.05}
                value={angularSpeed}
                onChange={e => setAngularSpeed(parseFloat(e.target.value))}
                className="w-full accent-blue-600"
              />
            </div>
          </div>
        </section>
      </div>

      {/* 우측: 미션 + 상태 + 로그 */}
      <div className="col-span-7 flex flex-col gap-3 min-h-0">
        {/* 현재 상태 요약 */}
        <div className="grid grid-cols-4 gap-3 shrink-0">
          <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm flex flex-col">
            <span className="text-[9px] font-bold text-gray-400 uppercase">미션 상태</span>
            <span className={`text-sm font-black mt-1 ${
              missionState === 'RUNNING' ? 'text-blue-600' :
              missionState === 'PAUSED'  ? 'text-amber-500' : 'text-gray-400'
            }`}>{missionState}</span>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm flex flex-col">
            <span className="text-[9px] font-bold text-gray-400 uppercase">현재 속도</span>
            <span className="text-sm font-black mt-1 text-gray-700 font-mono">
              {linearVel != null ? `${linearVel.toFixed(2)} m/s` : '--'}
            </span>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm flex flex-col">
            <span className="text-[9px] font-bold text-gray-400 uppercase">배터리</span>
            <span className={`text-sm font-black mt-1 font-mono ${batteryPct != null && batteryPct <= 20 ? 'text-red-500' : 'text-gray-700'}`}>
              {batteryPct != null ? `${batteryPct}%` : '--'}
            </span>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm flex flex-col">
            <span className="text-[9px] font-bold text-gray-400 uppercase">YAW</span>
            <span className="text-sm font-black mt-1 text-gray-700 font-mono">{yawDeg != null ? `${yawDeg}°` : '--'}</span>
          </div>
        </div>

        {/* 목표 지점 전송 */}
        <section className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm shrink-0">
          <div className="flex items-center justify-between mb-2 px-1 border-b border-gray-50 pb-1.5">
            <h2 className="text-[10px] font-bold text-gray-400 flex items-center gap-1.5"><MapPin size={12}/> 목표 지점 전송</h2>
            <span className="text-[8px] font-mono text-gray-300">/goal_pose › PoseStamped</span>
          </div>
          <div className="grid grid-cols-12 gap-2 items-end">
            <div className="col-span-3 flex flex-col gap-1">
              <label className="text-[9px] font-bold text-gray-400">X (m)</label>
              <input value={goalX} onChange={e => setGoalX(e.target.value)} placeholder="0.00"
                className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/20" />
            </div>
            <div className="col-span-3 flex flex-col gap-1">
              <label className="text-[9px] font-bold text-gray-400">Y (m)</label>
              <input value={goalY} onChange={e => setGoalY(e.target.value)} placeholder="0.00"
                className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/20" />
            </div>
            <div className="col-span-3 flex flex-col gap-1">
              <label className="text-[9px] font-bold text-gray-400">YAW (°)</label>
              <input value={goalYaw} onChange={e => setGoalYaw(e.target.value)} placeholder="0"
                className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/20" />
            </div>
            <button onClick={sendGoal} disabled={eStop}
              className={`col-span-3 px-4 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-2 shadow-sm transition-colors
                ${eStop ? 'bg-gray-100 text-gray-300 cursor-not-allowed' : 'bg-blue-600 text-white hover:bg-blue-700 shadow-blue-200'}`}>
              <Send size={14} /> 목표 전송
            </button>
          </div>
        </section>

        {/* 미션 제어 */}
        <section className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm shrink-0">
          <div className="flex items-center justify-between mb-2 px-1 border-b border-gray-50 pb-1.5">
            <h2 className="text-[10px] font-bold text-gray-400 flex items-center gap-1.5"><Radio size={12}/> 미션 제어</h2>
            <span className="text-[8px] font-mono text-gray-300">/mission › action</span>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <button onClick={() => handleMission('start')} disabled={eStop || missionState === 'RUNNING'}
              className="px-3 py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 border border-green-200 bg-green-50 text-green-700 hover:bg-green-100 disabled:opacity-40 disabled:cursor-not-allowed">
              <Play size={13} /> 시작
            </button>
            <button onClick={() => handleMission('pause')} disabled={eStop || missionState !== 'RUNNING'}
              className="px-3 py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 disabled:opacity-40 disabled:cursor-not-allowed">
              <Pause size={13} /> 일시정지
            </button>
            <button onClick={() => handleMission('cancel')} disabled={eStop || missionState === 'IDLE'}
              className="px-3 py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 border border-red-200 bg-red-50 text-red-700 hover:bg-red-100 disabled:opacity-40 disabled:cursor-not-allowed">
              <Square size={13} /> 취소
            </button>
            <button onClick={() => handleMission('return')} disabled={eStop}
              className="px-3 py-2.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-40 disabled:cursor-not-allowed">
              <RotateCcw size={13} /> 복귀
            </button>
          </div>
        </section>

        {/* 명령 로그 */}
        <section className="flex-1 bg-[#ebecef] border border-gray-200 rounded-lg p-3 flex flex-col min-h-0 shadow-inner">
          <h2 className="text-[11px] font-bold text-gray-400 mb-2 flex items-center gap-2 px-1">
            <Terminal size={12}/> 명령 송신 로그
          </h2>
          <div className="flex-1 bg-gray-900 rounded-lg overflow-y-auto font-mono text-[10px] p-3 text-green-300 leading-relaxed">
            {cmdLog.length > 0 ? cmdLog.map((c, i) => (
              <div key={i} className="flex gap-3">
                <span className="text-gray-500">[{c.ts}]</span>
                <span className="text-blue-300">{c.topic}</span>
                <span className="text-green-300">{c.payload}</span>
              </div>
            )) : (
              <div className="text-gray-500">// 명령 송신 대기 중...</div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
};

// ============================================================
// 메인 App
// ============================================================
function App() {
  const [activeTab, setActiveTab] = useState('monitoring');
  const videoRef = useRef(null);

  // ROS2 토픽 상태 — 백엔드 연동 전까지 null (데모 모드에서는 더미값 주입)
  const [odom, setOdom]             = useState(DEMO_MODE ? DEMO_INIT.odom : null);
  const [battery, setBattery]       = useState(DEMO_MODE ? DEMO_INIT.battery : null);
  const [sensorState, setSensorState] = useState(DEMO_MODE ? DEMO_INIT.sensorState : null);
  const [amclPose, setAmclPose]     = useState(DEMO_MODE ? DEMO_INIT.amclPose : null);
  const [goal, setGoal]             = useState(DEMO_MODE ? DEMO_INIT.goal : null);
  const [planData, setPlanData]     = useState(DEMO_MODE ? DEMO_INIT.planData : null);
  const [events, setEvents]         = useState(DEMO_MODE ? DEMO_INIT.events : []);
  const [speedHistory, setSpeedHistory] = useState(
    DEMO_MODE
      ? DEMO_INIT.speedHistory
      : [{ time: '-50s', v: 0 }, { time: '-40s', v: 0 }, { time: '-30s', v: 0 },
         { time: '-20s', v: 0 }, { time: '-10s', v: 0 }, { time: '현재', v: 0 }]
  );

  // 백엔드 연결 모드: WebSocket으로 텔레메트리 수신 + REST로 이벤트 폴링
  useEffect(() => {
    if (DEMO_MODE || !API_ENABLED) return;
    const disconnect = connectTelemetry((d) => {
      if (d.odom) {
        setOdom(d.odom);
        const v = d.odom.twist?.linear?.x ?? 0;
        setSpeedHistory(prev => {
          const labels = ['-50s', '-40s', '-30s', '-20s', '-10s', '현재'];
          return [...prev.slice(1).map((p, i) => ({ time: labels[i], v: p.v })),
                  { time: '현재', v: Math.max(0, v) }];
        });
      }
      if (d.battery) setBattery(d.battery);
      if (d.sensorState) setSensorState(d.sensorState);
      if (d.amclPose) setAmclPose(d.amclPose);
      if (d.goal !== undefined) setGoal(d.goal);
      if (d.planData !== undefined) setPlanData(d.planData);
    });
    const evId = setInterval(async () => {
      const res = await api.fetchEvents();
      if (res?.events) setEvents(res.events);
    }, 3000);
    api.fetchEvents().then(res => { if (res?.events) setEvents(res.events); });
    return () => { disconnect(); clearInterval(evId); };
  }, []);

  // 데모 모드: 주기적으로 더미 데이터 갱신
  useEffect(() => {
    if (!DEMO_MODE) return;
    let t = 0;
    const id = setInterval(() => {
      t += 1;
      const v = 0.35 + Math.sin(t / 3) * 0.15 + (Math.random() - 0.5) * 0.04;
      const w = Math.cos(t / 4) * 0.4 + (Math.random() - 0.5) * 0.05;
      setOdom({ twist: { linear: { x: v }, angular: { z: w } } });
      setAmclPose(prev => {
        const px = (prev?.pose.pose.position.x ?? 0) + v * 0.5 * Math.cos(t / 6);
        const py = (prev?.pose.pose.position.y ?? 0) + v * 0.5 * Math.sin(t / 6);
        const yawRad = t / 6;
        return {
          pose: { pose: {
            position: { x: px, y: py },
            orientation: { x: 0, y: 0, z: Math.sin(yawRad / 2), w: Math.cos(yawRad / 2) }
          }}
        };
      });
      setBattery(prev => {
        const next = Math.max(0.18, (prev?.percentage ?? 0.84) - 0.0005);
        return { percentage: next, voltage: (11.5 + next * 1.3).toFixed(1), current: (1.2 + Math.random() * 0.4).toFixed(1) };
      });
      setSpeedHistory(prev => {
        const labels = ['-50s', '-40s', '-30s', '-20s', '-10s', '현재'];
        const next = [...prev.slice(1).map((p, i) => ({ time: labels[i], v: p.v })), { time: '현재', v: Math.max(0, v) }];
        return next;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // 지도 위치: amcl_pose 수신 전까지 기준점 표시
  const robotPos = amclPose
    ? odomToLatLng(amclPose.pose.pose.position.x, amclPose.pose.pose.position.y)
    : { lat: BASE_LAT, lng: BASE_LNG };

  const goalPos = goal
    ? odomToLatLng(goal.pose.position.x, goal.pose.position.y)
    : null;

  const planPath = planData?.poses
    ? planData.poses.map(p => {
        const ll = odomToLatLng(p.pose.position.x, p.pose.position.y);
        return [ll.lat, ll.lng];
      })
    : [];

  useEffect(() => {
    if (activeTab === 'monitoring') {
      async function initCamera() {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: true });
          if (videoRef.current) videoRef.current.srcObject = stream;
        } catch (err) { console.error(err); }
      }
      initCamera();
    }
  }, [activeTab]);

  return (
    <div className="h-screen bg-[#f3f4f6] text-gray-800 font-sans flex flex-col overflow-hidden antialiased">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex justify-between items-center shrink-0 z-50 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-blue-500/10 rounded-xl text-blue-600 border border-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]">
            <Bot size={22} />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tighter text-gray-950 leading-none uppercase flex items-center gap-2">
              YogiBot
              {DEMO_MODE && <span className="text-[9px] font-black bg-amber-400 text-amber-900 px-2 py-0.5 rounded-md tracking-widest">DEMO</span>}
            </h1>
            <span className="text-[10px] text-blue-600 font-mono uppercase tracking-[0.3em]">
              {DEMO_MODE ? 'Control Tower · Mock Mode' : 'Control Tower v1.0'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-8">
          <nav className="flex gap-6 text-xs font-bold text-gray-400">
            <button onClick={() => setActiveTab('monitoring')} className={`pb-0.5 transition-all ${activeTab === 'monitoring' ? 'text-blue-600 border-b-2 border-blue-600' : 'hover:text-gray-600'}`}>실시간 모니터링</button>
            <button onClick={() => setActiveTab('logs')} className={`pb-0.5 transition-all ${activeTab === 'logs' ? 'text-blue-600 border-b-2 border-blue-600' : 'hover:text-gray-600'}`}>로그 & 이력</button>
            <button onClick={() => setActiveTab('control')} className={`pb-0.5 transition-all ${activeTab === 'control' ? 'text-blue-600 border-b-2 border-blue-600' : 'hover:text-gray-600'}`}>원격 제어</button>
          </nav>
          <div className="text-[10px] font-mono text-green-600 bg-green-50 px-4 py-2 rounded-full border border-green-100 animate-pulse font-bold tracking-wider">● 시스템 온라인</div>
        </div>
      </header>

      {activeTab === 'monitoring' && (
        <MonitoringPage
          robotPos={robotPos}
          goalPos={goalPos}
          planPath={planPath}
          odom={odom}
          amclPose={amclPose}
          battery={battery}
          sensorState={sensorState}
          goal={goal}
          speedHistory={speedHistory}
          events={events}
          videoRef={videoRef}
        />
      )}
      {activeTab === 'logs' && <LogsPage />}
      {activeTab === 'control' && (
        <ControlPage odom={odom} battery={battery} amclPose={amclPose} />
      )}
    </div>
  );
}

export default App;
