"use client";

import { useMemo, useState } from "react";
import { Calculator, Wallet, AlertTriangle, ExternalLink } from "lucide-react";

type EtfKey = "nasdaq" | "gold" | "dividend" | "csi300";

const ETF_META: Record<EtfKey, { label: string; ratio: number; valuationLabel: string; hint: string; link?: string }> = {
  nasdaq: { label: "纳指 100", ratio: 0.30, valuationLabel: "PE 分位", hint: "", link: "https://danjuanfunds.com/dj-valuation-table-detail/NDX" },
  gold: { label: "黄金 ETF", ratio: 0.20, valuationLabel: "价格分位", hint: "" },
  dividend: { label: "低波红利", ratio: 0.25, valuationLabel: "PE 分位", hint: "", link: "https://danjuanfunds.com/dj-valuation-table-detail/CSIH30269" },
  csi300: { label: "沪深 300", ratio: 0.25, valuationLabel: "PE 分位", hint: "", link: "https://danjuanfunds.com/dj-valuation-table-detail/SH000300" },
};

const ETF_ORDER: EtfKey[] = ["nasdaq", "gold", "dividend", "csi300"];

function getWeight(percentile: number): number {
  return Math.max(0, (90 - percentile) / 40);
}

function getZoneLabel(percentile: number): { text: string; color: string } {
  if (percentile < 15) return { text: "三档加仓区", color: "text-emerald-400" };
  if (percentile < 25) return { text: "二档加仓区", color: "text-emerald-400" };
  if (percentile < 30) return { text: "一档加仓区", color: "text-emerald-400" };
  if (percentile < 40) return { text: "低估", color: "text-emerald-400/80" };
  if (percentile < 70) return { text: "中性", color: "text-zinc-400" };
  if (percentile < 75) return { text: "偏高", color: "text-amber-400" };
  if (percentile < 85) return { text: "一档减仓区", color: "text-orange-400" };
  if (percentile < 95) return { text: "二档减仓区", color: "text-red-400" };
  return { text: "三档减仓区", color: "text-red-500" };
}

function fmtMoney(n: number): string {
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

export function EtfPage() {
  const [amount, setAmount] = useState<number>(0);
  const [remainingFunds, setRemainingFunds] = useState<number>(0);
  const [holdings, setHoldings] = useState<Record<EtfKey, number>>({
    nasdaq: 0,
    gold: 0,
    dividend: 0,
    csi300: 0,
  });
  const [percentiles, setPercentiles] = useState<Record<EtfKey, number>>({
    nasdaq: 76,
    gold: 55,
    dividend: 35,
    csi300: 86,
  });

  const totalHoldings = useMemo(() => ETF_ORDER.reduce((s, k) => s + holdings[k], 0), [holdings]);

  const [calculated, setCalculated] = useState(false);

  const result = useMemo(() => {
    const must = amount * 0.5;
    const flex = amount * 0.5;

    const mustAlloc: Record<EtfKey, number> = {
      nasdaq: must * ETF_META.nasdaq.ratio,
      gold: must * ETF_META.gold.ratio,
      dividend: must * ETF_META.dividend.ratio,
      csi300: must * ETF_META.csi300.ratio,
    };

    const weights: Record<EtfKey, number> = {
      nasdaq: getWeight(percentiles.nasdaq),
      gold: getWeight(percentiles.gold),
      dividend: getWeight(percentiles.dividend),
      csi300: getWeight(percentiles.csi300),
    };

    const totalWeight = ETF_ORDER.reduce((s, k) => s + weights[k] * ETF_META[k].ratio, 0);

    const flexAlloc: Record<EtfKey, number> = { nasdaq: 0, gold: 0, dividend: 0, csi300: 0 };
    const allHigh = totalWeight === 0;
    const bulletPool: Record<EtfKey, number> = { nasdaq: 0, gold: 0, dividend: 0, csi300: 0 };

    // 每个 ETF 的机动分配 = flex × 目标比例 × 权重系数
    // 权重 < 1 时，未投出的部分进入子弹池
    // 权重 > 1 时（低估加权），需要归一化防止超额
    const rawAlloc: Record<EtfKey, number> = { nasdaq: 0, gold: 0, dividend: 0, csi300: 0 };
    let rawTotal = 0;
    for (const k of ETF_ORDER) {
      rawAlloc[k] = flex * ETF_META[k].ratio * weights[k];
      rawTotal += rawAlloc[k];
    }

    if (rawTotal <= flex) {
      // 总投入 <= 机动资金：按原值投，剩余进子弹池
      for (const k of ETF_ORDER) {
        flexAlloc[k] = rawAlloc[k];
        bulletPool[k] = flex * ETF_META[k].ratio - rawAlloc[k];
      }
    } else {
      // 总投入 > 机动资金（低估加权场景）：归一化到 flex
      for (const k of ETF_ORDER) {
        flexAlloc[k] = (rawAlloc[k] / rawTotal) * flex;
      }
    }

    const total: Record<EtfKey, number> = {
      nasdaq: mustAlloc.nasdaq + flexAlloc.nasdaq,
      gold: mustAlloc.gold + flexAlloc.gold,
      dividend: mustAlloc.dividend + flexAlloc.dividend,
      csi300: mustAlloc.csi300 + flexAlloc.csi300,
    };

    // 加仓：根据子弹池上限和 PE 分位计算
    const bulletMax = amount * 0.5 * 9; // 9 个月机动资金上限
    const bulletRelease: Record<EtfKey, number> = { nasdaq: 0, gold: 0, dividend: 0, csi300: 0 };
    for (const k of ETF_ORDER) {
      const poolMax = bulletMax * ETF_META[k].ratio;
      const third = poolMax / 3;
      const pe = percentiles[k];
      if (pe < 15) bulletRelease[k] = third * 3;
      else if (pe < 25) bulletRelease[k] = third * 2;
      else if (pe < 40) bulletRelease[k] = third;
    }

    return { must, flex, mustAlloc, flexAlloc, weights, totalWeight, total, allHigh, bulletPool, bulletRelease };
  }, [amount, percentiles]);

  return (
    <div className="h-full overflow-y-auto pb-8 no-scrollbar">
      <div className="flex items-center gap-2 mb-5">
        <Calculator className="w-5 h-5 text-blue-400" />
        <h1 className="text-xl font-bold text-zinc-100">ETF 月度定投计算器</h1>
      </div>

      {/* 输入区：三栏布局 */}
      <section className="grid grid-cols-[1fr_1fr_2fr] gap-4 mb-5">
        {/* 左：本月可投金额 */}
        <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Wallet className="w-4 h-4 text-blue-400" />
            <h2 className="text-sm font-semibold text-zinc-200">本月可投金额</h2>
          </div>
          <div className="flex items-center gap-2 mb-3">
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(Math.max(0, Number(e.target.value) || 0))}
              min={0}
              step={500}
              className="w-28 bg-zinc-950 border border-zinc-800 rounded-md px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-blue-500 tabular-nums"
            />
            <span className="text-xs text-zinc-500">元</span>
          </div>
          <div className="flex items-center gap-2 text-xs whitespace-nowrap">
            <span className="text-zinc-500">必投</span>
            <input
              type="text"
              readOnly
              value={fmtMoney(result.must)}
              className="w-14 bg-zinc-950/60 border border-zinc-800 rounded px-1.5 py-0.5 text-xs text-zinc-300 tabular-nums text-right cursor-default"
            />
            <span className="text-zinc-500 ml-1">机动</span>
            <input
              type="text"
              readOnly
              value={fmtMoney(result.flex)}
              className="w-14 bg-zinc-950/60 border border-zinc-800 rounded px-1.5 py-0.5 text-xs text-zinc-300 tabular-nums text-right cursor-default"
            />
            <span className="text-[10px] text-zinc-600">元</span>
          </div>
        </div>

        {/* 中：剩余资金 */}
        <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Wallet className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-semibold text-zinc-200">剩余资金</h2>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={remainingFunds}
              onChange={(e) => setRemainingFunds(Math.max(0, Number(e.target.value) || 0))}
              min={0}
              step={0.1}
              className="w-28 bg-zinc-950 border border-zinc-800 rounded-md px-3 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-blue-500 tabular-nums"
            />
            <span className="text-xs text-zinc-500">万</span>
          </div>
        </div>

        {/* 右：目前仓位 */}
        <div className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Wallet className="w-4 h-4 text-green-400" />
            <h2 className="text-sm font-semibold text-zinc-200">目前仓位</h2>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
            {ETF_ORDER.map((k) => (
              <div key={k} className="flex items-center gap-2">
                <span className="text-xs text-zinc-400">{ETF_META[k].label}</span>
                <input
                  type="number"
                  value={holdings[k]}
                  onChange={(e) => setHoldings((prev) => ({ ...prev, [k]: Math.max(0, Number(e.target.value) || 0) }))}
                  min={0}
                  step={0.1}
                  className="w-16 bg-zinc-950 border border-zinc-800 rounded px-2 py-0.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500 tabular-nums text-right"
                />
                <span className="text-[10px] text-zinc-600">万</span>
              </div>
            ))}
          </div>
          <div className="mt-2 pt-2 border-t border-zinc-800 flex items-center justify-end text-xs">
            <span className="text-zinc-500 mr-2">合计</span>
            <span className="text-zinc-100 font-bold tabular-nums">{totalHoldings.toFixed(1)} 万</span>
          </div>
        </div>
      </section>

      {/* PE 分位输入 */}
      <section className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-5 mb-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-zinc-200">当前估值分位（手动填入）</h2>
          <span className="text-[11px] text-zinc-500">单位：%（0-100）</span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {ETF_ORDER.map((k) => {
            const meta = ETF_META[k];
            const p = percentiles[k];
            const zone = getZoneLabel(p);
            const w = getWeight(p);
            return (
              <div key={k} className="bg-zinc-950 border border-zinc-800 rounded-md p-3">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="text-sm font-medium text-zinc-200">
                      {meta.label}
                      {meta.link && (
                        <a href={meta.link} target="_blank" rel="noopener noreferrer" className="inline-flex ml-1.5 text-blue-400 hover:text-blue-300">
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                      <span className="text-[11px] text-zinc-500 font-normal ml-1">· 目标 {(meta.ratio * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <span className={`text-[11px] font-medium ${zone.color}`}>{zone.text}</span>
                </div>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    value={p}
                    onChange={(e) => {
                      const v = Math.min(100, Math.max(0, Number(e.target.value) || 0));
                      setPercentiles((prev) => ({ ...prev, [k]: v }));
                    }}
                    min={0}
                    max={100}
                    step={1}
                    className="w-20 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-sm text-zinc-200 focus:outline-none focus:border-blue-500 tabular-nums"
                  />
                  <input
                    type="range"
                    value={p}
                    onChange={(e) => setPercentiles((prev) => ({ ...prev, [k]: Number(e.target.value) }))}
                    min={0}
                    max={100}
                    step={1}
                    className="flex-1 accent-blue-500"
                  />
                  <span className="text-[11px] text-zinc-500 w-16 text-right tabular-nums">权重 {w}x</span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 计算按钮 */}
      <button
        onClick={() => setCalculated(true)}
        className="w-full py-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium flex items-center justify-center gap-2 transition-colors mb-5"
      >
        <Calculator className="w-4 h-4" />
        计算本月操作
      </button>

      {/* 计算结果 */}
      {calculated && (
      <>
      <section className="bg-zinc-900/50 rounded-lg border border-zinc-800 p-5 mb-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-zinc-200">本月分配方案</h2>
          {result.allHigh && (
            <span className="text-[11px] text-amber-400 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> 全部 ETF &gt; 90%，机动资金转入子弹池
            </span>
          )}
        </div>

        <div className="overflow-hidden border border-zinc-800 rounded-md">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-zinc-950 text-[11px] text-zinc-500 uppercase tracking-wider">
                <th className="text-left px-3 py-2 font-medium">ETF</th>
                <th className="text-right px-3 py-2 font-medium">PE 分位</th>
                <th className="text-right px-3 py-2 font-medium">权重</th>
                <th className="text-right px-3 py-2 font-medium">必投</th>
                <th className="text-right px-3 py-2 font-medium">机动</th>
                <th className="text-right px-3 py-2 font-medium">加仓</th>
                <th className="text-right px-3 py-2 font-medium text-zinc-300">本月合计</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {ETF_ORDER.map((k) => {
                const meta = ETF_META[k];
                const totalWithBullet = result.total[k] + result.bulletRelease[k];
                const pct = amount > 0 ? (totalWithBullet / (amount + ETF_ORDER.reduce((s, key) => s + result.bulletRelease[key], 0))) * 100 : 0;
                return (
                  <tr key={k} className="hover:bg-zinc-950/40">
                    <td className="px-3 py-2.5">
                      <div className="text-zinc-200">{meta.label}</div>
                      <div className="text-[10px] text-zinc-600">目标 {(meta.ratio * 100).toFixed(0)}%</div>
                    </td>
                    <td className="px-3 py-2.5 text-right text-zinc-400 tabular-nums">{percentiles[k]}%</td>
                    <td className="px-3 py-2.5 text-right text-zinc-400 tabular-nums">{result.weights[k].toFixed(3)}x</td>
                    <td className="px-3 py-2.5 text-right text-zinc-500 tabular-nums">{fmtMoney(result.mustAlloc[k])}</td>
                    <td className="px-3 py-2.5 text-right text-zinc-500 tabular-nums">
                      {fmtMoney(result.flexAlloc[k])}
                      {result.allHigh && (
                        <span className="text-[10px] text-amber-500 ml-1">(子弹 {fmtMoney(result.bulletPool[k])})</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {result.bulletRelease[k] > 0 ? (
                        <span className="text-emerald-400">{fmtMoney(result.bulletRelease[k])}</span>
                      ) : (
                        <span className="text-zinc-600">-</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right font-medium text-zinc-100 tabular-nums">
                      {fmtMoney(totalWithBullet)}
                      <span className="text-[10px] text-zinc-500 ml-1">({pct.toFixed(1)}%)</span>
                    </td>
                  </tr>
                );
              })}
              <tr className="bg-zinc-950/60 text-zinc-300 font-medium">
                <td className="px-3 py-2.5">合计</td>
                <td className="px-3 py-2.5"></td>
                <td className="px-3 py-2.5"></td>
                <td className="px-3 py-2.5 text-right tabular-nums">{fmtMoney(result.must)}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {result.allHigh ? "0" : fmtMoney(ETF_ORDER.reduce((s, k) => s + result.flexAlloc[k], 0))}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-emerald-400">
                  {ETF_ORDER.reduce((s, k) => s + result.bulletRelease[k], 0) > 0
                    ? fmtMoney(ETF_ORDER.reduce((s, k) => s + result.bulletRelease[k], 0))
                    : "-"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {fmtMoney(
                    result.must +
                    ETF_ORDER.reduce((s, k) => s + result.flexAlloc[k], 0) +
                    ETF_ORDER.reduce((s, k) => s + result.bulletRelease[k], 0)
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      </>
      )}
    </div>
  );
}
