"use client";

import { useEffect, useRef } from "react";
import { createChart, createSeriesMarkers, CandlestickSeries, HistogramSeries, LineSeries, type IChartApi, type Time } from "lightweight-charts";
import type { KlineBar, TradeRecord } from "@/lib/types";
import { detectNWave } from "@/lib/n-wave";

function formatVolume(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(0);
}

export function KlineChart({ bars, trades = [], nWaveEnabled = false }: { bars: KlineBar[]; trades?: TradeRecord[]; nWaveEnabled?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "#a1a1aa",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#27272a" },
        horzLines: { color: "#27272a" },
      },
      width: containerRef.current.clientWidth,
      height: 400,
      timeScale: { borderColor: "#3f3f46", timeVisible: false },
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

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
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
        color: b.close >= b.open ? "rgba(239,68,68,0.5)" : "rgba(34,197,94,0.5)",
      }))
    );

    if (trades.length) {
      createSeriesMarkers(
        candleSeries,
        trades.map((t) => ({
          time: t.date as Time,
          position: t.direction === "buy" ? "belowBar" : "aboveBar",
          color: t.direction === "buy" ? "#22c55e" : "#ef4444",
          shape: t.direction === "buy" ? "arrowUp" : "arrowDown",
          text: t.direction === "buy" ? "买" : "卖",
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

    chart.timeScale().fitContent();

    const barMap = new Map(bars.map((b) => [b.date, b]));

    let pricePriceLine: ReturnType<typeof candleSeries.createPriceLine> | null = null;
    let volumePriceLine: ReturnType<typeof volumeSeries.createPriceLine> | null = null;
    const clearPriceLines = () => {
      if (pricePriceLine) { candleSeries.removePriceLine(pricePriceLine); pricePriceLine = null; }
      if (volumePriceLine) { volumeSeries.removePriceLine(volumePriceLine); volumePriceLine = null; }
    };

    chart.subscribeCrosshairMove((param) => {
      const tooltip = tooltipRef.current;
      if (!tooltip) return;
      if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0) {
        tooltip.style.display = "none";
        clearPriceLines();
        return;
      }
      const bar = barMap.get(param.time as string);
      if (!bar) {
        tooltip.style.display = "none";
        clearPriceLines();
        return;
      }
      const change = bar.close - bar.open;
      const changePercent = (change / bar.open) * 100;
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

      tooltip.style.display = "block";
      tooltip.innerHTML = `
        <div class="text-zinc-400 text-[11px] mb-1">${bar.date}</div>
        <div class="flex justify-between gap-3"><span class="text-zinc-500">开</span><span style="color:${color}">${bar.open.toFixed(2)}</span></div>
        <div class="flex justify-between gap-3"><span class="text-zinc-500">高</span><span style="color:${color}">${bar.high.toFixed(2)}</span></div>
        <div class="flex justify-between gap-3"><span class="text-zinc-500">低</span><span style="color:${color}">${bar.low.toFixed(2)}</span></div>
        <div class="flex justify-between gap-3"><span class="text-zinc-500">收</span><span style="color:${color}">${bar.close.toFixed(2)}</span></div>
        <div class="flex justify-between gap-3"><span class="text-zinc-500">涨跌</span><span style="color:${color}">${changePercent >= 0 ? "+" : ""}${changePercent.toFixed(2)}%</span></div>
        <div class="flex justify-between gap-3"><span class="text-zinc-500">成交量</span><span class="text-zinc-200">${formatVolume(bar.volume)}</span></div>
      `;
      const containerWidth = containerRef.current?.clientWidth ?? 0;
      const tooltipWidth = 140;
      const x = param.point.x + 60 + tooltipWidth > containerWidth
        ? param.point.x - tooltipWidth - 10
        : param.point.x + 60;
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `8px`;
    });

    const ro = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, trades, nWaveEnabled]);

  return (
    <div className="relative w-full">
      <div ref={containerRef} className="w-full" />
      <div
        ref={tooltipRef}
        className="absolute z-10 pointer-events-none bg-zinc-900/95 border border-zinc-700 rounded-md p-2 text-xs shadow-lg"
        style={{ display: "none", minWidth: "140px" }}
      />
    </div>
  );
}
