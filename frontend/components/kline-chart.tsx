"use client";

import { useEffect, useRef } from "react";
import { createChart, createSeriesMarkers, CandlestickSeries, HistogramSeries, LineSeries, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import type { KlineBar, TradeRecord } from "@/lib/types";
import { detectNWave } from "@/lib/n-wave";
import { calcChipDistribution } from "@/lib/chip-distribution";

function formatVolume(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(0);
}

export function KlineChart({ bars, trades = [], nWaveEnabled = false, visibleFrom, locked = false }: { bars: KlineBar[]; trades?: TradeRecord[]; nWaveEnabled?: boolean; visibleFrom?: string; locked?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chipCanvasRef = useRef<HTMLCanvasElement>(null);
  const dataRef = useRef<HTMLDivElement>(null);
  const mainLabelRef = useRef<HTMLDivElement>(null);
  const volLabelRef = useRef<HTMLDivElement>(null);
  const kdjLabelRef = useRef<HTMLDivElement>(null);
  const macdLabelRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "#a1a1aa",
        attributionLogo: false,
        panes: {
          separatorColor: "transparent",
          separatorHoverColor: "transparent",
        },
      },
      grid: {
        vertLines: { color: "#27272a" },
        horzLines: { color: "#27272a" },
      },
      width: containerRef.current.clientWidth,
      height: 720,
      timeScale: {
        borderColor: "#3f3f46",
        timeVisible: false,
      },
      handleScroll: !locked,
      handleScale: !locked,
      rightPriceScale: { visible: false },
      leftPriceScale: { visible: true, borderColor: "#3f3f46" },
      localization: {
        dateFormat: "yyyy-MM-dd",
      },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#ef4444",
      downColor: "#22c55e",
      borderVisible: false,
      wickUpColor: "#ef4444",
      wickDownColor: "#22c55e",
      priceScaleId: "left",
      lastValueVisible: false,
      priceLineVisible: false,
    });

    // 主线指标：趋势白 EMA(EMA(C,10),10) + 大哥黄 (MA14+MA28+MA57+MA114)/4
    const ema = (data: number[], period: number) => {
      const k = 2 / (period + 1);
      const result: number[] = [data[0]];
      for (let i = 1; i < data.length; i++) {
        result.push(data[i] * k + result[i - 1] * (1 - k));
      }
      return result;
    };
    const ma = (data: number[], period: number, idx: number) => {
      if (idx < period - 1) return NaN;
      let sum = 0;
      for (let j = idx - period + 1; j <= idx; j++) sum += data[j];
      return sum / period;
    };

    const closes = bars.map((b) => b.close);
    const ema10 = ema(closes, 10);
    const trendWhite = ema(ema10, 10);
    const bigBroYellow: number[] = closes.map((_, i) => {
      const m14 = ma(closes, 14, i);
      const m28 = ma(closes, 28, i);
      const m57 = ma(closes, 57, i);
      const m114 = ma(closes, 114, i);
      if (isNaN(m14) || isNaN(m28) || isNaN(m57) || isNaN(m114)) return NaN;
      return (m14 + m28 + m57 + m114) / 4;
    });

    const trendWhiteSeries = chart.addSeries(LineSeries, {
      color: "#ffffff",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    trendWhiteSeries.setData(
      bars.map((b, i) => ({ time: b.date as Time, value: trendWhite[i] }))
    );

    const bigBroSeries = chart.addSeries(LineSeries, {
      color: "#00c0c0",
      lineWidth: 2,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    bigBroSeries.setData(
      bars.reduce<{ time: Time; value: number }[]>((acc, b, i) => {
        if (!isNaN(bigBroYellow[i])) acc.push({ time: b.date as Time, value: bigBroYellow[i] });
        return acc;
      }, [])
    );

    // 创建成交量 pane
    const volPane = chart.addPane();
    const volumeSeries = volPane.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "left",
      lastValueVisible: false,
      priceLineVisible: false,
      color: "transparent",
    });

    // 成交量MA计算
    const volMa = (period: number) => {
      const result: { time: Time; value: number }[] = [];
      for (let i = 0; i < bars.length; i++) {
        if (i < period - 1) continue;
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += bars[j].volume;
        result.push({ time: bars[i].date as Time, value: sum / period });
      }
      return result;
    };

    const volMa5Series = volPane.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const volMa10Series = volPane.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    volMa5Series.setData(volMa(5));
    volMa10Series.setData(volMa(10));

    // KDJ 计算
    const calcKDJ = (n = 9, m1 = 3, m2 = 3) => {
      const kArr: number[] = [];
      const dArr: number[] = [];
      const jArr: number[] = [];
      let prevK = 50, prevD = 50;

      for (let i = 0; i < bars.length; i++) {
        const start = Math.max(0, i - n + 1);
        let highN = -Infinity, lowN = Infinity;
        for (let j = start; j <= i; j++) {
          if (bars[j].high > highN) highN = bars[j].high;
          if (bars[j].low < lowN) lowN = bars[j].low;
        }
        const rsv = highN === lowN ? 50 : ((bars[i].close - lowN) / (highN - lowN)) * 100;
        const k = (prevK * (m1 - 1) + rsv) / m1;
        const d = (prevD * (m2 - 1) + k) / m2;
        const j = 3 * k - 2 * d;
        kArr.push(k);
        dArr.push(d);
        jArr.push(j);
        prevK = k;
        prevD = d;
      }
      return { kArr, dArr, jArr };
    };

    const { kArr, dArr, jArr } = calcKDJ();

    // 创建 KDJ pane
    const kdjPane = chart.addPane();
    const kdjKSeries = kdjPane.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const kdjDSeries = kdjPane.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const kdjJSeries = kdjPane.addSeries(LineSeries, {
      color: "#ec4899",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    kdjKSeries.setData(bars.map((b, i) => ({ time: b.date as Time, value: kArr[i] })));
    kdjDSeries.setData(bars.map((b, i) => ({ time: b.date as Time, value: dArr[i] })));
    kdjJSeries.setData(bars.map((b, i) => ({ time: b.date as Time, value: jArr[i] })));

    // MACD 计算 (12, 26, 9)
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const dif: number[] = closes.map((_, i) => ema12[i] - ema26[i]);
    const dea = ema(dif, 9);
    const macdHist: number[] = dif.map((d, i) => (d - dea[i]) * 2);

    // 创建 MACD pane
    const macdPane = chart.addPane();
    const macdDifSeries = macdPane.addSeries(LineSeries, {
      color: "#f59e0b",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const macdDeaSeries = macdPane.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 1,
      priceScaleId: "left",
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const macdHistSeries = macdPane.addSeries(HistogramSeries, {
      priceScaleId: "left",
      lastValueVisible: false,
      priceLineVisible: false,
      color: "transparent",
    });

    macdDifSeries.setData(bars.map((b, i) => ({ time: b.date as Time, value: dif[i] })));
    macdDeaSeries.setData(bars.map((b, i) => ({ time: b.date as Time, value: dea[i] })));
    macdHistSeries.setData(bars.map((b, i) => ({
      time: b.date as Time,
      value: macdHist[i],
      color: macdHist[i] >= 0 ? "rgba(239,68,68,0.8)" : "rgba(34,197,94,0.8)",
    })));

    // 设置各面板比例：K线 50%, 成交量 15%, KDJ 15%, MACD 20%
    const panes = chart.panes();
    if (panes[0]) panes[0].setStretchFactor(10);
    volPane.setStretchFactor(3);
    kdjPane.setStretchFactor(3);
    macdPane.setStretchFactor(4);

    // KDJ 面板顶部留出空间，避免线条和标签重叠
    kdjKSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.25, bottom: 0.05 },
    });

    candleSeries.setData(
      bars.map((b) => ({
        time: b.date as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
    );

    volumeSeries.setData(
      bars.map((b) => ({
        time: b.date as Time,
        value: b.volume,
        color: b.close >= b.open ? "rgba(239,68,68,0.8)" : "rgba(34,197,94,0.8)",
      }))
    );

    if (trades.length) {
      createSeriesMarkers(
        candleSeries,
        trades.map((t) => ({
          time: t.date as Time,
          position: t.direction === "buy" ? "belowBar" : "aboveBar",
          color: t.direction === "buy" ? "#ef4444" : "#22c55e",
          shape: t.direction === "buy" ? "arrowUp" : "arrowDown",
          text: t.direction === "buy" ? "B" : "S",
        }))
      );
    }

    if (nWaveEnabled) {
      const points = detectNWave(bars);
      const uniquePoints = points.filter((p, i, arr) => i === 0 || p.date !== arr[i - 1].date);
      if (uniquePoints.length >= 2) {
        const nWaveSeries = chart.addSeries(LineSeries, {
          color: "#f97316",
          lineWidth: 2,
          lineStyle: 2,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        nWaveSeries.setData(
          uniquePoints.map((p) => ({ time: p.date as Time, value: p.price }))
        );

        createSeriesMarkers(
          nWaveSeries,
          uniquePoints.map((p) => ({
            time: p.date as Time,
            position: p.type === "H" ? "aboveBar" : "belowBar",
            color: "#f97316",
            shape: p.type === "H" ? "circle" : "circle",
            text: p.type,
          }))
        );
      }
    }

    if (visibleFrom) {
      const fromIdx = bars.findIndex((b) => b.date >= visibleFrom);
      if (fromIdx > 0) {
        chart.timeScale().setVisibleLogicalRange({ from: fromIdx, to: bars.length - 1 });
      } else {
        chart.timeScale().fitContent();
      }
    } else {
      chart.timeScale().fitContent();
    }

    const barMap = new Map(bars.map((b) => [b.date, b]));
    const barIndexMap = new Map(bars.map((b, i) => [b.date, i]));

    let pricePriceLine: ReturnType<typeof candleSeries.createPriceLine> | null = null;
    let volumePriceLine: ReturnType<typeof volumeSeries.createPriceLine> | null = null;
    const clearPriceLines = () => {
      if (pricePriceLine) { candleSeries.removePriceLine(pricePriceLine); pricePriceLine = null; }
      if (volumePriceLine) { volumeSeries.removePriceLine(volumePriceLine); volumePriceLine = null; }
    };

    const drawChipDistribution = (bar: KlineBar, barIdx: number) => {
      const canvas = chipCanvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);

      const barsSlice = bars.slice(0, barIdx + 1);
      const { bins, profitRatio, avgCost } = calcChipDistribution(barsSlice, bar.close);

      if (!bins.length) return;

      const maxVol = Math.max(...bins.map((b) => b.volume));
      if (maxVol <= 0) return;

      const minBinPrice = bins[0].price;
      const maxBinPrice = bins[bins.length - 1].price;
      const priceRange = maxBinPrice - minBinPrice;
      const maxBarWidth = w - 4;

      for (let i = 0; i < bins.length; i++) {
        const bin = bins[i];
        const barWidth = (bin.volume / maxVol) * maxBarWidth;
        const pricePct = priceRange > 0 ? (bin.price - minBinPrice) / priceRange : 0.5;
        const y = h - pricePct * h - (h / bins.length / 2);
        const binH = h / bins.length;
        const isProfit = bin.price <= bar.close;
        ctx.fillStyle = isProfit ? "rgba(239, 68, 68, 0.6)" : "rgba(96, 165, 250, 0.6)";
        ctx.fillRect(w - barWidth - 2, y, barWidth, Math.max(binH - 0.5, 1));
      }

      // 更新数据面板
      const dataPanel = dataRef.current;
      if (dataPanel) {
        const change = bar.close - bar.open;
        const changePercent = (change / bar.open) * 100;
        const color = change >= 0 ? "#ef4444" : "#22c55e";
        dataPanel.innerHTML = `
          <div class="text-zinc-400 text-[11px] mb-1.5 pb-1 border-b border-zinc-800">${bar.date}</div>
          <div class="flex justify-between"><span class="text-zinc-500">开</span><span style="color:${color}">${bar.open.toFixed(2)}</span></div>
          <div class="flex justify-between"><span class="text-zinc-500">高</span><span style="color:${color}">${bar.high.toFixed(2)}</span></div>
          <div class="flex justify-between"><span class="text-zinc-500">低</span><span style="color:${color}">${bar.low.toFixed(2)}</span></div>
          <div class="flex justify-between"><span class="text-zinc-500">收</span><span style="color:${color}">${bar.close.toFixed(2)}</span></div>
          <div class="flex justify-between"><span class="text-zinc-500">涨幅</span><span style="color:${color}">${changePercent >= 0 ? "+" : ""}${changePercent.toFixed(2)}%</span></div>
          <div class="flex justify-between"><span class="text-zinc-500">成交量</span><span class="text-zinc-200">${formatVolume(bar.volume)}</span></div>
          <div class="mt-1.5 pt-1.5 border-t border-zinc-800"></div>
          <div class="flex justify-between"><span class="text-zinc-500">获利盘</span><span class="text-red-400">${(profitRatio * 100).toFixed(1)}%</span></div>
          <div class="flex justify-between"><span class="text-zinc-500">平均成本</span><span class="text-blue-400">${avgCost.toFixed(2)}</span></div>
        `;
      }
    };

    const updateIndicatorLabels = (barIdx: number) => {
      const mainLabel = mainLabelRef.current;
      if (mainLabel) {
        const tw = trendWhite[barIdx];
        const bb = bigBroYellow[barIdx];
        mainLabel.innerHTML = `
          <span class="text-white">趋势白: ${tw.toFixed(2)}</span>
          <span style="color:#00c0c0">大哥黄: ${isNaN(bb) ? "--" : bb.toFixed(2)}</span>
        `;
      }
      const volLabel = volLabelRef.current;
      const kdjLabel = kdjLabelRef.current;
      if (volLabel) {
        const vol = bars[barIdx].volume;
        const ma5 = barIdx >= 4 ? bars.slice(barIdx - 4, barIdx + 1).reduce((s, b) => s + b.volume, 0) / 5 : NaN;
        const ma10 = barIdx >= 9 ? bars.slice(barIdx - 9, barIdx + 1).reduce((s, b) => s + b.volume, 0) / 10 : NaN;
        volLabel.innerHTML = `
          <span class="text-zinc-300">成交量 <span class="text-zinc-100">${formatVolume(vol)}</span></span>
          <span class="text-amber-500">MA5: ${isNaN(ma5) ? "--" : formatVolume(ma5)}</span>
          <span class="text-blue-500">MA10: ${isNaN(ma10) ? "--" : formatVolume(ma10)}</span>
        `;
      }
      if (kdjLabel) {
        kdjLabel.innerHTML = `
          <span class="text-zinc-300">KDJ</span>
          <span class="text-amber-500">K: ${kArr[barIdx].toFixed(2)}</span>
          <span class="text-blue-500">D: ${dArr[barIdx].toFixed(2)}</span>
          <span class="text-pink-500">J: ${jArr[barIdx].toFixed(2)}</span>
        `;
      }
      const macdLabel = macdLabelRef.current;
      if (macdLabel) {
        macdLabel.innerHTML = `
          <span class="text-zinc-300">MACD</span>
          <span class="text-amber-500">DIF: ${dif[barIdx].toFixed(2)}</span>
          <span class="text-blue-500">DEA: ${dea[barIdx].toFixed(2)}</span>
          <span class="text-zinc-100">MACD: ${macdHist[barIdx].toFixed(2)}</span>
        `;
      }
    };

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
        clearPriceLines();
        return;
      }
      const bar = barMap.get(param.time as string);
      if (!bar) {
        clearPriceLines();
        return;
      }
      const change = bar.close - bar.open;
      const color = change >= 0 ? "#ef4444" : "#22c55e";

      clearPriceLines();
      pricePriceLine = candleSeries.createPriceLine({
        price: bar.close,
        color: "#a1a1aa",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        axisLabelColor: color,
        axisLabelTextColor: "#ffffff",
        title: "",
      });
      volumePriceLine = volumeSeries.createPriceLine({
        price: bar.volume,
        color: "#a1a1aa",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        axisLabelColor: "#3f3f46",
        axisLabelTextColor: "#ffffff",
        title: "",
      });

      const barIdx = barIndexMap.get(param.time as string) ?? bars.length - 1;
      drawChipDistribution(bar, barIdx);
      updateIndicatorLabels(barIdx);
    });

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    candleSeriesRef.current = candleSeries;

    // 初始绘制最后一根 K 线的筹码分布和指标数值
    if (bars.length > 0) {
      const lastBar = bars[bars.length - 1];
      drawChipDistribution(lastBar, bars.length - 1);
      updateIndicatorLabels(bars.length - 1);
    }

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [bars, trades, nWaveEnabled, visibleFrom, locked]);

  return (
    <div className="flex w-full">
      <div className="flex-1 min-w-0 relative isolate">
        <div ref={containerRef} className="w-full" />
        <div
          ref={mainLabelRef}
          className="absolute left-16 top-1 text-[11px] flex gap-3 pointer-events-none z-10 px-1 bg-zinc-950/70 rounded"
        />
        <div
          ref={volLabelRef}
          className="absolute left-16 text-[11px] flex gap-3 pointer-events-none z-10 px-1 bg-zinc-950/70 rounded"
          style={{ top: "362px" }}
        />
        <div
          ref={kdjLabelRef}
          className="absolute left-16 text-[11px] flex gap-3 pointer-events-none z-10 px-1 bg-zinc-950/70 rounded"
          style={{ top: "472px" }}
        />
        <div
          ref={macdLabelRef}
          className="absolute left-16 text-[11px] flex gap-3 pointer-events-none z-10 px-1 bg-zinc-950/70 rounded"
          style={{ top: "582px" }}
        />
      </div>
      <div className="w-[180px] flex flex-col ml-1" style={{ height: "720px" }}>
        <canvas
          ref={chipCanvasRef}
          className="w-full flex-none"
          style={{ height: "360px" }}
        />
        <div
          ref={dataRef}
          className="text-xs p-2 space-y-0.5"
        />
      </div>
    </div>
  );
}
