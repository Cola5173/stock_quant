"use client";

import { useEffect, useRef } from "react";
import { createChart, createSeriesMarkers, CandlestickSeries, HistogramSeries, LineSeries, type IChartApi, type Time } from "lightweight-charts";
import type { KlineBar, TradeRecord } from "@/lib/types";
import { detectNWave } from "@/lib/n-wave";

export function KlineChart({ bars, trades = [], nWaveEnabled = false }: { bars: KlineBar[]; trades?: TradeRecord[]; nWaveEnabled?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
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
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
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

  return <div ref={containerRef} className="w-full" />;
}
