"use client";

import { useState, useRef, useEffect } from "react";
import { Calendar } from "lucide-react";

interface DateRangePickerProps {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}

function pad(n: number) { return n < 10 ? `0${n}` : `${n}`; }
function toStr(y: number, m: number, d: number) { return `${y}-${pad(m + 1)}-${pad(d)}`; }
function getDaysInMonth(year: number, month: number) { return new Date(year, month + 1, 0).getDate(); }
function getFirstDayOfWeek(year: number, month: number) { return new Date(year, month, 1).getDay(); }

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

function CalendarPanel({ year, month, selectedStart, selectedEnd, onSelect, onPrev, onNext }: {
  year: number; month: number;
  selectedStart: string; selectedEnd: string;
  onSelect: (date: string) => void;
  onPrev: () => void; onNext: () => void;
}) {
  const days = getDaysInMonth(year, month);
  const firstDay = getFirstDayOfWeek(year, month);
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= days; d++) cells.push(d);

  return (
    <div className="w-[240px]">
      <div className="flex items-center justify-between mb-2">
        <button onClick={onPrev} className="text-zinc-400 hover:text-zinc-200 px-2">&lsaquo;</button>
        <span className="text-xs text-zinc-200 font-medium">{year}年{month + 1}月</span>
        <button onClick={onNext} className="text-zinc-400 hover:text-zinc-200 px-2">&rsaquo;</button>
      </div>
      <div className="grid grid-cols-7 text-center mb-1">
        {WEEKDAYS.map((w) => (
          <span key={w} className="text-[10px] text-zinc-500 py-0.5">{w}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 text-center">
        {cells.map((d, i) => {
          if (d === null) return <span key={`e${i}`} />;
          const dateStr = toStr(year, month, d);
          const isStart = dateStr === selectedStart;
          const isEnd = dateStr === selectedEnd;
          const inRange = selectedStart && selectedEnd && dateStr > selectedStart && dateStr < selectedEnd;
          return (
            <button
              key={d}
              onClick={() => onSelect(dateStr)}
              className={`py-1 text-xs rounded transition-colors ${
                isStart || isEnd
                  ? "bg-blue-600 text-white"
                  : inRange
                    ? "bg-blue-600/20 text-zinc-200"
                    : "text-zinc-300 hover:bg-zinc-700"
              }`}
            >
              {d}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DateRangePicker({ start, end, onChange }: DateRangePickerProps) {
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState<"start" | "end">("start");
  const [tempStart, setTempStart] = useState(start);
  const [tempEnd, setTempEnd] = useState(end);
  const ref = useRef<HTMLDivElement>(null);

  const startDate = new Date(start || new Date());
  const endDate = new Date(end || new Date());
  const [leftYear, setLeftYear] = useState(startDate.getFullYear());
  const [leftMonth, setLeftMonth] = useState(startDate.getMonth());
  const [rightYear, setRightYear] = useState(endDate.getFullYear());
  const [rightMonth, setRightMonth] = useState(endDate.getMonth());

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleSelect(dateStr: string) {
    if (picking === "start") {
      setTempStart(dateStr);
      if (tempEnd && dateStr >= tempEnd) {
        setTempEnd("");
      }
      setPicking("end");
    } else {
      if (dateStr <= tempStart) {
        setTempStart(dateStr);
        setPicking("end");
      } else {
        setTempEnd(dateStr);
        onChange(tempStart, dateStr);
        setOpen(false);
        setPicking("start");
      }
    }
  }

  function leftPrev() {
    if (leftMonth === 0) { setLeftYear(leftYear - 1); setLeftMonth(11); }
    else setLeftMonth(leftMonth - 1);
  }
  function leftNext() {
    const ny = leftMonth === 11 ? leftYear + 1 : leftYear;
    const nm = leftMonth === 11 ? 0 : leftMonth + 1;
    if (ny > rightYear || (ny === rightYear && nm >= rightMonth)) return;
    setLeftYear(ny); setLeftMonth(nm);
  }
  function rightPrev() {
    const ny = rightMonth === 0 ? rightYear - 1 : rightYear;
    const nm = rightMonth === 0 ? 11 : rightMonth - 1;
    if (ny < leftYear || (ny === leftYear && nm <= leftMonth)) return;
    setRightYear(ny); setRightMonth(nm);
  }
  function rightNext() {
    if (rightMonth === 11) { setRightYear(rightYear + 1); setRightMonth(0); }
    else setRightMonth(rightMonth + 1);
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 text-xs bg-zinc-900 border border-zinc-700 rounded text-zinc-300 hover:border-zinc-500"
      >
        <Calendar className="w-3 h-3" />
        <span>{start} ~ {end}</span>
      </button>
      {open && (
        <div className="absolute top-full mt-1 left-0 z-50 flex gap-4 bg-zinc-900 border border-zinc-700 rounded-lg p-4 shadow-xl">
          <CalendarPanel
            year={leftYear} month={leftMonth}
            selectedStart={tempStart} selectedEnd={tempEnd}
            onSelect={handleSelect}
            onPrev={leftPrev} onNext={leftNext}
          />
          <CalendarPanel
            year={rightYear} month={rightMonth}
            selectedStart={tempStart} selectedEnd={tempEnd}
            onSelect={handleSelect}
            onPrev={rightPrev} onNext={rightNext}
          />
        </div>
      )}
    </div>
  );
}
