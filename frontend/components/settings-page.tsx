"use client";

import { useState } from "react";
import { Database, Globe, Server, Save } from "lucide-react";

export function SettingsPage() {
  const [apiHost, setApiHost] = useState("127.0.0.1");
  const [apiPort, setApiPort] = useState("7088");
  const [dataSource, setDataSource] = useState("tushare");
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="max-w-2xl mx-auto h-full overflow-y-auto">
      <h1 className="text-xl font-bold text-zinc-100 mb-6">设置</h1>

      {/* API 连接 */}
      <section className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-5 mb-5">
        <div className="flex items-center gap-2 mb-4">
          <Server className="w-4 h-4 text-blue-400" />
          <h2 className="text-sm font-semibold text-zinc-200">API 连接</h2>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">后端地址</label>
            <input
              type="text"
              value={apiHost}
              onChange={(e) => setApiHost(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-zinc-500 mb-1.5 block">端口</label>
            <input
              type="text"
              value={apiPort}
              onChange={(e) => setApiPort(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
        <p className="text-[11px] text-zinc-600 mt-2">
          当前连接：http://{apiHost}:{apiPort}
        </p>
      </section>

      {/* 数据源 */}
      <section className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-5 mb-5">
        <div className="flex items-center gap-2 mb-4">
          <Database className="w-4 h-4 text-green-400" />
          <h2 className="text-sm font-semibold text-zinc-200">默认数据源</h2>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {[
            { key: "akshare", label: "AkShare", desc: "免费，基于东方财富", disabled: false },
            { key: "tushare", label: "Tushare", desc: "私有代理，速度快", disabled: false },
            { key: "baostock", label: "BaoStock", desc: "已弃用（服务不稳定）", disabled: true },
          ].map((s) => (
            <button
              key={s.key}
              onClick={() => !s.disabled && setDataSource(s.key)}
              disabled={s.disabled}
              className={
                "rounded-md border p-3 text-left transition-colors " +
                (s.disabled
                  ? "bg-zinc-950 border-zinc-800 text-zinc-600 opacity-50 cursor-not-allowed"
                  : dataSource === s.key
                  ? "bg-blue-600/10 border-blue-600/40 text-blue-400"
                  : "bg-zinc-950 border-zinc-800 text-zinc-400 hover:border-zinc-600")
              }
            >
              <div className="text-sm font-medium">{s.label}</div>
              <div className="text-[11px] text-zinc-500 mt-0.5">{s.desc}</div>
            </button>
          ))}
        </div>
      </section>

      {/* 关于 */}
      <section className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-5 mb-5">
        <div className="flex items-center gap-2 mb-4">
          <Globe className="w-4 h-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-zinc-200">关于</h2>
        </div>
        <div className="space-y-2 text-xs text-zinc-400">
          <div className="flex justify-between">
            <span>版本</span>
            <span className="text-zinc-300">v1.0.0</span>
          </div>
          <div className="flex justify-between">
            <span>前端</span>
            <span className="text-zinc-300">Next.js 16 + TailwindCSS</span>
          </div>
          <div className="flex justify-between">
            <span>后端</span>
            <span className="text-zinc-300">FastAPI + vnpy</span>
          </div>
          <div className="flex justify-between">
            <span>仓库</span>
            <span className="text-zinc-300">Cola5173/stock_quant</span>
          </div>
        </div>
      </section>

      {/* 保存按钮 */}
      <button
        onClick={handleSave}
        className="w-full py-2.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium flex items-center justify-center gap-2 transition-colors"
      >
        <Save className="w-4 h-4" />
        {saved ? "已保存" : "保存设置"}
      </button>
    </div>
  );
}
